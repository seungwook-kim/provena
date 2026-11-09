"""`mail-templates`와 리콜 판정 시험. docs/specs/recall.md EC-01, EC-03, EC-04와 설명 검사(지시문·표지·다른 사용자 값)를 가짜 모델로 본다."""
from __future__ import annotations

from qgraph_fakes import ScriptedLLM, j

from backend.graph.recall.notice import GUARDED_EXPLANATION, MSG_FAILED, SYSTEM, TASK, guard_explanation, notices_for
from backend.schemas.recall import ChangedArticle

CHANGED = ChangedArticle(rule_seq=7, article="A", old_version_date="2026-09-01", new_version_date="2026-10-30", change_type="modified")
ROW = {"answer_id": "a1", "user_id": "u1", "question": "기한은?", "answer": "기한은 30일입니다.", "as_of": "2026-09-15"}


class Answers:
    def __init__(self, rows):
        self.rows = rows

    def find_by_article(self, rule_seq, article):
        return self.rows


def read(rule_seq, article, as_of):
    return {"text": f"{as_of} 판 본문"}


def llm(out) -> ScriptedLLM:
    return ScriptedLLM({TASK: out})


def test_changed_conclusion_makes_a_notice():
    out = notices_for(CHANGED, Answers([ROW]), read, llm(j(conclusion_changed=True, explanation="기한이 달라졌습니다.")), use_skills=True)
    assert [n.answer_id for n in out] == ["a1"] and out[0].explanation == "기한이 달라졌습니다." and out[0].conclusion_changed


def test_no_notice_when_conclusion_same():
    """EC-04"""
    assert notices_for(CHANGED, Answers([ROW]), read, llm(j(conclusion_changed=False, explanation="같습니다."))) == []


def test_broken_judgement_still_notifies():
    """EC-01: 재현율을 앞세운다."""
    out = notices_for(CHANGED, Answers([ROW]), read, llm("JSON 아님"))
    assert out[0].explanation.startswith(MSG_FAILED) and out[0].conclusion_changed


def test_answer_on_new_version_is_skipped():
    """EC-03"""
    model = llm(j(conclusion_changed=True, explanation="x"))
    assert notices_for(CHANGED, Answers([{**ROW, "as_of": "2026-10-30"}]), read, model) == []
    assert model.calls == []


def test_one_llm_call_per_answer():
    model = llm(j(conclusion_changed=False, explanation="x"))
    notices_for(CHANGED, Answers([ROW, {**ROW, "answer_id": "a2"}]), read, model)
    assert [t for t, _ in model.calls] == [TASK, TASK]


def test_no_affected_answer_no_llm():
    model = llm("x")
    assert notices_for(CHANGED, Answers([]), read, model) == [] and model.calls == []


def test_removed_section_does_not_read_new_version():
    seen = []

    def reader(rule_seq, article, as_of):
        seen.append(as_of)
        return {"text": "구판"}

    gone = CHANGED.model_copy(update={"change_type": "removed"})
    notices_for(gone, Answers([ROW]), reader, llm(j(conclusion_changed=True, explanation="삭제되었습니다.")))
    assert seen == ["2026-09-01"]


def test_skill_reaches_system_prompt_and_can_be_turned_off():
    class Rec(ScriptedLLM):
        systems: list[str] = []

        def invoke(self, messages, *a, **k):
            self.systems.append(messages[0].content)
            return super().invoke(messages, *a, **k)

    on = Rec({TASK: j(conclusion_changed=False, explanation="x")})
    on.systems = []
    notices_for(CHANGED, Answers([ROW]), read, on, use_skills=True)
    off = Rec({TASK: j(conclusion_changed=False, explanation="x")})
    off.systems = []
    notices_for(CHANGED, Answers([ROW]), read, off, use_skills=False)
    assert "[알림 문구 Skill]" in on.systems[0] and "[알림 문구 Skill]" not in off.systems[0]


