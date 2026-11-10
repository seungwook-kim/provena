"""채팅 모델 팩토리. 키가 없으면 테스트용 가짜 모델을 돌려준다(데모·테스트·CI에서 외부 호출 없음).

환경변수:
- `LLM_API_KEY`: 비어 있거나 없으면 데모 모드. 키 값은 환경변수에서만 읽는다.
- `DEMO_MODE`: 1/true/yes/on이면 키가 있어도 데모 모드. 키가 없으면 이 값과 무관하게 데모(자동).
  데모 모드의 `get_chat_model()`은 `ReplayChatModel`(`demo_replay.py`)이다: 요청 키로 `data/demo_replay/*.jsonl`의 녹화 응답을 찾고,
  없으면 결정적 가짜 응답(검색된 근거 문장을 `[1]` 표시와 함께 인용)을 쓴다. `responses`를 직접 주면 예전처럼 그 목록을 되풀이하는 `FakeListChatModel`.
- `LLM_RECORD`: 1이고 실제 키가 있고 데모가 아니면 실제 모델을 `RecordingChatModel`로 감싸 요청 키 -> 응답을 `data/demo_replay/recorded.jsonl`에 남긴다
  (`python -m backend.services.demo_record --questions <파일>`). `DEMO_REPLAY_DIR`로 폴더를 바꾼다.
- `LLM_PROVIDER`: `anthropic`(기본), `openai`, `openrouter` 또는 `claude_cli`.
  `claude_cli`는 로컬 Claude Code CLI(`claude -p`)를 모델로 쓴다(`claude_cli_model.py`). `LLM_API_KEY`가 필요 없고, `DEMO_MODE=1`이 아니면 데모 모드가 아니다.
- `LLM_MODEL`: claude_cli는 기본 `claude-haiku-5-5`. anthropic은 기본 `claude-haiku-5-5`, openai는 필수, openrouter는 기본 `anthropic/claude-haiku-5.5`(OpenRouter 모델 id).
- `LLM_MAX_RETRIES`: 제공자 SDK가 429(요청 한도)·5xx·연결 오류에서 다시 시도하는 최대 횟수(0 이상 정수). SDK는 `Retry-After` 헤더가 있으면 그만큼 기다린다. 비우면 SDK 기본값.
- `LLM_TIMEOUT_S`: 요청 한 번의 시간 제한(초, 양수). 비우면 SDK 기본값.
- `LLM_FALLBACK_MODEL`: 기본 모델이 (재시도 뒤에도) 실패하면 같은 제공자·같은 키로 이 모델을 한 번 더 부른다. 비용 상한 초과(`CostCapExceeded`)와 설정 오류(ValueError)는 폴백하지 않는다. 비우면 폴백 없음.
- `LLM_REASONING`: openrouter 요청에 `reasoning.effort`를 붙인다(none, minimal, low, medium, high). 비우면 보내지 않는다. 다른 제공자에는 쓰지 않는다.
- `LLM_EFFORT`, `LLM_EFFORT_BY_TASK`: anthropic 요청의 `effort`(none, low, medium, high, xhigh, max, none은 생각 끔 `thinking: disabled`). 기본 수준과 단계별 덮기(`answer=medium,grounding=medium`)이며 단계는 시스템 프롬프트의 `[[task:...]]`로 읽는다. 둘 다 비우면 보내지 않는다(API 기본). 다른 제공자에는 쓰지 않는다.
- `LLM_DEADLINE_S`·`LLM_HEDGE_S`: 시도별 응답 상한과 같은 요청 하나 더(openrouter와 anthropic, `DeadlineTransport`). anthropic은 SDK가 httpx2라 같은 동작의 httpx2 전송을 쓴다.
- `LLM_DEADLINE_SKIP_TASKS`: 쉼표 목록(끝 `*`는 접두어). 시스템 프롬프트의 `[[task:...]]`가 맞는 요청은 위 상한과 hedge 없이 그대로 보낸다. 비면 모든 요청에 건다.
- `LLM_PROVIDER_SORT`: openrouter 요청에 `provider.sort`를 붙인다(latency, throughput, price). 비우면 보내지 않는다.
- `LLM_BASE_URL`: openrouter의 API 주소를 바꾼다(기본 `https://openrouter.ai/api/v1`). OpenAI 호환 주소면 된다.
  비용 단가는 OpenRouter id(`벤더/이름`, 점)를 단가표 이름으로 맞춰 찾는다(`cost.normalize_model_id`).

LLM 호출의 트레이스와 비용 기록도 이 파일 한 곳으로 모은다. 그래프를 돌릴 때 `run_config(...)`가 만든 config를 `invoke`/`stream`에 넘기고,
끝나면 `finish_run(config)`을 부른다.
- Langfuse 트레이스: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`가 있을 때만(`tracing.py`). 없으면 트레이스 없이 그대로 돈다.
- 비용 상한: `LLM_COST_CAP_USD`(`cost.py`). 한 질문의 LLM 비용이 상한에 닿으면 다음 호출에서 `CostCapExceeded`.
- 호출별 시간 기록: `llm_trace.capture()` 안에서 만든 config에만 붙는다(`llm_trace.py`). 평가 실행기가 켠다.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from concurrent.futures import TimeoutError as FutureTimeout

import httpx

import importlib
import logging
import json
import re
import os
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from backend.services import llm_trace, tracing
from backend.services.demo_replay import env_flag
from backend.services.cost import CostCapExceeded, CostTracker, cost_cap_from_env

log = logging.getLogger(__name__)

__all__ = ["CostCapExceeded", "finish_run", "get_chat_model", "is_demo_mode", "run_config"]

DEFAULT_FAKE_RESPONSES = ["(가짜 모델 응답) 합성 시험용 답변입니다. 실제 핸드북 근거가 아닙니다."]
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")  # OpenRouter `reasoning.effort`
PROVIDER_SORTS = ("latency", "throughput", "price")  # OpenRouter `provider.sort`


def get_chat_model(responses: list[str] | None = None) -> BaseChatModel:
    """키가 있으면 실제 모델, 데모 모드면 재생 모델(`ReplayChatModel`).

    `responses`는 가짜 모델이 차례대로 되풀이할 응답 목록이다(데모 모드일 때만 쓴다). 주면 재생 없이 `FakeListChatModel`.
    `LLM_RECORD=1`이고 데모가 아니면 실제 모델을 녹화 래퍼로 감싼다.
    """
    if is_demo_mode():
        if responses:
            return FakeListChatModel(responses=list(responses))
        from backend.services.demo_replay import ReplayChatModel

        return ReplayChatModel()
    model = _real_chat_model()
    if env_flag("LLM_RECORD"):
        from backend.services.demo_replay import RecordingChatModel

        return RecordingChatModel(inner=model, model_name=os.environ.get("LLM_MODEL") or getattr(model, "model", None) or getattr(model, "model_name", "") or "")
    return model


def _env_number(name: str, cast: type) -> Any:
    """양의 값(재시도는 0 이상)만 받는다. 비었거나 잘못된 값은 None(SDK 기본값)이고 경고만 남긴다."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        v = cast(raw)
    except ValueError:
        log.warning("%s=%r는 숫자가 아니라 무시합니다", name, raw)
        return None
    if v < 0 or (name == "LLM_TIMEOUT_S" and v == 0):
        log.warning("%s=%r는 범위 밖이라 무시합니다", name, raw)
        return None
    return v


