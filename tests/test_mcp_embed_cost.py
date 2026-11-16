"""MCP 검색 경로(`SEARCH_VIA_MCP=1`)의 임베딩 사용량 기록. 가짜 검색기를 넣은 서버를 같은 프로세스에서 부른다(Voyage·LLM·네트워크 없음, 0원).

운영은 /chat이 같은 앱의 /mcp를 HTTP로 다시 부르므로(루프백) 서버 쪽 검색에는 /chat의 요청 집계가 없다. 서버가 검색 한 번의 임베딩 사용량을
응답의 `usage`로 돌려주고, 그래프 쪽 검색기(`mcp_retriever`)가 그 값을 /chat 요청 집계에 더한다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastmcp")

from backend.graph.mcp_retriever import make_mcp_retriever  # noqa: E402
from backend.schemas.chunk import SearchQuery  # noqa: E402
from backend.services import step_cost  # noqa: E402
from extras.mcp_skill.mcp_client import client as mc  # noqa: E402
from tests.test_mcp_server import FakeSearch, call, make  # noqa: E402


class EmbeddingSearch(FakeSearch):
    """검색 한 번에 Voyage를 `calls`번 부른 것처럼 사용량을 기록하는 가짜 검색기(embed.py가 하는 기록과 같은 함수)."""

    def __init__(self, tokens=40, calls=2, **kw):
        super().__init__(**kw)
        self.tokens, self.n = tokens, calls

    def __call__(self, q):
        for _ in range(self.n):
            step_cost.record_embed(self.tokens)
        return super().__call__(q)


def test_server_returns_the_embedding_usage_of_one_search():
    got = call(make(EmbeddingSearch(tokens=40, calls=2)), "search_handbook", {"query": "on-call"})
    assert got["status"] == "ok" and got["usage"] == {"embed_tokens": 80, "embed_calls": 2}


def test_not_found_still_reports_usage_and_no_call_reports_zero():
    got = call(make(EmbeddingSearch(tokens=7, calls=1, out=[])), "search_handbook", {"query": "없는 질문"})
    assert got["status"] == "not_found" and got["usage"] == {"embed_tokens": 7, "embed_calls": 1}
    plain = call(make(FakeSearch()), "search_handbook", {"query": "on-call"})
    assert plain["usage"] == {"embed_tokens": 0, "embed_calls": 0}   # 캐시 적중 등 Voyage 호출이 없으면 0


def test_other_tools_do_not_carry_usage():
    got = call(make(), "get_section", {"rule_seq": 7})
    assert got.get("usage") is None


def test_mcp_retriever_adds_server_usage_to_the_request_meter_once():
    """서버는 자기 집계를 따로 열어 세고(같은 프로세스에서 /chat 집계가 따라와도 두 번 세지 않는다), 검색기가 응답의 값을 /chat 집계에 한 번 더한다."""
    retrieve = make_mcp_retriever(make(EmbeddingSearch(tokens=40, calls=2)))
    meter, token = step_cost.begin()
    try:
        assert [c.chunk_id for c in retrieve(SearchQuery(query="온콜"))] == ["c1", "c2"]
        retrieve(SearchQuery(query="휴가"))
    finally:
        step_cost.end(token)
    snap = meter.snapshot()
    assert (snap["embed_tokens"], snap["embed_calls"]) == (160, 4)
    assert snap["embed_cost_usd"] == round(160 * step_cost.embed_usd_per_mtok() / 1_000_000, 8) > 0
    assert mc.last_mcp_usage() == {"embed_tokens": 80, "embed_calls": 2}


def test_outside_a_request_and_on_failure_nothing_is_recorded():
    retrieve = make_mcp_retriever(make(EmbeddingSearch(tokens=40, calls=1)))
    retrieve(SearchQuery(query="온콜"))   # 요청 밖(집계 없음)이면 아무 일도 없다
    broken = make_mcp_retriever(make(EmbeddingSearch(tokens=40, calls=1, exc=RuntimeError("x"))))
    meter, token = step_cost.begin()
    try:
        with pytest.raises(mc.McpSearchError):
            broken(SearchQuery(query="온콜"))
    finally:
        step_cost.end(token)
    assert (meter.embed_tokens, meter.embed_calls) == (0, 0)
    assert mc.last_mcp_usage() is None


def test_record_embed_usage_ignores_bad_values():
    meter, token = step_cost.begin()
    try:
        step_cost.record_embed_usage({"embed_tokens": 5, "embed_calls": 2})
        step_cost.record_embed_usage({"embed_tokens": "x", "embed_calls": -1})
        step_cost.record_embed_usage(None)
    finally:
        step_cost.end(token)
    assert (meter.embed_tokens, meter.embed_calls) == (5, 2)
