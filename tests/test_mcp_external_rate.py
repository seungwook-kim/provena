"""/mcp 토큰 나누기와 외부 토큰 호출 수 제한 (docs/specs/mcp.md 열린 항목 5, EC-17, AC-11). 네트워크 없음.

내부 `MCP_TOKEN`은 제한 없음, 외부 `MCP_EXTERNAL_TOKEN`은 `tools/call`을 분당·하루(KST) 수로 제한해 넘으면 429.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from extras.mcp_skill.mcp_server import server

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
CALL = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def bearer(token: str) -> dict:
    return {**HDR, "Authorization": f"Bearer {token}"}


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    def make(internal: str, external: str | None = None, per_min: str | None = None, per_day: str | None = None):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("MCP_TOKEN", internal)
        for name, value in (("MCP_EXTERNAL_TOKEN", external), ("MCP_EXTERNAL_RATE_PER_MIN", per_min),
                            ("MCP_EXTERNAL_RATE_PER_DAY", per_day)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return TestClient(create_app())
    return make


# ---------- 인증 ----------

def test_verifier_tells_internal_and_external_apart():
    v = server.BearerTokenVerifier("inside", "outside")
    run = asyncio.run
    assert run(v.verify_token("inside")).client_id == server.INTERNAL_CLIENT
    assert run(v.verify_token("outside")).client_id == server.EXTERNAL_CLIENT
    assert run(v.verify_token("outsidex")) is None and run(v.verify_token("")) is None


def test_verifier_without_external_token_accepts_only_internal():
    v = server.BearerTokenVerifier("inside")
    assert asyncio.run(v.verify_token("inside")).client_id == server.INTERNAL_CLIENT
    assert asyncio.run(v.verify_token("")) is None
    assert asyncio.run(v.verify_token("outside")) is None


def test_wrong_token_is_401_with_external_token_set(app_client):
    with app_client("inside", "outside") as c:
        assert c.post("/mcp/", json=INIT, headers=HDR).status_code == 401
        assert c.post("/mcp/", json=INIT, headers=bearer("outsid")).status_code == 401
        assert c.post("/mcp/?token=outside", json=INIT, headers=HDR).status_code == 401
        assert c.post("/mcp/", json=INIT, headers=bearer("outside")).status_code == 200
        assert c.post("/mcp/", json=INIT, headers=bearer("inside")).status_code == 200


def test_unset_external_token_behaves_as_before(app_client):
    """외부 토큰이 없으면 MCP_TOKEN만 받고 제한도 없다(분당 1로 둬도 내부 호출은 막히지 않음)."""
    with app_client("inside", None, per_min="1", per_day="1") as c:
        assert c.post("/mcp/", json=INIT, headers=bearer("outside")).status_code == 401
        for _ in range(5):
            assert c.post("/mcp/", json=CALL, headers=bearer("inside")).status_code == 200


def test_external_equal_to_internal_is_ignored(app_client):
    """같은 값이면 제한을 걸 수 없으므로 외부 토큰을 쓰지 않는다(내부 토큰으로만 동작, 제한 없음)."""
    with app_client("same", "same", per_min="1") as c:
        for _ in range(3):
            assert c.post("/mcp/", json=CALL, headers=bearer("same")).status_code == 200


# ---------- 제한 ----------

def test_internal_token_is_unlimited(app_client):
    with app_client("inside", "outside", per_min="2", per_day="2") as c:
        for _ in range(6):
            assert c.post("/mcp/", json=CALL, headers=bearer("inside")).status_code == 200


def test_external_token_limited_per_minute(app_client):
    with app_client("inside", "outside", per_min="2", per_day="100") as c:
        assert c.post("/mcp/", json=CALL, headers=bearer("outside")).status_code == 200
        assert c.post("/mcp/", json=CALL, headers=bearer("outside")).status_code == 200
        r = c.post("/mcp/", json=CALL, headers=bearer("outside"))
        assert r.status_code == 429
        body = r.json()
        assert body["error"] == "rate_limited" and "분당 2회" in body["error_description"]
        assert 1 <= int(r.headers["Retry-After"]) <= 60
        # 세지 않는 요청(initialize, tools/list)과 내부 토큰은 그대로 통과한다
        assert c.post("/mcp/", json=INIT, headers=bearer("outside")).status_code == 200
        assert c.post("/mcp/", json=LIST, headers=bearer("outside")).status_code == 200
        assert c.post("/mcp/", json=CALL, headers=bearer("inside")).status_code == 200


def test_external_token_limited_per_day(app_client):
    with app_client("inside", "outside", per_min="0", per_day="3") as c:
        for _ in range(3):
            assert c.post("/mcp/", json=CALL, headers=bearer("outside")).status_code == 200
        r = c.post("/mcp/", json=CALL, headers=bearer("outside"))
        assert r.status_code == 429 and "하루 3회" in r.json()["error_description"]
        assert 1 <= int(r.headers["Retry-After"]) <= 86400


def test_batch_counts_each_tool_call(app_client):
    with app_client("inside", "outside", per_min="2", per_day="100") as c:
        r = c.post("/mcp/", json=[CALL, {**CALL, "id": 4}, {**CALL, "id": 5}], headers=bearer("outside"))
        assert r.status_code == 429


def test_limiter_minute_window_and_kst_day_reset():
    now = [datetime(2026, 11, 17, 23, 59, 30, tzinfo=server.KST).timestamp()]
    lim = server.ExternalRateLimiter(per_min=2, per_day=3, clock=lambda: now[0])
    assert lim.try_acquire() is None and lim.try_acquire() is None
    window, wait = lim.try_acquire()
    assert window == "minute" and wait == 60
    now[0] += 61                                    # 분 창이 지남 (KST 다음 날 00:00:31)
    assert lim.try_acquire() is None                # 하루 수는 KST 자정에 0으로 돌아가 1
    assert lim.try_acquire() is None
    assert lim.try_acquire()[0] == "minute"
    now[0] += 61
    assert lim.try_acquire() is None                # 하루 3(분 창에는 1)
    window, wait = lim.try_acquire()                # 분 창은 남았지만 하루 한도가 먼저
    assert window == "day"
    midnight = datetime(2026, 11, 19, 0, 0, tzinfo=server.KST).timestamp()
    assert wait == pytest.approx(midnight - now[0], abs=1)


def test_rate_env_parsing(monkeypatch, caplog):
    monkeypatch.delenv("MCP_EXTERNAL_RATE_PER_MIN", raising=False)
    assert server._rate_env("MCP_EXTERNAL_RATE_PER_MIN", 30) == 30
    monkeypatch.setenv("MCP_EXTERNAL_RATE_PER_MIN", "0")
    assert server._rate_env("MCP_EXTERNAL_RATE_PER_MIN", 30) == 0
    for bad in ("-1", "abc", "1.5"):
        monkeypatch.setenv("MCP_EXTERNAL_RATE_PER_MIN", bad)
        assert server._rate_env("MCP_EXTERNAL_RATE_PER_MIN", 30) == 30


def test_default_limits_are_literal_30_per_min_500_per_day():
    """기본 한도를 상수끼리 비교하지 않고 값(분당 30, 하루 500)으로 고정한다. 상수를 바꾸면 이 시험이 실패해야 한다."""
    assert server.DEFAULT_EXTERNAL_RATE_PER_MIN == 30
    assert server.DEFAULT_EXTERNAL_RATE_PER_DAY == 500


def test_app_without_rate_env_uses_30_and_500(monkeypatch):
    """한도 환경 변수가 없으면 외부 토큰 제한기가 분당 30, 하루 500으로 만들어진다(연결 코드가 기본 상수를 넘기는지)."""
    seen: list[tuple[int, int]] = []
    real = server.ExternalRateLimiter

    class Spy(real):
        def __init__(self, per_min, per_day, *a, **kw):
            seen.append((per_min, per_day))
            super().__init__(per_min, per_day, *a, **kw)

    monkeypatch.delenv("MCP_EXTERNAL_RATE_PER_MIN", raising=False)
    monkeypatch.delenv("MCP_EXTERNAL_RATE_PER_DAY", raising=False)
    monkeypatch.setattr(server, "ExternalRateLimiter", Spy)
    assert server.mcp_http_app(token="inside", external_token="outside") is not None
    assert seen == [(30, 500)]


def test_tool_call_counting():
    import json
    assert server._tool_calls(json.dumps(CALL).encode()) == 1
    assert server._tool_calls(json.dumps([CALL, LIST, CALL]).encode()) == 2
    assert server._tool_calls(json.dumps(INIT).encode()) == 0
    assert server._tool_calls(b"{not json") == 0
