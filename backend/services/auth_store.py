"""Postgres `users` 테이블을 읽는 AuthStore (backend/auth.py의 Protocol 구현).

- 계약은 `get_by_login_id(str)`, `get_by_user_id(UUID | str)` 두 조회뿐이다. 계정 만들기는 데모 시드(`demo_seed.py`)가
  `upsert_user`로만 한다. 저장소 연결 실패를 다른 저장소로 바꿔 끼우지 않는다(예외는 auth 라우터가 503으로 바꾼다).
- 연결은 호출마다 열고 닫는다(MVP). 풀러(transaction 모드)에서도 문제없도록 준비된 문장을 쓰지 않는다.
- 스키마는 `db/101_auth_users.sql`이다. 도커 `db`는 처음 만들 때 적용하고, 이미 있는 볼륨은 `ensure_schema()`가 만든다.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.auth import AuthUser

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "101_auth_users.sql"

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

    def ensure_schema(self) -> None:
        """`CREATE TABLE IF NOT EXISTS`로 users 테이블을 만든다. 이미 있으면 아무것도 바꾸지 않는다."""
        sql = SCHEMA_FILE.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.execute(sql)
