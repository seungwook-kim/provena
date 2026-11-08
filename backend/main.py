"""FastAPI 진입점.

그래프(backend/graph), 검색(backend/rag), 로그인(backend/auth.py)은 각자 자리에서 만들고
여기서는 엔드포인트로 연결만 합니다. LLM 호출은 services/llm.py 한 곳에서만 합니다.

- `/health`는 항상 있습니다(DB 없이도).
- `DATABASE_URL`이 있으면 로그인 라우터(`/auth/csrf`, `/auth/login`, `/auth/logout`, `/me`)와 결정표 실행·승인 라우터를 붙입니다.
  이때 `AUTH_SECRET`(32바이트 이상)이 없으면 시작하지 않습니다. 로컬 데모 모드에서만 비어 있으면 실행마다 무작위로 만듭니다.
- `PROVENA_ENV=local` 이고 `PROVENA_DEV_MODE=1` 일 때만 시작할 때 users 테이블을 만들고 데모 계정 2개를 시드합니다
  (backend/services/demo_seed.py). 그 밖의 모드에서는 스키마(db/101_auth_users.sql)가 미리 적용돼 있어야 합니다.
- `web/`의 정적 파일(현재 로그인 화면)을 `/`에서 내줍니다. API 경로가 먼저 잡히도록 마지막에 붙입니다.
- `SEARCH_WARMUP=1`이면 시작할 때 검색 모델·BM25를 백그라운드로 올립니다(docs/specs/search.md). 실패해도 서버는 뜨고,
  검색은 첫 요청 때 다시 준비를 시도합니다. compose의 `loader`가 색인을 적재한 뒤 api가 뜹니다.
- `MCP_TOKEN`이 있으면 읽기 전용 MCP 도구 6개를 `/mcp/`에 붙입니다(Bearer 토큰, docs/specs/mcp.md). 비어 있으면 붙이지 않습니다.
- 모든 오류는 `{"error": {"code", "message", "request_id"}}` 한 모양입니다(`backend/api/errors.py`). 요청마다 `X-Request-ID` 헤더와
  로그 한 줄을 남깁니다(`backend/api/middleware.py`).
- 로그인 라우터가 붙을 때 `/chat`(SSE), `/threads`, `/me/memory`도 붙습니다(`backend/api/routes.py`). 질문 그래프는 앱 시작에서
  결정표·합동 검토와 같은 체크포인터·Store로 한 번 만들고, 합동 검토는 질문 그래프의 하위 그래프로 돌립니다.
- `/health`가 불리면 10분(600초) 간격으로 DB에 `SELECT 1`을 백그라운드로 보냅니다(Supabase 무료 플랜 정지 방지). 실패해도 응답은 200입니다.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, nullcontext
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.errors import ApiError
from backend.api.errors import install_error_handlers
from backend.api.middleware import RequestContextMiddleware
from backend.api.routes import create_api_router
from backend.api.threads import InMemoryThreadStore, PostgresThreadStore
from backend.auth import AuthStore, TokenRevocationStore, create_auth_router
from backend.graph.checkpoint import is_restart_safe
from backend.graph.decision.routes import _LazyChatModel, create_decision_router, open_decision_runtime
from backend.services.auth_store import PostgresAuthStore, PostgresTokenRevocationStore
from backend.services.demo_seed import is_local_demo, seed_demo_accounts

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
BOOTSTRAP_TRIES = 10
BOOTSTRAP_WAIT_SECONDS = 2.0
KEEPALIVE_SECONDS = 600   # Supabase 무료 플랜 정지 방지: /health가 불릴 때 이 간격으로 DB에 SELECT 1


def bootstrap_local_auth(store: PostgresAuthStore) -> None:
    """로컬 데모에서만: users 테이블을 만들고 데모 계정을 시드한다. DB가 막 뜬 경우를 위해 몇 번 다시 시도한다."""
    for attempt in range(1, BOOTSTRAP_TRIES + 1):
        try:
            store.ensure_schema()
            break
        except Exception as exc:  # psycopg.OperationalError 등. DSN(비밀번호 포함)은 메시지에 쓰지 않는다
            if attempt == BOOTSTRAP_TRIES:
                raise
            log.warning("DB 준비 대기 (%d/%d): %s", attempt, BOOTSTRAP_TRIES, type(exc).__name__)
            time.sleep(BOOTSTRAP_WAIT_SECONDS)
    seed_demo_accounts(store)


def resolve_auth_secret() -> str | None:
    """`AUTH_SECRET`이 있으면 그 값. 없고 로컬 데모 모드면 이번 실행용 무작위 값(저장소에 서명 키를 두지 않으려고).

    그 밖의 모드에서는 None을 돌려주고, auth.py가 시작을 막는다.
    """
    secret = os.getenv("AUTH_SECRET")
    if secret or not is_local_demo():
        return secret
    log.warning("로컬 데모: AUTH_SECRET이 없어 이번 실행용 서명 키를 무작위로 만들었다(재시작하면 다시 로그인)")
    return secrets.token_urlsafe(48)


def start_search_warmup() -> threading.Thread | None:
    """SEARCH_WARMUP=1일 때만: 검색 준비(장부 대조·모델·BM25, 수십 초)를 백그라운드로. /health와 로그인은 기다리지 않는다."""
    if os.getenv("SEARCH_WARMUP") != "1":
        return None

    def run() -> None:
        try:
            from backend.rag.retrieve.search import warmup
            warmup()
            log.info("검색 준비 완료")
        except (RuntimeError, ValueError) as exc:   # 색인 미적재·장부 불일치 등 검색 쪽이 이유를 적은 오류
            log.warning("검색 준비 실패(첫 검색 때 다시 시도): %s", exc)
        except Exception as exc:  # DB 연결 오류 등. DSN(비밀번호 포함)이 섞일 수 있어 종류만 남긴다
            log.warning("검색 준비 실패(첫 검색 때 다시 시도): %s", type(exc).__name__)

    t = threading.Thread(target=run, name="search-warmup", daemon=True)
    t.start()
    return t


def create_mcp_app(**deps):
    """MCP_TOKEN이 있을 때만 MCP 앱(extras/mcp_skill). 비어 있으면 None — /mcp를 붙이지 않고 앱의 나머지는 그대로 뜬다.
    deps: `build_server` 인자. 결정표 저장소·체크포인터는 비워 두면 MCP 쪽이 `DATABASE_URL`로 처음 부를 때 연다(docs/specs/mcp.md 도구 4·5).
    답 저장소는 앱이 뜬 뒤에 열리므로 호출할 때 읽는 함수(`answer_store_fn`)로 넘긴다."""
    if not os.getenv("MCP_TOKEN", "").strip():
        return None
    from extras.mcp_skill.mcp_server.server import mcp_http_app
    return mcp_http_app(**deps)


def ping_database() -> None:
    """DB에 `SELECT 1` 한 번. 실패해도 예외를 내지 않는다(접속 문자열이 섞일 수 있어 오류 종류만 남긴다)."""
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return
    try:
        import psycopg

        with psycopg.connect(url, autocommit=True, connect_timeout=3, prepare_threshold=None) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - 정지 방지 호출이 실패해도 /health 응답은 그대로다
        log.warning("DB 정지 방지 호출 실패: %s", type(exc).__name__)


def build_question_graph(state: Any) -> Any:
    """질문 그래프. 체크포인터·Store·결정표 저장소·쟁점표 저장소는 `open_decision_runtime()`이 연 것을 나눠 쓴다.

    합동 검토는 체크포인터 없이 이 그래프의 하위 그래프로 붙인다(승인함 재개도 이 그래프로 한다, routes.py 안내문).
    모델은 처음 부를 때 만든다(키 없이도 서버가 뜬다). 답 저장소는 메모리 구현이다(Postgres 구현은 아직 없다)."""
    from backend.graph.build import build_graph
    from backend.graph.departments.review import build_review_graph

    llm = _LazyChatModel()
    review = build_review_graph(None, None, llm=llm, store=state.issue_store, approvals=state.decision_repo)
    return build_graph(None, state.checkpointer, llm=llm, store=state.store, answer_store=state.answer_store,
                       decision_repo=state.decision_repo, review_graph=review)


@contextmanager
def open_question_runtime(app: FastAPI, graph_factory: Callable[[Any], Any], database_url: str | None) -> Iterator[None]:
    """`open_decision_runtime()` 안에서 부른다. 질문 그래프, 대화 목록 저장소, 답 저장소를 `app.state`에 둔다.

    체크포인터가 열리지 않았으면(DB 연결 실패) 아무것도 두지 않는다. `/chat`, `/threads`, `/me/memory`는 503 `not_configured`다."""
    from backend.graph.answer_store import InMemoryAnswerStore

    state = app.state
    if getattr(state, "checkpointer", None) is None:
        yield
        return
    try:
        durable = is_restart_safe(state.checkpointer) and bool(database_url)
        threads = PostgresThreadStore(database_url) if durable else InMemoryThreadStore()
        if durable and is_local_demo():
            try:
                threads.ensure_schema()       # 로컬 데모만: 이미 만든 볼륨에도 threads 표를 만든다
            except Exception as exc:  # noqa: BLE001 - 접속 문자열이 섞일 수 있어 종류만 남긴다
                log.warning("threads 표를 만들지 못함: %s", type(exc).__name__)
        state.thread_store = threads
        state.answer_store = InMemoryAnswerStore()
        try:
            state.question_graph = graph_factory(state)
        except ValueError:      # 환경변수 값이 틀린 설정 오류는 시작을 막는다
            raise
        except Exception as exc:  # noqa: BLE001 - 접속 문자열이 섞일 수 있어 종류만 남긴다
            log.warning("질문 그래프를 만들지 못함: %s", type(exc).__name__)
            state.question_graph = None
        if state.question_graph is not None:
            state.review_graph = state.question_graph   # 합동 검토 승인은 대화를 시작한 질문 그래프로 재개한다
        yield
    finally:
        state.question_graph = state.thread_store = state.answer_store = None


def create_app(
    *,
    auth_store: AuthStore | None = None,
    revocation_store: TokenRevocationStore | None = None,
    graph_factory: Callable[[Any], Any] | None = None,
) -> FastAPI:
    """앱을 만든다. 인자는 시험용이다: 가짜 사용자 저장소(`auth_store`), 가짜 폐기 저장소(`revocation_store`),
    가짜 모델로 질문 그래프를 만드는 함수(`graph_factory(app.state)`)를 꽂는다. 비우면 환경변수대로 만든다."""
    database_url = os.getenv("DATABASE_URL")
    store = auth_store if auth_store is not None else (PostgresAuthStore(database_url) if database_url else None)
    if revocation_store is None and database_url:
        revocation_store = PostgresTokenRevocationStore(database_url)
    auth_secret = resolve_auth_secret() if store is not None else None   # 로컬 데모의 무작위 키도 라우터끼리 같아야 한다
    make_graph = graph_factory or build_question_graph

    def answer_store_fn():
        return getattr(app.state, "answer_store", None)   # 답 저장소는 lifespan 뒤에 열린다. get_grounding을 부를 때 읽는다

    mcp_app = create_mcp_app(answer_store_fn=answer_store_fn)

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        if store is not None and is_local_demo():
            bootstrap_local_auth(store)
        start_search_warmup()
        with open_decision_runtime(app_) if store is not None else nullcontext():      # 체크포인터·결정표 저장소·승인 그래프
            with open_question_runtime(app_, make_graph, database_url) if store is not None else nullcontext():   # 질문 그래프·대화 목록
                async with mcp_app.lifespan(app_) if mcp_app is not None else nullcontext():   # MCP 세션 관리자를 앱과 같이 켜고 끈다
                    yield

    app = FastAPI(title="3차 프로젝트 API", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)     # 요청 ID와 요청 로그(순수 ASGI, SSE를 버퍼링하지 않는다)
    install_error_handlers(app)                      # 오류 응답 규약

    if revocation_store is not None:
        app.state.token_revocation_store = revocation_store

    keepalive = {"last": None}
    keepalive_lock = threading.Lock()

    @app.get("/health")
    def health(background: BackgroundTasks) -> dict:
        """평가자와 배포 환경이 서비스 상태를 확인하는 곳. 지우지 마세요."""
        if database_url:
            now = time.monotonic()
            with keepalive_lock:
                due = keepalive["last"] is None or now - keepalive["last"] >= KEEPALIVE_SECONDS
                if due:
                    keepalive["last"] = now
            if due:
                background.add_task(lambda: ping_database())   # 응답을 보낸 뒤 돈다. 시험이 바꿔 끼울 수 있게 부를 때 찾는다
        return {"status": "ok"}

    if store is not None:
        app.include_router(create_auth_router(store=store, secret=auth_secret))
        app.include_router(create_decision_router(store=store, secret=auth_secret))
        app.include_router(create_api_router(store=store, secret=auth_secret))   # /chat, /threads, /me/memory
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)          # 정적 파일 마운트(/)보다 먼저

    # 도메인 엔드포인트는 여기(아래 정적 파일 마운트보다 위)에 추가합니다.

    web_root = WEB_DIR / "react-app" / "dist" if (WEB_DIR / "react-app" / "dist" / "index.html").is_file() else WEB_DIR
    if (web_root / "index.html").is_file() or (WEB_DIR / "login.html").is_file():

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(web_root / "index.html")

        if web_root != WEB_DIR:
            app.add_api_route("/login.html", lambda: FileResponse(web_root / "index.html"), methods=["GET"], include_in_schema=False)

            web_root_resolved = web_root.resolve()
            api_prefixes = ("auth", "api", "me", "health", "threads", "approvals", "mcp")
            spa_prefixes = ("login", "signup", "chat", "onboarding", "myinfo", "admin", "recalls", "changes", "demo")

        @app.post("/threads", include_in_schema=False)
        def threads_wrong_method() -> None:
            raise HTTPException(status_code=405, detail="Method Not Allowed")

        @app.post("/{path:path}", include_in_schema=False)
        def unknown_post(path: str) -> None:
            raise ApiError(404, "not_found", "요청한 경로를 찾을 수 없습니다.")

        if web_root != WEB_DIR:
            @app.get("/{path:path}", include_in_schema=False)
            def spa_fallback(path: str) -> FileResponse:
                first_segment = path.partition("/")[0]
                if first_segment in api_prefixes:
                    raise HTTPException(status_code=404, detail="Not Found")
                candidate = (web_root / path).resolve()
                if web_root_resolved in candidate.parents and candidate.is_file():
                    return FileResponse(candidate)
                if first_segment in spa_prefixes:
                    return FileResponse(web_root / "index.html")
                raise ApiError(404, "not_found", "요청한 경로를 찾을 수 없습니다.")
        app.mount("/", StaticFiles(directory=web_root), name="web")

    return app


app = create_app()
