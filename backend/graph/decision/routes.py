"""결정표 실행·승인 API (SDD 5장 API 표, docs/specs/decision-approval.md How).

- `POST /decision-tables/{table_id}/run`: 로그인. 지정한 표를 LLM 없이 실행한다.
- `POST /decision-tables/run`: 로그인. 표를 모를 때 업무 종류로 승인된 표가 정확히 1개면 실행한다 (EC-04, AC-06).
- `GET /decision-tables`: 로그인. 승인된 결정표 목록 (SDD 5장). 금액은 원문 표기와 함께 정확한 금액 표기(`band_label`)를 낸다.
- `POST /decision-tables/convert`: 관리자와 CSRF. 권한표 한 업무 종류를 LLM 초안으로 바꿔 승인 대기까지 간다 (AC-03).
- `GET /approvals`: 관리자. 승인 대기 목록과 초안, 셀 대조표. 쟁점표 건은 쟁점표 본문, 팀 실패 알림 건은 실패한 팀(`failed_teams`).
- `POST /approvals/{approval_id}`: 관리자와 CSRF. 그래프를 재개한다. 결정표와 쟁점표는 `{approve, comment}`, 팀 실패 알림은 `{action: retry | mark_unreviewed, comment}`로 같은 경로다.

규칙
- 코드: 400 형식·음수·필수 값 누락, 403 관리자 아님(승인 라우트), 404 없는 표·업무·구간, 409 미승인, 그 업무 종류로 승인된 표가 0개·2개 이상,
  이미 끝난 승인 건에 다른 결정, 422 금액이 두 구간에 함께 듦(`band`를 줘도 같다). FastAPI의 본문 검증이 내는 422와 섞이지 않도록 본문을 직접 읽어 검사한다.
- `decided_by`는 로그인한 관리자로 채운다. 요청 본문의 값은 읽지 않는다.
- 저장소와 그래프는 `app.state.decision_repo`, `app.state.decision_graph`, `app.state.review_graph`에서 읽는다. 앱 시작에서 `open_decision_runtime()`이 채운다.
  합동 검토를 질문 그래프의 하위 그래프로 돌리면 `app.state.review_graph`에는 그 질문 그래프를 둔다. 같은 체크포인터에서 대화를 시작한 그래프로 재개해야 한다.
- 재개 뒤 저장 실패: 사람 결정은 체크포인트에 남고 승인 건은 `pending`인 채 그래프가 `finalize` 앞에 멈춘다. 503(`save_failed`)으로 알리고, 승인함에는 `save_failed: true`로 보인다.
  같은 결정을 다시 보내면 그 노드만 다시 돈다(저장은 같은 번호로 두 번 돌아도 한 건). 다른 결정은 409다. 이미 접수된 결정을 말없이 바꾸지 않는다.
- 팀 실패 알림의 결정 뒤에는 그래프가 다음 단계로 이어져 응답의 `next_approval`에 다음 승인 건이 온다. 다음 단계에서 실패하면 같은 503이고 같은 결정을 다시 보내면 이어서 돈다.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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


def _paused(graph, rec) -> tuple[dict | None, dict | None]:
    """(승인을 기다리는 interrupt 값, 저장 실패로 멈춘 상태 값). 이 승인 건의 것이 아니면 버린다: 같은 대화에서 그래프가 이미 다른 일로 넘어간 경우다."""
    pending = pending_interrupt(graph, rec.thread_id)
    if pending is not None:
        return (pending if pending.get("approval_id") == rec.approval_id else None), None
    stalled = stalled_state(graph, rec.thread_id)
    return None, (stalled if stalled and stalled.get("approval_id") == rec.approval_id else None)


def _view(rec, graph) -> ApprovalView:
    view = ApprovalView(approval_id=rec.approval_id, kind=rec.kind, summary=rec.summary, created_at=rec.created_at)
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


def _resume(graph, rec, value: dict, approve: bool | None) -> None:
    """승인을 기다리면 사람 결정(`value`)으로 재개하고, 결정을 적다 실패해 멈췄으면 같은 결정일 때 그 노드만 다시 돌린다. `approve`가 None이면 알 수 없는 값이다."""
    cfg = {"configurable": {"thread_id": rec.thread_id}}
    pending, stalled = _paused(graph, rec)
    if pending is not None:
        graph.invoke(Command(resume=value), cfg)
    elif stalled is None:
        raise R.Conflict("승인을 기다리는 그래프를 찾을 수 없다")
    elif approve is None:
        raise _bad(RESUME_MESSAGES["bad_action"])
    elif stalled["decision"]["approve"] is not approve:
        raise R.AlreadyDecided("다른 결정이 이미 접수되어 저장을 기다리고 있다. 같은 결정만 다시 보낼 수 있다")
    else:
        graph.invoke(None, cfg)
    again = pending_interrupt(graph, rec.thread_id)
    if again is not None and again.get("approval_id") == rec.approval_id:   # 틀린 재개 값: 상태는 그대로이고 같은 승인 요청이 다시 올라와 있다
        why = again.get("rejected_resume", "bad_format")
        raise HTTPException(status_code=400, detail={"reason": why, "message": RESUME_MESSAGES.get(why, why)})


def _repeat_decision(request: Request, repo, rec, approve: bool | None, decided_by: str | None, comment: str):
    """이미 끝난 건: 같은 결정은 그대로 지나가고 다른 결정은 409다. 팀 실패 알림은 결정 뒤 단계에서 멈췄으면 이어서 돌리고, 쓴 그래프를 돌려준다."""
    if approve is None:
        raise _bad(RESUME_MESSAGES["bad_action"])
    decide = repo.decide if rec.kind == KIND else repo.decide_review_item
    decide(rec.approval_id, approve, decided_by, comment)
    if rec.kind != TEAM_FAILED_KIND:
        return None
    graph = _state(request, "review_graph")
    left = unfinished_state(graph, rec.thread_id)
    if left and left.get("approval_id") == rec.approval_id:
        graph.invoke(None, {"configurable": {"thread_id": rec.thread_id}})
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
        try:
            cells = _authz_cells(category)
            category = cells[0]["category"]                    # 원문 글자 그대로. 그래프가 칸의 업무 종류와 대조한다
            _check_convertible(repo, category)
            out = graph.invoke({"category": category, "rule_seq": rule_seq(AUTHZ_PATH), "version_id": AUTHZ_VERSION_ID, "source_cells": cells,
                                "requested_by": str(admin.user_id)}, {"configurable": {"thread_id": thread_id}})
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
            raise HTTPException(status_code=503, detail={"reason": "convert_failed", "message": "결정표 초안을 만들지 못했다"}) from None

    @router.get("/approvals", response_model=list[ApprovalView])
    def list_approvals(request: Request, _admin: AuthUser = Depends(require_admin)) -> list[ApprovalView]:
        repo = _state(request, "decision_repo")
        review = getattr(request.app.state, "review_graph", None)
        graphs = {KIND: _state(request, "decision_graph"), ISSUE_KIND: review, TEAM_FAILED_KIND: review}
        return [_view(rec, graphs.get(rec.kind)) for rec in repo.list_pending()]

    @router.post("/approvals/{approval_id}", response_model=DecisionResult)
    def decide(
        approval_id: str, request: Request, admin: AuthUser = Depends(require_admin),
        _csrf: None = Depends(require_csrf), body: Any = Depends(_json_body),
    ) -> DecisionResult:
        repo = _state(request, "decision_repo")
        try:
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
            _resume(graph, rec, value, approve)
            rec = repo.get_approval(approval_id)
            if rec.status == "pending":      # 그래프는 끝났는데 승인 건이 그대로다: 성공으로 돌려주지 않는다
                raise RuntimeError("approval still pending after resume")
            return _result(rec, graph)
        except R.DecisionError as e:
            raise _http(e) from None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - DB 오류 등. 메시지에 접속 문자열이 섞일 수 있어 종류만 남긴다
            log.warning("승인 저장 실패 %s: %s", approval_id, type(exc).__name__)
            raise HTTPException(status_code=503, detail={"reason": "save_failed", "message": MSG_SAVE_FAILED}) from None

    return router


class _LazyChatModel:
    """채팅 모델을 초안을 쓸 때 만든다. 승인 재개와 실행은 LLM을 쓰지 않으므로 키 없이도 서버가 떠야 한다."""

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        from backend.services.llm import get_chat_model

        return get_chat_model().invoke(*args, **kwargs)


@contextmanager
def open_decision_runtime(app: Any) -> Iterator[None]:
    """앱 시작(lifespan)에서 체크포인터, 결정표 저장소, 변환 그래프, 합동 검토 그래프를 열어 `app.state`에 둔다.
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
        app.state.decision_repo = repo
        app.state.decision_graph = build_convert_graph(_LazyChatModel(), repo, saver, store)
        app.state.review_graph = build_review_graph(None, saver, llm=_LazyChatModel(), store=issue_store, approvals=repo)
        yield
    finally:
        app.state.decision_repo = app.state.decision_graph = app.state.review_graph = None
        persistence.__exit__(None, None, None)
