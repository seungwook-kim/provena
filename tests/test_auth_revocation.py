"""J-05 implementation tests; no Supabase connection or schema/data changes."""
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
from uuid import uuid4
import secrets

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth_test_support import MemoryRevocationStore, SqliteTestRevocations
from backend.auth import (
    AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, JWT_ALGORITHM,
    create_access_token, create_auth_router, create_current_user_dependency,
    create_require_admin_dependency, current_user_id, decode_access_token, hash_password,
    InvalidTokenError,
)


class UserStore:
    def __init__(self, user):
        self.user = user

    def get_by_login_id(self, login_id):
        return self.user if login_id == self.user.login_id else None

    def get_by_user_id(self, user_id):
        return self.user if str(user_id) == str(self.user.user_id) else None


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    secret = secrets.token_urlsafe(48)
    monkeypatch.setenv("AUTH_SECRET", secret)
    password = secrets.token_urlsafe(16)
    user = AuthUser(uuid4(), "revocation-user", hash_password(password), "admin")
    return UserStore(user), MemoryRevocationStore(), secret, password


def make_app(store, revoked, secret):
    app = FastAPI()
    app.state.token_revocation_store = revoked
    app.include_router(create_auth_router(store=store, secret=secret, revocation_store=revoked))
    current = create_current_user_dependency(store=store, secret=secret, revocation_store=revoked)
    admin = create_require_admin_dependency(store=store, secret=secret, revocation_store=revoked)

    @app.get("/id")
    def identity(user_id: str = Depends(current_user_id)):
        return {"user_id": user_id}

    @app.get("/current")
    def current_user(user: AuthUser = Depends(current)):
        return {"user_id": str(user.user_id)}

    @app.get("/admin")
    def administrator(user: AuthUser = Depends(admin)):
        return {"user_id": str(user.user_id)}

    return app


def put_token(client, token):
    client.cookies.set(AUTH_COOKIE_NAME, token, domain="testserver.local", path="/")


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def login(client, store, password):
    return client.post("/auth/login", json={"login_id": store.user.login_id, "password": password},
                       headers=csrf(client))


def test_same_user_logins_issue_unique_jti_and_logout_revokes_only_one_session(context):
    store, revoked, secret, password = context
    app = make_app(store, revoked, secret)
    with TestClient(app) as a, TestClient(app) as b:
        assert login(a, store, password).status_code == 200
        token = a.cookies.get(AUTH_COOKIE_NAME)
        assert login(b, store, password).status_code == 200
        first = decode_access_token(token, secret=secret)
        second = decode_access_token(b.cookies.get(AUTH_COOKIE_NAME), secret=secret)
        assert first["jti"] != second["jti"]
        assert a.get("/me").status_code == b.get("/me").status_code == 200
        assert a.post("/auth/logout", headers=csrf(a)).status_code == 204
        assert a.cookies.get(AUTH_COOKIE_NAME) is None
        assert a.cookies.get(CSRF_COOKIE_NAME) is None
        put_token(a, token)
        for path in ["/me", "/id", "/current", "/admin"]:
            assert a.get(path).status_code == 401
            assert b.get(path).status_code == 200
        assert revoked.revoked[first["jti"]] == datetime.fromtimestamp(first["exp"], timezone.utc)


def test_two_independent_apps_observe_shared_revocation(context):
    store, revoked, secret, _ = context
    token = create_access_token(store.user.user_id, "admin", secret=secret)
    with TestClient(make_app(store, revoked, secret)) as a, TestClient(make_app(store, revoked, secret)) as b:
        put_token(a, token)
        put_token(b, token)
        assert a.get("/me").status_code == b.get("/me").status_code == 200
        assert a.post("/auth/logout", headers=csrf(a)).status_code == 204
        assert b.get("/me").status_code == 401


@pytest.mark.parametrize("failure", ["unconfigured", "lookup_error", "invalid_result"])
def test_revocation_lookup_failure_denies_every_authentication_entry(context, failure):
    store, revoked, secret, password = context
    if failure == "unconfigured":
        revoked = None
    elif failure == "lookup_error":
        revoked.fail_read = True
    else:
        revoked.is_revoked = lambda jti: None
    with TestClient(make_app(store, revoked, secret)) as client:
        put_token(client, create_access_token(store.user.user_id, "admin", secret=secret))
        for path in ["/me", "/id", "/current", "/admin"]:
            assert client.get(path).status_code == 503
        response = client.post("/auth/logout", headers=csrf(client))
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        client.cookies.clear()
        assert login(client, store, password).status_code == 503
        assert client.cookies.get(AUTH_COOKIE_NAME) is None


