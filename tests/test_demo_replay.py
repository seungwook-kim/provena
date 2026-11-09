"""데모 재생·녹화: 같은 요청의 응답 변형 돌려 내기, 질문 임베딩 녹화·재생 (backend/services/demo_replay.py, backend/rag/retrieve/embed.py)."""
import json

import numpy as np
import pytest

from backend.rag.retrieve import embed
from backend.services import demo_replay as dr


def _row(key: str, response: str) -> str:
    return json.dumps({"key": key, "role": "judge", "model": "m", "user_preview": "", "response": response, "recorded_at": "2026-11-09T00:00:00+00:00"}, ensure_ascii=False)


def test_variants_in_one_file_are_replayed_in_turn(tmp_path):
    (tmp_path / "recorded.jsonl").write_text("\n".join([_row("k", "a"), _row("k", "b"), _row("k", "c"), _row("z", "only")]) + "\n", encoding="utf-8")
    store = dr.ReplayStore(tmp_path)
    assert [store.pick("k")["response"] for _ in range(4)] == ["a", "b", "c", "a"]
    assert store.pick("z")["response"] == store.pick("z")["response"] == "only"
    assert store.get("k")["response"] == "c"       # get은 가장 나중 줄
    assert store.pick("none") is None
    assert len(store) == 2


def test_later_file_replaces_all_variants_of_earlier_file(tmp_path):
    (tmp_path / "a.jsonl").write_text(_row("k", "old1") + "\n" + _row("k", "old2") + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(_row("k", "new") + "\n", encoding="utf-8")
    store = dr.ReplayStore(tmp_path)
    assert [store.pick("k")["response"] for _ in range(3)] == ["new", "new", "new"]


def test_add_skips_a_response_already_recorded_for_the_key(tmp_path):
    store = dr.ReplayStore(tmp_path)
    assert store.add("k", "judge", "m", "p", "a") is True
    assert store.add("k", "judge", "m", "p", "b") is True
    assert store.add("k", "judge", "m", "p", "a") is False
    assert [store.pick("k")["response"] for _ in range(2)] == ["a", "b"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    for name in ("LLM_API_KEY", "VOYAGE_API_KEY", "DEMO_MODE", "LLM_RECORD", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(tmp_path))
    return embed.VoyageClient(embed.spec("voyage-4"))


def _vec(seed: int, dim: int = 1024) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=(1, dim)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_query_embedding_without_key_or_recording_is_no_key(client):
    with pytest.raises(embed.EmbedNoKey):
        client.embed(["아직 녹화하지 않은 질문"], "query")


def test_query_embedding_recorded_with_key_is_replayed_without_key(client, monkeypatch):
    want = _vec(1)
    monkeypatch.setattr(embed.VoyageClient, "_embed_remote", lambda self, texts, role, key: np.repeat(want, len(texts), axis=0))
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    monkeypatch.setenv("VOYAGE_API_KEY", "dummy-voyage")
    monkeypatch.setenv("LLM_RECORD", "1")
    assert np.allclose(client.embed(["질문 하나", "question two"], "query"), np.repeat(want, 2, axis=0))
    assert len(dr.get_store()) == 2
    # 키 없는 데모: 녹화한 질문(공백 차이는 무시)은 같은 벡터, 녹화에 없는 질문이 하나라도 섞이면 no_key
    for name in ("LLM_API_KEY", "VOYAGE_API_KEY", "LLM_RECORD"):
        monkeypatch.delenv(name)
    got = client.embed(["질문  하나", "question two"], "query")
    assert np.allclose(got, np.repeat(want, 2, axis=0), atol=1e-5)
    with pytest.raises(embed.EmbedNoKey):
        client.embed(["질문 하나", "녹화하지 않은 질문"], "query")


def test_documents_are_never_replayed_or_recorded(client, monkeypatch):
    monkeypatch.setattr(embed.VoyageClient, "_embed_remote", lambda self, texts, role, key: _vec(2))
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    monkeypatch.setenv("VOYAGE_API_KEY", "dummy-voyage")
    monkeypatch.setenv("LLM_RECORD", "1")
    client.embed(["문서 조각"], "document")
    assert len(dr.get_store()) == 0
