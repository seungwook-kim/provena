"""쟁점표 승인이 승인함과 같은 경로로 도는지 (docs/specs/team-review.md AC-01~06, `backend/graph/decision/routes.py`).

가짜 모델, 가짜 검색기, 메모리 저장소로 돈다(키·네트워크·DB 없음). 실제 라우터와 그래프를 지나고, 로그인은 가짜 폐기 저장소를 쓴다.
Postgres 구현은 `PostgresDecisionRepo`의 문장 순서만 가짜 풀로 본다. 실제 Postgres에서는 `tests/test_decision_approval.py`의 `test_postgres_*`가 돈다.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import pytest
from auth_test_support import MemoryRevocationStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from qgraph_fakes import j
from team_review_fakes import REQUEST, Retriever, review_llm

from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, create_access_token
from backend.graph.decision import routes as Routes
from backend.graph.decision.repo import (
    ISSUE_KIND,
    KIND,
    SUPERSEDED_COMMENT,
    TEAM_FAILED_KIND,
    ApprovalRecord,
    InMemoryDecisionRepo,
    PostgresDecisionRepo,
    team_resolution,
)
from backend.graph.decision.rules import AlreadyDecided, DecisionError
from backend.graph.decision.routes import create_decision_router, open_decision_runtime
from backend.graph.departments.review import TEAM_ATTEMPTS, build_review_graph
from backend.graph.departments.store import InMemoryIssueTableStore, PgIssueTableStore

ROOT = Path(__file__).resolve().parents[1]
CSRF = "csrf-token-for-test"
DB_ERROR = "connection failed postgresql://user:secret-password@db/x"


class FakeAuthStore:
    def __init__(self, *users):
        self.users = {str(u.user_id): u for u in users}

    def get_by_login_id(self, login_id):
        return None

    def get_by_user_id(self, user_id):
        return self.users.get(str(user_id))


class FailingOnce:
    """처음 `times`번은 지정한 메서드에서 DB 오류를 내는 저장소 껍데기. 나머지는 진짜 저장소가 한다."""

    def __init__(self, inner, method: str, times: int = 1):
        self.inner, self.method, self.left = inner, method, times

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if name != self.method:
            return attr

        def call(*a, **k):
            if self.left > 0:
                self.left -= 1
                raise RuntimeError(DB_ERROR)
            return attr(*a, **k)

        return call


class Parent(TypedDict, total=False):
    question: str
    user_id: str
    thread_id: str
    as_of: str
    kind: str
    answer: str
    review_status: str


class Ctx:
    def __init__(self, *, wrap_store=None, wrap_repo=None, subgraph: bool = False, llm=None, saver=None, repo=None, store=None):
        self.secret = secrets.token_urlsafe(32)
        self.admin = AuthUser(user_id=uuid4(), login_id="admin", password_hash="x", role="admin")
        self.user = AuthUser(user_id=uuid4(), login_id="user", password_hash="x", role="user")
        self.repo = repo if repo is not None else InMemoryDecisionRepo()
        self.store = store if store is not None else InMemoryIssueTableStore()
        self.llm = llm or review_llm()
        self.retriever = Retriever()
        self.saver = saver or InMemorySaver()
        graph_store = wrap_store(self.store) if wrap_store else self.store
        graph_repo = wrap_repo(self.repo) if wrap_repo else self.repo
        if subgraph:                 # 질문 그래프 아래에 붙인 모양: 재개는 바깥 그래프로 한다
            sub = build_review_graph(self.retriever, None, llm=self.llm, store=graph_store, approvals=graph_repo)
            p = StateGraph(Parent)
            p.add_node("review", sub)
            p.add_edge(START, "review")
            p.add_edge("review", END)
            self.graph = p.compile(checkpointer=self.saver)
        else:
            self.graph = build_review_graph(self.retriever, self.saver, llm=self.llm, store=graph_store, approvals=graph_repo)
        self.app = FastAPI()
        self.app.state.token_revocation_store = MemoryRevocationStore()
        self.app.state.decision_repo = self.repo
        self.app.state.decision_graph = object()          # 이 시험의 승인 건에는 쓰이지 않는다. 쓰이면 오류가 난다
        self.app.state.review_graph = self.graph
        self.app.include_router(create_decision_router(store=FakeAuthStore(self.admin, self.user), secret=self.secret))

    def client(self, who: AuthUser | None = None, csrf: bool = True) -> TestClient:
        c = TestClient(self.app)
        if who is not None:
            c.cookies.set(AUTH_COOKIE_NAME, create_access_token(who.user_id, who.role, secret=self.secret))
        if csrf:
            c.cookies.set(CSRF_COOKIE_NAME, CSRF)
            c.headers["X-CSRF-Token"] = CSRF
        return c

    def start(self, thread: str = "t1", question: str = REQUEST, as_of: str = "2026-11-05"):
        return self.graph.invoke({"question": question, "user_id": "u1", "thread_id": thread, "as_of": as_of}, {"configurable": {"thread_id": thread}})

    def pending_id(self, thread: str = "t1") -> str:
        return self.start(thread)["__interrupt__"][0].value["approval_id"]

    def post(self, approval_id: str, **body):
        return self.client(self.admin).post(f"/approvals/{approval_id}", json=body)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --- AC-01 승인함에 올라온다 -----------------------------------------------------------------------

def test_ac01_issue_table_shows_up_in_the_inbox_with_its_body(ctx):
    v = ctx.start()["__interrupt__"][0].value
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["approval_id"] == v["approval_id"] and item["kind"] == "issue_table" and item["summary"] == v["summary"]
    assert item["created_at"] and item["save_failed"] is False and item["draft"] is None
    assert item["issue_table"]["rows"] == v["table"]["rows"] and len(item["issue_table"]["rows"]) == 4
    rec = ctx.repo.get_approval(v["approval_id"])
    assert rec.kind == ISSUE_KIND and rec.status == "pending" and rec.thread_id == "t1"


def test_ac02_nothing_is_saved_while_it_waits_in_the_inbox(ctx):
    ctx.start()
    assert ctx.client(ctx.admin).get("/approvals").json() and ctx.store.tables == {} and ctx.store.rejections == {}


def test_ac05_no_issues_does_not_reach_the_inbox():
    ctx = Ctx(llm=review_llm(team_security=j(issues=[]), team_infra=j(issues=[]), team_itops=j(issues=[]), team_finance=j(issues=[])))
    assert ctx.start()["review_status"] == "no_issues"
    assert ctx.client(ctx.admin).get("/approvals").json() == []


def test_team_marked_unreviewed_reaches_the_issue_table_with_its_reason():
    ctx = Ctx(llm=review_llm(team_infra="이건 JSON이 아님"))
    aid = ctx.pending_id()
    assert ctx.post(aid, action="mark_unreviewed", comment="이번엔 넘어간다").status_code == 200
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["kind"] == "issue_table" and [u["team"] for u in item["issue_table"]["unreviewed"]] == ["infra"] and "검토하지 못한 팀" in item["summary"]


# --- 승인·반려가 같은 경로로 재개된다 --------------------------------------------------------------

def test_approve_resumes_and_saves(ctx):
    aid = ctx.pending_id()
    r = ctx.post(aid, approve=True, comment="확인함", decided_by="attacker")
    assert r.status_code == 200
    body = r.json()
    (saved,) = ctx.store.tables.values()
    assert body["status"] == "approved" and body["kind"] == "issue_table" and body["table_id"] == saved["table_id"]
    assert body["decided_by"] == str(ctx.admin.user_id) and saved["approved_by"] == str(ctx.admin.user_id)   # 본문의 값은 읽지 않는다
    assert ctx.client(ctx.admin).get("/approvals").json() == []
    assert ctx.repo.get_approval(aid).target_id == saved["table_id"]


def test_ac04_reject_resumes_and_records_reason_without_saving(ctx):
    aid = ctx.pending_id()
    r = ctx.post(aid, approve=False, comment="근거가 부족함")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["table_id"] is None
    assert ctx.store.tables == {} and ctx.store.rejections[aid]["reason"] == "근거가 부족함"
    assert ctx.repo.get_approval(aid).comment == "근거가 부족함"


def test_ac06_only_admin_with_csrf_and_nothing_resumes(ctx):
    aid = ctx.pending_id()
    assert ctx.client(None).post(f"/approvals/{aid}", json={"approve": True}).status_code == 401
    assert ctx.client(ctx.user).post(f"/approvals/{aid}", json={"approve": True}).status_code == 403
    assert ctx.client(ctx.user).get("/approvals").status_code == 403
    assert ctx.client(ctx.admin, csrf=False).post(f"/approvals/{aid}", json={"approve": True}).status_code == 403
    assert ctx.store.tables == {} and ctx.repo.get_approval(aid).status == "pending"


def test_repeat_and_flip_after_decision(ctx):
    aid = ctx.pending_id()
    first = ctx.post(aid, approve=True)
    assert ctx.post(aid, approve=True).json() == first.json() and len(ctx.store.tables) == 1
    flip = ctx.post(aid, approve=False)
    assert flip.status_code == 409 and flip.json()["detail"]["reason"] == "already_decided"
    assert ctx.repo.get_approval(aid).status == "approved" and ctx.store.rejections == {}


def test_ac03_resume_after_restart_keeps_the_inbox_and_does_not_rerun():
    saver, repo, store = InMemorySaver(), InMemoryDecisionRepo(), InMemoryIssueTableStore()
    before = Ctx(saver=saver, repo=repo, store=store)
    aid = before.pending_id("restart")
    after = Ctx(saver=saver, repo=repo, store=store)    # 체크포인터와 표만 서버 밖에 남는다
    assert [x["approval_id"] for x in after.client(after.admin).get("/approvals").json()] == [aid]
    assert after.post(aid, approve=True).status_code == 200
    assert after.llm.calls == [] and after.retriever.calls == [] and len(store.tables) == 1


def test_missing_review_runtime_is_503_not_a_decision(ctx):
    aid = ctx.pending_id()
    ctx.app.state.review_graph = None
    assert ctx.post(aid, approve=True).status_code == 503
    (item,) = ctx.client(ctx.admin).get("/approvals").json()          # 승인함 목록은 그대로 보인다
    assert item["approval_id"] == aid and item["issue_table"] is None
    assert ctx.repo.get_approval(aid).status == "pending"


def test_graph_refuses_approval_without_an_approver_when_the_inbox_is_connected(ctx):
    aid = ctx.pending_id()
    cfg = {"configurable": {"thread_id": "t1"}}
    out = ctx.graph.invoke(Command(resume={"approve": True, "comment": "x"}), cfg)
    assert out["__interrupt__"][0].value["rejected_resume"] == "approver_missing"
    assert ctx.store.tables == {} and ctx.repo.get_approval(aid).status == "pending"
    assert ctx.client(ctx.admin).get("/approvals").json()[0]["rejected_resume"] == "approver_missing"
    assert ctx.post(aid, approve=True).status_code == 200 and len(ctx.store.tables) == 1


# --- 재개 뒤 저장 실패 -----------------------------------------------------------------------------

@pytest.mark.parametrize("subgraph", [False, True], ids=["alone", "as_subgraph"])
def test_save_failure_is_visible_and_the_same_decision_can_be_retried(subgraph):
    ctx = Ctx(wrap_store=lambda s: FailingOnce(s, "save"), subgraph=subgraph)
    aid = ctx.pending_id()
    table_rows = ctx.client(ctx.admin).get("/approvals").json()[0]["issue_table"]["rows"]
    r = ctx.post(aid, approve=True, comment="확인함")
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "save_failed"
    assert "secret-password" not in r.text
    assert ctx.repo.get_approval(aid).status == "pending" and ctx.store.tables == {}
    (item,) = ctx.client(ctx.admin).get("/approvals").json()          # 멈춘 건이 승인함에 남고 실패가 드러난다
    assert item["save_failed"] is True and item["issue_table"]["rows"] == table_rows
    calls = len(ctx.llm.calls)
    again = ctx.post(aid, approve=True, comment="확인함")
    assert again.status_code == 200 and again.json()["status"] == "approved"
    (saved,) = ctx.store.tables.values()
    assert again.json()["table_id"] == saved["table_id"] and saved["rows"] == table_rows
    assert len(ctx.llm.calls) == calls and ctx.client(ctx.admin).get("/approvals").json() == []


def test_a_different_decision_cannot_replace_the_one_waiting_to_be_saved():
    ctx = Ctx(wrap_store=lambda s: FailingOnce(s, "save"))
    aid = ctx.pending_id()
    assert ctx.post(aid, approve=True).status_code == 503
    flip = ctx.post(aid, approve=False, comment="바꾼다")
    assert flip.status_code == 409 and flip.json()["detail"]["reason"] == "already_decided"
    assert ctx.store.rejections == {} and ctx.repo.get_approval(aid).status == "pending"
    assert ctx.post(aid, approve=True).status_code == 200 and len(ctx.store.tables) == 1


def test_rejection_failure_can_be_retried():
    ctx = Ctx(wrap_store=lambda s: FailingOnce(s, "record_rejection"))
    aid = ctx.pending_id()
    assert ctx.post(aid, approve=False, comment="사유").status_code == 503
    assert ctx.client(ctx.admin).get("/approvals").json()[0]["save_failed"] is True
    assert ctx.post(aid, approve=True).status_code == 409                # 접수된 반려를 승인으로 바꾸지 못한다
    ok = ctx.post(aid, approve=False, comment="사유")
    assert ok.status_code == 200 and ok.json()["status"] == "rejected" and ctx.store.rejections[aid]["reason"] == "사유" and ctx.store.tables == {}


def test_failure_after_the_table_is_saved_does_not_save_twice():
    ctx = Ctx(wrap_repo=lambda r: FailingOnce(r, "decide_review_item"))
    aid = ctx.pending_id()
    assert ctx.post(aid, approve=True).status_code == 503
    assert len(ctx.store.tables) == 1 and ctx.repo.get_approval(aid).status == "pending"   # 표는 저장됐지만 승인 건은 아직 대기다
    ok = ctx.post(aid, approve=True)
    assert ok.status_code == 200 and len(ctx.store.tables) == 1
    assert ok.json()["table_id"] == next(iter(ctx.store.tables.values()))["table_id"]


def test_save_keeps_failing_then_recovers():
    ctx = Ctx(wrap_store=lambda s: FailingOnce(s, "save", times=2))
    aid = ctx.pending_id()
    assert [ctx.post(aid, approve=True).status_code for _ in range(3)] == [503, 503, 200]
    assert len(ctx.store.tables) == 1


def test_database_down_when_reading_the_approval_is_503_without_details(ctx):
    aid = ctx.pending_id()
    ctx.app.state.decision_repo = FailingOnce(ctx.repo, "get_approval")
    r = ctx.post(aid, approve=True)
    assert r.status_code == 503 and "secret-password" not in r.text and ctx.store.tables == {}


def test_graph_that_finishes_without_closing_the_approval_is_not_reported_as_success():
    ctx = Ctx(wrap_repo=lambda r: type("NoClose", (), {"queue_review_item": r.queue_review_item, "decide_review_item": lambda *a, **k: None})())
    aid = ctx.pending_id()
    r = ctx.post(aid, approve=True)
    assert r.status_code == 503 and ctx.repo.get_approval(aid).status == "pending"


# --- 한 대화에서 다시 검토 -------------------------------------------------------------------------

def test_second_review_in_a_thread_after_a_decision_gets_its_own_approval(ctx):
    first = ctx.pending_id()
    ctx.post(first, approve=True)
    second = ctx.start(question=REQUEST + " 추가 조건이 있다.")["__interrupt__"][0].value["approval_id"]
    assert second != first and [x["approval_id"] for x in ctx.client(ctx.admin).get("/approvals").json()] == [second]
    assert ctx.post(second, approve=False, comment="보류").status_code == 200
    assert ctx.repo.get_approval(first).status == "approved" and ctx.repo.get_approval(second).status == "rejected"


def test_the_same_table_after_a_decision_is_a_new_approval_not_a_stale_one(ctx):
    first = ctx.pending_id()
    ctx.post(first, approve=False, comment="다시 보자")
    second = ctx.pending_id()                                            # 표 내용이 같아도 사람이 다시 본다
    assert second != first and ctx.repo.get_approval(second).status == "pending"
    assert [x["approval_id"] for x in ctx.client(ctx.admin).get("/approvals").json()] == [second]
    assert ctx.post(second, approve=True).status_code == 200 and len(ctx.store.tables) == 1
    (saved,) = ctx.store.tables.values()
    assert saved["approval_id"] == second


def test_new_review_while_one_waits_closes_the_old_one_and_it_cannot_approve_the_new_table(ctx):
    old = ctx.pending_id()
    new = ctx.start(question=REQUEST + " 다른 요청이다.")["__interrupt__"][0].value["approval_id"]
    assert new != old
    assert ctx.repo.get_approval(old).status == "rejected" and ctx.repo.get_approval(old).comment == SUPERSEDED_COMMENT
    refused = ctx.post(old, approve=True)
    assert refused.status_code == 409 and ctx.store.tables == {}
    assert [x["approval_id"] for x in ctx.client(ctx.admin).get("/approvals").json()] == [new]


def test_approval_whose_thread_moved_on_is_409_and_does_not_resume_the_new_interrupt(ctx):
    """승인함에 남은 옛 건으로 지금 멈춰 있는 다른 표를 승인하지 못한다."""
    ctx.start()
    now = next(iter(ctx.repo._approvals.values())).created_at
    ctx.repo._approvals["ap_old"] = ApprovalRecord(approval_id="ap_old", kind=ISSUE_KIND, thread_id="t1", status="pending", summary="옛 건", target_id="ap_old", created_at=now)
    assert ctx.post("ap_old", approve=True).status_code == 409
    assert ctx.store.tables == {}
    listed = {x["approval_id"]: x for x in ctx.client(ctx.admin).get("/approvals").json()}
    assert listed["ap_old"]["issue_table"] is None


def test_requeue_of_the_same_table_is_idempotent(ctx):
    a = ctx.repo.queue_review_item("t", "ap", "s")
    assert ctx.repo.queue_review_item("t", "ap", "s") == a
    assert len(ctx.repo.list_pending()) == 1


def test_decision_paths_do_not_cross(ctx):
    rec = ctx.repo.queue_review_item("t", "ap", "s")
    with pytest.raises(DecisionError):
        ctx.repo.decide(rec.approval_id, True, "admin")
    with pytest.raises(AlreadyDecided):
        ctx.repo.decide_review_item(rec.approval_id, True, "admin")
        ctx.repo.decide_review_item(rec.approval_id, False, "admin")
    with pytest.raises(DecisionError):                                   # 승인자 없는 승인은 어느 경로든 안 된다
        ctx.repo.decide_review_item(ctx.repo.queue_review_item("t2", "ap2", "s").approval_id, True, " ")


# --- 앱 시작 조립 ----------------------------------------------------------------------------------

def test_runtime_builds_the_review_graph_on_memory_without_llm_keys(monkeypatch):
    monkeypatch.setenv("CHECKPOINTER", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = FastAPI()
    with open_decision_runtime(app):
        assert app.state.review_graph is not None and isinstance(app.state.decision_repo, InMemoryDecisionRepo)
    assert app.state.review_graph is None and app.state.decision_repo is None


def test_runtime_uses_the_postgres_stores_with_a_postgres_checkpointer(monkeypatch):
    from contextlib import contextmanager

    class PostgresSaver(InMemorySaver):   # is_restart_safe는 이름으로 본다. 실제 연결은 만들지 않는다
        conn = object()

    @contextmanager
    def fake_open():
        yield PostgresSaver(), None

    seen = {}
    real = Routes.build_review_graph

    def spy(retriever, checkpointer, **kw):
        seen.update(kw)
        return real(Retriever(), checkpointer, **kw)

    monkeypatch.setattr(Routes, "open_persistence", fake_open)
    monkeypatch.setattr(Routes, "build_review_graph", spy)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    app = FastAPI()
    with open_decision_runtime(app):
        assert isinstance(app.state.decision_repo, PostgresDecisionRepo)
        assert isinstance(seen["store"], PgIssueTableStore) and seen["approvals"] is app.state.decision_repo


def test_runtime_does_not_fall_back_to_memory_when_the_database_fails(monkeypatch):
    def refuse(*_a, **_k):
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(Routes, "open_persistence", refuse)
    app = FastAPI()
    with open_decision_runtime(app):
        assert getattr(app.state, "review_graph", None) is None and getattr(app.state, "decision_repo", None) is None


# --- Postgres 저장소 문장 (가짜 풀, 실제 Postgres 미검증) ---------------------------------------------

class FakeCursor:
    def __init__(self, script, log):
        self.script, self.log, self.description = script, log, True
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self.log.append((" ".join(sql.split()), args))
        self.current = self.script.pop(0) if self.script else None

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current or []


class FakePool:
    def __init__(self, script):
        self.script, self.log = script, []

    def connection(self):
        return self

    def transaction(self):
        return self

    def cursor(self, row_factory=None):
        return FakeCursor(self.script, self.log)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def row(**kw):
    from datetime import datetime, timezone

    return {"approval_id": "ap", "kind": ISSUE_KIND, "thread_id": "t", "status": "pending", "summary": "s", "target_id": "ap",
            "created_at": datetime.now(timezone.utc), "decided_by": None, "comment": "", "decided_at": None, **kw}


def test_postgres_repo_queues_new_issue_table_with_parameters():
    pool = FakePool([[], None, row()])
    rec = PostgresDecisionRepo(pool).queue_review_item("t", "ap", "s")
    assert rec.approval_id == "ap" and rec.kind == ISSUE_KIND
    select, close_old, insert = pool.log
    assert "FOR UPDATE" in select[0] and select[1] == ("t", KIND)
    assert close_old[0].startswith("UPDATE approvals SET status = 'rejected'") and close_old[1] == (SUPERSEDED_COMMENT, "t", KIND)
    assert insert[0].startswith("INSERT INTO approvals") and insert[1] == ("ap", ISSUE_KIND, "t", "s", "ap")


def test_postgres_repo_returns_the_waiting_row_without_writing():
    pool = FakePool([[row()]])
    assert PostgresDecisionRepo(pool).queue_review_item("t", "ap", "s").approval_id == "ap"
    assert len(pool.log) == 1


def test_postgres_repo_decides_issue_table_and_records_the_saved_table():
    pool = FakePool([row(), row(status="approved", decided_by="admin", target_id="tbl")])
    rec = PostgresDecisionRepo(pool).decide_review_item("ap", True, "admin", "c", table_id="tbl")
    assert rec.status == "approved" and rec.target_id == "tbl"
    assert pool.log[1][1] == ("approved", "admin", "c", "tbl", "ap")


def test_postgres_repo_flip_is_already_decided_and_writes_nothing():
    pool = FakePool([row(status="approved", decided_by="admin")])
    with pytest.raises(AlreadyDecided):
        PostgresDecisionRepo(pool).decide_review_item("ap", False, "admin")
    assert len(pool.log) == 1


def test_sql_allows_a_new_review_in_a_thread_but_one_waiting_row_per_thread():
    sql = (ROOT / "db" / "102_decision_approvals.sql").read_text(encoding="utf-8")
    assert "UNIQUE (thread_id, kind)" not in sql
    assert "DROP CONSTRAINT IF EXISTS approvals_thread_id_kind_key" in sql
    assert "approvals (thread_id) WHERE kind = 'decision_table'" in sql
    assert "approvals (thread_id) WHERE kind <> 'decision_table' AND status = 'pending'" in sql
    assert "DROP CONSTRAINT IF EXISTS approvals_kind_check" in sql
    assert "CHECK (kind IN ('decision_table', 'issue_table', 'team_review_failed'))" in sql


def test_postgres_repo_queues_team_failure_with_its_own_kind():
    pool = FakePool([[], None, row(kind=TEAM_FAILED_KIND)])
    rec = PostgresDecisionRepo(pool).queue_review_item("t", "ap", "s", kind=TEAM_FAILED_KIND)
    assert rec.kind == TEAM_FAILED_KIND and pool.log[2][1] == ("ap", TEAM_FAILED_KIND, "t", "s", "ap")
    with pytest.raises(DecisionError):
        PostgresDecisionRepo(FakePool([])).queue_review_item("t", "ap", "s", kind=KIND)


# --- 팀 실패 알림 (team_review_failed) --------------------------------------------------------------

def bad_infra(**override):
    """infra 팀은 응답을 읽을 수 없다. `then`을 주면 사람이 다시 돌리라고 한 뒤부터 그 답을 쓴다."""
    return review_llm(team_infra="이건 JSON이 아님", **override)


def fixed_after(n: int):
    calls = {"n": 0}

    def handler(user):
        from team_review_fakes import issue_for

        calls["n"] += 1
        return "이건 JSON이 아님" if calls["n"] <= n else issue_for(user, topic="oncall-impact", text="호출 경로 반영이 필요하다.")

    return handler


def test_failed_team_goes_to_a_person_first_and_nothing_is_saved():
    ctx = Ctx(llm=bad_infra())
    out = ctx.start()
    v = out["__interrupt__"][0].value
    assert set(v) == {"approval_id", "kind", "summary", "failed_teams", "thread_id"} and v["kind"] == TEAM_FAILED_KIND and v["thread_id"] == "t1"
    assert v["failed_teams"] == [{"team": "infra", "reason": "모델 응답을 읽지 못했습니다.", "attempts": TEAM_ATTEMPTS}]
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["approval_id"] == v["approval_id"] and item["kind"] == TEAM_FAILED_KIND and item["summary"] == v["summary"]
    assert item["failed_teams"] == v["failed_teams"] and item["issue_table"] is None and item["draft"] is None
    assert ctx.store.tables == {} and ctx.store.rejections == {}
    assert ctx.repo.get_approval(v["approval_id"]).status == "pending"


def test_inbox_keeps_the_three_kinds_apart():
    from decision_fixtures import EXPENSE_CELLS, FakeLLM, draft_json

    from backend.graph.decision import rules as R
    from backend.graph.decision.convert import build_convert_graph

    ctx = Ctx(llm=bad_infra())
    ctx.app.state.decision_graph = build_convert_graph(FakeLLM(draft_json(R.rules_from_cells(EXPENSE_CELLS))), ctx.repo, InMemorySaver())
    ctx.app.state.decision_graph.invoke({"category": "Approving expense", "rule_seq": 1, "version_id": "v", "source_cells": EXPENSE_CELLS, "requested_by": "a"},
                                        {"configurable": {"thread_id": "dt"}})
    failing = ctx.start("failing")["__interrupt__"][0].value
    ctx.llm.handlers["team_infra"] = fixed_after(0)
    ready = ctx.start("ready")["__interrupt__"][0].value
    items = {x["kind"]: x for x in ctx.client(ctx.admin).get("/approvals").json()}
    assert set(items) == {KIND, ISSUE_KIND, TEAM_FAILED_KIND}
    assert items[TEAM_FAILED_KIND]["approval_id"] == failing["approval_id"] and items[ISSUE_KIND]["approval_id"] == ready["approval_id"]
    assert items[KIND]["draft"] and items[KIND]["issue_table"] is None and items[KIND]["failed_teams"] is None
    assert items[ISSUE_KIND]["issue_table"] and items[ISSUE_KIND]["draft"] is None and items[ISSUE_KIND]["failed_teams"] is None
    assert items[TEAM_FAILED_KIND]["failed_teams"] and items[TEAM_FAILED_KIND]["issue_table"] is None and items[TEAM_FAILED_KIND]["draft"] is None


@pytest.mark.parametrize("subgraph", [False, True], ids=["alone", "as_subgraph"])
def test_retry_reruns_only_the_failed_team_then_reaches_issue_approval(subgraph):
    ctx = Ctx(llm=review_llm(team_infra=fixed_after(TEAM_ATTEMPTS)), subgraph=subgraph)
    aid = ctx.pending_id()
    before = {t: ctx.llm.count(f"team_{t}") for t in ("security", "infra", "itops", "finance")}
    r = ctx.post(aid, action="retry", comment="일시 오류로 보임", decided_by="attacker")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == TEAM_FAILED_KIND and body["resolution"] == "retry" and "action" not in body and body["status"] == "approved" and body["table_id"] is None
    assert body["decided_by"] == str(ctx.admin.user_id) and body["next_approval"]["kind"] == ISSUE_KIND
    assert ctx.llm.count("team_infra") == before["infra"] + 1
    assert all(ctx.llm.count(f"team_{t}") == before[t] for t in ("security", "itops", "finance"))
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["approval_id"] == body["next_approval"]["approval_id"] and item["kind"] == ISSUE_KIND
    assert [row["team"] for row in item["issue_table"]["rows"]] == ["security", "infra", "itops", "finance"] and item["issue_table"]["unreviewed"] == []
    assert ctx.store.tables == {}
    assert ctx.post(item["approval_id"], approve=True).status_code == 200 and len(ctx.store.tables) == 1


def test_retry_that_fails_again_asks_again_with_a_new_approval():
    ctx = Ctx(llm=bad_infra())
    first = ctx.pending_id()
    r = ctx.post(first, action="retry")
    assert r.status_code == 200 and r.json()["next_approval"]["kind"] == TEAM_FAILED_KIND
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["kind"] == TEAM_FAILED_KIND and item["approval_id"] != first and ctx.store.tables == {}
    assert ctx.llm.count("team_infra") == 2 * TEAM_ATTEMPTS


@pytest.mark.parametrize("subgraph", [False, True], ids=["alone", "as_subgraph"])
def test_mark_unreviewed_goes_on_to_issue_approval_without_rerunning(subgraph):
    ctx = Ctx(llm=bad_infra(), subgraph=subgraph)
    aid = ctx.pending_id()
    calls = len(ctx.llm.calls)
    r = ctx.post(aid, action="mark_unreviewed", comment="이번엔 넘어간다")
    assert r.status_code == 200 and r.json()["resolution"] == "mark_unreviewed" and r.json()["status"] == "rejected" and r.json()["comment"] == "이번엔 넘어간다"
    assert r.json()["next_approval"]["kind"] == ISSUE_KIND and len(ctx.llm.calls) == calls
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["issue_table"]["unreviewed"] == [{"team": "infra", "team_label": "인프라·SRE", "reason": "모델 응답을 읽지 못했습니다."}]
    assert ctx.store.tables == {}
    assert ctx.post(item["approval_id"], approve=True).status_code == 200
    (saved,) = ctx.store.tables.values()
    assert saved["unreviewed"][0]["team"] == "infra"


@pytest.mark.parametrize("payload,why", [({"action": "다른 값"}, "bad_action"), ({}, "bad_action"), ({"action": 5}, "bad_action"), ({"action": ["retry"]}, "bad_action"),
                                         ({"approve": True}, "bad_action")])
def test_wrong_action_changes_nothing_and_asks_again(payload, why):
    ctx = Ctx(llm=bad_infra())
    aid = ctx.pending_id()
    calls = len(ctx.llm.calls)
    r = ctx.client(ctx.admin).post(f"/approvals/{aid}", json=payload)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == why
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["approval_id"] == aid and item["rejected_resume"] == why and item["failed_teams"][0]["team"] == "infra"
    assert ctx.repo.get_approval(aid).status == "pending" and len(ctx.llm.calls) == calls and ctx.store.tables == {}
    assert ctx.post(aid, action="mark_unreviewed").status_code == 200


@pytest.mark.parametrize("payload", [[1], "x", {"action": "retry", "comment": 5}, {"action": "retry", "approval_id": "다른 번호"}])
def test_bad_team_action_body_is_400_without_resuming(payload):
    ctx = Ctx(llm=bad_infra())
    aid = ctx.pending_id()
    calls = len(ctx.llm.calls)
    assert ctx.client(ctx.admin).post(f"/approvals/{aid}", json=payload).status_code == 400
    assert len(ctx.llm.calls) == calls and ctx.repo.get_approval(aid).status == "pending"
    assert ctx.client(ctx.admin).get("/approvals").json()[0]["rejected_resume"] is None


def test_team_action_needs_admin_and_csrf():
    ctx = Ctx(llm=bad_infra())
    aid = ctx.pending_id()
    calls = len(ctx.llm.calls)
    assert ctx.client(None).post(f"/approvals/{aid}", json={"action": "retry"}).status_code == 401
    assert ctx.client(ctx.user).post(f"/approvals/{aid}", json={"action": "retry"}).status_code == 403
    assert ctx.client(ctx.admin, csrf=False).post(f"/approvals/{aid}", json={"action": "retry"}).status_code == 403
    assert len(ctx.llm.calls) == calls and ctx.repo.get_approval(aid).status == "pending"


def test_team_action_repeat_and_flip():
    ctx = Ctx(llm=bad_infra())
    aid = ctx.pending_id()
    assert ctx.post(aid, action="mark_unreviewed").status_code == 200
    calls = len(ctx.llm.calls)
    assert ctx.post(aid, action="mark_unreviewed").status_code == 200       # 같은 결정은 그대로
    flip = ctx.post(aid, action="retry")
    assert flip.status_code == 409 and flip.json()["detail"]["reason"] == "already_decided"
    assert ctx.post(aid, action="모르는 값").status_code == 400
    assert len(ctx.llm.calls) == calls


def test_writing_the_team_action_can_fail_and_be_retried():
    ctx = Ctx(llm=bad_infra(), wrap_repo=lambda r: FailingOnce(r, "decide_review_item"))
    aid = ctx.pending_id()
    r = ctx.post(aid, action="mark_unreviewed")
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "save_failed" and "secret-password" not in r.text
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["save_failed"] is True and item["failed_teams"][0]["team"] == "infra" and ctx.repo.get_approval(aid).status == "pending"
    assert ctx.post(aid, action="retry").status_code == 409                 # 접수된 결정을 바꾸지 못한다
    assert ctx.post(aid, action="없는 값").status_code == 400
    ok = ctx.post(aid, action="mark_unreviewed")
    assert ok.status_code == 200 and ok.json()["next_approval"]["kind"] == ISSUE_KIND


def test_failure_after_the_decision_is_written_continues_on_the_same_request():
    class CostCapExceeded(Exception):
        pass

    n = {"i": 0}

    def infra(user):
        from team_review_fakes import issue_for

        n["i"] += 1
        if n["i"] <= TEAM_ATTEMPTS:
            return "이건 JSON이 아님"
        if n["i"] == TEAM_ATTEMPTS + 1:
            raise CostCapExceeded("상한")
        return issue_for(user, topic="oncall-impact", text="호출 경로 반영이 필요하다.")

    ctx = Ctx(llm=review_llm(team_infra=infra))
    aid = ctx.pending_id()
    r = ctx.post(aid, action="retry")
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "save_failed" and ctx.repo.get_approval(aid).status == "approved"
    again = ctx.post(aid, action="retry")
    assert again.status_code == 200 and again.json()["next_approval"]["kind"] == ISSUE_KIND
    assert ctx.client(ctx.admin).get("/approvals").json()[0]["kind"] == ISSUE_KIND


def test_team_action_after_restart_does_not_rerun_the_teams_that_passed():
    saver, repo, store = InMemorySaver(), InMemoryDecisionRepo(), InMemoryIssueTableStore()
    before = Ctx(saver=saver, repo=repo, store=store, llm=bad_infra())
    aid = before.pending_id("restart")
    after = Ctx(saver=saver, repo=repo, store=store, llm=review_llm(team_infra=fixed_after(0)))
    assert [x["kind"] for x in after.client(after.admin).get("/approvals").json()] == [TEAM_FAILED_KIND]
    assert after.post(aid, action="retry").status_code == 200
    assert after.llm.count("team_infra") == 1 and after.llm.count("team_security") == 0 and after.llm.count("supervisor") == 0


def test_inbox_shows_resolution_slot_only_for_team_failure():
    from decision_fixtures import EXPENSE_CELLS, FakeLLM, draft_json

    from backend.graph.decision import rules as R
    from backend.graph.decision.convert import build_convert_graph

    ctx = Ctx(llm=bad_infra())
    ctx.app.state.decision_graph = build_convert_graph(FakeLLM(draft_json(R.rules_from_cells(EXPENSE_CELLS))), ctx.repo, InMemorySaver())
    ctx.app.state.decision_graph.invoke({"category": "Approving expense", "rule_seq": 1, "version_id": "v", "source_cells": EXPENSE_CELLS, "requested_by": "a"},
                                        {"configurable": {"thread_id": "dt"}})
    ctx.start("failing")
    ctx.llm.handlers["team_infra"] = fixed_after(0)
    ctx.start("ready")
    items = {x["kind"]: x for x in ctx.client(ctx.admin).get("/approvals").json()}
    assert items[TEAM_FAILED_KIND]["resolution"] is None                    # 아직 고르지 않았다
    assert "resolution" not in items[KIND] and "resolution" not in items[ISSUE_KIND]
    assert "resolution" in ctx.app.openapi()["components"]["schemas"]["ApprovalView"]["properties"]


@pytest.mark.parametrize("approve", [True, False])
def test_decision_response_of_other_kinds_has_no_resolution(approve):
    ctx = Ctx()
    r = ctx.post(ctx.pending_id(), approve=approve)
    assert r.status_code == 200 and r.json()["kind"] == ISSUE_KIND and "resolution" not in r.json()


@pytest.mark.parametrize("action,status", [("retry", "approved"), ("mark_unreviewed", "rejected")])
def test_status_is_unchanged_and_resolution_says_what_really_happened(action, status):
    ctx = Ctx(llm=bad_infra())
    aid = ctx.pending_id()
    r = ctx.post(aid, action=action)
    assert r.status_code == 200 and r.json()["status"] == status and r.json()["resolution"] == action
    rec = ctx.repo.get_approval(aid)
    assert rec.status == status and team_resolution(rec) == action
    assert ctx.post(aid, action=action).json()["resolution"] == action      # 같은 결정을 다시 보내도 같다


def test_saved_decision_waiting_for_retry_shows_its_resolution_in_the_inbox():
    ctx = Ctx(llm=bad_infra(), wrap_repo=lambda r: FailingOnce(r, "decide_review_item"))
    aid = ctx.pending_id()
    assert ctx.post(aid, action="mark_unreviewed").status_code == 503
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["save_failed"] is True and item["resolution"] == "mark_unreviewed" and ctx.repo.get_approval(aid).status == "pending"


def test_closed_without_a_person_is_not_read_as_mark_unreviewed():
    ctx = Ctx(llm=bad_infra())
    old = ctx.pending_id()
    ctx.llm.handlers["team_infra"] = fixed_after(0)
    ctx.pending_id()
    rec = ctx.repo.get_approval(old)
    assert rec.status == "rejected" and rec.decided_by is None and team_resolution(rec) is None
    for action in ("mark_unreviewed", "retry"):
        r = ctx.post(old, action=action)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "already_decided"


def test_team_decision_needs_a_person_in_both_repos():
    for repo in (InMemoryDecisionRepo(),):
        rec = repo.queue_review_item("t", "a", "s", kind=TEAM_FAILED_KIND)
        for blank in (None, "", "  "):
            with pytest.raises(DecisionError):
                repo.decide_review_item(rec.approval_id, False, blank)
        assert repo.get_approval(rec.approval_id).status == "pending"
    pool = FakePool([row(kind=TEAM_FAILED_KIND, status="pending")])
    with pytest.raises(DecisionError):
        PostgresDecisionRepo(pool).decide_review_item("ap", False, None)
    assert len(pool.log) == 1 and "FOR UPDATE" in pool.log[0][0]


def test_issue_kind_rejection_still_needs_no_person_rule_change():
    repo = InMemoryDecisionRepo()
    rec = repo.queue_review_item("t", "a", "s")
    done = repo.decide_review_item(rec.approval_id, False, None, "반려")
    assert done.status == "rejected" and team_resolution(done) is None


def test_status_column_meaning_is_written_in_the_schema():
    sql = (ROOT / "db" / "102_decision_approvals.sql").read_text(encoding="utf-8")
    assert "COMMENT ON COLUMN approvals.status" in sql and "mark_unreviewed" in sql
    assert "status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected'))" in sql


@pytest.mark.parametrize("name,tables", [("102_decision_approvals.sql", ("decision_tables", "approvals")), ("110_issue_tables.sql", ("issue_tables", "issue_table_rejections"))])
def test_review_tables_turn_rls_on_like_the_search_tables(name, tables):
    import re

    sql = (ROOT / "db" / name).read_text(encoding="utf-8")
    assert tuple(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)) == tables
    for t in tables:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;" in sql
    assert "FORCE ROW LEVEL SECURITY" not in sql and "CREATE POLICY" not in sql   # 표 소유자인 앱을 막지 않는다


def test_new_review_while_a_team_failure_waits_closes_it():
    ctx = Ctx(llm=bad_infra())
    old = ctx.pending_id()
    ctx.llm.handlers["team_infra"] = fixed_after(0)
    new = ctx.pending_id()
    assert new != old and ctx.repo.get_approval(old).comment == SUPERSEDED_COMMENT
    assert [x["kind"] for x in ctx.client(ctx.admin).get("/approvals").json()] == [ISSUE_KIND]
