"""결정표 실행·승인 API 시험 (`backend/graph/decision/routes.py`). 가짜 인증 저장소, 메모리 저장소, 가짜 모델로 돈다. 실제 칸 파일을 읽는다."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from auth_test_support import MemoryRevocationStore
from decision_fixtures import FakeLLM, draft_json
from team_review_fakes import Retriever, review_llm
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, create_access_token
from backend.graph.decision import rules as R
from backend.graph.decision import routes as Routes
from backend.graph.decision.convert import build_convert_graph
from backend.graph.decision.repo import ApprovalRecord, InMemoryDecisionRepo
from backend.graph.decision.routes import create_decision_router
from backend.graph.departments.review import build_review_graph
from backend.rag.ingest.handbook import AUTHZ_COMMIT, AUTHZ_PATH, rule_seq
from backend.schemas import DecisionTable

CELLS_FILE = Path(__file__).resolve().parents[1] / "data" / "parsed" / "authz_cells.jsonl"
ABBREVIATED = re.compile(r"\$\s*\d[\d,.]*\s*[kKmM]\b")
EXPENSE, LEGAL, BAD_DEBT = "Approving expense", "Legal Contracts", "Bad debt write off"
PAO = "PAO or VP Finance"
CSRF = "csrf-token-for-test"


def cells_of(category: str) -> list[dict]:
    rows = [json.loads(x) for x in CELLS_FILE.read_text(encoding="utf-8").splitlines()]
    return [c for c in rows if c["category"] == category]


class FakeAuthStore:
    def __init__(self, *users: AuthUser) -> None:
        self.users = {str(u.user_id): u for u in users}

    def get_by_login_id(self, login_id):
        return None

    def get_by_user_id(self, user_id):
        return self.users.get(str(user_id))


class Ctx:
    def __init__(self) -> None:
        self.secret = secrets.token_urlsafe(32)
        self.admin = AuthUser(user_id=uuid4(), login_id="admin", password_hash="x", role="admin")
        self.user = AuthUser(user_id=uuid4(), login_id="user", password_hash="x", role="user")
        self.repo = InMemoryDecisionRepo()
        self.llm = FakeLLM(draft_json(R.rules_from_cells(cells_of(EXPENSE))))
        self.graph = build_convert_graph(self.llm, self.repo, InMemorySaver())
        self.app = FastAPI()
        self.app.state.token_revocation_store = MemoryRevocationStore()
        self.app.state.decision_repo = self.repo
        self.app.state.decision_graph = self.graph
        self.app.state.review_graph = build_review_graph(Retriever(), InMemorySaver(), llm=review_llm(), approvals=self.repo)
        self.app.include_router(create_decision_router(store=FakeAuthStore(self.admin, self.user), secret=self.secret))

    def client(self, who: AuthUser | None = None, csrf: bool = True) -> TestClient:
        c = TestClient(self.app)
        if who is not None:
            c.cookies.set(AUTH_COOKIE_NAME, create_access_token(who.user_id, who.role, secret=self.secret))
        if csrf:
            c.cookies.set(CSRF_COOKIE_NAME, CSRF)
            c.headers["X-CSRF-Token"] = CSRF
        return c

    def table(self, category: str = EXPENSE, tid: str | None = None, status: str = "approved") -> str:
        tid = tid or f"dt_{uuid4().hex[:6]}"
        t = DecisionTable(table_id=tid, rule_seq=9, version_id="0a3de8337541", cells=R.rules_from_cells(cells_of(category)), status="draft")
        rec = self.repo.queue_draft(tid, t, "s")
        if status != "draft":
            self.repo.decide(rec.approval_id, status == "approved", "admin-0")
        return tid

    def pending(self, draft=None, tid: str = "thread-1") -> dict:
        """변환 그래프를 승인 대기까지 돌린다."""
        if draft is not None:
            self.llm.reply = draft_json(draft)
        self.graph.invoke({"category": EXPENSE, "rule_seq": 9, "version_id": "0a3de8337541", "source_cells": cells_of(EXPENSE), "requested_by": "x"},
                          {"configurable": {"thread_id": tid}})
        return self.graph.get_state({"configurable": {"thread_id": tid}}).tasks[0].interrupts[0].value


@pytest.fixture
def ctx() -> Ctx:
    return Ctx()


# --- 실행 ------------------------------------------------------------------------------------

def test_run_returns_the_confirmed_shape(ctx):
    tid = ctx.table()
    r = ctx.client(ctx.user, csrf=False).post(f"/decision-tables/{tid}/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"table_id", "version_id", "band_label", "range_note", "approvers", "functional_approvers",
                         "financial_approvers", "cooperating", "source"}
    assert body["approvers"] == ["Director", PAO] and body["functional_approvers"] == ["Director"] and body["financial_approvers"] == [PAO]
    assert body["band_label"] == "$25,000 초과 $50,000 이하" and body["cooperating"] == []
    assert body["source"]["band"] == ">$25K up to $50K" and body["source"]["article"] == f"{EXPENSE} / >$25K up to $50K"
    assert body["source"]["rule_seq"] == 9 and "authorization-matrix" in body["source"]["source_url"]
    assert not ABBREVIATED.search(json.dumps({k: v for k, v in body.items() if k != "source"}, ensure_ascii=False))
    assert len(ctx.llm.calls) == 0                     # 실행에 LLM을 쓰지 않는다


def test_signs_only_role_is_cooperating(ctx):
    tid = ctx.table()
    body = ctx.client(ctx.user).post(f"/decision-tables/{tid}/run", json={"task_type": EXPENSE, "amount_usd": 2_000_000}).json()
    assert body["approvers"] == ["CEO"] and body["cooperating"] == ["CFO"]


def test_band_for_a_task_without_amount_bands(ctx):
    tid = ctx.table(LEGAL)
    c = ctx.client(ctx.user)
    only_amount = c.post(f"/decision-tables/{tid}/run", json={"task_type": LEGAL, "amount_usd": 1000})
    assert only_amount.status_code == 400 and "band" in only_amount.json()["detail"]["message"]
    ok = c.post(f"/decision-tables/{tid}/run", json={"task_type": LEGAL, "band": "NDA - Third Party"})
    assert ok.status_code == 200 and ok.json()["band_label"] == "NDA - Third Party"
    assert ok.json()["approvers"] == ["Director of legal", "CLO"]


@pytest.mark.parametrize("payload", [
    "이건 JSON이 아니다", "[1, 2]", "{}",
    {"amount_usd": 30000},
    {"task_type": "   ", "amount_usd": 30000},
    {"task_type": 5, "amount_usd": 30000},
    {"task_type": EXPENSE},
    {"task_type": EXPENSE, "amount_usd": None},
    {"task_type": EXPENSE, "amount_usd": -1},
    {"task_type": EXPENSE, "amount_usd": "3만"},
    {"task_type": EXPENSE, "amount_usd": True},
    {"task_type": EXPENSE, "amount_usd": 30000, "band": 5},
    {"task_type": EXPENSE, "amount_usd": 30000, "band": "  "},
    '{"task_type": "Approving expense", "amount_usd": 1e999}',
    '{"task_type": "Approving expense", "amount_usd": NaN}',
])
def test_format_errors_are_400_not_validation_422(ctx, payload):
    tid = ctx.table()
    data = payload if isinstance(payload, str) else json.dumps(payload)
    r = ctx.client(ctx.user).post(f"/decision-tables/{tid}/run", content=data.encode("utf-8"), headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["reason"] == "bad_request"


@pytest.mark.parametrize("path,payload", [
    ("/decision-tables/없는표/run", {"task_type": EXPENSE, "amount_usd": 30000}),
    ("TABLE", {"task_type": "다른 업무", "amount_usd": 30000}),
    ("TABLE", {"task_type": EXPENSE, "amount_usd": 30000, "band": "없는 구간"}),
    ("TABLE", {"task_type": EXPENSE, "amount_usd": 0}),
])
def test_missing_table_task_or_band_is_404(ctx, path, payload):
    tid = ctx.table()
    url = f"/decision-tables/{tid}/run" if path == "TABLE" else path
    r = ctx.client(ctx.user).post(url, json=payload)
    assert r.status_code == 404 and r.json()["detail"]["reason"] == "not_found"


@pytest.mark.parametrize("status", ["draft", "rejected"])
def test_unapproved_table_is_409(ctx, status):
    tid = ctx.table(status=status)
    r = ctx.client(ctx.user).post(f"/decision-tables/{tid}/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "not_approved"


def test_task_type_needs_exactly_one_approved_table(ctx):
    c = ctx.client(ctx.user)
    payload = {"task_type": EXPENSE, "amount_usd": 30000}
    zero = c.post("/decision-tables/run", json=payload)
    assert zero.status_code == 409 and zero.json()["detail"]["reason"] == "ambiguous_table"
    ctx.table()
    assert c.post("/decision-tables/run", json=payload).status_code == 200
    ctx.table()
    assert c.post("/decision-tables/run", json=payload).status_code == 409


@pytest.mark.parametrize("category,amount,message", [
    (EXPENSE, 500_000, "금액 $500,000은 두 구간에 함께 들어 구간을 정할 수 없다: $250,000 초과 $500,000 이하 / $500,000 이상 $1,000,000 이하"),
    (EXPENSE, 1_000_000, "금액 $1,000,000은 두 구간에 함께 들어 구간을 정할 수 없다: $500,000 이상 $1,000,000 이하 / $1,000,000 이상 $5,000,000 이하"),
    (BAD_DEBT, 10_000, "금액 $10,000은 두 구간에 함께 들어 구간을 정할 수 없다: $10,000 이하 / $10,000 이상 $100,000 이하"),
    (BAD_DEBT, 100_000, "금액 $100,000은 두 구간에 함께 들어 구간을 정할 수 없다: $10,000 이상 $100,000 이하 / $100,000 이상"),
])
def test_overlap_is_422_with_exact_amounts(ctx, category, amount, message):
    tid = ctx.table(category)
    r = ctx.client(ctx.user).post(f"/decision-tables/{tid}/run", json={"task_type": category, "amount_usd": amount})
    assert r.status_code == 422
    assert r.json()["detail"] == {"reason": "ambiguous_band", "message": message}


def test_run_requires_login(ctx):
    tid = ctx.table()
    assert ctx.client(None).post(f"/decision-tables/{tid}/run", json={"task_type": EXPENSE, "amount_usd": 30000}).status_code == 401


def test_run_without_runtime_is_503(ctx):
    ctx.app.state.decision_repo = None
    assert ctx.client(ctx.user).post("/decision-tables/x/run", json={"task_type": EXPENSE, "amount_usd": 1}).status_code == 503


# --- 승인함 ----------------------------------------------------------------------------------

def test_approvals_are_admin_only(ctx):
    req = ctx.pending()
    assert ctx.client(None).get("/approvals").status_code == 401
    assert ctx.client(ctx.user).get("/approvals").status_code == 403
    assert ctx.client(None).post(f"/approvals/{req['approval_id']}", json={"approve": True}).status_code == 401
    refused = ctx.client(ctx.user).post(f"/approvals/{req['approval_id']}", json={"approve": True})
    assert refused.status_code == 403
    assert ctx.repo.get_table(req["table_id"]).status == "draft"


def test_decide_needs_csrf(ctx):
    req = ctx.pending()
    r = ctx.client(ctx.admin, csrf=False).post(f"/approvals/{req['approval_id']}", json={"approve": True})
    assert r.status_code == 403 and ctx.repo.get_table(req["table_id"]).status == "draft"


def test_list_shows_draft_and_comparison_with_exact_labels(ctx):
    req = ctx.pending()
    body = ctx.client(ctx.admin).get("/approvals").json()
    assert [x["approval_id"] for x in body] == [req["approval_id"]]
    item = body[0]
    assert item["kind"] == "decision_table" and item["summary"] == req["summary"] and item["table_id"] == req["table_id"]
    assert datetime.fromisoformat(item["created_at"])
    assert {r["band_label"] for r in item["draft"]} >= {"$500,000 이상 $1,000,000 이하", "$5,000,000 초과"}
    assert {r["band"] for r in item["comparison"]["rows"]} >= {"$500K to $1M"}          # 원문 대조용 원문 표기
    assert all(not ABBREVIATED.search(r["band_label"]) for r in item["comparison"]["rows"])
    assert item["rejected_resume"] is None


def test_approve_fills_decided_by_from_login_and_ignores_body(ctx):
    req = ctx.pending()
    r = ctx.client(ctx.admin).post(f"/approvals/{req['approval_id']}", json={"approve": True, "decided_by": "attacker", "comment": "대조함"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["decided_by"] == str(ctx.admin.user_id) and body["comment"] == "대조함"
    table = ctx.repo.get_table(req["table_id"])
    assert table.status == "approved" and table.approved_by == str(ctx.admin.user_id)
    assert ctx.client(ctx.admin).get("/approvals").json() == []
    run = ctx.client(ctx.user).post(f"/decision-tables/{req['table_id']}/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert run.status_code == 200 and run.json()["approvers"] == ["Director", PAO]


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_mismatch_approval_without_comment_is_refused_then_can_retry(ctx, comment):
    rules = R.rules_from_cells(cells_of(EXPENSE))
    rules[0]["approvers"] = ["CEO"]
    req = ctx.pending(rules)
    c = ctx.client(ctx.admin)
    payload = {"approve": True} if comment is None else {"approve": True, "comment": comment}
    r = c.post(f"/approvals/{req['approval_id']}", json=payload)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "comment_required"
    assert ctx.repo.get_table(req["table_id"]).status == "draft"
    assert c.get("/approvals").json()[0]["rejected_resume"] == "comment_required"
    ok = c.post(f"/approvals/{req['approval_id']}", json={"approve": True, "comment": "원문 오탈자를 확인함"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert ctx.repo.get_approval(req["approval_id"]).comment == "원문 오탈자를 확인함"


def test_mismatch_rejection_needs_no_comment(ctx):
    rules = R.rules_from_cells(cells_of(EXPENSE))
    rules[0]["approvers"] = ["CEO"]
    req = ctx.pending(rules)
    r = ctx.client(ctx.admin).post(f"/approvals/{req['approval_id']}", json={"approve": False})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_repeat_and_flip(ctx):
    req = ctx.pending()
    c = ctx.client(ctx.admin)
    assert c.post(f"/approvals/{req['approval_id']}", json={"approve": True}).status_code == 200
    assert c.post(f"/approvals/{req['approval_id']}", json={"approve": True}).status_code == 200    # 같은 결정은 그대로
    flip = c.post(f"/approvals/{req['approval_id']}", json={"approve": False})
    assert flip.status_code == 409 and flip.json()["detail"]["reason"] == "already_decided"
    assert ctx.repo.get_table(req["table_id"]).status == "approved"


@pytest.mark.parametrize("payload", [{"comment": "x"}, {"approve": "yes"}, {"approve": True, "comment": 5}, {"approve": True, "approval_id": "ap_other"}, [1]])
def test_bad_decision_body_is_400(ctx, payload):
    req = ctx.pending()
    r = ctx.client(ctx.admin).post(f"/approvals/{req['approval_id']}", json=payload)
    assert r.status_code == 400 and ctx.repo.get_table(req["table_id"]).status == "draft"


def test_unknown_approval_is_404(ctx):
    assert ctx.client(ctx.admin).post("/approvals/ap_none", json={"approve": True}).status_code == 404


def test_lost_graph_of_either_kind_is_409(ctx):
    now = datetime.now(timezone.utc)
    ctx.repo._approvals["ap_issue"] = ApprovalRecord(approval_id="ap_issue", kind="issue_table", thread_id="r", status="pending", summary="쟁점표", target_id="x", created_at=now)
    ctx.repo._approvals["ap_lost"] = ApprovalRecord(approval_id="ap_lost", kind="decision_table", thread_id="없는대화", status="pending", summary="s", target_id="x", created_at=now)
    c = ctx.client(ctx.admin)
    assert c.post("/approvals/ap_issue", json={"approve": True}).status_code == 409
    assert c.post("/approvals/ap_lost", json={"approve": True}).status_code == 409
    listed = {x["approval_id"]: x for x in c.get("/approvals").json()}
    assert listed["ap_issue"]["draft"] is None and listed["ap_lost"]["comparison"] is None


# --- 금액이 겹치면 band를 줘도 422 (사용자 확정) ------------------------------------------------------

@pytest.mark.parametrize("category,amount,bands", [
    (EXPENSE, 500_000, (">$250K up to $500K", "$500K to $1M", "$500,000 이상 $1,000,000 이하")),
    (EXPENSE, 1_000_000, ("$500K to $1M", "$1M up to $5M", "$1,000,000 이상 $5,000,000 이하")),
    (BAD_DEBT, 10_000, ("$10,000 이하", "$10,000 이상 $100,000 이하")),
    (BAD_DEBT, 100_000, ("$10,000 이상 $100,000 이하", "$100,000 이상")),
])
@pytest.mark.parametrize("named_table", [True, False], ids=["table_id", "task_type"])
def test_overlap_stays_422_even_with_band(ctx, category, amount, bands, named_table):
    tid = ctx.table(category)
    url = f"/decision-tables/{tid}/run" if named_table else "/decision-tables/run"
    c = ctx.client(ctx.user)
    for band in bands:
        r = c.post(url, json={"task_type": category, "amount_usd": amount, "band": band})
        assert r.status_code == 422 and r.json()["detail"]["reason"] == "ambiguous_band", (band, r.text)


def test_run_by_task_type_route_stays(ctx):
    ctx.table()
    assert "/decision-tables/run" in ctx.app.openapi()["paths"]
    r = ctx.client(ctx.user).post("/decision-tables/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert r.status_code == 200 and r.json()["approvers"] == ["Director", PAO]


def test_missing_band_message_does_not_repeat_what_was_typed(ctx):
    tid = ctx.table()
    r = ctx.client(ctx.user).post(f"/decision-tables/{tid}/run", json={"task_type": EXPENSE, "amount_usd": 30000, "band": "$1.5M to $2M"})
    assert r.status_code == 404 and not ABBREVIATED.search(r.text)


# --- 승인된 결정표 목록 -------------------------------------------------------------------------------

def test_list_needs_login(ctx):
    assert ctx.client(None).get("/decision-tables").status_code == 401


def test_list_has_only_approved_tables_with_exact_labels(ctx):
    approved = ctx.table()
    ctx.table(LEGAL, status="draft")
    ctx.table(BAD_DEBT, status="rejected")
    r = ctx.client(ctx.user, csrf=False).get("/decision-tables")
    assert r.status_code == 200
    (item,) = r.json()
    assert item["table_id"] == approved and item["category"] == EXPENSE and item["status"] == "approved"
    assert item["rule_seq"] == 9 and item["version_id"] == "0a3de8337541"
    assert {c["band_label"] for c in item["cells"]} >= {"$500,000 이상 $1,000,000 이하"}
    assert all(not ABBREVIATED.search(c["band_label"]) for c in item["cells"])
    assert {c["band"] for c in item["cells"]} >= {"$500K to $1M"}                      # 원문 표기는 근거 칸에 그대로
    assert "approved_by" not in item and str(ctx.admin.user_id) not in r.text


def test_list_is_empty_without_approved_tables_and_503_without_runtime(ctx):
    ctx.table(status="draft")
    assert ctx.client(ctx.user).get("/decision-tables").json() == []
    ctx.app.state.decision_repo = None
    assert ctx.client(ctx.user).get("/decision-tables").status_code == 503


# --- 결정표 초안 변환 시작 ----------------------------------------------------------------------------

def test_convert_is_admin_only_with_csrf(ctx):
    payload = {"category": EXPENSE}
    assert ctx.client(None).post("/decision-tables/convert", json=payload).status_code == 401
    assert ctx.client(ctx.user).post("/decision-tables/convert", json=payload).status_code == 403
    assert ctx.client(ctx.admin, csrf=False).post("/decision-tables/convert", json=payload).status_code == 403
    assert ctx.llm.calls == [] and ctx.repo.list_pending() == []


def test_convert_runs_to_the_approval_inbox_and_stops(ctx):
    r = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": EXPENSE})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "decision_table" and len(ctx.llm.calls) == 1
    table = ctx.repo.get_table(body["table_id"])
    assert table.status == "draft" and table.approved_by is None                       # 승인 전에는 실행되지 않는다
    assert table.rule_seq == rule_seq(AUTHZ_PATH) and table.version_id == AUTHZ_COMMIT[:12]
    assert body["comparison"]["mismatch_count"] == 0 and {x["band_label"] for x in body["draft"]} >= {"$500,000 이상 $1,000,000 이하"}
    (item,) = ctx.client(ctx.admin).get("/approvals").json()
    assert item["approval_id"] == body["approval_id"] and item["comparison"] == body["comparison"]
    refused = ctx.client(ctx.user).post(f"/decision-tables/{body['table_id']}/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "not_approved"
    assert ctx.client(ctx.user).get("/decision-tables").json() == []


def test_converted_draft_resumes_through_the_approval_route_and_runs(ctx):
    body = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": EXPENSE}).json()
    done = ctx.client(ctx.admin).post(f"/approvals/{body['approval_id']}", json={"approve": True})
    assert done.status_code == 200 and done.json()["status"] == "approved" and done.json()["kind"] == "decision_table"
    assert len(ctx.llm.calls) == 1                                                     # 재개에서 초안을 다시 쓰지 않는다
    run = ctx.client(ctx.user).post("/decision-tables/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert run.status_code == 200 and run.json()["approvers"] == ["Director", PAO]
    assert [t["table_id"] for t in ctx.client(ctx.user).get("/decision-tables").json()] == [body["table_id"]]


def test_convert_finds_the_category_regardless_of_case_and_keeps_the_original_name(ctx):
    r = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": "  approving   EXPENSE "})
    assert r.status_code == 201 and "Approving expense" in r.json()["summary"]


@pytest.mark.parametrize("payload", ["이건 JSON이 아니다", "[1]", "{}", {"category": ""}, {"category": "   "}, {"category": 5}])
def test_convert_format_errors_are_400(ctx, payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    r = ctx.client(ctx.admin).post("/decision-tables/convert", content=data.encode("utf-8"), headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "bad_request" and ctx.llm.calls == []


def test_convert_unknown_category_is_404_without_llm(ctx):
    r = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": "없는 업무"})
    assert r.status_code == 404 and ctx.llm.calls == []


def test_convert_unreadable_draft_is_not_retried_and_reaches_no_inbox(ctx):
    ctx.llm.reply = "이건 JSON이 아니다"
    r = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": EXPENSE})
    assert r.status_code == 502 and r.json()["detail"]["reason"] == "draft_unreadable"
    assert len(ctx.llm.calls) == 1 and ctx.repo.list_pending() == []


def test_convert_llm_failure_is_503_without_details(ctx):
    def boom(_):
        raise RuntimeError("provider failed key=secret-value")

    ctx.llm.reply = boom
    r = ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": EXPENSE})
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "convert_failed" and "secret-value" not in r.text
    assert ctx.repo.list_pending() == []


def test_convert_refuses_while_one_waits_or_is_approved(ctx):
    c = ctx.client(ctx.admin)
    first = c.post("/decision-tables/convert", json={"category": EXPENSE}).json()
    assert c.post("/decision-tables/convert", json={"category": EXPENSE}).status_code == 409   # 승인함에 같은 업무가 겹치지 않는다
    assert len(ctx.llm.calls) == 1
    c.post(f"/approvals/{first['approval_id']}", json={"approve": True})
    assert c.post("/decision-tables/convert", json={"category": EXPENSE}).status_code == 409   # 승인된 표가 둘이면 실행이 막힌다
    assert len(ctx.llm.calls) == 1


def test_convert_can_start_again_after_rejection(ctx):
    c = ctx.client(ctx.admin)
    first = c.post("/decision-tables/convert", json={"category": EXPENSE}).json()
    c.post(f"/approvals/{first['approval_id']}", json={"approve": False, "comment": "다시"})
    second = c.post("/decision-tables/convert", json={"category": EXPENSE})
    assert second.status_code == 201 and second.json()["approval_id"] != first["approval_id"]


def test_convert_without_the_cells_file_is_503(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(Routes, "AUTHZ_CELLS_FILE", tmp_path / "없음.jsonl")
    assert ctx.client(ctx.admin).post("/decision-tables/convert", json={"category": EXPENSE}).status_code == 503


def test_cells_file_location_is_the_real_one():
    assert Routes.AUTHZ_CELLS_FILE == CELLS_FILE


# --- 재개 뒤 저장 실패 (결정표) -------------------------------------------------------------------------

class FailingDecide:
    def __init__(self, repo, times=1):
        self.repo, self.left = repo, times

    def __getattr__(self, name):
        return getattr(self.repo, name)

    def decide(self, *a, **k):
        if self.left > 0:
            self.left -= 1
            raise RuntimeError("connection failed postgresql://user:secret-password@db/x")
        return self.repo.decide(*a, **k)


@pytest.fixture
def failing(ctx):
    ctx.graph = build_convert_graph(ctx.llm, FailingDecide(ctx.repo), InMemorySaver())
    ctx.app.state.decision_graph = ctx.graph
    return ctx


def test_save_failure_used_to_stick_at_409_and_can_now_be_retried(failing):
    ctx = failing
    req = ctx.pending()
    c = ctx.client(ctx.admin)
    r = c.post(f"/approvals/{req['approval_id']}", json={"approve": True})
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "save_failed" and "secret-password" not in r.text
    assert ctx.repo.get_approval(req["approval_id"]).status == "pending" and ctx.repo.get_table(req["table_id"]).status == "draft"
    (item,) = c.get("/approvals").json()
    assert item["save_failed"] is True and item["table_id"] == req["table_id"] and item["comparison"] == req["comparison"]
    assert {x["band_label"] for x in item["draft"]} >= {"$500,000 이상 $1,000,000 이하"}
    again = c.post(f"/approvals/{req['approval_id']}", json={"approve": True})
    assert again.status_code == 200 and again.json()["status"] == "approved" and again.json()["decided_by"] == str(ctx.admin.user_id)
    assert ctx.repo.get_table(req["table_id"]).status == "approved" and c.get("/approvals").json() == []
    assert len(ctx.llm.calls) == 1
    run = ctx.client(ctx.user).post(f"/decision-tables/{req['table_id']}/run", json={"task_type": EXPENSE, "amount_usd": 30000})
    assert run.status_code == 200


def test_failed_save_cannot_be_flipped_to_the_other_decision(failing):
    ctx = failing
    req = ctx.pending()
    c = ctx.client(ctx.admin)
    assert c.post(f"/approvals/{req['approval_id']}", json={"approve": False, "comment": "반려"}).status_code == 503
    flip = c.post(f"/approvals/{req['approval_id']}", json={"approve": True})
    assert flip.status_code == 409 and flip.json()["detail"]["reason"] == "already_decided"
    assert ctx.repo.get_table(req["table_id"]).status == "draft"
    assert c.post(f"/approvals/{req['approval_id']}", json={"approve": False, "comment": "반려"}).json()["status"] == "rejected"
