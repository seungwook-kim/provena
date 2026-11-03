"""바뀐 섹션 목록 읽기 `list_changed` (docs/specs/mcp.md How 2). SELECT만 한다.

증분 수집(schedule.py)이 changed_articles에 쓴 줄을 새 판 날짜 >= since 로 읽고(쪽 통째 삭제는 새 판이 없어 적은 날로), 마지막 성공 실행(sync_runs
status IN succeeded·noop)을 함께 돌려준다. 실행 기록이 아예 없으면 last_run=None — "바뀐 것 없음"(빈 목록 + 실행 있음)과
가른다(EC-06). changed_articles.status(pending·sent·failed)는 리콜 쪽이 바꾸는 칸이라 여기서 건드리지 않는다.
"""
from __future__ import annotations

import os
import threading
from typing import Protocol

from pydantic import BaseModel

from backend.rag.ingest.schedule import JOB
from backend.rag.retrieve.section import check_date
from backend.schemas.recall import ChangedArticle

MAX_LIMIT = 200


class LastRun(BaseModel):
    run_id: int
    status: str                 # succeeded | noop
    finished_at: str | None     # ISO 시각(UTC)
    to_commit: str | None
    list_complete: bool | None  # False면 삭제 보류(사라진 섹션이 목록에 아직 없을 수 있다, EC-07)


class ChangesStore(Protocol):
    def rows(self, since: str, org: str | None, limit: int) -> list[dict]: ...
    def last_run(self) -> dict | None: ...


def list_changed(since: str, org: str | None = None, limit: int = MAX_LIMIT,
                 store: ChangesStore | None = None) -> tuple[list[ChangedArticle], LastRun | None]:
    if since is None:
        raise ValueError("since는 꼭 준다(YYYY-MM-DD)")
    check_date(since, "since")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit는 1~{MAX_LIMIT}: {limit!r}")
    st = store or default_store()
    run = st.last_run()
    items = [ChangedArticle(**r) for r in st.rows(since, org, limit)]
    return items, (LastRun(**run) if run else None)


# 기준 날짜 = 새 판 날짜. 쪽 통째 삭제는 새 판이 없어 new_version_date가 빈 칸(diff.py) → 그 줄을 적은 날(UTC)로 본다(EC-13).
_DAY = "COALESCE(NULLIF(ca.new_version_date, '')::date, (ca.created_at AT TIME ZONE 'UTC')::date)"


class PgChangesStore:
    def __init__(self, url: str):
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(url, min_size=1, max_size=2, open=True, kwargs={"prepare_threshold": None})

    def _all(self, sql: str, params: dict) -> list[tuple]:
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def rows(self, since, org, limit):
        rows = self._all(f"""SELECT ca.rule_seq, ca.article, ca.old_version_date, ca.new_version_date, ca.change_type
FROM changed_articles ca
WHERE {_DAY} >= %(since)s::date
  AND (%(org)s::text IS NULL OR EXISTS (SELECT 1 FROM docs d WHERE d.rule_seq = ca.rule_seq AND d.org = %(org)s::text))
ORDER BY {_DAY}, ca.rule_seq, ca.article, ca.change_type
LIMIT %(limit)s""", {"since": since, "org": org, "limit": limit})
        cols = ("rule_seq", "article", "old_version_date", "new_version_date", "change_type")
        return [dict(zip(cols, r)) for r in rows]

    def last_run(self):
        rows = self._all("""SELECT run_id, status, finished_at, to_commit, list_complete FROM sync_runs
WHERE job = %(job)s AND status IN ('succeeded', 'noop')
ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1""", {"job": JOB})
        if not rows:
            return None
        run_id, status, fin, commit, complete = rows[0]
        return {"run_id": run_id, "status": status, "finished_at": fin.isoformat() if fin else None,
                "to_commit": commit, "list_complete": complete}


_store: PgChangesStore | None = None
_lock = threading.Lock()


def default_store() -> PgChangesStore:
    global _store
    with _lock:
        if _store is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL이 없다")
            _store = PgChangesStore(url)
    return _store
