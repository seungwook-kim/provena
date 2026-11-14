"""사용자 관리 API — 최고 관리자 1명만 관리자를 등록·해제한다 (요청 2번, 방식 B, docs/specs/admin-roles.md).

- 최고 관리자 = DB `role='admin'` + 활성 + `login_id` 가 설정값 `PROVENA_OWNER_LOGIN_ID` 와 같음. 이메일(`@` 포함)은 대소문자 무시
  (db/113 이 이메일 아이디를 소문자로 맞추고 로그인도 소문자로 찾는다), 이메일이 아닌 아이디는 정확히 같아야 한다(대소문자 구분).
  DB 역할은 지금처럼 user/admin 둘뿐이다(db/101_auth_users.sql:10). 설정값은 main.py 가 시작할 때 한 번 읽어 넘긴다.
- 설정값이 비었거나 Google 자동 아이디 머리글자로 시작하면 아무도 통과하지 못한다(닫힘이 기본).
- 검사 순서: 인증(401) → 최고 관리자(403) → CSRF(403) → 대상 조회(404) → 대상이 최고 관리자·비활성(409) → 쓰기.
  권한을 먼저 봐서, 최고 관리자가 아닌 사람에게는 아이디가 있는지 없는지 새지 않는다.
- 목록은 login_id·role·is_owner·created_at 네 칸만. 비밀번호 해시·user_id·내 정보(user_profiles)는 읽지도 내보내지도 않는다.
- 역할은 요청마다 DB에서 다시 읽는다(backend/auth.py get_current_user). 등록·해제는 다시 로그인 없이 다음 요청부터 반영된다.
"""
from __future__ import annotations

import hmac
import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from backend.auth import AuthStore, AuthUser, TokenRevocationStore, create_require_admin_dependency, require_csrf

log = logging.getLogger(__name__)

# Google 첫 로그인 때 자동으로 만들 계정 아이디의 머리글자(열린 항목 4, 지금은 시험 대역 tests/test_google_oauth.py:71 과 같게).
# 최고 관리자 설정값이 이것으로 시작하면 닫는다: Google 계정이 최고 관리자 아이디를 차지하는 길을 막는다.
GOOGLE_LOGIN_PREFIX = "google-"

OWNER_REQUIRED = "최고 관리자 권한이 필요합니다."
NOT_FOUND = "사용자를 찾을 수 없습니다."
OWNER_TARGET = "최고 관리자는 바꿀 수 없습니다."
INACTIVE_TARGET = "비활성 계정입니다."
UNAVAILABLE = "인증 저장소를 사용할 수 없습니다."
INVALID_SIGNUP_ACTION = "가입 신청 처리 방식이 올바르지 않습니다."
SIGNUP_UNVERIFIED = "이메일 인증을 마치지 않은 가입 신청입니다."
RESET_UNAVAILABLE = "이 가입 신청은 인증번호를 초기화할 수 없습니다."
NO_STORE = {"Cache-Control": "no-store"}


class SignupRequestItem(BaseModel):
    request_id: int | None
    login_id: str
    requested_at: str | None
    status: str
    email_verified: bool


class SignupRequestList(BaseModel):
    requests: list[SignupRequestItem]


class SignupReviewByIdResult(BaseModel):
    request_id: int
    status: str
    changed: bool


class SignupVerificationResetResult(BaseModel):
    request_id: int
    reset: bool


_OWNER_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Authentication required"},
    403: {"description": "Owner-admin or CSRF authorization failed"},
    503: {"description": "Signup approval storage unavailable"},
}


class AdminUserStore(AuthStore, Protocol):
    def list_users(self) -> Iterable[Any]: ...   # 각 줄에 login_id, role, created_at 속성

    def set_role(self, target_login_id: str, new_role: str, by_user_id: UUID | str) -> str: ...

    def list_signup_requests(self) -> Iterable[Any]: ...
    def review_signup_request(self, login_id: str, action: str, reviewed_by: UUID | str) -> str: ...

    def reset_signup_verification_by_id(self, request_id: int) -> str: ...


def owner_configured(owner_login_id: str | None) -> bool:
    return bool(owner_login_id) and not owner_login_id.startswith(GOOGLE_LOGIN_PREFIX)


def same_owner_login(login_id: str, owner_login_id: str) -> bool:
    """아이디가 최고 관리자 설정값과 같은지. 이메일은 소문자로 비교하고, 그 밖은 정확히 비교한다(상수 시간)."""
    if "@" in owner_login_id:
        login_id, owner_login_id = login_id.lower(), owner_login_id.lower()
    return hmac.compare_digest(login_id.encode("utf-8"), owner_login_id.encode("utf-8"))


def is_owner(user: AuthUser | None, owner_login_id: str | None) -> bool:
    """이 사람이 지금 최고 관리자인가. user 는 요청마다 DB에서 다시 읽은 값이어야 한다."""
    if user is None or not owner_configured(owner_login_id):
        return False
    return (
        user.role == "admin"
        and user.is_active
        and same_owner_login(user.login_id, owner_login_id)
    )


