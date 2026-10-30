"""파싱: 수집한 원문(data/corpus/)을 요소 단위 중간 표현과 권한표 칸 목록으로 바꾼다.

Spec: docs/specs/parse.md. 원문은 읽기만 하고 결과는 data/parsed/ 에 쓴다(저장소에 커밋하지 않음).
파서 선택 근거: 표본 20쪽 비교에서 markdown-it-py 제목 F1 0.996·표 19/20·코드 20/20.
"""
from __future__ import annotations

import collections
import re
from html import unescape

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

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
