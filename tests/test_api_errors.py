"""오류 응답 규약, 요청 ID, `/health` 정지 방지 호출 시험 (SDD 4-4, `backend/api/errors.py`, `backend/api/middleware.py`, `backend/main.py`)."""
from __future__ import annotations

import logging

import pytest
from api_test_support import Env
from fastapi.testclient import TestClient

from backend import main
from backend.api.errors import VALIDATION_MESSAGE, code_and_message


def test_unknown_path_is_404_not_found_with_matching_request_id(monkeypatch):
    with Env(monkeypatch) as env:
        r = env.client(None).get("/no/such")
        err = r.json()["error"]
        assert r.status_code == 404 and err["code"] == "not_found" and err["request_id"] == r.headers["x-request-id"]


def test_valid_incoming_request_id_is_kept_and_bad_one_replaced(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(None)
        assert c.get("/health", headers={"X-Request-ID": "trace-abc-12345"}).headers["x-request-id"] == "trace-abc-12345"
        bad = c.get("/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["x-request-id"]
        assert bad != "bad id\nwith newline" and len(bad) == 32


def test_auth_and_admin_errors_use_codes(monkeypatch):
    with Env(monkeypatch) as env:
        r = env.client(None).get("/me")
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        r = env.client(env.alice).get("/approvals")
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
        r = env.client(env.admin, csrf=False).post("/approvals/ap_x", json={"approve": True})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_decision_route_reason_becomes_the_code(monkeypatch):
    with Env(monkeypatch) as env:
        r = env.client(env.admin).post("/approvals/ap_missing", json={"approve": True})
        err = r.json()["error"]
        assert r.status_code == 404 and err["code"] == "not_found" and err["message"] == "승인 건이 없다"
        assert r.json()["detail"] == "승인 건이 없다"            # 화면 호환용 detail은 문자열이다(reason 사전이 아니다)
        r = env.client(env.alice).post("/decision-tables/run", json={"amount_usd": 1})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request" and "task_type" in r.json()["error"]["message"]


def test_error_body_also_has_detail_string_for_the_screen(monkeypatch):
    """화면(`web/login.js`, `web/react-app/src/lib/api.js`)은 아직 `body.detail` 문자열을 읽는다. `error` 객체는 그대로다."""
    with Env(monkeypatch) as env:
        anon, alice = env.client(None), env.client(env.alice)
        cases = {
            "login_failed": (401, "unauthorized", anon.post("/auth/login", json={"login_id": "nobody", "password": "wrong-password-1"})),
            "csrf_failed": (403, "csrf_failed", env.client(env.alice, csrf=False).post("/chat", json={"message": "질문"})),
            "validation": (422, "validation_error", alice.post("/chat", json={"message": "", "password": "hunter2-secret"})),
            "api_error": (404, "not_found", alice.get("/threads/nope")),
            "decision_reason": (400, "bad_request", alice.post("/decision-tables/run", json={"amount_usd": 1})),
        }
        for name, (status, code, r) in cases.items():
            body = r.json()
            assert r.status_code == status and body["error"]["code"] == code, name
            assert isinstance(body["detail"], str) and body["detail"] and body["detail"] == body["error"]["message"], name
            assert body["error"]["request_id"] == r.headers["x-request-id"], name
        assert cases["login_failed"][2].json()["detail"] == "로그인 정보가 올바르지 않습니다."
        assert cases["validation"][2].json()["detail"] == VALIDATION_MESSAGE and "hunter2-secret" not in cases["validation"][2].text


def test_unhandled_error_is_500_internal_error_without_the_text(monkeypatch, caplog):
    with Env(monkeypatch) as env:
        @env.app.get("/boom-for-test")
        def boom():
            raise RuntimeError("secret-password-in-error")

        env.app.router.routes.insert(0, env.app.router.routes.pop())   # 정적 파일 마운트(/)보다 먼저 잡히게 앞으로 옮긴다
        with caplog.at_level(logging.ERROR, logger="backend.request"):
            r = TestClient(env.app, raise_server_exceptions=False).get("/boom-for-test")
        err = r.json()["error"]
        assert r.status_code == 500 and err["code"] == "internal_error" and err["request_id"] == r.headers["x-request-id"]
        assert r.json()["detail"] == err["message"]
        assert "secret-password" not in r.text and "secret-password" in caplog.text   # 내용은 로그에만


@pytest.mark.parametrize("status, detail, want", [
    (409, {"reason": "already_decided", "message": "이미 approved된 승인 건이다"}, ("already_decided", "이미 approved된 승인 건이다")),
    (403, "CSRF 검증에 실패했습니다.", ("csrf_failed", "CSRF 검증에 실패했습니다.")),
    (403, "관리자 권한이 필요합니다.", ("forbidden", "관리자 권한이 필요합니다.")),
    (429, "로그인 시도가 너무 많습니다.", ("rate_limited", "로그인 시도가 너무 많습니다.")),
    (503, "인증 저장소를 사용할 수 없습니다.", ("not_configured", "인증 저장소를 사용할 수 없습니다.")),
    (422, "잘못된 로그인 요청입니다.", ("validation_error", "잘못된 로그인 요청입니다.")),
])
def test_http_exception_detail_is_mapped(status, detail, want):
    assert code_and_message(status, detail) == want


def test_request_log_has_id_method_path_status_and_no_query(monkeypatch, caplog):
    with Env(monkeypatch) as env:
        with caplog.at_level(logging.INFO, logger="backend.request"):
            r = env.client(None).get("/health?token=secret-query-value")
        line = next(rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("request "))
        assert f"id={r.headers['x-request-id']}" in line and "method=GET path=/health status=200" in line and "ms=" in line
        assert "secret-query-value" not in caplog.text


# --- /health 정지 방지 호출 --------------------------------------------------------------------

def _health_app(monkeypatch, calls, fail=False):
    from api_test_support import FakeAuthStore
    from auth_test_support import MemoryRevocationStore

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", "x" * 40)

    def fake_ping():
        calls.append(1)
        if fail:
            main.log.warning("DB 정지 방지 호출 실패: %s", "OperationalError")

    monkeypatch.setattr(main, "ping_database", fake_ping)
    return main.create_app(auth_store=FakeAuthStore(), revocation_store=MemoryRevocationStore())


def test_health_pings_the_database_at_most_every_10_minutes(monkeypatch):
    calls: list = []
    c = TestClient(_health_app(monkeypatch, calls))
    assert [c.get("/health").json() for _ in range(3)] == [{"status": "ok"}] * 3
    assert len(calls) == 1 and main.KEEPALIVE_SECONDS == 600
    monkeypatch.setattr(main, "KEEPALIVE_SECONDS", 0)
    c.get("/health")
    assert len(calls) == 2


def test_health_stays_200_when_the_ping_fails(monkeypatch):
    calls: list = []
    r = TestClient(_health_app(monkeypatch, calls, fail=True)).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"} and calls == [1]


def test_ping_database_never_raises_and_hides_the_dsn(monkeypatch, caplog):
    import psycopg

    seen = {}

    def refuse(url, **kw):
        seen.update(kw)
        raise psycopg.OperationalError(f"could not connect {url}")

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secret-password@db/x")
    monkeypatch.setattr(psycopg, "connect", refuse)
    with caplog.at_level(logging.WARNING):
        main.ping_database()
    assert seen["prepare_threshold"] is None and seen["connect_timeout"] == 3
    assert "OperationalError" in caplog.text and "secret-password" not in caplog.text


def test_ping_database_without_database_url_does_nothing(monkeypatch):
    import psycopg

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("연결하면 안 된다"))
    main.ping_database()


def test_health_without_database_url_does_not_ping(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "ping_database", lambda: pytest.fail("DB가 없으면 부르지 않는다"))
    assert TestClient(main.create_app()).get("/health").status_code == 200
