"""멀티 에이전트 질문 그래프 시험 (D-09, `backend/graph/multi.py`). 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

확인하는 것: Supervisor가 하위 에이전트를 순서대로 부르는지, 거절 경로와 재검색 경로가 단일 그래프와 같게 끝나는지,
같은 입력에서 단일과 멀티의 결과 상태, LLM 호출 순서, 검색 호출이 같은지, 하위 에이전트가 자기 칸만 받는지.
"""
from __future__ import annotations

import pytest
from fake_search import fake_search
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from qgraph_fakes import first_chunk_id, j, normal_llm

from backend.graph import multi
from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.build import MAX_RESEARCH, MSG_REFUSE, MSG_REFUSE_NO_KEY, MSG_REFUSE_SEARCH_DOWN, build_graph
from backend.graph.multi import AGENTS, RETRIEVER, VERIFIER, WRITER, SingleParts, build_agents, build_multi_graph
from backend.graph.stream import stream_events
from backend.rag.retrieve.embed import EmbedUnavailable

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
MULTI_ONLY = {"next_agent", "agent_trace", "supervisor_log", "handoffs"}


def run(g, **kw):
    base = {"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"}
    base.update(kw)
    return g.invoke(base)


def rewrites():
    """재작성이 매번 다른 질의를 낸다(같은 질의면 검색 기억이 앞 결과를 쓴다)."""
    n = iter(range(100))
    return lambda user: j(query=f"SEV2 최초 대응 {next(n)}", org="TEST-security", as_of=None)


def recorded(fn=fake_search):
    calls = []

    def search(q):
        calls.append(q)
        return fn(q)

    return search, calls


# ---------- 시나리오: 단일과 멀티에 같은 입력을 준다 ----------
def _unavailable(q):
    raise EmbedUnavailable("임베딩 일시 오류")


def _no_key(q):
    from backend.rag.retrieve.search import SearchTrace, _last

    _last.set(SearchTrace("voyage-4", "none", "dense_en", fallback_reason="no_key"))
    return []


def _fake_cite(user):
    cid = first_chunk_id(user)
    return j(answer=f"대응 시간은 정해져 있다 [{cid}] 그리고 [deadbeefdeadbeef] 도 근거다.", citations=[{"chunk_id": cid}, {"chunk_id": "deadbeefdeadbeef"}])


def _insufficient(**kw):
    return normal_llm(judge=j(sufficient=False, reason="부족", clarify=None), rewrite=rewrites(), **kw)


SCENARIOS = {
    "normal": dict(llm=lambda: normal_llm()),
    "out_of_domain": dict(llm=lambda: normal_llm(classify=j(route="out_of_domain")), question="사내 연봉 협상은 어떻게 하나요?"),
    "out_of_domain_split_vote": dict(llm=lambda: normal_llm(classify=[j(route="out_of_domain"), j(route="rule")])),
    "refuse_after_two_researches": dict(llm=_insufficient),
    "clarify": dict(llm=lambda: normal_llm(judge=j(sufficient=False, reason="절 불명", clarify="어느 절 기준인가요?"))),
    "clarify_with_number_becomes_refuse": dict(llm=lambda: normal_llm(judge=j(sufficient=False, reason="x", clarify="30분이 맞나요?"))),
    "recovers_on_second_search": dict(llm=lambda: normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)], rewrite=rewrites())),
    "recovers_on_third_search": dict(llm=lambda: normal_llm(judge=[j(sufficient=False, reason="x", clarify=None)] * 2 + [j(sufficient=True)], rewrite=rewrites())),
    "same_query_requery_uses_search_memo": dict(llm=lambda: normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)])),
    "empty_search_result": dict(llm=lambda: normal_llm(), search=lambda q: []),
    "garbage_llm_output": dict(llm=lambda: normal_llm(classify="??", rewrite="not json", judge="}{", answer="x")),
    "broken_json_asked_again": dict(llm=lambda: normal_llm(judge=["}{", j(sufficient=True)])),
    "fake_citation_dropped": dict(llm=lambda: normal_llm(answer=_fake_cite)),
    "only_fake_citation": dict(llm=lambda: normal_llm(answer=j(answer="답 [deadbeefdeadbeef]", citations=[{"chunk_id": "deadbeefdeadbeef"}]))),
    "non_json_answer": dict(llm=lambda: normal_llm(answer="그냥 문장입니다.")),
    "grounding_rule_nonexistent_entity": dict(llm=lambda: normal_llm(), question="SEV9 장애 최초 대응은 몇 분 이내인가요?"),
    "grounding_llm_refuses": dict(llm=lambda: normal_llm(grounding=j(grounded=False, reason_code="unsupported", reason="기한이 다름")), grounding_llm=True),
    "grounding_llm_grounded": dict(llm=lambda: normal_llm(grounding=j(grounded=True)), grounding_llm=True),
    "period_covered_false": dict(llm=lambda: normal_llm(answer=j(answer="", citations=[], period_covered=False))),
    "search_unavailable": dict(llm=_insufficient, search=_unavailable),
    "search_no_key": dict(llm=_insufficient, search=_no_key),
    "skills_off": dict(llm=lambda: normal_llm(), use_skills=False),
    "unconnected_route_review": dict(llm=lambda: normal_llm(classify=j(route="review"))),
}


