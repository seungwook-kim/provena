"""리콜 웹훅을 업무시스템으로 보내는 쪽 (SDD 11-1 3-7·3-8, docs/specs/recall.md AC-03, EC-05).

형식: 구독 주소(`url`)로 POST, 본문은 리콜 알림 JSON(`GET /recalls`의 알림 한 건과 같은 모양), 헤더
`X-Signature: sha256=<HMAC-SHA256(secret, 원본 본문 bytes) 16진수>`. 서명은 보내는 bytes 그대로로 계산한다.

- 비밀값: 구독의 `secret_ref`는 비밀값이 든 환경변수 이름이다(`RECALL_WEBHOOK_SECRET` 또는 `RECALL_WEBHOOK_SECRET_<이름>`). 값은 저장소·DB에 적지 않는다.
- 비밀값이 비었을 때(3-8): 로컬 데모 모드(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`)에서만 서명 없이 보낸다. 그 밖에는 보내지 않고
  전송 기록에 `failed`(`secret_missing`)로 남긴다.
- 재시도: 2xx가 아니거나 연결이 실패하면 `RECALL_WEBHOOK_BACKOFF_S`(기본 1초)부터 두 배씩 기다려 다시 보낸다. 최대 `RECALL_WEBHOOK_MAX_TRIES`
  (기본 3)번 시도하고 그래도 실패하면 `failed`. 시도마다 상태 코드·오류 종류·시각을 `webhook_deliveries.attempts`에 남긴다.
- 주소 검사(SSRF 방지): http·https만 받는다. 로컬 데모가 아니면 https만, 내부망·메타데이터 주소는 막는다. 주소 이름을 실제로 풀어 나온 IP가
  공인 주소가 아니면(루프백·사설·링크로컬·예약, `127.0.0.1.nip.io`처럼 이름이 내부 IP를 가리키는 경우, 정수·16진수 IP 표기 포함) 막는다.
  등록할 때와 보낼 때마다 검사한다.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/recall"
SIGNATURE_HEADER = "X-Signature"
SECRET_ENV = "RECALL_WEBHOOK_SECRET"
SECRET_REF_RE = re.compile(r"^RECALL_WEBHOOK_SECRET(_[A-Z0-9_]{1,48})?$")
MAX_TRIES_ENV, BACKOFF_ENV, TIMEOUT_ENV = "RECALL_WEBHOOK_MAX_TRIES", "RECALL_WEBHOOK_BACKOFF_S", "RECALL_WEBHOOK_TIMEOUT_S"
DEFAULT_MAX_TRIES, DEFAULT_BACKOFF, DEFAULT_TIMEOUT = 3, 1.0, 5.0
_BLOCKED_HOSTS = ("localhost", "metadata.google.internal", "metadata")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign_payload(body: bytes, secret: str) -> str:
    """X-Signature 헤더 값("sha256=<hex>")."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    """받는 쪽 검사(시간 일정 비교). 접두사 `sha256=`가 없거나 값이 다르면 False."""
    if not header or not secret:
        return False
    return hmac.compare_digest(sign_payload(body, secret), header)


def encode_body(payload: dict) -> bytes:
    """본문 bytes. 서명과 전송이 같은 bytes를 쓰도록 한 곳에서 만든다."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def resolve_secret(secret_ref: str | None) -> str | None:
    """구독의 secret_ref(환경변수 이름) -> 비밀값. 이름 규칙에 맞지 않거나 비어 있으면 None."""
    ref = secret_ref or SECRET_ENV
    if not SECRET_REF_RE.match(ref):
        return None
    return os.environ.get(ref) or None


def check_secret_ref(secret_ref: str) -> None:
    if not SECRET_REF_RE.match(secret_ref):
        raise ValueError("secret_ref는 RECALL_WEBHOOK_SECRET 또는 RECALL_WEBHOOK_SECRET_<대문자·숫자·밑줄> 이어야 합니다")


def check_target_url(url: str, *, strict: bool) -> None:
    """구독 주소 검사. 위반하면 ValueError. strict(배포)면 https만, 내부망·메타데이터 주소를 막는다."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("url은 http 또는 https 주소여야 합니다")
    if parts.username or parts.password:
        raise ValueError("url에 사용자 정보를 넣을 수 없습니다")
    if not strict:
        return
    if parts.scheme != "https":
        raise ValueError("배포 환경에서는 https 주소만 쓸 수 있습니다")
    host = parts.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith((".internal", ".local", ".localhost")):
        raise ValueError("내부 주소는 쓸 수 없습니다")
    for ip in _resolve(host):
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ValueError("공인 주소가 아닌 IP는 쓸 수 없습니다")


_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){0,3}$", re.I)


def _resolve(host: str) -> list:
    """호스트 -> IP 목록. IP 글자(점 4개 꼴, IPv6, 정수·16진수·8진수 줄임 표기)는 그대로 풀고, 이름은 DNS로 푼다. 풀지 못하면 ValueError."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    if _NUMERIC_HOST.match(host):
        try:
            return [ipaddress.ip_address(socket.inet_aton(host))]
        except OSError:
            raise ValueError("주소를 해석할 수 없습니다") from None
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ValueError("주소 이름을 찾을 수 없습니다") from None
    ips = list(dict.fromkeys(ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos))
    if not ips:
        raise ValueError("주소 이름을 찾을 수 없습니다")
    return ips


