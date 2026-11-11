"""재배포(서버 재시작) 뒤 같은 승인 건 재개 확인 (강사 코멘트 11/10: "배포본에서 재시작 뒤 같은 승인 건을 재개하는 기록을 남기세요").

두 단계로 쓴다. 둘 다 접속 주소와 계정 정보는 환경 변수로만 받는다(출력·저장 안 함).

1) `prepare`(재배포 전, 현재 리비전): 승인 대기 건 3개를 새로 만들고 식별자를 **로컬 상태 파일**에 적는다.
   - a: 합동 검토 쟁점표(`issue_table`). 일반 계정 B가 `POST /chat`으로 합동 검토 요청을 보내 `approval_request`에서 멈춘다. 재시작 뒤 승인할 건.
   - b: 합동 검토 쟁점표. 같은 방법. 재시작 뒤 반려할 건.
   - c: 결정표 초안(`decision_table`). 관리자 A가 `POST /decision-tables/convert`로 만든다. 재시작 뒤 승인할 건.
   쟁점표 건은 한 번 되물음으로 끝나면(값이 빠졌다고 판단) 금액을 바꿔 새 대화로 다시 보낸다(최대 5번). 팀 실패 알림(`team_review_failed`)에서 멈추면
   `mark_unreviewed`로 넘겨 이어지는 쟁점표 건을 쓴다.
   결정표 건의 업무 종류는 금액 질문에 쓰이는 종류(Approving expense 등)를 피해 `Benefit changes`부터 승인된 표가 없는 것을 쓴다(`DEPLOY_RESTART_CATEGORY`로 지정 가능).
   **결정표 건은 재시작 뒤 승인하므로 운영에 승인된 표가 하나 남는다**(지울 API 없음).

2) `resume`(재배포 뒤, 새 리비전): 상태 파일의 3건을 승인·반려·승인하고, 그래프가 체크포인트에서 이어져 결과(쟁점표 저장, 반려 처리, 결정표 저장)가 나왔는지와
   중복 재개가 없는지를 본다. 결과는 식별자를 뺀 증거 JSON으로 남긴다(리비전 전·후, 시각 UTC, 건 종류, 결정, 응답 코드, 저장된 행 수만).

| 번호 | 확인 | 기대 |
|---|---|---|
| R1 | 재시작 뒤에도 대기 건이 승인함 목록에 있다 | 3건 모두 있음 |
| R2 | 체크포인트에서 내용이 복원된다(쟁점표 행 수, 초안 행 수) | 준비 때와 같은 행 수 |
| R3 | 대기 중인 대화에 새 질문을 보내면(쟁점표 건, LLM 호출 전에 막힘) | 409 approval_pending |
| R4 | 일반 계정(B)이 결정을 보냄 | 403 |
| R5 | 관리자가 결정(승인 또는 반려) | 200, 상태 approved 또는 rejected, 승인이면 table_id 있음 |
| R6 | 결과 확인: 쟁점표는 대화 답에 저장·반려 문구와 행 수, 결정표는 승인된 표 목록 | 저장되면 행 수 > 0, 반려면 저장 0 |
| R7 | 같은 결정 재요청은 200(같은 상태), 반대 결정은 409 | 그래프를 다시 재개하지 않음 |
| R8 | 재요청 뒤 결과가 바뀌거나 늘지 않음(대화 답 글·개수, 같은 업무 종류의 승인된 표 수) | 그대로 |
| R9 | 결정 뒤 승인함 대기 목록에서 빠짐 | 빠짐 |

식별자(승인 번호, 대화 번호, 사용자 id, 아이디)는 상태 파일에만 있다. 상태 파일은 저장소에 올리지 않는 로컬 전용이다.
"재시작"은 이 도구가 하지 않는다. 사용자가 운영 서비스를 재배포한 뒤 `resume`을 돌린다(새 리비전 이름이 준비 때와 같으면 멈춘다).

    환경 변수: DEPLOY_CHECK_BASE_URL, DEPLOY_CHECK_A_LOGIN, DEPLOY_CHECK_A_PASSWORD, DEPLOY_CHECK_B_LOGIN, DEPLOY_CHECK_B_PASSWORD
    선택: DEPLOY_RESTART_CATEGORY
    python -m evals.safety.deploy_restart_resume_check prepare --revision <현재 리비전> --state <상태 파일>
    python -m evals.safety.deploy_restart_resume_check resume --revision <새 리비전> --commit <커밋> --state <상태 파일> --out evals/results/d7_restart_<리비전>/restart_resume.json

종료 코드: 0 모두 통과(준비는 3건 생성), 1 일부 실패(준비는 3건 미만), 2 환경 변수·상태 파일 문제, 3 접속·로그인 실패.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.latency.deploy_latency import iter_sse
from evals.safety.deploy_check import ENV_REQUIRED, JSON_ACCEPT, Creds, _code
from evals.safety.deploy_mix_check import make_session

KIND_DECISION = "decision_table"
KIND_ISSUE = "issue_table"
KIND_TEAM_FAILED = "team_review_failed"
CATEGORY_CANDIDATES = ("Benefit changes", "Transfer of funds among GitLab entities", "Compensation/Hiring - non-executive")   # 금액 질문에 쓰이는 종류는 넣지 않는다
MAX_CONVERT_TRIES = 3
AMOUNTS = ("3만 달러", "5만 달러", "10만 달러", "1만 달러", "30만 달러")
MAX_JOINT_ATTEMPTS = len(AMOUNTS)
QUESTION = ("합동 검토 요청: 새 외부 SaaS 모니터링 도구를 연 {amount}에 1년 계약으로 도입하려 한다. "
            "벤더는 외부 상용 업체이고, 서비스 로그와 메트릭만 외부로 보내며 고객 개인정보는 포함하지 않는다.")
NEW_QUESTION_WHILE_PENDING = "재시작 뒤 확인용: 이 대화에 새 질문을 보냅니다."
COMMENT = "restart-resume check"
SAVED_TEXT = "승인되어 쟁점표를 저장했습니다"
REJECTED_TEXT = "반려되어 쟁점표를 저장하지 않았습니다"
ROWS_RE = re.compile(r"쟁점\s*(\d+)\s*건")
PLAN = (("a", KIND_ISSUE, "approve"), ("b", KIND_ISSUE, "reject"), ("c", KIND_DECISION, "approve"))
LOCAL_NOTE = "로컬 전용 파일: 승인 번호와 대화 번호가 들어 있다. 저장소에 올리지 않는다(저장소 밖에 둔다). 증거는 resume이 식별자를 뺀 JSON으로 따로 쓴다."


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(s: str) -> str:
    return " ".join(str(s).split()).casefold()


def _json(r) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def get_pending(a) -> tuple[int, dict[str, dict]]:
    r = a.get("/approvals", headers=JSON_ACCEPT)
    body = _json(r) if r.status_code == 200 else None
    return r.status_code, {v["approval_id"]: v for v in body} if isinstance(body, list) else {}


def get_tables(a) -> tuple[int, list[dict]]:
    r = a.get("/decision-tables", headers=JSON_ACCEPT)
    body = _json(r) if r.status_code == 200 else None
    return r.status_code, body if isinstance(body, list) else []


def decide(client, approval_id: str, approve: bool):
    return client.post(f"/approvals/{approval_id}", json={"approve": approve, "comment": COMMENT}, headers=JSON_ACCEPT)


def chat_until_pause(client, thread_id: str, message: str) -> dict[str, Any]:
    """`/chat` SSE를 끝까지 읽어 승인 대기(approval_request)·되물음 등 결과를 돌려준다."""
    out: dict[str, Any] = {"http": None, "event": None, "approval_id": None, "approval_kind": None, "done_kind": None, "error_code": None, "cost_usd": None}
    try:
        with client.stream("POST", "/chat", json={"thread_id": thread_id, "message": message}, headers={"Accept": "text/event-stream"}) as resp:
            out["http"] = resp.status_code
            if resp.status_code != 200:
                resp.read()
                out["error_code"] = _code(resp) or str(resp.status_code)
                return out
            for name, raw in iter_sse(resp.iter_lines()):
                try:
                    payload = json.loads(raw)
                except ValueError:
                    continue
                etype = name if name != "message" else (payload.get("type") or name)
                data = payload.get("data") or {}
                if etype == "approval_request":
                    out.update(event="approval_request", approval_id=data.get("approval_id"), approval_kind=data.get("kind"))
                elif etype == "done":
                    cost = (data.get("usage") or {}).get("cost_usd")
                    out.update(event="done", done_kind=data.get("kind"), cost_usd=float(cost) if isinstance(cost, (int, float)) else None)
                elif etype == "error":
                    out.update(event="error", error_code=str(data.get("code") or "unknown"))
    except Exception as exc:  # noqa: BLE001 - 네트워크 오류는 종류만 남긴다
        out.update(event="error", error_code=type(exc).__name__)
    return out


def thread_view(client, thread_id: str) -> tuple[int, str, int]:
    """(응답 코드, 마지막 답 글, 답 개수)."""
    r = client.get(f"/threads/{thread_id}", headers=JSON_ACCEPT)
    body = _json(r) if r.status_code == 200 else None
    msgs = [m for m in ((body or {}).get("messages") or []) if isinstance(m, dict) and m.get("role") == "assistant"]
    return r.status_code, (msgs[-1].get("text") or "") if msgs else "", len(msgs)


# ---------------------------------------------------------------- prepare


def _pending_row_count(view: dict) -> int:
    if view.get("kind") == KIND_DECISION:
        return len(view.get("draft") or [])
    return len((view.get("issue_table") or {}).get("rows") or [])


def _resolve_team_failure(a, approval_id: str, pending0: dict) -> tuple[str | None, str | None]:
    """팀 실패 알림에서 멈췄을 때 `mark_unreviewed`로 넘겨 이어지는 쟁점표 건을 얻는다."""
    r = a.post(f"/approvals/{approval_id}", json={"action": "mark_unreviewed", "comment": COMMENT}, headers=JSON_ACCEPT)
    body = _json(r) if r.status_code == 200 else None
    nxt = (body or {}).get("next_approval") or {}
    if nxt.get("kind") == KIND_ISSUE and nxt.get("approval_id") and nxt["approval_id"] not in pending0:
        return nxt["approval_id"], KIND_ISSUE
    return None, None


def prepare(a, b, *, revision: str, base_url: str, categories: list[str] | None = None, amounts: tuple[str, ...] = AMOUNTS,
            clock=now_utc) -> tuple[dict[str, Any], int]:
    code_p, pending0 = get_pending(a)
    code_t, tables0 = get_tables(a)
    state: dict[str, Any] = {"_note": LOCAL_NOTE, "revision_before": revision, "created_at_utc": clock(), "base_url": base_url, "complete": False,
                             "baseline": {"pending": len(pending0), "approved_tables": len(tables0)}, "items": [], "attempts": [], "problems": []}
    if code_p != 200 or code_t != 200:
        state["problems"].append(f"시작 상태를 읽지 못함: GET /approvals {code_p}, GET /decision-tables {code_t}(A가 관리자가 아닐 수 있다)")
        return state, 1
    plan = list(PLAN)
    joint_plan = [p for p in plan if p[1] == KIND_ISSUE]

    # a, b: 합동 검토 쟁점표
    for amount in amounts[:MAX_JOINT_ATTEMPTS]:
        if not joint_plan:
            break
        thread_id = "dc-rs-" + uuid.uuid4().hex[:10]
        r = chat_until_pause(b, thread_id, QUESTION.format(amount=amount))
        result = r["approval_kind"] if r["event"] == "approval_request" else (r["done_kind"] or r["error_code"] or "unknown")
        attempt = {"kind": "chat", "amount": amount, "http": r["http"], "result": result, "cost_usd": r["cost_usd"]}
        state["attempts"].append(attempt)
        if r["event"] != "approval_request" or not r["approval_id"]:
            continue
        approval_id, kind = r["approval_id"], r["approval_kind"]
        if kind == KIND_TEAM_FAILED:
            approval_id, kind = _resolve_team_failure(a, approval_id, pending0)
            attempt["resolved_team_failure"] = bool(approval_id)
        if not approval_id or kind != KIND_ISSUE or approval_id in pending0:
            continue
        _, now_pending = get_pending(a)
        view = now_pending.get(approval_id)
        rows = _pending_row_count(view) if view else 0
        if not view or view.get("kind") != KIND_ISSUE or rows <= 0:
            state["problems"].append("쟁점표 건이 승인함 목록에 없거나 쟁점 행이 0이다")
            continue
        label, _, decision = joint_plan.pop(0)
        state["items"].append({"label": label, "kind": KIND_ISSUE, "decision": decision, "approval_id": approval_id, "thread_id": thread_id,
                               "asker": "B", "pending_rows": rows, "category": None, "created_at_utc": clock()})

    # c: 결정표 초안
    cats = categories if categories is not None else ([os.environ["DEPLOY_RESTART_CATEGORY"].strip()] if os.environ.get("DEPLOY_RESTART_CATEGORY", "").strip() else list(CATEGORY_CANDIDATES))
    approved_cats = {norm(t.get("category", "")) for t in tables0}
    tries = 0
    for cat in cats:
        if norm(cat) in approved_cats:
            continue
        if tries >= MAX_CONVERT_TRIES:
            break
        tries += 1
        r = a.post("/decision-tables/convert", json={"category": cat}, headers=JSON_ACCEPT)
        state["attempts"].append({"kind": "convert", "category": cat, "http": r.status_code})
        if r.status_code != 201:
            if r.status_code != 409:
                break
            continue
        view = _json(r) or {}
        approval_id = view.get("approval_id")
        if not approval_id or approval_id in pending0:
            state["problems"].append("결정표 건 번호가 이미 있던 대기 건과 같아 쓰지 않음")
            break
        state["items"].append({"label": "c", "kind": KIND_DECISION, "decision": "approve", "approval_id": approval_id, "thread_id": None, "asker": "A",
                               "pending_rows": _pending_row_count({**view, "kind": KIND_DECISION}), "category": cat, "created_at_utc": clock()})
        break

    state["items"].sort(key=lambda i: i["label"])
    state["complete"] = [i["label"] for i in state["items"]] == ["a", "b", "c"]
    return state, 0 if state["complete"] else 1


# ---------------------------------------------------------------- resume


def check_item(a, b, it: dict, view: dict | None, tables_before: list[dict]) -> dict[str, Any]:
    """한 건의 R1~R9. 식별자는 결과에 넣지 않는다."""
    kind, approve = it["kind"], it["decision"] == "approve"
    want_status = "approved" if approve else "rejected"
    out: dict[str, Any] = {"label": it["label"], "kind": kind, "decision": it["decision"], "pending_rows_before_restart": it["pending_rows"]}
    checks: dict[str, bool] = {}
    aid = it["approval_id"]

    checks["R1"] = view is not None
    out["found_pending_after_restart"] = checks["R1"]
    restored = _pending_row_count(view) if view else 0
    out["restored_rows"] = restored
    checks["R2"] = bool(view) and restored == it["pending_rows"] and restored > 0 and not view.get("save_failed")

    if kind == KIND_ISSUE:
        try:
            with b.stream("POST", "/chat", json={"thread_id": it["thread_id"], "message": NEW_QUESTION_WHILE_PENDING}, headers={"Accept": "text/event-stream"}) as resp:
                code = resp.status_code
                if code != 200:
                    resp.read()
                    err = _code(resp)
                else:
                    err = ""
        except Exception as exc:  # noqa: BLE001
            code, err = 0, type(exc).__name__
        out["new_question_while_pending_http"] = code
        checks["R3"] = code == 409 and err == "approval_pending"

    r = decide(b, aid, approve)
    out["non_admin_decide_http"] = r.status_code
    checks["R4"] = r.status_code == 403

    tables_n_before = len([t for t in tables_before if norm(t.get("category", "")) == norm(it["category"] or "")]) if kind == KIND_DECISION else None
    r = decide(a, aid, approve)
    body = _json(r) if r.status_code == 200 else None
    body = body if isinstance(body, dict) else {}
    table_id = body.get("table_id")
    out.update(decide_http=r.status_code, decision_status=body.get("status"), saved_table_returned=bool(table_id))
    checks["R5"] = r.status_code == 200 and body.get("status") == want_status and (bool(table_id) if approve else not table_id)

    saved_rows, first = None, None
    if kind == KIND_ISSUE:
        tcode, text, n_msgs_1 = thread_view(b, it["thread_id"])
        first = (text, n_msgs_1)
        m = ROWS_RE.search(text)
        if approve:
            saved_rows = int(m.group(1)) if m and SAVED_TEXT in text else None
            checks["R6"] = tcode == 200 and saved_rows is not None and saved_rows > 0 and saved_rows == it["pending_rows"]
        else:
            saved_rows = 0 if REJECTED_TEXT in text else None
            checks["R6"] = tcode == 200 and saved_rows == 0
        out["thread_http"] = tcode
    else:
        tcode, tables = get_tables(a)
        mine = [t for t in tables if t.get("table_id") == table_id] if table_id else []
        saved_rows = len(mine[0].get("cells") or []) if mine else None
        out["tables_http"] = tcode
        out["saved_rows_equals_draft_rows"] = saved_rows == it["pending_rows"] if saved_rows is not None else None
        checks["R6"] = tcode == 200 and bool(mine) and mine[0].get("status") == "approved" and saved_rows > 0
    out["saved_rows"] = saved_rows

    same = decide(a, aid, approve)
    sbody = _json(same) if same.status_code == 200 else None
    flip = decide(a, aid, not approve)
    out.update(repeat_same_http=same.status_code, repeat_same_status=(sbody or {}).get("status") if isinstance(sbody, dict) else None, repeat_flip_http=flip.status_code)
    checks["R7"] = same.status_code == 200 and isinstance(sbody, dict) and sbody.get("status") == want_status and flip.status_code == 409

    if kind == KIND_ISSUE:
        _, text2, n_msgs_2 = thread_view(b, it["thread_id"])
        out["answers_before_after_repeat"] = [first[1], n_msgs_2]
        checks["R8"] = first is not None and first == (text2, n_msgs_2)   # 답 글과 개수가 그대로
    else:
        _, tables_after = get_tables(a)
        n_after = len([t for t in tables_after if norm(t.get("category", "")) == norm(it["category"] or "")])
        out["approved_tables_of_category_before_after"] = [tables_n_before, n_after]
        checks["R8"] = tables_n_before is not None and n_after == tables_n_before + 1

    _, pending_after = get_pending(a)
    checks["R9"] = aid not in pending_after
    out["checks"] = checks
    out["passed"] = all(checks.values())
    return out


def resume(a, b, state: dict, *, revision_after: str, commit: str, out_path: str | None = None, clock=now_utc) -> tuple[dict[str, Any], int]:
    started = clock()
    t0 = time.perf_counter()
    code_p, pending = get_pending(a)
    code_t, tables0 = get_tables(a)
    items_out: list[dict[str, Any]] = []
    problems: list[str] = []
    if code_p != 200 or code_t != 200:
        problems.append(f"시작 상태를 읽지 못함: GET /approvals {code_p}, GET /decision-tables {code_t}")
    else:
        for label in ("a", "b", "c"):
            it = next((i for i in state.get("items", []) if i["label"] == label), None)
            if it is None:
                problems.append(f"{label} 건이 상태 파일에 없음(준비 단계에서 만들지 못함)")
                continue
            try:
                items_out.append(check_item(a, b, it, pending.get(it["approval_id"]), tables0))
            except Exception as exc:  # noqa: BLE001 - 한 건이 깨져도 다음 건을 계속한다
                problems.append(f"{label} 건 확인 중 오류 {type(exc).__name__}")
                items_out.append({"label": label, "kind": it["kind"], "decision": it["decision"], "error": type(exc).__name__, "passed": False})
    passed_items = sum(1 for i in items_out if i.get("passed"))
    evidence = {
        "purpose": "서버 재시작(재배포) 뒤 같은 승인 건 재개 확인(강사 코멘트 2026-11-10). 식별자(승인 번호, 대화 번호, 사용자 id, 아이디)는 넣지 않는다.",
        "revision_before_restart": state.get("revision_before"), "revision_after_restart": revision_after, "commit_after_restart": commit,
        "pending_created_at_utc": state.get("created_at_utc"), "resume_started_at_utc": started, "resume_finished_at_utc": clock(),
        "elapsed_s": round(time.perf_counter() - t0, 1), "base_url": state.get("base_url"),
        "not_observable": "그래프 재개 횟수와 서버 로그는 API로 볼 수 없다. 응답 코드, 승인함 목록, 대화 답, 승인된 표 목록으로만 판정한다.",
        "state_complete": bool(state.get("complete")), "problems": problems, "items": items_out,
        "summary": {"items_expected": 3, "items_passed": passed_items, "all_passed": passed_items == 3 and not problems},
    }
    if out_path:
        evidence_path = write_unique(out_path, json.dumps(evidence, ensure_ascii=False, indent=2))
        evidence["_written_to"] = str(evidence_path)   # 파일 안에는 없고 반환값에만 있다
    return evidence, 0 if evidence["summary"]["all_passed"] else 1


def write_unique(path: str, text: str) -> Path:
    """결과 파일을 덮어쓰지 않는다. 같은 이름이 있으면 `_2`, `_3` ... 접미사를 붙인 새 파일에 쓴다(배타적 생성이라 동시 실행에도 안전)."""
    base = Path(path).absolute()
    base.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        target = base if n == 1 else base.with_name(f"{base.stem}_{n}{base.suffix}")
        try:
            with open(target, "x", encoding="utf-8") as fh:
                fh.write(text)
            return target
        except FileExistsError:
            n += 1


def render(evidence: dict) -> str:
    lines = ["| 건 | 종류 | 결정 | 결과 | 실패한 확인 |", "|---|---|---|---|---|"]
    for i in evidence["items"]:
        failed = ", ".join(k for k, v in (i.get("checks") or {}).items() if not v) or i.get("error", "")
        lines.append(f"| {i['label']} | {i['kind']} | {i['decision']} | {'통과' if i.get('passed') else '실패'} | {failed or '-'} |")
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="재시작 뒤 같은 승인 건 재개 확인(환경 변수로만 설정)")
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare", help="재배포 전: 승인 대기 건 3개를 만들고 상태 파일에 적는다")
    p.add_argument("--revision", required=True)
    p.add_argument("--state", required=True, help="로컬 전용 상태 파일 경로(식별자가 들어간다)")
    p.add_argument("--overwrite", action="store_true", help="상태 파일이 이미 있어도 덮어쓴다(이전 건의 식별자를 잃는다)")
    r = sub.add_parser("resume", help="재배포 뒤: 상태 파일의 3건을 승인·반려·승인하고 재개를 확인한다")
    r.add_argument("--revision", required=True)
    r.add_argument("--commit", required=True)
    r.add_argument("--state", required=True)
    r.add_argument("--out", required=True, help="식별자를 뺀 증거 JSON 경로(이미 있으면 _2, _3 접미사로 새로 쓴다. 덮어쓰지 않는다)")
    r.add_argument("--allow-same-revision", action="store_true", help="준비 때와 같은 리비전 이름이어도 진행(재시작 증거가 되지 않는다)")
    args = ap.parse_args(argv)
    missing = [n for n in ENV_REQUIRED if not os.environ.get(n)]
    if missing:
        print("환경 변수가 없다: " + ", ".join(missing), file=sys.stderr)
        return 2
    state_path = Path(args.state)
    if args.mode == "prepare":
        if state_path.exists() and not args.overwrite:
            print("상태 파일이 이미 있다. 이전 건의 식별자를 잃지 않게 멈춘다(--overwrite로 덮어쓴다).", file=sys.stderr)
            return 2
    else:
        if not state_path.exists():
            print("상태 파일이 없다. 먼저 prepare를 돌린다.", file=sys.stderr)
            return 2
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("revision_before") == args.revision and not args.allow_same_revision:
            print("새 리비전 이름이 준비 때와 같다. 재배포가 끝난 뒤 새 리비전 이름으로 돌린다.", file=sys.stderr)
            return 2
    import httpx

    base = os.environ["DEPLOY_CHECK_BASE_URL"].rstrip("/")
    try:
        health = httpx.get(base + "/health", timeout=60.0)
        print(f"/health {health.status_code}")
    except httpx.HTTPError as exc:
        print(f"/health 실패: {type(exc).__name__}", file=sys.stderr)
        return 3
    try:
        a, _ = make_session(base, Creds(os.environ["DEPLOY_CHECK_A_LOGIN"], os.environ["DEPLOY_CHECK_A_PASSWORD"]))
        b, _ = make_session(base, Creds(os.environ["DEPLOY_CHECK_B_LOGIN"], os.environ["DEPLOY_CHECK_B_PASSWORD"]))
    except RuntimeError as exc:
        print(f"로그인 실패: {exc}", file=sys.stderr)
        return 3
    try:
        if args.mode == "prepare":
            state, code = prepare(a, b, revision=args.revision, base_url=base)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")   # 식별자 포함: 로컬 전용
            made = [f"{i['label']}({i['kind']}, {i['decision']} 예정, 행 {i['pending_rows']})" for i in state["items"]]
            print("만든 대기 건: " + (", ".join(made) or "없음"))
            for at in state["attempts"]:
                print("  시도: " + json.dumps(at, ensure_ascii=False))
            for pr in state["problems"]:
                print("  문제: " + pr)
            print(f"상태 파일 저장(로컬 전용): {state_path.name}, 3건 {'완성' if state['complete'] else '미완성'}")
            return code
        evidence, code = resume(a, b, state, revision_after=args.revision, commit=args.commit, out_path=args.out)
        print(render(evidence))
        for pr in evidence["problems"]:
            print("문제: " + pr)
        print(f"{evidence['summary']['items_passed']}/3 통과, 증거 파일: {evidence.get('_written_to', args.out)}")
        return code
    finally:
        a.close()
        b.close()


if __name__ == "__main__":
    sys.exit(main())
