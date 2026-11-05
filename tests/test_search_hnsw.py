"""PgStore의 HNSW 질의(SEARCH_HNSW=1, 대상 모델만). 꺼져 있으면 지금과 같고, 읽기의 autocommit 변경과 트랜잭션 안 색인 설정이 서로 깨지지 않는지 본다.

DB 시험은 TEST_DATABASE_URL이 있을 때만 돈다(로컬 pgvector). 표를 지우고 다시 만드므로 시험 전용 DB에서만 돌린다.
"""
from __future__ import annotations

import contextlib
import os

import numpy as np
import pytest

from backend.rag.retrieve.search import _FILTER, _JOIN, HNSW_EF_SEARCH, HNSW_ITERATIVE, PgStore

DB = os.environ.get("TEST_DATABASE_URL")
MODEL, DIM, N_ROWS = "voyage-4", 1024, 300
# 최적화 전 전수 질의. 꺼진 상태의 결과가 이 기준과 비트 단위로 같아야 한다.
OLD_TOP = f"""SELECT c.chunk_id, c.version_id, -(c.embedding <#> %(q)s::vector) AS score {_JOIN}
WHERE c.embedder = %(embedder)s AND {_FILTER}
ORDER BY c.embedding <#> %(q)s::vector, c.chunk_id LIMIT %(n)s"""
INDEX = f"""CREATE INDEX chunks_emb_hnsw_half ON chunks USING hnsw ((embedding::halfvec({DIM})) halfvec_ip_ops)
WITH (m = 16, ef_construction = 128) WHERE embedder = '{MODEL}'"""


class _Rows:
    def fetchall(self):
        return [("a", "v", 0.5)]


class _RecordConn:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def execute(self, sql, params=None):
        self.sent.append((sql, params))
        return _Rows()


def _fake_store(hnsw):
    conn, reads = _RecordConn(), []

    class Pool:
        @contextlib.contextmanager
        def connection(self):
            yield conn

    def read(sql, params=None):
        reads.append(sql)
        return [("a", "v", 0.5)]

    st = PgStore.__new__(PgStore)
    st.pool, st._all, st.hnsw = Pool(), read, hnsw
    return st, conn, reads


Q = np.zeros(3, dtype=np.float32)


def test_off_by_default_even_for_the_listed_model():
    st = PgStore.__new__(PgStore)                                    # __init__을 거치지 않아도 꺼짐
    assert st.hnsw is False
    st, conn, reads = _fake_store(False)
    assert st.vector_top(Q, MODEL, None, None, 5) == [(("a", "v"), 0.5)]
    assert conn.sent == [] and len(reads) == 1 and "halfvec" not in reads[0] and reads[0].count("<#>") == 1


def test_on_but_model_not_listed_stays_on_the_exact_query():
    st, conn, reads = _fake_store(True)
    st.vector_top(Q, "kure-v1", None, None, 5)
    assert conn.sent == [] and len(reads) == 1 and "halfvec" not in reads[0]


def test_on_with_listed_model_sets_index_options_in_one_transaction_and_computes_distance_once():
    st, conn, reads = _fake_store(True)
    assert st.vector_top(Q, MODEL, None, None, 5) == [(("a", "v"), 0.5)]
    assert reads == []                                                # autocommit으로 바꾸는 `_all`을 타지 않는다
    (setting, opts), (sql, params) = conn.sent
    assert "'hnsw.ef_search'" in setting and "'hnsw.iterative_scan'" in setting and setting.count(", true)") == 2
    assert opts == {"ef": str(HNSW_EF_SEARCH), "it": HNSW_ITERATIVE} and opts == {"ef": "200", "it": "strict_order"}
    assert sql.count("<#>") == 1 and f"c.embedding::halfvec({DIM}) <#> %(q)s::halfvec({DIM})" in sql    # 색인 식과 같다
    assert "ORDER BY dist LIMIT %(n)s" in sql and sql.rstrip().endswith("ORDER BY dist, chunk_id")
    assert params["embedder"] == MODEL and params["n"] == 5


