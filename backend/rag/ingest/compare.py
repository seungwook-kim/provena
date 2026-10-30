"""원문 대조표 만들기: 파싱 결과 옆에 원본 줄과 GitLab 원본 링크(#L줄번호)를 붙여 사람이 눈으로 맞춰 본다.

python -m backend.rag.ingest.compare           (parse.py 를 먼저 돌려야 한다)
출력: data/parsed/compare/*.md (커밋하지 않음). 판정 결과는 ingest.md 에 옮겨 적는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.rag.ingest.handbook import AUTHZ_COMMIT, AUTHZ_PATH, AUTHZ_PROJECT, PINNED_COMMIT

PAGES = {   # 원문 대조 3건 중 본문 2쪽: 단축코드·경고 상자가 많은 쪽, 표가 많은 쪽
    "incident": "content/handbook/engineering/infrastructure-platforms/incident-management/_index.md",
    "table": "content/handbook/engineering/testing/test-environments-catalog.md",
}
MAX_ROWS = 15


def cell(s: str, n: int = 160) -> str:
    s = s.replace("|", "\\|").replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + " …"


def page_sheet(corpus: Path, parsed: Path, path: str) -> str:
    page = next(p for p in map(json.loads, (corpus / "pages.jsonl").open(encoding="utf-8")) if p["path"] == path)
    raw = (corpus / "handbook" / path.removeprefix("content/handbook/")).read_text(encoding="utf-8").split("\n")
    els = [e for e in map(json.loads, (parsed / "document_ir.jsonl").open(encoding="utf-8"))
           if e["rule_seq"] == page["rule_seq"]][:MAX_ROWS]
    base = f"https://gitlab.com/gitlab-com/content-sites/handbook/-/blob/{PINNED_COMMIT}/{path}"
    lines = [f"# 원문 대조 — {page['title']}", "",
             f"- 원본(같은 판 10/27): {base}", f"- 사이트: {page['source_url']}",
             "- 보는 법: **원본 링크**를 눌러 그 줄을 보고, **파싱 결과**가 같은 내용인지 본다. 기호(`{{% %}}`, `**`, `[](…)`)는 지워지는 게 정상.",
             "", "| # | 종류 | 제목 경로 | 파싱 결과 | 원본 줄 | 원본 링크 | 판정 |", "|---|---|---|---|---|---|---|"]
    for n, e in enumerate(els, 1):
        src = " ⏎ ".join(raw[e["line_start"] - 1:e["line_end"]])
        lines.append(f"| {n} | {e['kind']} | {cell(' > '.join(e['heading_path']), 60)} | {cell(e['text'])} | "
                     f"{cell(src)} | [L{e['line_start']}]({base}#L{e['line_start']}-{e['line_end']}) | |")
    return "\n".join(lines) + "\n"


def authz_sheet(parsed: Path) -> str:
    cells = [c for c in map(json.loads, (parsed / "authz_cells.jsonl").open(encoding="utf-8")) if c["value"]]
    base = f"https://gitlab.com/{AUTHZ_PROJECT}/-/blob/{AUTHZ_COMMIT}/{AUTHZ_PATH}"
    lines = [f"# 원문 대조 — 2023 권한표 글자 있는 칸 {len(cells)}개", "",
             f"- 원본: {base}",
             "- 보는 법: **원본 링크**를 누르면 그 칸의 줄로 간다. 줄 끝 `<!-- 역할 -->` 이 **역할** 칸과 같고, 값이 같은지 본다.",
             "- 역할 이름 대조(363칸 전부)는 코드가 이미 했다. 사람은 **값·업무·금액 구간**이 맞는지 본다.",
             "", "| # | 업무 | 금액 구간 | 역할 | 승인 종류 | 값 | 각주 | 원본 링크 | 판정 |", "|---|---|---|---|---|---|---|---|---|"]
    for n, c in enumerate(cells, 1):
        notes = ",".join(f"({x})" for x in c["notes"])
        lines.append(f"| {n} | {cell(c['category'], 40)} | {cell(c['band'], 40)} | {c['role']} | "
                     f"{'업무' if c['approval_type'] == 'functional' else '재무'} | {cell(c['value'], 60)} | {notes} | "
                     f"[L{c['line']}]({base}#L{c['line']}) | |")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    corpus, parsed = Path("data/corpus"), Path("data/parsed")
    out = parsed / "compare"
    out.mkdir(parents=True, exist_ok=True)
    for name, path in PAGES.items():
        (out / f"{name}.md").write_text(page_sheet(corpus, parsed, path), encoding="utf-8", newline="\n")
    (out / "authz.md").write_text(authz_sheet(parsed), encoding="utf-8", newline="\n")
    print("작성:", ", ".join(str(p) for p in sorted(out.glob("*.md"))))


if __name__ == "__main__":
    main()
