"""A/B authentication contract using an injected store; never creates database users."""
from auth_test_support import create_test_auth_router as create_auth_router
from auth_test_support import revocations_for

from dataclasses import replace
import secrets
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.auth import (
    AUTH_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    AuthUser,
    create_current_user_dependency,
    hash_password,
)


class TwoUserStore:
    def __init__(self, users):
        self.users = {str(user.user_id): user for user in users}

    def get_by_login_id(self, login_id):
        return next((user for user in self.users.values() if user.login_id == login_id), None)

    def get_by_user_id(self, user_id):
        return self.users.get(str(user_id))


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    passwords = {name: secrets.token_urlsafe(18) for name in ("A", "B")}
    users = {
        name: AuthUser(uuid4(), name, hash_password(passwords[name]), role)
        for name, role in (("A", "user"), ("B", "admin"))
    }
    store = TwoUserStore(users.values())
    secret = secrets.token_urlsafe(48)
    app = FastAPI()
    app.state.token_revocation_store = revocations_for(store)
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False))
    current = create_current_user_dependency(store=store, secret=secret)

    @app.post("/test/identity")
    def identity(user: AuthUser = Depends(current)):
        return {"user_id": str(user.user_id), "role": user.role}

    # Test-only integration consumer, not a new production admin endpoint.
    @app.get("/test/admin")
    def admin(user: AuthUser = Depends(current)):
        if user.role != "admin":
            raise HTTPException(status_code=403)
        return {"user_id": str(user.user_id)}

    with TestClient(app) as a, TestClient(app) as b:
        yield users, passwords, store, a, b


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def login(client, name, password):
    return client.post(
        "/auth/login",
        json={"login_id": name, "password": password},
        headers=csrf(client),
    )


def test_ab_have_distinct_uuid_and_independent_roles(accounts):
    users, passwords, _, a, b = accounts
    responses = [login(a, "A", passwords["A"]), login(b, "B", passwords["B"])]
    assert all(response.status_code == 200 for response in responses)
    ids = [UUID(response.json()["user_id"]) for response in responses]
    assert ids[0] != ids[1]
    for client, name in ((a, "A"), (b, "B")):
        assert client.get("/me").json() == {
            "user_id": str(users[name].user_id), "role": users[name].role
        }
    assert a.get("/test/admin").status_code == 403
    assert b.get("/test/admin").json() == {"user_id": str(users["B"].user_id)}


def test_ab_cookie_identity_cannot_be_replaced_by_body_or_query(accounts):
    users, passwords, _, a, b = accounts
    for client, own, other in ((a, "A", "B"), (b, "B", "A")):
        assert login(client, own, passwords[own]).status_code == 200
        response = client.post(
            "/test/identity", params={"user_id": str(users[other].user_id)},
            json={"user_id": str(users[other].user_id), "role": users[other].role},
        )
        assert response.status_code == 200
        assert response.json() == {"user_id": str(users[own].user_id), "role": users[own].role}


def test_failed_cross_account_login_does_not_switch_identity(accounts):
    users, passwords, _, a, _ = accounts
    assert login(a, "A", passwords["A"]).status_code == 200
    assert login(a, "B", passwords["A"]).status_code == 401
    assert a.get("/me").json() == {"user_id": str(users["A"].user_id), "role": "user"}


def test_logout_then_switch_to_b_without_logging_out_other_client(accounts):
    users, passwords, _, a, b = accounts
    assert login(a, "A", passwords["A"]).status_code == 200
    assert login(b, "B", passwords["B"]).status_code == 200
    assert a.post("/auth/logout", headers=csrf(a)).status_code == 204
    assert a.cookies.get(AUTH_COOKIE_NAME) is None
    assert a.get("/me").status_code == 401
    assert b.get("/me").json()["user_id"] == str(users["B"].user_id)
    assert login(a, "B", passwords["B"]).status_code == 200
    assert a.get("/me").json() == {"user_id": str(users["B"].user_id), "role": "admin"}


def test_b_role_and_active_status_are_read_from_store_not_old_jwt(accounts):
    users, passwords, store, a, b = accounts
    assert login(a, "A", passwords["A"]).status_code == 200
    assert login(b, "B", passwords["B"]).status_code == 200
    uid = str(users["B"].user_id)
    store.users[uid] = replace(users["B"], role="user")
    assert b.get("/test/admin").status_code == 403
    assert b.get("/me").json() == {"user_id": uid, "role": "user"}
    store.users[uid] = replace(store.users[uid], is_active=False)
    assert b.get("/me").status_code == 401
    assert a.get("/me").json()["user_id"] == str(users["A"].user_id)
