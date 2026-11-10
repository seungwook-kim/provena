"""남은 문항 수정안 시험(기본 꺼짐). A1b `GRAPH_CITE_PHRASE`: 인용 청크와 긴 문장을 그대로 공유하는 다른 페이지 청크를 인용에 더한다.
가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import Q_REVIEW, REVIEW, cite, llm, mk, run

SENT = "Patch releases are deployed to production during the scheduled patch window after the release manager approves the package."
PATCH = mk(SENT, title="Patch Releases", seq=71001, article="Patch window")
DEPLOY = mk(f"For deployments, {SENT[0].lower()}{SENT[1:]}", title="Deployments", seq=71002, article="PDM execution")
TEAM_COPY = mk(SENT, title="Delivery Group", seq=71003, article="Notes")
SAME_PAGE = mk(SENT + " More text.", title="Patch Releases", seq=71001, article="Other")
SHORT = mk("Patch releases are deployed to production during the window.", title="Release Notes", seq=71004)
from backend.graph import query_plan as QP  # noqa: E402


@pytest.fixture(autouse=True)
def _sample_terms(monkeypatch):
    """서비스 용어표는 비어 있다(62.34). 장치 시험은 표본 행으로 돈다."""
    from qgraph_fakes import sample_term_rows
    monkeypatch.setattr(QP, "TERM_ROWS", sample_term_rows())


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_CITE_PHRASE", "GRAPH_CITE_EXPAND", "GRAPH_CITE_MULTI", "GRAPH_TEAM_LAST", "GRAPH_KEEP_CITES",
                 "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_REQUERY_VOCAB", "GRAPH_UNKNOWN_NAME", "GRAPH_QUERY_TERMS", "GRAPH_QUERY_BRANCHES",
                 "GRAPH_KEEP_PRODUCT_NAME", "GRAPH_REQUERY_TERMS", "SEARCH_DECOMPOSE", "USE_SKILLS",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_REFUSE_ON_NONE",
                 "GRAPH_RESEARCH_SAME_PAGE", "GRAPH_HEADING_TERMS", "GRAPH_GROUNDING_QUOTE", "GRAPH_DROP_SCOPED_CITES", "GRAPH_HEADING_MARK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def d(c):
    return c.model_dump()


# ---------- A1b 규칙 ----------
def test_longest_shared_run():
    assert F.longest_shared_run("a b c d e".split(), "x b c d y".split()) == 3
    assert F.longest_shared_run([], ["a"]) == 0


def test_phrase_picker_adds_only_other_pages_with_a_long_shared_run():
    got = F.pick_phrase_extra([d(PATCH)], [d(PATCH), d(SAME_PAGE), d(SHORT), d(TEAM_COPY), d(DEPLOY)], cap=4)
    assert [(c["chunk_id"], i) for c, i in got] == [(DEPLOY.chunk_id, 0)]  # 같은 페이지, 짧은 겹침, 다른 팀 페이지는 빼고 다른 페이지만
    assert F.pick_phrase_extra([d(PATCH)], [d(DEPLOY)], cap=1) == []  # 상한
    assert F.pick_phrase_extra([d(PATCH)], [d(DEPLOY)], cap=4, n=99) == []


def test_phrase_picker_keeps_a_team_page_when_the_anchor_is_that_page():
    other = mk(SENT, title="Delivery Group", seq=71005, article="Copy")
    got = F.pick_phrase_extra([d(TEAM_COPY)], [d(other)], cap=4)
    assert [c["chunk_id"] for c, _ in got] == [other.chunk_id]  # 제목이 같으면 다른 팀 페이지가 아니다


@pytest.mark.parametrize("multi", [False, True])
def test_cite_phrase_adds_the_other_page_after_grounding(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_CITE_PHRASE", "1")
    fn = lambda q: [PATCH, DEPLOY, REVIEW]  # noqa: E731
    m = llm(answer=cite(PATCH, text="패치 릴리스는 승인 뒤 정해진 패치 시간에 배포한다"))
    g = build_multi_graph(fn, llm=m) if multi else build_graph(fn, llm=m)
    out = run(g, "패치 릴리스는 언제 배포해?")
    assert [c["chunk_id"] for c in out["citations"]] == [PATCH.chunk_id, DEPLOY.chunk_id]
    assert "[1][2]" in out["answer"] and out["grounding"]["cite_phrase"] == [DEPLOY.chunk_id]
    assert "cite_expand" not in out["grounding"]


def test_cite_phrase_off_keeps_the_citations():
    m = llm(answer=cite(PATCH, text="패치 릴리스는 승인 뒤 정해진 패치 시간에 배포한다"))
    out = run(build_graph(lambda q: [PATCH, DEPLOY], llm=m), "패치 릴리스는 언제 배포해?")
    assert [c["chunk_id"] for c in out["citations"]] == [PATCH.chunk_id] and "cite_phrase" not in out["grounding"]


OK = j(reason="", grounded=True)


# ---------- H 제목 경로 검색 ----------
Q38 = "새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?"
SUBS38 = ["새 SaaS 도구 도입 요청은 어디서 시작해?", "보안 검토(TPRM)는 언제 필요해?"]
VENDOR = mk("Open Zip and choose Request a new vendor.", title="Zip End Users Guide", seq=71010, article="Zip - Getting Started > How to request a new vendor?")


def test_heading_phrases_use_the_whole_term_table():
    table = ["procurement", "purchase request", "new vendor", "TPRM", "third party risk management assessment", "post-deploy migration"]
    texts = ["a (procurement, purchase request, new vendor)", "b (TPRM, third party risk management assessment)"]
    assert F.heading_phrases(texts, table) == ["purchase request", "new vendor", "third party risk management assessment"]  # 한 단어 용어는 빼고 표 순서로
    assert F.heading_phrases(["Post-Deploy Migration은 왜 안 돌려?"], table) == ["post-deploy migration"]  # 괄호가 아니어도, 어느 줄이든
    assert F.heading_phrases(None, table) == [] and F.heading_phrases(["(대상: GitLab 팀원)"], table) == []
    assert F.heading_phrases(["new vendor"]) == ["new vendor"]  # 기본은 코드 용어표 전체

def _heading_llm():
    from test_query_plan import make_llm
    return make_llm(subs=SUBS38)


def _heading_fake(seen):
    def fn(phrase, org, as_of, n):
        seen.append((phrase, as_of, n))
        return [VENDOR] if phrase == "new vendor" else []
    return fn


@pytest.mark.parametrize("multi", [False, True])
def test_heading_terms_add_the_heading_chunk_to_the_first_search(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_HEADING_TERMS", "1")
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    seen: list = []
    fn = lambda q: [REVIEW]  # noqa: E731
    kw = {"llm": _heading_llm(), "decompose": True, "heading_search": _heading_fake(seen)}
    g = build_multi_graph(fn, **kw) if multi else build_graph(fn, **kw)
    out = g.invoke({"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert [p for p, _, _ in seen] == ["purchase request", "new vendor", "third party risk management assessment"]
    assert all(a == "2025-06-01" and n == 1 for _, a, n in seen)
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert ids[:2] == [REVIEW.chunk_id, VENDOR.chunk_id]  # 첫 검색 결과 뒤에 붙는다


def test_heading_terms_need_the_terms_the_flag_and_the_search(monkeypatch):
    seen: list = []
    fn = lambda q: [REVIEW]  # noqa: E731
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    out = build_graph(fn, llm=_heading_llm(), decompose=True, heading_search=_heading_fake(seen)).invoke(
        {"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert seen == [] and VENDOR.chunk_id not in [c["chunk_id"] for c in out["chunks"]]  # 스위치 꺼짐
    monkeypatch.setenv("GRAPH_HEADING_TERMS", "1")
    monkeypatch.delenv("GRAPH_QUERY_TERMS")
    build_graph(fn, llm=_heading_llm(), decompose=True, heading_search=_heading_fake(seen)).invoke(
        {"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert seen == []  # 하위 질문에 용어가 없으면 부르지 않는다
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    out = build_graph(fn, llm=_heading_llm(), decompose=True).invoke({"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert VENDOR.chunk_id not in [c["chunk_id"] for c in out["chunks"]]  # 검색 함수가 없으면 그대로


def test_heading_search_failure_keeps_the_first_search(monkeypatch):
    monkeypatch.setenv("GRAPH_HEADING_TERMS", "1")
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")

    def boom(*a):
        raise RuntimeError("db")
    out = build_graph(lambda q: [REVIEW], llm=_heading_llm(), decompose=True, heading_search=boom).invoke(
        {"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert [c["chunk_id"] for c in out["chunks"]][:1] == [REVIEW.chunk_id]


def test_memory_store_heading_top_filters_and_orders():
    import numpy as np
    from backend.rag.retrieve.search import MemoryStore
    base = {"org": "gitlab", "kind": "text", "text": "t", "source_url": "u", "version_date": "2025-01-01", "fetched_at": "2025-01-01"}
    rows = [{**base, "chunk_id": "b" * 16, "version_id": "v1", "rule_seq": 1, "rule_title": "Zip End Users Guide", "article": "How to request a new vendor?", "ord": 2,
             "valid_from": "2025-01-01", "valid_to": None},
            {**base, "chunk_id": "a" * 16, "version_id": "v1", "rule_seq": 2, "rule_title": "Accounting", "article": "New Vendor Onboarding", "ord": 1,
             "valid_from": "2025-01-01", "valid_to": None},
            {**base, "chunk_id": "c" * 16, "version_id": "v0", "rule_seq": 3, "rule_title": "Old", "article": "new vendor", "ord": 0,
             "valid_from": "2024-01-01", "valid_to": "2024-06-01"}]
    s = MemoryStore(rows, np.zeros((3, 2), dtype=np.float32), "e")
    assert [k[0] for k in s.heading_top("New Vendor", None, None, 5)] == ["a" * 16, "b" * 16]  # 현재 판만, ord 순
    assert [k[0] for k in s.heading_top("new vendor", None, "2024-03-01", 5)] == ["c" * 16]
    assert s.heading_top("new vendor", None, None, 1) == [("a" * 16, "v1")] and s.heading_top(" ", None, None, 3) == []


# ---------- Q 근거 확인 구절 먼저 ----------
def test_grounding_quoted_prompt():
    from backend.prompts import question as P
    base = P.GROUNDING_SYSTEM
    q = P.grounding_quoted(base)
    assert q.startswith(base.rpartition("JSON 한 개만 출력한다.")[0])  # 앞 규칙은 그대로
    assert "NOTHING FOUND" in q and "번역이나 다른 말 바꿈" in q and "제목 경로" in q
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


# ---------- P 제품 한정 페이지 인용 빼기 ----------
DEDICATED = mk("If no response in 10 minutes, reassign to another Dedicated SRE.", title="GitLab Dedicated IMOC Response Team", seq=71020, article="Scenario 3")
NOTE_P = "질문의 나머지 부분은 근거를 확인하지 못해 답에서 뺐습니다."


def test_qualifiers_are_words_before_an_asked_word_missing_elsewhere():
    q = "IMOC가 응답이 없으면?"
    assert F.qualifiers(q, d(DEDICATED)) == ["dedicated"] and F.scoped_out(q, d(DEDICATED))
    assert not F.scoped_out("GitLab Dedicated IMOC가 응답이 없으면?", d(DEDICATED))  # 질문에 있으면 한정어가 아니다
    assert F.qualifiers("Dedicated IMOC가 응답이 없으면?", d(DEDICATED)) == ["gitlab"]  # 앞 낱말이 질문에 있으면 그 앞 낱말을 본다(알려진 한계)
    assert not F.scoped_out("코드 리뷰는?", d(DEDICATED))  # 질문에 영어 낱말이 없으면 보지 않는다
    other = mk("x", title="Dedicated IMOC Handbook", seq=71021)
    assert not F.scoped_out(q, d(DEDICATED), [d(DEDICATED), d(other)])  # 문맥의 다른 페이지 제목에 있으면 한정어가 아니다
    same_page = mk("y", title="GitLab Dedicated IMOC Response Team", seq=71020, article="Other")
    assert F.scoped_out(q, d(DEDICATED), [d(DEDICATED), d(same_page)])  # 같은 페이지는 다른 페이지로 세지 않는다
    section = mk("z", title="Deployments", seq=71022, article="Overview and terminology > Post-deploy migration (PDM)")
    assert not F.scoped_out("post-deploy migration(PDM)은 왜?", d(section))  # 절 제목은 보지 않는다(좁은 형태)
    assert F.qualifiers("post-deploy migration(PDM)은 왜?", d(section), adjacent=False)  # 넓은 형태는 걸린다(쓰지 않음)
    org_title = mk("w", title="TEST-eng IMOC Guide", seq=71023)
    assert not F.scoped_out(q, d(org_title))  # 조직 이름은 한정어가 아니다


def test_no_item_page_or_product_names_in_the_general_rules():
    import inspect
    import re as _re
    from backend.rag.retrieve.search import Searcher
    src = "".join(inspect.getsource(fn) for fn in (F.qualifiers, F.scoped_out, F.drop_scoped_cites, F.heading_phrases, F._heading_words,
                                                    F.heading_note, Searcher.intro_fill, F.scope_note_refuses,
                                                    F.drop_odd_cites, F.pointer_only))
    src += F.CITE_PICK_RULE + F._SCOPE_LIMITED.pattern + F._SCOPE_ABSENT.pattern + F._POINTER.pattern
    for name in LEAK_NAMES_RULES:
        assert name not in src.lower(), name
    src += inspect.getsource(F).split('"""', 2)[1]  # 모듈 설명도
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
    from backend.graph import query_plan as QP
    from backend.prompts import question as P
    if which == "query_plan.TERM_ROWS":
        import importlib
        return inspect.getsource(importlib.import_module("backend.graph.query_plan"))  # 표본 행이 아니라 서비스 코드의 표와 설명
    if which == "prompts/question.py":
        return inspect.getsource(P)
    return dec._PRODUCT_TARGET.pattern  # 분해의 제품 대상 정규식(`GRAPH_KEEP_PRODUCT_NAME`)


