"""리콜 웹훅 수신 쪽 서명 검증 예제 (mock_erp/python_example/python_example.md).

플랫폼이 보내는 형식(backend/graph/recall/webhook.py): 구독 주소로 POST, 본문은 리콜 알림 JSON,
헤더 `X-Signature: sha256=<HMAC-SHA256(비밀값, 받은 원본 본문 bytes) 16진수>`. 서명은 받은 bytes 그대로로 계산한다
(JSON으로 읽은 뒤 다시 직렬화하면 달라진다). 비밀값은 구독의 `secret_ref`가 가리키는 값과 같아야 하며 환경 변수 `RECALL_WEBHOOK_SECRET`으로 받는다.

    RECALL_WEBHOOK_SECRET=비밀값 python mock_erp/python_example/webhook_receiver.py [포트]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SIGNATURE_HEADER = "X-Signature"
SECRET_ENV = "RECALL_WEBHOOK_SECRET"
PATH = "/webhooks/recall"


def sign_payload(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    """접두사 `sha256=`가 없거나 값이 다르면 False. 시간 일정 비교."""
    if not header or not secret:
        return False
    return hmac.compare_digest(sign_payload(body, secret), header)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        secret = os.environ.get(SECRET_ENV, "")
        if self.path != PATH:
            self.send_response(404)
        elif not verify_signature(body, self.headers.get(SIGNATURE_HEADER), secret):
            self.send_response(401)
        else:
            notice = json.loads(body.decode("utf-8"))
            print("리콜 알림 수신:", json.dumps(notice, ensure_ascii=False)[:300], flush=True)
            self.send_response(204)
        self.end_headers()

    def log_message(self, *args) -> None:  # 요청 로그에 본문·헤더를 남기지 않는다
        pass


if __name__ == "__main__":
    if not os.environ.get(SECRET_ENV):
        raise SystemExit(f"환경 변수 {SECRET_ENV}가 없다")
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8081), Handler).serve_forever()