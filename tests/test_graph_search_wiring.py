"""그래프가 검색에 넘기는 값 시험 (docs/specs/question-graph.md 4단계). 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

검색마다 k는 상수 5(`DEFAULT_K`), 질문 분해(LLM)는 그래프의 첫 검색 전에 한 번, 재검색은 재작성 검색어로 분해 없이.
"""
from __future__ import annotations

import pytest
from fake_search import fake_search
from qgraph_fakes import first_chunk_id, j, normal_llm

from backend.graph import decompose as dec
from backend.graph.build import (
    MAX_RESEARCH,
    MSG_REFUSE,
    MSG_REFUSE_NO_KEY,
    MSG_REFUSE_SEARCH_DOWN,
    SEARCH_K,
    build_graph,
)
from backend.rag.retrieve.embed import EmbedUnavailable
from backend.schemas import SearchQuery
from backend.schemas.chunk import DEFAULT_K

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요? 그리고 누가 호출하나요?"
GOOD = j(split=True, sub_questions=["SEV2 장애 최초 대응은 몇 분 이내인가요?", "SEV2 장애는 누가 호출하나요?"])
NOT_SPLIT = j(split=False, sub_questions=[])


def recording_search():
    calls: list[SearchQuery] = []

    def fn(q):
        calls.append(q)
        return fake_search(q)

    return fn, calls


def run(g, **kw):
    base = {"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"}
    base.update(kw)
    return g.invoke(base)


def insufficient_llm(**kw):
    n = iter(range(100))
    return normal_llm(judge=j(sufficient=False, reason="부족", clarify=None),
                      rewrite=lambda u: j(query=f"SEV2 최초 대응 {next(n)}", org="TEST-security", as_of=None), **kw)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("SEARCH_DECOMPOSE", raising=False)


# ---------- k는 상수 5 ----------
def test_k_is_five_for_every_search():
    assert SEARCH_K == DEFAULT_K == 5 and SearchQuery(query="x").k == 5
    fn, calls = recording_search()
    run(build_graph(fn, llm=insufficient_llm()))
    assert len(calls) == 3 and all(c.k == 5 for c in calls)


# ---------- 분해는 그래프 단계, 한국어 원 질문 ----------
def test_first_search_carries_original_question_and_sub_queries_and_research_does_not():
    fn, calls = recording_search()
    llm = insufficient_llm(decompose=GOOD)
    run(build_graph(fn, llm=llm, decompose=True))
    assert len(calls) == 1 + MAX_RESEARCH == 3
    assert llm.count("decompose") == 1
    assert calls[0].query == Q and calls[0].sub_queries == ["SEV2 장애 최초 대응은 몇 분 이내인가요?", "SEV2 장애는 누가 호출하나요?"]
    assert [c.sub_queries for c in calls[1:]] == [None, None]                       # 재검색은 분해 없이
    assert [c.query for c in calls[1:]] == ["SEV2 최초 대응 1", "SEV2 최초 대응 2"]  # 재작성 검색어(영어)로
    assert next(u for t, u in llm.calls if t == "decompose") == Q                   # 분해 입력은 한국어 원 질문 그대로


def test_decompose_state_is_recorded():
    fn, _ = recording_search()
    out = run(build_graph(fn, llm=normal_llm(decompose=GOOD), decompose=True))
    assert out["sub_queries"] == ["SEV2 장애 최초 대응은 몇 분 이내인가요?", "SEV2 장애는 누가 호출하나요?"] and out["decompose_source"] == "llm"


@pytest.mark.parametrize("raw", [NOT_SPLIT, j(split=True, sub_questions=["하나뿐"]), j(split=False, sub_questions=["a b c", "d e f"]),
                                 j(split=True, sub_questions=[Q, "다른 질문"]), j(split=True, sub_questions=["가" * 1001, "나"])])
def test_not_split_or_out_of_rule_sends_no_sub_queries(raw):
    fn, calls = recording_search()
    run(build_graph(fn, llm=normal_llm(decompose=raw), decompose=True))
    assert calls[0].sub_queries is None and calls[0].query == Q and calls[0].k == 5


