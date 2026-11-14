"""LLM 호출별 시간 기록. 켜는 곳은 `capture()`뿐이고, 켜지 않으면 아무 일도 하지 않는다(서비스 요청 경로는 켜지 않는다).

- `with capture() as calls:` 안에서 만든 `run_config(...)`에 콜백(`LlmTraceHandler`)이 붙어, 그 config를 따라가는 LLM 호출마다 `calls`에 한 줄을 남긴다.
- 기록 칸: `seq`, `step`(노드/표지. 예: `judge/judge`, `search/decompose`, `ground/answer`, `translate_sentence`), `node`, `task`, `model_type`, `start_s`(capture 시작부터), `seconds`,
  `ok`, `error`(예외 종류 이름만), `retries`, `json_ok`, `model`, `input_tokens`, `output_tokens`, `reasoning_tokens`(출력 토큰 중 추론 몫, 공급자가 알려 줄 때만), `thinking_blocks`(Anthropic API 블록 목록 응답의 생각 블록 수, 목록일 때만), `cost_usd`(보고된 비용, 없으면 단가표 `cost.cost_usd`, 토큰을 모르면 None). 공급자가 알려 주면 `cli_duration_ms`, `cli_duration_api_ms`, `cli_wall_s`, `cli_queue_s`.
- 프롬프트, 응답, 오류 문장은 남기지 않는다. 표지는 시스템 프롬프트 앞의 `[[task:...]]`만 읽는다. 예외: `LLM_TRACE_DETAIL=1`(측정 전용)이면 답 작성과 판정의 응답 원문(`output_text`), 공급자(`provider`), HTTP 시도 횟수(`http_attempts`), 응답 코드(`http_statuses`), 요청 id(`request_id`)를 더한다. 서비스 경로는 켜지 않는다.
- `retries`: 어댑터 안에서 다시 시도한 횟수(`claude_cli`). SDK 안에서 다시 시도하는 공급자(OpenRouter 등)는 알 수 없어 None이다.
  응답 형식이 깨져 그래프가 다시 부른 호출은 같은 `step`의 다른 줄로 남고, 앞 줄의 `json_ok`가 False다.
- 콜백은 예외를 밖으로 내지 않는다(`raise_error=False`, 안에서도 잡는다). 기록이 실패해도 답은 그대로 나온다.
- 문항마다 따로 모으도록 contextvar를 쓴다. 다른 스레드로 넘길 때는 `bind(fn)`으로 기록 자리만 옮긴다(LangChain 실행 문맥은 옮기지 않는다).
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

log = logging.getLogger(__name__)

_TASK = re.compile(r"\[\[task:([a-z_]+)\]\]")
WRAPPER_TYPES = {"fallback", "demo-record"}   # 안쪽 모델을 부르는 덮개. 안쪽이 기록되면(그래프 노드 안) 겹쳐 세지 않고, 안 되면(번역처럼 config를 직접 넘긴 호출) 덮개 줄을 남긴다


class Collector:
    """문항 하나의 호출 기록. 여러 스레드가 함께 쓴다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.t0 = time.perf_counter()
        self.lock = threading.Lock()

    def add(self, row: dict) -> None:
        with self.lock:
            row["seq"] = len(self.calls) + 1
            self.calls.append(row)


_current: contextvars.ContextVar[Collector | None] = contextvars.ContextVar("llm_trace_collector", default=None)


@contextmanager
def capture() -> Iterator[list[dict]]:
    """이 블록 안에서 만든 `run_config`의 LLM 호출을 모은다. 돌려준 목록은 블록이 끝난 뒤에도 쓸 수 있다."""
    col = Collector()
    token = _current.set(col)
    try:
        yield col.calls
    finally:
        _current.reset(token)


def bind(fn: Callable) -> Callable:
    """`fn`을 다른 스레드에서 돌려도 지금의 기록 자리에 남게 한다. 기록을 켜지 않았으면 `fn`을 그대로 돌려준다."""
    col = _current.get()
    if col is None:
        return fn

    def run(*args: Any, **kwargs: Any) -> Any:
        token = _current.set(col)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)

    return run


