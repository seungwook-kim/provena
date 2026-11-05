"""확정 조합 측정 전용 검색기(`evals/agent/exp_confirmed_v1.py`) 시험. 가짜 벡터·행만 쓰고 모델, API, 로컬 색인을 쓰지 않는다."""
from types import SimpleNamespace

import numpy as np
import pytest

from backend.schemas.chunk import SearchQuery
from evals.agent import exp_confirmed_v1 as X
from evals.retrieval import exp_decompose_v1 as D

Q = "원 질문"
N = 8
W = np.arange(N, 0, -1, dtype=np.float32)       # 질문 벡터: 0번 청크가 가장 가깝고 7번이 가장 멀다
W_REV = np.arange(1, N + 1, dtype=np.float32)   # 재검색 벡터: 7번이 가장 가깝다


def make(*, orgs=None, valid_from=None, link_page=None, link_from=0, dec=None, sub_vec=None, embed=None, cache_path=None):
    ids = [f"c{i}" for i in range(N)]
    orgs = orgs or ["a"] * N
    valid_from = valid_from or ["2026-01-01"] * N
    rows = [{"chunk_id": ids[i], "org": orgs[i], "rule_seq": 100 + i, "rule_title": "t", "article": None, "version_id": "v",
             "version_date": "2026-01-01", "fetched_at": "2026-10-31", "kind": "article", "text": "x", "source_url": "u",
             "valid_from": valid_from[i], "valid_to": None} for i in range(N)]
    links = object.__new__(D.Links)
    links.target = [set() for _ in range(N)]
    links.page = {}
    if link_page is not None:  # link_from번 청크가 B 페이지를 링크하고, B 페이지의 청크는 link_page
        links.target[link_from] = {"B"}
        links.page = {"B": list(link_page)}
    cell = ([], [SimpleNamespace(chunk_id=i) for i in ids], np.eye(N, dtype=np.float32), {X.ev.qkey(Q): {"en": W.tolist()}})
    dec = dec if dec is not None else {"1": {"question": Q, "sub_questions": []}}
    r = X.ConfirmedRetriever(cell, rows, dec, sub_vec or {}, links=links, embed=embed, cache_path=cache_path or X.REQUERY_CACHE)
    r.set_item({"id": 1, "input": Q})
    return r


def ids_of(chunks):
    return [c.chunk_id for c in chunks]


def test_first_search_uses_original_question_and_requery_uses_rewritten_query():
    seen = []

    def embed(query):
        seen.append(query)
        return W_REV / np.linalg.norm(W_REV), 7, False

    r = make(embed=embed)
    first = r(SearchQuery(query="rewritten english query", k=8))
    assert ids_of(first) == ["c0", "c1", "c2", "c3", "c4"]     # 재작성 질의가 아니라 저장된 원 질문 벡터로 찾았다
    assert seen == []                                            # 첫 검색은 모델·API를 부르지 않는다
    again = r(SearchQuery(query="second rewrite", k=8))
    assert ids_of(again) == ["c7", "c6", "c5", "c4", "c3"]     # 재검색은 재작성 질의 벡터
    assert seen == ["second rewrite"]
    assert [(c["kind"], c["graph_query"], c["voyage_tokens"]) for c in r.calls] == [("first", "rewritten english query", 0), ("requery", "second rewrite", 7)]
    assert r.calls[0]["retrieval_query"] == Q and r.calls[1]["retrieval_query"] == "second rewrite"
    r.set_item({"id": 1, "input": Q})                            # 문항이 바뀌면 다시 첫 검색부터
    assert r.calls == [] and len(r(SearchQuery(query="x"))) == 5 and r.calls[0]["kind"] == "first"


