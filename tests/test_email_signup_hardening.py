"""PR #113 후속: 메일 발송기 선택, 발송 실패 처리, 미인증 신청 만료, 108 SQL, 명세.

모두 가짜 발송기·메모리 저장소로 돈다(메일, DB, 외부 호출 없음).
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_test_support import MemoryRevocationStore
from backend.auth import CSRF_COOKIE_NAME, create_auth_router
from backend.services.auth_store import MemoryAuthStore
from backend.services.email_sender import (
    EmailDeliveryUnavailable,
    RecordingEmailSender,
    UnavailableEmailSender,
    configured_email_sender,
)

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {"password": "signup-pass-123", "password_confirmation": "signup-pass-123"}


class FailingSender:
    """첫 호출부터 발송 실패(RuntimeError)를 내는 가짜 발송기. failures 번만 실패하고 그 뒤는 기록한다."""

    def __init__(self, failures: int = 99) -> None:
        self.failures = failures
        self.attempts = 0
        self.deliveries: list[dict[str, str]] = []

    def send_verification_email(self, *, email: str, code: str, expires_minutes: int) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RuntimeError("email delivery failed")
        self.deliveries.append({"email": email, "code": code})


def build(monkeypatch, sender=None):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MemoryAuthStore()
    app = FastAPI()
    kwargs = {} if sender is None else {"email_sender": sender}
    app.include_router(create_auth_router(store=store, secret="h" * 32, cookie_secure=False,
                                          revocation_store=MemoryRevocationStore(), **kwargs))
    return TestClient(app), store


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def signup(client, email):
    return client.post("/auth/signup", json={"login_id": email, **PAYLOAD}, headers=csrf(client))


# --- 발송기 선택 -------------------------------------------------------------

@pytest.mark.parametrize("environment", [None, "", "production", "demo"])
def test_unset_provider_outside_local_does_not_stop_startup_and_never_records(monkeypatch, environment):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    if environment is None:
        monkeypatch.delenv("PROVENA_ENV", raising=False)
    else:
        monkeypatch.setenv("PROVENA_ENV", environment)
    sender = configured_email_sender()  # 예외 없이 만들어져야 서버가 뜬다
    assert isinstance(sender, UnavailableEmailSender)
    assert not isinstance(sender, RecordingEmailSender)
    with pytest.raises(EmailDeliveryUnavailable):
        sender.send_verification_email(email="a@example.com", code="123456", expires_minutes=5)


def test_unset_provider_is_recording_only_when_local(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.setenv("PROVENA_ENV", "local")
    assert isinstance(configured_email_sender(), RecordingEmailSender)


def test_router_builds_without_provider_and_email_signup_is_503_but_others_work(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("PROVENA_ENV", raising=False)
    monkeypatch.delenv("PROVENA_DEV_MODE", raising=False)
    store = MemoryAuthStore()
    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret="h" * 32, revocation_store=MemoryRevocationStore()))
    client = TestClient(app, base_url="https://testserver")
    response = client.post("/auth/signup", json={"login_id": "mail@example.com", **PAYLOAD}, headers=csrf(client))
    assert response.status_code == 503
    assert "mail@example.com" not in response.text
    assert store.get_signup_verification("mail@example.com") is None  # 대기 신청이 남지 않는다
    # 이메일이 아닌 아이디의 가입은 메일이 필요 없어 그대로 된다
    assert client.post("/auth/signup", json={"login_id": "plain-id", **PAYLOAD}, headers=csrf(client)).status_code == 201


# --- 발송 실패 --------------------------------------------------------------

def test_first_send_failure_is_503_and_pending_row_is_removed(monkeypatch):
    sender = FailingSender()
    client, store = build(monkeypatch, sender)
    response = signup(client, "fail@example.com")
    assert response.status_code == 503
    assert "fail@example.com" not in response.text and "email delivery failed" not in response.text
    assert store.get_signup_verification("fail@example.com") is None
    # 지워졌으므로 같은 이메일로 바로 다시 가입할 수 있다
    sender.failures = 0
    assert signup(client, "fail@example.com").status_code == 201


def test_resend_failure_is_503_and_request_stays_resumable(monkeypatch):
    sender = FailingSender(failures=0)
    client, store = build(monkeypatch, sender)
    assert signup(client, "resume@example.com").status_code == 201
    row = store._signup_requests["resume@example.com"]
    row["last_verification_sent_at"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    count_before = row["verification_send_count"]
    sender.failures = 99
    response = client.post("/auth/signup/resend", json={"login_id": "resume@example.com", "code": "000000"}, headers=csrf(client))
    assert response.status_code == 503
    assert store._signup_requests["resume@example.com"]["verification_send_count"] == count_before
    sender.failures = 0
    sender.attempts = 0
    again = client.post("/auth/signup/resend", json={"login_id": "resume@example.com", "code": "000000"}, headers=csrf(client))
    assert again.status_code == 200 and again.json()["status"] == "sent"


# --- 미인증 신청 덮어쓰기(상세는 tests/test_signup_edges.py) --------------------------

def test_unverified_request_is_overwritten_even_when_code_never_expired(monkeypatch):
    sender = RecordingEmailSender()
    client, store = build(monkeypatch, sender)
    assert signup(client, "squat@example.com").status_code == 201
    old_id = store._signup_requests["squat@example.com"]["request_id"]
    store._signup_requests["squat@example.com"]["last_verification_sent_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    again = client.post("/auth/signup", json={"login_id": "squat@example.com", "password": "other-pass-456",
                                              "password_confirmation": "other-pass-456"}, headers=csrf(client))
    assert again.status_code == 201
    assert store._signup_requests["squat@example.com"]["request_id"] == old_id  # 같은 행을 덮어쓴다
    assert len(sender.deliveries) == 2


def test_verified_or_reviewed_requests_are_never_overwritten(monkeypatch):
    sender = RecordingEmailSender()
    client, store = build(monkeypatch, sender)
    assert signup(client, "done@example.com").status_code == 201
    code = sender.deliveries[-1]["code"]
    assert client.post("/auth/signup/verify", json={"login_id": "done@example.com", "code": code}, headers=csrf(client)).status_code == 200
    store._signup_requests["done@example.com"]["requested_at"] = datetime.now(timezone.utc) - timedelta(days=30)
    assert signup(client, "done@example.com").status_code == 409


def test_request_without_any_code_is_overwritten(monkeypatch):
    client, store = build(monkeypatch, RecordingEmailSender())
    store.create_pending_user("nocode@example.com", "hash", email_verification_required=True)
    assert signup(client, "nocode@example.com").status_code == 201


def test_postgres_store_overwrites_unverified_row_in_one_transaction():
    from backend.services.auth_store import PostgresAuthStore

    statements: list[tuple[str, tuple]] = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def transaction(self):
            return self

        def execute(self, sql, params=()):
            statements.append((" ".join(sql.split()), params))
            text = statements[-1][0]

            class Result:
                def fetchone(self_inner):
                    # 계정은 없고, 인증 전 대기 신청 한 행이 있다
                    return (7, True, None) if text.startswith("SELECT request_id") else None
            return Result()

    result = PostgresAuthStore(connect=lambda: Conn()).create_pending_user("pg@example.com", "hash", email_verification_required=True)
    assert result == "replaced"
    kinds = [s.split()[0] for s, _ in statements]
    assert kinds == ["SELECT", "SELECT", "UPDATE"]
    select_sql = statements[1][0]
    assert "status = 'pending'" in select_sql and "FOR UPDATE" in select_sql
    update_sql, params = statements[2]
    assert "verification_code_hash = NULL" in update_sql and params == ("hash", 7)


# --- 108 SQL, 명세 -----------------------------------------------------------

def test_108_revokes_supabase_roles_only_when_they_exist():
    sql = (ROOT / "db" / "108_auth_privacy_hardening.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert not re.search(r"FROM\s+anon\b|FROM\s+authenticated\b|anon\s*,\s*authenticated", code)
    assert "DO $$" in code and "pg_roles" in code
    assert "'anon'" in code and "'authenticated'" in code
    # 두 번 돌려도 되는 문장만 쓴다
    assert not re.search(r"\bCREATE\s+(TABLE|INDEX)\b(?!\s+IF NOT EXISTS)", code)


def test_openapi_lists_reset_verification_and_new_response_fields(monkeypatch):
    import importlib.util
    import json

    spec = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert "/admin/signup-requests/by-id/{request_id}/reset-verification" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert {"request_id", "email_verified"} <= set(schemas["SignupRequestItem"]["properties"])
    assert "request_id" in schemas["SignupVerificationResetResult"]["properties"]
    assert "request_id" in schemas["SignupReviewByIdResult"]["properties"]
    assert importlib.util.find_spec("backend.admin_api") is not None


def test_resend_does_not_need_a_code(monkeypatch):
    """C-21: 재발송 본문에 `code`가 없어도 된다(있어도 무시). 명세에도 필수가 아니다."""
    import json

    sender = FailingSender(failures=0)
    client, store = build(monkeypatch, sender)
    assert signup(client, "nocode@example.com").status_code == 201
    store._signup_requests["nocode@example.com"]["last_verification_sent_at"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    r = client.post("/auth/signup/resend", json={"login_id": "nocode@example.com"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["status"] == "sent"
    spec = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    body = spec["paths"]["/auth/signup/resend"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert spec["components"]["schemas"][body.rsplit("/", 1)[1]]["required"] == ["login_id"]
