"""user_profiles 표(db/104_user_profiles.sql)를 진짜 Postgres로 시험한다. TEST_DATABASE_URL 이 있을 때만 돈다.

시험용 DB에만 쓴다(계정은 시험마다 무작위 아이디로 만들고 끝나면 지운다). db/101 → db/104 순서로 스키마가 있어야 한다
(없으면 ensure_schema 가 만든다). 예: TEST_DATABASE_URL=postgresql://app:<비밀번호>@127.0.0.1:54331/app_myinfo
"""
from auth_test_support import create_test_auth_router, revocations_for

import os
import secrets
import time

import pytest

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 Postgres에서만)")

GOOD = {"name": "최다은", "dept": "IT 운영팀", "phone": "010-4321-8765", "address": "부산광역시 남구 용소로 45"}


@pytest.fixture
def stores():
    import psycopg

    from backend.auth import hash_password
    from backend.services.auth_store import PostgresAuthStore
    from backend.services.profile_store import PostgresProfileStore

    auth = PostgresAuthStore(DB)
    auth.ensure_schema()
    profiles = PostgresProfileStore(DB)
    profiles.ensure_schema()
    profiles.ensure_schema()   # 여러 번 돌려도 된다
    made = []

    def make_user(role="user"):
        login_id = f"pytest-myinfo-{secrets.token_hex(6)}"
        made.append(login_id)
        return auth.upsert_user(login_id, hash_password(secrets.token_urlsafe(12)), role)

    yield auth, profiles, make_user
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM users WHERE login_id = ANY(%s)", (made,))


def _sealed(cipher, user_id, values):
    from backend.services.profile_store import EncryptedProfile

    enc = {k: cipher.encrypt(user_id, k, v) for k, v in values.items()}
    return EncryptedProfile(user_id, enc["name"], enc["dept"], enc["phone"], enc["address"], cipher.current_version)


def test_upsert_get_exists_roundtrip(stores):
    from backend.services.profile_crypto import ProfileCipher

    _, profiles, make_user = stores
    cipher = ProfileCipher({1: os.urandom(32)})
    uid = str(make_user().user_id)
    assert profiles.get(uid) is None and profiles.exists(uid) is False
    first = profiles.upsert(_sealed(cipher, uid, GOOD))
    assert profiles.exists(uid) is True and first.updated_at is not None
    got = profiles.get(uid)
    assert got.user_id == uid and got.key_version == 1
    assert {k: cipher.decrypt(uid, k, getattr(got, f"{k}_enc"), got.key_version) for k in GOOD} == GOOD
    time.sleep(0.01)
    second = profiles.upsert(_sealed(cipher, uid, {**GOOD, "phone": "010-1111-0000"}))
    assert second.updated_at >= first.updated_at
    assert cipher.decrypt(uid, "phone", profiles.get(uid).phone_enc, 1) == "010-1111-0000"


def test_db_row_has_no_plaintext(stores):
    import psycopg

    from backend.services.profile_crypto import ProfileCipher

    _, profiles, make_user = stores
    cipher = ProfileCipher({1: os.urandom(32)})
    uid = str(make_user().user_id)
    profiles.upsert(_sealed(cipher, uid, GOOD))
    with psycopg.connect(DB, autocommit=True) as conn:
        row = conn.execute("SELECT name_enc, dept_enc, phone_enc, address_enc FROM user_profiles WHERE user_id = %s",
                           (uid,)).fetchone()
        text_dump = conn.execute("SELECT t::text FROM user_profiles t WHERE user_id = %s", (uid,)).fetchone()[0]
    blob = b"".join(bytes(col) for col in row)
    for value in ("최다은", "010-4321-8765", "01043218765", "8765", "IT 운영", "용소로"):
        assert value.encode("utf-8") not in blob
        assert value not in text_dump


def test_user_delete_cascades(stores):
    import psycopg

    from backend.services.profile_crypto import ProfileCipher

    _, profiles, make_user = stores
    user = make_user()
    uid = str(user.user_id)
    profiles.upsert(_sealed(ProfileCipher({1: os.urandom(32)}), uid, GOOD))
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DELETE FROM users WHERE user_id = %s", (uid,))
    assert profiles.exists(uid) is False


def test_profile_for_unknown_user_is_rejected_by_fk(stores):
    import psycopg

    from backend.services.profile_crypto import ProfileCipher

    _, profiles, _ = stores
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        profiles.upsert(_sealed(ProfileCipher({1: os.urandom(32)}), "33333333-3333-4333-8333-333333333333", GOOD))


def test_api_end_to_end_with_postgres(stores, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.auth import CSRF_COOKIE_NAME, hash_password
    from backend.profile_api import create_profile_router
    from backend.services.profile_crypto import ProfileCipher

    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    auth, profiles, make_user = stores
    a, b = make_user(), make_user("admin")
    password = secrets.token_urlsafe(12)
    for user in (a, b):
        auth.upsert_user(user.login_id, hash_password(password), user.role)
    secret = secrets.token_urlsafe(48)
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(auth)
    app.include_router(create_test_auth_router(store=auth, secret=secret, cookie_secure=False, profile_completed=profiles.exists))
    app.include_router(create_profile_router(auth_store=auth, profile_store=profiles,
                                             cipher=ProfileCipher({1: os.urandom(32)}), secret=secret))

    def client(user):
        c = TestClient(app)
        c.get("/auth/csrf")
        headers = {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE_NAME)}
        assert c.post("/auth/login", json={"login_id": user.login_id, "password": password}, headers=headers).status_code == 200
        return c, headers

    ca, ha = client(a)
    cb, _ = client(b)
    assert ca.get("/me").json()["profile_completed"] is False
    assert ca.put("/me/profile", json=GOOD, headers=ha).json()["phone_masked"] == "010-****-8765"
    assert ca.get("/me").json()["profile_completed"] is True
    assert ca.get("/me/profile", params={"view": "edit"}).json()["phone"] == "010-4321-8765"
    other = cb.get("/me/profile")
    assert other.status_code == 404 and "최다은" not in other.text