def _client_options() -> dict[str, Any]:
    """제공자 SDK 클라이언트에 넘길 재시도 상한·시간 제한(G-05). 둘 다 `ChatAnthropic`·`ChatOpenAI`가 같은 이름으로 받는다."""
    out: dict[str, Any] = {}
    retries = _env_number("LLM_MAX_RETRIES", int)
    if retries is not None:
        out["max_retries"] = retries
    timeout = _env_number("LLM_TIMEOUT_S", float)
    if timeout is not None:
        out["timeout"] = timeout
    return out


class DeadlineTransport(httpx.BaseTransport):
    """시도 한 번의 응답 전체를 받는 데 걸리는 시간의 상한. SDK의 `timeout`은 바이트 사이 간격이라 공급자가 빈 문자를 흘리는 동안에는 끊지 못한다.
    넘으면 `httpx.ReadTimeout`을 내고 SDK가 재시도한다. 재시도마다 상한을 늘려(상한 x (재시도 번호 + 1)) 원래 오래 걸리는 긴 답이 모든 시도에서 잘리지 않게 한다.
    끊은 시도는 뒤에서 끝까지 받고 버린다. 공급자가 그 시도에도 요금을 매길 수 있어 호출 기록의 `http_attempts`와 키 사용액으로 확인한다."""

    timeout_exc: Any = httpx.ReadTimeout  # 넘으면 내는 예외. SDK가 재시도하는 시간 초과 예외여야 한다(anthropic SDK는 httpx2, _deadline_transport_httpx2)

    def __init__(self, inner: httpx.BaseTransport, seconds: float, hedge: float = 0.0, skip_tasks: tuple[str, ...] = ()) -> None:
        self.inner, self.seconds, self.hedge = inner, seconds, hedge  # hedge(`LLM_HEDGE_S`): 이 시간 안에 답이 없으면 같은 요청을 하나 더 보내 먼저 온 답을 쓴다
        self.skip_tasks = tuple(skip_tasks)  # `LLM_DEADLINE_SKIP_TASKS`: 이 단계는 상한과 hedge 없이 그대로 보낸다(답이 긴 결정표 초안, 합동 검토)
        self.pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="llm-http")

    @staticmethod
    def _task_of(request: httpx.Request) -> str | None:
        """요청 본문의 시스템 프롬프트에서 첫 `[[task:...]]` 표지. 없거나 본문을 못 읽으면 None."""
        try:
            body = json.loads(request.read())
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        systems = [m.get("content") for m in body.get("messages") or [] if isinstance(m, dict) and m.get("role") == "system"]
        systems.append(body.get("system"))  # Anthropic 요청은 시스템 프롬프트가 맨 위 `system` 칸(글 또는 블록 목록)이다
        for content in systems:
            found = _TASK_MARK.search(str(content)) if content else None
            if found:
                return found.group(1)
        return None

    def _fetch(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        response.read()
        return response

    def _log_event(self, message: str, request: httpx.Request, task: str | None, elapsed: float, attempt: int) -> None:
        """운영에서 보이게 WARNING으로 남긴다. 요청 ID, 단계(`[[task:...]]` 표지 이름), 걸린 시간, 시도 번호만 쓴다. 프롬프트·키·주소는 쓰지 않는다."""
        stage = task if task is not None else (self._task_of(request) or "-")
        log.warning("%s request_id=%s stage=%s elapsed_s=%.1f attempt=%d", message, _current_request_id(), stage, elapsed, attempt)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            attempt = int(request.headers.get("x-stainless-retry-count") or 0)
        except ValueError:
            attempt = 0
        limit = self.seconds * (attempt + 1)
        task = self._task_of(request) if self.skip_tasks else None
        if task and task_matches(task, self.skip_tasks):
            return self.inner.handle_request(request)
        hedge = self.hedge
        future = self.pool.submit(self._fetch, request)
        if not hedge or hedge >= limit:
            try:
                return future.result(timeout=limit)
            except FutureTimeout:
                self._log_event("LLM 시간 상한 초과(SDK가 재시도)", request, task, limit, attempt)
                raise self.timeout_exc(f"attempt over {limit}s", request=request) from None
        try:
            return future.result(timeout=hedge)
        except FutureTimeout:
            pass
        self._log_event("LLM 무응답: 같은 요청을 하나 더 보냄", request, task, hedge, attempt)
        pending = {future, self.pool.submit(self._fetch, request)}
        left = limit - hedge
        error: BaseException | None = None
        while pending and left > 0:
            started = time.monotonic()
            done, pending = wait_futures(pending, timeout=left, return_when=FIRST_COMPLETED)
            left -= time.monotonic() - started
            for f in done:
                if f.exception() is None:
                    return f.result()
                error = f.exception()
        if error is not None and not pending:
            raise error
        self._log_event("LLM 시간 상한 초과(SDK가 재시도)", request, task, limit, attempt)
        raise self.timeout_exc(f"attempt over {limit}s", request=request)

    def close(self) -> None:
        self.pool.shutdown(wait=False)
        self.inner.close()


_TASK_MARK = re.compile(r"\[\[task:([a-z_]+)\]\]")


def _current_request_id() -> str:
    """지금 처리 중인 /chat 요청의 ID(`backend.api.middleware`). 요청 밖이거나 못 읽으면 "-"."""
    try:
        from backend.api.middleware import current_request_id
        return current_request_id()
    except Exception:  # noqa: BLE001 - 로그 한 줄 때문에 LLM 호출이 실패하면 안 된다
        return "-"


def deadline_skip_tasks() -> tuple[str, ...]:
    """`LLM_DEADLINE_SKIP_TASKS`(예: `decision_draft,supervisor,team_*`). 시간 상한(`LLM_DEADLINE_S`)과 hedge를 걸지 않을 단계.
    끝의 `*`는 접두어다. 비면 빈 목록이고 모든 단계에 지금처럼 건다. 틀린 이름은 ValueError다."""
    out: list[str] = []
    for part in (os.environ.get("LLM_DEADLINE_SKIP_TASKS") or "").split(","):
        name = part.strip().lower()
        if not name:
            continue
        if not re.fullmatch(r"[a-z_]+\*?", name):
            raise ValueError(f"LLM_DEADLINE_SKIP_TASKS는 단계 이름 목록이다(끝 *는 접두어): {part!r}")
        out.append(name)
    return tuple(out)


def task_matches(task: str, patterns: tuple[str, ...]) -> bool:
    return any(task.startswith(p[:-1]) if p.endswith("*") else task == p for p in patterns)


def reasoning_by_task() -> dict[str, str]:
    """`LLM_REASONING_BY_TASK`(예: `decompose=low,judge=low`). 나머지 단계는 `LLM_REASONING`을 따른다. 틀린 값은 ValueError다."""
    out: dict[str, str] = {}
    for part in (os.environ.get("LLM_REASONING_BY_TASK") or "").split(","):
        if not part.strip():
            continue
        task, _, effort = part.partition("=")
        task, effort = task.strip().lower(), effort.strip().lower()
        if not task or effort not in REASONING_EFFORTS:
            raise ValueError(f"LLM_REASONING_BY_TASK는 단계=수준 목록이고 수준은 {', '.join(REASONING_EFFORTS)} 중 하나다: {part!r}")
        out[task] = effort
    return out


class TaskReasoningTransport(httpx.BaseTransport):
    """시스템 프롬프트의 `[[task:...]]` 표지를 읽어 그 단계의 추론 수준으로 요청을 고쳐 보낸다. 표지가 없거나 목록에 없는 단계는 그대로 보낸다."""

    def __init__(self, inner: httpx.BaseTransport, efforts: dict[str, str]) -> None:
        self.inner, self.efforts = inner, efforts

    def _effort(self, body: dict) -> str | None:
        for m in body.get("messages") or []:
            if isinstance(m, dict) and m.get("role") == "system":
                found = _TASK_MARK.search(str(m.get("content")))
                if found:
                    return self.efforts.get(found.group(1))
        return None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.read())
        except ValueError:
            return self.inner.handle_request(request)
        effort = self._effort(body) if isinstance(body, dict) else None
        if effort is None:
            return self.inner.handle_request(request)
        body["reasoning"] = {"effort": effort}
        headers = [(k, v) for k, v in request.headers.multi_items() if k.lower() != "content-length"]
        changed = httpx.Request(request.method, request.url, headers=headers, content=json.dumps(body, ensure_ascii=False).encode("utf-8"), extensions=request.extensions)
        return self.inner.handle_request(changed)

    def close(self) -> None:
        self.inner.close()


