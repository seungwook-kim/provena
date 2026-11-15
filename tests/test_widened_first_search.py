"""분해 전제 보존(사전 등록 62.45) 시험과 다른 시험이 같이 쓰는 문맥 청크. 가짜 모델만 쓴다(키와 네트워크 없음).

62.45: 앞 문장(전제)의 내용어가 하위 질문에 없으면 코드가 하위 질문 앞에 전제를 붙인다.
넓힌 첫 검색의 앞 5자리 우선(62.44) 시험은 사전 등록 62.72로 그 장치를 코드째 제거하면서 지웠다. `CORE`(앞 5개)와 `WIDE`(뒤 3개)는 문맥 청크 8개를 만드는 시험 자료로만 남는다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import mk

from backend.graph import decompose as D
from backend.graph.build import SEARCH_K

CORE = [mk(f"Core fact number {i}: if the EOC does not respond, the incident is escalated to the IMOC by path {i}.", title="Incident Management", seq=71000 + i,
           article=f"Core {i}") for i in range(SEARCH_K)]
WIDE = [mk(f"Extended section {i}: if the EOC does not respond, the incident is escalated to the IMOC by route {i}.", title="Incident Management", seq=72000 + i,
           article=f"Extended {i}") for i in range(3)]
WIDE_IDS = [c.chunk_id for c in WIDE]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE",
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


