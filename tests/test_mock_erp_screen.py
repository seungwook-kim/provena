"""모의 업무시스템 화면 시험 (mock_erp/erp_screen.html, serve_screen.py). 외부 네트워크 없이 같은 컴퓨터의 가짜 서버만 쓴다."""
from __future__ import annotations

import importlib.util
import json
import re
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK_ERP = ROOT / "mock_erp"
PAGE = MOCK_ERP / "erp_screen.html"


def _route_table() -> set[str]:
    """backend/ 라우트 데코레이터에서 'METHOD 경로' 집합."""
    found = set()
    for py in (ROOT / "backend").rglob("*.py"):
        for m in re.finditer(r'@\w+\.(get|post)\(\s*"(/[^"]*)"', py.read_text(encoding="utf-8")):
            found.add(f"{m.group(1).upper()} {m.group(2)}")
    return found


def test_page_is_labelled_mock():
    html = PAGE.read_text(encoding="utf-8")
    assert "모의 업무시스템" in html and "<title>모의 업무시스템</title>" in html


def test_page_calls_only_existing_routes():
    html = PAGE.read_text(encoding="utf-8")
    called = {f"{m.group(1)} {m.group(2)}" for m in re.finditer(r"(?:call|show)\('(GET|POST)', '(/[^']*)'", html)}
    assert len(called) >= 6
    assert called <= _route_table(), called - _route_table()


def _load_server():
    spec = importlib.util.spec_from_file_location("mock_erp_serve_screen", MOCK_ERP / "serve_screen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_serve_screen_serves_page_and_forwards_cookie_and_csrf():
    seen = {}

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.update(path=self.path, csrf=self.headers.get("X-CSRF-Token"), cookie=self.headers.get("Cookie"), body=json.loads(body))
            out = b'{"ok": true}'
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "provena_auth=x; HttpOnly")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = HTTPServer(("127.0.0.1", 0), Upstream)
    front = HTTPServer(("127.0.0.1", 0), _load_server().make_handler(f"http://127.0.0.1:{up.server_port}"))
    for s in (up, front):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{front.server_port}"
        with urllib.request.urlopen(base + "/", timeout=10) as r:
            assert "모의 업무시스템" in r.read().decode("utf-8")
        req = urllib.request.Request(base + "/decision-tables/run", data=b'{"task_type": "t"}', method="POST",
                                     headers={"Content-Type": "application/json", "X-CSRF-Token": "tok", "Cookie": "other=1; provena_csrf=tok"})
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 201 and r.headers.get("Set-Cookie") == "provena_auth=x; HttpOnly"
        assert seen == {"path": "/decision-tables/run", "csrf": "tok", "cookie": "provena_csrf=tok", "body": {"task_type": "t"}}
    finally:
        for s in (up, front):
            s.shutdown()
            s.server_close()


def test_only_provena_cookies_are_forwarded():
    f = _load_server().only_provena_cookies
    assert f("a=1; provena_auth=x; other=2; provena_csrf=y") == "provena_auth=x; provena_csrf=y"
    assert f("a=1") == "" and f(None) == ""


def test_serve_screen_rejects_paths_that_could_change_the_host_and_does_not_follow_redirects():
    import http.client

    hits = []

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    other = HTTPServer(("127.0.0.1", 0), Other)

    class Redirecting(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append("upstream " + self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_port}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    up = HTTPServer(("127.0.0.1", 0), Redirecting)
    front = HTTPServer(("127.0.0.1", 0), _load_server().make_handler(f"http://127.0.0.1:{up.server_port}"))
    for s in (other, up, front):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        for bad in (f"127.0.0.1:{other.server_port}/x", "x"):
            conn = http.client.HTTPConnection("127.0.0.1", front.server_port, timeout=10)
            conn.request("GET", bad)
            assert conn.getresponse().status == 400
            conn.close()
        assert hits == []                                        # 어느 쪽 서버에도 닿지 않았다
        conn = http.client.HTTPConnection("127.0.0.1", front.server_port, timeout=10)
        conn.request("GET", f"//127.0.0.1:{other.server_port}/x")   # 표준 라이브러리가 맨 앞 `//`를 `/`로 줄이므로 API 서버의 경로로만 간다
        conn.getresponse().read()
        conn.close()
        assert all(h.startswith("upstream ") for h in hits)
        hits.clear()
        conn = http.client.HTTPConnection("127.0.0.1", front.server_port, timeout=10)
        conn.request("GET", "/go")
        assert conn.getresponse().status == 302                   # 따라가지 않고 그대로 돌려준다
        conn.close()
        assert hits == ["upstream /go"]
    finally:
        for s in (other, up, front):
            s.shutdown()
            s.server_close()
