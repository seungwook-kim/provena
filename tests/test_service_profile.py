"""서비스 기본 설정(61.51, `backend/graph/service_profile.py`) 시험. 가짜 모델, 가짜 검색기, 가짜 DB 주소만 쓴다(외부 호출 없음).

- 서비스 값이 측정 실행기(`exp_multi_v2 run`)가 같은 인자로 정하는 환경 변수, 그래프 인자, 추론 수준과 같은지 대조한다.
- 앱 lifespan이 서비스 값을 채우고 내려갈 때 되돌리는지, 시험이 그래프를 꽂으면 바꾸지 않는지 본다.
"""
from __future__ import annotations

import base64
import json
import os
import secrets

import pytest

from backend.graph import service_profile as SP

MEASUREMENT_ONLY = {"LLM_TRACE_DETAIL", "GRAPH_FACTS_LOG"}  # 측정 기록 전용(답 경로 밖). 서비스에 넣지 않는다
GRAPH_ARGS_ENV = {  # 측정 실행기가 `build_graph` 인자로 넘기는 값과 그래프가 같은 뜻으로 읽는 환경 변수
    "parallel_intake": "GRAPH_PARALLEL_INTAKE", "brief_output": "LLM_BRIEF_OUTPUT", "max_research": "SEARCH_MAX_RESEARCH",
    "judge_answer": "GRAPH_JUDGE_ANSWER", "skip_first_rewrite": "GRAPH_SKIP_FIRST_REWRITE", "stop_stalled_search": "GRAPH_STOP_STALLED_SEARCH",
    "ground_skip_backed": "GROUND_SKIP_BACKED", "json_only": "LLM_JSON_ONLY",
}


@pytest.fixture
def clean_env(monkeypatch):
    for name in [*SP.SERVICE_ENV, "SEARCH_VIA_MCP", SP.PROFILE_ENV, "MCP_TOKEN"]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def measured_args():
    from evals.agent import exp_multi_v2 as M

    seen = []
    saved = M.run_cmd
    M.run_cmd = lambda a: seen.append(a) or 0
    try:
        M.main(["run", "--llm", "anthropic", "--store", "pg", *SP.MEASURED_ARGS, "--warm", "--trace-detail", "--facts-log", "--out", "x"])
    finally:
        M.run_cmd = saved
    return M, seen[0]


def expected_env() -> dict[str, str]:
    """측정 실행기가 61.51 인자로 정하는 값(측정 전용 제외)을 서비스 환경 변수 이름으로 모은다."""
    M, args = measured_args()
    env = {k: v for k, v in M.chosen_model_switches(args).items() if v and k not in MEASUREMENT_ONLY}
    for arg, name in GRAPH_ARGS_ENV.items():
        value = M.chosen_switches(args)[arg]
        if value is True:
            env[name] = "1"
        elif value not in (False, "", None) and not (arg == "max_research" and value == 2):
            env[name] = str(value)
    env["LLM_EFFORT"], env["LLM_EFFORT_BY_TASK"] = args.effort, args.effort_by_task  # --llm anthropic일 때 run_cmd가 넣는 값
    return env


# 사전 등록 62.40 속도 묶음 중 서비스 값으로 올린 셋(측정 실행기 인자에는 없다. 서비스 경로만)
SPEED_6240 = {"ANSWER_STORE_REUSE_CONN": "1", "GRAPH_REVISE_AHEAD": "1", "LLM_DEADLINE_BY_TASK": "judge=12"}
# 사전 등록 62.16 그래프 밖 왕복 줄이기 둘(서비스 경로만, 측정 실행기 인자에는 없다)
GRAPH_OUTSIDE_6216 = {"CHAT_FINAL_FROM_STREAM": "1", "ANSWER_SAVE_ONE_CONN": "1"}
# 사전 등록 62.14 검색 hedge: 운영 Cloud Run 값(SEARCH_HEDGE=1, SEARCH_HEDGE_S=1.5, 2026-11-11 확인)을 서비스 값으로(사용자 결정 11/11 26). 측정 실행기 인자에는 없다
SEARCH_HEDGE_6214 = {"SEARCH_HEDGE": "1", "SEARCH_HEDGE_S": "1.5"}
# 사전 등록 62.53(62.15 재도입): 원 질문 첫 검색을 질문 접수와 동시에 시작. 측정 묶음 인자(MEASURED_ARGS)에는 넣지 않았다(서비스 경로만, 실행기에는 --speculate-early-search가 있다)
EARLY_SEARCH_6253 = {"GRAPH_SPECULATE_EARLY_SEARCH": "1"}