@pytest.mark.parametrize("failure", ["write_error", "silent_write_loss", "read_after_write_error"])
def test_logout_never_claims_success_when_revocation_cannot_be_confirmed(context, failure):
    store, revoked, secret, _ = context
    if failure == "write_error":
        revoked.fail_write = True
    elif failure == "silent_write_loss":
        revoked.discard_write = True
    else:
        original = revoked.revoke
        def revoke_then_fail_read(jti, expires_at):
            original(jti, expires_at)
            revoked.fail_read = True
        revoked.revoke = revoke_then_fail_read
    with TestClient(make_app(store, revoked, secret)) as client:
        put_token(client, create_access_token(store.user.user_id, "admin", secret=secret))
        response = client.post("/auth/logout", headers=csrf(client))
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        assert client.cookies.get(AUTH_COOKIE_NAME) is not None
        if failure == "write_error":
            revoked.fail_write = False
        elif failure == "silent_write_loss":
            revoked.discard_write = False
        else:
            revoked.fail_read = False
            assert client.get("/me").status_code == 401
            return
        assert client.post("/auth/logout", headers=csrf(client)).status_code == 204


@pytest.mark.parametrize("variant", ["missing_jti", "empty_jti", "invalid_jti", "numeric_jti", "expired", "tampered"])
def test_legacy_malformed_expired_and_tampered_tokens_are_401(context, variant):
    store, revoked, secret, _ = context
    claims = {"user_id": str(store.user.user_id), "role": "admin",
              "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()), "jti": str(uuid4())}
    if variant == "missing_jti":
        claims.pop("jti")
    elif variant == "empty_jti":
        claims["jti"] = ""
    elif variant == "invalid_jti":
        claims["jti"] = "not-an-identifier"
    elif variant == "numeric_jti":
        claims["jti"] = 1
    elif variant == "expired":
        claims["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    token = jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)
    if variant == "tampered":
        token += "bad"
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=secret)
    with TestClient(make_app(store, revoked, secret)) as client:
        put_token(client, token)
        for path in ["/me", "/id", "/current", "/admin"]:
            assert client.get(path).status_code == 401
        assert client.post("/auth/logout", headers=csrf(client)).status_code == 401
    assert revoked.revoked == {}


def test_csrf_failure_cannot_revoke_a_valid_session(context):
    store, revoked, secret, _ = context
    with TestClient(make_app(store, revoked, secret)) as client:
        put_token(client, create_access_token(store.user.user_id, "admin", secret=secret))
        assert client.post("/auth/logout").status_code == 403
        assert client.get("/me").status_code == 200
        assert revoked.revoked == {}


def test_missing_token_remains_401_even_when_revocation_store_is_down(context):
    store, revoked, secret, _ = context
    revoked.fail_read = True
    with TestClient(make_app(store, revoked, secret)) as client:
        assert client.get("/me").status_code == 401


WORKER = '''
import json,sys,os
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth import AuthUser,AUTH_COOKIE_NAME,CSRF_COOKIE_NAME,create_auth_router
from auth_test_support import SqliteTestRevocations
try:
 d=json.load(sys.stdin)
 os.environ['PROVENA_ENV']='local';os.environ['PROVENA_DEV_MODE']='1'
 user=AuthUser(UUID(d['user_id']),'process-user','unused','user')
 class Store:
  def get_by_user_id(self,uid):return user if str(uid)==str(user.user_id) else None
  def get_by_login_id(self,login_id):return None
 app=FastAPI();app.include_router(create_auth_router(store=Store(),secret=d['secret'],revocation_store=SqliteTestRevocations(d['db'])))
 with TestClient(app) as client:
  client.cookies.set(AUTH_COOKIE_NAME,d['token'],domain='testserver.local',path='/')
  if d['action']=='logout':
   client.get('/auth/csrf')
   result=client.post('/auth/logout',headers={'X-CSRF-Token':client.cookies.get(CSRF_COOKIE_NAME)})
  else:result=client.get('/me')
  print(json.dumps({'status':result.status_code,'pid':os.getpid()}))
except Exception:
 print(json.dumps({'worker_failed':True}))
'''


def test_separate_server_processes_share_committed_revocation_via_test_sql_adapter(context, tmp_path):
    """Real process separation; SQLite test adapter, not a PostgreSQL validation."""
    store, _, secret, _ = context
    path = tmp_path / "revocation-contract.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE revoked(jti TEXT PRIMARY KEY, expires_at REAL NOT NULL)")
    token = create_access_token(store.user.user_id, "user", secret=secret)
    env = os.environ.copy()
    for key in ["DATABASE_URL", "PROVENA_TEST_DATABASE_URL", "TEST_DATABASE_URL"]:
        env.pop(key, None)
    env["PYTHONPATH"] = os.pathsep.join([os.getcwd(), os.path.join(os.getcwd(), "tests")])
    statuses, pids = [], []
    for action in ["read", "logout", "read"]:
        data = {"db": str(path), "user_id": str(store.user.user_id), "secret": secret, "token": token, "action": action}
        result = subprocess.run([sys.executable, "-B", "-c", WORKER], input=json.dumps(data),
                                capture_output=True, text=True, env=env, timeout=20)
        assert result.returncode == 0
        outcome = json.loads(result.stdout)
        assert not outcome.get("worker_failed", False)
        statuses.append(outcome["status"])
        pids.append(outcome["pid"])
    assert statuses == [200, 204, 401]
    assert len(set(pids)) == 3
    assert os.getpid() not in pids
