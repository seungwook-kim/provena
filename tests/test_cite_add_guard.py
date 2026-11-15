"""사전 등록 62.70 `GRAPH_CITE_ADD_GUARD` 시험(코드 기본 꺼짐, 서비스 설정에서 켬). 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

- K: 기준 인용이 판정 구절 청크 밖이면 그 인용에 기대어 인용을 더하지 않는다(`pick_extra`, `pick_phrase_extra`의 `anchor_ok`, 배선은 `build.ground_checked`).
- L: 문장 공유로 더할 청크의 공유 글이 그 청크의 겹친 머리에만 있으면 앞 청크를 더한다(`pick_phrase_extra`의 `head_fix`).
- M: 다시 쓴 답과 문장을 뺀 답에도 재확인 구절로 겹친 머리 인용 바로잡기를 한다(`revise_answer`, `redraft_answer`, `ground_checked`).
- 스위치를 끄면 지금과 같다.
"""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, REVIEW, REVIEW_TOO, cite, llm, mk, run, searcher
from test_trace_fixes_1113 import GROUNDED, QUOTE, Q_OPT, X, Y, _ids
from test_widened_first_search import quoting

from backend.graph import answer_fixes as AF
from backend.graph import service_profile as SP
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_CITE_ADD_GUARD", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_BEST2_SAMEDOC",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_GROUNDING_QUOTE", "GRAPH_ANSWER_BEST2",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_CITE_EXPAND", "GRAPH_CITE_PHRASE", "GRAPH_DROP_SCOPED_CITES", "GRAPH_CITE_CONSENSUS",
                 "GRAPH_INTRO_FILL", "GRAPH_SPECULATE_GROUND", "GRAPH_ADOPT_GROUNDED_CANDIDATE", "GRAPH_UNCHANGED_REJUDGE", "GRAPH_KEEP_CITES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")


def d(c):
    return c.model_dump()


# ---------- 공유 문장 청크(L): 앞 청크 P_PREV의 끝이 다음 청크 P_NEXT의 머리에 그대로 복사돼 있다 ----------
SHARED = "Every new SaaS vendor must pass the security questionnaire before the purchase order is approved by the finance team."
ANCHOR = mk(f"Policy summary. {SHARED}", title="Vendor Policy", seq=73001, article="Summary")
P_PREV = mk(f"How to start. {SHARED}", title="Purchasing Guide", seq=73002, article="Start")
P_NEXT = mk(f"{SHARED} After approval the request moves to legal review and contract signature.", title="Purchasing Guide", seq=73002, article="Start")
P_OWN = mk(f"{SHARED} Reminder: {SHARED}", title="Purchasing Guide", seq=73002, article="Start")   # 겹친 머리 뒤 자기 본문에도 같은 글이 있다


def test_l_head_owner_is_found_in_the_context_or_read():
    assert AF.head_owner_of(d(P_NEXT), [d(ANCHOR), d(P_PREV)])[0]["chunk_id"] == P_PREV.chunk_id
    seen: list = []
    got = AF.head_owner_of(d(P_NEXT), [d(ANCHOR)], prev_reader=lambda c: seen.append(c["chunk_id"]) or d(P_PREV))
    assert got[0]["chunk_id"] == P_PREV.chunk_id and seen == [P_NEXT.chunk_id]
    assert AF.head_owner_of(d(P_NEXT), [d(ANCHOR)], prev_reader=lambda c: (_ for _ in ()).throw(RuntimeError("db"))) is None
    assert AF.head_owner_of(d(P_NEXT), [d(ANCHOR)], prev_reader=lambda c: d(REVIEW)) is None and AF.head_owner_of(d(P_NEXT), [d(ANCHOR)]) is None


