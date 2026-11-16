"""리콜·변경 감시 실행 환경을 환경변수로 조립한다(앱 시작, 명령줄 처리기 공통).

- `RECALL_STORE=postgres`: 답·인용(`PgAnswerStore`)과 리콜 저장소(`PgRecallStore`)를 `DATABASE_URL`의 표(`db/120_answers_recall.sql`)에 둔다.
  비우면(기본) 메모리 저장소라 재시작하면 지난 답과 알림이 사라진다(지금까지의 동작).
- `DATABASE_URL`이 있으면 바뀐 섹션 목록(`changed_articles`), 섹션 원문(`get_section`), 링크 그래프(`chunks.link_targets`), 문서 권한(`chunks.acl`)을
  같은 DB에서 읽는다. 없으면 빈 목록·원문 없음·후보 없음·공개다.
- 로컬 데모 모드(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`)에서 `RECALL_STORE=postgres`면 시작할 때 120 SQL을 실행한다(운영은 db/db.md 절차).
- 키 없는 로컬 데모(로컬 데모 모드 + LLM 데모 모드)는 시작할 때 가상 개정 한 건을 처리 대기로 넣고, 섹션 읽기가 그 개정본을 돌려준다(`demo_change.py`, 2026-11-16).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.graph.answer_store import InMemoryAnswerStore, PgAnswerStore
from backend.graph.recall.acl import PgAcl, PublicAcl
from backend.graph.recall.maintenance import PgLinks
from backend.graph.recall.monitor import InMemoryChangeStore, PgChangeStore
from backend.graph.recall.service import RecallService
from backend.graph.recall.store import InMemoryRecallStore, PgRecallStore
from backend.graph.recall.webhook import WebhookSender

log = logging.getLogger(__name__)

STORE_ENV = "RECALL_STORE"
SCHEMA_FILE = Path(__file__).resolve().parents[3] / "db" / "120_answers_recall.sql"


def use_postgres() -> bool:
    return (os.environ.get(STORE_ENV) or "").strip().lower() == "postgres" and bool((os.environ.get("DATABASE_URL") or "").strip())


def make_answer_store(database_url: str | None = None) -> Any:
    """답 저장소. RECALL_STORE=postgres면 Postgres, 아니면 메모리."""
    url = database_url or os.environ.get("DATABASE_URL")
    return PgAnswerStore(url) if use_postgres() and url else InMemoryAnswerStore()


def ensure_schema(database_url: str) -> None:
    import psycopg

    with psycopg.connect(database_url, autocommit=True, connect_timeout=5, prepare_threshold=None) as conn:
        conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


def section_reader(database_url: str | None = None):
    """(rule_seq, article, as_of) -> 섹션 dict(text, source_url, version_id, version_date ...) 또는 None. 비공개 주소는 가린다.

    증분 수집은 새 판의 유효 시작을 동결 기준일 다음 날보다 앞으로 두지 않는다(schedule.FLOOR). 그래서 그보다 이른 새 판 날짜로 읽으면
    옛 판이 나온다. 돌려받은 판 날짜가 요청 날짜보다 이르면 FLOOR 날짜로 한 번 더 읽는다."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        return None
    from backend.rag.ingest.schedule import FLOOR
    from backend.rag.retrieve.privacy import redact_chunk
    from backend.rag.retrieve.section import get_section

    floor = FLOOR.isoformat()

    def read(rule_seq: int, article: str, as_of: str | None) -> dict | None:
        try:
            s = get_section(int(rule_seq), article, as_of)
            if s is not None and as_of and s.version_date < as_of < floor:
                later = get_section(int(rule_seq), article, floor)
                s = later if later is not None and later.version_date > s.version_date else s
        except Exception as e:  # noqa: BLE001 - 원문을 못 읽으면 없는 것으로 본다(지문 불일치 포함). 종류만 남긴다
            log.warning("섹션 원문을 읽지 못함: %s", type(e).__name__)
            return None
        return redact_chunk(s.model_dump()) if s is not None else None

    return read


def keyless_demo() -> bool:
    """키 없는 로컬 데모(로컬 데모 모드이고 LLM 데모 모드). 이때만 가상 개정 한 건(`demo_change.py`)을 쓴다."""
    from backend.services.demo_seed import is_local_demo
    from backend.services.llm import is_demo_mode

    return is_local_demo() and is_demo_mode()


def build_service(*, answers: Any, database_url: str | None = None, store: Any = None) -> RecallService:
    url = database_url or os.environ.get("DATABASE_URL")
    store = store if store is not None else (PgRecallStore(url) if use_postgres() and url else InMemoryRecallStore())
    read = section_reader(url)
    if keyless_demo():
        from backend.graph.recall.demo_change import load_demo_change, with_demo_revision

        read = with_demo_revision(read, load_demo_change())
    return RecallService(
        store=store, answers=answers, read_section=read,
        links=PgLinks(url) if url else None, acl=PgAcl(url) if url else PublicAcl(), sender=WebhookSender(store),
    )


def make_change_store(database_url: str | None = None) -> Any:
    url = database_url or os.environ.get("DATABASE_URL")
    return PgChangeStore(url) if url else InMemoryChangeStore()


def build_service_from_env() -> RecallService:
    """명령줄 처리기용(`process_pending`, `digest`). 답 저장소도 환경변수대로 연다."""
    return build_service(answers=make_answer_store())


@contextmanager
def open_recall_runtime(app: Any, database_url: str | None) -> Iterator[None]:
    """앱 시작(lifespan)에서 부른다. `app.state.recall_service`, `app.state.change_store`를 둔다. 답 저장소는 질문 그래프와 같은 것을 쓴다."""
    from backend.services.demo_seed import is_local_demo

    state = app.state
    try:
        if use_postgres() and database_url and is_local_demo():
            try:
                ensure_schema(database_url)   # 로컬 데모만: 이미 만든 볼륨에도 리콜 표를 만든다
            except Exception as exc:  # noqa: BLE001 - 접속 문자열이 섞일 수 있어 종류만 남긴다
                log.warning("리콜 표를 만들지 못함: %s", type(exc).__name__)
        answers = getattr(state, "answer_store", None)
        if answers is None:
            answers = make_answer_store(database_url)
        state.recall_service = build_service(answers=answers, database_url=database_url)
        state.change_store = make_change_store(database_url)
        if database_url and keyless_demo():
            from backend.graph.recall.demo_change import load_demo_change, seed_pending_change

            rec = load_demo_change()
            if rec is not None:
                try:   # 메모리 리콜 저장소는 다시 시작하면 알림이 비므로 가상 개정도 처리 대기로 되돌린다
                    seed_pending_change(database_url, rec, reset=not use_postgres())
                except Exception as exc:  # noqa: BLE001 - 접속 문자열이 섞일 수 있어 종류만 남긴다. 데모 개정이 없어도 서버는 뜬다
                    log.warning("데모 가상 개정을 넣지 못함: %s", type(exc).__name__)
        yield
    finally:
        state.recall_service = state.change_store = None