def test_62_40_speed_values_are_service_defaults():
    assert {k: SP.SERVICE_ENV.get(k) for k in SPEED_6240} == SPEED_6240
    assert SP.SERVICE_ENV["GRAPH_SPECULATE_GROUND"] == "1"          # GRAPH_REVISE_AHEAD가 쓰는 앞선 근거 확인
    assert "GRAPH_JUDGE_RETRY_FAST" not in SP.SERVICE_ENV and "GRAPH_JUDGE_RETRY_FAST" not in SP.CANDIDATE_ENV   # 추론 끔은 코드째 제거했다
    assert "EVAL_REVIEW_SINGLE" not in SP.SERVICE_ENV and "EVAL_REVIEW_SINGLE" not in SP.CANDIDATE_ENV      # 평가용 단일 모드는 배포 때 따로 켠다
    assert not set(SPEED_6240) & set(SP.CANDIDATE_ENV)
    assert {k: SP.SERVICE_ENV.get(k) for k in GRAPH_OUTSIDE_6216} == GRAPH_OUTSIDE_6216 and not set(GRAPH_OUTSIDE_6216) & set(SP.CANDIDATE_ENV)   # 사용자 결정 11/11 19: 후보에서 서비스 값으로
    assert {k: SP.SERVICE_ENV.get(k) for k in SEARCH_HEDGE_6214} == SEARCH_HEDGE_6214 and not set(SEARCH_HEDGE_6214) & set(SP.CANDIDATE_ENV)   # 사용자 결정 11/11 26


def test_search_hedge_service_values_turn_the_hedge_on_with_the_production_wait(monkeypatch):
    from backend.rag.retrieve import hedge

    monkeypatch.delenv("SEARCH_HEDGE", raising=False)
    monkeypatch.delenv("SEARCH_HEDGE_S", raising=False)
    assert hedge.enabled() is False                                    # 서비스 값을 채우기 전(코드 기본)은 꺼짐
    env: dict = {}
    SP.apply_service_profile(env)
    assert (env["SEARCH_HEDGE"], env["SEARCH_HEDGE_S"]) == ("1", "1.5")
    assert hedge.enabled(env) is True and hedge.hedge_seconds(env) == 1.5
    given: dict = {"SEARCH_HEDGE": "", "SEARCH_HEDGE_S": "2.5"}
    SP.apply_service_profile(given)                                    # 값을 직접 준 변수는 그대로(빈 값은 서비스 값, 준 값은 유지)
    assert given["SEARCH_HEDGE_S"] == "2.5"