def test_l_adds_the_previous_chunk_when_the_shared_text_is_only_in_the_head():
    log: list = []
    got = AF.pick_phrase_extra([d(ANCHOR)], [d(ANCHOR), d(P_NEXT)], head_fix=True, prev_reader=lambda c: d(P_PREV), log=log)
    assert [(c["chunk_id"], i) for c, i in got] == [(P_PREV.chunk_id, 0)] and log == [{"from": P_NEXT.chunk_id, "to": P_PREV.chunk_id}]
    assert [c["chunk_id"] for c, _ in AF.pick_phrase_extra([d(ANCHOR)], [d(ANCHOR), d(P_NEXT)])] == [P_NEXT.chunk_id]   # 끄면 지금처럼


def test_l_keeps_the_chunk_when_its_own_text_shares_the_sentence_or_no_previous_chunk():
    log: list = []
    got = AF.pick_phrase_extra([d(ANCHOR)], [d(ANCHOR), d(P_OWN)], head_fix=True, prev_reader=lambda c: d(P_PREV), log=log)
    assert [c["chunk_id"] for c, _ in got] == [P_OWN.chunk_id] and log == []
    got = AF.pick_phrase_extra([d(ANCHOR)], [d(ANCHOR), d(P_NEXT)], head_fix=True, prev_reader=None, log=log)
    assert [c["chunk_id"] for c, _ in got] == [P_NEXT.chunk_id] and log == []   # 앞 청크를 찾지 못하면 그대로


H1 = "Every new SaaS vendor must pass the security"                                   # 공유 문장의 앞 8단어
H2 = "questionnaire before the purchase order is approved by the finance team."         # 뒤 10단어
P_PREV_SHORT = mk(f"How to start and which form to use for the request. {H1}", title="Purchasing Guide", seq=73002, article="Start")
P_SPLIT = mk(f"{H1} {H2} After approval the request moves to legal review.", title="Purchasing Guide", seq=73002, article="Start")


def test_l_keeps_the_chunk_when_the_previous_chunk_does_not_share_enough():
    """공유 글이 겹친 머리와 자기 본문에 걸쳐 있어 앞 청크도 문턱(12단어)을 넘지 못하면 원래 청크를 더한다(리뷰 보완)."""
    assert AF.head_overlap(d(P_SPLIT), d(P_PREV_SHORT)) > 0
    log: list = []
    got = AF.pick_phrase_extra([d(ANCHOR)], [d(ANCHOR), d(P_SPLIT)], head_fix=True, prev_reader=lambda c: d(P_PREV_SHORT), log=log)
    assert [c["chunk_id"] for c, _ in got] == [P_SPLIT.chunk_id] and log == []


def test_k_allows_an_add_when_the_candidate_itself_is_a_judge_quote_chunk():
    """K 예외(리뷰 보완): 기준 인용이 판정 구절 청크 밖이어도 더할 후보 자체가 판정 구절 청크면 더한다."""
    ctx = [d(ANCHOR), d(P_NEXT)]
    blocked = dict(anchor_ok=lambda x: False)
    assert AF.pick_phrase_extra([d(ANCHOR)], ctx, **blocked) == []
    assert [c["chunk_id"] for c, _ in AF.pick_phrase_extra([d(ANCHOR)], ctx, **blocked, add_ok=lambda c: c["chunk_id"] == P_NEXT.chunk_id)] == [P_NEXT.chunk_id]
    assert [c["chunk_id"] for c, _ in AF.pick_extra([d(REVIEW)], [d(REVIEW), d(REVIEW_TOO)], **blocked, add_ok=lambda c: True)] == [REVIEW_TOO.chunk_id]


def test_l_does_not_add_when_the_previous_chunk_is_already_cited():
    got = AF.pick_phrase_extra([d(ANCHOR), d(P_PREV)], [d(ANCHOR), d(P_PREV), d(P_NEXT)], head_fix=True)
    assert got == []


