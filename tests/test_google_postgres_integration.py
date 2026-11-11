"""Google 로그인 Postgres 실통합 시험. TEST_DATABASE_URL이 있는 전용 DB에서만 실행한다(없으면 건너뜀)."""
from __future__ import annotations

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.auth import (
    GoogleAccountLinkError,
    GoogleSignupPendingError,
    GoogleSignupRejectedError,
    hash_password,
)
from backend.services.auth_store import PostgresAuthStore

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(전용 Postgres에서만)")


@pytest.fixture
def ctx():
    import psycopg

    store = PostgresAuthStore(DB)
    store.ensure_schema()
    prefix = f"gpg{secrets.token_hex(5)}"
    reviewer = store.create_user(f"{prefix}-reviewer", hash_password("review-pass-123"), "admin")
    yield store, prefix, reviewer
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM user_identities WHERE subject LIKE %s OR email LIKE %s", (f"{prefix}%", f"{prefix}%"))
        conn.execute("UPDATE signup_requests SET user_id = NULL, reviewed_by = NULL WHERE login_id LIKE %s", (f"{prefix}%",))
        conn.execute("DELETE FROM signup_requests WHERE login_id LIKE %s OR google_sub LIKE %s", (f"{prefix}%", f"{prefix}%"))
        conn.execute("DELETE FROM admin_role_log WHERE by_user_id = %s", (reviewer.user_id,))
        conn.execute("DELETE FROM users WHERE login_id LIKE %s", (f"{prefix}%",))


def _approved_email_account(store, reviewer, email: str):
    """이메일 가입 -> 인증 -> 승인. 공개 저장소 메서드만 쓴다."""
    store.create_pending_user(email, hash_password("member-pass-123"), email_verification_required=True)
    now = datetime.now(timezone.utc)
    store.issue_verification(email, "h", "123456", now, now + timedelta(minutes=5), 5, 0, lambda _code: None)
    assert store.verify_signup_code(email, "h", now, 5) == "verified"
    assert store.review_signup_request(email, "approve", reviewer.user_id) == "changed"
    return store.get_by_login_id(email)


