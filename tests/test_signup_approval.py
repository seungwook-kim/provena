from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthUser, CSRF_COOKIE_NAME, create_auth_router, hash_password
from auth_test_support import create_test_auth_router


class ApprovalStore:
    def __init__(self, status=None):
        self.user = AuthUser(uuid4(), 'new-user', hash_password('password-123'), 'user', True)
        self.status = status
        self.created = []

    def get_by_login_id(self, login_id):
        return self.user if login_id == self.user.login_id else None

    def get_by_user_id(self, user_id):
        return self.user if str(user_id) == str(self.user.user_id) else None

    def get_signup_status(self, user_id):
        return self.status

    def create_pending_user(self, login_id, password_hash):
        self.created.append((login_id, password_hash))
        return replace(self.user, login_id=login_id, password_hash=password_hash)


def client_for(store):
    app = FastAPI()
    app.include_router(create_test_auth_router(store=store, secret='x' * 32, cookie_secure=False))
    return TestClient(app)


def csrf(client):
    assert client.get('/auth/csrf').status_code == 204
    return {'X-CSRF-Token': client.cookies.get(CSRF_COOKIE_NAME)}


def test_signup_fails_closed_without_pending_store(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    class LegacyStore(ApprovalStore):
        create_pending_user = None

    client = client_for(LegacyStore())
    response = client.post('/auth/signup', json={'login_id': 'signup-user', 'password': 'password-123', 'password_confirmation': 'password-123'}, headers=csrf(client))
    assert response.status_code == 503


def test_pending_and_rejected_accounts_cannot_login_but_approved_can(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    for status, expected in [('pending', 403), ('rejected', 403), ('approved', 200)]:
        client = client_for(ApprovalStore(status))
        response = client.post('/auth/login', json={'login_id': 'new-user', 'password': 'password-123'}, headers=csrf(client))
        assert response.status_code == expected