def handler() -> "LlmTraceHandler | None":
    """기록이 켜져 있으면 콜백, 아니면 None. `run_config`가 부른다."""
    try:
        col = _current.get()
        return LlmTraceHandler(col) if col is not None else None
    except Exception as e:  # noqa: BLE001  기록 실패가 답을 망치면 안 된다
        log.debug("LLM 기록 준비 실패: %s", type(e).__name__)
        return None


_TEXT_TASKS = {"answer", "answer_fast", "judge", "judge_answer", "grounding"}  # 원문을 남길 호출: 인용 검사 전 초안과 판정 응답(빠른 답 포함, 측정 기록에만 남는다)
_http = threading.local()  # 호출과 HTTP가 같은 스레드에서 돈다. 호출마다 새로 시작한다


def detail_on() -> bool:
    return (os.environ.get("LLM_TRACE_DETAIL") or "").strip() == "1"


def _note_request(request: Any) -> None:
    ev = getattr(_http, "events", None)
    if ev is not None:
        ev["attempts"] += 1


def _note_response(response: Any) -> None:
    ev = getattr(_http, "events", None)
    if ev is None:
        return
    try:
        ev["statuses"].append(response.status_code)
        ev["request_id"] = response.headers.get("x-request-id") or response.headers.get("x-generation-id") or response.headers.get("cf-ray")
        response.read()  # 본문을 읽어 둔다. SDK는 읽어 둔 본문을 그대로 쓴다
        body = response.json()
        ev["provider"] = body.get("provider")
        ev["generation_id"] = body.get("id")
    except Exception as e:  # noqa: BLE001  기록 실패가 답을 망치면 안 된다
        log.debug("HTTP 기록 실패: %s", type(e).__name__)


def http_hooks() -> dict:
    """httpx 클라이언트의 `event_hooks`. 기록이 켜진 호출 안에서만 값을 남긴다."""
    return {"request": [_note_request], "response": [_note_response]}


def _task_of(messages: Any) -> str | None:
    for batch in messages or []:
        for m in batch:
            found = _TASK.search(m.content) if isinstance(m.content, str) else None
            if found:
                return found.group(1)
    return None


def step_of(messages: Any, meta: dict | None) -> tuple[str, str | None, str | None]:
    """(step, node, task). 호출별 기록(`LlmTraceHandler`)과 요청 비용의 단계별 합(`cost.CostTracker`)이 같은 이름을 쓰게 한 곳에서 정한다."""
    meta = meta or {}
    node, task = meta.get("langgraph_node"), _task_of(messages)
    if task is None and meta.get("kind"):       # 번역(translate.py)은 프롬프트에 표지가 없고 config에 종류가 있다
        task = f"translate_{meta['kind']}"
    step = "/".join(x for x in (node, task) if x) or str(meta.get("graph") or "unknown")
    return step, node, task


_prices: dict | None = None


def _call_cost(model: Any, usage: dict, meta: dict) -> float | None:
    """호출 한 번의 비용(달러). 모델이 알려 준 값(`total_cost_usd`, claude_cli)이 있으면 그것, 없으면 단가표(`cost.cost_usd`). 토큰을 모르면 None."""
    global _prices
    reported = meta.get("total_cost_usd")
    if isinstance(reported, (int, float)):
        return round(float(reported), 8)
    i, o = usage.get("input_tokens"), usage.get("output_tokens")
    if i is None and o is None:
        return None
    from backend.services import cost
    if _prices is None:
        _prices = cost.load_prices()
    return round(cost.usage_cost(model, usage, _prices), 8)   # 프롬프트 캐시 읽기·쓰기 토큰은 `CostTracker`와 같은 배수로 센다


def _json_ok(text: Any) -> bool | None:
    from backend.graph.parsing import parse_json_obj

    if isinstance(text, list):  # 블록 목록(Anthropic API 생각 블록 포함): 글 블록만 본다
        text = "".join(str(b.get("text") or "") for b in text if isinstance(b, dict) and b.get("type") == "text")
    return parse_json_obj(text) is not None if isinstance(text, str) else None


def _message_of(response: Any) -> Any:
    for gens in getattr(response, "generations", None) or []:
        for g in gens:
            return getattr(g, "message", None)
    return None


