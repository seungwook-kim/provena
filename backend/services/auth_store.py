"""Postgres `users` 테이블을 읽는 AuthStore (backend/auth.py의 Protocol 구현).

- 계약은 `get_by_login_id(str)`, `get_by_user_id(UUID | str)` 두 조회뿐이다. 계정 만들기는 데모 시드(`demo_seed.py`)가
  `upsert_user`로만 한다. 저장소 연결 실패를 다른 저장소로 바꿔 끼우지 않는다(예외는 auth 라우터가 503으로 바꾼다).
- 연결은 호출마다 열고 닫는다(MVP). 풀러(transaction 모드)에서도 문제없도록 준비된 문장을 쓰지 않는다.
- 스키마는 `db/101_auth_users.sql`이다. 도커 `db`는 처음 만들 때 적용하고, 이미 있는 볼륨은 `ensure_schema()`가 만든다.
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
ADMIN_LOG_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "105_admin_role_log.sql"
ROLES = frozenset({"user", "admin"})

_COLUMNS = "user_id, login_id, password_hash, role, is_active"


class AccountExistsError(Exception):
    pass


@dataclass(frozen=True)
class UserListRow:
    login_id: str
    role: str
    created_at: datetime


@dataclass(frozen=True)
class SignupRequestRow:
    login_id: str
    requested_at: datetime
    status: str


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

    def create_user(self, login_id: str, password_hash: str, role: str) -> AuthUser:
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

    def create_pending_user(self, login_id: str, password_hash: str) -> AuthUser:
        """Create a user and its pending approval record in one transaction.

        The table is intentionally not created by application startup. Until the
        separately approved proposal is applied, this fails closed instead of
        creating an account that can log in without review.
        """
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    # A signup request must not be usable before an owner review.
                    # Keep the approval state in signup_requests, but also create
                    # the account inactive so older login paths cannot bypass it.
                    f"INSERT INTO users (login_id, password_hash, role, is_active) VALUES (%s, %s, 'user', false) "
                    f"RETURNING {_COLUMNS}", (login_id, password_hash)
                ).fetchone()
                user = _to_user(row)
                if user is None:
                    raise RuntimeError("pending user insert returned no row")
                conn.execute(
                    "INSERT INTO signup_requests (user_id, status) VALUES (%s, 'pending')",
                    (user.user_id,),
                )
        return user

    def get_signup_status(self, user_id: UUID | str) -> str | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM signup_requests WHERE user_id = %s", (UUID(str(user_id)),)
                ).fetchone()
        except Exception as exc:
            # Existing databases predating approval have no request table. Such
            # accounts remain compatible; signup itself still fails closed.
            if type(exc).__name__ == "UndefinedTable":
                return None
            raise
        return None if row is None else str(row[0])

    def list_signup_requests(self) -> list[SignupRequestRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT u.login_id, r.requested_at, r.status "
                "FROM signup_requests r JOIN users u ON u.user_id = r.user_id "
                "ORDER BY r.requested_at, u.login_id"
            ).fetchall()
        return [SignupRequestRow(row[0], row[1], row[2]) for row in rows]

    def review_signup_request(self, login_id: str, status: str, by_user_id: UUID | str) -> str:
        if status not in {"approved", "rejected"}:
            raise ValueError("invalid signup status")
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT r.request_id, r.status FROM signup_requests r "
                    "JOIN users u ON u.user_id = r.user_id WHERE u.login_id = %s FOR UPDATE",
                    (login_id,),
                ).fetchone()
                if row is None:
                    return "missing"
                if row[1] != "pending":
                    return "unchanged"
                conn.execute(
                    "UPDATE signup_requests SET status = %s, reviewed_at = now(), reviewed_by = %s "
                    "WHERE request_id = %s",
                    (status, UUID(str(by_user_id)), row[0]),
                )
                # Keep the legacy account gate consistent with the authoritative
                # signup request state in the same transaction.
                conn.execute(
                    "UPDATE users SET is_active = %s WHERE login_id = %s",
                    (status == "approved", login_id),
                )
        return "changed"

    def set_password(self, login_id: str, password_hash: str) -> AuthUser | None:
        return self._fetch_one(
            # Password changes must not approve or reactivate an account.
            f"UPDATE users SET password_hash = %s WHERE login_id = %s RETURNING {_COLUMNS}",
            (password_hash, login_id),
        )

    def list_users(self) -> list[UserListRow]:
        with self._connect() as conn:
            rows = conn.execute("SELECT login_id, role, created_at FROM users ORDER BY created_at, login_id").fetchall()
        return [UserListRow(login_id=row[0], role=row[1], created_at=row[2]) for row in rows]

    def set_role(self, target_login_id: str, new_role: str, by_user_id: UUID | str) -> str:
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
        """Additive auth schemas for fresh and existing local databases."""
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
