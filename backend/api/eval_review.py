"""평가 전용 합동 검토 단일 모드 `POST /admin/eval/review` (결정 0104, 사전 등록 62.41).

서비스의 합동 검토는 팀 에이전트 구성(멀티)이다. 이 엔드포인트는 그 팀 구성과 같은 요청을 에이전트 하나가 검토하는 기준선을 운영에서 재려고 둔 **측정 전용 통로**다.
`/chat`, 질문 그래프, 합동 검토 그래프는 이 파일을 부르지 않고 이 파일의 코드는 서비스 경로에서 쓰이지 않는다. 일반 사용자에게 열리지 않는다.

- 열리는 조건: 환경 변수 `EVAL_REVIEW_SINGLE=1`(요청마다 읽음). 아니면 권한 검사보다 먼저 404 `not_found`(존재를 드러내지 않음). 서비스 값(`SERVICE_ENV`)에 넣지 않는다.
  측정 리비전에서만 켜고 측정이 끝나면 지운다.
- 권한: 로그인한 관리자(저장소의 현재 역할로 판정) + CSRF. 인증 없음 401, 관리자 아님 403, CSRF 불일치 403 `csrf_failed`.
- 본문: `{"message": str(1~4000자), "as_of": "YYYY-MM-DD" | null, "search": "same" | "undivided"}`. 모르는 칸은 422.
  `same`은 팀과 같은 자료를 한 검토자에게, `undivided`는 나누지 않은 검색(같은 총 자료 수)이다(`backend/graph/departments/single_review.py`).
- 저장 없음: 쟁점표 저장소, 승인함, 대화 목록, 체크포인터를 부르지 않는다. 승인 대기를 만들지 않는다.
- 상한: 요청당 LLM 비용 상한은 `LLM_COST_CAP_USD`(넘으면 429 `limit_exceeded`), 하루 호출 수 상한은 `EVAL_REVIEW_SINGLE_MAX_PER_DAY`(기본 200, 프로세스 안, 넘으면 429 `rate_limited`).
- 기록: 호출·거절마다 WARNING 로그 한 줄(`eval_review_single ...`). 요청 문장은 쓰지 않고 sha256 앞 12자만 남긴다. Langfuse 추적은 `review_single_eval`
  (metadata `eval: true`, `search`)로 남는다(끄지 않는다). DB 감사 표는 만들지 않는다.
- 응답은 SSE가 아니라 JSON 한 번이다: `status`, `search`, `issue_rows`(쟁점 문장 포함), `unreviewed`, `clarify_question`, `retrieved`, `llm_calls`,
  `usage`, `cost_by_step`·`cost_by_step_total_usd`·`embed_*`, `latency_ms`, `revision`, `request_id`.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from backend.api.errors import ApiError
from backend.api.middleware import current_request_id, log_llm_usage
from backend.api.routes import COST_CAP_ERROR, DATE_PATTERN, MSG_INTERNAL, MSG_LIMIT, model_name
from backend.auth import AuthUser, TokenRevocationStore, create_require_admin_dependency, require_csrf
from backend.graph.departments import single_review
from backend.graph.mcp_retriever import default_retriever
from backend.graph.service_profile import SharedChatModel
from backend.services import step_cost
from backend.services.llm import finish_run, run_config

log = logging.getLogger(__name__)

FLAG_ENV = "EVAL_REVIEW_SINGLE"
MAX_PER_DAY_ENV = "EVAL_REVIEW_SINGLE_MAX_PER_DAY"
DEFAULT_MAX_PER_DAY = 200
GRAPH_NAME = "review_single_eval"
MSG_RATE = "평가용 단일 검토의 하루 호출 상한에 닿았습니다."


class EvalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 모르는 칸은 422
    message: str = Field(min_length=1, max_length=4000)
    as_of: str | None = Field(default=None, pattern=DATE_PATTERN)
    search: Literal["same", "undivided"] = "same"


def eval_review_enabled() -> bool:
    return (os.environ.get(FLAG_ENV) or "").strip() == "1"


def max_per_day() -> int:
    raw = (os.environ.get(MAX_PER_DAY_ENV) or "").strip()
    try:
        return int(raw) if raw else DEFAULT_MAX_PER_DAY
    except ValueError:
        return DEFAULT_MAX_PER_DAY


class DailyCounter:
    """프로세스 안 하루(UTC) 호출 수. 서버가 다시 뜨거나 인스턴스가 여럿이면 각자 센다(보조 안전장치이고 비용 상한이 본선이다)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: str | None = None
        self._n = 0

    def take(self, limit: int) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if self._day != today:
                self._day, self._n = today, 0
            if self._n >= limit:
                return False
            self._n += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._day, self._n = None, 0


DAILY = DailyCounter()


def message_sha(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]


