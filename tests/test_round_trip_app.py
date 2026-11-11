"""앱 한 바퀴 시험 (L-08 시험 공백): 가입 대기 -> 관리자 승인 -> 로그인 -> 채팅 -> 내 대화 목록. 실제 `create_app` 한 개에 이어서 부른다.
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

OWNER, OWNER_PW = "owner", "owner-password-1"
NEWBIE, NEWBIE_PW = "newbie", "newbie-password-1"


@pytest.fixture
def app_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_SECRET", "s" * 40)
    monkeypatch.setenv("CHECKPOINTER", "memory")
    monkeypatch.setenv("PROVENA_OWNER_LOGIN_ID", OWNER)
    store = MemoryAuthStore()
    owner = store.create_user(OWNER, hash_password(OWNER_PW), "admin")
    store.create_pending_user(NEWBIE, hash_password(NEWBIE_PW))
    app = create_app(auth_store=store, revocation_store=MemoryRevocationStore(), graph_factory=graph_factory())
    with TestClient(app):  # lifespan(체크포인터·저장소)을 연다
        yield app, store, owner


def with_csrf(app):
    c = TestClient(app, base_url="https://testserver")  # 운영처럼 Secure 쿠키 그대로(https 주소로 부른다)
    token = create_csrf_token("s" * 40)
    c.cookies.set(CSRF_COOKIE_NAME, token)
    c.headers["X-CSRF-Token"] = token
    return c


def login(app, login_id, password):
    c = with_csrf(app)
    r = c.post("/auth/login", json={"login_id": login_id, "password": password})
    return c, r


def test_pending_user_cannot_log_in_then_owner_approves_then_user_logs_in_and_chats(app_env):
    app, store, owner = app_env
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
    app, store, owner = app_env
    admin = with_csrf(app)
    admin.cookies.set(AUTH_COOKIE_NAME, create_access_token(owner.user_id, owner.role, secret="s" * 40))
    assert admin.post(f"/admin/signup-requests/{NEWBIE}/reject").status_code == 200
    assert login(app, NEWBIE, NEWBIE_PW)[1].status_code in (401, 403)
    anon = with_csrf(app)
    assert anon.post("/chat", json={"message": "안녕"}).status_code == 401
