"""배포 서비스 승인 동시 처리 시험 (EVAL_REPORT 6장 21행).

관리자 계정(A)으로 시험용 결정표 초안 승인 대기 건을 새로 하나 만들고(`POST /decision-tables/convert`, LLM 초안 1번), 그 건 하나에만 다음을 보낸다.
이미 있던 승인 대기 건과 승인된 결정표는 건드리지 않는다(시작과 끝에 목록을 대조해 변화가 없는지 본다). 시험 건은 반려로 끝낸다.

| 번호 | 시험 | 기대 |
|---|---|---|
| D1 | 일반 계정(B)이 결정(반려)을 보냄(건이 대기 중일 때) | 403, 건은 그대로 대기 |
| D2 | 관리자 두 요청이 같은 건에 반려를 동시에(서로 다른 comment) | 둘 다 200, 상태 rejected, 두 응답의 comment가 같음(먼저 처리된 것 하나만 저장) |
| D3 | 같은 건에 반려를 연속으로 한 번 더(또 다른 comment) | 200, 저장된 comment 그대로(새 comment로 바뀌지 않음) |
| D4 | 승인으로 번복 | 409 |
| D5 | 일반 계정(B)이 끝난 건에 결정 | 403 |
| D6 | 마지막 상태 | 시험 건은 대기 목록에서 빠짐, 이미 있던 대기 건은 모두 그대로, 승인된 결정표 목록은 시작과 같음 |

#90 이후 기대인 "그래프 재개 1번, 결과 행 1개"는 API로 볼 수 없다(서버 로그·DB 필요). 응답 코드와 최종 상태로만 판정하고 결과 JSON의 `not_observable`에 적는다.

시험 건의 업무 종류는 `data/parsed/authz_cells.jsonl`의 업무 종류 가운데 승인된 표가 없는 것을 차례로 시도한다(409면 다음). `DEPLOY_APPROVAL_CATEGORY`로 직접 줄 수 있다.
시험 중 오류로 중단되어도 시험 건이 대기로 남지 않게 반려로 정리한다. 접속 주소와 계정 정보는 환경 변수로만 받는다(출력·저장 안 함).

    환경 변수: DEPLOY_CHECK_BASE_URL, DEPLOY_CHECK_A_LOGIN, DEPLOY_CHECK_A_PASSWORD, DEPLOY_CHECK_B_LOGIN, DEPLOY_CHECK_B_PASSWORD
    선택: DEPLOY_APPROVAL_CATEGORY
    python -m evals.safety.deploy_approval_check --out evals/results/d7_deploy_<리비전>/approval_check.json [--revision 리비전] [--commit 커밋]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.safety.deploy_check import ENV_REQUIRED, JSON_ACCEPT, Creds, _code, _with_csrf, login

REPO = Path(__file__).resolve().parents[2]
CELLS = REPO / "data" / "parsed" / "authz_cells.jsonl"
MAX_CATEGORY_TRIES = 4


@dataclass
class Case:
    id: str
    desc: str
    expect: str
    actual: str
    passed: bool
    extra: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def make_session(base: str, creds: Creds):
    import httpx

    client = httpx.Client(base_url=base, timeout=httpx.Timeout(30.0, read=240.0))
    uid, why = login(client, creds)
    if not uid:
        raise RuntimeError(why)
    _with_csrf(client)
    return client, uid


def categories() -> list[str]:
    forced = os.environ.get("DEPLOY_APPROVAL_CATEGORY", "").strip()
    if forced:
        return [forced]
    seen: list[str] = []
    for line in CELLS.read_text(encoding="utf-8").splitlines():
        c = json.loads(line).get("category")
        if c and c not in seen:
            seen.append(c)
    return seen


def norm(s: str) -> str:
    return " ".join(str(s).split()).casefold()


def approved_snapshot(client) -> tuple[int, list[tuple[str, str, str]]]:
    r = client.get("/decision-tables")
    if r.status_code != 200:
        return r.status_code, []
    return 200, sorted((t["table_id"], t.get("category", ""), t.get("status", "")) for t in r.json())


def pending_ids(client) -> tuple[int, list[str]]:
    r = client.get("/approvals", headers=JSON_ACCEPT)
    if r.status_code != 200:
        return r.status_code, []
    return 200, sorted(v["approval_id"] for v in r.json())


def decide(client, approval_id: str, approve: bool, comment: str):
    return client.post(f"/approvals/{approval_id}", json={"approve": approve, "comment": comment}, headers=JSON_ACCEPT)


def brief(r) -> str:
    try:
        body = r.json()
    except ValueError:
        body = {}
    status = body.get("status") if isinstance(body, dict) else None
    return f"{r.status_code}" + (f"/{status}" if status else "") + (f"/{_code(r)}" if r.status_code >= 400 and _code(r) else "")


def run(base: str, a_creds: Creds, b_creds: Creds) -> tuple[list[Case], dict[str, Any]]:
    meta: dict[str, Any] = {"cost_note": "초안 LLM 호출 1번(convert)", "cleanup": "필요 없음",
                            "not_observable": "그래프 재개 횟수와 결과 행 수는 API로 볼 수 없다(서버 로그·DB 필요). 응답 코드와 최종 상태로만 판정"}
    cases: list[Case] = []
    a, a_id = make_session(base, a_creds)
    a2, _ = make_session(base, a_creds)   # 동시 요청용 두 번째 관리자 세션
    b, b_id = make_session(base, b_creds)
    approval_id: str | None = None
    finished = False
    try:
        if a_id == b_id:
            return [Case("L0", "A와 B가 서로 다른 계정이다", "user_id가 다름", "A와 B가 같은 계정이다", False)], meta
        code_t, tables0 = approved_snapshot(a)
        code_p, pending0 = pending_ids(a)
        if code_t != 200 or code_p != 200:
            return [Case("S0", "시작 상태를 읽는다(승인된 표 목록, 승인 대기 목록)", "둘 다 200", f"GET /decision-tables {code_t}, GET /approvals {code_p}(관리자 계정이 아닐 수 있다)", False)], meta
        meta["before"] = {"approved_tables": len(tables0), "pending_approvals": len(pending0)}
        approved_cats = {norm(c) for _, c, _ in tables0}

        # 준비: 시험 건 만들기
        tried: list[str] = []
        created = None
        for cat in categories():
            if norm(cat) in approved_cats:
                continue
            if len(tried) >= MAX_CATEGORY_TRIES:
                break
            r = a.post("/decision-tables/convert", json={"category": cat}, headers=JSON_ACCEPT)
            tried.append(f"{cat}: {r.status_code}")
            if r.status_code == 201:
                created = r.json()
                meta["category"] = cat
                break
            if r.status_code != 409:
                break
        meta["convert_tries"] = tried
        if not created:
            cases.append(Case("S1", "준비: 시험용 승인 대기 건 만들기", "201", "만들지 못함: " + "; ".join(tried), False))
            return cases, meta
        approval_id = created["approval_id"]
        if approval_id in pending0:
            approval_id = None   # 이미 있던 건이면 절대 건드리지 않는다
            cases.append(Case("S1", "준비: 시험용 승인 대기 건 만들기", "새 건", "이미 있던 대기 건과 같은 id라 중단", False))
            return cases, meta
        meta["approval_id_prefix"] = approval_id[:8]
        _, now_pending = pending_ids(a)
        cases.append(Case("S1", "준비: 시험용 승인 대기 건 만들기(결정표 초안)", "201, 대기 목록에 새 건 있음", f"201, 대기 목록에 {'있음' if approval_id in now_pending else '없음'}",
                          approval_id in now_pending))
        if approval_id not in now_pending:
            return cases, meta
        tag = uuid.uuid4().hex[:6]

        # D1: 일반 계정 결정(대기 중)
        r = decide(b, approval_id, False, f"dc-user-{tag}")
        _, p = pending_ids(a)
        bad = []
        if r.status_code != 403:
            bad.append(f"응답 {brief(r)}")
        if approval_id not in p:
            bad.append("건이 대기에서 사라짐")
        cases.append(Case("D1", "일반 계정(B)이 대기 중인 건에 결정(반려)", "403, 건은 그대로 대기", "; ".join(bad) or "403, 건은 그대로 대기", not bad))

        # D2: 관리자 동시 반려 2번
        res: dict[str, Any] = {}
        barrier = threading.Barrier(2)

        def worker(name: str, client, comment: str) -> None:
            barrier.wait()
            try:
                res[name] = decide(client, approval_id, False, comment)
            except Exception as exc:  # noqa: BLE001
                res[name] = exc

        c1, c2, c3 = f"dc-first-{tag}", f"dc-second-{tag}", f"dc-third-{tag}"
        ths = [threading.Thread(target=worker, args=("x", a, c1)), threading.Thread(target=worker, args=("y", a2, c2))]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        bad, comments, summary = [], [], []
        for k in ("x", "y"):
            r = res.get(k)
            if isinstance(r, Exception) or r is None:
                bad.append(f"요청 {k} 오류 {type(r).__name__}")
                continue
            summary.append(brief(r))
            body = r.json() if r.status_code == 200 else {}
            if r.status_code != 200:
                bad.append(f"요청 {k} 응답 {brief(r)}")
            elif body.get("status") != "rejected":
                bad.append(f"요청 {k} 상태 {body.get('status')}")
            comments.append(body.get("comment"))
        if len(comments) == 2 and comments[0] != comments[1]:
            bad.append("두 응답의 comment가 다름(둘 다 저장된 듯)")
        stored = comments[0] if comments else None
        if comments and stored not in (c1, c2):
            bad.append("저장된 comment가 보낸 값이 아님")
        cases.append(Case("D2", "관리자 두 요청이 같은 건에 반려를 동시에(comment 서로 다름)", "둘 다 200/rejected, 두 응답의 comment 같음",
                          "; ".join(bad) or f"응답 {' + '.join(summary)}, comment 같음(먼저 처리된 {'첫째' if stored == c1 else '둘째'} 요청 것)", not bad))

        # D3: 연속 한 번 더
        r = decide(a, approval_id, False, c3)
        body = r.json() if r.status_code == 200 else {}
        bad = []
        if r.status_code != 200 or body.get("status") != "rejected":
            bad.append(f"응답 {brief(r)}")
        elif body.get("comment") != stored:
            bad.append("저장된 comment가 새 값으로 바뀜")
        cases.append(Case("D3", "같은 건에 반려를 연속으로 한 번 더", "200/rejected, 저장된 comment 그대로", "; ".join(bad) or f"{brief(r)}, 저장된 comment 그대로", not bad))

        # D4: 번복
        r = decide(a, approval_id, True, f"dc-flip-{tag}")
        cases.append(Case("D4", "승인으로 번복", "409", f"{brief(r)}", r.status_code == 409))

        # D5: 일반 계정, 끝난 건
        r = decide(b, approval_id, False, f"dc-user2-{tag}")
        cases.append(Case("D5", "일반 계정(B)이 끝난 건에 결정", "403", f"{brief(r)}", r.status_code == 403))
        finished = True

        # D6: 마지막 상태
        code_t, tables1 = approved_snapshot(a)
        code_p, pending1 = pending_ids(a)
        bad = []
        if code_t != 200 or code_p != 200:
            bad.append(f"목록 조회 {code_t}/{code_p}")
        else:
            if approval_id in pending1:
                bad.append("시험 건이 아직 대기 중")
            lost = [i for i in pending0 if i not in pending1]
            if lost:
                bad.append(f"이미 있던 대기 건 {len(lost)}개가 사라짐")
            extra = [i for i in pending1 if i not in pending0]
            if extra:
                bad.append(f"새 대기 건 {len(extra)}개가 생김")
            if tables1 != tables0:
                bad.append(f"승인된 결정표가 바뀜({len(tables0)}개 -> {len(tables1)}개)")
        meta["after"] = {"approved_tables": len(tables1), "pending_approvals": len(pending1)}
        cases.append(Case("D6", "마지막 상태(대기 목록과 승인된 결정표)", "시험 건은 대기에서 빠지고 나머지는 시작과 같음",
                          "; ".join(bad) or f"시험 건 대기에서 빠짐, 대기 건 {len(pending0)}개 그대로, 승인된 결정표 {len(tables0)}->{len(tables1)}", not bad))
    finally:
        if approval_id and not finished:   # 중간에 멈췄으면 시험 건을 반려로 정리
            try:
                r = decide(a, approval_id, False, "dc-cleanup")
                meta["cleanup"] = f"중단되어 반려로 정리({r.status_code})"
            except Exception as exc:  # noqa: BLE001
                meta["cleanup"] = f"정리 실패({type(exc).__name__}): 승인함에서 시험 건 {approval_id[:8]}...을 직접 반려해야 함"
        for c in (a, a2, b):
            c.close()
    return cases, meta


def render(cases: list[Case]) -> str:
    lines = ["| 번호 | 시험 | 결과 | 근거 |", "|---|---|---|---|"]
    lines += [f"| {c.id} | {c.desc} | {'통과' if c.passed else '실패'} | {c.actual} |" for c in cases]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="배포 서비스 승인 동시 처리 시험(EVAL_REPORT 6장 21행, 환경 변수로만 설정)")
    ap.add_argument("--out", default="", help="결과 JSON을 쓸 경로")
    ap.add_argument("--revision", default="", help="배포 리비전 이름(결과에 적는다)")
    ap.add_argument("--commit", default="", help="배포 커밋(결과에 적는다)")
    args = ap.parse_args(argv)
    missing = [n for n in ENV_REQUIRED if not os.environ.get(n)]
    if missing:
        print("환경 변수가 없다: " + ", ".join(missing), file=sys.stderr)
        return 2
    import httpx

    base = os.environ["DEPLOY_CHECK_BASE_URL"].rstrip("/")
    started = now_iso()
    t0 = time.perf_counter()
    try:
        health = httpx.get(base + "/health", timeout=60.0)
        health_info = {"code": health.status_code, "body": health.text[:200]}
    except httpx.HTTPError as exc:
        print(f"/health 실패: {type(exc).__name__}", file=sys.stderr)
        return 3
    try:
        cases, meta = run(base, Creds(os.environ["DEPLOY_CHECK_A_LOGIN"], os.environ["DEPLOY_CHECK_A_PASSWORD"]),
                          Creds(os.environ["DEPLOY_CHECK_B_LOGIN"], os.environ["DEPLOY_CHECK_B_PASSWORD"]))
    except RuntimeError as exc:
        print(f"로그인 실패: {exc}", file=sys.stderr)
        return 3
    print(render(cases))
    counted = [c for c in cases if not c.id.startswith("S")]
    passed = sum(1 for c in counted if c.passed)
    setup_ok = all(c.passed for c in cases if c.id.startswith("S"))
    summary = {"row": 21, "passed": passed, "total": len(counted), "setup_ok": setup_ok}
    print(f"\n{passed}/{len(counted)} 통과(준비 {'성공' if setup_ok else '실패'}), 정리: {meta.get('cleanup')}")
    print("참고: " + meta["not_observable"])
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"row": 21, "revision": args.revision, "commit": args.commit, "base_url": base, "started_at": started, "finished_at": now_iso(),
                       "elapsed_s": round(time.perf_counter() - t0, 1), "health": health_info, "summary": summary, "meta": meta,
                       "cases": [asdict(c) for c in cases]}, f, ensure_ascii=False, indent=2)
    return 0 if setup_ok and counted and passed == len(counted) else 1


if __name__ == "__main__":
    sys.exit(main())
