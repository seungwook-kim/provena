"""분해 상한(`GRAPH_DECOMPOSE_CAP_S`, 기본 꺼짐) 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).
상한 안에 온 분해는 그대로 쓰고, 넘으면 원 질문 하나로 검색하며 늦은 분해는 버린다. 꺼져 있으면 지금과 같다."""
from __future__ import annotations

import time

import pytest
from qgraph_fakes import ScriptedLLM, j, normal_llm

from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import REVIEW, cite

SUBS = ["코드 리뷰 첫 응답은 며칠 안에 해야 해?", "리뷰를 못 하면 어떻게 해?"]
Q = "코드 리뷰 첫 응답은 며칠 안에 해야 하고, 못 하면 어떻게 해?"
SLOW_S = 1.0


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_DECOMPOSE_CAP_S", "GRAPH_CITE_EXPAND", "GRAPH_CITE_MULTI", "GRAPH_TEAM_LAST", "GRAPH_KEEP_CITES", "GRAPH_SUB_RESEARCH",
                 "GRAPH_PAGE_RESEARCH", "GRAPH_REQUERY_VOCAB", "GRAPH_UNKNOWN_NAME", "GRAPH_QUERY_TERMS", "GRAPH_QUERY_BRANCHES",
                 "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", "SEARCH_DECOMPOSE", "USE_SKILLS",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_PARALLEL_INTAKE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")


def model(delay: float) -> ScriptedLLM:
    def split(_u):
        time.sleep(delay)
        return j(split=True, sub_questions=SUBS)
    return ScriptedLLM({**normal_llm().handlers, "decompose": split, "grounding": j(reason="", grounded=True), "answer": cite(REVIEW)})


def graph(multi: bool, parallel: bool, delay: float):
    seen = []

    def fn(q):
        seen.append(q)
        return [REVIEW]
    kw = {"llm": model(delay), "decompose": True, "parallel_intake": parallel}
    return (build_multi_graph(fn, **kw) if multi else build_graph(fn, **kw)), seen


def run(g):
    return g.invoke({"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
def test_cap_off_waits_for_the_split(multi, parallel):
    g, seen = graph(multi, parallel, delay=0.3)
    out = run(g)
    assert out["decompose_source"] == "llm" and seen[0].sub_queries == SUBS


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
def test_split_inside_the_cap_is_used(monkeypatch, multi, parallel):
    monkeypatch.setenv("GRAPH_DECOMPOSE_CAP_S", "5")
    g, seen = graph(multi, parallel, delay=0.0)
    out = run(g)
    assert out["decompose_source"] == "llm" and seen[0].sub_queries == SUBS


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
def test_late_split_is_dropped_and_the_question_is_searched(monkeypatch, multi, parallel):
    monkeypatch.setenv("GRAPH_DECOMPOSE_CAP_S", "0.2")
    g, seen = graph(multi, parallel, delay=SLOW_S)
    started = time.monotonic()
    out = run(g)
    took = time.monotonic() - started
    assert out["decompose_source"] == "capped" and out["sub_queries"] == []
    assert seen[0].sub_queries is None and "리뷰" in seen[0].query  # 원 질문 하나로 찾는다
    assert out["kind"] == "answer"
    assert took < SLOW_S  # 늦은 분해를 기다리지 않는다
