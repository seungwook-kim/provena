from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.auth as auth_module
from backend.auth import (
    AUTH_COOKIE_NAME,
    GOOGLE_OAUTH_REQUEST_COOKIE_NAME,
    AuthUser,
    GoogleIdentity,
    GoogleOAuthConfig,
    GoogleOAuthError,
    GoogleJwkIdTokenVerifier,
    create_auth_router,
)


class MemoryRevocations:
    def is_revoked(self, _jti: str) -> bool:
        return False

    def revoke(self, _jti: str, _expires_at: datetime) -> None:
        return None


class MockGoogleStore:
    def __init__(self) -> None:
        self.user = AuthUser(uuid4(), "google-test-user", "unused", "user")
        self.calls: list[tuple[str, str]] = []

    def get_by_login_id(self, _login_id: str):
        return None

    def get_by_user_id(self, user_id: str):
        return self.user if str(self.user.user_id) == str(user_id) else None

    def get_or_create_google_user(self, provider: str, subject: str) -> AuthUser:
        self.calls.append((provider, subject))
        return self.user


class ProvisioningGoogleStore:
    """Storage-contract double: only provider/sub may select an OAuth user."""

    def __init__(self) -> None:
        self.users: dict[tuple[str, str], AuthUser] = {}
        self.create_count = 0

    def get_by_login_id(self, _login_id: str):
        return None

    def get_by_user_id(self, user_id: str):
        return next(
            (user for user in self.users.values() if str(user.user_id) == str(user_id)),
            None,
        )

    def get_or_create_google_user(self, provider: str, subject: str) -> AuthUser:
        assert provider == "google"
        assert subject
        key = (provider, subject)
        if key not in self.users:
            self.create_count += 1
            self.users[key] = AuthUser(
                uuid4(), f"google-{self.create_count}", "unused", "user"
            )
        return self.users[key]


class MockExchanger:
    def __init__(self) -> None:
        self.code_verifier = ""

    def exchange_code(self, *, code: str, config: GoogleOAuthConfig, code_verifier: str) -> str:
        assert code == "google-code"
        assert config.client_id == "test-client-id"
        self.code_verifier = code_verifier
        return "provider-id-token"


class MockVerifier:
    def __init__(self, subject: str = "google-subject-123") -> None:
        self.subject = subject
        self.nonce = ""

    def verify(self, *, id_token: str, config: GoogleOAuthConfig, nonce: str) -> GoogleIdentity:
        assert id_token == "provider-id-token"
        assert config.client_id == "test-client-id"
        self.nonce = nonce
        return GoogleIdentity(subject=self.subject)


class RejectingVerifier:
    def verify(self, **_kwargs) -> GoogleIdentity:
        raise GoogleOAuthError("invalid test token")


@pytest.fixture
def oauth_context(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MockGoogleStore()
    exchanger = MockExchanger()
    verifier = MockVerifier()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.test/auth/google/callback",
            ),
            google_token_exchanger=exchanger,
            google_id_token_verifier=verifier,
        )
    )
    return TestClient(app), store, exchanger, verifier


def _start(client: TestClient):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    return response


def test_google_start_uses_state_nonce_and_s256_pkce(oauth_context):
    client, _store, _exchanger, _verifier = oauth_context
    response = _start(client)
    target = urlsplit(response.headers["location"])
    params = parse_qs(target.query)
    assert target.scheme == "https"
    assert target.netloc == "accounts.google.com"
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email"]
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["state"][0]) >= 32
    assert len(params["nonce"][0]) >= 32
    assert GOOGLE_OAUTH_REQUEST_COOKIE_NAME in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_google_callback_issues_existing_jwt_cookie_for_verified_subject(oauth_context):
    client, store, exchanger, verifier = oauth_context
    start = _start(client)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.cookies.get(AUTH_COOKIE_NAME)
    assert client.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME) is None
    assert store.calls == [("google", "google-subject-123")]
    assert exchanger.code_verifier
    assert verifier.nonce
    assert client.get("/me").json() == {"user_id": str(store.user.user_id), "role": "user"}