@pytest.mark.parametrize("which", [
    "query_plan.TERM_ROWS",  # v2 문항 단어 행을 뺐다(사전 등록 62.34, 결정 0101). 알려진 실패 표시도 지웠다
    "prompts/question.py",
    "decompose._PRODUCT_TARGET",
])
def test_no_item_page_or_product_names_in_terms_prompts_and_decompose(which):
    """같은 누출 검사를 용어표, 질문 프롬프트, 분해의 제품 정규식에도 건다. 문항 단어가 들어 있으면 실패로 남긴다(보류 규칙 포함)."""
    import re as _re
    low = _leak_source(which).lower()
    hits = [name for name in (*LEAK_NAMES_RULES, *LEAK_NAMES_MORE) if name in low]
    ids = sorted(set(_re.findall(LEAK_ID, low)) - {"0123456789abcdef"})  # 출력 예의 자리표시 id(HEAD 때부터)는 문항 id가 아니다
    assert not hits and not ids, (hits, ids)

def test_drop_scoped_cites_removes_only_scoped_sentences_and_renumbers():
    body = "EOC는 incident.io로 올린다 [1]. IMOC는 10분 뒤 다른 SRE에게 넘긴다 [2]. 둘 다 리더십이 본다 [1][2]."
    got = F.drop_scoped_cites(body, [d(REVIEW), d(DEDICATED)], "EOC와 IMOC가 응답이 없으면?", NOTE_P)
    assert got is not None
    nb, kept, removed = got
    assert nb == f"EOC는 incident.io로 올린다 [1]. 둘 다 리더십이 본다 [1]. {NOTE_P}"
    assert [c["chunk_id"] for c in kept] == [REVIEW.chunk_id] and removed == [DEDICATED.chunk_id]
    body2 = "IMOC는 넘긴다 [1]. EOC는 올린다 [2]."
    nb2, kept2, _ = F.drop_scoped_cites(body2, [d(DEDICATED), d(REVIEW)], "IMOC?", NOTE_P)
    assert nb2 == f"EOC는 올린다 [1]. {NOTE_P}" and [c["chunk_id"] for c in kept2] == [REVIEW.chunk_id]


