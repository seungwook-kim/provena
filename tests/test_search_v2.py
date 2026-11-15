"""search() v2 시험 (조장 요청 1~4, docs/specs/search.md): 하위 질문 번갈아 합치기, 링크 확장 L1x2, 필터, voyage-4 실패 분류.
모델·DB·네트워크 없이 손으로 정한 벡터와 MemoryStore로 돈다. 측정과 같은 청크가 나오는지는 test_search_v2_repro.py."""
from __future__ import annotations

import io
import json
import socket
import urllib.error

import numpy as np
import pytest

from backend.rag.retrieve import embed, links, translate
from backend.rag.retrieve.embed import EmbedConfigError, EmbedNoKey, EmbedUnavailable
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, last_search_trace, roundrobin
from backend.schemas.chunk import DEFAULT_K, SearchQuery

# 벡터 칸: 0 = 전체 질문, 1 = 하위 질문 1, 2 = 하위 질문 2. 점수 = 내적이라 칸 값이 곧 점수다.
Q, S1, S2 = "saas approval", "approval steps", "budget owner"
QVEC = {Q: [1, 0, 0], S1: [0, 1, 0], S2: [0, 0, 1]}


def row(cid, v, *, page, links_to=(), org="finance", ver="v1", vf="2024-01-01", vt=None):
    return {"chunk_id": cid, "version_id": ver, "rule_seq": page, "org": org, "rule_title": f"page {page}", "article": None,
            "version_date": vf, "fetched_at": "2026-10-27", "kind": "article", "text": cid,
            "source_url": f"https://handbook.example/{page}", "text_sha256": None, "line_start": 1, "line_end": 1,
            "valid_from": vf, "valid_to": vt, "link_targets": list(links_to), "_v": v}


# a: 전체 질문·하위 질문 1과 가깝다(a1만 9쪽을 링크). c: 하위 질문 2와 가깝다. b: 9쪽(링크 대상).
# b1은 하위 질문 2와 더 가깝고, b2·b3은 전체 질문과 더 가깝다 → 어느 벡터로 고르느냐에 따라 뽑히는 집합이 다르다.
ROWS = [row(f"a{i}", [1 - 0.1 * i, 1 - 0.1 * i, 0], page=i, links_to=[9] if i == 1 else []) for i in range(1, 7)] + \
       [row(f"c{i}", [0, 0, 1 - 0.01 * i], page=10 + i) for i in range(1, 6)] + \
       [row("b1", [0.30, 0, 0.5], page=9), row("b2", [0.35, 0, 0], page=9), row("b3", [0.32, 0, 0.4], page=9)]


def make(rows=ROWS, calls=None, translator=None, **cfg):
    def embedder(texts):
        if calls is not None:
            calls.append(list(texts))
        return np.asarray([QVEC.get(t, [0.1, 0.1, 0.1]) for t in texts], dtype=np.float32)
    store = MemoryStore(rows, np.asarray([r["_v"] for r in rows], dtype=np.float32), "voyage-4")
    c = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", **cfg)
    return Searcher(c, store, embedder=embedder, reranker=None, check_meta=False,
                    translator=translator or (lambda q, kind: pytest.fail("영어 질문은 번역기를 부르지 않는다")))


def ids(chunks):
    return [c.chunk_id for c in chunks]


# ---------- 기본값 (요청 1·4) ----------

def test_defaults_are_confirmed_combo(monkeypatch):
    for k in ("EMBED_MODEL", "RERANK_MODEL", "SEARCH_MODE", "SEARCH_LINK_N"):
        monkeypatch.delenv(k, raising=False)
    cfg = SearchConfig.from_env()
    assert (cfg.embed_model, cfg.mode, cfg.rerank_model, cfg.link_n) == ("voyage-4", "dense_en", "none", 2)
    assert embed.spec().api and embed.spec().dim == 1024
    assert SearchQuery(query="x").k == DEFAULT_K == 5


def test_search_link_n_env(monkeypatch):
    monkeypatch.setenv("SEARCH_LINK_N", "0")
    assert SearchConfig.from_env().link_n == 0
    monkeypatch.setenv("SEARCH_LINK_N", "-1")
    with pytest.raises(ValueError):
        SearchConfig.from_env()


