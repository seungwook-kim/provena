"""2026-11-13 수정 시험: 사전 등록 62.51(넓힌 첫 검색의 앞자리에 도입부 채우기 청크 포함), 62.52(겹친 머리 인용 바로잡기), 측정 기록의 답 경로(`path`).
가짜 모델, 가짜 검색기, 메모리 저장소만 쓴다(키와 네트워크 없음).

- 62.51: 넓힌 자리(6~8)는 계속 뺀다. 도입부 채우기(R3)가 첫 검색 문맥 뒤에 더한 청크는 앞자리로 센다. 판정 입력의 `[보충]`은 넓힌 자리에만 붙는다.
- 62.52: 근거 확인이 복사한 구절이 인용 청크의 겹친 머리에만 있고 그 머리의 원래 청크가 문맥에 있으면 인용을 원래 청크로 바꾼다(LLM 호출 없음, 스위치 없음).
- path: `done.data.path`는 하위 질문, 문맥 청크 id, 판정 구절이 든 청크 id(구절 글은 없음), 답 후보와 고른 쪽을 싣는다. 답 경로는 읽지 않는다.
"""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, IMOC, Q_ESC, SUBS, cite, llm, mk, run, searcher
from test_widened_first_search import CORE, WIDE, WIDE_IDS, quoting

from backend.graph import answer_fixes as AF
from backend.graph.build import SEARCH_K, build_graph, core_chunks
from backend.graph.multi import build_multi_graph
from backend.graph.stream import stream_events
from backend.prompts import question as P
from backend.services.step_cost import path_meta

INTRO = mk("Overview of the incident management route for the EOC and the IMOC.", title="Incident Management", seq=71500, article="Overview")
INTRO_ID = INTRO.chunk_id


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_BEST2_SAMEDOC",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_GROUNDING_QUOTE",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_CITE_EXPAND", "GRAPH_CITE_PHRASE", "GRAPH_DROP_SCOPED_CITES", "GRAPH_CITE_CONSENSUS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")


def _intro_search(seen=None):
    def fn(chunks, query, org, as_of):
        if seen is not None:
            seen.append(query)
        return [INTRO]
    return fn


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, judge_answer="parallel_all", intro_search=_intro_search(), grounding_llm=True, **kw)


def answering_intro(user: str) -> str:
    """답 입력에 도입부 청크가 있고 넓힌 청크는 없으면 도입부 청크를, 넓힌 청크가 있으면 그 청크를, 아니면 앞자리 청크를 인용하는 가짜 답."""
    if WIDE_IDS[0] in user:
        return cite(WIDE[0])
    return cite(INTRO if INTRO_ID in user else CORE[0])


def intro_run(multi, quote_chunk, *, split=True, answer=answering_intro):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), judge=quoting(quote_chunk), answer=answer)
    return run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC), m


# ---------- 62.51 core_chunks ----------
def _state(chunks, **kw):
    return {"question": Q_ESC, "sub_queries": SUBS, "retries": 0, "chunks": [c.model_dump() for c in chunks], **kw}


def test_core_chunks_keeps_the_first_slots_and_the_intro_chunk_but_not_the_widened_slots():
    both = [*CORE, *WIDE, INTRO]
    got = [c["chunk_id"] for c in core_chunks(_state(both, intro_chunk_ids=[INTRO_ID]))]
    assert got == [*(c.chunk_id for c in CORE), INTRO_ID]
    assert [c["chunk_id"] for c in core_chunks(_state(both))] == [c.chunk_id for c in CORE]  # 도입부 청크 표시가 없으면 지금과 같다


def test_core_chunks_returns_the_whole_context_outside_a_widened_first_search():
    both = [*CORE, *WIDE, INTRO]
    assert len(core_chunks(_state(both, intro_chunk_ids=[INTRO_ID], sub_queries=[SUBS[0]]))) == len(both)  # 나뉘지 않은 질문
    assert len(core_chunks(_state(both, intro_chunk_ids=[INTRO_ID], retries=1))) == len(both)  # 재검색 뒤
    dollar = "계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구야?"
    assert len(core_chunks(_state(both, intro_chunk_ids=[INTRO_ID], question=dollar))) == len(both)  # 달러 금액 질문


