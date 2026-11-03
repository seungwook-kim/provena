"""Reusable auth guards and logout replay characterization; no real database."""
from auth_test_support import create_test_auth_router as create_auth_router
from auth_test_support import revocations_for

from dataclasses import replace
from datetime import timedelta
import secrets
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.auth import (
    AUTH_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    AuthUser,
    create_access_token,
    create_current_user_dependency,
    create_require_admin_dependency,
    require_csrf,
)


class GuardStore:
    def __init__(self, users):
        self.users = {str(user.user_id): user for user in users}
        self.lookups = 0
        self.unavailable = False

    def get_by_login_id(self, login_id):
        return next((user for user in self.users.values() if user.login_id == login_id), None)

    def get_by_user_id(self, user_id):
        self.lookups += 1
        if self.unavailable:
            raise RuntimeError("store unavailable")
        return self.users.get(str(user_id))


@pytest.fixture
def guards(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    secret = secrets.token_urlsafe(48)
    member = AuthUser(uuid4(), "member", "unused", "user")
    admin = AuthUser(uuid4(), "admin", "unused", "admin")
    store = GuardStore([member, admin])
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False))
    admin_guard = create_require_admin_dependency(store=store, secret=secret)
    current = create_current_user_dependency(store=store, secret=secret)
    effects = []

    @app.get("/admin/read")
    def admin_read(user: AuthUser = Depends(admin_guard)):
        return {"user_id": str(user.user_id), "role": user.role}

    # Production route wiring belongs to main.py's owner. These consumers exist
    # only in tests. The order gives authentication priority over CSRF errors.
    @app.api_route(
        "/admin/action", methods=["POST", "PATCH", "DELETE"],
        dependencies=[Depends(admin_guard), Depends(require_csrf)],
    )
    def admin_action(user: AuthUser = Depends(admin_guard)):
        effects.append(str(user.user_id))
        return {"user_id": str(user.user_id)}

    @app.post("/member/action", dependencies=[Depends(current), Depends(require_csrf)])
    def member_action(user: AuthUser = Depends(current)):
        effects.append(str(user.user_id))
        return {"user_id": str(user.user_id)}

    @app.post("/csrf-only", dependencies=[Depends(require_csrf)])
    def csrf_only():
        return {"csrf_checked": True}

    with TestClient(app) as client:
        yield client, store, secret, member, admin, effects


def authenticate(client, secret, user, **kwargs):
    client.cookies.set(
        AUTH_COOKIE_NAME,
        create_access_token(user.user_id, user.role, secret=secret, **kwargs),
        domain="testserver.local", path="/",
    )


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


@pytest.mark.parametrize("credential", ["missing", "tampered", "expired"])
def test_admin_guard_rejects_invalid_authentication_before_store_lookup(guards, credential):
    client, store, secret, _, admin, effects = guards
    if credential == "tampered":
        client.cookies.set(AUTH_COOKIE_NAME, create_access_token(admin.user_id, "admin", secret=secret) + "bad", domain="testserver.local", path="/")
    elif credential == "expired":
        authenticate(client, secret, admin, expires_delta=timedelta(seconds=-1))
    assert client.get("/admin/read").status_code == 401
    assert client.post("/admin/action").status_code == 401
    assert store.lookups == 0
    assert effects == []


def test_active_member_is_403_while_admin_is_allowed_with_injected_secret(guards):
    client, _, secret, member, admin, effects = guards
    authenticate(client, secret, member)
    assert client.get("/admin/read").status_code == 403
    assert client.post("/admin/action", headers=csrf(client)).status_code == 403
    assert effects == []
    authenticate(client, secret, admin)
    response = client.get("/admin/read")
    assert response.status_code == 200
    assert response.json() == {"user_id": str(admin.user_id), "role": "admin"}


@pytest.mark.parametrize("new_role, expected", [("user", 403), ("admin", 200)])
def test_admin_guard_uses_latest_store_role_not_the_jwt_role(guards, new_role, expected):
    client, store, secret, member, admin, _ = guards
    original = admin if new_role == "user" else member
    authenticate(client, secret, original)
    store.users[str(original.user_id)] = replace(original, role=new_role)
    assert client.get("/admin/read").status_code == expected


