"""경로 id에 NUL 문자가 든 요청과 `/threads` 경계 시험 (놓친 것 C-16·C-17·C-24·C-25). 키·네트워크·DB 없음."""
from __future__ import annotations

import pytest
from api_test_support import Env


@pytest.fixture
def env(monkeypatch):
    with Env(monkeypatch) as e:
        yield e


@pytest.mark.parametrize("method,path", [
    ("get", "/changes/ab%00c"), ("get", "/recalls/ab%00c"), ("get", "/threads/ab%00c"),
    ("post", "/decision-tables/ab%00c/run"), ("post", "/admin/signup-requests/ab%00c/approve"),
    ("post", "/admin/users/ab%00c/promote"), ("post", "/admin/users/ab%00c/revoke"), ("post", "/approvals/ab%00c"),
    ("get", "/%00"),
])
def test_nul_in_path_is_404_with_error_envelope(env, method, path):
    """C-16·C-17: NUL이 든 경로 id가 DB까지 가서 500·503이 나던 것. 어디서든 404 오류 봉투로 막는다."""
    r = getattr(env.client(env.admin), method)(path)
    assert r.status_code == 404, (path, r.status_code)
    assert r.json()["error"]["code"] == "not_found" and r.headers["x-request-id"] == r.json()["error"]["request_id"]


def test_dot_dot_thread_id_is_not_a_thread(env):
    """C-25: `%2e%2e`는 서버에서 정규화되지 않는다. 목록(200)으로 보이는 것은 `..`을 먼저 접는 클라이언트(curl·브라우저) 때문이다."""
    c = env.client(env.alice)
    assert c.get("/threads/%2e%2e").status_code == 404
    assert c.get("/threads/..%2fx").status_code == 404


def test_head_threads_has_request_id_and_no_body(env):
    """C-24: `/threads`는 GET 전용이라 FastAPI가 HEAD 경로를 만들지 않는다. 전에는 HEAD가 `backend/main.py` 끝의 `app.mount("/", StaticFiles)`로 떨어져 404가 났다.
    지금은 `api/middleware.py`가 405와 `Allow`(GET을 받는 경로의 메서드)로 답한다. HEAD라 본문은 없다."""
    for user in (env.alice, None):
        r = env.client(user).head("/threads")   # 로그인 안 한 사람도 같은 405(경로가 HEAD를 받지 않는다는 사실만 알림)
        assert r.status_code == 405 and r.content == b"" and r.headers.get("x-request-id"), r.status_code
        assert "GET" in r.headers["allow"] and "HEAD" not in r.headers["allow"]
    r = env.client(env.alice).head("/threads/t-unknown")
    assert r.status_code == 405 and "GET" in r.headers["allow"]


def test_head_keeps_routes_that_already_answer_head(env):
    """C-24 수정이 HEAD를 받는 경로(`/health`)와 없는 경로를 바꾸지 않는지."""
    c = env.client(env.alice)
    assert c.head("/health").status_code == 200
    assert c.head("/zz-no-such-api").status_code == 404


def test_broken_approval_row_is_skipped_not_500():
    """C-18: target_id가 NULL인 승인 행 하나가 `/approvals`·`/threads`의 대기 목록 전체를 깨뜨리던 것."""
    from datetime import datetime, timezone

    from backend.graph.decision.repo import PostgresDecisionRepo

    now = datetime.now(timezone.utc)
    good = {"approval_id": "ap-good", "kind": "decision_table", "thread_id": "t1", "status": "pending", "summary": "s", "target_id": "tbl-1",
            "created_at": now, "decided_by": None, "comment": "", "decided_at": None}
    bad = {**good, "approval_id": "ap-bad", "target_id": None}
    repo = PostgresDecisionRepo.__new__(PostgresDecisionRepo)
    repo._rows = lambda sql, params=(): [bad, good]
    assert [r.approval_id for r in repo.list_pending()] == ["ap-good"]


def test_middleware_blocks_nul_before_router():
    """C-16: 시험 앱은 메모리 저장소라 NUL id가 원래 404다. 그래서 라우터에 닿으면 500인 앱으로 미들웨어 거름만 따로 증명한다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.middleware import RequestContextMiddleware

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/x/{eid}")
    def get_boom(eid: str):
        raise RuntimeError("router reached")

    @app.post("/x/{eid}/run")
    def post_boom(eid: str):
        raise RuntimeError("router reached")

    c = TestClient(app, raise_server_exceptions=False)
    for method, path in [("get", "/x/ab%00c"), ("post", "/x/ab%00c/run"), ("get", "/x/ab%00c/")]:
        r = getattr(c, method)(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (path, r.status_code)
        assert r.headers["x-request-id"] == r.json()["error"]["request_id"]
    # 대조군: NUL이 없으면 라우터까지 가서 500이다(= 위 404는 라우터가 아니라 미들웨어가 낸 것)
    assert c.get("/x/abc").status_code == 500
    assert c.post("/x/abc/run").status_code == 500
