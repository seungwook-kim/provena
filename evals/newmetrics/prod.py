"""운영 배포판 호출 도우미: 로그인(평가용 계정), 서비스 키 웹훅, 운영 판 정보. 계정·키·DB 주소는 출력·저장하지 않는다.

계정은 대기 실행기(hold_runner)가 들고 있는 환경 변수를 작업 스크립트가 PROBE_A_*(관리자 평가용), PROBE_B_*(일반 평가용)로 넘긴다.
로그인은 `evals.safety.deploy_check`의 login·CSRF 규칙을 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
import os
import time


class LoginFailed(RuntimeError):
    pass


def uid_tag(user_id: str | None) -> str | None:
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8] if user_id else None


def client(base: str, read_s: float = 150.0):
    import httpx

    return httpx.Client(base_url=base.rstrip("/"), timeout=httpx.Timeout(30.0, read=read_s), follow_redirects=False)


def login(c, who: str, tries: int = 3, wait_s: float = 60.0) -> str:
    """who = 'A'(관리자 평가용) 또는 'B'(일반 평가용). 503(DB 세션 한도)은 쓰기 전이라 1분 뒤 다시."""
    from evals.safety.deploy_check import Creds, _with_csrf, login as _login

    lid, pw = os.environ.get(f"PROBE_{who}_LOGIN") or "", os.environ.get(f"PROBE_{who}_PASSWORD") or ""
    if not lid or not pw:
        raise LoginFailed(f"계정 {who} 환경 변수가 없다")
    why = ""
    for _ in range(tries):
        uid, why = _login(c, Creds(lid, pw))
        if uid:
            _with_csrf(c)
            return uid
        time.sleep(wait_s)
    raise LoginFailed(f"로그인 실패({who}): {why}")


def post_regulation_updated(base: str, changes: list[dict]) -> tuple[int, dict]:
    """서비스 키로 `POST /webhooks/regulation-updated`(로그인 쿠키 없는 새 연결). 키는 환경 변수 SERVICE_API_KEY에서만 읽는다."""
    key = os.environ.get("SERVICE_API_KEY") or ""
    if not key:
        raise RuntimeError("SERVICE_API_KEY 없음")
    with client(base) as c:
        r = c.post("/webhooks/regulation-updated", json=changes, headers={"X-Service-Key": key, "Accept": "application/json"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}
