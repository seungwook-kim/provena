"""조사 해법 시험(기본 꺼짐): 판정 다수결 `GRAPH_JUDGE_VOTE`, 인용 먼저 판정 `GRAPH_JUDGE_QUOTE`. 가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

import threading

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from backend.prompts import question as P
from test_answer_fixes_graph import Q_REVIEW, REVIEW, cite, llm, run, searcher

OK = j(sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
NO = j(sufficient=False, partial=False, reason="없음", missing=["리뷰 기한"], scope_note=None, clarify=None, query="review deadline")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_JUDGE_VOTE", "GRAPH_JUDGE_QUOTE", "GRAPH_CITE_PICK", "GRAPH_PROMPTS_HEAD", "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def in_order(*outs):
    """부른 순서대로 답한다(스레드에서 불려도 순서가 섞이지 않게 잠근다). 마지막 값은 되풀이한다."""
    lock, n = threading.Lock(), [0]

    def h(_user):
        with lock:
            i = n[0]
            n[0] += 1
        return outs[min(i, len(outs) - 1)]
    return h


# ---------- 합치기 ----------
def test_votes_settle_on_two_same_conclusions():
    s, n = {"sufficient": True}, {"sufficient": False, "partial": False}
    assert not F.votes_settled("judge", [s])
    assert not F.votes_settled("judge", [s, n])
    assert F.votes_settled("judge", [s, n, n]) and F.votes_settled("judge", [s, s])
    assert not F.votes_settled("judge", [n, n])  # 부족 2표는 셋째 표를 기다린다(62.33)
    assert F.votes_settled("judge", [n, n, n]) and F.votes_settled("judge", [{"sufficient": False, "partial": True}] * 2)
    assert F.votes_settled("grounding", [{"grounded": True}, {"grounded": True}])
    assert not F.votes_settled("grounding", [{"grounded": True}, {"grounded": False}])


def test_merge_keeps_majority_and_list_items_with_two_votes():
    a = {"sufficient": False, "partial": True, "missing": ["리뷰 응답 기한", "승인자"], "reason": "a"}
    b = {"sufficient": False, "partial": True, "missing": ["리뷰 응답의 기한"], "reason": "b"}
    c = {"sufficient": True, "partial": False, "missing": [], "reason": "c"}
    out = F.merge_votes("judge", [c, a, b])
    assert out["sufficient"] is False and out["partial"] is True and out["reason"] == "a"
    assert out["missing"] == ["리뷰 응답 기한"]  # 다른 표에도 있는 것만(말이 조금 달라도 같은 것으로 본다)
    assert out["_votes"] == {"n": 3, "agree": 2}
    g = F.merge_votes("grounding", [{"grounded": False, "unsupported_sentences": ["x.", "y."]}, {"grounded": False, "unsupported_sentences": ["y."]}])
    assert g["unsupported_sentences"] == ["y."]
    assert F.merge_votes("judge", [{}, {}]) == {}


def test_judge_from_quotes_decides_from_the_quote_list():
    both = {"sufficient": False, "checks": [{"fact": "기한", "quote": "within 2 business days"}, {"fact": "대상", "quote": "for team members"}]}
    assert F.judge_from_quotes(both)["sufficient"] is True and F.judge_from_quotes(both)["missing"] == []
    one = {"sufficient": True, "checks": [{"fact": "기한", "quote": "within 2 business days"}, {"fact": "승인자", "quote": "NOTHING FOUND"}]}
    got = F.judge_from_quotes(one)
    assert got["sufficient"] is False and got["partial"] is True and got["missing"] == ["승인자"]
    none = {"sufficient": True, "checks": [{"fact": "기한", "quote": "Nothing found."}]}
    assert F.judge_from_quotes(none)["sufficient"] is False and F.judge_from_quotes(none)["partial"] is False
    assert F.judge_from_quotes({"sufficient": True}) == {"sufficient": True}  # 목록이 없으면 그대로


# ---------- 그래프 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_vote_off_calls_the_judge_once(multi):
    fn, _ = searcher([("리뷰", [REVIEW])])
    m = llm(judge=OK, answer=cite(REVIEW))
    run((build_multi_graph if multi else build_graph)(fn, llm=m, grounding_llm=True), Q_REVIEW)
    assert m.count("judge") == 1 and m.count("grounding") == 1


@pytest.mark.parametrize("multi", [False, True])
def test_vote_takes_the_majority_judgement(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    fn, _ = searcher([("리뷰", [REVIEW])])
    m = llm(judge=in_order(NO, OK, OK), answer=cite(REVIEW), grounding=j(reason="", grounded=True))
    out = run((build_multi_graph if multi else build_graph)(fn, llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["citations"]] == [REVIEW.chunk_id]
    assert 2 <= m.count("judge") <= 3 and 2 <= m.count("grounding") <= 3


def test_vote_majority_of_ungrounded_rewrites(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    fn, _ = searcher([("리뷰", [REVIEW])])
    bad = j(reason="기한 다름", grounded=False, reason_code="unsupported", unsupported_sentences=[f"답 [{REVIEW.chunk_id}]"])
    m = llm(judge=OK, answer=cite(REVIEW), grounding=in_order(bad, bad, j(reason="", grounded=True)))
    out = run(build_graph(fn, llm=m, grounding_llm=True), Q_REVIEW)
    assert out["grounding"].get("redrafted") or out["kind"] != "answer"  # 받쳐지지 않는다는 2표가 이긴다


# ---------- 62.33: 첫 판정이 전무여도 표가 갈렸으면 바로 거절하지 않는다 ----------
def test_votes_unanimous_reads_the_merged_vote():
    assert F.votes_unanimous({"sufficient": False})  # 다수결을 쓰지 않은 표
    assert F.votes_unanimous(F.merge_votes("judge", [{"sufficient": False}] * 3))
    assert not F.votes_unanimous(F.merge_votes("judge", [{"sufficient": True}, {"sufficient": False}, {"sufficient": False}]))


@pytest.mark.parametrize("multi", [False, True])
def test_split_none_vote_researches_instead_of_refusing(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_REFUSE_ON_NONE", "1")
    build = build_multi_graph if multi else build_graph
    fn, seen = searcher([("", [REVIEW])])
    m = llm(judge=in_order(NO, OK, NO, OK), answer=cite(REVIEW), grounding=j(reason="", grounded=True))
    out = run(build(fn, llm=m, grounding_llm=True, max_research=1), Q_REVIEW)
    assert out["kind"] == "answer" and not out.get("judge_none") and len(seen) == 2  # 충분 1표, 전무 2표: 재검색 뒤 다시 판정한다
    fn, seen = searcher([("", [REVIEW])])
    m = llm(judge=NO, answer=cite(REVIEW), grounding=j(reason="", grounded=True))
    out = run(build(fn, llm=m, grounding_llm=True, max_research=1), Q_REVIEW)
    assert out["kind"] == "refuse" and out.get("judge_none") is True and len(seen) == 1 and m.count("judge") == 3  # 3표 모두 전무: 바로 거절


def test_quote_judge_prompt_and_code_conclusion(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    fn, _ = searcher([("리뷰", [REVIEW])])
    said_no = j(checks=[{"fact": "리뷰 기한", "quote": "within 2 business days"}], sufficient=False, partial=False, reason="", missing=["리뷰 기한"],
                scope_note=None, clarify=None, query="x")
    m = llm(judge=said_no, answer=cite(REVIEW))
    out = run(build_graph(fn, llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and m.count("judge") == 1  # 구절이 있으니 코드가 충분으로 정한다(재검색 없음)
    judge = P.judge_quoted(P.judge_with_query(P.JUDGE_SYSTEM), query=True)
    assert P.JUDGE_QUOTE_RULE in judge and "checks에는 질문이 묻는 사실마다 {\"fact\": 사실, \"value\"" not in judge


def test_quote_judge_off_keeps_the_checked_prompt():
    checked = P.judge_checked(P.judge_with_query(P.JUDGE_SYSTEM), query=True)
    assert P.JUDGE_QUOTE_RULE not in checked