def _run_pair(name):
    sc = SCENARIOS[name]
    outs = {}
    for label, build in (("single", build_graph), ("multi", build_multi_graph)):
        llm, (search, calls), store = sc["llm"](), recorded(sc.get("search", fake_search)), InMemoryAnswerStore()
        kw = {k: sc[k] for k in ("grounding_llm", "use_skills") if k in sc}
        g = build(search, llm=llm, answer_store=store, **kw)
        try:
            out = run(g, **({"question": sc["question"]} if "question" in sc else {}))
        finally:
            pass
        outs[label] = {"out": out, "llm": [t for t, _ in llm.calls], "llm_prompts": llm.calls, "search": calls, "saved": len(store.all_answers())}
    return outs


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_multi_ends_exactly_like_single(name):
    o = _run_pair(name)
    s, m = o["single"], o["multi"]
    keep = lambda out: {k: v for k, v in out.items() if k not in MULTI_ONLY | {"answer_id"}}  # noqa: E731  answer_id는 실행마다 새로 만든 uuid다
    assert keep(m["out"]) == keep(s["out"])  # 결과 상태 전체: kind, answer, citations, retries, search_stats, grounding ...
    assert (m["out"].get("answer_id") is None) == (s["out"].get("answer_id") is None)
    assert m["llm_prompts"] == s["llm_prompts"]  # LLM 호출 순서와 프롬프트 입력까지 같다(늘어나는 호출 없음)
    assert m["search"] == s["search"]  # 검색 호출(질의, 절, 기준일, k, 하위 질문)이 같다
    assert m["saved"] == s["saved"]


# ---------- Supervisor가 하위 에이전트를 순서대로 부른다 ----------
def test_supervisor_calls_retriever_writer_verifier_in_order():
    llm = normal_llm(grounding=j(grounded=True))
    out = run(build_multi_graph(fake_search, llm=llm, grounding_llm=True))
    assert out["kind"] == "answer"
    assert out["agent_trace"] == ["retriever", "writer", "verifier"]
    assert [(e["after"], e["to"]) for e in out["supervisor_log"]] == [("intake", "retriever"), ("retriever", "writer"), ("writer", "verifier"), ("verifier", "end")]
    # LLM 호출 순서가 에이전트 순서를 따른다: Supervisor(classify) -> retriever(rewrite, judge) -> writer(answer) -> verifier(grounding)
    assert [t for t, _ in llm.calls] == ["classify", "rewrite", "judge", "answer", "grounding"]
    assert [h["agent"] for h in out["handoffs"]] == ["retriever", "writer", "verifier"]


def test_each_agent_receives_only_its_own_fields():
    out = run(build_multi_graph(fake_search, llm=normal_llm()))
    got = {h["agent"]: set(h["received"]) for h in out["handoffs"]}
    ret = {h["agent"]: set(h["returned"]) for h in out["handoffs"]}
    for name, spec in AGENTS.items():
        assert got[name] <= spec.reads and ret[name] <= spec.writes
    assert "answer" not in got["retriever"] and "profile" not in got["writer"] and "route" not in got["verifier"]
    assert "raw_citations" not in got["retriever"] and "judge_reason" not in got["writer"] and "search_cache" not in got["verifier"]
    assert "chunks" in got["writer"] and "answer" in got["verifier"] and "citations" in ret["verifier"]
    # 에이전트가 쓰는 칸은 서로 겹치지 않는 몫이 있고, 최종 결과는 supervisor 상태에서 읽는다
    assert RETRIEVER.writes & {"raw_citations", "drafted"} == set() and WRITER.writes & {"chunks", "kind"} == set()


def test_agents_use_the_single_graph_nodes_not_copies():
    single = build_graph(fake_search, llm=normal_llm())
    parts = SingleParts(single)
    assert {n for a in AGENTS.values() for n in a.nodes} <= set(single.nodes)
    # 하위 에이전트 안의 노드는 단일 그래프의 노드 실행체와 같은 객체다
    agents = build_agents(parts)
    for name, spec in AGENTS.items():
        for n in spec.nodes:
            assert agents[name].builder.nodes[n].runnable is parts.node(n)