class LlmTraceHandler(BaseCallbackHandler):
    """호출 시작과 끝을 재서 기록한다. 예외를 밖으로 내지 않는다."""

    raise_error = False

    def __init__(self, collector: Collector) -> None:
        self.collector = collector
        self._open: dict[UUID, dict] = {}
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, metadata: dict | None = None, invocation_params: dict | None = None, **kwargs: Any) -> None:
        try:
            meta = metadata or {}
            model_type = (invocation_params or {}).get("_type")
            step, node, task = step_of(messages, meta)
            row = {"step": step, "node": node, "task": task, "model_type": model_type, "t": time.perf_counter()}
            if model_type in WRAPPER_TYPES:
                row["inner_mark"] = len(self.collector.calls)
            with self._lock:
                self._open[run_id] = row
            if detail_on() and model_type not in WRAPPER_TYPES:
                _http.events = {"attempts": 0, "statuses": [], "request_id": None, "provider": None, "generation_id": None}
        except Exception as e:  # noqa: BLE001  기록 실패가 답을 망치면 안 된다
            log.debug("LLM 기록 시작 실패: %s", type(e).__name__)

    def _add_detail(self, row: dict, msg: Any) -> None:
        ev = getattr(_http, "events", None)
        if ev is None:
            return
        _http.events = None
        row.update(provider=ev["provider"], http_attempts=ev["attempts"], http_statuses=ev["statuses"], request_id=ev["request_id"], generation_id=ev["generation_id"])
        if row.get("retries") is None and ev["attempts"]:
            row["retries"] = ev["attempts"] - 1
        if msg is not None and row.get("task") in _TEXT_TASKS and isinstance(getattr(msg, "content", None), str):
            row["output_text"] = msg.content

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> None:
        return None  # 이 저장소의 모델은 모두 채팅 모델이다. 문자열 모델은 기록 대상이 아니다

    def _close(self, run_id: UUID) -> dict | None:
        with self._lock:
            row = self._open.pop(run_id, None)
        if row is None:
            return None
        mark = row.pop("inner_mark", None)
        if mark is not None and len(self.collector.calls) > mark:
            return None
        t = row.pop("t")
        row["start_s"] = round(t - self.collector.t0, 3)
        row["seconds"] = round(time.perf_counter() - t, 3)
        return row

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            row = self._close(run_id)
            if row is None:
                return
            msg = _message_of(response)
            meta = getattr(msg, "response_metadata", None) or {}
            usage = getattr(msg, "usage_metadata", None) or {}
            row.update(ok=True, error=None, retries=meta.get("cli_retries"), json_ok=_json_ok(getattr(msg, "content", None)),
                       model=meta.get("model_name") or meta.get("model"),
                       input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                       reasoning_tokens=(usage.get("output_token_details") or {}).get("reasoning"),
                       cli_duration_ms=meta.get("duration_ms"), cli_duration_api_ms=meta.get("duration_api_ms"),
                       cli_wall_s=meta.get("wall_s"), cli_queue_s=meta.get("cli_queue_s"))
            row["cost_usd"] = _call_cost(row["model"], usage, meta)
            from backend.services.cost import cache_tokens
            read, w5, w1 = cache_tokens(usage)
            if read or w5 or w1:   # 프롬프트 캐시(`LLM_PROMPT_CACHE`)가 읽거나 쓴 입력 토큰. 캐시가 없으면 칸을 만들지 않는다(기록 모양 그대로)
                row.update(cache_read_tokens=read, cache_creation_tokens=w5 + w1)
            content = getattr(msg, "content", None)
            if isinstance(content, list):  # Anthropic API 블록 목록: 생각 블록 수(생각을 껐는지 확인용)
                row["thinking_blocks"] = sum(1 for b in content if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))
            self._add_detail(row, msg)
            self.collector.add(row)
        except Exception as e:  # noqa: BLE001
            log.debug("LLM 기록 실패: %s", type(e).__name__)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            row = self._close(run_id)
            if row is None:
                return
            row.update(ok=False, error=type(error).__name__, retries=getattr(error, "retries", None))
            self._add_detail(row, None)
            self.collector.add(row)
        except Exception as e:  # noqa: BLE001
            log.debug("LLM 기록 실패: %s", type(e).__name__)