# ---------- 링크 확장 L1x2 (요청 2·3) ----------

def test_l1x2_replaces_last_two_with_linked_page_chunks_by_full_query():
    assert ids(make(link_n=0).search(SearchQuery(query=Q))) == ["a1", "a2", "a3", "a4", "a5"]
    got = make().search(SearchQuery(query=Q))
    assert ids(got) == ["a1", "a2", "a3", "b2", "b3"]          # 9쪽 청크 중 전체 질문과 가까운 순(b2 .35 > b3 .32 > b1 .30)
    tr = last_search_trace()
    assert (tr.n_link, tr.n_sub) == (2, 0)


def test_no_links_means_unchanged():
    rows = [dict(r, link_targets=[]) for r in ROWS]
    assert ids(make(rows).search(SearchQuery(query=Q))) == ["a1", "a2", "a3", "a4", "a5"]
    assert last_search_trace().n_link == 0


def test_linked_chunks_pass_as_of_filter():
    """링크로 가져온 청크도 as_of를 거친다: 옛 판 b0(9쪽에서 전체 질문과 가장 가까움)은 기준일이 없으면 안 나오고, 옛 날짜면 그것만 나온다."""
    rows = ROWS + [row("b0", [0.45, 0, 0], page=9, ver="old", vf="2024-01-01", vt="2025-06-01")]
    rows = [dict(r, valid_from="2025-06-01", version_date="2025-06-01") if r["rule_seq"] == 9 and r["version_id"] == "v1" else r
            for r in rows]
    s = make(rows)
    assert "b0" not in ids(s.search(SearchQuery(query=Q)))
    got = s.search(SearchQuery(query=Q, as_of="2025-01-01"))
    assert ids(got) == ["a1", "a2", "a3", "a4", "b0"]             # 그날 유효한 9쪽 청크는 b0 하나 → 한 자리만 바꿈
    assert {c.version_id for c in got if c.rule_seq == 9} == {"old"}


def test_linked_chunks_pass_org_filter():
    rows = [dict(r, org="security") if r["rule_seq"] == 9 else r for r in ROWS]
    got = make(rows).search(SearchQuery(query=Q, org="finance"))
    assert ids(got) == ["a1", "a2", "a3", "a4", "a5"] and {c.org for c in got} == {"finance"}


def test_k_not_above_link_n_skips_expansion():
    assert ids(make().search(SearchQuery(query=Q, k=2))) == ["a1", "a2"]


# ---------- 하위 질문 (요청 2) ----------

def test_split_question_keeps_two_places_per_sub_question_before_links():
    # 하위 질문 2개는 4자리를 지키고 남은 1자리만 링크로 바꾼다
    got = make().search(SearchQuery(query=Q, sub_queries=[S1, S2]))
    assert ids(got) == ["a1", "c1", "a2", "c2", "b2"] and last_search_trace().n_link == 1


def test_three_sub_questions_leave_no_place_for_links():
    # 하위 질문 3개는 5자리를 모두 번갈아 합친 결과로 채운다. 링크가 하위 질문의 2위를 밀어내지 않는다(평가셋 v1 6번)
    got = make().search(SearchQuery(query=Q, sub_queries=[S1, S2, "third part"]))
    assert last_search_trace().n_link == 0 and last_search_trace().n_sub == 3 and len(got) == 5


def test_sub_queries_roundrobin_then_l1x2_with_full_query_vector():
    calls = []
    got = make(calls=calls, link_keep_per_sub=0).search(SearchQuery(query=Q, sub_queries=[S1, S2]))
    # 하위 질문 1 → a1 a2 a3 …, 하위 질문 2 → c1 c2 … 를 번갈아 5개(a1 c1 a2 c2 a3) → 뒤 2자리를 전체 질문 벡터로 고른 9쪽 청크로
    assert ids(got) == ["a1", "c1", "a2", "b2", "b3"]             # 하위 질문 2 벡터로 골랐다면 b1·b3
    assert calls == [[Q, S1, S2]]                                  # 임베딩은 한 번에(API 요청 1번)
    assert last_search_trace().n_sub == 2


