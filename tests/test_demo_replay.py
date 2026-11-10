"""데모 재생·녹화: 같은 요청의 응답 변형 돌려 내기, 질문 임베딩 녹화·재생 (backend/services/demo_replay.py, backend/rag/retrieve/embed.py)."""
import json
import re
from pathlib import Path

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


def test_parallel_calls_with_the_same_key_finish_in_recorded_order(tmp_path, monkeypatch):
    """같은 키를 동시에 부르는 단계(판정 다수결)는 녹화 파일 순서가 끝난 순서다. 재생도 몇 번째 변형인지에 비례해 늦춰 그 순서로 끝나야 한다(스레드 경쟁에 맡기지 않는다)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from langchain_core.messages import HumanMessage

    (tmp_path / "recorded.jsonl").write_text("\n".join(_row(dr.request_key([HumanMessage(content="q")]), r) for r in ("a", "b", "c")) + "\n", encoding="utf-8")
    monkeypatch.setattr(dr, "STAGGER_S", 0.05)
    store = dr.ReplayStore(tmp_path)
    assert [store.pick_ranked(dr.request_key([HumanMessage(content="q")]))[1] for _ in range(4)] == [0, 1, 2, 0]
    model = dr.ReplayChatModel(store=store)
    for _ in range(5):
        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = {pool.submit(model.invoke, [HumanMessage(content="q")]): i for i in range(3)}
            order = [f.result().content for f in as_completed(futs)]
        assert order == ["a", "b", "c"]


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


README = Path(__file__).resolve().parents[1] / "README.md"
RECORDED = Path(__file__).resolve().parents[1] / "data" / "demo_replay"


def _readme_demo_questions() -> tuple[list[str], list[str]]:
    """README의 '키 없이 인용 답이 나오는 질문' 목록(글자 그대로)과 '키 없이 거절이 나오는 질문'의 따옴표 안 글."""
    lines = README.read_text(encoding="utf-8").splitlines()
    answers, on = [], False
    for ln in lines:
        if "키 없이 인용 답이 나오는 질문" in ln:
            on = True
        elif on and ln.startswith("  - "):
            answers.append(ln[4:].strip())
        elif on:
            on = False
    refusals = [q for ln in lines if ln.startswith("- 키 없이 거절이 나오는 질문") for q in re.findall(r'"([^"]+)"', ln)]
    return answers, refusals


def test_readme_demo_questions_are_recorded_as_written():
    """README가 키 없이 된다고 적은 질문은 적힌 글자 그대로 녹화돼 있어야 한다(괄호 설명을 붙이면 다른 질문이라 녹화에 없다)."""
    answers, refusals = _readme_demo_questions()
    assert len(answers) == 5 and len(refusals) == 2
    rows = [json.loads(x) for x in (RECORDED / "recorded.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    classified = [r["user_preview"] for r in rows if r["role"] == "classify"]
    for q in answers + refusals:
        assert "데모 구간" not in q, f"README 질문에 설명이 붙었다: {q}"
        assert any(f"질문: {q}\n" in p for p in classified), f"녹화에 이 글자 그대로의 질문이 없다: {q}"


def test_demo_defaults_range_search_off_only_without_a_key(monkeypatch):
    """녹화가 금액 구간 조회 전 것이라, 키 없는 데모만 SEARCH_RANGE_N을 비우면 0이다. 키가 있는 서비스는 3, 직접 준 값이 이긴다."""
    from backend.rag.retrieve.search import SearchConfig

    for name in ("LLM_API_KEY", "DEMO_MODE", "LLM_PROVIDER", "SEARCH_RANGE_N"):
        monkeypatch.delenv(name, raising=False)
    assert SearchConfig.from_env().range_n == 0                  # 키 없음 = 데모
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    assert SearchConfig.from_env().range_n == 3                  # 키가 있는 서비스
    monkeypatch.setenv("DEMO_MODE", "1")
    assert SearchConfig.from_env().range_n == 0                  # 키가 있어도 DEMO_MODE=1이면 데모
    monkeypatch.setenv("SEARCH_RANGE_N", "2")
    assert SearchConfig.from_env().range_n == 2                  # 직접 준 값은 그대로


def test_documents_are_never_replayed_or_recorded(client, monkeypatch):
    monkeypatch.setattr(embed.VoyageClient, "_embed_remote", lambda self, texts, role, key: _vec(2))
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    monkeypatch.setenv("VOYAGE_API_KEY", "dummy-voyage")
    monkeypatch.setenv("LLM_RECORD", "1")
    client.embed(["문서 조각"], "document")
    assert len(dr.get_store()) == 0
