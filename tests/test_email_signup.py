from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_api import create_admin_router
from backend.auth import CSRF_COOKIE_NAME, create_auth_router, hash_password
from backend.services.auth_store import MemoryAuthStore
from backend.services.email_sender import RecordingEmailSender
from auth_test_support import MemoryRevocationStore


def build(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MemoryAuthStore()
    owner = store.create_user("owner", hash_password("owner-password-1"), "admin")
    sender = RecordingEmailSender()
    secret = "e" * 32
    app = FastAPI()
    revocations = MemoryRevocationStore()
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False, revocation_store=revocations, email_sender=sender))
    app.include_router(create_admin_router(store=store, owner_login_id=owner.login_id, secret=secret, revocation_store=revocations))
    return app, store, owner, sender, secret


def csrf(client):
    assert client.get("/auth/csrf").status_code == 204
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def test_email_signup_verification_and_approval(monkeypatch):
    app, store, owner, sender, secret = build(monkeypatch)
    applicant = TestClient(app)
    email = "  New.User@Example.COM "
    response = applicant.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=csrf(applicant))
    assert response.status_code == 201
    assert sender.deliveries[0]["email"] == "new.user@example.com"
    assert store.get_by_login_id("new.user@example.com") is None

    owner_client = TestClient(app)
    owner_client.cookies.set("provena_auth", __import__("backend.auth", fromlist=["create_access_token"]).create_access_token(owner.user_id, owner.role, secret=secret))
    denied = owner_client.post("/admin/signup-requests/new.user@example.com/approve", headers=csrf(owner_client))
    assert denied.status_code == 409
    verified = applicant.post("/auth/signup/verify", json={"login_id": email, "code": sender.deliveries[0]["code"]}, headers=csrf(applicant))
    assert verified.status_code == 200
    approved = owner_client.post("/admin/signup-requests/NEW.USER%40EXAMPLE.COM/approve", headers=csrf(owner_client))
    assert approved.status_code == 200
    login = applicant.post("/auth/login", json={"login_id": "NEW.USER@example.com", "password": "signup-pass-123"}, headers=csrf(applicant))
    assert login.status_code == 200


def test_code_is_single_use_and_attempt_limited(monkeypatch):
    app, store, _owner, sender, _secret = build(monkeypatch)
    client = TestClient(app)
    email = "limit@example.com"
    assert client.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=csrf(client)).status_code == 201
    for _ in range(5):
        response = client.post("/auth/signup/verify", json={"login_id": email, "code": "000000"}, headers=csrf(client))
    assert response.status_code == 400
    assert client.post("/auth/signup/verify", json={"login_id": email, "code": sender.deliveries[0]["code"]}, headers=csrf(client)).status_code == 429


def test_existing_non_email_signup_remains_compatible(monkeypatch):
    app, store, _owner, sender, _secret = build(monkeypatch)
    client = TestClient(app)
    response = client.post("/auth/signup", json={"login_id": "legacy-new-id", "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=csrf(client))
    assert response.status_code == 201
    assert sender.deliveries == []
    assert store.review_signup_request("legacy-new-id", "approve", uuid4()) == "changed"


def test_unknown_resend_is_indistinguishable_and_verified_code_material_is_cleared(monkeypatch):
    app, store, _owner, sender, _secret = build(monkeypatch)
    client = TestClient(app)
    headers = csrf(client)
    email = "privacy@example.com"
    assert client.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=headers).status_code == 201
    code = sender.deliveries[-1]["code"]
    assert client.post("/auth/signup/verify", json={"login_id": email, "code": code}, headers=csrf(client)).status_code == 200
    assert store._signup_requests[email]["verification_code_hash"] is None
    assert store._signup_requests[email]["verification_expires_at"] is None

    unknown = client.post("/auth/signup/resend", json={"login_id": "unknown@example.com", "code": "000000"}, headers=csrf(client))
    existing = client.post("/auth/signup/resend", json={"login_id": email, "code": "000000"}, headers=csrf(client))
    assert unknown.status_code == 200
    assert unknown.json() == {"status": "unavailable"}
    assert existing.status_code == 429


def test_request_id_approval_does_not_put_email_in_response_or_url(monkeypatch):
    app, store, owner, sender, secret = build(monkeypatch)
    applicant = TestClient(app)
    email = "request-id@example.com"
    assert applicant.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=csrf(applicant)).status_code == 201
    assert applicant.post("/auth/signup/verify", json={"login_id": email, "code": sender.deliveries[-1]["code"]}, headers=csrf(applicant)).status_code == 200
    owner_client = TestClient(app)
    owner_client.cookies.set("provena_auth", __import__("backend.auth", fromlist=["create_access_token"]).create_access_token(owner.user_id, owner.role, secret=secret))
    request_id = store._signup_requests[email]["request_id"]
    response = owner_client.post(f"/admin/signup-requests/by-id/{request_id}/approve", headers=csrf(owner_client))
    assert response.status_code == 200
    assert response.json() == {"request_id": request_id, "status": "approved", "changed": True}
