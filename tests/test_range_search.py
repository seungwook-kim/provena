"""금액 구간 조회 시험(사전 등록 62.7): 질문의 달러 금액 읽기, 구간 제목 읽기, 금액이 속한 구간 행 고르기(backend/rag/retrieve/ranges.py),
검색에 붙인 `Searcher._range_expand`(MemoryStore)와 `PgStore`의 두 질의(TEST_DATABASE_URL이 있을 때만).
모델·네트워크 없이 손으로 정한 벡터로 돈다. 측정은 evals/retrieval/range_context.py."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from backend.rag.retrieve import ranges, translate
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, SearchTrace, last_search_trace
from backend.schemas.chunk import SearchQuery


# ---------- 금액 읽기 ----------

@pytest.mark.parametrize("text,want", [
    ("$30,000", [30000]), ("$30K", [30000]), ("$30k", [30000]), ("$1.5M", [1500000]), ("$50 million", [50000000]),
    ("30,000 dollars", [30000]), ("USD 30K", [30000]), ("30K USD", [30000]), ("a $100,000 contract and $25K", [100000, 25000]),
    ("3만 달러", [30000]), ("3만 5천 달러", [35000]), ("10만 달러", [100000]), ("5천 달러", [5000]), ("50,000달러", [50000]),
    ("2천만 달러", [20000000]), ("1억 2천만 달러", [120000000]), ("계약 금액이 5만 달러라면", [50000]),
])
def test_amounts_are_read_from_english_and_korean(text, want):
    assert ranges.amounts_in([text]) == [float(x) for x in want]


@pytest.mark.parametrize("text", ["15분 안에 확인해야 해?", "SEV2 인시던트", "30 days", "500만 원", "Level 3 approval", "", "2026-10-27 기준"])
def test_numbers_without_a_currency_mark_are_not_amounts(text):
    assert ranges.amounts_in([text]) == []


def test_amounts_skip_none_and_dedupe_across_texts():
    assert ranges.amounts_in([None, "3만 달러", "contract worth $30,000", "$30K"]) == [30000.0]


def test_long_digit_run_does_not_hang():
    assert ranges.amounts_in(["1" * 5000 + " 만 " * 200 + "x"]) == []


# ---------- 구간 제목 읽기 ----------

@pytest.mark.parametrize("heading,lo,hi,lo_open", [
    (">$0K to $25K", 0, 25e3, True), (">$25K up to $50K", 25e3, 50e3, True), (">$50K up to $250K", 50e3, 250e3, True),
    ("$500K to $1M", 5e5, 1e6, False), ("$1M up to $5M", 1e6, 5e6, False), (">$0k up to $500k", 0, 5e5, True),
    ("Up to $10K", 0, 1e4, False), ("$10K to $100K", 1e4, 1e5, False),
    (">$5M", 5e6, float("inf"), True), (">$500K and above", 5e5, float("inf"), True), ("Over $500K", 5e5, float("inf"), True),
    ("$100K plus", 1e5, float("inf"), False),
])
def test_band_headings_are_parsed(heading, lo, hi, lo_open):
    b = ranges.parse_band(heading)
    assert (b.lo, b.hi, b.lo_open) == (lo, hi, lo_open)


@pytest.mark.parametrize("heading", [
    "$500k annual revenue", "Setting up an existing environment ($GCP_ENV_PREFIX)", "Standard Terms", "", None,
    "recurring charges for vendors under $5,000 USD for an individual charge", "$30K to $10K",
])
def test_headings_that_are_not_a_band_are_ignored(heading):
    assert ranges.parse_band(heading) is None


def test_band_edges_follow_the_printed_notation():
    gt = ranges.parse_band(">$25K up to $50K")        # '>'가 있으면 아래 끝은 포함하지 않는다
    assert not gt.covers(25000) and gt.covers(25001) and gt.covers(50000) and not gt.covers(50001)
    plain = ranges.parse_band("$10K to $100K")
    assert plain.covers(10000) and plain.covers(100000)


# ---------- 금액이 속한 행 고르기 ----------

TABLE = [(1, "Approving expense > >$0K to $25K"), (2, "Approving expense > >$25K up to $50K"), (3, "Approving expense > >$50K up to $250K"),
         (4, "Approving Payment > >$0k up to $500k"), (5, "Approving Payment > >$500K and above"),
         (6, "Non Billable Expenses > Up to $5K"), (7, "Non Billable Expenses > >$5K"), (8, "Non Billable Expenses > >$50K"),
         (9, "Legal Contracts > Standard Terms"), (10, "Legal Contracts > Non standard terms > $500k annual revenue")]


def keys(amounts):
    return [k for k, _ in ranges.covering(TABLE, amounts)]


def test_covering_picks_one_row_per_table_for_each_amount():
    assert keys([30000]) == [2, 4, 7]          # 표마다 하나: 지출 승인 >$25K~$50K, 지급 승인 >$0k~$500k, 비청구 경비 >$5K
    assert keys([100000]) == [3, 4, 8]         # 겹친 구간(>$5K와 >$50K)은 더 구체적인(아래 끝이 큰) 쪽
    assert keys([600000]) == [5, 8]            # 지출 승인 표에는 이 예제 표에서 $600K 구간이 없다
    assert keys([3000]) == [1, 4, 6]


def test_covering_with_two_amounts_returns_both_rows_of_a_table():
    assert keys([30000, 100000]) == [2, 3, 4, 7, 8]


def test_covering_returns_nothing_without_amounts_or_matching_band():
    assert keys([]) == [] and keys([-1]) == []
    assert ranges.covering([(9, "Legal Contracts > Standard Terms")], [30000]) == []


# ---------- 검색에 붙인 구간 조회(MemoryStore) ----------

QUESTION = "approval for 30k"            # 영어 질문은 번역하지 않는다(valid_english)


def mk(article, v, *, cid, seq=7, page="Authorization Matrix"):
    return {"chunk_id": cid, "version_id": "v1", "rule_seq": seq, "org": "finance", "rule_title": page, "article": article,
            "version_date": "2023-05-01", "fetched_at": "2026-10-27", "kind": "row", "text": cid, "source_url": "https://h/x", "text_sha256": None,
            "line_start": 1, "line_end": 1, "valid_from": "2023-05-01", "valid_to": None, "link_targets": [], "_v": v}


def axis(i, n=6, w=1.0):
    v = np.full(n, 0.0, dtype=np.float32)
    v[i] = w
    return v


# 벡터 칸 0 = 질문. 구간 행 셋은 금액과 무관하게 질문과 거의 같은 점수(실제 voyage-4처럼 구분이 안 된다), 다른 페이지 청크 다섯 개가 더 가깝다.
BAND = [mk("Approving expense > >$0K to $25K", [0.20, 1, 0, 0, 0, 0], cid="b1"),
        mk("Approving expense > >$25K up to $50K", [0.19, 0, 1, 0, 0, 0], cid="b2"),
        mk("Approving expense > >$50K up to $250K", [0.21, 0, 0, 1, 0, 0], cid="b3")]
OTHER = [mk(None, [0.9 - 0.01 * i, 0, 0, 0, 1, 0], cid=f"o{i}", seq=100 + i, page=f"page {i}") for i in range(5)]
MEM_ROWS = [BAND[0], BAND[1], BAND[2], dict(OTHER[0], rule_seq=7, article="Legal Contracts > Standard Terms")] + OTHER[1:]


def searcher(rows, **cfg):
    vecs = np.stack([np.asarray(r["_v"], dtype=np.float32) / np.linalg.norm(r["_v"]) for r in rows])
    calls: list = []
    q = np.asarray([1, 0, 0, 0, 0, 0], dtype=np.float32)

    def embedder(texts):
        calls.append(list(texts))
        return np.stack([q for _ in texts])
    s = Searcher(SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", **cfg), MemoryStore(rows, vecs, "voyage-4"),
                 embedder=embedder, reranker=None, check_meta=False,
                 translator=lambda query, kind: translate.Result(query, "stored"))
    s.calls = calls
    return s


def ids(chunks):
    return [c.chunk_id for c in chunks]


def test_range_row_for_the_amount_is_brought_into_the_top_k():
    s = searcher(MEM_ROWS, link_n=0)
    plain = ids(s.search(SearchQuery(query="approval for who", k=5)))
    assert "b2" not in plain                                    # 금액이 없으면 구간 행은 안 든다(벡터 점수가 낮다)
    got = s.search(SearchQuery(query="approval for $30,000 contract", k=5))
    assert "b2" in ids(got) and len(got) == 5
    tr = last_search_trace()
    assert tr.n_range == 1 and tr.ms["range"] >= 0


def test_other_amount_picks_the_other_row():
    s = searcher(MEM_ROWS, link_n=0)
    assert "b3" in ids(s.search(SearchQuery(query="approval for $100K", k=5)))
    assert "b1" in ids(s.search(SearchQuery(query="approval for $10,000", k=5)))


def test_korean_amount_in_the_original_question_counts_even_when_the_translation_dropped_it():
    s = searcher(MEM_ROWS, link_n=0)
    q = SearchQuery(query="계약 금액이 3만 달러라면 누가 승인해?", k=5)
    s.translator = lambda query, kind: translate.Result("who approves this contract", "stored")   # 번역이 금액을 잃은 경우
    assert "b2" in ids(s.search(q))


def test_amount_only_in_a_sub_question_counts():
    s = searcher(MEM_ROWS, link_n=0)
    got = s.search(SearchQuery(query="approval and finance owner", sub_queries=["who approves", "budget at $30K"], k=5))
    assert "b2" in ids(got)


def test_no_amount_leaves_results_unchanged():
    on, off = searcher(MEM_ROWS, link_n=0), searcher(MEM_ROWS, link_n=0, range_n=0)
    q = SearchQuery(query="approval for 15 minutes on SEV2", k=5)
    assert ids(on.search(q)) == ids(off.search(q))
    assert last_search_trace().n_range == 0


def test_switch_off_leaves_results_unchanged():
    on = searcher(MEM_ROWS, link_n=0, range_n=0)
    got = on.search(SearchQuery(query="approval for $30,000", k=5))
    assert "b2" not in ids(got) and last_search_trace().n_range == 0


def test_row_already_in_top_k_is_kept_and_costs_no_place():
    rows = [dict(r, _v=[0.99 if r["chunk_id"] == "b2" else r["_v"][0]] + r["_v"][1:]) for r in MEM_ROWS]
    on, off = searcher(rows, link_n=0), searcher(rows, link_n=0, range_n=0)
    q = SearchQuery(query="approval for $30,000", k=5)
    assert ids(on.search(q)) == ids(off.search(q)) and "b2" in ids(on.search(q))
    assert last_search_trace().n_range == 0


def test_page_without_band_rows_in_the_top_k_is_not_touched():
    rows = [r for r in MEM_ROWS if r["chunk_id"] not in ("b1", "b2", "b3")] + [dict(BAND[1], rule_seq=999, chunk_id="far")]
    s = searcher(rows, link_n=0)
    assert "far" not in ids(s.search(SearchQuery(query="approval for $30,000", k=5)))      # 상위 k의 페이지에 구간 행이 없으면 다른 페이지를 뒤지지 않는다


def test_range_n_caps_the_replaced_places_and_k_stays():
    rows = MEM_ROWS + [mk("Approving Payment > >$0k up to $500k", [0.10, 0, 0, 0, 0, 1], cid="p1"),
                       mk("Non Billable Expenses > >$5K", [0.11, 0, 0, 0, 0, 1], cid="n1"),
                       mk("Approving Payment > >$500K and above", [0.12, 0, 0, 0, 0, 1], cid="p2")]
    two = searcher(rows, link_n=0, range_n=2).search(SearchQuery(query="approval for $30,000", k=5))
    one = searcher(rows, link_n=0, range_n=1).search(SearchQuery(query="approval for $30,000", k=5))
    assert len(two) == len(one) == 5
    assert sum(c.chunk_id in {"b2", "p1", "n1"} for c in two) == 2 and sum(c.chunk_id in {"b2", "p1", "n1"} for c in one) == 1


def test_table_choice_follows_the_full_question_vector_not_the_sub_questions():
    """금액이 속한 표가 여럿일 때 어느 표의 행을 남기는지는 하위 질문(LLM이 회차마다 다르게 씀)이 아니라 전체 질문 벡터로 정한다."""
    rows = MEM_ROWS + [mk("Approving Payment > >$0k up to $500k", [0.10, 0, 0, 0, 0, 1], cid="p1"),
                       mk("Non Billable Expenses > >$5K", [0.11, 0, 0, 0, 0, 1], cid="n1")]
    rows += [mk(None, [0, 0, 0, 0, 1, 0.5], cid=f"f{i}", seq=300 + i, page=f"filler {i}") for i in range(4)]   # 하위 질문 쪽 상위를 채워 구간 행 b1~b3이 우연히 들지 않게 한다
    vecs = np.stack([np.asarray(r["_v"], dtype=np.float32) / np.linalg.norm(r["_v"]) for r in rows])
    full, sub = np.asarray([1, 0, 0, 0, 0, 0], dtype=np.float32), np.asarray([0, 0, 0, 0, 0, 1], dtype=np.float32)   # 하위 질문은 지급 승인 쪽으로 쏠린다

    def build(sub_vec):
        embed_ = lambda texts: np.stack([full if i == 0 else sub_vec for i in range(len(texts))])  # noqa: E731
        return Searcher(SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", link_n=0, range_n=1), MemoryStore(rows, vecs, "voyage-4"),
                        embedder=embed_, reranker=None, check_meta=False, translator=lambda query, kind: translate.Result(query, "stored"))

    q = SearchQuery(query="approval for $30,000", sub_queries=["who approves the contract", "who signs it"], k=5)
    assert "b2" in ids(build(sub).search(q))
    assert "b2" in ids(build(np.asarray([0, 0, 0, 0, 0.2, 1], dtype=np.float32)).search(q))     # 하위 질문이 바뀌어도 같은 표가 남는다


# ---------- 질문이 이름을 부른 표 먼저(사전 등록 62.27) ----------

@pytest.mark.parametrize("a,b,want", [
    ("approver", "approving", True), ("approval", "approving", True), ("expense", "expenses", True), ("payment", "payments", True),
    ("contract", "contracts", True), ("approve", "appropriate", False), ("debt", "debts", False), ("fund", "funds", False), ("sign", "signing", False),
])
def test_same_word_compares_stems(a, b, want):
    assert ranges.same_word(a, b) is want and ranges.same_word(b, a) is want


def test_table_named_matches_question_words_in_any_text():
    table = ("Approving expense",)
    assert ranges.table_named(table, ["계약 금액이 1만 달러라면 업무 승인자는 누구야?", "Who is the approver for a $10,000 contract?"])
    assert ranges.table_named(("Approving Payment",), [None, "who is the finance approver"])
    assert not ranges.table_named(("Bad debt write off",), ["Who is the approver for a $10,000 contract?"])
    assert not ranges.table_named(("Non Billable Expenses",), ["who signs a contract"])          # 'non'은 불용어, 'expenses'는 질문에 없다
    assert not ranges.table_named(table, ["계약 금액이 1만 달러라면 업무 승인자는 누구야?"])     # 한국어만 있으면 맞추지 못한다
    assert not ranges.table_named((), ["approver"])


FOUR_TABLES = MEM_ROWS + [mk("Approving Payment > >$0k up to $500k", [0.10, 0, 0, 0, 0, 1], cid="p1"),
                          mk("Bad debt write off > Up to $10K", [0.30, 0, 0, 0, 0, 1], cid="d1"),          # 질문의 "$10,000"과 글자가 겹쳐 점수가 가장 높다
                          mk("Non Billable Expenses > >$5K", [0.25, 0, 0, 0, 0, 1], cid="n1")]


def test_tables_named_by_the_question_come_before_higher_scoring_tables():
    """$10,000은 네 표에 든다. 질문이 'approver'라고 했으면 'Approving expense'·'Approving Payment'가 점수가 더 높은 'Bad debt write off'보다 먼저다."""
    got = ids(searcher(FOUR_TABLES, link_n=0, range_n=2).search(SearchQuery(query="who is the approver for a $10,000 contract", k=5)))
    assert "b1" in got and "p1" in got and "d1" not in got and "n1" not in got and len(got) == 5
    three = ids(searcher(FOUR_TABLES, link_n=0, range_n=3).search(SearchQuery(query="who is the approver for a $10,000 contract", k=5)))
    assert {"b1", "p1", "d1"} <= set(three)                      # 세 번째 자리는 이름이 없는 표 중 점수 순


def test_without_a_table_name_in_the_question_the_vector_order_stays():
    got = ids(searcher(FOUR_TABLES, link_n=0, range_n=2).search(SearchQuery(query="who signs a $10,000 contract", k=5)))
    assert "d1" in got and "n1" in got and "b1" not in got and "p1" not in got


def test_sub_question_text_can_name_the_table():
    """표 이름은 전체 질문뿐 아니라 하위 질문(번역 포함)에 있어도 센다. 이름이 맞는 표가 여럿이면 그 안에서는 전체 질문 벡터 점수 순이다."""
    q = SearchQuery(query="contract of $10,000", sub_queries=["who approves the payment", "who signs"], k=5)
    assert ids(searcher(FOUR_TABLES, link_n=0, range_n=1).search(q))[-1] == "b1"           # 'approves'가 두 표(expense, Payment)에 맞고 점수는 b1(0.20) > p1(0.10)
    got = ids(searcher(FOUR_TABLES, link_n=0, range_n=2).search(q))
    assert "b1" in got and "p1" in got and "d1" not in got


def test_full_question_top_pages_are_candidates_when_the_sub_questions_miss_the_table_page():
    """하위 질문만으로 만든 상위 k에 표 페이지가 없어도, 전체 질문 벡터의 상위 k에 그 페이지가 있으면 구간 행을 찾는다."""
    rows = BAND + [mk(None, [0.0, 0, 0, 0, 1, 0], cid=f"o{i}", seq=100 + i, page=f"page {i}") for i in range(6)]   # 다른 페이지 여섯 개, 전체 질문과는 멀다
    rows = [dict(r, _v=[0.9, *r["_v"][1:]]) if r["chunk_id"].startswith("b") else r for r in rows]                  # 구간 행은 전체 질문과 가깝다
    vecs = np.stack([np.asarray(r["_v"], dtype=np.float32) / np.linalg.norm(r["_v"]) for r in rows])
    full, sub = np.asarray([1, 0, 0, 0, 0, 0], dtype=np.float32), np.asarray([0, 0, 0, 0, 1, 0], dtype=np.float32)

    def build(range_n):
        embed_ = lambda texts: np.stack([full if i == 0 else sub for i in range(len(texts))])  # noqa: E731
        return Searcher(SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", link_n=0, range_n=range_n), MemoryStore(rows, vecs, "voyage-4"),
                        embedder=embed_, reranker=None, check_meta=False, translator=lambda query, kind: translate.Result(query, "stored"))

    q = SearchQuery(query="approval for $30,000", sub_queries=["who approves the contract", "who signs it"], k=5)
    assert "b2" not in ids(build(0).search(q))                   # 하위 질문의 상위 k는 다른 페이지뿐이다
    got = ids(build(1).search(q))
    assert "b2" in got and len(got) == 5 and last_search_trace().n_range == 1


def test_unsplit_question_does_not_run_the_extra_page_query():
    s = searcher(MEM_ROWS, link_n=0)
    calls: list = []
    orig = s.store.vector_top
    s.store.vector_top = lambda *a, **kw: calls.append(a) or orig(*a, **kw)
    s.search(SearchQuery(query="approval for $30,000 contract", k=5))
    assert len(calls) == 1                                       # 나누지 않은 질문은 상위 k가 곧 전체 질문의 것이라 다시 묻지 않는다


def test_link_expanded_chunks_are_dropped_before_rows_that_belong_to_the_question():
    rows = [dict(r, link_targets=[100]) if r["chunk_id"] == "o1" else r for r in MEM_ROWS]
    got = searcher(rows, link_n=2).search(SearchQuery(query="approval for $30,000", k=5))
    assert "b2" in ids(got) and len(got) == 5


def test_filter_applies_to_band_rows():
    rows = [dict(r, org="security") if r["chunk_id"] == "b2" else r for r in MEM_ROWS]
    got = searcher(rows, link_n=0).search(SearchQuery(query="approval for $30,000", org="finance", k=5))
    assert "b2" not in ids(got)
    old = [dict(r, valid_to="2024-01-01") if r["chunk_id"] == "b2" else r for r in MEM_ROWS]
    assert "b2" not in ids(searcher(old, link_n=0).search(SearchQuery(query="approval for $30,000", k=5)))   # 현재 판이 아닌 구간 행은 안 든다


def test_store_without_range_queries_is_skipped():
    s = searcher(MEM_ROWS, link_n=0)
    s.store = type("Bare", (), {})()
    top = [("o0", "v1")]
    got = s._range_expand(top, {("o0", "v1"): {"rule_seq": 100}}, [np.zeros(6)], ["$30K"], SearchQuery(query="x"), SearchTrace("m", "none", "dense_en"))
    assert got == top


def test_config_checks_and_env(monkeypatch):
    assert SearchConfig(embed_model="voyage-4").range_n == 3
    with pytest.raises(ValueError):
        SearchConfig(embed_model="voyage-4", range_n=-1).check()
    monkeypatch.setenv("SEARCH_RANGE_N", "0")
    assert SearchConfig.from_env().range_n == 0
    monkeypatch.setenv("SEARCH_RANGE_N", "-1")
    with pytest.raises(ValueError):
        SearchConfig.from_env()


# ---------- 실제 색인에서 (스냅샷이 풀려 있을 때만) ----------

def _snapshot():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "index" / "chunks.jsonl"
    return p if p.is_file() else None


@pytest.mark.skipif(_snapshot() is None, reason="data/index 없음(압축을 풀어야 함)")
def test_real_authorization_matrix_bands_cover_every_amount_once_per_table():
    rows = [json.loads(x) for x in _snapshot().read_text(encoding="utf-8").splitlines() if x.strip()]
    heads = [(r["chunk_id"], r["article"]) for r in rows if r["rule_title"].startswith("Authorization Matrix (2023-05)") and "$" in (r["article"] or "")]
    by_id = dict(heads)
    want = {10000: ">$0K to $25K", 30000: ">$25K up to $50K", 50000: ">$25K up to $50K", 100000: ">$50K up to $250K", 300000: ">$250K up to $500K"}
    for amount, band in want.items():
        got = [by_id[k] for k, table in ranges.covering(heads, [float(amount)]) if table == ("Approving expense",)]
        assert got == ["Approving expense > " + band]


# ---------- PgStore (로컬 pgvector에서만) ----------

DB = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
def test_pg_store_band_queries_match_memory_store(tmp_path):
    import psycopg
    from pgvector.psycopg import register_vector
    from backend.rag.retrieve import embed, index, load_snapshot
    from backend.rag.retrieve.search import PgStore
    rows = [dict(r, seq=i) for i, r in enumerate(MEM_ROWS)]
    for r in rows:
        r.pop("_v")
    vecs = np.zeros((len(rows), 1024), dtype=np.float32)
    for i, r in enumerate(MEM_ROWS):
        vecs[i, :6] = np.asarray(r["_v"], dtype=np.float32) / np.linalg.norm(r["_v"])
    src = tmp_path / "chunks.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = embed.spec("voyage-4")
    index.write_snapshot(tmp_path / "idx", src, rows, s, vecs, {"revision": s.revision, "prefixes": {}})
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS chunks, versions, docs, index_meta, query_translations CASCADE")
        conn.commit()
        register_vector(conn)
        load_snapshot.load(conn, tmp_path / "idx", s.name, batch=2, log=lambda *_: None)
    pg = PgStore(DB)
    mem = MemoryStore([dict(r, valid_from=r["valid_from"]) for r in MEM_ROWS], vecs, s.name)
    for org, as_of in [(None, None), ("finance", None), ("security", None), (None, "2023-06-01"), (None, "2022-01-01")]:
        a, b = pg.band_headings([7], org, as_of), mem.band_headings([7], org, as_of)
        assert [(k, art) for k, art in a] == [(k, art) for k, art in b]
    assert pg.band_headings([], None, None) == []
    keys_ = [(r["chunk_id"], r["version_id"]) for r in MEM_ROWS[:3]]
    q = np.zeros(1024, dtype=np.float32)
    q[0] = 1
    a, b = pg.key_scores(q, s.name, keys_), mem.key_scores(q, s.name, keys_)
    assert a.keys() == b.keys() and all(abs(a[k] - b[k]) < 1e-5 for k in a)
    assert pg.key_scores(q, s.name, []) == {}