def _query(sql: str, params: tuple = ()):
    import psycopg

    with psycopg.connect(DB, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def test_migration_114_can_run_repeatedly(ctx):
    store, _prefix, _reviewer = ctx
    store.ensure_schema()
    store.ensure_schema()


def test_link_existing_verified_account_keeps_role_and_is_idempotent(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-m@example.test"
    user = _approved_email_account(store, reviewer, email)
    for _ in range(2):  # 같은 구글 계정으로 다시 로그인해도 같은 계정, 줄은 1개
        linked = store.get_or_create_google_user("google", f"{prefix}-sub", email)
        assert linked.user_id == user.user_id and linked.role == "user" and linked.password_hash == user.password_hash
    assert _query("SELECT count(*) FROM user_identities WHERE user_id = %s", (user.user_id,)) == [(1,)]
    assert store.get_signup_by_login_id(email)[0] == "approved"  # 비밀번호 로그인 경로는 그대로


def test_admin_role_is_not_changed_by_linking(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-boss@example.test"
    boss = _approved_email_account(store, reviewer, email)
    assert store.set_role(email, "admin", reviewer.user_id) == "changed"
    linked = store.get_or_create_google_user("google", f"{prefix}-boss-sub", email)
    assert linked.user_id == boss.user_id and linked.role == "admin"
    assert store.get_by_login_id(email).role == "admin"


def test_email_case_and_spaces_are_normalised(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-case@example.test"
    user = _approved_email_account(store, reviewer, email)
    linked = store.get_or_create_google_user("google", f"{prefix}-case-sub", f"  {email.upper()} ")
    assert linked.user_id == user.user_id


def test_near_miss_email_does_not_link(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-near@example.test"
    _approved_email_account(store, reviewer, email)
    with pytest.raises(GoogleSignupPendingError):
        store.get_or_create_google_user("google", f"{prefix}-near-sub", email + ".evil")
    assert _query("SELECT count(*) FROM user_identities WHERE email = %s", (email,)) == [(0,)]


def test_account_without_verified_signup_proof_is_not_linked(ctx):
    store, prefix, _reviewer = ctx
    email = f"{prefix}-seed@example.test"
    store.create_user(email, hash_password("seed-pass-123"), "user")  # 신청 기록이 없는 시드·운영 생성 계정
    with pytest.raises(GoogleAccountLinkError):
        store.get_or_create_google_user("google", f"{prefix}-seed-sub", email)
    assert _query("SELECT count(*) FROM user_identities WHERE email = %s", (email,)) == [(0,)]


def test_inactive_account_is_not_linked(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-off@example.test"
    user = _approved_email_account(store, reviewer, email)
    _query("UPDATE users SET is_active = false WHERE user_id = %s", (user.user_id,))
    with pytest.raises(GoogleAccountLinkError):
        store.get_or_create_google_user("google", f"{prefix}-off-sub", email)


def test_second_google_account_cannot_take_over_a_linked_account(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-two@example.test"
    _approved_email_account(store, reviewer, email)
    store.get_or_create_google_user("google", f"{prefix}-first", email)
    with pytest.raises(GoogleAccountLinkError):
        store.get_or_create_google_user("google", f"{prefix}-second", email)
    assert _query("SELECT count(*) FROM user_identities WHERE email = %s", (email,)) == [(1,)]


def test_same_sub_reaches_same_account_after_email_change(ctx):
    store, prefix, reviewer = ctx
    email = f"{prefix}-chg@example.test"
    user = _approved_email_account(store, reviewer, email)
    sub = f"{prefix}-chg-sub"
    store.get_or_create_google_user("google", sub, email)
    again = store.get_or_create_google_user("google", sub, f"{prefix}-renamed@example.test")
    assert again.user_id == user.user_id
    assert _query("SELECT email FROM user_identities WHERE subject = %s", (sub,)) == [(f"{prefix}-renamed@example.test",)]


def test_no_account_makes_one_pending_request_then_approval_creates_passwordless_user_and_identity(ctx):
    store, prefix, reviewer = ctx
    email, sub = f"{prefix}-new@example.test", f"{prefix}-new-sub"
    for _ in range(2):  # 몇 번 와도 신청 1건, 계속 대기
        with pytest.raises(GoogleSignupPendingError):
            store.get_or_create_google_user("google", sub, email)
    assert _query(
        "SELECT count(*), max(status), bool_and(email_verified_at IS NOT NULL) FROM signup_requests WHERE google_sub = %s", (sub,)
    ) == [(1, "pending", True)]
    assert {r.login_id: r.status for r in store.list_signup_requests()}[email] == "pending"  # 관리자 승인 목록에 나온다
    assert store.get_by_login_id(email) is None
    assert store.get_signup_by_login_id(email) is None  # 비밀번호 로그인 경로에서는 안 보인다

    assert store.review_signup_request(email, "approve", reviewer.user_id) == "changed"
    user = store.get_or_create_google_user("google", sub, email)
    assert user.login_id == email and user.role == "user" and user.is_active and user.password_hash is None
    assert store.get_or_create_google_user("google", sub, email).user_id == user.user_id
    assert store.set_password(email, hash_password("new-pass-123")) is None  # 구글 계정에 비밀번호를 붙이지 않는다
    assert store.get_signup_status(user.user_id) == "approved"


def test_pending_password_signup_blocks_google_with_pending_and_no_new_row(ctx):
    store, prefix, _reviewer = ctx
    email = f"{prefix}-pw@example.test"
    store.create_pending_user(email, hash_password("member-pass-123"), email_verification_required=True)
    with pytest.raises(GoogleSignupPendingError):
        store.get_or_create_google_user("google", f"{prefix}-pw-sub", email)
    assert _query("SELECT count(*) FROM signup_requests WHERE login_id = %s", (email,)) == [(1,)]


def test_rejected_google_signup_stays_blocked(ctx):
    store, prefix, reviewer = ctx
    email, sub = f"{prefix}-rej@example.test", f"{prefix}-rej-sub"
    with pytest.raises(GoogleSignupPendingError):
        store.get_or_create_google_user("google", sub, email)
    assert store.review_signup_request(email, "reject", reviewer.user_id) == "changed"
    with pytest.raises(GoogleSignupRejectedError):
        store.get_or_create_google_user("google", sub, email)
    assert store.review_signup_request(email, "approve", reviewer.user_id) == "unchanged"


def test_concurrent_first_visits_make_exactly_one_row(ctx):
    store, prefix, reviewer = ctx

    def visit(email, sub):
        try:
            return store.get_or_create_google_user("google", sub, email).user_id
        except GoogleSignupPendingError:
            return "pending"

    new_email, new_sub = f"{prefix}-race@example.test", f"{prefix}-race-sub"
    with ThreadPoolExecutor(8) as pool:
        assert set(pool.map(lambda _i: visit(new_email, new_sub), range(16))) == {"pending"}
    assert _query("SELECT count(*) FROM signup_requests WHERE google_sub = %s", (new_sub,)) == [(1,)]

    email = f"{prefix}-race2@example.test"
    user = _approved_email_account(store, reviewer, email)
    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(lambda _i: visit(email, f"{prefix}-race2-sub"), range(16)))
    assert set(ids) == {user.user_id}
    assert _query("SELECT count(*) FROM user_identities WHERE user_id = %s", (user.user_id,)) == [(1,)]


def test_constraints_hold(ctx):
    import psycopg

    _store, prefix, reviewer = ctx
    with psycopg.connect(DB, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):  # 비밀번호도 구글 sub도 없는 가입 신청 금지
            conn.execute("INSERT INTO signup_requests (login_id, status) VALUES (%s, 'pending')", (f"{prefix}-bad@example.test",))
        with pytest.raises(psycopg.errors.CheckViolation):  # provider 는 google 만
            conn.execute(
                "INSERT INTO user_identities (provider, subject, user_id, email) VALUES ('x', 's', %s, 'e')", (reviewer.user_id,)
            )
