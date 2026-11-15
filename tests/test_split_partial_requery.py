"""사전 등록 62.63: 나뉜 질문(하위 질문 2개 이상)의 판정이 일부이면 재검색과 섹션 읽기 없이 같이 쓴 답을 일부 답으로 낸다.
나뉘지 않은 질문, 전무 판정, 표가 갈린 전무 판정(사전 등록 62.33)은 그대로다. 가짜 모델과 가짜 검색기만 쓴다(LLM·Voyage·운영 호출 없음)."""
from __future__ import annotations

import threading

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, IMOC, PARTIAL, Q_ESC, SUBS, cite, llm, run

from backend.graph.build import MSG_PARTIAL_NOTE, build_graph
from backend.graph.multi import build_multi_graph

OK = j(sufficient=True, reason="", clarify=None)
NONE = j(checks=[], sufficient=False, partial=False, reason="관련 규정 없음", missing=["EOC 무응답 단계"], scope_note=None, clarify=None, query="EOC escalation")
SPLIT = j(split=True, sub_questions=SUBS)
NO_SPLIT = j(split=False, sub_questions=[])
SWITCHES = ("GRAPH_REFUSE_ON_NONE", "GRAPH_RESEARCH_SAME_PAGE", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_JUDGE_VOTE", "GRAPH_SCOPE_NOTE_REFUSE",
            "GRAPH_SPECULATE_GROUND", "GRAPH_JUDGE_ANSWER", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_SECTION_KEEPS_RESEARCH",
            "GRAPH_REQUERY_SKIP_SEEN", "GRAPH_SPECULATE_FIRST", "SEARCH_DECOMPOSE", "USE_SKILLS")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def graph(multi, fn, m, **kw):
    return build_multi_graph(fn, llm=m, **kw) if multi else build_graph(fn, llm=m, **kw)


def recorder(result):
    seen: list = []

    def fn(q):
        seen.append(q)
        return list(result)
    return fn, seen


def page_recorder(found):
    pages: list = []

    def page_search(query, seqs, org, as_of, k):
        if query == Q_ESC:   # 사전 등록 62.55: 나뉜 질문의 첫 검색 뒤 같은 페이지 보충 검색은 여기서 세지 않는다
            return []
        pages.append((query, list(seqs)))
        return [c for c in found if c.rule_seq in seqs]
    return page_search, pages


def judges(m) -> int:
    return sum(1 for t, _ in m.calls if t == "judge")


def in_order(*outs):
    lock, n = threading.Lock(), [0]

    def h(_user):
        with lock:
            i = n[0]
            n[0] += 1
        return outs[min(i, len(outs) - 1)]
    return h


# ---------- (1) 나뉜 질문 + 첫 판정 일부 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_split_question_with_a_partial_first_judgement_answers_partially_without_requery(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    fn, seen = recorder([ESC])
    page_search, pages = page_recorder([IMOC])
    m = llm(decompose=SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE in out["answer"]      # 일부 답 안내 문구
    assert len(seen) == 1 and judges(m) == 1 and pages == []                  # 검색 1회, 판정 1회, 페이지 재검색 없음
    assert "page_requeries" not in (out.get("search_stats") or {}) and out["retries"] == 1
    assert [c["chunk_id"] for c in out["citations"]] == [ESC.chunk_id]        # 첫 문맥에서 나온 답이다


@pytest.mark.parametrize("multi", [False, True])
def test_split_partial_also_skips_the_global_requery(multi):
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, max_research=2), Q_ESC)
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE in out["answer"] and len(seen) == 1 and judges(m) == 1


# ---------- (2) 나뉘지 않은 질문의 일부 판정 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_unsplit_question_with_a_partial_judgement_still_requeries_the_page(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    fn, seen = recorder([ESC])
    page_search, pages = page_recorder([IMOC])
    m = llm(decompose=NO_SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert out["kind"] == "answer" and len(seen) == 1 and pages == [("EOC escalation", [ESC.rule_seq])]
    assert out["search_stats"].get("page_requeries") == 1 and judges(m) == 2
    assert IMOC.chunk_id in [c["chunk_id"] for c in out["chunks"]]


@pytest.mark.parametrize("multi", [False, True])
def test_unsplit_question_with_a_partial_judgement_still_ends_in_a_refusal_when_the_research_is_used_up(multi):
    fn, seen = recorder([ESC])
    m = llm(decompose=NO_SPLIT, judge=PARTIAL, answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "refuse" and len(seen) == 2 and judges(m) == 2    # 사실이 하나인 질문의 "일부"는 거절이다


# ---------- (3) 전무 판정 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_unanimous_none_refuses_at_once_and_split_votes_still_research(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_REFUSE_ON_NONE", "1")
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=NONE, answer=lambda u: cite(ESC), grounding=j(reason="", grounded=True))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, grounding_llm=True), Q_ESC)
    assert out["kind"] == "refuse" and out.get("judge_none") is True and len(seen) == 1 and judges(m) == 3   # 표 3개 모두 전무: 바로 거절
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=in_order(NONE, OK, NONE, OK), answer=lambda u: cite(ESC), grounding=j(reason="", grounded=True))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, grounding_llm=True), Q_ESC)
    assert out["kind"] == "answer" and not out.get("judge_none") and len(seen) == 2                          # 전무 2표, 충분 1표: 재검색 뒤 다시 판정한다


