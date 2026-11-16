"""원 하위 질문 힌트(`GRAPH_KEEP_SUBJECT_UNION`, 기본 꺼짐).

질문 분해의 대상 유지(`GRAPH_DECOMPOSE_KEEP_SUBJECT`)가 하위 질문 앞에 대상 구를 붙였으면, 그래프는 붙이기 전 하위 질문(원 하위 질문)도 검색에 넘긴다.
검색 계약(`SearchQuery`, SDD 6장)은 바꾸지 않고, 검색을 부르는 동안만 이 contextvar에 (하위 질문, 원 하위 질문)을 둔다(`given`).
검색기(`search.Searcher.search`)는 받은 질문의 `sub_queries`가 힌트의 하위 질문과 같을 때만 쓴다(`current`). MCP 경로는 클라이언트가 같은 값을
`search_handbook`의 `sub_query_alts` 입력으로 보내고 서버가 다시 이 힌트로 둔다. 힌트가 없으면 검색 입력과 동작이 지금과 같다.
원 하위 질문은 하위 질문과 같은 자리 수이고, 빈 글은 그 자리 없음이다.
"""
from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

MAX_CHARS = 1000   # search.MAX_QUERY_CHARS와 같다

_hint: contextvars.ContextVar[tuple[tuple[str, ...], tuple[str, ...]] | None] = contextvars.ContextVar("sub_query_alts", default=None)


def check(subs: Sequence[str] | None, alts: Sequence[str]) -> None:
    """자리 수가 하위 질문과 같고 각 항목이 0~1000자 글인지. 아니면 ValueError."""
    subs = list(subs or [])
    if len(alts) != len(subs) or not subs:
        raise ValueError(f"원 하위 질문은 하위 질문과 같은 수: {len(alts)}개, 하위 질문 {len(subs)}개")
    if any(not isinstance(a, str) or len(a) > MAX_CHARS for a in alts):
        raise ValueError(f"원 하위 질문 항목은 0~{MAX_CHARS}자 글")


@contextmanager
def given(subs: Sequence[str], alts: Sequence[str]) -> Iterator[None]:
    """이 안에서 부르는 검색에 원 하위 질문을 넘긴다(같은 문맥, `asyncio.to_thread`처럼 문맥을 옮기는 스레드 포함)."""
    check(subs, alts)
    token = _hint.set((tuple(subs), tuple(alts)))
    try:
        yield
    finally:
        _hint.reset(token)


def current(sub_queries: Sequence[str] | None) -> list[str] | None:
    """지금 문맥의 원 하위 질문. 힌트가 없거나, 받은 하위 질문이 힌트의 하위 질문과 다르거나, 원 하위 질문이 모두 비었으면 None."""
    hint = _hint.get()
    if hint is None or not sub_queries or tuple(sub_queries) != hint[0] or not any(a.strip() for a in hint[1]):
        return None
    return list(hint[1])
