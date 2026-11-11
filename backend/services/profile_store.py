"""Postgres `user_profiles` 표 (요청 1번 내 정보, db/104_user_profiles.sql).

- 이 저장소는 **암호문만** 다룬다. 평문으로 바꾸는 일은 라우터가 `ProfileCipher` 로 한다.
- 계약은 user_id 하나로 읽기·있나 보기·쓰기뿐이다. 목록·검색 함수는 일부러 두지 않는다(관리자에게도 안 보이게).
- 연결은 호출마다 열고 닫는다(auth_store.py 와 같은 방식, 준비된 문장 안 씀).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "104_user_profiles.sql"
FIELDS = ("name", "dept", "phone", "address")


@dataclass(frozen=True)
class EncryptedProfile:
    user_id: str
    name_enc: bytes
    dept_enc: bytes
    phone_enc: bytes
    address_enc: bytes
    key_version: int
    updated_at: datetime | None = None


class ProfileStore(Protocol):
    def get(self, user_id: str) -> EncryptedProfile | None: ...

    def exists(self, user_id: str) -> bool: ...

    def upsert(self, profile: EncryptedProfile) -> EncryptedProfile: ...


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


_COLUMNS = "user_id, name_enc, dept_enc, phone_enc, address_enc, key_version, updated_at"


def _to_profile(row: tuple | None) -> EncryptedProfile | None:
    if row is None:
        return None
    user_id, name, dept, phone, address, version, updated = row
    return EncryptedProfile(str(user_id), bytes(name), bytes(dept), bytes(phone), bytes(address), int(version), updated)


class PostgresProfileStore:
    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None):
        if connect is None:
            if not dsn:
                raise ValueError("DATABASE_URL 이 필요합니다")
            connect = _default_connect(dsn)
        self._connect = connect

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    def get(self, user_id: str) -> EncryptedProfile | None:
        with self._connect() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM user_profiles WHERE user_id = %s", (user_id,)).fetchone()
        return _to_profile(row)

    def exists(self, user_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM user_profiles WHERE user_id = %s", (user_id,)).fetchone() is not None

    def upsert(self, p: EncryptedProfile) -> EncryptedProfile:
        with self._connect() as conn:
            row = conn.execute(
                f"""INSERT INTO user_profiles (user_id, name_enc, dept_enc, phone_enc, address_enc, key_version, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (user_id) DO UPDATE SET name_enc = EXCLUDED.name_enc, dept_enc = EXCLUDED.dept_enc,
                        phone_enc = EXCLUDED.phone_enc, address_enc = EXCLUDED.address_enc,
                        key_version = EXCLUDED.key_version, updated_at = now()
                    RETURNING {_COLUMNS}""",
                (p.user_id, p.name_enc, p.dept_enc, p.phone_enc, p.address_enc, p.key_version),
            ).fetchone()
        return _to_profile(row)
