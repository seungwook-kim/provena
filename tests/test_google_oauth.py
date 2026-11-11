from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.auth as auth_module
from backend.auth import (
    AUTH_COOKIE_NAME,
    GOOGLE_OAUTH_REQUEST_COOKIE_NAME,
    AuthUser,
    GoogleIdentity,
    GoogleOAuthConfig,
    GoogleOAuthError,
    GoogleJwkIdTokenVerifier,
    create_auth_router,
)


class MemoryRevocations:
    def is_revoked(self, _jti: str) -> bool:
        return False

    def revoke(self, _jti: str, _expires_at: datetime) -> None:
        return None


class MockGoogleStore:
    def __init__(self) -> None:
        self.user = AuthUser(uuid4(), "google-test-user", "unused", "user")
        self.calls: list[tuple[str, str, str]] = []

    def get_by_login_id(self, _login_id: str):
        return None

    def get_by_user_id(self, user_id: str):
        return self.user if str(self.user.user_id) == str(user_id) else None

    def get_or_create_google_user(self, provider: str, subject: str, email: str) -> AuthUser:
        self.calls.append((provider, subject, email))
        return self.user


class ProvisioningGoogleStore:
    """Storage-contract double: only provider/sub may select an OAuth user."""

    def __init__(self) -> None:
        self.users: dict[tuple[str, str], AuthUser] = {}
        self.create_count = 0

    def get_by_login_id(self, _login_id: str):
        return None

    def get_by_user_id(self, user_id: str):
        return next(
            (user for user in self.users.values() if str(user.user_id) == str(user_id)),
            None,
        )

    def get_or_create_google_user(self, provider: str, subject: str, email: str) -> AuthUser:
        assert provider == "google"
        assert subject and email
        key = (provider, subject)
        if key not in self.users:
            self.create_count += 1
            self.users[key] = AuthUser(
                uuid4(), f"google-{self.create_count}", "unused", "user"
            )
        return self.users[key]


class MockExchanger:
    def __init__(self) -> None:
        self.code_verifier = ""

    def exchange_code(self, *, code: str, config: GoogleOAuthConfig, code_verifier: str) -> str:
        assert code == "google-code"
        assert config.client_id == "test-client-id"
        self.code_verifier = code_verifier
        return "provider-id-token"


class MockVerifier:
    def __init__(self, subject: str = "google-subject-123", email: str = "verified@example.test") -> None:
        self.subject = subject
        self.email = email
        self.nonce = ""

    def verify(self, *, id_token: str, config: GoogleOAuthConfig, nonce: str) -> GoogleIdentity:
        assert id_token == "provider-id-token"
        assert config.client_id == "test-client-id"
        self.nonce = nonce
        return GoogleIdentity(subject=self.subject, email=self.email)


class RejectingVerifier:
    def verify(self, **_kwargs) -> GoogleIdentity:
        raise GoogleOAuthError("invalid test token")


@pytest.fixture
def oauth_context(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = MockGoogleStore()
    exchanger = MockExchanger()
    verifier = MockVerifier()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig(
                client_id="test-client-id",
                client_secret="test-client-secret",
                redirect_uri="https://example.test/auth/google/callback",
            ),
            google_token_exchanger=exchanger,
            google_id_token_verifier=verifier,
        )
    )
    return TestClient(app), store, exchanger, verifier


def _start(client: TestClient):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    return response


def test_google_start_uses_state_nonce_and_s256_pkce(oauth_context):
    client, _store, _exchanger, _verifier = oauth_context
    response = _start(client)
    target = urlsplit(response.headers["location"])
    params = parse_qs(target.query)
    assert target.scheme == "https"
    assert target.netloc == "accounts.google.com"
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email"]
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["state"][0]) >= 32
    assert len(params["nonce"][0]) >= 32
    assert GOOGLE_OAUTH_REQUEST_COOKIE_NAME in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_google_callback_issues_existing_jwt_cookie_for_verified_subject(oauth_context):
    client, store, exchanger, verifier = oauth_context
    start = _start(client)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.cookies.get(AUTH_COOKIE_NAME)
    assert client.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME) is None
    assert store.calls == [("google", "google-subject-123", "verified@example.test")]
    assert exchanger.code_verifier
    assert verifier.nonce
    assert client.get("/me").json() == {"user_id": str(store.user.user_id), "role": "user", "login_id": store.user.login_id}


