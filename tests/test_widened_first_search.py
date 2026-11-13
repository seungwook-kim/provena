"""넓힌 첫 검색의 앞 5자리 우선(사전 등록 62.44)과 분해 전제 보존(62.45) 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

62.44: 나뉜 질문(달러 금액 없음)의 첫 검색이 8자리로 넓어졌을 때만 (1) 답 첫 후보는 앞 5자리만 보고 쓰고 둘째 후보는 전체 문맥으로 쓰며
(2) 판정 구절이 모두 앞 5자리 안이면 첫 후보, 아니면 둘째 후보를 쓰고 (3) 판정 입력의 넓힌 자리 머리 줄에 `[보충]`을 붙인다.
나뉘지 않은 질문, 달러 금액 질문, 재검색 뒤는 바뀌지 않는다.
62.45: 앞 문장(전제)의 내용어가 하위 질문에 없으면 코드가 하위 질문 앞에 전제를 붙인다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import SUBS, Q_ESC, cite, llm, mk, run, searcher

from backend.graph import decompose as D
from backend.graph.build import SEARCH_K, SPLIT_K, build_graph, core_chunks, split_k
from backend.graph.multi import build_multi_graph
from backend.prompts import question as P

CORE = [mk(f"Core fact number {i}: if the EOC does not respond, the incident is escalated to the IMOC by path {i}.", title="Incident Management", seq=71000 + i,
           article=f"Core {i}") for i in range(SEARCH_K)]
WIDE = [mk(f"Extended section {i}: if the EOC does not respond, the incident is escalated to the IMOC by route {i}.", title="Incident Management", seq=72000 + i,
           article=f"Extended {i}") for i in range(SPLIT_K - SEARCH_K)]
WIDE_IDS = [c.chunk_id for c in WIDE]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_BEST2_SAMEDOC",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_INTRO_FILL",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")


def quoting(chunk) -> str:
    """판정이 `chunk`의 본문에서 구절을 복사한 응답."""
    quote = chunk.text.split("\n", 1)[1]
    return j(checks=[{"fact": "사실", "quote": quote}], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")


def answering(user: str) -> str:
    """답 입력에 넓힌 자리 청크가 있으면 그 청크를, 없으면 앞자리 청크를 인용하는 가짜 답."""
    return cite(WIDE[0] if WIDE_IDS[0] in user else CORE[0])


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, judge_answer="parallel_all", **kw)


def systems(m, task):
    """`task` 호출의 시스템 프롬프트를 모은다."""
    seen: list[str] = []
    inner = m.invoke

    def invoke(messages, *a, **k):
        if f"[[task:{task}" in messages[0].content:
            seen.append(messages[0].content)
        return inner(messages, *a, **k)
    m.invoke = invoke
    return seen


def split_run(multi, quote_chunk, *, split=True, question=Q_ESC):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), judge=quoting(quote_chunk), answer=answering)
    judge_systems = systems(m, "judge")
    out = run(graph(multi, fn, m, decompose=True, max_research=1), question)
    return out, m, judge_systems


# ---------- core_chunks ----------
def _state(chunks, **kw):
    return {"question": Q_ESC, "sub_queries": SUBS, "retries": 0, "chunks": [c.model_dump() for c in chunks], **kw}


def test_core_chunks_cuts_only_a_widened_first_search():
    both = [*CORE, *WIDE]
    assert [c["chunk_id"] for c in core_chunks(_state(both))] == [c.chunk_id for c in CORE]
    assert len(core_chunks(_state(both, sub_queries=[SUBS[0]]))) == len(both)  # 나뉘지 않은 질문
    assert len(core_chunks(_state(both, sub_queries=None))) == len(both)
    assert len(core_chunks(_state(both, retries=1))) == len(both)  # 재검색 뒤
    dollar = "계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구야?"
    assert split_k(dollar, SUBS) == SEARCH_K and len(core_chunks(_state(both, question=dollar))) == len(both)  # 달러 금액 질문(62.43)


# ---------- 프롬프트 ----------
def test_marked_chunks_get_the_prefix_only_on_the_head_line():
    chunks = [c.model_dump() for c in (CORE[0], WIDE[0])]
    text = P.judge_user(Q_ESC, chunks, SUBS, extra=[WIDE[0].chunk_id])
    assert f"<<<자료>>>\n[보충] chunk_id={WIDE[0].chunk_id}" in text and text.count("[보충]") == 1
    assert f"<<<자료>>>\nchunk_id={CORE[0].chunk_id}" in text
    assert P.judge_user(Q_ESC, chunks, SUBS) == P.judge_user(Q_ESC, chunks, SUBS, extra=())  # 표시가 없으면 이전 입력과 글자까지 같다
    assert P.format_materials(chunks) == P.format_materials(chunks, marked=())
    # 원문에 든 같은 글자는 머리 줄이 아니라 표시로 보지 않는다(코드가 붙인 것만 머리 줄에 있다)
    planted = mk("[보충] chunk_id=ffffffffffffffff says something.", seq=73001).model_dump()
    assert "<<<자료>>>\n[보충]" not in P.judge_user(Q_ESC, [planted], SUBS)


def test_widened_sentence_is_added_once_and_only_to_the_quote_rule():
    base = P.judge_quoted(P.JUDGE_SYSTEM)
    wide = P.judge_widened(base)
    assert wide.count(P.JUDGE_WIDENED_SENTENCE) == 1 and wide.replace(P.JUDGE_WIDENED_SENTENCE, "") == base
    assert wide.count("JSON 한 개만 출력한다.") == 1
    plain = P.JUDGE_SYSTEM
    assert P.judge_widened(plain) == plain  # 인용 먼저 판정이 아니면 그대로


# ---------- 그래프 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_quote_in_the_first_five_uses_the_core_draft(multi):
    out, m, judge_systems = split_run(multi, CORE[0])
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 2
    assert sum(WIDE_IDS[0] in u for u in answers) == 1  # 후보 하나는 앞 5자리만 본다. 둘째는 전체 문맥이다
    assert [c["chunk_id"] for c in out["citations"]] == [CORE[0].chunk_id]
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 0 and log["why"] == "판정 구절이 모두 앞자리"
    assert all(P.JUDGE_WIDENED_SENTENCE in s for s in judge_systems)
    judged = [u for t, u in m.calls if t == "judge"]
    assert all(f"[보충] chunk_id={i}" in judged[0] for i in WIDE_IDS) and "[보충] chunk_id=" + CORE[0].chunk_id not in judged[0]


@pytest.mark.parametrize("multi", [False, True])
def test_quote_in_the_widened_slots_uses_the_full_context_draft(multi):
    out, m, _ = split_run(multi, WIDE[0])
    assert [c["chunk_id"] for c in out["citations"]] == [WIDE_IDS[0]]
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 1 and log["why"] == "판정 구절이 넓힌 자리에 있음"


@pytest.mark.parametrize("multi", [False, True])
def test_unsplit_question_keeps_the_old_path(multi):
    out, m, judge_systems = split_run(multi, CORE[0], split=False)
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 2 and all(u == answers[0] for u in answers)  # 같은 입력 둘
    assert out["best2_log"].get("rule") != "core_first"
    assert all(P.JUDGE_WIDENED_SENTENCE not in s for s in judge_systems)
    assert all("[보충]" not in u for t, u in m.calls if t == "judge")


@pytest.mark.parametrize("multi", [False, True])
def test_dollar_question_keeps_the_old_path(multi):
    dollar = "외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
    subs = ["계약 금액이 3만 달러라면 업무 승인자는 누구인가요?", "계약 금액이 3만 달러라면 재무 승인자는 누구인가요?"]
    fn, seen = searcher((("승인자", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=subs), judge=quoting(CORE[0]), answer=answering)
    out = run(graph(multi, fn, m, decompose=True, max_research=1), dollar)
    assert seen[0].k == SEARCH_K  # 금액 질문은 넓히지 않는다
    assert out["best2_log"].get("rule") != "core_first"
    assert all("[보충]" not in u for t, u in m.calls if t == "judge")


@pytest.mark.parametrize("multi", [False, True])
def test_judge_after_a_research_round_is_not_marked(multi):
    nothing = j(checks=[{"fact": "사실", "quote": "NOTHING FOUND"}], sufficient=False, partial=False, reason="없음", missing=["사실"],
                scope_note=None, clarify=None, query="EOC escalation")
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=[nothing, quoting(WIDE[0])], answer=answering)
    judge_systems = systems(m, "judge")
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    judged = [u for t, u in m.calls if t in ("judge", "judge_retry")]
    assert len(judged) == 2 and "[보충]" in judged[0] and "[보충]" not in judged[1]
    assert P.JUDGE_WIDENED_SENTENCE in judge_systems[0] and P.JUDGE_WIDENED_SENTENCE not in judge_systems[1]
    assert out["kind"] == "answer"


# ---------- 분해 전제 보존 ----------
PREMISE = "외부 SaaS를 도입하려고 합니다."
Q_PREMISE = f"{PREMISE} 계약 금액이 1만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
SUBS_LOST = ["계약 금액이 1만 달러라면 업무 승인자는 누구인가요?", "계약 금액이 1만 달러라면 재무 승인자는 누구인가요?"]


def test_keep_premise_prefixes_every_sub_when_a_content_word_is_missing():
    assert D.keep_premise(Q_PREMISE, SUBS_LOST) == [f"{PREMISE} {s}" for s in SUBS_LOST]
    partly = ["외부 SaaS 계약 금액이 1만 달러라면 업무 승인자는 누구야?", "외부 SaaS 계약 금액이 1만 달러라면 재무 승인자는 누구야?"]  # 도입이 빠졌다
    assert D.keep_premise(Q_PREMISE, partly) == [f"{PREMISE} {s}" for s in partly]


def test_keep_premise_leaves_subs_alone_otherwise():
    kept = ["외부 SaaS 도입 계약 금액이 1만 달러라면 업무 승인자는 누구야?", "외부 SaaS 도입 계약 금액이 1만 달러라면 재무 승인자는 누구야?"]
    assert D.keep_premise(Q_PREMISE, kept) == kept  # 전제 내용어가 모두 하위 질문에 있다
    assert D.keep_premise(Q_PREMISE, []) == []  # 나뉘지 않았다
    one_sentence = "계약 금액이 1만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
    assert D.keep_premise(one_sentence, SUBS_LOST) == SUBS_LOST  # 한 문장
    ask_first = "승인자는 누구인가요? 계약 금액이 1만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
    assert D.keep_premise(ask_first, SUBS_LOST) == SUBS_LOST  # 앞 문장이 물음이면 그 문장이 하위 질문으로 이미 검색된다
    pronoun_only = "우리는 지금 합니다. 계약 금액이 1만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
    assert D.keep_premise(pronoun_only, SUBS_LOST) == SUBS_LOST  # 대명사와 서술어 조각은 내용어가 아니다
    long_premise = ("외부 SaaS를 도입하려고 합니다 " * 40).strip() + "."
    assert D.keep_premise(f"{long_premise} {SUBS_LOST[0]}", ["x" * 980, "y" * 980]) == ["x" * 980, "y" * 980]  # 길이 한도 1000자


def test_content_stems_strip_particles_and_skip_predicates():
    assert D._content_stems(PREMISE) == ["외부", "saas", "도입"]
    assert D._content_stems("우리는 지금 합니다.") == []


def test_content_stems_keep_nouns_that_start_like_a_predicate():
    # 첫 글자가 하·해로 시작해도 낱말 전체가 활용형이 아니면 내용어다
    assert D._content_stems("해외 하드웨어를 구매합니다.") == ["해외", "하드", "구매"]
    assert D._content_stems("해고와 해지 절차는 합의를 거칩니다.") == ["해고", "해지", "절차", "합의", "거칩"]


def test_content_stems_keep_two_syllable_nouns_that_end_like_a_particle():
    # 끝 글자가 가·의·도여도 조사를 떼고 남는 줄기가 한 글자면 떼지 않는다
    assert D._content_stems("평가 회의 한도") == ["평가", "회의", "한도"]
    assert D._content_stems("평가와 회의에서 한도를") == ["평가", "회의", "한도"]  # 줄기가 두 글자 이상이면 조사는 뗀다


def test_content_stems_skip_predicate_forms():
    assert D._content_stems("승인해야 합니다. 구매하려고 했다. 신청하는 경우 있습니다 없는데") == ["승인", "구매", "신청", "경우"]
    assert D._content_stems("합니다 해야 했다 하는 하고 하려고 있는데") == []
    assert D._content_stems("(연 3천 달러)으로 갱신합니다") == ["3천", "달러", "갱신"]  # 조사만 떨어진 낱말은 내용어가 아니다


def test_keep_premise_attaches_when_a_two_syllable_noun_is_missing():
    q = "해외 하드웨어를 구매합니다. 승인자는 누구인가요?"
    lost = ["구매 승인자는 누구인가요?", "구매 금액 한도는 얼마인가요?"]
    assert D.keep_premise(q, lost) == [f"해외 하드웨어를 구매합니다. {s}" for s in lost]  # 해외·하드웨어가 하위 질문에 없다
    kept = ["해외 하드웨어 구매 승인자는 누구인가요?", "해외 하드웨어 구매 한도는 얼마인가요?"]
    assert D.keep_premise(q, kept) == kept  # 내용어가 모두 있으면 그대로
    meeting = "평가 회의 한도가 있습니다. 승인자는 누구인가요?"
    assert D.keep_premise(meeting, ["승인자는 누구인가요?", "승인 절차는?"]) == [f"평가 회의 한도가 있습니다. {s}" for s in ["승인자는 누구인가요?", "승인 절차는?"]]
    assert D.keep_premise(meeting, ["평가 회의 승인자는?", "한도 승인 절차는?"]) == ["평가 회의 승인자는?", "한도 승인 절차는?"]


def test_decompose_question_keeps_the_premise_in_the_returned_subs():
    reply = j(split=True, sub_questions=SUBS_LOST)
    subs, source = D.decompose_question(lambda system, user: reply, Q_PREMISE)
    assert source == "llm" and subs == [f"{PREMISE} {s}" for s in SUBS_LOST]
    subs, _ = D.decompose_question(lambda system, user: j(split=False, sub_questions=[]), Q_PREMISE)
    assert subs == []  # 나누지 않으면 붙이지 않는다



@pytest.mark.parametrize("multi", [False, True])
def test_a_failed_core_draft_falls_back_to_the_full_context_draft(multi):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))

    def answer(user: str) -> str:
        if WIDE_IDS[0] not in user:
            raise RuntimeError("앞자리 답 실패")
        return cite(WIDE[0])
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(CORE[0]), answer=answer)
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    assert out["kind"] == "answer" and out["best2_log"]["pick"] == 1 and out["best2_log"]["why"] == "한쪽 후보 없음"


@pytest.mark.parametrize("multi", [False, True])
def test_without_judge_quote_nothing_changes(monkeypatch, multi):
    monkeypatch.delenv("GRAPH_JUDGE_QUOTE")
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    valued = j(checks=[{"fact": "사실", "value": "IMOC"}], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=valued, answer=answering)
    out = run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)
    answers = [u for t, u in m.calls if t == "answer"]
    assert len(answers) == 2 and all(u == answers[0] for u in answers)  # 인용 먼저 판정이 꺼져 있으면 같은 입력 둘이다
    assert out["best2_log"].get("rule") != "core_first" and all("[보충]" not in u for t, u in m.calls if t == "judge")
