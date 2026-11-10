"""근거 판정 다수결(`GRAPH_JUDGE_VOTE`)에서 값은 받쳐졌고 단서 문장만 문제가 된 표의 처리.
운영 트레이스(2026-11-09, 리비전 00030-6t4)의 금액 승인자 질문 3건의 저장된 판정 응답(`fixtures/ground_caveat_traces.json`)을 가짜 모델에 그대로 넣어 재연한다. 키와 네트워크 없음.

- 4807636d(30만 달러): 세 표가 꼽은 문장이 서로 달라(값 문장 1, 단서 1, 통과 1) 합친 목록이 비었고 2표가 거절이라 답 전체가 거절됐다.
- f178bec0(10만 달러): 첫 초안이 값 없이 "확인 필요"뿐이라 거절이 맞고, 다시 쓴 답은 판 기준 안내 문장만 꼽혔다.
- c02a6765(5만 달러): 승인자 값이 자료에 없다. 이 건은 수정 뒤에도 거절이어야 한다."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from qgraph_fakes import j, normal_llm
from test_question_graph import graph, run

from backend.graph import grounding as G
from backend.prompts import question as P
from backend.schemas import Chunk

TRACES = {t["trace"]: t for t in json.loads((Path(__file__).parent / "fixtures" / "ground_caveat_traces.json").read_text(encoding="utf-8"))}


@pytest.fixture(autouse=True)
def _vote(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")


def replay(trace: dict, grounding_votes: list[str] | None = None, answers: list[str] | None = None):
    """저장된 응답으로 그래프를 돌린다. 판정 표는 호출한 차례대로 주되, 같은 묶음(3표) 안에서는 저장된 도착 순서로 끝나게 늦춘다."""
    votes = grounding_votes if grounding_votes is not None else [v for group in trace["vote_groups"] for v in group]
    lock, n = threading.Lock(), [0]

    def grounding(_user):
        with lock:
            i = n[0]
            n[0] += 1
        time.sleep(0.05 * (i % 3))
        return votes[min(i, len(votes) - 1)]

    draft = trace["draft"]
    first = j(answer=draft["answer"], citations=draft["citations"], period_covered=draft["period_covered"] is not False, partial=trace["judge_partial"])
    judge = j(sufficient=False, partial=True, reason="일부", missing=trace["judge_missing"], scope_note=None, clarify=None) if trace["judge_partial"] else j(sufficient=True, partial=False, reason="", missing=[], clarify=None)
    llm = normal_llm(judge=judge, answer=answers or [first, *trace["redrafts"]], grounding=grounding,
                     decompose=j(split=True, sub_questions=["계약 금액 업무 승인자는 누구인가요?", "계약 금액 재무 승인자는 누구인가요?"]))
    chunks = [Chunk(**c) for c in trace["retrieved"]]
    split = {"decompose": True, "max_research": 1} if trace["judge_partial"] else {}  # 일부 근거 경로는 질문이 나뉘어야 쓴다
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True, **split), question=trace["question"], as_of=trace["as_of"])
    return out, llm


# ---------- 운영 트레이스 재연 ----------
def test_trace_4807636d_hedge_vote_no_longer_decides_the_refusal():
    """값을 말하는 문장 하나만 꼽은 표(그 표의 claims에도 NOTHING FOUND는 없다)와 단서 문장만 꼽은 표, 통과 표. 값에 대한 표는 2:1로 받쳐졌다."""
    out, llm = replay(TRACES["4807636d"])
    assert out["kind"] == "answer" and not out.get("refuse_reason")
    assert "VP(Approves)" in out["answer"] and out["grounding"]["caveat_only"] is True


def test_trace_f178bec0_value_free_first_draft_is_redrafted_and_version_note_passes():
    out, llm = replay(TRACES["f178bec0"])
    assert out["kind"] == "answer" and out["grounding"]["redrafted"] is True and "Sr Director" in out["answer"]


def test_trace_c02a6765_missing_approver_value_is_still_refused():
    """승인자 값이 NOTHING FOUND인 건(재무 칸이 X)은 수정 뒤에도 거절이다."""
    out, llm = replay(TRACES["c02a6765"])
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and "caveat_only" not in out["grounding"]


# ---------- 값 주장은 느슨해지지 않는다 ----------
Q = TRACES["4807636d"]["question"]
CHUNKS = [Chunk(**c) for c in TRACES["4807636d"]["retrieved"]]
EVIDENCE = [c.model_dump() for c in CHUNKS]
FACT = "계약 금액 30만 달러는 '>$250K up to $500K' 구간에 해당하며, 업무 승인자는 VP(Approves), 재무 승인자는 PAO 또는 VP Finance(Approves/Signs)입니다 [fdde953c7bca6352]."
HEDGE = "다만 이 구간은 지출(expense) 승인 행이며, 자료만으로는 외부 SaaS 도입 계약이 이 행에 해당하는지 확인되지 않습니다."
ANSWER = f"{FACT} {HEDGE}"


def vote(*flagged, claims=(), code="unsupported", grounded=False):
    return j(grounded=grounded, reason_code=code, reason="r", unsupported_sentences=list(flagged),
             claims=[{"claim": c, "quote": q} for c, q in claims])


def graph_answer(votes):
    trace = {**TRACES["4807636d"], "redrafts": [], "vote_groups": [votes]}
    return replay(trace, votes, answers=[j(answer=ANSWER, citations=[{"chunk_id": "fdde953c7bca6352"}], period_covered=True, partial=False)])[0]


def test_two_votes_flagging_the_value_sentence_still_refuse_even_if_a_third_flags_the_hedge():
    out = graph_answer([vote(FACT), vote(FACT), vote(HEDGE)])
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported"


def test_value_flagged_by_different_wording_in_two_votes_still_refuses():
    """같은 값 문장을 두 표가 서로 다른 조각으로 꼽아도 거절 표가 둘이다(통과 표는 하나)."""
    out = graph_answer([vote("업무 승인자는 VP(Approves), 재무 승인자는 PAO 또는 VP Finance(Approves/Signs)입니다"), vote(FACT), vote(HEDGE)])
    assert out["kind"] == "refuse"


def test_nothing_found_value_claims_in_every_vote_still_refuse():
    nf = [("업무 승인자는 Director", "NOTHING FOUND")]
    out = graph_answer([vote(claims=nf), vote(claims=nf), vote(claims=nf)])
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported"


def test_hedge_only_votes_pass_but_a_single_value_vote_does_not_get_a_refusal_through_alone():
    """거절 표가 하나뿐이고 나머지가 받쳐진 표(단서만 꼽은 표 포함)이면 지금까지처럼 값은 다수결로 받쳐진다."""
    assert graph_answer([vote(FACT), vote(HEDGE), vote(HEDGE)])["kind"] == "answer"


def test_reason_codes_other_than_unsupported_are_not_eased():
    """사유가 unsupported가 아닌 표는 단서 문장만 꼽았어도 건드리지 않는다(`test_ground_caveat.py::test_other_reasons_are_not_affected`와 같은 기준)."""
    for code in ("out_of_period", "no_evidence", "nonexistent_entity"):
        assert G.caveat_only_vote(json.loads(vote(HEDGE, code=code)), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote(HEDGE, grounded=True)), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote(claims=[("SaaS 계약이 지출 행에 해당하는지는 자료로 확인 불가", "NOTHING FOUND")], code="out_of_period")), ANSWER, Q, EVIDENCE) == []


# ---------- 표 하나의 판별 ----------
def test_vote_flagging_only_the_hedge_is_eased_and_value_flag_is_not():
    assert G.caveat_only_vote(json.loads(vote(HEDGE)), ANSWER, Q, EVIDENCE) == [HEDGE]
    assert G.caveat_only_vote(json.loads(vote(FACT)), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote(HEDGE, FACT)), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote(HEDGE)), HEDGE, Q, EVIDENCE) == []  # 값을 말하는 문장이 없는 답


def test_empty_list_with_hedge_nothing_found_is_eased_but_value_nothing_found_is_not():
    hedge_nf = [("SaaS 계약이 지출 행에 해당하는지는 자료로 확인 불가", "NOTHING FOUND"), ("재무 승인자는 PAO 또는 VP Finance", "PAO or VP Finance (financial approval): Approves/Signs")]
    assert G.caveat_only_vote(json.loads(vote(claims=hedge_nf)), ANSWER, Q, EVIDENCE) == ["SaaS 계약이 지출 행에 해당하는지는 자료로 확인 불가"]
    value_nf = [*hedge_nf, ("업무 승인자는 VP(Approves)", "NOTHING FOUND")]
    assert G.caveat_only_vote(json.loads(vote(claims=value_nf)), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote(claims=[("업무 승인자는 Director", "nothing found.")])), ANSWER, Q, EVIDENCE) == []
    assert G.caveat_only_vote(json.loads(vote()), ANSWER, Q, EVIDENCE) == []  # 꼽은 문장도 NOTHING FOUND도 없다


def test_new_values_in_a_nothing_found_summary_are_not_a_caveat():
    claims = [("SaaS 계약이 지출 행에 해당하는지는 자료로 확인 불가, 승인 기한 3일", "NOTHING FOUND")]
    assert G.caveat_only_vote(json.loads(vote(claims=claims)), ANSWER, Q, EVIDENCE) == []


# ---------- 꼽은 문장과 답 문장의 일치(공백·구두점·따옴표를 지운 부분 일치) ----------
@pytest.mark.parametrize("flagged", [
    HEDGE,
    HEDGE.rstrip("."),                                              # 끝의 마침표 없이
    "자료만으로는 외부 SaaS 도입 계약이 이 행에 해당하는지 확인되지 않습니다.",   # 뒷부분만
    "다만 이 구간은 “지출(expense)” 승인 행이며, 자료만으로는 외부 SaaS 도입 계약이 이 행에 해당하는지 확인되지 않습니다",  # 따옴표를 더하고 마침표를 뺌
    HEDGE.replace("(expense)", " (expense) ").replace(", ", ","),   # 공백이 다름
])
def test_flagged_hedge_written_slightly_differently_still_matches(flagged):
    assert G.caveat_only_flags(ANSWER, [flagged], Q, EVIDENCE)


@pytest.mark.parametrize("flagged", [
    FACT.rstrip("."),
    "“업무 승인자는 VP(Approves)”",
    "계약 금액 30만 달러는 '>$250K up to $500K' 구간에 해당하며",     # 값 문장의 앞부분
])
def test_flagged_value_sentence_written_differently_is_still_a_value_flag(flagged):
    assert not G.caveat_only_flags(ANSWER, [flagged], Q, EVIDENCE)


# ---------- 프롬프트 ----------
def test_answer_and_redraft_prompts_forbid_self_caveats_about_the_row():
    assert "자기 단서" in P.ANSWER_SYSTEM and "자기 단서" in P.redraft_user("q", [], None, "d", "r", [])
    assert "자기 단서" in P.judge_answer_system()  # 합친 프롬프트도 답 작성 규칙을 그대로 가져온다
