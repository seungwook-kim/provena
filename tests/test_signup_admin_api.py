from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_api import create_admin_router
from backend.auth import CSRF_COOKIE_NAME, create_access_token, create_auth_router, hash_password
from backend.services.auth_store import MemoryAuthStore
from auth_test_support import MemoryRevocationStore


OWNER = "owner"
PASSWORD = "owner-password-1"


def build_app(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MemoryAuthStore()
    owner = store.create_user(OWNER, hash_password(PASSWORD), "admin")
    store.create_pending_user("pending-api", hash_password("pending-password-1"))
    secret = "s" * 32
    app = FastAPI()
    revocations = MemoryRevocationStore()
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False, revocation_store=revocations))
    app.include_router(create_admin_router(store=store, owner_login_id=OWNER, secret=secret, revocation_store=revocations))
    return app, store, owner, secret


def client_for(app, user=None, secret=None):
    client = TestClient(app)
    if user is not None:
        client.cookies.set("provena_auth", create_access_token(user.user_id, user.role, secret=secret))
    return client


def csrf(client):
    response = client.get("/auth/csrf")
    assert response.status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def test_signup_request_api_authorization_and_review_lifecycle(monkeypatch):
    app, store, owner, secret = build_app(monkeypatch)
    owner_client = client_for(app, owner, secret)
    anonymous = client_for(app)
    member = store.create_user("member-api", hash_password("member-password-1"), "user")
    member_client = client_for(app, member, secret)
    non_owner_admin = store.create_user("other-admin-api", hash_password("admin-password-1"), "admin")
    non_owner_admin_client = client_for(app, non_owner_admin, secret)

    listed = owner_client.get("/admin/signup-requests")
    assert listed.status_code == 200
    request = listed.json()["requests"][0]
    assert request["login_id"] == "pending-api"
    assert request["requested_at"]
    assert request["status"] == "pending"
    assert "password_hash" not in request

    assert anonymous.get("/admin/signup-requests").status_code == 401
    assert member_client.get("/admin/signup-requests").status_code == 403
    assert non_owner_admin_client.get("/admin/signup-requests").status_code == 403

    assert owner_client.post("/admin/signup-requests/pending-api/approve").status_code == 403
    headers = csrf(owner_client)
    assert owner_client.post("/admin/signup-requests/pending-api/unknown", headers=headers).status_code == 422
    assert owner_client.post("/admin/signup-requests/missing/approve", headers=headers).status_code == 404

    approved = owner_client.post("/admin/signup-requests/pending-api/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json() == {"login_id": "pending-api", "status": "approved", "changed": True}
    assert store.get_by_login_id("pending-api") is not None
    request_row = store._signup_requests["pending-api"]
    assert request_row["reviewed_by"] == owner.user_id
    assert request_row["reviewed_at"] is not None
    reviewed_at = request_row["reviewed_at"]

    repeated = owner_client.post("/admin/signup-requests/pending-api/reject", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["changed"] is False
    assert request_row["reviewed_by"] == owner.user_id
    assert request_row["reviewed_at"] == reviewed_at

    login_client = client_for(app)
    logged_in = login_client.post(
        "/auth/login",
        json={"login_id": "pending-api", "password": "pending-password-1"},
        headers=csrf(login_client),
    )
    assert logged_in.status_code == 200


def test_signup_request_rejects_without_creating_user(monkeypatch):
    app, store, owner, secret = build_app(monkeypatch)
    client = client_for(app, owner, secret)
    response = client.post("/admin/signup-requests/pending-api/reject", headers=csrf(client))
    assert response.status_code == 200
    assert response.json() == {"login_id": "pending-api", "status": "rejected", "changed": True}
    assert store.get_by_login_id("pending-api") is None
    request_row = store._signup_requests["pending-api"]
    assert request_row["reviewed_by"] == owner.user_id
    assert request_row["reviewed_at"] is not None

    login_client = client_for(app)
    rejected_login = login_client.post(
        "/auth/login",
        json={"login_id": "pending-api", "password": "pending-password-1"},
        headers=csrf(login_client),
    )
    assert rejected_login.status_code == 403