def test_page_query_never_uses_the_index_form():
    st, conn, reads = _fake_store(True)
    st.page_vector_top(Q, MODEL, [1], None, None, [], 2)
    assert conn.sent == [] and len(reads) == 1 and "halfvec" not in reads[0]


@pytest.mark.parametrize("env,want", [(None, False), ("0", False), ("", False), ("true", False), ("1", True)])
def test_env_switch(monkeypatch, env, want):
    monkeypatch.setattr("psycopg_pool.ConnectionPool", lambda *a, **k: object())
    if env is None:
        monkeypatch.delenv("SEARCH_HNSW", raising=False)
    else:
        monkeypatch.setenv("SEARCH_HNSW", env)
    assert PgStore("postgresql://u:p@127.0.0.1:1/x").hnsw is want


# ---------- DB (로컬 pgvector, TEST_DATABASE_URL이 있을 때만) ----------

need_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
CASES = [(None, None), ("x", None), ("y", None), ("nope", None), (None, "2024-06-01")]


def _unit(rng):
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _one_conn_pool():
    """연결 하나짜리 풀. autocommit을 바꾼 연결과 색인 설정을 준 연결이 반드시 같게 만든다."""
    from pgvector.psycopg import register_vector
    from psycopg_pool import ConnectionPool
    return ConnectionPool(DB, min_size=1, max_size=1, open=True, kwargs={"prepare_threshold": None}, configure=register_vector)


@pytest.fixture(scope="module")
def hnsw_db():
    """voyage-4 1024차원 300행(좁은 부서 y는 10행, 같은 벡터 묶음 포함)과 다른 모델의 8차원 행. 측정 때의 색인과 같은 문장으로 색인을 만든다."""
    import psycopg
    from pgvector.psycopg import register_vector

    from backend.rag.retrieve import load_snapshot
    rng = np.random.default_rng(11)
    same = _unit(rng)
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS changed_articles, sync_runs, chunks, versions, docs, index_meta, query_translations CASCADE")
        conn.execute(load_snapshot.SQL.read_text(encoding="utf-8"))
        conn.commit()
        register_vector(conn)
        conn.execute("INSERT INTO docs VALUES (1,'x','t','md','u','2025-01-01'), (2,'y','t','md','u','2025-01-01')")
        conn.execute("""INSERT INTO versions (rule_seq, version_id, version_date, valid_from, valid_to) VALUES
            (1,'old','2024-01-01','2024-01-01','2025-01-01'), (1,'cur','2025-01-01','2025-01-01',NULL), (2,'cur','2025-01-01','2025-01-01',NULL)""")
        rows = [(f"same{i}", "cur", 1, i, same) for i in (3, 1, 2)]
        rows += [(f"y{i:02d}", "cur", 2, 10 + i, _unit(rng)) for i in range(10)]
        rows += [(f"o{i:02d}", "old", 1, 50 + i, _unit(rng)) for i in range(20)]
        rows += [(f"r{i:03d}", "cur", 1, 100 + i, _unit(rng)) for i in range(N_ROWS - 33)]
        for cid, ver, seq, s, v in rows:
            conn.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, kind, text, source_url, embedding, embedder)
                            VALUES (%s,%s,%s,%s,%s,'article',%s,'u',%s,%s)""", (cid, ver, seq, s, s, f"text {cid}", v, MODEL))
        small = np.ones(8, dtype=np.float32)
        conn.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, kind, text, source_url, embedding, embedder)
                        VALUES ('small','cur',1,999,999,'article','t','u',%s,'other-model')""", (small,))
        conn.commit()
    st = PgStore(DB)
    queries = [same, -same] + [_unit(rng) for _ in range(6)]
    st.hnsw = True
    without_index = [(st.vector_top(q, MODEL, org, as_of, 5), org, as_of, q) for q in queries for org, as_of in CASES]
    st.hnsw = False
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute(INDEX)
        conn.execute("ANALYZE chunks")
        conn.commit()
    yield st, queries, without_index
    st.pool.close()


def _ids(rows):
    return [k[0] for k, _ in rows]


