"""사전 등록 62.67 시험. 가짜 모델과 가짜 검색기만 쓰고 키·네트워크를 쓰지 않는다(0원).

- 프롬프트 캐시(`LLM_PROMPT_CACHE`): 정해진 단계의 시스템 프롬프트 블록에만 `cache_control`을 붙이고, 그래프가 넘긴 메시지(재생 키의 재료)는 그대로다.
- 비용 집계: 캐시 읽기 0.1배, 5분 보관 쓰기 1.25배로 세고 단계 행에 캐시 토큰을 남긴다. 캐시 칸이 없으면 지금과 같다.
- 기록: 근거 확인 호출별 기록(`grounding.candidates`), 판정 표 구성(`judge_votes`), 답 경로 기록의 `partial_filter`.
- 근거 확인 미리 부르기 일꾼 수와 등록 상한, 그보다 작지 않은 HTTP 일꾼 수와 연결 한도. 기록이 실패해도 답은 그대로 끝난다.
- 다시 쓴 답의 일부 답 안내 조건(`redraft_needs_note`).
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from qgraph_fakes import j

from backend.graph import build as B
from backend.graph import service_profile as SP
from backend.graph.build import build_graph
from backend.services import cost as C
from backend.services import demo_replay, llm as L, llm_trace, step_cost
from test_answer_fixes_graph import Q_REVIEW, REVIEW, REVIEW_TOO, cite, llm, run, searcher
from test_judge_vote import NO, OK, in_order

HAIKU = "claude-haiku-5-5"
PRICES = {"models": {HAIKU: {"input": 0.10, "output": 0.50}, "gpt-6-luna": {"input": 0.10, "output": 0.50}}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("LLM_PROMPT_CACHE", "LLM_EFFORT", "LLM_EFFORT_BY_TASK", "LLM_DEADLINE_S", "LLM_HEDGE_S", "LLM_TRACE_DETAIL", "LLM_FALLBACK_MODEL",
                 "GRAPH_SPECULATE_GROUND", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_ANSWER", "GRAPH_JUDGE_VOTE",
                 "GRAPH_JUDGE_QUOTE", "USE_SKILLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


# ---------- 프롬프트 캐시 표시 ----------
@pytest.mark.parametrize("task", L.PROMPT_CACHE_TASKS)
def test_cached_tasks_get_one_breakpoint_on_the_system_block(task):
    got = L.cache_system_prefix(f"[[task:{task}]]\n고정 지시문")
    assert got == [{"type": "text", "text": f"[[task:{task}]]\n고정 지시문", "cache_control": {"type": "ephemeral"}}]


@pytest.mark.parametrize("task", ["decompose", "decompose_gate", "rewrite", "supervisor", "single"])
def test_other_tasks_and_unmarked_prompts_are_left_alone(task):
    text = f"[[task:{task}]]\n짧은 지시문"
    assert L.cache_system_prefix(text) == text
    assert L.cache_system_prefix("표지 없는 프롬프트") == "표지 없는 프롬프트"


def test_block_list_marks_the_last_text_block_once():
    blocks = [{"type": "text", "text": "[[task:judge]]\n앞"}, {"type": "text", "text": "뒤"}]
    got = L.cache_system_prefix(blocks)
    assert "cache_control" not in got[0] and got[1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]                       # 받은 목록은 고치지 않는다
    marked = [{"type": "text", "text": "[[task:judge]]", "cache_control": {"type": "ephemeral"}}]
    assert L.cache_system_prefix(marked) is marked                 # 이미 표시가 있으면 그대로


def _anthropic(monkeypatch, cache: bool):
    if cache:
        monkeypatch.setenv("LLM_PROMPT_CACHE", "1")
    return L._provider_model("anthropic", HAIKU, "test-key-not-real")


def test_switch_off_sends_the_system_prompt_as_before(monkeypatch):
    model = _anthropic(monkeypatch, cache=False)
    msgs = [SystemMessage(content="[[task:judge]]\n고정 지시문"), HumanMessage(content="질문과 자료")]
    payload = model._get_request_payload(msgs)
    assert "cache_control" not in str(payload.get("system")) and "cache_control" not in str(payload["messages"])


def test_switch_on_marks_only_the_system_prompt_and_keeps_the_messages(monkeypatch):
    model = _anthropic(monkeypatch, cache=True)
    assert getattr(model, "prompt_cache", False) is True
    msgs = [SystemMessage(content="[[task:grounding]]\n고정 지시문"), HumanMessage(content="질문과 자료")]
    key_before = demo_replay.request_key(msgs)
    payload = model._get_request_payload(msgs)
    assert payload["system"] == [{"type": "text", "text": "[[task:grounding]]\n고정 지시문", "cache_control": {"type": "ephemeral"}}]
    assert "cache_control" not in str(payload["messages"])          # 질문·검색 자료가 든 사용자 메시지에는 붙이지 않는다
    assert "cache_control" not in payload                           # 요청 전체 자동 캐시(맨 위 칸)는 쓰지 않는다
    assert isinstance(msgs[0].content, str) and demo_replay.request_key(msgs) == key_before   # 재생·녹화 키의 재료(메시지)는 그대로
    gate = model._get_request_payload([SystemMessage(content="[[task:decompose_gate]]\n짧은 지시문"), HumanMessage(content="q")])
    assert "cache_control" not in str(gate.get("system"))            # 최소 캐시 길이보다 짧은 분해 단계는 뺀다


def test_switch_on_keeps_the_effort_rules(monkeypatch):
    monkeypatch.setenv("LLM_EFFORT", "none")
    monkeypatch.setenv("LLM_EFFORT_BY_TASK", "judge=low")
    model = _anthropic(monkeypatch, cache=True)
    judge = model._get_request_payload([SystemMessage(content="[[task:judge]]\n지시"), HumanMessage(content="q")])
    ground = model._get_request_payload([SystemMessage(content="[[task:grounding]]\n지시"), HumanMessage(content="q")])
    assert judge["system"][0]["cache_control"] == {"type": "ephemeral"} and ground["thinking"] == {"type": "disabled"}
    assert ground["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_service_profile_turns_the_cache_on_and_off_is_respected():
    env: dict = {}
    SP.apply_service_profile(env)
    assert env["LLM_PROMPT_CACHE"] == "1"
    given = {"LLM_PROMPT_CACHE": "off"}
    SP.apply_service_profile(given)
    assert given["LLM_PROMPT_CACHE"] == ""                           # 운영에서 `off`를 주면 끈다


# ---------- 비용 집계 ----------
def _result(input_tokens: int, output_tokens: int, details: dict | None = None, model: str = HAIKU) -> LLMResult:
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}
    if details is not None:
        usage["input_token_details"] = details
    msg = AIMessage(content="{}", usage_metadata=usage, response_metadata={"model_name": model})
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def _tracked(tracker: C.CostTracker, result: LLMResult, system: str = "[[task:judge]]\n지시") -> None:
    from uuid import uuid4

    run_id = uuid4()
    tracker.on_chat_model_start({}, [[SystemMessage(content=system), HumanMessage(content="q")]], run_id=run_id, metadata={"langgraph_node": "judge"})
    tracker.on_llm_end(result, run_id=run_id)


# langchain-anthropic 1.7.7: input_tokens = 캐시 밖 입력 + 캐시 읽기 + 캐시 쓰기. 보관 시간별 값이 있으면 cache_creation은 0이다
CACHED = {"cache_read": 6000, "cache_creation": 0, "ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 0}


def test_cache_tokens_are_priced_by_the_cache_rates():
    want = (2000 + 6000 * 0.1 + 2000 * 1.25) * 0.10 / 1e6 + 100 * 0.50 / 1e6
    assert C.cost_usd(HAIKU, 10_000, 100, PRICES, C.cache_tokens({"input_token_details": CACHED})) == pytest.approx(want)
    assert C.cache_tokens({"input_token_details": CACHED}) == (6000, 2000, 0)
    assert C.cache_tokens({"input_token_details": {"cache_read": 10, "cache_creation": 30}}) == (10, 30, 0)   # 보관 시간별 값이 없으면 5분 보관 쓰기
    assert C.cache_tokens({"input_token_details": {"cache_read": 0, "cache_creation": 0, "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}) == (0, 0, 0)
    assert C.cost_usd(HAIKU, 10_000, 100, PRICES, (0, 0, 3000)) == pytest.approx((7000 + 3000 * 2.0) * 0.1 / 1e6 + 100 * 0.5 / 1e6)


def test_without_cache_details_the_cost_is_unchanged():
    plain = 10_000 * 0.10 / 1e6 + 100 * 0.50 / 1e6
    assert C.cost_usd(HAIKU, 10_000, 100, PRICES) == pytest.approx(plain)
    assert C.usage_cost(HAIKU, {"input_tokens": 10_000, "output_tokens": 100}, PRICES) == pytest.approx(plain)
    assert C.cost_usd("gpt-6-luna", 10_000, 100, PRICES, (6000, 0, 0)) == pytest.approx(plain)   # Claude가 아닌 모델은 지금처럼 센다


def test_tracker_totals_steps_and_cap_use_the_cache_rates():
    cached = C.CostTracker(0.0008, prices=PRICES, default_model=HAIKU)
    _tracked(cached, _result(10_000, 100, CACHED))
    assert cached.summary()["cost_usd"] == pytest.approx(0.00056)
    assert set(cached.summary()) == {"cost_usd", "input_tokens", "output_tokens", "calls", "cap_usd"}   # summary() 모양은 그대로
    row = cached.by_step()["judge/judge"]
    assert (row["cache_read_tokens"], row["cache_creation_tokens"], row["input_tokens"]) == (6000, 2000, 10_000)
    assert row["cost_usd"] == pytest.approx(cached.summary()["cost_usd"])
    cached._check()                                                    # 캐시 단가로 0.00056 < 상한 0.0008: 다음 호출이 막히지 않는다
    plain = C.CostTracker(0.0008, prices=PRICES, default_model=HAIKU)
    _tracked(plain, _result(10_000, 100))
    assert plain.summary()["cost_usd"] == pytest.approx(0.00105)
    assert plain.by_step()["judge/judge"]["cache_read_tokens"] == 0
    with pytest.raises(C.CostCapExceeded):
        plain._check()


def test_step_snapshot_keeps_the_cache_columns():
    meter = step_cost.StepMeter()
    meter.merge_steps({"search_translate/translate_keywords": {"calls": 1, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.00002, "llm_s": 0.4}})
    graph = {"judge/judge": {"calls": 1, "input_tokens": 10_000, "output_tokens": 100, "cost_usd": 0.00056, "llm_s": 1.0,
                             "cache_read_tokens": 6000, "cache_creation_tokens": 2000}}
    snap = meter.snapshot(graph)
    assert snap["cost_by_step"]["judge/judge"]["cache_read_tokens"] == 6000
    assert "cache_read_tokens" not in snap["cost_by_step"]["search_translate/translate_keywords"]   # 캐시 칸이 없는 행은 모양 그대로


def test_call_trace_cost_matches_the_tracker():
    usage = {"input_tokens": 10_000, "output_tokens": 100, "input_token_details": CACHED}
    llm_trace._prices = PRICES
    try:
        assert llm_trace._call_cost(HAIKU, usage, {}) == pytest.approx(0.00056)
    finally:
        llm_trace._prices = None


# ---------- 기록: 판정 표 구성 ----------
def test_vote_log_shapes():
    s, n = {"sufficient": True, "partial": False}, {"sufficient": False, "partial": False}
    two = B.vote_log([s, s], True, 0)
    assert two == {"votes": [{"sufficient": True, "partial": False}] * 2, "errors": 0, "early": True, "how": "two_agree"}
    assert B.vote_log([s, n, n], True, 0)["how"] == "majority" and B.vote_log([s, n, n], True, 0)["early"] is False
    split = B.vote_log([s, n, {"sufficient": False, "partial": True}], True, 0)
    assert split["how"] == "split"
    failed = B.vote_log([{}, s, s], True, 1)
    assert failed["votes"][0] == {"failed": True} and failed["errors"] == 1


def test_judge_votes_are_recorded_and_the_answer_is_unchanged(monkeypatch):
    fn, _ = searcher([("", [REVIEW])])
    base = run(build_graph(fn, llm=llm(judge=in_order(NO, OK, OK), answer=cite(REVIEW), grounding=j(reason="", grounded=True)), grounding_llm=True), Q_REVIEW)
    assert not base.get("judge_votes")                               # 다수결을 끄면 기록이 없다
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    fn, _ = searcher([("", [REVIEW])])
    out = run(build_graph(fn, llm=llm(judge=in_order(NO, OK, OK), answer=cite(REVIEW), grounding=j(reason="", grounded=True)), grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["citations"]] == [REVIEW.chunk_id]
    votes = out["judge_votes"]
    assert len(votes) == 1 and votes[0]["retries"] == 0 and votes[0]["how"] in ("majority", "two_agree")
    assert sum(1 for v in votes[0]["votes"] if v.get("sufficient")) == 2
    assert step_cost.path_meta(out)["path"]["judge_votes"] == votes


# ---------- 기록: 근거 확인 호출 ----------
def test_ground_candidates_record_the_used_call(monkeypatch):
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    m = llm(answer=cite(REVIEW))
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True), Q_REVIEW)
    rows = out["grounding"]["candidates"]
    used = [r for r in rows if r["used"]]
    assert len(used) == 1 and used[0]["ahead"] is True and used[0]["verdict"] == "grounded" and used[0]["kind"] == "answer" and used[0]["scope"] == "full"
    assert all("future" not in r and "key" not in r for r in rows)   # 기록에는 값만 남긴다
    assert step_cost.path_meta(out)["path"]["grounding"]["candidates"] == rows


def test_ground_candidates_without_speculation_record_the_direct_call():
    m = llm(answer=cite(REVIEW))
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["grounding"]["candidates"] == [{"kind": "chosen", "partial": False, "verdict": "grounded", "used": True, "ahead": False}]


def test_ground_candidates_do_not_change_the_answer(monkeypatch):
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=llm(answer=cite(REVIEW)), grounding_llm=True), Q_REVIEW)
    again = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=llm(answer=cite(REVIEW)), grounding_llm=True), Q_REVIEW)
    strip = lambda o: {k: v for k, v in o["grounding"].items() if k != "candidates"}  # noqa: E731
    assert out["answer"] == again["answer"] and strip(out) == strip(again)


def test_path_keeps_the_partial_filter_record():
    state = {"chunks": [{"chunk_id": "a" * 16}], "grounding": {"llm": "grounded", "partial_filter": {"result": "dropped", "sentences": 1, "chunks": ["b" * 16]}}}
    assert step_cost.path_meta(state)["path"]["grounding"]["partial_filter"] == {"result": "dropped", "sentences": 1, "chunks": ["b" * 16]}


# ---------- 미리 부르기 일꾼 수 ----------
def test_ground_ahead_pool_sizes():
    assert B.GROUND_AHEAD_WORKERS == 64 and B.GROUND_AHEAD_MAX_RUNS == 256


# ---------- 다시 쓴 답의 일부 답 안내 ----------
def test_redraft_note_follows_the_judge_partial_first():
    assert B.redraft_needs_note(True, False, [["a"]], ["a"]) is True
    assert B.redraft_needs_note(False, False, [], []) is False


def test_redraft_note_is_dropped_only_when_every_fact_is_cited():
    assert B.redraft_needs_note(False, True, [["a", "x"], ["b"]], ["a", "b"]) is False   # 사실마다 구절 청크를 인용했다
    assert B.redraft_needs_note(False, True, [["a"], ["b"]], ["a"]) is True              # 한 사실의 구절 청크가 인용에 없다
    assert B.redraft_needs_note(False, True, [["a"], []], ["a"]) is True                 # 구절이 없는 사실이 있다


def test_redraft_note_without_fact_rows_follows_the_model():
    assert B.redraft_needs_note(False, True, [], ["a"]) is True
    assert B.redraft_needs_note(False, True, None, ["a"]) is True


def test_quote_rows_cap_matches_the_answer_fixes_default():
    import inspect
    assert B.QUOTE_ROWS_MAX == inspect.signature(B.AF.quote_rows).parameters["limit"].default


def test_redraft_note_is_kept_when_the_fact_rows_may_be_cut():
    full = [[f"c{i}"] for i in range(B.QUOTE_ROWS_MAX)]               # 상한까지 찼다: 뒤 사실이 잘렸을 수 있다
    assert B.redraft_needs_note(False, True, full, [r[0] for r in full]) is True
    short = full[:-1]                                                  # 상한보다 짧으면 다 있는 목록이다
    assert B.redraft_needs_note(False, True, short, [r[0] for r in short]) is False


# ---------- HTTP 일꾼 수와 연결 한도 ----------
def test_http_workers_and_connections_cover_the_ground_ahead_pool(monkeypatch):
    assert L.LLM_HTTP_WORKERS >= 2 * B.GROUND_AHEAD_WORKERS            # hedge가 겹쳐도 미리 부르는 근거 확인이 줄을 서지 않는다
    monkeypatch.setenv("LLM_DEADLINE_S", "8")
    monkeypatch.setenv("LLM_HEDGE_S", "3.5")
    client = L._anthropic_http_client()
    try:
        transport = client._transport
        assert transport.pool._max_workers == L.LLM_HTTP_WORKERS
        assert transport.inner._pool._max_connections >= L.LLM_HTTP_WORKERS
    finally:
        client.close()
    import httpx
    plain = L.DeadlineTransport(httpx.HTTPTransport(limits=L._http_limits(httpx)), 8.0)
    assert plain.pool._max_workers == L.LLM_HTTP_WORKERS and plain.inner._pool._max_connections >= L.LLM_HTTP_WORKERS


# ---------- 기록 실패가 요청을 멈추지 않음 ----------
def test_candidate_rows_read_cancelled_failed_and_broken_futures():
    from concurrent.futures import Future

    cancelled, failed, done, waiting = Future(), Future(), Future(), Future()
    cancelled.cancel()
    failed.set_exception(RuntimeError("x"))
    done.set_result({"state": "grounded"})

    class Broken:
        def cancelled(self):
            raise RuntimeError("broken")

    rows = B.candidate_rows([{"kind": "answer", "key": "k", "future": f} for f in (cancelled, failed, done, waiting, Broken())])
    assert [r["verdict"] for r in rows] == ["cancelled", "error", "grounded", "pending", "unknown"]
    assert all("future" not in r and "key" not in r for r in rows)


def test_a_failing_ground_record_does_not_stop_the_answer(monkeypatch):
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    base = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=llm(answer=cite(REVIEW)), grounding_llm=True), Q_REVIEW)

    def boom(_rows):
        raise RuntimeError("record failed")

    monkeypatch.setattr(B, "candidate_rows", boom)
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=llm(answer=cite(REVIEW)), grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and out["answer"] == base["answer"] and "candidates" not in out["grounding"]


def test_a_failing_vote_record_does_not_stop_the_judgement(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")

    def boom(*_a, **_k):
        raise RuntimeError("record failed")

    monkeypatch.setattr(B, "vote_log", boom)
    fn, _ = searcher([("", [REVIEW])])
    out = run(build_graph(fn, llm=llm(judge=in_order(NO, OK, OK), answer=cite(REVIEW), grounding=j(reason="", grounded=True)), grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["citations"]] == [REVIEW.chunk_id] and not out.get("judge_votes")


# ---------- 단계 합치기와 단계별 보고의 캐시 칸 ----------
def test_merging_the_same_step_twice_adds_the_cache_columns_once_each():
    meter = step_cost.StepMeter()
    row = {"calls": 1, "input_tokens": 1000, "output_tokens": 10, "cost_usd": 0.0001, "llm_s": 0.5, "cache_read_tokens": 600, "cache_creation_tokens": 200}
    meter.merge_steps({"judge/judge": row})
    meter.merge_steps({"judge/judge": row})
    got = meter.steps["judge/judge"]
    assert got["cache_read_tokens"] == 1200 and got["cache_creation_tokens"] == 400 and got["input_tokens"] == 2000 and got["calls"] == 2


def test_stage_report_prices_cached_calls_like_the_tracker():
    from evals.agent import stage_report as SR

    call = {"step": "judge/judge", "model": HAIKU, "input_tokens": 10_000, "output_tokens": 100, "seconds": 1.0,
            "cache_read_tokens": 6000, "cache_creation_tokens": 2000}
    row = {"id": "q1", "latency_s": 2.0, "cost_usd": 0.0, "llm_trace": [call]}
    cached = sum(SR.row_stages(row, PRICES)["cost"].values())
    assert cached == pytest.approx(C.cost_usd(HAIKU, 10_000, 100, PRICES, cache=(6000, 2000, 0)))
    plain = {**row, "llm_trace": [{k: v for k, v in call.items() if not k.startswith("cache_")}]}
    assert sum(SR.row_stages(plain, PRICES)["cost"].values()) == pytest.approx(C.cost_usd(HAIKU, 10_000, 100, PRICES))