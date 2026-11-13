"""정답 근거 청크 중 표·수치가 든 청크를 원문 스냅샷과 현재 공개 원문에 대조한다 (체크포인트 3조 코멘트 ②, 2026-11-13).

대상: v2 50건의 관련 25문항과 검증 20건의 관련 10문항의 정답 위치(`gold_chunks`)에 맞는 청크 전부
(맞추는 규칙은 `evals/retrieval/gold.py`와 같다). 그중 아래 둘 중 하나인 청크를 고른다.
  - 수치 값이 든다: 금액($100, $25K), 비율(15%), 기간(15 minutes, 90 days), 등급·단계(Tier 1, Level 2, P1), 개수(20 people).
  - 표다: 원본 줄에 HTML 표(`<table`, `<tr`)나 마크다운 표(`|---`)가 있거나 승인 권한표 행(kind=row)이다.

대조 방법 (LLM·키 없음, 공개 원문은 GET만):
  1. 스냅샷: `data/corpus.tar.gz` 안의 원문 파일에서 청크의 `line_start`~`line_end` 줄만 꺼낸다. 청크 본문의 수치 값을 같은 규칙으로
     원문 줄에서 뽑은 값과 맞춘다. 제목 줄(청크 첫 줄)과 앞 청크에서 겹쳐 들어온 앞부분(`overlap_chars`)은 줄 범위 밖이므로
     같은 쪽 전체에서 찾는다. 값마다 앞뒤 낱말 3개(표 칸은 칸 안에서)가 원문과 같은지도 본다.
  2. 현재 원문: 청크의 `source_url`을 GET해 보이는 글자만 뽑아 같은 방식으로 맞춘다(쪽 전체에서 찾는다).
     승인 권한표 행은 GitLab의 고정 커밋 주소라 raw 본문의 같은 줄 범위를 줄 단위로 맞춘다.

사용: python evals/results/table_number_source_check_20261113/check.py --fetch [--cache <폴더>]
`--fetch`가 없으면 현재 원문 대조를 건너뛰고 스냅샷 대조만 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import tarfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from evals.retrieval.gold import GoldAny, parse_gold  # noqa: E402

DATASETS = [("v2", ROOT / "evals" / "dataset_v2.jsonl"), ("검증", ROOT / "evals" / "dataset_holdout_v1.jsonl")]
KST = timezone(timedelta(hours=9))
UA = "provena-source-check/1.0 (read-only GET)"

# ------------------------------------------------------------------ 수치 값 뽑기
UNITS = {"second": "second", "sec": "second", "minute": "minute", "min": "minute", "hour": "hour", "hr": "hour", "day": "day", "week": "week",
         "month": "month", "year": "year", "yr": "year"}
_NUM = r"\d[\d,]*(?:\.\d+)?"
RE_MONEY = re.compile(rf"\$\s?({_NUM})\s?(k|m|b|million|billion|thousand)?\b", re.I)
RE_PCT = re.compile(rf"({_NUM})\s?%")
RE_DUR = re.compile(rf"({_NUM})[\s-]*(?:business\s+|calendar\s+|working\s+)?(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|yrs?)\b", re.I)
RE_GRADE = re.compile(r"\b(tier|level|grade|priority|severity|band|stage|phase|category|class|type)\s?(\d+)\b|\b([ps][0-4])\b", re.I)
RE_QTY = re.compile(rf"({_NUM})\s+(people|persons?|employees?|members?|team members|users?|attempts?|times|characters|items?|reports?|approvers?)\b", re.I)
SUFFIX = {"k": "k", "thousand": "k", "m": "m", "million": "m", "b": "b", "billion": "b"}


def _num(s: str) -> str:
    s = s.replace(",", "")
    return s[:-2] if s.endswith(".0") else s


def values(text: str) -> list[str]:
    """글에서 수치 값을 정규 표기로 뽑는다(중복 제거, 순서 유지)."""
    t = html.unescape(text).replace("\xa0", " ")
    out: list[str] = []
    for m in RE_MONEY.finditer(t):
        out.append(f"${_num(m.group(1))}{SUFFIX.get((m.group(2) or '').lower(), '')}")
    for m in RE_PCT.finditer(t):
        out.append(f"{_num(m.group(1))}%")
    for m in RE_DUR.finditer(t):
        unit = re.sub(r"s$", "", m.group(2).lower())
        out.append(f"{_num(m.group(1))} {UNITS.get(unit, unit)}")
    for m in RE_GRADE.finditer(t):
        out.append(f"{m.group(1).lower()} {m.group(2)}" if m.group(1) else m.group(3).lower())
    for m in RE_QTY.finditer(t):
        out.append(f"{_num(m.group(1))} {re.sub(r's$', '', m.group(2).lower())}")
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------ 글 정리
def words(text: str) -> list[str]:
    """비교용 낱말 목록: 소문자, 쉼표 낀 숫자를 붙이고, 글자·숫자·$·%만 남긴다."""
    t = html.unescape(text).replace("\xa0", " ").lower()
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = re.sub(r"\$\s+(?=\d)", "$", t)
    return re.findall(r"[a-z0-9$%.]+(?:[-'][a-z0-9]+)*", t.replace("’", "'"))


def md_to_text(src: str) -> str:
    """원문(마크다운·HTML·주석)을 글자만 남긴다. 주석 안 글자는 승인 권한표의 역할 이름이라 남긴다."""
    t = re.sub(r"<!--(.*?)-->", r" \1 ", src, flags=re.S)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[*`_>#|]+", " ", t)
    return re.sub(r"\s+", " ", t)


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _Visible()
    p.feed(raw)
    return re.sub(r"\s+", " ", "".join(p.parts))


# ------------------------------------------------------------------ 문맥 대조
def contexts(body: str) -> list[tuple[str, str]]:
    """청크 본문의 (수치 값, 앞뒤 낱말 3개를 붙인 문맥). 줄과 ` | ` 칸을 넘지 않는다."""
    out = []
    for seg in re.split(r"\n| \| ", body):
        seg = re.sub(r"^[^:$%\d]{1,40}:\s", "", seg)  # 표 행의 "열 이름: " 머리는 원문에 없다(수치가 든 앞부분은 지우지 않는다)
        ws = words(seg)
        for v in values(seg):
            vw = words(v)
            for i in range(len(ws)):
                if ws[i : i + len(vw)] == vw or (len(vw) == 1 and ws[i] == vw[0]):
                    out.append((v, " ".join(ws[max(0, i - 3) : i + len(vw) + 3])))
                    break
            else:
                # 낱말로 안 잡히면(예: 15-minute) 값만 본다
                out.append((v, ""))
    return list(dict.fromkeys(out))


def present(ctx: str, src_words: list[str]) -> bool:
    if not ctx:
        return True
    cw = ctx.split()
    n = len(cw)
    return any(src_words[i : i + n] == cw for i in range(len(src_words) - n + 1))


def compare(chunk_values: list[tuple[str, str]], src_text: str) -> dict:
    """값이 원문에 있는지(has), 있으나 문맥이 다른지(ctx_diff)."""
    sw = words(src_text)
    src_vals = set(values(src_text))
    missing = [v for v, _ in chunk_values if v not in src_vals]
    ctx_diff = [{"value": v, "chunk_context": c} for v, c in chunk_values if v in src_vals and not present(c, sw)]
    return {"missing": missing, "ctx_diff": ctx_diff}


# ------------------------------------------------------------------ 입력
def _bare(text: str) -> list[str]:
    """표 청크용: 단위가 없는 숫자도 값으로 본다(`#5`)."""
    t = re.sub(r"(?<=\d),(?=\d{3})", "", html.unescape(text))
    return list(dict.fromkeys("#" + _num(m) for m in re.findall(r"(?<![\w.$#-])\d+(?:\.\d+)?(?![\w%])", t)))


def _ctx_with_bare(body: str, table: bool) -> list[tuple[str, str]]:
    out = contexts(body)
    if table:
        out += [(v, "") for v in _bare(body)]
    return list(dict.fromkeys(out))


def check_snapshot(c, lines: list[str], text: str, table: bool) -> dict:
    """청크 글(text)의 수치 값을 원문 줄 범위와 맞춘다. 제목 줄과 앞 청크에서 겹쳐 들어온 앞부분은 줄 범위 밖이라 쪽 전체에서 찾는다."""
    window = "\n".join(lines[c.line_start - 1 : c.line_end])
    header, _, body = text.partition("\n")
    ov = c.overlap_chars or 0
    main_body, overlap = body[ov:], body[:ov]
    vals_body = _ctx_with_bare(main_body, table)
    vals_other = [(v, "") for v in values(header) + (_bare(header) if table else [])] + _ctx_with_bare(overlap, table)
    page_text = md_to_text("\n".join(lines))
    win_text = md_to_text(window)
    body_cmp = compare_all(vals_body, win_text)
    other_cmp = compare_all(vals_other, page_text)
    page_vals = set(all_values(page_text, table))
    in_page_only = [v for v in body_cmp["missing"] if v in page_vals]
    missing = [v for v in body_cmp["missing"] if v not in in_page_only] + other_cmp["missing"]
    ctx = body_cmp["ctx_diff"] + other_cmp["ctx_diff"]
    allv = list(dict.fromkeys(v for v, _ in vals_other + vals_body))
    return {"values": allv, "missing": missing, "in_page_only": in_page_only, "ctx_diff": ctx, "match": not missing and not ctx and not in_page_only}


def all_values(text: str, table: bool) -> list[str]:
    return values(text) + (_bare(text) if table else [])


def compare_all(chunk_values: list[tuple[str, str]], src_text: str, table: bool = True) -> dict:
    sw = words(src_text)
    src_vals = set(values(src_text)) | set(_bare(src_text))
    missing = [v for v, _ in chunk_values if v not in src_vals]
    ctx_diff = [{"value": v, "chunk_context": c} for v, c in chunk_values if v in src_vals and not present(c, sw)]
    return {"missing": missing, "ctx_diff": ctx_diff}


def _mutations(text: str):
    """자기 점검용: 청크 글에서 수치 하나를 다른 값으로 바꾼 (원래, 바꾼) 쌍."""
    for rx in (RE_MONEY, RE_PCT, RE_DUR, RE_QTY):
        for m in rx.finditer(text):
            digits = m.group(1)
            if digits.isdigit() and len(digits) <= 4:
                yield m.group(0), m.group(0).replace(digits, str(int(digits) + 7), 1)


def load_chunks():
    return [SimpleNamespace(**json.loads(l)) for l in (ROOT / "data" / "index" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]


def gold_chunks(chunks):
    """(데이터셋, 문항 id) -> 정답 위치에 맞는 청크 id 목록."""
    result = []
    for name, path in DATASETS:
        for line in path.read_text(encoding="utf-8").splitlines():
            it = json.loads(line)
            if it["kind"] != "relevant":
                continue
            ids = []
            for g in parse_gold(it["gold_chunks"]):
                ids += [c.chunk_id for c in chunks if g.matches(c)]
            result.append({"dataset": name, "id": it["id"], "expected": it["expected"], "chunk_ids": list(dict.fromkeys(ids))})
    return result


def fetch(url: str, cache: Path | None) -> tuple[int, bytes]:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    if cache and (cache / key).exists():
        return 200, (cache / key).read_bytes()
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                body = r.read()
                status = r.status
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                return -1, str(e).encode()
            time.sleep(3)
    time.sleep(1.0)
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / key).write_bytes(body)
    return status, body


def write_report(out: Path, rows: list[dict], n_gold: int, snap_sha: str, fetched: bool) -> None:
    n = len(rows)
    snap_ok = sum(r["snapshot"]["match"] for r in rows)
    cur = [r for r in rows if r["current"].get("checked")]
    cur_ok = sum(1 for r in cur if r["current"].get("match"))
    when = rows[0]["checked_at"] if rows else ""
    lines = [
        "# 정답 근거 청크의 표·수치 원문 대조 (2026-11-13)",
        "",
        f"- 대상: v2 50건의 관련 25문항과 검증 20건의 관련 10문항의 정답 위치에 맞는 청크 {n_gold}개 중 수치 값이나 표가 든 {n}개(서로 다른 청크, 한 청크가 여러 문항의 정답이면 문항을 모두 적음).",
        f"- 스냅샷 `data/corpus.tar.gz`(sha256 `{snap_sha[:16]}…`)의 해당 페이지와 줄 범위(`line_start`~`line_end`)와 대조: {n}개 중 일치 {snap_ok}개, 불일치 {n - snap_ok}개.",
    ]
    if fetched:
        lines.append(f"- 공개 원문(`source_url`, GET만)의 {when} 본문과 대조: {len(cur)}개 확인, 일치 {cur_ok}개, 불일치 {len(cur) - cur_ok}개.")
    else:
        lines.append("- 현재 공개 원문 대조는 하지 않았다(`--fetch` 없음).")
    lines += ["", "일치의 뜻: 청크의 수치 값(금액, 비율, 기간, 등급, 개수, 표 청크의 단위 없는 숫자)이 모두 원문에 있고, 값 앞뒤 낱말 3개가 원문과 같다. 자세한 규칙은 `check.py` 머리말.", "",
              "| 청크 id | 문항 | 종류 | 수치 값 | 스냅샷 줄 | 스냅샷 일치 | 현재 원문 일치 | 확인 시각 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        vals = ", ".join(v for v in r["values"] if not v.startswith("#"))
        bare = [v[1:] for v in r["values"] if v.startswith("#")]
        if bare:
            vals += (", " if vals else "") + "숫자 " + ", ".join(bare[:6]) + ("…" if len(bare) > 6 else "")
        s = "일치" if r["snapshot"]["match"] else "불일치"
        c = r["current"]
        cs = "-" if not c.get("checked") else ("일치" if c.get("match") else ("불일치" if c.get("match") is False else "확인 못 함"))
        lines.append(f"| `{r['chunk_id']}` | {', '.join(r['questions'])} | {r['reason']} | {vals or '-'} | `{r['page'].split('/', 1)[1]}` {r['line_start']}~{r['line_end']} | {s} | {cs} | {r['checked_at']} |")
    bad = [r for r in rows if not r["snapshot"]["match"] or r["current"].get("match") is False]
    lines += ["", "## 불일치", ""]
    if not bad:
        lines.append("없음.")
    for r in bad:
        lines.append(f"- `{r['chunk_id']}` ({', '.join(r['questions'])}): 스냅샷 `{json.dumps(r['snapshot'], ensure_ascii=False)}`, 현재 `{json.dumps(r['current'], ensure_ascii=False)}`")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="현재 공개 원문을 GET해 대조한다")
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    chunks = load_chunks()
    by_id = {c.chunk_id: c for c in chunks}
    pages = {p["rule_seq"]: p for p in map(json.loads, (ROOT / "data" / "corpus" / "pages.jsonl").read_text(encoding="utf-8").splitlines())}
    tar = tarfile.open(ROOT / "data" / "corpus.tar.gz")
    snap_sha = hashlib.sha256((ROOT / "data" / "corpus.tar.gz").read_bytes()).hexdigest()
    cache_lines: dict[str, list[str]] = {}

    def page_lines(member: str) -> list[str]:
        if member not in cache_lines:
            cache_lines[member] = tar.extractfile(member).read().decode("utf-8").split("\n")
        return cache_lines[member]

    questions = gold_chunks(chunks)
    qs_by_chunk: dict[str, list[str]] = {}
    for q in questions:
        for cid in q["chunk_ids"]:
            qs_by_chunk.setdefault(cid, []).append(f"{q['dataset']} {q['id']}")

    rows = []
    selftest_pool = []
    for cid, qs in qs_by_chunk.items():
        c = by_id[cid]
        page = pages.get(c.rule_seq)
        member = "handbook/" + page["path"].replace("content/handbook/", "") if page else "authz/authorization-matrix-2023-05.html.md"
        lines = page_lines(member)
        window = "\n".join(lines[c.line_start - 1 : c.line_end])
        is_table = c.kind == "row" or bool(re.search(r"<table|<t[dhr]\b|^\s*\|.*\|\s*$|^\s*\|?\s*:?-{3,}", window, re.M | re.I))
        info = check_snapshot(c, lines, c.text, is_table)
        if not info["values"] and not is_table:
            continue
        reason = "표+수치" if is_table and info["values"] else ("표" if is_table else "수치")
        row = {
            "chunk_id": cid, "questions": qs, "kind": c.kind, "reason": reason, "page": member, "title": c.rule_title, "header": c.text.partition("\n")[0],
            "line_start": c.line_start, "line_end": c.line_end, "source_url": c.source_url, "version_date": c.version_date,
            "values": info["values"],
            "snapshot": {"file": member, "snapshot_sha256": snap_sha, "match": info["match"], "values_missing_in_page": info["missing"],
                         "values_outside_line_range_but_in_page": info["in_page_only"], "context_differs": info["ctx_diff"]},
        }
        rows.append((row, c, lines, is_table))
        selftest_pool.append((c, lines, is_table))

    # ------------------------------------------------------------ 대조가 틀린 값을 실제로 잡는지(자기 점검)
    st = []
    for c, lines, is_table in selftest_pool:
        for old, new in _mutations(c.text):
            r = check_snapshot(c, lines, c.text.replace(old, new, 1), is_table)
            st.append({"chunk_id": c.chunk_id, "changed": f"{old} -> {new}", "detected": not r["match"]})
            break
    (args.out).mkdir(parents=True, exist_ok=True)
    (args.out / "selftest.json").write_text(json.dumps({"checked": len(st), "detected": sum(x["detected"] for x in st), "cases": st}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    # ------------------------------------------------------------ 현재 원문
    now = datetime.now(KST).isoformat(timespec="seconds")
    pages_cache: dict[str, dict] = {}
    out_rows = []
    current_selftest: list[dict] = []
    for row, c, lines, is_table in rows:
        row["checked_at"] = now
        if not args.fetch:
            row["current"] = {"checked": False}
            out_rows.append(row)
            continue
        url = c.source_url
        if "/-/blob/" in url:   # 승인 권한표: GitLab의 고정 커밋 주소
            raw_url = re.sub(r"/-/blob/", "/-/raw/", url.split("#")[0])
            if raw_url not in pages_cache:
                status, body = fetch(raw_url, args.cache)
                pages_cache[raw_url] = {"status": status, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                        "lines": body.decode("utf-8", "replace").split("\n") if status == 200 else []}
            pg = pages_cache[raw_url]
            cur_window = "\n".join(pg["lines"][c.line_start - 1 : c.line_end]) if pg["status"] == 200 else ""
            snap_window = "\n".join(lines[c.line_start - 1 : c.line_end])
            same = pg["status"] == 200 and cur_window.strip() == snap_window.strip()
            row["current"] = {"checked": True, "url": raw_url, "http_status": pg["status"], "sha256": pg["sha256"], "bytes": pg["bytes"], "mode": "고정 커밋 raw의 같은 줄 범위",
                              "match": bool(same), "values_missing": [] if same else row["values"], "context_differs": []}
        else:
            if url not in pages_cache:
                status, body = fetch(url, args.cache)
                text = html_to_text(body.decode("utf-8", "replace")) if status == 200 else ""
                pages_cache[url] = {"status": status, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "text": text}
            pg = pages_cache[url]
            if pg["status"] != 200:
                row["current"] = {"checked": True, "url": url, "http_status": pg["status"], "match": None, "error": "가져오지 못함"}
            else:
                header, _, body_t = c.text.partition("\n")
                allv = _ctx_with_bare(body_t, is_table) + [(v, "") for v in values(header)]
                cmp_ = compare_all(allv, pg["text"])
                row["current"] = {"checked": True, "url": url, "http_status": pg["status"], "sha256": pg["sha256"], "bytes": pg["bytes"], "mode": "쪽 전체 글자",
                                  "match": not cmp_["missing"] and not cmp_["ctx_diff"], "values_missing": cmp_["missing"], "context_differs": cmp_["ctx_diff"]}
        out_rows.append(row)
        # 현재 원문 대조가 틀린 값을 실제로 잡는지(자기 점검): 수치 하나를 바꾼 글로 같은 쪽을 다시 맞춘다
        if args.fetch and "text" in pages_cache.get(url, {}) and pages_cache[url]["status"] == 200:
            for old, new in _mutations(c.text):
                h2, _, b2 = c.text.replace(old, new, 1).partition("\n")
                r2 = compare_all(_ctx_with_bare(b2, is_table) + [(v, "") for v in values(h2)], pages_cache[url]["text"])
                current_selftest.append({"chunk_id": c.chunk_id, "changed": f"{old} -> {new}", "detected": bool(r2["missing"] or r2["ctx_diff"])})
                break

    if args.fetch:
        d = json.loads((args.out / "selftest.json").read_text(encoding="utf-8"))
        d["current_page_checked"] = len(current_selftest)
        d["current_page_detected"] = sum(x["detected"] for x in current_selftest)
        d["current_page_cases"] = current_selftest
        (args.out / "selftest.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    write_report(out, out_rows, len(qs_by_chunk), snap_sha, args.fetch)
    n = len(out_rows)
    snap_ok = sum(r["snapshot"]["match"] for r in out_rows)
    cur_checked = [r for r in out_rows if r["current"].get("checked")]
    cur_ok = sum(1 for r in cur_checked if r["current"].get("match"))
    print(f"대상 청크 {n}개 (정답 위치에 맞는 청크 {len(qs_by_chunk)}개 중), 스냅샷 일치 {snap_ok}, 현재 원문 확인 {len(cur_checked)}개 중 일치 {cur_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