def test_google_first_login_provisions_user_and_relogin_reuses_provider_subject(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    store = ProvisioningGoogleStore()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig(
                "test-client-id", "test-client-secret", "https://example.test/callback"
            ),
            google_token_exchanger=MockExchanger(),
            google_id_token_verifier=MockVerifier("stable-google-subject"),
        )
    )

    with TestClient(app) as first, TestClient(app) as returning:
        first_state = parse_qs(urlsplit(_start(first).headers["location"]).query)["state"][0]
        first_response = first.get(
            "/auth/google/callback",
            params={"code": "google-code", "state": first_state},
            follow_redirects=False,
        )
        assert first_response.status_code == 303
        first_user = first.get("/me").json()

        returning_state = parse_qs(urlsplit(_start(returning).headers["location"]).query)["state"][0]
        returning_response = returning.get(
            "/auth/google/callback",
            params={"code": "google-code", "state": returning_state},
            follow_redirects=False,
        )
        assert returning_response.status_code == 303
        assert returning.get("/me").json() == first_user

    assert store.create_count == 1
    assert first_user["role"] == "user"


def test_google_callback_rejects_mismatched_state_without_creating_a_user(oauth_context):
    client, store, _exchanger, _verifier = oauth_context
    _start(client)
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": "wrong-state"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?oauth_error=google_login_failed"
    assert store.calls == []
    assert client.cookies.get(AUTH_COOKIE_NAME) is None
    assert client.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME) is None


def test_google_callback_rejects_token_verification_failure(oauth_context):
    client, store, _exchanger, _verifier = oauth_context
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig("test-client-id", "test-client-secret", "https://example.test/auth/google/callback"),
            google_token_exchanger=MockExchanger(),
            google_id_token_verifier=RejectingVerifier(),
        )
    )
    client = TestClient(app)
    start = _start(client)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": state}, follow_redirects=False
    )
    assert response.headers["location"] == "/login?oauth_error=google_login_failed"
    assert store.calls == []
    assert client.cookies.get(AUTH_COOKIE_NAME) is None


def test_google_start_fails_closed_without_an_oauth_store(monkeypatch):
    class PasswordOnlyStore:
        def get_by_login_id(self, _login_id: str):
            return None

        def get_by_user_id(self, _user_id: str):
            return None

    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=PasswordOnlyStore(),
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_config=GoogleOAuthConfig("id", "secret", "https://example.test/callback"),
        )
    )
    response = TestClient(app).get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login?oauth_error=google_unavailable"


def test_google_start_fails_closed_without_rs256_verification_support(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    monkeypatch.setattr(auth_module.jwt.algorithms, "has_crypto", False)
    store = MockGoogleStore()
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_oauth_store=store,
            google_config=GoogleOAuthConfig("id", "secret", "https://example.test/callback"),
        )
    )
    response = TestClient(app).get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login?oauth_error=google_unavailable"


def test_google_id_token_verifier_rejects_unverified_email(monkeypatch):
    class SigningKey:
        key = "unused"

    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "google-subject", "nonce": "nonce", "email_verified": False,
            "exp": 2_000_000_000, "iss": "https://accounts.google.com", "aud": "client",
        },
    )
    verifier = GoogleJwkIdTokenVerifier(jwks_client=Jwks())
    with pytest.raises(GoogleOAuthError):
        verifier.verify(
            id_token="ignored", config=GoogleOAuthConfig("client", "secret", "https://example.test/callback"), nonce="nonce"
        )


