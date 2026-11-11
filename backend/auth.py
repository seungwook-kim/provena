"""Recovered Provena authentication primitives and team API router.

This module provides primitives and an injectable FastAPI authentication router.
The caller supplies an AuthStore; PostgreSQL integration remains pending.
"""

from __future__ import annotations

import os
import secrets
import hmac
import time
import base64
import hashlib
import logging
import ipaddress
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Protocol, cast
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from uuid import UUID, uuid4
from backend.services.email_sender import EmailDeliveryUnavailable, EmailSender, configured_email_sender

log = logging.getLogger(__name__)

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
GOOGLE_OAUTH_REQUEST_COOKIE_NAME = "provena_google_oauth"
AUTH_TOKEN_EXPIRES_MINUTES = 30
AUTH_COOKIE_MAX_AGE = AUTH_TOKEN_EXPIRES_MINUTES * 60
JWT_ALGORITHM = "HS256"
GOOGLE_OAUTH_REQUEST_TTL_SECONDS = 600
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_OAUTH_FAILURE_PATH = "/login?oauth_error=google_login_failed"
GOOGLE_OAUTH_PENDING_PATH = "/login?oauth_error=google_signup_pending"
GOOGLE_OAUTH_REJECTED_PATH = "/login?oauth_error=google_signup_rejected"
GOOGLE_OAUTH_UNAVAILABLE_PATH = "/login?oauth_error=google_unavailable"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
MIN_AUTH_SECRET_BYTES = 32
EMAIL_VERIFICATION_EXPIRES_MINUTES = 5
EMAIL_VERIFICATION_MAX_ATTEMPTS = 5
EMAIL_VERIFICATION_RESEND_SECONDS = 60
EMAIL_VERIFICATION_MAX_SENDS = 5
EMAIL_RE = re.compile(r"^[^@\s]{1,254}@[^@\s]{1,254}\.[^@\s]{1,63}$")
# Pre-generated bcrypt hash used only to keep the missing-ID path comparable.
# The plaintext used to create it is intentionally not stored.
DUMMY_PASSWORD_HASH = "$2b$12$ZYMeUhjatrYhfQ9q1eu/1O7J2e6cMOK79Dh5mAMj3ra4MwL67h1oO"


def _is_missing_signup_table_error(exc: Exception) -> bool:
    """Treat only an undefined ``signup_requests`` relation as optional."""
    if getattr(exc, "sqlstate", None) != "42P01":
        return False
    diag = getattr(exc, "diag", None)
    table_name = getattr(diag, "table_name", None) if diag is not None else None
    if table_name is not None:
        return table_name == "signup_requests"
    first_line = str(exc).splitlines()[0].strip()
    match = re.fullmatch(r'relation "([^"]+)" does not exist', first_line)
    return match is not None and match.group(1) == "signup_requests"


SIGNUP_PENDING_MESSAGE = "가입 신청이 접수되었습니다. 관리자 승인 대기 중입니다. 승인 완료 후 로그인할 수 있습니다."
SIGNUP_REJECTED_MESSAGE = "가입 신청이 승인되지 않았습니다. 자세한 내용은 관리자에게 문의해 주세요."
# 이메일 인증을 마치지 않은 대기 신청: 관리자 승인 대기가 아니라 인증이 먼저다(오류 code signup_unverified)
SIGNUP_UNVERIFIED_CODE = "signup_unverified"
SIGNUP_UNVERIFIED_MESSAGE = "이메일 인증을 먼저 마쳐 주세요. 로그인 화면의 '이메일 인증 이어하기'에서 인증번호를 다시 받을 수 있습니다."


class AuthError(Exception):
    """Base error for authentication failures."""


class AuthConfigurationError(AuthError):
    """Raised when authentication cannot be safely configured."""


class InvalidTokenError(AuthError):
    """Raised when a token is missing, expired, malformed, or tampered with."""


class RevocationStoreUnavailableError(AuthError):
    """Revocation cannot be checked or durably recorded; never allow access."""


class GoogleOAuthError(AuthError):
    """Google OAuth could not prove the browser or identity request is valid."""


class GoogleLoginUnavailableError(AuthConfigurationError):
    """The user store cannot serve Google login yet (e.g. db/203 user_identities·google_sub not applied)."""


class GoogleAccountLinkError(GoogleOAuthError):
    """A verified Google e-mail cannot be linked (inactive, unverified or already linked account)."""


class GoogleSignupPendingError(AuthError):
    """A verified Google identity exists but its signup request is awaiting approval."""


