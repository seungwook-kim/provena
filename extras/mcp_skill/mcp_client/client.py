"""MCP 클라이언트 — 그래프가 검색을 FastMCP 서버(extras/mcp_skill/mcp_server)로 부를 때 쓴다 (docs/specs/mcp.md 클라이언트 절).

가산 MCP·Skill은 "에이전트가 MCP 클라이언트로 호출"해야 인정된다(가이드 p.20, PRD 194줄). 이 파일은 부르는 쪽만 만든다.
그래프 연결(SEARCH_VIA_MCP, SDD 2-3절)은 김승욱 build.py에서 한다 — 여기서 build.py·search.py를 고치지 않는다.

  load_tools()        MCP 도구 5개를 LangChain 도구로 (에이전트가 도구를 직접 고르게 할 때)
  search_via_mcp(q)   search()와 같은 모양(list[Chunk])으로 search_handbook을 부른다 (검색 노드가 search() 대신 부를 때)

라이브러리: langchain[mcp] (PRD 319줄·SDD 77줄, 베타). langchain.mcp는 FastMCP Client 위에서 MCP 도구를 LangChain 도구로 바꾼다.
search_via_mcp는 결과를 Chunk로 되돌려야 해서 같은 FastMCP Client로 직접 부른다(structured_content를 그대로 읽음).

주소·토큰: MCP_URL(기본 http://127.0.0.1:8000/mcp/), MCP_TOKEN(Bearer, 서버와 같은 값). 시험은 서버 객체를 그대로 넣는다(네트워크 없음).
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastmcp import Client

from backend.schemas.chunk import Chunk, SearchQuery

DEFAULT_URL = "http://127.0.0.1:8000/mcp/"
CALL_TIMEOUT_S = 35.0     # 서버 도구 제한 30초(server.TOOL_TIMEOUT_S)보다 조금 길게 — 서버가 먼저 unavailable로 답하게
SEARCH_TOOL = "search_handbook"

_last_note: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_last_note", default=None)


class McpSearchError(RuntimeError):
    """서버가 ok·not_found가 아닌 상태로 답했거나 부를 수 없었다. retryable이면 잠시 뒤 다시, 아니면 다시 불러도 같다."""

    def __init__(self, status: str, note: str | None, retryable: bool):
        super().__init__(f"{status}: {note or ''}".strip())
        self.status, self.note, self.retryable = status, note, retryable


class McpUnavailable(McpSearchError, ConnectionError):
    """다시 부르면 될 수 있는 실패(서버 unavailable, 연결 실패, 시간 초과). ConnectionError라 기존 재시도 판정에도 걸린다."""

    def __init__(self, note: str | None):
        super().__init__("unavailable", note, retryable=True)


def make_client(target: Any = None, token: str | None = None, timeout: float = CALL_TIMEOUT_S) -> Client:
    """target = http(s) 주소 문자열(기본 MCP_URL) 또는 FastMCP 서버·transport 객체(시험).

    문자열은 http(s)만 받는다 — fastmcp는 문자열을 파일 경로로 먼저 읽어 .py면 그 파일을 실행하므로(langchain.mcp도 같은 이유로 막음).
    """
    if target is None:
        target = os.getenv("MCP_URL", "").strip() or DEFAULT_URL
    if isinstance(target, str):
        if not target.startswith(("http://", "https://")):
            raise ValueError(f"MCP_URL은 http(s) 주소여야 합니다: {target!r}")
        token = (os.getenv("MCP_TOKEN", "") if token is None else token).strip()
        if not token:
            raise ValueError("MCP_TOKEN이 비어 있습니다. 서버의 /mcp는 토큰이 있을 때만 열립니다(EC-10).")
        return Client(target, auth=token, timeout=timeout)     # 문자열 auth = Bearer 헤더
    return Client(target, timeout=timeout)


async def load_tools(target: Any = None, token: str | None = None) -> list:
    """서버의 도구(지금 5개)를 LangChain 도구로. 도구 결과의 structured_content는 ToolMessage.artifact에 담긴다."""
    from langchain_core._api import LangChainBetaWarning
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainBetaWarning)
        from langchain.mcp import MCPAdapter
    return await MCPAdapter(make_client(target, token)).list_tools()


def _args(q: SearchQuery) -> dict[str, Any]:
    args: dict[str, Any] = {"query": q.query, "k": q.k}
    if q.sub_queries:
        # 몰래 빼지 않고 그대로 보낸다(빼면 직접 search()와 결과가 달라진다). 검사(2~3개)는 서버가 invalid로 돌려준다.
        args["sub_queries"] = list(q.sub_queries)
    if q.org is not None:
        args["org"] = q.org
    if q.as_of is not None:
        args["as_of"] = q.as_of
    return args


def _read(content: dict[str, Any] | None) -> tuple[list[Chunk], str | None]:
    """서버 응답(ToolResponse) → Chunk 목록. 상태별로 나눈다(Spec How 1)."""
    if not isinstance(content, dict) or "status" not in content:
        raise McpSearchError("error", "서버 응답 모양이 ToolResponse가 아닙니다.", retryable=False)
    status, note = content["status"], content.get("note")
    if status == "ok":
        return [Chunk.model_validate(d) for d in content.get("results", [])], note
    if status == "not_found":
        return [], note
    if status == "unavailable" or content.get("retryable") is True:
        raise McpUnavailable(note)
    raise McpSearchError(status, note, retryable=False)       # invalid·error·not_ready


async def asearch_via_mcp(q: SearchQuery, target: Any = None, token: str | None = None) -> tuple[list[Chunk], str | None]:
    """(청크 목록, 서버 note). note에는 fallback_reason(번역 실패·no_key 등)이 올 수 있다."""
    args = _args(q)
    client = make_client(target, token)
    try:
        async with client:
            res = await client.call_tool(SEARCH_TOOL, args, raise_on_error=False)
    except McpSearchError:
        raise
    except Exception as e:  # noqa: BLE001 — 연결 실패·시간 초과는 재시도 가능, 그 밖은 그대로 올린다
        if isinstance(e, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)) or _is_transport(e):
            raise McpUnavailable(f"MCP 서버에 닿지 못했습니다({type(e).__name__}). 잠시 뒤 다시 부르세요.") from e
        raise
    if res.is_error:   # 서버가 도구 실행 자체를 실패로 돌려줌(우리 서버는 상태로 답하므로 드묾)
        raise McpSearchError("error", "MCP 도구 실행 오류", retryable=False)
    return _read(res.structured_content)


def _is_transport(e: BaseException) -> bool:
    """httpx 계열 전송 오류(연결 거부·읽기 시간 초과)인지. fastmcp가 감싸 올리면 원인(__cause__)까지 본다."""
    seen = 0
    while e is not None and seen < 5:
        mod = type(e).__module__ or ""
        if mod.startswith(("httpx", "httpcore", "anyio")) and ("Connect" in type(e).__name__ or "Timeout" in type(e).__name__):
            return True
        e, seen = e.__cause__ or e.__context__, seen + 1
    return False


def search_via_mcp(q: SearchQuery, target: Any = None, token: str | None = None) -> list[Chunk]:
    """search(q)와 같은 모양. 그래프 노드가 동기 함수라도, 이미 이벤트 루프 안이어도 부를 수 있다(그때는 새 스레드에서)."""
    def go():
        return asyncio.run(asearch_via_mcp(q, target, token))
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        chunks, note = go()
    else:
        with ThreadPoolExecutor(max_workers=1) as ex:
            chunks, note = ex.submit(go).result()
    _last_note.set(note)
    return chunks


def last_mcp_note() -> str | None:
    """같은 스레드의 마지막 search_via_mcp가 받은 서버 note(fallback_reason 등). search.last_search_trace()의 짝."""
    return _last_note.get()
