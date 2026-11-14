"""요청 ID와 요청 로그 (SDD 4-4).

- 모든 응답에 `X-Request-ID` 헤더를 붙인다. 들어온 `X-Request-ID`가 `^[A-Za-z0-9._-]{8,64}$`이면 그대로 쓰고, 아니면 새로 만든다.
- 요청이 끝나면 한 줄을 남긴다: 요청 ID, 메서드, 경로, 상태, 걸린 시간(ms). SSE 응답은 스트림이 끝난 뒤의 시간이다.
  질의 문자열과 본문은 로그에 쓰지 않는다(질문 내용, 비밀번호 보호).
- 순수 ASGI 미들웨어다. `BaseHTTPMiddleware`는 응답 본문을 감싸 SSE를 버퍼링할 수 있어 쓰지 않는다.
- 경로에 NUL 문자(`%00`)가 있으면 라우터·DB에 닿기 전에 404 `not_found`로 답한다(Postgres는 NUL이 든 문자열을 못 받아 500·503이 났다).
- 예외 처리기 밖으로 나온 오류는 `internal_error` 500으로 마무리하고, 내용은 로그에만 남긴다.
- 사용 모델, 토큰 수, 비용은 LLM을 부르는 엔드포인트가 `log_llm_usage`로 따로 남긴다.
- 모든 응답에 보안 헤더를 붙인다: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`. `Strict-Transport-Security`는 https 요청에만 붙인다
  (요청 scheme 또는 프록시가 붙인 `X-Forwarded-Proto`의 첫 값). 응답이 이미 같은 헤더를 정했으면 그 값을 둔다.
  화면(`/`)과 `/docs`를 깨뜨릴 수 있어 Content-Security-Policy는 붙이지 않는다.
- GET 전용 API 경로(예: `/threads`)에 HEAD가 오면 405 `method_not_allowed`와 `Allow` 헤더로 답한다. 전에는 HEAD 경로가 없어
  `backend/main.py` 끝의 정적 파일 마운트로 떨어져 404가 났다(놓친 것 C-24). HEAD 응답은 규격상 본문을 보내지 않는다.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("backend.request")

HEADER = "X-Request-ID"
_HEADER_KEY = HEADER.lower().encode("latin-1")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)
HSTS_HEADER: tuple[bytes, bytes] = (b"strict-transport-security", b"max-age=31536000")


def _is_https(scope: Scope) -> bool:
    """요청 scheme이 https이거나 프록시가 붙인 X-Forwarded-Proto의 첫 값이 https면 참."""
    if scope.get("scheme") == "https":
        return True
    proto = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-forwarded-proto"), "")
    return proto.split(",")[0].strip().lower() == "https"


def _with_security_headers(headers: list[tuple[bytes, bytes]], https: bool) -> list[tuple[bytes, bytes]]:
    present = {k.lower() for k, _ in headers}
    extra = [*SECURITY_HEADERS, HSTS_HEADER] if https else list(SECURITY_HEADERS)
    return [*headers, *((k, v) for k, v in extra if k not in present)]


def current_request_id() -> str:
    """지금 처리 중인 요청의 ID. 요청 밖에서는 "-"."""
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == _HEADER_KEY), "")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        https = _is_https(scope)
        token = _request_id.set(rid)
        started = time.perf_counter()
        status = 500
        began = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, began
            if message["type"] == "http.response.start":
                status, began = message["status"], True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_KEY]
                headers = _with_security_headers(headers, https)
                message = {**message, "headers": [*headers, (_HEADER_KEY, rid.encode("latin-1"))]}
            await send(message)

        try:
            if "\x00" in scope.get("path", "") or b"%00" in scope.get("raw_path", b"").lower():
                await _send_not_found(send_wrapper, rid)
                return
            allowed = _head_without_route(scope)
            if allowed:
                await send_wrapper({"type": "http.response.start", "status": 405,
                                    "headers": [(b"allow", ", ".join(allowed).encode()), (b"content-type", b"application/json"),
                                                (b"content-length", b"0")]})
                await send_wrapper({"type": "http.response.body", "body": b""})
                return
            await self.app(scope, receive, send_wrapper)
        except Exception:  # noqa: BLE001 - 예외 처리기 밖으로 나온 오류도 요청 ID가 붙은 500으로 마무리한다
            log.exception("처리되지 않은 오류 request_id=%s", rid)
            if not began:
                msg = "서버 내부 오류입니다."
                body = json.dumps(   # errors.error_body와 같은 모양(화면 호환용 detail 포함)
                    {"detail": msg, "error": {"code": "internal_error", "message": msg, "request_id": rid}}, ensure_ascii=False
                ).encode("utf-8")
                await send_wrapper({"type": "http.response.start", "status": 500,
                                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            log.info("request id=%s method=%s path=%s status=%s ms=%.1f",
                     rid, scope.get("method"), scope.get("path"), status, (time.perf_counter() - started) * 1000)
            _request_id.reset(token)


_CATCH_ALL = "/{path:path}"   # backend/main.py의 화면·없는 경로 받이. 진짜 경로가 아니므로 판정에서 뺀다


def _head_without_route(scope: Scope) -> list[str]:
    """HEAD 요청인데 HEAD를 받는 경로는 없고 GET을 받는 API 경로가 있으면 그 경로가 받는 메서드 목록. 아니면 빈 목록(평소대로 처리)."""
    app = scope.get("app")
    if scope.get("method") != "HEAD" or app is None or not hasattr(app, "router"):
        return []
    routes = [r for r in app.router.routes if getattr(r, "path", None) != _CATCH_ALL and not isinstance(r, Mount)]

    def full(method: str) -> bool:
        return any(r.matches({**scope, "method": method})[0] == Match.FULL for r in routes)

    if full("HEAD") or not full("GET"):
        return []
    return [m for m in ("GET", "POST", "PUT", "PATCH", "DELETE") if full(m)]


async def _send_not_found(send, rid: str) -> None:
    msg = "요청한 경로를 찾을 수 없습니다."
    body = json.dumps({"detail": msg, "error": {"code": "not_found", "message": msg, "request_id": rid}}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def log_llm_usage(*, model: str, summary: dict, latency_ms: float, route: str, request_id: str | None = None) -> None:
    """LLM을 쓴 요청 한 건의 사용 모델, 토큰, 비용, 지연 시간. `summary`는 `services.llm.finish_run`의 반환값이다.

    SSE 본문은 요청 처리 함수가 끝난 뒤 다른 스레드에서 돌 수 있으므로 `request_id`를 직접 받는다."""
    log.info(
        "llm id=%s route=%s model=%s input_tokens=%s output_tokens=%s calls=%s cost_usd=%.6f ms=%.1f",
        request_id or current_request_id(), route, model, summary.get("input_tokens", 0), summary.get("output_tokens", 0),
        summary.get("calls", 0), float(summary.get("cost_usd") or 0.0), latency_ms,
    )