@need_db
def test_off_equals_the_old_exact_query_bit_for_bit(hnsw_db):
    st, queries, _ = hnsw_db
    assert st.hnsw is False
    for q in queries:
        for org, as_of in CASES:
            for n in (1, 2, 5, 400):
                old = st._all(OLD_TOP, {"q": q, "embedder": MODEL, "org": org, "as_of": as_of, "n": n})
                new = st.vector_top(q, MODEL, org, as_of, n)
                assert [(a, b, float(c).hex()) for a, b, c in old] == [(k[0], k[1], c.hex()) for k, c in new], (org, as_of, n)


@need_db
def test_without_the_index_the_on_query_gives_the_exact_top(hnsw_db):
    """색인을 만들기 전에 잰 값. 켜 두고 색인이 없어도 결과는 전수와 같다."""
    st, _, without_index = hnsw_db
    for rows, org, as_of, q in without_index:
        exact = st.vector_top(q, MODEL, org, as_of, 5)
        assert _ids(rows) == _ids(exact), (org, as_of)
        assert all(abs(a[1] - b[1]) < 5e-3 for a, b in zip(rows, exact))           # 점수는 반정밀도 거리라 조금 다르다


@need_db
def test_on_query_plan_uses_the_index_and_recomputes_nothing(hnsw_db):
    st, queries, _ = hnsw_db
    fake, conn, _ = _fake_store(True)
    fake.vector_top(queries[0], MODEL, None, None, 5)
    sql, params = conn.sent[1]
    with st.pool.connection() as real:
        real.execute("SET LOCAL enable_seqscan = off"); real.execute("SET LOCAL enable_sort = off")  # 300행은 작아 그냥 두면 정렬을 고른다
        text = "\n".join(r[0] for r in real.execute("EXPLAIN (COSTS OFF) " + sql, params).fetchall())
        real.rollback()
    assert "Index Scan using chunks_emb_hnsw_half" in text, text
    assert text.count("Sort Key") == 1 and "Sort Key: s.dist, s.chunk_id" in text, text      # 정렬은 바깥 동점 깨기 한 번뿐, 거리 순서는 색인이 준다


@need_db
def test_index_answers_match_exact_and_narrow_filter_does_not_shrink():
    """seq scan과 정렬을 끈 연결로 색인을 강제한다. 좁은 부서(10행)에서도 5개가 나와야 한다(반복 스캔)."""
    import psycopg
    forced = PgStore(psycopg.conninfo.make_conninfo(DB, options="-c enable_seqscan=off -c enable_sort=off"))
    exact = PgStore(DB)
    forced.hnsw = True
    try:
        qs = [np.asarray(r[0].to_list() if hasattr(r[0], "to_list") else r[0], dtype=np.float32)
              for r in exact._all("SELECT embedding FROM chunks WHERE embedder = %(m)s AND chunk_id LIKE 'r00%%' ORDER BY chunk_id", {"m": MODEL})]
        assert qs
        for q in qs[:6]:
            for org, as_of in CASES:
                got, want = forced.vector_top(q, MODEL, org, as_of, 5), exact.vector_top(q, MODEL, org, as_of, 5)
                assert len(got) == len(want), (org, as_of)
                assert len(set(_ids(got)) & set(_ids(want))) >= max(0, len(want) - 1), (org, as_of)   # 근사라 한 자리까지만 허용
    finally:
        forced.pool.close()
        exact.pool.close()


@need_db
def test_ties_on_the_index_query_are_ordered_by_chunk_id(hnsw_db):
    st, queries, _ = hnsw_db
    st.hnsw = True
    try:
        rows = st.vector_top(queries[0], MODEL, "x", None, 3)                       # same1, same2, same3은 같은 벡터
    finally:
        st.hnsw = False
    assert _ids(rows) == ["same1", "same2", "same3"] and rows[0][1] == rows[1][1] == rows[2][1]


class _SpyPool:
    """색인 설정 직후 같은 연결에서 설정값과 트랜잭션 상태를 읽어 둔다."""

    def __init__(self, pool):
        self.pool, self.seen = pool, []

    @contextlib.contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            yield _SpyConn(conn, self.seen)


