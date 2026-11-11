"""대화 목록 저장소 시험 (`backend/api/threads.py`, `db/111_threads.sql`).

기본은 메모리 구현과 가짜 연결로 돈다. 진짜 Postgres로도 돌리려면 `PROVENA_TEST_DATABASE_URL`에 시험용 DB 주소를 준다(그 DB에 threads 표를 만든다).
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

from backend.api import threads as T

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "db" / "111_threads.sql"


def _exercise(store) -> None:
    store.thread_touch("alice", "t1", title="  첫   질문 " + "가" * 100, status="running")
    store.thread_touch("bob", "t1", title="밥의 질문", status="running")
    store.thread_touch("alice", "t2", title="두 번째", status="idle")
    store.thread_touch("alice", "t1", title="바뀌면 안 되는 제목", status="idle", last={"kind": "answer", "answer": "답", "answer_id": "a1", "as_of": None})
    a1 = store.thread_get("alice", "t1")
    assert a1["title"] == ("첫 질문 " + "가" * 100)[:80] and a1["status"] == "idle" and a1["last"]["answer_id"] == "a1"
    assert store.thread_get("bob", "t1")["title"] == "밥의 질문" and store.thread_get("bob", "t1")["last"] is None
    assert store.thread_get("bob", "t2") is None and store.thread_get("carol", "t1") is None
    assert [t["thread_id"] for t in store.threads_of("alice")] == ["t1", "t2"]
    assert [t["thread_id"] for t in store.threads_of("bob")] == ["t1"] and store.threads_of("carol") == []
    store.thread_touch("alice", "t2", status="pending_approval")
    assert store.thread_get("alice", "t2")["status"] == "pending_approval" and store.thread_get("alice", "t2")["title"] == "두 번째"
    with pytest.raises(ValueError):
        store.thread_touch("alice", "t1", status="done")


def test_memory_store_separates_users_and_keeps_the_first_title():
    _exercise(T.InMemoryThreadStore())


class FakeCursor:
    def __init__(self, log):
        self.log, self.description = log, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.log.append((sql, params))
        self.description = ("x",) if sql.lstrip().startswith("SELECT") else None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, row_factory=None):
        return FakeCursor(self.log)


def test_postgres_statements_always_filter_by_user():
    log: list = []
    store = T.PostgresThreadStore(connect=lambda: FakeConn(log))
    store.thread_touch("alice", "t1", title="질문", status="running")
    assert store.thread_get("alice", "t1") is None and store.threads_of("alice") == []
    upsert, get, listing = (sql for sql, _ in log)
    assert "ON CONFLICT (user_id, thread_id)" in upsert and "title =" not in upsert.split("DO UPDATE", 1)[1]   # 제목은 처음 값을 둔다
    assert "WHERE user_id = %s AND thread_id = %s" in get and log[1][1] == ("alice", "t1")
    assert "WHERE user_id = %s" in listing and "ORDER BY updated_at DESC" in listing and log[2][1] == ("alice",)


def test_postgres_connection_turns_off_prepared_statements(monkeypatch):
    import psycopg

    seen = {}
    monkeypatch.setattr(psycopg, "connect", lambda dsn, **kw: seen.update(kw) or FakeConn([]))
    T.PostgresThreadStore("postgresql://u:p@127.0.0.1:1/x")._connect()
    assert seen["prepare_threshold"] is None and seen["autocommit"] is True


def test_schema_file_is_idempotent_with_rls_and_auto_applied_by_compose():
    sql = SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS threads" in sql and "PRIMARY KEY (user_id, thread_id)" in sql
    assert "CREATE INDEX IF NOT EXISTS threads_user_updated_idx ON threads (user_id, updated_at DESC)" in sql
    assert "ALTER TABLE threads ENABLE ROW LEVEL SECURITY" in sql
    assert "'idle', 'running', 'pending_approval'" in sql and tuple(T.STATUSES) == ("idle", "running", "pending_approval")
    numbers = [re.match(r"(\d+)_", p.name).group(1) for p in (ROOT / "db").glob("*.sql")]
    assert numbers.count("111") == 1 and len(numbers) == len(set(numbers))   # 번호가 겹치지 않는다
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./db:/docker-entrypoint-initdb.d" in compose and SQL.parent.name == "db"   # 하위 폴더가 아니라 db/ 바로 아래라 첫 기동에 적용된다


def test_env_example_lists_the_direct_database_url_name_without_a_value():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "DATABASE_DIRECT_URL=" in lines


@pytest.mark.skipif(not (os.getenv("PROVENA_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")), reason="PROVENA_TEST_DATABASE_URL·TEST_DATABASE_URL 없음")
def test_postgres_store_against_a_real_database():
    store = T.PostgresThreadStore(os.getenv("PROVENA_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL"))
    store.ensure_schema()
    prefix = uuid.uuid4().hex[:8]

    class Prefixed:   # 시험마다 다른 사용자 이름을 써서 앞 시험의 줄과 섞이지 않게 한다
        def __getattr__(self, name):
            fn = getattr(store, name)
            return lambda user_id, *a, **k: fn(f"{prefix}-{user_id}", *a, **k)

    _exercise(Prefixed())
