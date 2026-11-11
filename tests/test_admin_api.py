"""사용자 관리 API 시험 — docs/specs/admin-roles.md AC-01~18. 실제 DB 없이 가짜 저장소로 돈다(쓰기 횟수를 센다).

계정·비밀번호는 시험 안에서 만든 가짜다.
"""
from auth_test_support import create_test_auth_router, revocations_for

import logging
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.admin_api import check_owner, create_admin_router, is_owner, owner_check_for
from backend.auth import CSRF_COOKIE_NAME, AuthUser, create_require_admin_dependency, hash_password

OWNER = "owner"
LIST_KEYS = {"login_id", "role", "is_owner", "created_at"}
PASSWORD = secrets.token_urlsafe(12)
HASH = hash_password(PASSWORD)


@dataclass(frozen=True)
class Row:
    login_id: str
    role: str
    created_at: datetime
    password_hash: str = "must-not-leak"   # 저장소가 더 돌려줘도 라우터가 네 칸만 내보내는지 본다
    user_id: str = "must-not-leak"


class FakeStore:
    def __init__(self, users):
        self.users = {u.login_id: u for u in users}
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.created = {u.login_id: base + timedelta(hours=i) for i, u in enumerate(users)}
        self.log = []          # (by_user_id, target_user_id, action)
        self.writes = 0
        self.fail_read = False
        self.fail_log = False

    def _check(self):
        if self.fail_read:
            raise RuntimeError("test store failure")

    def get_by_login_id(self, login_id):
        self._check()
        return self.users.get(login_id)

    def get_by_user_id(self, user_id):
        self._check()
        return next((u for u in self.users.values() if str(u.user_id) == str(user_id)), None)

    def list_users(self):
        self._check()
        return [Row(u.login_id, u.role, self.created[u.login_id]) for u in
                sorted(self.users.values(), key=lambda u: self.created[u.login_id])]

    def set_role(self, target_login_id, new_role, by_user_id):
        self._check()
        target = self.users.get(target_login_id)
        if target is None:
            return "missing"
        if not target.is_active:
            return "inactive"
        if target.role == new_role:
            return "unchanged"
        if self.fail_log:   # 한 트랜잭션: 기록이 실패하면 역할도 그대로
            raise RuntimeError("test log write failure")
        self.users[target_login_id] = replace(target, role=new_role)
        self.log.append((str(by_user_id), str(target.user_id), "promote" if new_role == "admin" else "revoke"))
        self.writes += 1
        return "changed"


def make_user(login_id, role, active=True):
    return AuthUser(uuid4(), login_id, HASH, role, active)


def build(owner_login_id=OWNER, extra=()):
    users = [make_user(OWNER, "admin"), make_user("other-admin", "admin"), make_user("member", "user"),
             make_user("sleeper", "user", active=False), *extra]
    store = FakeStore(users)
    secret = secrets.token_urlsafe(48)
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_test_auth_router(store=store, secret=secret, cookie_secure=False,
                                               owner_check=owner_check_for(owner_login_id)))
    app.include_router(create_admin_router(store=store, owner_login_id=owner_login_id, secret=secret))
    admin_guard = create_require_admin_dependency(store=store, secret=secret)

    @app.get("/approvals-like")   # SDD "관리자" 경로 대역(시험에서만)
    def approvals_like(user: AuthUser = Depends(admin_guard)):
        return {"ok": True}

    return app, store


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    return build()


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def login(app, login_id):
    c = TestClient(app)
    r = c.post("/auth/login", json={"login_id": login_id, "password": PASSWORD}, headers=csrf(c))
    assert r.status_code == 200, r.text
    return c


def post(c, login_id, action, **kw):
    return c.post(f"/admin/users/{login_id}/{action}", headers=csrf(c), **kw)


# ---- AC-01 목록 -------------------------------------------------------------
def test_owner_lists_users_with_only_allowed_keys(env):
    app, store = env
    r = login(app, OWNER).get("/admin/users")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    users = r.json()["users"]
    assert [u["login_id"] for u in users] == [OWNER, "other-admin", "member", "sleeper"]   # created_at 오름차순
    assert all(set(u) == LIST_KEYS for u in users)
    assert [u["is_owner"] for u in users] == [True, False, False, False]
    assert "must-not-leak" not in r.text and "$2b$" not in r.text
    assert users[0]["created_at"].startswith("2026-11-01T00:00:00")


