"""내 정보 API 시험 — MYINFO_SPEC.md 3·6장. 계정·키·값은 시험 안에서 만든 가짜다(DB 없이 돈다)."""
from auth_test_support import create_test_auth_router, revocations_for
from profile_test_support import MemoryProfileStore

import base64
import logging
import os
import secrets
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.errors import install_error_handlers
from backend.auth import CSRF_COOKIE_NAME, AuthUser, hash_password
from backend.profile_api import create_profile_router, mask_phone, normalize_phone, validate_profile
from backend.services.profile_crypto import KEY_ENV, ProfileCipher

GOOD = {"name": "이영희", "dept": "인프라·SRE팀", "phone": "01098765432", "address": "부산광역시 해운대구 센텀로 1"}
OTHER = {"name": "박관리", "dept": "정보보안팀", "phone": "010-2222-3333", "address": "서울특별시 중구 세종대로 2"}


class Users:
    def __init__(self, users):
        self.users = {str(user.user_id): user for user in users}

    def get_by_login_id(self, login_id):
        return next((u for u in self.users.values() if u.login_id == login_id), None)

    def get_by_user_id(self, user_id):
        return self.users.get(str(user_id))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    passwords = {name: secrets.token_urlsafe(18) for name in ("A", "B", "ADMIN")}
    users = {name: AuthUser(uuid4(), name, hash_password(passwords[name]), role)
             for name, role in (("A", "user"), ("B", "user"), ("ADMIN", "admin"))}
    auth_store = Users(users.values())
    profiles = MemoryProfileStore()
    cipher = ProfileCipher({1: os.urandom(32)})
    secret = secrets.token_urlsafe(48)
    app = FastAPI()
    install_error_handlers(app)   # 운영 앱(backend/main.py)과 같은 오류 처리기. 없이 시험하면 칸별 이유가 사라지는 것을 못 잡는다
    app.state.token_revocation_store = revocations_for(auth_store)
    app.include_router(create_test_auth_router(store=auth_store, secret=secret, cookie_secure=False,
                                               profile_completed=profiles.exists))
    app.include_router(create_profile_router(auth_store=auth_store, profile_store=profiles, cipher=cipher, secret=secret))

    def client(name=None):
        c = TestClient(app)
        if name:
            r = c.post("/auth/login", json={"login_id": name, "password": passwords[name]}, headers=csrf(c))
            assert r.status_code == 200
        return c

    return {"users": users, "passwords": passwords, "profiles": profiles, "cipher": cipher, "client": client, "app": app}


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def put(client, body, **kwargs):
    return client.put("/me/profile", json=body, headers=csrf(client), **kwargs)


# ---- 로그인·CSRF ------------------------------------------------------------
def test_requires_login(env):
    c = env["client"]()
    assert c.get("/me/profile").status_code == 401
    assert c.get("/me/profile", params={"view": "edit"}).status_code == 401
    assert put(c, GOOD).status_code == 401
    assert env["profiles"].rows == {}


