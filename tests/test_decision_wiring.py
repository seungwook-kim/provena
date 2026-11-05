"""질문 그래프의 결정표 경로, 승인 요청 이벤트, 앱 등록 시험. d5_patch_approval.diff를 적용한 뒤에만 돈다. 적용 전에는 건너뛴다."""
from __future__ import annotations

import inspect
import secrets

import pytest
from auth_test_support import create_test_auth_router
from decision_fixtures import EXPENSE_CELLS, FakeLLM, draft_json
from fake_search import fake_search
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from qgraph_fakes import ScriptedLLM, j

from backend.graph.build import build_graph
from backend.graph.decision import rules as R
from backend.graph.decision.convert import build_convert_graph
from backend.graph.decision.repo import InMemoryDecisionRepo
from backend.graph.stream import stream_events
from backend.main import create_app
from backend.schemas import DecisionTable

pytestmark = pytest.mark.skipif("decision_repo" not in inspect.signature(build_graph).parameters,
                                reason="build.py에 결정표 연결 패치가 아직 적용되지 않음")

Q = "외부 SaaS 3만 달러 도입, 승인 단계가 정책과 맞나?"


def repo_with(status="approved"):
    repo = InMemoryDecisionRepo()
    t = DecisionTable(table_id="dt1", rule_seq=1, version_id="0a3de83375ab", cells=R.rules_from_cells(EXPENSE_CELLS), status="draft")
    rec = repo.queue_draft("t", t, "s")
    if status == "approved":
        repo.decide(rec.approval_id, True, "admin-1")
    return repo


def run(repo, params):
    llm = ScriptedLLM({"classify": j(route="decision"), "decision_params": j(**params)})
    g = build_graph(fake_search, InMemorySaver(), llm=llm, decision_repo=repo)
    out = g.invoke({"question": Q, "user_id": "u1", "thread_id": "t1"}, {"configurable": {"thread_id": "t1"}})
    return out, llm


def test_approved_table_answers_without_search_or_answer_llm():
    out, llm = run(repo_with(), {"task_type": "Approving expense", "amount_usd": 30000, "band": None})
    assert out["kind"] == "answer" and "Director → PAO or VP Finance" in out["answer"]
    assert llm.count("rewrite") == 0 and llm.count("answer") == 0       # 검색·답 작성 LLM을 거치지 않는다
    assert "$25K" not in out["answer"] and "$25,000 초과 $50,000 이하" in out["answer"]   # 답 본문은 정확한 금액 표기만
    assert out["citations"][0]["article"] == "Approving expense / >$25K up to $50K"        # 원문 표기는 근거 인용 칸에


def test_unapproved_table_is_refused_with_reason():
    out, _ = run(repo_with("draft"), {"task_type": "Approving expense", "amount_usd": 30000, "band": None})
    assert out["kind"] == "refuse" and "승인된 결정표가 0개" in out["answer"]


def test_missing_amount_is_refused():
    out, _ = run(repo_with(), {"task_type": "Approving expense", "amount_usd": None, "band": None})
    assert out["kind"] == "refuse"


# --- 승인 요청 이벤트와 앱 등록 ------------------------------------------------------------------

def _app(monkeypatch, **env):
    for key in ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE", "CHECKPOINTER", "MCP_TOKEN", "SEARCH_WARMUP"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("backend.main.create_auth_router", create_test_auth_router)
    return create_app()


def test_approval_request_event_has_only_the_sdd_keys():
    repo, llm = InMemoryDecisionRepo(), FakeLLM(draft_json(R.rules_from_cells(EXPENSE_CELLS)))
    graph = build_convert_graph(llm, repo, InMemorySaver())
    start = {"category": "Approving expense", "rule_seq": 1, "version_id": "v", "source_cells": EXPENSE_CELLS, "requested_by": "a"}
    events = list(stream_events(graph, start, thread_id="t"))
    assert [e.type for e in events] == ["approval_request"]
    pending = repo.list_pending()[0]
    assert events[0].data == {"approval_id": pending.approval_id, "kind": "decision_table", "summary": pending.summary}


def test_app_registers_routes_only_with_database_url(monkeypatch):
    paths = set(_app(monkeypatch).openapi()["paths"])
    assert "/approvals" not in paths
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x", AUTH_SECRET=secrets.token_urlsafe(32))
    assert {"/decision-tables", "/decision-tables/convert", "/decision-tables/{table_id}/run", "/decision-tables/run",
            "/approvals", "/approvals/{approval_id}"} <= set(app.openapi()["paths"])


def test_lifespan_opens_and_closes_the_runtime(monkeypatch):
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x", AUTH_SECRET=secrets.token_urlsafe(32), CHECKPOINTER="memory")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert isinstance(app.state.decision_repo, InMemoryDecisionRepo) and app.state.decision_graph is not None
        assert app.state.review_graph is not None
    assert app.state.decision_repo is None and app.state.decision_graph is None and app.state.review_graph is None


def test_database_failure_at_startup_keeps_health_and_does_not_fall_back_to_memory(monkeypatch):
    app = _app(monkeypatch, DATABASE_URL="postgresql://u:p@127.0.0.1:1/x", AUTH_SECRET=secrets.token_urlsafe(32))

    def refuse(*_a, **_k):
        raise RuntimeError("연결 실패")

    monkeypatch.setattr("backend.graph.decision.routes.open_persistence", refuse)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert getattr(app.state, "decision_repo", None) is None
