"""배포된 플랫폼 API를 부르는 최소 업무시스템 예제: 로그인 -> CSRF -> /chat SSE 읽기 (mock_erp/python_example/python_example.md).

    PROVENA_BASE_URL=https://배포주소 PROVENA_LOGIN_ID=계정 PROVENA_PASSWORD=비밀번호 \
        python mock_erp/python_example/provena_client.py "질문 문장"

표준 라이브러리만 쓴다. 계정과 주소는 환경 변수로만 받고 코드·로그에 남기지 않는다.
흐름(backend/auth.py, backend/api/routes.py):
1. GET /auth/csrf        -> 204, `provena_csrf` 쿠키 발급
2. POST /auth/login      -> 본문 {login_id, password}, 헤더 `X-CSRF-Token` = 쿠키 값, 성공하면 `provena_auth` 쿠키
3. POST /chat            -> 헤더 `X-CSRF-Token`, 본문 {message, thread_id?, as_of?, org?}, 응답은 SSE
   SSE 한 건은 `event: <type>` 과 `data: <AgentEvent JSON>` 이고 type은 token, citation, approval_request, error, done 이다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from http.cookiejar import CookieJar

CSRF_COOKIE = "provena_csrf"
CSRF_HEADER = "X-CSRF-Token"


def parse_sse(lines: Iterable[str | bytes]) -> Iterator[dict]:
    """SSE 줄 스트림을 이벤트로 바꾼다. 빈 줄이 이벤트의 끝이다. `:`로 시작하는 줄(ping)은 건너뛴다.

    돌려주는 값: {"event": 이름, "data": data 줄을 \\n으로 이은 글, "json": 파싱한 data(JSON이 아니면 None)}
    """
    event, data = "message", []

    def flush() -> dict | None:
        nonlocal event, data
        if not data:
            event = "message"
            return None
        text = "\n".join(data)
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        out = {"event": event, "data": text, "json": parsed}
        event, data = "message", []
        return out

    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if line == "":
            item = flush()
            if item is not None:
                yield item
        elif line.startswith(":"):
            continue
        else:
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                event = value
            elif name == "data":
                data.append(value)
    item = flush()
    if item is not None:
        yield item


class ProvenaClient:
    def __init__(self, base_url: str, opener: urllib.request.OpenerDirector | None = None):
        self.base_url = base_url.rstrip("/")
        self.jar = CookieJar()
        self.opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf_token(self) -> str:
        for cookie in self.jar:
            if cookie.name == CSRF_COOKIE:
                return cookie.value
        raise RuntimeError("CSRF 쿠키가 없다. 먼저 fetch_csrf()를 부른다")

    def _post(self, path: str, body: dict):
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", CSRF_HEADER: self._csrf_token()})
        return self.opener.open(req, timeout=120)

    def fetch_csrf(self) -> None:
        self.opener.open(urllib.request.Request(self.base_url + "/auth/csrf"), timeout=30).close()

    def login(self, login_id: str, password: str) -> dict:
        self.fetch_csrf()
        with self._post("/auth/login", {"login_id": login_id, "password": password}) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, message: str, *, thread_id: str | None = None, as_of: str | None = None,
             org: str | None = None) -> Iterator[dict]:
        body = {"message": message, **{k: v for k, v in (("thread_id", thread_id), ("as_of", as_of), ("org", org)) if v}}
        with self._post("/chat", body) as resp:
            yield from parse_sse(resp)


def main(argv: list[str]) -> int:
    question = " ".join(argv[1:]).strip()
    if not question:
        print("사용법: python provena_client.py \"질문 문장\"", file=sys.stderr)
        return 2
    try:
        base, login_id, password = (os.environ[k] for k in ("PROVENA_BASE_URL", "PROVENA_LOGIN_ID", "PROVENA_PASSWORD"))
    except KeyError as exc:
        print(f"환경 변수 {exc.args[0]}가 없다", file=sys.stderr)
        return 2
    client = ProvenaClient(base)
    client.login(login_id, password)
    for ev in client.chat(question):
        payload = (ev["json"] or {}).get("data", {})
        if ev["event"] == "token":
            print(payload.get("text", ""), end="", flush=True)
        elif ev["event"] == "citation":
            print(f"\n[근거] {payload.get('chunk_id')}", flush=True)
        elif ev["event"] in ("approval_request", "error", "done"):
            print(f"\n[{ev['event']}] {json.dumps(payload, ensure_ascii=False)[:300]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))