def test_requery_does_not_decompose_but_first_search_does():
    sub = {X.ev.qkey("하위1"): np.eye(N, dtype=np.float32)[6].tolist(), X.ev.qkey("하위2"): np.eye(N, dtype=np.float32)[7].tolist()}
    dec = {"1": {"question": Q, "sub_questions": ["하위1", "하위2"]}}
    r = make(dec=dec, sub_vec=sub, embed=lambda q: (W / np.linalg.norm(W), 0, True))
    first = ids_of(r(SearchQuery(query="a")))
    assert first[:2] == ["c6", "c7"] and r.calls[0]["split"] is True    # 하위 질문별 1위를 번갈아 담는다
    again = ids_of(r(SearchQuery(query="b")))
    assert again == ["c0", "c1", "c2", "c3", "c4"] and r.calls[1]["split"] is False


@pytest.mark.parametrize("k", [1, 3, 5, 8, 20])
def test_always_returns_five_whatever_k_asks(k):
    r = make(embed=lambda q: (W_REV, 0, True))
    assert len(r(SearchQuery(query="a", k=k))) == 5
    assert len(r(SearchQuery(query="b", k=k))) == 5


def test_org_and_as_of_filter_vector_candidates():
    r = make(orgs=["b", "a", "a", "a", "a", "a", "a", "a"], valid_from=["2026-01-01"] * 4 + ["2026-11-01"] + ["2026-01-01"] * 3)
    got = ids_of(r(SearchQuery(query="a", org="a", as_of="2026-10-27")))
    assert "c0" not in got and "c4" not in got       # 다른 절, 기준일 뒤에 생긴 판은 후보에서 빠진다
    assert got == ["c1", "c2", "c3", "c5", "c6"]


def test_link_chunks_pass_the_same_filter():
    # 링크 청크 5가 다른 절이다: 링크 쪽 순서도, 링크가 모자란 자리도 필터를 지켜야 한다
    orgs = ["a"] * N
    orgs[5] = "b"
    r = make(orgs=orgs, link_page=[5, 6, 7])
    assert ids_of(r(SearchQuery(query="a", org="a"))) == ["c0", "c1", "c2", "c6", "c7"]
    r = make(orgs=orgs, link_page=[5, 6, 7])
    assert ids_of(r(SearchQuery(query="a"))) == ["c0", "c1", "c2", "c5", "c6"]   # 필터가 없으면 5가 링크로 들어온다(대조)
    r = make(orgs=orgs, link_page=[5])
    got = ids_of(r(SearchQuery(query="a", org="a")))
    assert "c5" not in got and got == ["c0", "c1", "c2", "c3", "c4"]            # 필터를 못 지나는 링크 청크는 자리만 차지하지 않는다
    # 기준일: 링크 청크 6이 기준일 뒤 판이다
    r = make(valid_from=["2026-01-01"] * 6 + ["2026-11-01", "2026-01-01"], link_page=[5, 6, 7])
    assert ids_of(r(SearchQuery(query="a", as_of="2026-10-27"))) == ["c0", "c1", "c2", "c5", "c7"]


def test_missing_stored_values_stop_instead_of_skipping():
    r = make()
    with pytest.raises(SystemExit):
        r.set_item({"id": 2, "input": Q})                                   # 저장된 분해 없음
    with pytest.raises(SystemExit):
        r.set_item({"id": 1, "input": "다른 질문"})                          # 분해의 질문과 평가셋이 다름
    r.dec["3"] = {"question": "벡터 없는 질문", "sub_questions": []}
    with pytest.raises(SystemExit):
        r.set_item({"id": 3, "input": "벡터 없는 질문"})                      # 저장된 질문 벡터 없음
    r.dec["4"] = {"question": Q, "sub_questions": ["벡터 없는 하위"]}
    with pytest.raises(SystemExit):
        r.set_item({"id": 4, "input": Q})                                   # 저장된 하위 질문 벡터 없음


def test_search_errors_are_recorded_and_not_swallowed():
    def boom(query):
        raise RuntimeError("voyage down")

    r = make(embed=boom)
    r(SearchQuery(query="a"))
    with pytest.raises(RuntimeError):
        r(SearchQuery(query="b"))
    assert r.errors == ["RuntimeError: voyage down"]