def test_parts_fail_loudly_when_graph_internals_change():
    class Fake:
        builder = object()

    with pytest.raises(RuntimeError):
        SingleParts(Fake())
    with pytest.raises(KeyError):
        SingleParts(build_graph(fake_search, llm=normal_llm())).node("nonexistent")


# ---------- 거절 경로 ----------
def test_out_of_domain_closes_in_supervisor_without_calling_any_agent():
    fn, calls = recorded()
    llm = normal_llm(classify=j(route="out_of_domain"))
    out = run(build_multi_graph(fn, llm=llm), question="사내 연봉 협상은 어떻게 하나요?")
    assert out["kind"] == "refuse" and out["citations"] == [] and calls == []
    assert out["agent_trace"] == [] and out["supervisor_log"][0]["closed_by"] == "out_of_domain"
    assert llm.count("classify") == 2 and llm.count("rewrite") == 0  # 단일과 같다: 두 번 모두 도메인 밖일 때만 따른다


def test_refuse_after_two_researches_calls_retriever_three_times_then_closes():
    fn, calls = recorded()
    llm = _insufficient()
    out = run(build_multi_graph(fn, llm=llm))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and out["citations"] == []
    assert len(calls) == 3  # 리터럴: 첫 검색 1 + 재검색 2 (AC-03)
    assert out["agent_trace"] == ["retriever"] * 3 and MAX_RESEARCH == 2
    assert llm.count("judge") == 3 and llm.count("answer") == 0 and llm.count("classify") == 1
    assert out["supervisor_log"][-1]["closed_by"] == "give_up" and out["retries"] == 3


def test_requery_path_goes_back_to_retriever_then_on_to_writer_and_verifier():
    fn, calls = recorded()
    llm = normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)], rewrite=rewrites())
    out = run(build_multi_graph(fn, llm=llm))
    assert out["kind"] == "answer" and len(calls) == 2
    assert out["agent_trace"] == ["retriever", "retriever", "writer", "verifier"]
    assert [e["to"] for e in out["supervisor_log"]] == ["retriever", "retriever", "writer", "verifier", "end"]
    assert out["retries"] == 1 and out["search_stats"] == {"calls": 2, "cache_hits": 0}


def test_requery_with_same_query_uses_the_search_memo_like_single():
    fn, calls = recorded()
    llm = normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)])
    out = run(build_multi_graph(fn, llm=llm))
    assert out["kind"] == "answer" and len(calls) == 1 and out["search_stats"] == {"calls": 1, "cache_hits": 1}


def test_clarify_ends_in_supervisor_after_retries():
    out = run(build_multi_graph(fake_search, llm=normal_llm(judge=j(sufficient=False, reason="절 불명", clarify="어느 절 기준인가요?"))))
    assert out["kind"] == "clarify" and out["answer"] == "어느 절 기준인가요?" and out["agent_trace"] == ["retriever"] * 3


def test_verifier_refusal_after_draft_ends_without_save():
    st = InMemoryAnswerStore()
    out = run(build_multi_graph(fake_search, llm=normal_llm(), answer_store=st), question="SEV9 장애 최초 대응은 몇 분 이내인가요?")
    assert out["kind"] == "refuse" and out["refuse_reason"] == "nonexistent_entity" and out["drafted"] is True
    assert out["agent_trace"] == ["retriever", "writer", "verifier"] and st.all_answers() == [] and not out.get("answer_id")


def test_search_failures_end_at_the_retriever_with_fixed_messages():
    out = run(build_multi_graph(_unavailable, llm=_insufficient()))
    assert out["answer"] == MSG_REFUSE_SEARCH_DOWN and out["search_error"] == "unavailable" and out["agent_trace"] == ["retriever"]
    llm = _insufficient()
    out = run(build_multi_graph(_no_key, llm=llm))
    assert out["answer"] == MSG_REFUSE_NO_KEY and out["search_error"] == "no_key" and out["agent_trace"] == ["retriever"] and llm.count("judge") == 0


def test_answer_is_saved_once_by_the_verifier():
    st = InMemoryAnswerStore()
    out = run(build_multi_graph(fake_search, llm=normal_llm(), answer_store=st))
    assert out["answer_id"] and len(st.all_answers()) == 1


# ---------- 어댑터와 평가 실행기가 단일처럼 읽는다 ----------
def test_stream_events_work_on_the_multi_graph():
    g = build_multi_graph(fake_search, llm=normal_llm(), answer_store=InMemoryAnswerStore())
    ev = list(stream_events(g, {"question": Q, "user_id": "u1", "thread_id": "t9", "as_of": "2025-06-01"}, thread_id="t9"))
    types = [e.type for e in ev]
    assert types[0] == "token" and types[-1] == "done" and types.count("citation") == 1 and ev[-1].data["answer_id"]


