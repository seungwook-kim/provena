"""하루 요약 본문 계약 시험 (L-08 시험 공백). `build_digest`가 내는 칸과 값의 관계만 본다. 키·DB·네트워크 없음."""
from __future__ import annotations

from backend.graph.recall.digest import build_digest


def n(i, sev="high", changed=False):
    return {"notice_id": f"rn-{i}", "severity": sev, "created_at": f"2026-11-{i:02d}", "explanation": f"설명{i}", "conclusion_changed": changed,
            "changed": {"article": f"A{i}"}}


def test_counts_add_up_and_severity_follows_the_high_count():
    _, body = build_digest("u1", "2026-11-09", [n(1, "low"), n(2, "low")])
    assert body["count"] == body["high"] + body["low"] == 2 and body["high"] == 0 and body["severity"] == "low"
    _, body = build_digest("u1", "2026-11-09", [n(1, "low"), n(2, "high")])
    assert body["severity"] == "high" and body["needs_review"] is False


def test_conclusion_changed_is_true_if_any_notice_changed_a_conclusion():
    assert build_digest("u1", "d", [n(1), n(2, changed=True)])[1]["conclusion_changed"] is True
    assert build_digest("u1", "d", [n(1), n(2)])[1]["conclusion_changed"] is False


def test_explanation_lists_at_most_five_other_articles_and_marks_the_rest():
    _, body = build_digest("u1", "d", [n(i) for i in range(1, 9)])
    assert body["count"] == 8 and "외 7건" in body["explanation"] and body["explanation"].endswith("등")
    assert body["explanation"].count("A") == 5      # 첫 건 설명(설명1)에는 A가 없고 나머지 5건의 절 이름만 적는다
    _, small = build_digest("u1", "d", [n(1), n(2)])
    assert "외 1건: A2" in small["explanation"] and not small["explanation"].endswith("등")


def test_id_depends_on_user_day_and_notice_set_but_not_on_order():
    base = build_digest("u1", "d", [n(1), n(2)])[0]
    assert build_digest("u1", "d", [n(2), n(1)])[0] == base
    assert len({base, build_digest("u2", "d", [n(1), n(2)])[0], build_digest("u1", "e", [n(1), n(2)])[0], build_digest("u1", "d", [n(1)])[0]}) == 4
