"""남은 문항 수정안 시험(기본 꺼짐). SP 추측 실행, FL 판정 기록, BO2 답 두 개 중 고르기.
가짜 모델과 가짜 검색기만 쓴다. HT(제목 경로 머리 청크), CP(인용 고르기 규칙), SS(재검색 새 청크만), CS(인용 합의), R3(도입부 채우기), 같은 문서 이웃 절 우대,
SN(범위 메모 거절, `GRAPH_SCOPE_NOTE_REFUSE`), PT(안내만 있는 근거 거절, `GRAPH_POINTER_REFUSE`) 시험은 사전 등록 62.72로 그 장치를 코드째 제거하면서 지웠다.
남은 SN·PT 시험은 옛 스위치 이름을 켜도 답이 바뀌지 않는지(제거 확인)만 본다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import ESC, IMOC, Q_ESC, Q_REVIEW, REVIEW, SUBS, cite, llm, run


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_SECTION_KEEPS_RESEARCH", "GRAPH_GROUNDING_QUOTE",
                 "GRAPH_REFUSE_ON_NONE", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S",
                 "GRAPH_CITE_MULTI", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_STOP_STALLED_SEARCH",
                 "GRAPH_DECOMPOSE_CAP_S", "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_QUOTE", "GRAPH_JUDGE_ANSWER",
                 "GRAPH_SPEC_STOP_GROUND", "GRAPH_NONE_VOTE_WAIT_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def graph(multi, fn, m, **kw):
    return build_multi_graph(fn, llm=m, **kw) if multi else build_graph(fn, llm=m, **kw)


# ---------- SN ----------
NOTE_BAD = "Tableau 가이드는 대시보드 용도에 한정되며, 일반 회사 문서의 로고 규칙은 자료에 직접 없음"


@pytest.mark.parametrize("multi", [False, True])
def test_scope_note_never_turns_a_sufficient_judgement_into_a_refusal(monkeypatch, multi):
    """사전 등록 62.72: 범위 메모 거절을 제거했다. 옛 스위치 이름을 켜도 충분 판정은 그대로 답으로 간다."""
    monkeypatch.setenv("GRAPH_SCOPE_NOTE_REFUSE", "1")
    judged = j(checks=[{"fact": "리뷰 기한", "value": "2영업일"}], sufficient=True, partial=False, reason="", missing=[], scope_note=NOTE_BAD, clarify=None)
    m = llm(judge=judged, answer=cite(REVIEW))
    out = run(graph(multi, lambda q: [REVIEW], m), Q_REVIEW)
    assert out["kind"] == "answer" and m.count("judge") == 1


# ---------- SP ----------
def _sp_run(monkeypatch, multi, *, on, gate, split, route="rule"):
    if on:
        monkeypatch.setenv("GRAPH_SPECULATE_FIRST", "1")
    searched: list = []

    def fn(q):
        searched.append((q.query, tuple(q.sub_queries or ())))
        return [ESC, IMOC]
    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), decompose_gate=j(split=gate, sub_questions=SUBS if gate else []),
            judge=j(sufficient=True, reason="", clarify=None), classify=j(route=route), answer=lambda u: cite(ESC))
    out = run(graph(multi, fn, m, decompose=True, parallel_intake=True, skip_first_rewrite=True), Q_ESC)
    return out, m, searched


@pytest.mark.parametrize("multi", [False, True])
def test_speculation_is_used_when_the_split_says_one_question(monkeypatch, multi):
    base, m0, s0 = _sp_run(monkeypatch, multi, on=False, gate=False, split=False)
    out, m, s = _sp_run(monkeypatch, multi, on=True, gate=False, split=False)
    assert m0.count("decompose_gate") == 0 and m.count("decompose_gate") == 1
    assert m.count("judge") == m0.count("judge") == 1 and s == s0 and len(s) == 1
    assert out["answer"] == base["answer"] and [c["chunk_id"] for c in out["citations"]] == [c["chunk_id"] for c in base["citations"]]
    assert out["search_stats"].get("speculated") == "used" and "speculated" not in base["search_stats"]


@pytest.mark.parametrize("multi", [False, True])
def test_speculation_is_dropped_when_the_split_splits(monkeypatch, multi):
    base, m0, s0 = _sp_run(monkeypatch, multi, on=False, gate=False, split=True)
    out, m, s = _sp_run(monkeypatch, multi, on=True, gate=False, split=True)
    assert out["sub_queries"] == SUBS == base["sub_queries"]
    assert s[-1] == s0[-1] and s0[-1][1] == tuple(SUBS)  # 쓴 첫 검색은 하위 질문 검색이다
    assert m.count("judge") <= m0.count("judge") + 1  # 버린 판정은 많아야 하나다(판정 전에 멈출 수도 있다)
    assert out["answer"] == base["answer"] and out["search_stats"].get("speculated") == "dropped"


def test_no_speculation_when_the_gate_splits_or_the_route_is_not_policy(monkeypatch):
    out, m, s = _sp_run(monkeypatch, False, on=True, gate=True, split=False)
    assert m.count("decompose_gate") == 1 and m.count("judge") == 1 and len(s) == 1 and out["search_stats"].get("speculated") == "not_run"
    out, m, s = _sp_run(monkeypatch, False, on=True, gate=False, split=False, route="out_of_domain")
    assert out["kind"] == "refuse" and m.count("judge") == 0 and s == []


# ---------- FL ----------
CHECKS = [{"fact": "에스컬레이션", "value": "IMOC"}]
PICKS = [{"fact": "에스컬레이션", "value": "IMOC", "chunk_id": ESC.chunk_id}]


def _fl_run(monkeypatch, multi, on):
    if on:
        monkeypatch.setenv("GRAPH_FACTS_LOG", "1")
    else:
        monkeypatch.delenv("GRAPH_FACTS_LOG", raising=False)
    answer = j(asked=["에스컬레이션"], picks=PICKS, answer=f"답 [{ESC.chunk_id}]", citations=[{"chunk_id": ESC.chunk_id}], period_covered=True)
    m = llm(decompose=j(split=False, sub_questions=[]), judge=j(checks=CHECKS, sufficient=True, reason="", clarify=None), answer=answer)
    return run(graph(multi, lambda q: [ESC, IMOC], m, decompose=True, parallel_intake=True, skip_first_rewrite=True), Q_ESC)


@pytest.mark.parametrize("multi", [False, True])
def test_facts_log_records_checks_and_answer_facts_without_changing_the_answer(monkeypatch, multi):
    off = _fl_run(monkeypatch, multi, False)
    on = _fl_run(monkeypatch, multi, True)
    assert "judge_checks_log" not in off and "answer_facts" not in off
    assert on["answer"] == off["answer"] and [c["chunk_id"] for c in on["citations"]] == [c["chunk_id"] for c in off["citations"]]
    assert on["judge_checks_log"][0]["checks"] == CHECKS and on["judge_checks_log"][0]["sufficient"] is True and on["judge_checks_log"][0]["retries"] == 0
    assert on["answer_facts"] == {"asked": ["에스컬레이션"], "picks": PICKS}


def test_facts_helpers_keep_only_well_formed_items():
    assert F.judge_facts({"checks": [{"fact": "a"}, "x"], "sufficient": False, "_votes": {"n": 3, "agree": 2}}, 1) == \
        {"retries": 1, "sufficient": False, "partial": None, "checks": [{"fact": "a"}], "votes": {"n": 3, "agree": 2}}
    assert F.judge_facts({}, 0)["checks"] is None
    assert F.answer_facts({"asked": ["a", 1], "picks": "x"}) == {"asked": ["a"], "picks": None}


def test_gate_split_reads_the_same_rule():
    from backend.graph.decompose import SYSTEM_GATE, gate_split
    assert SYSTEM_GATE.startswith("[[task:decompose_gate]]")
    assert gate_split(lambda s, u: '{"split": true, "sub_questions": ["가?", "나?"]}', "가와 나?") is True
    assert gate_split(lambda s, u: '{"split": true, "sub_questions": ["가?"]}', "가와 나?") is False
    assert gate_split(lambda s, u: "x", "가?") is None

    def boom(s, u):
        raise ConnectionError("x")
    assert gate_split(boom, "가?") is None


# ---------- PT ----------


def test_pointer_quote_does_not_refuse_a_grounded_answer(monkeypatch):
    """사전 등록 62.72: 안내만 있는 근거 거절을 제거했다. 옛 스위치 이름을 켜도 받쳐진 답은 그대로 나간다."""
    monkeypatch.setenv("GRAPH_POINTER_REFUSE", "1")
    monkeypatch.setenv("GRAPH_GROUNDING_QUOTE", "1")
    ok = j(claims=[{"claim": "안내", "quote": "For more information, please refer to the following links.", "scope": None}], reason="", grounded=True, reason_code="", unsupported_sentences=[])
    m = llm(answer=cite(REVIEW, text="자세한 내용은 링크를 보라"), grounding=ok)
    out = run(build_graph(lambda q: [REVIEW], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == "answer" and "pointer_only" not in out["grounding"]
    assert sum(1 for t, _ in m.calls if t == "answer") == 1


# ---------- BO2 답 두 개 중 판정 구절과 맞는 쪽(`GRAPH_ANSWER_BEST2`) ----------
def _draft(*ids):
    return {"answer": "답", "raw_citations": [{"chunk_id": i} for i in ids], "drafted": True, "skills_used": []}


def test_best2_rules_without_quotes_and_ties_keep_the_first():
    a, b = _draft("x1"), _draft("x2", "x3")
    assert F.pick_best2(a, b, [])[0] is a and F.pick_best2(a, b, [])[1]["why"] == "구절 없음, 첫 후보"
    got, log = F.pick_best2(a, _draft("s1"), ["s1"])
    assert got["raw_citations"] == [{"chunk_id": "s1"}] and log["pick"] == 1 and log["why"] == "S 안 인용 청크 수"
    got, log = F.pick_best2(_draft("s1", "o1", "o2"), _draft("s1", "o1"), ["s1"])
    assert log["pick"] == 1 and log["why"] == "S 밖 인용 수"
    got, log = F.pick_best2(_draft("s1", "o1"), _draft("o2", "s1"), ["s1"])
    assert log["pick"] == 0 and log["why"] == "동점, 첫 후보"
    assert log["cands"] == [{"cited": ["s1", "o1"], "in_s": 1, "out_s": 1}, {"cited": ["o2", "s1"], "in_s": 1, "out_s": 1}]
    assert F.pick_best2(a, None, ["s1"])[0] is a and F.pick_best2(a, None, ["s1"])[1]["why"] == "둘째 후보 없음"


def test_quote_chunk_ids_finds_chunks_holding_a_quote():
    chunks = [{"chunk_id": ESC.chunk_id, "text": ESC.text}, {"chunk_id": IMOC.chunk_id, "text": IMOC.text}]
    obj = {"checks": [{"fact": "a", "quote": "the incident is escalated to the IMOC."}, {"fact": "b", "quote": "NOTHING FOUND"}, {"fact": "c", "quote": "IMOC"}]}
    assert F.quote_chunk_ids(obj, chunks) == [ESC.chunk_id]  # 짧은 구절(IMOC)은 쓰지 않는다
    assert F.quote_chunk_ids({"checks": [{"fact": "a", "value": "IMOC"}]}, chunks) == []  # 판정 구절 끔: value만 있다
    assert F.quote_chunk_ids(None, chunks) == []


QUOTED = j(checks=[{"fact": "에스컬레이션", "quote": "the incident is escalated to the IMOC"}], sufficient=True, partial=False, reason="",
           missing=[], scope_note=None, clarify=None, query="")
VALUED = j(checks=[{"fact": "에스컬레이션", "value": "IMOC"}], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
ON_IMOC = j(asked=["사실"], picks=[], answer=f"답 [{IMOC.chunk_id}]", citations=[{"chunk_id": IMOC.chunk_id}], period_covered=True)
ON_ESC = j(asked=["사실"], picks=[], answer=f"답 [{ESC.chunk_id}]", citations=[{"chunk_id": ESC.chunk_id}], period_covered=True)


def _bo2(monkeypatch, multi, *, on, quote, mode):
    if on:
        monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    if quote:
        monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    m = llm(judge=QUOTED if quote else VALUED, answer=[ON_IMOC, ON_ESC])
    out = run(graph(multi, lambda q: [ESC, IMOC], m, judge_answer=mode), Q_ESC)
    return out, m


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("mode", ["parallel_all", None])
def test_best2_picks_the_draft_citing_the_quoted_chunk(monkeypatch, multi, mode):
    out, m = _bo2(monkeypatch, multi, on=True, quote=True, mode=mode)
    assert m.count("answer") == 2 and out["kind"] == "answer"
    assert [c["chunk_id"] for c in out["citations"]] == [ESC.chunk_id]  # 어느 순서로 와도 구절이 든 청크를 인용한 답
    assert out["best2_log"]["quote_ids"] == [ESC.chunk_id] and out["best2_log"]["why"] == "S 안 인용 청크 수"


@pytest.mark.parametrize("multi", [False, True])
def test_best2_without_quotes_keeps_the_first_draft(monkeypatch, multi):
    out, m = _bo2(monkeypatch, multi, on=True, quote=False, mode="parallel_all")
    assert m.count("answer") == 2 and out["best2_log"]["why"] == "구절 없음, 첫 후보" and out["best2_log"]["pick"] == 0


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("mode", ["parallel_all", None])
def test_best2_off_keeps_one_draft_and_the_path(monkeypatch, multi, mode):
    out, m = _bo2(monkeypatch, multi, on=False, quote=True, mode=mode)
    assert m.count("answer") == 1 and "best2_log" not in out and "judge_quote_ids" not in out
    assert [c["chunk_id"] for c in out["citations"]] == [IMOC.chunk_id]  # 첫 답 그대로