# ---------- K ----------
def test_k_pick_extra_leans_only_on_allowed_anchors():
    assert [c["chunk_id"] for c, _ in AF.pick_extra([d(REVIEW)], [d(REVIEW), d(REVIEW_TOO)])] == [REVIEW_TOO.chunk_id]
    assert AF.pick_extra([d(REVIEW)], [d(REVIEW), d(REVIEW_TOO)], anchor_ok=lambda x: False) == []
    assert [c["chunk_id"] for c, _ in AF.pick_extra([d(REVIEW)], [d(REVIEW), d(REVIEW_TOO)], anchor_ok=lambda x: True)] == [REVIEW_TOO.chunk_id]


def test_k_pick_phrase_extra_leans_only_on_allowed_anchors():
    ctx = [d(ANCHOR), d(P_NEXT)]
    assert AF.pick_phrase_extra([d(ANCHOR)], ctx, anchor_ok=lambda x: x["chunk_id"] != ANCHOR.chunk_id) == []
    assert [c["chunk_id"] for c, _ in AF.pick_phrase_extra([d(ANCHOR)], ctx, anchor_ok=lambda x: True)] == [P_NEXT.chunk_id]


def _expand_run(monkeypatch, *, guard: bool, quote, multi=False):
    monkeypatch.setenv("GRAPH_CITE_EXPAND", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")   # 판정 구절 청크(`judge_quote_ids`)는 BO2가 켜져 있을 때 남는다(서비스 설정은 켬)
    if guard:
        monkeypatch.setenv("GRAPH_CITE_ADD_GUARD", "1")
    fn, _ = searcher((("리뷰", [REVIEW, REVIEW_TOO, ESC]),))
    m = llm(answer=cite(REVIEW), judge=quoting(quote))
    return run((build_multi_graph if multi else build_graph)(fn, llm=m), "코드 리뷰 첫 응답은 며칠 안에 해야 해?")


@pytest.mark.parametrize("multi", [False, True])
def test_k_in_the_graph_skips_an_add_when_the_anchor_is_outside_the_judge_quotes(monkeypatch, multi):
    out = _expand_run(monkeypatch, guard=True, quote=ESC, multi=multi)   # 판정 구절은 ESC, 답의 인용 REVIEW는 그 밖
    assert _ids(out["citations"]) == [REVIEW.chunk_id] and "cite_expand" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_k_in_the_graph_keeps_the_add_when_the_anchor_is_a_judge_quote_chunk(monkeypatch, multi):
    out = _expand_run(monkeypatch, guard=True, quote=REVIEW, multi=multi)
    assert _ids(out["citations"]) == [REVIEW.chunk_id, REVIEW_TOO.chunk_id] and out["grounding"]["cite_expand"] == [REVIEW_TOO.chunk_id]


def test_k_off_keeps_the_add_outside_the_judge_quotes(monkeypatch):
    out = _expand_run(monkeypatch, guard=False, quote=ESC)
    assert _ids(out["citations"]) == [REVIEW.chunk_id, REVIEW_TOO.chunk_id]


def test_k_without_judge_quotes_keeps_todays_adds(monkeypatch):
    monkeypatch.delenv("GRAPH_JUDGE_QUOTE")
    monkeypatch.setenv("GRAPH_CITE_EXPAND", "1")
    monkeypatch.setenv("GRAPH_CITE_ADD_GUARD", "1")
    fn, _ = searcher((("리뷰", [REVIEW, REVIEW_TOO, ESC]),))
    out = run(build_graph(fn, llm=llm(answer=cite(REVIEW))), "코드 리뷰 첫 응답은 며칠 안에 해야 해?")
    assert _ids(out["citations"]) == [REVIEW.chunk_id, REVIEW_TOO.chunk_id]   # 판정 구절이 없으면 기준을 알 수 없어 지금처럼 더한다


@pytest.mark.parametrize("guard", [False, True])
def test_l_in_the_graph_records_the_swap_only_when_on(monkeypatch, guard):
    monkeypatch.setenv("GRAPH_CITE_PHRASE", "1")
    if guard:
        monkeypatch.setenv("GRAPH_CITE_ADD_GUARD", "1")
    fn, _ = searcher((("구매", [ANCHOR, P_NEXT]),))
    m = llm(answer=cite(ANCHOR), judge=quoting(ANCHOR))
    out = run(build_graph(fn, llm=m, prev_chunk=lambda c: P_PREV if c["chunk_id"] == P_NEXT.chunk_id else None), "구매 승인 전에 무엇을 해야 해?")
    if guard:
        assert _ids(out["citations"]) == [ANCHOR.chunk_id, P_PREV.chunk_id]
        assert out["grounding"]["cite_phrase_head"] == [{"from": P_NEXT.chunk_id, "to": P_PREV.chunk_id}]
    else:
        assert _ids(out["citations"]) == [ANCHOR.chunk_id, P_NEXT.chunk_id] and "cite_phrase_head" not in out["grounding"]


# ---------- M ----------
BAD = j(claims=[{"claim": "구성원은 빠질 수 없다", "quote": QUOTE, "scope": None}], reason="일부 문장이 근거가 없다", grounded=False,
        reason_code="unsupported", unsupported_sentences=["엉뚱한 문장입니다"])


def _opt_run(monkeypatch, multi, *, guard, answer):
    if guard:
        monkeypatch.setenv("GRAPH_CITE_ADD_GUARD", "1")
    fn, _ = searcher((("프로그램", [Y, X]),))
    m = llm(answer=answer, grounding=[BAD, GROUNDED])
    return run((build_multi_graph if multi else build_graph)(fn, llm=m, grounding_llm=True), Q_OPT)


@pytest.mark.parametrize("multi", [False, True])
def test_m_swaps_the_head_citation_after_the_sentence_was_dropped(monkeypatch, multi):
    """문장을 뺀 답(revise)도 재확인 구절이 겹친 머리에만 있으면 원래 청크로 바꾼다. 끄면 지금처럼 바꾸지 않는다."""
    answer = cite(X, text="엉뚱한 문장입니다. 구성원은 빠질 수 없습니다")   # 인용 표시가 남는 문장이 뒤에 있어야 빼고 남은 답이 인용 검사를 지난다
    on = _opt_run(monkeypatch, multi, guard=True, answer=answer)
    assert on["kind"] == "answer" and on["grounding"].get("revised")
    assert _ids(on["citations"]) == [Y.chunk_id] and on["grounding"]["head_owner"] == [{"from": X.chunk_id, "to": Y.chunk_id}]
    assert "_claim_quotes" not in on["grounding"]
    monkeypatch.delenv("GRAPH_CITE_ADD_GUARD")
    off = _opt_run(monkeypatch, multi, guard=False, answer=answer)
    assert _ids(off["citations"]) == [X.chunk_id] and not off["grounding"].get("head_owner")


@pytest.mark.parametrize("multi", [False, True])
def test_m_swaps_the_head_citation_in_a_redrafted_answer(monkeypatch, multi):
    answers = [cite(X, text="구성원은 빠질 수 없습니다. 엉뚱한 문장입니다"), cite(X, text="구성원은 이 프로그램에서 빠질 수 없습니다")]
    on = _opt_run(monkeypatch, multi, guard=True, answer=answers)
    assert on["kind"] == "answer" and on["grounding"].get("redrafted")
    assert _ids(on["citations"]) == [Y.chunk_id] and on["grounding"]["head_owner"] == [{"from": X.chunk_id, "to": Y.chunk_id}]


# ---------- 서비스 설정 ----------
def test_the_switch_is_off_in_code_and_on_in_the_service_profile(monkeypatch):
    assert AF.cite_add_guard_enabled() is False
    assert SP.SERVICE_ENV["GRAPH_CITE_ADD_GUARD"] == "1" and "GRAPH_CITE_ADD_GUARD" not in SP.CANDIDATE_ENV
    env: dict = {}
    SP.apply_service_profile(env)
    assert env["GRAPH_CITE_ADD_GUARD"] == "1"
    monkeypatch.setenv("GRAPH_CITE_ADD_GUARD", "1")
    assert AF.cite_add_guard_enabled() is True