def test_requery_vector_is_cached_on_file(tmp_path, monkeypatch):
    calls = []

    def fake_voyage(texts, role, used):
        calls.append((texts, role))
        used[0] += 11
        return np.asarray([W_REV / np.linalg.norm(W_REV)], dtype=np.float32)

    monkeypatch.setattr(X.ev, "_voyage", fake_voyage)
    path = tmp_path / "requery.json"
    r = make(cache_path=path)
    r(SearchQuery(query="first"))
    r(SearchQuery(query="same english query"))
    r.set_item({"id": 1, "input": Q})
    r(SearchQuery(query="first"))
    r(SearchQuery(query="same english query"))
    assert calls == [(["same english query"], "query")]                      # 같은 질의는 다시 부르지 않는다
    assert r.calls[1]["voyage_tokens"] == 0 and r.calls[1]["vec_cached"] is True and r.voyage_tokens == 11
    r2 = make(cache_path=path)                                               # 새 검색기도 파일에서 읽는다
    r2(SearchQuery(query="first"))
    r2(SearchQuery(query="same english query"))
    assert len(calls) == 1


def test_align_rows_checks_order_and_ids():
    rows = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    assert X.align_rows(rows, ["a", "b"]) is rows
    assert [r["chunk_id"] for r in X.align_rows(rows, ["b", "a"])] == ["b", "a"]
    with pytest.raises(SystemExit):
        X.align_rows(rows, ["a", "c"])
    with pytest.raises(SystemExit):
        X.align_rows([{"chunk_id": "a"}, {"chunk_id": "a"}], ["a", "b"])


