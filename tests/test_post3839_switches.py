"""38, 39번 사후 진단 스위치 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

스위치(`GRAPH_KEEP_PRODUCT_NAME`, `GRAPH_REQUERY_TERMS`)는 기본 꺼짐이고,
꺼져 있으면 그래프의 프롬프트와 첫 검색어가 #44 측정 구성과 같아야 한다.
"""
from __future__ import annotations

import argparse
import re

import pytest
from fake_search import fake_search
from qgraph_fakes import ScriptedLLM, j, normal_llm

from backend.graph import decompose as dec
from backend.graph.build import build_graph
from backend.prompts import question as P
from backend.services.skills import SKILL_NAMES, load_skill
from evals.agent import exp_multi_v2 as M

SWITCHES = ("GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS")
NEW_RULES = (P.JUDGE_TERMS_RULE,)


class RecordingLLM(ScriptedLLM):
    """시스템 프롬프트도 기록한다."""

    def __init__(self, handlers):
        super().__init__(handlers)
        self.systems: dict[str, list[str]] = {}

    def invoke(self, messages, *a, **k):
        task = re.search(r"\[\[task:(\w+)\]\]", messages[0].content).group(1)
        self.systems.setdefault(task, []).append(messages[0].content)
        return super().invoke(messages, *a, **k)


def answer_top(user):
    cid = re.search(r"chunk_id=([0-9a-f]{16})", user).group(1)
    return j(asked=["사실"], picks=[], answer=f"답 [{cid}]", citations=[{"chunk_id": cid}], period_covered=True)


def llm():
    return RecordingLLM({**normal_llm().handlers, "decompose": j(split=False, sub_questions=[]), "answer": answer_top,
                         "grounding": j(reason="", grounded=True)})