@pytest.mark.parametrize("state", ["inactive", "deleted", "invalid_role"])
def test_admin_guard_rejects_no_longer_valid_users(guards, state):
    client, store, secret, _, admin, _ = guards
    authenticate(client, secret, admin)
    uid = str(admin.user_id)
    if state == "deleted":
        store.users.pop(uid)
    elif state == "inactive":
        store.users[uid] = replace(admin, is_active=False)
    else:
        store.users[uid] = replace(admin, role="owner")
    assert client.get("/admin/read").status_code == 401


def test_admin_guard_fails_closed_when_store_is_unavailable(guards):
    client, store, secret, _, admin, effects = guards
    authenticate(client, secret, admin)
    store.unavailable = True
    assert client.get("/admin/read").status_code == 503
    assert client.post("/admin/action", headers=csrf(client)).status_code == 503
    assert effects == []


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("failure", ["missing_cookie", "missing_header", "mismatch", "empty"])
def test_csrf_dependency_blocks_admin_mutations_without_side_effects(guards, method, failure):
    client, _, secret, _, admin, effects = guards
    authenticate(client, secret, admin)
    headers = csrf(client)
    if failure == "missing_cookie":
        client.cookies.clear()
        authenticate(client, secret, admin)
    elif failure == "missing_header":
        headers = {}
    elif failure == "mismatch":
        headers = {"X-CSRF-Token": "different-token"}
    else:
        client.cookies.clear()
        authenticate(client, secret, admin)
        client.cookies.set(CSRF_COOKIE_NAME, "", domain="testserver.local", path="/")
        headers = {"X-CSRF-Token": ""}
    response = client.request(method, "/admin/action", headers=headers)
    assert response.status_code == 403
    assert effects == []


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_valid_admin_and_csrf_allow_mutation_and_auth_lookup_is_cached_per_request(guards, method):
    client, store, secret, _, admin, effects = guards
    authenticate(client, secret, admin)
    response = client.request(method, "/admin/action", headers=csrf(client))
    assert response.status_code == 200
    assert effects == [str(admin.user_id)]
    assert store.lookups == 1


def test_csrf_is_reusable_for_members_but_does_not_grant_authentication(guards):
    client, _, secret, member, _, effects = guards
    headers = csrf(client)
    assert client.post("/csrf-only", headers=headers).status_code == 200
    assert client.post("/member/action", headers=headers).status_code == 401
    authenticate(client, secret, member)
    assert client.post("/member/action").status_code == 403
    assert client.post("/member/action", headers=headers).status_code == 200
    assert effects == [str(member.user_id)]


def test_request_body_and_query_cannot_elevate_a_member(guards):
    client, _, secret, member, admin, effects = guards
    authenticate(client, secret, member)
    response = client.post(
        "/admin/action", headers=csrf(client),
        params={"role": "admin", "user_id": str(admin.user_id)},
        json={"role": "admin", "user_id": str(admin.user_id), "groups": ["admin"]},
    )
    assert response.status_code == 403
    assert effects == []


def test_logout_revokes_copied_jwt_for_user_and_admin_guards(guards):
    """A copied token is rejected after confirmed server-side revocation."""
    client, _, secret, _, admin, _ = guards
    token = create_access_token(admin.user_id, admin.role, secret=secret)
    client.cookies.set(AUTH_COOKIE_NAME, token, domain="testserver.local", path="/")
    assert client.post("/auth/logout", headers=csrf(client)).status_code == 204
    assert not client.cookies.get(AUTH_COOKIE_NAME)
    assert not client.cookies.get(CSRF_COOKIE_NAME)
    assert client.get("/me").status_code == 401
    # A copy is rejected by both user and admin verification.
    client.cookies.set(AUTH_COOKIE_NAME, token, domain="testserver.local", path="/")
    assert client.get("/me").status_code == 401
    assert client.get("/admin/read").status_code == 401
