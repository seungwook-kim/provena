"""검색 search() AC 시험 (docs/specs/search.md). 모델·DB 없이 가짜 임베더·리랭커·번역기와 MemoryStore로 돈다.
DB 시험(PgStore·load_snapshot)은 TEST_DATABASE_URL이 있을 때만, 모델 시험은 torch·캐시가 있을 때만 돈다."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

from backend.rag.retrieve import embed, rerank, translate
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, last_search_trace, rrf, tokens
from backend.schemas.chunk import SearchQuery

search_mod = sys.modules["backend.rag.retrieve.search"]   # 패키지의 search 는 계약 함수

VOCAB = ["approval", "saas", "security", "incident", "oncall", "budget", "review", "release"]


def vec(words: str) -> np.ndarray:
    v = np.array([float(w in words.split()) for w in VOCAB]) + 0.01
    return (v / np.linalg.norm(v)).astype(np.float32)


def row(cid, text, *, org="finance", rule_seq=1, ver="v1", vf="2026-01-01", vt=None, vdb=False, lines=(1, 1)):
    return {"chunk_id": cid, "version_id": ver, "rule_seq": rule_seq, "org": org, "rule_title": f"page {rule_seq}",
            "article": None, "version_date": vf, "version_date_before": vdb, "fetched_at": "2026-10-27", "kind": "article",
            "text": text, "source_url": f"https://handbook.example/{rule_seq}#L{lines[0]}", "text_sha256": None,
            "line_start": lines[0], "line_end": lines[1], "valid_from": vf, "valid_to": vt}


def store(rows, embedder="Snowflake/snowflake-arctic-embed-l-v2.0"):
    return MemoryStore(rows, np.stack([vec(r["text"]) for r in rows]), embedder)


KO2EN = {"외부 SaaS 승인": "saas approval", "보안 사고": "security incident"}


def fake_translator(calls=None):
    def tr(query, kind):
        if calls is not None:
            calls.append((query, kind))
        text = KO2EN.get(query)
        return translate.Result(text, "llm" if text else "invalid")
    return tr


def fake_embed(texts):
    return np.stack([vec(KO2EN.get(t, t)) for t in texts])


class FakeReranker:
    """본문에 'release'가 있으면 맨 위로(순서를 바꾸는지 보려고)."""
    def score(self, query, texts):
        return [1.0 if "release" in t else 0.0 for t in texts]


def make(rows, mode="hybrid_ko_kw", reranker=None, translator=None, **kw):
    cfg = SearchConfig(embed_model="Snowflake/snowflake-arctic-embed-l-v2.0", mode=mode,
                       rerank_model="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1" if reranker else "none", **kw)
    return Searcher(cfg, store(rows), embedder=fake_embed, reranker=reranker,
                    translator=translator or fake_translator(), check_meta=False)


ROWS = [row("a1", "saas approval budget"), row("a2", "saas review", org="security", rule_seq=2),
        row("a3", "approval release", rule_seq=3), row("a4", "security incident oncall", org="security", rule_seq=4),
        row("a5", "budget review", rule_seq=5)]


# ---------- AC-01 · 필터는 검색 전에 ----------

def test_ac01_filter_before_search_returns_fewer_not_outside():
    s = make(ROWS)
    got = s.search(SearchQuery(query="외부 SaaS 승인", org="security", k=5))
    assert {c.org for c in got} == {"security"}
    assert len(got) == 2                       # 모자라도 필터 밖으로 채우지 않는다(EC-04)
    assert last_search_trace().n_filtered == 2


def test_ac01_as_of_too_early_and_unknown_org_return_empty():
    s = make(ROWS)
    assert s.search(SearchQuery(query="외부 SaaS 승인", as_of="2025-12-31")) == []
    assert s.search(SearchQuery(query="외부 SaaS 승인", org="no-such-org")) == []


# ---------- AC-01b · 기준일이 없으면 현재 판만 ----------

VERS = [row("o1", "saas approval budget", ver="old", vf="2024-01-01", vt="2025-06-01", vdb=True),
        row("n1", "saas approval budget", ver="new", vf="2025-06-01", vdb=True),
        row("x1", "security incident", rule_seq=9, org="security", vf="2024-01-01")]


def test_ac01b_no_as_of_returns_only_current_version():
    got = make(VERS).search(SearchQuery(query="외부 SaaS 승인", k=5))
    assert {(c.chunk_id, c.version_id) for c in got if c.rule_seq == 1} == {("n1", "new")}
    assert all(c.version_date_before for c in got if c.rule_seq == 1)


def test_ac01b_boundary_day_belongs_to_new_version():
    s = make(VERS)
    on = s.search(SearchQuery(query="외부 SaaS 승인", as_of="2025-06-01", k=5))
    before = s.search(SearchQuery(query="외부 SaaS 승인", as_of="2025-05-31", k=5))
    assert [c.version_id for c in on if c.rule_seq == 1] == ["new"]
    assert [c.version_id for c in before if c.rule_seq == 1] == ["old"]


# ---------- AC-02 · 같은 입력, 같은 결과 ----------

def test_ac02_same_order_and_translation_reused(monkeypatch):
    calls = []
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    st = store(ROWS)
    tr = lambda q, kind: translate.translate(q, kind, st, call=lambda q2, k2: (calls.append(q2), KO2EN[q2])[1])  # noqa: E731
    s = Searcher(SearchConfig(embed_model="Snowflake/snowflake-arctic-embed-l-v2.0", rerank_model="none"), st,
                 embedder=fake_embed, translator=tr, check_meta=False)
    q = SearchQuery(query="외부 SaaS 승인", k=4)
    first = [c.chunk_id for c in s.search(q)]
    second = [c.chunk_id for c in s.search(q)]
    assert first == second
    assert len(calls) == 1                      # 두 번째는 장부에서
    assert last_search_trace().translation_source == "stored"


# ---------- AC-03 · 모델은 환경 변수로만 ----------

@pytest.mark.parametrize("model", list(embed.EMBEDDERS))
@pytest.mark.parametrize("reranker", [*rerank.RERANKERS, "none"])
def test_ac03_every_candidate_name_runs(model, reranker, monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", model)
    monkeypatch.setenv("RERANK_MODEL", reranker)
    cfg = SearchConfig.from_env()
    s = Searcher(cfg, store(ROWS, model), embedder=fake_embed, reranker=FakeReranker(), translator=fake_translator(),
                 check_meta=False)
    assert s.search(SearchQuery(query="외부 SaaS 승인", k=3))


@pytest.mark.parametrize("var,value", [("EMBED_MODEL", "no/such-model"), ("RERANK_MODEL", "no-such"),
                                       ("SEARCH_MODE", "hybrid_en")])
def test_ac03_unknown_name_stops(var, value, monkeypatch):
    monkeypatch.setenv(var, value)
    with pytest.raises(ValueError):
        SearchConfig.from_env()


# ---------- AC-04 · 키 없이 동작 ----------

def test_ac04_demo_without_record_falls_back_to_dense_ko(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(tmp_path))      # 녹화 없음
    st = store(ROWS)
    s = Searcher(SearchConfig(embed_model="Snowflake/snowflake-arctic-embed-l-v2.0", rerank_model="none"), st,
                 embedder=fake_embed, check_meta=False)   # 진짜 translate + llm.py 재생 모델
    got = s.search(SearchQuery(query="외부 SaaS 승인", k=3))
    tr = last_search_trace()
    assert got and tr.mode == "dense_ko" and tr.fallback == "dense_ko" and tr.fallback_reason == "demo_no_record"
    assert st.translations == {}                 # 가짜 한국어 응답은 장부에 적지 않는다


@pytest.mark.parametrize("mode", ["hybrid_ko_kw", "dense_en", "bm25_kw"])
def test_english_query_is_not_sent_to_translator(mode):
    calls = []
    s = make(ROWS, mode=mode, translator=fake_translator(calls))
    s.search(SearchQuery(query="vendor approval limit"))
    tr = last_search_trace()
    assert calls == [] and tr.translation_source == "as_is" and tr.mode == mode and tr.fallback is None


def test_korean_query_still_goes_to_translator():
    calls = []
    s = make(ROWS, translator=fake_translator(calls))
    s.search(SearchQuery(query="외부 SaaS 승인"))
    assert len(calls) == 1 and last_search_trace().translation_source != "as_is"


def test_query_translate_off_is_dense_ko():
    s = make(ROWS, translate=False)
    s.search(SearchQuery(query="외부 SaaS 승인", k=3))
    assert last_search_trace().mode == "dense_ko" and last_search_trace().fallback_reason == "translate_off"


# ---------- AC-05 · 장부·판 대조 ----------

def test_meta_mismatch_or_not_ready_stops():
    base = {"embedder": "Snowflake/snowflake-arctic-embed-l-v2.0", "revision": embed.EMBEDDERS[
        "Snowflake/snowflake-arctic-embed-l-v2.0"].revision, "dim": 1024, "status": "ready"}
    for bad in ({**base, "embedder": "BAAI/bge-m3"}, {**base, "revision": "0" * 40}, {**base, "status": "loading"}, None):
        st = MemoryStore(ROWS, np.stack([vec(r["text"]) for r in ROWS]), "x", meta=bad)
        with pytest.raises(RuntimeError):
            Searcher(SearchConfig(embed_model=base["embedder"], rerank_model="none"), st, embedder=fake_embed,
                     translator=fake_translator())


def test_model_revision_must_match_cache_folder(monkeypatch, tmp_path):
    huggingface_hub = pytest.importorskip("huggingface_hub")   # 팀 requirements에는 아직 없다(모델 의존은 질문 6)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: str(tmp_path / ("f" * 40)))
    with pytest.raises(ValueError, match="판이 다르다"):
        embed.snapshot_dir("BAAI/bge-m3", "a" * 40, True)


def test_duplicate_weight_files_are_skipped_only_where_safetensors_exists():
    """중복 가중치만 받지 않는다. bge-m3는 pytorch_model.bin이 유일한 가중치라 받아야 한다. Dockerfile도 같은 목록이다."""
    assert "pytorch_model.bin" in embed.ignore_patterns("intfloat/multilingual-e5-large")
    assert "pytorch_model.bin" in embed.ignore_patterns("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    assert "pytorch_model.bin" not in embed.ignore_patterns("BAAI/bge-m3")
    docker = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "'pytorch_model.bin'" in docker and all(f"'{n}'" in docker for n in embed.DUPLICATE_BIN)


def test_every_search_table_turns_on_row_level_security():
    """Supabase Data API로 표가 열리지 않게, 201_search.sql의 모든 표에 RLS를 켠다."""
    import re
    sql = (Path(__file__).resolve().parents[1] / "db" / "201_search.sql").read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
    assert tables and set(tables) == set(re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY;", sql))


# ---------- 순위 결합·리랭킹 ----------

def test_rrf_uses_ranks_not_scores_and_ties_keep_first_seen():
    a, b, c, d = (("a", "v"), ("b", "v"), ("c", "v"), ("d", "v"))
    assert rrf([[a, b], [b, c]])[0] == (b, pytest.approx(1 / 62 + 1 / 61))   # 양쪽 다 상위면 위로(점수가 아니라 순위)
    fused = rrf([[d, b], [c, a]])                       # d·c 1/61 동점, b·a 1/62 동점 (가나다순과 반대로 넣음)
    assert [k for k, _ in fused] == [d, c, b, a]         # 동점은 먼저 들어온 순서(벡터 목록 먼저, experiment_v1과 같음)


def test_rerank_none_keeps_rrf_order_and_reranker_reorders():
    q = SearchQuery(query="외부 SaaS 승인", k=3)
    plain = [c.chunk_id for c in make(ROWS).search(q)]
    ranked = [c.chunk_id for c in make(ROWS, reranker=FakeReranker()).search(q)]
    assert plain[0] == "a1" and ranked[0] == "a3"


def test_vector_ids_and_scores_belong_together():
    st = store(ROWS)
    q = vec("saas approval")
    for (cid, ver), score in st.vector_top(q, st.embedder, None, None, 5):
        assert score == pytest.approx(float(vec(st.fetch([(cid, ver)])[(cid, ver)]["text"]) @ q), abs=1e-6)


def test_vector_ties_break_by_chunk_id():
    rows = [row("b", "saas approval"), row("a", "saas approval", rule_seq=2)]
    st = store(rows)
    assert [k[0] for k, _ in st.vector_top(vec("saas approval"), st.embedder, None, None, 2)] == ["a", "b"]


@pytest.mark.parametrize("q", [SearchQuery(query="x", k=0), SearchQuery(query="x", as_of="2026-1-1"),
                               SearchQuery(query="x", as_of="2026-02-30"), SearchQuery(query="  ")])
def test_bad_input_stops(q):
    with pytest.raises(ValueError):
        make(ROWS).search(q)


# ---------- 번역 ----------

def test_translate_rejects_echo_and_retries_once(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    st, calls = store(ROWS), []
    res = translate.translate("질문", "keywords", st, call=lambda q, k: (calls.append(1), "Rewrite the user's question")[1])
    assert res.text is None and res.source == "invalid" and len(calls) == 2 and st.translations == {}


def test_translate_cost_cap_does_not_retry(monkeypatch):
    from backend.services.cost import CostCapExceeded
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    calls = []

    def capped(q, k):
        calls.append(1)
        raise CostCapExceeded(0.06, 0.05)
    assert translate.translate("질문", "keywords", store(ROWS), call=capped).source == "cost_cap" and len(calls) == 1


@pytest.mark.parametrize("provider,model", [("openrouter", ""), ("anthropic", ""), ("claude_cli", ""),
                                            ("openrouter", "anthropic/claude-haiku-5.5")])
def test_translation_model_name_is_normalized(provider, model, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", model)
    assert translate.model_id() == "claude-haiku-5-5"


# ---------- 1차 비교와 같은 설정 ----------

def test_same_settings_as_experiment_v1():
    ex = pytest.importorskip("evals.retrieval.experiment_v1")
    assert translate.PROMPTS == ex.PROMPTS
    assert search_mod.RRF_K == ex.RRF_K and SearchConfig(embed_model="x").pool == ex.POOL
    for s in embed.EMBEDDERS.values():
        if s.api:                                   # API 모델은 1차 비교의 API 명부와 대조
            assert ex.API_EMBEDDERS[s.short] == s.name
            continue
        hf, prefixes, _ = ex.EMBEDDERS[s.short]
        assert (hf, prefixes) == (s.name, s.prefixes)
    for s in rerank.RERANKERS.values():
        assert ex.RERANKERS[s.short] == s.hf
    for text in ["How do I get approval for a $30K SaaS?", "the on-call SLA is 15 min", "a b c"]:
        assert tokens(text) == ex._tokens(text)
    for text in ["approval SaaS", "승인", "x@y.com", "Output only", "Rewrite the user's question", ""]:
        assert translate.valid_english(text) == ex.valid_english(text)


# ---------- 적재 ----------

def test_versions_valid_to_is_next_version_date():
    from backend.rag.retrieve.load_snapshot import versions_of
    rows = [{"rule_seq": 1, "version_id": "b", "version_date": "2025-06-01"},
            {"rule_seq": 1, "version_id": "a", "version_date": "2024-01-01"},
            {"rule_seq": 2, "version_id": "c", "version_date": "2026-10-27"}]
    got = {(v["rule_seq"], v["version_id"]): (v["valid_from"], v["valid_to"]) for v in versions_of(rows)}
    assert got == {(1, "a"): ("2024-01-01", "2025-06-01"), (1, "b"): ("2025-06-01", None), (2, "c"): ("2026-10-27", None)}


DB = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
def test_db_load_is_idempotent_and_matches_memory(tmp_path):
    """적재 두 번 → 행 수 같음·두 번째는 건너뜀 / PgStore 검색 == MemoryStore 검색(V2 축소판)."""
    import psycopg
    from pgvector.psycopg import register_vector
    from backend.rag.retrieve import index, load_snapshot
    from backend.rag.retrieve.search import PgStore
    rows = [dict(r, seq=i) for i, r in enumerate(ROWS)]
    src = tmp_path / "chunks.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = embed.EMBEDDERS["Snowflake/snowflake-arctic-embed-l-v2.0"]
    vecs = np.zeros((len(rows), s.dim), dtype=np.float32)
    vecs[:, :len(VOCAB)] = np.stack([vec(r["text"]) for r in rows])
    index.write_snapshot(tmp_path / "idx", src, rows, s, vecs, {"revision": s.revision, "prefixes": {}})
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS chunks, versions, docs, index_meta, query_translations CASCADE")
        conn.commit()
        register_vector(conn)
        first = load_snapshot.load(conn, tmp_path / "idx", s.name, batch=2, log=lambda *_: None)
        second = load_snapshot.load(conn, tmp_path / "idx", s.name, batch=2, log=lambda *_: None)
        assert first["chunks"] == len(rows) and second["skipped"]
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == len(rows)
        # 줄 범위 칸이 비어 있는 옛 DB(같은 스냅샷, ready)는 건너뛰지 않고 다시 채운다
        conn.execute("UPDATE chunks SET line_start = NULL, line_end = NULL")
        conn.commit()
        third = load_snapshot.load(conn, tmp_path / "idx", s.name, batch=2, log=lambda *_: None)
        assert not third["skipped"]
        assert conn.execute("SELECT count(*) FROM chunks WHERE line_start IS NULL").fetchone()[0] == 0
    pg = PgStore(DB)
    keys = [(r["chunk_id"], r["version_id"]) for r in rows]
    got = pg.fetch(keys)
    assert [(got[k]["line_start"], got[k]["line_end"]) for k in keys] == [(r["line_start"], r["line_end"]) for r in rows]
    mem = MemoryStore(rows, vecs, s.name)
    q = np.zeros(s.dim, dtype=np.float32)
    q[:len(VOCAB)] = vec("saas approval")
    for org, as_of in [(None, None), ("security", None), (None, "2025-12-31")]:
        a = [k for k, _ in pg.vector_top(q, s.name, org, as_of, 5)]
        b = [k for k, _ in mem.vector_top(q, s.name, org, as_of, 5)]
        assert a == b


# ---------- 실제 모델 (캐시가 있을 때만) ----------

def _cached(name, rev):
    try:
        embed.snapshot_dir(name, rev, True)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _cached("Snowflake/snowflake-arctic-embed-l-v2.0", embed.EMBEDDERS[
    "Snowflake/snowflake-arctic-embed-l-v2.0"].revision), reason="arctic 캐시 없음")
def test_real_arctic_query_prefix_and_dim():
    pytest.importorskip("torch")
    model = embed.load_model("Snowflake/snowflake-arctic-embed-l-v2.0", "cpu")
    v = embed.encode_queries(model, ["외부 SaaS 3만 달러 도입은 누가 승인하나"])
    assert v.shape == (1, 1024)
    assert embed.used_prefixes(model, embed.spec("Snowflake/snowflake-arctic-embed-l-v2.0"))["query"] == "query: "


# ---------- 줄 범위 (평가셋 `경로#L123` 정답, Spec 열린 항목 8) ----------

def test_result_carries_line_range_and_line_gold_matches():
    from evals.retrieval.gold import GoldRef
    rows = [row("a1", "saas approval budget", lines=(520, 525)), row("a3", "approval release", rule_seq=3, lines=(10, 12))]
    out = make(rows).search(SearchQuery(query="외부 SaaS 승인", k=5))
    by_id = {c.chunk_id: c for c in out}
    assert (by_id["a1"].line_start, by_id["a1"].line_end) == (520, 525)
    assert (by_id["a3"].line_start, by_id["a3"].line_end) == (10, 12)
    # 채점기(gold.py)는 `경로#L523`을 결과의 line_start <= 523 <= line_end 로 맞춘다. 줄 범위가 없으면 늘 0점이었다(Q15)
    gold = GoldRef(rule_seq=1, line=523)
    assert gold.matches(by_id["a1"]) and not gold.matches(by_id["a3"])
    assert not GoldRef(rule_seq=1, line=526).matches(by_id["a1"])   # 끝 줄 다음은 아니다


def test_line_range_defaults_to_none_for_old_rows():
    """줄 범위가 없는 행(옛 적재본)도 검색은 되고 칸만 비어 있다."""
    rows = [row("a1", "saas approval budget")]
    for r in rows:
        del r["line_start"], r["line_end"]
    c = make(rows).search(SearchQuery(query="외부 SaaS 승인", k=1))[0]
    assert c.line_start is None and c.line_end is None


# ---------- make_search (evals/retrieval/compare.py --factory 입구, 11/6 v2 비교) ----------

import dataclasses  # noqa: E402

from backend.rag.retrieve import index as index_mod  # noqa: E402

EMB = "Snowflake/snowflake-arctic-embed-l-v2.0"


def write_index(tmp_path, rows, monkeypatch, translations=True):
    """가짜 스냅샷(data/index/ 형식): chunks.jsonl · vectors/arctic-l-v2.npy · meta.json (+ 번역 장부)."""
    monkeypatch.delenv("EMBED_REVISION", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = dataclasses.replace(embed.EMBEDDERS[EMB], dim=len(VOCAB))
    monkeypatch.setitem(embed.EMBEDDERS, EMB, s)
    out = tmp_path / "index"
    (out / "vectors").mkdir(parents=True)
    keep = ("chunk_id", "version_id", "rule_seq", "org", "rule_title", "article", "version_date", "version_date_before",
            "fetched_at", "kind", "text", "source_url", "text_sha256", "line_start", "line_end")
    (out / "chunks.jsonl").write_text("".join(json.dumps({k: r[k] for k in keep}) + "\n" for r in rows), encoding="utf-8")
    np.save(out / "vectors" / "arctic-l-v2.npy", np.stack([vec(r["text"]) for r in rows]))
    meta = {"chunks_file": "chunks.jsonl", "chunks_sha256": index_mod.file_sha(out / "chunks.jsonl"), "n_chunks": len(rows),
            "embedders": {EMB: {"short": "arctic-l-v2", "revision": s.revision, "dim": s.dim, "prefixes": {},
                                "file": "vectors/arctic-l-v2.npy",
                                "sha256": index_mod.file_sha(out / "vectors" / "arctic-l-v2.npy")}}}
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if translations:
        src = tmp_path / "translations.json"
        src.write_text(json.dumps({"model": translate.model_id(),
                                   "items": {q: {"keywords": en, "sentence": en} for q, en in KO2EN.items()}}),
                       encoding="utf-8")
        assert index_mod.main(["translations", "--from", str(src), "--out", str(out)]) == 0
    monkeypatch.setenv("SEARCH_INDEX_DIR", str(out))
    return out


@pytest.fixture
def eval_env(monkeypatch):
    """비교 입구의 캐시를 비우고, 실제 모델 대신 가짜 임베더·리랭커를 끼운다(불린 횟수를 센다)."""
    loads = {"embed": 0, "rerank": 0, "bm25": 0}

    def load_embed(name, entry):
        loads["embed"] += 1
        return fake_embed

    def load_rerank(name):
        loads["rerank"] += 1
        return FakeReranker()

    real_build = Searcher._build_bm25

    def build(self):
        loads["bm25"] += 1
        real_build(self)

    monkeypatch.setattr(search_mod, "_load_embedder", load_embed)
    monkeypatch.setattr(search_mod, "_load_reranker", load_rerank)
    monkeypatch.setattr(Searcher, "_build_bm25", build)
    for k in ("index", "meta", "rows", "bm25", "translations", "embedder", "reranker"):
        monkeypatch.setattr(search_mod._EvalCache, k, None)
    return loads


@pytest.mark.parametrize("mode", ["hybrid_ko_kw", "dense_ko", "dense_en", "bm25_kw"])
@pytest.mark.parametrize("reranker", ["none", "mminilm"])
def test_make_search_gives_same_results_as_service_searcher(mode, reranker, tmp_path, monkeypatch, eval_env):
    """비교 입구가 서비스와 같은 코드인가: 같은 행·같은 번역이면 Searcher와 결과가 같다."""
    write_index(tmp_path, ROWS, monkeypatch)
    fn = search_mod.make_search("none" if mode == "bm25_kw" else "arctic-l-v2", mode, reranker, 10 if reranker != "none" else 0)
    q = SearchQuery(query="외부 SaaS 승인", k=3)
    got = [c.chunk_id for c in fn(q)]
    assert last_search_trace().translation_source in (None, "stored")     # 번역은 장부에서(LLM 호출 없음)
    assert last_search_trace().mode == mode
    want = [c.chunk_id for c in make(ROWS, mode=mode, reranker=FakeReranker() if reranker != "none" else None).search(q)]
    assert got == want and got


def test_make_search_takes_short_and_long_names_and_refuses_unknown(tmp_path, monkeypatch, eval_env):
    write_index(tmp_path, ROWS, monkeypatch)
    q = SearchQuery(query="외부 SaaS 승인", k=3)
    a = [c.chunk_id for c in search_mod.make_search("arctic-l-v2", "hybrid_ko_kw", "mminilm", 10)(q)]
    b = [c.chunk_id for c in search_mod.make_search(EMB, "hybrid_ko_kw", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", 10)(q)]
    assert a == b
    for args in [("no-such", "dense_ko"), ("arctic-l-v2", "hybrid_en"), ("arctic-l-v2", "dense_ko", "no-such", 10),
                 ("none", "hybrid_ko_kw"), ("arctic-l-v2", "bm25_kw"), ("arctic-l-v2", "dense_ko", "mminilm", 0)]:
        with pytest.raises(ValueError):
            search_mod.make_search(*args)


def test_make_search_keeps_one_model_and_builds_bm25_once(tmp_path, monkeypatch, eval_env):
    """45조합을 노트북에서 돌릴 수 있게: 같은 임베딩·리랭커는 다시 올리지 않고, BM25 색인은 한 번만 만든다."""
    write_index(tmp_path, ROWS, monkeypatch)
    for rr in ("none", "mminilm", "mminilm", "none"):
        search_mod.make_search("arctic-l-v2", "hybrid_ko_kw", rr, 10 if rr != "none" else 0)
    search_mod.make_search("none", "bm25_kw")
    search_mod.make_search("arctic-l-v2", "dense_ko")
    assert eval_env == {"embed": 2, "rerank": 1, "bm25": 1}   # arctic → none(내림) → arctic 다시: 한 번에 하나만


def test_make_search_refuses_tampered_vectors(tmp_path, monkeypatch, eval_env):
    out = write_index(tmp_path, ROWS, monkeypatch)
    np.save(out / "vectors" / "arctic-l-v2.npy", np.zeros((len(ROWS), len(VOCAB)), dtype=np.float32))
    with pytest.raises(RuntimeError, match="벡터 파일"):
        search_mod.make_search("arctic-l-v2", "dense_ko")


def test_translations_seed_file_and_tamper_check(tmp_path, monkeypatch, eval_env):
    """index.py translations: 1차 비교 번역 → 장부 파일 + meta sha256. 파일이 바뀌면 멈춘다."""
    out = write_index(tmp_path, ROWS, monkeypatch)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    tr = meta["query_translations"]
    assert tr["n"] == len(KO2EN) and tr["model"] == translate.model_id()
    seed = search_mod.seed_translations(out, meta)
    key = (translate.query_sha("외부 SaaS 승인"), translate.model_id())
    assert seed[key] == {"keywords": "saas approval", "sentence": "saas approval"}
    (out / tr["file"]).write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="번역 장부"):
        search_mod.seed_translations(out, meta)


def test_make_search_stops_when_translation_fails(tmp_path, monkeypatch, eval_env):
    """비교 입구는 번역이 실패하면 dense_ko로 내려가지 않고 멈춘다. 서비스 search()는 내려간다(Spec EC-02)."""
    write_index(tmp_path, ROWS, monkeypatch, translations=False)
    monkeypatch.setattr(translate, "translate", lambda q, kind, store: translate.Result(None, "timeout"))
    q = SearchQuery(query="외부 SaaS 승인", k=1)
    for mode in ("hybrid_ko_kw", "dense_en"):
        with pytest.raises(RuntimeError, match="번역 실패"):
            search_mod.make_search("arctic-l-v2", mode)(q)
    with pytest.raises(RuntimeError, match="번역 실패"):
        search_mod.make_search("none", "bm25_kw")(q)
    assert search_mod.make_search("arctic-l-v2", "dense_ko")(q)      # 번역을 쓰지 않는 방식은 그대로 돈다


def test_make_search_without_seed_calls_translator_once_per_question(tmp_path, monkeypatch, eval_env):
    """장부에 없는 질문은 서비스와 같이 llm.py로 번역해 장부에 적고, 다음 조합은 그 장부를 쓴다."""
    write_index(tmp_path, ROWS, monkeypatch, translations=False)
    calls = []

    def fake_call(query, kind):
        calls.append(kind)
        return KO2EN[query]
    real = translate.translate
    monkeypatch.setattr(translate, "translate", lambda q, kind, store: real(q, kind, store, call=fake_call))
    q = SearchQuery(query="외부 SaaS 승인", k=3)
    search_mod.make_search("arctic-l-v2", "hybrid_ko_kw")(q)
    search_mod.make_search("none", "bm25_kw")(q)
    assert calls == ["keywords"] and last_search_trace().translation_source == "stored"



# ---------- 배포: 이미지의 모델 판 · 색인 받기 · 시작 때 검색 준비 (Spec 파일 표, 열린 항목 6) ----------

import hashlib  # noqa: E402
import re as _re  # noqa: E402
import tarfile  # noqa: E402
from pathlib import Path  # noqa: E402

from backend.rag.retrieve import load_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_bakes_default_models_at_pinned_revisions():
    """비교용 로컬 모델은 서비스 이미지에 넣지 않는다(모델 이름 빌드 인자 기본값이 비어 있음). --build-arg로 이름을 주면 받을
    판 = 명부의 고정 판. 다르면 오프라인(HF_HUB_OFFLINE=1)에서 판 폴더를 못 찾아 검색이 안 뜬다."""
    args = dict(_re.findall(r"^ARG (SEARCH_\w+)=(\S*)$", (ROOT / "Dockerfile").read_text(encoding="utf-8"), _re.M))
    # 기본은 API 임베딩(voyage-4)·리랭커 없음이라 내려받을 것이 없다 → 로컬 모델은 비교할 때만 --build-arg로
    assert embed.EMBEDDERS[embed.DEFAULT_MODEL].api and rerank.DEFAULT_MODEL == rerank.NONE
    assert args["SEARCH_EMBED_MODEL"] == "" and args["SEARCH_RERANK_MODEL"] == ""
    e, r = embed.EMBEDDERS[embed.LOCAL_MODEL], rerank.RERANKERS[rerank.BAKED_MODEL]
    assert args["SEARCH_EMBED_REVISION"] == e.revision and args["SEARCH_RERANK_REVISION"] == r.revision


def _tarball(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "meta.json").write_text("{}", encoding="utf-8")
    (src / "chunks.jsonl").write_text("", encoding="utf-8")
    tgz = tmp_path / "index.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        for f in src.iterdir():
            t.add(f, arcname=f.name)
    return tgz, hashlib.sha256(tgz.read_bytes()).hexdigest()


@pytest.fixture
def no_index_env(monkeypatch):
    for k in ("INDEX_URL", "INDEX_SHA256", "INDEX_REQUIRED"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_ensure_index_skips_without_index_or_url(tmp_path, no_index_env):
    """색인도 주소도 없으면 건너뛴다(팀원 PC·CI의 compose가 지금처럼 뜬다). 배포용 INDEX_REQUIRED=1이면 멈춘다."""
    assert load_snapshot.ensure_index(tmp_path / "index", log=lambda *_: None) is False
    no_index_env.setenv("INDEX_REQUIRED", "1")
    with pytest.raises(SystemExit):
        load_snapshot.ensure_index(tmp_path / "index", log=lambda *_: None)


def test_ensure_index_downloads_only_with_matching_sha256(tmp_path, no_index_env):
    tgz, digest = _tarball(tmp_path)
    no_index_env.setenv("INDEX_URL", tgz.as_uri())
    with pytest.raises(SystemExit, match="INDEX_SHA256"):              # 대조값 없이 받지 않는다
        load_snapshot.ensure_index(tmp_path / "a", log=lambda *_: None)
    no_index_env.setenv("INDEX_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="다르다"):                     # 다르면 풀지 않는다
        load_snapshot.ensure_index(tmp_path / "b", log=lambda *_: None)
    assert not (tmp_path / "b" / "meta.json").exists()
    no_index_env.setenv("INDEX_SHA256", digest)
    assert load_snapshot.ensure_index(tmp_path / "c", log=lambda *_: None) is True
    assert (tmp_path / "c" / "meta.json").is_file()


def test_ensure_index_keeps_existing_index(tmp_path, no_index_env):
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    no_index_env.setenv("INDEX_URL", "http://127.0.0.1:9/never-called")
    assert load_snapshot.ensure_index(tmp_path, log=lambda *_: None) is True


def test_search_warmup_is_off_by_default_and_failure_does_not_stop_server(monkeypatch):
    pytest.importorskip("fastapi")
    from backend import main
    monkeypatch.delenv("SEARCH_WARMUP", raising=False)
    assert main.search_warmup_mode(default_on=False) == "off"       # 기본값이 꺼진 곳(데모·DB 없음)은 건너뛴다. 운영 기본값은 tests/test_startup_warmup.py
    monkeypatch.setenv("SEARCH_WARMUP", "background")
    assert main.search_warmup_mode(default_on=False) == "background"

    def broken():
        raise RuntimeError("색인이 준비되지 않았다")
    monkeypatch.setattr(search_mod, "warmup", broken)
    t = main.start_search_warmup()
    t.join(5)
    assert not t.is_alive()                     # 예외가 스레드 밖으로 나가 서버를 멈추지 않는다


def test_warmup_failure_closes_the_pool_it_opened(monkeypatch):
    """색인이 없어 warmup이 실패하면 방금 연 DB 풀을 닫는다. 안 닫으면 search()가 부를 때마다 풀이 하나씩 쌓인다."""
    class FakePgStore:
        made = []

        def __init__(self):
            self.closed = 0
            FakePgStore.made.append(self)

        def meta(self):
            return None                         # index_meta 없음 = 적재 전

        def close(self):
            self.closed += 1

    monkeypatch.setattr(search_mod.PgStore, "from_env", classmethod(lambda cls: FakePgStore()))
    monkeypatch.setattr(search_mod, "_searcher", None)
    for _ in range(2):                          # search()마다 warmup을 다시 하므로 두 번
        with pytest.raises(RuntimeError, match="색인이 준비되지 않았다"):
            search_mod.warmup()
    assert [s.closed for s in FakePgStore.made] == [1, 1]
    assert search_mod._searcher is None

    class FakePool:
        closed = 0

        def close(self):
            FakePool.closed += 1
    pg = object.__new__(search_mod.PgStore)    # DB 없이: 진짜 PgStore.close가 풀을 닫는지
    pg.pool = FakePool()
    pg.close()
    assert FakePool.closed == 1


def test_env_example_lists_search_variables():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for k in ("EMBED_MODEL", "SEARCH_MODE", "RERANK_MODEL", "RERANK_TOP", "QUERY_TRANSLATE", "INDEX_URL", "INDEX_SHA256",
              "INDEX_REQUIRED"):
        assert _re.search(rf"^{k}=", text, _re.M), k


def test_refresh_swaps_chunk_file_keeps_vectors(tmp_path, monkeypatch, eval_env):
    """index.py refresh(I-011): 판 날짜만 바뀐 청크 파일로 갈아 끼우고 벡터는 그대로. 본문·줄 순서가 다르면 멈춘다."""
    out = write_index(tmp_path, ROWS, monkeypatch)
    before = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    before["chunks_fingerprint"] = index_mod.fingerprint(index_mod.load_rows(out / "chunks.jsonl"))
    (out / "meta.json").write_text(json.dumps(before), encoding="utf-8")
    vec_sha = index_mod.file_sha(out / "vectors" / "arctic-l-v2.npy")
    old = index_mod.load_rows(out / "chunks.jsonl")

    def write(rows):
        p = tmp_path / "new.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return ["refresh", "--chunks", str(p), "--out", str(out)]

    with pytest.raises(SystemExit, match="본문"):                       # 본문이 다르면 벡터가 틀린다
        index_mod.main(write([dict(old[0], text="other")] + old[1:]))
    with pytest.raises(SystemExit, match="순서"):                       # n번째 벡터 = n번째 줄
        index_mod.main(write(old[::-1]))
    new = [dict(r, version_date="2026-10-27") if r["chunk_id"] == "a2" else r for r in old]
    assert index_mod.main(write(new)) == 0
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert index_mod.load_rows(out / "chunks.jsonl") == new
    assert meta["chunks_sha256"] == index_mod.file_sha(out / "chunks.jsonl") != before["chunks_sha256"]  # 적재기가 다시 적재
    assert meta["chunks_refreshed"]["changed"] == {"version_date": 1}
    assert index_mod.file_sha(out / "vectors" / "arctic-l-v2.npy") == vec_sha == meta["embedders"][EMB]["sha256"]
