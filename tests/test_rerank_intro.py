"""R3 도입부 채우기(`GRAPH_INTRO_FILL`) 시험. 기본 꺼짐이고 DB 없이 가짜로 돈다."""
from __future__ import annotations

import numpy as np
import pytest

from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher
from backend.schemas.chunk import SearchQuery
from test_answer_fixes_graph import REVIEW, llm, mk, run
from test_search import fake_embed, fake_translator, row, vec


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_INTRO_FILL",):
        monkeypatch.delenv(name, raising=False)


# ---------- R3 도입부 채우기 ----------
def _page_rows():
    arts = ["Overview", "Overview > Scope", "Overview > Goals", "Process", "Process > Steps", "Budget"]
    texts = ["saas overview", "saas approval scope", "incident goals list", "approval process", "approval review steps", "budget review"]
    out = []
    for i, (a, t) in enumerate(zip(arts, texts)):
        r = row(f"p{i}", t, rule_seq=7)
        out.append({**r, "article": a, "ord": i})
    # 페이지 9: 도입부 절이 청크 2개(한 문단이 나뉨)
    small = [("q0", "Intro", "vendor intro part one"), ("q1", "Intro", "vendor intro part two"), ("q2", "Steps", "vendor steps"),
             ("q3", "Steps > More", "vendor more steps"), ("q4", "Budget", "vendor budget")]
    out += [{**row(cid, t, rule_seq=9), "article": a, "ord": i} for i, (cid, a, t) in enumerate(small)]
    return out + [row("x1", "security incident", rule_seq=8)]


def _intro_searcher():
    rows = _page_rows()
    cfg = SearchConfig(embed_model="Snowflake/snowflake-arctic-embed-l-v2.0", mode="dense_en", rerank_model="none", link_n=0)
    return Searcher(cfg, MemoryStore(rows, np.stack([vec(r["text"]) for r in rows]), "Snowflake/snowflake-arctic-embed-l-v2.0"),
                    embedder=fake_embed, reranker=None, translator=fake_translator(), check_meta=False), {r["chunk_id"]: r for r in rows}


def test_intro_fill_adds_the_closest_intro_chunk_for_a_page_with_three_chunks():
    s, by = _intro_searcher()
    ctx = [by["p3"], by["p4"], by["p5"], by["x1"]]
    got = s.intro_fill(ctx, "saas approval")
    assert [c.chunk_id for c in got] == ["p1"]  # 첫 절(Overview, 청크 3개) 중 질문과 가장 가까운 것
    assert [c.chunk_id for c in s.intro_fill(ctx, "saas overview")] == ["p0"]


def test_intro_fill_adds_a_two_chunk_intro_section_whole():
    s, by = _intro_searcher()
    got = s.intro_fill([by["q2"], by["q3"], by["q4"]], "vendor budget")
    assert [c.chunk_id for c in got] == ["q0", "q1"]  # 절이 청크 2개면 벡터 순위 없이 ord 순 전체
    assert [c.chunk_id for c in s.intro_fill([by["q1"], by["q2"], by["q3"], by["q4"]], "vendor budget")] == []  # 절의 청크가 이미 있다


def test_intro_fill_skips_small_pages_and_pages_with_the_intro_already():
    s, by = _intro_searcher()
    assert s.intro_fill([by["p3"], by["p4"], by["x1"]], "saas approval") == []  # 같은 페이지 2개
    assert s.intro_fill([by["p0"], by["p3"], by["p4"]], "saas approval") == []  # 첫 절이 이미 있다
    assert s.intro_fill([], "saas approval") == []


def test_intro_fill_reuses_the_search_vector():
    s, by = _intro_searcher()
    calls = []
    inner = s.embed
    s.embed = lambda texts: (calls.append(list(texts)), inner(texts))[1]
    s.search(SearchQuery(query="saas approval", k=3))
    n = len(calls)
    s.intro_fill([by["p3"], by["p4"], by["p5"]], "saas approval")
    assert len(calls) == n  # 방금 찾은 질문은 다시 임베딩하지 않는다


PAGE_A = [mk(f"Step {i} of the release process.", title="Release Process", seq=72001, article=f"Process > Step {i}") for i in range(3)]
INTRO = mk("Overview of the release process.", title="Release Process", seq=72001, article="Overview")


def _fake_intro(seen):
    def fn(chunks, query, org, as_of):
        seen.append((len(chunks), query))
        return [INTRO]
    return fn


@pytest.mark.parametrize("multi", [False, True])
def test_intro_fill_switch_adds_the_chunk_in_the_graph(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")
    seen: list = []
    fn = lambda q: PAGE_A  # noqa: E731
    m = llm()
    g = build_multi_graph(fn, llm=m, intro_search=_fake_intro(seen)) if multi else build_graph(fn, llm=m, intro_search=_fake_intro(seen))
    out = run(g, "릴리스 절차는?")
    assert seen and INTRO.chunk_id in [c["chunk_id"] for c in out["chunks"]]
    assert [c["chunk_id"] for c in out["chunks"]][:3] == [c.chunk_id for c in PAGE_A]  # 뒤에 붙는다


def test_intro_fill_off_or_failing_keeps_the_context(monkeypatch):
    seen: list = []
    out = run(build_graph(lambda q: PAGE_A, llm=llm(), intro_search=_fake_intro(seen)), "릴리스 절차는?")
    assert seen == [] and INTRO.chunk_id not in [c["chunk_id"] for c in out["chunks"]]
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")

    def boom(*a):
        raise RuntimeError("db")
    out = run(build_graph(lambda q: PAGE_A, llm=llm(), intro_search=boom), "릴리스 절차는?")
    assert [c["chunk_id"] for c in out["chunks"]] == [c.chunk_id for c in PAGE_A]
    out = run(build_graph(lambda q: [REVIEW], llm=llm()), "릴리스 절차는?")  # 검색 함수가 없으면 그대로
    assert [c["chunk_id"] for c in out["chunks"]] == [REVIEW.chunk_id]