class GoogleSignupRejectedError(AuthError):
    """A verified Google identity's signup request was rejected."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_environ(cls) -> "GoogleOAuthConfig":
        values = {
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", ""),
        }
        if not all(values.values()):
            raise AuthConfigurationError("Google OAuth is not configured")
        return cls(**values)


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str  # email_verified=true 로 검증된 이메일(소문자 정규화는 저장소가 한다)


class GoogleOAuthStore(Protocol):
    """Persistence boundary for verified Google identities only."""

    def get_or_create_google_user(self, provider: str, subject: str, email: str) -> "AuthUser": ...


class GoogleTokenExchanger(Protocol):
    def exchange_code(
        self, *, code: str, config: GoogleOAuthConfig, code_verifier: str
    ) -> str: ...


class GoogleIdTokenVerifier(Protocol):
    def verify(
        self, *, id_token: str, config: GoogleOAuthConfig, nonce: str
    ) -> GoogleIdentity: ...


class TokenRevocationStore(Protocol):
    """Shared store contract. revoke must commit before returning.

    Implement with PostgreSQL, not a per-process cache. Preserve each record
    through expires_at and use the same store for all authentication consumers.
    """

    def is_revoked(self, jti: str) -> bool: ...

    def revoke(self, jti: str, expires_at: datetime) -> None: ...


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
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, _get_secret(secret), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str | None = None) -> dict[str, Any]:
    """Verify claims only; request authentication must also check revocation."""

    if not token:
        raise InvalidTokenError("authentication token is missing")

    try:
        payload = jwt.decode(
            token,
            _get_secret(secret),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["user_id", "role", "exp", "jti"]},
        )
        payload["user_id"] = _normalise_user_id(payload["user_id"])
        if not isinstance(payload["role"], str) or not payload["role"]:
            raise InvalidTokenError("token role is invalid")
        if not isinstance(payload["jti"], str) or str(UUID(payload["jti"])) != payload["jti"]:
            raise InvalidTokenError("token identifier is invalid")
        if type(payload["exp"]) is not int:
            raise InvalidTokenError("token expiration is invalid")
        datetime.fromtimestamp(payload["exp"], timezone.utc)
        return payload
    except AuthConfigurationError:
        raise
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError, TypeError, OverflowError, OSError) as exc:
        raise InvalidTokenError("authentication token is invalid") from exc


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _encode_google_oauth_request(
    *, state: str, nonce: str, code_verifier: str, secret: str
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "purpose": "google_oauth_request",
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "iat": now,
            "exp": now + timedelta(seconds=GOOGLE_OAUTH_REQUEST_TTL_SECONDS),
        },
        secret,
        algorithm=JWT_ALGORITHM,
    )


def _decode_google_oauth_request(token: str, *, secret: str) -> dict[str, str]:
    if not token:
        raise GoogleOAuthError("OAuth request is missing")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["purpose", "state", "nonce", "code_verifier", "exp"]},
        )
        if payload["purpose"] != "google_oauth_request":
            raise GoogleOAuthError("OAuth request purpose is invalid")
        values = {key: payload[key] for key in ("state", "nonce", "code_verifier")}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise GoogleOAuthError("OAuth request claims are invalid")
        return cast(dict[str, str], values)
    except GoogleOAuthError:
        raise
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise GoogleOAuthError("OAuth request is invalid") from exc


def _delete_google_oauth_request_cookie(response: Response) -> None:
    response.delete_cookie(
        key=GOOGLE_OAUTH_REQUEST_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        path="/auth/google/callback",
    )


def _google_oauth_failure_response(location: str = GOOGLE_OAUTH_FAILURE_PATH) -> Response:
    response = Response(status_code=303, headers={"Location": location})
    _delete_google_oauth_request_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return response


class GoogleAuthorizationCodeExchanger:
    """Exchange a one-time code without returning provider secrets to callers."""

    def exchange_code(
        self, *, code: str, config: GoogleOAuthConfig, code_verifier: str
    ) -> str:
        body = urlencode(
            {
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            }
        ).encode("ascii")
        request = UrlRequest(
            GOOGLE_TOKEN_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google HTTPS URL
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            raise GoogleOAuthError("Google token exchange failed") from exc
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise GoogleOAuthError("Google token response is invalid")
        return id_token


class GoogleJwkIdTokenVerifier:
    """Verify Google OIDC claims with Google's rotating public JWKs."""

    def __init__(self, jwks_client: Any | None = None) -> None:
        self._jwks_client = jwks_client if jwks_client is not None else jwt.PyJWKClient(GOOGLE_JWKS_URL)

    def verify(
        self, *, id_token: str, config: GoogleOAuthConfig, nonce: str
    ) -> GoogleIdentity:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=config.client_id,
                issuer=("https://accounts.google.com", "accounts.google.com"),
                options={"require": ["exp", "iss", "aud", "sub", "nonce", "email", "email_verified"]},
            )
        except (jwt.PyJWTError, ValueError, TypeError, OSError) as exc:
            raise GoogleOAuthError("Google ID token is invalid") from exc
        subject = claims.get("sub")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 255
            or not isinstance(claims.get("email"), str)
            or not claims["email"]
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("nonce"), str)
            or not hmac.compare_digest(claims["nonce"], nonce)
        ):
            raise GoogleOAuthError("Google ID token claims are invalid")
        return GoogleIdentity(subject=subject, email=claims["email"])


