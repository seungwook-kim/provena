"""MCP 읽기 전용 도구 get_agent_trace 시험 (docs/specs/mcp.md get_agent_trace 절).

실제 그래프(질문 그래프 + 합동 검토 하위 그래프, 합동 검토 그래프 단독, 멀티 에이전트 그래프)를 가짜 모델·가짜 검색기·메모리 체크포인터로 돌리고,
그 체크포인터를 도구에 넣어 읽는다(키·네트워크·DB 없음). 내보내는 칸이 화이트리스트뿐인지, 비용을 지어내지 않는지 본다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastmcp")
from fake_search import fake_search  # noqa: E402
from fastmcp import Client, FastMCP  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from qgraph_fakes import j, normal_llm  # noqa: E402
from team_review_fakes import REQUEST, Retriever, review_llm  # noqa: E402

from backend.graph.build import build_graph  # noqa: E402
from backend.graph.decision.repo import InMemoryDecisionRepo  # noqa: E402
from backend.graph.departments.review import build_review_graph  # noqa: E402
from backend.graph.multi import build_multi_graph  # noqa: E402
from extras.mcp_skill.mcp_server import server, trace_tool  # noqa: E402

USER = "u-secret-7f3a"                  # user_id. 출력에 나오면 안 된다
ADMIN = "admin-person-91c2"             # 사람 결정의 decided_by
COMMENT = "비밀 사유: 예산 검토 끝남"      # 사람 결정의 comment
ISSUE = "제3자 위험 검토를 받아야 한다."   # 보안 팀 쟁점 문장(team_review_fakes)
RESULT_KEYS = {"thread_id", "run_started_at", "last_checkpoint_at", "elapsed_ms", "runs_in_thread", "complete", "route", "agent_trace",
               "supervisor_log", "review", "waiting_approval", "stopped_on_error", "steps", "cost_usd"}
REVIEW_KEYS = {"review_status", "waiting_approval", "teams", "failed_teams"}
STEP_KEYS = {"graph", "step", "nodes", "at", "duration_ms", "includes_human_wait"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


def cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def start(g, thread: str, question: str = REQUEST):
    return g.invoke({"question": question, "user_id": USER, "thread_id": thread, "as_of": "2026-11-05"}, cfg(thread))


def question_graph_with_review(saver):
    llm = review_llm(classify=j(route="review"))
    sub = build_review_graph(Retriever(), None, llm=llm, approvals=InMemoryDecisionRepo())
    return build_graph(Retriever(), saver, llm=llm, review_graph=sub, decompose=False)


def make(saver) -> FastMCP:
    mcp = FastMCP("t")
    trace_tool.register(mcp, saver=saver)
    return mcp


def call(mcp, args: dict) -> dict:
    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool("get_agent_trace", args, raise_on_error=False)).structured_content
    return asyncio.run(go())


def trace(saver, thread: str) -> dict:
    r = call(make(saver), {"thread_id": thread})
    assert r["status"] == "ok", r
    return r


def nodes(result: dict, graph: str | None = None) -> list[str]:
    return [n for s in result["steps"] if graph in (None, s["graph"]) for n in s["nodes"]]


def no_content(r: dict) -> None:
    text = json.dumps(r, ensure_ascii=False)
    for secret in (USER, ADMIN, COMMENT, ISSUE, REQUEST, "chunk_id", "decided_by", "comment", "rows", "reason", "question"):
        assert secret not in text, secret


# ---------- 질문 그래프 아래 합동 검토(하위 그래프 ns "review:...") ----------

def test_review_as_subgraph_waiting_for_approval():
    saver = InMemorySaver()
    g = question_graph_with_review(saver)
    start(g, "q1")
    r = trace(saver, "q1")
    (res,) = r["results"]
    assert set(res) == RESULT_KEYS and set(res["review"]) == REVIEW_KEYS and all(set(s) == STEP_KEYS for s in res["steps"])
    assert res["route"] == "review" and res["runs_in_thread"] == 1 and res["complete"] is True
    assert res["waiting_approval"] is True and res["review"]["waiting_approval"] is True
    assert res["review"]["review_status"] == "pending_approval" and res["review"]["failed_teams"] == []
    assert res["review"]["teams"] == [{"team": t, "status": "reviewed", "attempts": 1} for t in ("finance", "infra", "itops", "security")]
    assert nodes(res, "main") == ["load_memory", "classify"]
    assert nodes(res, "review") == ["supervisor", "team_finance", "team_infra", "team_itops", "team_security", "check_teams", "merge", "queue_approval"]
    assert [s["at"] for s in res["steps"]] == sorted(s["at"] for s in res["steps"])
    assert all(isinstance(s["duration_ms"], int) and s["duration_ms"] >= 0 for s in res["steps"])
    assert r["source"] == "checkpoints" and r["as_of"] == res["last_checkpoint_at"]
    no_content(r)


def test_after_approval_status_and_human_wait_is_flagged():
    saver = InMemorySaver()
    g = question_graph_with_review(saver)
    start(g, "q1")
    g.invoke(Command(resume={"approve": True, "comment": COMMENT, "decided_by": ADMIN}), cfg("q1"))
    r = trace(saver, "q1")
    (res,) = r["results"]
    assert res["review"]["review_status"] == "approved" and res["waiting_approval"] is False and res["review"]["waiting_approval"] is False
    waited = [s for s in res["steps"] if s["includes_human_wait"]]
    assert {n for s in waited for n in s["nodes"]} == {"approval", "review"}   # 하위 그래프의 승인 노드, 바깥 그래프의 review 노드
    no_content(r)


# ---------- 합동 검토 그래프 단독(routes.py review_graph 모양, ns "") ----------

def test_standalone_review_team_failure_waits_with_failed_team():
    saver = InMemorySaver()
    g = build_review_graph(Retriever(), saver, llm=review_llm(team_security="not json"), approvals=InMemoryDecisionRepo())
    start(g, "f1")
    r = trace(saver, "f1")
    (res,) = r["results"]
    rv = res["review"]
    assert rv["review_status"] == "team_review_failed" and rv["waiting_approval"] is True and rv["failed_teams"] == ["security"]
    assert {"team": "security", "status": "not_reviewed", "attempts": 3} in rv["teams"]
    assert res["route"] is None and nodes(res)[-1] == "queue_team_failure"
    assert "모델 응답을 읽지 못했습니다" not in json.dumps(r, ensure_ascii=False)       # 팀 실패 이유 글은 내보내지 않는다
    no_content(r)


def test_only_the_last_run_of_a_thread_is_shown():
    saver = InMemorySaver()
    g = build_review_graph(Retriever(), saver, llm=review_llm(), approvals=InMemoryDecisionRepo())
    start(g, "t1")
    g.invoke(Command(resume={"approve": True, "comment": COMMENT, "decided_by": ADMIN}), cfg("t1"))
    start(g, "t1", REQUEST + " 두 번째")
    (res,) = trace(saver, "t1")["results"]
    assert res["runs_in_thread"] == 2 and nodes(res).count("supervisor") == 1 and res["review"]["review_status"] == "pending_approval"


# ---------- 멀티 에이전트 그래프(Supervisor와 에이전트 단위 단계) ----------

def test_multi_graph_supervisor_decisions_and_agents():
    saver = InMemorySaver()
    g = build_multi_graph(fake_search, saver, llm=normal_llm())
    g.invoke({"question": "SEV2 최초 대응 시간은?", "user_id": USER, "thread_id": "m1", "as_of": "2026-11-05"}, cfg("m1"))
    r = trace(saver, "m1")
    (res,) = r["results"]
    assert res["agent_trace"] == ["retriever", "writer", "verifier"]
    assert [(e["after"], e["to"]) for e in res["supervisor_log"]] == [("intake", "retriever"), ("retriever", "writer"),
                                                                       ("writer", "verifier"), ("verifier", "end")]
    # 하위 에이전트는 체크포인트를 끝날 때만 남긴다(`durability="exit"`). 그래서 단계는 바깥 그래프의 에이전트 단위로만 보이고 에이전트 안의 노드 단계는 없다
    assert nodes(res, "main") == ["supervisor", "retriever", "supervisor", "writer", "supervisor", "verifier", "supervisor"]
    assert {s["graph"] for s in res["steps"]} == {"main"} and res["review"] is None
    out = g.get_state(cfg("m1")).values
    text = json.dumps(r, ensure_ascii=False)
    assert out["answer"] not in text and "SEV2" not in text and USER not in text


# ---------- 비용 ----------

def test_cost_is_null_not_zero_and_the_note_says_why():
    saver = InMemorySaver()
    start(question_graph_with_review(saver), "q1")
    r = trace(saver, "q1")
    assert r["results"][0]["cost_usd"] is None and "비용 기록 없음" in r["note"] and "ts" in r["note"]


# ---------- 상태 ----------

def test_unknown_thread_is_not_found():
    r = call(make(InMemorySaver()), {"thread_id": "nope"})
    assert r["status"] == "not_found" and r["results"] == []


@pytest.mark.parametrize("thread_id", ["", "   ", "x" * 201, "a\nb", "t\x00"])
def test_bad_thread_id_is_invalid(thread_id):
    class Never:
        def list(self, *a, **k):
            raise AssertionError("체크포인터를 부르면 안 된다")

    r = call(make(Never()), {"thread_id": thread_id})
    assert r["status"] == "invalid" and r["retryable"] is False


def test_no_saver_and_no_database_url_is_not_ready(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(server, "_pg", None)
    r = call(make(None), {"thread_id": "q1"})
    assert r["status"] == "not_ready" and "DATABASE_URL" in r["note"]


class Failing:
    def __init__(self, exc):
        self.exc = exc

    def list(self, *a, **k):
        raise self.exc


def test_db_failure_is_unavailable_without_detail():
    import psycopg
    secret = "postgresql://app:pw@db.internal:5432/app"
    r = call(make(Failing(psycopg.OperationalError(f"connection to {secret} failed"))), {"thread_id": "q1"})
    assert r["status"] == "unavailable" and r["retryable"] is True and secret not in json.dumps(r)


def test_missing_checkpoint_tables_is_not_ready_and_other_errors_are_error():
    from psycopg.errors import UndefinedTable
    assert call(make(Failing(UndefinedTable('relation "checkpoints" does not exist'))), {"thread_id": "q1"})["status"] == "not_ready"
    r = call(make(Failing(KeyError("channel_values"))), {"thread_id": "q1"})
    assert r["status"] == "error" and r["retryable"] is False and "channel_values" not in json.dumps(r)


def test_too_many_checkpoints_reads_the_newest_and_says_so(monkeypatch):
    saver = InMemorySaver()
    start(question_graph_with_review(saver), "q1")
    monkeypatch.setattr(trace_tool, "MAX_CHECKPOINTS", 3)
    r = trace(saver, "q1")
    assert r["results"][0]["complete"] is False and "잘려" in r["note"]


def test_reads_only(monkeypatch):
    """체크포인터에 쓰지 않는다: put·put_writes·delete를 부르면 실패."""
    saver = InMemorySaver()
    start(question_graph_with_review(saver), "q1")
    before = json.dumps(sorted(str(t.checkpoint["id"]) for t in saver.list(cfg("q1"))))
    for name in ("put", "put_writes", "delete_thread", "setup"):
        monkeypatch.setattr(saver, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)), raising=False)
    trace(saver, "q1")
    assert json.dumps(sorted(str(t.checkpoint["id"]) for t in saver.list(cfg("q1")))) == before
