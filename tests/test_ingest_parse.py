"""파싱 (docs/specs/parse.md AC). 원문 없이 작은 예시로 돈다."""
import collections

from backend.rag.ingest import parse as P

PAGE = {"rule_seq": 7, "org": "security"}


def elements(md: str):
    return P.parse_page(PAGE, md, collections.Counter())


# AC-01 · 줄 번호 보존
def test_preprocess_keeps_line_count_and_classifies_shortcodes():
    raw = ('---\ntitle: X\n---\n{{% alert color="info" %}}\nkeep me\n{{% /alert %}}\n'
           'Owner: {{< member-by-name "Kirsty Allen" >}}\n{{< team-by-manager-slug "a" >}}\n'
           '{{% details summary="Open me" %}}\n{{</* performance-indicators "x" */>}}\n')
    counts, unknown = collections.Counter(), set()
    out = P.preprocess(raw, counts, unknown)
    assert out.count("\n") == raw.count("\n")
    assert "keep me" in out and "Kirsty Allen" in out and "Open me" in out
    assert "team-by-manager-slug" not in out and "{{% alert" not in out
    assert '{{< performance-indicators "x" >}}' in out          # 이스케이프는 글자로
    assert counts["data"] == 1 and not unknown


def test_unknown_shortcode_is_review_not_dropped():
    els = elements("Text {{< brand-new-thing >}}\n")
    assert els[0]["review"] == "unknown_shortcode:brand-new-thing"
    assert "brand-new-thing" in els[0]["text"]                  # 조용히 지우지 않는다


def test_line_numbers_point_to_source():
    raw = "---\ntitle: X\n---\n\n## Severities\n\nS1 is the highest.\n"
    els = elements(raw)
    para = [e for e in els if e["kind"] == "paragraph"][0]
    assert raw.split("\n")[para["line_start"] - 1] == "S1 is the highest."
    assert P.found_in_source(para, raw.split("\n"))
    assert not P.found_in_source(dict(para, line_start=5, line_end=5), raw.split("\n"))   # 다른 줄이면 실패


# AC-02 · HTML 정리 순서
def test_html_to_text_order():
    html = "<p>Beware of &lt;script&gt;alert(1)&lt;/script&gt; tags</p><script>evil()</script><br>next"
    text = P.html_to_text(html)
    assert "Beware of <script>alert(1)</script> tags" in text   # 엔티티를 먼저 풀면 이 문장이 지워진다
    assert "evil" not in text and "next" in text


# AC-03 · 코드 블록 속 # 는 제목이 아님
def test_hash_in_four_backtick_fence_is_not_heading():
    md = "````markdown\n# Not a heading\n```\ninner\n```\n## Still code\n````\n\n## Real\n"
    kinds = [(e["kind"], e["text"].split("\n")[0]) for e in elements(md)]
    assert kinds == [("code", "# Not a heading"), ("heading", "Real")]


def test_heading_path_and_parent():
    els = elements("## A\n\n### B\n\ntext\n\n## C\n\nmore\n")
    text, more = [e for e in els if e["kind"] == "paragraph"]
    assert text["heading_path"] == ["A", "B"] and more["heading_path"] == ["C"]
    assert text["parent_id"] == "7-0001" and more["parent_id"] == "7-0003"


def test_table_rows_carry_header_and_html_boundaries():
    els = elements("| Role | Duty |\n|---|---|\n| EOC | <ul><li>Page</li><li>Fix</li></ul> |\n")
    row = [e for e in els if e["kind"] == "table_row"][0]
    assert row["text"] == "Role: EOC | Duty: Page Fix"           # <li> 경계가 글자를 붙이지 않는다
    assert row["cells"] == ["EOC", "Page Fix"] and row["review"] is None


def test_internal_link_only_cell_marked_private():
    els = elements("| Name | Doc |\n|---|---|\n| Airflow | [Infra](https://internal.gitlab.com/x) |\n"
                   "| Docker | See [x](https://internal.gitlab.com/y) |\n")
    rows = [e for e in els if e["kind"] == "table_row"]
    assert rows[0]["private_cells"] == [1]          # 비공개 링크만 있는 칸 (PRD 8장 제외 규칙)
    assert rows[1]["private_cells"] == []           # 링크 밖 글자가 있으면 비공개 칸이 아니다


def test_emoji_removed_but_identifiers_kept():
    els = elements("## :tada: Achievements\n\nUse cpe:/o:redhat:enterprise_linux:8 here.\n")
    assert els[0]["text"] == "Achievements"
    assert ":redhat:" in els[1]["text"]
