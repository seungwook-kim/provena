"""PostgresAuthStore, 데모 시드, main.py 연결 시험.

기본은 가짜 연결로 키와 DB 없이 돈다. 진짜 Postgres로도 돌리려면 PROVENA_TEST_DATABASE_URL에 시험용 DB 주소를 준다
(users 테이블을 만들고 시험 계정을 넣었다가 지운다).
"""
from __future__ import annotations

import os
import secrets
import threading
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from auth_test_support import create_test_auth_router

from backend.main import WEB_DIR
from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, verify_password
from backend.services.auth_store import REVOCATION_SCHEMA_FILE, SCHEMA_FILE, AccountExistsError, MemoryAuthStore, PostgresAuthStore
from backend.services.demo_seed import seed_demo_accounts

LOCAL = {"PROVENA_ENV": "local", "PROVENA_DEV_MODE": "1"}


def test_memory_auth_store_signup_lifecycle_preserves_hash_and_metadata():
    store = MemoryAuthStore()
    reviewer = uuid4()
    assert store.create_pending_user("pending-memory", "bcrypt-hash") is None
    assert store.get_by_login_id("pending-memory") is None
    assert store.get_signup_by_login_id("pending-memory") == ("pending", "bcrypt-hash")
    assert store.get_signup_status(uuid4()) is None
    assert store.list_signup_requests()[0].status == "pending"
    assert store.review_signup_request("pending-memory", "approve", reviewer) == "changed"
    user = store.get_by_login_id("pending-memory")
    assert user is not None and user.password_hash == "bcrypt-hash"
    assert store.get_signup_status(user.user_id) == "approved"
    request = store._signup_requests["pending-memory"]
    assert request["user_id"] == user.user_id
    assert request["reviewed_by"] == reviewer
    assert request["reviewed_at"] is not None
    assert store.review_signup_request("pending-memory", "reject", reviewer) == "unchanged"


def test_memory_signup_status_contract_separates_user_and_login_lookups():
    store = MemoryAuthStore()
    existing = store.create_user("existing", "existing-hash", "user")
    assert store.get_signup_status(existing.user_id) is None
    assert store.get_signup_status(uuid4()) is None

    store.create_pending_user("pending", "pending-hash")
    assert store.get_signup_by_login_id("pending") == ("pending", "pending-hash")
    assert store.get_signup_status(uuid4()) is None

    store.create_pending_user("rejected", "rejected-hash")
    assert store.review_signup_request("rejected", "reject", uuid4()) == "changed"
    assert store.get_signup_by_login_id("rejected") == ("rejected", "rejected-hash")


def test_memory_approval_reuses_create_user_defaults_and_keeps_request_pending_on_failure(monkeypatch):
    store = MemoryAuthStore()
    direct = store.create_user("direct", "direct-hash", "user")
    store.create_pending_user("approved", "approved-hash")
    assert store.review_signup_request("approved", "approve", uuid4()) == "changed"
    approved = store.get_by_login_id("approved")
    assert approved is not None
    assert (approved.role, approved.is_active, approved.groups) == (direct.role, direct.is_active, direct.groups)
    assert approved.password_hash == "approved-hash"

    store.create_pending_user("fails", "fails-hash")

    def fail_create(*_args):
        raise AccountExistsError("simulated create failure")

    monkeypatch.setattr(store, "_create_user_locked", fail_create)
    with pytest.raises(AccountExistsError):
        store.review_signup_request("fails", "approve", uuid4())
    assert store.get_signup_by_login_id("fails") == ("pending", "fails-hash")
    assert store.get_by_login_id("fails") is None


