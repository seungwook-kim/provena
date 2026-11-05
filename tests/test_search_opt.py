"""검색 최적화가 결과를 바꾸지 않는지. PgStore의 거리 계산을 한 번으로 줄인 질의, 읽기 왕복, BM25 없는 방식의 기동 읽기를 본다.

DB 시험은 TEST_DATABASE_URL이 있을 때만 돈다(로컬 pgvector). 표를 지우고 다시 만드므로 시험 전용 DB에서만 돌린다.
옛 질의(OLD_*)는 최적화 전 문장을 그대로 둔 기준이다. 정렬, 동점, 점수가 이 기준과 정확히 같아야 한다.
"""
from __future__ import annotations

import contextlib
import os
import sys

import numpy as np
import pytest

from backend.rag.retrieve import translate
from backend.rag.retrieve.search import _FILTER, _JOIN, MemoryStore, PgStore, SearchConfig, Searcher
from backend.schemas.chunk import SearchQuery

DB = os.environ.get("TEST_DATABASE_URL")
OLD_TOP = f"""SELECT c.chunk_id, c.version_id, -(c.embedding <#> %(q)s::vector) AS score {_JOIN}
WHERE c.embedder = %(embedder)s AND {_FILTER}
ORDER BY c.embedding <#> %(q)s::vector, c.chunk_id LIMIT %(n)s"""
OLD_PAGE = f"""SELECT c.chunk_id, c.version_id, -(c.embedding <#> %(q)s::vector) AS score {_JOIN}
WHERE c.embedder = %(embedder)s AND c.rule_seq = ANY(%(seqs)s::bigint[]) AND {_FILTER}
  AND NOT EXISTS (SELECT 1 FROM unnest(%(ex_i)s::text[], %(ex_v)s::text[]) AS x(chunk_id, version_id)
                  WHERE x.chunk_id = c.chunk_id AND x.version_id = c.version_id)
ORDER BY c.embedding <#> %(q)s::vector, c.chunk_id LIMIT %(n)s"""


class _Capture:
    """DB 없이 PgStore가 보내는 문장만 받는다."""

    def __init__(self):
        self.sql: list[str] = []

    def __call__(self, sql, params=None):
        self.sql.append(sql)
        return []


def _no_db_store():
    st = PgStore.__new__(PgStore)
    st._all = _Capture()
    return st


def test_vector_queries_compute_distance_once():
    st = _no_db_store()
    q = np.zeros(3, dtype=np.float32)
    st.vector_top(q, "m", None, None, 5)
    st.page_vector_top(q, "m", [1], None, None, [], 2)
    assert len(st._all.sql) == 2
    for sql in st._all.sql:
        assert sql.count("<#>") == 1, sql
        assert sql.rstrip().endswith("ORDER BY dist, chunk_id"), sql      # 바깥 순서를 DB에 맡기지 않고 적어 둔다
        assert "ORDER BY dist, c.chunk_id LIMIT %(n)s" in sql, sql


def test_page_query_without_pages_does_not_touch_db():
    st = _no_db_store()
    assert st.page_vector_top(np.zeros(3, dtype=np.float32), "m", [], None, None, [], 2) == []
    assert st._all.sql == []


def test_row_meta_reads_text_only_when_asked():
    st = _no_db_store()
    assert st.row_meta(with_text=False).texts == []
    st.row_meta()
    lean, full = st._all.sql
    assert "c.text" not in lean and "c.text" in full


class _FakeConn:
    def __init__(self, fail=False):
        self.autocommit, self.fail, self.seen = False, fail, []

    def set_autocommit(self, value):
        self.autocommit = value

    def execute(self, sql, params):
        self.seen.append(self.autocommit)
        if self.fail:
            raise RuntimeError("읽기 실패")
        return self

    def fetchall(self):
        return [(1,)]


def _store_with(conn):
    class Pool:
        @contextlib.contextmanager
        def connection(self):
            yield conn
    st = PgStore.__new__(PgStore)
    st.pool = Pool()
    return st


def test_read_runs_in_autocommit_and_restores_the_pool_default():
    conn = _FakeConn()
    assert _store_with(conn)._all("SELECT 1") == [(1,)]
    assert conn.seen == [True] and conn.autocommit is False


