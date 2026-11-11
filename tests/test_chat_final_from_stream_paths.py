"""`CHAT_FINAL_FROM_STREAM`(사전 등록 62.16, 켜면 `/chat`이 끝난 뒤 체크포인트를 다시 읽지 않고 스트림이 모은 값을 씀)의 남은 두 길 시험.

62.16은 일반 정책 답, 거절, 되묻기, 범위 밖 네 길만 시험했다(tests/test_speed_p95_code.py). 켜기 전에 아래를 더 확인한다(F3 15장, 사전 등록 62.40의 선행 조건).
- 결정표 길: 승인된 결정표로 끝나는 답과 승인된 결정표가 없어 거절하는 길. `done`의 kind·as_of·answer_id·인용과 대화 목록의 마지막 답이 꺼짐과 같고, 최종 상태 재조회가 없다.
- 합동 검토 길: `/chat`은 쟁점표 승인 대기에서 `approval_request`로 끝난다(done 없음). 켜도 같은 이벤트·같은 대화 상태이고, 승인 뒤 재개는 `/chat`을 지나지 않는다
  (`/approvals`가 그래프에 `Command(resume=...)`를 보내고 이어 읽는 값은 체크포인트다). 재개를 `stream_events`로 보내도 스트림 값이 체크포인트 값과 같은지 본다.
가짜 모델·메모리 저장소만 쓴다(키·네트워크·DB 없음).
"""
from __future__ import annotations

import pytest
from api_test_support import Env, ask
from fake_search import fake_search
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from qgraph_fakes import j
from team_review_fakes import REQUEST, Retriever, review_llm
from test_multi_graph import APPROVE, Q_AMOUNT, RV_CFG, _decision_llm, _decision_repo, _no_wait  # noqa: F401  (_no_wait는 fixture)
from test_speed_p95_code import E_KEYS, CountingGraph, _stable

from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.build import build_graph
from backend.graph.departments.review import build_review_graph
from backend.graph.departments.store import InMemoryIssueTableStore
from backend.graph.multi import build_multi_graph
from backend.graph.stream import stream_events

AS_OF = "2026-11-05"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("CHAT_FINAL_FROM_STREAM", raising=False)
    monkeypatch.delenv("USE_SKILLS", raising=False)


def same_but_as_of(vals: dict, state: dict) -> None:
    """`/chat`이 쓰는 칸을 비교한다. 인용은 없음(None)과 빈 목록이 같은 뜻이다(`/chat`은 `or []`로 읽는다)."""
    for key in (k for k in E_KEYS if k != "as_of"):
        a, b = vals.get(key), state.get(key)
        assert (a or []) == (b or []) if key == "citations" else a == b, key


def _decision_graph(approved: bool):
    llm = _decision_llm()
    return build_multi_graph(fake_search, InMemorySaver(), llm=llm, decision_repo=_decision_repo(approved=approved), answer_store=InMemoryAnswerStore())


def _review_graph():
    llm = review_llm(classify=j(route="review"))
    sub = build_review_graph(Retriever(), None, llm=llm, store=InMemoryIssueTableStore())
    return build_multi_graph(fake_search, InMemorySaver(), llm=llm, review_graph=sub), llm


def _chat(monkeypatch, make_graph, message, *, on):
    if on:
        monkeypatch.setenv("CHAT_FINAL_FROM_STREAM", "1")
    with Env(monkeypatch) as env:
        counting = CountingGraph(make_graph())
        env.app.state.question_graph = counting
        c = env.client(env.alice)
        r, ev = ask(c, message, "t1", as_of=AS_OF)
        assert r.status_code == 200, r.text
        return ev, counting.get_state_calls, c.get("/threads/t1").json()


# ============================ 결정표 길 ============================

