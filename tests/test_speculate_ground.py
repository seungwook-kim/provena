"""SG `GRAPH_SPECULATE_GROUND`(기본 꺼짐): 답 후보가 나오는 대로 근거 판정을 미리 부르고, 같은 입력의 판정이 필요하면 그 결과를 쓴다.
판정 입력과 기준은 그대로라 결과는 꺼짐과 같고, 달라지는 것은 판정 호출 시점뿐이다. 가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

import threading
import time

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from test_answer_fixes_graph import REVIEW, REVIEW_TOO, Q_REVIEW, cite, llm, run


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_SPECULATE_GROUND", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_ANSWER", "GRAPH_JUDGE_VOTE", "GRAPH_JUDGE_QUOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def _grounding_calls(m) -> int:
    return sum(1 for t, _ in m.calls if t == "grounding")


def test_flag_is_off_by_default_and_reads_the_variable(monkeypatch):
    assert F.speculate_ground_enabled() is False
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    assert F.speculate_ground_enabled() is True


def test_off_has_no_ahead_mark():
    m = llm(answer=cite(REVIEW))
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and "ground_ahead" not in out["grounding"]
    assert _grounding_calls(m) == 1


def test_on_gives_the_same_answer_with_one_grounding_call(monkeypatch):
    off = llm(answer=cite(REVIEW))
    out_off = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=off, grounding_llm=True), Q_REVIEW)
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    on = llm(answer=cite(REVIEW))
    out_on = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=on, grounding_llm=True), Q_REVIEW)
    assert out_on["kind"] == out_off["kind"] == "answer"
    assert out_on["answer"] == out_off["answer"]
    assert [c["chunk_id"] for c in out_on["citations"]] == [c["chunk_id"] for c in out_off["citations"]]
    assert out_on["grounding"]["ground_ahead"] is True  # 미리 부른 판정을 썼다
    assert _grounding_calls(on) == _grounding_calls(off) == 1  # 같은 입력을 두 번 부르지 않는다


def test_on_keeps_an_ungrounded_verdict_and_the_refusal(monkeypatch):
    bad = j(reason="unsupported", grounded=False, reason_code="no_evidence", unsupported_sentences=[])
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    m = llm(answer=cite(REVIEW), grounding=bad)
    out = run(build_graph(lambda q: [REVIEW], llm=m, grounding_llm=True), Q_REVIEW)
    monkeypatch.delenv("GRAPH_SPECULATE_GROUND")
    ref = llm(answer=cite(REVIEW), grounding=bad)
    out_off = run(build_graph(lambda q: [REVIEW], llm=ref, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == out_off["kind"] == "refuse"
    assert out["answer"] == out_off["answer"]


def test_a_different_answer_is_judged_fresh(monkeypatch):
    """미리 부른 판정은 입력이 같을 때만 쓴다. 답이 다르면 새로 부른다."""
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    m = llm(answer=cite(REVIEW))
    g = build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True)
    out = run(g, Q_REVIEW)
    assert out["grounding"]["ground_ahead"] is True
    m2 = llm(answer=cite(REVIEW_TOO))
    out2 = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m2, grounding_llm=True), Q_REVIEW)
    assert [c["chunk_id"] for c in out2["citations"]] == [REVIEW_TOO.chunk_id]
    assert out2["grounding"]["ground_ahead"] is True


def test_speculation_failure_does_not_break_the_answer(monkeypatch):
    """검사가 걸려 판정을 미리 부르지 않은 답(인용 없음)은 지금처럼 거절된다."""
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    m = llm(answer=j(asked=["사실"], picks=[], answer="인용 없는 답", citations=[], period_covered=True))
    out = run(build_graph(lambda q: [REVIEW], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "refuse" and _grounding_calls(m) == 0


def test_best2_candidates_ground_ahead_and_the_picked_one_is_reused(monkeypatch):
    """둘째 답까지 쓰는 구성(BO2)에서 후보마다 미리 판정하고, 뽑힌 답의 판정을 쓴다. 판정 호출은 후보 수 이하다."""
    for name, value in (("GRAPH_SPECULATE_GROUND", "1"), ("GRAPH_JUDGE_QUOTE", "1"), ("GRAPH_ANSWER_BEST2", "1"), ("GRAPH_JUDGE_ANSWER", "parallel_all")):
        monkeypatch.setenv(name, value)
    answers = [cite(REVIEW), cite(REVIEW_TOO)]
    lock = threading.Lock()
    seen: list[int] = []

    def answer(user):
        with lock:
            i = len(seen)
            seen.append(i)
        time.sleep(0.01 * i)
        return answers[min(i, 1)]

    m = llm(answer=answer, judge=j(checks=[{"fact": "응답 기한", "value": "2 business days", "quote": "within 2 business days"}], sufficient=True, partial=False,
                                   reason="", missing=[], clarify=None, query=""))
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer"
    assert 1 <= _grounding_calls(m) <= 2