def _openrouter_client() -> dict[str, Any]:
    """`LLM_DEADLINE_S`(시도별 상한)와 `LLM_TRACE_DETAIL=1`(호출 기록)을 쓸 때만 전용 HTTP 클라이언트를 준다. 둘 다 비면 SDK 기본 클라이언트 그대로다."""
    from backend.services import llm_trace

    seconds = _env_number("LLM_DEADLINE_S", float)
    hedge = _env_number("LLM_HEDGE_S", float) or 0.0  # 상한(`LLM_DEADLINE_S`)이 있을 때만 쓴다
    efforts = reasoning_by_task()
    if seconds is None and not llm_trace.detail_on() and not efforts:
        return {}
    # SDK의 `DefaultHttpxClient`는 다른 HTTP 패키지(httpx2)를 쓸 수 있어 그 전송과 섞이지 않게 httpx로 통일한다. SDK는 호환 클라이언트를 받는다
    opts: dict[str, Any] = {"timeout": httpx.Timeout(600.0, connect=5.0), "follow_redirects": True}
    if llm_trace.detail_on():
        opts["event_hooks"] = llm_trace.http_hooks()
    if seconds is not None:
        opts["transport"] = DeadlineTransport(httpx.HTTPTransport(), seconds, hedge, deadline_skip_tasks())
    if efforts:
        opts["transport"] = TaskReasoningTransport(opts.get("transport") or httpx.HTTPTransport(), efforts)
    return {"http_client": httpx.Client(**opts)}


