"""LLM 호출별 시간 기록(`backend/services/llm_trace.py`). 기록은 동작을 바꾸지 않는다: 같은 가짜 응답에서 결과 상태와 호출 순서가 같고, 기록이 실패해도 답이 나온다.
실제 LLM, OpenRouter, DB를 부르지 않는다."""
from __future__ import annotations

import functools
import json
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fake_search import fake_search
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from qgraph_fakes import ScriptedLLM, answer_with_top_chunk, j, normal_llm

from backend.graph.build import build_graph
from backend.rag.retrieve import translate
from backend.rag.retrieve.search import Searcher, SearchTrace
from backend.services import claude_cli_model as C
from backend.services import llm as L
from backend.services import llm_trace as T
from backend.services.cost import CostTracker
from evals.agent.run_eval import compute_metrics, run_item

Q = "SEV2 인시던트의 최초 대응 시간은?"
SECRET_PROMPT = "프롬프트비밀문장"


class ChatScripted(BaseChatModel):
    """`ScriptedLLM`을 진짜 채팅 모델(콜백이 도는 모델)로 감싼다."""

    script: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.script.invoke(messages)
        msg.usage_metadata = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def scenario(name: str) -> ScriptedLLM:
    """답하는 길, 재검색 뒤 거절하는 길, 판정이 다시 쓰기를 부르는 길, 도메인 밖 거절 길."""
    decomp = j(split=True, sub_questions=["최초 대응은?", "담당은?"])
    grounded = j(reason="", grounded=True)
    if name == "answer":
        return normal_llm(decompose=decomp, grounding=grounded)
    if name == "refuse":
        return normal_llm(decompose=j(split=False, sub_questions=[]), judge=j(sufficient=False, reason="부족", clarify=None))
    if name == "redraft":
        bad = j(reason="없는 값", grounded=False, reason_code="unsupported", unsupported_sentences=["x"])
        return normal_llm(decompose=decomp, grounding=[bad, grounded],
                          answer=lambda u: answer_with_top_chunk(u).replace("근거에 따라 답합니다", "근거에 따라 답합니다" if "다시" not in u else "고쳐 답합니다"))
    if name == "out_of_domain":
        return normal_llm(classify=j(route="out_of_domain"))
    raise ValueError(name)


def run_graph(script: ScriptedLLM, *, thread: str = "t1") -> dict:
    g = build_graph(fake_search, llm=ChatScripted(script=script), grounding_llm=True, decompose=True)
    cfg = L.run_config("test", thread_id=thread)
    return g.invoke({"question": Q, "user_id": "u", "thread_id": thread, "as_of": "2025-06-01"}, cfg)


def stable(out: dict) -> dict:
    return {k: v for k, v in out.items() if k != "answer_id"}


@pytest.mark.parametrize("name", ["answer", "refuse", "redraft", "out_of_domain"])
def test_same_fake_responses_give_the_same_state_and_the_same_calls_with_and_without_the_trace(name):
    plain, traced = scenario(name), scenario(name)
    without = run_graph(plain)
    with T.capture() as calls:
        withit = run_graph(traced)
    assert stable(withit) == stable(without)
    assert traced.calls == plain.calls        # 호출 순서, 호출 수, 프롬프트 내용이 같다
    assert len(calls) == len(plain.calls)     # 호출마다 한 줄


def test_each_call_gets_a_step_with_seconds_and_no_prompt_or_answer_text():
    llm = scenario("answer")
    with T.capture() as calls:
        out = run_graph(llm)
    assert out["kind"] == "answer"
    assert [c["step"] for c in calls] == ["classify/classify", "rewrite/rewrite", "search/decompose", "judge/judge", "write_answer/answer", "ground/grounding"]
    for c in calls:
        assert c["ok"] is True and c["error"] is None and c["seconds"] >= 0 and c["start_s"] >= 0 and c["input_tokens"] == 10
        assert c["model_type"] == "scripted" and c["retries"] is None and c["cli_duration_ms"] is None
    assert [c["seq"] for c in calls] == list(range(1, 7)) and all(c["json_ok"] is True for c in calls)
    text = json.dumps(calls, ensure_ascii=False)
    assert Q not in text and "chunk_id" not in text and "citations" not in text and "근거에 따라" not in text


def test_redraft_and_rejudge_show_as_their_own_steps():
    with T.capture() as calls:
        run_graph(scenario("redraft"))
    assert [c["step"] for c in calls][-3:] == ["ground/grounding", "ground/answer", "ground/grounding"]


