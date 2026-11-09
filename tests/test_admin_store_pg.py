"""사용자 관리 저장소 메서드(list_users·set_role·create_user·set_password, db/105_admin_role_log.sql)를 진짜 Postgres로 시험한다.

TEST_DATABASE_URL 이 있을 때만 돈다. 시험용 DB에만 쓴다(계정은 무작위 아이디로 만들고 끝나면 기록·계정을 지운다).
예: TEST_DATABASE_URL=postgresql://app:<비밀번호>@127.0.0.1:54331/app_myinfo
"""
import os
import secrets

import pytest

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 Postgres에서만)")


@pytest.fixture
def store():
    import psycopg

    from backend.services.auth_store import PostgresAuthStore

    s = PostgresAuthStore(DB)
    s.ensure_schema()
    s.ensure_schema()   # 여러 번 돌려도 된다
    made = []

    def new_id():
        made.append(f"pytest-admin-{secrets.token_hex(6)}")
        return made[-1]

    yield s, new_id
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM admin_role_log WHERE by_user_id IN (SELECT user_id FROM users WHERE login_id = ANY(%s)) "
                     "OR target_user_id IN (SELECT user_id FROM users WHERE login_id = ANY(%s))", (made, made))
        conn.execute("DELETE FROM users WHERE login_id = ANY(%s)", (made,))


def _log_rows(user_id):
    import psycopg

    with psycopg.connect(DB, autocommit=True) as conn:
        return conn.execute("SELECT by_user_id, target_user_id, action FROM admin_role_log WHERE target_user_id = %s "
                            "ORDER BY log_id", (user_id,)).fetchall()


def test_create_user_refuses_duplicate_and_set_password_keeps_role(store):
    from backend.auth import hash_password, verify_password
    from backend.services.auth_store import AccountExistsError

    s, new_id = store
    login_id = new_id()
    first = s.create_user(login_id, hash_password("first-pass-1"), "admin")
    assert first.role == "admin"
    with pytest.raises(AccountExistsError):
        s.create_user(login_id, hash_password("second-pass-2"), "user")
    assert verify_password("first-pass-1", s.get_by_login_id(login_id).password_hash)
    changed = s.set_password(login_id, hash_password("third-pass-3"))
    assert changed.role == "admin" and changed.user_id == first.user_id
    assert verify_password("third-pass-3", s.get_by_login_id(login_id).password_hash)
    assert s.set_password(new_id(), hash_password("x-pass-1234")) is None


def test_list_users_has_no_hash_and_set_role_writes_one_log_row(store):
    from backend.auth import hash_password

    s, new_id = store
    owner = s.create_user(new_id(), hash_password("owner-pass-1"), "admin")
    member = s.create_user(new_id(), hash_password("member-pass-1"), "user")
    rows = {r.login_id: r for r in s.list_users()}
    assert rows[member.login_id].role == "user" and rows[member.login_id].created_at is not None
    assert not hasattr(rows[member.login_id], "password_hash")

    assert s.set_role(member.login_id, "admin", owner.user_id) == "changed"
    assert s.get_by_login_id(member.login_id).role == "admin"
    assert s.set_role(member.login_id, "admin", owner.user_id) == "unchanged"
    assert s.set_role(member.login_id, "user", owner.user_id) == "changed"
    assert [(str(b), str(t), a) for b, t, a in _log_rows(member.user_id)] == [
        (str(owner.user_id), str(member.user_id), "promote"), (str(owner.user_id), str(member.user_id), "revoke")]
    assert s.set_role(new_id(), "admin", owner.user_id) == "missing"


def test_set_role_rolls_back_when_log_insert_fails(store):
    """by_user_id 가 users 에 없으면 외래키로 INSERT 가 실패한다 → 같은 트랜잭션의 UPDATE 도 되돌아가야 한다."""
    from uuid import uuid4

    import psycopg

    from backend.auth import hash_password

    s, new_id = store
    member = s.create_user(new_id(), hash_password("member-pass-1"), "user")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        s.set_role(member.login_id, "admin", uuid4())
    assert s.get_by_login_id(member.login_id).role == "user"
    assert _log_rows(member.user_id) == []


def test_set_role_on_inactive_target_changes_nothing(store):
    import psycopg

    from backend.auth import hash_password

    s, new_id = store
    owner = s.create_user(new_id(), hash_password("owner-pass-1"), "admin")
    sleeper = s.create_user(new_id(), hash_password("sleep-pass-1"), "user")
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("UPDATE users SET is_active = false WHERE user_id = %s", (sleeper.user_id,))
    assert s.set_role(sleeper.login_id, "admin", owner.user_id) == "inactive"
    assert s.get_by_login_id(sleeper.login_id).role == "user" and _log_rows(sleeper.user_id) == []