def check_owner(store: AuthStore, owner_login_id: str | None) -> str:
    """서버 시작 때 한 번: 설정값 계정이 있고 admin·활성인지 로그로 알린다. 값(아이디)은 로그에 쓰지 않는다.

    알림일 뿐 막는 곳은 요청마다 도는 is_owner 다. 그래서 계정을 나중에 만들어도 재배포 없이 열린다.
    돌려주는 값(시험용): ok / unset / mismatch / unavailable.
    """
    if not owner_login_id:
        log.warning("최고 관리자 설정(PROVENA_OWNER_LOGIN_ID)이 없어 사용자 관리를 닫았다")
        return "unset"
    if not owner_configured(owner_login_id):
        log.error("최고 관리자 설정이 users 표와 맞지 않아 사용자 관리를 닫았다")
        return "mismatch"
    try:
        user = store.get_by_login_id(owner_login_id)
    except Exception as exc:   # DSN(비밀번호 포함)이 섞일 수 있어 종류만 남긴다
        log.warning("최고 관리자 설정을 확인하지 못했다(요청 때 다시 확인): %s", type(exc).__name__)
        return "unavailable"
    if not is_owner(user, owner_login_id):
        log.error("최고 관리자 설정이 users 표와 맞지 않아 사용자 관리를 닫았다")
        return "mismatch"
    log.info("최고 관리자 설정 확인됨: 사용자 관리를 열었다")
    return "ok"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def create_admin_router(
    *,
    store: AdminUserStore,
    owner_login_id: str | None,
    secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
    html_page: Callable[[], Path | None] | None = None,
) -> APIRouter:
    """`secret`·`revocation_store` 는 로그인 라우터와 같은 값을 넘긴다(로컬 데모의 무작위 서명 키 포함).

    `html_page`: React 화면 주소도 `/admin/users`(web/react-app/src/App.jsx)라서, 브라우저가 그 주소를 직접 열면
    (`Accept`에 text/html) 이 함수가 돌려준 index.html 을 내준다. 화면의 fetch 는 `Accept: */*` 라 API 가 답한다.
    index.html 에는 사용자 정보가 없고, 권한 확인은 화면이 부르는 API 가 한다.
    """
    if store is None:
        raise ValueError("store 가 필요합니다")
    router = APIRouter()
    admin_guard = create_require_admin_dependency(store=store, secret=secret, revocation_store=revocation_store)

    def owner_guard(request: Request) -> AuthUser:
        user = admin_guard(request)   # 401·503(인증), 일반 사용자 403 — 기존 require_admin 그대로
        if not is_owner(user, owner_login_id):
            raise HTTPException(status_code=403, detail=OWNER_REQUIRED, headers=NO_STORE)
        return user

    @router.get("/admin/users", response_model=None)
    def list_users(request: Request, response: Response) -> dict[str, list[dict[str, Any]]] | FileResponse:
        page = html_page() if html_page is not None else None
        if page is not None and "text/html" in request.headers.get("accept", "").lower():
            # 화면 새로고침·주소 직접 입력. 화면과 API 주소가 같으므로 브라우저가 이 HTML을 캐시하면
            # 화면의 fetch(/admin/users)가 HTML을 받아 "서버 응답 형식이 올바르지 않습니다"가 된다 → 캐시 금지·Accept별 구분
            return FileResponse(page, headers={"Cache-Control": "no-store", "Vary": "Accept"})
        owner_guard(request)   # 401·403·503. 화면 요청이 아닐 때만(위) 권한을 본다
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Accept"
        try:
            rows = list(store.list_users())
        except Exception as exc:
            log.warning("사용자 목록 읽기 실패: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        # 칸을 하나씩 골라 담는다: 저장소가 무엇을 더 돌려줘도 이 네 칸 말고는 나가지 않는다
        return {"users": [
            {
                "login_id": row.login_id,
                "role": row.role,
                "is_owner": owner_configured(owner_login_id) and same_owner_login(row.login_id, owner_login_id) and row.role == "admin",
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]}

    def change(request: Request, response: Response, owner: AuthUser, login_id: str, new_role: str) -> dict[str, Any]:
        require_csrf(request)   # 최고 관리자 확인 다음, 대상 조회·쓰기 전에
        response.headers["Cache-Control"] = "no-store"
        try:
            target = store.get_by_login_id(login_id)
        except Exception as exc:
            log.warning("대상 계정 조회 실패: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        if target is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND, headers=NO_STORE)
        if owner_login_id and same_owner_login(target.login_id, owner_login_id):
            raise HTTPException(status_code=409, detail=OWNER_TARGET, headers=NO_STORE)
        if not target.is_active:
            raise HTTPException(status_code=409, detail=INACTIVE_TARGET, headers=NO_STORE)
        try:
            result = store.set_role(target.login_id, new_role, owner.user_id)
        except Exception as exc:   # 기록 쓰기 실패 포함. 한 트랜잭션이라 역할도 되돌아간다
            log.warning("역할 변경 실패: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        if result == "missing":   # 조회와 쓰기 사이에 지워진 경우
            raise HTTPException(status_code=404, detail=NOT_FOUND, headers=NO_STORE)
        if result == "inactive":
            raise HTTPException(status_code=409, detail=INACTIVE_TARGET, headers=NO_STORE)
        if result not in {"changed", "unchanged"}:
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE)
        return {"login_id": target.login_id, "role": new_role, "changed": result == "changed"}

    @router.post("/admin/users/{login_id}/promote")
    def promote(login_id: str, request: Request, response: Response,
                owner: AuthUser = Depends(owner_guard)) -> dict[str, Any]:
        return change(request, response, owner, login_id, "admin")

    @router.post("/admin/users/{login_id}/revoke")
    def revoke(login_id: str, request: Request, response: Response,
               owner: AuthUser = Depends(owner_guard)) -> dict[str, Any]:
        return change(request, response, owner, login_id, "user")

    @router.get("/admin/signup-requests", response_model=SignupRequestList, responses=_OWNER_ERRORS)
    def list_signup_requests(request: Request, response: Response) -> dict[str, list[dict[str, Any]]]:
        owner_guard(request)
        response.headers["Cache-Control"] = "no-store"
        try:
            rows = list(store.list_signup_requests())
        except Exception:
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        return {"requests": [{"request_id": getattr(row, "request_id", None), "login_id": row.login_id,
                              "requested_at": _iso(row.requested_at), "status": row.status,
                              "email_verified": bool(getattr(row, "email_verified", False))} for row in rows]}

    @router.post("/admin/signup-requests/{login_id}/{action}")
    def review_signup_request(login_id: str, action: str, request: Request, response: Response,
                              owner: AuthUser = Depends(owner_guard)) -> dict[str, Any]:
        require_csrf(request)
        login_id = login_id.strip().lower() if "@" in login_id else login_id.strip()
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail=INVALID_SIGNUP_ACTION, headers=NO_STORE)
        response.headers["Cache-Control"] = "no-store"
        try:
            result = store.review_signup_request(login_id, action, owner.user_id)
        except Exception:
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        if result == "missing":
            raise HTTPException(status_code=404, detail=NOT_FOUND, headers=NO_STORE)
        if result == "unverified":
            raise HTTPException(status_code=409, detail=SIGNUP_UNVERIFIED, headers=NO_STORE)
        return {"login_id": login_id, "status": "approved" if action == "approve" else "rejected", "changed": result == "changed"}

    @router.post(
        "/admin/signup-requests/by-id/{request_id}/reset-verification",
        response_model=SignupVerificationResetResult,
        description="Owner-admin only; requires a valid CSRF token. Clears the verification code and resets the attempt and send counters of an unverified pending email signup request so a new code can be issued.",
        responses={**_OWNER_ERRORS, 404: {"description": "Signup request not found"},
                   409: {"description": "Verification reset is unavailable for this request"}},
    )
    def reset_signup_verification(request_id: int, request: Request, response: Response,
                                  owner: AuthUser = Depends(owner_guard)) -> dict[str, Any]:
        require_csrf(request)
        reset = getattr(store, "reset_signup_verification_by_id", None)
        if not callable(reset):
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE)
        response.headers["Cache-Control"] = "no-store"
        try:
            result = reset(request_id)
        except Exception:
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        if result == "missing":
            raise HTTPException(status_code=404, detail=NOT_FOUND, headers=NO_STORE)
        if result == "unavailable":
            raise HTTPException(status_code=409, detail=RESET_UNAVAILABLE, headers=NO_STORE)
        return {"request_id": request_id, "reset": True}

    @router.post(
        "/admin/signup-requests/by-id/{request_id}/{action}",
        response_model=SignupReviewByIdResult,
        description="Owner-admin only; requires a valid CSRF token. action must be approve or reject.",
        responses={**_OWNER_ERRORS, 404: {"description": "Signup request not found"},
                   409: {"description": "Email verification is required"}},
    )
    def review_signup_request_by_id(request_id: int, action: str, request: Request, response: Response,
                                    owner: AuthUser = Depends(owner_guard)) -> dict[str, Any]:
        require_csrf(request)
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=422, detail=INVALID_SIGNUP_ACTION, headers=NO_STORE)
        review = getattr(store, "review_signup_request_by_id", None)
        if not callable(review):
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE)
        response.headers["Cache-Control"] = "no-store"
        try:
            result = review(request_id, action, owner.user_id)
        except Exception:
            raise HTTPException(status_code=503, detail=UNAVAILABLE, headers=NO_STORE) from None
        if result == "missing":
            raise HTTPException(status_code=404, detail=NOT_FOUND, headers=NO_STORE)
        if result == "unverified":
            raise HTTPException(status_code=409, detail=SIGNUP_UNVERIFIED, headers=NO_STORE)
        return {"request_id": request_id, "status": "approved" if action == "approve" else "rejected", "changed": result == "changed"}

    return router


def owner_check_for(owner_login_id: str | None) -> Callable[[AuthUser], bool]:
    """`/me` 의 is_owner 칸용(create_auth_router(owner_check=...)). 화면은 메뉴를 숨기는 데만 쓴다."""
    return lambda user: is_owner(user, owner_login_id)