def test_split_question_wider_than_default_k_does_not_use_the_full_question_list():
    """원 질문 끝자리 규칙(62.38)은 사전 등록 62.72로 제거했다. 나뉜 질문을 k=8로 찾아도 k=5와 같은 규칙으로
    하위 질문만 번갈아 합치고 뒤 2자리를 링크 확장으로 채운다. 전체 질문 목록(0번)은 벡터 질의도 하지 않는다."""
    rows = ROWS + [row("z1", [2.0, 0, 0], page=30)]                   # 전체 질문에만 아주 가까운 청크: 하위 질문만으로는 못 찾는다
    s = make(rows)
    seen = []
    real = s.store.vector_top
    s.store.vector_top = lambda *a, **k: (seen.append(1), real(*a, **k))[1]
    got = s.search(SearchQuery(query=Q, sub_queries=[S1, S2], k=8))
    assert ids(got) == ["a1", "c1", "a2", "c2", "a3", "c3", "b2", "b3"] and len(seen) == 2
    assert last_search_trace().n_link == 2 and last_search_trace().n_sub == 2
    assert ids(make(rows, link_n=0).search(SearchQuery(query=Q, sub_queries=[S1, S2], k=8))) == ["a1", "c1", "a2", "c2", "a3", "c3", "a4", "c4"]


def test_split_question_at_default_k_does_not_use_the_full_question_list():
    """기본 자리 수(k=5)는 62.38 이전과 같다: 전체 질문 목록을 만들지 않고(벡터 질의도 하위 질문 수만큼만) 하위 질문만 번갈아 합친다."""
    rows = ROWS + [row("z1", [2.0, 0, 0], page=30)]
    s = make(rows)
    seen = []
    real = s.store.vector_top
    s.store.vector_top = lambda *a, **k: (seen.append(1), real(*a, **k))[1]
    assert ids(s.search(SearchQuery(query=Q, sub_queries=[S1, S2]))) == ["a1", "c1", "a2", "c2", "b2"]
    assert len(seen) == 2
    assert ids(make(rows).search(SearchQuery(query=Q))) == ["z1", "a1", "a2", "b2", "b3"]   # 나뉘지 않은 질문은 그대로(링크 확장 L1x2)


def test_full_question_equal_to_a_sub_question_has_no_full_list_and_is_searched_once():
    """사전 등록 62.41: 합동 검토 팀 검색은 SearchQuery(query=요청+보조어, sub_queries=[요청+보조어, 팀 보조어], k=10)다.
    전체 질문이 하위 질문 하나와 같은 문장이면 그 문장은 번역·임베딩·벡터 질의를 한 번만 하고, 원 질문 끝자리 없이 하위 질문 둘을 번갈아 합친다."""
    rows = ROWS + [row("z1", [2.0, 0, 0], page=30)]                   # 전체 질문에만 아주 가까운 청크: 끝자리가 있으면 들어올 청크
    calls = []
    s = make(rows, calls=calls)
    seen = []
    real = s.store.vector_top
    s.store.vector_top = lambda *a, **k: (seen.append(1), real(*a, **k))[1]
    got = s.search(SearchQuery(query=Q, sub_queries=[Q, S2], k=8))
    assert calls == [[Q, S2]] and len(seen) == 2                       # 같은 문장을 두 번 임베딩·질의하지 않는다
    assert last_search_trace().n_sub == 2                              # 기록의 하위 질문 수는 넘긴 그대로
    # 번갈아 합친 6자리(z1 c1 a1 c2 a2 c3) + 링크 2자리
    assert ids(got) == ["z1", "c1", "a1", "c2", "a2", "c3", "b2", "b3"]
    no_link = ids(make(rows, link_n=0).search(SearchQuery(query=Q, sub_queries=[Q, S2], k=8)))
    assert no_link == ["z1", "c1", "a1", "c2", "a2", "c3", "a3", "c4"]
    # 원 질문과 다른 하위 질문으로 나뉜 질문도 끝자리를 받지 않는다(원 질문 끝자리 규칙은 사전 등록 62.72로 제거)
    assert "z1" not in ids(make(rows, link_n=0).search(SearchQuery(query=Q, sub_queries=[S1, S2], k=8)))