@pytest.mark.parametrize("approved", [True, False], ids=["approved_table_answers", "no_approved_table_refuses"])
def test_decision_route_done_and_thread_are_the_same_with_the_switch_and_the_final_state_is_not_reread(monkeypatch, approved):
    off_ev, off_calls, off_rec = _chat(monkeypatch, lambda: _decision_graph(approved), Q_AMOUNT, on=False)
    on_ev, on_calls, on_rec = _chat(monkeypatch, lambda: _decision_graph(approved), Q_AMOUNT, on=True)
    assert off_calls == 1 and on_calls == 0
    last = on_ev[-1][1]["data"]
    assert on_ev[-1][0] == "done" and last["kind"] == ("answer" if approved else "refuse")
    if approved:
        assert "Director → PAO or VP Finance" in "".join(d["data"]["text"] for n, d in on_ev if n == "token") and last["attribution"]
    else:
        assert last["code"] == "no_results" and "승인된 결정표가 0개" in "".join(d["data"]["text"] for n, d in on_ev if n == "token")
    assert [n for n, _ in on_ev] == [n for n, _ in off_ev] and _stable(off_ev) == _stable(on_ev)   # 이벤트 종류·순서·내용(answer_id 제외)이 같다
    assert {k: on_rec["last"][k] for k in ("kind", "answer", "as_of")} == {k: off_rec["last"][k] for k in ("kind", "answer", "as_of")}
    assert on_rec["status"] == off_rec["status"] == "idle" and on_rec["last"]["answer_id"] == last["answer_id"]
    assert off_rec["last"]["answer_id"] == off_ev[-1][1]["data"]["answer_id"]
    assert [d["data"].get("chunk_id") for n, d in on_ev if n == "citation"] == [d["data"].get("chunk_id") for n, d in off_ev if n == "citation"]


@pytest.mark.parametrize("approved", [True, False], ids=["approved", "unapproved"])
def test_decision_route_stream_values_equal_the_checkpoint_values(approved):
    g = _decision_graph(approved)
    vals: dict = {}
    events = list(stream_events(g, {"question": Q_AMOUNT, "user_id": "u1", "thread_id": "dt", "as_of": AS_OF}, thread_id="dt", values_out=vals))
    state = dict(g.get_state({"configurable": {"thread_id": "dt"}}).values)
    assert events[-1].type == "done" and vals["kind"] == ("answer" if approved else "refuse")
    for key in E_KEYS:
        assert vals.get(key) == state.get(key), key
    assert vals["answer"] == state["answer"]


# ============================ 합동 검토 길 ============================

def test_review_route_stops_at_approval_with_the_same_events_and_thread_state_and_never_rereads_the_state(monkeypatch):
    off_ev, off_calls, off_rec = _chat(monkeypatch, lambda: _review_graph()[0], REQUEST, on=False)
    on_ev, on_calls, on_rec = _chat(monkeypatch, lambda: _review_graph()[0], REQUEST, on=True)
    assert off_calls == on_calls == 0                     # 승인 대기에서 끝나 done이 없으므로 켜도 꺼도 최종 상태를 읽지 않는다
    assert on_ev[-1][0] == "approval_request" and "done" not in [n for n, _ in on_ev]
    strip = lambda ev: [(n, {k: v for k, v in d["data"].items() if k != "approval_id"}) for n, d in ev]   # 승인 번호는 사용자·대화에서 정해져 앱마다 다르다
    assert strip(off_ev) == strip(on_ev)
    assert on_ev[-1][1]["data"]["kind"] == "issue_table" and on_ev[-1][1]["data"]["code"] == "approval_pending"
    assert on_rec["status"] == off_rec["status"] and on_rec.get("last") == off_rec.get("last")   # 시험 그래프는 승인함이 없어 상세 조회가 idle로 맞추지만 켜고 꺼도 같다


def test_review_resume_stream_values_equal_the_checkpoint_values_after_approval(_no_wait):
    """재개를 `stream_events`로 보냈을 때도 스트림이 모은 값이 체크포인트의 최종 값과 같다(켜진 `/chat`이 쓰는 칸)."""
    g, _ = _review_graph()
    first = list(stream_events(g, {"question": REQUEST, "user_id": "u1", "thread_id": "rv", "as_of": AS_OF}, thread_id="rv"))
    assert first[-1].type == "approval_request"
    vals: dict = {}
    events = list(stream_events(g, Command(resume=APPROVE), thread_id="rv", values_out=vals))
    state = dict(g.get_state(RV_CFG).values)
    assert events[-1].type == "done" and state["review_status"] == "approved" and state["kind"] == "answer"
    same_but_as_of(vals, state)   # as_of는 아래 시험이 알려진 한계로 고정한다(재개 스트림에는 인터럽트 앞 노드의 칸이 없다)
    assert vals["answer"] == state["answer"] and vals.get("review_status") == "approved"


