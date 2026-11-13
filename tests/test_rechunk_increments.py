"""증분 판 일회성 다시 청킹 `backend/rag/ingest/rechunk_increments.py` 시험 (결정 0118, 사전 등록 62.62).

DB 없이 도는 시험(판별·분류·CLI 거부)과, TEST_DATABASE_URL이 있을 때만 도는 DB 시험(로컬 pgvector, test_ingest_schedule.py와 같은 방식)으로 나뉜다.
DB 시험은 git 대신 가짜 쪽 원문 읽기와 가짜 임베딩(글의 해시로 만든 4차원 벡터)을 쓴다. 네트워크·Voyage·운영 DB는 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from backend.rag.ingest import rechunk_increments as R
from backend.rag.ingest import schedule
from backend.rag.ingest.handbook import rule_seq
from backend.rag.retrieve import links

ROOT = Path(__file__).resolve().parents[1]
MODEL, DIM = "test-model", 4
SNAP_ROWS = 10                 # 시험용: ord가 10 이상이면 증분 행
PATH_SNAP = "content/handbook/security/snap-page.md"
PATH_INC = "content/handbook/security/inc-page.md"
PATH_CLOSED = "content/handbook/security/closed-page.md"
RAW = ("---\ntitle: {t}\n---\n\n## Alpha\n\nAlpha rule text number one.\n\n## Beta\n\nBeta rule text number two.\n\n"
       "## Gamma\n\nGamma rule text number three.\n")
RAW_INC, RAW_SNAP, RAW_CLOSED = RAW.format(t="Inc Page"), RAW.format(t="Snap Page"), RAW.format(t="Closed Page")
VID_SNAP, VID_INC, VID_CLOSED_OLD, VID_CLOSED_NEW = "snap00000000", "inc000000000", "cl0000000001", "cl0000000002"


# ---------- DB 없이 ----------

def test_plan_version_classifies_rows():
    t = R.Target(1, "v", "2026-11-01", False, 10)
    base = {"seq": 0, "article": "A", "kind": "article", "source_url": "u", "text_sha256": "s", "line_start": 1, "line_end": 2}
    t.rows = [{**base, "chunk_id": "same", "text": "t1"}, {**base, "chunk_id": "chg", "text": "old"},
              {**base, "chunk_id": "meta", "text": "m", "line_end": 9}, {**base, "chunk_id": "gone", "text": "g"}]
    chunks = [{**base, "chunk_id": "same", "text": "t1"}, {**base, "chunk_id": "chg", "text": "new"},
              {**base, "chunk_id": "meta", "text": "m"}, {**base, "chunk_id": "fresh", "text": "f"}]
    p = R.plan_version(t, "p.md", {}, chunks)
    assert (p.unchanged, p.changed, p.new, p.removed) == (["same"], ["chg", "meta"], ["fresh"], ["gone"])
    assert p.dirty
    assert R.plan_version(t, "p.md", {}, [chunks[0]]).dirty                # 사라짐이 있으면 dirty
    t.rows = [chunks[0]]
    assert not R.plan_version(t, "p.md", {}, [chunks[0]]).dirty


def test_snapshot_versions_reads_doc_id(tmp_path):
    m = tmp_path / "m.jsonl"
    m.write_text('{"doc_id": 5, "version_id": "abc"}\n\n{"doc_id": "7", "version_id": "def"}\n', encoding="utf-8")
    assert R.snapshot_versions(m) == {(5, "abc"), (7, "def")}
    m.write_text("", encoding="utf-8")
    with pytest.raises(R.Refused):
        R.snapshot_versions(m)


@pytest.mark.skipif(not (ROOT / "data/manifest.jsonl").exists() or not (ROOT / "data/index/chunks.jsonl").exists(),
                    reason="스냅샷 파일 없음")
def test_manifest_covers_every_snapshot_chunk_version():
    """스냅샷 청크 파일의 (rule_seq, version_id)가 모두 manifest에 있다 → manifest로 스냅샷 판을 가려도 스냅샷 행을 대상으로 잡지 않는다."""
    snap = R.snapshot_versions(ROOT / "data/manifest.jsonl")
    seen = set()
    with (ROOT / "data/index/chunks.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            seen.add((int(r["rule_seq"]), r["version_id"]))
    assert seen <= snap


def test_estimate_uses_price_and_is_zero_for_nothing():
    assert R.estimate([])["est_cost_usd"] == 0
    e = R.estimate(["가" * 1000])
    assert e["est_tokens"] == 400 and e["est_cost_usd"] == round(400 * e["usd_per_mtok"] / 1e6, 6)


def test_cli_refuses_without_env_and_fake_on_remote_db(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert R.main(["--dry-run"]) == 2
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secretpw@db.example.com:5432/x")
    assert R.main(["--fake"]) == 2                                        # 운영으로 보이는 DB에는 가짜 벡터를 넣지 못한다
    out = capsys.readouterr()
    assert "secretpw" not in out.out + out.err                            # 접속 정보는 출력하지 않는다


def test_git_pages_reads_page_at_to_commit_and_checks_version_id(tmp_path):
    """로컬 임시 저장소만 쓴다(네트워크 없음). 판 번호 = 그 쪽을 마지막으로 고친 커밋의 앞 12자리, 원문 = to_commit 시점의 글."""
    import subprocess
    repo = tmp_path / "r"
    (repo / "content/handbook/security").mkdir(parents=True)

    def git(*a):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True, check=True).stdout.decode().strip()
    git("init", "-q")
    f = repo / PATH_INC
    f.write_text("v1\n", encoding="utf-8", newline="\n")
    git("add", "-A"); git("commit", "-q", "-m", "c1")
    c1 = git("rev-parse", "HEAD")
    (repo / "content/handbook/security/other.md").write_text("x\n", encoding="utf-8", newline="\n")
    git("add", "-A"); git("commit", "-q", "-m", "c2")
    c2 = git("rev-parse", "HEAD")
    gp = object.__new__(R.GitPages)
    gp.cache, gp.origins = repo, {rule_seq(PATH_INC): (PATH_INC, c2)}
    assert gp(rule_seq(PATH_INC), c1[:12]) == (PATH_INC, "v1\n")          # c2는 이 쪽을 안 고쳤다 → 마지막 수정은 c1
    with pytest.raises(R.SourceError) as e:
        gp(rule_seq(PATH_INC), "0" * 12)
    assert e.value.kind == "version_mismatch"
    with pytest.raises(R.SourceError) as e:
        gp(rule_seq(PATH_SNAP), c1[:12])
    assert e.value.kind == "source_unknown"


def test_fake_embed_is_deterministic_and_unit_length():
    f = R.fake_embed(8)
    a, b = f(["x", "y"]), f(["x", "y"])
    assert np.allclose(a, b) and np.allclose(np.linalg.norm(a, axis=1), 1, atol=1e-5) and not np.allclose(a[0], a[1])


# ---------- DB ----------

DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")


def fake_vec(text: str) -> np.ndarray:
    v = np.frombuffer(hashlib.sha256(text.encode()).digest()[:DIM * 4], dtype=np.uint32).astype(np.float32) + 1
    return v / np.linalg.norm(v)


class Embed:
    def __init__(self, hook=None):
        self.calls, self.hook = [], hook

    def __call__(self, texts):
        self.calls.append(list(texts))
        if self.hook:
            self.hook()
        return np.stack([fake_vec(t) for t in texts])


def insert_rows(c, vid, rows, ord0):
    for i, x in enumerate(rows):
        c.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url, text_sha256,
                                         line_start, line_end, embedding, embedder, link_targets)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}')""",
                  (x["chunk_id"], vid, x["rule_seq"], x["seq"], ord0 + i, x["article"], x["kind"], x["text"], x["source_url"],
                   x["text_sha256"], x["line_start"], x["line_end"], fake_vec(x["text"]), MODEL))