# ---- AC-02 권한 없음 ---------------------------------------------------------
@pytest.mark.parametrize("who, status", [("other-admin", 403), ("member", 403), (None, 401)])
def test_non_owner_cannot_use_any_endpoint(env, who, status):
    app, store = env
    c = login(app, who) if who else TestClient(app)
    assert c.get("/admin/users").status_code == status
    for target in ("member", "other-admin", "no-such-id", OWNER):
        for action in ("promote", "revoke"):
            r = post(c, target, action)
            assert r.status_code == status, (target, action)
    if status == 403:
        assert c.get("/admin/users").json()["detail"] in {"최고 관리자 권한이 필요합니다.", "관리자 권한이 필요합니다."}
    assert store.writes == 0 and store.log == []


# ---- AC-03 닫힘 / AC-14 대소문자 ---------------------------------------------
@pytest.mark.parametrize("configured, caller", [
    ("", OWNER), ("no-such-owner", OWNER), ("member", "member"), ("google-owner", "google-owner"),
    ("Owner", OWNER), ("owner ", OWNER),
])
def test_misconfigured_owner_closes_user_management_for_everyone(monkeypatch, configured, caller):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    app, store = build(configured, extra=(make_user("google-owner", "admin"),))
    c = login(app, caller)
    assert c.get("/admin/users").status_code == 403
    assert post(c, "member", "promote").status_code == 403
    assert c.get("/me").json()["is_owner"] is False
    assert store.writes == 0
    # 나머지 앱은 그대로: 관리자 경로·/me 는 정상
    assert login(app, OWNER).get("/approvals-like").status_code == 200


# ---- AC-04 등록 / AC-05 다시 로그인 없이 / AC-06 해제 ------------------------------
def test_promote_then_revoke_takes_effect_on_next_request_without_relogin(env):
    app, store = env
    owner = login(app, OWNER)
    member = login(app, "member")                       # 등록 전에 받은 쿠키
    assert member.get("/approvals-like").status_code == 403
    assert member.get("/me").json() == {"user_id": str(store.users["member"].user_id), "role": "user", "is_owner": False}

    r = post(owner, "member", "promote")
    assert r.status_code == 200 and r.json() == {"login_id": "member", "role": "admin", "changed": True}
    assert store.users["member"].role == "admin"
    assert store.log == [(str(store.users[OWNER].user_id), str(store.users["member"].user_id), "promote")]

    assert member.get("/approvals-like").status_code == 200             # 같은 쿠키, 다시 로그인 안 함
    assert member.get("/me").json()["role"] == "admin"
    assert member.get("/me").json()["is_owner"] is False
    assert member.get("/admin/users").status_code == 403                # 사용자 관리는 계속 막힘
    assert post(member, "other-admin", "revoke").status_code == 403    # 시나리오 8: 등록된 사람이 등록·해제 시도

    r = post(owner, "member", "revoke")
    assert r.status_code == 200 and r.json() == {"login_id": "member", "role": "user", "changed": True}
    assert [entry[2] for entry in store.log] == ["promote", "revoke"]
    assert member.get("/approvals-like").status_code == 403
    assert member.get("/me").json()["role"] == "user"
    assert store.writes == 2


# ---- AC-07 같은 요청 두 번 ----------------------------------------------------
def test_idempotent_requests_return_changed_false_without_log(env):
    app, store = env
    owner = login(app, OWNER)
    r = post(owner, "other-admin", "promote")
    assert r.status_code == 200 and r.json() == {"login_id": "other-admin", "role": "admin", "changed": False}
    r = post(owner, "member", "revoke")
    assert r.status_code == 200 and r.json()["changed"] is False
    assert store.writes == 0 and store.log == []


# ---- AC-08 없는 아이디 / AC-09 존재 숨김 -------------------------------------------
def test_unknown_id_is_404_for_owner_but_403_for_other_admin(env):
    app, store = env
    r = post(login(app, OWNER), "no-such-id", "promote")
    assert r.status_code == 404 and r.json()["detail"] == "사용자를 찾을 수 없습니다."
    r = post(login(app, "other-admin"), "no-such-id", "promote")
    assert r.status_code == 403 and r.json()["detail"] == "최고 관리자 권한이 필요합니다."
    assert store.writes == 0