def test_drop_scoped_cites_keeps_the_answer_when_nothing_would_be_left():
    assert F.drop_scoped_cites("IMOC는 넘긴다 [1].", [d(DEDICATED)], "IMOC?", NOTE_P) is None
    assert F.drop_scoped_cites("리뷰는 2일 [1].", [d(REVIEW)], "리뷰?", NOTE_P) is None
    assert F.drop_scoped_cites("IMOC는 넘긴다 [1]. 리뷰 [2].", [d(DEDICATED), d(REVIEW)], "GitLab Dedicated IMOC?", NOTE_P) is None


@pytest.mark.parametrize("multi", [False, True])
def test_drop_scoped_switch_in_the_graph(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_DROP_SCOPED_CITES", "1")
    ans = j(asked=["a"], picks=[], answer=f"리뷰는 2영업일 안이다 [{REVIEW.chunk_id}]. 응답이 없으면 다른 SRE에게 넘긴다 [{DEDICATED.chunk_id}].",
            citations=[{"chunk_id": REVIEW.chunk_id}, {"chunk_id": DEDICATED.chunk_id}], period_covered=True)
    m = llm(answer=ans, grounding=OK)
    fn = lambda q: [REVIEW, DEDICATED]  # noqa: E731
    g = build_multi_graph(fn, llm=m, grounding_llm=True) if multi else build_graph(fn, llm=m, grounding_llm=True)
    out = run(g, "코드 리뷰 첫 응답 기한과 IMOC 무응답 처리는?")
    assert [c["chunk_id"] for c in out["citations"]] == [REVIEW.chunk_id]
    assert out["grounding"]["scoped_drop"] == [DEDICATED.chunk_id] and NOTE_P in out["answer"] and "[2]" not in out["answer"]


def test_drop_scoped_off_keeps_both(monkeypatch):
    ans = j(asked=["a"], picks=[], answer=f"리뷰는 2영업일 안이다 [{REVIEW.chunk_id}]. 응답이 없으면 다른 SRE에게 넘긴다 [{DEDICATED.chunk_id}].",
            citations=[{"chunk_id": REVIEW.chunk_id}, {"chunk_id": DEDICATED.chunk_id}], period_covered=True)
    out = run(build_graph(lambda q: [REVIEW, DEDICATED], llm=llm(answer=ans, grounding=OK), grounding_llm=True), "코드 리뷰 첫 응답 기한과 IMOC 무응답 처리는?")
    assert len(out["citations"]) == 2 and "scoped_drop" not in out["grounding"]


# ---------- HM H가 더한 청크를 답 입력에서 알리기 ----------
def test_heading_note_lists_only_marked_chunks():
    assert F.heading_note([d(REVIEW)]) == ""
    note = F.heading_note([d(REVIEW), {**d(VENDOR), F.HEADING_MARK_KEY: "new vendor"}])
    assert f"chunk_id={VENDOR.chunk_id} (용어: new vendor)" in note and REVIEW.chunk_id not in note


def _answer_inputs(monkeypatch, mark: bool, heading: bool = True, multi: bool = False):
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    if heading:
        monkeypatch.setenv("GRAPH_HEADING_TERMS", "1")
    if mark:
        monkeypatch.setenv("GRAPH_HEADING_MARK", "1")
    m = _heading_llm()
    seen: list[str] = []
    inner = m.invoke

    def invoke(messages, *a, **k):
        if "[[task:answer" in messages[0].content:
            seen.append(messages[-1].content)
        return inner(messages, *a, **k)
    m.invoke = invoke
    kw = {"llm": m, "decompose": True, "heading_search": _heading_fake([])}
    g = build_multi_graph(lambda q: [REVIEW], **kw) if multi else build_graph(lambda q: [REVIEW], **kw)
    out = g.invoke({"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    return out, seen


def test_heading_mark_adds_the_note_to_the_redraft_input(monkeypatch):
    from qgraph_fakes import j as jj
    monkeypatch.setenv("GRAPH_QUERY_TERMS", "1")
    monkeypatch.setenv("GRAPH_HEADING_TERMS", "1")
    monkeypatch.setenv("GRAPH_HEADING_MARK", "1")
    from qgraph_fakes import ScriptedLLM, normal_llm
    bad = jj(grounded=False, reason_code="unsupported", reason="값 다름", unsupported_sentences=["x"])
    m = ScriptedLLM({**normal_llm().handlers, "decompose": jj(split=True, sub_questions=SUBS38), "grounding": [bad, jj(reason="", grounded=True)]})
    seen: list[str] = []
    inner = m.invoke

    def invoke(messages, *a, **k):
        if "[[task:answer" in messages[0].content and "이전 답이 근거 판정을 통과하지 못했다" in messages[-1].content:
            seen.append(messages[-1].content)
        return inner(messages, *a, **k)
    m.invoke = invoke
    tprm = mk("A TPRM review is required before approval.", title="Third Party Risk", seq=71030)  # 질문의 TPRM이 근거에 있어야 코드 규칙을 지난다
    out = build_graph(lambda q: [tprm], llm=m, decompose=True, grounding_llm=True, heading_search=_heading_fake([])).invoke(
        {"question": Q38, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert "redraft" in out["grounding"]
    assert seen and all(f"chunk_id={VENDOR.chunk_id} (용어: new vendor)" in s for s in seen)


@pytest.mark.parametrize("multi", [False, True])
def test_heading_mark_adds_the_note_to_the_answer_input(monkeypatch, multi):
    out, seen = _answer_inputs(monkeypatch, True, multi=multi)
    assert seen and all(f"chunk_id={VENDOR.chunk_id} (용어: new vendor)" in s for s in seen)
    assert all(F.HEADING_MARK_KEY not in c for c in out.get("citations") or [])  # 인용 출력에는 표시 칸이 없다


def test_heading_mark_off_or_without_h_keeps_the_answer_input(monkeypatch):
    _, seen = _answer_inputs(monkeypatch, False)
    assert seen and all("질문의 용어를 그대로 담은 자료" not in s for s in seen)
    monkeypatch.delenv("GRAPH_HEADING_TERMS")
    _, seen = _answer_inputs(monkeypatch, True, heading=False)
    assert seen and all("질문의 용어를 그대로 담은 자료" not in s for s in seen)  # H가 꺼져 있으면 HM도 없다