def seed_page(c, path, raw, vid, vdate, valid_to=None):
    page, chunks = schedule.page_chunks(path, raw, [vid, vdate, False], "2026-11-09")
    c.execute("""INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, %s, %s, %s, '2026-11-09')
                 ON CONFLICT (rule_seq) DO NOTHING""", (page["rule_seq"], page["org"], page["title"], page["source_url"]))
    c.execute("INSERT INTO versions (rule_seq, version_id, version_date, valid_from, valid_to) VALUES (%s, %s, %s, %s, %s)",
              (page["rule_seq"], vid, vdate, vdate, valid_to))
    return page, chunks


def old_chunker_rows(chunks):
    """옛 청크 생성 코드가 만들었을 행을 흉내낸다: 첫 청크는 글이 다르고(같은 id), 둘째는 없고, 가짜 id 행이 하나 더 있다."""
    first = {**chunks[0], "text": chunks[0]["text"] + "\nOLD-OVERLAP"}
    extra = {**chunks[0], "chunk_id": "deadbeef00000000", "seq": 99, "text": "orphan old chunk"}
    return [first, chunks[2], extra]


@pytest.fixture
def conn():
    import psycopg
    from pgvector.psycopg import register_vector
    with psycopg.connect(DB, prepare_threshold=None) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("DROP TABLE IF EXISTS changed_articles, sync_runs, chunks, versions, docs, index_meta, query_translations CASCADE")
        c.execute((ROOT / "db/201_search.sql").read_text(encoding="utf-8"))
        c.execute((ROOT / "db/202_sync.sql").read_text(encoding="utf-8"))
        c.commit()
        register_vector(c)
        # 스냅샷 판(ord 0..2, 현재), 증분 판(ord 10.., 현재, 옛 청크 코드 행), 닫힌 증분 판(ord 20.., valid_to 있음)
        _, snap_chunks = seed_page(c, PATH_SNAP, RAW_SNAP, VID_SNAP, "2026-09-01")
        insert_rows(c, VID_SNAP, snap_chunks, 0)
        seed_page(c, PATH_CLOSED, RAW_CLOSED, VID_CLOSED_OLD, "2026-09-01", "2026-11-02")
        _, closed_chunks = seed_page(c, PATH_CLOSED, RAW_CLOSED.replace("one", "uno"), VID_CLOSED_NEW, "2026-11-02")
        insert_rows(c, VID_CLOSED_OLD, schedule.page_chunks(PATH_CLOSED, RAW_CLOSED, [VID_CLOSED_OLD, "2026-09-01", False], "x")[1], 3)
        _, inc_chunks = seed_page(c, PATH_INC, RAW_INC, VID_INC, "2026-11-05")
        insert_rows(c, VID_INC, old_chunker_rows(inc_chunks), 10)
        c.execute("""INSERT INTO index_meta (id, embedder, revision, dim, n_chunks, chunks_sha256, vectors_sha256, status, generation)
                     VALUES (1, %s, 'r', %s, 0, 'x', 'y', 'ready', 7)""", (MODEL, DIM))
        c.execute("""INSERT INTO sync_runs (job, slot, trigger, status, started_at, to_commit, detail)
                     VALUES (%s, '2026-11-09', 'schedule', 'succeeded', now(), 'headcommit', %s)""",
                  (schedule.JOB, json.dumps({"modified": [PATH_INC], "added": []})))
        c.commit()
        yield c