def test_four_sub_questions_are_cut_to_three():
    four = j(split=True, sub_questions=["첫째 질문", "둘째 질문", "셋째 질문", "넷째 질문"])
    fn, calls = recording_search()
    run(build_graph(fn, llm=normal_llm(decompose=four), decompose=True))
    assert calls[0].sub_queries == ["첫째 질문", "둘째 질문", "셋째 질문"]


@pytest.mark.parametrize("bad", ["not json", "", "{", j(split="yes", sub_questions=[]), j(split=True, sub_questions=["가", ""]), "[1, 2]"])
def test_broken_decomposition_falls_back_to_one_query_without_stopping(bad):
    fn, calls = recording_search()
    llm = normal_llm(decompose=bad)
    out = run(build_graph(fn, llm=llm, decompose=True))
    assert calls[0].sub_queries is None and len(calls) == 1 and out["kind"] == "answer"
    assert out["decompose_source"] == "invalid" and llm.count("decompose") == dec.ATTEMPTS == 2


def test_decompose_asks_once_more_when_the_first_answer_is_broken():
    fn, calls = recording_search()
    llm = normal_llm(decompose=["garbage", GOOD])
    run(build_graph(fn, llm=llm, decompose=True))
    assert llm.count("decompose") == 2 and calls[0].sub_queries and len(calls[0].sub_queries) == 2


def test_decompose_llm_failure_does_not_stop_the_answer():
    class Boom:
        def __init__(self, inner):
            self.inner = inner

        def invoke(self, messages, *a, **k):
            if "[[task:decompose]]" in messages[0].content:
                raise RuntimeError("down")
            return self.inner.invoke(messages, *a, **k)

    fn, calls = recording_search()
    out = run(build_graph(fn, llm=Boom(normal_llm()), decompose=True))
    assert calls[0].sub_queries is None and out["kind"] == "answer" and out["decompose_source"] == "error"


def test_cost_cap_is_not_swallowed_by_decompose():
    from backend.services.llm import CostCapExceeded

    def ask(system, user):
        raise CostCapExceeded(1.0, 0.5)

    with pytest.raises(CostCapExceeded):
        dec.decompose_question(ask, Q)


def test_off_by_default_and_the_search_gets_the_rewritten_query_as_before():
    fn, calls = recording_search()
    llm = normal_llm(decompose=GOOD)
    out = run(build_graph(fn, llm=llm))
    assert llm.count("decompose") == 0 and calls[0].sub_queries is None and calls[0].query == "SEV2 최초 대응" and out["sub_queries"] == []


@pytest.mark.parametrize("env,want", [({}, False), ({"SEARCH_DECOMPOSE": "1"}, True), ({"SEARCH_DECOMPOSE": "0"}, False), ({"SEARCH_DECOMPOSE": ""}, False)])
def test_env_switch_and_explicit_argument(monkeypatch, env, want):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert dec.decompose_enabled() is want
    fn, _ = recording_search()
    llm = normal_llm(decompose=GOOD)
    run(build_graph(fn, llm=llm))
    assert (llm.count("decompose") == 1) is want
    llm = normal_llm(decompose=GOOD)
    run(build_graph(fn, llm=llm, decompose=False))
    assert llm.count("decompose") == 0


# ---------- 검색 캐시 열쇠에 하위 질문 ----------
def test_cache_key_includes_sub_queries():
    """같은 검색어라도 하위 질문이 있는 첫 검색과 없는 재검색은 다른 검색이다. 하위 질문이 없는 같은 검색은 기억에서 쓴다."""
    fn, calls = recording_search()
    llm = normal_llm(decompose=GOOD, judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)],
                     rewrite=j(query=Q, org="TEST-security", as_of=None))  # 재작성 결과가 원 질문과 같은 글자
    out = run(build_graph(fn, llm=llm, decompose=True))
    assert len(calls) == 2 and calls[0].sub_queries and calls[1].sub_queries is None and out["search_stats"]["calls"] == 2
    fn, calls = recording_search()
    llm = normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)], rewrite=j(query=Q, org="TEST-security", as_of=None))
    run(build_graph(fn, llm=llm))
    assert len(calls) == 1  # 하위 질문이 없으면 같은 검색은 한 번만