class _SpyConn:
    def __init__(self, conn, seen):
        self.conn, self.seen = conn, seen

    def execute(self, sql, params=None):
        out = self.conn.execute(sql, params)
        if "set_config" in sql:
            row = self.conn.execute("SELECT current_setting('hnsw.ef_search', true), current_setting('hnsw.iterative_scan', true)").fetchone()
            self.seen.append((row[0], row[1], self.conn.autocommit, self.conn.info.transaction_status.name))
        return out

    def __getattr__(self, name):
        return getattr(self.conn, name)


def _settings(st):
    return tuple(st._all("SELECT current_setting('hnsw.ef_search', true), current_setting('hnsw.iterative_scan', true)")[0])


def _assert_cleared(st):
    ef, it = _settings(st)
    assert ef != str(HNSW_EF_SEARCH) and it != HNSW_ITERATIVE, (ef, it)              # 다음 질의로 설정이 새지 않는다


@pytest.fixture
def one_conn(hnsw_db):
    """연결 하나짜리 풀 위의 저장소. `_all`이 autocommit을 바꾼 바로 그 연결에서 색인 질의가 돈다."""
    st = PgStore.__new__(PgStore)
    real = _one_conn_pool()
    st.pool, st.hnsw = _SpyPool(real), True
    yield st, hnsw_db[1][0]
    real.close()


@need_db
def test_autocommit_reads_and_transaction_settings_do_not_break_each_other(one_conn):
    st, q = one_conn
    for _ in range(3):
        assert st._all("SELECT 1") == [(1,)]                                         # autocommit으로 읽고 되돌린다
        assert len(st.vector_top(q, MODEL, None, None, 5)) == 5                      # 같은 연결에서 트랜잭션 안 설정
        _assert_cleared(st)
    # 설정은 트랜잭션 안에서 실제로 보였다. autocommit이 남아 있었다면 문장이 끝날 때 사라져 여기서 드러난다
    assert st.pool.seen == [(str(HNSW_EF_SEARCH), HNSW_ITERATIVE, False, "INTRANS")] * 3
    with st.pool.connection() as conn:
        assert conn.autocommit is False


@need_db
def test_failed_read_does_not_break_the_next_index_query(one_conn):
    import psycopg
    st, q = one_conn
    with pytest.raises(psycopg.errors.UndefinedTable):
        st._all("SELECT * FROM no_such_table")
    assert len(st.vector_top(q, MODEL, None, None, 5)) == 5
    assert st.pool.seen[-1] == (str(HNSW_EF_SEARCH), HNSW_ITERATIVE, False, "INTRANS")
    _assert_cleared(st)


@need_db
def test_failed_index_query_rolls_back_settings_and_the_next_read_works(one_conn):
    import psycopg
    st, q = one_conn
    with pytest.raises(psycopg.Error):
        st.vector_top(np.zeros(8, dtype=np.float32), MODEL, None, None, 5)           # 차원이 달라 halfvec(1024) 식이 오류
    assert st.pool.seen[-1][:2] == (str(HNSW_EF_SEARCH), HNSW_ITERATIVE)             # 설정까지는 갔다가 실패했다
    assert st._all("SELECT 1") == [(1,)]
    _assert_cleared(st)
    assert len(st.vector_top(q, MODEL, None, None, 5)) == 5


@need_db
def test_lost_connection_during_read_then_index_query_recovers(one_conn):
    import psycopg
    st, q = one_conn
    with pytest.raises(psycopg.OperationalError):
        st._all("SELECT pg_terminate_backend(pg_backend_pid())")
    assert len(st.vector_top(q, MODEL, None, None, 5)) == 5
    assert st.pool.seen[-1] == (str(HNSW_EF_SEARCH), HNSW_ITERATIVE, False, "INTRANS")


@need_db
def test_other_model_rows_are_not_cast_by_the_index_query(hnsw_db):
    """표에 다른 차원의 행이 있어도(다른 모델) 대상 모델 질의가 깨지지 않는다."""
    st, queries, _ = hnsw_db
    assert st._all("SELECT count(*) FROM chunks WHERE embedder = 'other-model'") == [(1,)]
    st.hnsw = True
    try:
        assert "small" not in _ids(st.vector_top(queries[0], MODEL, None, None, N_ROWS))
    finally:
        st.hnsw = False
