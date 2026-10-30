"""Recovered Provena authentication primitives and team API router.

This module provides primitives and an injectable FastAPI authentication router.
The caller supplies an AuthStore; PostgreSQL integration remains pending.
"""

from __future__ import annotations

import os
import secrets
import hmac
import time
from dataclasses import dataclass, field
from typing import Protocol
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response


# Provisional values. Cookie name and lifetime require team agreement before
# integration into the team service.
AUTH_COOKIE_NAME = "provena_auth"
CSRF_COOKIE_NAME = "provena_csrf"
AUTH_TOKEN_EXPIRES_MINUTES = 30
AUTH_COOKIE_MAX_AGE = AUTH_TOKEN_EXPIRES_MINUTES * 60
JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
MIN_AUTH_SECRET_BYTES = 32
# Pre-generated bcrypt hash used only to keep the missing-ID path comparable.
# The plaintext used to create it is intentionally not stored.
DUMMY_PASSWORD_HASH = "$2b$12$ZYMeUhjatrYhfQ9q1eu/1O7J2e6cMOK79Dh5mAMj3ra4MwL67h1oO"


class AuthError(Exception):
    """Base error for authentication failures."""


class AuthConfigurationError(AuthError):
    """Raised when authentication cannot be safely configured."""


class InvalidTokenError(AuthError):
    """Raised when a token is missing, expired, malformed, or tampered with."""


def _get_secret(secret: str | None = None) -> str:
    resolved = secret if secret is not None else os.getenv("AUTH_SECRET")
    if not resolved or len(resolved.encode("utf-8")) < MIN_AUTH_SECRET_BYTES:
        raise AuthConfigurationError("AUTH_SECRET is not configured")
    return resolved


def _is_valid_password(password: str) -> bool:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return False
    return len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES


def _normalise_user_id(user_id: UUID | str) -> str:
    try:
        return str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("user_id must be a valid UUID") from exc


def hash_password(password: str) -> str:
    """Return a bcrypt hash; never return or persist the plaintext password."""

    if not _is_valid_password(password):
        raise ValueError("password length is invalid")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Safely compare a plaintext candidate with a stored bcrypt hash."""

    if not _is_valid_password(password) or not isinstance(password_hash, str):
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: UUID | str,
    role: str,
    *,
    secret: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT containing only authentication metadata."""

    if not role:
        raise ValueError("role must be a non-empty string")

    now = datetime.now(timezone.utc)
    lifetime = expires_delta or timedelta(minutes=AUTH_TOKEN_EXPIRES_MINUTES)
    expires_at = now + lifetime
    payload: dict[str, Any] = {
        "user_id": _normalise_user_id(user_id),
        "role": role,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, _get_secret(secret), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str | None = None) -> dict[str, Any]:
    """Verify a JWT signature and expiration, returning its validated payload."""

    if not token:
        raise InvalidTokenError("authentication token is missing")

    try:
        payload = jwt.decode(
            token,
            _get_secret(secret),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["user_id", "role", "exp"]},
        )
        payload["user_id"] = _normalise_user_id(payload["user_id"])
        if not isinstance(payload["role"], str) or not payload["role"]:
            raise InvalidTokenError("token role is invalid")
        return payload
    except AuthConfigurationError:
        raise
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError("authentication token is invalid") from exc


def set_auth_cookie(
    response: Response,
    token: str,
    *,
    secure: bool = False,
    max_age: int = AUTH_COOKIE_MAX_AGE,
) -> None:
    """Set the provisional auth cookie for local HTTP or production HTTPS."""

    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(
    response: Response,
    token: str,
    *,
    secure: bool = False,
    max_age: int = AUTH_COOKIE_MAX_AGE,
) -> None:
    """Set a readable CSRF cookie; the JWT remains HttpOnly."""

    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )


def delete_auth_cookie(response: Response) -> None:
    """Remove the auth cookie from the client."""

    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        path="/",
    )


def delete_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        httponly=False,
        samesite="lax",
        path="/",
    )


def get_current_user_id(request: Request, *, secret: str | None = None) -> str:
    """Extract and validate user_id from the request cookie.

    The request body or query string is intentionally not consulted. The API
    layer must use this server-derived ID for ownership checks.
    """

    token = request.cookies.get(AUTH_COOKIE_NAME)
    payload = decode_access_token(token or "", secret=secret)
    return payload["user_id"]


def current_user_id(request: Request) -> str:
    """FastAPI dependency that returns the authenticated user's canonical ID.

    The ID is derived only from the signed, HttpOnly auth cookie. Invalid,
    expired, or missing credentials are exposed as the same 401 response so
    callers cannot distinguish token failure modes.
    """

    try:
        return get_current_user_id(request)
    except (AuthConfigurationError, InvalidTokenError):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.") from None


@dataclass(frozen=True)
class AuthUser:
    user_id: UUID
    login_id: str
    password_hash: str = field(repr=False)
    role: str
    is_active: bool = True


class AuthStore(Protocol):
    """Repository contract shared with the isolated PostgreSQL adapter draft."""

    def get_by_login_id(self, login_id: str) -> AuthUser | None: ...

    def get_by_user_id(self, user_id: UUID | str) -> AuthUser | None: ...


class LoginRequest(BaseModel):
    login_id: str
    password: str


class UserResponse(BaseModel):
    user_id: str
    role: str


