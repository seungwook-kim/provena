"""PostgresAuthStore, 데모 시드, main.py 연결 시험.

기본은 가짜 연결로 키와 DB 없이 돈다. 진짜 Postgres로도 돌리려면 PROVENA_TEST_DATABASE_URL에 시험용 DB 주소를 준다
(users 테이블을 만들고 시험 계정을 넣었다가 지운다).
"""
from __future__ import annotations

import os
import secrets
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from auth_test_support import create_test_auth_router

from backend.main import WEB_DIR
from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, verify_password
from backend.services.auth_store import REVOCATION_SCHEMA_FILE, SCHEMA_FILE, PostgresAuthStore
from backend.services.demo_seed import seed_demo_accounts

LOCAL = {"PROVENA_ENV": "local", "PROVENA_DEV_MODE": "1"}


# ---- 가짜 연결 -------------------------------------------------------------
class FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self, log, row):
        self.log, self.row, self.closed = log, row, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        return FakeCursor(self.row)


def fake_store(row=None):
    log, conns = [], []

    def connect():
        conns.append(FakeConn(log, row))
        return conns[-1]

    return PostgresAuthStore(connect=connect), log, conns


# ---- 저장소 ----------------------------------------------------------------
def test_get_by_login_id_maps_row_to_auth_user():
    uid = uuid4()
    store, log, conns = fake_store((uid, "alice", "hash", "admin", True))
    user = store.get_by_login_id("alice")
    assert user == AuthUser(user_id=uid, login_id="alice", password_hash="hash", role="admin", is_active=True)
    assert "FROM users WHERE login_id = %s" in log[0][0] and log[0][1] == ("alice",)
    assert conns[0].closed


def test_get_by_user_id_accepts_str_and_uuid_and_rejects_garbage_without_query():
    uid = uuid4()
    store, log, _ = fake_store((str(uid), "bob", "hash", "user", False))
    assert store.get_by_user_id(str(uid)).user_id == uid
    assert store.get_by_user_id(uid).is_active is False
    assert store.get_by_user_id("not-a-uuid") is None
    assert store.get_by_user_id(None) is None
    assert len(log) == 2  # 잘못된 id는 DB를 부르지 않는다
    assert log[0][1] == (UUID(str(uid)),)


def test_missing_user_returns_none():
    store, _, _ = fake_store(None)
    assert store.get_by_login_id("nobody") is None


def test_upsert_user_rejects_unknown_role_and_uses_conflict_update():
    uid = uuid4()
    store, log, _ = fake_store((uid, "carol", "h2", "user", True))
    with pytest.raises(ValueError):
        store.upsert_user("carol", "h2", "superuser")
    assert log == []
    store.upsert_user("carol", "h2", "user")
    assert "ON CONFLICT (login_id) DO UPDATE" in log[0][0]


def test_ensure_schema_runs_additive_auth_schema_files_without_account_values():
    store, log, _ = fake_store()
    store.ensure_schema()
    assert REVOCATION_SCHEMA_FILE.name == "103_auth_token_revocations.sql"
    assert log[0][0] == SCHEMA_FILE.read_text(encoding="utf-8")
    assert log[1][0] == REVOCATION_SCHEMA_FILE.read_text(encoding="utf-8")
    sql = "\n".join(row[0] for row in log)
    assert "user_id       uuid" in sql and "token_revocations" in sql and "INSERT" not in sql.upper()


# ---- 데모 시드 -------------------------------------------------------------
class RecordingStore:
    def __init__(self):
        self.rows = []

    def upsert_user(self, login_id, password_hash, role):
        self.rows.append((login_id, password_hash, role))


def test_seed_creates_exactly_two_accounts_in_local_dev_mode():
    store = RecordingStore()
    env = {**LOCAL, "DEMO_USER_PASSWORD": "user-pass-1234", "DEMO_ADMIN_PASSWORD": "admin-pass-1234"}
    assert seed_demo_accounts(store, env) == ["demo-user", "demo-admin"]
    assert [(r[0], r[2]) for r in store.rows] == [("demo-user", "user"), ("demo-admin", "admin")]
    assert verify_password("user-pass-1234", store.rows[0][1])
    assert all("pass" not in r[1] for r in store.rows)  # 평문이 아니라 해시


