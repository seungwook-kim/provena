"""서비스 검색기 측정 실행기(`evals/agent/exp_service_v1.py`) 시험. 가짜 임베딩·번역만 쓰고 모델과 API를 부르지 않는다."""
from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from backend.schemas.chunk import Chunk, SearchQuery
from evals.agent import exp_service_v1 as S
from evals.retrieval import exp_decompose_v1 as D


class FakeSearcher:
    def __init__(self, fail=False):
        self.fail, self.seen = fail, []

    def search(self, q):
        self.seen.append(q)
        if self.fail:
            raise ConnectionError("down")
        return [Chunk(chunk_id=f"{i:016x}", org="a", rule_seq=1, rule_title="t", article=None, version_id="v", version_date="2026-01-01",
                      fetched_at="2026-10-31", kind="article", text="x", source_url="u") for i in range(2)]


def test_recording_search_keeps_the_service_result_and_records_each_call():
    fs = FakeSearcher()
    r = S.RecordingSearch(fs)
    out = r(SearchQuery(query="원 질문", sub_queries=["가", "나"]))
    assert [c.chunk_id for c in out] == [f"{i:016x}" for i in range(2)] and fs.seen[0].sub_queries == ["가", "나"]
    r(SearchQuery(query="english query", as_of="2026-10-27"))
    assert [c["kind"] for c in r.calls] == ["first", "requery"]
    assert r.calls[0]["sub_queries"] == ["가", "나"] and r.calls[1]["sub_queries"] is None and r.calls[1]["as_of"] == "2026-10-27"
    assert r.calls[0]["k_requested"] == 5 and r.calls[0]["returned"] == [f"{i:016x}" for i in range(2)]
    r.set_item({"id": 1})
    assert r.calls == []


def test_recording_search_stops_loudly_on_a_search_error():
    r = S.RecordingSearch(FakeSearcher(fail=True))
    with pytest.raises(ConnectionError):
        r(SearchQuery(query="q"))
    assert r.errors and "ConnectionError" in r.errors[0]


def test_run_cmd_uses_the_service_searcher_with_graph_decomposition_and_marks_the_service_path():
    src = inspect.getsource(S.run_cmd)
    assert "decompose=True" in src and "build_searcher()" in src and "SERVICE_PATH" in src and "MemoryStore" in src
    assert "MemoryStore" in S.SERVICE_PATH and "DB 왕복 없음" in S.SERVICE_PATH and "PgStore" in S.SERVICE_PATH
    assert "anthropic_api_key" in src and "unused" in src


def test_pg_path_passes_the_env_file_url_only_to_the_store_and_keeps_the_meta_check(monkeypatch, tmp_path):
    from backend.rag.retrieve import search as _  # noqa: F401
    import importlib

    search_mod = importlib.import_module("backend.rag.retrieve.search")
    seen = {}

    class FakeStore:
        def __init__(self, url):
            seen["url"] = url

        def generation(self):
            return 7

    class FakeSearcherClass:
        def __init__(self, cfg, store, **kw):
            seen["kw"], seen["cfg"] = kw, cfg

    (tmp_path / ".env").write_text('OTHER=1\nDATABASE_URL="postgresql://u@h/db"\n', encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(search_mod, "PgStore", FakeStore)
    monkeypatch.setattr(search_mod, "Searcher", FakeSearcherClass)
    _s, setup = S.build_pg_searcher(embedder=lambda t: t)
    assert seen["url"] == "postgresql://u@h/db" and "DATABASE_URL" not in __import__("os").environ
    assert "check_meta" not in seen["kw"] and seen["cfg"].embed_model == "voyage-4" and setup["generation"] == 7
    assert "PgStore" in S.SERVICE_PATH_PG and S.SERVICE_PATH_PG != S.SERVICE_PATH
    src = inspect.getsource(S.run_cmd)
    assert "build_pg_searcher()" in src and "SERVICE_PATH_PG" in src


def test_pg_path_stops_without_a_database_url(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", tmp_path)
    with pytest.raises(SystemExit):
        S.database_url_from_env_file()


def test_build_searcher_returns_five_chunks_from_the_local_files_without_api_or_db():
    """로컬 입력 파일이 있을 때만: 가짜 임베딩(문서 벡터 하나)과 번역으로 서비스 Searcher가 5개를 돌려주고 DB·API를 부르지 않는다."""
    need = [D.CHUNKS, D.IR, D.MANIFEST, D.CACHE / "voyage-4.npy", D.CACHE / "chunk_ids.json"]
    if any(not p.is_file() for p in need):
        pytest.skip("로컬 입력 파일 없음")
    from backend.rag.retrieve import translate

    docs = np.load(D.CACHE / "voyage-4.npy")
    s, setup = S.build_searcher(embedder=lambda texts: np.stack([docs[0]] * len(texts)), translator=lambda q, kind: translate.Result("english sentence", "stub"))
    out = s.search(SearchQuery(query="질문", as_of="2026-10-27"))
    assert len(out) == 5 and setup["rows"] == len(docs) and setup["config"]["link_n"] == 2 and setup["config"]["mode"] == "dense_en"
    rec = S.RecordingSearch(s)
    rec(SearchQuery(query="질문", sub_queries=["가", "나"], as_of="2026-10-27"))
    assert rec.calls[0]["trace"]["n_sub"] == 2 and rec.calls[0]["trace"]["mode"] == "dense_en" and len(rec.calls[0]["returned"]) == 5
    json.dumps(rec.calls, ensure_ascii=False)  # rows.jsonl에 쓸 수 있다
