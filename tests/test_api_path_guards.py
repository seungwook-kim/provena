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
    """C-24: HEAD 응답은 규격상 본문이 없다(봉투를 실을 수 없다). 상태는 404·405 중 하나이고 X-Request-ID는 붙는다."""
    r = env.client(env.alice).head("/threads")
    assert r.status_code in (404, 405) and r.content == b"" and r.headers.get("x-request-id")


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
