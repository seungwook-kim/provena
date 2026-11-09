"""알림 피로 줄이기 시험 (F-08): 중요도·확신도 규칙, 사용자 의견 규칙, 하루 요약. LLM 없음."""
from __future__ import annotations

import pytest
from recall_test_support import WORDING_NEW, WORDING_OLD, answers_with, changed, reader

from backend.graph.recall.digest import build_digest, digest_mode, flush_digests
from backend.graph.recall.feedback import LOWERED_NOTE, adjust, summarize, threshold_from_env
from backend.graph.recall.judge import RuleJudge
from backend.graph.recall.service import RecallService
from backend.graph.recall.severity import WORDING_CAP, analyze_change, cap_for_wording, parse_confidence, relevance
from backend.graph.recall.store import InMemoryRecallStore


# ---------------------------------------------------------------- 중요도


@pytest.mark.parametrize("old,new,kind", [
    ("1천만원 미만은 팀 리드가 승인한다.", "5천만원 미만은 팀 리드가 승인한다.", "amount"),
    ("SEV2 장애 최초 대응은 30분 이내에 한다.", "SEV2 장애 최초 대응은 15분 이내에 한다.", "deadline"),
    ("도입 승인은 디렉터가 한다.", "도입 승인은 CTO가 한다.", "approver"),
    ("외부 공유는 허용된다.", "외부 공유는 금지된다.", "permission"),
    ("", "새 섹션 본문", "section_added"),
    ("옛 섹션 본문", "", "section_removed"),
])
def test_high_severity_kinds(old, new, kind):
    a = analyze_change(old, new)
    assert kind in a.kinds and a.severity == "high"


def test_wording_only_is_low():
    a = analyze_change(WORDING_OLD, WORDING_NEW)
    assert a.wording_only and a.severity == "low" and a.pattern == "wording"


def test_unknown_texts_are_high_and_identical_is_none():
    assert analyze_change("", "").severity == "high"
    assert analyze_change("같다", "같다").pattern == "none"


def test_relevance_confidence():
    a = analyze_change("5천만원 이상은 디렉터", "1억원 이상은 디렉터")
    assert relevance("5천만원 도입 승인은?", "디렉터가 승인합니다.", a)[0] == 0.9          # 값이 범위 안
    assert relevance("SaaS를 도입하려면?", "절차를 따릅니다.", a)[0] == 0.45              # 값이 없음
    assert relevance("10억원 도입은?", "CTO가 승인합니다.", a)[0] == 0.3                   # 범위 밖
    assert relevance("q", "a", analyze_change(WORDING_OLD, WORDING_NEW))[0] == 0.3


def test_cap_and_parse_confidence():
    wording = analyze_change(WORDING_OLD, WORDING_NEW)
    assert cap_for_wording(0.95, wording) == WORDING_CAP and cap_for_wording(None, wording) is None
    assert cap_for_wording(0.95, analyze_change("30일", "90일")) == 0.95
    assert parse_confidence(1.7) == 1.0 and parse_confidence(-1) == 0.0 and parse_confidence("0.4") == 0.4
    assert parse_confidence(True) is None and parse_confidence("x") is None and parse_confidence(float("nan")) is None


# ---------------------------------------------------------------- 의견 규칙


NOTICE = {"severity": "high", "explanation": "기한이 달라졌습니다.", "needs_review": False}


def test_feedback_lowers_then_suppresses():
    assert adjust(NOTICE, {"useful": 0, "not_useful": 1}, threshold=2) == NOTICE
    low = adjust(NOTICE, {"useful": 0, "not_useful": 2}, threshold=2)
    assert low["severity"] == "low" and low["explanation"].endswith(LOWERED_NOTE) and not low["needs_review"]
    sup = adjust({**NOTICE, "severity": "low"}, {"useful": 0, "not_useful": 4}, threshold=2)
    assert sup["needs_review"] is True and sup["review_reason"] == "feedback_suppressed"


def test_useful_feedback_cancels_and_zero_threshold_disables():
    assert adjust(NOTICE, {"useful": 2, "not_useful": 3}, threshold=2) == NOTICE
    assert adjust(NOTICE, {"useful": 0, "not_useful": 9}, threshold=0) == NOTICE


def test_threshold_env(monkeypatch):
    monkeypatch.delenv("RECALL_FEEDBACK_THRESHOLD", raising=False)
    assert threshold_from_env() == 2
    monkeypatch.setenv("RECALL_FEEDBACK_THRESHOLD", "0")
    assert threshold_from_env() == 0
    monkeypatch.setenv("RECALL_FEEDBACK_THRESHOLD", "x")
    assert threshold_from_env() == 2


