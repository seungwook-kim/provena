"""변경 감시: 증분 수집이 쌓은 바뀐 섹션(`changed_articles`)과 실행 기록(`sync_runs`)을 화면·리콜 처리기에 내주고, 감시 스위치를 둔다.

- 읽기: `GET /changes`, `GET /changes/{event_id}`가 쓴다. 기준 날짜는 새 판 날짜이고, 쪽 통째 삭제는 새 판이 없어 그 줄을 적은 날로 본다
  (`backend/rag/ingest/changes.py`와 같은 규칙). 최근 것이 앞이다.
- 처리 대기: 리콜 처리기(`process_pending.py`)가 `status = pending`인 줄을 읽고 `sent`·`failed`로 바꾼다. 이 칸은 리콜 쪽이 바꾸는 칸이다(202_sync.sql).
- 감시 스위치: `change_monitoring` 한 줄(120_answers_recall.sql). `paused`면 증분 수집이 noop(paused)으로 끝난다(schedule.py). 표가 없으면 `active`다.

`PgChangeStore`는 `DATABASE_URL`이 있을 때 쓴다(앱이 직접 쓰는 표가 아니라 수집 작업이 쓰는 표를 읽는다). DB가 없으면 `InMemoryChangeStore`(빈 목록).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from backend.rag.ingest.schedule import JOB, event_id
from backend.schemas.recall import ChangedArticle

STATUSES = ("pending", "sent", "failed")
MONITORING = ("active", "paused")
CHANGE_COLUMNS = ("event_id", "rule_seq", "article", "page_title", "old_version_date", "new_version_date", "change_type", "status",
                  "created_at", "source_url")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def changed_of(row: dict) -> ChangedArticle:
    return ChangedArticle(rule_seq=int(row["rule_seq"]), article=row["article"], old_version_date=row["old_version_date"] or "",
                          new_version_date=row["new_version_date"] or "", change_type=row["change_type"])


def day_of(row: dict) -> str:
    """기준 날짜(YYYY-MM-DD): 새 판 날짜, 없으면 그 줄을 적은 날(UTC)."""
    return (row.get("new_version_date") or str(row.get("created_at") or "")[:10])


class InMemoryChangeStore:
    """DB 없는 로컬·시험용. `add`로 줄을 넣는다(시험, `POST /webhooks/regulation-updated`가 아니라 수집 흉내)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.rows: dict[str, dict] = {}
        self.runs: list[dict] = []
        self.monitoring = {"status": "active", "updated_by": None, "updated_at": None}

    def add(self, changed: ChangedArticle | dict, *, status: str = "pending", page_title: str | None = None,
            source_url: str | None = None, created_at: str | None = None) -> dict:
        ch = changed if isinstance(changed, ChangedArticle) else ChangedArticle.model_validate(changed)
        row = {"event_id": event_id(ch.model_dump()), **ch.model_dump(), "page_title": page_title, "status": status,
               "created_at": created_at or _now(), "source_url": source_url}
        with self._lock:
            self.rows.setdefault(row["event_id"], row)
            return dict(self.rows[row["event_id"]])

    def changes(self, since: str, limit: int, offset: int = 0) -> tuple[list[dict], bool]:
        with self._lock:
            rows = sorted((r for r in self.rows.values() if day_of(r) >= since),
                          key=lambda r: (day_of(r), r["created_at"], r["event_id"]), reverse=True)
        page = rows[offset: offset + limit + 1]
        return [dict(r) for r in page[:limit]], len(page) > limit

    def count_by_type(self, since: str) -> dict[str, int]:
        """since 이후 전체 바뀐 섹션 수를 종류(change_type)별로 센다. 목록 쪽수(limit)와 무관한 전체 기준이다."""
        with self._lock:
            out: dict[str, int] = {}
            for r in self.rows.values():
                if day_of(r) >= since:
                    out[r["change_type"]] = out.get(r["change_type"], 0) + 1
            return out

    def get(self, event_id_: str) -> dict | None:
        with self._lock:
            r = self.rows.get(event_id_)
            return dict(r) if r else None

    def last_run(self) -> dict | None:
        ok = [r for r in self.runs if r.get("status") in ("succeeded", "noop")]
        return dict(ok[-1]) if ok else None

    def pending(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = sorted((r for r in self.rows.values() if r["status"] == "pending"), key=lambda r: (r["created_at"], r["event_id"]))
            return [dict(r) for r in rows[:limit]]

    def set_status(self, event_id_: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"status는 {', '.join(STATUSES)} 중 하나: {status!r}")
        with self._lock:
            if event_id_ in self.rows:
                self.rows[event_id_]["status"] = status

    def monitoring_get(self) -> dict:
        with self._lock:
            return dict(self.monitoring)

    def monitoring_set(self, status: str, by: str | None) -> dict:
        if status not in MONITORING:
            raise ValueError(f"status는 {', '.join(MONITORING)} 중 하나: {status!r}")
        with self._lock:
            self.monitoring = {"status": status, "updated_by": by, "updated_at": _now()}
            return dict(self.monitoring)


_DAY = "COALESCE(NULLIF(ca.new_version_date, '')::date, (ca.created_at AT TIME ZONE 'UTC')::date)"
_SELECT = f"""SELECT ca.event_id, ca.rule_seq, ca.article, d.title AS page_title, ca.old_version_date, ca.new_version_date,
       ca.change_type, ca.status, ca.created_at, d.source_url
FROM changed_articles ca LEFT JOIN docs d ON d.rule_seq = ca.rule_seq"""


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


class PgChangeStore:
    """`changed_articles`·`sync_runs`(202_sync.sql), `docs`(201_search.sql), `change_monitoring`(120_answers_recall.sql)."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn 또는 connect가 필요하다")
            connect = _default_connect(dsn)
        self._connect = connect

    def _q(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        from psycopg.rows import dict_row

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        return [{k: _iso(v) for k, v in r.items()} for r in rows]

    def _has(self, table: str) -> bool:
        return bool(self._q("SELECT to_regclass(%s) IS NOT NULL AS ok", (table,))[0]["ok"])

    def changes(self, since, limit, offset=0):
        if not self._has("changed_articles"):
            return [], False
        rows = self._q(f"{_SELECT} WHERE {_DAY} >= %(since)s::date ORDER BY {_DAY} DESC, ca.created_at DESC, ca.event_id DESC "
                       "LIMIT %(limit)s OFFSET %(offset)s", {"since": since, "limit": limit + 1, "offset": offset})
        return rows[:limit], len(rows) > limit

    def count_by_type(self, since):
        if not self._has("changed_articles"):
            return {}
        rows = self._q(f"SELECT ca.change_type, COUNT(*) AS n FROM changed_articles ca WHERE {_DAY} >= %(since)s::date GROUP BY ca.change_type",
                       {"since": since})
        return {r["change_type"]: int(r["n"]) for r in rows}

    def get(self, event_id_):
        if not self._has("changed_articles"):
            return None
        rows = self._q(f"{_SELECT} WHERE ca.event_id = %s", (event_id_,))
        return rows[0] if rows else None

    def last_run(self):
        if not self._has("sync_runs"):
            return None
        rows = self._q("SELECT run_id, status, finished_at, to_commit, list_complete FROM sync_runs WHERE job = %s "
                       "AND status IN ('succeeded', 'noop') ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1", (JOB,))
        return rows[0] if rows else None

    def pending(self, limit=50):
        if not self._has("changed_articles"):
            return []
        return self._q(f"{_SELECT} WHERE ca.status = 'pending' ORDER BY ca.created_at, ca.event_id LIMIT %s", (limit,))

    def set_status(self, event_id_, status):
        if status not in STATUSES:
            raise ValueError(f"status는 {', '.join(STATUSES)} 중 하나: {status!r}")
        self._q("UPDATE changed_articles SET status = %s WHERE event_id = %s", (status, event_id_))

    def monitoring_get(self):
        if not self._has("change_monitoring"):
            return {"status": "active", "updated_by": None, "updated_at": None}
        rows = self._q("SELECT status, updated_by, updated_at FROM change_monitoring WHERE id = 1")
        return rows[0] if rows else {"status": "active", "updated_by": None, "updated_at": None}

    def monitoring_set(self, status, by):
        if status not in MONITORING:
            raise ValueError(f"status는 {', '.join(MONITORING)} 중 하나: {status!r}")
        return self._q("INSERT INTO change_monitoring (id, status, updated_by, updated_at) VALUES (1, %s, %s, now()) "
                       "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_by = EXCLUDED.updated_by, updated_at = now() "
                       "RETURNING status, updated_by, updated_at", (status, by))[0]
