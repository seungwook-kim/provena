"""청킹: 파싱 결과(data/parsed/)를 검색용 청크로 묶는다.

python -m backend.rag.ingest.chunk                                   (기본: 구조 방식 800자, 겹침 120자, 머리말 있음)
python -m backend.rag.ingest.chunk --size 500 --out data/chunks/s500 (D2 비교용. 한 번에 하나만 바꾼다)
python -m backend.rag.ingest.chunk --mode fixed --overlap 100         (기준선: 고정 길이)

Spec: docs/specs/chunk.md. 800/120은 잠정값(조장 사전 측정 25문항 중 1문항 차이) → D2 골든셋으로 다시 잰다.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

from backend.rag.ingest.handbook import AUTHZ_COMMIT, AUTHZ_PATH, AUTHZ_PROJECT, rule_seq

AUTHZ_TITLE = "Authorization Matrix (2023-05)"
SHORT = 80           # 조장 실측 기준(80자 미만 제외)과 같은 숫자를 함께 보고
HEADER_LEVELS = 4    # 1~4단계 제목은 머리말(제목 경로)로만 쓰고, 5단계부터는 본문 글자로 남긴다


def is_header_heading(el: dict) -> bool:
    return el["kind"] == "heading" and el["level"] <= HEADER_LEVELS


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def split_long(text: str, size: int) -> list[str]:
    """size 넘는 요소 하나를 줄 → 문장 → 글자 순으로 쪼갠다. 조각을 이어 붙이면 원래 글자와 같다."""
    units = []
    for line in re.split(r"(?<=\n)", text):
        if len(line) <= size:
            units.append(line)
            continue
        for sent in re.split(r"(?<=[.!?] )", line):
            units += [sent[i:i + size] for i in range(0, len(sent), size)] if len(sent) > size else [sent]
    pieces, cur = [], ""
    for u in units:
        if cur and len(cur) + len(u) > size:
            pieces.append(cur)
            cur = ""
        cur += u
    if cur:
        pieces.append(cur)
    return pieces


def overlap_tail(prev_body: str, n: int) -> str:
    """앞 청크 끝 n자. 단어 중간에서 시작하지 않게 첫 공백 뒤부터."""
    if n <= 0 or not prev_body:
        return ""
    tail = prev_body[-n:]
    if len(prev_body) > n and not prev_body[-n - 1].isspace():
        cut = re.search(r"\s", tail)
        tail = tail[cut.end():] if cut else ""
    return tail.strip()


def pack_section(elements: list[dict], size: int) -> list[list[tuple[dict, str]]]:
    """절 안의 요소를 순서대로 담는다. 요소는 자르지 않고, size 넘는 요소만 조각 하나가 청크 하나."""
    groups, cur, cur_len = [], [], 0
    for el in elements:
        text = el["text"]
        if len(text) > size:
            if cur:
                groups.append(cur)
                cur, cur_len = [], 0
            groups += [[(el, piece)] for piece in split_long(text, size)]
            continue
        added = len(text) + (1 if cur else 0)
        if cur and cur_len + added > size:
            groups.append(cur)
            cur, cur_len, added = [], 0, len(text)
        cur.append((el, text))
        cur_len += added
    if cur:
        groups.append(cur)
    return groups


def make_chunk(page: dict, article: str | None, seq: int, body: str, tail: str, els: list[dict],
               header_on: bool, kind: str, config: str, **extra) -> dict:
    rest = article
    if article and (article == page["title"] or article.startswith(page["title"] + " > ")):
        rest = article[len(page["title"]):].removeprefix(" > ") or None          # 첫 제목 = 페이지 제목이면 한 번만
    header = page["title"] + (f" > {rest}" if rest else "")
    text = "\n".join(p for p in ((header if header_on else ""), tail, body) if p)
    return {
        "chunk_id": sha(f"{page['rule_seq']}:{seq}:{body}")[:16], "org": page["org"], "rule_seq": page["rule_seq"],
        "rule_title": page["title"], "article": article, "version_id": page["version_id"],
        "version_date": page["version_date"], "version_date_before": page["version_date_before"],      # 계약 Chunk 칸, 없으면 KeyError
        "fetched_at": page["fetched_at"], "kind": kind, "text": text,
        "source_url": page["source_url"], "body_sha256": sha(body), "text_sha256": sha(body),      # 계약 칸 = body_sha256(본문만, 머리말·겹침 뺌)
        "body_chars": len(body), "seq": seq,
        "header": header if header_on else None, "overlap_chars": len(tail),
        "element_ids": list(dict.fromkeys(e["element_id"] for e in els)),
        "line_start": extra.pop("line_start", None) or min(e["line_start"] for e in els),
        "line_end": extra.pop("line_end", None) or max(e["line_end"] for e in els),
        "config": config, "_body": body, **extra,      # _body: 검사용, 파일에 쓰기 전에 뺀다
    }


def chunk_structure(page: dict, elements: list[dict], size: int, overlap: int, header_on: bool, config: str) -> list[dict]:
    sections = collections.OrderedDict()
    for el in elements:
        if el["review"] or is_header_heading(el):
            continue                      # 1~4단계 제목은 머리말로, 검토 대기는 색인 제외
        sections.setdefault(tuple(el["heading_path"]), []).append(el)
    chunks = []
    for path, els in sections.items():
        article = " > ".join(path) or None
        prev, done = "", collections.Counter()      # done: 쪼갠 요소에서 이미 쓴 글자 수
        for group in pack_section(els, size):
            body = "\n".join(t for _, t in group)
            tail = overlap_tail(prev, overlap)
            lines = {}
            first, piece = group[0]
            if len(group) == 1 and len(piece) < len(first["text"]) and first["kind"] == "code":
                start = first["line_start"] + 1 + first["text"][:done[first["element_id"]]].count("\n")   # 펜스 줄 다음부터
                lines = {"line_start": start, "line_end": start + piece.rstrip("\n").count("\n")}
            if len(group) == 1:
                done[first["element_id"]] += len(piece)
            chunks.append(make_chunk(page, article, len(chunks), body, tail, [e for e, _ in group], header_on,
                                     "article", config, **lines))
            prev = body
    return chunks


def chunk_fixed(page: dict, elements: list[dict], size: int, overlap: int, config: str) -> list[dict]:
    """기준선: 쪽 본문을 이어 붙여 글자 수로 자른다(PRD 방식 B). 본문 지문은 겹침을 뺀 부분."""
    spans, parts, pos = [], [], 0
    for el in elements:
        if el["review"]:
            continue
        spans.append((pos, pos + len(el["text"]), el))
        parts.append(el["text"])
        pos += len(el["text"]) + 1
    full = "\n".join(parts)
    chunks, step = [], max(size - overlap, 1)
    for start in range(0, len(full), step):
        window = full[start:start + size]
        body = window if start == 0 else window[overlap:]
        if not body.strip():
            continue
        els = [e for s, t, e in spans if s < start + size and t > start] or [spans[-1][2]]
        chunks.append(make_chunk(page, None, len(chunks), body, window[:overlap] if start else "", els,
                                 False, "article", config))
        if start + size >= len(full):
            break
    return chunks


def authz_chunks(parsed: Path, corpus: Path, mode: str, size: int, overlap: int, header_on: bool,
                 config: str) -> tuple[list[dict], list[str], int]:
    """권한표: 표 밖 글(절차·각주·정책)은 쪽과 같은 방식으로, 표는 업무 × 금액 구간 한 행 = 청크(PRD).
    행 청크에도 각주 본문을 같이 넣어 청크만 읽어도 조건을 안다. 이사회 표 첫 행은 열 제목('Board')이라 건너뛰고 그 수를 돌려준다."""
    cells = [json.loads(line) for line in (parsed / "authz_cells.jsonl").open(encoding="utf-8")]
    board = [json.loads(line) for line in (parsed / "authz_board.jsonl").open(encoding="utf-8")]
    notes = {n["note"]: re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", n["text"])        # 각주의 Markdown 링크는 글자만
             for n in map(json.loads, (parsed / "authz_notes.jsonl").open(encoding="utf-8"))}
    commits = {c["sha"]: c for c in map(json.loads, (corpus / "history/authz_commits.jsonl").open(encoding="utf-8"))}
    collected = json.loads((corpus / "collect_manifest.json").read_text(encoding="utf-8"))["collected_at"]
    base = f"https://gitlab.com/{AUTHZ_PROJECT}/-/blob/{AUTHZ_COMMIT}/{AUTHZ_PATH}"
    page = {"rule_seq": rule_seq(AUTHZ_PATH), "org": "finance", "title": AUTHZ_TITLE, "version_id": AUTHZ_COMMIT[:12],
            "version_date": commits[AUTHZ_COMMIT]["date"], "version_date_before": False,      # 권한표는 커밋 날짜를 정확히 앎
            "fetched_at": collected, "source_url": base}
    prose = [json.loads(line) for line in (parsed / "authz_ir.jsonl").open(encoding="utf-8")]
    chunks = (chunk_structure(page, prose, size, overlap, header_on, config) if mode == "structure"
              else chunk_fixed(page, prose, size, overlap, config))
    missing = covered(prose, chunks) if mode == "structure" else []
    rows = collections.OrderedDict()
    for c in cells:
        rows.setdefault((c["category"], c["band"]), []).append(c)
    for (category, band), row in rows.items():
        filled = [c for c in row if c["value"]]
        used = sorted({n for c in row for n in c["category_notes"] + c["notes"]})
        body = "\n".join([f"{category}, {band}:"]
                         + [f"- {c['role']} ({c['approval_type']} approval): {c['value']}"
                            + "".join(f" ({n})" for n in c["notes"]) for c in filled]
                         + ([] if filled else ["- no approver listed"])
                         + [f"({n}) {notes[n]}" for n in used if n in notes])
        lines = [c["line"] for c in row]
        el = {"element_id": f"authz:{category}:{band}", "line_start": min(lines), "line_end": max(lines)}
        chunks.append(make_chunk(dict(page, source_url=f"{base}#L{min(lines)}-{max(lines)}"), f"{category} > {band}",
                                 len(chunks), body, "", [el], True, "row", "authz-row",
                                 band_lo=row[0]["band_lo"], band_hi=row[0]["band_hi"]))
    skipped = 0
    for b in board:
        if not b["item"]:
            if b["approval"] != "Board":
                raise ValueError(f"이사회 표에 항목 없는 행: approval={b['approval']!r}, 줄 {b['line']}")
            skipped += 1                      # 열 제목 칸(왼쪽 빈 칸 + 'Board')이지 항목이 아님
            continue
        el = {"element_id": f"authz-board:{b['item']}", "line_start": b["line"], "line_end": b["line"] + 1}
        chunks.append(make_chunk(dict(page, source_url=f"{base}#L{b['line']}"), "Board-level approvals",
                                 len(chunks), f"{b['item']}: {b['approval']}", "", [el], True, "row", "authz-board",
                                 private_reference=b["private_reference"]))
    return chunks, missing, skipped


def covered(elements: list[dict], chunks: list[dict]) -> list[str]:
    """빠짐없음 검사: 색인 대상 요소마다 글자가 청크 본문에 있는가(쪼갠 요소는 조각을 이어 붙여 본다)."""
    bodies = collections.defaultdict(list)
    for c in chunks:
        for eid in c["element_ids"]:
            bodies[eid].append(c)
    missing = []
    for el in elements:
        if el["review"] or is_header_heading(el):
            continue
        cs = bodies.get(el["element_id"], [])
        if not cs:
            missing.append(el["element_id"])
            continue
        texts = [c["_body"] for c in cs]
        if not any(el["text"] in t for t in texts) and "".join(texts) != el["text"]:
            missing.append(el["element_id"])
    return missing


def run(parsed: Path, corpus: Path, out: Path, mode: str, size: int, overlap: int, header_on: bool) -> dict:
    config = f"{mode}-s{size}-o{overlap}-{'h' if header_on else 'nh'}"
    pages = {p["rule_seq"]: p for p in map(json.loads, (corpus / "pages.jsonl").open(encoding="utf-8"))}
    by_page = collections.OrderedDict()
    for line in (parsed / "document_ir.jsonl").open(encoding="utf-8"):
        el = json.loads(line)
        by_page.setdefault(el["rule_seq"], []).append(el)

    chunks, missing = [], []
    for rs, els in by_page.items():
        page = pages[rs]
        page_chunks = (chunk_structure(page, els, size, overlap, header_on, config) if mode == "structure"
                       else chunk_fixed(page, els, size, overlap, config))
        if mode == "structure":
            missing += covered(els, page_chunks)
        chunks += page_chunks
    authz, authz_missing, board_header = authz_chunks(parsed, corpus, mode, size, overlap, header_on, config)
    chunks += authz
    missing += authz_missing

    out.mkdir(parents=True, exist_ok=True)
    with (out / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            c.pop("_body", None)
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (out / "chunks.jsonl").open(encoding="utf-8") as f:
        if sum(1 for _ in f) != len(chunks):
            raise RuntimeError("다시 읽은 청크 수가 다름")

    lens = [c["body_chars"] for c in chunks]
    long_ = [c for c in chunks if c["body_chars"] >= SHORT]
    report = {
        "config": config, "chunks": len(chunks), "by_kind": dict(collections.Counter(c["kind"] for c in chunks)),
        "docs_with_chunks": len({c["rule_seq"] for c in chunks}),
        "g3_unique_body_sha256": len({c["body_sha256"] for c in chunks}),
        "g3_unique_body_sha256_ge80": len({c["body_sha256"] for c in long_}),
        "short_lt80": len(chunks) - len(long_),
        "body_chars": {"p50": statistics.median(lens), "p90": statistics.quantiles(lens, n=10)[8], "max": max(lens)},
        "missing_elements": len(missing), "missing_ids": missing[:20], "skipped_board_header": board_header,
    }
    (out / "chunk_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                           newline="\n")
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--parsed", type=Path, default=Path("data/parsed"))
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ap.add_argument("--out", type=Path, default=Path("data/chunks"))
    ap.add_argument("--mode", choices=["structure", "fixed"], default="structure")
    ap.add_argument("--size", type=int, default=800)
    ap.add_argument("--overlap", type=int, default=120)
    ap.add_argument("--no-header", action="store_true")
    a = ap.parse_args()
    r = run(a.parsed, a.corpus, a.out, a.mode, a.size, a.overlap, not a.no_header)
    print(f"[{r['config']}] 청크 {r['chunks']} {r['by_kind']}, 문서 {r['docs_with_chunks']}")
    print(f"G3 서로 다른 본문 {r['g3_unique_body_sha256']} (80자 이상만 {r['g3_unique_body_sha256_ge80']}), "
          f"80자 미만 {r['short_lt80']}, 본문 길이 {r['body_chars']}, 빠진 요소 {r['missing_elements']}")
    if r["missing_elements"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