class FallbackChatModel(BaseChatModel):
    """`primary`가 실패하면 `fallback`을 한 번 부른다. 사용량 정보(비용 집계)는 실제로 답한 쪽 것이 그대로 간다."""

    primary: Any
    fallback: Any
    fallback_name: str = ""

    @property
    def _llm_type(self) -> str:
        return "fallback"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        try:
            ai = self.primary.invoke(messages, stop=stop, **kwargs)
        except (CostCapExceeded, ValueError):
            raise
        except Exception as e:  # noqa: BLE001  제공자 오류(429·5xx·시간 초과 등)는 폴백 모델로 한 번 더
            log.warning("기본 모델 호출이 실패해 폴백 모델(%s)로 다시 시도합니다: %s", self.fallback_name or "?", type(e).__name__)
            ai = self.fallback.invoke(messages, stop=stop, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=ai)])


def _openrouter_extra_body() -> dict[str, Any]:
    """OpenRouter 요청 본문에 더할 값. 둘 다 비어 있으면 빈 dict이고 요청이 지금과 같다. 다른 값은 ValueError다."""
    body: dict[str, Any] = {}
    effort = (os.environ.get("LLM_REASONING") or "").strip().lower()
    if effort:
        if effort not in REASONING_EFFORTS:
            raise ValueError(f"LLM_REASONING은 {', '.join(REASONING_EFFORTS)} 중 하나다: {effort!r}")
        body["reasoning"] = {"effort": effort}
    sort = (os.environ.get("LLM_PROVIDER_SORT") or "").strip().lower()
    if sort:
        if sort not in PROVIDER_SORTS:
            raise ValueError(f"LLM_PROVIDER_SORT는 {', '.join(PROVIDER_SORTS)} 중 하나다: {sort!r}")
        body["provider"] = {"sort": sort}
    return body


