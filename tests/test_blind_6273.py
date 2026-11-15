"""사전 등록 62.73 시험: `GRAPH_SPLIT_FULL_K`(코드 기본 꺼짐, 사전 등록 62.74로 서비스 설정에서도 뺌). 가짜 모델과 가짜 검색기, 합성 청크만 쓴다(키와 네트워크 없음).

- 켬: 분해가 하위 질문을 2개 이상 낸 첫 검색만 `k`를 `MAX_CHUNKS`(10)로 요청한다. 재검색은 `SEARCH_K`(5)이고 하위 질문을 넘기지 않는다.
- 켬: 나뉘지 않은 질문, 분해 오류, 미리 돌린 원 질문 검색(`GRAPH_SPECULATE_FIRST`, `GRAPH_SPECULATE_EARLY_SEARCH`)은 5 그대로다.
- 켬: 근거 목록은 기존 상한(`MAX_CHUNKS`) 안이고 판정 입력에도 그 수까지만 들어간다. 새 상한은 없다.
- 끔: 나뉜 질문의 첫 검색은 되살린 `SPLIT_K`(8, 사전 등록 62.38·62.74)이고 재검색은 5다.
"""
from __future__ import annotations

import re
import threading

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import Q_ESC, SUBS, cite, llm, mk, run

from backend.graph import answer_fixes as AF
from backend.graph.build import MAX_CHUNKS, SEARCH_K, SPLIT_K, build_graph
from backend.graph.multi import build_multi_graph

# 합성 청크 12개(검색기가 돌려줄 수 있는 수가 상한보다 많게)
POOL = [mk(f"If the EOC or the IMOC does not respond, synthetic escalation step {i} is handled by the on-call rotation.", title="Synthetic Handbook", seq=71000 + i, article=f"Step {i}")
        for i in range(12)]
POOL_IDS = {c.chunk_id for c in POOL}
OK = j(sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
NO = j(sufficient=False, partial=False, reason="없음", missing=["IMOC 무응답"], scope_note=None, clarify=None, query="IMOC escalation leadership")
Q_ONE = "EOC가 응답하지 않으면 어떻게 돼?"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_SPLIT_FULL_K", "GRAPH_SPECULATE_FIRST", "GRAPH_SPECULATE_EARLY_SEARCH", "GRAPH_SPECULATE_GROUND", "GRAPH_SPEC_STOP_GROUND",
                 "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_ANSWER", "GRAPH_JUDGE_VOTE", "GRAPH_NONE_VOTE_WAIT_S",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_QUOTE", "GRAPH_STOP_STALLED_SEARCH",
                 "GRAPH_DECOMPOSE_CAP_S", "GRAPH_REFUSE_ON_NONE", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "SEARCH_DECOMPOSE", "USE_SKILLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def pool_searcher():
    """질의마다 합성 청크를 요청한 수(`k`)만큼 돌려준다. 부른 질의를 기록한다(미리 돌리기는 다른 스레드에서 부른다)."""
    seen, lock = [], threading.Lock()

    def fn(q):
        with lock:
            seen.append(q)
        return POOL[: q.k]
    return fn, seen


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, **kw)


def judged_ids(m) -> list[set[str]]:
    """판정 호출마다 입력에 들어간 합성 청크 id."""
    return [set(re.findall(r"[0-9a-f]{16}", u)) & POOL_IDS for t, u in m.calls if t == "judge"]


def split_llm(**kw):
    return llm(decompose=j(split=True, sub_questions=SUBS), answer=cite(POOL[0]), **kw)


def test_switch_is_off_by_default_and_reads_one(monkeypatch):
    assert AF.split_full_k_enabled() is False
    monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
    assert AF.split_full_k_enabled() is True
    assert MAX_CHUNKS == 10 and SEARCH_K == 5   # 새 숫자가 아니라 이미 있는 두 상수를 쓴다


