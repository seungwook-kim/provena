"""FastAPI 진입점.

그래프(backend/graph), 검색(backend/rag), 로그인(backend/auth.py)은 각자 자리에서 만들고
여기서는 엔드포인트로 연결만 합니다. LLM 호출은 services/llm.py 한 곳에서만 합니다.

- `/health`는 항상 있습니다(DB 없이도).
- `DATABASE_URL`이 있으면 로그인 라우터(`/auth/csrf`, `/auth/login`, `/auth/logout`, `/me`)와 결정표 실행·승인 라우터를 붙입니다.
  이때 `AUTH_SECRET`(32바이트 이상)이 없으면 시작하지 않습니다. 로컬 데모 모드에서만 비어 있으면 실행마다 무작위로 만듭니다.
- 같은 조건에서 내 정보 라우터(`GET/PUT /me/profile`, backend/profile_api.py)도 붙이고, `/me`에 `profile_completed`를 더합니다.
  `PROFILE_ENC_KEYS`(AES-256 키, backend/services/profile_crypto.py)가 없거나 형식이 틀리면 시작하지 않습니다. 로컬 데모 모드에서만
  비어 있으면 실행마다 무작위 키를 만듭니다(재시작하면 내 정보를 다시 입력).
- 같은 조건에서 사용자 관리 라우터(`GET /admin/users`, `POST /admin/users/{login_id}/promote|revoke`, backend/admin_api.py)도 붙이고,
  `/me`에 `is_owner`를 더합니다. 최고 관리자는 `PROVENA_OWNER_LOGIN_ID`(시작할 때 한 번 읽음). 비었거나 계정과 맞지 않으면
  시작 로그 1줄(값은 쓰지 않음)을 남기고 사용자 관리만 닫습니다(모두 403). 서버는 멈추지 않습니다.
  화면 주소도 `/admin/users`라서, 브라우저가 그 주소를 직접 열면(`Accept: text/html`) API 대신 React 화면을 내줍니다.
- `PROVENA_ENV=local` 이고 `PROVENA_DEV_MODE=1` 일 때만 시작할 때 users·admin_role_log·user_profiles 테이블을 만들고 데모 계정 2개를 시드합니다
  (backend/services/demo_seed.py). 그 밖의 모드에서는 스키마(db/101_auth_users.sql, db/104_user_profiles.sql, db/105_admin_role_log.sql)가
  미리 적용돼 있어야 합니다(104가 없으면 `/me`가 503). 배포판 첫 계정은 `python -m backend.services.create_account` 로 만듭니다.
- `web/`의 정적 파일(현재 로그인 화면)을 `/`에서 내줍니다. API 경로가 먼저 잡히도록 마지막에 붙입니다.
- 시작할 때 검색 준비(모델·BM25·색인 연결, docs/specs/search.md)를 끝날 때까지 기다립니다(`SEARCH_WARMUP`). Cloud Run은 요청이 없을 때 CPU를
  거의 주지 않아 백그라운드 준비가 요청 사이에 못 돌고, 그러면 첫 `/chat`이 준비 시간(수십 초)을 떠안기 때문입니다.
  비어 있으면 운영(`PROVENA_ENV`가 local·demo가 아니고 DB와 LLM 키가 있음)에서만 켜고, 로컬 데모·키 없는 데모·DB 없음에서는 끕니다.
  `1`은 켬(기다림), `0`은 끔, `background`는 기다리지 않고 스레드로 올림(compose 기본). 기다리는 시간은 최대 60초이고, 넘거나 실패해도
  서버는 뜹니다(경고 로그만, 검색은 첫 요청 때 다시 준비를 시도). 기다릴 때는 현재 `LLM_PROVIDER`가 첫 호출에 쓰는 모듈도 미리 올립니다.
  compose의 `loader`가 색인을 적재한 뒤 api가 뜹니다.
- 시작할 때 `backend.*` 로거를 INFO로 둡니다(`configure_app_logging`). 안 두면 요청 로그와 LLM 지연 로그가 운영 로그에 나오지 않습니다.
- `MCP_TOKEN`이 있으면 읽기 전용 MCP 도구 6개를 `/mcp/`에 붙입니다(Bearer 토큰, docs/specs/mcp.md). 비어 있으면 붙이지 않습니다.
- 모든 오류는 `{"error": {"code", "message", "request_id"}}` 한 모양입니다(`backend/api/errors.py`). 요청마다 `X-Request-ID` 헤더와
  로그 한 줄을 남깁니다(`backend/api/middleware.py`).
- 로그인 라우터가 붙을 때 `/chat`(SSE), `/threads`, `/me/memory`도 붙습니다(`backend/api/routes.py`). 질문 그래프는 앱 시작에서
  결정표·합동 검토와 같은 체크포인터·Store로 한 번 만들고, 합동 검토는 질문 그래프의 하위 그래프로 돌립니다.
- 로그인 라우터가 붙을 때 리콜(`/recalls`, `/webhooks/regulation-updated`, `/impact-preview` 등, `backend/api/recalls.py`)과 변경 감시(`/changes`,
  `backend/api/changes.py`)도 붙는다. 저장소는 `backend/graph/recall/runtime.py`가 환경변수(`RECALL_STORE`, `DATABASE_URL`)대로 연다.
- `/health`가 불리면 10분(600초) 간격으로 DB에 `SELECT 1`을 백그라운드로 보냅니다(Supabase 무료 플랜 정지 방지). 실패해도 응답은 200입니다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, nullcontext
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match, Mount

from backend.api.errors import ApiError, install_error_handlers
from backend.api.middleware import RequestContextMiddleware
from backend.api.changes import create_changes_router
from backend.api.eval_review import create_eval_review_router
from backend.api.recalls import create_recall_router
from backend.api.routes import create_api_router
from backend.api.threads import InMemoryThreadStore, PostgresThreadStore
from backend.admin_api import check_owner, create_admin_router, owner_check_for
from backend.auth import AuthStore, TokenRevocationStore, create_auth_router
from backend.graph.checkpoint import is_restart_safe
from backend.graph.decision.routes import create_decision_router, open_decision_runtime
from backend.graph.recall.runtime import open_recall_runtime
from backend.profile_api import create_profile_router
from backend.services.auth_store import PostgresAuthStore, PostgresTokenRevocationStore
from backend.services.demo_seed import is_local_demo, seed_demo_accounts
from backend.services.profile_crypto import ProfileCipher
from backend.services.profile_store import PostgresProfileStore

log = logging.getLogger(__name__)


def warn_if_silent_demo() -> bool:
    """키가 없어 데모 모드(가짜 모델)로 떨어졌는데 그게 의도로 보이지 않으면 시작 로그에 경고를 남긴다. 남겼으면 True.
    의도로 보는 경우: `PROVENA_ENV`가 local·demo, `DEMO_MODE`를 켬, `LLM_PROVIDER=claude_cli`(키 없이 실제 모델).
    동작은 바꾸지 않는다(시험·로컬 데모가 키 없이 앱을 만든다). 배포에서 `LLM_API_KEY`가 빠진 것을 로그로 바로 알게 하려는 것이다."""
    from backend.services.demo_replay import env_flag
    from backend.services.llm import is_demo_mode

    if (os.getenv("PROVENA_ENV") or "").strip().lower() in ("local", "demo") or env_flag("DEMO_MODE"):
        return False
    if not is_demo_mode():
        return False
    log.warning("LLM_API_KEY가 없어 데모 모드(가짜 모델)로 동작합니다. 배포라면 LLM_API_KEY를 넣고 다시 배포하세요. "
                "의도한 데모라면 DEMO_MODE=1 또는 PROVENA_ENV=demo로 두면 이 경고가 사라집니다.")
    return True

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
BOOTSTRAP_TRIES = 10
BOOTSTRAP_WAIT_SECONDS = 2.0
KEEPALIVE_SECONDS = 600   # Supabase 무료 플랜 정지 방지: /health가 불릴 때 이 간격으로 DB에 SELECT 1
SEARCH_WARMUP_TIMEOUT_S = 60.0   # 시작 때 검색 준비를 기다리는 최대 시간. 넘으면 기다리지 않고 서버를 연다


def bootstrap_local_auth(store: PostgresAuthStore, profile_store: PostgresProfileStore | None = None) -> None:
    """로컬 데모에서만: users(·user_profiles) 테이블을 만들고 데모 계정을 시드한다. DB가 막 뜬 경우를 위해 몇 번 다시 시도한다."""
    for attempt in range(1, BOOTSTRAP_TRIES + 1):
        try:
            store.ensure_schema()
            break
        except Exception as exc:  # psycopg.OperationalError 등. DSN(비밀번호 포함)은 메시지에 쓰지 않는다
            if attempt == BOOTSTRAP_TRIES:
                raise
            log.warning("DB 준비 대기 (%d/%d): %s", attempt, BOOTSTRAP_TRIES, type(exc).__name__)
            time.sleep(BOOTSTRAP_WAIT_SECONDS)
    if profile_store is not None:
        profile_store.ensure_schema()   # users 다음(외래키). DB는 위에서 이미 준비됐다
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


def configure_app_logging() -> None:
    """시작할 때 `backend.*` 로거를 INFO로 둔다. 안 두면 루트 기본(WARNING)이라 요청 로그·LLM 지연 로그가 운영 로그에 안 나온다.
    루트에 핸들러가 없을 때만(uvicorn은 루트를 설정하지 않는다) 표준 오류로 내보내는 핸들러 하나를 붙인다. 여러 번 불러도 한 번만 붙는다."""
    lg = logging.getLogger("backend")
    lg.setLevel(logging.INFO)
    if logging.getLogger().handlers or any(getattr(h, "_provena", False) for h in lg.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler._provena = True  # type: ignore[attr-defined]
    lg.addHandler(handler)


def search_warmup_mode(*, default_on: bool) -> str:
    """`SEARCH_WARMUP` 값을 `sync`(시작 때 끝날 때까지 기다림), `background`(스레드로 올리고 기다리지 않음), `off`로 바꾼다.

    `1`·`true`·`yes`·`on`은 sync, `background`는 background, `0`·`false`·`no`·`off`는 off. 비어 있거나 없으면 `default_on`이 참일 때 sync다.
    알 수 없는 값은 off로 두고 경고를 남긴다(서버는 뜬다)."""
    raw = (os.getenv("SEARCH_WARMUP") or "").strip().lower()
    if not raw:
        return "sync" if default_on else "off"
    if raw in ("1", "true", "yes", "on"):
        return "sync"
    if raw == "background":
        return "background"
    if raw not in ("0", "false", "no", "off"):
        log.warning("SEARCH_WARMUP 값을 알 수 없어 검색 준비를 건너뜁니다")
    return "off"


def search_warmup_default_on(*, has_db: bool, graph_injected: bool) -> bool:
    """`SEARCH_WARMUP`이 비었을 때의 기본값. 운영(`PROVENA_ENV`가 local·demo가 아니고 DB가 있고 LLM 키가 있는 서비스)에서만 켠다.
    로컬 데모, 키 없는 데모(DEMO_MODE=1 또는 `LLM_API_KEY` 없음), DB 없음, 시험이 그래프를 꽂은 앱은 끈다."""
    if graph_injected or not has_db or is_local_demo():
        return False
    if (os.getenv("PROVENA_ENV") or "").strip().lower() in ("local", "demo"):
        return False
    from backend.services.llm import is_demo_mode
    return not is_demo_mode()


def _search_warmup_job() -> bool:
    """검색 준비(장부 대조·모델·BM25)를 한 번 하고 걸린 시간을 남긴다. 실패해도 예외를 내지 않는다(첫 검색 때 다시 시도)."""
    started = time.perf_counter()
    try:
        from backend.rag.retrieve.search import warmup
        warmup()
        log.info("검색 준비 완료 stage=search_warmup elapsed_s=%.1f", time.perf_counter() - started)
        return True
    except (RuntimeError, ValueError) as exc:   # 색인 미적재·장부 불일치 등 검색 쪽이 이유를 적은 오류
        log.warning("검색 준비 실패(첫 검색 때 다시 시도) stage=search_warmup elapsed_s=%.1f: %s", time.perf_counter() - started, exc)
    except Exception as exc:  # DB 연결 오류 등. DSN(비밀번호 포함)이 섞일 수 있어 종류만 남긴다
        log.warning("검색 준비 실패(첫 검색 때 다시 시도) stage=search_warmup elapsed_s=%.1f: %s", time.perf_counter() - started, type(exc).__name__)
    return False


def start_search_warmup() -> threading.Thread:
    """검색 준비를 백그라운드로. /health와 로그인은 기다리지 않는다(`SEARCH_WARMUP=background`, 로컬 compose 기본)."""
    t = threading.Thread(target=_search_warmup_job, name="search-warmup", daemon=True)
    t.start()
    return t


WARMUP_QUERY = "handbook warmup"   # 첫 요청 준비용 고정 문장. 평가 문항에 없고, 번역·LLM을 거치지 않으며 결과는 버린다


def first_request_warmup(*, searcher_ready: bool) -> None:
    """인스턴스의 첫 `/chat`이 떠안던 지연 초기화를 시작 때 미리 한다(F3 3차 18장: 그래프 시작 전 +1.3초, 검색 +1.0초).
    (1) Langfuse 클라이언트·핸들러 만들기(트레이스는 보내지 않음), (2) 검색 준비가 끝났으면 고정 문장으로 임베딩 1회와 색인 질의 1회
    (Voyage 연결과 검색 DB 연결을 미리 맺는다. 번역 LLM·번역 장부 쓰기는 하지 않고 결과는 버린다).
    단계마다 실패해도 경고만 남기고 서버 시작을 막지 않는다. 오류 종류만 남긴다(접속 문자열이 섞일 수 있다)."""
    started = time.perf_counter()
    done: list[str] = []
    try:
        from backend.services import tracing
        tracing.get_handler(allow_evaluation=True)   # 클라이언트는 프로세스 안에 캐시된다. 꺼져 있으면 None
        done.append("tracing")
    except Exception as exc:  # noqa: BLE001 - 못 만들어도 첫 요청 때 만든다
        log.warning("첫 요청 준비 실패(tracing) stage=first_request_warmup: %s", type(exc).__name__)
    if searcher_ready:
        try:
            import importlib
            searcher = importlib.import_module("backend.rag.retrieve.search")._searcher
            if searcher is not None:
                vec = searcher.embed([WARMUP_QUERY])[0]
                searcher.store.vector_top(vec, searcher.cfg.embed_model, None, None, 1)
                done.append("search")
        except Exception as exc:  # noqa: BLE001 - 못 해도 첫 검색 때 한다
            log.warning("첫 요청 준비 실패(search) stage=first_request_warmup: %s", type(exc).__name__)
    log.info("첫 요청 준비 stage=first_request_warmup elapsed_s=%.1f steps=%s", time.perf_counter() - started, ",".join(done) or "-")


def run_startup_warmup(*, preload_llm: bool, timeout: float = SEARCH_WARMUP_TIMEOUT_S) -> bool:
    """시작할 때 기다리며 준비한다: (1) 첫 LLM 호출에 필요한 제공자 모듈 올리기(`preload_llm`일 때), (2) 검색 준비.

    Cloud Run은 요청이 없을 때 CPU를 거의 주지 않아 백그라운드 스레드가 요청 사이에 못 돈다. 그래서 시작(CPU가 있는 때)에 끝까지 기다린다.
    `timeout`초 안에 안 끝나도 서버는 뜬다(스레드는 계속 돌고, 첫 검색은 같은 잠금을 기다려 준비를 다시 하지 않는다). 실패해도 경고만 남긴다."""
    outcome: dict[str, bool] = {}

    def work() -> None:
        started = time.perf_counter()
        if preload_llm:
            try:
                from backend.services.llm import preload_provider_modules
                names = preload_provider_modules()
                log.info("LLM 모듈 미리 올림 stage=llm_preload elapsed_s=%.1f modules=%s", time.perf_counter() - started, ",".join(names) or "-")
            except Exception as exc:  # noqa: BLE001 - 못 올려도 첫 호출 때 올라간다. 종류만 남긴다
                log.warning("LLM 모듈 미리 올리기 실패(첫 호출 때 올라감) stage=llm_preload: %s", type(exc).__name__)
        outcome["ok"] = _search_warmup_job()
        try:
            first_request_warmup(searcher_ready=outcome["ok"])
        except Exception as exc:  # noqa: BLE001 - 첫 요청 준비는 덤이다. 예상 밖 오류도 서버 시작과 검색 준비 결과를 바꾸지 않는다
            log.warning("첫 요청 준비 실패 stage=first_request_warmup: %s", type(exc).__name__)

    t = threading.Thread(target=work, name="startup-warmup", daemon=True)
    started = time.perf_counter()
    t.start()
    t.join(timeout)
    if t.is_alive():
        log.warning("시작 준비가 %.0f초 안에 끝나지 않아 서버를 먼저 연다(뒤에서 계속) stage=startup_warmup elapsed_s=%.1f", timeout, time.perf_counter() - started)
        return False
    return outcome.get("ok", False)


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
    모델은 처음 부를 때 만든다(키 없이도 서버가 뜬다). 답 저장소는 `RECALL_STORE=postgres`면 Postgres, 아니면 메모리 구현이다."""
    from backend.graph.build import build_graph
    from backend.graph.departments.review import build_review_graph
    from backend.graph.service_profile import SharedChatModel, service_searches

    llm = SharedChatModel()
    review = build_review_graph(None, None, llm=llm, store=state.issue_store, approvals=state.decision_repo)
    return build_graph(None, state.checkpointer, llm=llm, store=state.store, answer_store=state.answer_store,
                       decision_repo=state.decision_repo, review_graph=review, **service_searches())   # 서비스 설정 61.51(backend/graph/service_profile.py)