def test_failed_read_also_restores_the_pool_default():
    conn = _FakeConn(fail=True)
    with pytest.raises(RuntimeError):
        _store_with(conn)._all("SELECT 1")
    assert conn.seen == [True] and conn.autocommit is False


class _PgLike:
    """isinstance(store, PgStore)를 참으로 만들고 row_meta 호출만 기록한다. 나머지는 MemoryStore와 같다."""

    def __init__(self, base: MemoryStore):
        self.base, self.calls = base, []

    def row_meta(self, with_text=True):
        self.calls.append(with_text)
        rm = self.base.row_meta()
        return type(rm)(rm.keys, rm.org, rm.valid_from, rm.valid_to, rm.texts if with_text else [])

    def __getattr__(self, name):
        return getattr(self.base, name)


ROWS = [{"chunk_id": c, "version_id": "v", "org": o, "rule_seq": 1, "rule_title": "t", "article": None, "version_date": "2025-01-01",
         "fetched_at": "2025-01-01", "kind": "article", "text": t, "source_url": "u", "text_sha256": None, "version_date_before": False,
         "line_start": 1, "line_end": 2, "valid_from": "2025-01-01", "valid_to": None, "link_targets": []}
        for c, o, t in [("a", "x", "alpha beta"), ("b", "x", "beta gamma"), ("c", "y", "gamma delta")]]
