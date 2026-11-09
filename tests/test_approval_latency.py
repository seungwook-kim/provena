"""`evals/agent/approval_latency.py` 시험: 메모리 체크포인터로 짧게 돌려 잰 구간이 맞는 노드를 덮는지 본다(Postgres·키 없음)."""
from __future__ import annotations

import pytest

from evals.agent import approval_latency as A


@pytest.mark.parametrize("which,node", [("convert", "human_approval"), ("review", "approval")])
def test_resume_covers_the_paused_node_then_the_next(which, node):
    r = A.run_graph_bench("memory", which, 2, None)
    assert r["n"] == 2                                              # 데우기 1회는 뺀다
    assert r["nodes_after_resume"] == [node, "finalize"]            # 재개는 멈춘 노드부터 다시 돌고 그다음 저장 노드로 간다
    for raw in r["raw"]:
        assert 0 < raw["resume_first_node_s"] < raw["resume_end_s"]
        assert raw["stop_s"] > 0 and raw["read_s"] > 0


def test_trial_stops_when_resume_does_not_finish():
    graph, start, decision = A.convert_case(A.InMemorySaver(), A.InMemoryStore(), A.InMemoryDecisionRepo())
    wrong = lambda p: {"approval_id": "다른-건", "approve": True, "comment": "x", "decided_by": "admin-1"}  # noqa: E731
    with pytest.raises(SystemExit, match="재개 뒤에도 승인 대기다"):   # 틀린 결정이면 그래프가 다시 멈춘다: 잰 값으로 쓰지 않는다
        A.one_trial(graph, start, wrong, "t-wrong")


def test_question_graph_runs_without_and_with_checkpointer():
    for kind in ("none", "memory"):
        r = A.run_question_bench(kind, 2, None)
        assert r["n"] == 2 and r["total_s"]["p50"] > 0
