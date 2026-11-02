"""증분 수집 ② schedule.py 시험 (docs/specs/incremental.md AC).

DB 없이 도는 시험(슬롯·설정·처음 수집과 같은 청크)과, TEST_DATABASE_URL이 있을 때만 도는 DB 시험(로컬 pgvector)으로 나뉜다.
DB 시험은 git 대신 가짜 원천(diff.py의 실제 섹션 비교로 만든 보고서)과 가짜 임베딩(글의 해시로 만든 4차원 벡터)을 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from backend.rag.ingest import diff, schedule
from backend.rag.ingest.handbook import rule_seq

ROOT = Path(__file__).resolve().parents[1]
PATH = "content/handbook/security/test-disclosure.md"
OLD = "---\ntitle: Test Disclosure\n---\n\n## Disclosure\n\nSecurity issues are disclosed 30 days after the patch.\n\n" \
      "## Contacts\n\nAsk the security team in the channel.\n"
NEW = OLD.replace("30 days", "90 days")
LINK_ONLY = OLD.replace("Ask the security team", "Ask the [security team](https://example.com/new)")
MODEL, DIM = "test-model", 4
NOW = datetime(2026, 11, 2, 18, 7, tzinfo=timezone.utc)


# ---------- DB 없이 ----------

def test_slot_is_utc_date():
    kst = timezone(timedelta(hours=9))
    assert schedule.slot_of(datetime(2026, 11, 3, 3, 7, tzinfo=kst)) == "2026-11-02"      # 한국 03:07 = UTC 전날 18:07
    assert schedule.slot_of(datetime(2026, 11, 2, 18, 50, tzinfo=timezone.utc)) == "2026-11-02"   # 늦게 돌아도 같은 슬롯
    with pytest.raises(ValueError):
        schedule.slot_of(datetime(2026, 11, 2, 18, 7))                                      # 시간대 없는 시각은 거부


def test_chunk_settings_match_first_collect():
    src = (ROOT / "backend/rag/ingest/chunk.py").read_text(encoding="utf-8")
    assert f'"--size", type=int, default={schedule.CHUNK_SIZE}' in src
    assert f'"--overlap", type=int, default={schedule.CHUNK_OVERLAP}' in src


def test_event_id_same_change_same_id():
    a = {"rule_seq": 1, "article": "A > B", "new_version_date": "2026-10-30", "change_type": "modified"}
    assert schedule.event_id(a) == schedule.event_id(dict(a))
    assert schedule.event_id(a) != schedule.event_id({**a, "change_type": "removed"})


@pytest.mark.skipif(not (ROOT / "data/chunks/chunks.jsonl").exists() or not (ROOT / "data/corpus/pages.jsonl").exists(),
                    reason="처음 수집 결과(data/chunks·data/corpus) 없음")
def test_page_chunks_same_as_first_collect():
    """증분이 만든 청크 = 처음 수집이 만든 청크(같은 원문·같은 판이면 chunk_id·글·줄 범위가 같다). 쪽 5개 표본."""
    pages = [json.loads(x) for x in (ROOT / "data/corpus/pages.jsonl").open(encoding="utf-8")]
    want = {}
    for line in (ROOT / "data/chunks/chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        want.setdefault(c["rule_seq"], []).append(c)
    sample = [p for p in pages if not p["redirect_to"] and p["rule_seq"] in want][::300][:5]
    assert sample
    for p in sample:
        raw = (ROOT / "data/corpus/handbook" / p["path"].removeprefix("content/handbook/")).read_text(encoding="utf-8")
        _, got = schedule.page_chunks(p["path"], raw, [p["version_id"], p["version_date"], p["version_date_before"]],
                                      p["fetched_at"])
        key = lambda c: (c["chunk_id"], c["text"], c["line_start"], c["line_end"], c["article"])   # noqa: E731
        assert [key(c) for c in got] == [key(c) for c in want[p["rule_seq"]]], p["path"]


# ---------- DB ----------

DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")


def fake_vec(text: str) -> np.ndarray:
    v = np.frombuffer(hashlib.sha256(text.encode()).digest()[:DIM * 4], dtype=np.uint32).astype(np.float32) + 1
    return v / np.linalg.norm(v)


class Embed:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("모델을 못 불러옴")
        return np.stack([fake_vec(t) for t in texts])


def source(old_raw, new_raw, new_version, *, head="head1", head_date="2026-10-30", removed=(), list_complete=True):
    """diff.diff_commits 와 같은 모양의 보고서. 섹션 판정은 diff.py 실제 함수로."""
    page = diff.page_of(PATH)
    pages, articles, raw = [], [], {}
    if new_raw is not None:
        secs = diff.section_changes(page, old_raw, new_raw)
        articles = [a.model_dump() for a in diff.changed_articles(page["rule_seq"], secs, "2026-09-01", new_version[1])]
        pages.append({"path": PATH, "rule_seq": page["rule_seq"], "page_change": "modified" if old_raw else "added",
                      "new_version": new_version, "kind": diff.page_kind(secs), "review": False})
        raw[PATH] = new_raw
    for path in removed:
        pages.append({"path": path, "rule_seq": rule_seq(path), "page_change": "removed", "new_version": None,
                      "kind": "content", "review": False})
    report = {"changes": {"removed": [[p, "blob"] for p in removed], "list_complete": list_complete,
                          "reasons": [] if list_complete else ["폴더 비었음: security"]},
              "pages": pages, "articles": articles, "summary": {}}
    calls = []

    def fn(from_commit):
        calls.append(from_commit)
        return schedule.Source(head, head_date, report, raw)
    fn.calls = calls
    return fn


@pytest.fixture
def conn():
    import psycopg
    from pgvector.psycopg import register_vector
    with psycopg.connect(DB, prepare_threshold=None) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("DROP TABLE IF EXISTS changed_articles, sync_runs, chunks, versions, docs, index_meta, "
                  "query_translations CASCADE")
        c.execute((ROOT / "db/201_search.sql").read_text(encoding="utf-8"))
        c.execute((ROOT / "db/202_sync.sql").read_text(encoding="utf-8"))
        c.commit()
        register_vector(c)
        seed(c, PATH, OLD, "oldv00000000", "2026-09-01")
        c.execute("""INSERT INTO index_meta (id, embedder, revision, dim, n_chunks, chunks_sha256, vectors_sha256, status)
                     VALUES (1, %s, 'r', %s, 0, 'x', 'y', 'ready')""", (MODEL, DIM))
        c.commit()
        yield c


def seed(c, path, raw, vid, vdate):
    """스냅샷 적재(load_snapshot)가 넣은 것과 같은 모양: 쪽 하나, 판 하나(현재), 청크와 벡터."""
    page, chunks = schedule.page_chunks(path, raw, [vid, vdate, False], "2026-10-30")
    c.execute("INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, %s, %s, %s, '2026-10-30')",
              (page["rule_seq"], page["org"], page["title"], page["source_url"]))
    c.execute("INSERT INTO versions (rule_seq, version_id, version_date, valid_from) VALUES (%s, %s, %s, %s)",
              (page["rule_seq"], vid, vdate, vdate))
    for i, x in enumerate(chunks):
        c.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url,
                                         line_start, line_end, embedding, embedder)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                  (x["chunk_id"], vid, x["rule_seq"], x["seq"], i, x["article"], x["kind"], x["text"], x["source_url"],
                   x["line_start"], x["line_end"], fake_vec(x["text"]), MODEL))


def fingerprint(c) -> str:
    rows = []
    for t, order in (("docs", "rule_seq"), ("versions", "rule_seq, version_id"), ("chunks", "chunk_id, version_id"),
                     ("changed_articles", "event_id")):
        cols = "*" if t != "changed_articles" else "event_id, rule_seq, article, change_type, status"
        rows.append([str(r) for r in c.execute(f"SELECT {cols} FROM {t} ORDER BY {order}")])
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def current_and_asof(as_of):
    from backend.rag.retrieve.search import PgStore
    pg = PgStore(DB)
    try:
        q = fake_vec("security")
        return {v for (_, v), _ in pg.vector_top(q, MODEL, None, as_of, 50)}
    finally:
        pg.pool.close()


def go(c, src, emb=None, slot=None, now=NOW):
    return schedule.run(c, trigger="schedule", now=now, slot=slot, model=MODEL, dim=DIM, source=src,
                        embed_fn=emb or Embed(), log=lambda *_: None)


@needs_db
def test_new_version_keeps_old_for_as_of(conn):
    """AC-07: 새 판이 현재가 되고, 동결일(as_of=10/27) 검색은 옛 판 그대로. 바뀐 섹션은 리콜 표에."""
    out = go(conn, source(OLD, NEW, ["newv00000000", "2026-10-30", False]))
    assert out["status"] == "succeeded" and out["modified"] == 1 and out["articles"] >= 1
    assert current_and_asof(None) == {"newv00000000"}
    assert current_and_asof("2026-10-27") == {"oldv00000000"}
    arts = conn.execute("SELECT article, change_type, status FROM changed_articles").fetchall()
    assert ("Disclosure", "modified", "pending") in arts
    assert conn.execute("SELECT generation FROM index_meta").fetchone()[0] == 1


@needs_db
def test_change_on_frozen_day_does_not_leak_into_frozen_search(conn):
    """고정 커밋과 같은 날(10/27) 고친 쪽: 판 날짜는 그대로 두되 유효 시작을 10/28로 → 동결일 검색은 옛 판."""
    go(conn, source(OLD, NEW, ["newv00000000", "2026-10-27", False]))
    assert current_and_asof("2026-10-27") == {"oldv00000000"}
    row = conn.execute("SELECT version_date, valid_from FROM versions WHERE version_id = 'newv00000000'").fetchone()
    assert [str(x) for x in row] == ["2026-10-27", "2026-10-28"]


@needs_db
def test_same_commit_again_changes_nothing(conn):
    """AC-03: 같은 커밋을 다른 슬롯으로 다시 → noop, 반영 함수를 직접 다시 불러도 추가·갱신 0, 표 지문 같음."""
    src = source(OLD, NEW, ["newv00000000", "2026-10-30", False])
    go(conn, src, slot="2026-11-02")
    before = fingerprint(conn)
    again = go(conn, src, slot="manual-1")
    assert again["status"] == "noop" and src.calls[-1] == "head1"                # 마지막 성공 커밋부터 본다
    run_id = conn.execute("SELECT max(run_id) FROM sync_runs").fetchone()[0]
    counts = schedule.apply(conn, run_id, src("head1"), MODEL, Embed(), NOW, log=lambda *_: None)
    conn.commit()
    assert (counts["added"], counts["modified"], counts["articles"], counts["embedded"]) == (0, 0, 0, 0)
    assert fingerprint(conn) == before


@needs_db
def test_same_slot_runs_once(conn):
    """AC-05: 같은 슬롯 두 번 → 두 번째는 원천·임베딩 호출 0."""
    src, emb = source(OLD, NEW, ["newv00000000", "2026-10-30", False]), Embed()
    assert go(conn, src, emb)["status"] == "succeeded"
    second = go(conn, src, emb)
    assert second["status"] == "skipped_duplicate"
    assert len(src.calls) == 1 and len(emb.calls) == 1
    assert conn.execute("SELECT count(*) FROM sync_runs").fetchone()[0] == 1


@needs_db
def test_failure_rolls_back_everything(conn, monkeypatch):
    """AC-06: 쓰는 도중 실패 → 표가 실패 전과 같고 failed 기록, 다음 실행은 같은 커밋부터 다시."""
    before = fingerprint(conn)
    src = source(OLD, NEW, ["newv00000000", "2026-10-30", False])
    # 새 판·청크를 쓴 뒤, 바뀐 섹션을 쓰는 단계에서 실패시킨다(쓰기 전에 실패하면 트랜잭션을 시험하지 못한다)
    monkeypatch.setattr(schedule, "event_id", lambda a: (_ for _ in ()).throw(RuntimeError("일부러 실패")))
    with pytest.raises(schedule.SyncError):
        go(conn, src)
    assert fingerprint(conn) == before
    row = conn.execute("SELECT status, error_kind, from_commit FROM sync_runs").fetchone()
    assert row == ("failed", "RuntimeError", schedule.PINNED_COMMIT)
    monkeypatch.undo()
    go(conn, src, slot="manual-1")
    assert src.calls == [schedule.PINNED_COMMIT, schedule.PINNED_COMMIT]


@needs_db
def test_incomplete_list_holds_deletion(conn):
    """AC-04: 목록이 불완전하면 사라진 쪽을 닫지 않는다. 완전하면 닫고, 동결일 검색에는 남는다."""
    gone = "content/handbook/security/gone.md"
    seed(conn, gone, OLD.replace("Test Disclosure", "Gone"), "gonev0000000", "2026-09-01")
    conn.commit()
    held = go(conn, source(OLD, None, None, removed=[gone], list_complete=False))
    assert (held["removed_seen"], held["removed_applied"]) == (1, 0)
    assert conn.execute("SELECT valid_to FROM versions WHERE version_id = 'gonev0000000'").fetchone()[0] is None
    done = go(conn, source(OLD, None, None, head="head2", removed=[gone]), slot="manual-1")
    assert done["removed_applied"] == 1
    assert "gonev0000000" not in current_and_asof(None)
    assert "gonev0000000" in current_and_asof("2026-10-27")


@needs_db
def test_link_only_change_reuses_vectors(conn):
    """서식만 바뀐 쪽: 리콜에 안 보내고, 임베딩 입력 글이 같으면 모델을 부르지 않는다."""
    emb = Embed()
    out = go(conn, source(OLD, LINK_ONLY, ["linkv0000000", "2026-10-30", False]), emb)
    assert out["format_only"] == 1 and out["articles"] == 0
    assert emb.calls == [] and out["embedded"] == 0 and out["reused"] > 0


@needs_db
def test_index_mismatch_stops_before_work(conn):
    """색인 장부 모델이 다르면(차원이 같아도) 원천을 부르지 않고 failed — 조용히 섞인 벡터를 만들지 않는다(rag1-11)."""
    conn.execute("UPDATE index_meta SET embedder = 'other-model'")
    conn.commit()
    src = source(OLD, NEW, ["newv00000000", "2026-10-30", False])
    with pytest.raises(schedule.SyncError):
        go(conn, src)
    assert src.calls == []
    assert conn.execute("SELECT error_kind FROM sync_runs").fetchone()[0] == "index_mismatch"


@needs_db
def test_embedding_failure_keeps_old_current(conn):
    """임베딩 실패 → 실행 전체 failed, 장부는 옛 커밋에 그대로(새 판을 주장하지 않음)·현재 판도 옛 판."""
    with pytest.raises(schedule.SyncError):
        go(conn, source(OLD, NEW, ["newv00000000", "2026-10-30", False]), Embed(fail=True))
    assert current_and_asof(None) == {"oldv00000000"}
    assert schedule.last_commit(conn) == schedule.PINNED_COMMIT
