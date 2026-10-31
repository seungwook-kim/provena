"""파싱: 수집한 원문(data/corpus/)을 요소 단위 중간 표현과 권한표 칸 목록으로 바꾼다.

python -m backend.rag.ingest.parse            (handbook.py 를 먼저 돌려 data/corpus/ 가 있어야 한다)

Spec: docs/specs/parse.md. 원문은 읽기만 하고 결과는 data/parsed/ 에 쓴다(저장소에 커밋하지 않음).
파서 선택 근거: 표본 20쪽 비교에서 markdown-it-py 제목 F1 0.996·표 19/20·코드 20/20.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from html import unescape
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown_it import MarkdownIt

from backend.rag.ingest import snapshot
from backend.rag.ingest.handbook import AUTHZ_PATH, rule_seq

# ── Hugo 단축코드 분류 (원문 45종 전수 조사, 2026-10-29) ──
WRAP = {"alert", "details", "panel", "note", "tableau"}            # 표시만 지우고 안 글자 유지
NAME = {"member-by-name", "member-by-gitlab", "member-and-role-by-gitlab", "label"}   # 인자 글자로
LINK = {"ref"}                                                      # 링크 주소 자리 → 경로
DATA = {                                                            # 사이트가 다른 데이터로 채움 → 지우고 개수 기록
    "team-by-manager-slug", "team-by-manager-role", "team-by-departments", "group-by-slugs",
    "manager-by-report-name", "include", "include-readme", "include-remote", "youtube",
    "performance-indicators", "product/jtbd", "product/section-group-table", "devops-diagram",
    "release-schedule", "release-managers", "a", "all-data-warehouse-sources", "group-pages-by-category",
    "security/public-policy-standards-toc", "support/runbooks",
    "engineering/stable-counterparts", "engineering/test-execution-allure-link",
    "engineering/design-document-header", "engineering/workflow-labels", "engineering/create-retrospectives",
    "engineering/create/career-development", "engineering/verify-team-communication",
    "engineering/design-documents-list", "engineering/service-maturity-scores",
    "engineering/service-maturity-details", "engineering/support-glossary",
    "engineering/section-counterparts", "engineering/stages-counterparts", "engineering/support-skill-areas",
}
SHORTCODE = re.compile(r"\{\{([<%])\s*(/\*)?\s*(/)?\s*([\w/.-]+)(.*?)\s*[%>]\}\}")
QUOTED = re.compile(r'"([^"]*)"')
EMOJI = re.compile(r"(?<![\w/:]):[a-z][a-z0-9_+-]*:(?![\w/:])")   # 앞뒤가 글자면 이모지가 아님(cpe:/o:redhat:…)
FRONT_MATTER = re.compile(r"\A---\n.*?\n---[ \t]*\n", re.S)

MD = MarkdownIt("commonmark").enable("table")


class ParseError(RuntimeError):
    """구조가 약속과 다를 때(권한표 칸 밀림 등). 조용히 넘어가지 않고 멈춘다."""


# ── 전처리: 줄 수를 바꾸지 않는다(요소의 줄 번호 = 원본 줄 번호) ──
def preprocess(raw: str, counts: collections.Counter, unknown: set) -> str:
    text = FRONT_MATTER.sub(lambda m: "\n" * m.group(0).count("\n"), raw)

    def replace(m: re.Match) -> str:
        escaped, closing, name, args = m.group(2), m.group(3), m.group(4), m.group(5)
        if escaped:                       # {{</* x */>}} 는 Hugo도 글자 그대로 보여 준다
            counts["escaped"] += 1
            return m.group(0).replace("/*", "").replace("*/", "")
        if name in WRAP:
            counts["wrap"] += 1
            if closing:
                return ""
            title = re.search(r'(?:summary|header)="([^"]*)"', args)   # details 요약·panel 제목은 화면에 보이는 글자
            return title.group(1).replace("**", "") if title else ""
        if name in NAME:
            counts["name"] += 1
            named = re.search(r'name="([^"]*)"', args)
            return named.group(1) if named else ", ".join(QUOTED.findall(args))
        if name in LINK:
            counts["link"] += 1
            return (QUOTED.findall(args) or [""])[0]
        if name in DATA:
            counts["data"] += 1
            counts[f"data:{name}"] += 1
            return ""
        unknown.add(name)
        return m.group(0)                  # 모르는 것은 지우지 않는다 → 검토 대기

    return SHORTCODE.sub(replace, text)


def html_to_text(html: str) -> str:
    """순서가 로직이다(rag1-07): 주석·script·style 내용째 → 줄바꿈 태그 → 나머지 태그 → 엔티티 → 공백."""
    s = re.sub(r"(?s)<!--.*?-->", " ", html)
    s = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|summary)\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def render_inline(token, links: list) -> str:
    out = []
    for c in token.children or []:
        if c.type == "text":
            out.append(EMOJI.sub("", c.content))
        elif c.type == "code_inline":
            out.append(c.content)
        elif c.type == "softbreak":
            out.append(" ")
        elif c.type == "hardbreak":
            out.append("\n")
        elif c.type == "link_open":
            links.append(c.attrGet("href"))
        elif c.type == "image":
            out.append(f" {c.content} ")   # 대체 글자
        elif c.type == "html_inline":      # 태그는 지우되 경계는 남긴다(<li>A</li><li>B</li> → A B)
            out.append("\n" if re.match(r"(?i)<br", c.content) else " ")
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def closing_index(tokens, i: int) -> int:
    """tokens[i] (…_open) 와 짝인 …_close 위치."""
    depth = 0
    for j in range(i, len(tokens)):
        depth += tokens[j].nesting
        if depth == 0:
            return j
    raise ParseError(f"짝 없는 토큰 {tokens[i].type}")


def flatten(tokens, links: list) -> str:
    """목록·인용 안의 블록을 줄 단위 글자로. 안쪽 목록 항목은 들여쓰기로 남긴다."""
    lines, depth = [], 0
    for t in tokens:
        if t.type == "list_item_open":
            depth += 1
        elif t.type == "list_item_close":
            depth -= 1
        elif t.type == "inline":
            text = render_inline(t, links)
            if text:
                lines.append(("  " * max(depth - 1, 0)) + ("- " if depth else "") + text)
        elif t.type in ("fence", "code_block"):
            lines.append(t.content.rstrip("\n"))
        elif t.type == "html_block":
            text = html_to_text(t.content)
            if text:
                lines.append(text)
    return "\n".join(lines)


def private_cell(token) -> bool:
    """칸 글자가 모두 비공개 주소(internal.gitlab.com) 링크 글자인가(PRD 8장 제외 규칙: '비공개'로 표시, 근거에서 뺌)."""
    hrefs, outside, inside = [], "", 0
    for c in token.children or []:
        if c.type == "link_open":
            inside += 1
            hrefs.append(c.attrGet("href") or "")
        elif c.type == "link_close":
            inside -= 1
        elif c.type == "text" and not inside:
            outside += c.content
    return bool(hrefs) and all("internal.gitlab.com" in h for h in hrefs) and not outside.strip(" ,;/")


def table_rows(tokens) -> tuple[list[str], list[tuple[list[str], list[int] | None, list[int]]]]:
    header, rows, cur, private, in_head, row_map = [], [], [], [], False, None
    for t in tokens:
        if t.type == "thead_open":
            in_head = True
        elif t.type == "thead_close":
            in_head = False
        elif t.type == "tr_open":
            cur, private, row_map = [], [], t.map
        elif t.type == "inline":
            if private_cell(t):
                private.append(len(cur))
            cur.append(render_inline(t, []))
        elif t.type == "tr_close":
            if in_head:
                header = cur
            else:
                rows.append((cur, row_map, private))
    return header, rows


def row_text(header: list[str], cells: list[str]) -> str:
    return " | ".join(f"{h}: {v}" if h else v for h, v in zip(header + [""] * len(cells), cells) if v)


def html_tables(html: str) -> list[tuple[list[str], list[list[str]]]]:
    tables = []
    for table in BeautifulSoup(html, "lxml").find_all("table"):
        rows = [[html_to_text(str(c)) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        has_head = bool(table.find("tr") and table.find("tr").find("th"))
        tables.append((rows[0] if has_head else [], rows[1:] if has_head else rows))
    return tables


def parse_page(page: dict, raw: str, counts: collections.Counter) -> list[dict]:
    """한 쪽 → 요소 목록. 줄 번호는 원본 파일 기준 1부터."""
    unknown: set = set()
    text = preprocess(raw, counts, unknown)
    if text.count("\n") != raw.count("\n"):
        raise ParseError(f"전처리가 줄 수를 바꿈: {page['path']}")
    tokens = MD.parse(text)
    elements, open_heads, parent = [], {}, None        # 제목 단계(1~4) → 글자. 위치가 아니라 단계로 둔다(## 로 시작하는 쪽이 대부분)
    review = f"unknown_shortcode:{','.join(sorted(unknown))}" if unknown else None

    def add(kind: str, txt: str, mp, links=None, **extra) -> dict:
        el = {"element_id": f"{page['rule_seq']}-{len(elements):04d}", "rule_seq": page["rule_seq"],
              "org": page["org"], "kind": kind, "heading_path": [open_heads[k] for k in sorted(open_heads)],
              "parent_id": parent,
              "order": len(elements), "line_start": mp[0] + 1, "line_end": mp[1], "text": txt,
              "links": links or [], "review": review, **extra}
        elements.append(el)
        return el

    i, table_no = 0, 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            level = int(t.tag[1])
            links: list = []
            title = render_inline(tokens[i + 1], links)
            if level <= 4:
                for k in [k for k in open_heads if k >= level]:
                    del open_heads[k]
                open_heads[level] = title
            el = add("heading", title, t.map, links, level=level)
            if level <= 4:
                parent = el["element_id"]
            i = closing_index(tokens, i) + 1
        elif t.type == "paragraph_open":
            links = []
            txt = render_inline(tokens[i + 1], links)
            if txt:
                add("paragraph", txt, t.map, links)
            i = closing_index(tokens, i) + 1
        elif t.type in ("bullet_list_open", "ordered_list_open"):
            end = closing_index(tokens, i)
            j = i + 1
            while j < end:                      # 최상위 항목 하나 = 요소 하나
                k = closing_index(tokens, j)
                links = []
                txt = flatten(tokens[j:k + 1], links)
                if txt:
                    add("list_item", txt, tokens[j].map, links)
                j = k + 1
            i = end + 1
        elif t.type == "blockquote_open":
            end = closing_index(tokens, i)
            links = []
            txt = flatten(tokens[i:end + 1], links)
            if txt:
                add("quote", txt, t.map, links)
            i = end + 1
        elif t.type == "table_open":
            end = closing_index(tokens, i)
            header, rows = table_rows(tokens[i:end + 1])
            table_no += 1
            for n, (cells, mp, private) in enumerate(rows):
                bad = len(cells) != len(header)
                el = add("table_row", row_text(header, cells), mp or t.map,
                         table_id=f"{page['rule_seq']}-t{table_no}", row=n, header=header, cells=cells,
                         private_cells=private)
                if bad and not el["review"]:
                    el["review"] = "cell_count"
            i = end + 1
        elif t.type in ("fence", "code_block"):
            add("code", t.content.rstrip("\n"), t.map, lang=t.info.strip() or None)
            i += 1
        elif t.type == "html_block":
            tables = html_tables(t.content)
            for header, rows in tables:
                table_no += 1
                for n, cells in enumerate(rows):
                    add("table_row", row_text(header, cells), t.map,
                        table_id=f"{page['rule_seq']}-t{table_no}", row=n, header=header, cells=cells, source="html")
            if not tables:
                txt = html_to_text(t.content)
                if txt:
                    add("html", txt, t.map)
            i += 1
        else:
            i += 1                              # hr 등
    return elements


WORD = re.compile(r"[a-z0-9]+")


def found_in_source(el: dict, raw_lines: list[str]) -> bool:
    """요소 글자의 단어가 모두 원본 line_start~line_end 안에 있는가(위치 추적이 맞는지, 내용 검증은 아님).
    표 행은 칸 글자만 본다(머리 이름은 다른 줄에 있다). 원본은 기호를 뺀 글자열로 비교한다(`a`b → ab)."""
    span = "\n".join(raw_lines[el["line_start"] - 1:el["line_end"]]).lower()
    no_link = re.sub(r"\]\([^)]*\)", "]", span)       # 링크 주소는 화면 글자가 아니다([dri](…)s → dris). 코드 속 링크는 글자라 원본도 같이 본다
    src = "\n".join(re.sub(r"[^a-z0-9]", "", s) for s in (span, unescape(span), no_link))
    text = " ".join(el["cells"]) if el["kind"] == "table_row" else el["text"]
    return all(w in src for w in WORD.findall(text.lower()))


# ── 권한표 (2023-05, CSS grid) ──
ROLE_ALIAS = {"Exec Team": "Exec Group"}     # 원문 주석 오타 1곳
GRID_COL = re.compile(r"grid-column:\s*(\d+)\s*/\s*(\d+)")
AMOUNT = re.compile(r"\$\s*([\d.]+)\s*([KkMm])?")


def div_lines(html: str, container: str, cls: str) -> list[int]:
    """<div class="cls ..."> 가 container 뒤에서 나오는 줄 번호(1부터)를 순서대로. lxml 은 sourceline 을 주지 않아 직접 센다."""
    start = html.index(f'class="{container}"')
    return [html.count("\n", 0, m.start()) + 1 for m in re.compile(rf'<div class="{cls}[" ]').finditer(html, start)]


def comment_after(tag: Tag) -> str | None:
    for sib in tag.next_siblings:
        if isinstance(sib, Comment):
            return sib.strip()
        if isinstance(sib, Tag):
            return None
    return None


def text_and_notes(tag: Tag) -> tuple[str, list[int]]:
    notes = [int(n) for sup in tag.find_all("sup") for n in re.findall(r"\((\d+)\)", sup.get_text())]
    clone = BeautifulSoup(str(tag), "lxml")
    for sup in clone.find_all("sup"):
        sup.decompose()
    return clone.get_text(" ", strip=True), notes


def band_range(label: str) -> tuple[float | None, float | None]:
    nums = [float(n) * {"k": 1e3, "m": 1e6}.get((u or "").lower(), 1) for n, u in AMOUNT.findall(label)]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return nums[0], nums[1]
    return (0.0, nums[0]) if label.strip().lower().startswith("up to") else (nums[0], None)


def band_gaps(cells: list[dict]) -> list[dict]:
    """금액 구간이 빈틈없이 이어지는가(도메인 검산). 모든 행이 금액인 업무만 본다. 끊김은 원문 사실로 보고."""
    gaps, by_cat = [], collections.defaultdict(list)
    for c in cells:
        if c["band"] not in [b["band"] for b in by_cat[c["category"]]]:
            by_cat[c["category"]].append(c)
    for cat, bands in by_cat.items():
        if not bands or any(b["band_lo"] is None for b in bands):
            continue
        for prev, cur in zip(bands, bands[1:]):
            if prev["band_hi"] is None or cur["band_lo"] != prev["band_hi"]:
                gaps.append({"category": cat, "after": prev["band"], "band": cur["band"]})
    return gaps


def parse_authz(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    grids = soup.select("div.grid-auth-matrix")
    if len(grids) != 1:
        raise ParseError(f"권한표 본표가 {len(grids)}개 (1개여야 함)")
    items = grids[0].find_all("div", class_="item-auth-matrix", recursive=False)
    item_lines = div_lines(html, "grid-auth-matrix", "item-auth-matrix")
    if len(item_lines) != len(items):
        raise ParseError(f"칸 줄 번호 {len(item_lines)}개 ≠ 칸 {len(items)}개")

    spans = {}
    for d in items[:3]:
        m = GRID_COL.search(d.get("style") or "")
        if m:
            spans[d.get_text(strip=True)] = int(m.group(2)) - int(m.group(1))
    n_func, n_fin = spans.get("Functional approval"), spans.get("Financial approval")
    if not n_func or not n_fin:
        raise ParseError(f"머리 칸(업무/재무 승인) 구조가 다름: {spans}")
    n = n_func + n_fin
    roles = [d.get_text(" ", strip=True) for d in items[4:4 + n]]
    if len(roles) != n or not all(roles):
        raise ParseError(f"역할 머리 칸 {len(roles)}개 (기대 {n})")

    cells, categories, category, cat_notes, i = [], collections.OrderedDict(), None, [], 4 + n
    while i < len(items):
        d = items[i]
        m = GRID_COL.search(d.get("style") or "")
        if m and int(m.group(1)) == 1 and int(m.group(2)) - 1 == n + 1:      # 전체 폭 = 업무 종류 제목
            category, cat_notes = text_and_notes(d)
            categories[category] = 0
            i += 1
            continue
        if category is None:
            raise ParseError(f"업무 종류 제목 없이 행이 시작됨 ({item_lines[i]}줄)")
        band = d.get_text(" ", strip=True)
        row = items[i + 1:i + 1 + n]
        if len(row) != n:
            raise ParseError(f"'{category} / {band}' 행의 칸 {len(row)}개 (기대 {n})")
        lo, hi = band_range(band)
        for col, (role, cell) in enumerate(zip(roles, row)):
            line = item_lines[i + 1 + col]
            note = comment_after(cell)
            if note is None or GRID_COL.search(cell.get("style") or ""):
                raise ParseError(f"'{category} / {band}' {col + 1}번째 칸 구조가 다름 ({line}줄)")
            if ROLE_ALIAS.get(note, note).lower() != role.lower():
                raise ParseError(f"칸 밀림: '{category} / {band}' 열 {role} 인데 주석 {note} ({line}줄)")
            value, notes = text_and_notes(cell)
            cells.append({"category": category, "category_notes": cat_notes, "band": band, "band_lo": lo,
                          "band_hi": hi, "role": role, "approval_type": "functional" if col < n_func else "financial",
                          "value": value, "notes": notes, "line": line,
                          "comment_alias": note if note in ROLE_ALIAS else None})
        categories[category] += 1
        i += 1 + n

    board_divs = soup.select("div.treasury-auth-matrix > div.tr-auth-matrix")
    if not board_divs or len(board_divs) % 2:
        raise ParseError(f"이사회 표 칸 {len(board_divs)}개 (짝수여야 함)")
    board_lines = div_lines(html, "treasury-auth-matrix", "tr-auth-matrix")
    if len(board_lines) != len(board_divs):
        raise ParseError(f"이사회 표 줄 번호 {len(board_lines)}개 ≠ 칸 {len(board_divs)}개")
    board = []
    for k, (item, appr) in enumerate(zip(board_divs[::2], board_divs[1::2])):
        hrefs = [a.get("href") for a in appr.find_all("a")]
        board.append({"item": item.get_text(" ", strip=True), "approval": appr.get_text(" ", strip=True),
                      "links": hrefs, "line": board_lines[2 * k],
                      "private_reference": any("docs.google.com" in (h or "") for h in hrefs)})

    notes = [{"note": int(m.group(1)), "text": m.group(2).strip()}
             for m in re.finditer(r"^- \((\d+)\)\s*(.+)$", html.split("**Notes/Comments**", 1)[-1], re.M)]
    if not notes:
        raise ParseError("각주 (n) 를 찾지 못함")
    return {"roles": roles, "n_functional": n_func, "cells": cells, "rows_by_category": dict(categories),
            "board": board, "notes": notes, "band_gaps": band_gaps(cells)}


def parse_authz_prose(raw: str, counts: collections.Counter) -> list[dict]:
    """권한표 파일의 표 밖 글(계약 승인 절차·각주·Authorization Matrix Policy) → 요소.
    본표·이사회 표(CSS grid div)는 parse_authz 가 칸으로 따로 읽으므로 여기서 뺀다. 그 밖의 HTML이 나오면 멈춘다."""
    lines = raw.split("\n")
    start = next(i for i, l in enumerate(lines) if 'class="grid-auth-matrix"' in l) + 1
    end = next(i for i, l in enumerate(lines) if l.startswith("**Notes/Comments**"))     # 표 두 개가 끝나는 곳
    page = {"rule_seq": rule_seq(AUTHZ_PATH), "org": "finance", "path": AUTHZ_PATH}
    els = [e for e in parse_page(page, raw, counts) if not start <= e["line_start"] <= end]
    stray = [e for e in els if e["kind"] == "html"]
    if stray:
        raise ParseError(f"권한표 본문에 예상 밖 HTML {len(stray)}개 ({stray[0]['line_start']}줄)")
    if not any("Primary Authorized Signatories" in e["text"] for e in els):
        raise ParseError("권한표 정책 본문(Primary Authorized Signatories)을 찾지 못함")
    return els


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with path.open(encoding="utf-8") as f:                       # 저장 성공 ≠ 재사용 가능
        back = sum(1 for line in f if json.loads(line))
    if back != len(rows):
        raise ParseError(f"다시 읽은 건수 {back} ≠ 쓴 건수 {len(rows)}: {path}")


def run(corpus: Path, out: Path) -> dict:
    pages = [json.loads(line) for line in (corpus / "pages.jsonl").open(encoding="utf-8")]
    counts, elements, skipped, review_pages, prov_fail = collections.Counter(), [], [], [], []
    for page in pages:
        if page["redirect_to"]:
            skipped.append(page["path"])
            continue
        raw = (corpus / "handbook" / page["path"].removeprefix("content/handbook/")).read_text(encoding="utf-8")
        page_elements = parse_page(page, raw, counts)
        if any(e["review"] and e["review"].startswith("unknown") for e in page_elements):
            review_pages.append(page["path"])
        raw_lines = raw.split("\n")
        prov_fail += [e["element_id"] for e in page_elements if not found_in_source(e, raw_lines)]
        elements += page_elements

    authz_raw = (corpus / "authz/authorization-matrix-2023-05.html.md").read_text(encoding="utf-8")
    authz = parse_authz(authz_raw)
    authz_prose = parse_authz_prose(authz_raw, counts)
    prov_fail += [e["element_id"] for e in authz_prose if not found_in_source(e, authz_raw.split("\n"))]
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "document_ir.jsonl", elements)
    write_jsonl(out / "authz_cells.jsonl", authz["cells"])
    write_jsonl(out / "authz_board.jsonl", authz["board"])
    write_jsonl(out / "authz_notes.jsonl", authz["notes"])
    write_jsonl(out / "authz_ir.jsonl", authz_prose)

    kinds = collections.Counter(e["kind"] for e in elements)
    report = {
        "parser": {"markdown-it-py": _version("markdown-it-py"), "beautifulsoup4": _version("beautifulsoup4")},
        "corpus_id": json.loads((corpus / "collect_manifest.json").read_text(encoding="utf-8"))["corpus_id"],
        "pages": len(pages), "pages_parsed": len(pages) - len(skipped), "skipped_redirect": skipped,
        "elements": len(elements), "elements_by_kind": dict(kinds),
        "review": {"unknown_shortcode_pages": review_pages,
                   "cell_count_rows": sum(1 for e in elements if e["review"] == "cell_count")},
        "provenance_failures": len(prov_fail), "provenance_failure_ids": prov_fail[:20],
        "shortcodes": {k: v for k, v in sorted(counts.items())},
        "authz": {"roles": authz["roles"], "categories": authz["rows_by_category"],
                  "cells": len(authz["cells"]), "cells_nonempty": sum(1 for c in authz["cells"] if c["value"]),
                  "comment_aliases": sum(1 for c in authz["cells"] if c["comment_alias"]),
                  "band_gaps": authz["band_gaps"], "board_rows": len(authz["board"]),
                  "board_private_reference": [b["item"] for b in authz["board"] if b["private_reference"]],
                  "notes": len(authz["notes"]), "prose_elements": len(authz_prose)},
    }
    (out / "parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
    return report


def _version(dist: str) -> str:
    from importlib.metadata import version
    return version(dist)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ap.add_argument("--out", type=Path, default=Path("data/parsed"))
    args = ap.parse_args()
    snapshot.ensure(args.corpus)  # clone한 뒤 처음이면 data/corpus.tar.gz를 푼다
    r = run(args.corpus, args.out)
    a = r["authz"]
    print(f"{r['pages_parsed']}쪽 → 요소 {r['elements']}개 {r['elements_by_kind']}")
    print(f"건너뜀 {len(r['skipped_redirect'])}쪽, 검토 대기 {len(r['review']['unknown_shortcode_pages'])}쪽, "
          f"표 칸 수 불일치 {r['review']['cell_count_rows']}행, 원문 되찾기 실패 {r['provenance_failures']}개")
    print(f"권한표 {len(a['categories'])}종 {a['cells']}칸(글자 {a['cells_nonempty']}), 구간 끊김 {len(a['band_gaps'])}, "
          f"이사회 {a['board_rows']}행, 각주 {a['notes']}개, 표 밖 본문 요소 {a['prose_elements']}개")
    if r["review"]["unknown_shortcode_pages"] or r["provenance_failures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