def test_checkpointer_keeps_thread_state():
    from langgraph.checkpoint.memory import InMemorySaver

    g = build_multi_graph(fake_search, llm=normal_llm(), checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "tk"}}
    g.invoke({"question": Q, "user_id": "u1", "thread_id": "tk", "as_of": "2025-06-01"}, cfg)
    assert g.get_state(cfg).values["kind"] == "answer"


def test_eval_runner_reads_multi_output_like_single():
    from evals.agent.run_eval import run_item
    from evals.retrieval.gold import GoldRef

    item = {"id": 1, "kind": "relevant", "input": Q, "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=90002, label="런북")]}
    rows = {}
    for label, build in (("single", build_graph), ("multi", build_multi_graph)):
        rows[label] = run_item(build(fake_search, llm=normal_llm(), grounding_llm=False), item, run_id="t")
    for r in rows.values():
        r.pop("latency_s"), r.pop("cost_usd", None)
    assert rows["multi"] == rows["single"] and rows["multi"]["answered"] and rows["multi"]["gold_hit"] == 1


def test_callbacks_reach_nodes_inside_sub_agents():
    """평가 실행기의 비용 집계(CostTracker)와 Langfuse는 config의 콜백으로 붙는다. 하위 에이전트 안의 LLM 호출도 같은 콜백에 잡혀야 한다."""

    class Count(BaseCallbackHandler):
        def __init__(self):
            self.n = 0

        def on_chain_start(self, serialized, inputs, **kw):
            if kw.get("name") == "fake_llm":
                self.n += 1

    counts = {}
    for label, build in (("single", build_graph), ("multi", build_multi_graph)):
        scripted = normal_llm()
        wrapped = RunnableLambda(lambda msgs, _s=scripted: _s.invoke(msgs), name="fake_llm")
        cb = Count()
        out = build(fake_search, llm=wrapped).invoke({"question": Q, "user_id": "u", "thread_id": "t", "as_of": "2025-06-01"}, {"callbacks": [cb]})
        assert out["kind"] == "answer"
        counts[label] = (cb.n, len(scripted.calls))
    assert counts["multi"] == counts["single"] and counts["multi"][0] == counts["multi"][1] > 0


def test_module_constants_are_consistent():
    assert multi.AGENTS == {"retriever": RETRIEVER, "writer": WRITER, "verifier": VERIFIER}
    assert RETRIEVER.fields | WRITER.fields | VERIFIER.fields <= set(multi.AgentState.__annotations__)


# ---------- 일부 근거 경로와 답 다시 쓰기도 단일과 같다 ----------
def test_partial_route_runs_the_same_in_multi():
    from backend.graph.build import MSG_PARTIAL_NOTE

    two = j(split=True, sub_questions=["SEV2 최초 대응 기한은 얼마인가요?", "SEV2 장애 사후 분석 담당은 누구인가요?"])
    verdict = j(sufficient=False, partial=True, reason="사후 분석 담당이 자료에 없다", clarify=None)
    outs = []
    for make in (build_graph, build_multi_graph):
        llm = normal_llm(decompose=two, judge=verdict, rewrite=rewrites(), grounding=j(grounded=True))
        outs.append((run(make(fake_search, llm=llm, decompose=True, grounding_llm=True)), [t for t, _ in llm.calls]))
    (single, calls_single), (many, calls_multi) = outs
    assert many["kind"] == single["kind"] == "answer" and many["answer"] == single["answer"] and MSG_PARTIAL_NOTE in many["answer"]
    assert calls_multi == calls_single and many["agent_trace"] == ["retriever"] * 3 + ["writer", "verifier"]


def test_rewrite_after_refused_answer_runs_the_same_in_multi():
    def answer(user):
        cid = first_chunk_id(user)
        return j(answer=f"다시 쓴 답이다 [{cid}]." if "<<<이전 답>>>" in user else f"처음 쓴 답이다 [{cid}].", citations=[{"chunk_id": cid}])

    def grounding(user):
        return j(grounded=True) if "다시 쓴 답" in user else j(grounded=False, reason_code="unsupported", reason="근거 없음", unsupported_sentences=["처음 쓴 답이다"])

    outs = []
    for make in (build_graph, build_multi_graph):
        llm = normal_llm(answer=answer, grounding=grounding)
        outs.append((run(make(fake_search, llm=llm, grounding_llm=True)), [t for t, _ in llm.calls]))
    (single, calls_single), (many, calls_multi) = outs
    assert many["kind"] == single["kind"] == "answer" and "다시 쓴 답" in many["answer"] and many["answer"] == single["answer"]
    assert calls_multi == calls_single and many["grounding"]["redrafted"] is True
