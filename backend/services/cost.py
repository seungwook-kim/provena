"""질문 한 건의 토큰·비용 집계와 비용 상한.

`CostTracker`는 LangChain 콜백이다. 그래프 실행의 `config["callbacks"]`에 한 번 넣으면 그래프 안의 모든 LLM 호출(서브그래프 포함)에 따라간다.
- 호출이 끝날 때마다 모델이 돌려준 사용량(`usage_metadata`, 없으면 `llm_output["token_usage"]`)을 합산한다.
- 합계가 상한 이상이면 다음 LLM 호출이 시작되기 전에 `CostCapExceeded`를 던져 그 실행의 이후 호출을 막는다.
  이미 보낸 호출은 되돌릴 수 없으므로 상한을 넘기는 마지막 한 번은 나갈 수 있다.
- 모델이 `response_metadata["total_cost_usd"]`로 비용을 직접 알려 주면(claude_cli: CLI가 보고한 API 환산 비용, 캐시 단가 반영) 단가표 대신 그 값을 합산한다.
- 가짜 모델(데모 모드)은 사용량을 안 돌려주므로 비용은 0이다.

환경변수:
- `LLM_COST_CAP_USD`: 질문 한 건의 비용 상한(달러). 없거나 비면 기본 `DEFAULT_COST_CAP_USD`. `0`, `off`, `none`이면 상한 없음.
- `LLM_PRICES_FILE`: 단가표 JSON 경로(기본 `llm_prices.json`). 형식은 그 파일을 본다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

log = logging.getLogger(__name__)

DEFAULT_COST_CAP_USD = 0.05  # PRD 목표(질문 1건 평균 $0.01 이하)의 5배. 평균이 아니라 한 건의 폭주를 막는 값
DEFAULT_PRICES_FILE = Path(__file__).with_name("llm_prices.json")
_CAP_OFF = {"0", "off", "none", "false", "no", "끔"}


class CostCapExceeded(RuntimeError):
    """한 질문의 LLM 비용이 상한에 닿아 더 부를 수 없다."""

    def __init__(self, spent_usd: float, cap_usd: float) -> None:
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(f"LLM 비용 상한 초과: ${spent_usd:.6f} >= ${cap_usd:.6f} (LLM_COST_CAP_USD)")


def load_prices(path: str | os.PathLike | None = None) -> dict:
    """단가표(JSON)를 읽는다. 못 읽으면 빈 표(모든 모델 비용 0)로 두고 경고만 남긴다."""
    p = Path(path or os.environ.get("LLM_PRICES_FILE") or DEFAULT_PRICES_FILE)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("LLM 단가표를 읽지 못했다(%s): %s. 비용은 0으로 센다", p, e)
        return {}


def normalize_model_id(model: str | None) -> str:
    """OpenRouter 같은 중개 서비스의 모델 이름을 단가표 이름으로 맞춘다: 소문자, `벤더/` 접두어와 `:free` 같은 변형 꼬리를 떼고 점을 대시로.

    예: `anthropic/claude-haiku-5.5` -> `claude-haiku-5-5`, `openai/gpt-6-luna:free` -> `gpt-6-luna`.
    """
    m = (model or "").strip().lower().split(":", 1)[0]
    if "/" in m:
        m = m.rsplit("/", 1)[1]
    return m.replace(".", "-")


def _lookup(models: dict, name: str) -> dict | None:
    if name in models:
        return models[name]
    keys = [k for k in models if name.startswith(k)]
    return models[max(keys, key=len)] if keys else None


def price_for(model: str | None, prices: dict) -> tuple[float, float]:
    """(입력, 출력) 100만 토큰당 달러. 정확히 같은 이름, 가장 긴 접두어, 그다음 OpenRouter식 이름을 정규화한 같은 규칙(`normalize_model_id`), 없으면 `default`."""
    models = prices.get("models") or {}
    row = _lookup(models, model) if model else None
    if row is None and model:
        norm_models = {normalize_model_id(k): v for k, v in models.items()}
        row = _lookup(norm_models, normalize_model_id(model))
    row = row or prices.get("default") or {}
    return float(row.get("input", 0.0)), float(row.get("output", 0.0))


def cost_usd(model: str | None, input_tokens: int, output_tokens: int, prices: dict | None = None) -> float:
    p_in, p_out = price_for(model, prices if prices is not None else load_prices())
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def cost_cap_from_env() -> float | None:
    """상한(달러). None이면 상한 없음."""
    raw = (os.environ.get("LLM_COST_CAP_USD") or "").strip()
    if not raw:
        return DEFAULT_COST_CAP_USD
    if raw.lower() in _CAP_OFF:
        return None
    try:
        v = float(raw)
    except ValueError:
        log.warning("LLM_COST_CAP_USD=%r를 숫자로 읽지 못했다. 기본 $%s를 쓴다", raw, DEFAULT_COST_CAP_USD)
        return DEFAULT_COST_CAP_USD
    return v if v > 0 else None


def _usage_of(response: Any) -> list[tuple[str | None, int, int, float | None]]:
    """LLMResult에서 (모델 이름, 입력 토큰, 출력 토큰, 보고된 비용)을 호출 단위로 뽑는다. 보고된 비용은 모델이 직접 알려 준 값(`response_metadata["total_cost_usd"]`, claude_cli)이고 없으면 None."""
    out: list[tuple[str | None, int, int, float | None]] = []
    for gens in getattr(response, "generations", None) or []:
        for g in gens:
            msg = getattr(g, "message", None)
            um = getattr(msg, "usage_metadata", None)
            if um:
                meta = getattr(msg, "response_metadata", None) or {}
                name = meta.get("model_name") or meta.get("model")
                reported = meta.get("total_cost_usd")
                out.append((name, int(um.get("input_tokens") or 0), int(um.get("output_tokens") or 0), float(reported) if isinstance(reported, (int, float)) else None))
    if out:
        return out
    llm_output = getattr(response, "llm_output", None) or {}
    tu = llm_output.get("token_usage") or llm_output.get("usage") or {}
    i = tu.get("prompt_tokens", tu.get("input_tokens", 0)) or 0
    o = tu.get("completion_tokens", tu.get("output_tokens", 0)) or 0
    if i or o:
        out.append((llm_output.get("model_name") or llm_output.get("model"), int(i), int(o), None))
    return out


class CostTracker(BaseCallbackHandler):
    """한 질문(한 그래프 실행)의 토큰·비용 합계. 상한 이상이면 다음 LLM 호출을 막는다."""

    raise_error = True  # 콜백에서 던진 예외를 LangChain이 삼키지 않고 호출 쪽으로 올린다

    def __init__(self, cap_usd: float | None = None, *, prices: dict | None = None, default_model: str | None = None) -> None:
        self.cap_usd = cap_usd
        self.prices = prices if prices is not None else load_prices()
        self.default_model = default_model
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.calls = 0
        self._lock = threading.Lock()

    def _check(self) -> None:
        with self._lock:
            if self.cap_usd is not None and self.cost_usd >= self.cap_usd:
                raise CostCapExceeded(self.cost_usd, self.cap_usd)

    def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._check()

    def on_llm_start(self, serialized: dict[str, Any], prompts: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._check()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            for model, i_tok, o_tok, reported in _usage_of(response):
                self.calls += 1
                self.input_tokens += i_tok
                self.output_tokens += o_tok
                self.cost_usd += reported if reported is not None else cost_usd(model or self.default_model, i_tok, o_tok, self.prices)

    def summary(self) -> dict:
        with self._lock:
            return {
                "cost_usd": round(self.cost_usd, 8),
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "calls": self.calls,
                "cap_usd": self.cap_usd,
            }
