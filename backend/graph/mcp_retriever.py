"""그래프 쪽 MCP 검색 연결 (SDD 78줄 `SEARCH_VIA_MCP`). 호출 코드는 `extras/mcp_skill/mcp_client/client.py`에 있고, 여기서는 그 실패를 그래프가 아는 모양으로 바꾼다.

직접 호출과 같은 동작을 맞추는 곳:
- `unavailable`, 연결 실패, 시간 초과: `EmbedUnavailable`로 바꾼다. 그래프의 "검색을 지금 쓸 수 없음" 거절로 간다.
- `invalid`: 빈 결과로 바꾼다. 직접 `search()`는 모르는 절이면 빈 목록을 돌려주는데, 서버는 `invalid`로 답한다(재작성 LLM이 낸 절 이름이 코퍼스에 없을 때).
- `fallback_reason`: 서버 쪽 검색 기록(contextvar)은 그래프에서 읽을 수 없어 서버 note에서 읽는다.
- 임베딩 사용량: 서버 쪽 검색에는 /chat 요청 집계(`step_cost`)가 없어 서버가 응답 `usage`로 돌려준 값을 이 요청 집계에 더한다(`record_embed_usage`).
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
from collections.abc import Callable
from typing import Any

from backend.rag.retrieve.embed import EmbedUnavailable
from backend.schemas import Chunk, SearchQuery

log = logging.getLogger(__name__)

_ON_VALUES = {"1", "true", "yes", "on"}
_REASON = re.compile(r"fallback_reason=(\S+)")
_fallback: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_fallback_reason", default=None)


def search_via_mcp_enabled() -> bool:
    """SEARCH_VIA_MCP가 1, true, yes, on일 때만 MCP로 부른다. 기본은 직접 호출이다."""
    return os.environ.get("SEARCH_VIA_MCP", "").strip().lower() in _ON_VALUES


def last_fallback_reason() -> str | None:
    """같은 스레드의 마지막 MCP 검색이 받은 `fallback_reason`."""
    return _fallback.get()


def make_mcp_retriever(target: Any = None, token: str | None = None) -> Callable[[SearchQuery], list[Chunk]]:
    """`SearchQuery -> list[Chunk]`. target은 주소 문자열이나 FastMCP 서버 객체(측정과 시험, 네트워크 없음)다."""
    from extras.mcp_skill.mcp_client.client import McpSearchError, McpUnavailable, last_mcp_note, last_mcp_usage, search_via_mcp
    from backend.services import step_cost

    def retrieve(q: SearchQuery) -> list[Chunk]:
        _fallback.set(None)
        try:
            out = search_via_mcp(q, target, token)
        except McpUnavailable as e:
            raise EmbedUnavailable(str(e)) from e
        except McpSearchError as e:
            if e.status == "invalid":
                log.warning("MCP 검색 입력 거절, 빈 결과로 처리: %s", e.note)
                return []
            raise
        found = _REASON.search(last_mcp_note() or "")
        _fallback.set(found.group(1) if found else None)
        step_cost.record_embed_usage(last_mcp_usage())   # 서버가 센 이 검색의 임베딩 사용량을 /chat 요청 집계에 더한다(루프백이라 서버 쪽에는 집계가 없다)
        return out

    return retrieve


def make_mcp_section_reader(target: Any = None, token: str | None = None) -> Callable[[int, str | None, str | None], dict | None]:
    """`(rule_seq, article, as_of) -> 섹션 dict | None`. 실패 구분은 검색과 같다."""
    from extras.mcp_skill.mcp_client.client import McpUnavailable, section_via_mcp

    def read(rule_seq: int, article: str | None, as_of: str | None) -> dict | None:
        try:
            return section_via_mcp(rule_seq, article, as_of, target, token)
        except McpUnavailable as e:
            raise EmbedUnavailable(str(e)) from e

    return read


def default_section_reader(rule_seq: int, article: str | None, as_of: str | None) -> dict | None:
    """그래프의 기본 섹션 읽기. 검색과 같은 설정값을 따른다. 직접 호출도 MCP와 같게 비공개 주소를 가린다."""
    if search_via_mcp_enabled():
        return make_mcp_section_reader()(rule_seq, article, as_of)
    from backend.rag.retrieve.privacy import redact_chunk
    from backend.rag.retrieve.section import get_section

    found = get_section(rule_seq, article, as_of)
    return redact_chunk(found.model_dump()) if found else None


_default: Callable[[SearchQuery], list[Chunk]] | None = None


def default_retriever(q: SearchQuery) -> list[Chunk]:
    """검색 노드와 합동 검토의 기본 검색기. 설정값 하나로 MCP와 직접 호출을 바꾼다."""
    global _default
    if search_via_mcp_enabled():
        if _default is None:
            _default = make_mcp_retriever()
        return _default(q)
    from backend.rag.retrieve import search

    return search(q)