@pytest.mark.parametrize("subs", [None, []])
def test_empty_sub_queries_means_no_split(subs):
    assert ids(make().search(SearchQuery(query=Q, sub_queries=subs))) == ["a1", "a2", "a3", "b2", "b3"]


@pytest.mark.parametrize("subs", [[S1], [S1, S2, Q, "x"], [S1, "  "], [S1, "x" * 1001]])
def test_bad_sub_queries_stop(subs):
    with pytest.raises(ValueError):
        make().search(SearchQuery(query=Q, sub_queries=subs))


def test_roundrobin_same_as_measurement():
    dec = pytest.importorskip("evals.retrieval.exp_decompose_v1")
    rng = np.random.default_rng(0)
    for _ in range(200):
        lists = [list(rng.choice(12, size=rng.integers(0, 8), replace=False)) for _ in range(rng.integers(1, 4))]
        if not any(lists):
            continue
        assert roundrobin(lists, 5) == dec.roundrobin(lists, 5)
    assert roundrobin([[1, 2, 3], [2, 4], [5]], 5) == [1, 2, 5, 4, 3]


def test_sub_queries_translated_in_parallel_and_fallback_when_one_fails():
    seen = []

    def tr(q, kind):
        seen.append((q, kind))
        return translate.Result(None if q == "하위2" else {"전체": Q, "하위1": S1}[q], "llm" if q != "하위2" else "invalid")
    s = make(translator=tr)
    s.search(SearchQuery(query="전체", sub_queries=["하위1", "하위2"]))
    t = last_search_trace()
    assert sorted(seen) == [("전체", "sentence"), ("하위1", "sentence"), ("하위2", "sentence")]
    assert (t.mode, t.fallback, t.fallback_reason) == ("dense_ko", "dense_ko", "invalid")


# ---------- 키 없음 (G2) ----------

def test_no_key_returns_empty_without_crash():
    def embedder(texts):
        raise EmbedNoKey("VOYAGE_API_KEY가 없다")
    s = make()
    s.embed = embedder
    assert s.search(SearchQuery(query=Q)) == []
    assert last_search_trace().fallback_reason == "no_key"


# ---------- 서비스 입구 warmup()·search() (리뷰: warmup에서 embed import 누락 → 첫 호출 NameError) ----------

def _pad(vecs, dim):
    """3칸 시험 벡터를 모델 차원으로 늘린다(나머지 0, 점수는 그대로)."""
    m = np.zeros((len(vecs), dim), dtype=np.float32)
    m[:, :3] = vecs
    return m


