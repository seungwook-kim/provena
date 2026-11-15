"""인증·가입·가입 관리 API의 오류 문구가 한국어인지 본다(놓친 것 C-26).

두 겹으로 본다.
1. 코드 훑기: `backend/auth.py`, `backend/admin_api.py`, `backend/profile_api.py`의 모든 `HTTPException(detail=...)` 문구에 한글이 있다.
2. 실제 응답: 예전에 영어였던 오류 길 12개를 불러 `detail`이 한국어인지, 상태 코드가 그대로인지 본다.
"""
import ast
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_api import create_admin_router
from backend.auth import CSRF_COOKIE_NAME, create_access_token, create_auth_router, hash_password
from backend.services.auth_store import MemoryAuthStore
from backend.services.email_sender import RecordingEmailSender
from auth_test_support import MemoryRevocationStore

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("backend/auth.py", "backend/admin_api.py", "backend/profile_api.py")
HANGUL = re.compile("[가-힣]")
ENGLISH_WORD = re.compile("[a-z]{3,}")   # CSRF 같은 대문자 약어는 허용
PASSWORD = "signup-pass-123"
EMAIL = "new.user@example.com"


def is_korean(message) -> bool:
    return isinstance(message, str) and bool(HANGUL.search(message)) and not ENGLISH_WORD.search(message)


