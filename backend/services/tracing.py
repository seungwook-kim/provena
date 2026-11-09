"""Langfuse 트레이스 콜백. 키가 없거나 Langfuse에 닿지 못해도 그래프 실행에는 영향이 없다.

환경변수(이름은 템플릿 `.env.example`과 같다):
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`: 둘 다 있어야 켠다. 하나라도 비면 콜백이 없다(데모 모드).
- `LANGFUSE_HOST`: 비면 `LANGFUSE_BASE_URL`, 그것도 비면 `https://cloud.langfuse.com`.
- `LANGFUSE_TIMEOUT`: 요청 제한 시간(초). 기본 `DEFAULT_TIMEOUT_S`. SDK 기본(5초)보다 짧게 잡는다.
- `LANGFUSE_TRACING_ENABLED=false`: 키가 있어도 끈다(SDK 공통 스위치).

전송은 SDK의 백그라운드 스레드가 모아서 보낸다. 그래서 Langfuse가 죽어 있어도 호출 경로는 막히지 않고,
여기서 하는 일(클라이언트·핸들러 만들기, 점수 남기기, flush)은 예외를 로그로만 남기고 삼킨다.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://cloud.langfuse.com"
DEFAULT_TIMEOUT_S = 2

_lock = threading.Lock()
_clients: dict[tuple[str, str, str], Any] = {}
_failed: set[tuple[str, str, str]] = set()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def langfuse_settings() -> tuple[str, str, str] | None:
    """(public_key, secret_key, host). 키가 하나라도 비었거나 꺼져 있으면 None."""
    if _env("LANGFUSE_TRACING_ENABLED").lower() in {"0", "false", "no", "off"}:
        return None
    pk, sk = _env("LANGFUSE_PUBLIC_KEY"), _env("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        return None
    return pk, sk, _env("LANGFUSE_HOST") or _env("LANGFUSE_BASE_URL") or DEFAULT_HOST


def tracing_enabled() -> bool:
    return langfuse_settings() is not None


def _timeout() -> int:
    try:
        return max(1, int(_env("LANGFUSE_TIMEOUT") or DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _make_client(public_key: str, secret_key: str, host: str) -> Any:
    """Langfuse 클라이언트. 같은 public_key로 `get_client`/`CallbackHandler`가 찾아 쓴다. 시험에서는 이 함수를 바꿔 끼운다."""
    from langfuse import Langfuse

    return Langfuse(public_key=public_key, secret_key=secret_key, host=host, timeout=_timeout())


def _make_handler(public_key: str) -> Any:
    """LangChain/LangGraph 콜백 핸들러. 시험에서는 이 함수를 바꿔 끼운다."""
    from langfuse.langchain import CallbackHandler

    return CallbackHandler(public_key=public_key)


def get_handler() -> Any | None:
    """실행 한 번에 쓸 Langfuse 콜백 핸들러. 꺼져 있거나 만들지 못하면 None(트레이스만 없고 실행은 그대로)."""
    cfg = langfuse_settings()
    if cfg is None or cfg in _failed:
        return None
    if _env("LANGFUSE_CONTENT_CAPTURE_ENABLED").lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        with _lock:
            if cfg not in _clients:
                _clients[cfg] = _make_client(*cfg)
        return _make_handler(cfg[0])
    except Exception as e:  # noqa: BLE001 - 트레이스 때문에 질문이 실패하면 안 된다
        _failed.add(cfg)
        log.warning("Langfuse를 켜지 못해 이번 프로세스에서는 트레이스 없이 돌린다: %s", e)
        return None


def trace_metadata(
    *, session_id: str | None = None, user_id: str | None = None, name: str | None = None
) -> dict[str, str]:
    """Langfuse 핸들러가 트레이스 속성으로 읽는 metadata 키."""
    if _env("LANGFUSE_CONTENT_CAPTURE_ENABLED").lower() not in {"1", "true", "yes", "on"}:
        return {}
    out: dict[str, str] = {}
    if session_id:
        out["langfuse_session_id"] = str(session_id)[:200]
    if user_id:
        out["langfuse_user_id"] = str(user_id)[:200]
    if name:
        out["langfuse_trace_name"] = name
    return out


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if _env("LANGFUSE_CONTENT_CAPTURE_ENABLED").lower() in {"1", "true", "yes", "on"}:
        return dict(metadata or {})
    blocked = {"prompt", "response", "input", "output", "user_id", "session_id", "thread_id"}
    return {key: value for key, value in (metadata or {}).items() if key not in blocked}


def create_safe_event(*, name: str, metadata: dict[str, Any] | None = None) -> bool:
    """Record aggregate-only telemetry without content or user identifiers."""
    if _env("LANGFUSE_SAFE_EVENTS_ENABLED").lower() not in {"1", "true", "yes", "on"}:
        return False
    cfg = langfuse_settings()
    if cfg is None:
        return False
    allowed = {"graph", "calls", "status", "result", "duration_ms"}
    safe_metadata = {
        key: value for key, value in (metadata or {}).items()
        if key in allowed and isinstance(value, (str, int, float, bool))
    }
    try:
        with _lock:
            if cfg not in _clients:
                _clients[cfg] = _make_client(*cfg)
            client = _clients[cfg]
        client.create_event(name=name, input=None, output=None, metadata=safe_metadata)
        return True
    except Exception as exc:  # noqa: BLE001 - tracing must never affect application work
        log.warning("Langfuse safe event failed: %s", type(exc).__name__)
        return False


def record_score(handler: Any, name: str, value: float, *, comment: str | None = None) -> bool:
    """이 핸들러가 마지막으로 만든 트레이스에 숫자 점수를 붙인다(예: 실행 비용). 실패하면 False."""
    trace_id = getattr(handler, "last_trace_id", None)
    cfg = langfuse_settings()
    if handler is None or not trace_id or cfg is None:
        return False
    try:
        client = _clients.get(cfg)
        if client is None:
            return False
        client.create_score(name=name, value=float(value), trace_id=trace_id, data_type="NUMERIC", comment=comment)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Langfuse 점수 기록 실패(%s): %s", name, e)
        return False


def record_scores(handler: Any, scores: dict[str, float | None], *, prefix: str = "", comment: str | None = None) -> int:
    """`record_score`를 여러 개 한꺼번에(평가 지표 묶음). None 값은 건너뛴다. 붙인 점수 수를 돌려준다. 키가 없으면 0."""
    n = 0
    for name, value in scores.items():
        if value is None:
            continue
        if record_score(handler, f"{prefix}{name}", float(value), comment=comment):
            n += 1
    return n


def record_session_score(session_id: str, name: str, value: float | None, *, comment: str | None = None) -> bool:
    """세션(예: 평가 실행 한 번) 전체에 숫자 점수를 붙인다. 평가 집계 지표용. 키가 없거나 실패하면 False."""
    cfg = langfuse_settings()
    if value is None or not session_id or cfg is None:
        return False
    try:
        client = _clients.get(cfg)
        if client is None:
            return False
        client.create_score(name=name, value=float(value), session_id=str(session_id)[:200], data_type="NUMERIC", comment=comment)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Langfuse 세션 점수 기록 실패(%s): %s", name, e)
        return False


def flush() -> None:
    """모인 트레이스를 지금 보낸다(프로세스를 끝내기 전, 스크린샷을 찍기 전). 실패는 삼킨다."""
    for client in list(_clients.values()):
        try:
            client.flush()
        except Exception as e:  # noqa: BLE001
            log.warning("Langfuse flush 실패: %s", e)


def reset() -> None:
    """캐시한 클라이언트와 실패 기록을 비운다(시험용). 클라이언트는 닫는다."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
        _failed.clear()
    for client in clients:
        try:
            client.shutdown()
        except Exception:  # noqa: BLE001
            pass
