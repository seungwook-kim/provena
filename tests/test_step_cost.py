"""요청 한 건의 단계별 비용·Voyage 토큰·거절 단계 (backend/services/step_cost.py, `/chat` done 이벤트의 측정용 칸).

가짜 모델(사용량을 돌려주는 채팅 모델)과 가짜 Voyage 응답으로 돈다. 키·네트워크·LLM 호출 없음(0원).
- 단계별 합 = 요청 합계(`CostTracker.summary()`, done의 `usage`)
- Voyage 응답의 `usage.total_tokens`를 요청 단위로 합산하고, 호출이 없으면 0, 요청 밖이면 아무 일도 없다
- 거절·되묻기면 done에 `refuse_stage`, `refuse_reason`
- 기존 칸(`usage` 키 이름·모양)은 그대로
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any

import httpx
import numpy as np
import pytest
from api_test_support import Env, ask
from fake_search import fake_search
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from qgraph_fakes import answer_with_top_chunk, j, normal_llm

from backend.rag.retrieve import embed
from backend.rag.retrieve.embed import EmbedUnavailable
from backend.services import step_cost
from backend.services.cost import CostTracker

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2025-06-01"
TOKENS = {"classify": (200, 10), "rewrite": (300, 20), "judge": (1000, 100), "answer": (3000, 300)}   # 단계마다 다른 사용량(입력, 출력)


class UsageLLM(BaseChatModel):
    """`ScriptedLLM`의 답에 사용량(`usage_metadata`)을 붙이는 채팅 모델. LangChain 콜백(비용 집계)이 실제 모델처럼 돈다."""

    inner: Any

    @property
    def _llm_type(self) -> str:
        return "usage-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        task = re.search(r"\[\[task:(\w+)\]\]", messages[0].content).group(1)
        text = self.inner.invoke(messages).content
        i, o = TOKENS.get(task, (50, 5))
        msg = AIMessage(content=text, usage_metadata={"input_tokens": i, "output_tokens": o, "total_tokens": i + o},
                        response_metadata={"model_name": "claude-haiku-5-5"})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def count(self, task: str) -> int:
        return self.inner.count(task)


def usage_llm(**override) -> UsageLLM:
    return UsageLLM(inner=normal_llm(**override))


def price(i: int, o: int) -> float:
    return (i * 0.10 + o * 0.50) / 1_000_000   # llm_prices.json default(claude-haiku-5-5)


def done_of(ev) -> dict:
    assert ev[-1][0] == "done"
    return ev[-1][1]["data"]


# ---------------------------------------------------------------- 단계별 합 = 요청 합계

def test_cost_by_step_sums_to_the_request_total_and_usage_keys_stay():
    llm = UsageLLM(inner=normal_llm(answer="{}"))
    tracker = CostTracker(prices={"default": {"input": 0.10, "output": 0.50}})
    from langchain_core.messages import HumanMessage, SystemMessage

    for task, node in (("judge", "judge"), ("judge", "judge"), ("classify", "classify"), ("answer", "write_answer")):
        llm.invoke([SystemMessage(f"[[task:{task}]] 시스템"), HumanMessage("사용자 비밀 질문")],
                   config={"callbacks": [tracker], "metadata": {"langgraph_node": node}})
    steps, total = tracker.by_step(), tracker.summary()
    assert set(steps) == {"judge/judge", "classify/classify", "write_answer/answer"}
    assert steps["judge/judge"]["calls"] == 2 and steps["judge/judge"]["input_tokens"] == 2000 and steps["judge/judge"]["output_tokens"] == 200
    assert sum(s["calls"] for s in steps.values()) == total["calls"] == 4
    assert sum(s["input_tokens"] for s in steps.values()) == total["input_tokens"]
    assert sum(s["output_tokens"] for s in steps.values()) == total["output_tokens"]
    assert sum(s["cost_usd"] for s in steps.values()) == pytest.approx(total["cost_usd"], abs=1e-7)
    assert set(total) == {"cost_usd", "input_tokens", "output_tokens", "calls", "cap_usd"}      # summary() 모양은 그대로
    assert all(s["llm_s"] >= 0 for s in steps.values())
    assert "사용자 비밀 질문" not in json.dumps(steps, ensure_ascii=False) and "시스템" not in json.dumps(steps, ensure_ascii=False)   # 숫자만 남는다


def test_failed_call_leaves_no_open_step_and_cost_cap_still_blocks():
    from backend.services.cost import CostCapExceeded
    from langchain_core.messages import HumanMessage, SystemMessage

    tracker = CostTracker(cap_usd=0.0001, prices={"default": {"input": 100.0, "output": 100.0}})
    llm = UsageLLM(inner=normal_llm(answer="{}"))
    msgs = [SystemMessage("[[task:judge]]"), HumanMessage("q")]
    llm.invoke(msgs, config={"callbacks": [tracker], "metadata": {"langgraph_node": "judge"}})
    with pytest.raises(CostCapExceeded):
        llm.invoke(msgs, config={"callbacks": [tracker], "metadata": {"langgraph_node": "judge"}})
    assert tracker.summary()["calls"] == 1 and tracker._open == {}


def test_meter_merges_translation_steps_and_reports_totals():
    meter = step_cost.StepMeter()
    meter.merge_steps({"search_translate/translate_keywords": {"calls": 1, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.00002, "llm_s": 0.4}})
    meter.merge_steps({"search_translate/translate_keywords": {"calls": 1, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.00002, "llm_s": 0.5}})
    snap = meter.snapshot({"judge/judge": {"calls": 2, "input_tokens": 2000, "output_tokens": 200, "cost_usd": 0.0003, "llm_s": 1.2}})
    tr = snap["cost_by_step"]["search_translate/translate_keywords"]
    assert tr["calls"] == 2 and tr["input_tokens"] == 200 and tr["cost_usd"] == pytest.approx(0.00004) and tr["llm_s"] == pytest.approx(0.9)
    assert snap["cost_by_step_total_usd"] == pytest.approx(0.00034, abs=1e-8)
    assert snap["embed_tokens"] == 0 and snap["embed_calls"] == 0 and snap["embed_cost_usd"] == 0.0


# ---------------------------------------------------------------- Voyage 토큰

def vec(n: int = 1) -> list[list[float]]:
    return [[3.0, 4.0] + [0.0] * 1022 for _ in range(n)]


class _Resp:
    def __init__(self, body: dict) -> None:
        self._b = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def voyage_body(n: int, tokens: int | None) -> dict:
    body: dict = {"data": [{"index": i, "embedding": v} for i, v in enumerate(vec(n))]}
    if tokens is not None:
        body["usage"] = {"total_tokens": tokens}
    return body


def test_voyage_total_tokens_are_summed_per_request(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    monkeypatch.delenv("EMBED_KEEPALIVE", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _Resp(voyage_body(len(json.loads(req.data)["input"]), 11)))
    client = embed.load_model("voyage-4")
    meter, token = step_cost.begin()
    try:
        embed.encode_queries(client, ["a", "b"])
        embed.encode_queries(client, ["c"])
    finally:
        step_cost.end(token)
    snap = meter.snapshot()
    assert snap["embed_tokens"] == 22 and snap["embed_calls"] == 2
    assert snap["embed_cost_usd"] == pytest.approx(22 * 0.06 / 1_000_000)   # llm_prices.json embeddings.voyage-4 = 0.06 / 1M


def test_voyage_without_usage_or_without_a_call_is_zero_and_outside_a_request_is_a_no_op(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    monkeypatch.delenv("EMBED_KEEPALIVE", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _Resp(voyage_body(1, None)))
    client = embed.load_model("voyage-4")
    embed.encode_queries(client, ["a"])            # 요청 밖(워밍업 등): 오류도 기록도 없다
    assert step_cost.current() is None
    meter, token = step_cost.begin()
    try:
        embed.encode_queries(client, ["a"])        # usage 칸이 없는 응답: 호출은 세고 토큰은 0
        idle, idle_token = step_cost.begin()       # 캐시 적중처럼 호출이 없는 요청
        step_cost.end(idle_token)
    finally:
        step_cost.end(token)
    assert meter.snapshot()["embed_tokens"] == 0 and meter.snapshot()["embed_calls"] == 1
    assert idle.snapshot() == {"cost_by_step": {}, "cost_by_step_total_usd": 0.0, "embed_tokens": 0, "embed_calls": 0, "embed_cost_usd": 0.0}


def test_voyage_reused_connection_counts_tokens_from_worker_threads(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    monkeypatch.setenv("EMBED_KEEPALIVE", "1")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("연결 재사용이면 urllib을 쓰지 않는다"))
    client = embed.load_model("voyage-4")
    client._http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=voyage_body(1, 7))))
    meter, token = step_cost.begin()
    try:
        embed.encode_queries(client, ["a", "b", "c"])    # 질문 여러 개는 스레드 풀에서 하나씩 보낸다
    finally:
        step_cost.end(token)
    assert (meter.embed_tokens, meter.embed_calls) == (21, 3)


def test_voyage_failure_is_not_counted(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key-123")
    monkeypatch.setenv("EMBED_KEEPALIVE", "1")
    client = embed.load_model("voyage-4")
    client._http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    meter, token = step_cost.begin()
    try:
        with pytest.raises(EmbedUnavailable):
            embed.encode_queries(client, ["a"])
    finally:
        step_cost.end(token)
    assert meter.embed_calls == 0


# ---------------------------------------------------------------- /chat done 이벤트 (진짜 그래프 + 가짜 모델)

def counting_search(tokens: int):
    def search(q):
        step_cost.record_embed(tokens)       # 그래프 노드(다른 스레드)에서도 요청 집계에 남는지
        return fake_search(q)
    return search


def test_chat_done_carries_step_costs_that_add_up(monkeypatch):
    llm = usage_llm()
    with Env(monkeypatch, llm=llm, search=counting_search(13)) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "answer"
    assert set(done["usage"]) == {"input_tokens", "output_tokens", "cost_usd", "calls"}      # 기존 칸 그대로
    steps = done["cost_by_step"]
    assert {"classify/classify", "judge/judge", "write_answer/answer"} <= set(steps)
    assert steps["judge/judge"]["calls"] == llm.count("judge") and steps["judge/judge"]["input_tokens"] == 1000 * llm.count("judge")
    assert sum(s["calls"] for s in steps.values()) == done["usage"]["calls"]
    assert sum(s["input_tokens"] for s in steps.values()) == done["usage"]["input_tokens"]
    assert sum(s["output_tokens"] for s in steps.values()) == done["usage"]["output_tokens"]
    assert sum(s["cost_usd"] for s in steps.values()) == pytest.approx(done["usage"]["cost_usd"], abs=1e-7)
    assert done["cost_by_step_total_usd"] == pytest.approx(done["usage"]["cost_usd"], abs=1e-7)      # 번역이 없는 요청은 같다
    assert done["usage"]["cost_usd"] == pytest.approx(sum(price(*TOKENS[t]) * llm.count(t) for t in TOKENS), abs=1e-7)
    assert (done["embed_tokens"], done["embed_calls"]) == (13, 1)
    assert done["embed_cost_usd"] == pytest.approx(13 * 0.06 / 1_000_000)
    assert "refuse_stage" not in done and "refuse_reason" not in done


def test_chat_without_voyage_calls_reports_zero_embed(monkeypatch):
    with Env(monkeypatch, llm=usage_llm()) as env:      # fake_search는 Voyage를 부르지 않는다(캐시 적중과 같은 모양)
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert (done["embed_tokens"], done["embed_calls"], done["embed_cost_usd"]) == (0, 0, 0.0)


def test_requests_do_not_share_the_meter(monkeypatch):
    with Env(monkeypatch, llm=usage_llm(), search=counting_search(5)) as env:
        c = env.client(env.alice)
        results: list[dict] = []

        def one(tid: str) -> None:
            _, ev = ask(env.client(env.alice), Q, tid, as_of=AS_OF)
            results.append(done_of(ev))

        threads = [threading.Thread(target=one, args=(f"t{i}",)) for i in range(3)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        _, ev = ask(c, Q, "t9", as_of=AS_OF)
    assert [r["embed_tokens"] for r in results] == [5, 5, 5] and done_of(ev)["embed_tokens"] == 5


# ---------------------------------------------------------------- 거절 단계와 사유

def test_refusal_from_give_up_has_stage_and_reason(monkeypatch):
    with Env(monkeypatch, llm=usage_llm(judge=j(sufficient=False, reason="부족", clarify=None))) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "refuse" and done["code"] == "no_results"
    assert (done["refuse_stage"], done["refuse_reason"]) == ("give_up", "no_evidence")
    assert "cost_by_step" in done and "judge/judge" in done["cost_by_step"]


def test_clarify_has_stage_and_reason(monkeypatch):
    with Env(monkeypatch, llm=usage_llm(judge=j(sufficient=False, reason="부족", clarify="어느 조직의 규정인가요?"))) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "clarify" and (done["refuse_stage"], done["refuse_reason"]) == ("give_up", "clarify")


def test_out_of_domain_refusal(monkeypatch):
    with Env(monkeypatch, llm=usage_llm(classify=j(route="out_of_domain"))) as env:
        _, ev = ask(env.client(env.alice), "오늘 점심 뭐 먹지?", "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "refuse" and (done["refuse_stage"], done["refuse_reason"]) == ("out_of_domain", "out_of_domain")


def test_search_down_refusal(monkeypatch):
    def down(_q):
        raise EmbedUnavailable("Voyage API 503")

    with Env(monkeypatch, llm=usage_llm(), search=down) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "refuse" and (done["refuse_stage"], done["refuse_reason"]) == ("search", "unavailable")


def test_citation_check_refusal_comes_from_verify(monkeypatch):
    bad = j(answer="근거 없는 답 [deadbeefdeadbeef]", citations=[{"chunk_id": "deadbeefdeadbeef"}])
    with Env(monkeypatch, llm=usage_llm(answer=bad)) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert done["kind"] == "refuse" and (done["refuse_stage"], done["refuse_reason"]) == ("verify", "citation_check")


def test_index_not_ready_done_has_the_same_fields(monkeypatch):
    from types import SimpleNamespace

    from backend.rag.retrieve.search import Searcher

    def not_ready(_q):
        Searcher._check_meta(SimpleNamespace(store=SimpleNamespace(meta=lambda: None), cfg=None))

    with Env(monkeypatch, llm=usage_llm(), search=not_ready) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
    done = done_of(ev)
    assert set(done["usage"]) == {"input_tokens", "output_tokens", "cost_usd", "calls"}
    assert (done["refuse_stage"], done["refuse_reason"]) == ("search", "index_not_ready") and done["embed_tokens"] == 0 and "cost_by_step" in done


def test_refuse_meta_prefers_the_graph_reason():
    from backend.graph.build import REFUSE_REASON_BY_MESSAGE

    meta = step_cost.refuse_meta("ground", "refuse", {"refuse_reason": "unsupported", "answer": "x"}, REFUSE_REASON_BY_MESSAGE)
    assert meta == {"refuse_stage": "ground", "refuse_reason": "unsupported"}
    assert step_cost.refuse_meta("decision_answer", "refuse", {"decision_error": {"reason": "x"}}, {})["refuse_reason"] == "decision_error"


def test_trace_step_names_match_between_trace_and_tracker():
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.services import llm_trace

    assert llm_trace.step_of([[SystemMessage("[[task:judge]] x"), HumanMessage("y")]], {"langgraph_node": "judge"})[0] == "judge/judge"
    assert llm_trace.step_of([[SystemMessage("번역 지시"), HumanMessage("y")]], {"kind": "sentence", "graph": "search_translate"})[0] == "translate_sentence"
    assert llm_trace.step_of(None, {"graph": "question"})[0] == "question" and llm_trace.step_of(None, None)[0] == "unknown"


# ---------------------------------------------------------------- 금액 구간 측정기(deploy_range_answers)도 같은 칸을 저장

def test_range_answers_row_keeps_old_columns_and_adds_step_fields():
    from evals.retrieval import deploy_range_answers as dr

    def sse_body() -> bytes:
        done = {"type": "done", "thread_id": "t", "data": {"kind": "answer", "usage": {"cost_usd": 0.001, "input_tokens": 10, "output_tokens": 2, "calls": 3},
                                                            "cost_by_step": {"judge/judge": {"calls": 3, "input_tokens": 10, "output_tokens": 2, "cost_usd": 0.001, "llm_s": 0.1}},
                                                            "cost_by_step_total_usd": 0.001, "embed_tokens": 9, "embed_calls": 1, "embed_cost_usd": 5.4e-07}}
        tok = {"type": "token", "thread_id": "t", "data": {"text": "답"}}
        return "".join(f"event: {e['type']}\r\ndata: {json.dumps(e)}\r\n\r\n" for e in (tok, done)).encode()

    client = httpx.Client(base_url="http://x", transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sse_body(), headers={"content-type": "text/event-stream"})))
    r = dr.ask(client, {"input": "q", "as_of": None})
    assert r["status"] == "ok" and r["kind"] == "answer" and r["cost_usd"] == 0.001 and r["answer"] == "답" and r["citations"] == []
    assert r["llm_calls"] == 3 and r["cost_by_step"]["judge/judge"]["calls"] == 3 and r["embed_tokens"] == 9 and r["refuse_stage"] is None
