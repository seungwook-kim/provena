"""MCP 클라이언트 시험 (docs/specs/mcp.md 클라이언트 절 AC-C1~C4).

CI: 가짜 검색기를 넣은 서버를 같은 프로세스에서 부른다. HTTP 토큰 시험도 ASGI로 붙여 실제 네트워크를 쓰지 않는다
(연결 거부 시험만 내 PC의 닫힌 포트 127.0.0.1:9 로). Voyage·LLM은 부르지 않는다.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("langchain.mcp")
import httpx2  # noqa: E402
from fastmcp.client.transports import StreamableHttpTransport  # noqa: E402

from backend.schemas.chunk import Chunk, SearchQuery  # noqa: E402
from extras.mcp_skill.mcp_client import client as mc  # noqa: E402
from extras.mcp_skill.mcp_server import server  # noqa: E402
from tests.test_mcp_server import FakeChanges, FakeSearch, chunk, section_rows  # noqa: E402

TOOLS = {"search_handbook", "get_section", "list_changed_sections"}


def deps(search=None):
    return dict(search_fn=search or FakeSearch(), section_store=section_rows(["x"]), changes_store=FakeChanges())


def make(search=None):
    return server.build_server(**deps(search))


# ---------- AC-C1: 도구 3개가 LangChain 도구로 ----------

def test_load_tools_gives_three_langchain_tools():
    from langchain_core.tools import BaseTool
    tools = asyncio.run(mc.load_tools(make()))
    assert {t.name for t in tools} == TOOLS
    assert all(isinstance(t, BaseTool) for t in tools)


def test_langchain_tool_call_returns_server_response_as_artifact():
    tools = {t.name: t for t in asyncio.run(mc.load_tools(make()))}
    msg = asyncio.run(tools["search_handbook"].ainvoke(
        {"type": "tool_call", "id": "t1", "name": "search_handbook", "args": {"query": "on-call"}}))
    assert msg.artifact["structured_content"]["status"] == "ok"
    assert [r["chunk_id"] for r in msg.artifact["structured_content"]["results"]] == ["c1", "c2"]


# ---------- AC-C2: search_via_mcp == 직접 search() ----------

def test_search_via_mcp_equals_direct_search():
    out = [chunk(3, "first"), chunk(1, "second"), chunk(2, "third")]
    fake = FakeSearch(out=out)
    q = SearchQuery(query="온콜 호출 확인 시간", org="security", as_of="2026-10-30", k=3)
    got = mc.search_via_mcp(q, make(fake))
    assert got == fake(q)                                  # 같은 Chunk, 같은 순서
    assert all(isinstance(c, Chunk) for c in got)
    sent = fake.calls[0]
    assert (sent.query, sent.org, sent.as_of, sent.k) == (q.query, q.org, q.as_of, q.k)


def test_not_found_is_empty_list_and_note_kept():
    fake = FakeSearch(out=[], fallback="no_key")
    assert mc.search_via_mcp(SearchQuery(query="없는 질문"), make(fake)) == []
    assert "no_key" in (mc.last_mcp_note() or "")


def test_sub_queries_reach_server_not_dropped():
    fake = FakeSearch(out=[chunk(2, "a"), chunk(1, "b")])
    q = SearchQuery(query="두 가지 질문", sub_queries=["하나", "둘"])
    got = mc.search_via_mcp(q, make(fake))
    assert fake.calls[0].sub_queries == ["하나", "둘"]       # 빠짐없이, 같은 순서로
    assert [c.chunk_id for c in got] == ["c2", "c1"]


def test_bad_sub_queries_are_refused_by_server():
    q = SearchQuery.model_construct(query="q", k=5, sub_queries=["하나"])   # 1개 — 서버 검사(2~3개)에 걸린다
    with pytest.raises(mc.McpSearchError) as e:
        mc.search_via_mcp(q, make())
    assert e.value.status == "invalid" and not e.value.retryable


def test_works_inside_running_event_loop():
    async def inside():
        return mc.search_via_mcp(SearchQuery(query="q"), make())
    assert [c.chunk_id for c in asyncio.run(inside())] == ["c1", "c2"]


# ---------- AC-C3: 실패 상태 → 재시도 가능 / 불가 ----------

def test_server_unavailable_is_retryable():
    fake = FakeSearch(exc=ConnectionError("db down"))
    with pytest.raises(mc.McpUnavailable) as e:
        mc.search_via_mcp(SearchQuery(query="q"), make(fake))
    assert e.value.retryable and isinstance(e.value, ConnectionError)


def test_server_internal_error_is_not_retryable():
    fake = FakeSearch(exc=KeyError("bug"))
    with pytest.raises(mc.McpSearchError) as e:
        mc.search_via_mcp(SearchQuery(query="q"), make(fake))
    assert e.value.status == "error" and not e.value.retryable
    assert not isinstance(e.value, mc.McpUnavailable)


def test_connection_refused_is_retryable():
    with pytest.raises(mc.McpUnavailable):
        mc.search_via_mcp(SearchQuery(query="q"), "http://127.0.0.1:9/mcp/", token="abc")


def test_string_target_must_be_http_and_token_required(monkeypatch):
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    with pytest.raises(ValueError):
        mc.make_client("extras/mcp_skill/mcp_server/server.py", token="abc")   # 파일 경로를 실행하지 않는다
    with pytest.raises(ValueError):
        mc.make_client("http://127.0.0.1:8000/mcp/")                            # 토큰 없음


# ---------- AC-C4: HTTP Bearer 토큰 ----------

def _http_search(token: str):
    app = server.mcp_http_app(token="abc", **deps())

    def factory(headers=None, timeout=None, auth=None, **kw):
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test",
                                  headers=headers, timeout=timeout, auth=auth, **kw)

    async def go():
        async with app.router.lifespan_context(app):
            tr = StreamableHttpTransport("http://test/", auth=token, httpx_client_factory=factory)
            return await mc.asearch_via_mcp(SearchQuery(query="q"), tr)
    return asyncio.run(go())


def test_http_right_token_gets_results():
    chunks, _ = _http_search("abc")
    assert [c.chunk_id for c in chunks] == ["c1", "c2"]


def test_http_wrong_token_is_blocked(caplog):
    caplog.set_level("INFO", logger="fastmcp.server.auth.middleware")
    with pytest.raises(Exception) as e:
        _http_search("abd")
    assert not isinstance(e.value, mc.McpUnavailable)     # 토큰 틀림은 다시 불러도 같다
    # 다른 이유(설정 오류 등)로 실패한 것이 아니라 서버 인증이 401로 막았는지
    assert any("status=401" in r.getMessage() for r in caplog.records)