def test_service_values_match_the_measured_arguments():
    want = expected_env()
    have = {k: v for k, v in SP.SERVICE_ENV.items() if k not in ("SEARCH_HNSW", "LLM_REASONING", "LLM_REASONING_BY_TASK", "LLM_DEADLINE_SKIP_TASKS", *SPEED_6240, *GRAPH_OUTSIDE_6216, *SEARCH_HEDGE_6214, *EARLY_SEARCH_6253)}
    assert have == want
    assert {k: SP.SERVICE_ENV.get(k) for k in EARLY_SEARCH_6253} == EARLY_SEARCH_6253 and not set(EARLY_SEARCH_6253) & set(SP.CANDIDATE_ENV)   # 62.53: 서비스 기본 켬
    assert SP.SERVICE_ENV["GRAPH_SPECULATE_FIRST"] == "1"                 # 일찍 시작하는 검색은 예비 분해(SP)가 켜져 있어야 쓰인다
    assert "GRAPH_CITE_HEAD_OWNER" not in SP.SERVICE_ENV                  # 62.52는 스위치 없이 기본 동작이다
    assert SP.SERVICE_ENV["SEARCH_HNSW"] == "1"  # 측정 환경 변수
    # openrouter 공급자는 같은 수준을 LLM_REASONING*로 읽는다
    assert (SP.SERVICE_ENV["LLM_REASONING"], SP.SERVICE_ENV["LLM_REASONING_BY_TASK"]) == (SP.SERVICE_ENV["LLM_EFFORT"], SP.SERVICE_ENV["LLM_EFFORT_BY_TASK"])
    _, args = measured_args()
    assert args.via_mcp and args.connected  # 서비스에서는 SEARCH_VIA_MCP(MCP_TOKEN이 있을 때)와 원래 연결된 결정표·합동 검토


def test_measured_args_are_the_61_51_setting():
    _, args = measured_args()
    assert (args.effort, args.effort_by_task) == ("none", "decompose=low,answer=low,judge=low")
    assert (args.llm_deadline, args.llm_hedge, args.llm_retries, args.answer_wait, args.answer_budget) == ("8", "3.5", "2", 4.0, 6.5)
    assert args.judge_quote and args.answer_best2 and args.best2_samedoc and args.judge_vote and args.max_research == 1


def test_values_are_valid_for_the_readers(clean_env):
    """서비스 값이 각 모듈의 검사(틀린 값이면 ValueError)를 지나는지."""
    for name, value in SP.SERVICE_ENV.items():
        clean_env.setenv(name, value)
    from backend.graph.build import resolve_judge_answer, resolve_max_research
    from backend.prompts.question import structured_stages
    from backend.services import llm

    assert resolve_max_research() == 1 and resolve_judge_answer() == "parallel_all"
    assert structured_stages() == {"judge", "answer", "grounding"}
    assert llm.anthropic_efforts() == ("none", {"decompose": "low", "answer": "low", "judge": "low"})
    assert llm.reasoning_by_task() == {"decompose": "low", "answer": "low", "judge": "low"}
    assert llm._openrouter_extra_body() == {"reasoning": {"effort": "none"}}
    assert llm._client_options() == {"max_retries": 2}
    assert llm.deadline_skip_tasks() == ("decision_draft", "supervisor", "team_*", "single")
    assert llm.deadline_by_task() == {"judge": 12.0}


def test_deadline_skip_tasks_cover_only_long_calls_outside_the_question_graph():
    """상한을 빼는 단계는 결정표 변환 초안과 합동 검토 감독·팀뿐이다. 질문 그래프의 단계는 하나도 맞지 않는다(측정과 같은 상한)."""
    from backend.graph import decompose
    from backend.graph.decision import convert
    from backend.graph.decision.params import TASK_PARAMS
    from backend.graph.departments import teams
    from backend.prompts import question as P
    from backend.services.llm import _TASK_MARK, task_matches

    skip = tuple(SP.SERVICE_ENV["LLM_DEADLINE_SKIP_TASKS"].split(","))
    long_calls = [convert.DRAFT_SYSTEM, teams.SUPERVISOR_SYSTEM, *(teams.team_system(t, "") for t in teams.TEAMS)]
    assert len(long_calls) >= 3 and all(task_matches(_TASK_MARK.search(s).group(1), skip) for s in long_calls)
    from backend.graph.departments import single_review

    assert task_matches(_TASK_MARK.search(single_review.SINGLE_SYSTEM).group(1), skip)   # 평가용 단일 검토자도 팀과 같은 조건(시간 상한·hedge 없음)
    question = [P.TASK_CLASSIFY, P.TASK_REWRITE, P.TASK_JUDGE, P.TASK_ANSWER, "answer_fast", P.TASK_GROUNDING, P.TASK_SUPERVISOR_ROUTE,
                P.TASK_JUDGE_ANSWER, decompose.TASK, decompose.GATE_TASK, TASK_PARAMS]
    assert not [t for t in question if task_matches(t, skip)]