# ---------- 임베딩 API 오류와 키 없음 ----------
def test_embed_unavailable_ends_with_a_fixed_refusal_not_an_exception():
    def down(q):
        raise EmbedUnavailable("Voyage API 503")

    llm = normal_llm(decompose=GOOD)
    out = run(build_graph(down, llm=llm, decompose=True))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE_SEARCH_DOWN and out["search_error"] == "unavailable"
    assert out["citations"] == [] and llm.count("judge") == 0 and llm.count("answer") == 0 and not out.get("refuse_reason")


def test_embed_unavailable_on_a_research_ends_the_same_way():
    n = iter(range(3))

    def flaky(q):
        if next(n) == 0:
            return fake_search(q)[:1]
        raise EmbedUnavailable("timeout")

    out = run(build_graph(flaky, llm=insufficient_llm()))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE_SEARCH_DOWN and out["search_error"] == "unavailable"


def test_no_key_search_result_ends_at_once_with_a_fixed_refusal():
    from backend.rag.retrieve.search import SearchTrace, _last

    calls = []

    def no_key(q):
        calls.append(q)
        _last.set(SearchTrace("voyage-4", "none", "dense_en", fallback_reason="no_key"))
        return []

    llm = insufficient_llm()
    out = run(build_graph(no_key, llm=llm))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE_NO_KEY and out["search_error"] == "no_key"
    assert len(calls) == 1 and llm.count("judge") == 0  # 같은 검색을 되풀이하지 않는다


def test_stale_no_key_trace_does_not_leak_into_the_next_search():
    from backend.rag.retrieve.search import SearchTrace, _last

    _last.set(SearchTrace("voyage-4", "none", "dense_en", fallback_reason="no_key"))
    out = run(build_graph(lambda q: [], llm=normal_llm()))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and not out["search_error"]  # 빈 결과는 보통 경로(근거 없음)로 거절한다


def test_empty_result_without_trace_is_refused_by_the_normal_path():
    llm = insufficient_llm()
    out = run(build_graph(lambda q: [], llm=llm))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and not out["search_error"]


# ---------- 평가 코드와 같은 규칙 ----------
def test_system_prompt_and_parsing_match_the_measurement_code():
    D = pytest.importorskip("evals.retrieval.exp_decompose_v1")
    assert dec.SYSTEM == D.SYSTEM
    cases = ['{"split": true, "sub_questions": ["a?", "b?"]}', '```json\n{"split": false, "sub_questions": []}\n```', "no json",
             '{"split": "yes", "sub_questions": []}', '{"split": true, "sub_questions": ["a", ""]}', '{"split": true, "sub_questions": "x"}']
    for text in cases:
        assert dec.parse_split(text) == D.parse_split(text)
    for q, obj, want in [("가나다", {"split": True, "sub_questions": ["가", "나"]}, ["가", "나"]), ("가나다", {"split": True, "sub_questions": ["가나다", "나"]}, []),
                         ("q", {"split": False, "sub_questions": ["a", "b"]}, []), ("q", {"split": True, "sub_questions": ["a"]}, [])]:
        assert dec.normalize(q, obj) == want
        subs = [s.strip() for s in obj["sub_questions"]][:3]  # 측정 코드의 정리 규칙(prep)과 같은 결과(2개 이상일 때)
        measured = subs if bool(obj["split"]) and len(subs) >= 2 and all(s != q for s in subs) else []
        assert dec.normalize(q, obj) == measured


def test_tagged_prompt_keeps_the_rule_text():
    assert dec.SYSTEM_TAGGED.startswith("[[task:decompose]]\n") and dec.SYSTEM_TAGGED.endswith(dec.SYSTEM)


def test_answer_step_still_works_with_sub_queries_and_default_retriever_gets_the_same_query(monkeypatch):
    seen = []
    import sys

    search_mod = sys.modules["backend.rag.retrieve.search"]  # 패키지의 `search` 이름이 함수라서 모듈은 이렇게 얻는다

    monkeypatch.setattr(search_mod, "_searcher", type("S", (), {"search": lambda self, q: (seen.append(q), fake_search(q))[1]})())
    out = run(build_graph(llm=normal_llm(decompose=GOOD, answer=lambda u: j(answer=f"답 [{first_chunk_id(u)}]", citations=[{"chunk_id": first_chunk_id(u)}])), decompose=True))
    assert seen and seen[0].sub_queries and seen[0].k == 5 and out["kind"] in ("answer", "refuse")