def test_core_chunks_does_not_repeat_an_intro_chunk_that_sits_in_the_first_slots():
    chunks = [INTRO, *CORE[: SEARCH_K - 1], *WIDE]
    got = [c["chunk_id"] for c in core_chunks(_state(chunks, intro_chunk_ids=[INTRO_ID]))]
    assert got == [c.chunk_id for c in chunks[:SEARCH_K]]


# ---------- 62.51 그래프 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_search_records_the_intro_chunk_ids_and_marks_only_the_widened_slots(multi):
    out, m = intro_run(multi, CORE[0])
    assert out["intro_chunk_ids"] == [INTRO_ID]
    assert [c["chunk_id"] for c in out["chunks"]][-1] == INTRO_ID
    judged = [u for t, u in m.calls if t == "judge"][0]
    assert all(f"[보충] chunk_id={i}" in judged for i in WIDE_IDS)  # 넓힌 자리에는 표시
    assert f"chunk_id={INTRO_ID}" in judged and f"[보충] chunk_id={INTRO_ID}" not in judged  # 도입부 청크에는 표시가 없다
    assert "[보충] chunk_id=" + CORE[0].chunk_id not in judged


@pytest.mark.parametrize("multi", [False, True])
def test_quote_in_the_intro_chunk_uses_the_core_draft_and_that_draft_sees_the_intro_chunk(multi):
    out, m = intro_run(multi, INTRO)
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 2
    core_input = [u for u in answers if WIDE_IDS[0] not in u]
    assert len(core_input) == 1 and INTRO_ID in core_input[0]  # 앞자리 답의 입력: 도입부 청크 있음, 넓힌 청크 없음
    assert all(i not in core_input[0] for i in WIDE_IDS)
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 0 and log["why"] == "판정 구절이 모두 앞자리"
    assert [c["chunk_id"] for c in out["citations"]] == [INTRO_ID]


@pytest.mark.parametrize("multi", [False, True])
def test_quote_in_the_widened_slots_still_uses_the_full_context_draft_with_the_intro_chunk_present(multi):
    out, m = intro_run(multi, WIDE[0])
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 1 and log["why"] == "판정 구절이 넓힌 자리에 있음"
    assert [c["chunk_id"] for c in out["citations"]] == [WIDE_IDS[0]]


@pytest.mark.parametrize("multi", [False, True])
def test_without_an_intro_chunk_the_input_is_the_same_as_before(multi):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(CORE[0]), answer=lambda u: cite(CORE[0]))
    build = build_multi_graph if multi else build_graph
    out = run(build(fn, llm=m, judge_answer="parallel_all", decompose=True, max_research=1, intro_search=lambda *a: []), Q_ESC)
    assert "intro_chunk_ids" not in out  # 더해진 것이 없으면 칸을 쓰지 않는다
    core_input = [u for t, u in m.calls if t == "answer" and WIDE_IDS[0] not in u]
    assert len(core_input) == 1 and INTRO_ID not in core_input[0]
    assert out["best2_log"]["why"] == "판정 구절이 모두 앞자리"


@pytest.mark.parametrize("multi", [False, True])
def test_unsplit_question_does_not_cut_the_intro_chunk(multi):
    out, m = intro_run(multi, INTRO, split=False)
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 2 and all(u == answers[0] for u in answers) and INTRO_ID in answers[0]
    assert out["best2_log"].get("rule") != "core_first"


