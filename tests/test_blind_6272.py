"""사전 등록 62.72 시험: 정답을 보지 않은 실행 기록에서 고른 세 가지. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

- 2 `GRAPH_NONE_VOTE_WAIT_S`(코드 기본 빈 값, 서비스 1.0): 판정 다수결에서 먼저 온 두 표가 모두 "근거 없음"이면 셋째 표를 상한 초까지만 기다린다.
  상한 안에 오지 않으면 두 표로 확정하고 기록에 `how="none_capped"`를 남긴다. 충분·일부 두 표, 상한 안에 온 셋째 표, 스위치 끔은 지금과 같다.
- 6 `GRAPH_SPEC_STOP_GROUND`(코드 기본 꺼짐, 서비스 켬): 분해가 질문을 나눠 미리 돌리기를 버리기로 하면, 그 미리 돌리기 안의 답 후보는 근거 확인을 미리 부르지 않는다
  (기록 `skipped_spec_dropped`). 쓰는 미리 돌리기와 스위치 끔은 지금과 같다.
- 7 단계 시간 기록(스위치 없음, 기록만): 요청 집계 안에서 `path_meta`가 노드별 시간(`timing`)과 판정 표마다 걸린 초(`vote_s`)를 싣고,
  `search_stats`에 검색 단계 시간(`ms_*`)이 더해진다. 기록이 실패해도 답은 그대로다.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, IMOC, Q_ESC, Q_REVIEW, REVIEW, SUBS, cite, llm, run, searcher

from backend.graph import answer_fixes as AF
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from backend.services import step_cost

OK = j(sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
NO = j(sufficient=False, partial=False, reason="없음", missing=["리뷰 기한"], scope_note=None, clarify=None, query="review deadline")
PART = j(sufficient=False, partial=True, reason="일부", missing=["승인자"], scope_note=None, clarify=None, query="review approver")
GROUNDED = j(reason="", grounded=True)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("GRAPH_JUDGE_VOTE", "GRAPH_NONE_VOTE_WAIT_S", "GRAPH_SPEC_STOP_GROUND", "GRAPH_SPECULATE_FIRST", "GRAPH_SPECULATE_GROUND",
                 "GRAPH_SPECULATE_EARLY_SEARCH", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_ANSWER", "GRAPH_ANSWER_WAIT_S",
                 "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_QUOTE", "GRAPH_REVISE_AHEAD", "GRAPH_ADOPT_GROUNDED_CANDIDATE",
                 "GRAPH_STOP_STALLED_SEARCH", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_REFUSE_ON_NONE", "SEARCH_DECOMPOSE", "USE_SKILLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, **kw)


# ---------- 2 근거 없음 두 표 뒤 셋째 표 대기 상한 ----------
def votes(first, second, third, *, third_after: float):
    """판정 표 셋: 앞 둘은 바로, 셋째로 불린 호출은 `third_after`초 뒤에 답한다(스레드에서 불려도 순서를 잠가 센다)."""
    lock, n = threading.Lock(), [0]

    def h(_user):
        with lock:
            i = n[0]
            n[0] += 1
        if i % 3 == 2:
            time.sleep(third_after)
            return third
        return (first, second)[i % 3]
    return h


def judged(multi, handler):
    fn, _ = searcher([("", [REVIEW])])
    m = llm(judge=handler, answer=cite(REVIEW), grounding=GROUNDED)
    t0 = time.monotonic()
    out = run(graph(multi, fn, m, grounding_llm=True, max_research=0), Q_REVIEW)
    return out, time.monotonic() - t0


@pytest.mark.parametrize("raw, want", [("", None), ("  ", None), ("1.0", 1.0), ("0", 0.0), ("2.5", 2.5)])
def test_none_vote_wait_reads_seconds_and_empty_means_off(monkeypatch, raw, want):
    monkeypatch.setenv("GRAPH_NONE_VOTE_WAIT_S", raw)
    assert AF.none_vote_wait_s() == want


@pytest.mark.parametrize("raw", ["-1", "x", "1s"])
def test_none_vote_wait_rejects_bad_values(monkeypatch, raw):
    monkeypatch.setenv("GRAPH_NONE_VOTE_WAIT_S", raw)
    with pytest.raises(ValueError):
        AF.none_vote_wait_s()


def test_none_vote_wait_is_off_when_unset():
    assert AF.none_vote_wait_s() is None


@pytest.mark.parametrize("multi", [False, True])
def test_two_none_votes_settle_when_the_third_is_later_than_the_cap(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_NONE_VOTE_WAIT_S", "0.1")
    out, took = judged(multi, votes(NO, NO, OK, third_after=1.5))
    assert out["kind"] == "refuse" and took < 1.2   # 셋째 표(1.5초 뒤)를 기다리지 않았다
    if multi:   # 다중 에이전트 그래프는 표 구성 기록(`judge_votes`)을 상태에 싣지 않는다(62.67부터 그대로)
        return
    log = out["judge_votes"][0]
    assert log["how"] == "none_capped" and len(log["votes"]) == 2 and log["early"] is True


@pytest.mark.parametrize("multi", [False, True])
def test_a_third_vote_within_the_cap_is_counted_as_before(monkeypatch, multi):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_NONE_VOTE_WAIT_S", "2.0")
    on, _ = judged(multi, votes(NO, NO, PART, third_after=0.05))
    monkeypatch.delenv("GRAPH_NONE_VOTE_WAIT_S")
    off, _ = judged(multi, votes(NO, NO, PART, third_after=0.05))
    assert on["kind"] == off["kind"]
    if multi:
        return
    assert on["judge_votes"][0]["how"] == off["judge_votes"][0]["how"] == "majority"
    assert len(on["judge_votes"][0]["votes"]) == 3 and on["kind"] == off["kind"]


def test_switch_off_waits_for_the_third_vote(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    out, took = judged(False, votes(NO, NO, OK, third_after=0.4))
    assert took >= 0.4 and out["judge_votes"][0]["how"] == "majority" and len(out["judge_votes"][0]["votes"]) == 3


@pytest.mark.parametrize("pair", [OK, PART])
def test_sufficient_or_partial_two_votes_are_unchanged(monkeypatch, pair):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    monkeypatch.setenv("GRAPH_NONE_VOTE_WAIT_S", "0.1")
    on, _ = judged(False, votes(pair, pair, NO, third_after=0.6))
    monkeypatch.delenv("GRAPH_NONE_VOTE_WAIT_S")
    off, _ = judged(False, votes(pair, pair, NO, third_after=0.6))
    assert on["judge_votes"][0]["how"] == off["judge_votes"][0]["how"] == "two_agree"
    assert on["kind"] == off["kind"] and on.get("answer") == off.get("answer")


def test_vote_log_names_the_capped_case():
    from backend.graph import build as B

    n = {"sufficient": False, "partial": False}
    assert B.vote_log([n, n], False, 0, capped=True)["how"] == "none_capped"
    assert B.vote_log([n, n, n], True, 0)["how"] != "none_capped"
    assert B.vote_log([n, n], False, 0, capped=True, vote_s=[0.4, 0.5])["vote_s"] == [0.4, 0.5]


# ---------- 6 버린 미리 돌리기의 근거 확인 멈춤 ----------
def spec_run(monkeypatch, *, on, split, multi=False):
    """예비 분해(게이트)는 나누지 않고, 본 분해는 `split`. 미리 돌리기의 답이 나올 때는 분류 노드가 이미 버리기로 정했다(본 분해가 끝난 뒤 0.3초)."""
    monkeypatch.setenv("GRAPH_SPECULATE_FIRST", "1")
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    if on:
        monkeypatch.setenv("GRAPH_SPEC_STOP_GROUND", "1")
    else:
        monkeypatch.delenv("GRAPH_SPEC_STOP_GROUND", raising=False)
    split_done = threading.Event()

    def decompose(_user):   # 미리 돌리기가 판정과 답 작성까지 가도록 본 분해를 늦춘다
        time.sleep(0.3)
        split_done.set()
        return j(split=split, sub_questions=SUBS if split else [])

    def answer(_user):
        split_done.wait(5)
        time.sleep(0.3)
        return cite(ESC)

    m = llm(decompose=decompose, decompose_gate=j(split=False, sub_questions=[]), judge=OK, classify=j(route="rule"), answer=answer, grounding=GROUNDED)
    def search(q):   # 미리 돌리기(원 질문 하나)와 본 경로(하위 질문)의 문맥을 다르게 해 근거 확인 입력이 겹치지 않게 한다
        return [ESC, IMOC] if q.sub_queries else [ESC]
    out = run(graph(multi, search, m, decompose=True, parallel_intake=True, skip_first_rewrite=True, judge_answer="parallel_all",
                    grounding_llm=True), Q_ESC)
    time.sleep(0.3)   # 끔일 때 버린 쪽의 미리 부른 근거 확인이 배경에서 끝나도록 기다린다
    return out, m


@pytest.mark.parametrize("multi", [False, True])
def test_dropped_speculation_does_not_ground_ahead(monkeypatch, multi):
    off, m_off = spec_run(monkeypatch, on=False, split=True, multi=multi)
    on, m_on = spec_run(monkeypatch, on=True, split=True, multi=multi)
    assert off["search_stats"].get("speculated") == on["search_stats"].get("speculated") == "dropped"
    assert on["kind"] == off["kind"] == "answer" and on["answer"] == off["answer"]
    assert m_on.count("grounding") == m_off.count("grounding") - 1   # 버린 쪽의 미리 부른 근거 확인 1건이 없다
    rows = on["grounding"]["candidates"]
    assert any(r["verdict"] == "skipped_spec_dropped" and r["used"] is False for r in rows)
    assert not any(r["verdict"] == "skipped_spec_dropped" for r in off["grounding"]["candidates"])


def test_used_speculation_still_grounds_ahead(monkeypatch):
    off, m_off = spec_run(monkeypatch, on=False, split=False)
    on, m_on = spec_run(monkeypatch, on=True, split=False)
    assert on["search_stats"].get("speculated") == "used"
    assert m_on.count("grounding") == m_off.count("grounding") and on["answer"] == off["answer"]
    rows = on["grounding"]["candidates"]
    assert not any(r["verdict"] == "skipped_spec_dropped" for r in rows) and any(r["used"] and r["ahead"] for r in rows)


def test_spec_stop_ground_switch_reads_one():
    assert AF.spec_stop_ground_enabled() is False


# ---------- 7 단계 시간 기록 ----------
def test_path_meta_has_node_timing_and_vote_seconds_inside_a_request(monkeypatch):
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    fn, _ = searcher([("", [REVIEW])])
    m = llm(judge=OK, answer=cite(REVIEW), grounding=GROUNDED)
    meter, token = step_cost.begin()
    try:
        out = run(build_graph(fn, llm=m, grounding_llm=True), Q_REVIEW)
        path = step_cost.path_meta(out)["path"]
    finally:
        step_cost.end(token)
    timing = path["timing"]
    assert {"classify", "search", "judge", "answer_pick", "ground"} <= set(timing) and all(v >= 0 for v in timing.values())
    assert path["vote_s"] and path["vote_s"][0]["task"] == "judge" and 2 <= len(path["vote_s"][0]["s"]) <= 3
    assert out["judge_votes"][0]["vote_s"] == path["vote_s"][0]["s"]


def test_search_stats_carry_the_search_step_times(monkeypatch):
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")

    def fn(q):
        S._last.set(SimpleNamespace(ms={"translate": 1.0, "embed": 20.5, "vector": 3.0, "link": 4.0, "other": 9.0}, fallback_reason=None))
        return [REVIEW]
    out = run(build_graph(fn, llm=llm(answer=cite(REVIEW))), Q_REVIEW)
    stats = out["search_stats"]
    assert (stats["ms_translate"], stats["ms_embed"], stats["ms_vector"], stats["ms_link"]) == (1.0, 20.5, 3.0, 4.0) and "ms_other" not in stats
    assert step_cost.path_meta(out)["path"]["search_stats"]["ms_embed"] == 20.5


def test_recording_failures_do_not_change_the_answer(monkeypatch):
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")
    fn, _ = searcher([("", [REVIEW])])
    base = run(build_graph(fn, llm=llm(answer=cite(REVIEW), grounding=GROUNDED), grounding_llm=True), Q_REVIEW)

    def boom(*a, **k):
        raise RuntimeError("기록 실패")
    monkeypatch.setattr(step_cost.StepMeter, "add_time", boom)
    monkeypatch.setattr(step_cost.StepMeter, "add_votes", boom)
    monkeypatch.setattr(S, "last_search_trace", boom)
    fn, _ = searcher([("", [REVIEW])])
    meter, token = step_cost.begin()
    try:
        out = run(build_graph(fn, llm=llm(answer=cite(REVIEW), grounding=GROUNDED), grounding_llm=True), Q_REVIEW)
        path = step_cost.path_meta(out)["path"]
    finally:
        step_cost.end(token)
    assert out["kind"] == base["kind"] == "answer" and out["answer"] == base["answer"] and out["citations"] == base["citations"]
    assert path["timing"] == {}


def test_timing_sums_only_graph_nodes_not_background_calls():
    meter = step_cost.StepMeter()
    meter.add_time("search", 0.0, 1.0, False)
    meter.add_time("search", 0.2, 0.9, True)    # 노드 안 배경 호출은 더하지 않는다
    meter.add_time("judge", 1.0, 2.5, False)
    meter.add_time("write_answer", 2.5, 3.0, False)
    meter.add_time("rewrite", 0.0, 9.0, False)  # 칸 이름에 없는 노드는 싣지 않는다
    assert meter.timing() == {"search": 1.0, "judge": 1.5, "answer_pick": 0.5}
