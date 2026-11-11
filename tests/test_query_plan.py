"""첫 검색어 코드 보강(`GRAPH_QUERY_BRANCHES`) 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

스위치는 기본 꺼짐이고, 꺼져 있으면 첫 검색어, 하위 질문, 답 입력이 #44 측정 구성과 같아야 한다.
"""
from __future__ import annotations

import re

import pytest
from fake_search import fake_search
from qgraph_fakes import ScriptedLLM, j, normal_llm

from backend.graph import query_plan as QP
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from evals.agent import exp_multi_v2 as M

ACCOUNT_Q = "GitLab 계정 2FA 초기화 요청은 어떻게 처리해?"
NOTE = "대상에 따라 절차가 갈린다"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_QUERY_BRANCHES", "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", 
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def answer_with(text_for):
    """답 handler: user를 받아 답 문장을 정한다. 첫 자료를 인용한다."""
    def handler(user):
        cid = re.search(r"chunk_id=([0-9a-f]{16})", user).group(1)
        return j(asked=["사실"], picks=[], answer=f"{text_for(user)} [{cid}]", citations=[{"chunk_id": cid}], period_covered=True)
    return handler


def make_llm(subs=(), answer=None):
    split = j(split=bool(subs), sub_questions=list(subs))
    return ScriptedLLM({**normal_llm().handlers, "decompose": split, "answer": answer or answer_with(lambda u: "답"),
                        "grounding": j(reason="", grounded=True)})


def recording_search():
    seen = []

    def fn(q):
        seen.append(q)
        return fake_search(q)
    return fn, seen


def run(g, question):
    return g.invoke({"question": question, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})


# ---------- 표 ----------
def test_branch_rule_needs_topic_without_audience():
    assert QP.branch_rule(ACCOUNT_Q) is not None
    assert QP.branch_rule("비밀번호를 잊어버렸어") is not None
    assert QP.branch_rule("사내 비밀번호 표준에서 최소 길이는 몇 자야?") is None  # 대상(사내)이 있다
    assert QP.branch_rule("고객 계정 2FA 초기화는?") is None
    assert QP.branch_rule("코드 리뷰는 며칠 안에 해야 해?") is None


def test_plan_is_identity_when_both_switches_are_off():
    p = QP.plan_first_search(ACCOUNT_Q, "계정 2FA 초기화 요청은 어떻게 처리해?", ["a 도구 도입", "b"], branches=False)
    assert (p.query, p.subs, p.targets) == ("계정 2FA 초기화 요청은 어떻게 처리해?", ["a 도구 도입", "b"], [])


def test_plan_splits_an_unsplit_question_by_target():
    p = QP.plan_first_search(ACCOUNT_Q, "계정 2FA 초기화 요청은 어떻게 처리해?", [], branches=True)
    assert p.subs == ["계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)", "계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)"]
    assert p.targets == ["GitLab 팀원", "GitLab.com 사용자(고객)"]


def test_plan_splits_only_the_matching_sub_and_keeps_the_sub_limit():
    p = QP.plan_first_search("계정 잠김은 어떻게 풀고 온콜은 누가 해?", "q", ["계정 잠김은 어떻게 풀어?", "온콜은 누가 해?"], branches=True)
    assert p.subs == ["계정 잠김은 어떻게 풀어? (대상: GitLab 팀원)", "계정 잠김은 어떻게 풀어? (대상: GitLab.com 사용자, 고객)", "온콜은 누가 해?"]
    three = ["계정 잠김은 어떻게 풀어?", "온콜은 누가 해?", "릴리스는 언제야?"]
    p = QP.plan_first_search("계정 잠김, 온콜, 릴리스", "q", three, branches=True)
    assert p.subs == three and p.targets == []  # 4개가 되면 나누지 않는다


def test_missing_targets_and_note():
    t = ["GitLab 팀원", "GitLab.com 사용자(고객)"]
    assert QP.missing_targets("팀원은 IT Ops에 문의하고 고객은 그룹 소유자가 요청한다", t) == []
    assert QP.missing_targets("고객은 그룹 소유자가 요청한다", t) == ["GitLab 팀원"]
    assert QP.missing_targets("아무 말", []) == []
    assert QP.targets_note([]) == ""
    assert NOTE in QP.targets_note(t) and "빠뜨렸다: GitLab 팀원" in QP.targets_note(t, ["GitLab 팀원"])


# ---------- 그래프: 기본 꺼짐 ----------
def test_switches_off_keep_the_m44_first_search_and_answer_input():
    fn, seen = recording_search()
    m = make_llm(subs=["새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"])
    out = run(build_graph(fn, llm=m, decompose=True), "새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?")
    assert seen[0].sub_queries == ["새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]
    assert "query_targets" not in out
    assert all(NOTE not in u for t, u in m.calls if t == "answer")
    fn, seen = recording_search()
    m = make_llm()
    run(build_graph(fn, llm=m, decompose=True), ACCOUNT_Q)
    assert seen[0].query == "계정 2FA 초기화 요청은 어떻게 처리해?" and seen[0].sub_queries is None
    assert all(NOTE not in u for t, u in m.calls if t == "answer")


def _args(argv):
    seen = []
    saved = M.run_cmd
    M.run_cmd = lambda a: seen.append(a) or 0
    try:
        M.main(["run", "--out", "x", *argv])
    finally:
        M.run_cmd = saved
    return seen[0]


def test_runner_maps_the_new_flags():
    off = M.chosen_model_switches(_args([]))
    assert off["GRAPH_QUERY_BRANCHES"] == ""
    on = M.chosen_model_switches(_args(["--query-branches"]))
    assert on["GRAPH_QUERY_BRANCHES"] == "1"


# ---------- 그래프: 켬 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_query_branches_split_the_search_and_check_the_answer(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_QUERY_BRANCHES", "1")
    fn, seen = recording_search()
    m = make_llm(answer=answer_with(lambda u: "팀원은 IT에 문의한다" if "빠뜨렸다" not in u else "팀원은 IT에, 고객은 그룹 소유자가 요청한다"))
    g = build_multi_graph(fn, llm=m, decompose=True, judge_answer="parallel_all") if multi else build_graph(fn, llm=m, decompose=True, judge_answer="parallel_all")
    out = run(g, ACCOUNT_Q)
    assert seen[0].sub_queries == ["계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)", "계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)"]
    answers = [u for t, u in m.calls if t == "answer"]
    assert NOTE in answers[0] and "빠뜨렸다: GitLab.com 사용자(고객)" in answers[1]
    assert "고객" in out["answer"]


def test_query_branches_do_not_redraft_a_complete_answer(monkeypatch):
    monkeypatch.setenv("GRAPH_QUERY_BRANCHES", "1")
    m = make_llm(answer=answer_with(lambda u: "팀원은 IT에, 고객은 그룹 소유자가 요청한다"))
    run(build_graph(fake_search, llm=m, decompose=True), ACCOUNT_Q)
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 1 and NOTE in answers[0]


def test_query_branches_leave_other_questions_alone(monkeypatch):
    monkeypatch.setenv("GRAPH_QUERY_BRANCHES", "1")
    fn, seen = recording_search()
    m = make_llm()
    out = run(build_graph(fn, llm=m, decompose=True), "SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert seen[0].sub_queries is None and seen[0].query == "SEV2 장애 최초 대응은 몇 분 이내인가요?"
    assert out.get("query_targets") == [] and all(NOTE not in u for t, u in m.calls if t == "answer")