def test_google_id_token_verifier_accepts_verified_subject(monkeypatch):
    class SigningKey:
        key = "unused"

    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "google-subject", "nonce": "nonce", "email": "verified@example.test",
            "email_verified": True, "exp": 2_000_000_000,
            "iss": "https://accounts.google.com", "aud": "client",
        },
    )
    identity = GoogleJwkIdTokenVerifier(jwks_client=Jwks()).verify(
        id_token="ignored", config=GoogleOAuthConfig("client", "secret", "https://example.test/callback"), nonce="nonce"
    )
    assert identity == GoogleIdentity(subject="google-subject", email="verified@example.test")


# ---- 실제 저장소(MemoryAuthStore) 와 맞물린 Google 연결·가입 시험 ----
from datetime import timedelta, timezone  # noqa: E402

from backend.auth import GoogleAccountLinkError, GoogleSignupPendingError, GoogleSignupRejectedError, hash_password  # noqa: E402
from backend.services.auth_store import MemoryAuthStore  # noqa: E402

PENDING_PATH = "/login?oauth_error=google_signup_pending"
REJECTED_PATH = "/login?oauth_error=google_signup_rejected"
FAILED_PATH = "/login?oauth_error=google_login_failed"
EMAIL = "member@example.test"


def _google_app(store, subject: str = "sub-1", email: str = EMAIL):
    app = FastAPI()
    app.include_router(
        create_auth_router(
            store=store,
            secret="x" * 32,
            cookie_secure=False,
            revocation_store=MemoryRevocations(),
            google_config=GoogleOAuthConfig("test-client-id", "test-client-secret", "https://example.test/cb"),
            google_token_exchanger=MockExchanger(),
            google_id_token_verifier=MockVerifier(subject, email),
        )
    )
    return app


