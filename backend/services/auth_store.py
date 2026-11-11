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
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from backend.auth import AuthUser

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "101_auth_users.sql"
REVOCATION_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "103_auth_token_revocations.sql"
ADMIN_LOG_SCHEMA_FILE = SCHEMA_FILE.with_name("105_admin_role_log.sql")
SIGNUP_SCHEMA_FILE = SCHEMA_FILE.with_name("106_signup_approval.sql")
EMAIL_VERIFICATION_SCHEMA_FILE = SCHEMA_FILE.with_name("107_email_signup_verification.sql")
PRIVACY_SCHEMA_FILE = SCHEMA_FILE.with_name("108_auth_privacy_hardening.sql")
SIGNUP_EDGES_SCHEMA_FILE = SCHEMA_FILE.with_name("112_signup_edges.sql")
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


# 이메일 가입 신청이 인증 전(미인증 pending)이면 같은 이메일로 다시 가입할 때 새 비밀번호로 덮어쓴다(create_pending_user).
# 인증을 마친 신청, 승인된 신청, 이미 있는 계정은 덮어쓰지 않는다.


class AccountExistsError(Exception):
    """create_user: 같은 로그인 아이디가 이미 있다(덮어쓰지 않는다)."""


@dataclass(frozen=True)
class UserListRow:
    """사용자 관리 목록 한 줄. 비밀번호 해시·user_id·groups·is_active 는 일부러 담지 않는다."""
    login_id: str
    role: str
    created_at: datetime

@dataclass(frozen=True)
class SignupRequestRow:
    login_id: str
    requested_at: datetime
    status: str
    request_id: int | None = None
    email_verified: bool = False


