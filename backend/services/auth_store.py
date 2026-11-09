"""Postgres `users` 테이블을 읽는 AuthStore (backend/auth.py의 Protocol 구현).

- 로그인 계약은 `get_by_login_id(str)`, `get_by_user_id(UUID | str)` 두 조회다. 저장소 연결 실패를 다른 저장소로 바꿔 끼우지 않는다
  (예외는 auth 라우터가 503으로 바꾼다).
- 계정 만들기: 로컬 데모 시드(`demo_seed.py`)는 `upsert_user`(역할까지 덮어씀), 배포 계정은 `create_account` 명령이
  `create_user`(덮어쓰지 않음)·`set_password`(역할 그대로)를 쓴다(docs/specs/admin-roles.md).
- 사용자 관리(최고 관리자, backend/admin_api.py): `list_users`(아이디·역할·만든 날짜만, 해시 없음), `set_role`(역할 변경 + 기록 한 트랜잭션).
- 연결은 호출마다 열고 닫는다(MVP). 풀러(transaction 모드)에서도 문제없도록 준비된 문장을 쓰지 않는다.
- 스키마는 `db/101_auth_users.sql`, `db/105_admin_role_log.sql`이다. 도커 `db`는 처음 만들 때 적용하고, 이미 있는 볼륨은 `ensure_schema()`가 만든다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.auth import AuthUser

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "101_auth_users.sql"
REVOCATION_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "103_auth_token_revocations.sql"
ADMIN_LOG_SCHEMA_FILE = SCHEMA_FILE.with_name("105_admin_role_log.sql")
ROLES = frozenset({"user", "admin"})

_COLUMNS = "user_id, login_id, password_hash, role, is_active"


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


def _to_user(row: tuple | None) -> AuthUser | None:
    if row is None:
        return None
    user_id, login_id, password_hash, role, is_active = row
    return AuthUser(
        user_id=user_id if isinstance(user_id, UUID) else UUID(str(user_id)),
        login_id=login_id,
        password_hash=password_hash,
        role=role,
        is_active=bool(is_active),
    )


class AccountExistsError(Exception):
    """create_user: 같은 로그인 아이디가 이미 있다(덮어쓰지 않는다)."""


@dataclass(frozen=True)
class UserListRow:
    """사용자 관리 목록 한 줄. 비밀번호 해시·user_id·groups·is_active 는 일부러 담지 않는다."""
    login_id: str
    role: str
    created_at: datetime


class PostgresAuthStore:
    """`connect`는 시험에서 가짜 연결을 넣기 위한 자리다. 비우면 `dsn`으로 psycopg 연결을 만든다."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn 또는 connect가 필요하다")
            connect = _default_connect(dsn)
        self._connect = connect

    def _fetch_one(self, sql: str, params: tuple) -> AuthUser | None:
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _to_user(row)

    def get_by_login_id(self, login_id: str) -> AuthUser | None:
        return self._fetch_one(f"SELECT {_COLUMNS} FROM users WHERE login_id = %s", (login_id,))

    def get_by_user_id(self, user_id: UUID | str) -> AuthUser | None:
        try:
            uid = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            return None
        return self._fetch_one(f"SELECT {_COLUMNS} FROM users WHERE user_id = %s", (uid,))

    def upsert_user(self, login_id: str, password_hash: str, role: str) -> AuthUser:
        """로그인 아이디로 계정을 만들거나 해시·역할을 갱신하고 다시 활성으로 둔다 (데모 시드 전용)."""
        if role not in {"user", "admin"}:
            raise ValueError("role must be 'user' or 'admin'")
        user = self._fetch_one(
            "INSERT INTO users (login_id, password_hash, role) VALUES (%s, %s, %s) "
            "ON CONFLICT (login_id) DO UPDATE SET password_hash = EXCLUDED.password_hash, "
            f"role = EXCLUDED.role, is_active = true RETURNING {_COLUMNS}",
            (login_id, password_hash, role),
        )
        if user is None:
            raise RuntimeError("upsert returned no row")
        return user

    def create_user(self, login_id: str, password_hash: str, role: str) -> AuthUser:
        """새 계정만 만든다. 같은 아이디가 있으면 AccountExistsError(아무것도 바꾸지 않음). create_account 명령용."""
        if role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        user = self._fetch_one(
            "INSERT INTO users (login_id, password_hash, role) VALUES (%s, %s, %s) "
            f"ON CONFLICT (login_id) DO NOTHING RETURNING {_COLUMNS}",
            (login_id, password_hash, role),
        )
        if user is None:
            raise AccountExistsError("login_id already exists")
        return user

    def set_password(self, login_id: str, password_hash: str) -> AuthUser | None:
        """해시만 바꾸고 다시 활성으로 둔다. 역할은 그대로. 없는 아이디면 None."""
        return self._fetch_one(
            f"UPDATE users SET password_hash = %s, is_active = true WHERE login_id = %s RETURNING {_COLUMNS}",
            (password_hash, login_id),
        )

    def list_users(self) -> list[UserListRow]:
        """사용자 관리 목록: 아이디·역할·만든 날짜만(해시를 SELECT 하지 않는다). 만든 순서."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT login_id, role, created_at FROM users ORDER BY created_at, login_id"
            ).fetchall()
        return [UserListRow(login_id=r[0], role=r[1], created_at=r[2]) for r in rows]

    def set_role(self, target_login_id: str, new_role: str, by_user_id: UUID | str) -> str:
        """역할 변경 + admin_role_log 1줄을 한 트랜잭션으로. 돌려주는 값: changed / unchanged / missing / inactive.

        연결이 autocommit 이라 `conn.transaction()` 으로 묶는다. 기록 쓰기가 실패하면 역할 변경도 되돌아가고 예외가 난다.
        """
        if new_role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        action = "promote" if new_role == "admin" else "revoke"
        by = UUID(str(by_user_id))
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT user_id, role, is_active FROM users WHERE login_id = %s FOR UPDATE",
                    (target_login_id,),
                ).fetchone()
                if row is None:
                    return "missing"
                target_id, role, is_active = row
                if not is_active:
                    return "inactive"
                if role == new_role:
                    return "unchanged"
                conn.execute("UPDATE users SET role = %s WHERE user_id = %s", (new_role, target_id))
                conn.execute(
                    "INSERT INTO admin_role_log (by_user_id, target_user_id, action) VALUES (%s, %s, %s)",
                    (by, target_id, action),
                )
        return "changed"

    def ensure_schema(self) -> None:
        """`CREATE TABLE IF NOT EXISTS`로 users, token_revocations, admin_role_log 표를 만든다(이 순서, 외래키). 이미 있으면 아무것도 바꾸지 않는다."""
        with self._connect() as conn:
            for schema_file in (SCHEMA_FILE, REVOCATION_SCHEMA_FILE, ADMIN_LOG_SCHEMA_FILE):
                conn.execute(schema_file.read_text(encoding="utf-8"))


class PostgresTokenRevocationStore:
    """Durable ``TokenRevocationStore`` implementation backed by PostgreSQL."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn or connect is required")
            connect = _default_connect(dsn)
        self._connect = connect

    def is_revoked(self, jti: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM token_revocations WHERE jti = %s AND expires_at > now())",
                (jti,),
            ).fetchone()
        return bool(row and row[0])

    def revoke(self, jti: str, expires_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO token_revocations (jti, expires_at) VALUES (%s, %s) "
                "ON CONFLICT (jti) DO NOTHING",
                (jti, expires_at),
            )
