"""결정표 실행·승인 API (SDD 5장 API 표, docs/specs/decision-approval.md How).

- `POST /decision-tables/{table_id}/run`: 로그인. 지정한 표를 LLM 없이 실행한다.
- `POST /decision-tables/run`: 로그인. 표를 모를 때 업무 종류로 승인된 표가 정확히 1개면 실행한다 (EC-04, AC-06).
- `GET /decision-tables`: 로그인. 승인된 결정표 목록 (SDD 5장). 금액은 원문 표기와 함께 정확한 금액 표기(`band_label`)를 낸다.
- `POST /decision-tables/convert`: 관리자와 CSRF. 권한표 한 업무 종류를 LLM 초안으로 바꿔 승인 대기까지 간다 (AC-03).
- `GET /approvals`: 관리자. 승인 대기 목록과 초안, 셀 대조표. 쟁점표 건은 쟁점표 본문, 팀 실패 알림 건은 실패한 팀(`failed_teams`).
- `GET /approvals/{approval_id}`: 관리자. 승인 건 하나(끝난 건 포함)와 그래프 재개 기록(`resume_count`, `duplicate_ignored_count`, `last_resumed_at`, `last_resume_result`).
  같은 건에 결정이 여러 번 와도 `resume_count`는 그래프가 실제로 돈 횟수만 센다(같은 결정 재전송은 `duplicate_ignored_count`). 저장소는 `record_resume`, Postgres 칸은 `db/112_approval_resume_log.sql`이다.
- `POST /approvals/{approval_id}`: 관리자와 CSRF. 그래프를 재개한다. 결정표와 쟁점표는 `{approve, comment}`, 팀 실패 알림은 `{action: retry | mark_unreviewed, comment}`로 같은 경로다.

규칙
- 코드: 400 형식·음수·필수 값 누락, 403 관리자 아님(승인 라우트), 404 없는 표·업무·구간, 409 미승인, 그 업무 종류로 승인된 표가 0개·2개 이상,
  이미 끝난 승인 건에 다른 결정, 422 금액이 두 구간에 함께 듦(`band`를 줘도 같다). FastAPI의 본문 검증이 내는 422와 섞이지 않도록 본문을 직접 읽어 검사한다.
- `decided_by`는 로그인한 관리자로 채운다. 요청 본문의 값은 읽지 않는다.
- 저장소와 그래프는 `app.state.decision_repo`, `app.state.decision_graph`, `app.state.review_graph`에서 읽는다. 앱 시작에서 `open_decision_runtime()`이 채운다.
  합동 검토를 질문 그래프의 하위 그래프로 돌리면 `app.state.review_graph`에는 그 질문 그래프를 둔다. 같은 체크포인터에서 대화를 시작한 그래프로 재개해야 한다.
- 재개 뒤 저장 실패: 사람 결정은 체크포인트에 남고 승인 건은 `pending`인 채 그래프가 `finalize` 앞에 멈춘다. 503(`save_failed`)으로 알리고, 승인함에는 `save_failed: true`로 보인다.
  같은 결정을 다시 보내면 그 노드만 다시 돈다(저장은 같은 번호로 두 번 돌아도 한 건). 다른 결정은 409다. 이미 접수된 결정을 말없이 바꾸지 않는다.
- 같은 승인 건에 동시에 온 요청은 하나씩 처리한다(`_decision_lock`). 프로세스 안은 스레드 잠금, 인스턴스 사이는 Postgres 자문 잠금(`pg_advisory_xact_lock`)이 막는다.
  뒤 요청은 끝난 건의 재전송으로 처리되어 그래프를 다시 재개하지 않는다. 잠금을 못 잡으면(대기 시간 초과, DB 오류) 503(`save_failed`)이다.
- 팀 실패 알림의 결정 뒤에는 그래프가 다음 단계로 이어져 응답의 `next_approval`에 다음 승인 건이 온다. 다음 단계에서 실패하면 같은 503이고 같은 결정을 다시 보내면 이어서 돈다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from langgraph.types import Command
from pydantic import BaseModel, model_serializer
from starlette.requests import Request

from backend.auth import (
    AuthStore,
    AuthUser,
    TokenRevocationStore,
    create_current_user_dependency,
    create_require_admin_dependency,
    require_csrf,
)
from backend.graph.checkpoint import is_restart_safe, open_persistence
from backend.graph.decision import rules as R
from backend.graph.decision.convert import ERR_DRAFT, build_convert_graph, pending_interrupt, stalled_state, unfinished_state
from backend.graph.decision.execute import DecisionExecutor
from backend.graph.decision.repo import ISSUE_KIND, KIND, TEAM_FAILED_KIND, InMemoryDecisionRepo, PostgresDecisionRepo, new_id, table_category, team_resolution
from backend.graph.departments.review import TEAM_ACTIONS, build_review_graph
from backend.graph.departments.store import InMemoryIssueTableStore, PgIssueTableStore
from backend.rag.ingest.handbook import AUTHZ_COMMIT, AUTHZ_PATH, rule_seq
from backend.schemas import Decision
from backend.services.auth_store import _default_connect
from backend.services.llm import is_demo_mode

log = logging.getLogger(__name__)

AUTHZ_CELLS_FILE = Path(__file__).resolve().parents[3] / "data" / "parsed" / "authz_cells.jsonl"
AUTHZ_VERSION_ID = AUTHZ_COMMIT[:12]
MSG_SAVE_FAILED = "결정을 끝까지 처리하지 못했다. 같은 결정을 다시 보내면 이어서 한다"

RESUME_MESSAGES = {
    "comment_required": "원문과 다른 칸이 있는 초안을 승인하려면 comment가 필요하다",
    "approver_missing": "승인에는 승인한 관리자가 필요하다",
    "approval_id_mismatch": "승인 건 번호가 멈춘 승인 요청과 다르다",
    "bad_format": "승인 값의 형식이 틀렸다",
    "bad_action": "action은 retry 또는 mark_unreviewed여야 한다",
}


class RunSource(BaseModel):
    rule_seq: int
    category: str
    band: str  # 권한표 원문 표기 그대로
    article: str
    source_url: str | None = None


class RunResponse(BaseModel):
    table_id: str
    version_id: str
    band_label: str  # 정확한 금액 표기. 금액 없는 구간은 원문 이름
    range_note: str | None = None
    approvers: list[str]  # 승인 순서: 업무 승인 다음 재무 승인
    functional_approvers: list[str]
    financial_approvers: list[str]
    cooperating: list[str]  # 승인이 아닌 표시(Signs, Recommends 등)
    source: RunSource


class DecisionTableItem(BaseModel):
    """승인된 결정표 한 건. `cells`의 규칙마다 정확한 금액 표기 `band_label`을 더한다. 승인한 관리자 id는 일반 사용자 목록에 내지 않는다."""

    table_id: str
    rule_seq: int
    version_id: str
    category: str
    status: str
    cells: list[dict]


class _TeamResolutionOnly(BaseModel):
    """`resolution` 칸은 팀 실패 알림 건에만 나간다. 다른 kind의 응답 모양은 그대로다."""

    kind: str
    resolution: str | None = None

    @model_serializer(mode="wrap")
    def _hide_resolution(self, handler):
        data = handler(self)
        if self.kind != TEAM_FAILED_KIND:
            data.pop("resolution", None)
        return data


class ApprovalView(_TeamResolutionOnly):
    """`ApprovalItem`과 같은 이름에 승인 화면에 필요한 값을 더했다. 결정표 건은 초안과 셀 대조표, 쟁점표 건은 `issue_table`, 팀 실패 알림 건은 `failed_teams`다.
    `save_failed`는 결정을 받았지만 저장에 실패해 같은 결정을 다시 보내야 하는 건이고, 팀 실패 알림이면 `resolution`에 접수된 행동이 보인다."""

    approval_id: str
    summary: str
    created_at: datetime
    table_id: str | None = None
    draft: list[dict] | None = None
    comparison: dict | None = None
    rejected_resume: str | None = None
    issue_table: dict | None = None
    failed_teams: list[dict] | None = None
    save_failed: bool = False
    status: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    # 그래프 재개 기록. `resume_count`는 결정이 그래프를 실제로 돌린 횟수, `duplicate_ignored_count`는 같은 결정의 재전송이라 돌리지 않고 넘긴 횟수다.
    # 같은 건에 결정이 동시에 여러 번 와도 `resume_count`는 1이어야 한다. `last_resume_result`는 resumed | resume_failed | rejected_value | duplicate_ignored.
    resume_count: int = 0
    duplicate_ignored_count: int = 0
    last_resumed_at: datetime | None = None
    last_resume_result: str | None = None


class DecisionResult(_TeamResolutionOnly):
    """쟁점표 반려와 팀 실패 알림은 저장된 표가 없어 `table_id`가 비어 있다. `next_approval`은 팀 실패 알림 건에서만 채운다.
    팀 실패 알림의 `status`는 저장용 값이다. 사람이 고른 행동은 `resolution`(`retry` | `mark_unreviewed`)으로 읽는다."""

    approval_id: str
    status: str
    table_id: str | None = None
    decided_by: str | None = None
    comment: str = ""
    next_approval: dict | None = None


def _http(e: R.DecisionError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"reason": e.reason, "message": e.message})


def _bad(message: str) -> HTTPException:
    return _http(R.BadRequest(message))


def _state(request: Request, name: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(status_code=503, detail="결정표 저장소를 사용할 수 없습니다.")
    return value


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        raise _bad("요청 본문이 JSON이 아니다") from None


def _parse_run(body: Any) -> tuple[str, Any, str | None]:
    if not isinstance(body, dict):
        raise _bad("요청 본문은 JSON 객체여야 한다")
    task_type, amount, band = body.get("task_type"), body.get("amount_usd"), body.get("band")
    if not isinstance(task_type, str) or not task_type.strip():
        raise _bad("task_type이 필요하다")
    if band is not None and (not isinstance(band, str) or not band.strip()):
        raise _bad("band는 비어 있지 않은 문자열이어야 한다")
    try:
        if amount is not None:
            R.check_amount(amount)
    except R.DecisionError as e:
        raise _http(e) from None
    return task_type, amount, band


def _parse_common(approval_id: str, body: Any) -> str:
    """본문의 공통 칸을 검사하고 comment를 돌려준다."""
    if not isinstance(body, dict):
        raise _bad("요청 본문은 JSON 객체여야 한다")
    if body.get("approval_id", approval_id) != approval_id:
        raise _bad("본문의 approval_id가 주소와 다르다")
    comment = body.get("comment", "")
    if not isinstance(comment, str):
        raise _bad("comment는 문자열이어야 한다")
    return comment


def _parse_decision(approval_id: str, body: Any, admin: AuthUser) -> Decision:
    comment = _parse_common(approval_id, body)
    approve = body.get("approve")
    if not isinstance(approve, bool):
        raise _bad("approve는 true 또는 false여야 한다")
    return Decision(approval_id=approval_id, approve=approve, comment=comment, decided_by=str(admin.user_id))


def _parse_team_action(approval_id: str, body: Any, admin: AuthUser) -> dict:
    """팀 실패 알림의 재개 값. `action` 값은 여기서 거르지 않는다: 틀린 값은 그래프가 `rejected_resume`으로 같은 요청을 다시 올린다."""
    comment = _parse_common(approval_id, body)
    return {"approval_id": approval_id, "action": body.get("action"), "comment": comment, "decided_by": str(admin.user_id)}


def _parse_convert(body: Any) -> str:
    if not isinstance(body, dict):
        raise _bad("요청 본문은 JSON 객체여야 한다")
    category = body.get("category")
    if not isinstance(category, str) or not category.strip():
        raise _bad("category(권한표 업무 종류)가 필요하다")
    return category


def _authz_cells(category: str) -> list[dict]:
    """그 업무 종류의 권한표 칸. 표기는 원문 그대로 돌려준다. 칸 파일이 없으면 503, 없는 업무 종류는 404다."""
    try:
        lines = AUTHZ_CELLS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise HTTPException(status_code=503, detail="권한표 칸 파일을 읽을 수 없습니다.") from None
    cells = [c for c in map(json.loads, lines) if R.norm(c["category"]) == R.norm(category)]
    if not cells:
        raise R.NotFound("권한표에 그 업무 종류가 없다")
    return cells


def _known_category(category: str) -> bool:
    """권한표에 그 업무 종류가 있나. 칸 파일을 못 읽으면 모른다고 보지 않는다(없는 업무로 오판해 404를 내지 않도록)."""
    try:
        lines = AUTHZ_CELLS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return True
    return any(R.norm(json.loads(line)["category"]) == R.norm(category) for line in lines if line.strip())


def _check_convertible(repo, category: str) -> None:
    """같은 업무 종류로 승인된 표가 둘이 되면 실행이 거절되고(AC-06), 대기 건이 둘이면 승인함이 겹치므로 시작 전에 막는다."""
    if repo.find_approved(category):
        raise R.Conflict("이 업무 종류로 승인된 결정표가 이미 있다")
    for rec in repo.list_pending():
        if rec.kind == KIND and R.norm(table_category(repo.get_table(rec.target_id))) == R.norm(category):
            raise R.Conflict("이 업무 종류의 결정표 초안이 이미 승인을 기다리고 있다")


def _table_item(table) -> DecisionTableItem:
    cells = table.cells if isinstance(table.cells, list) else []
    return DecisionTableItem(table_id=table.table_id, rule_seq=table.rule_seq, version_id=table.version_id, category=table_category(table),
                             status=table.status, cells=[{**r, "band_label": R.band_label(r, cells)} for r in cells])


EXAMPLE_LABEL = "예시 응답"


def _example_view(category: str, cells: list[dict]) -> ApprovalView:
    """키 없는 데모(`is_demo_mode()`)에서 결정표 변환 대신 내는 고정 응답(L-23). 승인함에 올리지 않고 저장도 하지 않는다.
    초안은 LLM이 아니라 권한표 칸에서 코드로 만든 기준 규칙(`rules_from_cells`)이라 지어낸 값이 없고, 쓸 수 있는 결정표가 아니다."""
    rules = R.rules_from_cells(cells)
    return ApprovalView(approval_id="example-convert", kind=KIND, summary=f"{EXAMPLE_LABEL}: {category} 결정표 초안 (키 없는 데모, 저장·승인되지 않음)",
                        created_at=datetime.now(), status="example",
                        draft=[{**r, "band_label": R.band_label(r, rules)} for r in rules])


def _paused(graph, rec) -> tuple[dict | None, dict | None]:
    """(승인을 기다리는 interrupt 값, 저장 실패로 멈춘 상태 값). 이 승인 건의 것이 아니면 버린다: 같은 대화에서 그래프가 이미 다른 일로 넘어간 경우다."""
    pending = pending_interrupt(graph, rec.thread_id)
    if pending is not None:
        return (pending if pending.get("approval_id") == rec.approval_id else None), None
    stalled = stalled_state(graph, rec.thread_id)
    return None, (stalled if stalled and stalled.get("approval_id") == rec.approval_id else None)


def _view(rec, graph) -> ApprovalView:
    view = ApprovalView(approval_id=rec.approval_id, kind=rec.kind, summary=rec.summary, created_at=rec.created_at, status=rec.status,
                        decided_by=rec.decided_by, decided_at=rec.decided_at, resume_count=rec.resume_count,
                        duplicate_ignored_count=rec.duplicate_ignored_count, last_resumed_at=rec.last_resumed_at,
                        last_resume_result=rec.last_resume_result)
    if rec.kind == KIND:
        view.table_id = rec.target_id
    if graph is None:
        return view
    pending, stalled = _paused(graph, rec)
    values = pending or stalled
    view.save_failed = stalled is not None
    if not values:
        return view
    view.rejected_resume = (pending or {}).get("rejected_resume")
    if rec.kind == KIND:
        rules = pending["draft"] if pending else stalled["draft_rules"]
        view.draft = [{**r, "band_label": R.band_label(r, rules)} for r in rules]
        view.comparison = values["comparison"]
    elif rec.kind == TEAM_FAILED_KIND:
        view.failed_teams = values["failed_teams"]
        view.resolution = stalled["decision"]["action"] if stalled else None
    else:
        view.issue_table = values["table"]
    return view


def _next_approval(graph, rec) -> dict | None:
    """결정 뒤 같은 대화가 다음 승인 건에서 멈췄으면 그 건."""
    pending = pending_interrupt(graph, rec.thread_id)
    if pending is None or pending.get("approval_id") == rec.approval_id:
        return None
    return {k: pending.get(k) for k in ("approval_id", "kind", "summary")}


def _result(rec, graph=None) -> DecisionResult:
    out = DecisionResult(approval_id=rec.approval_id, kind=rec.kind, status=rec.status, decided_by=rec.decided_by, comment=rec.comment,
                         table_id=rec.target_id if rec.kind == KIND or (rec.kind == ISSUE_KIND and rec.status == "approved") else None)
    if rec.kind == TEAM_FAILED_KIND:
        out.resolution = team_resolution(rec)
        out.next_approval = _next_approval(graph, rec) if graph is not None else None
    return out


def _note_resume(repo, approval_id: str, result: str) -> None:
    """재개 기록을 남긴다. 기록이 실패해도(예: `db/112_approval_resume_log.sql` 적용 전) 결정 처리는 막지 않는다."""
    try:
        repo.record_resume(approval_id, result)
    except Exception as exc:  # noqa: BLE001 - DB 오류 등. 메시지에 접속 문자열이 섞일 수 있어 종류만 남긴다
        log.warning("재개 기록 실패 %s: %s", approval_id, type(exc).__name__)


def _invoke(graph, repo, rec, inp, cfg) -> None:
    """그래프를 재개한다. 오류로 끝나면 `resume_failed`를 기록하고 오류를 그대로 올린다. 성공 기록은 부른 쪽이 결과를 보고 남긴다."""
    try:
        graph.invoke(inp, cfg)
    except Exception:
        _note_resume(repo, rec.approval_id, "resume_failed")
        raise


def _resume(graph, repo, rec, value: dict, approve: bool | None) -> None:
    """승인을 기다리면 사람 결정(`value`)으로 재개하고, 결정을 적다 실패해 멈췄으면 같은 결정일 때 그 노드만 다시 돌린다. `approve`가 None이면 알 수 없는 값이다.
    그래프를 돌릴 때마다 승인 건에 재개 기록을 남긴다(`ApprovalRecord.resume_count` 등)."""
    cfg = {"configurable": {"thread_id": rec.thread_id}}
    pending, stalled = _paused(graph, rec)
    if pending is not None:
        _invoke(graph, repo, rec, Command(resume=value), cfg)
    elif stalled is None:
        raise R.Conflict("승인을 기다리는 그래프를 찾을 수 없다")
    elif approve is None:
        raise _bad(RESUME_MESSAGES["bad_action"])
    elif stalled["decision"]["approve"] is not approve:
        raise R.AlreadyDecided("다른 결정이 이미 접수되어 저장을 기다리고 있다. 같은 결정만 다시 보낼 수 있다")
    else:
        _invoke(graph, repo, rec, None, cfg)
    again = pending_interrupt(graph, rec.thread_id)
    if again is not None and again.get("approval_id") == rec.approval_id:   # 틀린 재개 값: 상태는 그대로이고 같은 승인 요청이 다시 올라와 있다
        _note_resume(repo, rec.approval_id, "rejected_value")
        why = again.get("rejected_resume", "bad_format")
        raise HTTPException(status_code=400, detail={"reason": why, "message": RESUME_MESSAGES.get(why, why)})
    _note_resume(repo, rec.approval_id, "resumed")


def _repeat_decision(request: Request, repo, rec, approve: bool | None, decided_by: str | None, comment: str):
    """이미 끝난 건: 같은 결정은 그대로 지나가고 다른 결정은 409다. 팀 실패 알림은 결정 뒤 단계에서 멈췄으면 이어서 돌리고, 쓴 그래프를 돌려준다."""
    if approve is None:
        raise _bad(RESUME_MESSAGES["bad_action"])
    decide = repo.decide if rec.kind == KIND else repo.decide_review_item
    decide(rec.approval_id, approve, decided_by, comment)
    if rec.kind != TEAM_FAILED_KIND:
        _note_resume(repo, rec.approval_id, "duplicate_ignored")
        return None
    graph = _state(request, "review_graph")
    left = unfinished_state(graph, rec.thread_id)
    if left and left.get("approval_id") == rec.approval_id:
        _invoke(graph, repo, rec, None, {"configurable": {"thread_id": rec.thread_id}})
        _note_resume(repo, rec.approval_id, "resumed")
    else:
        _note_resume(repo, rec.approval_id, "duplicate_ignored")
    return graph


def create_decision_router(
    *, store: AuthStore, secret: str | None = None, revocation_store: TokenRevocationStore | None = None
) -> APIRouter:
    """인증 라우터와 같은 `store`, `secret`을 넘긴다(로컬 데모의 무작위 서명 키도 같아야 한다)."""
    router = APIRouter()
    current_user = create_current_user_dependency(store=store, secret=secret, revocation_store=revocation_store)
    require_admin = create_require_admin_dependency(store=store, secret=secret, revocation_store=revocation_store)

    def execute(request: Request, table_id: str | None, body: Any) -> dict:
        task_type, amount, band = _parse_run(body)
        try:
            return DecisionExecutor(_state(request, "decision_repo")).run(task_type, amount, table_id=table_id, band=band)
        except R.AmbiguousTable as e:
            if table_id is None and task_type and not _known_category(task_type):   # C-23: 없는 업무 종류는 404, 표가 0개·2개 이상인 모호함만 409
                raise _http(R.NotFound("권한표에 그 업무 종류가 없다")) from None
            raise _http(e) from None
        except R.DecisionError as e:
            raise _http(e) from None

    @router.post("/decision-tables/run", response_model=RunResponse)
    def run_by_task_type(request: Request, _user: AuthUser = Depends(current_user), body: Any = Depends(_json_body)) -> dict:
        return execute(request, None, body)

    @router.post("/decision-tables/{table_id}/run", response_model=RunResponse)
    def run_table(table_id: str, request: Request, _user: AuthUser = Depends(current_user), body: Any = Depends(_json_body)) -> dict:
        return execute(request, table_id, body)

    @router.get("/decision-tables", response_model=list[DecisionTableItem])
    def list_decision_tables(request: Request, _user: AuthUser = Depends(current_user)) -> list[DecisionTableItem]:
        return [_table_item(t) for t in _state(request, "decision_repo").list_approved()]

    @router.post("/decision-tables/convert", response_model=ApprovalView, status_code=201)
    def start_convert(
        request: Request, admin: AuthUser = Depends(require_admin), _csrf: None = Depends(require_csrf), body: Any = Depends(_json_body),
    ) -> ApprovalView:
        repo, graph = _state(request, "decision_repo"), _state(request, "decision_graph")
        category = _parse_convert(body)
        thread_id = new_id("convert")
        cells, cells_ok = [], False
        try:
            cells = _authz_cells(category)
            category = cells[0]["category"]                    # 원문 글자 그대로. 그래프가 칸의 업무 종류와 대조한다
            _check_convertible(repo, category)
            cells_ok = True
            out = graph.invoke({"category": category, "rule_seq": rule_seq(AUTHZ_PATH), "version_id": AUTHZ_VERSION_ID, "source_cells": cells,
                                "requested_by": str(admin.user_id)}, {"configurable": {"thread_id": thread_id}})
            if out.get("error") and is_demo_mode():            # L-23: 키 없는 데모는 녹화에 초안이 없어 늘 여기로 온다
                return _example_view(category, cells)
            if out.get("error"):                               # EC-05: 재시도 없이 실패로 끝낸다. 승인함에 올라가지 않는다
                raise HTTPException(status_code=502, detail={"reason": out["error"], "message": "초안을 읽지 못해 승인함에 올리지 않았다" if out["error"] == ERR_DRAFT else "권한표 칸을 읽지 못했다"})
            pending = pending_interrupt(graph, thread_id)
            if pending is None:
                raise R.Conflict("초안이 승인 대기에 이르지 못했다")
            return _view(repo.get_approval(pending["approval_id"]), graph)
        except R.DecisionError as e:
            raise _http(e) from None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - LLM·DB 오류. 메시지에 접속 문자열이 섞일 수 있어 종류만 남긴다
            log.warning("결정표 변환 실패: %s", type(exc).__name__)
            if is_demo_mode() and cells_ok:
                return _example_view(category, cells)
            raise HTTPException(status_code=503, detail={"reason": "convert_failed", "message": "결정표 초안을 만들지 못했다"}) from None

    @router.get("/approvals", response_model=None)
    def list_approvals(request: Request, response: Response) -> list[ApprovalView] | FileResponse:
        # 화면 주소와 API 주소가 같으므로 HTML·JSON 둘 다 캐시 금지와 Accept별 구분(/admin/users 와 같은 규칙)
        if "text/html" in request.headers.get("accept", ""):
            react_index = getattr(request.app.state, "react_index", None)
            if react_index is not None:
                return FileResponse(react_index, headers={"Cache-Control": "no-store", "Vary": "Accept"})
        require_admin(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Accept"
        repo = _state(request, "decision_repo")
        review = getattr(request.app.state, "review_graph", None)
        graphs = {KIND: _state(request, "decision_graph"), ISSUE_KIND: review, TEAM_FAILED_KIND: review}
        return [_view(rec, graphs.get(rec.kind)) for rec in repo.list_pending()]

    @router.get("/approvals/{approval_id}", response_model=ApprovalView)
    def get_approval(approval_id: str, request: Request, _admin: AuthUser = Depends(require_admin)) -> ApprovalView:
        """승인 건 하나의 상태와 그래프 재개 기록(`resume_count`, `duplicate_ignored_count`, `last_resumed_at`, `last_resume_result`). 끝난 건도 읽는다.
        결정 응답은 같은 결정을 다시 보내도 같게 유지하므로 재개 횟수는 여기서 읽는다."""
        repo = _state(request, "decision_repo")
        try:
            rec = repo.get_approval(approval_id)
        except R.DecisionError as e:
            raise _http(e) from None
        view = _view(rec, None)
        view.resolution = team_resolution(rec) if rec.kind == TEAM_FAILED_KIND else None
        return view

    @router.post("/approvals/{approval_id}", response_model=DecisionResult)
    def decide(
        approval_id: str, request: Request, admin: AuthUser = Depends(require_admin),
        _csrf: None = Depends(require_csrf), body: Any = Depends(_json_body),
    ) -> DecisionResult:
        repo = _state(request, "decision_repo")
        with _decide_errors(approval_id), _decision_lock(approval_id, repo):   # 같은 승인 건의 동시 요청은 인스턴스가 달라도 차례로: 뒤 요청은 끝난 건으로 보고 재개하지 않는다
            rec = repo.get_approval(approval_id)
            if rec.kind == TEAM_FAILED_KIND:
                value = _parse_team_action(approval_id, body, admin)
                approve = value["action"] == "retry" if value["action"] in TEAM_ACTIONS else None
            else:
                decision = _parse_decision(approval_id, body, admin)
                value, approve = decision.model_dump(), decision.approve
            if rec.status != "pending":
                graph = _repeat_decision(request, repo, rec, approve, value["decided_by"], value["comment"])
                return _result(repo.get_approval(approval_id), graph)
            graph = _state(request, "decision_graph" if rec.kind == KIND else "review_graph")
            _resume(graph, repo, rec, value, approve)
            rec = repo.get_approval(approval_id)
            if rec.status == "pending":      # 그래프는 끝났는데 승인 건이 그대로다: 성공으로 돌려주지 않는다
                raise RuntimeError("approval still pending after resume")
            return _result(rec, graph)

    return router


_LOCKS_GUARD = threading.Lock()
_DECISION_LOCKS: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()


@contextmanager
def _decision_lock(approval_id: str, repo: Any = None) -> Iterator[None]:
    """같은 승인 건의 결정 요청을 하나씩 처리한다. 없으면 동시에 온 같은 결정 두 건이 둘 다 `pending`을 보고
    그래프를 두 번 재개했다(저장은 승인 건 번호로 한 건이지만 재개 노드가 두 번 돈다).
    프로세스 안은 스레드 잠금이 막고, 저장소가 Postgres면 DB 자문 잠금(`PostgresDecisionRepo.decision_lock`)이 인스턴스 사이도 막는다.
    메모리 저장소는 프로세스 하나뿐이므로 스레드 잠금만 쓴다."""
    with _LOCKS_GUARD:
        lock = _DECISION_LOCKS.get(approval_id)
        if lock is None:
            lock = _DECISION_LOCKS[approval_id] = threading.Lock()
    with lock:
        db_lock = getattr(repo, "decision_lock", None)
        with db_lock(approval_id) if db_lock is not None else nullcontext():
            yield


@contextmanager
def _decide_errors(approval_id: str) -> Iterator[None]:
    """결정 처리의 오류를 응답으로 바꾼다. 규칙은 모듈 설명."""
    try:
        yield
    except R.DecisionError as e:
        raise _http(e) from None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - DB 오류 등. 메시지에 접속 문자열이 섞일 수 있어 종류만 남긴다
        log.warning("승인 저장 실패 %s: %s", approval_id, type(exc).__name__)
        raise HTTPException(status_code=503, detail={"reason": "save_failed", "message": MSG_SAVE_FAILED}) from None


class _LazyChatModel:
    """채팅 모델을 초안을 쓸 때 만든다. 승인 재개와 실행은 LLM을 쓰지 않으므로 키 없이도 서버가 떠야 한다."""

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        from backend.services.llm import get_chat_model

        return get_chat_model().invoke(*args, **kwargs)


@contextmanager
def open_decision_runtime(app: Any) -> Iterator[None]:
    """앱 시작(lifespan)에서 체크포인터, 결정표 저장소, 변환 그래프, 합동 검토 그래프를 열어 `app.state`에 둔다.
    체크포인터와 Store(`app.state.checkpointer`, `app.state.store`), 쟁점표 저장소(`app.state.issue_store`)도 같이 두어 질문 그래프가 나눠 쓴다.
    DB가 없으면 메모리로 내려가지 않고 경고를 남기며, 결정표 라우트는 503을 돌려준다(`/health`와 로그인은 그대로 뜬다)."""
    try:
        persistence = open_persistence()
        saver, store = persistence.__enter__()
    except ValueError:        # CHECKPOINTER 값이 틀린 설정 오류는 시작을 막는다
        raise
    except Exception as exc:  # noqa: BLE001 - DB 연결 오류 등. 접속 문자열이 섞일 수 있어 종류만 남긴다
        log.warning("결정표 저장소를 열지 못함: %s", type(exc).__name__)
        yield
        return
    try:
        durable = is_restart_safe(saver)
        repo = PostgresDecisionRepo(saver.conn) if durable else InMemoryDecisionRepo()
        # 쟁점표 저장소는 튜플 행을 읽으므로 dict_row 풀(saver.conn)을 나눠 쓰지 않고 호출마다 연결한다. Postgres 체크포인터는 DATABASE_URL 없이 열리지 않는다
        issue_store = PgIssueTableStore(_default_connect(os.environ["DATABASE_URL"])) if durable else InMemoryIssueTableStore()
        app.state.checkpointer, app.state.store, app.state.issue_store = saver, store, issue_store   # 질문 그래프(backend/main.py)가 같은 것을 쓴다
        app.state.decision_repo = repo
        app.state.decision_graph = build_convert_graph(_LazyChatModel(), repo, saver, store)
        app.state.review_graph = build_review_graph(None, saver, llm=_LazyChatModel(), store=issue_store, approvals=repo)
        yield
    finally:
        app.state.decision_repo = app.state.decision_graph = app.state.review_graph = None
        app.state.checkpointer = app.state.store = app.state.issue_store = None
        persistence.__exit__(None, None, None)
