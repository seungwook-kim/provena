"""`GRAPH_SPLIT_VOTE_WAIT_S` 시험(2026-11-17, 검증 v2 응답 시간 분석 `evals/results/latency_holdout_v2_analysis_20261117/`의 후보 A).
가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

- 코드 기본 빈 값: 지금처럼 셋째 표를 끝까지 기다린다.
- 값이 있으면: 판정 다수결에서 먼저 온 두 표가 충분과 일부로 갈렸을 때 셋째 표를 그 초까지만 기다리고, 오지 않으면 두 표로 확정한다(기록 `how="split_capped"`).
  두 표가 같은 수이므로 `merge_votes`의 규칙대로 먼저 온 표가 결론이다.
- 근거 없음 표가 섞인 갈림(충분·근거 없음, 일부·근거 없음)은 대상이 아니다. 상한 안에 온 셋째 표는 지금처럼 센다.
"""
from __future__ import annotations

import pytest
from test_blind_6272 import NO, OK, PART, judged, votes

from backend.graph import answer_fixes as AF


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_JUDGE_VOTE", "GRAPH_NONE_VOTE_WAIT_S", "GRAPH_SPLIT_VOTE_WAIT_S", "GRAPH_SPEC_STOP_GROUND", "GRAPH_SPECULATE_FIRST",
                 "GRAPH_SPECULATE_GROUND", "GRAPH_SPECULATE_EARLY_SEARCH", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_ANSWER",
                 "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_QUOTE", "GRAPH_REVISE_AHEAD",
                 "GRAPH_ADOPT_GROUNDED_CANDIDATE", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_REFUSE_ON_NONE", "SEARCH_DECOMPOSE", "USE_SKILLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


@pytest.mark.parametrize("raw, want", [("", None), ("  ", None), ("1.0", 1.0), ("0", 0.0), ("2.5", 2.5)])
def test_split_vote_wait_reads_seconds_and_empty_means_off(monkeypatch, raw, want):
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", raw)
    assert AF.split_vote_wait_s() == want


@pytest.mark.parametrize("raw", ["-1", "x", "1s"])
def test_split_vote_wait_rejects_bad_values(monkeypatch, raw):
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", raw)
    with pytest.raises(ValueError):
        AF.split_vote_wait_s()


def test_split_vote_wait_is_off_when_unset():
    assert AF.split_vote_wait_s() is None


@pytest.mark.parametrize("multi", [False, True])
def test_split_votes_settle_when_the_third_is_later_than_the_cap(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", "0.1")
    out, took = judged(multi, votes(OK, PART, OK, third_after=1.5))
    assert took < 1.2   # 셋째 표(1.5초 뒤)를 기다리지 않았다
    if multi:   # 다중 에이전트 그래프는 표 구성 기록(`judge_votes`)을 상태에 싣지 않는다
        return
    log = out["judge_votes"][0]
    assert log["how"] == "split_capped" and len(log["votes"]) == 2 and log["early"] is True


def test_switch_off_waits_for_the_third_split_vote(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    out, took = judged(False, votes(OK, PART, OK, third_after=0.4))
    log = out["judge_votes"][0]
    assert took >= 0.4 and log["how"] == "majority" and len(log["votes"]) == 3


@pytest.mark.parametrize("multi", [False, True])
def test_a_third_split_vote_within_the_cap_is_counted_as_before(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", "2.0")
    on, _ = judged(multi, votes(OK, PART, OK, third_after=0.05))
    monkeypatch.delenv("GRAPH_SPLIT_VOTE_WAIT_S")
    off, _ = judged(multi, votes(OK, PART, OK, third_after=0.05))
    assert on["kind"] == off["kind"] and on.get("answer") == off.get("answer")
    if multi:
        return
    assert on["judge_votes"][0]["how"] == off["judge_votes"][0]["how"] == "majority"
    assert len(on["judge_votes"][0]["votes"]) == 3


@pytest.mark.parametrize("pair", [(OK, NO), (PART, NO)])
def test_splits_with_a_none_vote_still_wait_for_the_third(monkeypatch, pair):
    """근거 없음 표가 섞인 갈림은 셋째 표가 재검색·거절 여부를 정하므로 상한을 걸지 않는다(결정 0100)."""
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", "0.05")
    out, took = judged(False, votes(*pair, OK, third_after=0.4))
    assert took >= 0.4 and out["judge_votes"][0]["how"] != "split_capped" and len(out["judge_votes"][0]["votes"]) == 3


def test_agreeing_two_votes_are_unchanged(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_SPLIT_VOTE_WAIT_S", "0.1")
    on, _ = judged(False, votes(OK, OK, PART, third_after=0.6))
    monkeypatch.delenv("GRAPH_SPLIT_VOTE_WAIT_S")
    off, _ = judged(False, votes(OK, OK, PART, third_after=0.6))
    assert on["judge_votes"][0]["how"] == off["judge_votes"][0]["how"] == "two_agree"
    assert on["kind"] == off["kind"] and on.get("answer") == off.get("answer")


def test_two_split_votes_merge_to_the_first_arrived():
    """상한으로 두 표만 남으면 같은 수이고, `merge_votes`는 먼저 온 표를 결론으로 쓴다(새 규칙 없음)."""
    s = {"sufficient": True, "partial": False, "missing": []}
    p = {"sufficient": False, "partial": True, "missing": ["승인자"]}
    assert AF.merge_votes("judge", [s, p])["sufficient"] is True
    assert AF.merge_votes("judge", [p, s])["partial"] is True


def test_vote_log_names_the_split_capped_case():
    from backend.graph import build as B

    s, p = {"sufficient": True, "partial": False}, {"sufficient": False, "partial": True}
    assert B.vote_log([s, p], False, 0, capped="split")["how"] == "split_capped"
    assert B.vote_log([s, p], False, 0, capped="none")["how"] == "none_capped"
    assert B.vote_log([s, p], False, 0, capped=True)["how"] == "none_capped"   # 기존 호출 그대로
    assert B.vote_log([s, p, s], True, 0)["how"] == "majority"
