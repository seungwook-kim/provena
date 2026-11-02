"""FastAPI 진입점.

그래프(backend/graph), 검색(backend/rag), 로그인(backend/auth.py)은 각자 자리에서 만들고
여기서는 엔드포인트로 연결만 합니다. LLM 호출은 services/llm.py 한 곳에서만 합니다.

- `/health`는 항상 있습니다(DB 없이도).
- `DATABASE_URL`이 있으면 로그인 라우터(`/auth/csrf`, `/auth/login`, `/auth/logout`, `/me`)를 붙입니다.
  이때 `AUTH_SECRET`(32바이트 이상)이 없으면 시작하지 않습니다. 로컬 데모 모드에서만 비어 있으면 실행마다 무작위로 만듭니다.
- `PROVENA_ENV=local` 이고 `PROVENA_DEV_MODE=1` 일 때만 시작할 때 users 테이블을 만들고 데모 계정 2개를 시드합니다
  (backend/services/demo_seed.py). 그 밖의 모드에서는 스키마(db/101_auth_users.sql)가 미리 적용돼 있어야 합니다.
- `web/`의 정적 파일(현재 로그인 화면)을 `/`에서 내줍니다. API 경로가 먼저 잡히도록 마지막에 붙입니다.
- `SEARCH_WARMUP=1`이면 시작할 때 검색 모델·BM25를 백그라운드로 올립니다(docs/specs/search.md). 실패해도 서버는 뜨고,
  검색은 첫 요청 때 다시 준비를 시도합니다. compose의 `loader`가 색인을 적재한 뒤 api가 뜹니다.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import create_auth_router
from backend.services.auth_store import PostgresAuthStore
from backend.services.demo_seed import is_local_demo, seed_demo_accounts

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
BOOTSTRAP_TRIES = 10
BOOTSTRAP_WAIT_SECONDS = 2.0


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


def create_app() -> FastAPI:
    database_url = os.getenv("DATABASE_URL")
    store = PostgresAuthStore(database_url) if database_url else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if store is not None and is_local_demo():
            bootstrap_local_auth(store)
        start_search_warmup()
        yield

    app = FastAPI(title="3차 프로젝트 API", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        """평가자와 배포 환경이 서비스 상태를 확인하는 곳. 지우지 마세요."""
        return {"status": "ok"}

    if store is not None:
        app.include_router(create_auth_router(store=store, secret=resolve_auth_secret()))

    # TODO: 도메인 엔드포인트를 여기에 추가하세요 (아래 정적 파일 마운트보다 위에).
    #   - 질의 엔드포인트: 로그인한 사용자 id로 thread를 정하고 그래프를 호출합니다
    #   - 오류 응답 규약을 정합니다 (검색 결과 없음, 승인 대기 중, 한도 초과 등을 구분)
    #   - 요청 ID, 사용 모델, 토큰 수, 지연 시간을 로그에 남깁니다

    if (WEB_DIR / "login.html").is_file():

        @app.get("/", include_in_schema=False)
        def index() -> RedirectResponse:
            return RedirectResponse("/login.html")

        app.mount("/", StaticFiles(directory=WEB_DIR), name="web")

    return app


app = create_app()
