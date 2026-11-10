"""회원가입 승인 Postgres 실통합 시험. TEST_DATABASE_URL이 있는 전용 DB에서만 실행한다."""
from __future__ import annotations

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from backend.auth import hash_password, verify_password
from backend.services.auth_store import AccountExistsError, PostgresAuthStore


DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(전용 Postgres에서만)")


@pytest.fixture
def store():
    import psycopg

    value = PostgresAuthStore(DB)
    value.ensure_schema()
    prefix = f"signup-pg-{secrets.token_hex(5)}"
    yield value, prefix
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM signup_requests WHERE login_id LIKE %s", (f"{prefix}%",))
        conn.execute("DELETE FROM users WHERE login_id LIKE %s", (f"{prefix}%",))


def test_postgres_signup_lifecycle_and_duplicate_protection(store):
    value, prefix = store
    reviewer = value.create_user(f"{prefix}-reviewer", hash_password("review-pass-123"), "admin")
    pending = f"{prefix}-pending"
    rejected = f"{prefix}-rejected"
    approved = f"{prefix}-approved"
    password_hash = hash_password("signup-pass-123")

    value.create_pending_user(pending, password_hash)
    assert value.get_by_login_id(pending) is None
    assert value.get_signup_by_login_id(pending) == ("pending", password_hash)
    assert value.get_signup_status(uuid4()) is None
    with pytest.raises(AccountExistsError):
        value.create_pending_user(pending, password_hash)
    existing = value.create_user(f"{prefix}-existing", password_hash, "user")
    with pytest.raises(AccountExistsError):
        value.create_pending_user(existing.login_id, password_hash)

    value.create_pending_user(rejected, password_hash)
    assert value.review_signup_request(rejected, "reject", reviewer.user_id) == "changed"
    assert value.get_by_login_id(rejected) is None
    assert value.get_signup_by_login_id(rejected) == ("rejected", password_hash)
    assert value.review_signup_request(rejected, "approve", reviewer.user_id) == "unchanged"

    value.create_pending_user(approved, password_hash)
    rows = {row.login_id: row for row in value.list_signup_requests()}
    assert rows[pending].status == "pending" and not hasattr(rows[pending], "password_hash")
    assert rows[rejected].status == "rejected"
    assert value.review_signup_request(approved, "approve", reviewer.user_id) == "changed"
    user = value.get_by_login_id(approved)
    assert user is not None and verify_password("signup-pass-123", user.password_hash)
    assert value.get_signup_status(user.user_id) == "approved"
    assert value.review_signup_request(approved, "approve", reviewer.user_id) == "unchanged"

    import psycopg
    with psycopg.connect(DB, autocommit=True) as conn:
        reviewed = conn.execute(
            "SELECT status, user_id, reviewed_by, reviewed_at, password_hash FROM signup_requests WHERE login_id = %s",
            (approved,),
        ).fetchone()
    assert reviewed[:3] == ("approved", user.user_id, reviewer.user_id)
    assert reviewed[3] is not None and reviewed[4] == user.password_hash


def test_postgres_signup_rollback_and_concurrent_requests(store):
    value, prefix = store
    reviewer = value.create_user(f"{prefix}-reviewer", hash_password("review-pass-123"), "admin")
    failing = f"{prefix}-rollback"
    value.create_pending_user(failing, hash_password("signup-pass-123"))

    import psycopg
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION signup_test_reject_insert() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'forced user insert failure'; END $$",
        )
        conn.execute("CREATE TRIGGER signup_test_reject_insert BEFORE INSERT ON users FOR EACH ROW EXECUTE FUNCTION signup_test_reject_insert()")
    try:
        with pytest.raises(psycopg.errors.RaiseException):
            value.review_signup_request(failing, "approve", reviewer.user_id)
    finally:
        with psycopg.connect(DB, autocommit=True) as conn:
            conn.execute("DROP TRIGGER IF EXISTS signup_test_reject_insert ON users")
            conn.execute("DROP FUNCTION IF EXISTS signup_test_reject_insert()")
    assert value.get_by_login_id(failing) is None
    assert value.get_signup_by_login_id(failing)[0] == "pending"
    assert value.review_signup_request(failing, "approve", reviewer.user_id) == "changed"

    duplicate = f"{prefix}-concurrent-request"
    def submit():
        try:
            value.create_pending_user(duplicate, hash_password("signup-pass-123"))
            return "created"
        except AccountExistsError:
            return "duplicate"
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _value: submit(), range(8)))
    assert outcomes.count("created") == 1 and outcomes.count("duplicate") == 7

    concurrent = f"{prefix}-concurrent-approve"
    value.create_pending_user(concurrent, hash_password("signup-pass-123"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _value: value.review_signup_request(concurrent, "approve", reviewer.user_id), range(8)))
    assert outcomes.count("changed") == 1 and outcomes.count("unchanged") == 7
    assert value.get_by_login_id(concurrent) is not None