# ---- AC-10 최고 관리자 보호 / AC-11 비활성 대상 ---------------------------------------
def test_owner_cannot_be_target_and_inactive_target_is_409(env):
    app, store = env
    owner = login(app, OWNER)
    for action in ("promote", "revoke"):
        r = post(owner, OWNER, action)
        assert r.status_code == 409 and r.json()["detail"] == "최고 관리자는 바꿀 수 없습니다."
    r = post(owner, "sleeper", "promote")
    assert r.status_code == 409 and r.json()["detail"] == "비활성 계정입니다."
    assert store.writes == 0 and store.users[OWNER].role == "admin"


# ---- AC-12 CSRF -----------------------------------------------------------
def test_csrf_missing_or_mismatched_is_403_and_no_write(env):
    app, store = env
    owner = login(app, OWNER)
    assert owner.post("/admin/users/member/promote").status_code == 403
    csrf(owner)
    r = owner.post("/admin/users/member/promote", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and r.json()["detail"] == "CSRF 검증에 실패했습니다."
    assert store.writes == 0 and store.users["member"].role == "user"


# ---- AC-13 요청으로 올리기 불가 ---------------------------------------------------
def test_request_fields_cannot_grant_owner(env):
    app, store = env
    c = login(app, "other-admin")
    h = csrf(c)
    assert c.post("/admin/users/member/promote?owner=1&is_owner=true", json={"is_owner": True, "role": "owner"},
                  headers=h).status_code == 403
    assert c.get("/admin/users", params={"is_owner": "true"}).status_code == 403
    assert store.writes == 0


# ---- AC-15 트랜잭션 / AC-16 저장소 오류 --------------------------------------------
def test_log_write_failure_is_503_and_role_unchanged(env):
    app, store = env
    owner = login(app, OWNER)
    store.fail_log = True
    r = post(owner, "member", "promote")
    assert r.status_code == 503 and r.json()["detail"] == "인증 저장소를 사용할 수 없습니다."
    assert store.users["member"].role == "user" and store.log == []


def test_store_failure_is_503(env):
    app, store = env
    owner = login(app, OWNER)
    store.fail_read = True
    assert owner.get("/admin/users").status_code == 503
    assert post(owner, "member", "promote").status_code == 503


def test_list_failure_after_auth_is_503(env):
    app, store = env
    owner = login(app, OWNER)
    original = store.list_users
    store.list_users = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert owner.get("/admin/users").status_code == 503
    store.list_users = original


# ---- AC-17 /me -----------------------------------------------------------
def test_me_is_owner_only_for_owner(env):
    app, _ = env
    assert login(app, OWNER).get("/me").json()["is_owner"] is True
    assert login(app, "other-admin").get("/me").json()["is_owner"] is False
    assert login(app, "member").get("/me").json()["is_owner"] is False


def test_me_without_owner_check_keeps_old_shape(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = FakeStore([make_user("member", "user")])
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_test_auth_router(store=store, secret=secrets.token_urlsafe(48), cookie_secure=False))
    assert set(login(app, "member").get("/me").json()) == {"user_id", "role"}


def test_is_owner_rules():
    owner = make_user(OWNER, "admin")
    assert is_owner(owner, OWNER) is True
    assert is_owner(replace(owner, role="user"), OWNER) is False
    assert is_owner(replace(owner, is_active=False), OWNER) is False
    assert is_owner(owner, "") is False and is_owner(owner, None) is False
    assert is_owner(None, OWNER) is False
    assert is_owner(make_user("google-x", "admin"), "google-x") is False


def test_owner_endpoints_are_exactly_three(env):
    app, _ = env
    paths = app.openapi()["paths"]
    assert {p for p in paths if p.startswith("/admin/users")} == {
        "/admin/users", "/admin/users/{login_id}/promote", "/admin/users/{login_id}/revoke"}
    assert set(paths["/admin/users"]) == {"get"}
    assert set(paths["/admin/users/{login_id}/promote"]) == {"post"}


# ---- AC-18 시작 확인 ----------------------------------------------------------
@pytest.mark.parametrize("configured, want, level", [
    ("", "unset", logging.WARNING),
    ("ghost-owner", "mismatch", logging.ERROR),
    ("member", "mismatch", logging.ERROR),
    ("sleeper", "mismatch", logging.ERROR),
    ("google-owner", "mismatch", logging.ERROR),
    (OWNER, "ok", logging.INFO),
])
def test_startup_check_logs_one_line_without_value(caplog, configured, want, level):
    store = FakeStore([make_user(OWNER, "admin"), make_user("member", "user"),
                       make_user("sleeper", "admin", active=False), make_user("google-owner", "admin")])
    with caplog.at_level(logging.INFO, logger="backend.admin_api"):
        assert check_owner(store, configured) == want
    records = [r for r in caplog.records if r.name == "backend.admin_api"]
    assert len(records) == 1 and records[0].levelno == level
    if configured:
        assert configured not in caplog.text


def test_startup_check_store_failure_is_warning(caplog):
    store = FakeStore([])
    store.fail_read = True
    with caplog.at_level(logging.INFO, logger="backend.admin_api"):
        assert check_owner(store, OWNER) == "unavailable"
    assert "RuntimeError" in caplog.text and OWNER not in caplog.text.replace("backend.admin_api", "")


def test_main_app_mounts_admin_router_and_health_survives_bad_owner(monkeypatch, caplog):
    import base64
    import os

    from profile_test_support import MemoryProfileStore

    from backend.services.profile_crypto import KEY_ENV

    store = FakeStore([make_user("member", "user")])
    monkeypatch.setattr("backend.main.PostgresAuthStore", lambda dsn: store)
    monkeypatch.setattr("backend.main.PostgresProfileStore", lambda dsn: MemoryProfileStore())
    for key in ("PROVENA_ENV", "PROVENA_DEV_MODE", "MCP_TOKEN", "SEARCH_WARMUP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv(KEY_ENV, "1:" + base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("PROVENA_OWNER_LOGIN_ID", "typo-owner-id")
    from backend.main import create_app

    with caplog.at_level(logging.INFO, logger="backend.admin_api"):
        app = create_app()
        with TestClient(app) as client:   # lifespan 이 돈다(시작 확인)
            assert client.get("/health").status_code == 200
            assert client.get("/admin/users").status_code == 401
    assert "사용자 관리를 닫았다" in caplog.text and "typo-owner-id" not in caplog.text
    assert {"/admin/users", "/admin/users/{login_id}/promote", "/admin/users/{login_id}/revoke"} <= set(app.openapi()["paths"])
    assert {"/me/profile"} <= set(app.openapi()["paths"])


# ---- 화면 주소와 API 주소가 같다 (/admin/users, web/react-app/src/App.jsx) ---------
NAVIGATE = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}   # 브라우저 주소창·새로고침


def test_browser_navigation_gets_react_page_and_fetch_gets_api(env, tmp_path):
    app, store = env
    page = tmp_path / "index.html"
    page.write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    secret = secrets.token_urlsafe(48)
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_test_auth_router(store=store, secret=secret, cookie_secure=False,
                                               owner_check=owner_check_for(OWNER)))
    app.include_router(create_admin_router(store=store, owner_login_id=OWNER, secret=secret, html_page=lambda: page))
    anon = TestClient(app)
    html = anon.get("/admin/users", headers=NAVIGATE)
    assert html.status_code == 200 and '<div id="root"></div>' in html.text   # 화면이 뜨고, 화면이 /me·API로 권한을 본다
    # 같은 주소의 HTML이 브라우저 캐시에 남으면 화면 fetch가 HTML을 받아 '응답 형식 오류'가 난다(11/11 새로고침 재현)
    assert html.headers["cache-control"] == "no-store" and "accept" in html.headers["vary"].lower()
    assert anon.get("/admin/users").status_code == 401                        # fetch 기본 Accept(*/*)는 API
    assert anon.get("/admin/users", headers={"Accept": "application/json"}).status_code == 401
    member = login(app, "member")
    assert member.get("/admin/users").status_code == 403
    assert "users" not in member.get("/admin/users", headers=NAVIGATE).text     # 화면 HTML에는 목록이 없다
    owner = login(app, OWNER)
    r = owner.get("/admin/users", headers={"Accept": "*/*"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert "accept" in r.headers["vary"].lower()
    assert {row["login_id"] for row in r.json()["users"]} >= {OWNER, "member"}


def test_without_react_build_navigation_still_gets_api(env):
    app, store = env
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_admin_router(store=store, owner_login_id=OWNER, secret=secrets.token_urlsafe(48),
                                           html_page=lambda: None))
    assert TestClient(app).get("/admin/users", headers=NAVIGATE).status_code == 401
