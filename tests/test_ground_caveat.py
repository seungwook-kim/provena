"""근거 판정이 값을 말하지 않는 단서 문장("자료만으로는 확인되지 않습니다", "공개 판 기준입니다")만 받쳐지지 않는다고 꼽았을 때의 처리.
운영 트레이스(2026-11-09, 리비전 00030-6t4)의 금액 승인자 질문에서 값은 모두 받쳐졌는데 이런 문장 하나 때문에 답 전체가 거절됐다.
가짜 모델만 쓴다(키와 네트워크 없음). 판정 가짜는 트레이스의 판정처럼 단서 문장을 받쳐지지 않는 문장으로 꼽는다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j, normal_llm
from test_question_graph import graph, run

from backend.graph import grounding as G
from backend.schemas import Chunk

QUESTION = "외부 SaaS를 도입하려고 합니다. 계약 금액이 30만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"
ROW = Chunk(
    chunk_id="fdde953c7bca6352", org="finance", rule_seq=3054269612, rule_title="Authorization Matrix (2023-05)",
    article="Approving expense > >$250K up to $500K", version_id="0a3de8337541", version_date="2023-05-11", fetched_at="2026-10-31", kind="row",
    text=("Authorization Matrix (2023-05) > Approving expense > >$250K up to $500K\nApproving expense, >$250K up to $500K:\n"
          "- VP (functional approval): Approves\n- PAO or VP Finance (financial approval): Approves/Signs"),
    source_url="https://example.invalid/authorization-matrix")
FACT = f"계약 금액 30만 달러는 '>$250K up to $500K' 구간에 해당하며, 업무 승인자는 VP(Approves), 재무 승인자는 PAO 또는 VP Finance(Approves/Signs)입니다 [{ROW.chunk_id}]."
HEDGE = "다만 이 구간은 지출(expense) 승인 행이며, 자료만으로는 외부 SaaS 도입 계약이 이 행에 해당하는지 확인되지 않습니다."
VERSION = "이 구간의 승인자는 공개 판(2023-05) 기준입니다."
KNOWN = f"{QUESTION}\n{ROW.rule_title} {ROW.article} {ROW.text}"


def reply(*sentences):
    return j(answer=" ".join(sentences), citations=[{"chunk_id": ROW.chunk_id}], period_covered=True, partial=False)


def judge_flagging(*flagged):
    """답에 flagged 문장이 있으면 그 문장을 받쳐지지 않는다고 꼽고(구절 없음), 없으면 통과시킨다. 트레이스의 판정과 같은 모양이다."""
    def grounding(user):
        answer = user.split("<<<답>>>", 1)[1].split("<<<끝>>>", 1)[0]
        hit = [s for s in flagged if s in answer]
        return j(grounded=False, reason_code="unsupported", reason="단서 문장에 근거 구절이 없음", unsupported_sentences=hit) if hit else j(grounded=True)
    return grounding


def ask(llm):
    return run(graph(lambda q: [ROW], llm=llm, grounding_llm=True), question=QUESTION)


# ---------- 단서 문장 판별 ----------
@pytest.mark.parametrize("sentence", [
    HEDGE, VERSION, "SaaS 계약이 지출 행에 해당하는지는 자료만으로 확인되지 않습니다 [fdde953c7bca6352].",
    "자료에는 해당 업무의 행이 없어 확인 필요입니다.", "공개된 과거 판 기준이며 현재 판과 다를 수 있습니다.",
])
def test_caveat_sentences_are_recognized(sentence):
    assert G.is_caveat(sentence, KNOWN)


@pytest.mark.parametrize("sentence", [
    FACT, "업무 승인자는 VP입니다.",
    "자료만으로는 확인되지 않지만 Director가 승인합니다.",         # 값(Director)을 새로 들인다
    "자료에는 없지만 승인 기한은 3일입니다.",                       # 질문과 근거에 없는 숫자
    "", "계약은 법무 승인을 받아야 한다.",
])
def test_sentences_with_values_are_not_caveats(sentence):
    assert not G.is_caveat(sentence, KNOWN)


def test_caveat_only_flags_needs_a_value_sentence_left_in_the_answer():
    answer = f"{FACT} {HEDGE}"
    assert G.caveat_only_flags(answer, [HEDGE], QUESTION, [ROW.model_dump()])
    assert not G.caveat_only_flags(answer, [], QUESTION, [ROW.model_dump()])                  # 꼽은 문장이 없으면 해당 없음
    assert not G.caveat_only_flags(answer, [HEDGE, FACT], QUESTION, [ROW.model_dump()])       # 값을 말하는 문장도 꼽았다
    assert not G.caveat_only_flags(f"{HEDGE} {VERSION}", [HEDGE], QUESTION, [ROW.model_dump()])  # 값을 말하는 문장이 없는 답


# ---------- 그래프: 트레이스 재연 ----------
def test_hedge_flagged_twice_no_longer_refuses_a_supported_answer():
    """205 r1: 답 초안과 다시 쓴 답 모두 값은 받쳐졌고 단서 문장만 꼽혔다. 예전에는 두 번째 판정에서 거절했다."""
    llm = normal_llm(answer=reply(FACT, HEDGE), grounding=judge_flagging(HEDGE))
    out = ask(llm)
    assert out["kind"] == "answer" and not out.get("refuse_reason")
    assert "VP(Approves)" in out["answer"] and "확인되지 않습니다" in out["answer"]       # 단서는 답에 그대로 남는다
    assert out["grounding"]["caveat_only"] is True and llm.count("grounding") == 1 and llm.count("answer") == 1


def test_wrong_absence_only_draft_is_still_rewritten_and_version_note_passes():
    """204 r2: 첫 초안은 값 없이 "확인 필요"뿐이라 거절 판정이 맞다. 다시 쓴 답은 값을 말하고 판 기준 안내가 꼽혔지만 값은 받쳐졌다."""
    wrong = "10만 달러 계약에 해당하는 승인 구간이 공개 권한표에 명확히 확인되지 않아 승인자를 특정할 수 없습니다. 확인 필요."
    llm = normal_llm(answer=[reply(wrong), reply(FACT, VERSION)], grounding=judge_flagging(wrong, VERSION))
    out = ask(llm)
    assert out["kind"] == "answer" and out["grounding"]["redrafted"] is True and "VP(Approves)" in out["answer"]
    assert llm.count("grounding") == 2 and llm.count("answer") == 2


def test_flagged_value_sentence_still_refuses():
    llm = normal_llm(answer=reply(FACT, HEDGE), grounding=judge_flagging(HEDGE, FACT))
    out = ask(llm)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and "caveat_only" not in out["grounding"]


def test_answer_without_a_value_sentence_still_refuses():
    llm = normal_llm(answer=reply(HEDGE, VERSION), grounding=judge_flagging(HEDGE))
    out = ask(llm)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported"


def test_flagged_sentence_that_is_not_in_the_answer_does_not_excuse_other_sentences():
    """꼽은 문장이 답의 어느 문장과도 맞지 않으면(꼽은 문장이 단서처럼 보여도) 답의 다른 문장은 판정이 거절한 것으로 둔다."""
    made_up = "승인은 3분 안에 끝난다 [%s]." % ROW.chunk_id
    llm = normal_llm(answer=reply(made_up), grounding=j(grounded=False, reason_code="unsupported", reason="근거 없음", unsupported_sentences=["자료에 없는 문장입니다"]))
    out = ask(llm)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported"
    assert not G.caveat_only_flags(made_up, ["자료에 없는 문장입니다"], QUESTION, [ROW.model_dump()])


def test_other_reasons_are_not_affected():
    """사유가 no_evidence나 nonexistent_entity인 판정은 단서 문장만 꼽았어도 거절 그대로다."""
    for code in ("no_evidence", "nonexistent_entity"):
        llm = normal_llm(answer=reply(FACT, HEDGE), grounding=j(grounded=False, reason_code=code, reason="사유", unsupported_sentences=[HEDGE]))
        out = ask(llm)
        assert out["kind"] == "refuse" and out["refuse_reason"] == code


def test_out_of_period_flag_on_a_hedge_only_is_eased_when_the_question_is_in_period():
    """판정 모델은 같은 단서 문장("현재 판의 값은 확인할 수 없다")을 표마다 unsupported 또는 out_of_period로 달리 부른다(운영 트레이스 bfd7bdbc).
    질문 자체는 근거의 기간 안이고 꼽은 문장이 값을 말하지 않는 단서뿐이면 사유 이름과 상관없이 값은 받쳐진 것으로 센다."""
    llm = normal_llm(answer=reply(FACT, HEDGE), grounding=j(grounded=False, reason_code="out_of_period", reason="판 없음", unsupported_sentences=[HEDGE]))
    out = ask(llm)
    assert out["kind"] == "answer" and not out.get("refuse_reason") and "VP(Approves)" in out["answer"]
    assert out["grounding"]["caveat_only"] is True


def test_out_of_period_flag_on_a_value_sentence_still_refuses():
    llm = normal_llm(answer=reply(FACT, HEDGE), grounding=j(grounded=False, reason_code="out_of_period", reason="판 없음", unsupported_sentences=[HEDGE, FACT]))
    out = ask(llm)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "out_of_period"


def test_out_of_period_flag_still_refuses_when_the_question_itself_is_out_of_period():
    """질문이 근거의 가장 이른 판(2023년)보다 앞선 연도를 물으면 코드 규칙의 기간 판정이 기간 밖이므로, 단서 문장만 꼽았어도 거절 그대로다."""
    question = QUESTION.replace("계약 금액이", "2019년에 계약 금액이")
    assert G.check_rules(question, [ROW.model_dump()], [ROW.model_dump()]).reason == G.OUT_OF_PERIOD
    out = run(graph(lambda q: [ROW], llm=normal_llm(answer=reply(FACT, HEDGE), grounding=j(grounded=False, reason_code="out_of_period", reason="판 없음", unsupported_sentences=[HEDGE])), grounding_llm=True), question=question)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "out_of_period"