def test_summarize_precision():
    rows = [{"user_id": "u1", "pattern": "amount", "useful": True}, {"user_id": "u1", "pattern": "wording", "useful": False},
            {"user_id": "u2", "pattern": "amount", "useful": True}]
    s = summarize(rows)
    assert s["total"] == 3 and s["precision_from_feedback"] == pytest.approx(2 / 3)
    assert s["by_pattern"]["amount"]["useful"] == 2 and s["by_user"]["u2"]["total"] == 1
    assert summarize([])["precision_from_feedback"] is None


def svc_for(answers, **kw) -> RecallService:
    return RecallService(store=InMemoryRecallStore(), answers=answers, read_section=kw.pop("read_section", reader()), judge=RuleJudge(),
                         min_confidence=0.5, **kw)


def test_feedback_applies_to_next_notice_of_same_user_section_pattern(monkeypatch):
    monkeypatch.setenv("RECALL_FEEDBACK_THRESHOLD", "1")
    svc = svc_for(answers_with(("a1", "u1"), ("a2", "u2")))
    first = svc.process(changed())["notices"]
    n1 = next(n for n in first if n["user_id"] == "u1")
    svc.store.feedback_put({"notice_id": n1["notice_id"], "user_id": "u1", "answer_id": "a1", "rule_seq": n1["changed"]["rule_seq"],
                            "article": n1["changed"]["article"], "pattern": n1["change_pattern"], "severity": "high", "useful": False,
                            "reason": "", "given_by": "u1"})
    later = svc.process(changed(new="2025-09-01"))["notices"]
    by_user = {n["user_id"]: n for n in later}
    assert by_user["u1"]["severity"] == "low" and by_user["u2"]["severity"] == "high"


# ---------------------------------------------------------------- 하루 요약


def test_digest_mode(monkeypatch):
    monkeypatch.delenv("RECALL_DIGEST", raising=False)
    assert digest_mode() == "immediate"
    monkeypatch.setenv("RECALL_DIGEST", "Daily")
    assert digest_mode() == "daily"
    monkeypatch.setenv("RECALL_DIGEST", "weekly")
    assert digest_mode() == "immediate"


def test_build_digest_orders_high_first_and_is_stable():
    def n(i, sev):
        return {"notice_id": f"rn-{i}", "severity": sev, "created_at": f"2026-11-0{i}", "explanation": f"설명{i}", "conclusion_changed": True,
                "changed": {"article": f"A{i}"}}

    did, body = build_digest("u1", "2026-11-09", [n(1, "low"), n(2, "high")])
    assert body["notices"][0]["notice_id"] == "rn-2" and body["high"] == 1 and body["low"] == 1 and body["count"] == 2
    assert body["type"] == "recall_digest" and body["explanation"].startswith("[하루 요약 2건")
    assert build_digest("u1", "2026-11-09", [n(2, "high"), n(1, "low")])[0] == did


def test_daily_mode_holds_webhook_and_flush_groups_by_user(monkeypatch):
    monkeypatch.setenv("RECALL_DIGEST", "daily")
    sent = []
    svc = svc_for(answers_with(("a1", "u1"), ("a2", "u2"), ("a3", "u1")))
    res = svc.process(changed())
    assert res["to_send"] == [] and len(res["notices"]) == 3
    made = flush_digests(svc, day="2026-11-09", deliver=lambda did, body: sent.append(did))
    assert sorted((d["user_id"], d["count"]) for d in made) == [("u1", 2), ("u2", 1)] and len(sent) == 2
    assert all(r["digest_status"] == "sent" for r in svc.store.notices_all())
    assert flush_digests(svc, day="2026-11-09", deliver=lambda *a: sent.append(a)) == [] and len(sent) == 2   # 다시 불러도 중복 없음


def test_review_queue_notices_are_not_in_digest(monkeypatch):
    monkeypatch.setenv("RECALL_DIGEST", "daily")
    svc = svc_for(answers_with(("a1", "u1")), read_section=reader(WORDING_OLD, WORDING_NEW))
    svc.process(changed())
    assert flush_digests(svc, day="2026-11-09", send=False) == []
    nid = svc.store.notices_all()[0]["notice_id"]
    assert svc.review(nid, "release")[1] == []                     # 요약 모드면 풀어 줘도 바로 보내지 않고 요약 대기
    assert [d["count"] for d in flush_digests(svc, day="2026-11-09", send=False)] == [1]