def test_google_first_login_provisions_user_and_relogin_reuses_provider_subject(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = ProvisioningGoogleStore()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig(
                "test-client-id", "test-client-secret", "https://example.test/callback"
            ),
            google_token_exchanger=MockExchanger(),
            google_id_token_verifier=MockVerifier("stable-google-subject"),
        )
    )

    with TestClient(app) as first, TestClient(app) as returning:
        first_state = parse_qs(urlsplit(_start(first).headers["location"]).query)["state"][0]
        first_response = first.get(
            "/auth/google/callback",
            params={"code": "google-code", "state": first_state},
            follow_redirects=False,
        )
        assert first_response.status_code == 303
        first_user = first.get("/me").json()

        returning_state = parse_qs(urlsplit(_start(returning).headers["location"]).query)["state"][0]
        returning_response = returning.get(
            "/auth/google/callback",
            params={"code": "google-code", "state": returning_state},
            follow_redirects=False,
        )
        assert returning_response.status_code == 303
        assert returning.get("/me").json() == first_user

    assert store.create_count == 1
    assert first_user["role"] == "user"


def test_google_callback_rejects_mismatched_state_without_creating_a_user(oauth_context):
    client, store, _exchanger, _verifier = oauth_context
    _start(client)
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": "wrong-state"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?oauth_error=google_login_failed"
    assert store.calls == []
    assert client.cookies.get(AUTH_COOKIE_NAME) is None
    assert client.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME) is None


def test_google_callback_rejects_token_verification_failure(oauth_context):
    client, store, _exchanger, _verifier = oauth_context
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig("test-client-id", "test-client-secret", "https://example.test/auth/google/callback"),
            google_token_exchanger=MockExchanger(),
            google_id_token_verifier=RejectingVerifier(),
        )
    )
    client = TestClient(app)
    start = _start(client)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": state}, follow_redirects=False
    )
    assert response.headers["location"] == "/login?oauth_error=google_login_failed"
    assert store.calls == []
    assert client.cookies.get(AUTH_COOKIE_NAME) is None


def test_google_start_fails_closed_without_an_oauth_store(monkeypatch):
    class PasswordOnlyStore:
        def get_by_login_id(self, _login_id: str):
            return None

        def get_by_user_id(self, _user_id: str):
            return None

    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=PasswordOnlyStore(),
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_config=GoogleOAuthConfig("id", "secret", "https://example.test/callback"),
        )
    )
    assert TestClient(app).get("/auth/google/start", follow_redirects=False).status_code == 503


def test_google_start_fails_closed_without_rs256_verification_support(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    monkeypatch.setattr(auth_module.jwt.algorithms, "has_crypto", False)
    store = MockGoogleStore()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig("id", "secret", "https://example.test/callback"),
        )
    )
    assert TestClient(app).get("/auth/google/start", follow_redirects=False).status_code == 503


def test_google_id_token_verifier_rejects_unverified_email(monkeypatch):
    class SigningKey:
        key = "unused"

    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "google-subject", "nonce": "nonce", "email_verified": False,
            "exp": 2_000_000_000, "iss": "https://accounts.google.com", "aud": "client",
        },
    )
    verifier = GoogleJwkIdTokenVerifier(jwks_client=Jwks())
    with pytest.raises(GoogleOAuthError):
        verifier.verify(
            id_token="ignored", config=GoogleOAuthConfig("client", "secret", "https://example.test/callback"), nonce="nonce"
        )


def test_google_id_token_verifier_accepts_verified_subject(monkeypatch):
    class SigningKey:
        key = "unused"

    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "google-subject", "nonce": "nonce", "email": "verified@example.test",
            "email_verified": True, "exp": 2_000_000_000,
            "iss": "https://accounts.google.com", "aud": "client",
        },
    )
    identity = GoogleJwkIdTokenVerifier(jwks_client=Jwks()).verify(
        id_token="ignored", config=GoogleOAuthConfig("client", "secret", "https://example.test/callback"), nonce="nonce"
    )
    assert identity == GoogleIdentity(subject="google-subject")