def test_format_retry_is_a_second_line_and_the_first_says_the_json_was_broken():
    llm = normal_llm(decompose=j(split=False, sub_questions=[]), judge=["형식이 깨진 응답", j(sufficient=True, reason="", clarify=None)], grounding=j(reason="", grounded=True))
    with T.capture() as calls:
        run_graph(llm)
    judge = [c for c in calls if c["step"] == "judge/judge"]
    assert [c["json_ok"] for c in judge] == [False, True]


@pytest.mark.parametrize("broken", ["start", "end", "add", "handler"])
def test_a_broken_recorder_does_not_change_the_answer(monkeypatch, broken):
    def boom(*a, **k):
        raise RuntimeError("기록 실패")

    if broken == "start":
        monkeypatch.setattr(T, "_task_of", boom)
    elif broken == "end":
        monkeypatch.setattr(T, "_message_of", boom)
    elif broken == "add":
        monkeypatch.setattr(T.Collector, "add", boom)
    else:
        monkeypatch.setattr(T, "LlmTraceHandler", boom)
    expected = stable(run_graph(scenario("answer")))
    with T.capture() as calls:
        out = run_graph(scenario("answer"))
    assert stable(out) == expected and out["kind"] == "answer"
    assert calls == []


def test_a_failing_llm_call_is_recorded_and_the_graph_fails_the_same_way():
    class Fails(ChatScripted):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if "[[task:classify]]" in messages[0].content:
                raise ConnectionError(SECRET_PROMPT)
            return super()._generate(messages, stop, run_manager, **kwargs)

    g = build_graph(fake_search, llm=Fails(script=scenario("answer")), grounding_llm=True, decompose=True)
    with pytest.raises(ConnectionError):
        with T.capture() as calls:
            g.invoke({"question": Q, "user_id": "u", "thread_id": "t", "as_of": "2025-06-01"}, L.run_config("test", thread_id="t"))
    assert calls[0]["ok"] is False and calls[0]["error"] == "ConnectionError" and calls[0]["step"] == "classify/classify"
    assert SECRET_PROMPT not in json.dumps(calls, ensure_ascii=False)


def test_without_capture_nothing_is_attached_and_bind_returns_the_same_function():
    cfg = L.run_config("test")
    assert not any(isinstance(cb, T.LlmTraceHandler) for cb in cfg["callbacks"]) and T.handler() is None
    fn = lambda: 1  # noqa: E731
    assert T.bind(fn) is fn
    with T.capture():
        assert any(isinstance(cb, T.LlmTraceHandler) for cb in L.run_config("test")["callbacks"])
    assert T.handler() is None


def test_concurrent_items_do_not_mix_their_records():
    n, barrier = 12, threading.Barrier(2)
    seen: dict[str, list] = {}

    def one(task: str) -> None:
        with T.capture() as calls:
            model = ChatScripted(script=ScriptedLLM({task: "ok"}))
            barrier.wait()
            for _ in range(n):
                model.invoke([SystemMessage(f"[[task:{task}]]"), HumanMessage("q")], config=L.run_config("test"))
                time.sleep(0.001)
        seen[task] = calls

    ts = [threading.Thread(target=one, args=(x,)) for x in ("alpha", "beta")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for task in ("alpha", "beta"):
        assert [c["task"] for c in seen[task]] == [task] * n and [c["seq"] for c in seen[task]] == list(range(1, n + 1))


def test_concurrent_graphs_do_not_mix_their_records():
    seen: dict[str, list] = {}

    def one(name: str) -> None:
        with T.capture() as calls:
            run_graph(scenario(name), thread=name)
        seen[name] = calls

    ts = [threading.Thread(target=one, args=(x,)) for x in ("answer", "out_of_domain")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert [c["task"] for c in seen["out_of_domain"]] == ["classify", "classify"]
    assert "answer" in [c["task"] for c in seen["answer"]]


# ---------- 번역: 스레드 두 겹을 건너간다 ----------

class Ledger:
    def __init__(self, hit: dict | None = None):
        self.hit, self.puts = hit, []

    def get_translation(self, query_sha256, model):
        return self.hit

    def put_translation(self, query_sha256, model, kind, text):
        self.puts.append(kind)


def _translate_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    monkeypatch.setattr(L, "get_chat_model", lambda *a, **k: ChatEcho())


class ChatEcho(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "echo"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="what is the first response time"))])


