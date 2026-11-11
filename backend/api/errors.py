"""오류 응답 규약 (SDD 4-4).

모든 오류는 한 가지 모양이다: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`. 필요하면 `details`가 붙는다.
화면과 업무시스템은 HTTP 상태가 아니라 `code`로 분기한다. `request_id`는 응답 헤더 `X-Request-ID`와 같다.
화면 호환을 위해 본문 맨 위에 `message`와 같은 `detail` 문자열도 함께 낸다(422는 고정 문구이고 입력값은 넣지 않는다).

| code | HTTP | 뜻 |
|---|---|---|
| unauthorized | 401 | 로그인 안 됨, 토큰 만료 |
| forbidden | 403 | 관리자 전용 |
| csrf_failed | 403 | CSRF 헤더와 쿠키 불일치 |
| not_found | 404 | 없는 자원(남의 thread도 없는 것처럼 404) |
| validation_error | 422 | 요청 형식 오류 |
| conflict | 409 | 상태 충돌 |
| manual_sync_not_supported | 501 | `POST /admin/sync`에서 `dry_run=false`(실제 수동 수집 방식 미정, 정시 수집 workflow를 쓴다) |
| approval_pending | 409 | 승인 대기 중인 thread에 새 질문 |
| not_approved | 409 | 승인되지 않은 결정표 실행 (결정표 라우트가 아래 규칙으로 낸다, `backend/graph/decision/rules.py`) |
| signup_unverified | 403 | 이메일 인증을 마치지 않은 가입 신청으로 로그인(`backend/auth.py`, 이어하기 안내) |
| rate_limited | 429 | 로그인 시도 제한 |
| limit_exceeded | 429 | LLM 비용 상한 초과 (SSE `error` 이벤트의 data.code도 같은 값) |
| not_configured | 503 | 서버 설정이나 저장소를 쓸 수 없음 |
| internal_error | 500 | 예상 못 한 오류(내용은 로그에만) |
| no_results | - | 근거를 못 찾아 거절 (SSE `done` 이벤트의 data.code). 검색 색인이 적재되지 않은 경우도 같다 |

옮기는 규칙
- `ApiError(status, code, message)`는 그대로 쓴다.
- `HTTPException`의 `detail`이 `{"reason", "message"}`이면(결정표·승인 라우트) `reason`을 code로, `message`를 message로 옮긴다.
- `detail`이 문자열이면 HTTP 상태로 code를 정하고 문자열을 message로 쓴다. 403 중 CSRF 검사 실패 문구는 `csrf_failed`다.
- 본문 검증 오류(`RequestValidationError`)는 422 `validation_error`이고, `details`에는 입력값을 넣지 않고 `loc`, `msg`, `type`만 담는다(비밀번호 보호).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.middleware import current_request_id

log = logging.getLogger(__name__)

STATUS_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
    409: "conflict", 413: "payload_too_large", 422: "validation_error", 429: "rate_limited",
    500: "internal_error", 502: "bad_gateway", 503: "not_configured",
}
# backend/auth.py의 require_csrf가 내는 문구. auth.py는 HTTPException만 쓰므로 문구로 구분한다
CSRF_FAILED_DETAIL = "CSRF 검증에 실패했습니다."
VALIDATION_MESSAGE = "요청 형식이 올바르지 않습니다."


class ApiError(Exception):
    """엔드포인트가 던지는 오류. `code`는 모듈 설명의 표 값이다."""

    def __init__(self, status: int, code: str, message: str, *, headers: dict[str, str] | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers
        self.details = details


def error_body(code: str, message: str, *, details: Any = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": current_request_id()}
    if details is not None:
        body["details"] = details
    return {"detail": message, "error": body}   # detail: 아직 `body.detail` 문자열을 읽는 화면용


def code_and_message(status: int, detail: Any) -> tuple[str, str]:
    """`HTTPException`의 상태와 `detail`을 (code, message)로 옮긴다. 규칙은 모듈 설명."""
    if isinstance(detail, dict) and isinstance(detail.get("reason"), str) and detail["reason"]:
        return detail["reason"], str(detail.get("message") or "")
    message = detail if isinstance(detail, str) else ""
    if status == 403 and message == CSRF_FAILED_DETAIL:
        return "csrf_failed", message
    return STATUS_CODES.get(status, "internal_error" if status >= 500 else "bad_request"), message


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, details=exc.details), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = code_and_message(exc.status_code, exc.detail)
        return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))} for e in exc.errors()]
        return JSONResponse(error_body("validation_error", VALIDATION_MESSAGE, details=jsonable_encoder(details)), status_code=422)
