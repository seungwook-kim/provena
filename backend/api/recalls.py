"""답변 리콜 라우터 (F-02, F-05, F-08, docs/specs/recall.md, SDD 4-4).

- `GET /recalls`: 로그인. `{"items": [알림], "unread": int}`. 관리자는 전체 알림과 `review_queue`(관리자 검토함), `candidates`(함께 볼 정책),
  `judge_failures`(판정이 깨져 확인이 필요한 알림 id)를 더 받는다. 일반 사용자는 자기 알림 중 볼 수 있는 섹션의 것만 본다(EC-11, F-06).
  `unread`는 요청한 사람 자신의 확인하지 않은 알림 수다.
- `GET /recalls/{notice_id}`: 남의 알림·검토함 알림은 404 `not_found`(관리자는 모두 본다). `POST .../ack`(본인, CSRF), `POST .../feedback`(본인, 관리자는 전체, CSRF),
  `POST .../review`(관리자, CSRF, `{"action": "release"|"dismiss"}`).
- `GET /recalls/feedback-stats`(관리자), `GET /recalls/digests`(본인, 관리자는 전체), `POST /recalls/digest/flush`(관리자, CSRF), `POST /recalls/process-pending`(관리자, CSRF).
- `GET, POST /webhook-subscriptions`, `GET /webhook-deliveries`(관리자). `GET /maintenance-candidates`, `POST /maintenance-candidates/{id}`(관리자).
- `POST /webhooks/regulation-updated`: 서비스 키(`X-Service-Key` 또는 `Authorization: Bearer`, 환경변수 `SERVICE_API_KEY`). 없거나 틀리면 401,
  형식 오류는 400, 받으면 202이고 리콜은 응답 뒤 백그라운드로 돈다(EC-10, AC-06).
- `POST /impact-preview`(관리자, CSRF): 드라이런 영향 미리보기. 저장·알림·웹훅 없음.

알림 JSON 모양은 `backend/graph/recall/service.py`의 `notice_json` 한 곳에서 정한다. 계약(`backend/schemas/recall.py`)은 바꾸지 않고, 화면용 칸은 이 모양에만 있다.
웹훅 전송은 응답을 보낸 뒤 백그라운드로 한다(재시도 대기가 응답을 막지 않는다). 저장소가 없으면 503 `not_configured`.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.api.errors import ApiError
from backend.auth import AuthStore, AuthUser, TokenRevocationStore, create_current_user_dependency, create_require_admin_dependency, require_csrf
from backend.graph.recall.digest import flush_digests
from backend.graph.recall.feedback import summarize
from backend.graph.recall.process_pending import DEFAULT_LIMIT, MAX_LIMIT, process_pending
from backend.graph.recall.service import candidate_json, notice_json, user_visible
from backend.graph.recall.store import now_iso
from backend.graph.recall.webhook import SECRET_ENV, check_secret_ref, check_target_url, resolve_secret
from backend.schemas.recall import ChangedArticle

log = logging.getLogger(__name__)

SERVICE_KEY_ENV = "SERVICE_API_KEY"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MAX_EVENTS = 100          # /webhooks/regulation-updated 한 번에 받는 바뀐 섹션 수
MSG_NOT_FOUND = "리콜 알림을 찾을 수 없습니다."


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["release", "dismiss"]


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    useful: bool
    reason: str | None = Field(default=None, max_length=500)


class SubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=500)
    secret_ref: str = Field(default=SECRET_ENV, max_length=80)
    active: bool = True


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["needed", "not_needed"]


class RegulationUpdate(BaseModel):
    """`POST /webhooks/regulation-updated` 본문 한 건. 계약 `ChangedArticle`과 같은 칸이고 change_type이 없으면 modified로 본다."""
    model_config = ConfigDict(extra="forbid")
    rule_seq: int = Field(ge=0)
    article: str = Field(min_length=1, max_length=1000)
    old_version_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    new_version_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    change_type: Literal["added", "removed", "modified"] = "modified"


class ImpactPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    old: str | None = Field(default=None, max_length=500_000)
    new: str | None = Field(default=None, max_length=500_000)


class ImpactChange(RegulationUpdate):
    old_text: str | None = Field(default=None, max_length=200_000)
    new_text: str | None = Field(default=None, max_length=200_000)


class ImpactBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[ImpactChange] | None = Field(default=None, max_length=200)
    pages: list[ImpactPage] | None = Field(default=None, max_length=50)
    old_version_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    new_version_date: str | None = Field(default=None, pattern=DATE_PATTERN)


def service_of(request: Request) -> Any:
    svc = getattr(request.app.state, "recall_service", None)
    if svc is None:
        raise ApiError(503, "not_configured", "리콜 저장소를 사용할 수 없습니다.")
    return svc


def spa_page(request: Request) -> FileResponse | None:
    """브라우저가 화면 주소(/recalls, /changes)를 직접 열거나 새로 고치면 API JSON 대신 화면(index.html)을 준다(`/approvals`와 같은 규칙).
    Accept에 text/html이 있으면 화면이다. 로그인 확인보다 먼저 보므로 로그인하지 않은 사람도 화면을 받고, 화면이 로그인으로 보낸다.
    fetch 요청(Accept: application/json 등)은 그대로 API다."""
    index = getattr(request.app.state, "react_index", None)
    if index is None:
        return None
    if "text/html" in request.headers.get("accept", "") or request.headers.get("sec-fetch-mode") == "navigate":
        return FileResponse(index)
    return None


def _visible_to(svc: Any, rec: dict, user: AuthUser, cache: dict | None = None) -> bool:
    """사용자에게 보이는가: 본인 알림 + 검토함·폐기 아님 + 볼 수 있는 섹션(F-06)."""
    if rec["user_id"] != str(user.user_id) or not user_visible(rec):
        return False
    key = ((rec.get("changed") or {}).get("rule_seq"), (rec.get("changed") or {}).get("article"))
    if cache is None:
        return svc.can_see(rec, user.groups)
    if key not in cache:
        cache[key] = svc.can_see(rec, user.groups)
    return cache[key]


def _notice_for(svc: Any, notice_id: str, user: AuthUser, *, admin_any: bool = True) -> dict:
    rec = svc.store.notice_get(notice_id)
    if rec is None or rec.get("review_status") == "dismissed" and user.role != "admin":
        raise ApiError(404, "not_found", MSG_NOT_FOUND)
    if user.role == "admin" and admin_any:
        return rec
    if not _visible_to(svc, rec, user):
        raise ApiError(404, "not_found", MSG_NOT_FOUND)
    return rec


def _check_service_key(request: Request) -> None:
    expected = os.environ.get(SERVICE_KEY_ENV) or ""
    got = request.headers.get("x-service-key") or ""
    auth = request.headers.get("authorization") or ""
    if not got and auth.lower().startswith("bearer "):
        got = auth[7:].strip()
    if not expected or not got or not hmac.compare_digest(expected.encode("utf-8"), got.encode("utf-8")):
        raise ApiError(401, "unauthorized", "서비스 키가 없거나 틀립니다.")


def _run_events(svc: Any, changes: list[ChangedArticle]) -> None:
    """백그라운드: 개정마다 리콜 처리 뒤 웹훅. 한 건이 실패해도 나머지는 이어 간다."""
    for ch in changes:
        try:
            res = svc.process(ch)
            svc.dispatch(res["to_send"])
        except Exception as e:  # noqa: BLE001 - 응답은 이미 202로 나갔다. 처리 기록(recall_events)에 failed로 남는다
            log.warning("리콜 처리 실패(regulation-updated): %s", type(e).__name__)


def create_recall_router(*, store: AuthStore, secret: str | None = None, revocation_store: TokenRevocationStore | None = None) -> APIRouter:
    router = APIRouter()
    current_user = create_current_user_dependency(store=store, secret=secret, revocation_store=revocation_store)
    admin_user = create_require_admin_dependency(store=store, secret=secret, revocation_store=revocation_store)

    # ---------------------------------------------------------------- 목록·집계 (경로가 /recalls/{notice_id}보다 먼저다)
    @router.get("/recalls", response_model=None)
    def list_recalls(request: Request, limit: int = Query(100, ge=1, le=500)):
        if (page := spa_page(request)) is not None:
            return page
        user = current_user(request)
        svc = service_of(request)
        me = str(user.user_id)
        cache: dict = {}
        mine = [r for r in svc.store.notices_all(me) if _visible_to(svc, r, user, cache)]
        unread = sum(1 for r in mine if not r.get("acked"))
        if user.role != "admin":
            return {"items": [notice_json(r) for r in mine[:limit]], "unread": unread}
        every = svc.store.notices_all()
        return {
            "items": [notice_json(r) for r in every if user_visible(r)][:limit],
            "unread": unread,
            "review_queue": [notice_json(r) for r in every if r.get("review_status") == "pending"][:limit],
            "candidates": [candidate_json(c) for c in svc.store.candidates()][:limit],
            "judge_failures": [r["notice_id"] for r in every if r.get("judge_failed") and r.get("review_status") != "dismissed"][:limit],
        }

    @router.get("/recalls/feedback-stats")
    def feedback_stats(request: Request, _admin: AuthUser = Depends(admin_user)) -> dict:
        return summarize(service_of(request).store.feedback_list())

    @router.get("/recalls/digests")
    def list_digests(request: Request, user: AuthUser = Depends(current_user)) -> dict:
        svc = service_of(request)
        rows = svc.store.digests(None if user.role == "admin" else str(user.user_id))
        return {"digests": [{k: r.get(k) for k in ("digest_id", "user_id", "day", "count", "notice_ids", "created_at")} for r in rows]}

    @router.post("/recalls/digest/flush")
    def digest_flush(request: Request, background: BackgroundTasks, _admin: AuthUser = Depends(admin_user),
                     _csrf: None = Depends(require_csrf), day: str | None = Query(None, pattern=DATE_PATTERN)) -> dict:
        svc = service_of(request)
        bodies: list[tuple[str, bytes]] = []
        made = flush_digests(svc, day=day, deliver=lambda did, body: bodies.append((did, body)))
        if svc.sender is not None:
            for did, body in bodies:
                background.add_task(svc.sender.send, did, body, kind="digest")
        return {"digests": len(made), "notices": sum(int(d["count"]) for d in made)}

    @router.post("/recalls/process-pending")
    def process(request: Request, background: BackgroundTasks, _admin: AuthUser = Depends(admin_user), _csrf: None = Depends(require_csrf),
                limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict:
        svc = service_of(request)
        changes = getattr(request.app.state, "change_store", None)
        if changes is None:
            raise ApiError(503, "not_configured", "변경 목록 저장소를 사용할 수 없습니다.")
        res = process_pending(svc, changes, limit=limit)
        to_send = res.pop("to_send")
        if to_send:
            background.add_task(svc.dispatch, to_send)
        return {"status": "done", **res}

    # ---------------------------------------------------------------- 알림 한 건
    @router.get("/recalls/{notice_id}", response_model=None)
    def get_recall(notice_id: str, request: Request):
        if (page := spa_page(request)) is not None:
            return page
        user = current_user(request)
        svc = service_of(request)
        return notice_json(_notice_for(svc, notice_id, user))

    @router.post("/recalls/{notice_id}/ack")
    def ack(notice_id: str, request: Request, user: AuthUser = Depends(current_user), _csrf: None = Depends(require_csrf)) -> dict:
        svc = service_of(request)
        rec = _notice_for(svc, notice_id, user, admin_any=False)
        if not rec.get("acked"):
            rec = svc.store.notice_update(notice_id, acked=True, acked_at=now_iso()) or rec
        return notice_json(rec)

    @router.post("/recalls/{notice_id}/feedback")
    def feedback(notice_id: str, body: FeedbackBody, request: Request, user: AuthUser = Depends(current_user),
                 _csrf: None = Depends(require_csrf)) -> dict:
        svc = service_of(request)
        rec = _notice_for(svc, notice_id, user)
        changed = rec.get("changed") or {}
        pattern = rec.get("change_pattern") or ""
        svc.store.feedback_put({"notice_id": notice_id, "user_id": rec["user_id"], "answer_id": rec["answer_id"], "rule_seq": int(changed["rule_seq"]),
                                "article": changed["article"], "pattern": pattern, "severity": rec.get("severity"), "useful": body.useful,
                                "reason": (body.reason or "").strip(), "given_by": str(user.user_id)})
        counts = svc.store.feedback_counts(rec["user_id"], int(changed["rule_seq"]), changed["article"], pattern)
        return {"notice_id": notice_id, "useful": body.useful, "counts": counts}

    @router.post("/recalls/{notice_id}/review")
    def review(notice_id: str, body: ReviewBody, request: Request, background: BackgroundTasks, _admin: AuthUser = Depends(admin_user),
               _csrf: None = Depends(require_csrf)) -> dict:
        svc = service_of(request)
        if svc.store.notice_get(notice_id) is None:
            raise ApiError(404, "not_found", MSG_NOT_FOUND)
        rec, to_send = svc.review(notice_id, body.action)
        if rec is None:
            raise ApiError(409, "conflict", "관리자 검토함에 있는 알림이 아닙니다.")
        if to_send:
            background.add_task(svc.dispatch, to_send)
        return notice_json(rec)

    # ---------------------------------------------------------------- 웹훅 구독
    def sub_json(s: dict) -> dict:
        return {**{k: s.get(k) for k in ("sub_id", "url", "secret_ref", "active", "created_at")},
                "secret_configured": resolve_secret(s.get("secret_ref")) is not None}

    @router.get("/webhook-subscriptions")
    def list_subs(request: Request, _admin: AuthUser = Depends(admin_user)) -> dict:
        return {"items": [sub_json(s) for s in service_of(request).store.subs()]}

    @router.post("/webhook-subscriptions", status_code=201)
    def add_sub(body: SubscriptionBody, request: Request, admin: AuthUser = Depends(admin_user), _csrf: None = Depends(require_csrf)) -> dict:
        from backend.services.demo_seed import is_local_demo

        svc = service_of(request)
        try:
            check_target_url(body.url, strict=not is_local_demo())
            check_secret_ref(body.secret_ref)
        except ValueError as e:
            raise ApiError(400, "bad_request", str(e)) from None
        sub = svc.store.sub_add({"sub_id": "ws-" + uuid.uuid4().hex[:12], "url": body.url, "secret_ref": body.secret_ref,
                                 "active": body.active, "created_by": str(admin.user_id)})
        return sub_json(sub)

    @router.get("/webhook-deliveries")
    def list_deliveries(request: Request, _admin: AuthUser = Depends(admin_user), notice_id: str | None = Query(None, max_length=64)) -> dict:
        return {"items": service_of(request).store.deliveries(notice_id)}

    # ---------------------------------------------------------------- 함께 볼 정책 후보
    @router.get("/maintenance-candidates")
    def list_candidates(request: Request, _admin: AuthUser = Depends(admin_user),
                        status: Literal["pending", "needed", "not_needed"] | None = Query(None)) -> dict:
        return {"items": [candidate_json(c) for c in service_of(request).store.candidates(status)]}

    @router.post("/maintenance-candidates/{candidate_id}")
    def decide_candidate(candidate_id: str, body: CandidateDecision, request: Request, admin: AuthUser = Depends(admin_user),
                         _csrf: None = Depends(require_csrf)) -> dict:
        rec = service_of(request).store.candidate_decide(candidate_id, body.status, admin.login_id)
        if rec is None:
            raise ApiError(404, "not_found", "함께 볼 정책 후보를 찾을 수 없습니다.")
        return candidate_json(rec)

    # ---------------------------------------------------------------- 수집 쪽 알림
    @router.post("/webhooks/regulation-updated", status_code=202)
    async def regulation_updated(request: Request, background: BackgroundTasks) -> dict:
        _check_service_key(request)          # 본문을 읽기 전에 키부터 본다(키 없는 호출은 형식과 무관하게 401)
        svc = service_of(request)
        try:
            payload = json.loads(await request.body() or b"null")
        except ValueError:
            raise ApiError(400, "bad_request", "본문이 JSON이 아닙니다.") from None
        items = payload if isinstance(payload, list) else [payload]
        if not items or len(items) > MAX_EVENTS or not all(isinstance(i, dict) for i in items):
            raise ApiError(400, "bad_request", f"본문은 바뀐 섹션 객체 하나 또는 1~{MAX_EVENTS}개의 목록이어야 합니다.")
        try:
            changes = [ChangedArticle(**RegulationUpdate.model_validate(i).model_dump()) for i in items]
        except ValidationError:
            raise ApiError(400, "bad_request", "바뀐 섹션 형식이 올바르지 않습니다.") from None
        from backend.rag.ingest.schedule import event_id

        background.add_task(_run_events, svc, changes)
        return {"accepted": len(changes), "event_ids": [event_id(c.model_dump()) for c in changes]}

    # ---------------------------------------------------------------- 변경 전 영향 미리보기 (드라이런)
    @router.post("/impact-preview")
    def impact_preview(body: ImpactBody, request: Request, _admin: AuthUser = Depends(admin_user), _csrf: None = Depends(require_csrf)) -> dict:
        from backend.graph.recall.impact import changes_from_pages, preview_impact, render_markdown

        svc = service_of(request)
        if bool(body.changes) == bool(body.pages):
            raise ApiError(400, "bad_request", "changes 또는 pages 중 하나만 주세요.")
        if body.pages:
            if not (body.old_version_date and body.new_version_date):
                raise ApiError(400, "bad_request", "pages에는 old_version_date, new_version_date가 필요합니다.")
            changes, texts = changes_from_pages([p.model_dump() for p in body.pages], old_date=body.old_version_date,
                                                new_date=body.new_version_date)
        else:
            changes = [ChangedArticle(**{k: v for k, v in c.model_dump().items() if k in ChangedArticle.model_fields}) for c in body.changes or []]
            texts = {(c.rule_seq, c.article): (c.old_text, c.new_text) for c in body.changes or [] if c.old_text is not None or c.new_text is not None}
        repo = getattr(request.app.state, "decision_repo", None)
        tables = repo.list_approved() if repo is not None else []
        report = preview_impact(changes, answers=svc.answers, read_section=svc.read_section, texts=texts, tables=tables, judge=svc.judge)
        return {**report.model_dump(), "markdown": render_markdown(report)}

    return router
