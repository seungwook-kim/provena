from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import (
    AUTH_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    AuthConfigurationError,
    AuthUser,
    LoginRateLimiter,
    create_access_token,
    create_auth_router,
    hash_password,
)


class FakeAuthStore:
    def __init__(self, user: AuthUser) -> None:
        self.user = user
        self.fail_login_lookup = False
        self.fail_user_lookup = False

    def get_by_login_id(self, login_id: str) -> AuthUser | None:
        if self.fail_login_lookup:
            raise RuntimeError("database unavailable")
        return self.user if self.user.login_id == login_id else None

    def get_by_user_id(self, user_id: str) -> AuthUser | None:
        if self.fail_user_lookup:
            raise RuntimeError("database unavailable")
        return self.user if str(self.user.user_id) == str(user_id) else None


@pytest.fixture
def auth_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    secret = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(16)
    user = AuthUser(
        user_id=uuid4(),
        login_id="runtime-user",
        password_hash=hash_password(password),
        role="user",
        is_active=True,
    )
    store = FakeAuthStore(user)
    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False))
    return TestClient(app), store, secret, password


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token
    return {"X-CSRF-Token": token}


def issue_csrf(client: TestClient) -> None:
    response = client.get("/auth/csrf")
    assert response.status_code == 204
    assert client.cookies.get(CSRF_COOKIE_NAME)


def login(client: TestClient, password: str):
    issue_csrf(client)
    return client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": password},
        headers=csrf_headers(client),
    )


def test_csrf_login_me_logout_and_relogin(auth_context):
    client, store, _secret, password = auth_context

    response = login(client, password)
    assert response.status_code == 200
    assert response.json() == {"user_id": str(store.user.user_id), "role": "user"}
    assert AUTH_COOKIE_NAME in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]

    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == str(store.user.user_id)

    logout = client.post("/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    assert client.get("/me").status_code == 401

    relogin = login(client, password)
    assert relogin.status_code == 200
    assert client.get("/me").status_code == 200


def test_uniform_auth_failures_and_csrf_rejection(auth_context):
    client, _store, _secret, password = auth_context
    issue_csrf(client)
    headers = csrf_headers(client)

    wrong_password = client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": secrets.token_urlsafe(16)},
        headers=headers,
    )
    unknown_user = client.post(
        "/auth/login",
        json={"login_id": "missing-user", "password": password},
        headers=headers,
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]

    missing_csrf = client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": password},
    )
    mismatched_csrf = client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": password},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert missing_csrf.status_code == mismatched_csrf.status_code == 403


def test_rate_limit_and_validation_do_not_expose_password(auth_context):
    client, _store, secret, password = auth_context
    app = FastAPI()
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    app.include_router(
        create_auth_router(store=_store, secret=secret, cookie_secure=False, rate_limiter=limiter)
    )
    limited_client = TestClient(app)
    issue_csrf(limited_client)
    headers = csrf_headers(limited_client)
    for _ in range(2):
        response = limited_client.post(
            "/auth/login",
            json={"login_id": "runtime-user", "password": password + "wrong"},
            headers=headers,
        )
        assert response.status_code == 401
    response = limited_client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": password},
        headers=headers,
    )
    assert response.status_code == 429

    validation_app = FastAPI()
    validation_app.include_router(create_auth_router(store=_store, secret=secret, cookie_secure=False))
    validation_client = TestClient(validation_app)
    missing_field = validation_client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "unexpected": "sensitive-runtime-value"},
    )
    assert missing_field.status_code == 422
    assert "sensitive-runtime-value" not in missing_field.text


def test_expired_tampered_tokens_and_current_user_state(auth_context):
    client, store, secret, _password = auth_context
    issue_csrf(client)
    expired = create_access_token(store.user.user_id, store.user.role, secret=secret,
                                  expires_delta=timedelta(seconds=-1))
    client.cookies.set(AUTH_COOKIE_NAME, expired)
    assert client.get("/me").status_code == 401

    valid = create_access_token(store.user.user_id, store.user.role, secret=secret)
    client.cookies.set(AUTH_COOKIE_NAME, valid + "tampered")
    assert client.get("/me").status_code == 401

    client.cookies.set(AUTH_COOKIE_NAME, valid)
    store.user = replace(store.user, role="admin")
    assert client.get("/me").json()["role"] == "admin"
    store.user = replace(store.user, is_active=False)
    assert client.get("/me").status_code == 401


def test_store_errors_return_503(auth_context):
    client, store, _secret, password = auth_context
    issue_csrf(client)
    store.fail_login_lookup = True
    login_response = client.post(
        "/auth/login",
        json={"login_id": "runtime-user", "password": password},
        headers=csrf_headers(client),
    )
    assert login_response.status_code == 503

    store.fail_login_lookup = False
    assert login(client, password).status_code == 200
    store.fail_user_lookup = True
    assert client.get("/me").status_code == 503


def test_secret_and_secure_cookie_policies(auth_context, monkeypatch: pytest.MonkeyPatch):
    _client, store, _secret, _password = auth_context
    with pytest.raises(AuthConfigurationError):
        create_auth_router(store=store, secret="short-secret", cookie_secure=True)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(AuthConfigurationError):
        create_auth_router(store=store, cookie_secure=True)

    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    local_app = FastAPI()
    local_app.include_router(create_auth_router(store=store, secret=secrets.token_urlsafe(32)))
    local_client = TestClient(local_app)
    local_cookie = local_client.get("/auth/csrf").headers["set-cookie"]
    assert "Secure" not in local_cookie

    monkeypatch.delenv("PROVENA_ENV")
    monkeypatch.delenv("PROVENA_DEV_MODE")
    production_app = FastAPI()
    production_app.include_router(create_auth_router(store=store, secret=secrets.token_urlsafe(32)))
    production_client = TestClient(production_app)
    production_cookie = production_client.get("/auth/csrf").headers["set-cookie"]
    assert "Secure" in production_cookie