def test_seed_login_ids_can_be_overridden_by_env():
    store = RecordingStore()
    env = {**LOCAL, "DEMO_USER_LOGIN_ID": "u1", "DEMO_USER_PASSWORD": "user-pass-1234"}
    assert seed_demo_accounts(store, env) == ["u1"]  # 관리자 비밀번호가 없으면 그 계정은 건너뛴다


@pytest.mark.parametrize(
    "env",
    [
        {},  # 모드 없음
        {"PROVENA_ENV": "local"},  # DEV_MODE 없음
        {"PROVENA_DEV_MODE": "1"},  # ENV 없음
        {"PROVENA_ENV": "production", "PROVENA_DEV_MODE": "1"},
        {"PROVENA_ENV": "local", "PROVENA_DEV_MODE": "0"},
    ],
)
def test_seed_never_runs_outside_local_dev_mode(env):
    store = RecordingStore()
    env = {**env, "DEMO_USER_PASSWORD": "user-pass-1234", "DEMO_ADMIN_PASSWORD": "admin-pass-1234"}
    assert seed_demo_accounts(store, env) == []
    assert store.rows == []


def test_seed_rejects_short_password_without_echoing_it():
    short = "short1"
    with pytest.raises(ValueError) as err:
        seed_demo_accounts(RecordingStore(), {**LOCAL, "DEMO_USER_PASSWORD": short})
    assert short not in str(err.value) and "DEMO_USER_PASSWORD" in str(err.value)


def test_seed_skips_account_with_empty_password():
    store = RecordingStore()
    assert seed_demo_accounts(store, {**LOCAL, "DEMO_ADMIN_PASSWORD": "admin-pass-1234"}) == ["demo-admin"]


# ---- main.py 연결 ----------------------------------------------------------
def _app(monkeypatch, **env):
    for key in ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from backend.main import create_app

    monkeypatch.setattr("backend.main.create_auth_router", create_test_auth_router)
    return create_app()


def _paths(app):
    # FastAPI 버전에 따라 app.routes 안의 모양이 달라서 OpenAPI 경로로 본다
    return set(app.openapi()["paths"])


def test_auth_router_is_not_mounted_without_database_url(monkeypatch):
    app = _app(monkeypatch)
    assert "/auth/login" not in _paths(app)
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_auth_router_is_mounted_with_database_url_and_secret(monkeypatch):
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x", AUTH_SECRET=secrets.token_urlsafe(32),
               **LOCAL)
    assert {"/auth/csrf", "/auth/login", "/auth/logout", "/me", "/health"} <= _paths(app)
    assert TestClient(app).get("/health").status_code == 200  # DB가 없어도 /health는 산다


def test_database_url_without_auth_secret_refuses_to_start(monkeypatch):
    from backend.auth import AuthConfigurationError

    with pytest.raises(AuthConfigurationError):
        _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x")


def test_local_demo_without_auth_secret_starts_with_random_secret(monkeypatch):
    # 저장소에 서명 키를 두지 않는다: 로컬 데모 모드에서만 실행마다 새로 만든다
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x", **LOCAL)
    assert "/auth/login" in _paths(app)


def test_random_secret_differs_per_run_and_is_long_enough(monkeypatch):
    from backend.auth import MIN_AUTH_SECRET_BYTES
    from backend.main import resolve_auth_secret

    monkeypatch.delenv("AUTH_SECRET", raising=False)
    for key, value in LOCAL.items():
        monkeypatch.setenv(key, value)
    first, second = resolve_auth_secret(), resolve_auth_secret()
    assert first != second and len(first.encode()) >= MIN_AUTH_SECRET_BYTES


def test_login_flow_through_main_app_with_fake_store(monkeypatch):
    """main.create_app()이 붙인 라우터가 PostgresAuthStore(가짜 연결)로 로그인·/me·로그아웃을 끝까지 하는지."""
    from backend.auth import hash_password

    uid, password = uuid4(), secrets.token_urlsafe(12)
    row = (uid, "demo-user", hash_password(password), "user", True)
    monkeypatch.setattr("backend.main.PostgresAuthStore", lambda dsn: fake_store(row)[0])
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@db/x", AUTH_SECRET=secrets.token_urlsafe(32), **LOCAL)
    client = TestClient(app)
    assert client.get("/auth/csrf").status_code == 204
    headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
    bad = client.post("/auth/login", json={"login_id": "demo-user", "password": "wrong-password"}, headers=headers)
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"login_id": "demo-user", "password": password}, headers=headers)
    assert ok.status_code == 200 and ok.json() == {"user_id": str(uid), "role": "user"}
    assert client.cookies.get(AUTH_COOKIE_NAME)
    assert client.get("/me").json() == {"user_id": str(uid), "role": "user"}
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/me").status_code == 401