class MemoryAuthStore:
    """Explicit in-process AuthStore for tests and opt-in local use only."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._users: dict[str, AuthUser] = {}
        self._signup_requests: dict[str, dict[str, Any]] = {}
        self._next_signup_request_id = 1

    def get_by_login_id(self, login_id: str) -> AuthUser | None:
        with self._lock:
            found = self._users.get(login_id)
            if found is None and "@" in login_id:
                # 이메일은 대소문자를 가리지 않는다(소문자화 규칙 전에 대문자로 저장된 계정도 찾는다)
                found = next((u for k, u in self._users.items() if "@" in k and k.lower() == login_id.lower()), None)
            return found

    def get_by_user_id(self, user_id: UUID | str) -> AuthUser | None:
        try:
            uid = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            return None
        with self._lock:
            return next((user for user in self._users.values() if user.user_id == uid), None)

    def get_signup_by_login_id(self, login_id: str) -> tuple[str, str] | None:
        """Return a signup request's status and password hash by login ID.

        This is the lookup for pending/rejected login verification.  It does
        not imply that a users record exists.
        """
        with self._lock:
            request = self._signup_requests.get(login_id)
            return (request["status"], request["password_hash"]) if request else None

    def create_user(self, login_id: str, password_hash: str, role: str) -> AuthUser:
        if role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        with self._lock:
            return self._create_user_locked(login_id, password_hash, role)

    def _create_user_locked(self, login_id: str, password_hash: str, role: str) -> AuthUser:
        """Create one active user while ``_lock`` is held."""
        if role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        if login_id in self._users:
            raise AccountExistsError("login_id already exists")
        user = AuthUser(uuid4(), login_id, password_hash, role, True)
        self._users[login_id] = user
        return user

    def upsert_user(self, login_id: str, password_hash: str, role: str) -> AuthUser:
        if role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        with self._lock:
            existing = self._users.get(login_id)
            user = AuthUser(existing.user_id if existing else uuid4(), login_id, password_hash, role, True)
            self._users[login_id] = user
            return user

    def set_password(self, login_id: str, password_hash: str) -> AuthUser | None:
        with self._lock:
            existing = self._users.get(login_id)
            if existing is None:
                return None
            user = AuthUser(existing.user_id, existing.login_id, password_hash, existing.role, True, existing.groups)
            self._users[login_id] = user
            return user

    def create_pending_user(self, login_id: str, password_hash: str, *, email_verification_required: bool = False) -> str | None:
        """Store a pending request only; no users record or user ID is made.

        새 신청이면 None, 인증 전 이메일 신청을 새 비밀번호로 덮어썼으면 "replaced"를 돌려준다.
        거절된 신청은 새 신청으로 대체한다. 인증을 마친·승인된 신청과 이미 있는 계정은 AccountExistsError.
        """
        with self._lock:
            if self.get_by_login_id(login_id) is not None:
                raise AccountExistsError("login_id already exists")
            now = datetime.now(timezone.utc)
            existing = self._signup_requests.get(login_id)
            if existing is not None and existing["status"] == "rejected":
                del self._signup_requests[login_id]
            elif (existing is not None and email_verification_required and existing["status"] == "pending"
                  and existing["email_verification_required"] and existing["email_verified_at"] is None):
                existing.update(password_hash=password_hash, requested_at=now, verification_code_hash=None,
                                verification_expires_at=None, verification_attempts=0)
                return "replaced"
            if login_id in self._signup_requests:
                raise AccountExistsError("login_id already exists")
            request_id = self._next_signup_request_id
            self._next_signup_request_id += 1
            self._signup_requests[login_id] = {
                "request_id": request_id, "login_id": login_id, "password_hash": password_hash, "requested_at": now, "status": "pending",
                "user_id": None, "reviewed_at": None, "reviewed_by": None,
                "email_verification_required": email_verification_required,
                "email_verified_at": None, "verification_code_hash": None,
                "verification_expires_at": None, "verification_attempts": 0,
                "verification_send_count": 0, "last_verification_sent_at": None,
            }

    def get_signup_verification(self, login_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._signup_requests.get(login_id)
            return dict(row) if row else None

    def issue_verification(self, login_id: str, code_hash: str, code: str, now: datetime, expires_at: datetime,
                           max_sends: int, resend_seconds: int, send: Callable[[str], None]) -> str:
        """Send and persist one code while holding the store lock."""
        with self._lock:
            row = self._signup_requests.get(login_id)
            if not row or row.get("status") != "pending" or not row.get("email_verification_required"):
                return "unavailable"
            if row.get("email_verified_at") is not None:
                return "unavailable"
            last_sent = row.get("last_verification_sent_at")
            if last_sent and (now - last_sent).total_seconds() < resend_seconds:
                return "limited"
            if row.get("verification_send_count", 0) >= max_sends:
                return "limited"
            send(code)
            row.update(verification_code_hash=code_hash, verification_expires_at=expires_at,
                       verification_attempts=0, verification_send_count=row["verification_send_count"] + 1,
                       last_verification_sent_at=now)
            return "sent"

    def save_verification(self, login_id: str, code_hash: str, expires_at: datetime, sent_at: datetime) -> None:
        with self._lock:
            row = self._signup_requests[login_id]
            row.update(verification_code_hash=code_hash, verification_expires_at=expires_at,
                       verification_attempts=0, verification_send_count=row["verification_send_count"] + 1,
                       last_verification_sent_at=sent_at)

    def delete_pending_signup(self, login_id: str) -> None:
        with self._lock:
            row = self._signup_requests.get(login_id)
            if row and row.get("status") == "pending" and row.get("email_verified_at") is None:
                del self._signup_requests[login_id]

    def verify_signup_code(self, login_id: str, code_hash: str, now: datetime, max_attempts: int) -> str:
        with self._lock:
            row = self._signup_requests.get(login_id)
            if not row or not row["email_verification_required"]: return "not_required"
            if row["email_verified_at"] is not None: return "already_verified"
            if row["verification_expires_at"] is None or row["verification_expires_at"] <= now:
                row["verification_code_hash"] = None
                return "expired"
            if row["verification_attempts"] >= max_attempts: return "too_many_attempts"
            row["verification_attempts"] += 1
            if row["verification_code_hash"] != code_hash: return "invalid"
            row["email_verified_at"] = now
            row["verification_code_hash"] = None
            row["verification_expires_at"] = None
            row["verification_attempts"] = 0
            return "verified"

    def get_signup_status(self, user_id: UUID | str) -> str | None:
        """Return ``approved`` only for a request linked to an actual user ID.

        Pending and rejected requests intentionally have no user ID; callers
        must use :meth:`get_signup_by_login_id` for those login-time states.
        """
        try:
            uid = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            return None
        with self._lock:
            request = next(
                (row for row in self._signup_requests.values()
                 if row["status"] == "approved" and row["user_id"] == uid),
                None,
            )
            return "approved" if request else None

    def list_signup_requests(self) -> list[SignupRequestRow]:
        with self._lock:
            rows = sorted(self._signup_requests.values(), key=lambda row: (row["requested_at"], row["login_id"]))
            return [SignupRequestRow(row["login_id"], row["requested_at"], row["status"], row.get("request_id"), row.get("email_verified_at") is not None) for row in rows]

    def review_signup_request(self, login_id: str, action: str, reviewed_by: UUID | str) -> str:
        if action not in {"approve", "reject"}:
            raise ValueError("invalid signup action")
        reviewer = UUID(str(reviewed_by))
        status = "approved" if action == "approve" else "rejected"
        with self._lock:
            request = self._signup_requests.get(login_id)
            if request is None:
                return "missing"
            if request["status"] != "pending":
                return "unchanged"
            if action == "approve":
                if request.get("email_verification_required") and request.get("email_verified_at") is None:
                    return "unverified"
                if login_id in self._users:
                    return "unchanged"
                user = self._create_user_locked(login_id, request["password_hash"], "user")
                request["user_id"] = user.user_id
            request["status"] = status
            request["reviewed_at"] = datetime.now(timezone.utc)
            request["reviewed_by"] = reviewer
            return "changed"

    def review_signup_request_by_id(self, request_id: int, action: str, reviewed_by: UUID | str) -> str:
        with self._lock:
            login_id = next((key for key, row in self._signup_requests.items()
                             if row.get("request_id") == request_id), None)
        return "missing" if login_id is None else self.review_signup_request(login_id, action, reviewed_by)

    def reset_signup_verification_by_id(self, request_id: int) -> str:
        with self._lock:
            row = next((item for item in self._signup_requests.values()
                        if item.get("request_id") == request_id), None)
            if row is None:
                return "missing"
            if row.get("status") != "pending" or not row.get("email_verification_required") or row.get("email_verified_at") is not None:
                return "unavailable"
            row.update(verification_code_hash=None, verification_expires_at=None,
                       verification_attempts=0, verification_send_count=0,
                       last_verification_sent_at=None)
            return "reset"


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
        if "@" in login_id:
            # 이메일은 대소문자를 가리지 않는다. db/112 가 users 의 이메일 소문자 유니크 색인(같은 조건)을 둔다.
            return self._fetch_one(
                f"SELECT {_COLUMNS} FROM users WHERE position('@' in login_id) > 0 AND lower(login_id) = lower(%s)",
                (login_id,),
            )
        return self._fetch_one(f"SELECT {_COLUMNS} FROM users WHERE login_id = %s", (login_id,))

    def get_by_user_id(self, user_id: UUID | str) -> AuthUser | None:
        try:
            uid = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            return None
        return self._fetch_one(f"SELECT {_COLUMNS} FROM users WHERE user_id = %s", (uid,))

    def get_signup_by_login_id(self, login_id: str) -> tuple[str, str] | None:
        """Return a signup request's status and password hash by login ID.

        This lookup is used to verify and block pending/rejected login attempts
        before a users record exists.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, password_hash FROM signup_requests WHERE login_id = %s ORDER BY request_id DESC LIMIT 1",
                (login_id,),
            ).fetchone()
        return (row[0], row[1]) if row else None

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
        with self._connect() as conn:
            with conn.transaction():
                if conn.execute("SELECT 1 FROM users WHERE login_id = %s", (login_id,)).fetchone() is not None:
                    raise AccountExistsError("login_id already exists")
                return self._insert_user(conn, login_id, password_hash, role)

    def set_password(self, login_id: str, password_hash: str) -> AuthUser | None:
        """해시만 바꾸고 다시 활성으로 둔다. 역할은 그대로. 없는 아이디면 None."""
        return self._fetch_one(
            f"UPDATE users SET password_hash = %s, is_active = true WHERE login_id = %s RETURNING {_COLUMNS}",
            (password_hash, login_id),
        )

    def create_pending_user(self, login_id: str, password_hash: str, *, email_verification_required: bool = False) -> str | None:
        """Store a pending request only; no users record or user ID is made.

        새 신청이면 None, 인증 전 이메일 신청을 새 비밀번호로 덮어썼으면 "replaced"를 돌려준다(한 트랜잭션).
        거절된 신청 행은 남기고 새 행을 만든다(db/112 의 부분 유니크 색인이 거절 행을 제외한다).
        인증을 마친·승인된 신청과 이미 있는 계정은 AccountExistsError.
        """
        with self._connect() as conn:
            with conn.transaction():
                if self._user_exists(conn, login_id):
                    raise AccountExistsError("login_id already exists")
                if email_verification_required:
                    open_row = conn.execute(
                        "SELECT request_id, email_verification_required, email_verified_at FROM signup_requests "
                        "WHERE login_id = %s AND status = 'pending' FOR UPDATE", (login_id,)
                    ).fetchone()
                    if open_row is not None and open_row[1] and open_row[2] is None:
                        conn.execute(
                            "UPDATE signup_requests SET password_hash = %s, requested_at = now(), "
                            "verification_code_hash = NULL, verification_expires_at = NULL, verification_attempts = 0 "
                            "WHERE request_id = %s", (password_hash, open_row[0])
                        )
                        return "replaced"
                try:
                    conn.execute(
                        "INSERT INTO signup_requests (login_id, password_hash, status, email_verification_required) VALUES (%s, %s, 'pending', %s)",
                        (login_id, password_hash, email_verification_required),
                    )
                except Exception as exc:
                    if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                        raise AccountExistsError("login_id already exists") from None
                    raise
        return None

    @staticmethod
    def _user_exists(conn: Any, login_id: str) -> bool:
        if "@" in login_id:
            row = conn.execute(
                "SELECT 1 FROM users WHERE position('@' in login_id) > 0 AND lower(login_id) = lower(%s)", (login_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT 1 FROM users WHERE login_id = %s", (login_id,)).fetchone()
        return row is not None

    def get_signup_status(self, user_id: UUID | str) -> str | None:
        """Return ``approved`` only for a request linked to an actual user ID.

        Pending and rejected requests have ``user_id IS NULL`` by design and
        are looked up with :meth:`get_signup_by_login_id` during login.
        """
        try:
            uid = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM signup_requests WHERE user_id = %s AND status = 'approved' "
                "ORDER BY request_id DESC LIMIT 1", (uid,)
            ).fetchone()
        return row[0] if row else None

    def get_signup_verification(self, login_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, email_verification_required, email_verified_at, verification_expires_at, "
                "verification_attempts, verification_send_count, last_verification_sent_at "
                "FROM signup_requests WHERE login_id = %s ORDER BY request_id DESC LIMIT 1", (login_id,)
            ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "email_verification_required": row[1], "email_verified_at": row[2],
                "verification_expires_at": row[3], "verification_attempts": row[4],
                "verification_send_count": row[5], "last_verification_sent_at": row[6]}

    def issue_verification(self, login_id: str, code_hash: str, code: str, now: datetime, expires_at: datetime,
                           max_sends: int, resend_seconds: int, send: Callable[[str], None]) -> str:
        """Serialize eligibility, delivery, and persistence with a row lock."""
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT status, email_verification_required, email_verified_at, verification_send_count, "
                    "last_verification_sent_at FROM signup_requests "
                    "WHERE login_id = %s ORDER BY request_id DESC LIMIT 1 FOR UPDATE", (login_id,)
                ).fetchone()
                if row is None or row[0] != "pending" or not row[1] or row[2] is not None:
                    return "unavailable"
                if row[4] and (now - row[4]).total_seconds() < resend_seconds:
                    return "limited"
                if row[3] >= max_sends:
                    return "limited"
                send(code)
                conn.execute(
                    "UPDATE signup_requests SET verification_code_hash = %s, verification_expires_at = %s, "
                    "verification_attempts = 0, verification_send_count = verification_send_count + 1, "
                    "last_verification_sent_at = %s WHERE login_id = %s AND status = 'pending'",
                    (code_hash, expires_at, now, login_id),
                )
                return "sent"

    def save_verification(self, login_id: str, code_hash: str, expires_at: datetime, sent_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE signup_requests SET verification_code_hash = %s, verification_expires_at = %s, "
                "verification_attempts = 0, verification_send_count = verification_send_count + 1, "
                "last_verification_sent_at = %s WHERE login_id = %s AND status = 'pending'",
                (code_hash, expires_at, sent_at, login_id),
            )

    def delete_pending_signup(self, login_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM signup_requests WHERE login_id = %s AND status = 'pending' AND email_verified_at IS NULL", (login_id,))

    def verify_signup_code(self, login_id: str, code_hash: str, now: datetime, max_attempts: int) -> str:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT email_verification_required, email_verified_at, verification_code_hash, "
                    "verification_expires_at, verification_attempts FROM signup_requests "
                    "WHERE login_id = %s ORDER BY request_id DESC LIMIT 1 FOR UPDATE", (login_id,)
                ).fetchone()
                if row is None or not row[0]: return "not_required"
                if row[1] is not None: return "already_verified"
                if row[3] is None or row[3] <= now:
                    conn.execute("UPDATE signup_requests SET verification_code_hash = NULL WHERE login_id = %s AND status = 'pending'", (login_id,))
                    return "expired"
                if row[4] >= max_attempts: return "too_many_attempts"
                conn.execute("UPDATE signup_requests SET verification_attempts = verification_attempts + 1 WHERE login_id = %s AND status = 'pending'", (login_id,))
                if not hmac.compare_digest(str(row[2] or ""), code_hash): return "invalid"
                conn.execute("UPDATE signup_requests SET email_verified_at = %s, verification_code_hash = NULL, verification_expires_at = NULL, verification_attempts = 0 WHERE login_id = %s AND status = 'pending'", (now, login_id))
                return "verified"

    def list_signup_requests(self) -> list[SignupRequestRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.request_id, s.login_id, s.requested_at, s.status, s.email_verified_at IS NOT NULL "
                "FROM signup_requests s "
                "ORDER BY s.requested_at, s.login_id"
            ).fetchall()
        return [SignupRequestRow(request_id=r[0], login_id=r[1], requested_at=r[2], status=r[3], email_verified=r[4]) for r in rows]

    def review_signup_request(self, login_id: str, action: str, reviewed_by: UUID | str) -> str:
        if action not in {"approve", "reject"}:
            raise ValueError("invalid signup action")
        status = "approved" if action == "approve" else "rejected"
        reviewer = UUID(str(reviewed_by))
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT request_id, status, password_hash, email_verification_required, email_verified_at FROM signup_requests "
                    "WHERE login_id = %s ORDER BY request_id DESC LIMIT 1 FOR UPDATE", (login_id,)
                ).fetchone()
                if row is None:
                    return "missing"
                request_id, current, password_hash, verification_required, verified_at = row
                if current != "pending":
                    return "unchanged"
                if action == "approve":
                    if verification_required and verified_at is None:
                        return "unverified"
                    existing = conn.execute("SELECT 1 FROM users WHERE login_id = %s", (login_id,)).fetchone()
                    if existing is not None:
                        return "unchanged"
                    user = self._insert_user(conn, login_id, password_hash, "user")
                    user_id = user.user_id
                else:
                    user_id = None
                conn.execute(
                    "UPDATE signup_requests SET status = %s, user_id = %s, reviewed_at = now(), reviewed_by = %s WHERE request_id = %s",
                    (status, user_id, reviewer, request_id),
                )
        return "changed"

    def review_signup_request_by_id(self, request_id: int, action: str, reviewed_by: UUID | str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT login_id FROM signup_requests WHERE request_id = %s", (request_id,)).fetchone()
        return "missing" if row is None else self.review_signup_request(row[0], action, reviewed_by)

    def reset_signup_verification_by_id(self, request_id: int) -> str:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT status, email_verification_required, email_verified_at "
                    "FROM signup_requests WHERE request_id = %s FOR UPDATE", (request_id,)
                ).fetchone()
                if row is None:
                    return "missing"
                if row[0] != "pending" or not row[1] or row[2] is not None:
                    return "unavailable"
                conn.execute(
                    "UPDATE signup_requests SET verification_code_hash = NULL, verification_expires_at = NULL, "
                    "verification_attempts = 0, verification_send_count = 0, last_verification_sent_at = NULL "
                    "WHERE request_id = %s", (request_id,)
                )
                return "reset"

    def _insert_user(self, conn: Any, login_id: str, password_hash: str, role: str) -> AuthUser:
        if role not in ROLES:
            raise ValueError("role must be 'user' or 'admin'")
        row = conn.execute(
            f"INSERT INTO users (login_id, password_hash, role) VALUES (%s, %s, %s) RETURNING {_COLUMNS}",
            (login_id, password_hash, role),
        ).fetchone()
        if row is None:
            raise AccountExistsError("login_id already exists")
        return _to_user(row)

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
            for schema_file in (SCHEMA_FILE, REVOCATION_SCHEMA_FILE, ADMIN_LOG_SCHEMA_FILE, SIGNUP_SCHEMA_FILE, EMAIL_VERIFICATION_SCHEMA_FILE, PRIVACY_SCHEMA_FILE, SIGNUP_EDGES_SCHEMA_FILE):
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