ANTHROPIC_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")  # Anthropic `output_config.effort`(claude_cli `--effort`와 같은 값). none은 생각을 끈다(`thinking: disabled`)


def anthropic_efforts() -> tuple[str | None, dict[str, str]]:
    """`LLM_EFFORT`(기본 수준)와 `LLM_EFFORT_BY_TASK`(예: `answer=medium,grounding=medium`). anthropic 공급자에만 쓴다.
    둘 다 비면 (None, {})이고 요청이 지금과 같다(API 기본 수준). none은 effort 대신 `thinking: {"type": "disabled"}`를 보낸다. 틀린 값은 ValueError다."""
    default = (os.environ.get("LLM_EFFORT") or "").strip().lower() or None
    if default is not None and default not in ANTHROPIC_EFFORTS:
        raise ValueError(f"LLM_EFFORT는 {', '.join(ANTHROPIC_EFFORTS)} 중 하나다: {default!r}")
    by_task: dict[str, str] = {}
    for part in (os.environ.get("LLM_EFFORT_BY_TASK") or "").split(","):
        if not part.strip():
            continue
        task, _, effort = part.partition("=")
        task, effort = task.strip().lower(), effort.strip().lower()
        if not task or effort not in ANTHROPIC_EFFORTS:
            raise ValueError(f"LLM_EFFORT_BY_TASK는 단계=수준 목록이고 수준은 {', '.join(ANTHROPIC_EFFORTS)} 중 하나다: {part!r}")
        by_task[task] = effort
    return default, by_task


