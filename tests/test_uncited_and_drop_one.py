"""S-04: (1) 인용 없는 답 건수·비율과 분모 계산(`evals/uncited_answers.py`), (2) 하위 질문 하나를 빼도 1등이 그대로인지(`merge_by_score`). 저장된 결과와 순수 함수만 쓴다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import uncited_answers as U  # noqa: E402

from backend.rag.retrieve.search import merge_by_score  # noqa: E402


def row(i, result, cited):
    return {"id": i, "result": result, "cited": cited}


def test_denominators_are_answered_and_total_and_refusals_do_not_count_as_missing_citations():
    rows = [row(1, "answer", ["a"]), row(2, "answer", []), row(3, "refuse", []), row(4, "clarify", []), row(5, "refuse", [])]
    s = U.uncited_stats(rows)
    assert (s["total"], s["answered"], s["uncited_answers"], s["uncited_ids"]) == (5, 2, 1, [2])
    assert s["rate_of_answered"] == 0.5 and s["rate_of_total"] == 0.2


def test_no_answers_gives_no_rate_instead_of_dividing_by_zero():
    s = U.uncited_stats([row(1, "refuse", []), row(2, "clarify", [])])
    assert s["answered"] == 0 and s["uncited_answers"] == 0 and s["rate_of_answered"] is None
    assert U.uncited_stats([])["rate_of_total"] is None


def test_stored_results_in_the_repo_have_no_uncited_answers():
    """저장된 최종 결과(`agent_v1_final_cite`)를 읽어 센다. 값이 바뀌면 EVAL_REPORT의 인용 수치와 같이 본다."""
    folder = ROOT / "evals" / "results" / "agent_v1_final_cite"
    rows = U.load_rows(folder)
    s = U.uncited_stats(rows)
    assert s["total"] == len(rows) > 0 and s["answered"] > 0
    assert s["uncited_answers"] == 0 and s["rate_of_answered"] == 0.0


# ---------- 질의를 하나 빼도 1등이 그대로인지 ----------
FULL = ["f1", "f2", "f3", "f4", "f5"]                 # 전체 질문의 상위 목록
SUBS = [["a1", "a2", "x1", "x2"], ["b1", "b2", "x1", "x3"], ["c1", "c2", "x2", "x3"]]
SCORES = {k: 1.0 - i / 100 for i, k in enumerate(["a1", "b1", "c1", "x1", "x2", "x3", "a2", "b2", "c2", *FULL])}


def top(lists, k=5):
    return merge_by_score(lists, SCORES, k)


def test_dropping_a_later_sub_query_keeps_the_first_place():
    full = top([FULL, *SUBS])
    for drop in (1, 2):                                # 둘째, 셋째 하위 질문을 뺀다
        rest = [FULL, *[s for i, s in enumerate(SUBS) if i != drop]]
        assert top(rest)[0] == full[0] == "a1", drop
    assert top([FULL, *SUBS[:1], *SUBS[2:]])[:1] == ["a1"]


def test_every_remaining_sub_query_still_gets_its_first_hit_in_the_top():
    for drop in range(3):
        rest = [FULL, *[s for i, s in enumerate(SUBS) if i != drop]]
        out = top(rest)
        assert all(s[0] in out for s in rest[1:]), (drop, out)


def test_dropping_the_first_sub_query_does_change_the_first_place():
    """대조: 1등은 첫 하위 질문의 첫 후보에서 온다. 이 줄이 틀리면 위 두 시험이 우연히 통과한 것이다."""
    assert top([FULL, *SUBS[1:]])[0] == "b1" != top([FULL, *SUBS])[0]