def test_fills_empty_and_missing_keeps_given_and_off_clears():
    env = {"GRAPH_JUDGE_VOTE": "", "SEARCH_MAX_RESEARCH": "2", "LLM_STRUCTURED": "off", "LLM_DEADLINE_S": " OFF "}
    original = dict(env)
    before = SP.apply_service_profile(env)
    assert env["GRAPH_JUDGE_VOTE"] == "1" and env["GRAPH_CITE_PICK"] == "1"     # 빈 값, 없는 값은 서비스 값
    assert env["SEARCH_MAX_RESEARCH"] == "2"                                     # 직접 준 값은 그대로
    assert env["LLM_STRUCTURED"] == "" and env["LLM_DEADLINE_S"] == ""          # off는 그 설정을 쓰지 않는다
    assert "SEARCH_VIA_MCP" not in env                                           # MCP_TOKEN이 없으면 직접 호출
    SP.restore_env(before, env)
    assert env == original


def test_profile_off_fills_nothing_but_still_clears_off():
    env = {SP.PROFILE_ENV: "off", "GRAPH_JUDGE_QUOTE": "1", "LLM_STRUCTURED": "off"}
    SP.apply_service_profile(env)
    assert env == {SP.PROFILE_ENV: "off", "GRAPH_JUDGE_QUOTE": "1", "LLM_STRUCTURED": ""}


def test_profile_name_is_checked():
    assert SP.profile_enabled({SP.PROFILE_ENV: "61.51"}) and SP.profile_enabled({})
    with pytest.raises(ValueError):
        SP.apply_service_profile({SP.PROFILE_ENV: "61.50"})


def test_search_via_mcp_only_with_a_token():
    env = {"MCP_TOKEN": "t"}
    SP.apply_service_profile(env)
    assert env["SEARCH_VIA_MCP"] == "1"
    env = {"MCP_TOKEN": "t", "SEARCH_VIA_MCP": "0"}
    SP.apply_service_profile(env)
    assert env["SEARCH_VIA_MCP"] == "0"


def test_context_restores_and_disabled_changes_nothing(clean_env):
    with SP.service_profile(enabled=False):
        assert "GRAPH_JUDGE_VOTE" not in os.environ
    with SP.service_profile():
        assert os.environ["GRAPH_JUDGE_VOTE"] == "1" and os.environ["LLM_EFFORT"] == "none"
    assert "GRAPH_JUDGE_VOTE" not in os.environ and "LLM_EFFORT" not in os.environ


def test_shared_model_is_made_once(monkeypatch):
    made = []

    class Fake:
        def invoke(self, *a, **k):
            return "ok"

    monkeypatch.setattr("backend.services.llm.get_chat_model", lambda: made.append(1) or Fake())
    m = SP.SharedChatModel()
    assert made == []                      # 처음 부를 때까지 만들지 않는다
    assert m.invoke([]) == "ok" and m.invoke([]) == "ok"
    assert made == [1]


def test_service_searches_call_the_service_searcher(monkeypatch):
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")
    calls = []

    class FakeSearcher:
        def search_pages(self, *a):
            calls.append(("pages", a))
            return ["p"]

        def intro_fill(self, *a):
            calls.append(("intro", a))
            return ["i"]

    monkeypatch.setattr(S, "_searcher", FakeSearcher())
    parts = SP.service_searches()
    assert parts["page_search"]("q", [1, 2], None, "2026-11-09", 8) == ["p"]
    assert parts["intro_search"]([{"chunk_id": "a"}], "q", None, None) == ["i"]
    assert [c[0] for c in calls] == ["pages", "intro"]
    assert calls[0][1] == ("q", [1, 2], None, "2026-11-09", 8)