def test_only_a_resumed_stream_loses_as_of_and_chat_never_streams_a_resume():
    """알려진 한계를 고정한다: 재개 실행의 스트림에는 인터럽트 앞 노드가 쓴 칸(`as_of`)이 없다. 그래서 재개를 스트림으로 보내는 길이 생기면
    `CHAT_FINAL_FROM_STREAM`의 `as_of`가 비게 된다. 지금은 그런 길이 없다: `/chat`은 입력 dict만 그래프에 보내고(`Command`는 `/approvals`가 `invoke`로 보낸다),
    승인 뒤 마지막 답은 `_settle`이 체크포인터(`get_state`)에서 읽는다(스위치와 무관)."""
    import inspect

    from backend.api import routes

    src = inspect.getsource(routes.create_api_router)
    assert "Command" not in src and "resume" not in src and "graph_input = {" in src
    assert "_final_values(graph, internal)" in inspect.getsource(routes._settle)   # 승인 뒤 상태는 스위치와 관계없이 체크포인트에서 읽는다
    g, _ = _review_graph()
    list(stream_events(g, {"question": REQUEST, "user_id": "u1", "thread_id": "rv", "as_of": AS_OF}, thread_id="rv"))
    vals: dict = {}
    list(stream_events(g, Command(resume=APPROVE), thread_id="rv", values_out=vals))
    assert vals.get("as_of") is None and g.get_state(RV_CFG).values["as_of"] == AS_OF


def test_review_rejection_and_clarify_stream_values_equal_the_checkpoint_values(_no_wait):
    g, _ = _review_graph()
    list(stream_events(g, {"question": REQUEST, "user_id": "u1", "thread_id": "rv", "as_of": AS_OF}, thread_id="rv"))
    vals: dict = {}
    events = list(stream_events(g, Command(resume={"approve": False, "comment": "사유", "decided_by": "admin-1"}), thread_id="rv", values_out=vals))
    state = dict(g.get_state(RV_CFG).values)
    assert events[-1].type == "done" and state["review_status"] == "rejected"
    same_but_as_of(vals, state)
    # 되묻기(빠진 값): 승인 없이 한 번에 끝난다
    llm = review_llm(classify=j(route="review"), supervisor=j(missing=["금액"], tasks={}))
    sub = build_review_graph(Retriever(), None, llm=llm, store=InMemoryIssueTableStore())
    g2 = build_multi_graph(fake_search, InMemorySaver(), llm=llm, review_graph=sub)
    vals2: dict = {}
    events2 = list(stream_events(g2, {"question": REQUEST, "user_id": "u1", "thread_id": "rc", "as_of": AS_OF}, thread_id="rc", values_out=vals2))
    state2 = dict(g2.get_state({"configurable": {"thread_id": "rc"}}).values)
    assert events2[-1].type == "done" and state2["kind"] == "clarify"
    for key in E_KEYS:
        assert vals2.get(key) == state2.get(key), key
    assert vals2["answer"] == state2["answer"]


def test_review_clarify_through_chat_has_the_same_done_with_the_switch(monkeypatch, _no_wait):
    def make():
        llm = review_llm(classify=j(route="review"), supervisor=j(missing=["금액"], tasks={}))
        sub = build_review_graph(Retriever(), None, llm=llm, store=InMemoryIssueTableStore())
        return build_multi_graph(fake_search, InMemorySaver(), llm=llm, review_graph=sub)

    off_ev, off_calls, off_rec = _chat(monkeypatch, make, REQUEST, on=False)
    on_ev, on_calls, on_rec = _chat(monkeypatch, make, REQUEST, on=True)
    assert off_calls == 1 and on_calls == 0
    assert on_ev[-1][1]["data"]["kind"] == "clarify" and on_ev[-1][1]["data"]["refuse_stage"] == "review"
    assert _stable(off_ev) == _stable(on_ev) and {k: on_rec["last"][k] for k in ("kind", "answer", "as_of")} == {k: off_rec["last"][k] for k in ("kind", "answer", "as_of")}
