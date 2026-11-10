"""쟁점표 저장소 (F-03, B-11, 미정 P-03 추천안). 사람 승인 뒤에만 `save`가 불린다.

`IssueTableStore` Protocol을 지키면 인메모리와 Postgres를 바꿔 끼울 수 있다. 스키마는 `db/110_issue_tables.sql`이다.
- `save`: 같은 `approval_id`로 다시 불려도 한 건만 남는다(재개가 겹쳐도 중복 저장 없음). table_id를 돌려준다.
- `record_rejection`: 반려 사유만 남기고 쟁점표는 저장하지 않는다. Postgres 는 별도 표 없이 승인함 `approvals` 의 같은 `approval_id` 줄에 사유를 쓴다.
- `get_by_thread`: 요청한 사용자가 자기 쟁점표를 확인한다(Happy Path 8). 다른 사용자 것은 돌려주지 않는다.
Postgres 구현은 연결 만드는 함수를 주입받는다(`backend/services/auth_store.py`와 같은 방식, 호출마다 열고 닫음).
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IssueTableStore(Protocol):
    def save(self, *, approval_id: str, thread_id: str, user_id: str, request: str, as_of: str | None,
             rows: list[dict], unreviewed: list[dict], approved_by: str | None) -> str: ...

    def record_rejection(self, *, approval_id: str, thread_id: str, user_id: str, reason: str, decided_by: str | None) -> None: ...

    def get_by_thread(self, thread_id: str, user_id: str) -> dict | None: ...


class InMemoryIssueTableStore:
    """시험·데모용. `tables`는 저장된 쟁점표(승인된 것만), `rejections`는 반려 기록이다."""

    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}  # approval_id -> 표
        self.rejections: dict[str, dict] = {}

    def save(self, *, approval_id, thread_id, user_id, request, as_of, rows, unreviewed, approved_by):
        if approval_id in self.tables:
            return self.tables[approval_id]["table_id"]
        table_id = str(uuid.uuid4())
        self.tables[approval_id] = {
            "table_id": table_id, "approval_id": approval_id, "thread_id": thread_id, "user_id": user_id, "request": request,
            "as_of": as_of, "rows": json.loads(json.dumps(rows)), "unreviewed": json.loads(json.dumps(unreviewed)),
            "approved_by": approved_by, "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        return table_id

    def record_rejection(self, *, approval_id, thread_id, user_id, reason, decided_by):
        self.rejections.setdefault(approval_id, {
            "approval_id": approval_id, "thread_id": thread_id, "user_id": user_id, "reason": reason, "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        })

    def get_by_thread(self, thread_id, user_id):
        for t in reversed(list(self.tables.values())):  # Postgres 구현과 같이 최신부터
            if t["thread_id"] == thread_id and t["user_id"] == user_id:
                return t
        return None


class PgIssueTableStore:
    """Postgres 구현. `connect()`는 autocommit 연결 하나를 돌려주는 함수다. 실제 DB 시험은 `tests/test_decision_approval.py`의 `test_postgres_*`다."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def save(self, *, approval_id, thread_id, user_id, request, as_of, rows, unreviewed, approved_by):
        sql = (
            "INSERT INTO issue_tables (approval_id, thread_id, user_id, request, as_of, issue_rows, unreviewed, approved_by) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
            "ON CONFLICT (approval_id) DO UPDATE SET approval_id = EXCLUDED.approval_id RETURNING table_id"
        )
        params = (approval_id, thread_id, user_id, request, as_of, json.dumps(rows, ensure_ascii=False),
                  json.dumps(unreviewed, ensure_ascii=False), approved_by)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return str(row[0])

    def record_rejection(self, *, approval_id, thread_id, user_id, reason, decided_by):
        """반려 사유와 결정자를 승인함 줄(approvals)에 쓴다. 이미 사유가 있으면 첫 사유를 지키고(재개가 겹쳐도 한 번), 줄이 없으면 아무것도 하지 않는다.
        상태(rejected)와 결정 시각은 곧이어 `decide_review_item` 이 쓴다. 옛 issue_table_rejections 표는 db/109_realign.sql 이 이 줄로 합쳤다."""
        sql = (
            "UPDATE approvals SET comment = %s, decided_by = COALESCE(decided_by, %s) "
            "WHERE approval_id = %s AND kind = 'issue_table' AND comment = ''"
        )
        with self._connect() as conn:
            conn.execute(sql, (reason, decided_by, approval_id))

    def get_by_thread(self, thread_id, user_id):
        sql = (
            "SELECT table_id, approval_id, thread_id, user_id, request, as_of, issue_rows, unreviewed, approved_by, approved_at "
            "FROM issue_tables WHERE thread_id = %s AND user_id = %s ORDER BY approved_at DESC LIMIT 1"
        )
        with self._connect() as conn:
            r = conn.execute(sql, (thread_id, user_id)).fetchone()
        if r is None:
            return None
        rows, unreviewed = (json.loads(x) if isinstance(x, str) else x for x in (r[6], r[7]))
        return {"table_id": str(r[0]), "approval_id": r[1], "thread_id": r[2], "user_id": r[3], "request": r[4],
                "as_of": str(r[5]) if r[5] else None, "rows": rows, "unreviewed": unreviewed, "approved_by": r[8],
                "approved_at": r[9].isoformat() if hasattr(r[9], "isoformat") else r[9]}
