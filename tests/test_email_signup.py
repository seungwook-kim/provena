from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_api import create_admin_router
from backend.auth import CSRF_COOKIE_NAME, LoginRateLimiter, create_auth_router, hash_password
from backend.services.auth_store import MemoryAuthStore
from backend.services.email_sender import RecordingEmailSender
from auth_test_support import MemoryRevocationStore


def build(monkeypatch, *, rate_limiter=None):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MemoryAuthStore()
    owner = store.create_user("owner", hash_password("owner-password-1"), "admin")
    sender = RecordingEmailSender()
    secret = "e" * 32
    app = FastAPI()
    revocations = MemoryRevocationStore()
    app.include_router(create_auth_router(store=store, secret=secret, cookie_secure=False, revocation_store=revocations,
                                          email_sender=sender, rate_limiter=rate_limiter))
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


def test_duplicate_email_signup_does_not_claim_verified_application(monkeypatch):
    app, _store, _owner, sender, _secret = build(monkeypatch)
    client = TestClient(app)
    payload = {"login_id": "existing@example.com", "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}
    assert client.post("/auth/signup", json=payload, headers=csrf(client)).status_code == 201
    # 인증 전 신청은 덮어쓰기 대상이다(발송 간격 안이면 429, 상세는 test_signup_edges.py). 인증을 마친 신청은 409.
    assert client.post("/auth/signup", json=payload, headers=csrf(client)).status_code == 429
    verified = client.post("/auth/signup/verify", json={"login_id": "existing@example.com", "code": sender.deliveries[-1]["code"]}, headers=csrf(client))
    assert verified.status_code == 200

    duplicate = client.post("/auth/signup", json=payload, headers=csrf(client))

    assert duplicate.status_code == 409
    detail = duplicate.json()["detail"]
    assert "진행 중인 가입 신청" not in detail
    assert "이메일 인증 이어하기" in detail


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
    assert existing.status_code == 200
    assert existing.json() == {"status": "unavailable"}


def test_approved_signup_cannot_resend(monkeypatch):
    app, store, owner, sender, secret = build(monkeypatch)
    applicant = TestClient(app)
    email = "approved@example.com"
    assert applicant.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"}, headers=csrf(applicant)).status_code == 201
    assert applicant.post("/auth/signup/verify", json={"login_id": email, "code": sender.deliveries[-1]["code"]}, headers=csrf(applicant)).status_code == 200
    owner_client = TestClient(app)
    owner_client.cookies.set("provena_auth", __import__("backend.auth", fromlist=["create_access_token"]).create_access_token(owner.user_id, owner.role, secret=secret))
    request_id = store._signup_requests[email]["request_id"]
    assert owner_client.post(f"/admin/signup-requests/by-id/{request_id}/approve", headers=csrf(owner_client)).status_code == 200
    response = applicant.post("/auth/signup/resend", json={"login_id": email, "code": "000000"}, headers=csrf(applicant))
    assert response.status_code == 200
    assert response.json() == {"status": "unavailable"}


def test_rate_limited_pending_resend_is_indistinguishable(monkeypatch):
    app, _store, _owner, sender, _secret = build(monkeypatch)
    client = TestClient(app)
    email = "limited-resend@example.com"
    headers = csrf(client)
    assert client.post(
        "/auth/signup",
        json={"login_id": email, "password": "signup-pass-123", "password_confirmation": "signup-pass-123"},
        headers=headers,
    ).status_code == 201

    response = client.post(
        "/auth/signup/resend",
        json={"login_id": email, "code": "000000"},
        headers=csrf(client),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "unavailable"}
    assert len(sender.deliveries) == 1


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


def test_signup_ip_limit_applies_across_email_addresses_and_expires(monkeypatch):
    limiter = LoginRateLimiter(max_ip_attempts=2, window_seconds=60)
    app, _store, _owner, _sender, _secret = build(monkeypatch, rate_limiter=limiter)
    client = TestClient(app)
    now = 100.0
    monkeypatch.setattr("backend.auth.time.monotonic", lambda: now)

    def signup(email):
        return client.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123",
                                                  "password_confirmation": "signup-pass-123"}, headers=csrf(client))

    assert signup("first@example.com").status_code == 201
    assert signup("second@example.com").status_code == 201
    limited = signup("third@example.com")
    assert limited.status_code == 429
    assert "third@example.com" not in limited.text

    now = 160.0
    assert signup("after-window@example.com").status_code == 201


def test_resend_ip_limit_is_shared_with_signup_and_x_forwarded_for_cannot_bypass(monkeypatch):
    limiter = LoginRateLimiter(max_ip_attempts=2, window_seconds=60)
    app, _store, _owner, _sender, _secret = build(monkeypatch, rate_limiter=limiter)
    client = TestClient(app)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)

    headers = {**csrf(client), "X-Forwarded-For": "198.51.100.10"}
    for email in ("one@example.com", "two@example.com"):
        response = client.post("/auth/signup", json={"login_id": email, "password": "signup-pass-123",
                                                      "password_confirmation": "signup-pass-123"}, headers=headers)
        assert response.status_code == 201

    bypass = client.post("/auth/signup/resend", json={"login_id": "other@example.com", "code": "000000"},
                         headers={**csrf(client), "X-Forwarded-For": "203.0.113.99"})
    assert bypass.status_code == 429