SNAP = {(rule_seq(PATH_SNAP), VID_SNAP)}


def reader(raws=None, errors=None):
    raws = raws or {PATH_INC: RAW_INC}
    by_seq = {rule_seq(p): (p, r) for p, r in raws.items()}

    def read(rs, vid):
        if errors and rs in errors:
            raise R.SourceError(errors[rs], "시험")
        return by_seq[rs]
    return read


def table(c):
    return c.execute("SELECT chunk_id, version_id, ord, text, embedding::text, link_targets FROM chunks ORDER BY version_id, chunk_id").fetchall()


def generation(c):
    c.commit()
    return c.execute("SELECT generation FROM index_meta WHERE id = 1").fetchone()[0]


def go(c, embed=None, **kw):
    kw.setdefault("dry_run", False)
    return R.run(c, model=MODEL, dim=DIM, read=kw.pop("read", reader()), embed_fn=embed or Embed(), snap=SNAP,
                 snapshot_rows=SNAP_ROWS, today="2026-11-13", log=lambda *_: None, **kw)


@needs_db
def test_dry_run_reports_and_writes_nothing(conn):
    before, gen, emb = table(conn), generation(conn), Embed()
    rep = go(conn, emb, dry_run=True)
    assert rep["dry_run"] and rep["targets"] == 1 and rep["versions_to_replace"] == 1 and rep["pages_to_replace"] == 1
    assert rep["current_snapshot"] == 1 and rep["closed_incremental"] == 1 and rep["current_incremental"] == 1
    assert rep["rows"] == {"unchanged": 1, "changed": 1, "new": 1, "removed": 1}          # chunks[2] 같음, chunks[0] 바뀜, chunks[1] 새로, 가짜 id 사라짐
    assert rep["embeddings_needed"] == 2 and rep["estimate"]["est_tokens"] > 0
    assert emb.calls == []                                                                  # 임베딩을 부르지 않는다
    assert table(conn) == before and generation(conn) == gen                               # DB는 그대로
    lines = []
    R.print_report(rep, log=lines.append)
    text = "\n".join(lines)
    assert "dry-run" in text and "바꿀 판 1개" in text and "같음 1, 바뀜 1, 새로 1, 사라짐 1" in text and "임베딩 필요 2개" in text
    assert "test-model" not in text and "postgresql" not in text                           # 접속 정보는 출력에 없다
    with pytest.raises(Exception):                                                          # dry-run 연결은 쓰기를 못 한다
        conn.read_only = True
        try:
            conn.execute("UPDATE index_meta SET generation = 99")
        finally:
            conn.rollback()
            conn.read_only = False