class LoginRateLimiter:
    """MVP process-local limiter; replace with shared storage before deployment."""

    def __init__(self, *, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures_by_login_id: dict[str, list[float]] = {}
        self._failures_by_ip: dict[str, list[float]] = {}

    def _is_limited(self, failures: dict[str, list[float]], key: str) -> bool:
        now = time.monotonic()
        recent = [stamp for stamp in failures.get(key, []) if now - stamp < self.window_seconds]
        failures[key] = recent
        return len(recent) >= self.max_attempts

    def is_limited(self, login_id: str, client_ip: str) -> bool:
        """Return whether either the login ID or client IP reached its limit."""

        return self._is_limited(self._failures_by_login_id, login_id) or self._is_limited(
            self._failures_by_ip, client_ip
        )

    def record_failure(self, login_id: str, client_ip: str) -> None:
        stamp = time.monotonic()
        self._failures_by_login_id.setdefault(login_id, []).append(stamp)
        self._failures_by_ip.setdefault(client_ip, []).append(stamp)

    def reset_login_id(self, login_id: str) -> None:
        """Clear only the ID bucket; IP failures remain independent."""

        self._failures_by_login_id.pop(login_id, None)


def _client_ip(request: Request) -> str:
    """Return the direct peer address until a trusted proxy policy is defined."""

    return request.client.host if request.client and request.client.host else "unknown"


class AuthRoute(APIRoute):
    """Redact validation errors only for this router, without changing main.py."""

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                raise HTTPException(status_code=422, detail="잘못된 로그인 요청입니다.") from None

        return handler


def _csrf_or_reject(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(
        cookie_token.encode("utf-8"), header_token.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="CSRF 검증에 실패했습니다.")


def get_current_user(
    request: Request, *, store: AuthStore, secret: str | None = None
) -> AuthUser:
    """Re-read current role and active status; JWT role alone grants no access."""
    try:
        user_id = get_current_user_id(request, secret=secret)
    except (AuthConfigurationError, InvalidTokenError):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.") from None
    try:
        user = store.get_by_user_id(user_id)
    except Exception:
        raise HTTPException(status_code=503, detail="인증 저장소를 사용할 수 없습니다.") from None
    if user is None or not user.is_active or user.role not in {"user", "admin"}:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    return user


def create_current_user_dependency(
    *, store: AuthStore, secret: str | None = None
) -> Callable:
    """Use Depends(result) in future protected team endpoints."""
    def current_user(request: Request) -> AuthUser:
        return get_current_user(request, store=store, secret=secret)

    return current_user


def create_auth_router(
    *,
    store: AuthStore,
    secret: str | None = None,
    cookie_secure: bool | None = None,
    rate_limiter: LoginRateLimiter | None = None,
) -> APIRouter:
    """Explicit repository only: no account seed, in-memory or DB fallback.

    Future integration: app.include_router(create_auth_router(store=repository)).
    The caller owns repository configuration and its connection lifecycle.
    """
    if store is None:
        raise AuthConfigurationError("AuthStore is required")
    _get_secret(secret)  # Fail at router construction, before accepting requests.
    local_dev = os.getenv("PROVENA_ENV") == "local" and os.getenv("PROVENA_DEV_MODE") == "1"
    if cookie_secure is False and not local_dev:
        raise AuthConfigurationError("Insecure cookies require explicit local development mode")
    if cookie_secure is None:
        cookie_secure = not local_dev
    router = APIRouter(route_class=AuthRoute)
    limiter = rate_limiter if rate_limiter is not None else LoginRateLimiter()
    current_user = create_current_user_dependency(store=store, secret=secret)

    @router.get("/auth/csrf", status_code=204)
    def csrf() -> Response:
        response = Response(status_code=204)
        set_csrf_cookie(response, create_csrf_token(), secure=cookie_secure)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/auth/login", response_model=UserResponse)
    def login(request: Request, payload: LoginRequest, response: Response) -> UserResponse:
        _csrf_or_reject(request)
        client_ip = _client_ip(request)
        if limiter.is_limited(payload.login_id, client_ip):
            raise HTTPException(status_code=429, detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        try:
            user = store.get_by_login_id(payload.login_id)
        except Exception:
            raise HTTPException(status_code=503, detail="인증 저장소를 사용할 수 없습니다.") from None
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        password_valid = verify_password(payload.password, password_hash)
        if (user is None or not user.is_active or user.role not in {"user", "admin"}
                or not password_valid):
            limiter.record_failure(payload.login_id, client_ip)
            raise HTTPException(status_code=401, detail="로그인 정보가 올바르지 않습니다.")
        try:
            token = create_access_token(user.user_id, user.role, secret=secret)
        except AuthConfigurationError:
            raise HTTPException(status_code=500, detail="인증 설정을 사용할 수 없습니다.") from None
        limiter.reset_login_id(payload.login_id)
        set_auth_cookie(response, token, secure=cookie_secure)
        response.headers["Cache-Control"] = "no-store"
        return UserResponse(user_id=str(user.user_id), role=user.role)

    @router.post("/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        _csrf_or_reject(request)
        response = Response(status_code=204)
        delete_auth_cookie(response)
        delete_csrf_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/me", response_model=UserResponse)
    def me(response: Response, user: AuthUser = Depends(current_user)) -> UserResponse:
        response.headers["Cache-Control"] = "no-store"
        return UserResponse(user_id=str(user.user_id), role=user.role)

    return router