@pytest.fixture(autouse=True)
def _m44(monkeypatch):
    """#44 측정의 프롬프트 스위치(구조화 칸, 판정 재검색어, 짧은 이유)를 켜고 새 스위치는 지운다."""
    for name in (*SWITCHES, "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def run(g, question="SEV2 장애 최초 대응은 몇 분 이내인가요?"):
    return g.invoke({"question": question, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})


def expected_m44_judge() -> str:
    """스위치가 없던 때(#44)의 판정 프롬프트 조립 그대로."""
    system = P.judge_checked(P.judge_with_query(P.JUDGE_SYSTEM_BRIEF), query=True)
    return P.with_skills(system, [("도구 고르기 Skill", load_skill("chat-tool-guide", enabled=True))])


# ---------- 기본 꺼짐: #44 구성과 같다 ----------
def test_switches_off_keep_the_m44_prompts():
    m = llm()
    run(build_graph(fake_search, llm=m, brief_output=True, decompose=True, grounding_llm=True))
    assert m.systems["judge"][0] == expected_m44_judge()
    assert m.systems["answer"][0].startswith(P.answer_picked(P.ANSWER_SYSTEM))
    for task, systems in m.systems.items():
        for s in systems:
            assert not any(rule in s for rule in NEW_RULES), task
            assert "재검색어 용어표" not in s


def test_switches_off_in_the_runner_are_empty_values():
    p = argparse.ArgumentParser()
    for flag in ("--keep-product-name", "--requery-terms", "--query-branches",
                 "--cite-expand", "--cite-multi", "--team-last", "--keep-cites", "--sub-research", "--page-research", "--requery-vocab", "--unknown-name",
                 "--refuse-on-none", "--research-same-page", "--cite-phrase", "--grounding-quote", "--drop-scoped-cites", "--intro-fill",
                 "--scope-note-refuse", "--cite-pick", "--requery-skip-seen", "--cite-consensus", "--pointer-refuse", "--speculate-first", "--unchanged-rejudge", "--prompts-head",
                 "--judge-vote", "--judge-quote", "--sub-merge", "--facts-log", "--answer-best2", "--best2-samedoc", "--speculate-ground"):
        p.add_argument(flag, action="store_true")
    ns = p.parse_args([])
    keys = {"reasoning": "", "provider_sort": "", "llm_deadline": "", "llm_hedge": "", "llm_retries": "", "trace_detail": False, "json_reminder": False,
            "reasoning_by_task": "", "section_keeps_research": False, "answer_wait": 0, "answer_budget": 0, "structured": "", "judge_query": False,
            "embed_keepalive": False, "parallel_subs": False, "decompose_cap": 0, "search_hedge": 0}
    for k, v in keys.items():
        setattr(ns, k, v)
    got = M.chosen_model_switches(ns)
    assert all(got[name] == "" for name in SWITCHES)


@pytest.mark.parametrize("question,want", [
    ("GitLab 계정 2FA 초기화 요청은 어떻게 처리해?", "계정 2FA 초기화 요청은 어떻게 처리해?"),  # 꺼짐: 이전과 같이 뗀다
    ("GitLab 정기 릴리스는 언제 나가?", "정기 릴리스는 언제 나가?"),
])
def test_company_name_rule_is_unchanged_when_off(question, want):
    assert dec.drop_company_prefix([question]) == [want]


# ---------- (a) 회사 이름 ----------
@pytest.mark.parametrize("question,want", [
    ("GitLab 계정 2FA 초기화 요청은 어떻게 처리해?", "GitLab 계정 2FA 초기화 요청은 어떻게 처리해?"),
    ("GitLab 그룹 소유자는 누구야?", "GitLab 그룹 소유자는 누구야?"),
    ("gitlab project 삭제는 어떻게 해?", "gitlab project 삭제는 어떻게 해?"),
    ("GitLab 정기 릴리스는 언제 나가?", "정기 릴리스는 언제 나가?"),  # v1 3번: 그대로 뗀다
    ("GitLab의 패치 릴리스는 몇 번 나가?", "패치 릴리스는 몇 번 나가?"),
    ("GitLab의 계정 정책은 뭐야?", "계정 정책은 뭐야?"),  # 조사가 붙으면 회사다
    ("GitLab에서 온콜은 누가 해?", "온콜은 누가 해?"),
    ("GitLab.com 가용률은 얼마야?", "GitLab.com 가용률은 얼마야?"),
])
def test_keep_product_name_keeps_only_product_targets(monkeypatch, question, want):
    monkeypatch.setenv("GRAPH_KEEP_PRODUCT_NAME", "1")
    assert dec.drop_company_prefix([question]) == [want]


def test_keep_product_name_reaches_the_first_search(monkeypatch):
    seen = []

    def fn(q):
        seen.append(q)
        return fake_search(q)

    q = "GitLab 계정 2FA 초기화 요청은 어떻게 처리해?"
    run(build_graph(fn, llm=llm(), decompose=True), question=q)
    assert seen[0].query == "계정 2FA 초기화 요청은 어떻게 처리해?"
    monkeypatch.setenv("GRAPH_KEEP_PRODUCT_NAME", "1")
    seen.clear()
    run(build_graph(fn, llm=llm(), decompose=True), question=q)
    assert seen[0].query == q


# ---------- 프롬프트 스위치 ----------


def test_requery_terms_attaches_the_terms_skill_only_with_judge_query(monkeypatch):
    monkeypatch.setenv("GRAPH_REQUERY_TERMS", "1")
    m = llm()
    out = run(build_graph(fake_search, llm=m, brief_output=True, decompose=True, grounding_llm=True))
    s = m.systems["judge"][0]
    assert P.JUDGE_TERMS_RULE in s and "[용어 Skill]" in s and "재검색어 용어표" not in s.split("[용어 Skill]")[0]
    assert "search-terms" in out["skills_used"]
    monkeypatch.delenv("GRAPH_JUDGE_QUERY")
    m = llm()
    run(build_graph(fake_search, llm=m, brief_output=True, decompose=True, grounding_llm=True))
    assert P.JUDGE_TERMS_RULE not in m.systems["judge"][0] and "[용어 Skill]" not in m.systems["judge"][0]


def test_add_rule_keeps_the_output_example():
    s = P._add_rule(P.JUDGE_SYSTEM, "- 새 규칙")
    assert s.endswith(P.JUDGE_SYSTEM.rpartition("JSON 한 개만 출력한다.")[2])
    assert "- 새 규칙\nJSON 한 개만 출력한다." in s


# ---------- Skill ----------
def test_search_terms_skill_is_registered_and_well_formed():
    assert "search-terms" in SKILL_NAMES
    body = load_skill("search-terms", enabled=True)
    assert body and load_skill("search-terms", enabled=False) == ""
    assert "<<<" not in body and "## 출력 형식" in body and "## 출처" in body and "3차에서 새로 작성했다" in body


# ---------- 대조군: HEAD 때 기본 프롬프트(`GRAPH_PROMPTS_HEAD`) ----------
def _base_lines():
    return [ln for sp in P.SYSTEM_PROMPTS for ln in sp.split("\n")]


def test_prompts_head_is_off_by_default_and_keeps_every_prompt():
    for sp in (*P.SYSTEM_PROMPTS, P.judge_checked(P.judge_with_query(P.JUDGE_SYSTEM_BRIEF), query=True), P.grounding_quoted(P.GROUNDING_SYSTEM_BRIEF)):
        assert P.at_head(sp) == sp


def test_prompts_head_entries_each_hit_one_base_line(monkeypatch):
    lines = _base_lines()
    for head in P.HEAD_DROP_LINES:
        assert sum(ln.startswith(head) for ln in lines) == 1, head
    for tail in P.HEAD_DROP_TAILS:
        assert sum(ln.endswith(tail) for ln in lines) == 1, tail
    assert P.HEAD_EXAMPLE_CUT in P.JUDGE_SYSTEM.split("\n")[-1]
    monkeypatch.setenv("GRAPH_PROMPTS_HEAD", "1")
    for sp in P.SYSTEM_PROMPTS:
        got = P.at_head(sp)
        assert got.split("\n")[0] == sp.split("\n")[0] and got.endswith("}") and "JSON 한 개만 출력한다." in got
        assert not any(ln.startswith(P.HEAD_DROP_LINES) or ln.endswith(P.HEAD_DROP_TAILS) for ln in got.split("\n"))
    assert P.HEAD_EXAMPLE_CUT not in P.at_head(P.JUDGE_SYSTEM)


def test_prompts_head_keeps_switch_rules(monkeypatch):
    monkeypatch.setenv("GRAPH_PROMPTS_HEAD", "1")
    judge = P.judge_terms(P.judge_checked(P.judge_with_query(P.JUDGE_SYSTEM_BRIEF), query=True))
    got = P.at_head(judge)
    assert P.JUDGE_TERMS_RULE in got and P.JUDGE_QUERY_RULE in got and '"checks"' in got and judge.split("\n")[-1] == got.split("\n")[-1]
    ground = P.grounding_quoted(P.GROUNDING_SYSTEM_BRIEF)
    assert P.GROUNDING_QUOTE_RULES in P.at_head(ground)


def test_prompts_head_drops_the_input_notes(monkeypatch):
    chunks = [{"chunk_id": "a" * 16, "rule_title": "Code Review", "article": "SLA", "text": "x"}]
    on = {"judge": P.judge_user("q", chunks, ["s1", "s2"]), "answer": P.answer_user("q", chunks, None, partial=True, scope_note="note"),
          "grounding": P.grounding_user("q", "a", chunks, None, partial=True), "rewrite": P.rewrite_user("q", {}, "why", missing=["m"], seen=["T"])}
    monkeypatch.setenv("GRAPH_PROMPTS_HEAD", "1")
    head = {"judge": P.judge_user("q", chunks, ["s1", "s2"]), "answer": P.answer_user("q", chunks, None, partial=True, scope_note="note"),
            "grounding": P.grounding_user("q", "a", chunks, None, partial=True), "rewrite": P.rewrite_user("q", {}, "why", missing=["m"], seen=["T"])}
    assert head["judge"] == P.judge_user("q", chunks) != on["judge"]
    assert "범위 메모" not in head["answer"] and "범위 메모" in on["answer"] and "질문의 일부는 근거를 찾지 못했다" in head["answer"]
    assert head["grounding"] == P.grounding_user("q", "a", chunks, None) != on["grounding"]
    assert head["rewrite"] == "소속·직급: 없음\n질문: q\n이전 검색이 부족했던 사유: why" != on["rewrite"]


def test_prompts_head_reaches_the_model(monkeypatch):
    monkeypatch.setenv("GRAPH_PROMPTS_HEAD", "1")
    m = llm()
    run(build_graph(fake_search, llm=m, brief_output=True, decompose=True, grounding_llm=True))
    assert m.systems["judge"][0] == P.at_head(expected_m44_judge()) != expected_m44_judge()
    for systems in m.systems.values():
        for s in systems:
            assert not any(ln.startswith(P.HEAD_DROP_LINES) for ln in s.split("\n"))