def test_create_app_binds_revocation_store_for_login_me_logout_and_reuse_block(monkeypatch):
    from backend.main import create_app
    from backend.auth import hash_password

    uid, password = uuid4(), secrets.token_urlsafe(12)
    user = AuthUser(uid, "demo-user", hash_password(password), "user", True)
    revocations = set()

    class FakeAuthStore:
        def __init__(self, _dsn):
            self.user = user

        def ensure_schema(self):
            pass

        def upsert_user(self, login_id, password_hash, role):
            pass

        def get_by_login_id(self, login_id):
            return self.user if login_id == self.user.login_id else None

        def get_by_user_id(self, user_id):
            return self.user if str(user_id) == str(self.user.user_id) else None

    class FakeRevocationStore:
        def __init__(self, _dsn):
            pass

        def is_revoked(self, jti):
            return jti in revocations

        def revoke(self, jti, _expires_at):
            revocations.add(jti)

    for key, value in {"DATABASE_URL": "postgresql://test", "AUTH_SECRET": secrets.token_urlsafe(32), **LOCAL}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("backend.main.PostgresAuthStore", FakeAuthStore)
    monkeypatch.setattr("backend.main.PostgresTokenRevocationStore", FakeRevocationStore)

    app = create_app()
    assert isinstance(app.state.token_revocation_store, FakeRevocationStore)
    with TestClient(app) as client:
        assert client.get("/auth/csrf").status_code == 204
        headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
        assert client.post("/auth/login", json={"login_id": user.login_id, "password": password}, headers=headers).status_code == 200
        token = client.cookies.get(AUTH_COOKIE_NAME)
        assert client.get("/me").status_code == 200
        assert client.post("/auth/logout", headers=headers).status_code == 204
        client.cookies.set(AUTH_COOKIE_NAME, token, domain="testserver.local", path="/")
        assert client.get("/me").status_code == 401


@pytest.mark.skipif(not (WEB_DIR / "react-app" / "dist" / "index.html").is_file(), reason="React production build 없음")
def test_react_entry_and_spa_fallback_do_not_shadow_api(monkeypatch):
    client = TestClient(_app(monkeypatch))
    root = client.get("/")
    assert root.status_code == 200 and '<div id="root"></div>' in root.text
    assert client.get("/login.html").status_code == 200
    assert client.get("/chat").status_code == 200
    assert client.get("/admin").status_code == 200
    assert client.get("/api/not-found").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


# ---- 진짜 Postgres (선택) ---------------------------------------------------
@pytest.mark.skipif(not os.getenv("PROVENA_TEST_DATABASE_URL"), reason="PROVENA_TEST_DATABASE_URL 없음")
def test_real_postgres_roundtrip():
    from backend.auth import hash_password

    store = PostgresAuthStore(os.environ["PROVENA_TEST_DATABASE_URL"])
    store.ensure_schema()
    store.ensure_schema()  # 두 번 돌려도 된다
    login = f"pytest-{secrets.token_hex(4)}"
    try:
        created = store.upsert_user(login, hash_password("first-pass-1234"), "user")
        again = store.upsert_user(login, hash_password("second-pass-1234"), "admin")
        assert again.user_id == created.user_id and again.role == "admin" and again.is_active
        got = store.get_by_login_id(login)
        assert got.user_id == created.user_id and verify_password("second-pass-1234", got.password_hash)
        assert store.get_by_user_id(str(created.user_id)).login_id == login
        assert store.get_by_login_id("pytest-no-such-user") is None
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM users WHERE login_id = %s", (login,))


def test_dockerfile_does_not_let_clients_pick_their_ip():
    # --forwarded-allow-ips=*면 uvicorn이 X-Forwarded-For 맨 앞(위조 가능) 값을 client IP로 쓴다
    from pathlib import Path

    cmd = [line for line in (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("CMD")]
    assert cmd and "--no-proxy-headers" in cmd[-1] and "forwarded-allow-ips" not in cmd[-1]