def test_translation_calls_across_threads_land_in_the_item_that_asked(monkeypatch):
    _translate_model(monkeypatch)
    ledger = Ledger()
    stub = SimpleNamespace(cfg=SimpleNamespace(translate=True), translator=lambda q, k: translate.translate(q, k, ledger))
    stub._translate_one = lambda q, k: Searcher._translate_one(stub, q, k)
    tr = SearchTrace("voyage-4", "none", "dense_en")
    with T.capture() as calls:
        got = Searcher._translate_all(stub, ["전체 질문", "하위 하나", "하위 둘"], "sentence", tr)
    assert got == ["what is the first response time"] * 3 and ledger.puts == ["sentence"] * 3
    assert [c["step"] for c in calls] == ["translate_sentence"] * 3 and all(c["ok"] for c in calls)
    assert all(c["json_ok"] is False for c in calls)       # 번역은 JSON이 아니다. 형식 재시도로 읽지 않는다


def test_stored_translation_makes_no_call_and_no_record(monkeypatch):
    _translate_model(monkeypatch)
    ledger = Ledger({"sentence": "stored english", "keywords": None})
    with T.capture() as calls:
        r = translate.translate("질문", "sentence", ledger)
    assert (r.text, r.source) == ("stored english", "stored") and calls == [] and ledger.puts == []


def test_translate_without_capture_still_works(monkeypatch):
    _translate_model(monkeypatch)
    r = translate.translate("질문", "sentence", Ledger())
    assert r.source == "llm"


# ---------- claude_cli: CLI 값과 재시도 ----------

def cli_output(**over) -> str:
    return json.dumps({"result": "응답 본문", "duration_ms": 4000, "duration_api_ms": 2500, "total_cost_usd": 0.001, "is_error": False,
                       "usage": {"input_tokens": 3, "cache_read_input_tokens": 7, "output_tokens": 5}, "modelUsage": {"claude-haiku-5-5": {}}, **over})


def fake_cli(monkeypatch, outputs: list[tuple[int, str]]) -> list:
    seen: list = []

    def run(cmd, **kw):
        seen.append(cmd)
        code, out = outputs[min(len(seen) - 1, len(outputs) - 1)]
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="")

    monkeypatch.setattr(C.subprocess, "run", run)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    return seen


def cli_model(**kw) -> C.ClaudeCliChatModel:
    return C.ClaudeCliChatModel(cli_path="claude-fake", retries=2, **kw)


MSGS = [SystemMessage("[[task:judge]]\n" + SECRET_PROMPT), HumanMessage(SECRET_PROMPT)]


def test_cli_values_split_process_time_from_model_time(monkeypatch):
    fake_cli(monkeypatch, [(0, cli_output())])
    with T.capture() as calls:
        msg = cli_model().invoke(MSGS, config=L.run_config("test"))
    assert msg.content == "응답 본문"
    c = calls[0]
    assert c["step"] == "judge" and c["model_type"] == "claude-cli" and c["model"] == "claude-haiku-5-5"
    assert (c["cli_duration_ms"], c["cli_duration_api_ms"], c["retries"]) == (4000, 2500, 0)
    assert c["cli_wall_s"] is not None and c["cli_queue_s"] is not None and (c["input_tokens"], c["output_tokens"]) == (10, 5)
    assert SECRET_PROMPT not in json.dumps(calls, ensure_ascii=False) and "응답 본문" not in json.dumps(calls, ensure_ascii=False)


def test_cli_retry_count_and_retry_behaviour_stay_as_they_were(monkeypatch):
    seen = fake_cli(monkeypatch, [(1, cli_output(is_error=True, result="일시 오류")), (0, cli_output())])
    with T.capture() as calls:
        msg = cli_model().invoke(MSGS, config=L.run_config("test"))
    assert msg.content == "응답 본문" and len(seen) == 2 and calls[0]["retries"] == 1 and calls[0]["ok"] is True


def test_cli_final_failure_records_retries_and_raises_the_same_error(monkeypatch):
    seen = fake_cli(monkeypatch, [(1, cli_output(is_error=True, result="오류"))])
    with T.capture() as calls:
        with pytest.raises(C.ClaudeCliError, match="오류"):
            cli_model().invoke(MSGS, config=L.run_config("test"))
    assert len(seen) == 3 and (calls[0]["ok"], calls[0]["error"], calls[0]["retries"]) == (False, "ClaudeCliError", 2)


