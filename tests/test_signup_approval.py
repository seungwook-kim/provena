from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import (
    AUTH_COOKIE_NAME,
    AuthUser,
    CSRF_COOKIE_NAME,
    SIGNUP_PENDING_MESSAGE,
    SIGNUP_REJECTED_MESSAGE,
    create_auth_router,
    hash_password,
)
from backend.services.auth_store import MemoryAuthStore
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


def test_memory_pending_and_rejected_logins_verify_password_before_status_disclosure(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    store = MemoryAuthStore()
    password = 'password-123'
    store.create_pending_user('pending-user', hash_password(password))
    store.create_pending_user('rejected-user', hash_password(password))
    assert store.review_signup_request('rejected-user', 'reject', uuid4()) == 'changed'
    client = client_for(store)

    missing = client.post('/auth/login', json={'login_id': 'missing-user', 'password': password}, headers=csrf(client))
    pending_wrong = client.post('/auth/login', json={'login_id': 'pending-user', 'password': 'wrong-password'}, headers=csrf(client))
    rejected_wrong = client.post('/auth/login', json={'login_id': 'rejected-user', 'password': 'wrong-password'}, headers=csrf(client))
    assert missing.status_code == pending_wrong.status_code == rejected_wrong.status_code == 401
    assert missing.json()['detail'] == pending_wrong.json()['detail'] == rejected_wrong.json()['detail']

    pending = client.post('/auth/login', json={'login_id': 'pending-user', 'password': password}, headers=csrf(client))
    rejected = client.post('/auth/login', json={'login_id': 'rejected-user', 'password': password}, headers=csrf(client))
    assert pending.status_code == 403 and pending.json()['detail'] == SIGNUP_PENDING_MESSAGE
    assert rejected.status_code == 403 and rejected.json()['detail'] == SIGNUP_REJECTED_MESSAGE
    assert AUTH_COOKIE_NAME not in pending.headers.get('set-cookie', '')
    assert AUTH_COOKIE_NAME not in rejected.headers.get('set-cookie', '')
    assert client.cookies.get(AUTH_COOKIE_NAME) is None


def test_memory_existing_and_approved_users_use_normal_login_path(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    store = MemoryAuthStore()
    password = 'password-123'
    existing_user = store.create_user('existing-user', hash_password(password), 'user')
    existing_admin = store.create_user('existing-admin', hash_password(password), 'admin')
    inactive_user = store.create_user('inactive-user', hash_password(password), 'user')
    store._users[inactive_user.login_id] = replace(inactive_user, is_active=False)
    assert store.get_signup_status(existing_user.user_id) is None
    assert store.get_signup_status(existing_admin.user_id) is None
    store.create_pending_user('approved-user', hash_password(password))
    assert store.review_signup_request('approved-user', 'approve', uuid4()) == 'changed'
    approved_user = store.get_by_login_id('approved-user')
    assert approved_user is not None
    assert store.get_signup_status(approved_user.user_id) == 'approved'
    assert store.get_signup_by_login_id('approved-user') == ('approved', approved_user.password_hash)

    client = client_for(store)
    for login_id, user in [('existing-user', existing_user), ('existing-admin', existing_admin), ('approved-user', approved_user)]:
        response = client.post('/auth/login', json={'login_id': login_id, 'password': password}, headers=csrf(client))
        assert response.status_code == 200
        assert response.json() == {'user_id': str(user.user_id), 'role': user.role}
        assert AUTH_COOKIE_NAME in response.headers.get('set-cookie', '')

    wrong_password = client.post('/auth/login', json={'login_id': 'existing-user', 'password': 'wrong-password'}, headers=csrf(client))
    assert wrong_password.status_code == 401
    inactive = client.post('/auth/login', json={'login_id': 'inactive-user', 'password': password}, headers=csrf(client))
    assert inactive.status_code == 401


class _SignupTableMissing(Exception):
    sqlstate = "42P01"

    def __init__(self, table_name=None, message=None):
        self.diag = type('Diag', (), {'table_name': table_name})() if table_name is not None else None
        super().__init__(message or (f'relation "{table_name}" does not exist' if table_name else "undefined table"))


class _SignupStoreError(Exception):
    sqlstate = "08006"


class _ExistingUserWithoutSignupTable(ApprovalStore):
    def get_signup_status(self, user_id):
        raise _SignupTableMissing("signup_requests")


class _ExistingUserWithOtherTableMissing(ApprovalStore):
    def get_signup_status(self, user_id):
        raise _SignupTableMissing("other_table")


class _ExistingUserWithSignupMessageOnly(ApprovalStore):
    def get_signup_status(self, user_id):
        raise _SignupTableMissing(message='relation "signup_requests" does not exist\nLINE 1: SELECT status FROM signup_requests WHERE user_id = $1\n                           ^')


class _UnknownSignupStoreError(ApprovalStore):
    def get_signup_by_login_id(self, login_id):
        raise _SignupStoreError()


def test_existing_account_login_survives_missing_signup_table(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    client = client_for(_ExistingUserWithoutSignupTable())
    response = client.post('/auth/login', json={'login_id': 'new-user', 'password': 'password-123'}, headers=csrf(client))
    assert response.status_code == 200


def test_unknown_signup_table_error_is_not_hidden(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    client = client_for(_UnknownSignupStoreError())
    response = client.post('/auth/login', json={'login_id': 'missing-user', 'password': 'password-123'}, headers=csrf(client))
    assert response.status_code == 503


def test_other_missing_table_error_is_not_treated_as_missing_signup_table(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    client = client_for(_ExistingUserWithOtherTableMissing())
    response = client.post('/auth/login', json={'login_id': 'new-user', 'password': 'password-123'}, headers=csrf(client))
    assert response.status_code == 503


def test_signup_table_message_fallback_is_strict(monkeypatch):
    monkeypatch.setenv('PROVENA_ENV', 'local')
    monkeypatch.setenv('PROVENA_DEV_MODE', '1')
    client = client_for(_ExistingUserWithSignupMessageOnly())
    response = client.post('/auth/login', json={'login_id': 'new-user', 'password': 'password-123'}, headers=csrf(client))
    assert response.status_code == 200
