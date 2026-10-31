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
- `LLM_BASE_URL`: openrouter의 API 주소를 바꾼다(기본 `https://openrouter.ai/api/v1`). OpenAI 호환 주소면 된다.
  비용 단가는 OpenRouter id(`벤더/이름`, 점)를 단가표 이름으로 맞춰 찾는다(`cost.normalize_model_id`).

LLM 호출의 트레이스와 비용 기록도 이 파일 한 곳으로 모은다. 그래프를 돌릴 때 `run_config(...)`가 만든 config를 `invoke`/`stream`에 넘기고,
끝나면 `finish_run(config)`을 부른다.
- Langfuse 트레이스: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`가 있을 때만(`tracing.py`). 없으면 트레이스 없이 그대로 돈다.
- 비용 상한: `LLM_COST_CAP_USD`(`cost.py`). 한 질문의 LLM 비용이 상한에 닿으면 다음 호출에서 `CostCapExceeded`.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from backend.services import tracing
from backend.services.demo_replay import env_flag
from backend.services.cost import CostCapExceeded, CostTracker, cost_cap_from_env

log = logging.getLogger(__name__)

__all__ = ["CostCapExceeded", "finish_run", "get_chat_model", "is_demo_mode", "run_config"]

DEFAULT_FAKE_RESPONSES = ["(가짜 모델 응답) 합성 시험용 답변입니다. 실제 핸드북 근거가 아닙니다."]
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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


def _real_chat_model() -> BaseChatModel:
    key = os.environ.get("LLM_API_KEY")
    provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model or DEFAULT_ANTHROPIC_MODEL, api_key=key)
    if provider == "openai":
        if not model:
            raise ValueError("LLM_PROVIDER=openai이면 LLM_MODEL이 필요합니다")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=key)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        base_url = (os.environ.get("LLM_BASE_URL") or "").strip() or OPENROUTER_BASE_URL
        return ChatOpenAI(model=model or DEFAULT_OPENROUTER_MODEL, api_key=key, base_url=base_url)
    if provider == "claude_cli":
        from backend.services.claude_cli_model import ClaudeCliChatModel

        return ClaudeCliChatModel(model=model or DEFAULT_ANTHROPIC_MODEL)
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {provider!r} (anthropic, openai, openrouter 또는 claude_cli)")


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
    meta.update(tracing.trace_metadata(session_id=session_id or thread_id, user_id=user_id, name=graph_name))
    meta.update(metadata or {})
    tracker = CostTracker(
        cost_cap_usd if cost_cap_usd is not None else cost_cap_from_env(),
        default_model=os.environ.get("LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL,
    )
    callbacks: list[Any] = [tracker]
    handler = tracing.get_handler()
    if handler is not None:
        callbacks.append(handler)
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