@needs_db
def test_replaces_only_current_incremental_version_and_keeps_snapshot(conn):
    snap_rows = [r for r in table(conn) if r[1] == VID_SNAP]
    closed_rows = [r for r in table(conn) if r[1] in (VID_CLOSED_OLD, VID_CLOSED_NEW)]
    old_inc = {r[0]: r for r in table(conn) if r[1] == VID_INC}
    gen, emb = generation(conn), Embed()
    rep = go(conn, emb)
    assert rep["replaced"] == 1 and rep["failed"] == [] and rep["generation_bumped"] and generation(conn) == gen + 1
    after = table(conn)
    assert [r for r in after if r[1] == VID_SNAP] == snap_rows                              # 스냅샷 행은 한 칸도 안 바뀐다(ord 포함)
    assert [r for r in after if r[1] in (VID_CLOSED_OLD, VID_CLOSED_NEW)] == closed_rows    # 닫힌 증분 판도 그대로
    _, want = schedule.page_chunks(PATH_INC, RAW_INC, [VID_INC, "2026-11-05", False], "x")
    got = {r[0]: r for r in after if r[1] == VID_INC}
    assert sorted(got) == sorted(c["chunk_id"] for c in want) and "deadbeef00000000" not in got
    assert all(got[c["chunk_id"]][3] == c["text"] for c in want)                            # 글이 새 청크 코드 결과와 같다
    assert min(r[2] for r in got.values()) >= 10 + 3                                       # 새 ord는 기존 최대 뒤부터
    assert sorted(r[2] for r in got.values()) == list(range(min(r[2] for r in got.values()), min(r[2] for r in got.values()) + 3))
    # 벡터 재사용: 글이 같은 청크는 옛 벡터 그대로, 임베딩은 바뀐·새 글 2개만
    same = [c for c in want if c["chunk_id"] in old_inc and old_inc[c["chunk_id"]][3] == c["text"]]
    assert len(same) == 1 and got[same[0]["chunk_id"]][4] == old_inc[same[0]["chunk_id"]][4]
    assert sorted(t for call in emb.calls for t in call) == sorted(c["text"] for c in want if c is not same[0])
    assert len(emb.calls) == 1                                                              # 한 번에 묶어 임베딩


@needs_db
def test_second_run_changes_nothing_and_does_not_bump_generation(conn):
    go(conn)
    before, gen, emb = table(conn), generation(conn), Embed()
    rep = go(conn, emb)
    assert rep["versions_to_replace"] == 0 and rep["replaced"] == 0 and not rep["generation_bumped"]
    assert rep["rows"]["changed"] == rep["rows"]["new"] == rep["rows"]["removed"] == 0 and rep["rows"]["unchanged"] == 3
    assert emb.calls == [] and table(conn) == before and generation(conn) == gen


@needs_db
def test_version_replace_is_atomic_when_insert_fails_midway(conn, monkeypatch):
    before, gen = table(conn), generation(conn)
    calls = {"n": 0}
    real = links.targets

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("삽입 도중 실패")
        return real(*a, **k)
    monkeypatch.setattr(links, "targets", boom)
    rep = go(conn)
    assert rep["replaced"] == 0 and len(rep["failed"]) == 1 and "삽입 도중 실패" in rep["failed"][0]["error"]
    assert table(conn) == before                                                            # 지운 행도 되돌아와 옛 행이 그대로(섞이지 않음)
    assert not rep["generation_bumped"] and generation(conn) == gen                         # 바꾼 판이 없으면 generation 그대로


