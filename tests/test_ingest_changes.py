"""바뀐 섹션 목록 list_changed 시험 (docs/specs/mcp.md AC-06·AC-07·EC-03·EC-06·EC-07·EC-13).

DB 없이: 입력 검사, 실행 기록이 없을 때. TEST_DATABASE_URL이 있으면 증분 수집(schedule.run)이 실제로 쓴 표를 읽는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.rag.ingest import changes, schedule

ROOT = Path(__file__).resolve().parents[1]


class FakeStore:
    def __init__(self, rows=(), run=None):
        self._rows, self._run = list(rows), run

    def rows(self, since, org, limit):
        return self._rows[:limit]

    def last_run(self):
        return self._run


@pytest.mark.parametrize("since", ["2026-1-1", "2026-02-30", "", None, "2026-11-03T00:00"])
def test_bad_since_is_value_error(since):
    with pytest.raises(ValueError):
        changes.list_changed(since, store=FakeStore())


@pytest.mark.parametrize("limit", [0, 201, -1, True, 1.5])
def test_bad_limit_is_value_error(limit):
    with pytest.raises(ValueError):
        changes.list_changed("2026-10-01", limit=limit, store=FakeStore())


def test_no_run_is_none_not_empty_ok():
    """EC-06: 실행 기록이 없으면 last_run=None("아직 모름"). 빈 목록 + 실행 있음("바뀐 것 없음")과 다르다."""
    assert changes.list_changed("2026-10-01", store=FakeStore()) == ([], None)
    run = {"run_id": 3, "status": "noop", "finished_at": "2026-11-02T18:08:00+00:00", "to_commit": "abc",
           "list_complete": True}
    items, last = changes.list_changed("2026-10-01", store=FakeStore(run=run))
    assert items == [] and last.run_id == 3 and last.status == "noop"


# ---------- DB (로컬 pgvector) ----------

DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
GONE = "content/handbook/security/test-gone.md"
GONE_RAW = "---\ntitle: Test Gone\n---\n\n## Old rule\n\nThis page will be removed.\n"


@pytest.fixture
def conn():
    import psycopg
    from pgvector.psycopg import register_vector
    from tests import test_ingest_schedule as ts
    with psycopg.connect(DB, prepare_threshold=None) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("DROP TABLE IF EXISTS changed_articles, sync_runs, chunks, versions, docs, index_meta, "
                  "query_translations CASCADE")
        c.execute((ROOT / "db/201_search.sql").read_text(encoding="utf-8"))
        c.execute((ROOT / "db/202_sync.sql").read_text(encoding="utf-8"))
        c.commit()
        register_vector(c)
        ts.seed(c, ts.PATH, ts.OLD, "oldv00000000", "2026-09-01")
        ts.seed(c, GONE, GONE_RAW, "gone00000000", "2026-09-01")
        c.execute("""INSERT INTO index_meta (id, embedder, revision, dim, n_chunks, chunks_sha256, vectors_sha256, status)
                     VALUES (1, %s, 'r', %s, 0, 'x', 'y', 'ready')""", (ts.MODEL, ts.DIM))
        c.commit()
        yield c


@pytest.fixture
def pg():
    st = changes.PgChangesStore(DB)
    yield st
    st.pool.close()


def run_once(c, *, list_complete=True, removed=(GONE,), slot=None):
    from tests import test_ingest_schedule as ts
    src = ts.source(ts.OLD, ts.NEW, ["newv00000000", "2026-10-30", False], removed=removed, gone_raw=GONE_RAW,
                    list_complete=list_complete)
    out = schedule.run(c, trigger="schedule", now=datetime(2026, 11, 2, 18, 7, tzinfo=timezone.utc), slot=slot,
                       model=ts.MODEL, dim=ts.DIM, source=src, embed_fn=ts.Embed(), log=lambda *_: None)
    assert out["status"] == "succeeded", out
    return out


def table_print(c) -> str:
    rows = c.execute("SELECT event_id, status FROM changed_articles ORDER BY event_id").fetchall()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


@needs_db
def test_pg_no_run_is_not_ready(conn, pg):
    """AC-07 (가): sync_runs가 빈 DB → last_run None."""
    assert changes.list_changed("2026-01-01", store=pg) == ([], None)


@needs_db
def test_pg_lists_changes_and_does_not_write(conn, pg):
    """AC-06·AC-07 (나): 바뀐 섹션과 쪽 통째 삭제를 읽고, 두 번 불러도 같으며 표 지문이 그대로다."""
    run_once(conn)
    before = table_print(conn)
    a = changes.list_changed("2026-10-30", store=pg)
    b = changes.list_changed("2026-10-30", store=pg)
    assert a == b and table_print(conn) == before
    items, last = a
    kinds = {(i.article, i.change_type, i.new_version_date) for i in items}
    assert ("Disclosure", "modified", "2026-10-30") in kinds                      # 새 판 날짜 = since 인 날도 든다(>=)
    assert ("Old rule", "removed", "") in kinds                                     # 쪽 통째 삭제(새 판 없음)도 든다
    assert last.status == "succeeded" and last.list_complete is True and last.to_commit == "head1"
    assert [i.new_version_date or "9" for i in items] == sorted(i.new_version_date or "9" for i in items)
    statuses = {r[0] for r in conn.execute("SELECT status FROM changed_articles")}
    assert statuses == {"pending"}                                                  # 읽기만, sent로 안 바꿈


@needs_db
def test_pg_since_after_change_is_empty_ok(conn, pg):
    """AC-07 (나): since 뒤 바뀐 것이 없으면 빈 목록 + 마지막 실행(삭제 줄은 적은 날 기준이라 내일 since면 빠짐)."""
    run_once(conn, removed=())
    items, last = changes.list_changed("2026-10-31", store=pg)
    assert items == [] and last is not None and last.finished_at


@needs_db
def test_pg_org_and_limit(conn, pg):
    run_once(conn)
    assert changes.list_changed("2026-10-01", org="finance", store=pg)[0] == []
    assert len(changes.list_changed("2026-10-01", org="security", store=pg)[0]) >= 2
    assert len(changes.list_changed("2026-10-01", limit=1, store=pg)[0]) == 1


@needs_db
def test_pg_held_run_is_flagged(conn, pg):
    """AC-07 (다): 마지막 성공 실행이 목록 불완전(삭제 보류)이면 list_complete=False."""
    run_once(conn, list_complete=False)
    _, last = changes.list_changed("2026-10-01", store=pg)
    assert last.list_complete is False
