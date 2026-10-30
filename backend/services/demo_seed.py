"""로컬 데모 계정 2개(user, admin) 시드 (G2, 가이드 p.19).

- `PROVENA_ENV=local` 이고 `PROVENA_DEV_MODE=1` 일 때만 넣는다. 그 밖의 모드(배포 포함)에서는 저장소를 건드리지 않는다.
- 아이디·비밀번호는 환경변수에서 읽는다. 코드와 SQL에는 계정 값이 없다. 비밀번호는 8자 이상(auth.py가 더 짧은 값을 거부).
    DEMO_USER_LOGIN_ID / DEMO_USER_PASSWORD     (역할 user, 아이디 기본값 demo-user)
    DEMO_ADMIN_LOGIN_ID / DEMO_ADMIN_PASSWORD   (역할 admin, 아이디 기본값 demo-admin)
- 비밀번호가 비어 있는 계정은 넣지 않는다. 잘못된 값(8자 미만 등)은 시작 오류로 알린다(값은 메시지에 쓰지 않는다).
- 이 계정은 데모 전용이다. 배포·평가용 계정은 이 시드로 만들지 않고 저장소에도 적지 않는다.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Protocol

from backend.auth import hash_password

log = logging.getLogger(__name__)

# (역할, 아이디 환경변수, 아이디 기본값, 비밀번호 환경변수)
DEMO_ACCOUNTS = (
    ("user", "DEMO_USER_LOGIN_ID", "demo-user", "DEMO_USER_PASSWORD"),
    ("admin", "DEMO_ADMIN_LOGIN_ID", "demo-admin", "DEMO_ADMIN_PASSWORD"),
)


class SeedableStore(Protocol):
    def upsert_user(self, login_id: str, password_hash: str, role: str): ...


def is_local_demo(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("PROVENA_ENV") == "local" and env.get("PROVENA_DEV_MODE") == "1"


def seed_demo_accounts(store: SeedableStore, environ: Mapping[str, str] | None = None) -> list[str]:
    """시드한 로그인 아이디 목록을 돌려준다. 로컬 데모 모드가 아니면 아무것도 하지 않고 빈 목록이다."""
    env = os.environ if environ is None else environ
    if not is_local_demo(env):
        return []
    seeded: list[str] = []
    for role, login_var, default_login, password_var in DEMO_ACCOUNTS:
        password = env.get(password_var, "")
        login_id = env.get(login_var) or default_login
        if not password:
            log.warning("%s 가 비어 있어 %s 계정을 시드하지 않았다", password_var, role)
            continue
        try:
            password_hash = hash_password(password)
        except ValueError:
            raise ValueError(f"{password_var} 는 8자 이상, 72바이트 이하여야 한다") from None
        store.upsert_user(login_id, password_hash, role)
        seeded.append(login_id)
    if seeded:
        log.info("로컬 데모 계정 %d개를 시드했다(아이디: %s)", len(seeded), ", ".join(seeded))
    return seeded
