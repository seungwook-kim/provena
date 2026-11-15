"""K-24: 키 없는 데모에서 같은 녹화 질문의 답이 실행마다 달라지던 문제.

재생 저장소는 같은 요청 키의 응답 변형을 "부를 때마다 차례로" 낸다. 차례를 프로세스 전체로 세면 한 실행이 그 키를 변형 수의 배수만큼 부르지 않을 때
다음 실행이 다른 변형부터 시작해 근거 확인 다수결이 바뀌었다. 이제 `run_config`가 데모 모드에서 실행마다 metadata `replay_run`을 붙이고,
재생은 그 실행 안에서만 0번부터 센다 (backend/services/demo_replay.py `pick_ranked`, backend/services/llm.py `run_config`).
"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from backend.services import demo_replay as dr
from backend.services import llm


def _row(key: str, response: str) -> str:
    return json.dumps({"key": key, "role": "grounding", "model": "m", "user_preview": "", "response": response,
                       "recorded_at": "2026-11-13T00:00:00+00:00"}, ensure_ascii=False)


def _write(tmp_path, key: str, responses: list[str]) -> None:
    (tmp_path / "recorded.jsonl").write_text("\n".join(_row(key, r) for r in responses) + "\n", encoding="utf-8")


Q = [HumanMessage(content="근거 확인 요청")]


@pytest.fixture
def no_stagger(monkeypatch):
    monkeypatch.setattr(dr, "STAGGER_S", 0.0)


def test_each_run_starts_from_the_first_variant(tmp_path):
    _write(tmp_path, "k", ["a", "b", "c"])
    store = dr.ReplayStore(tmp_path)
    assert [store.pick_ranked("k", run="r1")[0]["response"] for _ in range(2)] == ["a", "b"]
    assert [store.pick_ranked("k", run="r2")[0]["response"] for _ in range(2)] == ["a", "b"]
    assert store.pick_ranked("k", run="r1")[0]["response"] == "c"   # r1의 차례는 r2와 따로 이어진다
    assert store.pick_ranked("k", run="r2")[1] == 2                  # 몇 번째 변형인지(늦춤에 쓰는 값)도 실행 안에서 센다


def test_without_a_run_the_turn_is_process_wide_as_before(tmp_path):
    _write(tmp_path, "k", ["a", "b", "c"])
    store = dr.ReplayStore(tmp_path)
    assert [store.pick("k")["response"] for _ in range(4)] == ["a", "b", "c", "a"]


def test_old_runs_are_forgotten_beyond_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "MAX_RUNS", 2)
    _write(tmp_path, "k", ["a", "b"])
    store = dr.ReplayStore(tmp_path)
    for run in ("r1", "r2", "r3"):
        store.pick_ranked("k", run=run)
    assert list(store._run_turns) == ["r2", "r3"]
    assert store.pick_ranked("k", run="r1")[0]["response"] == "a"   # 잊은 실행은 처음부터 다시 센다


def test_model_reads_the_run_from_config_metadata_also_in_worker_threads(tmp_path, no_stagger):
    """그래프는 판정 다수결·답 두 번 쓰기를 스레드로 보낸다(`build.py` `in_background`: 문맥 복사). 그 스레드의 호출도 같은 실행으로 세야 한다."""
    import contextvars

    _write(tmp_path, dr.request_key(Q), ["a", "b", "c"])
    model = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))

    def one_run(_):
        first = model.invoke(Q).content
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(contextvars.copy_context().run, lambda: model.invoke(Q).content).result()
        return [first, second]

    graph = RunnableLambda(one_run)
    assert graph.invoke(0, {"metadata": {"replay_run": "run-1"}}) == ["a", "b"]
    assert graph.invoke(0, {"metadata": {"replay_run": "run-2"}}) == ["a", "b"]


def test_same_question_gives_the_same_grounding_vote_every_run(tmp_path, no_stagger):
    """조사에서 본 모양: 근거 확인 키에 변형 6개, 한 실행이 3표를 부른다. 예전에는 실행 1·3과 2·4의 다수결이 달랐다."""
    from backend.graph import answer_fixes as AF

    responses = [json.dumps({"grounded": g}) for g in (False, False, True, True, True, False)]
    _write(tmp_path, dr.request_key(Q), responses)
    model = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))

    def votes(cfg):
        return RunnableLambda(lambda _: [json.loads(model.invoke(Q).content) for _ in range(3)]).invoke(0, cfg)

    per_run = [AF.merge_votes("grounding", votes({"metadata": {"replay_run": f"run-{i}"}})) for i in range(4)]
    assert all(v == per_run[0] for v in per_run), per_run

    old_way = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))   # 실행 표지가 없으면(예전 동작) 실행마다 다수결이 바뀐다
    old = [AF.merge_votes("grounding", [json.loads(old_way.invoke(Q).content) for _ in range(3)]) for _ in range(4)]
    assert old[0] != old[1]


def test_run_config_adds_a_fresh_run_mark_only_in_demo_mode(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    a = llm.run_config("question", thread_id="t")["metadata"][dr.REPLAY_RUN_KEY]
    b = llm.run_config("question", thread_id="t")["metadata"][dr.REPLAY_RUN_KEY]
    assert a and b and a != b                                         # 같은 대화라도 질문(실행)마다 새 표지

    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("LLM_API_KEY", "test-not-a-real-key")
    assert dr.REPLAY_RUN_KEY not in llm.run_config("question", thread_id="t")["metadata"]   # 실제 모델 실행에는 붙이지 않는다
