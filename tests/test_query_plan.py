"""첫 검색어 코드 보강(`GRAPH_QUERY_TERMS`, `GRAPH_QUERY_BRANCHES`) 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

두 스위치는 기본 꺼짐이고, 꺼져 있으면 첫 검색어, 하위 질문, 답 입력이 #44 측정 구성과 같아야 한다.
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
    for name in ("GRAPH_QUERY_TERMS", "GRAPH_QUERY_BRANCHES", "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", 
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
@pytest.mark.parametrize("text,want", [
    ("새 SaaS 도구 도입 요청은 어디서 시작해?", "새 SaaS 도구 도입 요청은 어디서 시작해? (procurement, purchase request, new vendor)"),
    ("보안 검토(TPRM)는 언제 필요해?", "보안 검토(TPRM)는 언제 필요해? (TPRM, third party risk management assessment)"),
    ("소프트웨어를 구매하려면 어떻게 해?", "소프트웨어를 구매하려면 어떻게 해? (procurement, purchase request, new vendor)"),
    ("별도 데이터베이스나 마이크로서비스를 새로 도입하자고 제안하려면 누구 승인을 받아야 해?", None),  # 도구, 소프트웨어, 업체가 없다
    ("같은 벤더와 계약을 한 번 승인받은 뒤 추가 계약 금액은?", None),  # 구매, 도입이 없다
    ("EU DORA 규정에서 요구하는 ICT 제3자 계약 필수 조항이 뭐야?", None),
    ("x (procurement, purchase request, new vendor) 도구 도입", None),  # 이미 다 있으면 붙이지 않는다
])
def test_term_rows(text, want):
    assert QP.add_terms(text) == (want or text)


@pytest.mark.parametrize("text", ["5만 달러짜리 SaaS 도입은 누가 승인해?", "500만 원짜리 도구 구매 승인은?", "$50K SaaS purchase", "3,000 유로 소프트웨어 구매",
                                  "10000엔 앱 구매", "USD 2,000", "20 dollars", "₩300,000 툴", "1억원 솔루션 도입", "2 million USD",
                                  "10K 도구 구매", "1억 넘는 소프트웨어 구매", "50,000달러"])  # 통화 단어 없는 K·억도 금액(리뷰 보완)
def test_mentions_money_finds_currency_amounts(text):
    assert QP.mentions_money([text]) and QP.mentions_money([None, "x", text])


@pytest.mark.parametrize("text", ["금액 기준으로 누가 승인해?", "접근 권한은 60일마다 검토해?", "2FA 초기화는 어떻게 해?", "3개월 안에 끝내야 해?",
                                  "새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?", "SEV2 장애 최초 대응은 몇 분 이내인가요?",
                                  "3만 원격 근무자 장비 구매는?", "5천 원칙", "직원 5천 명이 쓰는 도구 구매", "90일", "2FA", "CVSS 9.0"])  # 셈 단위·원으로 시작하는 낱말은 금액 아님
def test_mentions_money_ignores_other_numbers(text):
    assert not QP.mentions_money([text]) and not QP.mentions_money([]) and not QP.mentions_money([None])


def test_branch_rule_needs_topic_without_audience():
    assert QP.branch_rule(ACCOUNT_Q) is not None
    assert QP.branch_rule("비밀번호를 잊어버렸어") is not None
    assert QP.branch_rule("사내 비밀번호 표준에서 최소 길이는 몇 자야?") is None  # 대상(사내)이 있다
    assert QP.branch_rule("고객 계정 2FA 초기화는?") is None
    assert QP.branch_rule("코드 리뷰는 며칠 안에 해야 해?") is None


def test_plan_is_identity_when_both_switches_are_off():
    p = QP.plan_first_search(ACCOUNT_Q, "계정 2FA 초기화 요청은 어떻게 처리해?", ["a 도구 도입", "b"], terms=False, branches=False)
    assert (p.query, p.subs, p.targets) == ("계정 2FA 초기화 요청은 어떻게 처리해?", ["a 도구 도입", "b"], [])


def test_plan_splits_an_unsplit_question_by_target():
    p = QP.plan_first_search(ACCOUNT_Q, "계정 2FA 초기화 요청은 어떻게 처리해?", [], terms=False, branches=True)
    assert p.subs == ["계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)", "계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)"]
    assert p.targets == ["GitLab 팀원", "GitLab.com 사용자(고객)"]


def test_plan_splits_only_the_matching_sub_and_keeps_the_sub_limit():
    p = QP.plan_first_search("계정 잠김은 어떻게 풀고 온콜은 누가 해?", "q", ["계정 잠김은 어떻게 풀어?", "온콜은 누가 해?"], terms=False, branches=True)
    assert p.subs == ["계정 잠김은 어떻게 풀어? (대상: GitLab 팀원)", "계정 잠김은 어떻게 풀어? (대상: GitLab.com 사용자, 고객)", "온콜은 누가 해?"]
    three = ["계정 잠김은 어떻게 풀어?", "온콜은 누가 해?", "릴리스는 언제야?"]
    p = QP.plan_first_search("계정 잠김, 온콜, 릴리스", "q", three, terms=False, branches=True)
    assert p.subs == three and p.targets == []  # 4개가 되면 나누지 않는다


def test_plan_terms_apply_to_subs_or_the_query():
    p = QP.plan_first_search("q", "새 도구 도입은?", [], terms=True, branches=False)
    assert p.query.endswith("(procurement, purchase request, new vendor)") and p.subs == []
    p = QP.plan_first_search("q", "전체", ["새 도구 도입은?", "TPRM은 언제?"], terms=True, branches=False)
    assert p.query == "전체" and p.subs[0].endswith("new vendor)") and p.subs[1].endswith("assessment)")


def test_plan_splits_by_target_before_adding_terms():
    p = QP.plan_first_search("계정 잠김은 어떻게 풀고 새 도구 도입은?", "q", ["계정 잠김은 어떻게 풀어?", "새 도구 도입은?"], terms=True, branches=True)
    assert p.subs[:2] == ["계정 잠김은 어떻게 풀어? (대상: GitLab 팀원)", "계정 잠김은 어떻게 풀어? (대상: GitLab.com 사용자, 고객)"]
    assert p.subs[2].endswith("(procurement, purchase request, new vendor)")


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
    assert off["GRAPH_QUERY_TERMS"] == "" and off["GRAPH_QUERY_BRANCHES"] == ""
    on = M.chosen_model_switches(_args(["--query-terms", "--query-branches"]))
    assert on["GRAPH_QUERY_TERMS"] == "1" and on["GRAPH_QUERY_BRANCHES"] == "1"


# ---------- 그래프: 켬 ----------
Q_TOOL = "새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?"
SUBS_TOOL = ["새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]


def test_query_terms_reach_the_first_search_only(monkeypatch):
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    fn, seen = recording_search()
    m = make_llm(subs=SUBS_TOOL)
    run(build_graph(fn, llm=m, decompose=True), Q_TOOL)
    assert seen[0].sub_queries[0].endswith("(procurement, purchase request, new vendor)")
    assert seen[0].sub_queries[1].endswith("(TPRM, third party risk management assessment)")
    assert all(q.sub_queries is None for q in seen[1:])  # 재검색은 그대로다


def test_query_terms_attach_to_an_unsplit_question(monkeypatch):
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    fn, seen = recording_search()
    run(build_graph(fn, llm=make_llm(), decompose=True), "새 SaaS 도구 도입 요청은 어디서 시작해?")
    assert seen[0].sub_queries is None and seen[0].query.endswith("(procurement, purchase request, new vendor)")


@pytest.mark.parametrize("amount", ["5만 달러", "500만 원", "$50K"])
def test_query_terms_skip_a_question_with_money(monkeypatch, amount):
    """62.69: 질문에 통화 금액이 있으면 덧붙이지 않는다. 검색 입력이 스위치를 끈 것과 같다."""
    q = f"{amount}짜리 새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?"
    subs = [f"{amount}짜리 새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]
    fn_off, off = recording_search()
    run(build_graph(fn_off, llm=make_llm(subs=subs), decompose=True), q)
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    fn_on, on = recording_search()
    run(build_graph(fn_on, llm=make_llm(subs=subs), decompose=True), q)
    assert [(x.query, x.sub_queries, x.k) for x in on] == [(x.query, x.sub_queries, x.k) for x in off]


def test_query_terms_skip_when_only_a_sub_has_money(monkeypatch):
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    fn, seen = recording_search()
    run(build_graph(fn, llm=make_llm(subs=["5만 달러 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]), decompose=True), Q_TOOL)
    assert seen[0].sub_queries == ["5만 달러 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]


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
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    fn, seen = recording_search()
    m = make_llm()
    out = run(build_graph(fn, llm=m, decompose=True), "SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert seen[0].sub_queries is None and seen[0].query == "SEV2 장애 최초 대응은 몇 분 이내인가요?"
    assert out.get("query_targets") == [] and all(NOTE not in u for t, u in m.calls if t == "answer")