def _anthropic_http_client() -> Any:
    """anthropic 공급자의 HTTP 클라이언트. `LLM_DEADLINE_S`(시도별 상한)·`LLM_HEDGE_S`(같은 요청 하나 더)와 `LLM_TRACE_DETAIL=1`(호출 기록)을
    openrouter(`_openrouter_client`)와 같은 `DeadlineTransport`로 건다. 셋 다 비면 None이고 SDK 기본 클라이언트 그대로다."""
    from backend.services import llm_trace

    seconds = _env_number("LLM_DEADLINE_S", float)
    if seconds is None and not llm_trace.detail_on():
        return None
    import httpx2  # anthropic SDK는 httpx가 아니라 httpx2 클라이언트만 받는다

    opts: dict[str, Any] = {"timeout": httpx2.Timeout(600.0, connect=5.0), "follow_redirects": True}
    if llm_trace.detail_on():
        opts["event_hooks"] = llm_trace.http_hooks()
    if seconds is not None:
        opts["transport"] = _deadline_transport_httpx2(seconds, _env_number("LLM_HEDGE_S", float) or 0.0, deadline_skip_tasks())
    return httpx2.Client(**opts)


_deadline2_cls: Any = None


def _deadline_transport_httpx2(seconds: float, hedge: float, skip_tasks: tuple[str, ...] = ()) -> Any:
    """`DeadlineTransport`와 같은 동작을 httpx2 전송으로. 넘으면 httpx2.ReadTimeout을 내 anthropic SDK가 재시도한다."""
    import httpx2

    global _deadline2_cls
    if _deadline2_cls is None:
        class DeadlineTransport2(DeadlineTransport, httpx2.BaseTransport):
            timeout_exc = httpx2.ReadTimeout

        _deadline2_cls = DeadlineTransport2
    return _deadline2_cls(httpx2.HTTPTransport(), seconds, hedge, skip_tasks)


_tuned_anthropic_cls: Any = None


def _tuned_anthropic() -> Any:
    """ChatAnthropic에 두 가지를 더한다. (1) 시스템 프롬프트 앞의 `[[task:...]]` 표지로 요청마다 `effort`를 고른다(claude_cli의 `effort_for`와 같은 규칙,
    none이면 생각 끔). (2) `http_client_override`가 있으면 그 HTTP 클라이언트로 부른다(`_anthropic_http_client`)."""
    global _tuned_anthropic_cls
    if _tuned_anthropic_cls is None:
        from functools import cached_property

        import anthropic
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage
        from pydantic import Field

        from backend.services.claude_cli_model import effort_for

        class TaskEffortAnthropic(ChatAnthropic):
            effort_default: str | None = None
            effort_by_task: dict[str, str] = {}
            http_client_override: Any = Field(default=None, exclude=True)

            @cached_property
            def _client(self) -> Any:
                if self.http_client_override is None:
                    return ChatAnthropic._client.func(self)
                return anthropic.Client(**self._client_params, http_client=self.http_client_override)

            def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
                effort = None
                if "effort" not in kwargs and "reasoning_effort" not in kwargs and (self.effort_default or self.effort_by_task):
                    system = "\n".join(str(m.content) for m in self._convert_input(input_).to_messages() if isinstance(m, SystemMessage))
                    effort = effort_for(system, self.effort_default or "", self.effort_by_task)
                    if effort in ANTHROPIC_EFFORTS and effort != "none":
                        kwargs["effort"] = effort
                payload = super()._get_request_payload(input_, stop=stop, **kwargs)
                if effort == "none":
                    payload["thinking"] = {"type": "disabled"}
                return payload

        _tuned_anthropic_cls = TaskEffortAnthropic
    return _tuned_anthropic_cls


