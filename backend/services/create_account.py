"""배포판 첫 계정 만들기 — 일회용 명령 (docs/specs/admin-roles.md "첫 계정 만들기").

    python -m backend.services.create_account --login-id <아이디> --role admin      # 최고 관리자
    python -m backend.services.create_account --login-id <아이디> --role user       # 평가용 계정
    python -m backend.services.create_account --login-id <아이디> --reset-password  # 비밀번호 잃었을 때(역할 그대로)

- `DATABASE_URL` 은 환경변수(돌리는 사람의 로컬 .env, 커밋 금지)에서 읽는다. 연결 문자열은 화면·로그에 쓰지 않는다.
- 비밀번호는 명령 인자로 받지 않는다(셸 기록에 남음). 터미널이면 숨김 입력(getpass) 두 번, 터미널이 없을 때만
  환경변수 `PROVENA_NEW_ACCOUNT_PASSWORD` 를 읽는다. PC에서 bcrypt 로 바꾸고(backend/auth.py hash_password) 해시만 보낸다.
- 같은 아이디가 있으면 멈춘다(덮어쓰지 않음). `--reset-password` 일 때만 해시를 바꾸고 역할은 그대로 둔다.
- 출력은 결과 한 줄뿐. 비밀번호·해시·연결 문자열은 쓰지 않는다. 오류 메시지에 입력값을 되풀이하지 않는다.
- 이 명령으로 만든 일은 admin_role_log 에 남지 않는다(화면 기록 전용). 돌린 사람이 db/db.md 에 "누가, 언제, 어떤 역할 몇 개"만 적는다.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, TextIO

from backend.auth import hash_password

PASSWORD_ENV = "PROVENA_NEW_ACCOUNT_PASSWORD"
ROLES = ("user", "admin")
MAX_LOGIN_ID_LENGTH = 64

EXIT_OK = 0
EXIT_INPUT = 2      # 입력이 틀림(역할·비밀번호·아이디)
EXIT_EXISTS = 3     # 같은 아이디가 있음 / 바꿀 아이디가 없음
EXIT_STORE = 4      # DB 연결·쓰기 실패


class AccountStore(Protocol):
    def create_user(self, login_id: str, password_hash: str, role: str) -> Any: ...

    def set_password(self, login_id: str, password_hash: str) -> Any: ...


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:   # argparse 기본 오류는 받은 값을 되풀이한다 → 값 없는 문장으로
        raise _Usage()


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m backend.services.create_account", add_help=True,
                description="배포판 계정을 만든다(비밀번호는 숨김 입력).")
    p.add_argument("--login-id", required=True)
    p.add_argument("--role")
    p.add_argument("--reset-password", action="store_true")
    return p


def read_password(*, interactive: bool, environ: Mapping[str, str],
                  prompt: Callable[[str], str]) -> str | None:
    """터미널이면 두 번 받아 같은지 본다. 터미널이 없으면 환경변수. 못 받으면 None."""
    if interactive:
        first = prompt("새 비밀번호: ")
        second = prompt("한 번 더: ")
        if first != second:
            return None
        return first
    return environ.get(PASSWORD_ENV) or None


def main(
    argv: Sequence[str] | None = None,
    *,
    store: AccountStore | None = None,
    environ: Mapping[str, str] | None = None,
    interactive: bool | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    env = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        args = _parser().parse_args(argv)
    except _Usage:
        print("사용법: --login-id <아이디> (--role user|admin | --reset-password)", file=err)
        return EXIT_INPUT

    login_id = args.login_id
    if not login_id or login_id != login_id.strip() or len(login_id) > MAX_LOGIN_ID_LENGTH or any(c.isspace() for c in login_id):
        print(f"아이디는 공백 없이 1~{MAX_LOGIN_ID_LENGTH}자여야 합니다.", file=err)
        return EXIT_INPUT
    if args.reset_password and args.role is not None:
        print("--reset-password 는 역할을 바꾸지 않습니다. --role 없이 실행하세요.", file=err)
        return EXIT_INPUT
    if not args.reset_password and args.role not in ROLES:
        print("--role 은 user 또는 admin 만 됩니다.", file=err)
        return EXIT_INPUT

    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    password = read_password(interactive=interactive, environ=env, prompt=prompt)
    if password is None:
        print("비밀번호를 받지 못했습니다(두 입력이 다르거나, 터미널이 아닐 때 "
              f"{PASSWORD_ENV} 가 비어 있음).", file=err)
        return EXIT_INPUT
    try:
        password_hash = hash_password(password)
    except ValueError:
        print("비밀번호는 8자 이상, 72바이트 이하여야 합니다.", file=err)
        return EXIT_INPUT
    finally:
        password = None   # noqa: F841 — 더 쓰지 않는다

    if store is None:
        dsn = env.get("DATABASE_URL", "")
        if not dsn:
            print("DATABASE_URL 이 없습니다(로컬 .env 에 두고 커밋하지 마세요).", file=err)
            return EXIT_STORE
        from backend.services.auth_store import PostgresAuthStore
        store = PostgresAuthStore(dsn)

    from backend.services.auth_store import AccountExistsError
    try:
        if args.reset_password:
            user = store.set_password(login_id, password_hash)
            if user is None:
                print("그 아이디의 계정이 없습니다.", file=err)
                return EXIT_EXISTS
            print(f"비밀번호 변경: {login_id} ({user.role})", file=out)
            return EXIT_OK
        user = store.create_user(login_id, password_hash, args.role)
    except AccountExistsError:
        print("같은 아이디가 이미 있어 멈췄습니다(덮어쓰지 않음). 비밀번호만 바꾸려면 --reset-password.", file=err)
        return EXIT_EXISTS
    except Exception as exc:   # DSN(비밀번호 포함)이 섞일 수 있어 종류만
        print(f"DB 작업 실패: {type(exc).__name__}", file=err)
        return EXIT_STORE
    print(f"계정 생성: {login_id} ({user.role})", file=out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