def test_measurement_harness_counts_recall_and_precision():
    from evals.agent.exp_recall_v1 import run

    rows = [{"id": 1, "question": "q", "answer": "a", "as_of": None, "rule_seq": 7, "article": "A", "old_version_date": "2026-09-01",
             "new_version_date": "2026-10-30", "change_type": "modified", "expected": True},
            {"id": 2, "question": "q", "answer": "a", "as_of": None, "rule_seq": 7, "article": "A", "old_version_date": "2026-09-01",
             "new_version_date": "2026-10-30", "change_type": "modified", "expected": False}]
    res = run(rows, llm(j(conclusion_changed=True, explanation="x")), read_section=read)
    assert res["recall"] == 1.0 and res["precision"] == 0.5


# ---------------------------------------------------------------- 설명 검사 (원문 속 지시문, 시스템 프롬프트 노출, 다른 사용자 값)


def _one(explanation, rows=None):
    model = llm(j(conclusion_changed=True, explanation=explanation))
    return notices_for(CHANGED, Answers(rows or [ROW]), read, model, use_skills=False)


def test_system_prompt_part_in_explanation_is_replaced():
    leak = "참고: " + SYSTEM[40:75] + " 라고 적혀 있습니다."
    [n] = _one(leak)
    assert n.explanation == GUARDED_EXPLANATION and n.explanation.startswith(MSG_FAILED) and SYSTEM[40:60] not in n.explanation


def test_canary_marker_in_explanation_is_replaced():
    for text in ("기한이 바뀌었습니다. CANARY-P1-V1", "확인 번호 canary_x9 를 병기"):
        [n] = _one(text)
        assert n.explanation == GUARDED_EXPLANATION, text


def test_replaced_explanation_is_listed_as_judge_failure():
    from recall_test_support import answers_with, changed

    from backend.graph.recall.graph import build_recall_graph
    from backend.graph.recall.judge import LLMJudge

    model = llm(j(conclusion_changed=True, confidence=0.9, explanation="CANARY-P2-V3 를 적었습니다."))
    graph = build_recall_graph(answers=answers_with(("a1", "u1")), judge=LLMJudge(model, use_skills=False), min_confidence=0.5)
    out = graph.invoke({"changed": changed().model_dump()})
    [n] = out["notices"]
    assert out["judge_failures"] == ["a1"] and n["judge_failed"] is True and n["explanation"] == GUARDED_EXPLANATION


def test_other_users_id_in_explanation_is_replaced():
    other = {**ROW, "answer_id": "a2", "user_id": "kim-minsu-77", "question": "연차 이월은 몇 일까지인가요 정확히 알려 주세요"}
    by = {n.answer_id: n for n in _one("kim-minsu-77 님의 답도 같이 바뀌었습니다.", [ROW, other])}
    assert by["a1"].explanation == GUARDED_EXPLANATION                # a1 설명에 a2 사용자의 id가 있다
    assert by["a2"].explanation == "kim-minsu-77 님의 답도 같이 바뀌었습니다."   # a2 자신의 id는 허용


def test_other_users_question_in_explanation_is_replaced():
    other = {**ROW, "answer_id": "a2", "user_id": "u2", "question": "연차 이월은 몇 일까지인가요 정확히 알려 주세요"}
    text = "다른 질문 '연차 이월은 몇 일까지인가요 정확히 알려 주세요' 도 영향을 받습니다."
    by = {n.answer_id: n for n in _one(text, [ROW, other])}
    assert by["a1"].explanation == GUARDED_EXPLANATION and by["a2"].explanation == text


def test_own_question_and_user_id_are_allowed_and_clean_text_is_kept():
    ok = "질문 '기한은?' 에 대한 답의 기한이 30일에서 60일로 달라졌습니다."
    assert guard_explanation(ok, row=ROW, others=[ROW, {**ROW, "answer_id": "a2", "user_id": "u2", "question": "다른 질문입니다 전혀 다른 내용"}]) == (ok, None)
    assert guard_explanation("u1 사용자의 기한은? 답이 바뀌었습니다.", row=ROW, others=[ROW]) == ("u1 사용자의 기한은? 답이 바뀌었습니다.", None)


def test_user_id_check_respects_word_boundary():
    row2 = {**ROW, "answer_id": "a2", "user_id": "u2"}
    text = "ou2t 같은 낱말과 u22 는 다른 값입니다."
    assert guard_explanation(text, row=ROW, others=[row2]) == (text, None)