@needs_db
def test_generation_bumped_once_for_several_versions(conn):
    seed_page(conn, "content/handbook/security/inc2-page.md", RAW.format(t="Inc2"), "inc200000000", "2026-11-06")
    _, ch = schedule.page_chunks("content/handbook/security/inc2-page.md", RAW.format(t="Inc2"), ["inc200000000", "2026-11-06", False], "x")
    insert_rows(conn, "inc200000000", old_chunker_rows(ch), 40)
    conn.commit()
    gen = generation(conn)
    raws = {PATH_INC: RAW_INC, "content/handbook/security/inc2-page.md": RAW.format(t="Inc2")}
    conn.execute("UPDATE sync_runs SET detail = %s", (json.dumps({"modified": list(raws)}),))
    conn.commit()
    rep = go(conn, read=reader(raws))
    assert rep["replaced"] == 2 and generation(conn) == gen + 1


@needs_db
def test_refuses_when_index_not_ready_or_sync_running(conn):
    conn.execute("UPDATE index_meta SET status = 'loading'")
    conn.commit()
    with pytest.raises(R.Refused):
        go(conn)
    conn.execute("UPDATE index_meta SET status = 'ready'")
    conn.execute("""INSERT INTO sync_runs (job, slot, trigger, status, started_at) VALUES (%s, 'manual-1', 'manual', 'running', now())""",
                 (schedule.JOB,))
    conn.commit()
    with pytest.raises(R.Refused):
        go(conn)
    assert go(conn, ignore_running=True)["replaced"] == 1
    conn.execute("UPDATE index_meta SET embedder = 'other-model'")
    conn.commit()
    with pytest.raises(R.Refused):                                                          # 임베딩 모델이 다르면 거부
        go(conn)


@needs_db
def test_cost_cap_stops_before_embedding_and_writes(conn):
    before, emb = table(conn), Embed()
    with pytest.raises(R.CostCap):
        go(conn, emb, max_cost=0.0)
    assert emb.calls == [] and table(conn) == before


@needs_db
def test_version_closed_during_run_is_left_alone(conn):
    """계획 뒤(임베딩 중) 증분 수집이 이 판을 닫았다 → 그 판은 건드리지 않고 stale로 센다. 바꾼 판이 없으니 generation도 그대로."""
    import psycopg

    def close_it():
        with psycopg.connect(DB) as other:
            other.execute("UPDATE versions SET valid_to = '2026-11-12' WHERE version_id = %s", (VID_INC,))
    before_rows = [r for r in table(conn) if r[1] == VID_INC]
    gen = generation(conn)
    rep = go(conn, Embed(hook=close_it))
    assert rep["replaced"] == 0 and len(rep["stale"]) == 1 and not rep["generation_bumped"]
    assert [r for r in table(conn) if r[1] == VID_INC] == before_rows and generation(conn) == gen


@needs_db
def test_ord_anomaly_and_source_errors_are_skipped_not_changed(conn):
    # 증분 판인데 스냅샷 번호대 행이 있는 판은 건드리지 않는다
    conn.execute("UPDATE chunks SET ord = 4 WHERE version_id = %s AND seq = 99", (VID_INC,))
    conn.commit()
    before = table(conn)
    rep = go(conn)
    assert rep["ord_anomaly"] == 1 and rep["targets"] == 0 and rep["replaced"] == 0 and table(conn) == before
    conn.execute("UPDATE chunks SET ord = 12 WHERE version_id = %s AND seq = 99", (VID_INC,))
    conn.commit()
    rep = go(conn, read=reader(errors={rule_seq(PATH_INC): "version_mismatch"}))
    assert rep["skipped"] == 1 and rep["skipped_by_kind"] == {"version_mismatch": 1} and rep["replaced"] == 0


@needs_db
def test_load_origins_uses_latest_succeeded_run(conn):
    conn.execute("""INSERT INTO sync_runs (job, slot, trigger, status, started_at, to_commit, detail)
                    VALUES (%s, '2026-11-10', 'schedule', 'succeeded', now(), 'later', %s)""",
                 (schedule.JOB, json.dumps({"format_only": [PATH_INC]})))
    conn.execute("""INSERT INTO sync_runs (job, slot, trigger, status, started_at, to_commit, detail)
                    VALUES (%s, '2026-11-11', 'schedule', 'failed', now(), 'bad', %s)""", (schedule.JOB, json.dumps({"modified": [PATH_INC]})))
    conn.commit()
    assert R.load_origins(conn)[rule_seq(PATH_INC)] == (PATH_INC, "later")
