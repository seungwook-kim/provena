"""영향 미리보기 마크다운: 빈 섹션 이름은 표에서만 '(제목 없는 구간)'으로 보이고 데이터(article='')는 그대로다."""
from __future__ import annotations

from recall_test_support import answers_with, changed, reader

from backend.graph.recall.impact import preview_impact, render_markdown

LABEL = "(제목 없는 구간)"


def test_empty_article_shows_label_in_markdown_but_stays_empty_in_report():
    rep = preview_impact([changed(article="")], answers=answers_with(("a1", "u1")), read_section=reader(), today="2026-11-13")
    md = render_markdown(rep)
    assert rep.changes[0].article == ""
    assert md.count(LABEL) >= 1
    assert f"| {LABEL} | modified |" in md
    assert "|  | modified |" not in md


def test_whitespace_article_also_shows_label():
    rep = preview_impact([changed(article="  ")], answers=answers_with(("a1", "u1")), read_section=reader(), today="2026-11-13")
    assert f"| {LABEL} | modified |" in render_markdown(rep)


def test_answers_table_uses_label_for_empty_article():
    rep = preview_impact([changed()], answers=answers_with(("a1", "u1")), read_section=reader(), today="2026-11-13")
    rep.answers[0].verdict = "needs_review"
    rep.answers[0].article = ""
    md = render_markdown(rep)
    assert f"| {LABEL} | 확인 필요 |" in md


def test_named_article_is_unchanged():
    rep = preview_impact([changed()], answers=answers_with(("a1", "u1")), read_section=reader(), today="2026-11-13")
    assert LABEL not in render_markdown(rep)
