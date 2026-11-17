"""Keyless demo: log in as demo-user, ask the README's 9 recorded questions via POST /chat (SSE), record results.

Usage: python -I ask_demo.py <clone_dir> <out_dir> [base_url]
The demo password is read from <clone_dir>/.env.example (README documents it for local demo) and never printed.
"""
import http.cookiejar
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
clone, out = Path(sys.argv[1]), Path(sys.argv[2])
base = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000"

QUESTIONS = [  # README "키 없이 뜨는 데모 모드" order: 7 cited answers, then 2 refusals
    ("제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?", "answer"),
    ("CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?", "answer"),
    ("클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?", "answer"),
    ("EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?", "answer"),
    ("외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?", "answer"),
    ("외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요?", "answer"),
    ("외부 SaaS 구매 비용이 10만 달러라면 업무 승인자와 재무 승인자는 누구인가요?", "answer"),
    ("구매 승인에는 어떤 승인자가 필요한가요?", "refuse"),
    ("오늘 점심 메뉴 추천해줘", "refuse"),
]

env = {}
for line in (clone / ".env.example").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
login_id, password = env["DEMO_USER_LOGIN_ID"], env["DEMO_USER_PASSWORD"]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def cookie(name):
    for c in jar:
        if c.name == name:
            return c.value
    return None


def req(method, path, body=None, accept="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    r.add_header("Accept", accept)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    tok = cookie("provena_csrf")
    if tok:
        r.add_header("X-CSRF-Token", tok)
    return opener.open(r, timeout=120)


log = []
h = req("GET", "/health")
log.append(f"GET /health -> {h.status} {h.read().decode()[:60]}")
c = req("GET", "/auth/csrf")
log.append(f"GET /auth/csrf -> {c.status}")
lg = req("POST", "/auth/login", {"login_id": login_id, "password": password})
lg_body = json.loads(lg.read().decode() or "{}")
log.append(f"POST /auth/login ({login_id}) -> {lg.status} keys={sorted(lg_body)}")

rows = []
for n, (q, expected) in enumerate(QUESTIONS, 1):
    t0 = time.perf_counter()
    status, events, err = None, [], None
    try:
        resp = req("POST", "/chat", {"message": q}, accept="text/event-stream")
        status = resp.status
        ev_type, buf = None, []
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                ev_type = line[6:].strip()
            elif line.startswith("data:"):
                buf.append(line[5:].lstrip())
            elif line == "":
                if ev_type and buf:
                    events.append((ev_type, json.loads("\n".join(buf))))
                    if ev_type in ("done", "error"):
                        break
                ev_type, buf = None, []
    except urllib.error.HTTPError as e:
        status, err = e.code, e.read().decode()[:200]
    secs = round(time.perf_counter() - t0, 2)
    text = "".join(d.get("data", {}).get("text", "") or "" for t, d in events if t == "token")
    cites = [d.get("data", {}) for t, d in events if t == "citation"]
    done = next((d.get("data", {}) for t, d in events if t == "done"), {})
    kind = done.get("kind") or ("error" if err or any(t == "error" for t, _ in events) else None)
    attribution = done.get("attribution") or {}
    cite_rows = [{k: ci.get(k) for k in ci if k != "text"} for ci in cites]
    rows.append({
        "n": n, "question": q, "expected": expected, "http_status": status, "kind": kind,
        "matches_expected": kind == expected, "citations": len(cites),
        "cited": cite_rows,
        "cited_version_dates": sorted({str(ci.get("version_date")) for ci in cites if ci.get("version_date")}),
        "attribution_source": attribution.get("source"), "attribution_license": attribution.get("license"),
        "answer_mentions_handbook": "GitLab Handbook" in text, "answer_mentions_version_date": "판 날짜" in text,
        "cost_usd": (done.get("usage") or {}).get("cost_usd"), "seconds": secs,
        "refuse_reason": done.get("refuse_reason"), "error": err, "answer": text,
        "asked_at": datetime.now(KST).isoformat(timespec="seconds"),
    })
    print(n, status, kind, len(cites), secs, flush=True)

out.mkdir(parents=True, exist_ok=True)
with (out / "answers.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
(out / "api_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
print("\n".join(log))
