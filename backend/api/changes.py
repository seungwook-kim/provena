"""변경 감시 라우터 (PRD 6-4 자동화, F-07). 증분 수집이 쌓은 바뀐 섹션과 실행 기록을 보여 주고, 감시를 멈추거나 다시 켠다.

- `GET /changes?since=YYYY-MM-DD&limit=&offset=`: 로그인. since를 비우면 30일 전(UTC). 최근 것이 앞이다.
  `{"items": [바뀐 섹션], "last_run": {run_id, status, finished_at, to_commit, list_complete} | null, "more": bool, "monitoring": "active"|"paused",`
  `"total": int | null, "counts": {change_type: int} | null}`. `total`·`counts`는 limit·offset과 무관하게 since 이후 전체 건수와 종류별(added·removed·modified) 건수다(화면 분포 카드용).
  `last_run`이 null이면 수집이 한 번도 성공하지 않았다는 뜻이다("바뀐 것 없음"인 빈 목록과 구분한다).
- `GET /changes/monitoring`: 로그인. `{"status"}`. `PUT /changes/monitoring`: 관리자, CSRF. `{"status": "active"|"paused"}`.
  paused면 정해진 시각의 증분 수집(`backend/rag/ingest/schedule.py`)과 명령줄 리콜 처리기가 아무것도 하지 않는다.
- `GET /changes/{event_id}`: 로그인. 바뀐 섹션 한 건과 개정 전후 원문(`old_text`, `new_text`, 읽을 수 없으면 null). 없는 id는 404.
`impacted_answer_count`는 그 섹션을 인용한 과거 답 수(답 저장소 기준)다. DB가 없으면 빈 목록이다(500이 아니다).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.api.errors import ApiError
from backend.api.recalls import no_store, spa_page
from backend.auth import AuthStore, AuthUser, TokenRevocationStore, create_current_user_dependency, create_require_admin_dependency, require_csrf
from backend.graph.answer_store import count_by_articles
from backend.rag.retrieve.section import check_date

DEFAULT_DAYS = 30
MAX_LIMIT = 200
CHANGE_KEYS = ("event_id", "rule_seq", "article", "page_title", "old_version_date", "new_version_date", "change_type", "status",
               "created_at", "source_url")


class MonitoringBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "paused"]


class SyncBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dry_run: bool = True    # 기본은 시험 실행: 무엇을 할지만 알려 주고 수집은 시작하지 않는다


class ChangeItem(BaseModel):
    """`GET /changes`의 `items` 한 건(`change_json`의 반환과 같은 칸). 명세용이며 응답을 걸러내지 않는다."""
    event_id: str | None = None
    rule_seq: int
    article: str | None = None
    page_title: str | None = None
    old_version_date: str | None = None
    new_version_date: str | None = None
    change_type: str | None = None
    status: str | None = None
    created_at: str
    source_url: str | None = None
    impacted_answer_count: int


class ChangeLastRun(BaseModel):
    run_id: str | int | None = None
    status: str | None = None
    finished_at: str | None = None
    to_commit: str | None = None
    list_complete: bool | None = None


class ChangesResponse(BaseModel):
    """`GET /changes` 응답 칸(명세용). `total`·`counts`는 저장소가 못 세면 null이다."""
    items: list[ChangeItem]
    last_run: ChangeLastRun | None
    more: bool
    monitoring: Literal["active", "paused"]
    total: int | None
    counts: dict[str, int] | None


def _store(request: Request) -> Any:
    st = getattr(request.app.state, "change_store", None)
    if st is None:
        raise ApiError(503, "not_configured", "변경 목록 저장소를 사용할 수 없습니다.")
    return st


def _counts(request: Request, rows: list[dict]) -> dict:
    svc = getattr(request.app.state, "recall_service", None)
    if svc is None or not rows:
        return {}
    try:
        return count_by_articles(svc.answers, [(int(r["rule_seq"]), r["article"]) for r in rows])
    except Exception:  # noqa: BLE001 - 답 수를 못 세도 목록은 보여 준다(0으로 둔다)
        return {}


def change_json(row: dict, count: int = 0) -> dict:
    out = {k: row.get(k) for k in CHANGE_KEYS}
    out["rule_seq"] = int(out["rule_seq"])
    out["created_at"] = str(out["created_at"] or "")
    out["impacted_answer_count"] = int(count)
    return out


def _totals(st: Any, since: str) -> dict[str, int] | None:
    """since 이후 전체 건수를 종류별로 센다. 저장소가 못 세면 None(화면은 불러온 목록으로 세는 옛 방식으로 돌아간다)."""
    counter = getattr(st, "count_by_type", None)
    if counter is None:
        return None
    try:
        return {str(k): int(v) for k, v in counter(since).items()}
    except Exception:  # noqa: BLE001 - 합계를 못 세도 목록은 보여 준다
        return None


def _spawn_sync(slot: str) -> None:
    """수집 한 번을 별도 프로세스로 시작한다(응답을 막지 않는다). 시험은 `app.state.sync_launcher`로 바꿔 끼운다."""
    subprocess.Popen([sys.executable, "-m", "backend.rag.ingest.schedule", "--once", "--slot", slot])  # noqa: S603


def _monitoring(st: Any) -> str:
    try:
        return st.monitoring_get().get("status") or "active"
    except Exception:  # noqa: BLE001 - 스위치 표가 없거나 읽을 수 없으면 감시 중으로 본다(수집 기본 동작)
        return "active"


def create_changes_router(*, store: AuthStore, secret: str | None = None, revocation_store: TokenRevocationStore | None = None) -> APIRouter:
    router = APIRouter()
    current_user = create_current_user_dependency(store=store, secret=secret, revocation_store=revocation_store)
    admin_user = create_require_admin_dependency(store=store, secret=secret, revocation_store=revocation_store)

    @router.get("/changes", response_model=None, responses={200: {"model": ChangesResponse, "description": "화면 주소를 직접 열면 HTML이 온다."}})
    def list_changes(request: Request, response: Response, since: str | None = Query(None, max_length=10),
                     limit: int = Query(50, ge=1, le=MAX_LIMIT), offset: int = Query(0, ge=0, le=1_000_000)):
        if (page := spa_page(request)) is not None:   # 화면 주소를 직접 열면 로그인 확인 전에 화면을 준다(/approvals와 같은 규칙)
            return page
        no_store(response)
        current_user(request)
        st = _store(request)
        since = since or (datetime.now(timezone.utc).date() - timedelta(days=DEFAULT_DAYS)).isoformat()
        try:
            check_date(since, "since")
        except ValueError:
            raise ApiError(422, "validation_error", "since는 YYYY-MM-DD 형식이어야 합니다.") from None
        rows, more = st.changes(since, limit, offset)
        counts = _counts(request, rows)
        run = st.last_run()
        totals = _totals(st, since)
        return {
            "items": [change_json(r, counts.get((int(r["rule_seq"]), r["article"]), 0)) for r in rows],
            "last_run": {k: run.get(k) for k in ("run_id", "status", "finished_at", "to_commit", "list_complete")} if run else None,
            "more": bool(more),
            "monitoring": _monitoring(st),
            "total": sum(totals.values()) if totals is not None else None,
            "counts": totals,
        }

    @router.get("/changes/monitoring")
    def get_monitoring(request: Request, _user: AuthUser = Depends(current_user)) -> dict:
        return {"status": _monitoring(_store(request))}

    @router.put("/changes/monitoring")
    def put_monitoring(body: MonitoringBody, request: Request, admin: AuthUser = Depends(admin_user), _csrf: None = Depends(require_csrf)) -> dict:
        rec = _store(request).monitoring_set(body.status, admin.login_id)
        return {"status": rec["status"], "updated_by": rec.get("updated_by"), "updated_at": str(rec.get("updated_at") or "") or None}

    @router.post("/admin/sync")
    def post_sync(request: Request, body: SyncBody | None = None, admin: AuthUser = Depends(admin_user), _csrf: None = Depends(require_csrf)) -> dict:
        """증분 수집 수동 실행(C-14). 관리자만. 기본은 dry_run=true(시작하지 않고 계획만). `dry_run=false`일 때만 수집을 시작한다."""
        from backend.rag.ingest import schedule   # 수집 모듈은 읽기만 한다(import). 무거운 의존성이라 부를 때 불러온다

        body = body or SyncBody()
        now = datetime.now(timezone.utc)
        slot = f"manual-{now:%Y%m%d%H%M%S}"
        st = _store(request)
        plan = {"slot": slot, "scheduled_slot": schedule.slot_of(now), "monitoring": _monitoring(st)}
        if body.dry_run:
            return {"dry_run": True, "started": False, **plan}
        if plan["monitoring"] == "paused":
            raise ApiError(409, "monitoring_paused", "변경 감시가 멈춰 있어 수집을 시작하지 않습니다.")
        launcher = getattr(request.app.state, "sync_launcher", None) or _spawn_sync
        launcher(slot)
        return {"dry_run": False, "started": True, **plan}

    @router.get("/changes/{event_id}", response_model=None)
    def get_change(event_id: str, request: Request, response: Response):
        if (page := spa_page(request)) is not None:
            return page
        no_store(response)
        current_user(request)
        row = _store(request).get(event_id)
        if row is None:
            raise ApiError(404, "not_found", "바뀐 섹션을 찾을 수 없습니다.")
        out = change_json(row, _counts(request, [row]).get((int(row["rule_seq"]), row["article"]), 0))
        svc = getattr(request.app.state, "recall_service", None)
        reader = getattr(svc, "read_section", None)
        old = new = None
        if reader is not None:
            if row["change_type"] != "added" and row.get("old_version_date"):
                old = (reader(int(row["rule_seq"]), row["article"], row["old_version_date"]) or {}).get("text")
            if row["change_type"] != "removed" and row.get("new_version_date"):
                new = (reader(int(row["rule_seq"]), row["article"], row["new_version_date"]) or {}).get("text")
        return {**out, "old_text": old, "new_text": new}

    return router
