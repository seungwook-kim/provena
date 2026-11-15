"""재검색 수정안 시험(기본 꺼짐). R `GRAPH_REFUSE_ON_NONE`: 첫 판정이 전무면 재검색 없이 거절. 가짜 모델과 가짜 검색기만 쓴다.
가 `GRAPH_RESEARCH_SAME_PAGE`(부분 판정 뒤 재검색을 문맥 페이지 안 검색으로 바꾸기)는 사전 등록 62.72로 코드째 제거했다. 부분 판정 뒤 재검색은 전체 검색이다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import ESC, IMOC, PARTIAL, Q_ESC, Q_REVIEW, REVIEW, SUBS, cite, llm, run

NONE = j(checks=[], sufficient=False, partial=False, reason="육아휴직 규정 없음", missing=["육아휴직 기간"], scope_note=None, clarify=None, query="parental leave")
OK = j(sufficient=True, reason="", clarify=None)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_REFUSE_ON_NONE", "GRAPH_CITE_MULTI", "GRAPH_KEEP_CITES",
                 "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_REQUERY_VOCAB", "GRAPH_UNKNOWN_NAME",
                 "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", "SEARCH_DECOMPOSE", "USE_SKILLS",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_DECOMPOSE_CAP_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def recorder(result):
    seen = []

    def fn(q):
        seen.append(q)
        return list(result)
    return fn, seen


def graph(multi, fn, m, **kw):
    return build_multi_graph(fn, llm=m, **kw) if multi else build_graph(fn, llm=m, **kw)


# ---------- R ----------
def test_judged_none_rule():
    assert F.judged_none({"sufficient": False, "partial": False, "clarify": None})
    assert F.judged_none({"sufficient": False})
    assert not F.judged_none({"sufficient": False, "partial": True})
    assert not F.judged_none({"sufficient": False, "partial": False, "clarify": "어느 팀 말인가요?"})
    assert not F.judged_none({})  # 파싱 실패는 전무로 보지 않는다
    assert not F.judged_none({"sufficient": True})


@pytest.mark.parametrize("multi", [False, True])
def test_refuse_on_none_skips_the_research(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_REFUSE_ON_NONE", "1")
    fn, seen = recorder([REVIEW])
    m = llm(judge=[NONE, OK], answer=cite(REVIEW))
    out = run(graph(multi, fn, m, max_research=1), "육아휴직은 최대 몇 개월까지 쓸 수 있어?")
    assert out["kind"] == "refuse" and out.get("judge_none") is True
    assert len(seen) == 1 and sum(1 for t, _ in m.calls if t == "judge") == 1


@pytest.mark.parametrize("multi", [False, True])
def test_refuse_on_none_off_keeps_the_research(multi):
    fn, seen = recorder([REVIEW])
    m = llm(judge=[NONE, NONE], answer=cite(REVIEW))
    out = run(graph(multi, fn, m, max_research=1), "육아휴직은 최대 몇 개월까지 쓸 수 있어?")
    assert out["kind"] == "refuse" and not out.get("judge_none")
    assert sum(1 for t, _ in m.calls if t == "judge") == 2


@pytest.mark.parametrize("multi", [False, True])
def test_refuse_on_none_leaves_partial_and_sufficient(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_REFUSE_ON_NONE", "1")
    fn, seen = recorder([ESC])
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, OK], answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "answer" and not out.get("judge_none") and len(seen) == 2  # 나뉘지 않은 질문의 부분 판정은 재검색한다(나뉜 질문은 재검색 없이 일부 답: 사전 등록 62.63)
    fn, seen = recorder([ESC])
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=[PARTIAL, OK], answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "answer" and not out.get("judge_none") and len(seen) == 1 and sum(1 for t, _ in m.calls if t == "judge") == 1
    fn, seen = recorder([REVIEW])
    out = run(graph(multi, fn, llm(answer=cite(REVIEW)), max_research=1), Q_REVIEW)
    assert out["kind"] == "answer" and len(seen) == 1


# ---------- 가(제거됨) ----------
def page_recorder(found):
    pages = []

    def page_search(query, seqs, org, as_of, k):
        pages.append((query, list(seqs)))
        return [c for c in found if c.rule_seq in seqs]
    return page_search, pages


def test_partial_research_is_global_even_with_a_page_search():
    """같은 페이지 재검색과 같은 페이지 보충(62.55)은 제거했으므로 페이지 검색을 넘겨도 부르지 않고 전체에서 다시 찾는다."""
    fn, seen = recorder([ESC])
    page_search, pages = page_recorder([IMOC])
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, OK], answer=lambda u: cite(ESC))
    run(build_graph(fn, llm=m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert len(seen) == 2 and pages == []