def test_intro_chunk_ids_do_not_stay_for_the_next_question_of_the_same_thread():
    from langgraph.checkpoint.memory import InMemorySaver

    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(classify=lambda u: j(route="out_of_domain" if "점심" in u else "rule"), decompose=j(split=True, sub_questions=SUBS), judge=quoting(CORE[0]), answer=answering_intro)
    g = build_graph(fn, llm=m, judge_answer="parallel_all", intro_search=_intro_search(), decompose=True, max_research=1, checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t-left"}}
    g.invoke({"question": Q_ESC, "user_id": "u1", "thread_id": "t-left", "as_of": "2025-06-01"}, cfg)
    assert g.get_state(cfg).values["intro_chunk_ids"] == [INTRO_ID] and g.get_state(cfg).values["judge_quotes"]
    out = g.invoke({"question": "오늘 점심 뭐 먹지?", "user_id": "u1", "thread_id": "t-left", "as_of": "2025-06-01"}, cfg)
    assert out["kind"] == "refuse" and out["intro_chunk_ids"] == [] and out["judge_quotes"] == []   # 앞 질문 값이 남지 않는다
    from backend.graph.build import LEFTOVER_FIELDS

    assert LEFTOVER_FIELDS["intro_chunk_ids"] == [] and LEFTOVER_FIELDS["judge_quotes"] == []


# ---------- 62.52 겹친 머리 ----------
HEAD = "Team members can not opt out of this program because it keeps team members, customers and the company secure."
Y = mk(f"Questions and Answers. I do not want to be included, how do I remove myself? {HEAD}", title="Security Awareness", seq=71600, article="Questions and Answers")
X = mk(f"{HEAD} Privacy and public shaming are discussed in the following paragraphs of this section.", title="Security Awareness", seq=71600, article="Questions and Answers")
QUOTE = "Team members can not opt out of this program"


def _ids(cs):
    return [c["chunk_id"] for c in cs]


def test_head_overlap_counts_the_copied_head_only_for_the_same_page_version():
    assert AF.head_overlap(X.model_dump(), Y.model_dump()) >= len(HEAD)
    assert AF.head_overlap(Y.model_dump(), X.model_dump()) == 0
    assert AF.head_overlap(X.model_dump(), X.model_dump()) == 0
    other_page = mk(Y.text.split("\n", 1)[1], title="Security Awareness", seq=71601, article="Questions and Answers")
    assert AF.head_overlap(X.model_dump(), other_page.model_dump()) == 0  # 다른 페이지
    other_version = {**Y.model_dump(), "version_id": "TEST-other"}
    assert AF.head_overlap(X.model_dump(), other_version) == 0  # 다른 판


def test_head_overlap_ignores_an_overlap_shorter_than_40_characters():
    short = mk("It ends with the short tail of text.", title="Security Awareness", seq=71602, article="A")
    nxt = mk("short tail of text. And then comes its own body.", title="Security Awareness", seq=71602, article="A")
    assert AF.head_overlap(nxt.model_dump(), short.model_dump()) == 0


def test_head_owner_swaps_the_cited_chunk_when_the_quote_is_only_in_the_copied_head():
    body = "구성원은 빠질 수 없습니다 [1]"
    got = AF.head_owner_cites(body, [X.model_dump()], [Y.model_dump(), X.model_dump()], [QUOTE])
    assert got is not None
    new_body, cited, log = got
    assert new_body == body and _ids(cited) == [Y.chunk_id] and log == [{"from": X.chunk_id, "to": Y.chunk_id}]


def test_head_owner_merges_numbers_when_the_original_chunk_is_already_cited():
    body = "구성원은 빠질 수 없습니다 [1][2]. 다른 문장입니다 [2]"
    got = AF.head_owner_cites(body, [Y.model_dump(), X.model_dump()], [Y.model_dump(), X.model_dump()], [QUOTE])
    new_body, cited, log = got
    assert _ids(cited) == [Y.chunk_id] and log == [{"from": X.chunk_id, "to": Y.chunk_id}]
    assert new_body == "구성원은 빠질 수 없습니다 [1]. 다른 문장입니다 [1]"  # `[1][2]`는 한 번만 남고 번호가 다시 매겨진다


def test_head_owner_renumbers_the_other_citations():
    third = mk("Another page about onboarding.", title="Onboarding", seq=71700, article="Start")
    got = AF.head_owner_cites("가 [1] 나 [2] 다 [3]", [X.model_dump(), third.model_dump(), Y.model_dump()], [Y.model_dump(), X.model_dump(), third.model_dump()], [QUOTE])
    new_body, cited, _ = got
    assert _ids(cited) == [Y.chunk_id, third.chunk_id] and new_body == "가 [1] 나 [2] 다 [1]"


def test_head_owner_leaves_the_citation_when_the_quote_is_in_the_chunks_own_text():
    own = "Privacy and public shaming are discussed in the following paragraphs"
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [Y.model_dump(), X.model_dump()], [own]) is None
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [Y.model_dump(), X.model_dump()], [QUOTE, own]) is None  # 하나는 머리, 하나는 자기 본문