@contextmanager
def open_question_runtime(app: FastAPI, graph_factory: Callable[[Any], Any], database_url: str | None) -> Iterator[None]:
    """`open_decision_runtime()` 안에서 부른다. 질문 그래프, 대화 목록 저장소, 답 저장소를 `app.state`에 둔다.

    체크포인터가 열리지 않았으면(DB 연결 실패) 아무것도 두지 않는다. `/chat`, `/threads`, `/me/memory`는 503 `not_configured`다."""
    from backend.graph.recall.runtime import make_answer_store

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
        state.answer_store = make_answer_store(database_url)   # 리콜이 지난 답을 찾는 저장소(backend/graph/recall/runtime.py)
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
    # 내 정보 저장소는 실제 사용자 저장소(users 외래키)와 짝. 시험이 가짜 사용자 저장소를 꽂으면 열지 않는다
    profile_store = PostgresProfileStore(database_url) if database_url and auth_store is None else None
    owner_login_id = os.getenv("PROVENA_OWNER_LOGIN_ID", "").strip()   # 시작할 때 한 번만 읽는다(바꾸려면 새 리비전)
    make_graph = graph_factory or build_question_graph

    def answer_store_fn():
        return getattr(app.state, "answer_store", None)   # 답 저장소는 lifespan 뒤에 열린다. get_grounding을 부를 때 읽는다

    mcp_app = create_mcp_app(answer_store_fn=answer_store_fn)

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        from backend.graph.service_profile import service_profile
        configure_app_logging()   # backend.* 로그를 INFO로(요청 로그·LLM 지연 로그가 운영 로그에 나오게)
        if graph_factory is None:
            warn_if_silent_demo()   # 배포에서 키가 빠져 조용히 가짜 모델로 도는 것을 시작 로그로 알린다(동작은 그대로)
        with service_profile(enabled=graph_factory is None):   # 서비스 기본 설정(61.51)을 환경 변수로 채운다. 시험이 그래프를 꽂으면 바꾸지 않는다
            if store is not None and is_local_demo():
                bootstrap_local_auth(store, profile_store)
            if store is not None:
                check_owner(store, owner_login_id)   # 알림만. 막는 곳은 요청마다 도는 최고 관리자 확인
            # 검색 준비: 운영은 시작 때 기다려 끝낸다(첫 /chat이 느려지지 않게). 환경 변수 SEARCH_WARMUP이 기본값을 덮는다
            warm_mode = search_warmup_mode(default_on=search_warmup_default_on(has_db=bool(database_url) and store is not None,
                                                                              graph_injected=graph_factory is not None))
            if warm_mode == "sync":
                from backend.services.llm import is_demo_mode
                await asyncio.to_thread(run_startup_warmup, preload_llm=graph_factory is None and not is_demo_mode())
            elif warm_mode == "background":
                start_search_warmup()
            with open_decision_runtime(app_) if store is not None else nullcontext():      # 체크포인터·결정표 저장소·승인 그래프
                with open_question_runtime(app_, make_graph, database_url) if store is not None else nullcontext():   # 질문 그래프·대화 목록
                    with open_recall_runtime(app_, database_url) if store is not None else nullcontext():   # 리콜·변경 감시
                        async with mcp_app.lifespan(app_) if mcp_app is not None else nullcontext():   # MCP 세션 관리자를 앱과 같이 켜고 끈다
                            yield

    # PROVENA_DOCS_PUBLIC=0 이면 /docs·/redoc·/openapi.json 을 끈다(A-07). 비우면 기존대로 공개
    docs_off = {} if os.environ.get("PROVENA_DOCS_PUBLIC", "1").strip().lower() not in ("0", "false", "no", "off") \
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="3차 프로젝트 API", lifespan=lifespan, **docs_off)
    app.add_middleware(RequestContextMiddleware)     # 요청 ID와 요청 로그(순수 ASGI, SSE를 버퍼링하지 않는다)
    install_error_handlers(app)                      # 오류 응답 규약

    react_index = WEB_DIR / "react-app" / "dist" / "index.html"
    app.state.react_index = react_index if react_index.is_file() else None

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

    @app.head("/health", include_in_schema=False)   # HEAD로 살아 있는지 보는 감시도 200을 받게 한다
    def health_head(background: BackgroundTasks) -> dict:
        return health(background)

    if store is not None:
        app.include_router(create_auth_router(store=store, secret=auth_secret, profile_completed=profile_store.exists if profile_store is not None else None,
                                              owner_check=owner_check_for(owner_login_id)))
        app.include_router(create_decision_router(store=store, secret=auth_secret))
        app.include_router(create_api_router(store=store, secret=auth_secret))   # /chat, /threads, /me/memory
        app.include_router(create_recall_router(store=store, secret=auth_secret))   # /recalls, /webhooks/regulation-updated 등(F-02)
        app.include_router(create_changes_router(store=store, secret=auth_secret))  # /changes(변경 감시)
        if profile_store is not None:   # 시험의 가짜 사용자 저장소일 땐 내 정보 API만 열지 않는다
            # 로그인·내 정보·사용자 관리 라우터가 같은 서명 키(auth_secret)를 쓴다(로컬 데모의 무작위 키 포함)
            cipher = ProfileCipher.from_env(allow_ephemeral=is_local_demo())
            app.include_router(create_profile_router(auth_store=store, profile_store=profile_store, cipher=cipher, secret=auth_secret))
            # 화면 주소도 /admin/users라 브라우저가 직접 열면(새로고침) React 화면을 내준다(app.state.react_index, 빌드 없으면 API 그대로)
        app.include_router(create_admin_router(store=store, owner_login_id=owner_login_id, secret=auth_secret,
                                               html_page=lambda: app.state.react_index))
        # 평가 전용(결정 0104, 사전 등록 62.41): 환경 변수 EVAL_REVIEW_SINGLE=1일 때만 열린다(꺼지면 404). 서비스 값에 넣지 않는다
        app.include_router(create_eval_review_router(store=store, secret=auth_secret))
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)          # 정적 파일 마운트(/)보다 먼저

    # 도메인 엔드포인트는 여기(아래 정적 파일 마운트보다 위)에 추가합니다.

    web_root = react_index.parent if app.state.react_index is not None else WEB_DIR
    if (web_root / "index.html").is_file() or (WEB_DIR / "login.html").is_file():

        @app.get("/", include_in_schema=False, response_model=None)
        def index() -> FileResponse | RedirectResponse:
            if app.state.react_index is not None:
                return FileResponse(app.state.react_index)
            return RedirectResponse("/login.html")

        if web_root != WEB_DIR:
            app.add_api_route("/login.html", lambda: FileResponse(web_root / "index.html"), methods=["GET"], include_in_schema=False)

            web_root_resolved = web_root.resolve()
            api_prefixes = ("auth", "api", "me", "health", "threads", "approvals", "mcp")
            spa_prefixes = ("login", "signup", "chat", "onboarding", "myinfo", "admin", "recalls", "changes", "demo")

        # 정적 파일 마운트(/)는 GET·HEAD만 받아 다른 메서드는 405가 된다. 맞는 경로가 하나도 없으면 모든 메서드를 404 not_found로,
        # 경로는 맞는데 메서드만 틀리면 405 method_not_allowed로 돌려준다(오류 응답 규약, K-12).
        @app.api_route("/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
        def unknown_path(request: Request) -> None:
            # 라우터가 감싸져 있어 route.methods를 읽을 수 없다 → 메서드를 하나씩 바꿔 가며 실제로 맞는 경로가 있는지 본다
            others = [r for r in request.app.router.routes if getattr(r, "path", None) != "/{path:path}" and not isinstance(r, Mount)]
            allowed = [m for m in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                       if any(r.matches({**request.scope, "method": m})[0] == Match.FULL for r in others)]
            if any(r.matches(request.scope)[0] != Match.NONE for r in others):
                raise HTTPException(status_code=405, detail="Method Not Allowed", headers={"Allow": ", ".join(allowed)} if allowed else None)
            raise ApiError(404, "not_found", "요청한 경로를 찾을 수 없습니다.")

        if web_root != WEB_DIR:
            @app.get("/{path:path}", include_in_schema=False)
            def spa_fallback(path: str, request: Request) -> FileResponse:
                first_segment = path.partition("/")[0]
                if first_segment in api_prefixes:
                    raise ApiError(404, "not_found", "요청한 경로를 찾을 수 없습니다.")   # 아래 404와 같은 한국어 문구
                candidate = (web_root / path).resolve()
                if web_root_resolved in candidate.parents and candidate.is_file():
                    return FileResponse(candidate)
                if first_segment in spa_prefixes:
                    return FileResponse(web_root / "index.html")
                if path == "favicon.ico" and (web_root / "favicon.svg").is_file():
                    return FileResponse(web_root / "favicon.svg", media_type="image/svg+xml")
                # 브라우저가 주소창으로 연 없는 화면 주소는 React 화면(404 안내)을 404 상태로 내준다. API 호출은 아래 JSON 규약 그대로(H-27)
                if "text/html" in request.headers.get("accept", ""):
                    return FileResponse(web_root / "index.html", status_code=404)
                raise ApiError(404, "not_found", "요청한 경로를 찾을 수 없습니다.")
        app.mount("/", StaticFiles(directory=web_root), name="web")

    return app


app = create_app()