def test_cost_summary_is_the_same_with_the_trace_on(monkeypatch):
    def spent() -> dict:
        cfg = L.run_config("test")
        cli_model().invoke(MSGS, config=cfg)
        return next(cb for cb in cfg["callbacks"] if isinstance(cb, CostTracker)).summary()

    fake_cli(monkeypatch, [(0, cli_output())])
    plain = spent()
    with T.capture():
        traced = spent()
    assert plain == traced and plain["calls"] == 1


# ---------- 운영 경로(OpenRouter): 가짜 HTTP로 같은 기록이 나오는지 ----------

def openrouter_reply(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "fake.invalid"
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "anthropic/claude-haiku-5.5",
                                     "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": j(sufficient=True)}}],
                                     "usage": {"prompt_tokens": 21, "completion_tokens": 4, "total_tokens": 25}})


def test_openrouter_path_gives_the_same_record_without_cli_values(monkeypatch):
    import langchain_openai

    client = httpx.Client(transport=httpx.MockTransport(openrouter_reply))
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", functools.partial(langchain_openai.ChatOpenAI, http_client=client))
    monkeypatch.setenv("LLM_BASE_URL", "http://fake.invalid/v1")
    model = L._provider_model("openrouter", "", "dummy-key")
    with T.capture() as calls:
        msg = model.invoke(MSGS, config=L.run_config("test"))
    assert json.loads(msg.content) == {"sufficient": True}
    c = calls[0]
    assert c["step"] == "judge" and c["ok"] is True and c["model"] == "anthropic/claude-haiku-5.5" and (c["input_tokens"], c["output_tokens"]) == (21, 4)
    assert c["retries"] is None and c["cli_duration_ms"] is None and c["cli_duration_api_ms"] is None and c["json_ok"] is True
    assert SECRET_PROMPT not in json.dumps(calls, ensure_ascii=False) and "dummy-key" not in json.dumps(calls, ensure_ascii=False)


def test_fallback_wrapper_is_not_counted_twice_inside_a_node_and_is_kept_outside():
    class Down(ChatScripted):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise ConnectionError("down")

    def wrapped() -> L.FallbackChatModel:
        return L.FallbackChatModel(primary=Down(script=None), fallback=ChatScripted(script=scenario("answer")), fallback_name="fb")

    with T.capture() as calls:
        out = build_graph(fake_search, llm=wrapped(), grounding_llm=True, decompose=False).invoke(
            {"question": Q, "user_id": "u", "thread_id": "t", "as_of": "2025-06-01"}, L.run_config("test", thread_id="t"))
    assert out["kind"] == "answer"
    classify = [c for c in calls if c["step"] == "classify/classify"]
    assert [(c["model_type"], c["ok"]) for c in classify] == [("scripted", False), ("scripted", True)]
    with T.capture() as direct:   # 번역처럼 config를 직접 넘기면 안쪽 호출이 콜백을 받지 않는다. 덮개 줄 하나는 남는다
        wrapped().invoke([SystemMessage("[[task:classify]]"), HumanMessage("q")], config=L.run_config("test"))
    assert [(c["model_type"], c["ok"]) for c in direct] == [("fallback", True)]


# ---------- 평가 행 ----------

ITEM = {"id": 1, "kind": "relevant", "input": Q, "as_of": "2025-06-01", "gold": []}


def test_run_item_adds_the_column_and_metrics_do_not_read_it():
    g = build_graph(fake_search, llm=ChatScripted(script=scenario("answer")), grounding_llm=True, decompose=True)
    row = run_item(g, ITEM, run_id="t")
    assert [c["step"] for c in row["llm_trace"]][0] == "classify/classify" and row["answered"] is True
    old = {k: v for k, v in row.items() if k != "llm_trace"}                 # 기존 결과 행에는 이 칸이 없다
    assert compute_metrics([old]) == compute_metrics([row])
    assert json.loads(json.dumps(row, ensure_ascii=False))["llm_trace"] == row["llm_trace"]


def test_run_item_still_turns_a_graph_error_into_an_error_row_with_the_column():
    class Bad:
        def invoke(self, *a, **k):
            raise ConnectionError("x")

    row = run_item(Bad(), ITEM, run_id="t")
    assert row["result"] == "error" and row["llm_trace"] == []


def test_recording_search_records_wall_seconds_without_changing_the_result():
    from backend.schemas.chunk import SearchQuery
    from evals.agent.exp_service_v1 import RecordingSearch

    class Fake:
        def search(self, q):
            return fake_search(q)

    r = RecordingSearch(Fake())
    q = SearchQuery(query="SEV2 최초 대응", as_of="2025-06-01")
    assert r(q) == fake_search(q) and r.calls[0]["wall_s"] >= 0