def test_postgres_fastapi_signup_approval_and_rejection_flow(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth_test_support import MemoryRevocationStore
    from backend.admin_api import create_admin_router
    from backend.auth import CSRF_COOKIE_NAME, create_access_token, create_auth_router

    value, prefix = store
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    owner = value.create_user(f"{prefix}-owner", hash_password("owner-pass-123"), "admin")
    member = value.create_user(f"{prefix}-member", hash_password("member-pass-123"), "user")
    secret = "x" * 32
    app = FastAPI()
    revocations = MemoryRevocationStore()
    app.include_router(create_auth_router(store=value, secret=secret, cookie_secure=False, revocation_store=revocations))
    app.include_router(create_admin_router(store=value, owner_login_id=owner.login_id, secret=secret, revocation_store=revocations))
    owner_client = TestClient(app)
    owner_client.cookies.set("provena_auth", create_access_token(owner.user_id, owner.role, secret=secret))
    member_client = TestClient(app)
    member_client.cookies.set("provena_auth", create_access_token(member.user_id, member.role, secret=secret))

    def csrf(client):
        assert client.get("/auth/csrf").status_code == 204
        return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}

    pending = f"{prefix}-api-approved"
    password = "signup-pass-123"
    assert TestClient(app).get("/admin/signup-requests").status_code == 401
    assert member_client.get("/admin/signup-requests").status_code == 403
    assert owner_client.post("/auth/signup", json={"login_id": pending, "password": password, "password_confirmation": password}, headers=csrf(owner_client)).status_code == 201
    assert member_client.post(f"/admin/signup-requests/{pending}/approve", headers=csrf(member_client)).status_code == 403
    assert owner_client.post(f"/admin/signup-requests/{pending}/approve").status_code == 403
    assert owner_client.post(f"/admin/signup-requests/{pending}/invalid", headers=csrf(owner_client)).status_code == 422
    assert owner_client.post(f"/admin/signup-requests/{prefix}-missing/approve", headers=csrf(owner_client)).status_code == 404
    applicant = TestClient(app)
    blocked = applicant.post("/auth/login", json={"login_id": pending, "password": password}, headers=csrf(applicant))
    assert blocked.status_code == 403 and "승인 대기" in blocked.json()["detail"]
    assert owner_client.get("/admin/signup-requests").status_code == 200
    assert owner_client.post(f"/admin/signup-requests/{pending}/approve", headers=csrf(owner_client)).status_code == 200
    logged_in = applicant.post("/auth/login", json={"login_id": pending, "password": password}, headers=csrf(applicant))
    assert logged_in.status_code == 200 and "provena_auth" in logged_in.headers.get("set-cookie", "")

    rejected = f"{prefix}-api-rejected"
    assert owner_client.post("/auth/signup", json={"login_id": rejected, "password": password, "password_confirmation": password}, headers=csrf(owner_client)).status_code == 201
    assert owner_client.post(f"/admin/signup-requests/{rejected}/reject", headers=csrf(owner_client)).status_code == 200
    rejected_client = TestClient(app)
    denied = rejected_client.post("/auth/login", json={"login_id": rejected, "password": password}, headers=csrf(rejected_client))
    assert denied.status_code == 403 and "승인되지 않았습니다" in denied.json()["detail"]
    assert value.get_by_login_id(rejected) is None

    existing_client = TestClient(app)
    existing_login = existing_client.post("/auth/login", json={"login_id": member.login_id, "password": "member-pass-123"}, headers=csrf(existing_client))
    owner_login_client = TestClient(app)
    owner_login = owner_login_client.post("/auth/login", json={"login_id": owner.login_id, "password": "owner-pass-123"}, headers=csrf(owner_login_client))
    assert existing_login.status_code == owner_login.status_code == 200
