"""단일 대 멀티 측정 진입 파일 시험 (`evals/agent/exp_multi_v2.py`). 가짜 모델과 가짜 검색기만 쓰고 실제 측정은 하지 않는다."""
from __future__ import annotations

import pytest
from fake_search import fake_search
from qgraph_fakes import j, normal_llm

import os

from evals.agent import exp_multi_v2 as M
from evals.agent.exp_service_v1 import RecordingSearch
from evals.agent.run_eval import verify_frozen
from evals.retrieval.gold import GoldRef

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
ITEMS = [
    {"id": 1, "kind": "relevant", "input": Q, "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=90002, label="런북")]},
    {"id": 2, "kind": "irrelevant", "irrelevant_type": "out_of_domain", "input": "연봉 협상 방법을 알려 주세요", "gold": []},
    {"id": 3, "kind": "relevant", "input": "SEV2 장애 최초 대응은 몇 분 이내인가요? 에스컬레이션은?", "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=90002, label="런북")]},
]


class FakeSearcher:
    def search(self, q):
        return fake_search(q)


def judge(user):
    return j(sufficient=False, reason="없음", clarify=None) if "연봉" in user else j(sufficient=True)


def make_arms(**llm_over):
    arms = []
    for name in M.ARMS:
        llm = M.CountingLLM(normal_llm(judge=judge, **llm_over))
        rec = RecordingSearch(FakeSearcher())
        arms.append(M.Arm(name, M.build_arm_graph(name, rec, llm, decompose=False, grounding_llm=False), rec, llm))
    return arms


def test_dataset_v2_is_frozen_and_default():
    assert M.DATASET.name == "dataset_v2.jsonl"
    verify_frozen(M.DATASET)  # 동결 해시와 같은 파일이어야 돈다


def test_same_items_run_on_both_arms_with_same_metrics_and_no_changed_items():
    arms = make_arms()
    seen = []
    rows = M.run_arms(ITEMS, arms, "t", on_row=lambda a, r: seen.append((r["id"], a.name)))
    assert [len(rows[n]) for n in M.ARMS] == [3, 3]
    assert seen[:4] == [(1, "single"), (1, "multi"), (2, "multi"), (2, "single")]  # 문항마다 순서가 바뀐다
    res = M.compare(rows)
    assert res["changed_items"] == [] and res["changed_count"] == 0
    assert all(v == 0 for k, v in res["delta_multi_minus_single"].items() if k != "latency_p95_s")  # 응답 시간은 실행마다 다르다
    assert res["metrics"]["single"]["correct_refusal_rate"] == 1.0 and res["metrics"]["single"]["errors"] == 0
    assert [r["llm_calls"] for r in rows["single"]] == [r["llm_calls"] for r in rows["multi"]]  # 멀티가 LLM 호출을 늘리지 않는다
    assert res["totals"]["single"]["llm_calls"] == res["totals"]["multi"]["llm_calls"]


def test_llm_calls_are_counted_per_item_and_multi_rows_carry_agent_trace():
    rows = M.run_arms(ITEMS, make_arms(), "t")
    one, off, _ = rows["multi"]
    assert one["llm_calls"] == 4 and one["agent_trace"] == ["retriever", "writer", "verifier"]  # classify, rewrite, judge, answer
    assert off["agent_trace"] == ["retriever"] * 3 and off["result"] == "refuse"  # 연봉 질문: 재검색 2회 뒤 거절
    assert off["llm_calls"] == 1 + 3 * 2  # classify 1 + (rewrite, judge) 3번
    assert "agent_trace" not in rows["single"][0] and rows["single"][0]["arm"] == "single"
    for r in rows["multi"]:
        assert r["retrieval_calls"] is not None and r["supervisor_log"][-1]["to"] == "end"


def test_compare_lists_items_that_changed():
    rows = M.run_arms(ITEMS, make_arms(), "t")
    rows["multi"][0] = {**rows["multi"][0], "result": "refuse", "answered": False}
    res = M.compare(rows)
    assert res["changed_count"] == 1 and res["changed_items"][0]["id"] == 1
    assert res["changed_items"][0]["changed"]["result"] == {"single": "answer", "multi": "refuse"}
    assert res["delta_multi_minus_single"]["over_refusal_rate"] > 0


def test_compare_with_one_arm_only_reports_metrics():
    arm = make_arms()[0]
    res = M.compare(M.run_arms(ITEMS, [arm], "t"))
    assert set(res["metrics"]) == {"single"} and "changed_items" not in res


def test_search_error_stops_the_run():
    def boom(q):
        raise RuntimeError("검색 실패")

    class Boom:
        search = staticmethod(boom)

    llm = M.CountingLLM(normal_llm())
    rec = RecordingSearch(Boom())
    arm = M.Arm("multi", M.build_arm_graph("multi", rec, llm, decompose=False, grounding_llm=False), rec, llm)
    with pytest.raises(SystemExit):
        M.run_arms(ITEMS, [arm], "t")
    with pytest.raises(ValueError):
        M.build_arm_graph("triple", rec, llm)


def test_use_openrouter_env_sends_only_to_openrouter(monkeypatch):
    """`--llm openrouter`: 주소를 바꾸는 값과 다른 키를 지우고, 기본 OpenRouter 주소로 Haiku를 고른다."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-value")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-other")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-other")
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    M.use_openrouter_env()
    assert os.environ["LLM_PROVIDER"] == "openrouter"
    assert os.environ["LLM_MODEL"] == "anthropic/claude-haiku-5.5"
    assert os.environ["LLM_API_KEY"] == "sk-or-test-value"
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY"):
        assert name not in os.environ
    from backend.services.llm import OPENROUTER_BASE_URL, _real_chat_model
    model = _real_chat_model()
    assert str(model.openai_api_base) == OPENROUTER_BASE_URL
    assert model.openai_api_key.get_secret_value() == "sk-or-test-value"


def test_use_anthropic_env_sends_only_to_anthropic_with_the_cli_model(monkeypatch):
    """`--llm anthropic`: 주소를 바꾸는 값과 다른 키를 지우고, 기본 Anthropic 주소로 CLI와 같은 Haiku 5.5를 고른다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-value")
    monkeypatch.setenv("LLM_API_KEY", "")  # 시험이 끝나면 되돌리도록 monkeypatch에 먼저 걸어 둔다
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-other")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "x")
    monkeypatch.setenv("LLM_REASONING", "low")
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    for name in ("LLM_EFFORT", "LLM_EFFORT_BY_TASK"):
        monkeypatch.setenv(name, "")
    for name in ("CLAUDE_CLI_EFFORT", "CLAUDE_CLI_EFFORT_BY_TASK"):
        monkeypatch.delenv(name, raising=False)
    M.use_anthropic_env()
    assert os.environ["LLM_PROVIDER"] == "anthropic" and os.environ["LLM_MODEL"] == "claude-haiku-5-5"  # claude_cli 경로(`X.fix_env`)와 같은 모델
    assert os.environ["LLM_EFFORT"] == "low" and os.environ["LLM_EFFORT_BY_TASK"] == "answer=medium,grounding=medium"  # claude_cli 기본 추론 수준과 같다
    assert os.environ["LLM_API_KEY"] == "sk-ant-test-value"
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "LLM_REASONING"):
        assert name not in os.environ
    from backend.services.llm import _real_chat_model
    model = _real_chat_model()
    assert type(model).__name__ == "TaskEffortAnthropic" and model.model == "claude-haiku-5-5"
    assert model.anthropic_api_key.get_secret_value() == "sk-ant-test-value"
    assert "anthropic.com" in str(model.anthropic_api_url)
    from langchain_core.messages import HumanMessage, SystemMessage

    def effort(system):
        payload = model._get_request_payload([SystemMessage(content=system), HumanMessage(content="q")])
        return (payload.get("output_config") or {}).get("effort")

    # claude_cli `effort_for`와 같은 규칙: 단계 표지가 answer·grounding이면 medium, 그 밖과 표지 없음은 low
    assert effort("[[task:answer]] 답을 쓴다") == "medium"
    assert effort("[[task:grounding]] 근거") == "medium"
    assert effort("[[task:judge]] 판정") == "low"
    assert effort("표지 없음") == "low"


def test_anthropic_effort_off_keeps_the_plain_request(monkeypatch):
    """`LLM_EFFORT`·`LLM_EFFORT_BY_TASK`가 비면 예전처럼 ChatAnthropic이고 effort를 보내지 않는다. 틀린 값은 ValueError다."""
    from backend.services import llm as L
    from langchain_core.messages import HumanMessage

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-test-value")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "")
    monkeypatch.setenv("LLM_EFFORT", "")
    monkeypatch.setenv("LLM_EFFORT_BY_TASK", "")
    for name in ("LLM_DEADLINE_S", "LLM_HEDGE_S", "LLM_TRACE_DETAIL"):
        monkeypatch.setenv(name, "")
    model = L._real_chat_model()
    assert type(model).__name__ == "ChatAnthropic"
    payload = model._get_request_payload([HumanMessage(content="q")])
    assert "effort" not in (payload.get("output_config") or {}) and "thinking" not in payload
    monkeypatch.setenv("LLM_EFFORT", "fast")
    with pytest.raises(ValueError):
        L._real_chat_model()
    monkeypatch.setenv("LLM_EFFORT", "")
    monkeypatch.setenv("LLM_EFFORT_BY_TASK", "answer=fast")
    with pytest.raises(ValueError):
        L._real_chat_model()


def test_anthropic_fast_settings_turn_thinking_off_and_use_the_deadline_transport(monkeypatch):
    """#44와 같은 빠른 설정: 기본 none(생각 끔), decompose·answer low, 시도 상한 8초·hedge 3.5초·재시도 2.
    none 단계는 effort 없이 `thinking: disabled`, low 단계는 effort low, 시간 스위치는 openrouter와 같은 DeadlineTransport로 건다."""
    from backend.services import llm as L
    from langchain_core.messages import HumanMessage, SystemMessage

    for name, value in (("LLM_PROVIDER", "anthropic"), ("LLM_MODEL", ""), ("LLM_API_KEY", "sk-ant-test-value"), ("LLM_FALLBACK_MODEL", ""),
                        ("LLM_EFFORT", "none"), ("LLM_EFFORT_BY_TASK", "decompose=low,answer=low"), ("LLM_DEADLINE_S", "8"), ("LLM_HEDGE_S", "3.5"),
                        ("LLM_MAX_RETRIES", "2"), ("LLM_TRACE_DETAIL", "")):
        monkeypatch.setenv(name, value)
    model = L._real_chat_model()
    assert type(model).__name__ == "TaskEffortAnthropic" and model.max_retries == 2

    def payload(tag):
        return model._get_request_payload([SystemMessage(content=f"[[task:{tag}]] 지시"), HumanMessage(content="q")])

    for tag in ("judge", "grounding", "classify", "decompose_gate", "answer_fast"):
        p = payload(tag)
        assert p.get("thinking") == {"type": "disabled"} and "effort" not in (p.get("output_config") or {}), tag
    for tag in ("decompose", "answer"):
        p = payload(tag)
        assert (p.get("output_config") or {}).get("effort") == "low" and "thinking" not in p, tag
    transport = model.http_client_override._transport
    import httpx2

    assert isinstance(transport, L.DeadlineTransport) and transport.seconds == 8.0 and transport.hedge == 3.5
    assert isinstance(transport, httpx2.BaseTransport) and transport.timeout_exc is httpx2.ReadTimeout  # anthropic SDK(httpx2)가 재시도하는 예외
    assert model._client._client is model.http_client_override  # anthropic SDK가 이 HTTP 클라이언트로 부른다


def test_httpx2_deadline_transport_hedges_and_times_out():
    """httpx2 판(anthropic SDK용)도 hedge로 먼저 온 답을 쓰고, 상한을 넘으면 httpx2.ReadTimeout을 낸다."""
    import threading
    import time as _time

    import httpx2
    from backend.services.llm import _deadline_transport_httpx2

    calls = {"n": 0}
    lock = threading.Lock()

    class FirstSlow(httpx2.BaseTransport):
        def handle_request(self, request):
            with lock:
                calls["n"] += 1
                n = calls["n"]
            if n == 1:
                _time.sleep(0.6)
            return httpx2.Response(200, json={"n": n}, request=request)

    t = _deadline_transport_httpx2(2.0, 0.1)
    t.inner = FirstSlow()
    with httpx2.Client(transport=t) as c:
        assert c.post("https://api.anthropic.com/v1/messages", json={"system": "x"}).json() == {"n": 2}

    class Slow(httpx2.BaseTransport):
        def handle_request(self, request):
            _time.sleep(0.5)
            return httpx2.Response(200, request=request)

    t2 = _deadline_transport_httpx2(0.1, 0.0)
    t2.inner = Slow()
    with httpx2.Client(transport=t2) as c, pytest.raises(httpx2.ReadTimeout):
        c.post("https://api.anthropic.com/v1/messages", json={})


def test_deadline_transport_reads_the_task_from_the_anthropic_system_field():
    """Anthropic 요청은 시스템 프롬프트가 맨 위 `system` 칸이다(글 또는 블록 목록). 단계 건너뛰기(`LLM_DEADLINE_SKIP_TASKS`)가 그 표지를 읽는다."""
    import json as _json

    import httpx
    from backend.services.llm import DeadlineTransport

    t = DeadlineTransport(httpx.MockTransport(lambda r: httpx.Response(200)), 8.0, 3.5)
    for system in ("[[task:classify]] 분류", [{"type": "text", "text": "[[task:classify]] 분류"}]):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages", content=_json.dumps({"system": system, "messages": []}).encode())
        assert t._task_of(req) == "classify"
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages", content=_json.dumps({"system": "[[task:judge]] 판정", "messages": []}).encode())
    assert t._task_of(req) == "judge"
    t.close()


def test_run_effort_flags_override_the_cli_defaults_for_anthropic(monkeypatch):
    """`--effort`·`--effort-by-task`는 --llm anthropic에서 CLI 기본 추론 수준을 덮는다."""
    seen = {}

    def stop():
        seen.update(effort=os.environ.get("LLM_EFFORT"), by_task=os.environ.get("LLM_EFFORT_BY_TASK"))
        raise SystemExit("확인")

    monkeypatch.setenv("LLM_EFFORT", "")
    monkeypatch.setenv("LLM_EFFORT_BY_TASK", "")
    monkeypatch.setattr(M, "use_anthropic_env", lambda: None)
    monkeypatch.setattr(M.X, "load_voyage_key", stop)
    with pytest.raises(SystemExit):
        M.main(["run", "--llm", "anthropic", "--effort", "none", "--effort-by-task", "decompose=low", "--effort-by-task", "answer=low", "--out", "x"])
    assert seen == {"effort": "none", "by_task": "decompose=low,answer=low"}


@pytest.mark.parametrize("value", ["", "sk-or-other", "other"])
def test_use_anthropic_env_rejects_other_keys(monkeypatch, value, capsys):
    """Anthropic 형식이 아닌 키는 보내지 않고 멈추며, 값을 출력하지 않는다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    with pytest.raises(SystemExit) as e:
        M.use_anthropic_env()
    assert os.environ["LLM_PROVIDER"] == "claude_cli"
    if value:
        assert value not in str(e.value)
        assert value not in capsys.readouterr().out


def test_run_with_anthropic_goes_through_the_anthropic_path(monkeypatch):
    def reached():
        raise SystemExit("anthropic 경로에 도달")

    monkeypatch.setattr(M, "use_anthropic_env", reached)
    monkeypatch.setattr(M.X, "fix_env", lambda: (_ for _ in ()).throw(AssertionError("CLI 경로로 가면 안 된다")))
    with pytest.raises(SystemExit) as e:
        M.main(["run", "--llm", "anthropic", "--out", "x"])
    assert str(e.value) == "anthropic 경로에 도달"


# ---------- 멀티 LLM 라우팅 갈래 (`multi_llm`) ----------
def _insufficient_then_give_up():
    return {"judge": j(sufficient=False, reason="없음", clarify=None), "supervisor_route": j(next="give_up")}


def _arm(name, **llm_over):
    llm = M.CountingLLM(normal_llm(**{"judge": judge, **llm_over}))
    rec = RecordingSearch(FakeSearcher())
    return M.Arm(name, M.build_arm_graph(name, rec, llm, decompose=False, grounding_llm=False), rec, llm)


def test_default_arms_are_unchanged_and_the_new_arm_is_opt_in(monkeypatch):
    assert M.ARMS == ("single", "multi") and M.ALL_ARMS == ("single", "multi", "multi_llm")
    args = []
    monkeypatch.setattr(M, "run_cmd", lambda a: args.append(a) or 0)
    M.main(["run", "--out", "x"])
    assert args[0].arms == "single,multi" and args[0].llm == "claude_cli"


def test_multi_arm_stays_on_code_routing_even_if_the_environment_says_llm(monkeypatch):
    """v2 재현: 환경 변수가 켜져 있어도 `multi` 갈래는 코드 라우팅이다."""
    monkeypatch.setenv("SUPERVISOR_ROUTER", "llm")
    arm = _arm("multi", **_insufficient_then_give_up())
    row = M.run_arms(ITEMS[:1], [arm], "t")["multi"][0]
    assert row["agent_trace"] == ["retriever"] * 3 and arm.llm.llm.count("supervisor_route") == 0


def test_multi_llm_arm_routes_with_the_same_counted_model():
    arm = _arm("multi_llm", **_insufficient_then_give_up())
    row = M.run_arms(ITEMS[:1], [arm], "t")["multi_llm"][0]
    assert row["arm"] == "multi_llm" and row["agent_trace"] == ["retriever"] and row["supervisor_log"][1]["router"] == "llm"
    assert row["llm_calls"] == 4 and arm.llm.llm.count("supervisor_route") == 1  # classify, rewrite, judge, 라우터: 같은 모델을 거쳐 함께 센다


def test_compare_reports_the_llm_arm_against_the_code_multi_arm():
    arms = [_arm("multi"), _arm("multi_llm", supervisor_route=j(next="give_up"))]
    res = M.compare(M.run_arms(ITEMS, arms, "t"))
    assert "delta_multi_minus_single" not in res and "delta_multi_llm_minus_multi" in res
    (changed,) = res["changed_multi_llm_vs_multi"]  # 연봉 문항: 라우터가 첫 판정 뒤 닫아 재검색이 없다
    assert changed["id"] == 2 and changed["changed"]["retries"] == {"multi": 3, "multi_llm": 1}
    assert res["routing"]["multi_llm"] == {"llm_routed": 1, "fallbacks": 0, "differs_from_code": 1}


def test_compare_with_default_arms_keeps_its_old_keys():
    res = M.compare(M.run_arms(ITEMS, [_arm("single"), _arm("multi")], "t"))
    assert {"metrics", "totals", "delta_multi_minus_single", "changed_items", "changed_count", "note"} == set(res)


def test_multi_llm_arm_needs_the_openrouter_path_and_stops_before_touching_keys(monkeypatch):
    touched = []
    monkeypatch.setattr(M.X, "fix_env", lambda: touched.append("fix_env"))
    monkeypatch.setattr(M.X, "load_voyage_key", lambda: touched.append("voyage"))
    with pytest.raises(SystemExit) as e:
        M.main(["run", "--arms", "multi,multi_llm", "--out", "x"])
    assert "openrouter" in str(e.value) and touched == []


def test_multi_llm_arm_goes_through_the_existing_openrouter_path(monkeypatch):
    def reached():
        raise SystemExit("openrouter 경로에 도달")

    monkeypatch.setattr(M, "use_openrouter_env", reached)
    with pytest.raises(SystemExit) as e:
        M.main(["run", "--llm", "openrouter", "--arms", "multi,multi_llm", "--out", "x"])
    assert str(e.value) == "openrouter 경로에 도달"


@pytest.mark.parametrize("value", ["", "sk-ant-other", "other"])
def test_use_openrouter_env_rejects_other_keys(monkeypatch, value, capsys):
    """OpenRouter 형식이 아닌 키는 보내지 않고 멈추며, 값을 출력하지 않는다."""
    monkeypatch.setenv("OPENROUTER_API_KEY", value)
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    with pytest.raises(SystemExit) as e:
        M.use_openrouter_env()
    assert os.environ["LLM_PROVIDER"] == "claude_cli"
    if value:
        assert value not in str(e.value)
        assert value not in capsys.readouterr().out


# ---------- 속도 스위치를 측정에서 고른다 ----------
def _parse(argv):
    seen = []
    saved = M.run_cmd
    M.run_cmd = lambda a: seen.append(a) or 0
    try:
        M.main(["run", "--out", "x", *argv])
    finally:
        M.run_cmd = saved
    return seen[0]


OFF = {"parallel_intake": False, "brief_output": False, "max_research": 2, "judge_answer": "", "skip_first_rewrite": False, "stop_stalled_search": False, "ground_skip_backed": False, "json_only": False}


MODEL_OFF = {"LLM_REASONING": "", "LLM_PROVIDER_SORT": "", "LLM_DEADLINE_S": "", "LLM_MAX_RETRIES": "", "LLM_TRACE_DETAIL": "", "LLM_JSON_REMINDER": "", "LLM_REASONING_BY_TASK": "", "GRAPH_SECTION_KEEPS_RESEARCH": "", "LLM_HEDGE_S": "", "GRAPH_ANSWER_WAIT_S": "", "GRAPH_ANSWER_BUDGET_S": "", "LLM_STRUCTURED": "", "GRAPH_JUDGE_QUERY": "", "EMBED_KEEPALIVE": "", "SEARCH_PARALLEL_SUBS": "",
             "GRAPH_KEEP_PRODUCT_NAME": "", "GRAPH_REQUERY_TERMS": "", 
             "GRAPH_QUERY_BRANCHES": "",
             "GRAPH_CITE_EXPAND": "", "GRAPH_CITE_MULTI": "", "GRAPH_TEAM_LAST": "", "GRAPH_KEEP_CITES": "", "GRAPH_SUB_RESEARCH": "", "GRAPH_PAGE_RESEARCH": "",
             "GRAPH_REQUERY_VOCAB": "", "GRAPH_UNKNOWN_NAME": "", "GRAPH_DECOMPOSE_CAP_S": "", "GRAPH_REFUSE_ON_NONE": "", "GRAPH_RESEARCH_SAME_PAGE": "",
             "GRAPH_CITE_PHRASE": "", "GRAPH_GROUNDING_QUOTE": "", "GRAPH_DROP_SCOPED_CITES": "", 
             "GRAPH_INTRO_FILL": "", 
             "GRAPH_SCOPE_NOTE_REFUSE": "", "GRAPH_CITE_PICK": "",
             "GRAPH_REQUERY_SKIP_SEEN": "", "GRAPH_CITE_CONSENSUS": "", "GRAPH_POINTER_REFUSE": "", "GRAPH_SPECULATE_FIRST": "", "GRAPH_UNCHANGED_REJUDGE": "", "GRAPH_PROMPTS_HEAD": "", "GRAPH_JUDGE_VOTE": "", "GRAPH_JUDGE_QUOTE": "", "SEARCH_SUB_MERGE": "", "GRAPH_FACTS_LOG": "", "GRAPH_ANSWER_BEST2": "", "GRAPH_BEST2_SAMEDOC": "", "GRAPH_SPECULATE_GROUND": "",
            "SEARCH_HEDGE": "", "SEARCH_HEDGE_S": ""}


def test_switches_default_to_off_and_ignore_the_environment(monkeypatch):
    for name, value in (("GRAPH_PARALLEL_INTAKE", "1"), ("LLM_BRIEF_OUTPUT", "1"), ("SEARCH_MAX_RESEARCH", "0"), ("GRAPH_JUDGE_ANSWER", "joint"), ("GRAPH_SKIP_FIRST_REWRITE", "1"),
                        ("GRAPH_STOP_STALLED_SEARCH", "1"), ("GROUND_SKIP_BACKED", "1"), ("LLM_JSON_ONLY", "1"), ("LLM_REASONING", "none"), ("LLM_PROVIDER_SORT", "latency")):
        monkeypatch.setenv(name, value)
    assert M.chosen_switches(_parse([])) == OFF
    assert M.chosen_model_switches(_parse([])) == MODEL_OFF  # 빈 값으로 덮어 끈다


def test_switches_can_be_chosen_on_the_command_line():
    args = _parse(["--parallel-intake", "--brief-output", "--max-research", "1"])
    assert M.chosen_switches(args) == {**OFF, "parallel_intake": True, "brief_output": True, "max_research": 1}
    args = _parse(["--judge-answer", "parallel", "--skip-first-rewrite", "--stop-stalled-search", "--ground-skip-backed", "--json-only", "--reasoning", "none", "--provider-sort", "latency"])
    assert M.chosen_switches(args) == {**OFF, "judge_answer": "parallel", "skip_first_rewrite": True, "stop_stalled_search": True, "ground_skip_backed": True, "json_only": True}
    assert M.chosen_model_switches(args) == {**MODEL_OFF, "LLM_REASONING": "none", "LLM_PROVIDER_SORT": "latency"}
    args = _parse(["--llm-deadline", "6", "--llm-retries", "2", "--trace-detail", "--parallel-subs", "--json-reminder"])
    assert M.chosen_model_switches(args) == {**MODEL_OFF, "LLM_DEADLINE_S": "6", "LLM_MAX_RETRIES": "2", "LLM_TRACE_DETAIL": "1", "SEARCH_PARALLEL_SUBS": "1", "LLM_JSON_REMINDER": "1"}
    assert M.chosen_model_switches(_parse(["--decompose-cap", "2.5"])) == {**MODEL_OFF, "GRAPH_DECOMPOSE_CAP_S": "2.5"}
    assert M.chosen_model_switches(_parse(["--refuse-on-none", "--research-same-page"])) == {**MODEL_OFF, "GRAPH_REFUSE_ON_NONE": "1", "GRAPH_RESEARCH_SAME_PAGE": "1"}
    assert M.chosen_model_switches(_parse(["--cite-phrase"])) == {**MODEL_OFF, "GRAPH_CITE_PHRASE": "1"}
    assert M.chosen_model_switches(_parse(["--grounding-quote"])) == {**MODEL_OFF, "GRAPH_GROUNDING_QUOTE": "1"}
    assert M.chosen_model_switches(_parse(["--drop-scoped-cites"])) == {**MODEL_OFF, "GRAPH_DROP_SCOPED_CITES": "1"}
    assert M.chosen_model_switches(_parse(["--intro-fill"])) == {**MODEL_OFF, "GRAPH_INTRO_FILL": "1"}
    assert M.chosen_model_switches(_parse(["--scope-note-refuse", "--cite-pick"])) == {
        **MODEL_OFF, "GRAPH_SCOPE_NOTE_REFUSE": "1", "GRAPH_CITE_PICK": "1"}
    assert M.chosen_model_switches(_parse(["--requery-skip-seen", "--cite-consensus", "--pointer-refuse", "--speculate-first"])) == {
        **MODEL_OFF, "GRAPH_REQUERY_SKIP_SEEN": "1", "GRAPH_CITE_CONSENSUS": "1", "GRAPH_POINTER_REFUSE": "1", "GRAPH_SPECULATE_FIRST": "1"}


def test_prompts_head_flag_sets_only_its_switch():
    assert M.chosen_model_switches(_parse(["--prompts-head"])) == {**MODEL_OFF, "GRAPH_PROMPTS_HEAD": "1"}


@pytest.mark.parametrize("flag, env", [("--judge-vote", "GRAPH_JUDGE_VOTE"), ("--judge-quote", "GRAPH_JUDGE_QUOTE"), ("--sub-merge", "SEARCH_SUB_MERGE"), ("--facts-log", "GRAPH_FACTS_LOG"), ("--answer-best2", "GRAPH_ANSWER_BEST2"), ("--best2-samedoc", "GRAPH_BEST2_SAMEDOC")])
def test_research_fix_flags_set_only_their_switch(flag, env):
    assert M.chosen_model_switches(_parse([flag])) == {**MODEL_OFF, env: "1"}


def test_by_task_lists_merge_instead_of_replacing():
    """61.8: 실행기가 준 decompose=low,answer=low 뒤에 answer=low를 더 주자 decompose가 사라졌다. 여러 번 주면 단계별로 합친다."""
    args = _parse(["--reasoning-by-task", "decompose=low,answer=low", "--reasoning-by-task", "answer=none,judge=low"])
    sw = M.chosen_model_switches(args)
    assert sw["LLM_REASONING_BY_TASK"] == "decompose=low,answer=none,judge=low"
    assert M.chosen_model_switches(_parse(["--reasoning-by-task", "decompose=low"]))["LLM_REASONING_BY_TASK"] == "decompose=low"
    with pytest.raises(SystemExit):
        _parse(["--judge-answer", "both"])
    with pytest.raises(SystemExit):
        _parse(["--max-research", "3"])


@pytest.mark.parametrize("arm", M.ALL_ARMS)
def test_switches_reach_every_arm(arm):
    llm = M.CountingLLM(normal_llm(judge=j(sufficient=False, reason="없음", clarify=None), supervisor_route=j(next="retriever")))
    rec = RecordingSearch(FakeSearcher())
    graph = M.build_arm_graph(arm, rec, llm, decompose=False, grounding_llm=False, parallel_intake=True, brief_output=True, max_research=1)
    row = M.run_arm_item(M.Arm(arm, graph, rec, llm), ITEMS[0], "t")
    assert row["retries"] == 2 and row["result"] == "refuse" and llm.llm.count("judge") == 2  # 재검색 상한 1: 판정 2번. 같은 검색어라 실제 검색은 기억에서 나온다


def test_run_records_the_switches_and_routers_in_the_meta(monkeypatch, tmp_path):
    import json

    from evals.agent import exp_service_v1 as S

    monkeypatch.setattr(M.X, "fix_env", lambda: None)
    monkeypatch.setattr(M.X, "load_voyage_key", lambda: None)
    monkeypatch.setattr(S, "build_searcher", lambda: (FakeSearcher(), {"store": "fake"}))
    monkeypatch.setattr("backend.services.llm.get_chat_model", lambda: normal_llm(judge=j(sufficient=True), decompose=j(split=False, sub_questions=[])))
    monkeypatch.setattr("backend.services.llm.is_demo_mode", lambda: False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("LLM_REASONING", "none")  # 인자를 안 주면 끈다. monkeypatch가 시험 뒤에 되돌린다
    monkeypatch.setenv("LLM_PROVIDER_SORT", "latency")
    out = tmp_path / "r"
    assert M.main(["run", "--ids", "1", "--arms", "single,multi", "--parallel-intake", "--max-research", "1", "--out", str(out)]) == 0
    meta = json.loads((out / "compare.json").read_text(encoding="utf-8"))["meta"]
    assert meta["switches"] == {**OFF, "parallel_intake": True, "max_research": 1}
    assert meta["model_switches"] == MODEL_OFF
    row = json.loads((out / "single" / "rows.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["context_chunks"] and all(c["text"] for c in row["context_chunks"]) and {c["chunk_id"] for c in row["context_chunks"]} >= set(row["cited"])
    assert meta["routers"] == {"multi": "code"} and meta["partial"] is True
    assert json.loads((out / "multi" / "summary.json").read_text(encoding="utf-8"))["meta"]["switches"]["parallel_intake"] is True
    assert meta["repeat"] == 1 and row["repeat"] == 0


def test_repeat_runs_the_chosen_items_again_and_needs_ids(monkeypatch, tmp_path):
    import json

    from evals.agent import exp_service_v1 as S

    monkeypatch.setattr(M.X, "fix_env", lambda: None)
    monkeypatch.setattr(M.X, "load_voyage_key", lambda: None)
    monkeypatch.setattr(S, "build_searcher", lambda: (FakeSearcher(), {"store": "fake"}))
    monkeypatch.setattr("backend.services.llm.get_chat_model", lambda: normal_llm(judge=j(sufficient=True), decompose=j(split=False, sub_questions=[])))
    monkeypatch.setattr("backend.services.llm.is_demo_mode", lambda: False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "fake")
    out = tmp_path / "r"
    assert M.main(["run", "--ids", "1", "--repeat", "3", "--arms", "single,multi", "--out", str(out)]) == 0
    for arm in ("single", "multi"):
        rows = [json.loads(x) for x in (out / arm / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [(r["id"], r["repeat"]) for r in rows] == [(rows[0]["id"], k) for k in range(3)]
    assert json.loads((out / "compare.json").read_text(encoding="utf-8"))["meta"]["repeat"] == 3
    with pytest.raises(SystemExit):
        M.main(["run", "--repeat", "3", "--out", str(tmp_path / "x")])  # 전체 문항 반복은 하지 않는다


def test_dataset_sha256_checks_only_the_given_file(tmp_path):
    f = tmp_path / "other.jsonl"
    f.write_text('{"id": 1}\n', encoding="utf-8")
    import hashlib as _h
    M.check_dataset(f, _h.sha256(f.read_bytes()).hexdigest())  # 해시가 같으면 돈다
    with pytest.raises(SystemExit):
        M.check_dataset(f, "0" * 64)
    with pytest.raises(SystemExit):
        M.check_dataset(f)  # 기본은 동결 목록이라 목록 밖 파일은 멈춘다
    with pytest.raises(SystemExit):
        M.check_dataset(M.DATASET, "0" * 64)  # v2 기본값에는 쓰지 않는다
    M.check_dataset(M.DATASET)


