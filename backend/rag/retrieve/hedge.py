"""검색 hedge(사전 등록 62.14): 읽기 전용 일 하나를 일정 시간 안에 못 끝내면 같은 일을 한 번 더 보내 먼저 끝난 결과를 쓴다.

- 켜는 곳: `SearchConfig.hedge`(환경 변수 `SEARCH_HEDGE=1`, 기본 꺼짐), 대기 시간 `SEARCH_HEDGE_S`(초, 기본 1.5). 꺼져 있으면 이 모듈은 부르지 않는다.
- 같은 일을 두 번 돌려도 결과가 같은 일에만 쓴다(질문 임베딩 + 벡터 질의). 쓰는 쪽이 `fn`에 시도 번호를 넘겨 받아, 시도마다 따로 기록을 모으게 한다.
- 첫 시도가 대기 시간 안에 끝나면(성공이든 오류든) 하나만 돌고 오류는 그대로 올라간다(지금과 같다). 한 번 더 보낸 뒤에는 먼저 성공한 쪽을 쓰고,
  둘 다 실패해야 먼저 실패한 쪽의 오류를 올린다. 늦은 쪽은 멈출 수 없어 끝까지 돌지만 결과는 버린다(스레드 풀은 기다리지 않고 닫는다).
"""
from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HEDGE_S = 1.5
_ON = {"1", "true", "yes", "on"}


def enabled(environ: Any = None) -> bool:
    import os

    env = os.environ if environ is None else environ
    return (env.get("SEARCH_HEDGE") or "").strip().lower() in _ON


def hedge_seconds(environ: Any = None) -> float:
    """`SEARCH_HEDGE_S`. 비면 기본 1.5초. 0 이하이거나 숫자가 아니면 ValueError."""
    import os

    env = os.environ if environ is None else environ
    raw = (env.get("SEARCH_HEDGE_S") or "").strip()
    if not raw:
        return DEFAULT_HEDGE_S
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"SEARCH_HEDGE_S는 0보다 큰 초다: {raw!r}") from None
    if not value > 0:
        raise ValueError(f"SEARCH_HEDGE_S는 0보다 큰 초다: {raw!r}")
    return value


def hedged(fn: Callable[[int], Any], seconds: float) -> tuple[Any, int, bool]:
    """`fn(시도 번호)`를 돌리고 `seconds`초 안에 안 끝나면 `fn(1)`을 하나 더 돌린다. (결과, 이긴 시도 번호, 한 번 더 보냈는지)를 돌려준다.
    각 시도는 지금의 컨텍스트 변수 복사본에서 돈다(호출한 쪽의 컨텍스트 변수는 바뀌지 않는다)."""
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="search_hedge")
    try:
        first = pool.submit(contextvars.copy_context().run, fn, 0)
        wait({first}, timeout=seconds)     # fn 안에서 난 TimeoutError와 섞이지 않게 result(timeout=)을 쓰지 않는다
        if first.done():
            return first.result(), 0, False
        log.info("검색 %.1f초 무응답: 같은 검색을 하나 더 보냄", seconds)
        second = pool.submit(contextvars.copy_context().run, fn, 1)
        owner = {first: 0, second: 1}
        pending = set(owner)
        error: BaseException | None = None
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in sorted(done, key=owner.get):
                exc = fut.exception()
                if exc is None:
                    return fut.result(), owner[fut], True
                error = error or exc
        assert error is not None
        raise error
    finally:
        pool.shutdown(wait=False)
