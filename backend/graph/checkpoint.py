"""체크포인터와 Store 만들기 (B-09, D-08). SDD 4-3 "체크포인트와 재시작", 가이드 p.7, p.22 질문 8.

- 배포·시연은 Postgres 체크포인터다. 사람 승인(interrupt)에서 멈춘 그래프는 서버를 다시 띄운 뒤에도 같은 `thread_id`로 이어진다.
- 메모리 체크포인터는 시험과 로컬 개발용이다. 프로세스가 끝나면 사라지므로 "재시작해도 된다"의 근거로 쓰지 않는다
  (`is_restart_safe()`가 거짓이다).
- `open_persistence()`가 체크포인트 표와 Store 표를 만든다(`.setup()`, 여러 번 돌려도 된다). 접속 문자열은 로그에 쓰지 않는다.
- 그 표에는 대화 내용이 들어가므로 만든 직후 RLS를 켠다(`enable_rls`). 정책은 두지 않는다(`db/201_search.sql`과 같은 방식): 공개 키 역할은 막히고, 표 소유자인 앱은 그대로 쓴다.
- Postgres 쪽 패키지(`langgraph-checkpoint-postgres`, `psycopg`)는 Postgres를 고를 때만 불러온다.

선택 규칙: 환경변수 `CHECKPOINTER`가 `memory` 또는 `postgres`면 그대로. 비어 있으면 `DATABASE_URL`이 있을 때 postgres, 없으면 memory.
`CHECKPOINTER=postgres`인데 `DATABASE_URL`이 없으면 조용히 메모리로 내려가지 않고 오류로 멈춘다.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

KINDS = ("memory", "postgres")
POOL_MIN = 1
POOL_MAX = 4
LANGGRAPH_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations", "store", "store_migrations")


def checkpointer_kind(env: Mapping[str, str] | None = None) -> str:
    """`memory` 또는 `postgres`. 규칙은 모듈 설명."""
    env = os.environ if env is None else env
    kind = (env.get("CHECKPOINTER") or "").strip().lower()
    if kind:
        if kind not in KINDS:
            raise ValueError(f"CHECKPOINTER는 {' 또는 '.join(KINDS)} 여야 합니다")
        return kind
    return "postgres" if (env.get("DATABASE_URL") or "").strip() else "memory"


def is_restart_safe(checkpointer: Any) -> bool:
    """서버를 다시 띄워도 이 체크포인터의 대화가 남는가. 메모리 체크포인터는 거짓이다."""
    return type(checkpointer).__name__ == "PostgresSaver"


def enable_rls(pool: Any) -> None:
    """LangGraph 표에 RLS를 켠다. 이미 켜진 표는 건드리지 않아 잠금 없이 여러 번 돌릴 수 있다.

    FORCE를 쓰지 않으므로 표 소유자(앱)는 막히지 않는다. 표가 없으면 패키지 버전이 바뀌어 표 이름이 달라진 것이므로 조용히 넘어가지 않고 멈춘다.
    """
    with pool.connection() as conn:
        for table in LANGGRAPH_TABLES:
            row = conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(%s)", (table,)).fetchone()
            if row is None:
                raise RuntimeError(f"RLS를 켤 표가 없습니다: {table}. langgraph-checkpoint-postgres 버전이 바뀌었는지 확인하세요")
            if not row["relrowsecurity"]:
                conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


@contextmanager
def open_persistence(
    kind: str | None = None,
    database_url: str | None = None,
    *,
    setup: bool = True,
    env: Mapping[str, str] | None = None,
) -> Iterator[tuple[Any, Any]]:
    """`(checkpointer, store)`를 돌려주고, 블록이 끝나면 연결을 닫는다.

    `build_graph(checkpointer=..., store=...)`에 그대로 넘긴다. 앱 시작(lifespan)에서 한 번 열고 끝날 때 닫는다.
    """
    env = os.environ if env is None else env
    kind = kind or checkpointer_kind(env)
    if kind not in KINDS:
        raise ValueError(f"kind는 {' 또는 '.join(KINDS)} 여야 합니다")

    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        log.warning("메모리 체크포인터: 서버를 다시 띄우면 승인 대기 중이던 대화가 사라집니다(시험·로컬 전용)")
        yield InMemorySaver(), InMemoryStore()
        return

    url = (database_url or env.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("Postgres 체크포인터에는 DATABASE_URL이 필요합니다")

    # 지연 import: 메모리로 쓰는 쪽(시험·로컬)은 psycopg 없이도 돈다
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # autocommit: setup()의 마이그레이션이 필요로 한다.
    # prepare_threshold=None: 준비된 문장을 쓰지 않는다. Supabase 풀러(트랜잭션 모드)는 요청마다 서버 연결이 바뀌어
    # 준비된 문장을 찾지 못한다("prepared statement ... does not exist"). 0은 "처음부터 준비"라 반대 동작이다.
    pool = ConnectionPool(
        url,
        min_size=POOL_MIN,
        max_size=POOL_MAX,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        open=False,
    )
    pool.open(wait=True, timeout=15)
    try:
        saver = PostgresSaver(pool)
        store = PostgresStore(pool)
        if setup:
            saver.setup()
            store.setup()
            enable_rls(pool)
        yield saver, store
    finally:
        pool.close()
