"""앱 한 바퀴 시험 (L-08 시험 공백): 가입(/auth/signup) -> 이메일 인증(/auth/signup/verify) -> 관리자 승인 -> 로그인 -> 채팅 -> 내 대화 목록. 실제 `create_app` 한 개에 이어서 부른다.
인증번호는 기록용 발송기(`RecordingEmailSender.deliveries`)에서 읽는다. `create_app` 은 발송기를 인자로 받지 않아(`backend/auth.py` `configured_email_sender()`) 시험에서 `backend.auth.configured_email_sender` 를 기록용 발송기로 바꿔 끼운다.
DB·키·네트워크 없이 메모리 사용자 저장소와 가짜 모델을 쓴다. 한계: 내 정보(`/me/profile`)는 DB 없이 조립한 앱에 열리지 않아(`backend/main.py`의 profile_store) 여기에 없고
`tests/test_profile_api.py`가 따로 본다. 만들어진 화면 번들은 서빙하지 않는다(번들 빌드는 npm이 필요)."""
from __future__ import annotations

import pytest
from api_test_support import ENV_KEYS, ask, graph_factory
from auth_test_support import MemoryRevocationStore
from fastapi.testclient import TestClient

from backend.auth import CSRF_COOKIE_NAME, AUTH_COOKIE_NAME, create_access_token, create_csrf_token, hash_password
from backend.main import create_app
from backend.services.auth_store import MemoryAuthStore
from backend.services.email_sender import RecordingEmailSender

OWNER, OWNER_PW = "owner", "owner-password-1"
NEWBIE, NEWBIE_PW = "newbie@example.com", "newbie-password-1"


@pytest.fixture
def app_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_SECRET", "s" * 40)
    monkeypatch.setenv("CHECKPOINTER", "memory")
    monkeypatch.setenv("PROVENA_OWNER_LOGIN_ID", OWNER)
    sender = RecordingEmailSender()
    monkeypatch.setattr("backend.auth.configured_email_sender", lambda: sender)
    store = MemoryAuthStore()
    owner = store.create_user(OWNER, hash_password(OWNER_PW), "admin")
    app = create_app(auth_store=store, revocation_store=MemoryRevocationStore(), graph_factory=graph_factory())
    with TestClient(app):  # lifespan(체크포인터·저장소)을 연다
        yield app, store, owner, sender


def with_csrf(app):
    c = TestClient(app, base_url="https://testserver")  # 운영처럼 Secure 쿠키 그대로(https 주소로 부른다)
    token = create_csrf_token("s" * 40)
    c.cookies.set(CSRF_COOKIE_NAME, token)
    c.headers["X-CSRF-Token"] = token
    return c


def signup(app, sender, verify=True):
    """가입 신청 -> (verify 이면) 기록용 발송기에서 받은 인증번호로 인증. 가입 신청자는 승인 전까지 대기 상태."""
    c = with_csrf(app)
    r = c.post("/auth/signup", json={"login_id": NEWBIE, "password": NEWBIE_PW, "password_confirmation": NEWBIE_PW})
    assert r.status_code == 201, r.text
    assert sender.deliveries[-1]["email"] == NEWBIE
    if verify:
        code = sender.deliveries[-1]["code"]
        r = c.post("/auth/signup/verify", json={"login_id": NEWBIE, "code": code})
        assert r.status_code == 200, r.text


def login(app, login_id, password):
    c = with_csrf(app)
    r = c.post("/auth/login", json={"login_id": login_id, "password": password})
    return c, r


def test_signup_verify_then_owner_approves_then_user_logs_in_and_chats(app_env):
    app, store, owner, sender = app_env
    signup(app, sender)
    _, before = login(app, NEWBIE, NEWBIE_PW)
    assert before.status_code in (401, 403)                                  # 승인 전에는 로그인 안 됨
    assert not any(k.startswith("provena_auth") for k in before.cookies.keys())

    admin = with_csrf(app)
    admin.cookies.set(AUTH_COOKIE_NAME, create_access_token(owner.user_id, owner.role, secret="s" * 40))
    assert admin.get("/admin/signup-requests").json()["requests"][0]["login_id"] == NEWBIE
    r = admin.post(f"/admin/signup-requests/{NEWBIE}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"

    c, ok = login(app, NEWBIE, NEWBIE_PW)
    assert ok.status_code == 200
    resp, events = ask(c, "SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert resp.status_code == 200 and events and events[-1][0] in ("done", "end"), events[-3:]
    tid = next(d["thread_id"] for _, d in events if d.get("thread_id"))
    threads = c.get("/threads")
    assert threads.status_code == 200 and tid in threads.text


def test_rejected_user_stays_out_and_chat_needs_login(app_env):
    app, store, owner, sender = app_env
    signup(app, sender)
    admin = with_csrf(app)
    admin.cookies.set(AUTH_COOKIE_NAME, create_access_token(owner.user_id, owner.role, secret="s" * 40))
    assert admin.post(f"/admin/signup-requests/{NEWBIE}/reject").status_code == 200
    assert login(app, NEWBIE, NEWBIE_PW)[1].status_code in (401, 403)
    anon = with_csrf(app)
    assert anon.post("/chat", json={"message": "안녕"}).status_code == 401
