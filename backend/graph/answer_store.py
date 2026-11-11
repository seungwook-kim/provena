"""답변·인용 저장소 (SDD 5장 `answers`, `citations`).

`AnswerStore` Protocol을 지키면 Postgres 구현으로 바꿔 끼울 수 있다(B-05).
`find_by_article`은 리콜(backend/graph/recall)이 "이 섹션을 인용한 과거 답"을 찾는 데 쓴다. 이름·반환 키는 리콜 담당과 맞춘 것이다.

- `InMemoryAnswerStore`: 테스트·데모용. 프로세스가 끝나면 사라진다(기본).
- `PgAnswerStore`: `db/120_answers_recall.sql`의 `answers`(인용 검사 결과는 `grounding`, `skills_used` 칸), `citations` 표. 재시작해도 답과 인용이 남아 리콜이 지난 답을 찾을 수 있다.
  앱은 `RECALL_STORE=postgres`일 때만 이 구현을 쓴다(`backend/graph/recall/runtime.py`).
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from backend.schemas import Chunk


@runtime_checkable
class AnswerStore(Protocol):
    def save(
        self,
        answer_id: str,
        user_id: str,
        thread_id: str,
        question: str,
        answer: str,
        as_of: str | None,
        citations: list[Chunk],
    ) -> None: ...

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        """그 정책(rule_seq)의 그 섹션(article)을 인용한 답. 키: answer_id, user_id, question, answer, as_of, version_id.
        구현에 따라 thread_id, version_date(인용한 판 날짜), source_url이 더 붙는다."""
        ...


def count_by_articles(store: Any, pairs: Iterable[tuple[int, str]]) -> dict[tuple[int, str], int]:
    """(rule_seq, article)마다 그 섹션을 인용한 서로 다른 답 수. 저장소에 묶음 조회가 있으면 그것을 쓴다(변경 감시 화면)."""
    keys = list(dict.fromkeys(pairs))
    if not keys:
        return {}
    fast = getattr(store, "count_by_articles", None)
    if fast is not None:
        return fast(keys)
    return {k: len({r["answer_id"] for r in store.find_by_article(*k)}) for k in keys}


class InMemoryAnswerStore:
    """인메모리 구현(테스트·데모용)."""

    def __init__(self) -> None:
        self._answers: dict[str, dict] = {}
        self._citations: dict[str, list[Chunk]] = {}
        self._grounding: dict[str, dict] = {}

    def save(self, answer_id, user_id, thread_id, question, answer, as_of, citations) -> None:
        self._answers[answer_id] = {
            "answer_id": answer_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "question": question,
            "answer": answer,
            "as_of": as_of,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._citations[answer_id] = list(citations)

    def save_grounding(self, answer_id: str, grounding: dict, skills_used: list[str]) -> None:
        """밖으로 낼 수 있는 값만 받는다(`grounding.public_grounding`). 없어도 답 저장은 그대로다."""
        self._grounding[answer_id] = {"grounding": dict(grounding), "skills_used": list(skills_used)}

    def get_grounding(self, answer_id: str) -> dict | None:
        rec = self._grounding.get(answer_id)
        if rec is None:
            return None
        return {"answer_id": answer_id, **rec, "citations": [{"chunk_id": c.chunk_id, "version_id": c.version_id} for c in self._citations.get(answer_id, [])]}

    def get(self, answer_id: str) -> dict | None:
        a = self._answers.get(answer_id)
        return None if a is None else {**a, "citations": list(self._citations[answer_id])}

    def all_answers(self) -> list[dict]:
        return [self.get(i) for i in self._answers]  # type: ignore[misc]

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for aid, cites in self._citations.items():
            a = self._answers[aid]
            for c in cites:
                if c.rule_seq == rule_seq and c.article == article and (aid, c.version_id) not in seen:
                    seen.add((aid, c.version_id))
                    out.append(
                        {
                            "answer_id": aid,
                            "user_id": a["user_id"],
                            "question": a["question"],
                            "answer": a["answer"],
                            "as_of": a["as_of"],
                            "version_id": c.version_id,
                            "thread_id": a["thread_id"],
                            "version_date": c.version_date,
                            "source_url": c.source_url,
                        }
                    )
        return out


REUSE_IDLE_MAX = 2        # 놀고 있는 연결을 최대 몇 개 들고 있을지
REUSE_IDLE_SECONDS = 20.0  # 이 시간보다 오래 논 연결은 서버 쪽에서 끊겼을 수 있어 쓰지 않고 새로 연다


def reuse_connection_enabled() -> bool:
    """`ANSWER_STORE_REUSE_CONN=1`(기본 꺼짐): 답 저장소가 호출마다 새로 연결하지 않고 프로세스 안에서 연결을 다시 쓴다. 저장 문장과 트랜잭션 경계는 그대로다."""
    return (os.environ.get("ANSWER_STORE_REUSE_CONN") or "").strip().lower() in {"1", "true", "yes", "on"}


class _ReusedConnection:
    """`with` 한 번에 연결 하나를 빌려 쓰고 돌려주는 자리. 쓰는 동안 그 연결은 한 호출만 가진다(동시 저장은 서로 다른 연결).
    오류가 났거나 트랜잭션이 열려 있거나 이미 닫힌 연결은 돌려주지 않고 닫는다. 오래 논 연결(`REUSE_IDLE_SECONDS`)은 새로 연다."""

    def __init__(self, pool: "_ConnectionReuse") -> None:
        self._pool, self._conn = pool, None

    def __enter__(self) -> Any:
        self._conn = self._pool.take()
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._pool.give(self._conn, healthy=exc_type is None)
        return False


class _ConnectionReuse:
    def __init__(self, open_conn: Callable[[], Any], clock: Callable[[], float] = time.monotonic) -> None:
        self._open, self._clock = open_conn, clock
        self._idle: list[tuple[float, Any]] = []
        self._lock = threading.Lock()

    def take(self) -> Any:
        while True:
            with self._lock:
                entry = self._idle.pop() if self._idle else None
            if entry is None:
                return self._open()
            since, conn = entry
            if self._clock() - since > REUSE_IDLE_SECONDS or getattr(conn, "closed", False):
                self._close(conn)
                continue
            return conn

    def give(self, conn: Any, *, healthy: bool) -> None:
        if conn is None:
            return
        ok = healthy and not getattr(conn, "closed", False)
        if ok:
            try:
                from psycopg.pq import TransactionStatus

                ok = conn.info.transaction_status == TransactionStatus.IDLE
            except Exception:  # noqa: BLE001 - 상태를 못 읽으면 재사용하지 않는다
                ok = False
        with self._lock:
            if ok and len(self._idle) < REUSE_IDLE_MAX:
                self._idle.append((self._clock(), conn))
                return
        self._close(conn)

    @staticmethod
    def _close(conn: Any) -> None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def __call__(self) -> _ReusedConnection:
        return _ReusedConnection(self)


def reuse_if_enabled(connect: Callable[[], Any]) -> Callable[[], Any]:
    """`ANSWER_STORE_REUSE_CONN=1`이면 `connect`를 연결 다시 쓰기로 감싸고, 아니면 그대로 돌려준다. 답 저장소, 대화 상태(`api/threads.py`),
    인증 조회(`services/auth_store.py`)가 같은 스위치와 같은 방식(`_ConnectionReuse`)을 쓴다(사전 등록 62.40)."""
    return _ConnectionReuse(connect) if reuse_connection_enabled() else connect


def run_again(connect: Callable[[], Any], fn: Callable[[], Any]) -> Any:
    """다시 쓰는 연결(`_ConnectionReuse`)이 서버 쪽에서 끊겨 있던 경우에만 `fn`을 한 번 더 부른다. 끊긴 연결은 돌려주지 않고 닫으므로 다시 부르면 새 연결이다.
    같은 값을 두 번 읽거나 써도 같은 호출에만 쓴다. 연결을 다시 쓰지 않는 길(`connect`가 `_ConnectionReuse`가 아님)은 그대로 한 번만 부른다."""
    if not isinstance(connect, _ConnectionReuse):
        return fn()
    import psycopg

    try:
        return fn()
    except (psycopg.OperationalError, psycopg.InterfaceError):
        return fn()


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        # Supabase 풀러(transaction 모드)가 준비된 문장을 쓰지 못하므로 끈다(threads.py와 같다)
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return reuse_if_enabled(connect)   # 62.40: 저장마다 새로 연결하지 않고 다시 쓴다


_FIND_COLUMNS = ("answer_id", "user_id", "question", "answer", "as_of", "version_id", "thread_id", "version_date", "source_url")


class PgAnswerStore:
    """`db/120_answers_recall.sql` 위의 구현. `connect`는 시험에서 연결을 바꿔 넣는 자리다. 호출마다 연결한다."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn 또는 connect가 필요하다")
            connect = _default_connect(dsn)
        self._connect = connect

    def _again(self, fn: Callable[[], Any]) -> Any:
        """다시 쓰는 연결(`ANSWER_STORE_REUSE_CONN`)이 서버 쪽에서 끊겨 있던 경우에만 한 번 더 부른다. 저장 문장은 모두 같은 값을 두 번 써도 같다(ON CONFLICT).
        끊긴 연결은 돌려주지 않고 닫으므로 다시 부르면 새 연결이다. 연결을 다시 쓰지 않는 길은 그대로 한 번만 부른다."""
        return run_again(self._connect, fn)

    def _rows(self, sql: str, params: tuple | dict) -> list[tuple]:
        def run() -> list[tuple]:
            with self._connect() as conn:
                cur = conn.execute(sql, params)
                return cur.fetchall() if cur.description else []

        return self._again(run)

    def save(self, answer_id, user_id, thread_id, question, answer, as_of, citations) -> None:
        self._again(lambda: self._save(answer_id, user_id, thread_id, question, answer, as_of, citations))

    def _save(self, answer_id, user_id, thread_id, question, answer, as_of, citations) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO answers (answer_id, user_id, thread_id, question, answer, as_of) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (answer_id) DO NOTHING",
                (answer_id, user_id, thread_id or "", question, answer, as_of),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO citations (answer_id, chunk_id, version_id, rule_seq, article, version_date, source_url) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    [(answer_id, c.chunk_id, c.version_id, c.rule_seq, c.article, c.version_date, c.source_url) for c in citations],
                )

    def save_with_grounding(self, answer_id, user_id, thread_id, question, answer, as_of, citations, grounding: dict, skills_used: list[str]) -> None:
        """답, 인용, 근거 검사 결과를 연결 하나, 트랜잭션 하나, 답 INSERT 한 문장으로 쓴다(사전 등록 62.16 `ANSWER_SAVE_ONE_CONN`).
        근거 검사 결과(grounding, skills_used)는 answers 의 칸이라 따로 INSERT 하지 않는다(별도 표를 쓰지 않아 왕복 한 번이 준다. 옛 DB 이전은 db/109_realign.sql).
        검사 결과를 JSON 으로 만들 수 없으면 그 칸만 비우고(NULL) 답과 인용은 남긴다."""
        g, s = self._json_pair(grounding, skills_used)

        def run() -> None:
            with self._connect() as conn:
                with conn.transaction():
                    self._insert_answer(conn, answer_id, user_id, thread_id, question, answer, as_of, citations, g, s)

        self._again(run)

    @staticmethod
    def _json_pair(grounding: dict, skills_used: list[str]):
        import json

        from psycopg.types.json import Jsonb

        try:
            g, s = dict(grounding), list(skills_used)
            json.dumps([g, s])
        except (TypeError, ValueError):
            return None, None
        return Jsonb(g), Jsonb(s)

    @staticmethod
    def _insert_answer(conn, answer_id, user_id, thread_id, question, answer, as_of, citations, grounding=None, skills_used=None) -> None:
        if grounding is None:
            conn.execute(
                "INSERT INTO answers (answer_id, user_id, thread_id, question, answer, as_of) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (answer_id) DO NOTHING",
                (answer_id, user_id, thread_id or "", question, answer, as_of),
            )
        else:
            conn.execute(
                "INSERT INTO answers (answer_id, user_id, thread_id, question, answer, as_of, grounding, skills_used) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (answer_id) DO UPDATE SET grounding = EXCLUDED.grounding, skills_used = EXCLUDED.skills_used",
                (answer_id, user_id, thread_id or "", question, answer, as_of, grounding, skills_used),
            )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO citations (answer_id, chunk_id, version_id, rule_seq, article, version_date, source_url) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(answer_id, c.chunk_id, c.version_id, c.rule_seq, c.article, c.version_date, c.source_url) for c in citations],
            )

    def save_grounding(self, answer_id: str, grounding: dict, skills_used: list[str]) -> None:
        """이미 저장한 답의 근거 검사 결과를 쓴다(`save` 뒤에 따로 부를 때). 답이 없으면 아무것도 바꾸지 않는다."""
        g, s = self._json_pair(grounding, skills_used)
        self._rows("UPDATE answers SET grounding = %s, skills_used = %s WHERE answer_id = %s", (g, s, answer_id))

    def get_grounding(self, answer_id: str) -> dict | None:
        rows = self._rows("SELECT grounding, skills_used FROM answers WHERE answer_id = %s AND grounding IS NOT NULL", (answer_id,))
        if not rows:
            return None
        cites = self._rows("SELECT chunk_id, version_id FROM citations WHERE answer_id = %s ORDER BY chunk_id", (answer_id,))
        return {"answer_id": answer_id, "grounding": rows[0][0], "skills_used": rows[0][1],
                "citations": [{"chunk_id": c, "version_id": v} for c, v in cites]}

    def get(self, answer_id: str) -> dict | None:
        rows = self._rows("SELECT answer_id, user_id, thread_id, question, answer, as_of, created_at FROM answers WHERE answer_id = %s",
                          (answer_id,))
        if not rows:
            return None
        aid, uid, tid, q, a, as_of, created = rows[0]
        cites = self._rows("SELECT chunk_id, version_id, rule_seq, article, version_date, source_url FROM citations "
                           "WHERE answer_id = %s ORDER BY chunk_id", (answer_id,))
        return {"answer_id": aid, "user_id": uid, "thread_id": tid, "question": q, "answer": a, "as_of": as_of,
                "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                "citations": [dict(zip(("chunk_id", "version_id", "rule_seq", "article", "version_date", "source_url"), c)) for c in cites]}

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        rows = self._rows(
            "SELECT DISTINCT a.answer_id, a.user_id, a.question, a.answer, a.as_of, c.version_id, a.thread_id, c.version_date, "
            "c.source_url, a.created_at FROM citations c JOIN answers a ON a.answer_id = c.answer_id "
            "WHERE c.rule_seq = %s AND c.article = %s ORDER BY a.created_at, a.answer_id",
            (rule_seq, article),
        )
        return [dict(zip(_FIND_COLUMNS, r[:len(_FIND_COLUMNS)])) for r in rows]

    def count_by_articles(self, pairs: list[tuple[int, str]]) -> dict[tuple[int, str], int]:
        seqs, arts = [int(s) for s, _ in pairs], [a for _, a in pairs]
        rows = self._rows(
            "SELECT k.rule_seq, k.article, count(DISTINCT c.answer_id) FROM unnest(%s::bigint[], %s::text[]) AS k(rule_seq, article) "
            "LEFT JOIN citations c ON c.rule_seq = k.rule_seq AND c.article = k.article GROUP BY k.rule_seq, k.article",
            (seqs, arts),
        )
        got = {(int(s), a): int(n) for s, a, n in rows}
        return {k: got.get((int(k[0]), k[1]), 0) for k in pairs}