def test_fix_env_never_leaves_api_keys(monkeypatch):
    for k, v in {"LLM_API_KEY": "x", "LLM_FALLBACK_MODEL": "m", "ANTHROPIC_API_KEY": "y", "DEMO_MODE": "1", "LLM_PROVIDER": "anthropic"}.items():
        monkeypatch.setenv(k, v)
    X.fix_env()
    import os

    assert (os.environ["LLM_PROVIDER"], os.environ["LLM_MODEL"]) == ("claude_cli", "claude-haiku-5-5")
    assert not any(k in os.environ for k in ("LLM_API_KEY", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY", "DEMO_MODE"))


# ---------- 기록 칸: 근거 판정 사유를 행에 저장한다 ----------

def test_recorded_grounding_reason_is_saved_and_score_row_unchanged():
    from fake_search import fake_search
    from qgraph_fakes import j, normal_llm

    from backend.graph.build import build_graph
    from evals.agent.run_eval import _row

    llm = normal_llm(grounding=j(grounded=False, reason_code="unsupported", reason="기한이 다름"))
    g = X.RecordingGraph(build_graph(fake_search, llm=llm, grounding_llm=True))
    assert g.last is None
    out = g.invoke({"question": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "user_id": "u", "thread_id": "t", "as_of": "2025-06-01"})
    assert g.last is out                                                      # 덮개는 결과를 그대로 돌려준다
    item = {"id": 1, "kind": "relevant", "input": "q", "gold": []}
    plain = _row(item, out, 1.0)
    row = X.add_recorded(dict(plain), g.last)
    assert {k: v for k, v in row.items() if k not in X.RECORDED_FIELDS} == plain  # 점수에 쓰는 칸은 그대로
    assert row["result"] == "refuse" and row["refuse_reason"] == "unsupported"
    assert row["grounding"]["reason"] == "unsupported" and row["grounding"]["detail"] == "기한이 다름"
    assert row["judge_reason"] == "" and row["clarify_question"] is None


def test_recorded_fields_are_none_when_graph_raised():
    row = X.add_recorded({"id": 1}, None)
    assert row == {"id": 1, "grounding": None, "judge_reason": None, "clarify_question": None, "trimmed_citations": None}


# ---------- 월 단위 기준일이 측정 전용 검색기까지 가는지 (수정 4) ----------

def test_month_level_as_of_reaches_the_retriever_as_the_last_day_of_the_month():
    """15번 경로: 평가셋 `2023-05`가 그래프를 거쳐 검색기의 첫 검색 `q.as_of`(`2023-05-31`)가 되고, 필터 후보 수도 그 날짜 기준이다."""
    from qgraph_fakes import j, normal_llm

    from backend.graph.build import build_graph
    from evals.agent.run_eval import run_item

    r = make(valid_from=["2023-01-01", "2023-05-01", "2023-06-01", "2025-07-01"] + ["2026-01-01"] * 4)
    g = X.RecordingGraph(build_graph(r, llm=normal_llm(rewrite=j(query="q", org=None, as_of=None))))
    item = {"id": 1, "kind": "relevant", "input": Q, "gold": [], "as_of": "2023-05"}
    r.set_item(item)
    row = run_item(g, item, run_id="test-run")
    assert r.calls[0]["as_of"] == "2023-05-31" and r.calls[0]["n_filtered"] == 2          # 2023-05-31까지 유효해진 판만
    assert row["id"] == 1
    other = {"id": 1, "kind": "relevant", "input": Q, "gold": [], "as_of": "2026-10-27"}
    r.set_item(other)
    run_item(g, other, run_id="test-run")
    assert r.calls[0]["as_of"] == "2026-10-27"                                            # 10자리 기준일은 그대로


# ---------- 그래프 분해 연결과 측정 경로의 분리 ----------

def test_measurement_graph_never_calls_the_decompose_llm_and_values_do_not_change(monkeypatch):
    """측정 전용 검색기는 저장된 분해를 읽는다. 그래프의 질문 분해는 환경 변수가 켜져 있어도 부르지 않고, 검색기가 받는 입력과 결과는 분해 연결 전과 같다."""
    from qgraph_fakes import j, normal_llm

    from backend.graph.build import build_graph
    from evals.agent.run_eval import run_item

    def one(graph_factory, env):
        for k in ("SEARCH_DECOMPOSE",):
            monkeypatch.delenv(k, raising=False)
        if env:
            monkeypatch.setenv("SEARCH_DECOMPOSE", "1")
        r = make(embed=lambda q: (W_REV / np.linalg.norm(W_REV), 0, True))
        n = iter(range(9))
        llm = normal_llm(rewrite=lambda u: j(query=f"q{next(n)}", org=None, as_of=None), decompose=j(split=True, sub_questions=["하위1", "하위2"]),
                         judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)])
        g = graph_factory(r, llm)
        item = {"id": 1, "kind": "relevant", "input": Q, "gold": [], "as_of": "2026-10-27"}
        r.set_item(item)
        row = run_item(g, item, run_id="sep")
        return row, r.calls, llm

    legacy = lambda r, llm: X.RecordingGraph(build_graph(r, llm=llm, decompose=False))  # noqa: E731  분해 연결 전과 같은 동작
    measured = lambda r, llm: X.make_graph(r, llm=llm)                                    # noqa: E731
    row_a, calls_a, llm_a = one(legacy, env=False)
    row_b, calls_b, llm_b = one(measured, env=True)                                       # 환경 변수가 켜져 있어도
    assert llm_b.count("decompose") == 0 and llm_a.count("decompose") == 0
    assert [c["retrieval_query"] for c in calls_b] == [Q, "q1"] == [c["retrieval_query"] for c in calls_a]   # 첫 검색은 원 질문, 재검색은 재작성 검색어
    for key in ("returned", "as_of", "org", "kind", "split", "n_filtered"):
        assert [c[key] for c in calls_a] == [c[key] for c in calls_b], key
    drop = {"latency_s", "cost_usd"}
    assert {k: v for k, v in row_a.items() if k not in drop} == {k: v for k, v in row_b.items() if k not in drop}


def test_run_cmd_uses_the_measurement_graph_without_decomposition():
    import inspect

    src = inspect.getsource(X.run_cmd)
    assert "make_graph(retr)" in src and "build_graph(retr)" not in src
    assert "decompose=False" in inspect.getsource(X.make_graph)
