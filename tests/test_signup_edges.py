"""가입 모서리 3건: 미인증 신청 덮어쓰기, 거절 뒤 재가입, 대문자 이메일 로그인.

메모리 저장소 시험은 항상 돈다. Postgres 시험은 TEST_DATABASE_URL 이 있을 때만 돈다(전용 DB).
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_test_support import MemoryRevocationStore
from backend.auth import CSRF_COOKIE_NAME, create_auth_router, hash_password, verify_password
from backend.services.auth_store import AccountExistsError, MemoryAuthStore, PostgresAuthStore
from backend.services.email_sender import RecordingEmailSender

ROOT = Path(__file__).resolve().parents[1]
OLD = "old-pass-12345"
NEW = "new-pass-67890"


def build(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MemoryAuthStore()
    sender = RecordingEmailSender()
    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret="s" * 32, cookie_secure=False,
                                          revocation_store=MemoryRevocationStore(), email_sender=sender))
    return TestClient(app), store, sender


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def signup(client, email, password):
    return client.post("/auth/signup", json={"login_id": email, "password": password, "password_confirmation": password},
                       headers=csrf(client))


def verify(client, email, code):
    return client.post("/auth/signup/verify", json={"login_id": email, "code": code}, headers=csrf(client))


def cool_down(store, email):
    store._signup_requests[email]["last_verification_sent_at"] = datetime.now(timezone.utc) - timedelta(hours=1)


# --- 1. 미인증 신청 덮어쓰기 -------------------------------------------------

def test_unverified_pending_is_overwritten_with_new_password_and_new_code(monkeypatch):
    client, store, sender = build(monkeypatch)
    assert signup(client, "squat@example.com", OLD).status_code == 201
    first_code = sender.deliveries[-1]["code"]
    cool_down(store, "squat@example.com")

    assert signup(client, "Squat@Example.com", NEW).status_code == 201
    assert len(sender.deliveries) == 2
    row = store._signup_requests["squat@example.com"]
    assert verify_password(NEW, row["password_hash"]) and not verify_password(OLD, row["password_hash"])
    # 옛 코드로는 인증되지 않고, 새 코드로만 된다(실제로 받은 사람만 끝낼 수 있다)
    if sender.deliveries[-1]["code"] != first_code:
        assert verify(client, "squat@example.com", first_code).status_code == 400
    assert verify(client, "squat@example.com", sender.deliveries[-1]["code"]).status_code == 200


def test_overwrite_inside_resend_cooldown_is_429_and_keeps_old_request(monkeypatch):
    client, store, sender = build(monkeypatch)
    assert signup(client, "fast@example.com", OLD).status_code == 201
    again = signup(client, "fast@example.com", NEW)
    assert again.status_code == 429
    row = store._signup_requests["fast@example.com"]
    assert verify_password(OLD, row["password_hash"])  # 발송 제한에 걸리면 비밀번호도 바꾸지 않는다
    assert len(sender.deliveries) == 1


def test_overwrite_mail_failure_keeps_existing_request(monkeypatch):
    client, store, sender = build(monkeypatch)
    assert signup(client, "keep@example.com", OLD).status_code == 201
    cool_down(store, "keep@example.com")
    request_id = store._signup_requests["keep@example.com"]["request_id"]

    def boom(**_):
        raise RuntimeError("smtp down")
    sender.send_verification_email = boom
    assert signup(client, "keep@example.com", NEW).status_code == 503
    # 덮어쓰기 중 실패해도 원래 신청을 지우지 않는다(처음 만든 경우만 지운다)
    assert store._signup_requests["keep@example.com"]["request_id"] == request_id


def test_verified_pending_cannot_be_overwritten(monkeypatch):
    client, store, sender = build(monkeypatch)
    assert signup(client, "done@example.com", OLD).status_code == 201
    assert verify(client, "done@example.com", sender.deliveries[-1]["code"]).status_code == 200
    assert signup(client, "done@example.com", NEW).status_code == 409
    assert verify_password(OLD, store._signup_requests["done@example.com"]["password_hash"])


# --- 2. 거절 뒤 재가입 ---------------------------------------------------------

def test_rejected_email_can_sign_up_again(monkeypatch):
    client, store, sender = build(monkeypatch)
    admin = store.create_user("owner", hash_password("owner-pass-12345"), "admin")
    assert signup(client, "again@example.com", OLD).status_code == 201
    assert verify(client, "again@example.com", sender.deliveries[-1]["code"]).status_code == 200
    assert store.review_signup_request("again@example.com", "reject", admin.user_id) == "changed"
    assert store.get_signup_by_login_id("again@example.com")[0] == "rejected"

    assert signup(client, "again@example.com", NEW).status_code == 201
    status, password_hash = store.get_signup_by_login_id("again@example.com")
    assert status == "pending" and verify_password(NEW, password_hash)
    assert verify(client, "again@example.com", sender.deliveries[-1]["code"]).status_code == 200
    assert store.review_signup_request("again@example.com", "approve", admin.user_id) == "changed"


# --- 3. 대문자 이메일 -----------------------------------------------------------

def test_login_finds_account_stored_with_uppercase_email(monkeypatch):
    client, store, _ = build(monkeypatch)
    store.create_user("Legacy@Example.com", hash_password(OLD), "user")  # 소문자화 규칙 전에 만든 계정
    assert store.get_by_login_id("legacy@example.com") is not None
    for typed in ("legacy@example.com", "LEGACY@EXAMPLE.COM", " Legacy@Example.com "):
        res = client.post("/auth/login", json={"login_id": typed, "password": OLD}, headers=csrf(client))
        assert res.status_code == 200, typed


def test_non_email_login_id_stays_case_sensitive(monkeypatch):
    _, store, _ = build(monkeypatch)
    store.create_user("Admin", hash_password(OLD), "admin")
    assert store.get_by_login_id("Admin") is not None
    assert store.get_by_login_id("admin") is None


# --- Postgres --------------------------------------------------------------------

DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(전용 Postgres에서만)")


@pytest.fixture
def pgstore():
    import psycopg

    value = PostgresAuthStore(DB)
    value.ensure_schema()
    prefix = f"edge-{secrets.token_hex(5)}"
    yield value, prefix
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM signup_requests WHERE lower(login_id) LIKE %s", (f"{prefix}%",))
        conn.execute("DELETE FROM users WHERE lower(login_id) LIKE %s", (f"{prefix}%",))


@pg
def test_pg_unverified_pending_overwrite_keeps_one_row(pgstore):
    import psycopg

    value, prefix = pgstore
    email = f"{prefix}-a@example.com"
    value.create_pending_user(email, hash_password(OLD), email_verification_required=True)
    assert value.create_pending_user(email, hash_password(NEW), email_verification_required=True) == "replaced"
    status, password_hash = value.get_signup_by_login_id(email)
    assert status == "pending" and verify_password(NEW, password_hash)
    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT count(*) FROM signup_requests WHERE login_id = %s", (email,)).fetchone()[0] == 1
    # 인증을 마친 신청은 덮어쓰지 않는다
    code_hash = "h" * 64
    now = datetime.now(timezone.utc)
    assert value.issue_verification(email, code_hash, "000000", now, now + timedelta(minutes=5), 5, 0, lambda _c: None) == "sent"
    assert value.verify_signup_code(email, code_hash, now, 5) == "verified"
    with pytest.raises(AccountExistsError):
        value.create_pending_user(email, hash_password(OLD), email_verification_required=True)


@pg
def test_pg_rejected_request_allows_signup_again_and_keeps_history(pgstore):
    import psycopg

    value, prefix = pgstore
    reviewer = value.create_user(f"{prefix}-rev", hash_password(OLD), "admin")
    email = f"{prefix}-b@example.com"
    for _round in range(2):
        value.create_pending_user(email, hash_password(OLD), email_verification_required=True)
        assert value.review_signup_request(email, "reject", reviewer.user_id) == "changed"
    value.create_pending_user(email, hash_password(NEW), email_verification_required=True)
    assert value.get_signup_by_login_id(email)[0] == "pending"
    with psycopg.connect(DB) as conn:
        statuses = [r[0] for r in conn.execute(
            "SELECT status FROM signup_requests WHERE login_id = %s ORDER BY request_id", (email,)).fetchall()]
    assert statuses == ["rejected", "rejected", "pending"]  # 거절 기록은 남는다
    plain = f"{prefix}-plain"  # 이메일 아닌 아이디도 같다
    value.create_pending_user(plain, hash_password(OLD))
    assert value.review_signup_request(plain, "reject", reviewer.user_id) == "changed"
    value.create_pending_user(plain, hash_password(NEW))
    with pytest.raises(AccountExistsError):
        value.create_pending_user(plain, hash_password(NEW))


@pg
def test_pg_uppercase_email_lookup_and_unique_lower(pgstore):
    import psycopg

    value, prefix = pgstore
    upper = f"{prefix}-C@Example.com"
    with psycopg.connect(DB, autocommit=True) as conn:  # 규칙 전 데이터를 흉내 내 직접 넣는다
        conn.execute("INSERT INTO users (login_id, password_hash, role) VALUES (%s, %s, 'user')", (upper, hash_password(OLD)))
    assert value.get_by_login_id(upper.lower()) is not None
    with pytest.raises(Exception):  # 대소문자만 다른 두 번째 계정은 DB가 막는다
        with psycopg.connect(DB, autocommit=True) as conn:
            conn.execute("INSERT INTO users (login_id, password_hash, role) VALUES (%s, %s, 'user')", (upper.lower(), hash_password(OLD)))


@pg
def test_pg_migration_lowercases_legacy_emails_and_skips_collisions():
    import psycopg

    sql = (ROOT / "db" / "112_signup_edges.sql").read_text(encoding="utf-8")
    prefix = f"mig-{secrets.token_hex(5)}"
    with psycopg.connect(DB, autocommit=True) as conn:
        try:
            conn.execute("DROP INDEX IF EXISTS users_login_id_lower_unique")
            conn.execute("INSERT INTO users (login_id, password_hash, role) VALUES (%s,'h','user'), (%s,'h','user'), (%s,'h','user')",
                         (f"{prefix}-Solo@X.com", f"{prefix}-Dup@X.com", f"{prefix}-DUP@x.com"))
            conn.execute(sql)
            conn.execute(sql)  # 다시 돌려도 같다
            got = {r[0] for r in conn.execute("SELECT login_id FROM users WHERE login_id ILIKE %s", (f"{prefix}%",)).fetchall()}
            assert f"{prefix}-solo@x.com" in got
            assert {f"{prefix}-Dup@X.com", f"{prefix}-DUP@x.com"} <= got  # 충돌하는 쌍은 건드리지 않는다
        finally:
            conn.execute("DELETE FROM users WHERE login_id ILIKE %s", (f"{prefix}%",))
            conn.execute(sql)  # 색인 복구