@pytest.mark.parametrize("multi", [False, True])
def test_on_split_first_search_asks_for_the_evidence_cap_and_research_stays_at_k5(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
    fn, seen = pool_searcher()
    m = split_llm(judge=[NO, OK])
    out = run(graph(multi, fn, m, decompose=True), Q_ESC)
    first, *rest = seen
    assert (first.k, first.sub_queries) == (MAX_CHUNKS, SUBS)
    assert rest and all(q.k == SEARCH_K and not q.sub_queries for q in rest)   # 재검색은 5, 하위 질문 없음
    assert len(out["chunks"]) == MAX_CHUNKS                                    # 재검색을 합쳐도 기존 상한 안
    assert all(len(ids) <= MAX_CHUNKS for ids in judged_ids(m)) and len(judged_ids(m)[0]) == MAX_CHUNKS


@pytest.mark.parametrize("multi", [False, True])
def test_on_split_chunks_and_judge_input_stay_within_the_cap(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
    fn, seen = pool_searcher()
    m = split_llm(judge=OK)
    out = run(graph(multi, fn, m, decompose=True), Q_ESC)
    assert len(seen) == 1 and seen[0].k == MAX_CHUNKS
    assert [c["chunk_id"] for c in out["chunks"]] == [c.chunk_id for c in POOL[:MAX_CHUNKS]]   # 검색기가 12개를 가져도 10개
    assert judged_ids(m) == [{c.chunk_id for c in POOL[:MAX_CHUNKS]}]
    assert out["kind"] == "answer"


@pytest.mark.parametrize("multi", [False, True])
def test_off_split_first_search_is_unchanged(monkeypatch, multi):
    fn, seen = pool_searcher()
    m = split_llm(judge=[NO, OK])
    out = run(graph(multi, fn, m, decompose=True), Q_ESC)
    assert seen[0].k == SPLIT_K and seen[0].sub_queries == SUBS               # 62.74: 끄면 되살린 넓힌 첫 검색(8)
    assert all(q.k == SEARCH_K for q in seen[1:])
    assert len(judged_ids(m)[0]) == SPLIT_K


@pytest.mark.parametrize("decompose_reply", [j(split=False, sub_questions=[]), "분해 응답이 아님"])
def test_on_unsplit_or_failed_decomposition_keeps_k5(monkeypatch, decompose_reply):
    """안 나눔(`split=false`)과 분해 실패(형식이 깨진 응답)는 하위 질문이 비어 첫 검색이 5 그대로다."""
    runs = {}
    for on in (False, True):
        if on:
            monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
        fn, seen = pool_searcher()
        m = llm(decompose=decompose_reply, judge=OK, answer=cite(POOL[0]))
        out = run(build_graph(fn, llm=m, decompose=True), Q_ONE)
        assert [(q.k, q.sub_queries) for q in seen] == [(SEARCH_K, None)]
        runs[on] = (out["kind"], out["answer"], [c["chunk_id"] for c in out["chunks"]])
    assert runs[True] == runs[False]


def spec_run(monkeypatch, *, split: bool, on: bool):
    """미리 돌리기(예비 분해는 안 나눔)와 일찍 시작하는 원 질문 검색을 켠 실행. 본 분해가 `split`이다."""
    for name in ("GRAPH_SPECULATE_FIRST", "GRAPH_SPECULATE_EARLY_SEARCH"):
        monkeypatch.setenv(name, "1")
    if on:
        monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
    else:
        monkeypatch.delenv("GRAPH_SPLIT_FULL_K", raising=False)
    fn, seen = pool_searcher()
    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), decompose_gate=j(split=False, sub_questions=[]),
            classify=j(route="rule"), judge=OK, answer=cite(POOL[0]))
    out = run(build_graph(fn, llm=m, decompose=True, parallel_intake=True, skip_first_rewrite=True), Q_ESC)
    return out, seen


def test_speculated_original_question_search_keeps_k5_and_split_main_search_asks_for_the_cap(monkeypatch):
    out, seen = spec_run(monkeypatch, split=True, on=True)
    assert out["search_stats"].get("speculated") == "dropped"
    main = [q for q in seen if q.sub_queries]
    early = [q for q in seen if not q.sub_queries]
    assert [(q.k, q.sub_queries) for q in main] == [(MAX_CHUNKS, SUBS)]
    assert early and all(q.k == SEARCH_K for q in early)                       # 미리 돌린 원 질문 검색은 5 그대로
    assert len(out["chunks"]) == MAX_CHUNKS                                    # 쓴 것은 본 경로(하위 질문) 결과


def test_speculation_used_for_unsplit_question_is_unchanged(monkeypatch):
    off, seen_off = spec_run(monkeypatch, split=False, on=False)
    on, seen_on = spec_run(monkeypatch, split=False, on=True)
    assert on["search_stats"].get("speculated") == off["search_stats"].get("speculated") == "used"
    assert [(q.k, q.sub_queries) for q in seen_on] == [(q.k, q.sub_queries) for q in seen_off] == [(SEARCH_K, None)]
    assert on["answer"] == off["answer"] and [c["chunk_id"] for c in on["chunks"]] == [c["chunk_id"] for c in off["chunks"]]


def test_search_memo_key_keeps_k10_and_k5_results_apart(monkeypatch):
    """같은 실행 안에서 같은 질의라도 k가 다르면 다른 검색이다(검색 기억 열쇠에 k가 있다). k=5 결과를 10개 요청에 다시 쓰지 않는다."""
    monkeypatch.setenv("GRAPH_SPLIT_FULL_K", "1")
    fn, seen = pool_searcher()
    out = run(build_graph(fn, llm=split_llm(judge=OK), decompose=True), Q_ESC)
    keys = [k for k in out["search_cache"] if isinstance(k, str) and k.startswith("[")]
    assert len(keys) == 1 and f", {MAX_CHUNKS}, " in keys[0] and out["search_stats"]["cache_hits"] == 0