def _revocation_store(
    request: Request, store: TokenRevocationStore | None
) -> TokenRevocationStore:
    resolved = store if store is not None else getattr(request.app.state, "token_revocation_store", None)
    if resolved is None:
        raise RevocationStoreUnavailableError("revocation store is not configured")
    return resolved


def _is_revoked(store: TokenRevocationStore, jti: str) -> bool:
    try:
        result = store.is_revoked(jti)
    except Exception:
        raise RevocationStoreUnavailableError("revocation lookup failed") from None
    if type(result) is not bool:
        raise RevocationStoreUnavailableError("invalid revocation lookup result")
    return result


def _authenticated_payload(
    request: Request, *, secret: str | None, revocation_store: TokenRevocationStore | None
) -> dict[str, Any]:
    payload = decode_access_token(request.cookies.get(AUTH_COOKIE_NAME, ""), secret=secret)
    if _is_revoked(_revocation_store(request, revocation_store), payload["jti"]):
        raise InvalidTokenError("authentication token is revoked")
    return payload


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


def get_current_user_id(
    request: Request, *, secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> str:
    """Extract and validate user_id from the request cookie.

    The request body or query string is intentionally not consulted. The API
    layer must use this server-derived ID for ownership checks.
    """

    payload = _authenticated_payload(request, secret=secret, revocation_store=revocation_store)
    return payload["user_id"]


def current_user_id(request: Request) -> str:
    """FastAPI dependency that returns the authenticated user's canonical ID.

    The ID is derived only from the signed, HttpOnly auth cookie. Invalid,
    expired, or missing credentials are exposed as the same 401 response so
    callers cannot distinguish token failure modes.
    """

    try:
        return get_current_user_id(request)
    except RevocationStoreUnavailableError:
        raise HTTPException(status_code=503, detail="인증 폐기 저장소를 사용할 수 없습니다.") from None
    except (AuthConfigurationError, InvalidTokenError):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.") from None


@dataclass(frozen=True)
class AuthUser:
    user_id: UUID
    login_id: str
    password_hash: str | None = field(repr=False)  # Google 계정은 None (비밀번호 로그인 불가)
    role: str
    is_active: bool = True
    groups: tuple[str, ...] = ()


class AuthStore(Protocol):
    """Repository contract shared with the isolated PostgreSQL adapter draft."""

    def get_by_login_id(self, login_id: str) -> AuthUser | None: ...

    def get_by_user_id(self, user_id: UUID | str) -> AuthUser | None: ...


class LoginRequest(BaseModel):
    login_id: str
    password: str


class SignupRequest(BaseModel):
    login_id: str
    password: str
    password_confirmation: str


class SignupVerificationRequest(BaseModel):
    login_id: str
    code: str


class UserResponse(BaseModel):
    user_id: str
    role: str


class MeResponse(UserResponse):
    # 내 정보(요청 1번): /me에만 "있다/없다"를 더한다. 로그인 응답(UserResponse)은 그대로 두려고 따로 뺐다.
    profile_completed: bool | None = None
    # 사용자 관리(요청 2번): 최고 관리자면 true. 화면이 메뉴를 숨기는 데만 쓰고, 서버는 요청마다 다시 확인한다
    is_owner: bool | None = None


class LoginRateLimiter:
    """MVP process-local limiter; replace with shared storage before deployment."""

    def __init__(
        self, *, max_attempts: int = 5, max_ip_attempts: int = 30, window_seconds: int = 60
    ) -> None:
        self.max_attempts = max_attempts
        self.max_ip_attempts = max_ip_attempts
        self.window_seconds = window_seconds
        self._failures_by_login_id: dict[str, list[float]] = {}
        self._failures_by_ip: dict[str, list[float]] = {}
        self._signup_requests_by_ip: dict[str, list[float]] = {}
        self._signup_rate_lock = threading.Lock()

    def _prune_expired(self, now: float) -> None:
        # Sweep both maps so abandoned IDs and IPs do not accumulate forever.
        for failures in (self._failures_by_login_id, self._failures_by_ip, self._signup_requests_by_ip):
            for key, stamps in list(failures.items()):
                recent = [stamp for stamp in stamps if now - stamp < self.window_seconds]
                if recent:
                    failures[key] = recent
                else:
                    failures.pop(key, None)

    def is_limited(self, login_id: str, client_ip: str) -> bool:
        """Return whether either independent failure budget is exhausted."""

        self._prune_expired(time.monotonic())
        return (
            len(self._failures_by_login_id.get(login_id, [])) >= self.max_attempts
            or len(self._failures_by_ip.get(client_ip, [])) >= self.max_ip_attempts
        )

    def record_failure(self, login_id: str, client_ip: str) -> None:
        stamp = time.monotonic()
        self._prune_expired(stamp)
        self._failures_by_login_id.setdefault(login_id, []).append(stamp)
        self._failures_by_ip.setdefault(client_ip, []).append(stamp)

    def reset_login_id(self, login_id: str) -> None:
        """Clear only the ID bucket; IP failures remain independent."""

        self._failures_by_login_id.pop(login_id, None)

    def is_signup_ip_limited(self, client_ip: str) -> bool:
        """Use the existing 60-second/30-request IP policy for signup mail routes."""

        self._prune_expired(time.monotonic())
        return len(self._signup_requests_by_ip.get(client_ip, [])) >= self.max_ip_attempts

    def record_signup_ip_request(self, client_ip: str) -> None:
        """Record every accepted signup/resend attempt, independent of email address."""

        stamp = time.monotonic()
        self._prune_expired(stamp)
        self._signup_requests_by_ip.setdefault(client_ip, []).append(stamp)

    def allow_signup_ip_request(self, client_ip: str) -> bool:
        """Atomically check and record one signup/resend request in this process."""

        with self._signup_rate_lock:
            if self.is_signup_ip_limited(client_ip):
                return False
            self.record_signup_ip_request(client_ip)
            return True


def _trusted_proxy_hops() -> int:
    """TRUSTED_PROXY_HOPS: proxies in front of the app that append to X-Forwarded-For (0 = trust none)."""

    try:
        hops = int(os.getenv("TRUSTED_PROXY_HOPS", "0").strip() or "0")
    except ValueError:
        return 0
    return max(hops, 0)


def _client_ip(request: Request) -> str:
    """Return the client address used for the IP failure budget.

    With TRUSTED_PROXY_HOPS=0 (default) only the direct peer address is used and
    X-Forwarded-For is ignored. With N > 0 the N-th entry from the right of
    X-Forwarded-For is used: each trusted proxy appends the address it saw, so
    entries left of that one may be written by the client and are never trusted
    (Cloud Run appends the real client address as the last entry, so N = 1).
    A missing, too short or malformed header falls back to the peer address.
    """

    peer = request.client.host if request.client and request.client.host else "unknown"
    hops = _trusted_proxy_hops()
    if hops == 0:
        return peer
    values = request.headers.getlist("x-forwarded-for")
    entries = [entry.strip() for value in values for entry in value.split(",")]
    if len(entries) < hops:
        return peer
    candidate = entries[-hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


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


def require_csrf(request: Request) -> None:
    """Reusable Depends(require_csrf) guard for cookie-authenticated mutations.

    This validates the existing double-submit CSRF contract only; pair it with
    a current-user or admin dependency. It does not grant authentication.
    """
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(
        cookie_token.encode("utf-8"), header_token.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="CSRF 검증에 실패했습니다.")


def get_current_user(
    request: Request, *, store: AuthStore, secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> AuthUser:
    """Re-read current role and active status; JWT role alone grants no access."""
    try:
        user_id = get_current_user_id(request, secret=secret, revocation_store=revocation_store)
    except RevocationStoreUnavailableError:
        raise HTTPException(status_code=503, detail="인증 폐기 저장소를 사용할 수 없습니다.") from None
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
    *, store: AuthStore, secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> Callable:
    """Use Depends(result) in future protected team endpoints."""
    def current_user(request: Request) -> AuthUser:
        return get_current_user(request, store=store, secret=secret, revocation_store=revocation_store)

    return current_user


def require_admin(
    request: Request, *, store: AuthStore, secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> AuthUser:
    """Require an active administrator using the store's current role.

    Missing/invalid authentication is 401, an active non-admin is 403, and
    store failures remain 503. The JWT role and request fields grant no access.
    Use create_require_admin_dependency to bind the store and signing secret.
    """
    user = get_current_user(request, store=store, secret=secret, revocation_store=revocation_store)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


def create_require_admin_dependency(
    *, store: AuthStore, secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> Callable:
    """Bind app-owned dependencies, then use Depends(result) on admin routes.

    For a state-changing route, also add Depends(require_csrf). Bind the same
    secret as the auth router, including when local demo uses a random secret.
    """
    def admin_dependency(request: Request) -> AuthUser:
        return require_admin(request, store=store, secret=secret, revocation_store=revocation_store)

    return admin_dependency


def create_auth_router(
    *,
    store: AuthStore,
    secret: str | None = None,
    cookie_secure: bool | None = None,
    rate_limiter: LoginRateLimiter | None = None,
    revocation_store: TokenRevocationStore | None = None,
    google_oauth_store: GoogleOAuthStore | None = None,
    google_config: GoogleOAuthConfig | None = None,
    google_token_exchanger: GoogleTokenExchanger | None = None,
    google_id_token_verifier: GoogleIdTokenVerifier | None = None,
    profile_completed: Callable[[str], bool] | None = None,
    owner_check: Callable[[AuthUser], bool] | None = None,
    email_sender: EmailSender | None = None,
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
    resolved_email_sender = email_sender if email_sender is not None else configured_email_sender()
    current_user = create_current_user_dependency(store=store, secret=secret, revocation_store=revocation_store)
    resolved_secret = _get_secret(secret)
    resolved_google_store = google_oauth_store
    if resolved_google_store is None and callable(getattr(store, "get_or_create_google_user", None)):
        resolved_google_store = cast(GoogleOAuthStore, store)

    def configured_google_oauth() -> tuple[GoogleOAuthConfig, GoogleOAuthStore]:
        config = google_config
        if config is None:
            config = GoogleOAuthConfig.from_environ()
        if resolved_google_store is None:
            raise AuthConfigurationError("Google OAuth user store is not configured")
        if google_id_token_verifier is None and not getattr(jwt.algorithms, "has_crypto", False):
            raise AuthConfigurationError("Google ID token verification dependency is not configured")
        available = getattr(resolved_google_store, "google_login_available", None)
        if callable(available) and not available():
            # 운영 DB에 Google 연결 표(db/203)가 아직 없으면 Google 로그인만 끄고 비밀번호 로그인은 그대로 둔다.
            raise GoogleLoginUnavailableError("Google login schema is not applied")
        return config, resolved_google_store

    @router.get("/auth/csrf", status_code=204)
    def csrf() -> Response:
        response = Response(status_code=204)
        set_csrf_cookie(response, create_csrf_token(), secure=cookie_secure)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _signup_unverified(login_id: str) -> bool:
        """비밀번호가 맞은 대기 신청이 이메일 인증 전인지. 확인하지 못하면 False(기존 승인 대기 안내)."""
        get_verification = getattr(store, "get_signup_verification", None)
        if not callable(get_verification):
            return False
        try:
            row = get_verification(login_id)
        except Exception:
            return False
        return bool(row and row.get("status") == "pending" and row.get("email_verification_required")
                    and row.get("email_verified_at") is None)

    @router.post(
        "/auth/login",
        response_model=UserResponse,
        responses={403: {"description": "Signup request is pending approval or rejected, or (error code signup_unverified) its email verification is not finished yet"}},
    )
    def login(request: Request, payload: LoginRequest, response: Response) -> UserResponse:
        require_csrf(request)
        login_id = payload.login_id.strip().lower() if "@" in payload.login_id else payload.login_id
        client_ip = _client_ip(request)
        if limiter.is_limited(login_id, client_ip):
            raise HTTPException(status_code=429, detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        try:
            user = store.get_by_login_id(login_id)
        except Exception:
            raise HTTPException(status_code=503, detail="인증 저장소를 사용할 수 없습니다.") from None
        signup = None
        if user is None:
            get_signup = getattr(store, "get_signup_by_login_id", None)
            if callable(get_signup):
                try:
                    signup = get_signup(login_id)
                except Exception as exc:
                    if not _is_missing_signup_table_error(exc):
                        raise HTTPException(status_code=503, detail="authentication storage unavailable") from None
        password_hash = (user.password_hash if user is not None else (signup[1] if signup else None)) or DUMMY_PASSWORD_HASH
        password_valid = verify_password(payload.password, password_hash)
        get_status = getattr(store, "get_signup_status", None)
        if callable(get_status) and user is not None and password_valid:
            try:
                approval_status = get_status(user.user_id)
            except Exception as exc:
                if not _is_missing_signup_table_error(exc):
                    raise HTTPException(status_code=503, detail="authentication storage unavailable") from None
                approval_status = None
            if approval_status == "pending":
                raise HTTPException(status_code=403, detail=SIGNUP_PENDING_MESSAGE)
            if approval_status == "rejected":
                raise HTTPException(status_code=403, detail=SIGNUP_REJECTED_MESSAGE)
        elif signup is not None and password_valid:
            approval_status = signup[0]
            if approval_status == "pending" and _signup_unverified(login_id):
                raise HTTPException(status_code=403, detail={"reason": SIGNUP_UNVERIFIED_CODE, "message": SIGNUP_UNVERIFIED_MESSAGE})
            if approval_status == "pending":
                raise HTTPException(status_code=403, detail=SIGNUP_PENDING_MESSAGE)
            if approval_status == "rejected":
                raise HTTPException(status_code=403, detail=SIGNUP_REJECTED_MESSAGE)
        if (user is None or not user.is_active or user.role not in {"user", "admin"}
                or not password_valid):
            limiter.record_failure(login_id, client_ip)
            raise HTTPException(status_code=401, detail="로그인 정보가 올바르지 않습니다.")
        try:
            token = create_access_token(user.user_id, user.role, secret=secret)
            token_claims = decode_access_token(token, secret=secret)
            if _is_revoked(_revocation_store(request, revocation_store), token_claims["jti"]):
                raise RevocationStoreUnavailableError("new token identifier is already revoked")
        except RevocationStoreUnavailableError:
            raise HTTPException(status_code=503, detail="인증 폐기 저장소를 사용할 수 없습니다.") from None
        except AuthConfigurationError:
            raise HTTPException(status_code=500, detail="인증 설정을 사용할 수 없습니다.") from None
        limiter.reset_login_id(login_id)
        set_auth_cookie(response, token, secure=cookie_secure)
        response.headers["Cache-Control"] = "no-store"
        return UserResponse(user_id=str(user.user_id), role=user.role)

    def _normalise_signup_login(login_id: str) -> str:
        return login_id.strip().lower()

    def _check_signup_ip_rate_limit(request: Request) -> None:
        client_ip = _client_ip(request)
        if not limiter.allow_signup_ip_request(client_ip):
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")

    def _verification_hash(login_id: str, code: str) -> str:
        return hmac.new(resolved_secret.encode(), f"{login_id}\x00{code}".encode(), hashlib.sha256).hexdigest()

    def _issue_signup_verification(login_id: str) -> tuple[datetime, datetime]:
        get_verification = getattr(store, "get_signup_verification", None)
        save_verification = getattr(store, "save_verification", None)
        if not callable(get_verification) or not callable(save_verification):
            raise HTTPException(status_code=503, detail="email verification storage is unavailable")
        now = datetime.now(timezone.utc)
        row = get_verification(login_id)
        if row is None:
            raise HTTPException(status_code=404, detail="signup request not found")
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=EMAIL_VERIFICATION_EXPIRES_MINUTES)
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = _verification_hash(login_id, code)
        issue_verification = getattr(store, "issue_verification", None)
        if callable(issue_verification):
            def deliver(value: str) -> None:
                resolved_email_sender.send_verification_email(
                    email=login_id, code=value, expires_minutes=EMAIL_VERIFICATION_EXPIRES_MINUTES
                )
            try:
                result = issue_verification(
                    login_id, code_hash, code, now, expires_at,
                    EMAIL_VERIFICATION_MAX_SENDS, EMAIL_VERIFICATION_RESEND_SECONDS, deliver,
                )
            except EmailDeliveryUnavailable:
                log.error("verification email not sent: EMAIL_PROVIDER is not configured")
                raise HTTPException(status_code=503, detail="이메일 인증 기능을 사용할 수 없습니다.") from None
            except RuntimeError as exc:
                # 발송 실패: 저장소가 같은 트랜잭션을 되돌려 발송 횟수·코드는 바뀌지 않는다.
                # 가입 첫 발송이면 호출한 쪽(signup)이 방금 만든 대기 신청을 지우고,
                # 재발송이면 신청은 그대로 두어 다시 시도할 수 있다.
                log.warning("verification email delivery failed: %s", type(exc).__name__)
                raise HTTPException(status_code=503, detail="이메일 발송에 실패했습니다.") from None
            if result == "unavailable":
                raise HTTPException(status_code=404, detail="signup request not found")
            if result == "limited":
                raise HTTPException(status_code=429, detail="인증번호 발송 제한을 초과했습니다.")
            return expires_at, now + timedelta(seconds=EMAIL_VERIFICATION_RESEND_SECONDS)
        last_sent = row.get("last_verification_sent_at")
        if last_sent and (now - last_sent).total_seconds() < EMAIL_VERIFICATION_RESEND_SECONDS:
            raise HTTPException(status_code=429, detail="인증번호 재발송은 잠시 후 다시 시도해 주세요.")
        if row.get("verification_send_count", 0) >= EMAIL_VERIFICATION_MAX_SENDS:
            raise HTTPException(status_code=429, detail="인증번호 발송 횟수를 초과했습니다.")
        try:
            resolved_email_sender.send_verification_email(email=login_id, code=code, expires_minutes=EMAIL_VERIFICATION_EXPIRES_MINUTES)
            expires_at = now + timedelta(minutes=EMAIL_VERIFICATION_EXPIRES_MINUTES)
            save_verification(login_id, _verification_hash(login_id, code), expires_at, now)
            return expires_at, now + timedelta(seconds=EMAIL_VERIFICATION_RESEND_SECONDS)
        except EmailDeliveryUnavailable:
            log.error("verification email not sent: EMAIL_PROVIDER is not configured")
            raise HTTPException(status_code=503, detail="이메일 인증 기능을 사용할 수 없습니다.") from None
        except Exception as exc:
            log.warning("verification email delivery failed: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="이메일 발송에 실패했습니다.") from None

    @router.post(
        "/auth/signup",
        status_code=201,
        description=("Email signup. An unverified pending request for the same email is replaced only after its code expired more than "
                     "24 hours ago (STALE_UNVERIFIED_SIGNUP_HOURS); until then the same email returns 409. Verified or approved requests "
                     "and existing accounts (email compared case-insensitively) return 409. A rejected request does not block signing up again."),
        responses={409: {"description": "Email already has an account, or a non-stale pending request or an approved request exists"},
                   503: {"description": "Signup storage unavailable, or the verification email could not be sent (the pending request is removed so the same email can sign up again)"}},
    )
    def signup(request: Request, payload: SignupRequest) -> dict[str, str]:
        require_csrf(request)
        _check_signup_ip_rate_limit(request)
        login_id = _normalise_signup_login(payload.login_id)
        if (not login_id or len(login_id) > 64 or any(char.isspace() for char in login_id)
                or payload.password != payload.password_confirmation):
            raise HTTPException(status_code=422, detail="회원가입 입력값을 확인해 주세요.")
        email_required = bool(EMAIL_RE.fullmatch(login_id))
        if "@" in login_id and not email_required:
            raise HTTPException(status_code=422, detail="이메일 형식을 확인해 주세요.")
        try:
            password_hash = hash_password(payload.password)
        except ValueError:
            raise HTTPException(status_code=422, detail="비밀번호는 8자 이상 72바이트 이하이어야 합니다.") from None
        create_pending = getattr(store, "create_pending_user", None)
        if not callable(create_pending):
            raise HTTPException(status_code=503, detail="signup approval storage is unavailable")
        try:
            if email_required:
                create_pending(login_id, password_hash, email_verification_required=True)
            else:
                create_pending(login_id, password_hash)
            issued = _issue_signup_verification(login_id) if email_required else None
        except HTTPException:
            if email_required:
                delete_pending = getattr(store, "delete_pending_signup", None)
                if callable(delete_pending):
                    delete_pending(login_id)
            raise
        except Exception as exc:
            if type(exc).__name__ == "AccountExistsError":
                if email_required:
                    raise HTTPException(status_code=409, detail="회원가입을 완료할 수 없습니다. 입력값을 확인하거나 이메일 인증 이어하기를 이용해 주세요.") from None
                raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.") from None
            raise HTTPException(status_code=503, detail="회원가입을 처리할 수 없습니다.") from None
        response = {"message": "회원가입이 완료되었습니다. 로그인해 주세요."}
        if issued is not None:
            response["verification_expires_at"] = issued[0].isoformat()
            response["verification_resend_available_at"] = issued[1].isoformat()
        return response

    @router.post(
        "/auth/signup/verify",
        description="Requires a valid CSRF token and a six-digit verification code.",
        responses={400: {"description": "Incorrect verification code"},
                   410: {"description": "Verification code expired"},
                   429: {"description": "Verification attempts exceeded"},
                   503: {"description": "Email verification storage unavailable"}},
    )
    def verify_signup(request: Request, payload: SignupVerificationRequest) -> dict[str, str]:
        require_csrf(request)
        login_id = _normalise_signup_login(payload.login_id)
        if not EMAIL_RE.fullmatch(login_id) or not re.fullmatch(r"\d{6}", payload.code):
            raise HTTPException(status_code=422, detail="이메일 또는 인증번호 형식을 확인해 주세요.")
        verify = getattr(store, "verify_signup_code", None)
        if not callable(verify):
            raise HTTPException(status_code=503, detail="email verification storage is unavailable")
        result = verify(login_id, _verification_hash(login_id, payload.code), datetime.now(timezone.utc), EMAIL_VERIFICATION_MAX_ATTEMPTS)
        if result in {"verified", "already_verified"}:
            return {"status": "verified"}
        if result == "expired":
            raise HTTPException(status_code=410, detail="인증번호가 만료되었습니다.")
        if result == "too_many_attempts":
            raise HTTPException(status_code=429, detail="인증번호 시도 횟수를 초과했습니다.")
        raise HTTPException(status_code=400, detail="인증번호가 올바르지 않습니다.")

    @router.post(
        "/auth/signup/resend",
        description="Resends only for pending, unverified email signup requests. Missing, completed, and rate-limited requests are intentionally returned as status unavailable.",
        responses={503: {"description": "Email verification storage or provider unavailable (also returned when EMAIL_PROVIDER is not configured or delivery fails)"}},
    )
    def resend_signup(request: Request, payload: SignupVerificationRequest) -> dict[str, str]:
        require_csrf(request)
        _check_signup_ip_rate_limit(request)
        login_id = _normalise_signup_login(payload.login_id)
        if not EMAIL_RE.fullmatch(login_id):
            raise HTTPException(status_code=422, detail="이메일 형식을 확인해 주세요.")
        row = getattr(store, "get_signup_verification", lambda _login_id: None)(login_id)
        if (not row or row.get("status") != "pending"
                or not row.get("email_verification_required")
                or row.get("email_verified_at") is not None):
            return {"status": "unavailable"}
        try:
            issued = _issue_signup_verification(login_id)
        except HTTPException as exc:
            # Keep unavailable, missing, and rate-limited requests
            # indistinguishable to callers. The store still enforces the
            # limits atomically before any delivery attempt.
            if exc.status_code in {404, 429}:
                return {"status": "unavailable"}
            raise
        return {"status": "sent", "verification_expires_at": issued[0].isoformat(),
                "verification_resend_available_at": issued[1].isoformat()}

    @router.get("/auth/google/start", status_code=303)
    def google_start() -> Response:
        try:
            config, _google_store = configured_google_oauth()
        except AuthConfigurationError:
            # 브라우저가 주소창으로 오는 길이라 JSON 글자 대신 로그인 화면으로 돌려보낸다.
            return Response(status_code=303, headers={"Location": GOOGLE_OAUTH_UNAVAILABLE_PATH, "Cache-Control": "no-store"})
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        request_cookie = _encode_google_oauth_request(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            secret=resolved_secret,
        )
        query = urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": "openid email",
                "state": state,
                "nonce": nonce,
                "code_challenge": _pkce_challenge(code_verifier),
                "code_challenge_method": "S256",
            }
        )
        response = Response(status_code=303, headers={"Location": f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"})
        response.set_cookie(
            key=GOOGLE_OAUTH_REQUEST_COOKIE_NAME,
            value=request_cookie,
            max_age=GOOGLE_OAUTH_REQUEST_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=cookie_secure,
            path="/auth/google/callback",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/auth/google/callback", status_code=303)
    def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
        del error  # Provider details are intentionally not surfaced to the browser or logs.
        try:
            config, oauth_store = configured_google_oauth()
            pending = _decode_google_oauth_request(
                request.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME, ""), secret=resolved_secret
            )
            if not code or not state or not hmac.compare_digest(state, pending["state"]):
                raise GoogleOAuthError("OAuth callback state is invalid")
            exchanger = google_token_exchanger or GoogleAuthorizationCodeExchanger()
            verifier = google_id_token_verifier or GoogleJwkIdTokenVerifier()
            identity = verifier.verify(
                id_token=exchanger.exchange_code(
                    code=code, config=config, code_verifier=pending["code_verifier"]
                ),
                config=config,
                nonce=pending["nonce"],
            )
            user = oauth_store.get_or_create_google_user("google", identity.subject, identity.email)
            if user is None or not user.is_active or user.role not in {"user", "admin"}:
                raise GoogleOAuthError("OAuth user is not active")
            token = create_access_token(user.user_id, user.role, secret=resolved_secret)
            if _is_revoked(_revocation_store(request, revocation_store), decode_access_token(token, secret=resolved_secret)["jti"]):
                raise RevocationStoreUnavailableError("new token identifier is already revoked")
        except GoogleSignupPendingError:
            return _google_oauth_failure_response(GOOGLE_OAUTH_PENDING_PATH)
        except GoogleSignupRejectedError:
            return _google_oauth_failure_response(GOOGLE_OAUTH_REJECTED_PATH)
        except GoogleLoginUnavailableError:
            return _google_oauth_failure_response(GOOGLE_OAUTH_UNAVAILABLE_PATH)
        except (AuthConfigurationError, GoogleOAuthError, RevocationStoreUnavailableError, InvalidTokenError, Exception):
            # OAuth failures must not disclose token, provider, storage, or configuration details.
            return _google_oauth_failure_response()
        response = Response(status_code=303, headers={"Location": "/"})
        set_auth_cookie(response, token, secure=cookie_secure)
        _delete_google_oauth_request_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        require_csrf(request)
        try:
            payload = _authenticated_payload(request, secret=secret, revocation_store=revocation_store)
            revocations = _revocation_store(request, revocation_store)
            try:
                revocations.revoke(payload["jti"], datetime.fromtimestamp(payload["exp"], timezone.utc))
            except Exception:
                raise RevocationStoreUnavailableError("revocation write failed") from None
            if not _is_revoked(revocations, payload["jti"]):
                raise RevocationStoreUnavailableError("revocation was not persisted")
        except RevocationStoreUnavailableError:
            raise HTTPException(status_code=503, detail="인증 폐기 저장소를 사용할 수 없습니다.") from None
        except (AuthConfigurationError, InvalidTokenError):
            raise HTTPException(status_code=401, detail="인증이 필요합니다.") from None
        response = Response(status_code=204)
        delete_auth_cookie(response)
        delete_csrf_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        return response

    # profile_completed: 내 정보(요청 1번) 첫 로그인 막기용. 콜백을 안 넘기면 /me 응답은 예전과 같다(None은 빼고 보냄).
    @router.get("/me", response_model=MeResponse, response_model_exclude_none=True)
    def me(response: Response, user: AuthUser = Depends(current_user)) -> MeResponse:
        response.headers["Cache-Control"] = "no-store"
        completed = None
        if profile_completed is not None:
            try:
                completed = profile_completed(str(user.user_id))
            except Exception:
                completed = None
            if type(completed) is not bool:   # 저장소 오류·이상한 값은 막힘/열림을 추측하지 않고 503
                raise HTTPException(status_code=503, detail="내 정보 저장소를 사용할 수 없습니다.")
        owner = None if owner_check is None else owner_check(user) is True   # backend/admin_api.py is_owner (DB 조회 없음)
        return MeResponse(user_id=str(user.user_id), role=user.role, profile_completed=completed, is_owner=owner)

    return router