@pytest.mark.parametrize("quotes", [None, [], ["NOTHING FOUND"], ["too short"], ["This sentence is not copied from the chunk at all"]])
def test_head_owner_leaves_the_citation_without_a_usable_quote(quotes):
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [Y.model_dump(), X.model_dump()], quotes) is None


def test_head_owner_leaves_the_citation_when_the_original_chunk_is_not_in_the_context():
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [X.model_dump()], [QUOTE]) is None
    other_page = mk(Y.text.split("\n", 1)[1], title="Security Awareness", seq=71601, article="Questions and Answers")
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [other_page.model_dump(), X.model_dump()], [QUOTE]) is None
    assert AF.head_owner_cites("답 [1]", [], [Y.model_dump()], [QUOTE]) is None


GROUNDED = j(claims=[{"claim": "구성원은 빠질 수 없다", "quote": QUOTE, "scope": None}], reason="", grounded=True, reason_code="", unsupported_sentences=[])
Q_OPT = "참여자는 프로그램에서 빠지고 싶으면 어떻게 해?"


def _opt_run(multi, grounding, *, answer=None, **kw):
    fn, _ = searcher((("프로그램", [Y, X]),))
    m = llm(answer=answer or cite(X, text="구성원은 빠질 수 없습니다"), grounding=grounding)
    build = build_multi_graph if multi else build_graph
    out = run(build(fn, llm=m, grounding_llm=True, **kw), Q_OPT)
    return out, m


@pytest.mark.parametrize("multi", [False, True])
def test_graph_swaps_the_citation_to_the_original_chunk_and_records_it(multi):
    out, m = _opt_run(multi, GROUNDED)
    assert out["kind"] == "answer" and _ids(out["citations"]) == [Y.chunk_id]
    assert out["grounding"]["head_owner"] == [{"from": X.chunk_id, "to": Y.chunk_id}]
    assert "_claim_quotes" not in out["grounding"]
    assert sum(1 for t, _ in m.calls if t == "grounding") == 1  # LLM 호출은 늘지 않는다(바꾼 뒤 근거 확인을 다시 부르지 않는다)


@pytest.mark.parametrize("multi", [False, True])
def test_graph_keeps_the_citation_without_claim_quotes(multi):
    plain = j(reason="", grounded=True, reason_code="", unsupported_sentences=[])
    out, _ = _opt_run(multi, plain)
    assert _ids(out["citations"]) == [X.chunk_id] and "head_owner" not in out["grounding"] and "_claim_quotes" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_graph_keeps_the_citation_when_the_quote_is_in_the_chunks_own_text(multi):
    own = j(claims=[{"claim": "사생활", "quote": "Privacy and public shaming are discussed in the following paragraphs", "scope": None}],
            reason="", grounded=True, reason_code="", unsupported_sentences=[])
    out, _ = _opt_run(multi, own)
    assert _ids(out["citations"]) == [X.chunk_id] and "head_owner" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_graph_does_not_swap_after_a_sentence_was_dropped_or_the_answer_was_redrafted(multi):
    """문장을 뺀 답이나 다시 쓴 답은 구절이 그 답의 것이 아니므로 바꾸지 않는다(근거 확인이 받쳐지지 않는다고 한 뒤의 경로)."""
    bad = j(claims=[{"claim": "구성원은 빠질 수 없다", "quote": QUOTE, "scope": None}], reason="일부 문장이 근거가 없다", grounded=False,
            reason_code="unsupported", unsupported_sentences=["엉뚱한 문장입니다"])
    out, _ = _opt_run(multi, [bad, GROUNDED], answer=cite(X, text="구성원은 빠질 수 없습니다. 엉뚱한 문장입니다"))
    info = out.get("grounding") or {}
    assert not info.get("head_owner")


