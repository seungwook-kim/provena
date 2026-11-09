"""create_account 명령 시험 — docs/specs/admin-roles.md AC-19~21. 가짜 저장소로 돈다(DB 없음). 비밀번호는 시험 안에서 만든다."""
import io
import secrets
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.auth import AuthUser, verify_password
from backend.services.auth_store import AccountExistsError
from backend.services.create_account import EXIT_EXISTS, EXIT_INPUT, EXIT_OK, EXIT_STORE, PASSWORD_ENV, main


class FakeAccounts:
    def __init__(self, users=()):
        self.users = {u.login_id: u for u in users}
        self.writes = 0
        self.fail = False

    def create_user(self, login_id, password_hash, role):
        if self.fail:
            raise RuntimeError("postgresql://app:dsn-secret@db/x is down")
        if login_id in self.users:
            raise AccountExistsError("login_id already exists")
        self.users[login_id] = AuthUser(uuid4(), login_id, password_hash, role)
        self.writes += 1
        return self.users[login_id]

    def set_password(self, login_id, password_hash):
        user = self.users.get(login_id)
        if user is None:
            return None
        self.users[login_id] = replace(user, password_hash=password_hash, is_active=True)
        self.writes += 1
        return self.users[login_id]


def run(argv, store, *, password=None, typed=None, environ=None):
    out, err = io.StringIO(), io.StringIO()
    answers = iter(typed or [])
    env = dict(environ or {})
    if password is not None:
        env[PASSWORD_ENV] = password
    code = main(argv, store=store, environ=env, interactive=typed is not None,
                prompt=lambda _label: next(answers), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# ---- AC-19 계정 만들기 ---------------------------------------------------------
@pytest.mark.parametrize("role", ["admin", "user"])
def test_creates_account_with_verifiable_hash_and_prints_one_line(role):
    store, pw = FakeAccounts(), secrets.token_urlsafe(12)
    code, out, err = run(["--login-id", "first-owner", "--role", role], store, password=pw)
    assert code == EXIT_OK and err == ""
    assert out == f"계정 생성: first-owner ({role})\n"
    user = store.users["first-owner"]
    assert user.role == role and verify_password(pw, user.password_hash)
    assert pw not in out and user.password_hash not in out


def test_interactive_password_is_asked_twice_and_must_match():
    store, pw = FakeAccounts(), secrets.token_urlsafe(12)
    code, out, _ = run(["--login-id", "a1", "--role", "user"], store, typed=[pw, pw])
    assert code == EXIT_OK and verify_password(pw, store.users["a1"].password_hash) and pw not in out
    code, out, err = run(["--login-id", "a2", "--role", "user"], store, typed=[pw, pw + "x"])
    assert code == EXIT_INPUT and "a2" not in store.users and pw not in out + err


def test_env_password_is_ignored_when_interactive():
    store, pw, typed = FakeAccounts(), secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    run(["--login-id", "a1", "--role", "user"], store, password=pw, typed=[typed, typed])
    assert verify_password(typed, store.users["a1"].password_hash)


def test_no_password_given_stops():
    store = FakeAccounts()
    code, _, err = run(["--login-id", "a1", "--role", "user"], store)
    assert code == EXIT_INPUT and store.writes == 0 and PASSWORD_ENV in err


def test_password_is_not_a_cli_argument():
    store = FakeAccounts()
    code, _, err = run(["--login-id", "a1", "--role", "user", "--password", "abcdefgh123"], store,
                       password=secrets.token_urlsafe(12))
    assert code == EXIT_INPUT and store.writes == 0 and "abcdefgh123" not in err


# ---- AC-20 덮어쓰기 금지 / --reset-password -------------------------------------------
def test_existing_id_is_not_overwritten():
    old = AuthUser(uuid4(), "taken", "old-hash", "user")
    store = FakeAccounts([old])
    code, out, err = run(["--login-id", "taken", "--role", "admin"], store, password=secrets.token_urlsafe(12))
    assert code == EXIT_EXISTS and out == "" and store.writes == 0
    assert store.users["taken"] == old


def test_reset_password_changes_hash_only_and_keeps_role():
    old = AuthUser(uuid4(), "boss", "old-hash", "admin", is_active=False)
    store, pw = FakeAccounts([old]), secrets.token_urlsafe(12)
    code, out, _ = run(["--login-id", "boss", "--reset-password"], store, password=pw)
    assert code == EXIT_OK and out == "비밀번호 변경: boss (admin)\n"
    user = store.users["boss"]
    assert user.role == "admin" and user.user_id == old.user_id and user.is_active
    assert verify_password(pw, user.password_hash) and pw not in out


def test_reset_password_for_unknown_id_and_with_role_is_refused():
    store = FakeAccounts()
    assert run(["--login-id", "ghost", "--reset-password"], store, password=secrets.token_urlsafe(12))[0] == EXIT_EXISTS
    store = FakeAccounts([AuthUser(uuid4(), "boss", "old-hash", "admin")])
    code, _, _ = run(["--login-id", "boss", "--reset-password", "--role", "user"], store, password=secrets.token_urlsafe(12))
    assert code == EXIT_INPUT and store.users["boss"].role == "admin" and store.writes == 0


# ---- AC-21 입력 검사 ------------------------------------------------------------
@pytest.mark.parametrize("password", ["seven77", "가" * 25])   # 7자 / 75바이트
def test_password_length_rules(password):
    store = FakeAccounts()
    code, out, err = run(["--login-id", "a1", "--role", "user"], store, password=password)
    assert code == EXIT_INPUT and store.writes == 0
    assert password not in out + err and "8자 이상" in err


@pytest.mark.parametrize("argv, secret_value", [
    (["--login-id", "a1", "--role", "owner"], "owner"),
    (["--login-id", "a1", "--role", "superuser"], "superuser"),
    (["--login-id", " spaced ", "--role", "user"], " spaced "),
    (["--login-id", "a1", "--rol", "zzz-typo"], "zzz-typo"),
])
def test_bad_role_or_id_stops_without_echoing_input(argv, secret_value):
    store = FakeAccounts()
    code, out, err = run(argv, store, password=secrets.token_urlsafe(12))
    assert code == EXIT_INPUT and store.writes == 0
    assert secret_value.strip() not in (out + err).replace("user 또는 admin", "")


def test_store_failure_prints_type_only():
    store = FakeAccounts()
    store.fail = True
    code, out, err = run(["--login-id", "a1", "--role", "user"], store, password=secrets.token_urlsafe(12))
    assert code == EXIT_STORE and "RuntimeError" in err and "dsn-secret" not in err


def test_missing_database_url_stops_before_connecting():
    err = io.StringIO()
    code = main(["--login-id", "a1", "--role", "user"], environ={PASSWORD_ENV: secrets.token_urlsafe(12)},
                interactive=False, out=io.StringIO(), err=err)
    assert code == EXIT_STORE and "DATABASE_URL" in err.getvalue()