def preload_provider_modules() -> list[str]:
    """현재 `LLM_PROVIDER`가 첫 호출에 쓰는 무거운 모듈을 미리 올린다(서버 시작 때). 안 올리면 첫 `/chat`이 import 시간(1 vCPU에서 수 초~십수 초)을 떠안는다.

    데모 모드와 claude_cli는 올릴 것이 없다. 제공자에 필요한 것만 올린다(anthropic은 anthropic·langchain_anthropic, openai·openrouter는 langchain_openai).
    모델 객체나 HTTP 연결은 만들지 않는다(키를 쓰지 않는다). 올린 모듈 이름을 돌려준다."""
    if is_demo_mode():
        return []
    provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if provider == "anthropic":
        names = ["anthropic", "langchain_anthropic"]
    elif provider in ("openai", "openrouter"):
        names = ["langchain_openai"]
    else:
        return []
    for name in names:
        importlib.import_module(name)
    if provider == "anthropic":
        _tuned_anthropic()   # ChatAnthropic 서브클래스 정의와 claude_cli_model import까지(처음 만들 때 한 번)
    return names


def _provider_model(provider: str, model: str, key: str | None) -> BaseChatModel:
    opts = _client_options()
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        default, by_task = anthropic_efforts()
        http_client = _anthropic_http_client()
        if default or by_task or http_client is not None:  # 단계별 추론 수준(`LLM_EFFORT*`)이나 시간 스위치(`LLM_DEADLINE_S`·`LLM_HEDGE_S`)를 쓸 때만
            return _tuned_anthropic()(model=model or DEFAULT_ANTHROPIC_MODEL, api_key=key, effort_default=default, effort_by_task=by_task,
                                      http_client_override=http_client, **opts)
        return ChatAnthropic(model=model or DEFAULT_ANTHROPIC_MODEL, api_key=key, **opts)
    if provider == "openai":
        if not model:
            raise ValueError("LLM_PROVIDER=openai이면 LLM_MODEL이 필요합니다")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=key, **opts)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        base_url = (os.environ.get("LLM_BASE_URL") or "").strip() or OPENROUTER_BASE_URL
        extra = _openrouter_extra_body()
        return ChatOpenAI(model=model or DEFAULT_OPENROUTER_MODEL, api_key=key, base_url=base_url, **opts, **({"extra_body": extra} if extra else {}), **_openrouter_client())
    if provider == "claude_cli":
        from backend.services.claude_cli_model import ClaudeCliChatModel

        return ClaudeCliChatModel(model=model or DEFAULT_ANTHROPIC_MODEL)
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {provider!r} (anthropic, openai, openrouter 또는 claude_cli)")


def _real_chat_model() -> BaseChatModel:
    key = os.environ.get("LLM_API_KEY")
    provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()
    primary = _provider_model(provider, model, key)
    fb = (os.environ.get("LLM_FALLBACK_MODEL") or "").strip()
    if not fb or fb == (model or getattr(primary, "model", None) or getattr(primary, "model_name", "")):
        return primary
    return FallbackChatModel(primary=primary, fallback=_provider_model(provider, fb, key), fallback_name=fb)


