"""합동 검토 Supervisor의 팀 선택(`REVIEW_TEAM_SELECT`, `backend/graph/departments/review.py`) 시험. 가짜 모델·가짜 검색기만 쓴다(키·네트워크·DB 없음).

- 켜면 Supervisor가 낸 `teams`의 팀만 돌고, 고르지 않은 팀은 쟁점표 `team_status`에 `not_selected`로만 남는다(검토하지 못함이 아니다).
- `teams`가 없거나 틀리면 네 팀 전부(지금 동작).
- 끄면 Supervisor 프롬프트가 `SUPERVISOR_SYSTEM` 글자 그대로이고 네 팀 전부 돈다(키 없는 데모 녹화 보호). 데모 모드에서는 환경 변수가 켜져 있어도 끈다.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from qgraph_fakes import j
from team_review_fakes import REQUEST, Retriever, review_llm

from backend.graph import service_profile as SP
from backend.graph.departments import issue_table as IT
from backend.graph.departments import review as R
from backend.graph.departments import teams as T
from backend.graph.departments.store import InMemoryIssueTableStore

TEAM_TASKS = ("team_security", "team_infra", "team_itops", "team_finance")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.delenv(R.TEAM_SELECT_ENV, raising=False)
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


def run(llm, team_select=None, question=REQUEST, thread="t1"):
    retriever = Retriever()
    g = R.build_review_graph(retriever, InMemorySaver(), llm=llm, store=InMemoryIssueTableStore(), team_select=team_select)
    cfg = {"configurable": {"thread_id": thread}}
    out = g.invoke({"question": question, "user_id": "u1", "thread_id": thread, "as_of": "2026-11-05"}, cfg)
    return out, g.get_state(cfg).values, retriever


def supervisor_says(**kw):
    return j(missing=[], tasks={"security": "보안을 본다", "infra": "운영을 본다", "itops": "도구 등록을 본다", "finance": "승인권자를 본다"}, **kw)


def test_switch_on_runs_only_the_selected_team_and_marks_the_rest_not_selected():
    llm = review_llm(supervisor=supervisor_says(teams=["finance"]))
    out, state, retriever = run(llm, team_select=True)
    assert state["selected_teams"] == ["finance"]
    assert set(state["team_results"]) == {"finance"}
    assert [llm.count(t) for t in TEAM_TASKS] == [0, 0, 0, 1]          # 고르지 않은 팀은 모델을 부르지 않는다
    assert {q.org for q in retriever.calls} == {"finance"}               # 검색도 고른 팀 절만
    table = out["__interrupt__"][0].value["table"]
    assert table["team_status"] == {"security": "not_selected", "infra": "not_selected", "itops": "not_selected", "finance": "reviewed"}
    assert table["unreviewed"] == []                                     # 고르지 않음은 "검토하지 못함"이 아니다
    assert [s["team"] for s in table["not_selected"]] == ["security", "infra", "itops"]
    assert {r["team"] for r in table["rows"]} == {"finance"}
    assert table["table_hash"] == IT.table_hash(table)                   # 해시 규칙(request·as_of·rows·unreviewed) 그대로
    assert "Supervisor가 고르지 않은 팀 보안, 인프라·SRE, IT 운영" in out["__interrupt__"][0].value["summary"]
    assert llm.systems["supervisor"][0] == T.SUPERVISOR_SYSTEM + T.TEAM_SELECT_RULE


def test_different_inputs_take_different_team_paths():
    def supervisor(user: str) -> str:
        return supervisor_says(teams=["infra"] if "노드 풀" in user else ["security", "finance"])

    llm = review_llm(supervisor=supervisor)
    _, a, _ = run(llm, team_select=True, question="프로덕션 클러스터의 노드 풀을 늘리려 한다.", thread="a")
    _, b, _ = run(llm, team_select=True, question=REQUEST, thread="b")
    assert a["selected_teams"] == ["infra"] and set(a["team_results"]) == {"infra"}
    assert b["selected_teams"] == ["security", "finance"] and set(b["team_results"]) == {"security", "finance"}


@pytest.mark.parametrize("teams", [None, [], ["x"], "finance", [1, None], {"finance": True}])
def test_missing_or_invalid_teams_fall_back_to_all_four(teams):
    sup = supervisor_says() if teams is None else supervisor_says(teams=teams)
    llm = review_llm(supervisor=sup)
    out, state, _ = run(llm, team_select=True)
    assert state["selected_teams"] == list(T.TEAM_IDS)
    assert set(state["team_results"]) == set(T.TEAM_IDS) and [llm.count(t) for t in TEAM_TASKS] == [1, 1, 1, 1]
    table = out["__interrupt__"][0].value["table"]
    assert "not_selected" not in table and set(table["team_status"].values()) == {"reviewed"}


def test_unknown_ids_are_dropped_and_order_follows_the_team_definition():
    llm = review_llm(supervisor=supervisor_says(teams=["FINANCE", "nope", " security "]))
    _, state, _ = run(llm, team_select=True)
    assert state["selected_teams"] == ["security", "finance"]


def test_switch_off_keeps_the_prompt_and_runs_all_four_even_if_teams_are_given():
    llm = review_llm(supervisor=supervisor_says(teams=["finance"]))
    out, state, _ = run(llm, team_select=False)
    assert llm.systems["supervisor"] == [T.SUPERVISOR_SYSTEM]            # 데모 녹화 키가 되는 프롬프트가 바이트 단위로 같다
    assert T.supervisor_system(False) == T.SUPERVISOR_SYSTEM
    assert state["selected_teams"] == list(T.TEAM_IDS) and [llm.count(t) for t in TEAM_TASKS] == [1, 1, 1, 1]
    table = out["__interrupt__"][0].value["table"]
    assert "not_selected" not in table and out["__interrupt__"][0].value["summary"] == IT.summarize(table)


def test_env_switch_and_demo_mode(monkeypatch):
    monkeypatch.setenv(R.TEAM_SELECT_ENV, "1")
    monkeypatch.setattr(R, "is_demo_mode", lambda: True)
    assert R.team_select_enabled() is False                              # 키 없는 데모는 끈다
    monkeypatch.setattr(R, "is_demo_mode", lambda: False)
    assert R.team_select_enabled() is True
    monkeypatch.setenv(R.TEAM_SELECT_ENV, "")
    assert R.team_select_enabled() is False                              # 코드 기본 꺼짐
    llm = review_llm(supervisor=supervisor_says(teams=["finance"]))
    monkeypatch.setenv(R.TEAM_SELECT_ENV, "1")
    _, state, _ = run(llm)                                               # team_select=None이면 환경 변수를 그래프를 만들 때 읽는다
    assert state["selected_teams"] == ["finance"]


def test_selected_team_with_no_issues_says_which_teams_were_reviewed():
    llm = review_llm(supervisor=supervisor_says(teams=["finance"]), team_finance=j(issues=[]))
    out, state, _ = run(llm, team_select=True)
    assert state["review_status"] == "no_issues" and "__interrupt__" not in out
    assert out["answer"].startswith("쟁점 없음: Supervisor가 고른 팀(재무)이 이 요청에서 쟁점을 찾지 못했습니다.")


def test_service_profile_turns_team_select_on_but_demo_stays_off(monkeypatch):
    """사전 등록 62.82(2026-11-17 팀장 결정): 서비스 설정은 팀 선택을 켠다. 같은 로컬 측정기에서 네 팀 전부 0.649(62.36, 3회)와 팀 선택 0.649(1회)가 같고 비용이 준다.
    코드 기본은 꺼짐이고(`DEFAULT_ON_ENV` 아님), 키 없는 데모에서는 서비스 설정을 채워도 꺼진다."""
    assert SP.SERVICE_ENV[R.TEAM_SELECT_ENV] == "1" and R.TEAM_SELECT_ENV not in SP.CANDIDATE_ENV
    assert R.TEAM_SELECT_ENV not in SP.DEFAULT_ON_ENV
    env: dict = {}
    SP.apply_service_profile(env)
    assert env[R.TEAM_SELECT_ENV] == "1"
    monkeypatch.setenv(R.TEAM_SELECT_ENV, env[R.TEAM_SELECT_ENV])
    monkeypatch.setattr(R, "is_demo_mode", lambda: False)
    assert R.team_select_enabled() is True                                # 서비스: 켬
    monkeypatch.setattr(R, "is_demo_mode", lambda: True)
    assert R.team_select_enabled() is False                               # 데모: 끔
    off: dict = {R.TEAM_SELECT_ENV: "off"}
    SP.apply_service_profile(off)
    assert off[R.TEAM_SELECT_ENV] == ""                                   # 운영에서 off를 주면 꺼진다