@pytest.mark.parametrize("multi", [False, True])
def test_none_judgement_without_the_refuse_switch_still_researches_a_split_question(multi):
    fn, seen = recorder([ESC, IMOC])
    m = llm(decompose=SPLIT, judge=[NONE, OK], answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "answer" and len(seen) == 2 and judges(m) == 2


# ---------- (4) 섹션 읽기 ----------
def _read_section_judge():
    return j(checks=[], sufficient=False, partial=True, reason="일부", missing=["IMOC 무응답 단계"], scope_note=None, clarify=None, query="IMOC",
             next_tool="get_section", chunk_id=ESC.chunk_id)


@pytest.mark.parametrize("multi", [False, True])
def test_split_partial_does_not_read_the_section_the_judge_picked(multi):
    reads: list = []

    def reader(rule_seq, article, as_of):
        reads.append(article)
        return {"text": ESC.text, "version_id": ESC.version_id}
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=[_read_section_judge(), OK], answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, use_skills=True, section_reader=reader), Q_ESC)
    assert out["kind"] == "answer" and reads == [] and out["search_stats"].get("section_reads", 0) == 0 and len(seen) == 1 and judges(m) == 1


def test_unsplit_partial_still_reads_the_section_the_judge_picked():
    reads: list = []

    def reader(rule_seq, article, as_of):
        reads.append(article)
        return {"text": ESC.text, "version_id": ESC.version_id}
    fn, seen = recorder([ESC])
    m = llm(decompose=NO_SPLIT, judge=[_read_section_judge(), OK], answer=lambda u: cite(ESC))
    out = run(build_graph(fn, llm=m, decompose=True, max_research=1, use_skills=True, section_reader=reader), Q_ESC)
    assert out["kind"] == "answer" and len(reads) == 1 and out["search_stats"]["section_reads"] == 1 and len(seen) == 1


# ---------- (5) 범위 메모로 충분을 일부로 바꾼 경우 ----------
NOTE = "IMOC 자료는 다른 팀에 한정된 절차이며 일반 IMOC 절차는 자료에 없음"


@pytest.mark.parametrize("multi", [False, True])
def test_scope_note_turned_partial_drops_the_early_answer_and_writes_a_new_one(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SCOPE_NOTE_REFUSE", "1")
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "3")
    note = j(checks=[], sufficient=True, partial=False, reason="", missing=[], clarify=None, query="IMOC", scope_note=NOTE)
    users: list = []

    def answer(u):
        users.append(u)
        return cite(ESC, text="새 답" if NOTE in u else "같이 쓴 답")
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=note, answer=answer, answer_fast=answer)
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "answer" and len(seen) == 1 and judges(m) == 1       # 재검색 없이 끝난다
    assert out["answer"].startswith("새 답") and MSG_PARTIAL_NOTE in out["answer"]   # 판정 전에 같이 쓴 답이 아니라 범위 메모를 받아 새로 쓴 답이다
    assert any(NOTE not in u for u in users) and any(NOTE in u for u in users)


# ---------- (6) 일부 답의 근거 확인을 미리 부른다 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_partial_answer_uses_the_grounding_verdict_called_ahead(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "3")
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(ESC), grounding=j(reason="", grounded=True))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, grounding_llm=True), Q_ESC)
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE in out["answer"] and len(seen) == 1 and judges(m) == 1
    assert out["grounding"]["ground_ahead"] is True and out["grounding"]["partial_route"] is True


def test_partial_answer_without_the_speculative_switch_grounds_after_the_judge(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "3")
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(ESC), grounding=j(reason="", grounded=True))
    out = run(build_graph(fn, llm=m, decompose=True, max_research=1, grounding_llm=True), Q_ESC)
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE in out["answer"] and "ground_ahead" not in out["grounding"]


# ---------- (7) 하위 질문 재검색(B1)·페이지 재검색(B4)을 켠 구성 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_sub_and_page_research_switches_still_search_the_missing_sub_once(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SUB_RESEARCH", "1")
    monkeypatch.setenv("GRAPH_PAGE_RESEARCH", "1")
    seen: list = []

    def fn(q):
        seen.append(q)
        return [IMOC] if q.query == SUBS[1] else [ESC]
    page_search, pages = page_recorder([IMOC])
    m = llm(decompose=SPLIT, judge=[PARTIAL, OK], answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, fn, m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert out["kind"] == "answer" and out["sub_research_phase"] == "done"
    assert [q.query for q in seen][-1] == SUBS[1] and pages == [(SUBS[1], [ESC.rule_seq])]     # 빠진 하위 질문 재검색은 한 번
    assert IMOC.chunk_id in [c["chunk_id"] for c in out["chunks"]] and judges(m) == 2


def test_after_judge_rule_is_the_only_new_branch():
    """나뉜 질문의 일부 판정이 아닌 모든 경우의 재검색 횟수는 그대로다: 부분 판정이 아닌 나뉜 질문은 재검색 상한까지 판정한다."""
    fn, seen = recorder([ESC])
    m = llm(decompose=SPLIT, judge=NONE, answer=lambda u: cite(ESC))
    out = run(build_graph(fn, llm=m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "refuse" and len(seen) == 2 and judges(m) == 2
