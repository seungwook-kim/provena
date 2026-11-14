"""내 정보 API — `GET /me/profile`, `GET /me/profile?view=edit`, `PUT /me/profile` (요청 1번, MYINFO_SPEC.md 3장).

- 사용자는 쿠키 JWT에서만 정한다(`create_current_user_dependency`). 본문·주소의 user_id는 읽지 않는다.
- 다른 사람의 내 정보를 주는 경로는 없다. 관리자도 자기 것만 본다.
- 기본 보기는 전화번호를 서버에서 가린다(010-****-5678). 원래 번호는 본인이 `view=edit`로 열 때만 준다.
- 입력 검사 규칙은 시안 `src/lib/profile-preview.js`의 validateProfile·normalizePhone과 같다. 서버 검사가 기준이다.
- 422 응답에는 입력값을 되풀이하지 않는다: 팀 표준 `ApiError`로 `{"error": {"code": "validation_error", "message": ..., "details": {"fields": {칸: 이유}}}}`.
  (`HTTPException`의 dict detail은 운영 오류 처리기가 `reason`이 없으면 message·칸별 이유를 버린다. `backend/api/errors.py`)
- 본문은 로그에 남기지 않는다. 저장소·암호화 실패는 이유를 숨기고 503으로 답한다.
- 예외 하나(놓친 것 K-23): 로컬 데모가 스스로 만든 키(`cipher.local_generated`)로 돌 때만, 저장된 줄을 풀 수 없으면 503 대신
  404 `profile_reentry_required`("다시 입력해 주세요")로 답한다. 화면은 빈 칸을 열고 PUT으로 덮어쓴다. `PROFILE_ENC_KEYS`를 준
  실행(운영 포함)은 그대로 503이다. 저장소 오류도 그대로 503이다.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from backend.api.errors import ApiError
from backend.auth import AuthStore, AuthUser, TokenRevocationStore, create_current_user_dependency, require_csrf
from backend.services.profile_crypto import ProfileCipher, ProfileCryptoError
from backend.services.profile_store import FIELDS, EncryptedProfile, ProfileStore

log = logging.getLogger(__name__)

INVALID_MESSAGE = "입력한 내용을 확인해 주세요."
UNAVAILABLE_MESSAGE = "내 정보 저장소를 사용할 수 없습니다."
NOT_FOUND_MESSAGE = "내 정보가 아직 없습니다."
REENTRY_CODE = "profile_reentry_required"
REENTRY_MESSAGE = "저장된 내 정보를 열 수 없습니다. 로컬 데모의 암호화 키가 바뀌었습니다. 다시 입력해 저장해 주세요."
MAX_BODY_BYTES = 8192   # 네 칸 최대 길이를 다 채워도 1KB 안팎. 큰 본문은 읽기 전에 거절한다

_MOBILE = re.compile(r"01[016789][0-9]{7,8}")
_SEOUL = re.compile(r"02[0-9]{7,8}")
_AREA = re.compile(r"0[3-6][1-5][0-9]{7,8}")
_SPACE_OR_HYPHEN = re.compile(r"[\s-]")


def _invalid(fields: dict[str, str] | None = None) -> ApiError:
    return ApiError(422, "validation_error", INVALID_MESSAGE, details={"fields": fields or {}})


class ProfileRoute(APIRoute):
    """auth.py의 AuthRoute와 같은 방식: FastAPI 기본 422(입력값 `input`이 들어 있다)를 값 없는 문장으로 바꾼다.

    AuthRoute를 그대로 쓰지 않는 이유: 그 문장이 "잘못된 로그인 요청입니다."라서 내 정보 화면에 맞지 않는다.
    """

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                raise _invalid() from None

        return handler


def normalize_phone(raw: str) -> str | None:
    """시안 normalizePhone과 같다. 숫자(0-9)만 남겨 휴대폰 01[016789] 10~11자리, 02, 031~064면 하이픈을 다시 붙인다."""
    d = _SPACE_OR_HYPHEN.sub("", raw)
    if not re.fullmatch(r"[0-9]+", d):   # \d 는 유니코드 숫자(예: ٣)도 받으므로 쓰지 않는다
        return None
    if _MOBILE.fullmatch(d):
        return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if _SEOUL.fullmatch(d):
        return f"02-{d[2:-4]}-{d[-4:]}"
    if _AREA.fullmatch(d):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    return None


def mask_phone(phone: str) -> str:
    """010-1234-5678 → 010-****-5678. 모양이 다르면 통째로 가린다."""
    parts = phone.split("-")
    if len(parts) != 3:
        return "***"
    return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"


def _is_name(value: str) -> bool:
    # 시안 /^[\p{L} ]{2,20}$/u 와 같다: 글자(유니코드 L 분류)와 공백만, 2~20자
    return 2 <= len(value) <= 20 and all(ch == " " or unicodedata.category(ch).startswith("L") for ch in value)


def validate_profile(body: Any) -> tuple[dict[str, str], dict[str, str]]:
    """(오류, 저장할 값)을 돌려준다. 오류 문장은 시안과 같고 입력값을 담지 않는다."""
    if not isinstance(body, dict):
        return {"_": INVALID_MESSAGE}, {}
    errors: dict[str, str] = {}
    values: dict[str, str] = {}
    for key in FIELDS:
        raw = body.get(key)
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            errors[key] = "문자로 입력해 주세요."
            continue
        values[key] = raw.strip()

    name = values.get("name")
    if name is not None:
        if not name:
            errors["name"] = "이름을 입력해 주세요."
        elif not _is_name(name):
            errors["name"] = "이름은 글자 2~20자로 입력해 주세요(숫자·기호 제외)."
    dept = values.get("dept")
    if dept is not None:
        if not dept:
            errors["dept"] = "소속(담당부서)을 입력해 주세요."
        elif len(dept) > 40:
            errors["dept"] = "소속은 40자 이하로 입력해 주세요."
    phone = values.get("phone")
    if phone is not None:
        normalized = normalize_phone(phone) if phone else None
        if not phone:
            errors["phone"] = "전화번호를 입력해 주세요."
        elif normalized is None:
            errors["phone"] = "전화번호 형식이 맞지 않습니다. 예: 010-1234-5678"
        else:
            values["phone"] = normalized
    address = values.get("address")
    if address is not None:
        if not address:
            errors["address"] = "주소를 입력해 주세요."
        elif len(address) < 5 or len(address) > 100:
            errors["address"] = "주소는 5~100자로 입력해 주세요."
    return errors, values


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _view(values: dict[str, str], updated_at: datetime | None, *, edit: bool) -> dict[str, Any]:
    phone_key, phone_value = ("phone", values["phone"]) if edit else ("phone_masked", mask_phone(values["phone"]))
    return {"name": values["name"], "dept": values["dept"], phone_key: phone_value,
            "address": values["address"], "updated_at": _iso(updated_at)}


def create_profile_router(
    *,
    auth_store: AuthStore,
    profile_store: ProfileStore,
    cipher: ProfileCipher,
    secret: str | None = None,
    revocation_store: TokenRevocationStore | None = None,
) -> APIRouter:
    """`secret`·`revocation_store`는 로그인 라우터와 같은 값을 넘긴다(로컬 데모의 무작위 서명 키 포함)."""
    if auth_store is None or profile_store is None or cipher is None:
        raise ValueError("auth_store, profile_store, cipher 가 모두 필요합니다")
    router = APIRouter(route_class=ProfileRoute)
    current_user = create_current_user_dependency(store=auth_store, secret=secret, revocation_store=revocation_store)

    def load_plain(user_id: str) -> tuple[dict[str, str], datetime | None] | None:
        row = profile_store.get(user_id)
        if row is None:
            return None
        if row.user_id != user_id:   # 저장소가 다른 줄을 돌려주면 내보내지 않는다
            raise LookupError("profile row does not belong to the current user")
        blobs = {"name": row.name_enc, "dept": row.dept_enc, "phone": row.phone_enc, "address": row.address_enc}
        return {k: cipher.decrypt(user_id, k, blobs[k], row.key_version) for k in FIELDS}, row.updated_at

    def save_plain(user_id: str, values: dict[str, str]) -> datetime | None:
        sealed = {k: cipher.encrypt(user_id, k, values[k]) for k in FIELDS}
        stored = profile_store.upsert(EncryptedProfile(
            user_id=user_id, name_enc=sealed["name"], dept_enc=sealed["dept"], phone_enc=sealed["phone"],
            address_enc=sealed["address"], key_version=cipher.current_version,
        ))
        return stored.updated_at if stored is not None else None

    @router.get("/me/profile")
    async def get_profile(response: Response, view: Literal["edit"] | None = None,
                          user: AuthUser = Depends(current_user)) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        user_id = str(user.user_id)
        try:
            loaded = await run_in_threadpool(load_plain, user_id)
        except ProfileCryptoError as exc:   # 줄은 있는데 지금 키로 풀 수 없다
            log.warning("내 정보 읽기 실패: %s", type(exc).__name__)
            if getattr(cipher, "local_generated", False):   # 로컬 데모가 만든 키일 때만: 막지 않고 다시 입력하게 한다(K-23)
                raise ApiError(404, REENTRY_CODE, REENTRY_MESSAGE, headers={"Cache-Control": "no-store"}) from None
            raise HTTPException(status_code=503, detail=UNAVAILABLE_MESSAGE, headers={"Cache-Control": "no-store"}) from None
        except Exception as exc:   # 저장소 오류 등. 값·이유는 응답과 로그에 쓰지 않는다
            log.warning("내 정보 읽기 실패: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=UNAVAILABLE_MESSAGE, headers={"Cache-Control": "no-store"}) from None
        if loaded is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MESSAGE, headers={"Cache-Control": "no-store"})
        values, updated_at = loaded
        return _view(values, updated_at, edit=view == "edit")

    @router.put("/me/profile")
    async def put_profile(request: Request, response: Response, user: AuthUser = Depends(current_user),
                          _csrf: None = Depends(require_csrf)) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise _invalid()
        try:
            body = await request.json()
        except ValueError:
            raise _invalid() from None
        errors, values = validate_profile(body)
        if errors:
            errors.pop("_", None)
            raise _invalid(errors)
        user_id = str(user.user_id)
        try:
            updated_at = await run_in_threadpool(save_plain, user_id, values)
        except Exception as exc:
            log.warning("내 정보 저장 실패: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail=UNAVAILABLE_MESSAGE, headers={"Cache-Control": "no-store"}) from None
        return _view(values, updated_at, edit=False)

    return router
