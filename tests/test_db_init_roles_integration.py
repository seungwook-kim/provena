"""db/*.sql 초기화 Postgres 실통합 시험. TEST_DATABASE_URL이 있는 서버에서만 실행한다.

docker compose의 db(pgvector/pgvector:pg16)에는 Supabase 역할 anon·authenticated가 없고 Supabase에는 있다.
두 환경 모두에서 db/*.sql이 오류 없이 처음부터 끝까지 적용되는지 본다. 시험마다 임시 DB를 만들고 지우므로
TEST_DATABASE_URL의 DB 자체는 건드리지 않는다(CREATEDB 권한 필요, 역할이 필요하면 CREATEROLE 권한도).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest


DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(전용 Postgres에서만)")

DB_DIR = Path(__file__).resolve().parents[1] / "db"
SUPABASE_ROLES = ("anon", "authenticated")


def _roles_present(conn) -> set[str]:
    rows = conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(SUPABASE_ROLES),)).fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def scratch_db():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = f"provena_init_{secrets.token_hex(5)}"
    with psycopg.connect(DB, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(DB, dbname=name)
    finally:
        with psycopg.connect(DB, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _apply_all(dsn: str) -> list[str]:
    import psycopg

    files = sorted(DB_DIR.glob("*.sql"))
    assert files, "db/*.sql 없음"
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in files:
            conn.execute(path.read_text(encoding="utf-8"))
    return [path.name for path in files]


def _assert_signup_requests_locked(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass('public.signup_requests')"
        ).fetchone()
        assert row is not None, "signup_requests 표가 만들어지지 않음"
        assert row[0] is True, "signup_requests RLS가 꺼져 있음"
        for role in _roles_present(conn):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                allowed = conn.execute(
                    "SELECT has_table_privilege(%s, 'public.signup_requests', %s)", (role, privilege)
                ).fetchone()[0]
                assert not allowed, f"{role}에 signup_requests {privilege} 권한이 남아 있음"
        # PUBLIC 권한도 없어야 한다: 임의의 새 역할이 읽을 수 없다.
        public_acl = conn.execute(
            "SELECT 1 FROM pg_class c, aclexplode(c.relacl) a "
            "WHERE c.oid = to_regclass('public.signup_requests') AND a.grantee = 0"
        ).fetchone()
        assert public_acl is None, "signup_requests에 PUBLIC 권한이 남아 있음"


def test_init_scripts_apply_on_plain_postgres_without_supabase_roles(scratch_db):
    import psycopg

    with psycopg.connect(DB, autocommit=True) as conn:
        if _roles_present(conn):
            pytest.skip("이 서버에는 anon·authenticated 역할이 이미 있다(일반 Postgres 시험은 역할 없는 서버에서만)")

    _apply_all(scratch_db)
    _assert_signup_requests_locked(scratch_db)


@pytest.fixture
def supabase_roles():
    """anon·authenticated가 없으면 만들고, 이 시험이 만든 것만 시험 뒤에 지운다(임시 DB가 먼저 지워진 뒤)."""
    import psycopg

    created: list[str] = []
    with psycopg.connect(DB, autocommit=True) as conn:
        present = _roles_present(conn)
        for role in SUPABASE_ROLES:
            if role not in present:
                conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
                created.append(role)
    yield
    with psycopg.connect(DB, autocommit=True) as conn:
        for role in created:
            conn.execute(f'DROP ROLE IF EXISTS "{role}"')


def test_init_scripts_apply_with_supabase_roles_and_revoke_default_grants(supabase_roles, scratch_db):
    import psycopg

    # Supabase처럼 새 public 표에 anon·authenticated 권한이 기본으로 열리게 한다(이 임시 DB에만 적용된다).
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated")

    _apply_all(scratch_db)
    _assert_signup_requests_locked(scratch_db)

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        assert _roles_present(conn) == set(SUPABASE_ROLES)
        # 기본 권한이 실제로 열려 있었음을 다른 표로 확인한다(회수 대상이 106 하나뿐임을 보여 준다).
        assert conn.execute("SELECT has_table_privilege('anon', 'public.users', 'SELECT')").fetchone()[0] is True
