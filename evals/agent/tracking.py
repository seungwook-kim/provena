"""평가 실행기의 Langfuse 연결 (G6): 평가 실행이 트레이스로 보이고, 지표가 점수로 붙는다.

- `eval_config(...)`: `backend.services.llm.run_config`로 만든 config. 문항마다 트레이스 하나, 같은 평가 실행은 같은 세션(`run_id`)이다.
  비용 집계(CostTracker)도 같이 따라붙는다. 키(`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`)가 없으면 Langfuse 쪽은 아무 일도 하지 않는다(콜백 없음).
- `record_item_scores(config, scores)`: 그 문항 트레이스에 점수를 붙인다(`eval/<이름>`).
- `record_run_scores(run_id, metrics)`: 평가 실행 전체(세션)에 집계 지표를 점수로 붙인다(`eval/<이름>`, 값이 None인 지표는 건너뜀).
- 어느 쪽도 예외를 던지지 않는다. 점수 기록 실패가 평가를 망치면 안 된다.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.services import tracing
from backend.services.cost import CostTracker
from backend.services.llm import finish_run, run_config

log = logging.getLogger(__name__)

SCORE_PREFIX = "eval/"


def new_run_id(name: str) -> str:
    return f"eval-{name}-{time.strftime('%Y%m%d-%H%M%S')}"


def eval_config(eval_name: str, item_id: str, *, run_id: str, thread_id: str, metadata: dict[str, Any] | None = None) -> dict:
    """그래프 `invoke`에 넘길 config(체크포인터용 thread_id 포함)."""
    meta = {"eval": eval_name, "item_id": str(item_id), "run_id": run_id}
    meta.update(metadata or {})
    return run_config(
        f"eval:{eval_name}",
        session_id=run_id,
        user_id="eval",
        thread_id=thread_id,
        metadata=meta,
        configurable={"thread_id": thread_id},
    )


def handler_of(config: dict | None) -> Any | None:
    """config 안의 Langfuse 콜백 핸들러(없으면 None)."""
    for cb in (config or {}).get("callbacks") or []:
        if not isinstance(cb, CostTracker):
            return cb
    return None


def finish_item(config: dict | None, scores: dict[str, float | None] | None = None) -> dict:
    """문항 하나가 끝난 뒤: 비용 점수를 남기고(`finish_run`), 문항 지표를 점수로 붙인다. 비용·토큰 합계를 돌려준다."""
    summary = finish_run(config)
    if scores:
        try:
            tracing.record_scores(handler_of(config), scores, prefix=SCORE_PREFIX)
        except Exception as e:  # noqa: BLE001
            log.warning("문항 점수 기록 실패: %s", e)
    return summary


def record_run_scores(run_id: str, metrics: dict[str, Any], *, comment: str | None = None) -> int:
    """집계 지표(숫자만)를 세션 점수로 붙인다. 붙인 개수를 돌려준다(키가 없으면 0)."""
    n = 0
    try:
        for name, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if tracing.record_session_score(run_id, f"{SCORE_PREFIX}{name}", float(value), comment=comment):
                n += 1
        if n:
            tracing.flush()
    except Exception as e:  # noqa: BLE001
        log.warning("집계 점수 기록 실패: %s", e)
    return n
