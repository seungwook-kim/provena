"""모의 업무시스템 화면(erp_screen.html)을 띄운다. 표준 라이브러리만 쓴다.

    PROVENA_BASE_URL=http://localhost:8000 python mock_erp/serve_screen.py   # 그 뒤 http://localhost:8765/ 를 연다

API 서버에는 CORS 설정이 없어 다른 주소의 화면에서 쿠키 로그인을 못 한다. 그래서 `/`는 화면 파일을 내주고,
나머지 경로는 API 서버로 그대로 넘긴다(프록시).
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "erp_screen.html"
FORWARD_REQUEST = ("Cookie", "Content-Type", "X-CSRF-Token", "Accept")


def make_handler(upstream: str):
    upstream = upstream.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else None
            req = urllib.request.Request(upstream + self.path, data=data, method=self.command,
                                         headers={h: self.headers[h] for h in FORWARD_REQUEST if self.headers.get(h)})
            try:
                resp = urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                resp = e
            except OSError:
                self._send(502, b"API server unreachable", "text/plain; charset=utf-8", [])
                return
            with resp:
                self._send(resp.status, resp.read(), resp.headers.get("Content-Type", "application/octet-stream"),
                           resp.headers.get_all("Set-Cookie") or [])

        def _send(self, status: int, body: bytes, ctype: str, cookies: list[str]) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8", [])
            else:
                self._proxy()

        do_POST = _proxy  # noqa: N815

        def log_message(self, fmt, *args) -> None:  # 요청 본문·쿠키는 남기지 않는다
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    return Handler


def main() -> int:
    upstream = os.environ.get("PROVENA_BASE_URL", "http://localhost:8000")
    port = int(os.environ.get("MOCK_ERP_PORT", "8765"))
    print(f"모의 업무시스템 화면: http://localhost:{port}/  (API: {upstream})")
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(upstream)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
