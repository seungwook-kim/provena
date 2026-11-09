"""배포 보강 시험: 로그인 IP 식별(TRUSTED_PROXY_HOPS)과 보안 응답 헤더 (키·DB 없음)."""
from __future__ import annotations

import asyncio
import secrets
from uuid import uuid4

import pytest
from api_test_support import Env, ask
from auth_test_support import create_test_auth_router
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

import backend.auth as auth_module
from backend.api.middleware import RequestContextMiddleware
from backend.auth import CSRF_COOKIE_NAME, AuthUser, LoginRateLimiter, hash_password

PEER = "198.51.100.10"


def _request(xff: list[str] | None = None, peer: str | None = PEER) -> Request:
    headers = [(b"x-forwarded-for", v.encode("latin-1")) for v in (xff or [])]
    scope = {"type": "http", "method": "POST", "path": "/auth/login", "headers": headers, "scheme": "http"}
    if peer is not None:
        scope["client"] = (peer, 12345)
    return Request(scope)


# --- Fix 1: 로그인 IP 식별 -------------------------------------------------------------


def test_default_ignores_spoofed_forwarded_for(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert auth_module._client_ip(_request(["203.0.113.99"])) == PEER
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert auth_module._client_ip(_request(["203.0.113.99, 203.0.113.100"])) == PEER


def test_one_hop_uses_last_entry(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert auth_module._client_ip(_request(["203.0.113.5"])) == "203.0.113.5"
    assert auth_module._client_ip(_request(["2001:db8:0:0::1"])) == "2001:db8::1"


def test_spoofed_leftmost_entries_are_ignored(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    # 클라이언트가 직접 적은 앞쪽 값은 버리고, 프록시가 붙인 맨 끝 값만 쓴다
    assert auth_module._client_ip(_request(["10.0.0.1, 1.2.3.4, 203.0.113.5"])) == "203.0.113.5"
    # 헤더가 여러 줄로 와도 순서대로 이어 붙여 오른쪽에서 센다
    assert auth_module._client_ip(_request(["10.0.0.1", "203.0.113.5"])) == "203.0.113.5"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert auth_module._client_ip(_request(["10.0.0.1, 203.0.113.5, 192.0.2.7"])) == "203.0.113.5"


@pytest.mark.parametrize(
    ("hops", "xff"),
    [
        ("1", None),                       # 헤더 없음
        ("1", [""]),                       # 빈 값
        ("1", ["not-an-ip"]),              # 주소가 아님
        ("1", ["203.0.113.5:443"]),        # 포트가 붙음
        ("1", ["203.0.113.5, "]),          # 맨 끝이 비어 있음
        ("1", ["203.0.113.5, garbage"]),   # 맨 끝이 깨짐(앞 값으로 넘어가지 않는다)
        ("3", ["203.0.113.5, 192.0.2.7"]),  # 믿을 항목 수보다 짧다
        ("abc", ["203.0.113.5"]),          # 설정 값이 숫자가 아님 -> 0으로 본다
        ("-1", ["203.0.113.5"]),           # 음수 -> 0으로 본다
    ],
)
def test_malformed_values_fall_back_to_peer(monkeypatch, hops, xff):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", hops)
    assert auth_module._client_ip(_request(xff)) == PEER


def test_missing_peer_and_bad_header_returns_unknown(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert auth_module._client_ip(_request(["junk"], peer=None)) == "unknown"


def _login_client(monkeypatch, limiter: LoginRateLimiter):
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    secret = secrets.token_urlsafe(32)
    user = AuthUser(user_id=uuid4(), login_id="runtime-user", password_hash=hash_password("pw-ok-123"), role="user")

    class Store:
        def get_by_login_id(self, login_id):
            return user if login_id == user.login_id else None

        def get_by_user_id(self, user_id):
            return user if str(user_id) == str(user.user_id) else None

    app = FastAPI()
    app.include_router(create_test_auth_router(store=Store(), secret=secret, cookie_secure=False, rate_limiter=limiter))
    client = TestClient(app)   # 모든 요청의 직접 peer는 같다(프록시 하나 뒤와 같은 상황)
    assert client.get("/auth/csrf").status_code == 204
    return client


def _fail(client: TestClient, login_id: str, xff: str):
    token = client.cookies.get(CSRF_COOKIE_NAME)
    return client.post("/auth/login", json={"login_id": login_id, "password": "wrong"},
                       headers={"X-CSRF-Token": token, "X-Forwarded-For": xff})


def test_limiter_buckets_are_separate_per_real_ip(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    limiter = LoginRateLimiter(max_attempts=100, max_ip_attempts=2, window_seconds=60)
    client = _login_client(monkeypatch, limiter)
    # 사용자 A(203.0.113.5)가 IP 예산을 다 쓴다. 앞쪽 값을 바꿔 적어도 같은 IP로 센다
    assert _fail(client, "a1", "1.1.1.1, 203.0.113.5").status_code == 401
    assert _fail(client, "a2", "9.9.9.9, 203.0.113.5").status_code == 401
    assert _fail(client, "a3", "8.8.8.8, 203.0.113.5").status_code == 429
    # 같은 프록시 뒤의 사용자 B(203.0.113.6)는 막히지 않는다
    assert _fail(client, "b1", "1.1.1.1, 203.0.113.6").status_code == 401
    assert set(limiter._failures_by_ip) == {"203.0.113.5", "203.0.113.6"}


def test_default_hops_shares_peer_bucket(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    limiter = LoginRateLimiter(max_attempts=100, max_ip_attempts=2, window_seconds=60)
    client = _login_client(monkeypatch, limiter)
    assert _fail(client, "a1", "203.0.113.5").status_code == 401
    assert _fail(client, "b1", "203.0.113.6").status_code == 401
    assert _fail(client, "c1", "203.0.113.7").status_code == 429   # 기본값은 직접 peer 하나로 센다
    assert set(limiter._failures_by_ip) == {"testclient"}


# --- Fix 3: 보안 응답 헤더 ----------------------------------------------------------------

BASE = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def _small_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/framed")
    def framed():
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    @app.get("/boom")
    def boom():
        raise RuntimeError("x")

    return app


def _assert_base(headers) -> None:
    for k, v in BASE.items():
        assert headers.get(k) == v, k
    assert headers.get("x-request-id")


def test_security_headers_on_plain_http_without_hsts():
    r = TestClient(_small_app()).get("/ok")
    assert r.status_code == 200
    _assert_base(r.headers)
    assert "strict-transport-security" not in r.headers
    assert "content-security-policy" not in r.headers


def test_hsts_only_for_https_scheme_or_forwarded_proto():
    c = TestClient(_small_app())
    assert c.get("/ok", headers={"X-Forwarded-Proto": "https"}).headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in c.get("/ok", headers={"X-Forwarded-Proto": "http"}).headers
    https = TestClient(_small_app(), base_url="https://testserver")
    assert https.get("/ok").headers["strict-transport-security"] == "max-age=31536000"


def test_security_headers_on_errors_and_existing_value_kept():
    c = TestClient(_small_app(), raise_server_exceptions=False)
    r404 = c.get("/missing")
    assert r404.status_code == 404
    _assert_base(r404.headers)
    r500 = c.get("/boom")
    assert r500.status_code == 500
    _assert_base(r500.headers)
    framed = c.get("/framed")
    assert framed.headers.get_list("x-frame-options") == ["SAMEORIGIN"]


def test_streaming_body_is_not_buffered_and_gets_headers():
    sent: list[dict] = []

    async def gen():
        yield b"event: token\ndata: 1\n\n"
        await asyncio.sleep(0)
        # 다음 조각을 만들기 전에 앞 조각이 이미 밖으로 나갔어야 한다(버퍼링 없음)
        assert any(m["type"] == "http.response.body" and m.get("body", b"").startswith(b"event: token") for m in sent)
        yield b"event: done\ndata: 2\n\n"

    async def app(scope, receive, send):
        await StreamingResponse(gen(), media_type="text/event-stream")(scope, receive, send)

    async def receive():
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/chat", "headers": [(b"x-forwarded-proto", b"https")],
             "scheme": "http", "query_string": b"", "http_version": "1.1"}
    asyncio.run(RequestContextMiddleware(app)(scope, receive, send))
    start = sent[0]
    assert start["type"] == "http.response.start" and start["status"] == 200
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["x-content-type-options"] == "nosniff" and headers["strict-transport-security"] == "max-age=31536000"
    bodies = [m.get("body", b"") for m in sent[1:] if m["type"] == "http.response.body"]
    assert bodies[0].startswith(b"event: token") and bodies[1].startswith(b"event: done")


def test_chat_sse_keeps_streaming_with_security_headers(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        c.headers["X-Forwarded-Proto"] = "https"
        r, ev = ask(c, "SEV2 장애 최초 대응은 몇 분 이내인가요?", "t-sec", as_of="2025-06-01")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        _assert_base(r.headers)
        assert r.headers["strict-transport-security"] == "max-age=31536000"
        names = [n for n, _ in ev]
        assert names[0] == "token" and names[-1] == "done"
        health = env.client().get("/health")
        _assert_base(health.headers)
        assert "strict-transport-security" not in health.headers