def is_demo_mode() -> bool:
    """`LLM_API_KEY`가 없거나 `DEMO_MODE=1`이면 데모 모드(재생·가짜 모델, 외부 호출 없음). `LLM_PROVIDER=claude_cli`는 키 없이도 실제 모델이다(`DEMO_MODE=1`이면 데모)."""
    if env_flag("DEMO_MODE"):
        return True
    if (os.environ.get("LLM_PROVIDER") or "").strip().lower() == "claude_cli":
        return False
    return not os.environ.get("LLM_API_KEY")


def run_config(
    graph_name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    configurable: dict[str, Any] | None = None,
    cost_cap_usd: float | None = None,
) -> dict:
    """그래프 한 번 실행에 넘길 LangChain config(`graph.invoke(inp, config)`, `stream_events(..., config=config)`).

    - `callbacks`: 비용 집계(`CostTracker`, 항상)와 Langfuse 핸들러(키가 있을 때만). 그래프 안의 모든 노드·LLM 호출에 따라간다.
    - `tags`: `mode:demo`/`mode:real`, `graph:<이름>`. `metadata`: Langfuse 세션·사용자·트레이스 이름과 `run_mode`, `graph`, `thread_id`.
    - `session_id`를 안 주면 `thread_id`를 세션으로 쓴다.
    - `cost_cap_usd`를 안 주면 `LLM_COST_CAP_USD`(없으면 기본값)를 따른다.
    """
    mode = "demo" if is_demo_mode() else "real"
    meta: dict[str, Any] = {"run_mode": mode, "graph": graph_name}
    if thread_id:
        meta["thread_id"] = str(thread_id)
    # Evaluation traces are explicitly opted into; ordinary requests remain
    # fail-closed unless content capture is enabled by the operator.
    evaluation_mode = bool(metadata and metadata.get("eval"))
    meta.update(tracing.trace_metadata(session_id=session_id or thread_id, user_id=user_id, name=graph_name,
                                      allow_evaluation=evaluation_mode))
    meta.update(tracing.sanitize_metadata(metadata))
    tracker = CostTracker(
        cost_cap_usd if cost_cap_usd is not None else cost_cap_from_env(),
        default_model=os.environ.get("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL,
    )
    callbacks: list[Any] = [tracker]
    handler = tracing.get_handler(allow_evaluation=evaluation_mode)
    if handler is not None:
        callbacks.append(handler)
    recorder = llm_trace.handler()  # `llm_trace.capture()` 안에서만 있다. 평소에는 None
    if recorder is not None:
        callbacks.append(recorder)
    config: dict[str, Any] = {
        "callbacks": callbacks,
        "metadata": meta,
        "tags": [f"mode:{mode}", f"graph:{graph_name}"],
        "run_name": graph_name,
    }
    if configurable:
        config["configurable"] = dict(configurable)
    return config


def finish_run(config: dict | None) -> dict:
    """실행이 끝난 뒤(성공·실패 모두) 부른다. 비용·토큰 합계를 돌려주고, Langfuse가 켜져 있으면 트레이스에 `cost_usd` 점수로 남긴다.

    `run_config`가 만든 config가 아니면 빈 합계를 돌려준다. 예외를 던지지 않는다.
    """
    summary = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0, "cap_usd": None, "trace_id": None}
    try:
        for cb in (config or {}).get("callbacks") or []:
            if isinstance(cb, CostTracker):
                summary.update(cb.summary())
        for cb in (config or {}).get("callbacks") or []:
            if isinstance(cb, CostTracker):
                continue
            trace_id = getattr(cb, "last_trace_id", None)
            if trace_id:
                summary["trace_id"] = trace_id
                if summary["calls"]:
                    tracing.record_score(cb, "cost_usd", summary["cost_usd"], comment=f"{summary['input_tokens']} in / {summary['output_tokens']} out")
    except Exception as e:  # noqa: BLE001 - 기록 실패가 질문을 망치면 안 된다
        log.warning("실행 비용 기록 실패: %s", e)
    return summary
