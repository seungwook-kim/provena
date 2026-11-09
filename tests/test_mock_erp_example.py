"""업무시스템 Python 예제 시험 (mock_erp/python_example/). 외부 네트워크 없이 돈다(서명 검증, SSE 파싱, 같은 컴퓨터의 가짜 서버로 로그인->CSRF->/chat 흐름)."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.graph.recall import webhook as platform_webhook

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "mock_erp" / "python_example"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mock_erp_{name}", EXAMPLE_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


client = _load("provena_client")
receiver = _load("webhook_receiver")
SECRET = "test-secret-value"


def test_signature_matches_platform_sender():
    body = platform_webhook.encode_body({"notice_id": "n-1", "title": "정책 개정", "changed": True})
    header = platform_webhook.sign_payload(body, SECRET)
    assert receiver.sign_payload(body, SECRET) == header
    assert receiver.verify_signature(body, header, SECRET)


def test_signature_rejects_tampered_body_wrong_secret_and_bad_header():
    body = platform_webhook.encode_body({"notice_id": "n-1"})
    header = platform_webhook.sign_payload(body, SECRET)
    assert not receiver.verify_signature(body + b" ", header, SECRET)
    assert not receiver.verify_signature(body, header, "other-secret")
    assert not receiver.verify_signature(body, header.removeprefix("sha256="), SECRET)
    assert not receiver.verify_signature(body, None, SECRET)
    assert not receiver.verify_signature(body, header, "")


def test_parse_sse_events_ping_and_multiline_data():
    stream = [
        ": ping - 2026-11-09\r\n", "\r\n",
        "event: token\r\n", 'data: {"type":"token","thread_id":"t-1","data":{"text":"안녕"}}\r\n', "\r\n",
        "event: citation\n", 'data: {"type":"citation","thread_id":"t-1","data":{"chunk_id":"c1"}}\n', "\n",
        "event: error\n", "data: 첫 줄\n", "data: 둘째 줄\n", "\n",
        "event: done\n", 'data: {"type":"done","thread_id":"t-1","data":{"kind":"answer"}}',   # 마지막 빈 줄 없이 끝남
    ]
    events = list(client.parse_sse(stream))
    assert [e["event"] for e in events] == ["token", "citation", "error", "done"]
    assert events[0]["json"]["data"]["text"] == "안녕"
    assert events[2]["json"] is None and events[2]["data"] == "첫 줄\n둘째 줄"
    assert events[3]["json"]["data"]["kind"] == "answer"


def test_parse_sse_accepts_bytes():
    events = list(client.parse_sse([b"event: token\n", b'data: {"a": 1}\n', b"\n"]))
    assert events == [{"event": "token", "data": '{"a": 1}', "json": {"a": 1}}]


class _Fake(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str | None]] = []

    def _csrf_ok(self) -> bool:
        cookie = (self.headers.get("Cookie") or "")
        return "provena_csrf=tok123" in cookie and self.headers.get("X-CSRF-Token") == "tok123"

    def do_GET(self):  # noqa: N802
        self.seen.append(("GET", self.path, None))
        self.send_response(204)
        self.send_header("Set-Cookie", "provena_csrf=tok123; Path=/")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.seen.append(("POST", self.path, self.headers.get("X-CSRF-Token")))
        if not self._csrf_ok():
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/auth/login":
            ok = json.loads(body) == {"login_id": "erp", "password": "pw"}
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "provena_auth=jwt; Path=/")
            self.end_headers()
            self.wfile.write(json.dumps({"user_id": "u1", "role": "user"}).encode())
        elif self.path == "/chat":
            assert "provena_auth=jwt" in (self.headers.get("Cookie") or "")
            assert json.loads(body)["message"] == "승인권자는?"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for kind, data in (("token", {"text": "팀장"}), ("done", {"kind": "answer"})):
                payload = json.dumps({"type": kind, "thread_id": "t-1", "data": data}, ensure_ascii=False)
                self.wfile.write(f"event: {kind}\r\ndata: {payload}\r\n\r\n".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def test_login_csrf_chat_flow_against_local_fake_server():
    _Fake.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        c = client.ProvenaClient(f"http://127.0.0.1:{server.server_port}")
        assert c.login("erp", "pw") == {"user_id": "u1", "role": "user"}
        events = list(c.chat("승인권자는?"))
    finally:
        server.shutdown()
        server.server_close()
    assert [e["event"] for e in events] == ["token", "done"]
    assert events[0]["json"]["data"]["text"] == "팀장"
    assert [s[:2] for s in _Fake.seen] == [("GET", "/auth/csrf"), ("POST", "/auth/login"), ("POST", "/chat")]
    assert all(s[2] == "tok123" for s in _Fake.seen[1:])


def test_chat_without_login_fails_before_sending():
    c = client.ProvenaClient("http://127.0.0.1:9")
    try:
        list(c.chat("질문"))
    except RuntimeError as exc:
        assert "CSRF" in str(exc)
    else:
        raise AssertionError("CSRF 쿠키 없이 보내면 안 된다")