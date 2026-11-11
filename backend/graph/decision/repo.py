"""결정표·승인 저장소 (B-06, SDD 5장 `decision_tables`, `approvals`).

그래프와 API는 이 인터페이스로만 표를 읽고 쓴다. 구현이 둘이다.
- `InMemoryDecisionRepo`: 시험과 로컬. 프로세스가 끝나면 사라진다.
- `PostgresDecisionRepo`: `db/102_decision_approvals.sql` 표를 쓴다. 연결 풀은 `backend/graph/checkpoint.py`의 `open_persistence()`가 쓰는 것과
  같은 모양(autocommit)이면 된다.

규칙
- 승인함에 올릴 때(`queue_draft`) 표는 `draft`, 승인 건은 `pending`이다. 같은 `thread_id`로 다시 부르면 새로 만들지 않고 있던 것을 돌려준다
  (재개 때 노드가 다시 돌아도 승인 건이 둘이 되지 않는다).
- 승인(`decide`)은 `pending`인 건에만 된다. 승인에는 승인한 관리자(`decided_by`)가 반드시 있어야 한다.
  같은 결정을 다시 보내면 그대로 돌려주고(멱등), 다른 결정은 `AlreadyDecided`(409)다.
- 승인된 표만 `approved`이고, 실행은 `status == "approved"`일 때만 된다(`execute.py`).
- 합동 검토의 두 멈춤도 같은 `approvals` 표에 올린다(`queue_review_item`, `decide_review_item`). 내용은 대기 동안 체크포인트에 있다.
  - `issue_table`: 쟁점표 승인. 승인 뒤 `issue_tables`에 저장된다. `target_id`는 승인 전에는 승인 건 번호, 승인 뒤에는 저장된 쟁점표 `table_id`다.
  - `team_review_failed`: 재시도 상한까지 실패한 팀을 사람에게 알린 건. 실제 행동은 `status`로 짐작하지 않고 `team_resolution()`으로 읽는다.
  한 대화에서 합동 검토를 다시 할 수 있으므로 대화마다 대기 건은 1개이고, 끝난 건은 기록으로 남는다. 새 건이 올라오면 앞선 대기 건은 그래프가 이미 떠나
  재개할 수 없으므로 사유를 적어 닫는다(`SUPERSEDED_COMMENT`).
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.graph.decision.rules import AlreadyDecided, Conflict, DecisionError, NotFound, norm
from backend.schemas import DecisionTable

KIND = "decision_table"
ISSUE_KIND = "issue_table"
TEAM_FAILED_KIND = "team_review_failed"
REVIEW_KINDS = (ISSUE_KIND, TEAM_FAILED_KIND)
LOCK_WAIT_SECONDS = 120   # 같은 승인 건의 앞 요청이 끝나기를 기다리는 최대 시간(`PostgresDecisionRepo.decision_lock`)
SUPERSEDED_COMMENT ="같은 대화의 합동 검토가 다음 단계로 넘어가 이 승인 건은 더 재개할 수 없다."
Status = Literal["pending", "approved", "rejected"]


class ApprovalRecord(BaseModel):
    approval_id: str
    kind: str
    thread_id: str
    status: Status
    summary: str
    target_id: str  # 승인 대상. 결정표면 table_id, 쟁점표면 모듈 설명 참고
    created_at: datetime
    decided_by: str | None = None
    comment: str = ""
    decided_at: datetime | None = None
    # 그래프 재개 기록(`record_resume`). 결정이 몇 번 그래프를 실제로 돌렸는지와 같은 결정의 재전송이 몇 번 무시됐는지를 API로 읽는다.
    resume_count: int = 0
    duplicate_ignored_count: int = 0
    last_resumed_at: datetime | None = None
    last_resume_result: str | None = None


RESUME_RESULTS = ("resumed", "resume_failed", "rejected_value", "duplicate_ignored")
"""재개 기록의 결과 값. `resumed` 그래프를 재개했고 끝까지 갔다, `resume_failed` 재개 도중 오류, `rejected_value` 그래프가 재개 값을 거절해 같은 승인 요청을 다시 올렸다,
`duplicate_ignored` 이미 끝난 건의 같은 결정이라 그래프를 돌리지 않았다. 앞의 셋이 `resume_count`를, 마지막이 `duplicate_ignored_count`를 올린다."""


def _bump_resume(rec: ApprovalRecord, result: str) -> ApprovalRecord:
    if result not in RESUME_RESULTS:
        raise DecisionError(f"알 수 없는 재개 결과: {result}")
    if result == "duplicate_ignored":
        return rec.model_copy(update={"duplicate_ignored_count": rec.duplicate_ignored_count + 1, "last_resume_result": result})
    return rec.model_copy(update={"resume_count": rec.resume_count + 1, "last_resumed_at": datetime.now(timezone.utc), "last_resume_result": result})


def team_resolution(rec: ApprovalRecord) -> str | None:
    """팀 실패 알림 건에서 사람이 실제로 고른 행동. 고르지 않았으면(대기 중, 사람 결정 없이 닫힘) None이다.

    따로 칸에 적지 않고 `status`와 `decided_by`에서 읽는다. 사람 결정에는 항상 `decided_by`가 있고(`decide_review_item`이 막는다)
    닫힌 건에는 없으므로 정보가 빠지지 않고, 같은 사실을 두 칸에 적어 서로 달라질 일도 없다."""
    if rec.kind != TEAM_FAILED_KIND or rec.status == "pending" or not rec.decided_by:
        return None
    return "retry" if rec.status == "approved" else "mark_unreviewed"


class DecisionRepo(Protocol):
    def queue_draft(self, thread_id: str, table: DecisionTable, summary: str) -> ApprovalRecord: ...
    def decide(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "") -> DecisionTable: ...
    def get_approval(self, approval_id: str) -> ApprovalRecord: ...
    def get_table(self, table_id: str) -> DecisionTable: ...
    def list_pending(self) -> list[ApprovalRecord]: ...
    def list_approved(self) -> list[DecisionTable]: ...
    def find_approved(self, task_type: str) -> list[DecisionTable]: ...
    def queue_review_item(self, thread_id: str, approval_id: str, summary: str, kind: str = ISSUE_KIND) -> ApprovalRecord: ...
    def decide_review_item(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "",
                           table_id: str | None = None) -> ApprovalRecord: ...
    def record_resume(self, approval_id: str, result: str) -> ApprovalRecord: ...


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def table_category(table: DecisionTable) -> str:
    cells = table.cells if isinstance(table.cells, list) else []
    return str(cells[0].get("category", "")) if cells else ""


def _check_decision(approve: bool, decided_by: str | None) -> None:
    if approve and not (decided_by or "").strip():
        raise DecisionError("승인에는 승인한 관리자(decided_by)가 필요하다")


def _check_kind(kind: str, *want: str) -> None:
    if kind not in want:
        raise Conflict(f"{' 또는 '.join(want)} 승인 경로로 {kind} 승인 건을 처리할 수 없다")


def _same_decision(status: str, recorded_by: str | None, approve: bool, decided_by: str | None) -> None:
    """이미 끝난 건에 온 결정이 같은 결정이면 그대로 지나가고(멱등), 다르면 `AlreadyDecided`다."""
    if status != ("approved" if approve else "rejected") or (approve and recorded_by != decided_by):
        raise AlreadyDecided(f"이미 {status}된 승인 건이다")


def _review_decision_done(kind: str, status: str, recorded_by: str | None, approve: bool, decided_by: str | None) -> bool:
    """합동 검토 승인 건의 결정을 검사한다. 이미 끝난 건에 온 같은 결정이면 True다.

    팀 실패 알림은 `retry`와 `mark_unreviewed` 모두 결정한 사람이 있어야 한다. 사람 결정 없이 닫힌 건(`SUPERSEDED_COMMENT`)에 `mark_unreviewed`가 와도
    같은 결정으로 치지 않는다: 그 행동은 일어난 적이 없다."""
    if status == "pending":
        _check_decision(approve or kind == TEAM_FAILED_KIND, decided_by)
        return False
    if kind == TEAM_FAILED_KIND and not recorded_by:
        raise AlreadyDecided("다음 단계로 넘어가 닫힌 승인 건이다")
    _same_decision(status, recorded_by, approve, decided_by)
    return True


def _issue_queue_plan(approval_id: str, rows: list[ApprovalRecord]) -> tuple[ApprovalRecord | None, str | None]:
    """같은 대화의 합동 검토 승인 건을 보고 (돌려줄 대기 건, 새 승인 건 번호) 중 하나를 정한다.

    같은 표의 대기 건이 있으면 노드가 다시 돈 것이므로 그 건을 돌려준다. 같은 표가 이미 결정됐는데 다시 올라오면 사람이 다시 봐야 하는 새 검토이므로 새 번호를 쓴다."""
    for r in rows:
        if r.status == "pending" and (r.approval_id == approval_id or r.approval_id.startswith(f"{approval_id}_")):
            return r, None
    return None, new_id(approval_id) if any(r.approval_id == approval_id for r in rows) else approval_id


class InMemoryDecisionRepo:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tables: dict[str, DecisionTable] = {}
        self._approvals: dict[str, ApprovalRecord] = {}

    def queue_draft(self, thread_id: str, table: DecisionTable, summary: str) -> ApprovalRecord:
        with self._lock:
            for a in self._approvals.values():
                if a.thread_id == thread_id and a.kind == KIND:
                    return a
            if table.status != "draft" or table.approved_by:
                raise DecisionError("승인함에는 draft 표만 올린다")
            rec = ApprovalRecord(approval_id=new_id("ap"), kind=KIND, thread_id=thread_id, status="pending", summary=summary,
                                 target_id=table.table_id, created_at=datetime.now(timezone.utc))
            self._tables[table.table_id] = table.model_copy(deep=True)
            self._approvals[rec.approval_id] = rec
            return rec

    def decide(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "") -> DecisionTable:
        with self._lock:
            rec = self.get_approval(approval_id)
            _check_kind(rec.kind, KIND)
            want: Status = "approved" if approve else "rejected"
            if rec.status != "pending":
                _same_decision(rec.status, rec.decided_by, approve, decided_by)
                return self.get_table(rec.target_id)           # 같은 결정을 다시 보냄: 그대로
            _check_decision(approve, decided_by)
            self._approvals[approval_id] = rec.model_copy(update={
                "status": want, "decided_by": decided_by, "comment": comment, "decided_at": datetime.now(timezone.utc)})
            t = self._tables[rec.target_id]
            self._tables[rec.target_id] = t.model_copy(update={"status": "approved" if approve else "rejected",
                                                               "approved_by": decided_by if approve else None})
            return self._tables[rec.target_id]

    def queue_review_item(self, thread_id: str, approval_id: str, summary: str, kind: str = ISSUE_KIND) -> ApprovalRecord:
        _check_kind(kind, *REVIEW_KINDS)
        with self._lock:
            rows = [a for a in self._approvals.values() if a.thread_id == thread_id and a.kind in REVIEW_KINDS]
            found, new = _issue_queue_plan(approval_id, rows)
            if found is not None:
                return found
            for r in rows:
                if r.status == "pending":
                    self._approvals[r.approval_id] = r.model_copy(update={
                        "status": "rejected", "comment": SUPERSEDED_COMMENT, "decided_at": datetime.now(timezone.utc)})
            rec = ApprovalRecord(approval_id=new, kind=kind, thread_id=thread_id, status="pending", summary=summary,
                                 target_id=new, created_at=datetime.now(timezone.utc))
            self._approvals[new] = rec
            return rec

    def decide_review_item(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "",
                           table_id: str | None = None) -> ApprovalRecord:
        with self._lock:
            rec = self.get_approval(approval_id)
            _check_kind(rec.kind, *REVIEW_KINDS)
            if _review_decision_done(rec.kind, rec.status, rec.decided_by, approve, decided_by):
                return rec
            self._approvals[approval_id] = rec.model_copy(update={
                "status": "approved" if approve else "rejected", "decided_by": decided_by, "comment": comment,
                "decided_at": datetime.now(timezone.utc), "target_id": table_id or rec.target_id})
            return self._approvals[approval_id]

    def record_resume(self, approval_id: str, result: str) -> ApprovalRecord:
        with self._lock:
            self._approvals[approval_id] = _bump_resume(self.get_approval(approval_id), result)
            return self._approvals[approval_id]

    def get_approval(self, approval_id: str) -> ApprovalRecord:
        try:
            return self._approvals[approval_id]
        except KeyError:
            raise NotFound("승인 건이 없다") from None

    def get_table(self, table_id: str) -> DecisionTable:
        try:
            return self._tables[table_id]
        except KeyError:
            raise NotFound("결정표가 없다") from None

    def list_pending(self) -> list[ApprovalRecord]:
        return sorted((a for a in self._approvals.values() if a.status == "pending"), key=lambda a: a.created_at)

    def list_approved(self) -> list[DecisionTable]:
        return [t for t in self._tables.values() if t.status == "approved"]

    def find_approved(self, task_type: str) -> list[DecisionTable]:
        return [t for t in self.list_approved() if norm(table_category(t)) == norm(task_type)]


class PostgresDecisionRepo:
    """`db/102_decision_approvals.sql` 표 위의 구현. `pool`은 psycopg_pool.ConnectionPool(autocommit=True)."""

    def __init__(self, pool) -> None:
        self.pool = pool

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        from psycopg.rows import dict_row

        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else []

    @staticmethod
    def _table(r: dict) -> DecisionTable:
        return DecisionTable(table_id=r["table_id"], rule_seq=r["rule_seq"], version_id=r["version_id"], cells=r["cells"],
                             status=r["status"], approved_by=r["approved_by"])

    @contextmanager
    def decision_lock(self, approval_id: str) -> Iterator[None]:
        """같은 승인 건의 결정 처리(그래프 재개 포함)를 인스턴스 사이에서도 하나씩 하게 하는 DB 잠금. 블록이 끝나면 풀린다.

        `approvals` 행 잠금(`FOR UPDATE`)은 결정을 적는 짧은 순간만 지켜서, 두 인스턴스가 둘 다 `pending`을 본 채 그래프를 두 번 재개하는 것은 못 막는다.
        그래서 행이 아닌 자문 잠금 하나를 요청 전체에 건다. 행 잠금을 쓰면 재개 중 `decide()`가 같은 행을 기다려 스스로 막힌다.
        - 연결은 풀과 따로 연다: 풀(최대 4개)에서 잠금용 연결을 잡으면 동시 요청이 몰릴 때 그래프가 쓸 연결이 없어 서로 기다린다.
        - 세션 잠금이 아닌 트랜잭션 잠금(`pg_advisory_xact_lock`)이다: 트랜잭션 모드 풀러(Supabase)는 요청마다 서버 연결이 바뀌어 세션 잠금을 보장하지 못한다.
        - 기다림은 `LOCK_WAIT_SECONDS`까지다. 넘으면 오류로 올라와 호출한 쪽이 503으로 돌려준다."""
        import psycopg

        kwargs = {**self.pool.kwargs, "autocommit": False, "connect_timeout": 5}
        with psycopg.connect(self.pool.conninfo, **kwargs) as conn:
            conn.execute(f"SET LOCAL lock_timeout = '{LOCK_WAIT_SECONDS}s'")
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"approval-decision:{approval_id}",))
            yield

    def queue_draft(self, thread_id: str, table: DecisionTable, summary: str) -> ApprovalRecord:
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        if table.status != "draft" or table.approved_by:
            raise DecisionError("승인함에는 draft 표만 올린다")
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM approvals WHERE thread_id = %s AND kind = %s", (thread_id, KIND))
            found = cur.fetchone()
            if found:
                return ApprovalRecord(**found)
            cur.execute(
                "INSERT INTO decision_tables (table_id, rule_seq, version_id, cells, status) VALUES (%s, %s, %s, %s, 'draft')",
                (table.table_id, table.rule_seq, table.version_id, Jsonb(table.cells)))
            cur.execute(
                "INSERT INTO approvals (approval_id, kind, thread_id, status, summary, target_id) VALUES (%s, %s, %s, 'pending', %s, %s) RETURNING *",
                (new_id("ap"), KIND, thread_id, summary, table.table_id))
            return ApprovalRecord(**cur.fetchone())

    def decide(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "") -> DecisionTable:
        from psycopg.rows import dict_row

        want = "approved" if approve else "rejected"
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM approvals WHERE approval_id = %s FOR UPDATE", (approval_id,))
            rec = cur.fetchone()
            if not rec:
                raise NotFound("승인 건이 없다")
            _check_kind(rec["kind"], KIND)
            if rec["status"] != "pending":
                _same_decision(rec["status"], rec["decided_by"], approve, decided_by)
                cur.execute("SELECT * FROM decision_tables WHERE table_id = %s", (rec["target_id"],))
                return self._table(cur.fetchone())
            _check_decision(approve, decided_by)
            cur.execute("UPDATE approvals SET status = %s, decided_by = %s, comment = %s, decided_at = now() WHERE approval_id = %s",
                        (want, decided_by, comment, approval_id))
            cur.execute("UPDATE decision_tables SET status = %s, approved_by = %s WHERE table_id = %s RETURNING *",
                        (want, decided_by if approve else None, rec["target_id"]))
            return self._table(cur.fetchone())

    def queue_review_item(self, thread_id: str, approval_id: str, summary: str, kind: str = ISSUE_KIND) -> ApprovalRecord:
        from psycopg.rows import dict_row

        _check_kind(kind, *REVIEW_KINDS)
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM approvals WHERE thread_id = %s AND kind <> %s FOR UPDATE", (thread_id, KIND))
            found, new = _issue_queue_plan(approval_id, [ApprovalRecord(**r) for r in cur.fetchall()])
            if found is not None:
                return found
            cur.execute("UPDATE approvals SET status = 'rejected', comment = %s, decided_at = now() WHERE thread_id = %s AND kind <> %s AND status = 'pending'",
                        (SUPERSEDED_COMMENT, thread_id, KIND))
            cur.execute(
                "INSERT INTO approvals (approval_id, kind, thread_id, status, summary, target_id) VALUES (%s, %s, %s, 'pending', %s, %s) RETURNING *",
                (new, kind, thread_id, summary, new))
            return ApprovalRecord(**cur.fetchone())

    def decide_review_item(self, approval_id: str, approve: bool, decided_by: str | None, comment: str = "",
                           table_id: str | None = None) -> ApprovalRecord:
        from psycopg.rows import dict_row

        want = "approved" if approve else "rejected"
        with self.pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM approvals WHERE approval_id = %s FOR UPDATE", (approval_id,))
            rec = cur.fetchone()
            if not rec:
                raise NotFound("승인 건이 없다")
            _check_kind(rec["kind"], *REVIEW_KINDS)
            if _review_decision_done(rec["kind"], rec["status"], rec["decided_by"], approve, decided_by):
                return ApprovalRecord(**rec)
            cur.execute("UPDATE approvals SET status = %s, decided_by = %s, comment = %s, decided_at = now(), target_id = COALESCE(%s, target_id) "
                        "WHERE approval_id = %s RETURNING *", (want, decided_by, comment, table_id, approval_id))
            return ApprovalRecord(**cur.fetchone())

    def record_resume(self, approval_id: str, result: str) -> ApprovalRecord:
        """재개 기록을 한 문장으로 올린다(읽고 쓰는 사이에 다른 요청이 끼지 않는다). 칸은 `db/112_approval_resume_log.sql`이 만든다."""
        if result not in RESUME_RESULTS:
            raise DecisionError(f"알 수 없는 재개 결과: {result}")
        if result == "duplicate_ignored":
            sql = "UPDATE approvals SET duplicate_ignored_count = duplicate_ignored_count + 1, last_resume_result = %s WHERE approval_id = %s RETURNING *"
        else:
            sql = ("UPDATE approvals SET resume_count = resume_count + 1, last_resumed_at = now(), last_resume_result = %s "
                   "WHERE approval_id = %s RETURNING *")
        rows = self._rows(sql, (result, approval_id))
        if not rows:
            raise NotFound("승인 건이 없다")
        return ApprovalRecord(**rows[0])

    def get_approval(self, approval_id: str) -> ApprovalRecord:
        rows = self._rows("SELECT * FROM approvals WHERE approval_id = %s", (approval_id,))
        if not rows:
            raise NotFound("승인 건이 없다")
        return ApprovalRecord(**rows[0])

    def get_table(self, table_id: str) -> DecisionTable:
        rows = self._rows("SELECT * FROM decision_tables WHERE table_id = %s", (table_id,))
        if not rows:
            raise NotFound("결정표가 없다")
        return self._table(rows[0])

    def list_pending(self) -> list[ApprovalRecord]:
        return [ApprovalRecord(**r) for r in self._rows("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at")]

    def list_approved(self) -> list[DecisionTable]:
        return [self._table(r) for r in self._rows("SELECT * FROM decision_tables WHERE status = 'approved' ORDER BY table_id")]

    def find_approved(self, task_type: str) -> list[DecisionTable]:
        return [t for t in self.list_approved() if norm(table_category(t)) == norm(task_type)]