VECS = np.asarray([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)


def _embed(texts):
    return np.tile(VECS[0], (len(texts), 1))


def _stored(q, kind):
    return translate.Result("alpha", "stored")


def _lean_searcher(monkeypatch, mode):
    S = sys.modules["backend.rag.retrieve.search"]
    store = _PgLike(MemoryStore(ROWS, VECS, "m"))
    monkeypatch.setattr(S, "PgStore", _PgLike)
    return store, Searcher(SearchConfig(embed_model="m", mode=mode, rerank_model="none"), store, embedder=_embed, reranker=None,
                           translator=_stored, check_meta=False)


@pytest.mark.parametrize("mode", ["dense_en", "dense_ko"])
def test_vector_only_modes_skip_text_and_results_match_memory(monkeypatch, mode):
    store, lean = _lean_searcher(monkeypatch, mode)
    assert store.calls == [False] and lean._bm25 is None and lean._rm.texts == []
    full = Searcher(SearchConfig(embed_model="m", mode=mode, rerank_model="none"), MemoryStore(ROWS, VECS, "m"), embedder=_embed,
                    reranker=None, translator=_stored, check_meta=False)
    assert full._bm25 is not None                                     # 비교 입구(MemoryStore)는 그대로 만든다
    for q in (SearchQuery(query="alpha", k=2), SearchQuery(query="alpha", k=2, org="y"), SearchQuery(query="alpha", k=2, as_of="2024-01-01")):
        assert [c.chunk_id for c in lean.search(q)] == [c.chunk_id for c in full.search(q)]


def test_dense_fallback_from_failed_translation_needs_no_bm25(monkeypatch):
    """번역이 실패해 dense_ko로 내려가도 BM25를 부르지 않는다(본문을 읽지 않은 기동에서 멈추지 않는다)."""
    store, s = _lean_searcher(monkeypatch, "dense_en")
    s.translator = lambda q, kind: translate.Result(None, "timeout")
    assert [c.chunk_id for c in s.search(SearchQuery(query="한국어 질문", k=2))] == ["a", "b"]


@pytest.mark.parametrize("mode", ["hybrid_ko_kw", "bm25_kw"])
def test_bm25_modes_still_read_text(monkeypatch, mode):
    store, s = _lean_searcher(monkeypatch, mode)
    assert store.calls == [True] and s._bm25 is not None and s._rm.texts


# ---------- DB (로컬 pgvector, TEST_DATABASE_URL이 있을 때만) ----------

need_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
DIM = 8


def _unit(rng):
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture(scope="module")
def tie_db():
    """동점이 많은 표: 같은 벡터 묶음(LIMIT 경계에 걸침), 대소문자 chunk_id, 옛 판과 현재 판, 부서 둘, 다른 모델 행."""
    import psycopg
    from pgvector.psycopg import register_vector

    from backend.rag.retrieve import load_snapshot
    rng = np.random.default_rng(7)
    same, other = _unit(rng), _unit(rng)
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS chunks, versions, docs, index_meta, query_translations CASCADE")
        conn.execute(load_snapshot.SQL.read_text(encoding="utf-8"))
        conn.commit()
        register_vector(conn)
        conn.execute("INSERT INTO docs VALUES (1,'x','t','md','u','2025-01-01'), (2,'y','t','md','u','2025-01-01'), (3,'x','t','md','u','2025-01-01')")
        conn.execute("""INSERT INTO versions (rule_seq, version_id, version_date, valid_from, valid_to) VALUES
            (1,'old','2024-01-01','2024-01-01','2025-01-01'), (1,'cur','2025-01-01','2025-01-01',NULL),
            (2,'cur','2025-01-01','2025-01-01',NULL), (3,'cur','2025-06-01','2025-06-01',NULL)""")
        rows = [(cid, "cur", 1 + i % 3, i, same) for i, cid in enumerate(["t3", "T1", "t2", "a-9", "Z0", "t10", "t1"])]   # 전부 같은 벡터(동점)
        rows += [(cid, "old", 1, 100 + i, same if i < 2 else other) for i, cid in enumerate(["t3", "t1", "o5", "o2"])]      # 옛 판: 같은 chunk_id도 있다
        rows += [(f"r{i:02d}", "cur", 1 + i % 3, 200 + i, _unit(rng)) for i in range(60)]
        rows += [("other-model", "cur", 1, 999, same)]
        for cid, ver, seq, s, v in rows:
            conn.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, kind, text, source_url, embedding, embedder)
                            VALUES (%s,%s,%s,%s,%s,'article',%s,'u',%s,%s)""",
                         (cid, ver, seq, s, s, f"text {cid}", v, "n" if cid == "other-model" else "m"))
        conn.commit()
    st = PgStore(DB)
    yield st, same, other, rng
    st.pool.close()


CASES = [(None, None), ("x", None), ("y", None), ("nope", None), (None, "2024-06-01"), ("x", "2024-06-01"), (None, "2025-03-01"), (None, "2020-01-01")]


def _bits(rows):
    return [(a, b, float(c).hex()) for a, b, c in rows]


def _bits_new(rows):
    return [(k[0], k[1], c.hex()) for k, c in rows]


@need_db
def test_vector_top_equals_old_sql_with_ties(tie_db):
    st, same, other, rng = tie_db
    ties = 0
    for q in [same, -same, other, np.zeros(DIM, dtype=np.float32), same * 3] + [_unit(rng) for _ in range(5)]:
        for org, as_of in CASES:
            for n in (1, 2, 3, 5, 7, 8, 100):
                old = st._all(OLD_TOP, {"q": q, "embedder": "m", "org": org, "as_of": as_of, "n": n})
                new = st.vector_top(q, "m", org, as_of, n)
                assert _bits(old) == _bits_new(new), (org, as_of, n)          # 순서와 점수가 비트 단위로 같다
                ties += sum(a[1] == b[1] for a, b in zip(new, new[1:]))
    assert ties > 0                                                           # 동점이 실제로 있었다(빈 시험이 아님)


@need_db
def test_page_vector_top_equals_old_sql_with_ties_and_exclude(tie_db):
    st, same, other, rng = tie_db
    excludes = [[], [("t1", "cur")], [("t1", "cur"), ("T1", "cur"), ("t1", "old"), ("zzz", "cur")]]
    seen = 0
    for q in [same, -same, other, _unit(rng)]:
        for seqs in ([1], [1, 3], [2, 3], [99]):
            for org, as_of in CASES:
                for ex in excludes:
                    for n in (1, 2, 5, 100):
                        old = st._all(OLD_PAGE, {"q": q, "embedder": "m", "seqs": seqs, "org": org, "as_of": as_of,
                                                 "ex_i": [k[0] for k in ex], "ex_v": [k[1] for k in ex], "n": n})
                        new = st.page_vector_top(q, "m", seqs, org, as_of, ex, n)
                        assert _bits(old) == _bits_new(new), (seqs, org, as_of, ex, n)
                        seen += len(new)
    assert seen > 0


@need_db
def test_plan_keeps_subquery_and_sorts_once(tie_db):
    """서브쿼리가 펼쳐지면 바깥 출력에 거리 식이 다시 나타나 절약이 사라진다. 계획으로 본다."""
    st, same, _, _ = tie_db
    real_all, sent = st._all, []
    st._all = lambda s, p=None: (sent.append((s, p)), [])[1]
    try:
        st.vector_top(same, "m", None, None, 5)
    finally:
        st._all = real_all
    text = "\n".join(r[0] for r in real_all("EXPLAIN (VERBOSE, COSTS OFF) " + sent[0][0], sent[0][1]))
    assert text.startswith("Subquery Scan on s") and "(- s.dist)" in text, text
    assert text.count("Sort Key") == 1, text                                  # 바깥에서 다시 정렬하지 않는다


@need_db
def test_pool_default_stays_transactional_after_reads(tie_db):
    st, _, _, _ = tie_db
    st.generation()
    with st.pool.connection() as conn:
        assert conn.autocommit is False
        conn.execute("SELECT 1")
        assert conn.info.transaction_status.name == "INTRANS"                 # 묶어서 쓰는 쪽(with pool.connection)은 예전처럼 트랜잭션이다


@need_db
def test_write_still_commits_and_a_failed_read_leaves_pool_usable(tie_db):
    import psycopg
    st, _, _, _ = tie_db
    st.put_translation("s" * 64, "m", "sentence", "hello there")
    assert st.get_translation("s" * 64, "m")["sentence"] == "hello there"
    with psycopg.connect(DB, prepare_threshold=None) as other:                # 다른 연결에서 보인다 = 커밋됐다
        assert other.execute("SELECT sentence FROM query_translations WHERE query_sha256 = %s", ("s" * 64,)).fetchone()[0] == "hello there"
    with pytest.raises(psycopg.errors.UndefinedTable):
        st._all("SELECT * FROM no_such_table")
    assert st._all("SELECT 1") == [(1,)]
    with st.pool.connection() as conn:
        assert conn.autocommit is False


@need_db
def test_lost_connection_raises_same_error_and_pool_recovers(tie_db):
    """읽는 중 서버 쪽 연결이 끊기면 OperationalError이고, 풀은 새 연결로 이어 간다."""
    import psycopg
    st, _, _, _ = tie_db
    with pytest.raises(psycopg.OperationalError):
        st._all("SELECT pg_terminate_backend(pg_backend_pid())")
    for _ in range(3):
        assert st._all("SELECT 1") == [(1,)]


@need_db
def test_row_meta_without_text_matches_full_mask(tie_db):
    st, _, _, _ = tie_db
    a, b = st.row_meta(), st.row_meta(with_text=False)
    assert a.keys == b.keys and b.texts == [] and len(a.texts) == len(a.keys)
    assert (a.org == b.org).all() and (a.valid_from == b.valid_from).all()
    assert (np.isnat(a.valid_to) == np.isnat(b.valid_to)).all()


@need_db
def test_searcher_on_pg_dense_mode_same_as_full_row_meta(tie_db, monkeypatch):
    """dense_en 서비스 경로: 본문 없는 기동과 본문을 읽은 기동이 같은 청크와 같은 n_filtered를 돌려준다."""
    S = sys.modules["backend.rag.retrieve.search"]
    st, same, _, _ = tie_db
    emb = lambda texts: np.tile(same, (len(texts), 1))  # noqa: E731
    tr = lambda q, kind: translate.Result(q, "stored")  # noqa: E731
    cfg = SearchConfig(embed_model="m", mode="dense_en", rerank_model="none")
    lean = Searcher(cfg, st, embedder=emb, reranker=None, translator=tr, check_meta=False)
    assert lean._bm25 is None and lean._rm.texts == []
    with monkeypatch.context() as m:
        m.setattr(S, "PgStore", type("NotPg", (), {}))
        full = Searcher(cfg, st, embedder=emb, reranker=None, translator=tr, check_meta=False)
    assert full._bm25 is not None
    for q in (SearchQuery(query="q one"), SearchQuery(query="q one", org="x"), SearchQuery(query="q one", as_of="2024-06-01"),
              SearchQuery(query="q one", sub_queries=["s one", "s two"]), SearchQuery(query="q one", org="nope")):
        a = lean.search(q)
        na = S.last_search_trace().n_filtered
        b = full.search(q)
        assert [c.model_dump() for c in a] == [c.model_dump() for c in b] and na == S.last_search_trace().n_filtered