def create_eval_review_router(*, store: Any, secret: str | None = None, revocation_store: TokenRevocationStore | None = None) -> APIRouter:
    """`create_api_router`와 같은 `store`, `secret`을 넘긴다. 모델·검색기는 시험이 `app.state.eval_review_llm` 등으로 갈아 끼울 수 있다(기본은 서비스 모델과 검색기)."""
    router = APIRouter()
    admin_dependency = create_require_admin_dependency(store=store, secret=secret, revocation_store=revocation_store)
    shared_llm = SharedChatModel()

    def denied(request: Request, reason: str, status: int, user: AuthUser | None = None) -> None:
        log.warning("eval_review_single denied reason=%s status=%d request_id=%s user_id=%s", reason, status, current_request_id(),
                    str(user.user_id) if user is not None else "-")

    def guard(request: Request) -> AuthUser:
        """플래그(404) -> 관리자(401·403) -> CSRF(403) 순서. 어느 쪽이든 거절은 한 줄 남긴다."""
        if not eval_review_enabled():
            denied(request, "flag_off", 404)
            raise ApiError(404, "not_found", "찾을 수 없습니다.")
        try:
            user = admin_dependency(request)
        except Exception as exc:
            denied(request, "not_admin", getattr(exc, "status_code", 403))
            raise
        try:
            require_csrf(request)
        except Exception as exc:
            denied(request, "csrf", getattr(exc, "status_code", 403), user)
            raise
        return user

    @router.post("/admin/eval/review")
    async def eval_review(req: EvalReviewRequest, request: Request, user: AuthUser = Depends(guard)) -> dict:
        request_id = current_request_id()
        sha = message_sha(req.message)
        if not DAILY.take(max_per_day()):
            denied(request, "daily_limit", 429, user)
            raise ApiError(429, "rate_limited", MSG_RATE)
        llm = getattr(request.app.state, "eval_review_llm", None) or shared_llm
        retriever = getattr(request.app.state, "eval_review_retriever", None) or default_retriever
        wide = getattr(request.app.state, "eval_review_wide_retriever", None)   # None이면 검색 함수를 직접 부른다(k 40은 MCP 한도 밖)
        user_id = str(user.user_id)

        def work() -> dict:
            started = time.perf_counter()
            cfg = run_config(GRAPH_NAME, user_id=user_id, thread_id=f"eval-single:{request_id}",
                             metadata={"eval": True, "search": req.search})
            meter, meter_token = step_cost.begin()
            status = "error"
            try:
                out = single_review.run_single(req.message, req.as_of, retriever=retriever, llm=llm, config=cfg, search=req.search, wide_retriever=wide)
                status = out["status"]
            except Exception as exc:   # noqa: BLE001 - 원문은 로그에 남기지 않고 종류만 남긴다
                summary = finish_run(cfg)
                step_cost.end(meter_token)
                latency = (time.perf_counter() - started) * 1000
                log_llm_usage(model=model_name(), summary=summary, latency_ms=latency, route="/admin/eval/review", request_id=request_id)
                log.warning("eval_review_single request_id=%s user_id=%s search=%s as_of=%s status=error rows=0 calls=%s cost_usd=%.6f message_sha=%s error=%s",
                            request_id, user_id, req.search, req.as_of, summary.get("calls"), float(summary.get("cost_usd") or 0.0), sha, type(exc).__name__)
                raise
            summary = finish_run(cfg)
            try:
                extra = meter.snapshot(summary.get("cost_by_step"))
            except Exception as exc:   # noqa: BLE001 - 집계 실패가 응답을 막지 않는다
                log.warning("단계별 비용 집계 실패: %s", type(exc).__name__)
                extra = {}
            step_cost.end(meter_token)
            latency = (time.perf_counter() - started) * 1000
            log_llm_usage(model=model_name(), summary=summary, latency_ms=latency, route="/admin/eval/review", request_id=request_id)
            log.warning("eval_review_single request_id=%s user_id=%s search=%s as_of=%s status=%s rows=%d calls=%s cost_usd=%.6f message_sha=%s",
                        request_id, user_id, req.search, req.as_of, status, len(out["issue_rows"]), summary.get("calls"),
                        float(summary.get("cost_usd") or 0.0), sha)
            return {
                "status": status, "search": req.search, "issue_rows": out["issue_rows"], "unreviewed": out["unreviewed"],
                "clarify_question": out["clarify_question"], "team_status": out["team_status"], "retrieved": out["retrieved"],
                "llm_calls": summary.get("calls"),
                "usage": {k: summary.get(k) for k in ("input_tokens", "output_tokens", "cost_usd", "calls")},
                **extra, "latency_ms": round(latency, 1), "revision": os.environ.get("K_REVISION"), "request_id": request_id,
            }

        try:
            return await run_in_threadpool(work)
        except ApiError:
            raise
        except Exception as exc:   # noqa: BLE001
            if type(exc).__name__ == COST_CAP_ERROR:
                raise ApiError(429, "limit_exceeded", MSG_LIMIT) from exc
            raise ApiError(500, "internal_error", MSG_INTERNAL) from exc

    return router