def _app(monkeypatch, **kw):
    from auth_test_support import create_test_auth_router

    from backend.main import create_app

    for key in ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE", "CHECKPOINTER", "MCP_TOKEN", "SEARCH_WARMUP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", secrets.token_urlsafe(32))
    # 배포 모드에선 내 정보 키가 없으면 시작하지 않는다(backend/main.py). AUTH_SECRET처럼 시험마다 새로 만든다
    monkeypatch.setenv("PROFILE_ENC_KEYS", "1:" + base64.b64encode(secrets.token_bytes(32)).decode())
    monkeypatch.delenv("PROVENA_OWNER_LOGIN_ID", raising=False)
    monkeypatch.setenv("CHECKPOINTER", "memory")
    monkeypatch.setattr("backend.main.create_auth_router", create_test_auth_router)
    return create_app(**kw)


def test_app_builds_the_service_graph_with_the_profile_and_restores_env(clean_env):
    from fastapi.testclient import TestClient

    import backend.graph.build as B

    seen = {}
    real = B.build_graph

    def spy(*a, **k):
        seen.update(k, env={n: os.environ.get(n) for n in SP.SERVICE_ENV})
        return real(*a, **k)  # 서비스 값을 모두 켠 채로 그래프가 만들어지는지(설정 오류가 없는지)

    clean_env.setattr(B, "build_graph", spy)
    clean_env.setenv("GRAPH_JUDGE_VOTE", "off")  # 하나는 끈다
    app = _app(clean_env)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.question_graph is not None
        assert os.environ["GRAPH_ANSWER_BEST2"] == "1"
    assert seen["env"] == {**SP.SERVICE_ENV, "GRAPH_JUDGE_VOTE": ""}
    assert {"page_search", "intro_search"} <= set(seen) and isinstance(seen["llm"], SP.SharedChatModel)
    assert seen["decision_repo"] is not None and seen["review_graph"] is not None  # --connected: 결정표와 합동 검토가 연결돼 있다
    assert "GRAPH_ANSWER_BEST2" not in os.environ and os.environ["GRAPH_JUDGE_VOTE"] == "off"  # 앱이 내려가면 되돌린다


def test_app_with_a_test_graph_does_not_touch_env(clean_env):
    from fastapi.testclient import TestClient

    seen = {}

    def factory(state):
        seen["env"] = {n: os.environ.get(n) for n in SP.SERVICE_ENV}
        return object()

    app = _app(clean_env, graph_factory=factory)
    with TestClient(app):
        pass
    assert set(seen["env"].values()) == {None}


def test_env_example_shows_the_service_values_once():
    """.env.example(compose가 먼저 읽는다)의 값이 서비스 값과 같고, 같은 이름이 두 번 나오지 않는다."""
    from pathlib import Path

    lines = [x for x in (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8").splitlines() if x and not x.startswith("#") and "=" in x]
    names = [x.split("=", 1)[0] for x in lines]
    assert len(names) == len(set(names)), sorted(n for n in set(names) if names.count(n) > 1)
    values = dict(x.split("=", 1) for x in lines)
    assert {n: values.get(n) for n in SP.SERVICE_ENV} == SP.SERVICE_ENV
    assert values[SP.PROFILE_ENV] == "" and values["SEARCH_VIA_MCP"] == ""


def test_corpus_text_reads_the_unpacked_index_when_chunks_are_missing(tmp_path):
    from backend.graph import answer_fixes as F

    row = {"rule_title": "Incident Management", "article": "Severity", "text": "Hard PCL is declared."}
    (tmp_path / "data" / "index").mkdir(parents=True)
    (tmp_path / "data" / "index" / "chunks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert "hard pcl is declared" in F.corpus_text(str(tmp_path))
    both = tmp_path / "both"
    for sub, text in (("chunks", "first file"), ("index", "second file")):
        (both / "data" / sub).mkdir(parents=True)
        (both / "data" / sub / "chunks.jsonl").write_text(json.dumps({**row, "text": text}) + "\n", encoding="utf-8")
    got = F.corpus_text(str(both))
    assert "first file" in got and "second file" not in got  # 같은 코퍼스를 두 번 읽지 않는다
