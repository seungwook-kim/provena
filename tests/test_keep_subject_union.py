"""대상 구를 붙인 하위 질문과 원 하위 질문 검색 합치기(`GRAPH_KEEP_SUBJECT_UNION`). 가짜 LLM, 가짜 검색기, 메모리 저장소만 쓴다(키와 네트워크 없음, 0원).
예시 질문은 핸드북·평가셋과 무관한 일반 문장이다.

(1) 스위치를 비우면 분해 결과, 검색 입력, 모델 입력이 지금과 같다. (2) 켜면 대상 구를 붙인 하위 질문 자리의 후보 목록이 두 문장의 목록을 번갈아 합친 것이고
자리 수 k는 그대로, 순서는 늘 같다. (3) 대상 구를 붙이지 않았으면 켜도 검색 입력이 같다.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from fake_search import fake_search
from qgraph_fakes import j, normal_llm
from test_search_v2 import ids, row

from backend.graph import decompose as D
from backend.graph import service_profile as SP
from backend.graph.build import build_graph
from backend.rag import sub_alts
from backend.rag.retrieve import translate
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, last_search_trace
from backend.schemas.chunk import SearchQuery

UNION = "GRAPH_KEEP_SUBJECT_UNION"
KEEP = "GRAPH_DECOMPOSE_KEEP_SUBJECT"
Q = "해외 주문의 배송은 며칠 걸리고 반품 수수료는 얼마야?"
SUBS_DROPPED = ["배송은 며칠 걸려?", "반품 수수료는 얼마야?"]
SUBS_KEPT = [f"해외 주문의 {s}" for s in SUBS_DROPPED]


def fake_ask(subs, seen):
    def ask(system, user):
        seen.append((system, user))
        return json.dumps({"split": True, "sub_questions": subs}, ensure_ascii=False)
    return ask


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (UNION, KEEP, "SEARCH_DECOMPOSE", "SEARCH_SUB_MERGE", "SEARCH_PARALLEL_SUBS", "SEARCH_FULL_TAIL", "GRAPH_QUERY_BRANCHES"):
        monkeypatch.delenv(name, raising=False)


# ---------- 분해: 원 하위 질문 ----------
def test_switch_reader_is_off_unless_one():
    assert D.keep_subject_union_enabled() is False
    for v in ("0", "off", "true", ""):
        with pytest.MonkeyPatch.context() as m:
            m.setenv(UNION, v)
            assert D.keep_subject_union_enabled() is False
    with pytest.MonkeyPatch.context() as m:
        m.setenv(UNION, "1")
        assert D.keep_subject_union_enabled() is True


def test_detail_gives_the_subs_before_the_subject_was_added(monkeypatch):
    monkeypatch.setenv(KEEP, "1")
    seen: list = []
    subs, source, alts = D.decompose_detail(fake_ask(SUBS_DROPPED, seen), Q)
    assert (subs, source) == (SUBS_KEPT, "llm") and alts == SUBS_DROPPED
    seen2: list = []
    assert D.decompose_question(fake_ask(SUBS_DROPPED, seen2), Q) == (subs, source)   # 같은 하위 질문, 같은 분해 입력
    assert seen == seen2 and len(seen) == 1


def test_detail_has_no_alts_when_the_subject_was_not_added(monkeypatch):
    monkeypatch.setenv(KEEP, "1")
    assert D.decompose_detail(fake_ask(SUBS_KEPT, []), Q) == (SUBS_KEPT, "llm", None)   # 이미 대상이 있다
    monkeypatch.delenv(KEEP)
    assert D.decompose_detail(fake_ask(SUBS_DROPPED, []), Q) == (SUBS_DROPPED, "llm", None)   # 대상 유지가 꺼져 있다
    assert D.decompose_detail(fake_ask([], []), Q) == ([], "llm", None)


def test_alts_carry_the_same_premise_and_mark_untouched_slots_empty():
    base = ["배송은 며칠 걸려?", "해외 주문 반품 수수료는 얼마야?"]
    kept = ["해외 주문 배송은 며칠 걸려?", base[1]]
    final = [f"주문을 넣으려고 합니다. {s}" for s in kept]
    assert D.subject_alts(base, kept, final) == ["주문을 넣으려고 합니다. 배송은 며칠 걸려?", ""]
    assert D.subject_alts(base, base, base) is None
    assert D.subject_alts([], [], []) is None


# ---------- 검색: 같은 자리 수로 번갈아 합치기 ----------
# 벡터 칸: 0 = 전체 질문, 1 = 대상 구를 붙인 하위 질문 1, 2 = 하위 질문 2, 3 = 원 하위 질문 1
QE, S1X, S1, S2 = "overseas order shipping and return fee", "overseas order shipping days", "shipping days", "return fee"
QV = {QE: [1, 0, 0, 0], S1X: [0, 1, 0, 0], S2: [0, 0, 1, 0], S1: [0, 0, 0, 1]}
ROWS = [row(f"a{i}", [0, 1 - 0.1 * i, 0, 0], page=i) for i in range(1, 7)] + \
       [row(f"c{i}", [0, 0, 1 - 0.01 * i, 0], page=10 + i) for i in range(1, 7)] + \
       [row(f"d{i}", [0, 0, 0, 1 - 0.1 * i], page=20 + i) for i in range(1, 7)] + \
       [row(f"z{i}", [1 - 0.1 * i, 0, 0, 0], page=30 + i) for i in range(1, 4)]


def make(calls=None, translator=None, **cfg):
    def embedder(texts):
        if calls is not None:
            calls.append(list(texts))
        return np.asarray([QV.get(t, [0.1, 0.1, 0.1, 0.1]) for t in texts], dtype=np.float32)
    store = MemoryStore(ROWS, np.asarray([r["_v"] for r in ROWS], dtype=np.float32), "voyage-4")
    c = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", **{"link_n": 0, **cfg})
    return Searcher(c, store, embedder=embedder, reranker=None, check_meta=False,
                    translator=translator or (lambda q, kind: pytest.fail("영어 질문은 번역기를 부르지 않는다")))


def run_search(q, alts=None, **cfg):
    """검색 결과, 임베딩 요청(묶음마다 문장 목록), 벡터 질의 수. alts가 있으면 원 하위 질문 힌트(`sub_alts.given`) 안에서 찾는다."""
    emb: list = []
    s = make(emb, **cfg)
    vq: list = []
    real = s.store.vector_top
    s.store.vector_top = lambda *a, **k: (vq.append(1), real(*a, **k))[1]
    if alts is None:
        return ids(s.search(q)), emb, len(vq)
    with sub_alts.given(q.sub_queries, alts):
        return ids(s.search(q)), emb, len(vq)


SPLIT = SearchQuery(query=QE, sub_queries=[S1X, S2])


def test_without_alts_the_search_is_unchanged():
    got, emb, n = run_search(SPLIT)
    assert got == ["a1", "c1", "a2", "c2", "a3"] and emb == [[QE, S1X, S2]] and n == 2
    assert run_search(SPLIT, ["", ""]) == (got, emb, n)        # 빈 자리는 없는 것
    assert run_search(SPLIT, [S1X, ""]) == (got, emb, n)       # 같은 문장도 없는 것
    with sub_alts.given([S1, S2], [S1X, ""]):                  # 하위 질문이 다른 검색에는 힌트를 쓰지 않는다
        assert run_search(SPLIT) == (got, emb, n)


def test_alts_merge_both_lists_into_the_same_number_of_slots():
    base, _, _ = run_search(SPLIT)
    got, emb, n = run_search(SPLIT, [S1, ""])
    # 하위 질문 1 자리 = a(붙인 문장)·d(원 문장)를 번갈아 합친 a1, d1, a2, d2, a3. 그 목록과 하위 질문 2 목록을 번갈아 5자리
    assert got == ["a1", "c1", "d1", "c2", "a2"]
    assert len(got) == len(base) == 5 and {"a1", "d1"} <= set(got)
    assert emb == [[QE, S1X, S2, S1]] and n == 3                   # 임베딩 요청은 1번(문장 1개 더), 벡터 질의 1번 더
    assert all(run_search(SPLIT, [S1, ""])[0] == got for _ in range(3))   # 순서가 늘 같다


def test_alts_keep_the_widened_first_search_cap_and_the_full_question_tail():
    wide = SearchQuery(query=QE, sub_queries=[S1X, S2], k=8)
    base, _, n0 = run_search(wide)
    got, _, n = run_search(wide, [S1, ""])
    assert len(base) == len(got) == 8 and base[-1] == got[-1] == "z1"   # 끝 1자리는 원 질문 목록 그대로
    assert "d1" in got and n == n0 + 1


def test_parallel_subs_give_the_same_order(monkeypatch):
    want, _, _ = run_search(SPLIT, [S1, ""])
    monkeypatch.setenv("SEARCH_PARALLEL_SUBS", "1")
    assert run_search(SPLIT, [S1, ""])[0] == want


def test_score_merge_mode_uses_the_merged_lists(monkeypatch):
    monkeypatch.setenv("SEARCH_SUB_MERGE", "1")
    got, _, n = run_search(SPLIT, [S1, ""])
    assert len(got) == 5 and n == 4                                # 전체 질문 + 하위 질문 2 + 원 하위 질문 1


KO = {"전체": QE, "붙인 1": S1X, "하위 2": S2, "원 1": S1}
KO_SPLIT = SearchQuery(query="전체", sub_queries=["붙인 1", "하위 2"])


def test_translation_failure_of_an_alt_drops_only_that_alt():
    def tr_ok(qtext, kind):
        return translate.Result(KO[qtext], "llm")

    def tr_fail_alt(qtext, kind):
        return translate.Result(None, "invalid") if qtext == "원 1" else translate.Result(KO[qtext], "llm")

    base = make(translator=tr_ok).search(KO_SPLIT)
    with sub_alts.given(KO_SPLIT.sub_queries, ["원 1", ""]):
        got = make(translator=tr_fail_alt).search(KO_SPLIT)
        tr = last_search_trace()
        with_alt = make(translator=tr_ok).search(KO_SPLIT)
    assert ids(got) == ids(base) and tr.mode == "dense_en" and tr.fallback is None and tr.fallback_reason is None
    assert "d1" in ids(with_alt)


def test_missing_alt_vector_in_a_keyless_demo_falls_back_to_the_main_texts():
    from backend.rag.retrieve.embed import EmbedNoKey

    s = make()
    real = s.embed
    seen: list = []

    def embed(texts):          # 키 없는 데모: 녹화에 없는 문장(원 하위 질문)이 묶음에 있으면 벡터를 못 만든다
        seen.append(list(texts))
        if S1 in texts:
            raise EmbedNoKey("녹화 없음")
        return real(texts)

    s.embed = embed
    with sub_alts.given(SPLIT.sub_queries, [S1, ""]):
        got = s.search(SPLIT)
    assert ids(got) == ["a1", "c1", "a2", "c2", "a3"] and seen == [[QE, S1X, S2, S1], [QE, S1X, S2]]
    assert last_search_trace().fallback_reason is None


def test_hint_refuses_misaligned_alts_and_leaves_the_contract_alone():
    with pytest.raises(ValueError):
        with sub_alts.given(["a", "b"], ["x"]):
            pass
    with pytest.raises(ValueError):
        with sub_alts.given([], ["x"]):
            pass
    assert sub_alts.current(["a", "b"]) is None
    with sub_alts.given(["a", "b"], ["x", ""]):
        assert sub_alts.current(["a", "b"]) == ["x", ""] and sub_alts.current(["a", "c"]) is None
    assert sub_alts.current(["a", "b"]) is None
    assert list(SearchQuery.model_fields) == ["query", "org", "as_of", "k", "sub_queries"]   # SDD 6장 계약은 그대로


# ---------- 그래프: 검색 입력과 모델 입력 ----------
def graph_run(monkeypatch, union: str | None, subs=SUBS_DROPPED):
    """그래프를 가짜 모델·가짜 검색으로 돌린다. 검색마다 (SearchQuery, 그때의 원 하위 질문 힌트)를 모은다."""
    if union is None:
        monkeypatch.delenv(UNION, raising=False)
    else:
        monkeypatch.setenv(UNION, union)
    calls: list[tuple[dict, list[str] | None]] = []

    def fn(q):
        calls.append((q.model_dump(), sub_alts.current(q.sub_queries)))
        return fake_search(q)

    llm = normal_llm(decompose=j(split=True, sub_questions=subs))
    out = build_graph(fn, llm=llm, decompose=True).invoke({"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    return out, calls, llm.calls


def test_graph_unset_or_zero_keeps_search_input_and_model_input(monkeypatch):
    monkeypatch.setenv(KEEP, "1")
    out0, calls0, llm0 = graph_run(monkeypatch, None)
    assert calls0[0][0]["sub_queries"] == SUBS_KEPT and all(h is None for _, h in calls0)
    out1, calls1, llm1 = graph_run(monkeypatch, "0")
    assert calls1 == calls0 and llm1 == llm0
    assert out1["sub_queries"] == out0["sub_queries"] == SUBS_KEPT


def test_graph_on_sends_the_original_subs_and_changes_nothing_else(monkeypatch):
    monkeypatch.setenv(KEEP, "1")
    out0, calls0, llm0 = graph_run(monkeypatch, None)
    out1, calls1, llm1 = graph_run(monkeypatch, "1")
    assert calls1[0][1] == SUBS_DROPPED                                          # 첫 검색에만 원 하위 질문 힌트
    assert all(h is None for _, h in calls1[1:])                                 # 재검색은 분해 없이
    assert [q for q, _ in calls1] == [q for q, _ in calls0]                      # SearchQuery(k, 검색어, 하위 질문)는 그대로
    assert llm1 == llm0                                                          # 가짜 검색 결과가 같으면 모델 입력(분해 포함)이 같다
    assert out1["sub_queries"] == out0["sub_queries"]


def test_graph_on_without_a_rewrite_is_the_same_as_off(monkeypatch):
    monkeypatch.setenv(KEEP, "1")
    _, calls0, llm0 = graph_run(monkeypatch, None, subs=SUBS_KEPT)
    _, calls1, llm1 = graph_run(monkeypatch, "1", subs=SUBS_KEPT)
    assert calls1 == calls0 and llm1 == llm0
    monkeypatch.delenv(KEEP)                                                     # 대상 유지가 꺼지면 붙인 문장이 없다
    _, calls2, _ = graph_run(monkeypatch, "1")
    assert all(h is None for _, h in calls2)


def test_service_profile_turns_the_union_on_and_off_turns_it_off():
    assert SP.SERVICE_ENV[UNION] == "1" and SP.SERVICE_ENV[KEEP] == "1"
    env: dict = {}
    SP.apply_service_profile(env)
    assert env[UNION] == "1"
    env2: dict = {UNION: "off"}
    SP.apply_service_profile(env2)
    assert env2[UNION] == ""


# ---------- MCP: 같은 힌트가 서버의 검색까지 ----------
def test_mcp_sends_alts_only_when_given():
    pytest.importorskip("fastmcp")
    from extras.mcp_skill.mcp_client import client as mc
    from tests.test_mcp_client import make as make_server
    from tests.test_mcp_server import FakeSearch, chunk

    q = SearchQuery(query="두 가지 질문", sub_queries=["하나 붙인", "둘"])
    assert "sub_query_alts" not in mc._args(q)                                  # 힌트가 없으면 도구 입력이 지금과 같다
    seen: list = []

    class Spy(FakeSearch):
        def __call__(self, q):
            seen.append(sub_alts.current(q.sub_queries))
            return super().__call__(q)

    fake = Spy(out=[chunk(2, "a"), chunk(1, "b")])
    mc.search_via_mcp(q, make_server(fake))
    with sub_alts.given(q.sub_queries, ["하나", ""]):
        assert mc._args(q, sub_alts.current(q.sub_queries))["sub_query_alts"] == ["하나", ""]
        mc.search_via_mcp(q, make_server(fake))
    assert seen == [None, ["하나", ""]] and fake.calls[1].sub_queries == ["하나 붙인", "둘"]
