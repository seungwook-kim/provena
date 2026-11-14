"""남은 문항 수정안 시험(기본 꺼짐). SN `GRAPH_SCOPE_NOTE_REFUSE`, CP `GRAPH_CITE_PICK`, R3를 첫 검색에만 붙이기.
가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j

from backend.graph import answer_fixes as F
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from test_answer_fixes_graph import ESC, IMOC, PARTIAL, Q_ESC, Q_REVIEW, REVIEW, SUBS, cite, llm, mk, run


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_SCOPE_NOTE_REFUSE", "GRAPH_CITE_PICK", "GRAPH_INTRO_FILL", "GRAPH_REQUERY_SKIP_SEEN", "GRAPH_CITE_CONSENSUS",
                 "GRAPH_POINTER_REFUSE", "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_SECTION_KEEPS_RESEARCH", "GRAPH_GROUNDING_QUOTE", "GRAPH_DROP_SCOPED_CITES", "GRAPH_CITE_PHRASE",
                 "GRAPH_QUERY_BRANCHES", "GRAPH_RESEARCH_SAME_PAGE", "GRAPH_REFUSE_ON_NONE", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S",
                 "GRAPH_CITE_EXPAND", "GRAPH_CITE_MULTI", "GRAPH_TEAM_LAST", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_STOP_STALLED_SEARCH",
                 "GRAPH_DECOMPOSE_CAP_S", "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_ANSWER_BEST2", "GRAPH_BEST2_SAMEDOC", "GRAPH_JUDGE_QUOTE", "GRAPH_JUDGE_ANSWER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def graph(multi, fn, m, **kw):
    return build_multi_graph(fn, llm=m, **kw) if multi else build_graph(fn, llm=m, **kw)


# ---------- SN ----------
NOTE_BAD = "Tableau 가이드는 대시보드 용도에 한정되며, 일반 회사 문서의 로고 규칙은 자료에 직접 없음"


def test_scope_note_refuses_needs_both_parts():
    assert F.scope_note_refuses({"sufficient": True, "scope_note": NOTE_BAD})
    assert F.scope_note_refuses({"sufficient": True, "scope_note": "벤더 조항은 외부 벤더에만 적용되고 일반 규칙은 자료에 없다"})
    assert not F.scope_note_refuses({"sufficient": True, "scope_note": "다른 팀이나 커뮤니티 기여자 MR에 대한 기준은 자료에 없다."})  # 한정이 없다
    assert not F.scope_note_refuses({"sufficient": True, "scope_note": "두 질문 모두 자료에 직접 답이 있음"})
    assert not F.scope_note_refuses({"sufficient": True, "scope_note": "대시보드 용도에 한정된 문서다"})  # 부재가 없다
    assert not F.scope_note_refuses({"sufficient": False, "scope_note": NOTE_BAD}) and not F.scope_note_refuses({"sufficient": True, "scope_note": None})


@pytest.mark.parametrize("multi", [False, True])
def test_scope_note_refuse_refuses_in_the_graph(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SCOPE_NOTE_REFUSE", "1")
    judged = j(checks=[{"fact": "로고 규칙", "value": "링크 참고"}], sufficient=True, partial=False, reason="", missing=[], scope_note=NOTE_BAD, clarify=None)
    m = llm(judge=[judged, judged], answer=cite(REVIEW))
    out = run(graph(multi, lambda q: [REVIEW], m, max_research=1), "회사 문서에 회사 로고 넣을 때 브랜드 가이드라인 어떻게 돼?")
    assert out["kind"] == "refuse"  # 일부 근거로 보고 재검색한 뒤, 나뉘지 않은 질문이라 거절한다
    assert sum(1 for t, _ in m.calls if t == "judge") == 2


@pytest.mark.parametrize("multi", [False, True])
def test_scope_note_refuse_on_a_split_question_researches_and_answers(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_SCOPE_NOTE_REFUSE", "1")
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    note = j(checks=[], sufficient=True, partial=False, reason="", missing=[], clarify=None, query="IMOC",
             scope_note="IMOC 자료는 다른 팀에 한정된 절차이며 일반 IMOC 절차는 자료에 없음")
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=[note, j(sufficient=True, reason="", clarify=None)],
            answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, lambda q: [ESC], m, decompose=True, max_research=1, page_search=lambda *a: [IMOC]), Q_ESC)
    assert out["kind"] == "answer" and IMOC.chunk_id in [c["chunk_id"] for c in out["citations"]]  # 재검색 뒤 새 근거로 쓴 답이다(앞 답을 쓰지 않는다)


def test_scope_note_refuse_off_or_plain_note_keeps_the_answer(monkeypatch):
    judged = j(checks=[{"fact": "리뷰 기한", "value": "2영업일"}], sufficient=True, partial=False, reason="", missing=[], scope_note=NOTE_BAD, clarify=None)
    out = run(build_graph(lambda q: [REVIEW], llm=llm(judge=judged, answer=cite(REVIEW))), Q_REVIEW)
    assert out["kind"] == "answer"
    monkeypatch.setenv("GRAPH_SCOPE_NOTE_REFUSE", "1")
    plain = j(checks=[{"fact": "리뷰 기한", "value": "2영업일"}], sufficient=True, partial=False, reason="", missing=[], scope_note="두 문서 모두 2영업일이다", clarify=None)
    out = run(build_graph(lambda q: [REVIEW], llm=llm(judge=plain, answer=cite(REVIEW))), Q_REVIEW)
    assert out["kind"] == "answer"


# ---------- CP ----------
def _answer_systems(monkeypatch, on: bool, wait: bool):
    if on:
        monkeypatch.setenv("GRAPH_CITE_PICK", "1")
    if wait:
        monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "5")
    m = llm(answer=cite(REVIEW, text="리뷰는 2영업일 안이다"), answer_fast=cite(REVIEW, text="리뷰는 2영업일 안이다"))
    seen: list[str] = []
    inner = m.invoke

    def invoke(messages, *a, **k):
        if "[[task:answer" in messages[0].content:
            seen.append(messages[0].content)
        return inner(messages, *a, **k)
    m.invoke = invoke
    out = run(build_graph(lambda q: [REVIEW], llm=m), Q_REVIEW)
    return out, seen


@pytest.mark.parametrize("wait", [False, True])
def test_cite_pick_adds_the_rule_to_every_answer_prompt(monkeypatch, wait):
    out, seen = _answer_systems(monkeypatch, True, wait)
    assert out["kind"] == "answer" and seen and all(F.CITE_PICK_RULE in s and s.count("JSON 한 개만 출력한다.") == 1 for s in seen)


def test_cite_pick_off_keeps_the_answer_prompt(monkeypatch):
    _, seen = _answer_systems(monkeypatch, False, True)
    assert seen and all(F.CITE_PICK_RULE not in s for s in seen)


# ---------- SS ----------
EXTRA = mk("If the IMOC is unable to respond within 15 minutes, page leadership.", title="Incident Management", seq=70004, article="Leadership > Fallback")


@pytest.mark.parametrize("multi", [False, True])
def test_requery_skip_seen_takes_only_new_chunks(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    monkeypatch.setenv("GRAPH_REQUERY_SKIP_SEEN", "1")
    asked: list = []

    def page_search(query, seqs, org, as_of, k):
        if query == Q_ESC:  # 사전 등록 62.55: 첫 검색 뒤 같은 페이지 보충 검색은 세지 않는다
            return []
        asked.append(k)
        return [ESC, IMOC, EXTRA][:k]  # ESC는 이미 문맥에 있다
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, j(sufficient=True, reason="", clarify=None)],   # 나뉜 질문의 일부 판정은 재검색하지 않는다(사전 등록 62.63)
            answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, lambda q: [ESC], m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert asked == [6]  # 새 청크 5개 + 문맥 1개만큼 더 받는다
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert ids == [ESC.chunk_id, IMOC.chunk_id, EXTRA.chunk_id]


def test_requery_skip_seen_caps_new_chunks_and_off_keeps_k(monkeypatch):
    from backend.graph.build import REQUERY_NEW
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    many = [mk(f"Fallback step {i} for incidents.", title="Incident Management", seq=70004, article=f"Step {i}") for i in range(6)]
    asked: list = []

    def page_search(query, seqs, org, as_of, k):
        if query == Q_ESC:  # 사전 등록 62.55: 첫 검색 뒤 같은 페이지 보충 검색은 세지 않는다
            return []
        asked.append(k)
        return [ESC, *many][:k]
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, j(sufficient=True, reason="", clarify=None)], answer=lambda u: cite(ESC))   # 62.63: 나뉘지 않은 질문
    out = run(build_graph(lambda q: [ESC], llm=m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert asked == [5] and len(out["chunks"]) == 5  # 꺼짐: k=5 그대로, 문맥에 있던 ESC도 다시 받는다
    monkeypatch.setenv("GRAPH_REQUERY_SKIP_SEEN", "1")
    asked.clear()
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, j(sufficient=True, reason="", clarify=None)], answer=lambda u: cite(ESC))
    out = run(build_graph(lambda q: [ESC], llm=m, decompose=True, max_research=1, page_search=page_search), Q_ESC)
    assert len(out["chunks"]) == 1 + REQUERY_NEW


@pytest.mark.parametrize("on", [False, True])
def test_requery_skip_seen_stops_section_reads_after_a_page_requery(monkeypatch, on):
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    monkeypatch.setenv("GRAPH_SECTION_KEEPS_RESEARCH", "1")
    if on:
        monkeypatch.setenv("GRAPH_REQUERY_SKIP_SEEN", "1")
    reads: list = []

    def reader(rule_seq, article, as_of):
        reads.append(article)
        return {"text": "x", "version_id": ESC.version_id}
    second = j(checks=[], sufficient=False, partial=True, reason="일부", missing=["리더십"], scope_note=None, clarify=None, query="IMOC",
               next_tool="get_section", chunk_id=IMOC.chunk_id)
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[PARTIAL, second, j(sufficient=True, reason="", clarify=None)],   # 62.63: 나뉘지 않은 질문
            answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(build_graph(lambda q: [ESC], llm=m, decompose=True, max_research=2, use_skills=True, page_search=lambda *a: [IMOC], section_reader=reader), Q_ESC)   # 나뉘지 않은 질문은 셋째 판정까지 재검색 상한 2가 필요하다
    assert out["kind"] == "answer"
    assert (reads == []) is on and (out["search_stats"].get("section_reads", 0) == 0) is on


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


# ---------- CS ----------
SHARED = "Acknowledge a page within 15 minutes of receiving it while on call."


def _cs(text, title, seq):
    return {"chunk_id": f"{seq:016x}", "rule_seq": seq, "text": f"{title} > X\n{text}"}


def test_drop_odd_cites_keeps_the_repeated_sentence_side():
    odd = _cs("Engineers should acknowledge pages within the first 15 minutes of their shift.", "Duty Guide", 3)
    cited = [odd, _cs("Slack mentions have no SLA.", "Policy", 4), _cs(SHARED, "Norms A", 1), _cs(SHARED, "Norms B", 2)]
    body = "호출은 15분 안에 확인한다 [1][4][3]. 멘션은 기한이 없다 [2]."
    new, kept, removed = F.drop_odd_cites(body, cited)
    assert new == "호출은 15분 안에 확인한다 [3][2]. 멘션은 기한이 없다 [1]."
    assert [c["rule_seq"] for c in kept] == [4, 1, 2] and removed == [odd["chunk_id"]]


def test_drop_odd_cites_leaves_other_answers():
    a, b, c = _cs(SHARED, "Norms A", 1), _cs(SHARED, "Norms B", 2), _cs("A different fact entirely about reviews.", "Other", 3)
    assert F.drop_odd_cites("사실 [1][2].", [a, b]) is None  # 인용 둘
    assert F.drop_odd_cites("사실 [1][2][3].", [a, _cs("Unrelated text one.", "P", 5), c]) is None  # 같은 문장을 공유하는 다른 페이지 둘이 없다
    still = F.drop_odd_cites("사실 [1][2][3]. 다른 사실 [3].", [a, b, c])
    assert still[0] == "사실 [1][2]. 다른 사실 [3]." and still[2] == []  # 다른 문장이 쓰는 인용은 목록에 남는다


def test_consensus_switch_in_the_graph(monkeypatch):
    duty = mk("Engineers should acknowledge pages within the first 15 minutes of their shift.", title="Duty Guide", seq=70101)
    na = mk(SHARED, title="Team Norms", seq=70102)
    nb = mk(SHARED, title="Team Norms Copy", seq=70103)
    q = "온콜 호출은 몇 분 안에 확인해야 해?"
    for on in (False, True):
        if on:
            monkeypatch.setenv("GRAPH_CITE_CONSENSUS", "1")
        out = run(build_graph(lambda q: [duty, na, nb], llm=llm(answer=cite(duty, na, nb, text="호출은 15분 안에 확인한다"))), q)
        ids = [c["chunk_id"] for c in out["citations"]]
        assert (duty.chunk_id in ids) is (not on) and na.chunk_id in ids and nb.chunk_id in ids


# ---------- PT ----------
def test_pointer_only_rule():
    assert F.pointer_only(["For information on how to use logo images, please refer to the following links: - Core logo", "Style Guide > Look and Feel"])
    assert not F.pointer_only(["Merge requests should receive a first review response within 2 business days.", "please refer to the following links"])
    assert not F.pointer_only(["Style Guide > Look and Feel"]) and not F.pointer_only([]) and not F.pointer_only(None)
    # NOTHING FOUND 구절(답이 '자료에 없다'고 한 주장)은 보지 않는다: 나머지 구절이 모두 안내뿐이면 참이다
    assert F.pointer_only(["NOTHING FOUND", "see the links"])
    assert F.pointer_only(["The guidelines at the company provides instructions on images.", "NOTHING FOUND"])
    assert not F.pointer_only(["NOTHING FOUND"]) and not F.pointer_only(["nothing found.", "NOTHING FOUND"])
    assert not F.pointer_only(["NOTHING FOUND", "Merge requests should receive a first review response within 2 business days.", "see the links"])
    assert F.pointer_only(["The guidelines at the company provides instructions on images.", "Core logo\nLogomark\nBranded lockups"])  # 링크 이름 목록
    assert not F.pointer_only(["For more information see the page.", "Within 2 business days\nfor all teams"])  # 숫자가 든 줄은 값이다


@pytest.mark.parametrize("on", [False, True])
def test_pointer_refuse_in_the_graph(monkeypatch, on):
    if on:
        monkeypatch.setenv("GRAPH_POINTER_REFUSE", "1")
    monkeypatch.setenv("GRAPH_GROUNDING_QUOTE", "1")
    ok = j(claims=[{"claim": "안내", "quote": "For more information, please refer to the following links.", "scope": None}], reason="", grounded=True, reason_code="", unsupported_sentences=[])
    m = llm(answer=cite(REVIEW, text="자세한 내용은 링크를 보라"), grounding=ok)
    out = run(build_graph(lambda q: [REVIEW], llm=m, grounding_llm=True), Q_REVIEW)
    assert out["kind"] == ("refuse" if on else "answer")
    assert sum(1 for t, _ in m.calls if t == "answer") == 1  # 다시 쓰지 않는다


# ---------- R3 첫 검색에만 ----------
INTRO = mk("Overview of incident management.", title="Incident Management", seq=70004, article="Overview")


@pytest.mark.parametrize("multi", [False, True])
def test_intro_fill_runs_only_on_the_first_search(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")
    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    calls: list = []

    def intro(chunks, query, org, as_of):
        calls.append(query)
        return [INTRO]

    def page_search(query, seqs, org, as_of, k):
        return [IMOC]
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=[PARTIAL, j(sufficient=True, reason="", clarify=None)],
            answer=lambda u: cite(*[c for c in (ESC, IMOC) if c.chunk_id in u]))
    out = run(graph(multi, lambda q: [ESC], m, decompose=True, max_research=1, page_search=page_search, intro_search=intro), Q_ESC)
    assert len(calls) == 1  # 페이지 재검색 뒤에는 부르지 않는다
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert INTRO.chunk_id in ids and IMOC.chunk_id in ids


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


def test_best2_samedoc_counts_only_outside_chunks_from_other_documents():
    doc_of = {"s1": 1, "n1": 1, "o1": 2}
    a, b = _draft("s1", "o1"), _draft("s1", "n1")
    got, log = F.pick_best2(a, b, ["s1"])
    assert got is a and log["why"] == "동점, 첫 후보" and log["rule"] == "s_in,s_out"  # 기본: S 밖 1 대 1
    got, log = F.pick_best2(a, b, ["s1"], doc_of)
    assert got is b and log["why"] == "S 밖 다른 문서 인용 수" and log["rule"] == "s_in,s_out_otherdoc"
    assert [c["out_s"] for c in log["cands"]] == [1, 0]
    got, log = F.pick_best2(_draft("s1", "n1"), _draft("s1"), ["s1"], doc_of)
    assert got["raw_citations"][1] == {"chunk_id": "n1"} and log["why"] == "동점, 첫 후보"  # 같은 문서 이웃 절은 벌하지 않는다
    got, log = F.pick_best2(_draft("o1"), _draft("s1", "o1", "x9"), ["s1"], doc_of)
    assert log["pick"] == 1 and log["why"] == "S 안 인용 청크 수" and log["cands"][1]["out_s"] == 2  # 첫 규칙이 먼저, 문서 모르는 청크는 다른 문서


OTHER = mk("Leadership pages are listed on the on-call schedule page.", title="On-call", seq=70009, article="Schedule")
ESC_OTHER = j(asked=["사실"], picks=[], answer=f"답 [{ESC.chunk_id}] [{OTHER.chunk_id}]",
              citations=[{"chunk_id": ESC.chunk_id}, {"chunk_id": OTHER.chunk_id}], period_covered=True)
ESC_IMOC = j(asked=["사실"], picks=[], answer=f"답 [{ESC.chunk_id}] [{IMOC.chunk_id}]",
             citations=[{"chunk_id": ESC.chunk_id}, {"chunk_id": IMOC.chunk_id}], period_covered=True)


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("mode", ["parallel_all", None])
@pytest.mark.parametrize("samedoc", [False, True])
def test_best2_samedoc_switch_reaches_the_graph(monkeypatch, multi, mode, samedoc):
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    if samedoc:
        monkeypatch.setenv("GRAPH_BEST2_SAMEDOC", "1")
    m = llm(judge=QUOTED, answer=[ESC_OTHER, ESC_IMOC])
    out = run(graph(multi, lambda q: [ESC, IMOC, OTHER], m, judge_answer=mode), Q_ESC)
    log = out["best2_log"]
    assert m.count("answer") == 2 and log["quote_ids"] == [ESC.chunk_id]
    # 두 답은 두 스레드가 동시에 쓰므로 가짜 모델의 답 목록 중 어느 것이 첫 후보가 될지는 스레드 순서에 달렸다(CI에서 뒤바뀐다).
    # 그래서 몇 번째를 골랐는지가 아니라 고른 후보가 무엇을 인용했는지 본다
    assert sorted(OTHER.chunk_id in c["cited"] for c in log["cands"]) == [False, True]
    if samedoc:  # 다른 문서(OTHER)를 인용한 답 대신 같은 문서 이웃 절(IMOC)을 인용한 답
        assert log["rule"] == "s_in,s_out_otherdoc" and log["why"] == "S 밖 다른 문서 인용 수"
        assert log["cands"][log["pick"]]["cited"] == [ESC.chunk_id, IMOC.chunk_id]
        assert OTHER.chunk_id not in [c["chunk_id"] for c in out["citations"]]
    else:
        assert log["rule"] == "s_in,s_out" and log["pick"] == 0 and log["why"] == "동점, 첫 후보"