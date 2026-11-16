"""키 없이 뜬 로컬 서비스(새 clone, `.env` 없음)에서 README 데모 구간 03(팀 합동 검토, 리콜)을 API로 따라가 결과를 기록한다. 비용 0원.

    python evals/results/fresh_clone_20261116_demo_review_recall/scenario_check.py --base-url http://localhost:8000 --clone <새 clone> --out <폴더>

순서: README 질문 9개(`ask_readme_questions.py`)를 먼저 보낸 뒤 실행한다(5만·3만 달러 질문의 답이 리콜 대상이 된다).
1. 합동 검토: `demo-user`가 `data/demo_replay/scenarios.json`의 검토 요청을 `/chat`으로 보내 `approval_request`(쟁점표)를 받고, `demo-admin`이 `POST /approvals/{id}`로 승인한다.
2. 리콜: `demo-admin`이 `POST /recalls/process-pending`(리콜 화면 "처리 대기 변경 지금 처리")을 부르고, `demo-user`와 `demo-admin`의 `GET /recalls`로 알림을 읽는다.
데모 계정 비밀번호는 새 clone의 `.env.example`에 적힌 공개 데모 값이다. 비밀번호·쿠키는 기록하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from evals.agent.review_deploy import compact_rows, fetch_issue_table, post_chat  # noqa: E402
from evals.results.g2_keyless_answers_b541e97.ask_readme_questions import env_value  # noqa: E402
from evals.safety.deploy_check import Creds, _with_csrf, login  # noqa: E402

FAKE_MARK = "실제 LLM이 쓴 답이 아닙니다"


def client_for(base: str, creds: Creds) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=180)
    uid, why = login(c, creds)
    assert uid, f"{creds.login_id} 로그인 실패: {why}"
    _with_csrf(c)
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--clone", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    assert not (args.clone / ".env").exists(), "새 clone에 .env가 있다"
    scen = json.loads((args.clone / "data" / "demo_replay" / "scenarios.json").read_text(encoding="utf-8"))
    ex = args.clone / ".env.example"
    user = client_for(args.base_url, Creds("demo-user", env_value(ex, "DEMO_USER_PASSWORD")))
    admin = client_for(args.base_url, Creds("demo-admin", env_value(ex, "DEMO_ADMIN_PASSWORD")))
    out: dict = {}

    # 1. 팀 합동 검토
    t = time.perf_counter()
    ev = post_chat(user, {"input": scen["review"]["question"]}, "scenario-" + uuid.uuid4().hex[:8], 180)
    appr = ev.get("approval") or {}
    # 쟁점표 행은 스트림에 없다(`evals/agent/review_deploy.py` 머리말). 승인 전에 관리자 승인함(`GET /approvals`)에서 읽는다
    table = (fetch_issue_table(admin, appr["approval_id"]) or {}) if appr.get("approval_id") else {}
    rows, unrev = compact_rows(table) if table else ([], [])
    review = {"stream_status": ev.get("status"), "approval_kind": appr.get("kind"), "issue_rows": len(rows), "unreviewed": unrev,
              "teams": sorted({r.get("team") for r in rows if r.get("team")}), "seconds": round(time.perf_counter() - t, 2),
              "error_code": ev.get("error_code"), "rows": rows}
    aid = appr.get("approval_id")
    if aid:
        denied = user.post(f"/approvals/{aid}", json={"approve": True, "comment": "일반 계정 승인 시도"}, headers={"Accept": "application/json"})
        review["user_approve_status"] = denied.status_code
        r = admin.post(f"/approvals/{aid}", json={"approve": True, "comment": "데모 승인"}, headers={"Accept": "application/json"})
        review["admin_approve_status"] = r.status_code
        try:
            body = r.json()
            review["admin_approve_body_keys"] = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
            review["admin_approve_status_field"] = body.get("status") if isinstance(body, dict) else None
        except ValueError:
            review["admin_approve_body_keys"] = "not-json"
        pend = admin.get("/approvals", headers={"Accept": "application/json"})
        review["still_pending_after_approve"] = any(isinstance(v, dict) and v.get("approval_id") == aid for v in (pend.json() if pend.status_code == 200 else []))
    out["review"] = review

    # 2. 리콜
    t = time.perf_counter()
    r = admin.post("/recalls/process-pending", headers={"Accept": "application/json"})
    out["process_pending"] = {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else None,
                              "seconds": round(time.perf_counter() - t, 2)}
    time.sleep(2)

    def notices(c):
        res = c.get("/recalls", headers={"Accept": "application/json"})
        return res.status_code, (res.json() if res.status_code == 200 else {})

    keep = ("notice_id", "article", "change_type", "conclusion_changed", "confidence", "explanation", "review_status", "judge_failed", "new_version_date",
            "old_version_date", "question_excerpt", "question")
    st_u, body_u = notices(user)
    st_a, body_a = notices(admin)
    pick = lambda items: [{k: it.get(k) for k in keep if k in it} for it in items or []]  # noqa: E731
    out["recall"] = {"user_status": st_u, "user_items": pick(body_u.get("items")), "user_unread": body_u.get("unread"),
                     "admin_status": st_a, "admin_items": pick(body_a.get("items")), "admin_review_queue": pick(body_a.get("review_queue")),
                     "admin_judge_failures": body_a.get("judge_failures")}
    # 확신도가 낮은 알림은 관리자 검토함으로 간다. 관리자가 내보내면(release) 사용자에게 보인다
    released = []
    for it in body_a.get("review_queue") or []:
        rr = admin.post(f"/recalls/{it['notice_id']}/review", json={"action": "release"}, headers={"Accept": "application/json"})
        released.append(rr.status_code)
    time.sleep(1)
    st_u2, body_u2 = notices(user)
    out["recall"].update(released=released, user_status_after_release=st_u2, user_items_after_release=pick(body_u2.get("items")),
                         user_unread_after_release=body_u2.get("unread"))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scenarios.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    rc = out["recall"]
    all_items = rc["user_items"] + rc["admin_items"] + rc["admin_review_queue"]
    ok_review = review["approval_kind"] == "issue_table" and review["issue_rows"] > 0 and review.get("admin_approve_status") == 200 \
        and review.get("user_approve_status") == 403 and not review.get("still_pending_after_approve")
    user_seen = rc["user_items"] + rc["user_items_after_release"]
    ok_recall = r.status_code == 200 and any("Sr Director" in str(it.get("explanation") or "") for it in all_items) \
        and any("Sr Director" in str(it.get("explanation") or "") for it in user_seen)
    print(json.dumps({"review_ok": ok_review, "recall_ok": ok_recall, "review_rows": review["issue_rows"], "teams": review["teams"],
                      "process_pending": out["process_pending"]["body"], "user_notices": len(rc["user_items"]),
                      "admin_review_queue": len(rc["admin_review_queue"]), "released": released,
                      "user_notices_after_release": len(rc["user_items_after_release"])}, ensure_ascii=False))
    return 0 if ok_review and ok_recall else 1


if __name__ == "__main__":
    raise SystemExit(main())
