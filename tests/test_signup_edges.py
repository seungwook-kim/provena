"""가입 모서리: 미인증 신청은 24시간 규칙 전에는 덮어쓰지 않음(계정 가로채기 방지), 거절 뒤 재가입, 대문자 이메일 로그인.

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


# --- 1. 미인증 신청은 24시간 규칙(STALE_UNVERIFIED_SIGNUP_HOURS) 전에는 덮어쓰지 않는다 ------------

def test_second_signup_cannot_replace_password_of_unverified_request(monkeypatch):
    """피해자 가입 뒤 다른 사람이 같은 이메일로 자기 비밀번호를 넣어도 409, 피해자 비밀번호·코드는 그대로다."""
    client, store, sender = build(monkeypatch)
    assert signup(client, "victim@example.com", OLD).status_code == 201
    victim_code = sender.deliveries[-1]["code"]
    cool_down(store, "victim@example.com")  # 재발송 간격(60초)이 지난 뒤에도

    assert signup(client, "Victim@Example.com", NEW).status_code == 409
    row = store._signup_requests["victim@example.com"]
    assert verify_password(OLD, row["password_hash"]) and not verify_password(NEW, row["password_hash"])
    assert len(sender.deliveries) == 1
    assert verify(client, "victim@example.com", victim_code).status_code == 200


def test_verified_pending_cannot_be_overwritten(monkeypatch):
    client, store, sender = build(monkeypatch)
    assert signup(client, "done@example.com", OLD).status_code == 201
    assert verify(client, "done@example.com", sender.deliveries[-1]["code"]).status_code == 200
    assert signup(client, "done@example.com", NEW).status_code == 409
    assert verify_password(OLD, store._signup_requests["done@example.com"]["password_hash"])


def test_signup_response_says_request_received_not_completed(monkeypatch):
    from backend.auth import SIGNUP_RECEIVED_MESSAGE, SIGNUP_VERIFICATION_SENT_MESSAGE

    client, _store, _sender = build(monkeypatch)
    email = signup(client, "fresh@example.com", OLD)
    assert email.status_code == 201
    assert email.json()["code"] == "verification_sent" and email.json()["message"] == SIGNUP_VERIFICATION_SENT_MESSAGE
    assert "verification_expires_at" in email.json()
    plain = signup(client, "plain-id", OLD)
    assert plain.status_code == 201
    assert plain.json() == {"code": "approval_pending", "message": SIGNUP_RECEIVED_MESSAGE}
    assert "완료" not in email.json()["message"] + plain.json()["message"]

def test_login_before_email_verification_says_verify_first(monkeypatch):
    """인증 전 대기 신청으로 로그인하면 '관리자 승인 대기'가 아니라 '이메일 인증 먼저'(code signup_unverified)."""
    from backend.api.errors import install_error_handlers
    from backend.auth import SIGNUP_PENDING_MESSAGE, SIGNUP_UNVERIFIED_MESSAGE

    client, store, sender = build(monkeypatch)
    install_error_handlers(client.app)
    assert signup(client, "early@example.com", OLD).status_code == 201
    early = client.post("/auth/login", json={"login_id": "early@example.com", "password": OLD}, headers=csrf(client))
    assert early.status_code == 403
    assert early.json()["error"]["code"] == "signup_unverified" and early.json()["detail"] == SIGNUP_UNVERIFIED_MESSAGE
    wrong = client.post("/auth/login", json={"login_id": "early@example.com", "password": NEW}, headers=csrf(client))
    assert wrong.status_code == 401  # 비밀번호가 틀리면 신청 상태를 알려 주지 않는다
    assert verify(client, "early@example.com", sender.deliveries[-1]["code"]).status_code == 200
    later = client.post("/auth/login", json={"login_id": "early@example.com", "password": OLD}, headers=csrf(client))
    assert later.status_code == 403 and later.json()["detail"] == SIGNUP_PENDING_MESSAGE
    assert later.json()["error"]["code"] == "forbidden"

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


def test_review_by_id_acts_only_on_that_request(monkeypatch):
    """번호로 승인·거절하면 그 번호의 신청만 바뀐다. 사라진(대체된) 번호는 missing 이고 현재 신청은 그대로다."""
    client, store, sender = build(monkeypatch)
    admin = store.create_user("owner", hash_password("owner-pass-12345"), "admin")
    assert signup(client, "byid@example.com", OLD).status_code == 201
    old_id = store._signup_requests["byid@example.com"]["request_id"]
    assert store.review_signup_request_by_id(old_id, "reject", admin.user_id) == "changed"
    assert signup(client, "byid@example.com", NEW).status_code == 201
    assert verify(client, "byid@example.com", sender.deliveries[-1]["code"]).status_code == 200
    new_id = store._signup_requests["byid@example.com"]["request_id"]
    assert new_id != old_id
    assert store.review_signup_request_by_id(old_id, "approve", admin.user_id) == "missing"
    assert store._signup_requests["byid@example.com"]["status"] == "pending"
    assert store.review_signup_request_by_id(new_id, "approve", admin.user_id) == "changed"


# --- 3. 대문자 이메일 -----------------------------------------------------------

def test_login_finds_account_stored_with_uppercase_email(monkeypatch):
    client, store, _ = build(monkeypatch)
    store.create_user("Legacy@Example.com", hash_password(OLD), "user")  # 소문자화 규칙 전에 만든 계정
    assert store.get_by_login_id("legacy@example.com") is not None
    for typed in ("legacy@example.com", "LEGACY@EXAMPLE.COM", " Legacy@Example.com "):
        res = client.post("/auth/login", json={"login_id": typed, "password": OLD}, headers=csrf(client))
        assert res.status_code == 200, typed


def test_non_email_login_uses_signup_rule_but_keeps_legacy_uppercase_accounts(monkeypatch):
    """가입은 비이메일 아이디도 소문자로 저장한다. 로그인은 입력 그대로 먼저, 없으면 소문자로 찾는다."""
    client, store, _ = build(monkeypatch)
    store.create_user("Admin", hash_password(OLD), "admin")   # 소문자 규칙 전·데모 시드로 만든 대문자 계정
    store.create_user("kim", hash_password(OLD), "user")      # 가입으로 만든 계정(소문자 저장)

    def login(typed):
        return client.post("/auth/login", json={"login_id": typed, "password": OLD}, headers=csrf(client)).status_code

    assert login("Admin") == 200
    assert login("Kim") == 200 and login(" KIM ") == 200
    assert login("admin") == 401   # 다른 아이디다(대문자 계정을 소문자 입력으로 열지 않는다)


def test_non_email_pending_signup_found_with_any_case(monkeypatch):
    from backend.auth import SIGNUP_PENDING_MESSAGE

    client, store, _ = build(monkeypatch)
    assert signup(client, "Lee-Plain", OLD).status_code == 201   # 소문자로 저장된다
    assert "lee-plain" in store._signup_requests
    r = client.post("/auth/login", json={"login_id": "Lee-Plain", "password": OLD}, headers=csrf(client))
    assert r.status_code == 403 and r.json()["detail"] == SIGNUP_PENDING_MESSAGE


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
def test_pg_unverified_pending_is_not_overwritten_inside_24h(pgstore):
    import psycopg

    value, prefix = pgstore
    email = f"{prefix}-a@example.com"
    value.create_pending_user(email, hash_password(OLD), email_verification_required=True)
    with pytest.raises(AccountExistsError):
        value.create_pending_user(email, hash_password(NEW), email_verification_required=True)
    status, password_hash = value.get_signup_by_login_id(email)
    assert status == "pending" and verify_password(OLD, password_hash)
    with psycopg.connect(DB, autocommit=True) as conn:  # 24시간이 지난 신청만 지우고 새로 받는다
        conn.execute("UPDATE signup_requests SET requested_at = now() - interval '25 hours' WHERE login_id = %s", (email,))
    value.create_pending_user(email, hash_password(NEW), email_verification_required=True)
    assert verify_password(NEW, value.get_signup_by_login_id(email)[1])
    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT count(*) FROM signup_requests WHERE login_id = %s", (email,)).fetchone()[0] == 1


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
def test_pg_review_by_id_acts_only_on_that_row(pgstore):
    """같은 이메일에 거절 행(#옛)과 새 신청(#새)이 있을 때, 옛 번호로 승인해도 새 신청이 승인되지 않는다."""
    import psycopg

    value, prefix = pgstore
    reviewer = value.create_user(f"{prefix}-rev2", hash_password(OLD), "admin")
    email = f"{prefix}-d@example.com"
    value.create_pending_user(email, hash_password(OLD))
    assert value.review_signup_request(email, "reject", reviewer.user_id) == "changed"
    value.create_pending_user(email, hash_password(NEW))
    with psycopg.connect(DB) as conn:
        (old_id,), (new_id,) = conn.execute(
            "SELECT request_id FROM signup_requests WHERE login_id = %s ORDER BY request_id", (email,)).fetchall()
    assert value.review_signup_request_by_id(old_id, "approve", reviewer.user_id) == "unchanged"
    assert value.get_signup_by_login_id(email)[0] == "pending"  # 새 신청은 그대로
    assert value.review_signup_request_by_id(new_id, "reject", reviewer.user_id) == "changed"
    with psycopg.connect(DB) as conn:
        statuses = [r[0] for r in conn.execute(
            "SELECT status FROM signup_requests WHERE login_id = %s ORDER BY request_id", (email,)).fetchall()]
    assert statuses == ["rejected", "rejected"]
    assert value.review_signup_request_by_id(10**9, "approve", reviewer.user_id) == "missing"


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

    sql = (ROOT / "db" / "113_signup_edges.sql").read_text(encoding="utf-8")
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


@pg
def test_pg_migration_lowercases_signup_request_emails_and_skips_collisions(pgstore):
    import psycopg

    _value, prefix = pgstore
    sql = (ROOT / "db" / "113_signup_edges.sql").read_text(encoding="utf-8")
    rows = [(f"{prefix}-Solo@X.com", "approved"), (f"{prefix}-Dup@X.com", "rejected"), (f"{prefix}-dup@x.com", "pending")]
    with psycopg.connect(DB, autocommit=True) as conn:
        for login_id, status in rows:
            conn.execute("INSERT INTO signup_requests (login_id, password_hash, status) VALUES (%s, 'h', %s)", (login_id, status))
        conn.execute(sql)
        conn.execute(sql)  # 다시 돌려도 같다
        got = {r[0] for r in conn.execute("SELECT login_id FROM signup_requests WHERE login_id ILIKE %s", (f"{prefix}%",)).fetchall()}
    assert got == {f"{prefix}-solo@x.com", f"{prefix}-Dup@X.com", f"{prefix}-dup@x.com"}  # 겹치는 쌍은 그대로


@pg
def test_pg_ensure_schema_reruns_after_rejected_email_signs_up_again():
    """로컬은 시작할 때마다 ensure_schema 가 107 을 다시 돌린다. 거절 행과 같은 이메일의 새 신청이 있어도 통과해야 한다.

    새 스키마에서 한다(끝나면 지운다). 107 은 113 전에는 옛 소문자 색인을 만들고, 113 뒤에는 되살리지 않는다.
    """
    import psycopg

    schema = f"reboot_{secrets.token_hex(4)}"
    old_index, new_index = "signup_requests_login_id_lower_unique", "signup_requests_login_id_lower_open_unique"

    def connect():
        return psycopg.connect(DB, autocommit=True, connect_timeout=5, prepare_threshold=None,
                               options=f"-c search_path={schema}")

    def indexes():
        with connect() as conn:
            return {r[0] for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = 'signup_requests'", (schema,)).fetchall()}

    def read(name):
        return (ROOT / "db" / name).read_text(encoding="utf-8")

    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with connect() as conn:  # 113 전: 107 은 전과 같이 옛 색인을 만든다(두 번 돌려도 같다)
            for name in ("101_auth_users.sql", "103_auth_token_revocations.sql", "105_admin_role_log.sql",
                         "106_signup_approval.sql", "107_email_signup_verification.sql", "107_email_signup_verification.sql"):
                conn.execute(read(name))
        assert old_index in indexes() and new_index not in indexes()

        value = PostgresAuthStore(connect=connect)
        value.ensure_schema()  # 113 이 옛 색인을 새 색인으로 바꾼다
        assert old_index not in indexes() and new_index in indexes()

        reviewer = value.create_user("reboot-admin", hash_password(OLD), "admin")
        email = "reboot@example.com"
        value.create_pending_user(email, hash_password(OLD), email_verification_required=True)
        assert value.review_signup_request(email, "reject", reviewer.user_id) == "changed"
        value.create_pending_user(email, hash_password(NEW), email_verification_required=True)

        value.ensure_schema()  # 다시 시작: 107 이 옛 색인을 되살리면 여기서 UniqueViolation
        value.ensure_schema()
        with connect() as conn:  # 107·113·114 를 손으로 두 번 더 돌려도 오류가 없다
            for _round in range(2):
                for name in ("107_email_signup_verification.sql", "113_signup_edges.sql", "114_google_identities.sql"):
                    conn.execute(read(name))
            statuses = [r[0] for r in conn.execute(
                "SELECT status FROM signup_requests WHERE login_id = %s ORDER BY request_id", (email,)).fetchall()]
        assert statuses == ["rejected", "pending"]
        assert old_index not in indexes() and new_index in indexes()
        with pytest.raises(AccountExistsError):  # 거절되지 않은 신청은 여전히 하나뿐
            value.create_pending_user(email, hash_password(NEW), email_verification_required=True)
    finally:
        with psycopg.connect(DB, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
