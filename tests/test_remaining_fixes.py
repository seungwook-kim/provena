"""남은 문항 수정안 시험: 근거 확인 구절 먼저(`GRAPH_GROUNDING_QUOTE`)와 일반 규칙의 문항 단어 누출 검사. 가짜 모델과 가짜 검색기만 쓴다.
문장 공유 인용 더하기, 제목 경로 검색, 제품 한정 인용 빼기, 제목 경로 알림 시험은 사전 등록 62.72로 그 장치를 코드째 제거하면서 지웠다.
같은 사전 등록으로 범위 메모 거절과 안내 구절 거절의 정규식이 없어져 누출 검사는 `answer_fixes.py` 모듈 설명만 본다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import Q_REVIEW, REVIEW, cite, llm, run


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_CITE_MULTI", "GRAPH_KEEP_CITES",
                 "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_REQUERY_VOCAB", "GRAPH_UNKNOWN_NAME",
                 "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", "SEARCH_DECOMPOSE", "USE_SKILLS",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_REFUSE_ON_NONE",
                 "GRAPH_GROUNDING_QUOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


OK = j(reason="", grounded=True)


# ---------- Q 근거 확인 구절 먼저 ----------
def test_grounding_quoted_prompt():
    from backend.prompts import question as P
    base = P.GROUNDING_SYSTEM
    q = P.grounding_quoted(base)
    assert q.startswith(base.rpartition("JSON 한 개만 출력한다.")[0])  # 앞 규칙은 그대로
    assert "NOTHING FOUND" in q and "번역이나 다른 말 바꿈" in q
    assert "간접 근거" not in q  # 제목 경로(적용 범위)의 간접 근거 문장은 사전 등록 62.72로 뺐다
    assert q.count("JSON 한 개만 출력한다.") == 1 and '"quote"' in q
    assert "NOTHING FOUND" not in P.grounding_checked(base)  # 끄면 지금 프롬프트


def _grounding_systems(monkeypatch, on: bool, multi: bool = False):
    if on:
        monkeypatch.setenv("GRAPH_GROUNDING_QUOTE", "1")
    m = llm(answer=cite(REVIEW, text="리뷰는 2영업일 안이다"), grounding=OK)
    seen: list[str] = []
    inner = m.invoke

    def invoke(messages, *a, **k):
        if "[[task:grounding]]" in messages[0].content:
            seen.append(messages[0].content)
        return inner(messages, *a, **k)
    m.invoke = invoke
    g = build_multi_graph(lambda q: [REVIEW], llm=m, grounding_llm=True) if multi else build_graph(lambda q: [REVIEW], llm=m, grounding_llm=True)
    out = run(g, Q_REVIEW)
    return out, seen


@pytest.mark.parametrize("multi", [False, True])
def test_grounding_quote_switch_changes_only_the_grounding_prompt(monkeypatch, multi):
    out, seen = _grounding_systems(monkeypatch, True, multi)
    assert out["kind"] == "answer" and seen and all("NOTHING FOUND" in s for s in seen)


def test_grounding_quote_off_keeps_the_checked_prompt(monkeypatch):
    out, seen = _grounding_systems(monkeypatch, False)
    assert seen and all("NOTHING FOUND" not in s and '"source"' in s for s in seen)


# ---------- 일반 규칙의 문항 단어 누출 검사 ----------
def test_no_item_page_or_product_names_in_the_general_rules():
    import inspect
    import re as _re
    assert not any(hasattr(F, n) for n in ("scope_note_refuses", "pointer_only", "_SCOPE_LIMITED", "_POINTER", "_TEAM_TITLE", "head_owner_cites"))  # 62.72로 제거
    src = inspect.getsource(F).split('"""', 2)[1]  # 모듈 설명
    for name in LEAK_NAMES_RULES:
        assert name not in src.lower(), name
    low = src.lower()
    assert not _re.search(LEAK_ID, low)  # 청크·페이지 id 없음
    for name in LEAK_NAMES_MORE:
        assert name not in low, name
    assert not hasattr(F, "PRODUCT_SCOPES")


LEAK_NAMES_RULES = ("eoc", "sirt", "tableau", "logo", "로고", "approval threshold")
LEAK_NAMES_MORE = ("dedicated", "imoc", "new vendor", "purchase request", "zip ", "procurement", "tprm")
LEAK_ID = r"\b[0-9a-f]{6,16}\b"


def _leak_source(which: str) -> str:
    import inspect

    from backend.graph import decompose as dec
    from backend.prompts import question as P
    if which == "prompts/question.py":
        return inspect.getsource(P)
    return dec._PRODUCT_TARGET.pattern  # 분해의 제품 대상 정규식(`GRAPH_KEEP_PRODUCT_NAME`)


@pytest.mark.parametrize("which", [
    # 용어표(`query_plan.py`)는 사전 등록 62.72로 코드째 제거했으므로 실패 기록용 표시(strict xfail)도 지웠다.
    "prompts/question.py",
    "decompose._PRODUCT_TARGET",
])
def test_no_item_page_or_product_names_in_terms_prompts_and_decompose(which):
    """같은 누출 검사를 질문 프롬프트와 분해의 제품 정규식에도 건다. 문항 단어가 들어 있으면 실패로 남긴다."""
    import re as _re
    low = _leak_source(which).lower()
    hits = [name for name in (*LEAK_NAMES_RULES, *LEAK_NAMES_MORE) if name in low]
    ids = sorted(set(_re.findall(LEAK_ID, low)) - {"0123456789abcdef"})  # 출력 예의 자리표시 id(HEAD 때부터)는 문항 id가 아니다
    assert not hits and not ids, (hits, ids)