# ---------- path (측정 기록) ----------
def test_quote_rows_lists_only_chunk_ids_per_fact():
    chunks = [CORE[0].model_dump(), INTRO.model_dump()]
    obj = {"checks": [{"fact": "사실 하나", "quote": CORE[0].text.split("\n", 1)[1]}, {"fact": "사실 둘", "quote": "NOTHING FOUND"},
                      {"fact": "사실 셋", "quote": INTRO.text.split("\n", 1)[1]}, {"fact": "사실 넷", "quote": "x"}]}
    assert AF.quote_rows(obj, chunks) == [[CORE[0].chunk_id], [], [INTRO_ID], []]
    assert AF.quote_rows(None, chunks) == [] and AF.quote_rows({"checks": "x"}, chunks) == []
    assert len(AF.quote_rows({"checks": [{"fact": "f", "quote": "NOTHING FOUND"}] * 12}, chunks)) == 8


def _full_run(multi=False, **kw):
    return intro_run(multi, INTRO, **kw)[0]


@pytest.mark.parametrize("multi", [False, True])
def test_path_meta_has_the_sub_queries_context_ids_quotes_and_the_pick(multi):
    out = _full_run(multi)
    path = path_meta(out)["path"]
    assert path["sub_queries"] == SUBS and path["context_ids"] == _ids(out["chunks"]) and path["intro_chunk_ids"] == [INTRO_ID]
    assert path["judge_quote_ids"] == [INTRO_ID] and path["judge_quotes"] == [[INTRO_ID]]
    assert path["best2"]["pick"] == 0 and path["best2"]["rule"] == "core_first" and path["retries"] == 0
    assert path["grounding"]["llm"] == "grounded"
    flat = repr(path)
    assert "quote" not in path["best2"] and INTRO.text.split("\n", 1)[1] not in flat  # 구절 글은 싣지 않는다


def test_path_meta_is_empty_without_a_search():
    assert path_meta({"kind": "refuse", "answer": "도메인 밖"}) == {}
    assert path_meta({"chunks": [], "kind": "refuse"}) == {}
    assert path_meta({}) == {}


def test_path_meta_does_not_change_the_answer_and_the_done_event_carries_it():
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(INTRO), answer=answering_intro)
    g = build_graph(fn, llm=m, judge_answer="parallel_all", intro_search=_intro_search(), decompose=True, max_research=1)
    events = list(stream_events(g, {"question": Q_ESC, "user_id": "u1", "thread_id": "tp", "as_of": "2025-06-01"}, thread_id="tp"))
    done = events[-1]
    assert done.type == "done" and done.data["path"]["sub_queries"] == SUBS and done.data["path"]["judge_quotes"] == [[INTRO_ID]]
    assert done.data["answer_id"] and "refuse_stage" not in done.data  # 기존 칸은 그대로
    assert [e.type for e in events].count("citation") == 1


def test_done_has_no_path_without_a_search():
    m = llm(classify=j(route="out_of_domain"))
    g = build_graph(lambda q: [ESC, IMOC], llm=m)
    events = list(stream_events(g, {"question": "오늘 점심 뭐 먹지?", "user_id": "u1", "thread_id": "tn", "as_of": "2025-06-01"}, thread_id="tn"))
    assert events[-1].type == "done" and "path" not in events[-1].data


def test_judge_quotes_do_not_exist_without_the_best_of_two_switch(monkeypatch):
    monkeypatch.delenv("GRAPH_ANSWER_BEST2")
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(CORE[0]), answer=lambda u: cite(CORE[0]))
    out = run(build_graph(fn, llm=m, judge_answer="parallel_all", decompose=True, max_research=1), Q_ESC)
    assert "judge_quotes" not in out and "judge_quote_ids" not in out


def test_judge_input_helper_still_marks_nothing_when_no_extra_is_given():
    chunks = [c.model_dump() for c in (CORE[0], INTRO)]
    assert "[보충]" not in P.judge_user(Q_ESC, chunks, SUBS)