def _env_number(name: str, default: float, cast: type) -> Any:
    raw = (os.environ.get(name) or "").strip()
    try:
        v = cast(raw) if raw else default
    except ValueError:
        return default
    return v if v >= 0 else default


def _local_demo() -> bool:
    from backend.services.demo_seed import is_local_demo

    return is_local_demo()


def _http_post(timeout: float) -> Callable[[str, bytes, dict], int]:
    def post(url: str, content: bytes, headers: dict) -> int:
        import httpx

        return httpx.post(url, content=content, headers=headers, timeout=timeout, follow_redirects=False).status_code

    return post


class WebhookSender:
    """켜진 구독마다 본문을 보내고 시도를 기록한다. `post(url, bytes, headers) -> 상태 코드`와 `sleep`은 시험에서 바꿔 넣는다."""

    def __init__(self, store: Any, *, post: Callable[[str, bytes, dict], int] | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_tries: int | None = None, backoff: float | None = None, local_demo: bool | None = None) -> None:
        self.store = store
        self.max_tries = max(1, int(max_tries if max_tries is not None else _env_number(MAX_TRIES_ENV, DEFAULT_MAX_TRIES, int)))
        self.backoff = backoff if backoff is not None else _env_number(BACKOFF_ENV, DEFAULT_BACKOFF, float)
        self.post = post or _http_post(_env_number(TIMEOUT_ENV, DEFAULT_TIMEOUT, float))
        self.sleep = sleep
        self.local_demo = _local_demo() if local_demo is None else local_demo

    def send(self, notice_id: str, body: bytes, *, kind: str = "notice") -> list[dict]:
        """구독마다 전송 한 건. 반환: 전송 기록 목록(status = success | failed)."""
        out = []
        for sub in self.store.subs(active_only=True):
            out.append(self._deliver(sub, notice_id, body, kind))
        return out

    def _deliver(self, sub: dict, notice_id: str, body: bytes, kind: str) -> dict:
        rec = {"delivery_id": "wd-" + uuid.uuid4().hex[:16], "sub_id": sub["sub_id"], "notice_id": notice_id, "kind": kind,
               "status": "pending", "tries": 0, "last_status_code": None, "last_error": None, "attempts": []}
        self.store.delivery_add(rec)
        secret = resolve_secret(sub.get("secret_ref"))
        headers = {"Content-Type": "application/json", "X-Webhook-Delivery": rec["delivery_id"]}
        if secret:
            headers[SIGNATURE_HEADER] = sign_payload(body, secret)
        elif not self.local_demo:   # 3-8: 배포 주소는 서명 필수. 서명 없는 웹훅은 보내지 않는다
            log.error("웹훅 비밀값이 비어 있어 보내지 않았습니다 sub=%s", sub["sub_id"])
            return self._finish(rec, "failed", None, "secret_missing")
        try:
            check_target_url(sub["url"], strict=not self.local_demo)
        except ValueError as e:
            return self._finish(rec, "failed", None, f"blocked_url: {e}"[:200])
        for i in range(self.max_tries):
            code, error = None, None
            try:
                code = int(self.post(sub["url"], body, headers))
                ok = 200 <= code < 300
                if not ok:
                    error = f"http_{code}"
            except Exception as e:  # noqa: BLE001 - 연결 오류·시간 초과 등. 종류만 남긴다(주소에 비밀이 섞일 수 있다)
                ok, error = False, type(e).__name__
            rec["tries"] = i + 1
            rec["attempts"].append({"at": now_iso(), "ok": ok, "status_code": code, "error": error})
            rec["last_status_code"], rec["last_error"] = code, error
            if ok:
                return self._finish(rec, "success", code, None)
            if i + 1 < self.max_tries:
                self.store.delivery_update(rec["delivery_id"], status="pending", tries=rec["tries"], last_status_code=code,
                                           last_error=error, attempts=rec["attempts"])
                self.sleep(self.backoff * (2 ** i))
        log.error("웹훅 전송을 포기합니다 delivery=%s tries=%d", rec["delivery_id"], rec["tries"])
        return self._finish(rec, "failed", rec["last_status_code"], rec["last_error"])

    def _finish(self, rec: dict, status: str, code: int | None, error: str | None) -> dict:
        rec.update(status=status, last_status_code=code, last_error=error)
        if error and not rec["attempts"]:
            rec["attempts"].append({"at": now_iso(), "ok": False, "status_code": None, "error": error})
        self.store.delivery_update(rec["delivery_id"], status=status, tries=rec["tries"], last_status_code=code, last_error=error,
                                   attempts=rec["attempts"])
        return rec
