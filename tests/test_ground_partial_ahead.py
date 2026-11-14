"""사전 등록 62.49: 판정과 같이 쓴 답의 근거 판정을, 그 판정이 낼 수 있는 일부 답 여부 값마다 미리 부른다(`GRAPH_SPECULATE_GROUND`가 켜져 있을 때만).

재검색 뒤 판정이 일부에서 충분으로 바뀌면, 같이 쓴 답의 근거 판정은 "일부 답" 입력으로 미리 돌아 있어 쓰이지 못하고 판정이 끝난 뒤 "전체 답" 입력으로 다시 불렸다.
바꾼 뒤에는 두 입력을 모두 미리 불러 판정이 끝나면 바로 쓴다. 판정 입력·기준·답은 그대로이고 달라지는 것은 호출 시점뿐이다. 가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

import threading
import time

import pytest
from qgraph_fakes import ScriptedLLM, j
from test_answer_fixes_graph import ESC, IMOC, PARTIAL, Q_ESC, SUBS, cite
from test_answer_fixes_graph import llm as base_llm
from test_answer_fixes_graph import run as run_q

from backend.graph.build import MSG_PARTIAL_NOTE, build_graph

SWITCHES = ("GRAPH_SPECULATE_GROUND", "GRAPH_JUDGE_ANSWER", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_VOTE", "GRAPH_JUDGE_QUOTE",
            "GRAPH_REVISE_AHEAD", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH", "GRAPH_SPECULATE_FIRST",
            "SEARCH_DECOMPOSE", "USE_SKILLS", "GROUND_SKIP_BACKED")
OK_JUDGE = j(sufficient=True, reason="", clarify=None)
NONE_JUDGE = j(checks=[], sufficient=False, partial=False, reason="관련 규정 없음", missing=["EOC 무응답 단계"], scope_note=None, clarify=None, query="EOC escalation")   # 나뉜 질문의 일부 판정은 재검색 없이 일부 답이 되므로(62.63) 재검색을 낳는 첫 판정은 전무다
JUDGE_SLOW_S = 0.4  # 재검색 뒤 판정이 걸리는 시간. 같이 쓴 답과 그 근거 판정은 이 안에 끝난다


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def _research(judges: list[str], *, ahead: bool, monkeypatch):
    """나뉜 질문의 첫 검색은 ESC만, 재검색은 ESC와 IMOC를 준다. 첫 판정은 `judges[0]`(전무), 재검색 뒤 판정은 `judges[1]`이고 0.4초 걸린다.
    돌려주는 것: 결과, 모델, 재검색 뒤 답(IMOC 인용)의 근거 판정 호출 시작 시각들, 재검색 뒤 판정이 끝난 시각."""
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", "3")
    if ahead:
        monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    else:
        monkeypatch.delenv("GRAPH_SPECULATE_GROUND", raising=False)
    lock = threading.Lock()
    seen = {"judge": 0, "judge_end": 0.0, "ground": []}

    def judge(user):
        with lock:
            i = seen["judge"]
            seen["judge"] += 1
        if i >= 1:
            time.sleep(JUDGE_SLOW_S)
            seen["judge_end"] = time.monotonic()
        return judges[min(i, len(judges) - 1)]

    def grounding(user):
        if IMOC.chunk_id in user.split("참고")[0]:    # 재검색 뒤 답만 IMOC를 인용한다
            with lock:
                seen["ground"].append(time.monotonic())
        return j(reason="", grounded=True)

    def answer(user):
        return cite(*[c for c in (ESC, IMOC) if c.chunk_id in user])

    def fn(q):
        return [ESC, IMOC] if q.query != Q_ESC and not q.sub_queries else [ESC]

    handlers = {**base_llm().handlers, "decompose": j(split=True, sub_questions=SUBS), "judge": judge, "answer": answer, "answer_fast": answer, "grounding": grounding}
    llm = ScriptedLLM(handlers)
    out = run_q(build_graph(fn, llm=llm, decompose=True, max_research=1, grounding_llm=True), Q_ESC)
    time.sleep(0.2)   # 버려진 미리 부르기가 끝나도록
    return out, llm, list(seen["ground"]), seen["judge_end"]


def _core(out):
    return out["kind"], out["answer"], [c["chunk_id"] for c in out.get("citations", [])]


def test_partial_then_sufficient_uses_a_verdict_started_before_the_judge_ended(monkeypatch):
    """전무 -> 충분: 전체 답 입력의 근거 판정이 재검색 뒤 판정과 같이 돌고 있어, 판정이 끝난 뒤에 새로 부르지 않는다."""
    off, _, _, _ = _research([NONE_JUDGE, OK_JUDGE], ahead=False, monkeypatch=monkeypatch)
    on, llm, starts, judge_end = _research([NONE_JUDGE, OK_JUDGE], ahead=True, monkeypatch=monkeypatch)
    assert _core(on) == _core(off) and on["kind"] == "answer" and MSG_PARTIAL_NOTE not in on["answer"]
    assert [c["chunk_id"] for c in on["citations"]] == [ESC.chunk_id, IMOC.chunk_id]
    assert on["grounding"]["ground_ahead"] is True                 # 미리 부른 판정을 썼다(바꾸기 전에는 입력이 달라 못 썼다)
    assert len(starts) == 2 and all(t < judge_end for t in starts)  # 일부 답 입력 1번, 전체 답 입력 1번. 둘 다 판정이 끝나기 전에 시작했다


def test_partial_then_partial_keeps_the_partial_answer_and_reuses_the_early_verdict(monkeypatch):
    """전무 -> 일부: 지금처럼 일부 답 입력의 판정을 쓴다. 전체 답 입력으로 미리 부른 판정 하나가 버려진다(비용만)."""
    off, _, _, _ = _research([NONE_JUDGE, PARTIAL], ahead=False, monkeypatch=monkeypatch)
    on, llm, starts, judge_end = _research([NONE_JUDGE, PARTIAL], ahead=True, monkeypatch=monkeypatch)
    assert _core(on) == _core(off) and on["kind"] == "answer" and MSG_PARTIAL_NOTE in on["answer"]
    assert on["grounding"]["ground_ahead"] is True and on["grounding"]["partial_route"] is True
    assert len(starts) == 2 and all(t < judge_end for t in starts)


def test_grounding_inputs_are_the_same_set_as_without_the_early_calls(monkeypatch):
    """미리 부른 판정의 입력은 꺼짐에서 부르던 입력과 글자까지 같다(전무 -> 충분에서 쓰인 판정 기준)."""
    _, off_llm, _, _ = _research([NONE_JUDGE, OK_JUDGE], ahead=False, monkeypatch=monkeypatch)
    _, on_llm, _, _ = _research([NONE_JUDGE, OK_JUDGE], ahead=True, monkeypatch=monkeypatch)
    used_off = [u for t, u in off_llm.calls if t == "grounding" and IMOC.chunk_id in u.split("참고")[0]]
    used_on = {u for t, u in on_llm.calls if t == "grounding" and IMOC.chunk_id in u.split("참고")[0]}
    assert len(used_off) == 1 and used_off[0] in used_on


def test_first_judge_sufficient_starts_no_extra_verdict(monkeypatch):
    """첫 판정에서 끝나는 질문(대부분)은 미리 부르는 판정 수가 그대로다: 답 후보마다 하나."""
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    llm = base_llm(answer=cite(ESC))
    out = run_q(build_graph(lambda q: [ESC, IMOC], llm=llm, grounding_llm=True), Q_ESC)
    time.sleep(0.1)
    assert out["kind"] == "answer" and out["grounding"]["ground_ahead"] is True
    assert llm.count("grounding") == 1


def test_without_the_speculative_pool_nothing_changes(monkeypatch):
    """`GRAPH_SPECULATE_GROUND`가 꺼져 있으면 미리 부르지 않는다: 재검색 뒤 답의 근거 판정은 판정이 끝난 뒤 한 번이다."""
    out, llm, starts, judge_end = _research([NONE_JUDGE, OK_JUDGE], ahead=False, monkeypatch=monkeypatch)
    assert out["kind"] == "answer" and "ground_ahead" not in out["grounding"]
    assert len(starts) == 1 and starts[0] > judge_end