def _detail_texts(path: Path) -> list[tuple[int, str]]:
    """파일 안 `HTTPException(detail=...)`의 문구를 (줄, 문구)로 모은다. 상수 이름은 모듈 맨 위 대입에서 찾는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}

    def text_of(node: ast.AST) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.Dict):   # {"reason": 코드, "message": 문구}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "message":
                    return text_of(value)
        return f"<읽을 수 없는 detail: {ast.dump(node)[:80]}>"

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException":
            for keyword in node.keywords:
                if keyword.arg == "detail":
                    found.append((node.lineno, text_of(keyword.value)))
    return found


@pytest.mark.parametrize("source", SOURCES)
def test_every_http_error_detail_in_source_is_korean(source):
    details = _detail_texts(ROOT / source)
    assert details, f"{source}에서 HTTPException detail을 하나도 찾지 못했다"
    english = [(line, text) for line, text in details if not is_korean(text)]
    assert english == [], f"{source}에 한국어가 아닌 오류 문구가 있다: {english}"


def build(monkeypatch, store):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    owner = store.create_user("owner", hash_password("owner-password-1"), "admin")
    secret = "k" * 32
    app = FastAPI()
    revocations = MemoryRevocationStore()
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False, revocation_store=revocations,
                                          email_sender=RecordingEmailSender()))
    app.include_router(create_admin_router(store=store, owner_login_id=owner.login_id, secret=secret, revocation_store=revocations))
    owner_client = TestClient(app)
    owner_client.cookies.set("provena_auth", create_access_token(owner.user_id, owner.role, secret=secret))
    return app, owner_client


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def post(client, path, body=None):
    return client.post(path, json=body, headers=csrf(client))


def signup_body(login_id):
    return {"login_id": login_id, "password": PASSWORD, "password_confirmation": PASSWORD}


def assert_korean_error(response, status):
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert is_korean(detail), f"한국어가 아닌 오류 문구: {detail!r}"


class SignupLookupFails(MemoryAuthStore):
    def get_signup_by_login_id(self, login_id):
        raise RuntimeError("test lookup failure")


class SignupStatusFails(MemoryAuthStore):
    def get_signup_status(self, user_id):
        raise RuntimeError("test status failure")


class NoPendingSignup(MemoryAuthStore):
    create_pending_user = None


class NoVerificationSave(MemoryAuthStore):
    save_verification = None


class NoVerify(MemoryAuthStore):
    verify_signup_code = None


class VerificationRowMissing(MemoryAuthStore):
    def get_signup_verification(self, login_id):
        return None


class IssueUnavailable(MemoryAuthStore):
    def issue_verification(self, *args, **kwargs):
        return "unavailable"


def test_login_storage_failure_while_reading_signup_is_korean(monkeypatch):
    app, _owner = build(monkeypatch, SignupLookupFails())
    assert_korean_error(post(TestClient(app), "/auth/login", {"login_id": "nobody", "password": PASSWORD}), 503)


def test_login_storage_failure_while_reading_approval_status_is_korean(monkeypatch):
    app, _owner = build(monkeypatch, SignupStatusFails())
    assert_korean_error(post(TestClient(app), "/auth/login", {"login_id": "owner", "password": "owner-password-1"}), 503)


def test_signup_without_approval_storage_is_korean(monkeypatch):
    app, _owner = build(monkeypatch, NoPendingSignup())
    assert_korean_error(post(TestClient(app), "/auth/signup", signup_body("plain-user")), 503)


def test_email_signup_without_verification_storage_is_korean(monkeypatch):
    app, _owner = build(monkeypatch, NoVerificationSave())
    assert_korean_error(post(TestClient(app), "/auth/signup", signup_body(EMAIL)), 503)


def test_verify_without_verification_storage_is_korean(monkeypatch):
    app, _owner = build(monkeypatch, NoVerify())
    assert_korean_error(post(TestClient(app), "/auth/signup/verify", {"login_id": EMAIL, "code": "123456"}), 503)


@pytest.mark.parametrize("store_class", [VerificationRowMissing, IssueUnavailable])
def test_email_signup_request_not_found_is_korean(monkeypatch, store_class):
    app, _owner = build(monkeypatch, store_class())
    assert_korean_error(post(TestClient(app), "/auth/signup", signup_body(EMAIL)), 404)


def test_admin_invalid_signup_action_is_korean(monkeypatch):
    store = MemoryAuthStore()
    store.create_pending_user("pending-api", hash_password(PASSWORD))
    _app, owner = build(monkeypatch, store)
    request_id = owner.get("/admin/signup-requests").json()["requests"][0]["request_id"]
    assert_korean_error(post(owner, "/admin/signup-requests/pending-api/unknown"), 422)
    assert_korean_error(post(owner, f"/admin/signup-requests/by-id/{request_id}/unknown"), 422)


def test_admin_approving_unverified_email_signup_is_korean(monkeypatch):
    app, owner = build(monkeypatch, MemoryAuthStore())
    assert post(TestClient(app), "/auth/signup", signup_body(EMAIL)).status_code == 201
    request_id = owner.get("/admin/signup-requests").json()["requests"][0]["request_id"]
    assert_korean_error(post(owner, f"/admin/signup-requests/{EMAIL}/approve"), 409)
    assert_korean_error(post(owner, f"/admin/signup-requests/by-id/{request_id}/approve"), 409)


def test_admin_verification_reset_unavailable_is_korean(monkeypatch):
    store = MemoryAuthStore()
    store.create_pending_user("pending-api", hash_password(PASSWORD))   # 이메일 인증이 없는 신청은 초기화할 수 없다
    _app, owner = build(monkeypatch, store)
    request_id = owner.get("/admin/signup-requests").json()["requests"][0]["request_id"]
    assert_korean_error(post(owner, f"/admin/signup-requests/by-id/{request_id}/reset-verification"), 409)


# ---------- 저장소가 멈췄을 때 인증번호 확인·재발송은 503(팀장 수정, 놓친 것 N-3) ----------
class VerifyStoreDown(MemoryAuthStore):
    def verify_signup_code(self, *args, **kwargs):
        raise RuntimeError("test store down")


class VerificationReadDown(MemoryAuthStore):
    def get_signup_verification(self, login_id):
        raise RuntimeError("test store down")


def test_verify_code_storage_failure_is_503_and_korean(monkeypatch):
    app, _owner = build(monkeypatch, VerifyStoreDown())
    response = post(TestClient(app, raise_server_exceptions=False), "/auth/signup/verify", {"login_id": EMAIL, "code": "123456"})
    assert_korean_error(response, 503)
    assert response.json()["detail"] == "이메일 인증 저장소를 사용할 수 없습니다."


def test_resend_storage_failure_is_503_and_korean(monkeypatch):
    app, _owner = build(monkeypatch, VerificationReadDown())
    response = post(TestClient(app, raise_server_exceptions=False), "/auth/signup/resend", {"login_id": EMAIL})
    assert_korean_error(response, 503)
    assert response.json()["detail"] == "이메일 인증 저장소를 사용할 수 없습니다."


def test_missing_signup_request_says_signup_request_not_user(monkeypatch):
    """가입 신청 경로 세 곳의 없는 신청 404는 "가입 신청을 찾을 수 없습니다."이다(팀장 수정, 놓친 것 N-6). 사용자 계정 경로는 그대로다."""
    _app, owner = build(monkeypatch, MemoryAuthStore())
    for path in ("/admin/signup-requests/nobody@example.com/approve", "/admin/signup-requests/by-id/999999/approve",
                 "/admin/signup-requests/by-id/999999/reset-verification"):
        response = post(owner, path)
        assert response.status_code == 404 and response.json()["detail"] == "가입 신청을 찾을 수 없습니다.", (path, response.text)
    response = post(owner, "/admin/users/no-such-id/promote")
    assert response.status_code == 404 and response.json()["detail"] == "사용자를 찾을 수 없습니다."
