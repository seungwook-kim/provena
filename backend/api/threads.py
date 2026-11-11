"""사용자별 대화(thread) 목록 저장소 (G4, SDD 4-4 `/threads`). 표는 `db/111_threads.sql`이다.

규칙
- 열쇠는 `(user_id, thread_id)`다. `thread_id`는 화면이 보낸(또는 서버가 만든) 바깥 이름이고, 그래프와 체크포인트에는 `<user_id>:<thread_id>`를 쓴다.
  같은 `t1`도 사용자마다 다른 줄이다.
- 모든 조회와 갱신에 `user_id` 조건을 붙인다. 남의 thread는 없는 것과 같다(라우터가 404로 돌려준다).
- `thread_touch`는 UPSERT다. 제목은 처음 만들 때의 첫 질문 앞 80자로 정하고 뒤에는 바꾸지 않는다. `status`, `last`는 준 값만 바꾼다.
- `status`: `idle` | `running` | `pending_approval`. `last`: 마지막 답 `{kind, answer, answer_id, as_of}`.
- 대화 내용 전체는 여기에 두지 않는다(체크포인트에 있다). 상세 조회는 마지막 답 하나만 준다.
- Postgres 구현은 호출마다 연결하고 준비된 문장을 끈다(`prepare_threshold=None`). Supabase 풀러(transaction 모드)가 준비된 문장을 쓰지 못한다.
  `ANSWER_STORE_REUSE_CONN=1`이면 답 저장소와 같은 방식으로 연결을 프로세스 안에서 다시 쓰고(`graph/answer_store.py` `_ConnectionReuse`), 서버가 끊은 연결이면
  한 번 더 부른다(문장 셋 모두 같은 값을 두 번 읽거나 써도 같다: 조회 둘과 UPSERT). 꺼져 있으면 지금처럼 호출마다 연결한다(사전 등록 62.40).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "111_threads.sql"
TITLE_MAX = 80
STATUSES = ("idle", "running", "pending_approval")
_COLUMNS = "thread_id, title, status, last, created_at, updated_at"


def thread_title(message: str | None) -> str:
    return " ".join((message or "").split())[:TITLE_MAX]


def _check_status(status: str | None) -> None:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status는 {', '.join(STATUSES)} 중 하나다: {status!r}")


class ThreadStore(Protocol):
    def thread_touch(self, user_id: str, thread_id: str, *, title: str | None = None, status: str | None = None,
                     last: dict | None = None) -> None: ...

    def thread_get(self, user_id: str, thread_id: str) -> dict | None: ...

    def threads_of(self, user_id: str) -> list[dict]: ...


class InMemoryThreadStore:
    """시험과 로컬(메모리 체크포인터)용. 프로세스가 끝나면 사라진다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], dict] = {}
        self._seq = 0

    def thread_touch(self, user_id: str, thread_id: str, *, title: str | None = None, status: str | None = None,
                     last: dict | None = None) -> None:
        _check_status(status)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._seq += 1
            row = self._rows.get((user_id, thread_id))
            if row is None:
                row = {"thread_id": thread_id, "title": thread_title(title), "status": status or "idle", "last": None,
                       "created_at": now, "updated_at": now}
                self._rows[(user_id, thread_id)] = row
            if status is not None:
                row["status"] = status
            if last is not None:
                row["last"] = dict(last)
            row["updated_at"] = now
            row["_seq"] = self._seq

    def thread_get(self, user_id: str, thread_id: str) -> dict | None:
        with self._lock:
            row = self._rows.get((user_id, thread_id))
            return None if row is None else {k: v for k, v in row.items() if not k.startswith("_")}

    def threads_of(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = sorted((r for (u, _), r in self._rows.items() if u == user_id), key=lambda r: r["_seq"], reverse=True)
            return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    from backend.graph.answer_store import reuse_if_enabled

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return reuse_if_enabled(connect)   # 62.40: 같은 스위치(ANSWER_STORE_REUSE_CONN)로 켜진다


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _row(r: dict) -> dict:
    return {"thread_id": r["thread_id"], "title": r["title"], "status": r["status"], "last": r.get("last"),
            "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])}


class PostgresThreadStore:
    """`db/111_threads.sql`의 `threads` 표 위의 구현. `connect`는 시험에서 가짜 연결을 넣는 자리다."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn 또는 connect가 필요하다")
            connect = _default_connect(dsn)
        self._connect = connect

    def _fetch(self, sql: str, params: tuple) -> list[dict]:
        from psycopg.rows import dict_row

        from backend.graph.answer_store import run_again

        def run() -> list[dict]:
            with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []

        return run_again(self._connect, run)   # 다시 쓰는 연결이 끊겨 있었으면 새 연결로 한 번 더

    def ensure_schema(self) -> None:
        """로컬 데모에서만 부른다(이미 만든 볼륨에도 표를 만든다). 운영에서는 `db/db.md` 절차대로 SQL을 직접 실행한다."""
        with self._connect() as conn:
            conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    def thread_touch(self, user_id: str, thread_id: str, *, title: str | None = None, status: str | None = None,
                     last: dict | None = None) -> None:
        from psycopg.types.json import Jsonb

        _check_status(status)
        doc = Jsonb(last) if last is not None else None
        self._fetch(
            "INSERT INTO threads AS t (user_id, thread_id, title, status, last) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, thread_id) DO UPDATE SET status = COALESCE(%s, t.status), last = COALESCE(%s, t.last), updated_at = now()",
            (user_id, thread_id, thread_title(title), status or "idle", doc, status, doc),
        )

    def thread_get(self, user_id: str, thread_id: str) -> dict | None:
        rows = self._fetch(f"SELECT {_COLUMNS} FROM threads WHERE user_id = %s AND thread_id = %s", (user_id, thread_id))
        return _row(rows[0]) if rows else None

    def threads_of(self, user_id: str) -> list[dict]:
        rows = self._fetch(f"SELECT {_COLUMNS} FROM threads WHERE user_id = %s ORDER BY updated_at DESC, created_at DESC", (user_id,))
        return [_row(r) for r in rows]
