"""배포 점검: 배포된 서비스(또는 시험용 앱)에 사용자 A·B로 접속해 신뢰 경계를 확인한다 (SDD 9장, `evals/safety/safety.md`).

확인하는 것
- 로그인하지 않은 요청은 401이다.
- 사용자 B는 A의 대화를 읽지 못한다(404, 목록에도 없음). B의 기억 조회에 A의 기억이 섞이지 않는다.
- 관리자 전용 경로(`GET /approvals`, `POST /decision-tables/convert`, `POST /approvals/{id}`)는 일반 사용자에게 403이다.
- 오류 본문에 스택 트레이스가 없고 보낸 입력값을 되풀이하지 않는다.
- 응답 헤더에 `X-Content-Type-Options`와 `X-Frame-Options`가 있다.

접속 주소와 두 계정의 로그인 정보는 환경 변수로만 받는다(파일에 쓰지 않고, 출력에도 내지 않는다). 질문(LLM 호출)은 하지 않는다.
A의 대화가 없으면 그 점검은 건너뛴다(`DEPLOY_CHECK_A_THREAD_ID`로 대화 id를 주거나, 한 번 질문한 뒤 다시 돌린다).

    환경 변수: DEPLOY_CHECK_BASE_URL, DEPLOY_CHECK_A_LOGIN, DEPLOY_CHECK_A_PASSWORD, DEPLOY_CHECK_B_LOGIN, DEPLOY_CHECK_B_PASSWORD
    선택: DEPLOY_CHECK_A_THREAD_ID(A의 대화 id), DEPLOY_CHECK_WRITE_MEMORY(기본 1: A의 기억에 표식을 쓰고 원래대로 되돌려 B 조회와 대조. 0이면 쓰지 않음)
    python -m evals.safety.deploy_check [--out evals/results/deploy_check.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable

AUTH_COOKIE = "provena_auth"
CSRF_COOKIE = "provena_csrf"
CSRF_HEADER = "X-CSRF-Token"
ENV_REQUIRED = ("DEPLOY_CHECK_BASE_URL", "DEPLOY_CHECK_A_LOGIN", "DEPLOY_CHECK_A_PASSWORD", "DEPLOY_CHECK_B_LOGIN", "DEPLOY_CHECK_B_PASSWORD")
JSON_ACCEPT = {"Accept": "application/json"}
STACK_TRACE = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+|\.py\", line \d+|\bat [\w.$]+\([\w$]+\.java:\d+\)")
ANON_PROBES = (("GET", "/me"), ("GET", "/threads"), ("GET", "/threads/probe-thread"), ("GET", "/me/memory"), ("GET", "/approvals"), ("GET", "/decision-tables"))


@dataclass
class Check:
    id: str
    desc: str
    status: str   # 통과 | 실패 | 건너뜀
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == "실패"


@dataclass
class Creds:
    login_id: str
    password: str


def _set_cookies(client, headers) -> None:
    """Set-Cookie 응답에서 값을 읽어 클라이언트에 심는다. Secure 표시와 상관없이(시험 앱은 http) 다음 요청에 보내게 한다."""
    for raw in headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        value = rest.split(";", 1)[0]
        if name in (AUTH_COOKIE, CSRF_COOKIE):
            client.cookies.delete(name)   # 응답이 이미 쿠키 저장소에 넣은 같은 이름을 지우고 한 개만 둔다
            client.cookies.set(name, value)


def _with_csrf(client) -> None:
    r = client.get("/auth/csrf")
    _set_cookies(client, r.headers)
    token = client.cookies.get(CSRF_COOKIE)
    if token:
        client.headers[CSRF_HEADER] = token


def login(client, creds: Creds) -> tuple[str | None, str]:
    """로그인해 (user_id, 사유). 사유에는 상태 코드만 쓴다(비밀번호·응답 본문을 남기지 않는다)."""
    _with_csrf(client)
    r = client.post("/auth/login", json={"login_id": creds.login_id, "password": creds.password})
    if r.status_code != 200:
        return None, f"로그인 응답 {r.status_code}"
    _set_cookies(client, r.headers)
    try:
        return str(r.json().get("user_id")), "ok"
    except ValueError:
        return None, "로그인 응답이 JSON이 아님"


def _code(r) -> str:
    try:
        return str(((r.json() or {}).get("error") or {}).get("code") or "")
    except ValueError:
        return ""


def _text(r) -> str:
    try:
        return r.text
    except Exception:  # noqa: BLE001
        return ""


def check_unauthenticated(make_client) -> Check:
    bad = []
    c = make_client()
    for method, path in ANON_PROBES:
        r = c.request(method, path, headers=JSON_ACCEPT)
        if r.status_code != 401:
            bad.append(f"{method} {path} -> {r.status_code}")
    _with_csrf(c)   # CSRF 검사에 걸려 403이 나오는 것과 구분하려고 헤더를 갖춘 뒤 보낸다
    r = c.post("/chat", json={"message": "probe"}, headers=JSON_ACCEPT)
    if r.status_code != 401:
        bad.append(f"POST /chat -> {r.status_code}")
    return Check("U1", "로그인하지 않은 요청은 401이다", "실패" if bad else "통과", "; ".join(bad) or f"{len(ANON_PROBES) + 1}개 경로 모두 401")


def check_other_users_thread(a, b, a_id: str, b_id: str, thread_id: str | None) -> Check:
    desc = "사용자 B는 A의 대화를 읽지 못한다(404)"
    if not thread_id:
        listed = a.get("/threads").json().get("threads") if a.get("/threads").status_code == 200 else []
        thread_id = (listed[0]["thread_id"] if listed else None)
    if not thread_id:
        return Check("X1", desc, "건너뜀", "A의 대화가 없어 점검하지 못했다(A가 질문 1건을 한 뒤 다시 돌리거나 DEPLOY_CHECK_A_THREAD_ID를 준다)")
    own = a.get(f"/threads/{thread_id}")
    if own.status_code != 200:
        return Check("X1", desc, "실패", f"A가 자기 대화를 읽지 못해 비교할 수 없다(응답 {own.status_code})")
    other = b.get(f"/threads/{thread_id}", headers=JSON_ACCEPT)
    listing = b.get("/threads")
    leaked_in_list = listing.status_code == 200 and any(t.get("thread_id") == thread_id for t in listing.json().get("threads", []))
    bad = []
    if other.status_code != 404 or _code(other) != "not_found":
        bad.append(f"B의 조회 응답 {other.status_code}/{_code(other)}")
    if leaked_in_list:
        bad.append("B의 대화 목록에 A의 대화가 있음")
    return Check("X1", desc, "실패" if bad else "통과", "; ".join(bad) or "B의 조회 404(not_found), B의 목록에 없음")


def check_other_users_memory(a, b, a_id: str, b_id: str, write: bool) -> Check:
    desc = "B의 기억 조회에 A의 기억이 섞이지 않는다"
    before = a.get("/me/memory")
    if before.status_code != 200:
        return Check("X2", desc, "실패", f"A의 기억 조회 응답 {before.status_code}")
    original = before.json().get("profile") or {}
    marker = "dc-" + uuid.uuid4().hex[:10]
    wrote = False
    if write:
        w = a.patch("/me/memory", json={"affiliation": marker})
        wrote = w.status_code == 200
        if not wrote:
            return Check("X2", desc, "실패", f"A의 기억에 표식을 쓰지 못했다(응답 {w.status_code})")
    try:
        probe = marker if wrote else json.dumps(original, ensure_ascii=False)
        mine = b.get("/me/memory")
        spoof = b.get("/me/memory", params={"user_id": a_id})
        direct = b.get(f"/me/memory/{a_id}", headers=JSON_ACCEPT)
        bad = []
        for label, r in (("B 조회", mine), ("user_id를 A로 준 B 조회", spoof)):
            if r.status_code != 200 or r.json().get("user_id") != b_id:
                bad.append(f"{label}: 응답 {r.status_code}, 다른 사용자 id")
            elif wrote and probe in _text(r):
                bad.append(f"{label}에 A의 표식이 있음")
            elif not wrote and original and probe in _text(r):
                bad.append(f"{label}에 A의 기억이 있음")
        if direct.status_code not in (404, 405) or (wrote and marker in _text(direct)):
            bad.append(f"A의 id를 경로에 준 조회 응답 {direct.status_code}")
        note = "A의 기억이 비어 있어 표식 없이는 대조할 수 없다" if (not wrote and not original) else ""
        status = "실패" if bad else ("건너뜀" if note else "통과")
        return Check("X2", desc, status, "; ".join(bad) or note or "B의 조회 3가지 모두 B 자신의 기억만 나옴(표식 대조)")
    finally:
        if wrote:   # A의 기억을 원래대로
            if original:
                a.patch("/me/memory", json={k: v for k, v in original.items() if k in ("affiliation", "rank")})
            else:
                a.delete("/me/memory")


def check_admin_routes(user) -> Check:
    bad = []
    r = user.get("/approvals", headers=JSON_ACCEPT)
    if r.status_code != 403:
        bad.append(f"GET /approvals -> {r.status_code}")
    r = user.post("/decision-tables/convert", json={"category": "probe"}, headers=JSON_ACCEPT)
    if r.status_code != 403:
        bad.append(f"POST /decision-tables/convert -> {r.status_code}")
    r = user.post("/approvals/probe-approval", json={"approve": False, "comment": "probe"}, headers=JSON_ACCEPT)
    if r.status_code != 403:
        bad.append(f"POST /approvals/{{id}} -> {r.status_code}")
    return Check("R1", "관리자 전용 경로는 일반 사용자에게 403이다", "실패" if bad else "통과", "; ".join(bad) or "3개 경로 모두 403")


def check_error_bodies(anon_make, a) -> Check:
    marker = "dc-echo-" + uuid.uuid4().hex[:10]
    c = anon_make()
    _with_csrf(c)
    cases = [
        ("422 로그인 형식 오류", c.post("/auth/login", json={"login_id": "probe", "password": {"x": marker}}, headers=JSON_ACCEPT)),
        ("422 기억 길이 초과", a.patch("/me/memory", json={"affiliation": marker + "x" * 101}, headers=JSON_ACCEPT)),
        ("404 없는 대화", a.get(f"/threads/{marker}", headers=JSON_ACCEPT)),
        ("깨진 JSON", a.post("/decision-tables/run", content=b'{"task_type": ' + marker.encode(), headers={**JSON_ACCEPT, "Content-Type": "application/json"})),
        ("401 로그인 안 됨", c.get(f"/threads/{marker}", headers=JSON_ACCEPT)),
    ]
    bad = []
    for label, r in cases:
        body = _text(r)
        if r.status_code >= 500:
            bad.append(f"{label}: 서버 오류 {r.status_code}")
        if STACK_TRACE.search(body):
            bad.append(f"{label}: 스택 트레이스가 보임")
        if marker in body:
            bad.append(f"{label}: 보낸 입력값을 되풀이함")
        if r.status_code >= 400 and not _code(r):
            bad.append(f"{label}: 오류 규약(error.code) 본문이 아님")
    return Check("E1", "오류 본문에 스택 트레이스와 입력값이 없다", "실패" if bad else "통과", "; ".join(bad) or f"{len(cases)}가지 오류 응답 모두 깨끗함")


def check_security_headers(make_client, a) -> Check:
    bad = []
    c = make_client()
    probes = (("GET /health", c.get("/health")), ("GET /auth/csrf", c.get("/auth/csrf")), ("401 응답", c.get("/me", headers=JSON_ACCEPT)),
              ("로그인 후 GET /threads", a.get("/threads")))
    for label, r in probes:
        h = r.headers
        if (h.get("x-content-type-options") or "").lower() != "nosniff":
            bad.append(f"{label}: X-Content-Type-Options 없음")
        if (h.get("x-frame-options") or "").upper() not in ("DENY", "SAMEORIGIN"):
            bad.append(f"{label}: X-Frame-Options 없음")
    return Check("H1", "응답에 X-Content-Type-Options와 X-Frame-Options가 있다", "실패" if bad else "통과", "; ".join(bad) or f"{len(probes)}개 응답 모두 있음")


def run_checks(make_client: Callable[[], Any], a_creds: Creds, b_creds: Creds, *, a_thread_id: str | None = None, write_memory: bool = True) -> list[Check]:
    """`make_client()`는 쿠키가 따로 보관되는 새 HTTP 클라이언트(httpx 호환)를 돌려준다."""
    out: list[Check] = []
    a, b = make_client(), make_client()
    (a_id, why_a), (b_id, why_b) = login(a, a_creds), login(b, b_creds)
    if not a_id or not b_id:
        return [Check("L0", "두 계정으로 로그인한다", "실패", f"A: {why_a}; B: {why_b}")]
    out.append(Check("L0", "두 계정으로 로그인한다", "통과" if a_id != b_id else "실패", "A와 B의 user_id가 다름" if a_id != b_id else "A와 B가 같은 계정이다"))
    out.append(check_unauthenticated(make_client))
    out.append(check_other_users_thread(a, b, a_id, b_id, a_thread_id))
    out.append(check_other_users_memory(a, b, a_id, b_id, write_memory))
    out.append(check_admin_routes(b))
    out.append(check_error_bodies(make_client, a))
    out.append(check_security_headers(make_client, a))
    return out


def render(checks: list[Check]) -> str:
    lines = ["| 번호 | 점검 | 결과 | 근거 |", "|---|---|---|---|"]
    lines += [f"| {c.id} | {c.desc} | {c.status} | {c.detail} |" for c in checks]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="배포 점검(사용자 A·B 접속, 환경 변수로만 설정)")
    ap.add_argument("--out", default="", help="결과 JSON을 쓸 경로(비밀번호는 쓰지 않는다)")
    args = ap.parse_args(argv)
    missing = [n for n in ENV_REQUIRED if not os.environ.get(n)]
    if missing:
        print("환경 변수가 없다: " + ", ".join(missing), file=sys.stderr)
        return 2
    import httpx

    base = os.environ["DEPLOY_CHECK_BASE_URL"].rstrip("/")
    checks = run_checks(lambda: httpx.Client(base_url=base, timeout=30.0),
                        Creds(os.environ["DEPLOY_CHECK_A_LOGIN"], os.environ["DEPLOY_CHECK_A_PASSWORD"]),
                        Creds(os.environ["DEPLOY_CHECK_B_LOGIN"], os.environ["DEPLOY_CHECK_B_PASSWORD"]),
                        a_thread_id=os.environ.get("DEPLOY_CHECK_A_THREAD_ID") or None,
                        write_memory=os.environ.get("DEPLOY_CHECK_WRITE_MEMORY", "1") != "0")
    print(render(checks))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"base_url": base, "checks": [asdict(c) for c in checks]}, f, ensure_ascii=False, indent=2)
    return 1 if any(c.failed for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
