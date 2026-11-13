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


def _msgs(task: str):
    from langchain_core.messages import HumanMessage, SystemMessage

    return [SystemMessage(content=f"[[task:{task}]]\n규칙"), HumanMessage(content="기준일: 2026-11-11\n질문: q\n<<<자료>>>\nchunk_id=c1\n본문 문장입니다. 둘째.\n<<<끝>>>")]


def test_missing_reasoning_answer_fails_instead_of_faking_when_the_fast_answer_is_also_sent(tmp_path, monkeypatch):
    """추론 답(answer)과 빠른 답(answer_fast)을 같이 보내는 구성(GRAPH_ANSWER_WAIT_S)에서 추론 답 녹화가 없으면 가짜 발췌 답을 내지 않고 실패시킨다.
    가짜 답이 인용과 함께 오면 그래프가 그것을 추론 답으로 뽑아 녹화한 빠른 답을 이긴다(11/11 G2: README 질문 1번이 발췌형 답으로 나온 원인)."""
    model = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "4.0")
    with pytest.raises(dr.ReplayMiss):
        model.invoke(_msgs("answer"))
    assert model.invoke(_msgs("answer_fast")).content == dr.DEFAULT_FAKE_TEXT                                                           # 빠른 답은 기존대로(녹화 없으면 고정 문장)
    assert json.loads(model.invoke(_msgs("judge")).content)["sufficient"] is True                                                      # 다른 역할도 기존대로
    monkeypatch.delenv("GRAPH_ANSWER_WAIT_S")
    assert "발췌한 답" in model.invoke(_msgs("answer")).content                                                                           # 빠른 답을 같이 보내지 않는 구성은 기존대로


def test_recorded_reasoning_answer_is_still_replayed_when_the_fast_answer_is_also_sent(tmp_path, monkeypatch):
    store = dr.ReplayStore(tmp_path)
    msgs = _msgs("answer")
    store.add(dr.request_key(msgs), "answer", "m", "p", '{"answer":"녹화한 답 [1]","citations":[{"chunk_id":"c1"}]}')
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "4.0")
    assert "녹화한 답" in dr.ReplayChatModel(store=store).invoke(msgs).content


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
    assert len(answers) == 6 and len(refusals) == 3
    rows = [json.loads(x) for x in (RECORDED / "recorded.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    classified = [r["user_preview"] for r in rows if r["role"] == "classify"]
    for q in answers + refusals:
        assert "데모 구간" not in q, f"README 질문에 설명이 붙었다: {q}"
        assert any(f"질문: {q}\n" in p for p in classified), f"녹화에 이 글자 그대로의 질문이 없다: {q}"


def test_demo_and_service_share_the_range_search_default(monkeypatch):
    """키 없는 데모도 서비스와 같이 SEARCH_RANGE_N 기본 3이다(녹화를 금액 구간 조회를 켠 채 만든다). 직접 준 값이 이긴다."""
    from backend.rag.retrieve.search import SearchConfig

    for name in ("LLM_API_KEY", "DEMO_MODE", "LLM_PROVIDER", "SEARCH_RANGE_N"):
        monkeypatch.delenv(name, raising=False)
    assert SearchConfig.from_env().range_n == 3                  # 키 없음 = 데모
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    assert SearchConfig.from_env().range_n == 3                  # 키가 있는 서비스
    monkeypatch.setenv("DEMO_MODE", "1")
    assert SearchConfig.from_env().range_n == 3                  # 키가 있어도 DEMO_MODE=1이면 데모
    monkeypatch.setenv("SEARCH_RANGE_N", "2")
    assert SearchConfig.from_env().range_n == 2                  # 직접 준 값은 그대로


def test_documents_are_never_replayed_or_recorded(client, monkeypatch):
    monkeypatch.setattr(embed.VoyageClient, "_embed_remote", lambda self, texts, role, key: _vec(2))
    monkeypatch.setenv("LLM_API_KEY", "dummy-llm")
    monkeypatch.setenv("VOYAGE_API_KEY", "dummy-voyage")
    monkeypatch.setenv("LLM_RECORD", "1")
    client.embed(["문서 조각"], "document")
    assert len(dr.get_store()) == 0


def test_replay_adds_no_fixed_delay(tmp_path):
    """H-32 ③: 키 없는 데모의 재생은 고정 지연이 없다. 같은 요청의 n번째 변형만 n*STAGGER_S초 늦출 뿐이라 변형 3개와 녹화 밖 요청이 합쳐 0.5초 안에 끝나야 한다(기본 STAGGER_S 기준)."""
    import time

    from langchain_core.messages import HumanMessage

    key = dr.request_key([HumanMessage(content="q")])
    (tmp_path / "recorded.jsonl").write_text("\n".join(_row(key, r) for r in ("a", "b", "c")) + "\n", encoding="utf-8")
    model = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))
    started = time.perf_counter()
    assert [model.invoke([HumanMessage(content="q")]).content for _ in range(3)] == ["a", "b", "c"]
    model.invoke([HumanMessage(content="녹화에 없는 질문")])
    assert time.perf_counter() - started < 0.5