def test_put_without_or_with_wrong_csrf_is_403_and_stores_nothing(env):
    c = env["client"]("A")
    assert c.put("/me/profile", json=GOOD).status_code == 403
    csrf(c)
    assert c.put("/me/profile", json=GOOD, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert env["profiles"].rows == {}


# ---- 입력 검사 ---------------------------------------------------------------
def test_invalid_input_is_422_with_fields_and_no_echo(env):
    c = env["client"]("A")
    bad = {"name": "이영희1", "dept": "부서" * 21, "phone": "1234-99887", "address": "부산"}
    r = put(c, bad)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error" and error["message"]
    assert set(error["details"]["fields"]) == {"name", "dept", "phone", "address"}
    assert r.json()["detail"] == error["message"]
    for value in bad.values():
        assert value not in r.text
    assert "99887" not in r.text
    assert env["profiles"].rows == {}


def test_empty_body_reports_every_field(env):
    r = put(env["client"]("A"), {})
    assert r.status_code == 422 and set(r.json()["error"]["details"]["fields"]) == {"name", "dept", "phone", "address"}


@pytest.mark.parametrize("raw", [b"not json 01055556666", b"[1, 2]", b'"01055556666"', b'{"name": 12345678}'])
def test_malformed_bodies_are_422_without_echo(env, raw):
    c = env["client"]("A")
    r = c.put("/me/profile", content=raw, headers={**csrf(c), "Content-Type": "application/json"})
    assert r.status_code == 422
    assert "01055556666" not in r.text and "12345678" not in r.text
    assert isinstance(r.json()["error"]["details"]["fields"], dict)


def test_oversized_body_is_rejected(env):
    r = put(env["client"]("A"), {**GOOD, "address": "가" * 9000})
    assert r.status_code == 422 and env["profiles"].rows == {}


def test_bad_view_value_is_422_without_echo(env):
    c = env["client"]("A")
    assert put(c, GOOD).status_code == 200
    r = c.get("/me/profile", params={"view": "raw-please"})
    assert r.status_code == 422 and "raw-please" not in r.text


@pytest.mark.parametrize("raw, expected", [
    ("01012345678", "010-1234-5678"), ("010-1234-5678", "010-1234-5678"), (" 011 123 4567 ", "011-123-4567"),
    ("0212345678", "02-1234-5678"), ("021234567", "02-123-4567"), ("0517771234", "051-777-1234"),
    ("06412345678", "064-1234-5678"),
    ("1234", None), ("01212345678", None), ("070-1234-5678", None), ("0661234567", None), ("010-1234-567a", None),
    ("０１０１２３４５６７８", None), ("٠١٠١٢٣٤٥٦٧٨", None), ("010123456789", None),
])
def test_normalize_phone_matches_mockup_rules(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("name, ok", [("이영희", True), ("Kim Min", True), ("김", False), ("이영희1", False),
                                      ("가" * 20, True), ("가" * 21, False), ("이-영희", False)])
def test_name_rule(name, ok):
    errors, _ = validate_profile({**GOOD, "name": name})
    assert ("name" not in errors) is ok


def test_dept_and_address_length_rules():
    assert "dept" not in validate_profile({**GOOD, "dept": "가" * 40})[0]
    assert "dept" in validate_profile({**GOOD, "dept": "가" * 41})[0]
    assert "address" in validate_profile({**GOOD, "address": "가" * 4})[0]
    assert "address" not in validate_profile({**GOOD, "address": "가" * 100})[0]
    assert "address" in validate_profile({**GOOD, "address": "가" * 101})[0]


def test_mask_phone():
    assert mask_phone("010-1234-5678") == "010-****-5678"
    assert mask_phone("02-123-4567") == "02-***-4567"
    assert mask_phone("01012345678") == "***"


# ---- 저장·보기 ---------------------------------------------------------------
def test_put_then_get_shows_only_masked_phone(env):
    c = env["client"]("A")
    saved = put(c, GOOD)
    assert saved.status_code == 200 and saved.headers["cache-control"] == "no-store"
    assert saved.json()["phone_masked"] == "010-****-5432" and "phone" not in saved.json()
    r = c.get("/me/profile")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body == {"name": "이영희", "dept": "인프라·SRE팀", "phone_masked": "010-****-5432",
                    "address": "부산광역시 해운대구 센텀로 1", "updated_at": body["updated_at"]}
    assert body["updated_at"]
    for raw in ("010-9876-5432", "01098765432", "9876"):
        assert raw not in r.text and raw not in saved.text


def test_edit_view_returns_raw_phone_no_store(env):
    c = env["client"]("A")
    put(c, GOOD)
    r = c.get("/me/profile", params={"view": "edit"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["phone"] == "010-9876-5432" and "phone_masked" not in r.json()


def test_missing_profile_is_404_no_store(env):
    r = env["client"]("A").get("/me/profile")
    assert r.status_code == 404 and r.headers["cache-control"] == "no-store"


def test_update_overwrites_own_profile(env):
    c = env["client"]("A")
    put(c, GOOD)
    assert put(c, {**GOOD, "phone": "010-1111-2222"}).json()["phone_masked"] == "010-****-2222"
    assert c.get("/me/profile", params={"view": "edit"}).json()["phone"] == "010-1111-2222"
    assert len(env["profiles"].rows) == 1


def test_me_profile_completed_false_then_true(env):
    c = env["client"]("A")
    assert c.get("/me").json()["profile_completed"] is False
    put(c, GOOD)
    me = c.get("/me").json()
    assert me == {"user_id": str(env["users"]["A"].user_id), "role": "user", "profile_completed": True}


def test_login_response_is_unchanged(env):
    c = TestClient(env["app"])
    r = c.post("/auth/login", json={"login_id": "A", "password": env["passwords"]["A"]}, headers=csrf(c))
    assert r.json() == {"user_id": str(env["users"]["A"].user_id), "role": "user"}


# ---- 사용자 분리 -------------------------------------------------------------
def test_a_saves_b_gets_404_and_never_a_values(env):
    a, b = env["client"]("A"), env["client"]("B")
    put(a, GOOD)
    r = b.get("/me/profile")
    assert r.status_code == 404
    edit = b.get("/me/profile", params={"view": "edit"})
    assert edit.status_code == 404
    for value in ("이영희", "5432", "해운대"):
        assert value not in r.text and value not in edit.text
    assert b.get("/me").json()["profile_completed"] is False


def test_body_user_id_is_ignored(env):
    a, b = env["client"]("A"), env["client"]("B")
    put(a, GOOD)
    a_id = str(env["users"]["A"].user_id)
    put(b, {**OTHER, "user_id": a_id})
    assert a.get("/me/profile").json()["name"] == "이영희"
    assert b.get("/me/profile").json()["name"] == "박관리"
    assert set(env["profiles"].rows) == {a_id, str(env["users"]["B"].user_id)}


def test_admin_sees_only_own(env):
    a, admin = env["client"]("A"), env["client"]("ADMIN")
    put(a, GOOD)
    assert admin.get("/me/profile").status_code == 404
    put(admin, OTHER)
    r = admin.get("/me/profile", params={"view": "edit"})
    assert r.json()["name"] == "박관리" and "이영희" not in r.text and "9876" not in r.text


def test_only_me_profile_route_mentions_profile(env):
    # FastAPI 버전에 따라 app.routes 모양이 달라서 OpenAPI 경로로 본다(test_auth_store.py 와 같은 방식)
    paths = env["app"].openapi()["paths"]
    assert {p for p in paths if "profile" in p} == {"/me/profile"}
    assert set(paths["/me/profile"]) == {"get", "put"}


def test_main_app_mounts_only_me_profile(monkeypatch):
    for key in ("PROVENA_ENV", "PROVENA_DEV_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv(KEY_ENV, "1:" + base64.b64encode(os.urandom(32)).decode())
    from backend.main import create_app

    app = create_app()
    paths = set(app.openapi()["paths"])
    assert {p for p in paths if "profile" in p} == {"/me/profile"}
    assert set(app.openapi()["paths"]["/me/profile"]) == {"get", "put"}


def test_main_app_refuses_start_without_key_outside_local(monkeypatch):
    from backend.services.profile_crypto import ProfileCryptoError

    for key in ("PROVENA_ENV", "PROVENA_DEV_MODE", KEY_ENV):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", secrets.token_urlsafe(48))
    from backend.main import create_app

    with pytest.raises(ProfileCryptoError):
        create_app()


# ---- 저장 형태·실패 ----------------------------------------------------------
def test_store_holds_ciphertext_only(env):
    put(env["client"]("A"), GOOD)
    blob = env["profiles"].raw_bytes()
    row = next(iter(env["profiles"].rows.values()))
    assert row.key_version == env["cipher"].current_version
    for text in ("이영희", "010-9876-5432", "01098765432", "98765432", "5432", "인프라", "해운대"):
        assert text.encode("utf-8") not in blob


def test_store_failure_is_503_without_details(env):
    c = env["client"]("A")
    env["profiles"].fail = True
    for r in (c.get("/me/profile"), put(c, GOOD), c.get("/me")):
        assert r.status_code == 503
        assert "test profile store failure" not in r.text and "RuntimeError" not in r.text


def test_tampered_row_is_503_and_not_leaked(env):
    c = env["client"]("A")
    put(c, GOOD)
    uid = str(env["users"]["A"].user_id)
    row = env["profiles"].rows[uid]
    env["profiles"].rows[uid] = replace(row, name_enc=row.name_enc[:-1] + bytes([row.name_enc[-1] ^ 1]))
    r = c.get("/me/profile")
    assert r.status_code == 503 and "5432" not in r.text


def test_row_moved_to_other_user_does_not_decrypt(env):
    a, b = env["client"]("A"), env["client"]("B")
    put(a, GOOD)
    a_row = env["profiles"].rows[str(env["users"]["A"].user_id)]
    b_id = str(env["users"]["B"].user_id)
    env["profiles"].rows[b_id] = replace(a_row, user_id=b_id)   # 암호문을 B 줄로 옮겨 붙임
    r = b.get("/me/profile")
    assert r.status_code == 503 and "이영희" not in r.text


def test_put_body_is_not_logged(env, caplog):
    c = env["client"]("A")
    caplog.set_level(logging.DEBUG)
    put(c, GOOD)
    put(c, {**GOOD, "name": "이영희1"})
    env["profiles"].fail = True
    put(c, GOOD)
    for value in GOOD.values():
        assert value not in caplog.text


def test_me_without_callback_has_no_profile_completed(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    password = secrets.token_urlsafe(18)
    user = AuthUser(uuid4(), "solo", hash_password(password), "user")
    store = Users([user])
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_test_auth_router(store=store, secret=secrets.token_urlsafe(48), cookie_secure=False))
    c = TestClient(app)
    login = c.post("/auth/login", json={"login_id": "solo", "password": password}, headers=csrf(c))
    assert login.json() == {"user_id": str(user.user_id), "role": "user"}
    assert c.get("/me").json() == {"user_id": str(user.user_id), "role": "user"}


def test_me_callback_bad_value_is_503(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    password = secrets.token_urlsafe(18)
    user = AuthUser(uuid4(), "solo", hash_password(password), "user")
    store = Users([user])
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_test_auth_router(store=store, secret=secrets.token_urlsafe(48), cookie_secure=False,
                                               profile_completed=lambda uid: "yes"))
    c = TestClient(app)
    login = c.post("/auth/login", json={"login_id": "solo", "password": password}, headers=csrf(c))
    assert login.json() == {"user_id": str(user.user_id), "role": "user"}   # 로그인 응답은 그대로
    assert c.get("/me").status_code == 503
