"""답변·인용 저장소 (SDD 5장 `answers`, `citations`).

`AnswerStore` Protocol을 지키면 Postgres 구현으로 바꿔 끼울 수 있다(B-05).
`find_by_article`은 리콜(backend/graph/recall)이 "이 섹션을 인용한 과거 답"을 찾는 데 쓴다. 이름·반환 키는 리콜 담당과 맞춘 것이다.

- `InMemoryAnswerStore`: 테스트·데모용. 프로세스가 끝나면 사라진다(기본).
- `PgAnswerStore`: `db/120_answers_recall.sql`의 `answers`, `citations`, `answer_grounding` 표. 재시작해도 답과 인용이 남아 리콜이 지난 답을 찾을 수 있다.
  앱은 `RECALL_STORE=postgres`일 때만 이 구현을 쓴다(`backend/graph/recall/runtime.py`).
"""
from __future__ import annotations

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


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        # Supabase 풀러(transaction 모드)가 준비된 문장을 쓰지 못하므로 끈다(threads.py와 같다)
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


_FIND_COLUMNS = ("answer_id", "user_id", "question", "answer", "as_of", "version_id", "thread_id", "version_date", "source_url")


class PgAnswerStore:
    """`db/120_answers_recall.sql` 위의 구현. `connect`는 시험에서 연결을 바꿔 넣는 자리다. 호출마다 연결한다."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            if not dsn:
                raise ValueError("dsn 또는 connect가 필요하다")
            connect = _default_connect(dsn)
        self._connect = connect

    def _rows(self, sql: str, params: tuple | dict) -> list[tuple]:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def save(self, answer_id, user_id, thread_id, question, answer, as_of, citations) -> None:
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

    def save_grounding(self, answer_id: str, grounding: dict, skills_used: list[str]) -> None:
        from psycopg.types.json import Jsonb

        self._rows(
            "INSERT INTO answer_grounding (answer_id, grounding, skills_used) VALUES (%s, %s, %s) "
            "ON CONFLICT (answer_id) DO UPDATE SET grounding = EXCLUDED.grounding, skills_used = EXCLUDED.skills_used",
            (answer_id, Jsonb(dict(grounding)), Jsonb(list(skills_used))),
        )

    def get_grounding(self, answer_id: str) -> dict | None:
        rows = self._rows("SELECT grounding, skills_used FROM answer_grounding WHERE answer_id = %s", (answer_id,))
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