def test_memory_auth_store_serializes_concurrent_approval():
    store = MemoryAuthStore()
    store.create_pending_user("approve-once", "hash")
    results = []

    def approve():
        results.append(store.review_signup_request("approve-once", "approve", uuid4()))

    workers = [threading.Thread(target=approve) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert results.count("changed") == 1
    assert results.count("unchanged") == 7
    assert store.get_by_login_id("approve-once") is not None


def test_memory_auth_store_rejects_duplicates_and_invalid_actions():
    store = MemoryAuthStore()
    store.create_pending_user("duplicate-memory", "hash")
    with pytest.raises(AccountExistsError):
        store.create_pending_user("duplicate-memory", "other-hash")
    assert store.review_signup_request("missing", "approve", uuid4()) == "missing"
    with pytest.raises(ValueError):
        store.review_signup_request("duplicate-memory", "unknown", uuid4())


def test_memory_auth_store_serializes_concurrent_duplicate_signup():
    store = MemoryAuthStore()
    results = []

    def submit():
        try:
            store.create_pending_user("concurrent-memory", "hash")
            results.append("created")
        except AccountExistsError:
            results.append("duplicate")

    workers = [threading.Thread(target=submit) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert results.count("created") == 1
    assert results.count("duplicate") == 7
    assert len(store.list_signup_requests()) == 1


def test_postgres_signup_request_list_uses_request_login_id_without_user_join():
    from datetime import datetime, timezone

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Conn:
        def __init__(self, rows):
            self.rows = rows
            self.sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql = sql
            return Rows(self.rows)

    rows = [
        (1, "pending-user", datetime(2026, 1, 1, tzinfo=timezone.utc), "pending", False),
        (2, "approved-user", datetime(2026, 1, 2, tzinfo=timezone.utc), "approved", True),
        (3, "rejected-user", datetime(2026, 1, 3, tzinfo=timezone.utc), "rejected", False),
    ]
    connections = []

    def connect():
        connection = Conn(rows)
        connections.append(connection)
        return connection

    store = PostgresAuthStore(connect=connect)
    result = store.list_signup_requests()
    assert [(row.login_id, row.status) for row in result] == [
        ("pending-user", "pending"),
        ("approved-user", "approved"),
        ("rejected-user", "rejected"),
    ]
    assert "JOIN users" not in connections[0].sql
    assert "password_hash" not in connections[0].sql


def test_postgres_signup_status_contract_queries_only_approved_linked_users():
    approved_user_id = uuid4()

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def __init__(self, row):
            self.sql = ""
            self.params = None
            self.row = row

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql, self.params = sql, params
            return Cursor(self.row)

    connection = Conn(("approved",))
    store = PostgresAuthStore(connect=lambda: connection)
    assert store.get_signup_status(approved_user_id) == "approved"
    assert connection.params == (approved_user_id,)
    assert "user_id = %s" in connection.sql and "status = 'approved'" in connection.sql

    missing = PostgresAuthStore(connect=lambda: Conn(None))
    assert missing.get_signup_status(uuid4()) is None
    assert missing.get_signup_status("not-a-uuid") is None


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
    for key in ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE", "PROVENA_OWNER_LOGIN_ID"):
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
    # 내 정보(요청 1번): main.py가 /me에 profile_completed를 더하므로 내 정보 저장소도 가짜로 둔다(DB 연결 안 함)
    from profile_test_support import MemoryProfileStore
    monkeypatch.setattr("backend.main.PostgresProfileStore", lambda dsn: MemoryProfileStore())
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@db/x", AUTH_SECRET=secrets.token_urlsafe(32), **LOCAL)
    client = TestClient(app)
    assert client.get("/auth/csrf").status_code == 204
    headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
    bad = client.post("/auth/login", json={"login_id": "demo-user", "password": "wrong-password"}, headers=headers)
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"login_id": "demo-user", "password": password}, headers=headers)
    assert ok.status_code == 200 and ok.json() == {"user_id": str(uid), "role": "user"}
    assert client.cookies.get(AUTH_COOKIE_NAME)
    # 사용자 관리(요청 2번): main.py가 /me에 is_owner를 더한다. PROVENA_OWNER_LOGIN_ID가 없으면 false(닫힘)
    assert client.get("/me").json() == {"user_id": str(uid), "role": "user", "login_id": "demo-user", "profile_completed": False, "is_owner": False}
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
    # 내 정보(요청 1번): main.py가 /me에 profile_completed를 더하므로 내 정보 저장소도 가짜로 둔다(DB 연결 안 함)
    from profile_test_support import MemoryProfileStore

    class FakeProfileStore(MemoryProfileStore):
        def ensure_schema(self):   # 로컬 데모 시작(bootstrap_local_auth)이 부른다
            pass

    monkeypatch.setattr("backend.main.PostgresProfileStore", lambda dsn: FakeProfileStore())

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

