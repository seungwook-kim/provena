"""리콜 저장소: 처리 기록, 알림, 함께 볼 정책 후보, 웹훅 구독·전송, 의견, 하루 요약 (표는 `db/120_answers_recall.sql`).

- `InMemoryRecallStore`: 시험과 DB 없는 로컬용(기본). 프로세스가 끝나면 사라진다.
- `PgRecallStore`: `RECALL_STORE=postgres`일 때. 호출마다 연결하고 준비된 문장을 끈다(Supabase 풀러).
두 구현은 같은 메서드와 같은 dict 모양을 돌려준다. 시각은 ISO 문자열(UTC)이다.

멱등(EC-06): 같은 개정(event_key)은 `claim_event`가 한 번만 넘긴다(실패한 개정은 다시 넘긴다). 같은 답·같은 개정의 알림은
`notice_add`가 한 줄만 만든다(UNIQUE (answer_id, event_key)).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

NOTICE_COLUMNS = (
    "notice_id", "event_key", "answer_id", "user_id", "thread_id", "question", "answer_excerpt", "changed", "conclusion_changed",
    "explanation", "severity", "confidence", "change_pattern", "review_status", "review_reason", "digest_status", "judge_failed",
    "acked", "acked_at", "source_url", "old_text", "new_text", "created_at",
)
CANDIDATE_COLUMNS = ("candidate_id", "event_key", "upper_rule", "upper_version_id", "rule_seq", "article", "reason", "status",
                     "decided_by", "decided_at", "created_at")
SUB_COLUMNS = ("sub_id", "url", "secret_ref", "active", "created_by", "created_at")
DELIVERY_COLUMNS = ("delivery_id", "sub_id", "notice_id", "kind", "status", "tries", "last_status_code", "last_error", "attempts",
                    "created_at", "updated_at")
FEEDBACK_COLUMNS = ("notice_id", "user_id", "answer_id", "rule_seq", "article", "pattern", "severity", "useful", "reason", "given_by",
                    "created_at")
DIGEST_COLUMNS = ("digest_id", "user_id", "day", "count", "notice_ids", "payload", "created_at")
EVENT_COLUMNS = ("event_key", "changed", "status", "notices", "review", "judge_failures", "candidates", "error_kind", "started_at",
                 "finished_at")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecallStore(Protocol):
    def claim_event(self, event_key: str, changed: dict) -> bool: ...
    def finish_event(self, event_key: str, status: str, stats: dict | None = None, error_kind: str | None = None) -> None: ...
    def event_get(self, event_key: str) -> dict | None: ...
    def notice_add(self, rec: dict) -> tuple[dict, bool]: ...
    def notice_get(self, notice_id: str) -> dict | None: ...
    def notices_all(self, user_id: str | None = None) -> list[dict]: ...
    def notice_update(self, notice_id: str, **fields: Any) -> dict | None: ...
    def digest_pending(self) -> list[dict]: ...
    def feedback_put(self, rec: dict) -> None: ...
    def feedback_counts(self, user_id: str, rule_seq: int, article: str, pattern: str) -> dict: ...
    def feedback_list(self) -> list[dict]: ...
    def digest_add(self, rec: dict) -> tuple[dict, bool]: ...
    def digests(self, user_id: str | None = None) -> list[dict]: ...
    def candidates_add(self, recs: list[dict]) -> int: ...
    def candidates(self, status: str | None = None) -> list[dict]: ...
    def candidate_get(self, candidate_id: str) -> dict | None: ...
    def candidate_decide(self, candidate_id: str, status: str, by: str) -> dict | None: ...
    def subs(self, active_only: bool = False) -> list[dict]: ...
    def sub_add(self, rec: dict) -> dict: ...
    def delivery_add(self, rec: dict) -> None: ...
    def delivery_update(self, delivery_id: str, **fields: Any) -> None: ...
    def deliveries(self, notice_id: str | None = None) -> list[dict]: ...


def _counts(rows: list[dict]) -> dict:
    u = sum(1 for r in rows if r["useful"])
    return {"useful": u, "not_useful": len(rows) - u}


class InMemoryRecallStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.events: dict[str, dict] = {}
        self.notices: dict[str, dict] = {}
        self.candidate_rows: dict[str, dict] = {}
        self.sub_rows: dict[str, dict] = {}
        self.delivery_rows: dict[str, dict] = {}
        self.feedback_rows: dict[str, dict] = {}
        self.digest_rows: dict[str, dict] = {}
        self._seq = 0

    def _tick(self) -> int:
        self._seq += 1
        return self._seq

    # ---- 처리 기록
    def claim_event(self, event_key, changed):
        with self._lock:
            ev = self.events.get(event_key)
            if ev is not None and ev["status"] in ("running", "done"):
                return False
            self.events[event_key] = {"event_key": event_key, "changed": dict(changed), "status": "running", "notices": 0, "review": 0,
                                      "judge_failures": 0, "candidates": 0, "error_kind": None, "started_at": now_iso(), "finished_at": None}
            return True

    def finish_event(self, event_key, status, stats=None, error_kind=None):
        with self._lock:
            ev = self.events.get(event_key)
            if ev is not None:
                ev.update({k: v for k, v in (stats or {}).items() if k in EVENT_COLUMNS}, status=status, error_kind=error_kind,
                          finished_at=now_iso())

    def event_get(self, event_key):
        with self._lock:
            ev = self.events.get(event_key)
            return dict(ev) if ev else None

    # ---- 알림
    def notice_add(self, rec):
        with self._lock:
            for old in self.notices.values():
                if old["answer_id"] == rec["answer_id"] and old["event_key"] == rec["event_key"]:
                    return dict(old), False
            row = {k: rec.get(k) for k in NOTICE_COLUMNS}
            row["acked"] = bool(row.get("acked"))
            row["judge_failed"] = bool(row.get("judge_failed"))
            row["created_at"] = row.get("created_at") or now_iso()
            row["_seq"] = self._tick()
            self.notices[row["notice_id"]] = row
            return self._out(row), True

    @staticmethod
    def _out(row: dict) -> dict:
        return {k: v for k, v in row.items() if not k.startswith("_")}

    def notice_get(self, notice_id):
        with self._lock:
            row = self.notices.get(notice_id)
            return self._out(row) if row else None

    def notices_all(self, user_id=None):
        with self._lock:
            rows = [r for r in self.notices.values() if user_id is None or r["user_id"] == user_id]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"], reverse=True)]

    def notice_update(self, notice_id, **fields):
        with self._lock:
            row = self.notices.get(notice_id)
            if row is None:
                return None
            row.update({k: v for k, v in fields.items() if k in NOTICE_COLUMNS})
            return self._out(row)

    def digest_pending(self):
        with self._lock:
            rows = [r for r in self.notices.values() if r.get("digest_status") == "pending" and r.get("review_status") not in ("pending", "dismissed")]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"])]

    # ---- 의견
    def feedback_put(self, rec):
        with self._lock:
            row = {k: rec.get(k) for k in FEEDBACK_COLUMNS}
            row["created_at"] = row.get("created_at") or now_iso()
            self.feedback_rows[row["notice_id"]] = row

    def feedback_counts(self, user_id, rule_seq, article, pattern):
        with self._lock:
            rows = [r for r in self.feedback_rows.values() if (r["user_id"], int(r["rule_seq"]), r["article"], r["pattern"]) ==
                    (user_id, int(rule_seq), article, pattern)]
            return _counts(rows)

    def feedback_list(self):
        with self._lock:
            return [dict(r) for r in self.feedback_rows.values()]

    # ---- 하루 요약
    def digest_add(self, rec):
        with self._lock:
            old = self.digest_rows.get(rec["digest_id"])
            if old is not None:
                return dict(old), False
            row = {k: rec.get(k) for k in DIGEST_COLUMNS}
            row["created_at"] = row.get("created_at") or now_iso()
            row["_seq"] = self._tick()
            self.digest_rows[row["digest_id"]] = row
            return self._out(row), True

    def digests(self, user_id=None):
        with self._lock:
            rows = [r for r in self.digest_rows.values() if user_id is None or r["user_id"] == user_id]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"], reverse=True)]

    # ---- 함께 볼 정책 후보
    def candidates_add(self, recs):
        with self._lock:
            new = 0
            for rec in recs:
                if rec["candidate_id"] in self.candidate_rows:
                    continue
                row = {k: rec.get(k) for k in CANDIDATE_COLUMNS}
                row["status"] = row.get("status") or "pending"
                row["created_at"] = row.get("created_at") or now_iso()
                row["_seq"] = self._tick()
                self.candidate_rows[row["candidate_id"]] = row
                new += 1
            return new

    def candidates(self, status=None):
        with self._lock:
            rows = [r for r in self.candidate_rows.values() if status is None or r["status"] == status]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"], reverse=True)]

    def candidate_get(self, candidate_id):
        with self._lock:
            row = self.candidate_rows.get(candidate_id)
            return self._out(row) if row else None

    def candidate_decide(self, candidate_id, status, by):
        with self._lock:
            row = self.candidate_rows.get(candidate_id)
            if row is None:
                return None
            row.update(status=status, decided_by=by, decided_at=now_iso())
            return self._out(row)

    # ---- 웹훅
    def subs(self, active_only=False):
        with self._lock:
            rows = [r for r in self.sub_rows.values() if r["active"] or not active_only]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"])]

    def sub_add(self, rec):
        with self._lock:
            row = {k: rec.get(k) for k in SUB_COLUMNS}
            row["created_at"] = row.get("created_at") or now_iso()
            row["_seq"] = self._tick()
            self.sub_rows[row["sub_id"]] = row
            return self._out(row)

    def delivery_add(self, rec):
        with self._lock:
            row = {k: rec.get(k) for k in DELIVERY_COLUMNS}
            row["attempts"] = list(row.get("attempts") or [])
            row["created_at"] = row["updated_at"] = now_iso()
            row["_seq"] = self._tick()
            self.delivery_rows[row["delivery_id"]] = row

    def delivery_update(self, delivery_id, **fields):
        with self._lock:
            row = self.delivery_rows.get(delivery_id)
            if row is not None:
                row.update({k: (list(v) if k == "attempts" else v) for k, v in fields.items() if k in DELIVERY_COLUMNS})
                row["updated_at"] = now_iso()

    def deliveries(self, notice_id=None):
        with self._lock:
            rows = [r for r in self.delivery_rows.values() if notice_id is None or r["notice_id"] == notice_id]
            return [self._out(r) for r in sorted(rows, key=lambda r: r["_seq"])]


# ---------------------------------------------------------------- Postgres
def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


class PgRecallStore:
    """`db/120_answers_recall.sql` 위의 구현. `connect`는 시험에서 연결을 바꿔 넣는 자리다."""

    JSON_FIELDS = {"changed", "attempts", "notice_ids", "payload"}

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

    def _val(self, key: str, value: Any) -> Any:
        if key in self.JSON_FIELDS and value is not None:
            from psycopg.types.json import Jsonb

            return Jsonb(value)
        return value

    def _insert(self, table: str, cols: tuple[str, ...], rec: dict, conflict: str) -> list[dict]:
        use = [c for c in cols if c in rec and not (c == "created_at" and rec.get(c) is None)]
        sql = (f"INSERT INTO {table} ({', '.join(use)}) VALUES ({', '.join(['%s'] * len(use))}) {conflict} "
               f"RETURNING {', '.join(cols)}")
        return self._q(sql, tuple(self._val(c, rec[c]) for c in use))

    def _update(self, table: str, key: str, key_value: str, cols: tuple[str, ...], fields: dict, extra: str = "") -> list[dict]:
        use = [c for c in fields if c in cols and c != key]
        if not use and not extra:
            return self._q(f"SELECT {', '.join(cols)} FROM {table} WHERE {key} = %s", (key_value,))
        sets = [f"{c} = %s" for c in use] + ([extra] if extra else [])
        return self._q(f"UPDATE {table} SET {', '.join(sets)} WHERE {key} = %s RETURNING {', '.join(cols)}",
                       (*[self._val(c, fields[c]) for c in use], key_value))

    # ---- 처리 기록
    def claim_event(self, event_key, changed):
        rows = self._q(
            "INSERT INTO recall_events (event_key, changed, status) VALUES (%s, %s, 'running') "
            "ON CONFLICT (event_key) DO UPDATE SET status = 'running', started_at = now(), finished_at = NULL, error_kind = NULL "
            "WHERE recall_events.status = 'failed' RETURNING event_key",
            (event_key, self._val("changed", dict(changed))))
        return bool(rows)

    def finish_event(self, event_key, status, stats=None, error_kind=None):
        s = stats or {}
        self._q("UPDATE recall_events SET status = %s, notices = %s, review = %s, judge_failures = %s, candidates = %s, "
                "error_kind = %s, finished_at = now() WHERE event_key = %s",
                (status, int(s.get("notices", 0)), int(s.get("review", 0)), int(s.get("judge_failures", 0)), int(s.get("candidates", 0)),
                 error_kind, event_key))

    def event_get(self, event_key):
        rows = self._q(f"SELECT {', '.join(EVENT_COLUMNS)} FROM recall_events WHERE event_key = %s", (event_key,))
        return rows[0] if rows else None

    # ---- 알림
    def notice_add(self, rec):
        row = dict(rec)
        row["acked"], row["judge_failed"] = bool(row.get("acked")), bool(row.get("judge_failed"))
        got = self._insert("recall_notices", NOTICE_COLUMNS, row, "ON CONFLICT (answer_id, event_key) DO NOTHING")
        if got:
            return got[0], True
        old = self._q(f"SELECT {', '.join(NOTICE_COLUMNS)} FROM recall_notices WHERE answer_id = %s AND event_key = %s",
                      (rec["answer_id"], rec["event_key"]))
        return old[0], False

    def notice_get(self, notice_id):
        rows = self._q(f"SELECT {', '.join(NOTICE_COLUMNS)} FROM recall_notices WHERE notice_id = %s", (notice_id,))
        return rows[0] if rows else None

    def notices_all(self, user_id=None):
        return self._q(f"SELECT {', '.join(NOTICE_COLUMNS)} FROM recall_notices WHERE (%s::text IS NULL OR user_id = %s::text) "
                       "ORDER BY created_at DESC, notice_id", (user_id, user_id))

    def notice_update(self, notice_id, **fields):
        rows = self._update("recall_notices", "notice_id", notice_id, NOTICE_COLUMNS, fields)
        return rows[0] if rows else None

    def digest_pending(self):
        return self._q(f"SELECT {', '.join(NOTICE_COLUMNS)} FROM recall_notices WHERE digest_status = 'pending' "
                       "AND (review_status IS NULL OR review_status = 'released') ORDER BY created_at, notice_id")

    # ---- 의견
    def feedback_put(self, rec):
        cols = [c for c in FEEDBACK_COLUMNS if c != "created_at"]
        self._q(f"INSERT INTO recall_feedback ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                "ON CONFLICT (notice_id) DO UPDATE SET useful = EXCLUDED.useful, reason = EXCLUDED.reason, given_by = EXCLUDED.given_by, "
                "created_at = now()", tuple(rec.get(c) for c in cols))

    def feedback_counts(self, user_id, rule_seq, article, pattern):
        rows = self._q("SELECT useful FROM recall_feedback WHERE user_id = %s AND rule_seq = %s AND article = %s AND pattern = %s",
                       (user_id, int(rule_seq), article, pattern))
        return _counts(rows)

    def feedback_list(self):
        return self._q(f"SELECT {', '.join(FEEDBACK_COLUMNS)} FROM recall_feedback ORDER BY created_at")

    # ---- 하루 요약
    def digest_add(self, rec):
        got = self._insert("recall_digests", DIGEST_COLUMNS, rec, "ON CONFLICT (digest_id) DO NOTHING")
        if got:
            return got[0], True
        return self._q(f"SELECT {', '.join(DIGEST_COLUMNS)} FROM recall_digests WHERE digest_id = %s", (rec["digest_id"],))[0], False

    def digests(self, user_id=None):
        return self._q(f"SELECT {', '.join(DIGEST_COLUMNS)} FROM recall_digests WHERE (%s::text IS NULL OR user_id = %s::text) "
                       "ORDER BY created_at DESC", (user_id, user_id))

    # ---- 함께 볼 정책 후보
    def candidates_add(self, recs):
        return sum(1 for rec in recs if self._insert("maintenance_candidates", CANDIDATE_COLUMNS, rec, "ON CONFLICT (candidate_id) DO NOTHING"))

    def candidates(self, status=None):
        return self._q(f"SELECT {', '.join(CANDIDATE_COLUMNS)} FROM maintenance_candidates WHERE (%s::text IS NULL OR status = %s::text) "
                       "ORDER BY created_at DESC, candidate_id", (status, status))

    def candidate_get(self, candidate_id):
        rows = self._q(f"SELECT {', '.join(CANDIDATE_COLUMNS)} FROM maintenance_candidates WHERE candidate_id = %s", (candidate_id,))
        return rows[0] if rows else None

    def candidate_decide(self, candidate_id, status, by):
        rows = self._update("maintenance_candidates", "candidate_id", candidate_id, CANDIDATE_COLUMNS,
                            {"status": status, "decided_by": by}, extra="decided_at = now()")
        return rows[0] if rows else None

    # ---- 웹훅
    def subs(self, active_only=False):
        return self._q(f"SELECT {', '.join(SUB_COLUMNS)} FROM webhook_subscriptions WHERE active OR NOT %s ORDER BY created_at, sub_id",
                       (bool(active_only),))

    def sub_add(self, rec):
        return self._insert("webhook_subscriptions", SUB_COLUMNS, rec, "")[0]

    def delivery_add(self, rec):
        self._insert("webhook_deliveries", DELIVERY_COLUMNS, {k: v for k, v in rec.items() if k not in ("created_at", "updated_at")}, "")

    def delivery_update(self, delivery_id, **fields):
        self._update("webhook_deliveries", "delivery_id", delivery_id, DELIVERY_COLUMNS, fields, extra="updated_at = now()")

    def deliveries(self, notice_id=None):
        return self._q(f"SELECT {', '.join(DELIVERY_COLUMNS)} FROM webhook_deliveries WHERE (%s::text IS NULL OR notice_id = %s::text) "
                       "ORDER BY created_at, delivery_id", (notice_id, notice_id))
