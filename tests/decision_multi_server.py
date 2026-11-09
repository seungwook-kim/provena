"""여러 인스턴스 시험용 서버. 실제 결정표 라우터와 `open_decision_runtime()`을 그대로 쓰고, 같은 DB를 보는 프로세스를 포트만 달리해 둘 이상 띄운다.
LLM 키와 `.env`는 읽지 않는다. 가짜 모델은 이 시험이 만드는 시작 쪽(`start_pending`)에서만 쓰고, 서버에는 모델이 필요 없다(재개는 LLM을 쓰지 않는다).

사용: python tests/decision_multi_server.py <port>
환경변수: DATABASE_URL, LOCKTEST_SECRET(서명 키), LOCKTEST_ADMIN_ID(관리자 user_id), LOCKTEST_DELAY(초, 재개 직전 지연. 기본 0)
결정 저장과 그래프 재개는 `lock_events` 표에 한 줄씩 남긴다. 시험이 이 표로 프로세스를 가로질러 센다.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402
import uvicorn  # noqa: E402
from auth_test_support import MemoryRevocationStore  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from langgraph.types import Command  # noqa: E402

from backend.auth import AuthUser  # noqa: E402
from backend.graph.decision.routes import create_decision_router, open_decision_runtime  # noqa: E402

EVENTS_DDL = "CREATE TABLE IF NOT EXISTS lock_events (id bigserial PRIMARY KEY, at timestamptz DEFAULT clock_timestamp(), pid int, kind text, ref text, detail text)"


def _log(url: str, kind: str, ref: str, detail: str = "") -> None:
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO lock_events (pid, kind, ref, detail) VALUES (%s, %s, %s, %s)", (os.getpid(), kind, ref, detail))


def _instrument(app: FastAPI, url: str, delay: float) -> None:
    repo = app.state.decision_repo

    def wrap_decide(name: str) -> None:
        orig = getattr(repo, name)

        def decide_logged(approval_id, approve, *a, **k):
            try:
                out = orig(approval_id, approve, *a, **k)
            except Exception as e:  # noqa: BLE001
                _log(url, "decide_error", approval_id, f"approve={approve} {type(e).__name__}")
                raise
            _log(url, "decide_ok", approval_id, f"approve={approve}")
            return out

        setattr(repo, name, decide_logged)

    def wrap_invoke(graph) -> None:
        invoke = graph.invoke

        def invoke_logged(value, config=None, *a, **k):
            tid = (config or {}).get("configurable", {}).get("thread_id", "")
            if isinstance(value, Command):
                _log(url, "graph_resume", tid, f"approve={(value.resume or {}).get('approve')}")
                if delay:
                    time.sleep(delay)
            elif value is None:
                _log(url, "graph_continue", tid)
            return invoke(value, config, *a, **k)

        graph.invoke = invoke_logged

    wrap_decide("decide")
    wrap_decide("decide_review_item")
    wrap_invoke(app.state.decision_graph)
    wrap_invoke(app.state.review_graph)   # 쟁점표 승인은 합동 검토 그래프로 재개한다


def build_app() -> FastAPI:
    url, secret = os.environ["DATABASE_URL"], os.environ["LOCKTEST_SECRET"]
    admin = AuthUser(user_id=UUID(os.environ["LOCKTEST_ADMIN_ID"]), login_id="admin", password_hash="x", role="admin")
    delay = float(os.environ.get("LOCKTEST_DELAY") or 0)

    class Users:
        def get_by_login_id(self, login_id):
            return None

        def get_by_user_id(self, user_id):
            return admin if str(user_id) == str(admin.user_id) else None

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        with open_decision_runtime(app_):
            _instrument(app_, url, delay)
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.token_revocation_store = MemoryRevocationStore()
    app.include_router(create_decision_router(store=Users(), secret=secret))
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
