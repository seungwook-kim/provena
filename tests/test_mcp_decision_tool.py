"""MCP 읽기 전용 도구 explain_decision 시험 (docs/specs/mcp.md explain_decision 절).

결정표 실행기(`DecisionExecutor`)를 그대로 부르는지, HTTP 실행 응답(`routes.RunResponse`)과 같은 칸만 내보내는지(승인자 id 없음),
실행기 오류가 상태로 옮겨지는지 본다. 메모리 저장소와 2023 권한표 고정 데이터(`decision_fixtures`)만 쓴다(키·네트워크·DB 없음).
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastmcp")
from decision_fixtures import EXPENSE_CELLS, LEGAL_CELLS  # noqa: E402
from fastmcp import Client, FastMCP  # noqa: E402

from backend.graph.decision import rules as R  # noqa: E402
from backend.graph.decision.execute import DecisionExecutor  # noqa: E402
from backend.graph.decision.repo import InMemoryDecisionRepo  # noqa: E402
from backend.graph.decision.routes import RunResponse  # noqa: E402
from backend.schemas import DecisionTable  # noqa: E402
from extras.mcp_skill.mcp_server import decision_tool, server  # noqa: E402

EXPENSE, LEGAL = "Approving expense", "Legal Contracts"
PERSON = "admin-7f3a9c-person"          # 승인한 관리자 user_id. 출력 어디에도 나오면 안 된다
PINNED = "0a3de8337541"                 # 고정해 둔 2023 권한표 판(execute._source_url이 원문 주소를 아는 판)


def approve(repo: InMemoryDecisionRepo, tid: str, cells=EXPENSE_CELLS, version=PINNED, rules=None) -> str:
    rec = repo.queue_draft(tid, DecisionTable(table_id=f"dt_{tid}", rule_seq=7, version_id=version,
                                              cells=rules if rules is not None else R.rules_from_cells(cells), status="draft"), "s")
    repo.decide(rec.approval_id, True, PERSON)
    return f"dt_{tid}"


class Spy:
    """저장소 호출을 세는 껍데기. exc가 있으면 읽기마다 그 예외를 낸다."""

    def __init__(self, inner=None, exc: BaseException | None = None):
        self.inner, self.exc, self.calls = inner or InMemoryDecisionRepo(), exc, 0

    def __getattr__(self, name):
        attr = getattr(self.inner, name)

        def call(*a, **k):
            self.calls += 1
            if self.exc:
                raise self.exc
            return attr(*a, **k)

        return call


def make(repo) -> FastMCP:
    mcp = FastMCP("t")
    decision_tool.register(mcp, repo=repo)
    return mcp


def call(mcp, args: dict):
    async def go():
        async with Client(mcp) as c:
            return await c.call_tool("explain_decision", args, raise_on_error=False)
    return asyncio.run(go())


def run(repo, **args) -> dict:
    return call(make(repo), args).structured_content


@pytest.fixture
def repo():
    r = InMemoryDecisionRepo()
    approve(r, "a")
    return r


# ---------- 실행기와 같다 ----------

@pytest.mark.parametrize("amount", [0.01, 25_000, 25_000.01, 30_000, 50_000, 250_000, 750_000, 1_000_000.5, 6_000_000])
def test_same_answer_as_the_executor_and_the_http_route(repo, amount):
    """그래프·HTTP와 같은 실행기를 부른다: 경계 금액에서도 승인 순서·구간이 같고, 칸은 HTTP 응답(RunResponse)과 같다."""
    want = DecisionExecutor(repo).run(EXPENSE, amount)
    r = run(repo, task_type=EXPENSE, amount_usd=amount)
    assert r["status"] == "ok" and len(r["results"]) == 1
    got = r["results"][0]
    assert {k: v for k, v in got.items() if k != "approved"} == RunResponse(**want).model_dump()
    assert got["approved"] is True and r["source"] == f"decision_tables:dt_a@{PINNED}"


def test_pinned_version_has_date_unknown_version_has_none():
    """as_of는 고정해 둔 권한표 판일 때만(decision_citation). 모르는 판은 날짜·주소를 지어내지 않는다."""
    known, other = InMemoryDecisionRepo(), InMemoryDecisionRepo()
    approve(known, "a")
    approve(other, "a", version="other")
    a, b = run(known, task_type=EXPENSE, amount_usd=30_000), run(other, task_type=EXPENSE, amount_usd=30_000)
    assert a["as_of"] == "2023-05-11" and a["results"][0]["source"]["source_url"].startswith("https://gitlab.com/")
    assert b["as_of"] is None and b["results"][0]["source"]["source_url"] is None


def test_approver_id_never_leaves(repo):
    """approved_by(승인한 관리자 user_id)는 칸 이름도 값도 나가지 않는다. 사람 id 없는 approved=true만."""
    r = run(repo, task_type=EXPENSE, amount_usd=30_000)
    text = json.dumps(r, ensure_ascii=False)
    assert PERSON not in text and "approved_by" not in text and r["results"][0]["approved"] is True


def test_band_name_category_uses_band():
    """금액 칸이 없는 업무(Legal Contracts)는 band로 고른다. 없으면 실행기 BadRequest → invalid(note는 실행기 글)."""
    r = InMemoryDecisionRepo()
    approve(r, "l", cells=LEGAL_CELLS)
    ok = run(r, task_type=LEGAL, band="Standard Terms")
    assert ok["status"] == "ok" and ok["results"][0]["band_label"] == "Standard Terms"
    assert ok["results"][0]["approvers"] == DecisionExecutor(r).run(LEGAL, None, band="Standard Terms")["approvers"]
    bad = run(r, task_type=LEGAL)
    assert bad["status"] == "invalid" and "band" in bad["note"] and bad["retryable"] is False


# ---------- 실행기 오류 → 상태 ----------

def test_amount_in_two_bands_is_not_found_not_guessed(repo):
    """EC-03: $500,000은 두 구간에 함께 든다. 아래 구간을 고르지 않는다(AmbiguousBand 422 → not_found, band를 줘도 같다)."""
    for args in ({}, {"band": ">$250K up to $500K"}):
        r = run(repo, task_type=EXPENSE, amount_usd=500_000, **args)
        assert r["status"] == "not_found" and r["results"] == []
        assert "$250,000 초과 $500,000 이하" in r["note"] and "$500,000 이상 $1,000,000 이하" in r["note"]


def test_no_approved_table_is_not_ready_with_candidates():
    """그 업무 종류로 승인된 표 0개(AmbiguousTable) → not_ready("없다"가 아님) + 승인된 업무 종류 후보."""
    r = InMemoryDecisionRepo()
    assert run(r, task_type=EXPENSE, amount_usd=1)["status"] == "not_ready"
    approve(r, "l", cells=LEGAL_CELLS)
    out = run(r, task_type=EXPENSE, amount_usd=1)
    assert out["status"] == "not_ready" and out["retryable"] is False and LEGAL in out["note"]


def test_two_approved_tables_ask_for_table_id(repo):
    """승인된 표 2개 이상 → invalid + 후보 table_id. table_id를 주면 그 표로 실행한다."""
    approve(repo, "b")
    r = run(repo, task_type=EXPENSE, amount_usd=30_000)
    assert r["status"] == "invalid" and "dt_a" in r["note"] and "dt_b" in r["note"]
    ok = run(repo, task_type=EXPENSE, amount_usd=30_000, table_id="dt_b")
    assert ok["status"] == "ok" and ok["results"][0]["table_id"] == "dt_b"


def test_unapproved_table_is_not_ready_and_not_executed():
    """초안 표를 table_id로 불러도 실행기가 먼저 막는다(NotApproved 409 → not_ready)."""
    r = InMemoryDecisionRepo()
    r.queue_draft("d", DecisionTable(table_id="dt_draft", rule_seq=7, version_id=PINNED, cells=R.rules_from_cells(EXPENSE_CELLS),
                                     status="draft"), "s")
    out = run(r, task_type=EXPENSE, amount_usd=30_000, table_id="dt_draft")
    assert out["status"] == "not_ready" and out["results"] == [] and "draft" in out["note"]


@pytest.mark.parametrize("args,status", [
    ({"task_type": EXPENSE, "amount_usd": -1}, "invalid"),                       # 실행기 check_amount
    ({"task_type": EXPENSE, "amount_usd": 30_000, "table_id": "dt_none"}, "not_found"),
    ({"task_type": "Other category", "amount_usd": 30_000, "table_id": "dt_a"}, "not_found"),
    ({"task_type": EXPENSE, "amount_usd": 30_000, "band": "$9M to $10M"}, "not_found"),
])
def test_executor_errors_map_to_states(repo, args, status):
    r = run(repo, **args)
    assert r["status"] == status and r["results"] == [] and r["note"]


@pytest.mark.parametrize("args", [{"task_type": ""}, {"task_type": "   "}, {"task_type": "x" * 201},
                                  {"task_type": EXPENSE, "table_id": ""}, {"task_type": EXPENSE, "band": " "},
                                  {"task_type": EXPENSE, "band": "b" * 201}])
def test_bad_input_is_invalid_without_touching_the_store(args):
    spy = Spy()
    r = run(spy, **args)
    assert r["status"] == "invalid" and r["retryable"] is False and spy.calls == 0


@pytest.mark.parametrize("amount", ["30000", True])
def test_amount_must_be_a_json_number_like_http(repo, amount):
    """HTTP는 글·불리언 금액을 400으로 막는다(rules.check_amount). MCP도 실행하지 않는다(기본 float는 true를 1로 받아 실행했다)."""
    res = call(make(repo), {"task_type": EXPENSE, "amount_usd": amount})
    assert res.is_error and not (res.structured_content or {}).get("results")


def test_private_address_in_table_text_is_marked():
    """결정표 글 칸도 비공개 주소를 [비공개 문서]로 바꿔 보낸다(server.redact)."""
    r = InMemoryDecisionRepo()
    rule = {"category": "X", "band": "See [doc](https://internal.gitlab.com/x/y)", "band_lo": None, "band_hi": None,
            "approvers": ["CEO"], "financial_approvers": [], "cooperating_depts": [], "range_note": None}
    approve(r, "p", rules=[rule])
    out = run(r, task_type="X")
    text = json.dumps(out, ensure_ascii=False)
    assert out["status"] == "ok" and "internal.gitlab.com" not in text and server.PRIVATE_MARK in text


# ---------- 저장소 ----------

def test_no_store_and_no_database_url_is_not_ready(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(server, "_pg", None)
    r = run(None, task_type=EXPENSE, amount_usd=1)
    assert r["status"] == "not_ready" and "DATABASE_URL" in r["note"] and r["retryable"] is False


def test_store_failure_is_unavailable_without_detail():
    import psycopg
    secret = "postgresql://app:pw@db.internal:5432/app"
    r = run(Spy(exc=psycopg.OperationalError(f"connection to {secret} failed")), task_type=EXPENSE, amount_usd=1)
    assert r["status"] == "unavailable" and r["retryable"] is True and secret not in json.dumps(r)


def test_missing_table_is_not_ready():
    from psycopg.errors import UndefinedTable
    r = run(Spy(exc=UndefinedTable('relation "decision_tables" does not exist')), task_type=EXPENSE, amount_usd=1)
    assert r["status"] == "not_ready" and "decision_tables" in r["note"]
