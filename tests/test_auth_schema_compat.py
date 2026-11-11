"""운영 DB가 Google 연결 SQL(signup_requests.google_sub, user_identities)과 113 전이어도 비밀번호 로그인·가입·승인이 되는지.

운영 Supabase는 109까지만 적용돼 있고 ensure_schema 는 로컬 데모에서만 돈다(backend/main.py). 그래서 저장소는
google_sub 열·user_identities 표가 있는지 한 번 확인하고, 없으면 비밀번호 경로 쿼리에서 google_sub 를 빼고
Google 로그인만 "사용할 수 없음"으로 돌린다. 가짜 연결 시험은 항상 돌고, Postgres 시험은 TEST_DATABASE_URL 이 있을 때만 돈다.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_test_support import MemoryRevocationStore
from backend.auth import (
    CSRF_COOKIE_NAME,
    GoogleIdentity,
    GoogleLoginUnavailableError,
    GoogleOAuthConfig,
    create_auth_router,
    hash_password,
)
from backend.services.auth_store import AccountExistsError, PostgresAuthStore
from backend.services.email_sender import RecordingEmailSender

ROOT = Path(__file__).resolve().parents[1]
PRE_GOOGLE_SQL = ("101_auth_users.sql", "103_auth_token_revocations.sql", "105_admin_role_log.sql",
                  "106_signup_approval.sql", "107_email_signup_verification.sql", "108_auth_privacy_hardening.sql")
GOOGLE_CONFIG = GoogleOAuthConfig(client_id="test-client-id", client_secret="test-client-secret",
                                  redirect_uri="https://example.test/auth/google/callback")


# --- 가짜 연결: 114 전 스키마 -------------------------------------------------------

class _PreGoogleConn:
    """information_schema 확인에는 '없음'(False)을, 나머지는 빈 결과를 돌려주고 SQL 을 모두 적어 둔다."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def transaction(self):
        return self

    def execute(self, sql, _params=()):
        text = " ".join(sql.split())
        self.log.append(text)

        class Result:
            def fetchone(self_inner):
                return (False,) if "information_schema" in text else None

            def fetchall(self_inner):
                return []
        return Result()


def test_store_omits_google_sub_and_checks_schema_once_when_114_is_missing():
    log: list[str] = []
    store = PostgresAuthStore(connect=lambda: _PreGoogleConn(log))
    reviewer = "00000000-0000-0000-0000-000000000001"

    assert store.get_signup_by_login_id("someone@example.com") is None
    assert store.review_signup_request("someone@example.com", "approve", reviewer) == "missing"
    assert store.get_signup_by_login_id("other@example.com") is None
    assert store.google_login_available() is False
    with pytest.raises(GoogleLoginUnavailableError):
        store.get_or_create_google_user("google", "sub-1", "g@example.com")

    schema_checks = [s for s in log if "information_schema" in s]
    assert len(schema_checks) == 1  # 저장소마다 한 번만 확인한다
    signup_sql = [s for s in log if "signup_requests" in s and "information_schema" not in s]
    assert signup_sql and all("google_sub" not in s for s in signup_sql)
    assert not any("user_identities" in s for s in log if "information_schema" not in s)


def test_google_start_and_callback_show_unavailable_notice_when_store_lacks_schema(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = PostgresAuthStore(connect=lambda: _PreGoogleConn([]))

    class Verifier:
        def verify(self, **_kwargs):
            return GoogleIdentity(subject="sub-1", email="g@example.com")

    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret="x" * 32, cookie_secure=False,
                                          revocation_store=MemoryRevocationStore(), google_config=GOOGLE_CONFIG,
                                          google_id_token_verifier=Verifier()))
    client = TestClient(app)
    start = client.get("/auth/google/start", follow_redirects=False)
    assert start.status_code == 303 and start.headers["location"] == "/login?oauth_error=google_unavailable"
    callback = client.get("/auth/google/callback", params={"code": "c", "state": "s"}, follow_redirects=False)
    assert callback.status_code == 303 and callback.headers["location"] == "/login?oauth_error=google_unavailable"


# --- Postgres: 109 이전 인증 SQL 만 적용한 스키마 ---------------------------------------

DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(전용 Postgres에서만)")


@pytest.fixture
def pre_google_store():
    """새 스키마에 101·103·105·106·107·108 만 적용한다(113·114 없음). 끝나면 스키마를 지운다."""
    import psycopg

    schema = f"pre114_{secrets.token_hex(4)}"

    def connect():
        return psycopg.connect(DB, autocommit=True, connect_timeout=5, prepare_threshold=None,
                               options=f"-c search_path={schema}")

    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with connect() as conn:
            for name in PRE_GOOGLE_SQL:
                conn.execute((ROOT / "db" / name).read_text(encoding="utf-8"))
        yield PostgresAuthStore(connect=connect), connect
    finally:
        with psycopg.connect(DB, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _client(store):
    sender = RecordingEmailSender()
    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret="s" * 32, cookie_secure=False,
                                          revocation_store=MemoryRevocationStore(), email_sender=sender,
                                          google_config=GOOGLE_CONFIG))
    return TestClient(app), sender


def _csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def _login(client, login_id, password):
    return client.post("/auth/login", json={"login_id": login_id, "password": password}, headers=_csrf(client))


@pg
def test_pg_password_signup_login_and_review_work_before_google_and_113_sql(pre_google_store, monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store, connect = pre_google_store
    with connect() as conn:
        assert conn.execute("SELECT to_regclass('user_identities')").fetchone()[0] is None
    client, sender = _client(store)
    reviewer = store.create_user("owner-admin", hash_password("owner-pass-12345"), "admin")
    password = "signup-pass-123"

    assert _login(client, "nobody@example.com", password).status_code == 401  # 503 이 아니다

    for email in ("ok@example.com", "no@example.com"):
        body = {"login_id": email, "password": password, "password_confirmation": password}
        assert client.post("/auth/signup", json=body, headers=_csrf(client)).status_code == 201
        verify = {"login_id": email, "code": sender.deliveries[-1]["code"]}
        assert client.post("/auth/signup/verify", json=verify, headers=_csrf(client)).status_code == 200
        assert _login(client, email, password).status_code == 403  # 승인 대기

    assert store.review_signup_request("ok@example.com", "approve", reviewer.user_id) == "changed"
    assert store.review_signup_request("no@example.com", "reject", reviewer.user_id) == "changed"
    assert _login(client, "ok@example.com", password).status_code == 200
    assert _login(client, "OK@Example.com", password).status_code == 200  # 113 색인 없이도 대소문자 무시 조회
    assert _login(client, "no@example.com", password).status_code == 403
    # 113 전에는 login_id UNIQUE 가 거절 행도 막으므로 재가입은 409(오류 아님)
    with pytest.raises(AccountExistsError):
        store.create_pending_user("no@example.com", hash_password(password), email_verification_required=True)

    # Google 로그인은 사용할 수 없음 안내로 보낸다
    assert store.google_login_available() is False
    with pytest.raises(GoogleLoginUnavailableError):
        store.get_or_create_google_user("google", "sub-1", "g@example.com")
    start = client.get("/auth/google/start", follow_redirects=False)
    assert start.headers["location"] == "/login?oauth_error=google_unavailable"


@pg
def test_pg_google_becomes_available_after_ensure_schema(pre_google_store):
    store, _connect = pre_google_store
    assert store.google_login_available() is False
    store.ensure_schema()  # 113·114 적용(로컬 데모와 같은 길). 캐시를 비우고 다시 확인한다
    assert store.google_login_available() is True
