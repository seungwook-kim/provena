"""영향 미리보기(드라이런) 계약 시험 (L-08 시험 공백). 바뀐 섹션을 만드는 비교(`changes_from_pages`)와 `preview_impact`가 내는 칸의 관계만 본다.
규칙 판정(키 없음)만 쓴다. 키·DB·네트워크 없음."""
from __future__ import annotations

import pytest
from recall_test_support import ARTICLE, SEQ, answers_with, changed, reader

from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.recall.impact import changes_from_pages, preview_impact, render_markdown

DOC = "---\ntitle: X\n---\n\n## Policy\n\nWe disclose issues 30 days after the fix.\n\n## Other\n\nUnrelated text stays.\n"


def page(path, old, new):
    return {"path": path, "old": old, "new": new}


def test_changes_from_pages_classifies_modified_added_and_removed():
    pages = [page("content/handbook/security/a.md", DOC, DOC.replace("30 days", "90 days")),
             page("content/handbook/security/b.md", None, DOC),
             page("content/handbook/security/c.md", DOC, None)]
    arts, texts = changes_from_pages(pages, old_date="2026-01-01", new_date="2026-02-01")
    kinds = sorted((a.change_type, a.article) for a in arts)
    assert ("modified", "Policy") in kinds and not any(k == "Other" for _, k in kinds if _ == "modified")  # 안 바뀐 섹션은 바뀐 목록에 없다
    assert {t for t, _ in kinds} == {"modified", "added", "removed"}
    mod = next(a for a in arts if a.change_type == "modified")
    assert any("30 days" in o and "90 days" in n for o, n in texts.values())  # 개정 전후 본문이 같이 나온다
    assert mod.old_version_date == "2026-01-01" and mod.new_version_date == "2026-02-01"


def test_formatting_only_change_is_not_a_change():
    arts, _ = changes_from_pages([page("content/handbook/security/a.md", DOC, DOC.replace("We disclose", "We  disclose  "))],
                                 old_date="2026-01-01", new_date="2026-02-01")
    assert arts == []


def test_report_counts_follow_the_judged_rows():
    answers = answers_with(("a1", "u1"), ("a2", "u2"), ("a3", "u1"))
    rep = preview_impact([changed()], answers=answers, read_section=reader(), today="2026-11-10")
    s = rep.summary
    assert rep.dry_run is True and rep.judge_mode == "rule" and rep.generated_on == "2026-11-10"
    assert s.answers_checked == len(rep.answers) == 3 and s.recipients == 2
    assert s.answers_checked == s.answers_invalidated + s.answers_unchanged
    assert s.changes == 1 and s.changes_by_type == {"added": 0, "removed": 0, "modified": 1}
    assert rep.changes[0].answers_affected == 3 and rep.changes[0].answers_invalidated == s.answers_invalidated
    assert any("규칙 판정" in n for n in rep.notes)


def test_no_saved_answers_gives_zero_rows_and_a_note():
    rep = preview_impact([changed()], answers=InMemoryAnswerStore(), read_section=reader())
    assert rep.summary.answers_checked == 0 and rep.summary.recipients == 0 and rep.answers == []
    assert any("과거 답이 없습니다" in n for n in rep.notes)


def test_preview_never_writes_to_the_answer_store():
    store = answers_with(("a1", "u1"))
    before = [dict(a) for a in store.all_answers()]
    preview_impact([changed()], answers=store, read_section=reader())
    assert [dict(a) for a in store.all_answers()] == before


def test_answers_of_another_section_are_not_counted():
    store = answers_with(("a1", "u1"))
    rep = preview_impact([changed(article="Another > Section")], answers=store, read_section=reader())
    assert rep.summary.answers_checked == 0


def test_markdown_has_no_user_ids_and_keeps_the_attribution():
    rep = preview_impact([changed()], answers=answers_with(("a1", "user-secret-1")), read_section=reader())
    md = render_markdown(rep)
    assert "user-secret-1" not in md and "드라이런" in md and "CC BY-SA" in md
    assert md.count("\n| ") >= 1 and f"**{rep.summary.changes}개**" in md


@pytest.mark.parametrize("kind", ["added", "removed"])
def test_added_and_removed_changes_are_counted_by_type(kind):
    rep = preview_impact([changed(kind)], answers=InMemoryAnswerStore(), read_section=reader())
    assert rep.summary.changes_by_type[kind] == 1 and rep.changes[0].change_type == kind
