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


# ---------- K-24 남은 차이: 같은 요청을 동시에 보내는 두 답 후보 ----------
def test_candidate_lane_fixes_the_variant_whichever_call_arrives_first(tmp_path):
    """답 두 번 쓰기의 두 후보가 같은 요청을 보낸다. 자리(lane)를 주면 온 순서와 무관하게 첫 후보는 0번, 둘째 후보는 1번 변형부터 받는다."""
    _write(tmp_path, "k", ["a", "b"])
    store = dr.ReplayStore(tmp_path)
    assert store.pick_ranked("k", run="r1", lane=1) == (store._variants["k"][1], 1)   # 둘째 후보가 먼저 와도 1번
    assert store.pick_ranked("k", run="r1", lane=0)[0]["response"] == "a"
    assert store.pick_ranked("k", run="r2", lane=0)[0]["response"] == "a"             # 첫 후보가 먼저 와도 같다
    assert store.pick_ranked("k", run="r2", lane=1)[0]["response"] == "b"
    assert store.pick_ranked("k", run="r2", lane=1)[0]["response"] == "a"             # 같은 자리의 다음 호출은 그 자리 안에서 다음 변형
    assert [store.pick_ranked("k", run="r3")[0]["response"] for _ in range(2)] == ["a", "b"]   # 자리가 없으면 온 순서대로(예전과 같다)


def test_model_reads_the_lane_also_in_worker_threads(tmp_path, no_stagger):
    """후보는 추론 답과 빠른 답을 다시 스레드로 보낸다(`build.py` `timed_reply`). 문맥을 복사한 스레드의 호출도 그 후보의 자리로 센다. 자리 밖에서는 값이 남지 않는다."""
    import contextvars

    _write(tmp_path, dr.request_key(Q), ["a", "b"])
    model = dr.ReplayChatModel(store=dr.ReplayStore(tmp_path))

    def in_thread():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(contextvars.copy_context().run, lambda: model.invoke(Q).content).result()

    def one_run(_):
        second = dr.in_lane(1, in_thread)()   # 둘째 후보가 먼저 불러도
        first = dr.in_lane(0, in_thread)()
        return [first, second, dr._lane.get()]

    for run in ("run-1", "run-2"):
        assert RunnableLambda(one_run).invoke(0, {"metadata": {"replay_run": run}}) == ["a", "b", None]


def _two_candidate_graph(monkeypatch, model, together):
    from test_answer_fixes_graph import ESC, searcher

    from backend.graph.build import build_graph

    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_SPECULATE_FIRST",
                 "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    fn, _ = searcher([("", [ESC])])
    return build_graph(fn, llm=model, judge_answer=together)


def _scripted(lanes: list):
    from qgraph_fakes import j
    from test_answer_fixes_graph import ESC, cite, llm

    def answer(_user: str) -> str:
        lanes.append(dr._lane.get())
        return cite(ESC)

    quote = ESC.text.split("\n", 1)[1]
    judge = j(checks=[{"fact": "사실", "quote": quote}], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
    return llm(judge=judge, answer=answer)


class _ScriptedReplay(dr.ReplayChatModel):
    """재생 모델인 것만 같고(그래프의 `replay_demo()` 판정) 응답은 대본에서 낸다."""

    script: object = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.script.invoke(messages).content))])


@pytest.mark.parametrize("together", ["parallel_all", "off"])   # 판정과 같이 쓰는 답(`judge`), 판정 뒤에 쓰는 답(`write_answer`)
def test_graph_marks_the_two_answer_candidates_only_for_the_replay_model(monkeypatch, together):
    """그래프는 재생 모델일 때만 답 두 번 쓰기의 두 후보에 자리 0, 1을 붙인다. 실제 모델(여기서는 재생 모델이 아닌 가짜 모델)에는 붙이지 않는다."""
    from test_answer_fixes_graph import run

    lanes: list = []
    out = run(_two_candidate_graph(monkeypatch, _ScriptedReplay(script=_scripted(lanes)), together), "EOC가 응답하지 않으면 어떻게 하나요?")
    assert out["kind"] == "answer" and sorted(lanes) == [0, 1]

    plain: list = []
    out = run(_two_candidate_graph(monkeypatch, _scripted(plain), together), "EOC가 응답하지 않으면 어떻게 하나요?")
    assert out["kind"] == "answer" and plain == [None, None]