def _service(monkeypatch, model_name):
    """warmup()을 그대로 부른다. DB만 MemoryStore로 바꾸고 장부는 지금 설정과 같게 둔다."""
    import importlib
    search_mod = importlib.import_module("backend.rag.retrieve.search")  # 패키지의 search 이름은 함수라 모듈로 직접
    s = embed.spec(model_name)
    store = MemoryStore(ROWS, _pad([r["_v"] for r in ROWS], s.dim), s.name,
                        meta={"status": "ready", "embedder": s.name, "revision": embed.revision_for(s), "dim": s.dim})
    for var in ("SEARCH_MODE", "SEARCH_POOL", "RERANK_MODEL", "RERANK_TOP", "QUERY_TRANSLATE", "SEARCH_LINK_N"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EMBED_MODEL", s.name)
    monkeypatch.setattr(search_mod.PgStore, "from_env", staticmethod(lambda: store))
    monkeypatch.setattr(search_mod, "_searcher", None)
    return search_mod


def test_first_search_runs_warmup_with_api_model_and_skips_warmup_call(monkeypatch):
    search_mod = _service(monkeypatch, "voyage-4")
    calls = []

    def fake_voyage(self, texts, role):
        calls.append((list(texts), role))
        return _pad([QVEC.get(t, [0.1, 0.1, 0.1]) for t in texts], 1024)
    monkeypatch.setattr(embed.VoyageClient, "embed", fake_voyage)
    out = search_mod.search(SearchQuery(query=Q))          # 첫 호출 → warmup() → Searcher
    assert search_mod._searcher is not None
    assert len(out) == DEFAULT_K
    assert calls == [([Q], "query")]                       # warm-up 문장은 보내지 않는다(API는 부르면 돈)
    assert search_mod.warmup() is search_mod._searcher     # 두 번째는 만든 것을 그대로


def test_warmup_with_local_model_embeds_once(monkeypatch):
    search_mod = _service(monkeypatch, embed.LOCAL_MODEL)
    calls = []
    monkeypatch.setattr(embed, "load_model", lambda name=None, dev=None: object())
    monkeypatch.setattr(embed, "used_prefixes", lambda model, s: {"query": "", "document": "", "source": "test"})
    monkeypatch.setattr(embed, "encode_queries", lambda model, texts: calls.append(list(texts)) or np.zeros((len(texts), 3)))
    search_mod.warmup()
    assert calls == [["warm-up"]]                          # 내려받는 모델은 미리 한 번 돌려 둔다


# ---------- 링크 대상 (links.py) ----------

def test_link_targets_rule():
    url2seq = links.url_map([("https://h.example/a/", 1), ("https://h.example/b", 2), ("https://h.example/c", 3)])
    chunk = {"rule_seq": 1, "source_url": "https://h.example/a#L3", "element_ids": ["e1", "e2"]}
    el = {"e1": ["../b/#sec", "https://h.example/a", "https://internal.gitlab.com/x"], "e2": ["https://h.example/c/", "/zzz"]}
    assert links.targets(chunk, el, url2seq) == [2, 3]            # 자기 쪽·코퍼스 밖 제외, '#'·끝 '/' 무시, 정렬


# ---------- voyage-4 API (요청 1) ----------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client():
    return embed.load_model("voyage-4")


def test_voyage_request_and_normalized_output(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    sent = {}

    def urlopen(req, timeout):
        sent.update(body=json.loads(req.data), auth=req.get_header("Authorization"), timeout=timeout, url=req.full_url)
        vecs = [[3.0, 4.0] + [0.0] * 1022, [0.0, 2.0] + [0.0] * 1022]
        return _Resp(json.dumps({"data": [{"index": 1, "embedding": vecs[1]}, {"index": 0, "embedding": vecs[0]}]}).encode())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    out = embed.encode_queries(_client(), ["a", "b"])
    assert sent["body"] == {"input": ["a", "b"], "model": "voyage-4", "input_type": "query"}
    assert sent["auth"] == "Bearer test-key-123" and sent["timeout"] == embed.VOYAGE_TIMEOUT_S
    assert sent["url"] == embed.VOYAGE_URL
    assert np.allclose(out[0][:2], [0.6, 0.8]) and np.allclose(out[1][:2], [0, 1])


@pytest.mark.parametrize("exc", [urllib.error.URLError("dns"), socket.timeout("t"), TimeoutError(), ConnectionResetError(),
                                 urllib.error.HTTPError("u", 429, "rate", {}, None),
                                 urllib.error.HTTPError("u", 503, "down", {}, None)])
def test_voyage_transient_failures_are_unavailable(exc, monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")

    def urlopen(req, timeout):
        raise exc
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(EmbedUnavailable) as e:
        embed.encode_queries(_client(), ["a"])
    assert isinstance(e.value, ConnectionError) and "test-key-123" not in str(e.value)


@pytest.mark.parametrize("code", [400, 401, 403])
def test_voyage_config_errors_are_not_retryable(code, monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")

    def urlopen(req, timeout):
        raise urllib.error.HTTPError("u", code, "no", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(EmbedConfigError) as e:
        embed.encode_queries(_client(), ["a"])
    assert not isinstance(e.value, ConnectionError) and "test-key-123" not in str(e.value)


def test_voyage_no_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("키 없이 부르면 안 된다"))
    with pytest.raises(EmbedNoKey):
        embed.encode_queries(_client(), ["a"])


# ---------- MCP (요청 1·4) ----------

def _mcp_call(search_fn, args):
    pytest.importorskip("fastmcp")
    import asyncio

    from fastmcp import Client

    from extras.mcp_skill.mcp_server import server

    async def go():
        async with Client(server.build_server(search_fn=search_fn)) as c:
            return (await c.call_tool("search_handbook", args, raise_on_error=False)).structured_content
    return asyncio.run(go())


def test_mcp_voyage_unavailable_is_retryable():
    def fail(q):
        raise EmbedUnavailable("Voyage API 503")
    r = _mcp_call(fail, {"query": "q"})
    assert r["status"] == "unavailable" and r["retryable"] is True and "임베딩 API" in r["note"]


def test_mcp_voyage_config_error_is_not_retryable():
    def fail(q):
        raise EmbedConfigError("Voyage API 401")
    r = _mcp_call(fail, {"query": "q"})
    assert r["status"] == "error" and r["retryable"] is False


def test_mcp_default_k_is_shared_constant():
    got = []

    def fn(q):
        got.append(q)
        return []
    _mcp_call(fn, {"query": "q"})
    assert got[0].k == DEFAULT_K


# ---------- DB (로컬 pgvector, TEST_DATABASE_URL이 있을 때만) ----------

DB = __import__("os").environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")
def test_db_links_load_and_pg_search_equals_memory(tmp_path):
    """링크 적재(links.jsonl → chunks.link_targets) → PgStore 검색(L1x2·하위 질문·필터) == MemoryStore 검색."""
    import hashlib

    import psycopg
    from pgvector.psycopg import register_vector

    from backend.rag.retrieve import index, load_snapshot
    from backend.rag.retrieve.search import PgStore
    rows = ROWS + [row("b0", [0.45, 0, 0], page=9, ver="old", vf="2024-01-01", vt="2025-06-01")]
    rows = [dict(r, valid_from="2025-06-01", version_date="2025-06-01") if r["rule_seq"] == 9 and r["version_id"] == "v1" else r
            for r in rows]
    rows = [{**{k: v for k, v in r.items() if k not in ("_v", "link_targets", "valid_from", "valid_to")}, "seq": i}
            for i, r in enumerate(rows)]
    s = embed.EMBEDDERS["voyage-4"]
    raw = np.zeros((len(rows), s.dim), dtype=np.float32)
    src_rows = ROWS + [row("b0", [0.45, 0, 0], page=9)]
    for i, r in enumerate(src_rows):
        raw[i, :3], raw[i, 3] = r["_v"], 0.01 * i + 0.01               # 4번째 칸: 동점을 피하려고
    vecs = raw / np.linalg.norm(raw, axis=1, keepdims=True)
    src = tmp_path / "chunks.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    idx = tmp_path / "idx"
    index.write_snapshot(idx, src, rows, s, vecs, {"revision": s.revision, "prefixes": {}})
    targets = [[9] if r["chunk_id"] == "a1" else [] for r in rows]
    lf = idx / "links.jsonl"
    lf.write_text("".join(json.dumps({"chunk_id": r["chunk_id"], "version_id": r["version_id"], "targets": t}) + "\n"
                          for r, t in zip(rows, targets)), encoding="utf-8")
    meta = json.loads((idx / "meta.json").read_text(encoding="utf-8"))
    meta["links"] = {"file": "links.jsonl", "sha256": hashlib.sha256(lf.read_bytes()).hexdigest()}
    (idx / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    quiet = dict(batch=3, log=lambda *_: None)
    with psycopg.connect(DB, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS chunks, versions, docs, index_meta, query_translations CASCADE")
        conn.commit()
        register_vector(conn)
        first = load_snapshot.load(conn, idx, s.name, **quiet)
        assert first["links"] == 1 and load_snapshot.load(conn, idx, s.name, **quiet)["skipped"]
        # 링크를 아직 안 실은 DB(같은 스냅샷, ready)는 건너뛰지 않고 링크를 채운다
        conn.execute("UPDATE chunks SET link_targets = '{}'")
        conn.execute("UPDATE index_meta SET links_sha256 = NULL")
        conn.commit()
        assert not load_snapshot.load(conn, idx, s.name, **quiet)["skipped"]
        got = dict(((a, b), list(t)) for a, b, t in conn.execute("SELECT chunk_id, version_id, link_targets FROM chunks"))
        assert got == {(r["chunk_id"], r["version_id"]): t for r, t in zip(rows, targets)}
    valid = {(v["rule_seq"], v["version_id"]): v for v in load_snapshot.versions_of(rows)}
    mem_rows = [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
                 "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"], "link_targets": t}
                for r, t in zip(rows, targets)]
    qv = {t: np.pad(np.asarray(v, dtype=np.float32), (0, s.dim - 3)) for t, v in QVEC.items()}
    cfg = SearchConfig(embed_model=s.name, mode="dense_en", rerank_model="none")
    emb = lambda texts: np.stack([qv[t] for t in texts])  # noqa: E731
    pg = Searcher(cfg, PgStore(DB), embedder=emb, reranker=None, check_meta=False, translator=None)
    mem = Searcher(cfg, MemoryStore(mem_rows, vecs, s.name), embedder=emb, reranker=None, check_meta=False, translator=None)
    n_link = []
    for q in [SearchQuery(query=Q), SearchQuery(query=Q, sub_queries=[S1, S2]), SearchQuery(query=Q, as_of="2025-01-01"),
              SearchQuery(query=Q, org="finance"), SearchQuery(query=Q, as_of="2023-01-01")]:
        a = ids(pg.search(q))
        n_link.append(last_search_trace().n_link)
        b = ids(mem.search(q))
        assert a == b, (q, a, b)
    assert max(n_link) >= 1                                  # 링크 확장이 실제로 일어난 질의가 있다(빈 시험이 아님)


# ---------- 하위 질문 동시 검색과 DB 시간 ----------
def test_parallel_sub_questions_give_the_same_order(monkeypatch):
    query = SearchQuery(query=Q, sub_queries=[S1, S2])
    monkeypatch.delenv("SEARCH_PARALLEL_SUBS", raising=False)
    before = ids(make(link_keep_per_sub=0).search(query))
    monkeypatch.setenv("SEARCH_PARALLEL_SUBS", "1")
    assert ids(make(link_keep_per_sub=0).search(query)) == before


def test_parallel_sub_questions_run_at_the_same_time(monkeypatch):
    import threading

    monkeypatch.setenv("SEARCH_PARALLEL_SUBS", "1")
    s = make()
    both = threading.Barrier(2, timeout=5)
    real = s.store.vector_top

    def meet(*a, **k):
        both.wait()  # 순차면 두 번째가 오지 않아 시간이 다 되어 실패한다
        return real(*a, **k)

    s.store.vector_top = meet
    assert ids(s.search(SearchQuery(query=Q, sub_queries=[S1, S2])))


def test_db_time_is_only_noted_inside_a_search():
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")

    S._note_db(0.1, 0.2)  # 검색 밖이면 아무 일도 없다
    ms: dict = {}
    token = S._db_ms.set(ms)
    try:
        S._note_db(0.1, 0.2)
        S._note_db(0.1, 0.2)
    finally:
        S._db_ms.reset(token)
    assert ms == {"db_wait": 200.0, "db_query": 400.0}


def _reused_client(handler, monkeypatch):
    import httpx
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    monkeypatch.setenv("EMBED_KEEPALIVE", "1")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("연결 재사용이면 urllib을 쓰지 않는다"))
    c = _client()
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_voyage_reused_connection_sends_queries_one_by_one_in_order(monkeypatch):
    import httpx
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        v = {"a": [3.0, 4.0], "b": [0.0, 2.0], "c": [1.0, 0.0]}[body["input"][0]] + [0.0] * 1022
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": v}]})

    out = embed.encode_queries(_reused_client(handler, monkeypatch), ["a", "b", "c"])
    assert sorted(b["input"][0] for b in bodies) == ["a", "b", "c"] and all(len(b["input"]) == 1 and b["input_type"] == "query" for b in bodies)
    assert np.allclose(out[0][:2], [0.6, 0.8]) and np.allclose(out[1][:2], [0, 1]) and np.allclose(out[2][:2], [1, 0])


@pytest.mark.parametrize("code,exc", [(429, EmbedUnavailable), (503, EmbedUnavailable), (401, EmbedConfigError), (400, EmbedConfigError)])
def test_voyage_reused_connection_maps_errors_like_before(monkeypatch, code, exc):
    import httpx
    c = _reused_client(lambda req: httpx.Response(code), monkeypatch)
    with pytest.raises(exc) as e:
        embed.encode_queries(c, ["a"])
    assert "test-key-123" not in str(e.value)


def test_voyage_reused_connection_failure_is_unavailable(monkeypatch):
    import httpx

    def handler(req):
        raise httpx.ConnectError("끊김")

    with pytest.raises(EmbedUnavailable):
        embed.encode_queries(_reused_client(handler, monkeypatch), ["a", "b"])



# ---------- 분해 검색 개편 SEARCH_SUB_MERGE(기본 꺼짐, 조사 해법 Ammann 2025) ----------

def test_merge_by_score_one_place_per_sub_then_score():
    from backend.rag.retrieve.search import merge_by_score
    lists = [["q1", "q2"], ["a1", "a2", "a3"], ["c1", "c2"]]
    sc = {"q1": 0.9, "q2": 0.5, "a1": 0.8, "a2": 0.7, "a3": 0.2, "c1": 0.3, "c2": 0.1}
    assert merge_by_score(lists, sc, 5) == ["a1", "c1", "q1", "a2", "q2"]   # 하위 질문마다 한 자리, 나머지는 점수 순(전체 질문 후보 포함)
    assert merge_by_score([["x"], ["x", "y"], ["x", "z"]], {}, 5) == ["x", "z", "y"]  # 겹치면 다음 청크가 그 하위 질문의 자리다
    assert merge_by_score(lists, sc, 1) == ["a1"]


def test_sub_merge_off_is_unchanged(monkeypatch):
    monkeypatch.delenv("SEARCH_SUB_MERGE", raising=False)
    assert ids(make().search(SearchQuery(query=Q, sub_queries=[S1, S2]))) == ["a1", "c1", "a2", "c2", "b2"]


def test_sub_merge_adds_full_query_and_fills_by_score(monkeypatch):
    monkeypatch.setenv("SEARCH_SUB_MERGE", "1")
    calls = []
    got = make(calls=calls, link_n=0).search(SearchQuery(query=Q, sub_queries=[S1, S2]))
    # 하위 1의 a1, 하위 2의 c1을 먼저, 나머지 3자리는 점수 순: c2 .98, c3 .97, c4 .96이 a2 .8(하위 1과 전체 질문)보다 앞
    assert ids(got) == ["a1", "c1", "c2", "c3", "c4"]
    assert calls == [[Q, S1, S2]] and last_search_trace().n_sub == 2   # 임베딩 요청은 그대로 한 번, k는 5
    assert len(got) == 5

# ---------- (나) 형제 절 sibling_firsts(그래프에는 아직 잇지 않음, 오프라인 확인용) ----------

def test_sibling_firsts_picks_first_chunk_of_sibling_sections_by_score():
    from backend.rag.retrieve.search import sibling_firsts

    def r(cid, art, line, seq=1):
        return {"chunk_id": cid, "version_id": "v", "rule_seq": seq, "article": art, "line_start": line}
    ctx = [r("c1", "A > B", 10)]
    rows = [r("c1", "A > B", 10), r("s1", "A > C", 30), r("s1b", "A > C", 20), r("s2", "A > D", 40), r("deep", "A > C > E", 25),
            r("top", "A", 1), r("other", "A > C", 5, seq=2)]
    sc = {("s1", "v"): 0.2, ("s1b", "v"): 0.1, ("s2", "v"): 0.9}
    assert sibling_firsts(ctx, rows, sc, 2) == [("s2", "v"), ("s1b", "v")]   # 절마다 첫 청크(s1b), 같은 깊이만, 다른 페이지는 뺀다
    assert sibling_firsts(ctx, rows, sc, 1) == [("s2", "v")]
    assert sibling_firsts([r("t", "", 1)], rows, sc, 2) == []                 # 제목 경로 없는 문맥은 형제를 만들지 않는다