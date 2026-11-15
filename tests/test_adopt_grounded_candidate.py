"""사전 등록 62.68 시험. 가짜 모델과 가짜 검색기만 쓰고 키·네트워크를 쓰지 않는다(0원).

- `GRAPH_ADOPT_GROUNDED_CANDIDATE`: 고른 답의 근거 확인이 받쳐지지 않는 주장을 찾으면, 답을 다시 쓰기 전에 미리 부른 근거 확인이 이미 끝나
  같은 일부 답 값·같은 문맥으로 받쳐졌다고 한 다른 후보를 같은 검사와 후처리를 거쳐 쓴다. 조건이 하나라도 맞지 않으면 지금처럼 다시 쓴다.
- 기록: done 이벤트 `path.grounding`의 `switched_from`·`switched_to`와 답 다시 쓰기 기록(`redraft`, 본문 제외).

답 후보 두 개는 같은 입력으로 쓰는 두 번 쓰기(`GRAPH_ANSWER_BEST2`)의 후보다. 첫 후보(일꾼 `answer2_0`)가 고른 답이고, 둘째 후보(`answer2_1`)가 다른 후보다.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future

import pytest
from qgraph_fakes import ScriptedLLM, j
from test_answer_fixes_graph import Q_REVIEW, REVIEW, REVIEW_TOO, cite, run
from test_answer_fixes_graph import llm as base_llm

from backend.graph import build as B
from backend.graph import service_profile as SP
from backend.graph.build import build_graph
from backend.services import step_cost

SWITCH = "GRAPH_ADOPT_GROUNDED_CANDIDATE"
OTHERS = ("GRAPH_SPECULATE_GROUND", "GRAPH_ANSWER_BEST2", "GRAPH_JUDGE_ANSWER", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_JUDGE_VOTE",
          "GRAPH_JUDGE_QUOTE", "GRAPH_REVISE_AHEAD", "GRAPH_POINTER_REFUSE", "GRAPH_UNCHANGED_REJUDGE", "GRAPH_KEEP_CITES", "GRAPH_BEST2_SAMEDOC",
          "GRAPH_GROUNDING_QUOTE", "GRAPH_CITE_EXPAND", "GRAPH_CITE_PHRASE", "GRAPH_CITE_CONSENSUS", "GRAPH_DROP_SCOPED_CITES", "GROUND_SKIP_BACKED",
          "SEARCH_DECOMPOSE", "USE_SKILLS")
REDRAFT_MARK = "이전 답이 근거 판정을 통과하지 못했다"   # 다시 쓰는 답 입력(`redraft_user`)에만 있는 문장
CHOSEN, OTHER, REDONE = "첫 후보 답", "둘째 후보 답", "다시 쓴 답"
UNSUPPORTED = j(grounded=False, reason_code="unsupported", reason="자료와 다름", unsupported_sentences=[f"{CHOSEN} [{REVIEW.chunk_id}]"])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (SWITCH, *OTHERS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")


def _answer_of(user: str) -> str:
    return user.split("<<<답>>>")[-1].split("<<<끝>>>")[0]


def _scenario(*, chosen_ok: bool = False, other_ok: bool = True, other_slow_s: float = 0.0, chosen_text: str = CHOSEN):
    """첫 후보는 REVIEW, 둘째 후보는 REVIEW_TOO를 인용한다. 첫 후보는 0.3초 늦게 끝나 둘째 후보의 미리 부른 근거 확인이 먼저 끝난다.
    근거 확인: 첫 후보는 `chosen_ok`, 둘째 후보는 `other_ok`(그 호출은 `other_slow_s`초 걸린다), 다시 쓴 답은 받쳐진다."""
    def answer(user):
        if REDRAFT_MARK in user:
            return cite(REVIEW, text=REDONE)
        if threading.current_thread().name.endswith("_0"):
            time.sleep(0.3)
            return cite(REVIEW, text=chosen_text)
        return cite(REVIEW_TOO, text=OTHER)

    def grounding(user):
        said = _answer_of(user)
        if OTHER in said:
            if other_slow_s:
                time.sleep(other_slow_s)
            return j(reason="", grounded=True) if other_ok else UNSUPPORTED
        if chosen_text in said and not chosen_ok:
            return UNSUPPORTED
        return j(reason="", grounded=True)

    m = base_llm(answer=answer, answer_fast=answer, grounding=grounding)
    out = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=m, grounding_llm=True), Q_REVIEW)
    return out, m


def _redraft_calls(m: ScriptedLLM) -> int:
    return sum(1 for t, u in m.calls if t in ("answer", "answer_fast") and REDRAFT_MARK in u)


def _ids(out):
    return [c["chunk_id"] for c in out.get("citations", [])]


# ---------- 꺼짐 ----------
def test_switch_off_redrafts_as_before_and_records_no_switch():
    out, m = _scenario()
    g = out["grounding"]
    assert out["kind"] == "answer" and REDONE in out["answer"] and g["redrafted"] is True and _redraft_calls(m) == 1
    assert "switched_from" not in g and "switched_to" not in g and "switch_failed" not in g
    assert all("cand" not in r and "adopted" not in r for r in g["candidates"])   # 후보 답은 기록에 싣지 않는다


def test_service_profile_turns_the_switch_on_and_off_is_respected():
    env: dict = {}
    SP.apply_service_profile(env)
    assert env[SWITCH] == "1" and env["GRAPH_SPECULATE_GROUND"] == "1"
    given = {SWITCH: "off"}
    SP.apply_service_profile(given)
    assert given[SWITCH] == ""
    assert B.AF.adopt_grounded_enabled() is False                    # 코드 기본은 꺼짐


@pytest.mark.parametrize("best2", [True, False])
def test_switch_on_keeps_answers_whose_first_check_passes(monkeypatch, best2):
    """처음 근거 확인이 통과한 경로의 답·인용·근거 기록은 스위치와 관계없이 같다(후보가 둘일 때와 하나일 때)."""
    if not best2:
        monkeypatch.setenv("GRAPH_ANSWER_BEST2", "")
    off, _ = _scenario(chosen_ok=True)
    monkeypatch.setenv(SWITCH, "1")
    on, m = _scenario(chosen_ok=True)
    strip = lambda o: {k: v for k, v in o["grounding"].items() if k != "candidates"}  # noqa: E731
    assert on["answer"] == off["answer"] and _ids(on) == _ids(off) and strip(on) == strip(off)
    assert "switched_from" not in on["grounding"] and _redraft_calls(m) == 0


def test_switch_needs_the_speculative_ground(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    monkeypatch.delenv("GRAPH_SPECULATE_GROUND")
    out, m = _scenario()
    assert REDONE in out["answer"] and _redraft_calls(m) == 1 and "switched_from" not in out["grounding"]


# ---------- 켬: 이미 받쳐진 다른 후보를 쓴다 ----------
def test_switch_on_adopts_the_grounded_sibling_without_a_redraft(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    out, m = _scenario()
    g = out["grounding"]
    assert out["kind"] == "answer" and OTHER in out["answer"] and _ids(out) == [REVIEW_TOO.chunk_id]
    assert _redraft_calls(m) == 0 and "redraft" not in g and "redrafted" not in g
    assert (g["switched_from"], g["switched_to"]) == ("answer", "answer") and g["llm"] == "grounded" and g["ground_ahead"] is True
    assert CHOSEN in g["draft_answer"]                               # 처음 고른 답은 기록에만 남긴다
    assert m.count("grounding") == 2                                  # 두 후보의 미리 부른 근거 확인뿐(다시 쓴 답의 재판정이 없다)
    adopted = [r for r in g["candidates"] if r.get("adopted")]
    assert len(adopted) == 1 and adopted[0]["used"] is True and adopted[0]["verdict"] == "grounded"
    assert all("cand" not in r for r in g["candidates"])
    path = step_cost.path_meta(out)["path"]["grounding"]
    assert (path["switched_from"], path["switched_to"]) == ("answer", "answer") and "redraft" not in path


def test_adopted_answer_is_post_processed_like_a_chosen_answer(monkeypatch):
    """쓴 후보의 답은 그 후보가 처음부터 고른 답으로 통과했을 때와 글자까지 같다(인용 번호, 기준일, 인용 정리)."""
    monkeypatch.setenv(SWITCH, "1")
    out, _ = _scenario()

    def answer(user):
        return cite(REVIEW_TOO, text=OTHER)
    direct = run(build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=base_llm(answer=answer, answer_fast=answer), grounding_llm=True), Q_REVIEW)
    assert out["answer"] == direct["answer"] and _ids(out) == _ids(direct)
    assert out.get("trimmed_citations", []) == direct.get("trimmed_citations", []) and out["answer"].endswith(direct["answer"].split("\n\n")[-1])


# ---------- 켬: 조건이 맞지 않으면 지금처럼 다시 쓴다 ----------
def test_sibling_still_running_is_not_awaited(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    started = time.monotonic()
    out, m = _scenario(other_slow_s=1.5)
    assert REDONE in out["answer"] and _redraft_calls(m) == 1 and "switched_from" not in out["grounding"]
    assert out["grounding"]["switch_failed"] == "no_sibling"
    assert time.monotonic() - started < 1.5                           # 끝나지 않은 미리 부른 판정을 기다리지 않는다


def test_sibling_not_grounded_redrafts(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    out, m = _scenario(other_ok=False)
    assert REDONE in out["answer"] and out["grounding"]["redrafted"] is True and _redraft_calls(m) == 1
    assert "switched_from" not in out["grounding"] and out["grounding"]["switch_failed"] == "no_sibling"   # 켰지만 쓸 후보가 없었다(꺼짐과 구분)
    assert step_cost.path_meta(out)["path"]["grounding"]["switch_failed"] == "no_sibling"


def test_an_error_while_switching_falls_back_to_the_redraft(monkeypatch):
    """후보를 다시 검사하다 예외가 나면(여기서는 `verify`의 누출 검사) 요청을 멈추지 않고 지금처럼 다시 쓴다."""
    monkeypatch.setenv(SWITCH, "1")
    real = B.leaks_internal

    def leaks(text):
        if OTHER in (text or "") and not threading.current_thread().name.startswith("answer2"):   # 미리 부르기 때의 검사는 그대로, 바꿀 때의 검사만 실패
            raise RuntimeError("check failed")
        return real(text)

    monkeypatch.setattr(B, "leaks_internal", leaks)
    out, m = _scenario()
    assert out["kind"] == "answer" and REDONE in out["answer"] and _redraft_calls(m) == 1
    assert out["grounding"]["switch_failed"] == "error" and "switched_from" not in out["grounding"]


def _closure_value(graph, name: str):
    """시험용: 그래프 노드 함수의 클로저를 따라가 `build_graph` 안의 변수(`ground_runs` 등)를 찾는다."""
    seen, todo = set(), [graph.builder.nodes[n].runnable.func for n in graph.builder.nodes]
    while todo:
        fn = todo.pop()
        if id(fn) in seen or not callable(fn) or not hasattr(fn, "__code__"):
            continue
        seen.add(id(fn))
        for var, cell in zip(fn.__code__.co_freevars, fn.__closure__ or ()):
            try:
                value = cell.cell_contents
            except ValueError:   # 아직 값이 없는 칸
                continue
            if var == name:
                return value
            if callable(value):
                todo.append(value)
    raise LookupError(name)


def test_adoption_leaves_the_early_verdict_registry_to_the_normal_expiry(monkeypatch):
    """쓴 후보의 미리 부른 판정 등록은 지우지 않는다. 같은 판정의 다른 일부 답 값 짝(`ground_twins`)도 지금처럼 2분 뒤 등록과 함께 지워진다."""
    monkeypatch.setenv(SWITCH, "1")

    def answer(user):
        if REDRAFT_MARK in user:
            return cite(REVIEW, text=REDONE)
        if threading.current_thread().name.endswith("_0"):
            time.sleep(0.3)
            return cite(REVIEW, text=CHOSEN)
        return cite(REVIEW_TOO, text=OTHER)

    def grounding(user):
        return UNSUPPORTED if CHOSEN in _answer_of(user) else j(reason="", grounded=True)

    g = build_graph(lambda q: [REVIEW, REVIEW_TOO], llm=base_llm(answer=answer, answer_fast=answer, grounding=grounding), grounding_llm=True)
    out = run(g, Q_REVIEW)
    assert out["grounding"]["switched_to"] == "answer"
    runs, twins = _closure_value(g, "ground_runs"), _closure_value(g, "ground_twins")
    adopted = [k for k, (_, f) in runs.items() if f.done() and f.result().get("state") == "grounded"]
    assert len(adopted) == 1                                           # 쓴 후보의 등록이 남아 있다(같은 입력의 다른 요청이 같이 쓸 수 있다)
    key = adopted[0]
    twins[key], twins["짝"] = ("짝",), (key,)                          # 같은 후보를 다른 일부 답 값으로 미리 부른 짝이 있었다고 둔다
    real = time.monotonic
    monkeypatch.setattr(B.time, "monotonic", lambda: real() + 300.0)   # 2분이 지난 뒤의 다음 요청
    run(g, "코드 리뷰 응답 기한은 며칠이야?")
    assert key not in runs and key not in twins


def test_sibling_failing_the_after_checks_redrafts(monkeypatch):
    """다른 후보가 고른 답과 같은 후처리(여기서는 다른 자료 안내뿐인 구절 거절)에서 거절되면 쓰지 않고 다시 쓴다."""
    monkeypatch.setenv(SWITCH, "1")
    monkeypatch.setenv("GRAPH_POINTER_REFUSE", "1")
    monkeypatch.setattr(B.AF, "pointer_only", lambda quotes: True)
    out, m = _scenario()
    assert REDONE in out["answer"] and _redraft_calls(m) == 1
    assert out["grounding"]["switch_failed"] == "refused_after_switch" and "switched_from" not in out["grounding"]


# ---------- 다른 후보 고르기 규칙 ----------
def _done(state: str) -> Future:
    f: Future = Future()
    f.set_result({"state": state})
    return f


def _row(key: str, fut: Future | None, *, scope: str = "full", partial: bool = False, cand: bool = True, kind: str = "fast") -> dict:
    return {"kind": kind, "scope": scope, "partial": partial, "key": key, "future": fut, **({"cand": {"answer": key}} if cand else {})}


def test_grounded_sibling_rules():
    chosen = _row("c", _done("ungrounded"))
    ok = _row("s", _done("grounded"), kind="reasoning")
    got = B.grounded_sibling([chosen, ok], "c", False)
    assert got is not None and got[0] is chosen and got[1] is ok and got[2] == {"state": "grounded"}
    pending, cancelled, failed = Future(), Future(), Future()
    cancelled.cancel()
    failed.set_exception(RuntimeError("x"))
    for other in (_row("s", pending), _row("s", cancelled), _row("s", failed), _row("s", _done("ungrounded")), _row("s", _done("inconclusive")),
                  _row("s", _done("grounded"), partial=True), _row("s", _done("grounded"), scope="core"), _row("s", _done("grounded"), cand=False),
                  _row("c", _done("grounded"))):
        assert B.grounded_sibling([chosen, other], "c", False) is None
    assert B.grounded_sibling([chosen, _row("s", _done("grounded"), partial=False)], "c", True) is None   # 지금 넘기는 일부 답 값과 달라 쓰지 않는다
    assert B.grounded_sibling([_row("c", _done("ungrounded"), partial=True), _row("s", _done("grounded"), partial=True)], "c", True) is not None
    assert B.grounded_sibling([ok], "c", False) is None                # 고른 답이 미리 부른 판정을 쓰지 않았다(문맥을 모른다)
    assert B.grounded_sibling([{"kind": "chosen", "key": "c", "partial": False}, ok], "c", False) is None


def test_grounded_sibling_survives_a_broken_record():
    class Broken:
        def cancelled(self):
            raise RuntimeError("broken")

    assert B.grounded_sibling([_row("c", _done("ungrounded")), _row("s", Broken())], "c", False) is None


# ---------- 기록: 답 다시 쓰기 결과 ----------
def test_path_keeps_the_redraft_record_without_the_answer_text():
    dropped = [{"chunk_id": "b" * 16, "quote": "모델이 낸 구절"}, "자유 글", {"chunk_id": 3}, None]   # 모델이 낸 인용 값 그대로
    redraft = {"result": "rejudge_grounded", "answer": "다시 쓴 답 본문", "partial_note": "dropped_facts_cited", "carried": ["a" * 16], "dropped": dropped}
    state = {"chunks": [{"chunk_id": "a" * 16}], "grounding": {"llm": "ungrounded", "redrafted": True, "redraft": redraft,
                                                               "switch_failed": "refused_after_switch"}}
    g = step_cost.path_meta(state)["path"]["grounding"]
    assert g["redraft"] == {"result": "rejudge_grounded", "partial_note": "dropped_facts_cited", "carried": ["a" * 16], "dropped": ["b" * 16]}
    assert "answer" not in g["redraft"] and g["switch_failed"] == "refused_after_switch"
    plain = step_cost.path_meta({"chunks": [{"chunk_id": "a" * 16}], "grounding": {"llm": "grounded"}})["path"]["grounding"]
    assert plain == {"llm": "grounded"}                                # 다시 쓰지 않은 행의 모양은 그대로


def test_redraft_row_in_a_graph_run_reaches_the_path(monkeypatch):
    out, _ = _scenario()
    path = step_cost.path_meta(out)["path"]["grounding"]
    assert path["redraft"]["result"] == "rejudge_grounded" and "answer" not in path["redraft"]
