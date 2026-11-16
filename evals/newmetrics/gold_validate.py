"""정답 파일 기계 확인(요청 문서 5장 "확인은 기계로, 위치만 봅니다"). 내용은 고치지 않는다. 오류가 있으면 작성자에게 다시 묻는다.

    python -m evals.newmetrics.gold_validate --gold-dir evals [--out 보고.json]

오류(error, 종료 코드 1):
- 공통: 번호 범위 밖·작성 예시·뺀 커밋(4667e540)·중복(`common.check_rows`), 예시 글을 그대로 옮긴 행
- 리콜: 커밋이 캐시에 있음, 커밋 직전 판에 페이지가 있음, 바뀐 섹션을 찾음, 개정 전 근거 문장이 커밋 직전 판 파일에, 개정 뒤 근거 문장이 커밋 판 파일에 있음
  (링크 표기·백틱·굵게·공백 차이 무시, "삭제됨"이면 개정 뒤 칸은 보지 않음), 결론 바뀜이 예/아니오
- 결정표: 구간 줄 번호의 줄에 그 구간 글자가 있음, 줄이 주 권한표(61~481줄) 안
- 링크: 출발 페이지가 코퍼스에 있음, 줄 번호의 줄에 링크 주소가 있음, 대상 페이지가 pages.jsonl 경로이거나 코퍼스 밖/자기 페이지/비공개
- 후보: 링크하는 페이지가 코퍼스에 있음, 줄 번호마다 그 줄에 개정된 페이지 주소(페이지 이름)가 있음, 함께 봐야 하나가 예/아니오
경고(warning, 묻기 전 참고): 맡은 범위 밖 페이지·업무 종류, 근거 문장이 바뀐 섹션 본문 밖, 결정표 칸 글자가 원문 칸 줄과 다름, 섹션 이름이 원문 제목 경로와 다름.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from evals.newmetrics.common import (AUTHZ_MD, GOLD_FILES, HANDBOOK, GoldError, check_rows, line_articles, read_jsonl, read_pages,
                                     section_key)
from evals.newmetrics.spec_tables import (AUTHZ_RANGE, LINK_PAGES, LINK_SPECIAL, MAINTENANCE_REVISIONS, ROLES, category_for_line,
                                          parser_category)

# 요청 문서 작성 예시의 글(이 글이 정답 행에 그대로 있으면 예시를 옮긴 것이다)
EXAMPLE_SNIPPETS = (
    "보안 취약점 기밀 이슈는 패치가 나오고 얼마 뒤에 공개로 바꿔?", "계속 기밀로 둬야 하는 보안 이슈는 어떻게 표시해?",
    "(예시) Team Lunch", "(예시) Up to $100", "hackerone-process/#closing-out--disclosing-issues",
    "공개 절차를 안내하는 답이라 공개 기한(30일 → 90일)이 바뀌면 함께 확인해야 함", "심각도별 해결 기한 표를 가리키는 링크로, 공개 기한 변경과 관계없음",
)
_LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def norm_text(s: str | None) -> str:
    """근거 문장 비교용: 링크 표기 [글자](주소) -> 글자, 백틱·굵게·기울임·따옴표 정리, 공백 하나로."""
    t = str(s or "")
    t = re.sub(r"(?m)^[ \t]*(?:>[ \t]?)+", "", t)      # 인용 블록 표시(> )는 줄을 넘는 문장을 끊으므로 뗀다
    t = _LINK_MD.sub(r"\1", t)
    t = t.replace("`", "").replace("**", "").replace("__", "")
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def evidence_core(s: str | None) -> str:
    """감싼 따옴표와 끝 말줄임을 뗀 근거 문장."""
    t = norm_text(s).strip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        t = t[1:-1].strip()
    return t.rstrip("…").removesuffix("...").strip()


def strip_tags(s: str) -> str:
    s = re.sub(r"<sup>\s*(\([^)]*\))\s*</sup>", r"\1", s)
    s = re.sub(r"<!--.*?-->", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class Report:
    def __init__(self):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def err(self, metric, rid, msg):
        self.errors.append({"metric": metric, "id": rid, "msg": msg})

    def warn(self, metric, rid, msg):
        self.warnings.append({"metric": metric, "id": rid, "msg": msg})

    def as_dict(self):
        return {"ok": not self.errors, "errors": self.errors, "warnings": self.warnings}


def _examples(metric: str, rows: list[dict], rep: Report) -> None:
    for r in rows:
        blob = json.dumps(r, ensure_ascii=False)
        for s in EXAMPLE_SNIPPETS:
            if s in blob:
                rep.err(metric, r.get("id"), f"작성 예시 글을 옮긴 행이다: {s[:30]}")


def validate_recall(rows: list[dict], rep: Report, history=None) -> None:
    from evals.newmetrics.handbook_history import HandbookHistory

    h = history or HandbookHistory()
    if not h.available():
        rep.err("recall", "*", f"핸드북 캐시가 없다: {h.cache}")
        return
    cache: dict = {}
    for r in rows:
        rid = r["id"]
        if r.get("expected") is None:
            rep.err("recall", rid, f"결론 바뀜이 예/아니오가 아니다: {r.get('expected_raw')!r}")
        if not str(r.get("question") or "").strip() or not str(r.get("answer") or "").strip():
            rep.err("recall", rid, "질문 또는 지난 답이 비었다")
        key = (r["commit"], r["page"], r["section"])
        if key not in cache:
            try:
                cache[key] = h.section_change(*key)
            except Exception as e:  # noqa: BLE001
                cache[key] = e
        c = cache[key]
        if isinstance(c, Exception):
            rep.err("recall", rid, f"커밋·페이지·섹션 확인 실패: {c}")
            continue
        for k in ("rule_seq", "article", "old_version_date", "new_version_date", "as_of", "change_type"):
            if r.get(k) in (None, ""):
                rep.err("recall", rid, f"시스템 칸 {k}가 비었다(변환기를 핸드북 캐시와 함께 다시 돌린다)")
        old_file, new_file = norm_text(c.old_raw), norm_text(c.new_raw)
        oe, ne = evidence_core(r.get("old_evidence")), evidence_core(r.get("new_evidence"))
        if not oe:
            rep.err("recall", rid, "개정 전 근거 문장이 비었다")
        elif oe not in old_file:
            rep.err("recall", rid, "개정 전 근거 문장이 커밋 직전 판 파일에 없다")
        elif oe not in norm_text(c.old_text):
            rep.warn("recall", rid, "개정 전 근거 문장이 바뀐 섹션 본문 밖에 있다")
        if ne == "삭제됨":
            if oe and oe in new_file:
                rep.warn("recall", rid, "개정 뒤 칸이 '삭제됨'인데 개정 전 문장이 커밋 판 파일에 그대로 있다")
        elif not ne:
            rep.err("recall", rid, "개정 뒤 근거 문장이 비었다")
        elif ne not in new_file:
            rep.err("recall", rid, "개정 뒤 근거 문장이 커밋 판 파일에 없다")


def validate_decision(rows: list[dict], rep: Report) -> None:
    lines = AUTHZ_MD.read_text(encoding="utf-8").split("\n")
    for r in rows:
        rid, ln = r["id"], r.get("band_line")
        if not ln:
            rep.err("decision", rid, f"구간 줄이 숫자가 아니다: {r.get('band_line_raw')!r}")
            continue
        if not (AUTHZ_RANGE[0] <= ln <= AUTHZ_RANGE[1]):
            rep.err("decision", rid, f"구간 줄 {ln}이 주 권한표(61~481줄) 밖이다")
            continue
        got = strip_tags(lines[ln - 1])
        if norm_text(r.get("band")) != norm_text(got):
            rep.err("decision", rid, f"구간 줄 {ln}의 글자가 적은 구간과 다르다")
        cat = category_for_line(ln)
        if cat is None:
            rep.err("decision", rid, f"구간 줄 {ln}이 어느 업무 종류에도 들지 않는다")
        elif r.get("category") and parser_category(r["category"]) != parser_category(cat):
            rep.warn("decision", rid, f"업무 종류 칸이 줄 범위의 업무 종류({cat})와 다르다")
        for k, role in enumerate(ROLES, start=1):
            want = strip_tags(lines[ln - 1 + k]) if ln - 1 + k < len(lines) else ""
            if norm_text(r["cells"].get(role)) != norm_text(want):
                rep.warn("decision", rid, f"{role} 칸(구간 줄+{k})이 원문 칸 줄과 다르다")


def _line(rel: str, n: int | None, cache: dict) -> str | None:
    if rel not in cache:
        p = HANDBOOK / rel
        cache[rel] = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n") if p.exists() else None
    ls = cache[rel]
    if ls is None or not n or n < 1 or n > len(ls):
        return None
    return ls[n - 1]


def validate_link(rows: list[dict], rep: Report) -> None:
    pages, cache, arts = read_pages(), {}, {}
    for r in rows:
        rid, src = r["id"], r["source_page"]
        if src not in pages:
            rep.err("link", rid, f"출발 페이지가 코퍼스에 없다: {src}")
            continue
        if src not in LINK_PAGES.get(r.get("author") or "", ()):
            rep.warn("link", rid, "맡은 페이지가 아니다")
        line = _line(src, r.get("line"), cache)
        if line is None:
            rep.err("link", rid, f"줄 번호가 페이지 범위 밖이다: {r.get('line_raw')!r}")
            continue
        url = str(r.get("url") or "").strip()
        if not url or (url not in line and html.unescape(url) not in html.unescape(line)):
            rep.err("link", rid, "줄 번호의 줄에 링크 주소가 없다")
        t = r.get("target")
        if t not in LINK_SPECIAL and t not in pages:
            rep.err("link", rid, f"대상 페이지가 pages.jsonl 경로도, 코퍼스 밖·자기 페이지·비공개도 아니다: {r.get('target_raw')!r}")
        if src not in arts:
            arts[src] = line_articles(src)
        if r.get("section") and section_key(r["section"]) != section_key(arts[src][r["line"]]):
            rep.warn("link", rid, "섹션 이름이 원문 제목 경로와 다르다(측정은 줄 번호의 제목 경로로 센다)")


def validate_maintenance(rows: list[dict], rep: Report) -> None:
    pages, cache = read_pages(), {}
    for r in rows:
        rid, page = r["id"], r["linking_page"]
        rev = next((v for v in MAINTENANCE_REVISIONS.values() if v["page"] == r["revised_page"]), None)
        if page not in pages:
            rep.err("maintenance", rid, f"링크하는 페이지가 코퍼스에 없다: {page}")
            continue
        if page == r["revised_page"]:
            rep.err("maintenance", rid, "개정된 페이지 자신이다(빼야 한다)")
        if r.get("needed") is None:
            rep.err("maintenance", rid, f"함께 봐야 하나가 예/아니오가 아니다: {r.get('needed_raw')!r}")
        if not r.get("lines"):
            rep.err("maintenance", rid, "줄 번호가 없다")
        for n in r.get("lines") or []:
            line = _line(page, n, cache)
            if line is None:
                rep.err("maintenance", rid, f"줄 번호 {n}이 페이지 범위 밖이다")
            elif rev and rev["slug"] not in line:
                rep.err("maintenance", rid, f"줄 {n}에 개정된 페이지 주소({rev['slug']})가 없다")


def validate_all(gold_dir: Path, history=None) -> dict:
    rep = Report()
    found = {}
    for metric, name in GOLD_FILES.items():
        p = gold_dir / name
        if not p.exists():
            rep.err(metric, "*", f"정답 파일이 없다: {p}")
            continue
        rows = read_jsonl(p)
        found[metric] = len(rows)
        try:
            check_rows(metric, rows)
        except GoldError as e:
            rep.err(metric, "*", str(e))
            continue
        _examples(metric, rows, rep)
        {"recall": lambda: validate_recall(rows, rep, history), "decision": lambda: validate_decision(rows, rep),
         "link": lambda: validate_link(rows, rep), "maintenance": lambda: validate_maintenance(rows, rep)}[metric]()
    return {**rep.as_dict(), "rows": found, "ambiguous": {m: sum(1 for r in read_jsonl(gold_dir / n) if r.get("ambiguous"))
                                                          for m, n in GOLD_FILES.items() if (gold_dir / n).exists()}}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="정답 파일 위치 확인(내용은 고치지 않음)")
    ap.add_argument("--gold-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    res = validate_all(a.gold_dir)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
    print(text)
    print("확인 통과" if res["ok"] else f"오류 {len(res['errors'])}건: 작성자에게 다시 묻는다(정답을 고치지 않는다)")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