def _google_login(app) -> tuple[TestClient, object]:
    client = TestClient(app)
    state = parse_qs(urlsplit(_start(client).headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/google/callback", params={"code": "google-code", "state": state}, follow_redirects=False
    )
    return client, response


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")


def _reviewer(store):
    if store.get_by_login_id("reviewer") is not None:
        return store.get_by_login_id("reviewer")
    return store.create_user("reviewer", hash_password("review-pass-123"), "admin")


def _approved_email_account(store, email: str = EMAIL, *, verify: bool = True):
    """이메일 가입 -> 인증 -> 승인까지 거친 계정. 공개 저장소 메서드만 쓴다."""
    store.create_pending_user(email, hash_password("member-pass-123"), email_verification_required=True)
    if verify:
        now = datetime.now(timezone.utc)
        store.issue_verification(email, "h", "123456", now, now + timedelta(minutes=5), 5, 0, lambda _code: None)
        assert store.verify_signup_code(email, "h", now, 5) == "verified"
    result = store.review_signup_request(email, "approve", _reviewer(store).user_id)
    return result, store.get_by_login_id(email)


def test_google_email_links_to_existing_verified_account(local_env):
    store = MemoryAuthStore()
    result, user = _approved_email_account(store)
    assert result == "changed"
    client, response = _google_login(_google_app(store))
    assert response.headers["location"] == "/"
    assert client.get("/me").json() == {"user_id": str(user.user_id), "role": "user", "login_id": user.login_id}
    assert [r.status for r in store.list_signup_requests()] == ["approved"]  # 새 신청이 생기지 않았다


def test_google_link_keeps_admin_role_and_does_not_mint_admins(local_env):
    store = MemoryAuthStore()
    _result, boss = _approved_email_account(store, "boss@example.test")
    store._users["boss@example.test"] = AuthUser(boss.user_id, boss.login_id, boss.password_hash, "admin", True)  # 운영자가 올린 상태
    client, response = _google_login(_google_app(store, "boss-sub", "boss@example.test"))
    assert response.headers["location"] == "/"
    assert client.get("/me").json() == {"user_id": str(boss.user_id), "role": "admin", "login_id": "boss@example.test"}
    assert store.get_by_login_id("boss@example.test").role == "admin"
    # 계정이 없는 이메일은 구글로 와도 admin 이 되지 않고 승인 대기 신청만 생긴다
    client2, response2 = _google_login(_google_app(store, "other-sub", "new-admin@example.test"))
    assert response2.headers["location"] == PENDING_PATH and client2.cookies.get(AUTH_COOKIE_NAME) is None


def test_google_email_match_ignores_case_and_spaces(local_env):
    store = MemoryAuthStore()
    _result, user = _approved_email_account(store, "member@example.test")
    client, response = _google_login(_google_app(store, "sub-case", "  Member@Example.TEST "))
    assert response.headers["location"] == "/"
    assert client.get("/me").json()["user_id"] == str(user.user_id)


def test_google_email_must_match_exactly_not_by_prefix(local_env):
    store = MemoryAuthStore()
    _approved_email_account(store, "member@example.test")
    for other in ("member@example.test.evil", "xmember@example.test", "member@example.tes", "member+1@example.test"):
        client, response = _google_login(_google_app(store, f"sub-{other}", other))
        assert response.headers["location"] == PENDING_PATH, other
        assert client.cookies.get(AUTH_COOKIE_NAME) is None


def test_unverified_google_email_never_reaches_the_store(local_env):
    # email_verified=false 이면 검증기가 GoogleOAuthError (test_google_id_token_verifier_rejects_unverified_email 가 검증기를 직접 확인)
    store = MemoryAuthStore()
    _approved_email_account(store)
    app = FastAPI()
    app.include_router(create_auth_router(
        store=store, secret="x" * 32, cookie_secure=False, revocation_store=MemoryRevocations(),
        google_config=GoogleOAuthConfig("test-client-id", "test-client-secret", "https://example.test/cb"),
        google_token_exchanger=MockExchanger(), google_id_token_verifier=RejectingVerifier(),
    ))
    client, response = _google_login(app)
    assert response.headers["location"] == FAILED_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None
    assert store._identities == {}


def test_existing_account_without_email_proof_is_not_linked(local_env):
    store = MemoryAuthStore()
    store.create_user(EMAIL, hash_password("seed-pass-123"), "user")  # 신청 기록 없는 시드·운영 생성 계정
    client, response = _google_login(_google_app(store))
    assert response.headers["location"] == FAILED_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None
    assert store._identities == {}


def test_account_whose_signup_email_was_not_verified_is_not_linked(local_env):
    store = MemoryAuthStore()
    assert _approved_email_account(store)[0] == "changed"  # 인증 없이는 승인되지 않으므로(unverified) 승인 뒤 기록이 비는 옛 데이터를 흉내
    store._signup_requests[EMAIL]["email_verified_at"] = None
    client, response = _google_login(_google_app(store))
    assert response.headers["location"] == FAILED_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None


def test_inactive_account_is_not_linked(local_env):
    store = MemoryAuthStore()
    _result, user = _approved_email_account(store)
    store._users[EMAIL] = AuthUser(user.user_id, user.login_id, user.password_hash, user.role, False)
    client, response = _google_login(_google_app(store))
    assert response.headers["location"] == FAILED_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None
    assert store._identities == {}


def test_second_google_account_cannot_take_over_a_linked_account(local_env):
    store = MemoryAuthStore()
    _approved_email_account(store)
    _, first = _google_login(_google_app(store, "sub-first"))
    assert first.headers["location"] == "/"
    client, second = _google_login(_google_app(store, "sub-second"))
    assert second.headers["location"] == FAILED_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None
    with pytest.raises(GoogleAccountLinkError):
        store.get_or_create_google_user("google", "sub-second", EMAIL)


def test_relogin_with_same_google_sub_reaches_same_account_even_if_email_changed(local_env):
    store = MemoryAuthStore()
    _approved_email_account(store)
    first, _ = _google_login(_google_app(store, "sub-same"))
    again, response = _google_login(_google_app(store, "sub-same", "renamed@example.test"))
    assert response.headers["location"] == "/"
    assert again.get("/me").json() == first.get("/me").json()


def test_no_account_creates_one_pending_request_and_no_jwt(local_env):
    store = MemoryAuthStore()
    client, response = _google_login(_google_app(store, "sub-new", "New@Example.test"))
    assert response.status_code == 303 and response.headers["location"] == PENDING_PATH
    assert client.cookies.get(AUTH_COOKIE_NAME) is None
    assert client.cookies.get(GOOGLE_OAUTH_REQUEST_COOKIE_NAME) is None
    rows = store.list_signup_requests()  # 관리자 승인 목록에 나온다
    assert len(rows) == 1 and rows[0].status == "pending" and rows[0].login_id == "new@example.test" and rows[0].email_verified
    assert store.get_by_login_id("new@example.test") is None  # 승인 전에는 users 행도 없다


def test_pending_google_account_stays_blocked_on_every_visit(local_env):
    store = MemoryAuthStore()
    app = _google_app(store)
    for _ in range(3):
        client, response = _google_login(app)
        assert response.headers["location"] == PENDING_PATH
        assert client.cookies.get(AUTH_COOKIE_NAME) is None
    assert len(store.list_signup_requests()) == 1


def test_pending_email_signup_makes_google_login_say_pending_without_new_request(local_env):
    store = MemoryAuthStore()
    store.create_pending_user(EMAIL, hash_password("member-pass-123"), email_verification_required=True)
    client, response = _google_login(_google_app(store))
    assert response.headers["location"] == PENDING_PATH and client.cookies.get(AUTH_COOKIE_NAME) is None
    assert len(store.list_signup_requests()) == 1 and store._identities == {}


def test_approved_google_signup_logs_in_as_user_and_same_account_each_time(local_env):
    store = MemoryAuthStore()
    app = _google_app(store)
    _google_login(app)
    assert store.review_signup_request(EMAIL, "approve", _reviewer(store).user_id) == "changed"
    first, first_response = _google_login(app)
    assert first_response.headers["location"] == "/"
    me = first.get("/me").json()
    assert me["role"] == "user"
    again, _ = _google_login(app)
    assert again.get("/me").json() == me  # 같은 sub = 같은 계정
    user = store.get_by_login_id(EMAIL)
    assert str(user.user_id) == me["user_id"] and user.password_hash is None
    assert store.set_password(EMAIL, hash_password("new-pass-123")) is None  # 구글 계정에 비밀번호를 붙이지 않는다


def test_rejected_google_account_is_blocked(local_env):
    store = MemoryAuthStore()
    app = _google_app(store)
    _google_login(app)
    reviewer = _reviewer(store)
    assert store.review_signup_request(EMAIL, "reject", reviewer.user_id) == "changed"
    client, response = _google_login(app)
    assert response.headers["location"] == REJECTED_PATH
    assert client.cookies.get(AUTH_COOKIE_NAME) is None
    assert store.review_signup_request(EMAIL, "approve", reviewer.user_id) == "unchanged"
    with pytest.raises(GoogleSignupRejectedError):
        store.get_or_create_google_user("google", "sub-1", EMAIL)


def test_store_rejects_empty_subject_unknown_provider_and_bad_email():
    store = MemoryAuthStore()
    for args in (("google", "", EMAIL), ("github", "s", EMAIL), ("google", "s", ""), ("google", "s", "no-at-sign")):
        with pytest.raises(ValueError):
            store.get_or_create_google_user(*args)
    with pytest.raises(GoogleSignupPendingError):
        store.get_or_create_google_user("google", "s", "ok@example.test")


def test_google_start_redirects_to_login_notice_when_env_is_missing(local_env, monkeypatch):
    # 환경변수가 없으면 JSON 503 대신 로그인 화면(안내 문구)으로 보낸다. 콜백 오류도 같은 /login?oauth_error=... 방식.
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    store = MemoryAuthStore()
    app = FastAPI()
    app.include_router(create_auth_router(store=store, secret="x" * 32, cookie_secure=False, revocation_store=MemoryRevocations()))
    response = TestClient(app).get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?oauth_error=google_unavailable"
    assert "content-type" not in response.headers or "json" not in response.headers["content-type"]
