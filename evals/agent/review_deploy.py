"""운영 합동 검토 공정 비교 측정 도구 (사전 등록 62.41, 결정 0104). 팀(`POST /chat`)과 평가용 단일 두 종류(`POST /admin/eval/review`의 `same`, `undivided`)를
같은 리비전에서 문항·회차마다 하나씩 부르고, 정답 쟁점 누락률과 비용 배수를 한 표로 모은다. 이 파일은 만들기만 했고 운영에는 부르지 않았다(시험은 가짜 서버).

호출 경로
- 팀: `POST /chat`(일반 계정, 쿠키 + CSRF)의 질문 그래프가 합동 검토로 분류하면 쟁점표 승인 대기(`approval_request`)로 끝난다. 쟁점표 행은 스트림에 없으므로
  관리자 계정으로 `GET /approvals`를 읽고(`issue_table.rows`, 쟁점 문장 `issue`·`topic` 포함) 이 도구가 만든 건만 반려한다. 비용은 응답에 없고 서버 로그(`fill-cost`)로 채운다.
- 단일: `POST /admin/eval/review`(관리자 계정 + CSRF, 서버 환경 변수 `EVAL_REVIEW_SINGLE=1` 필요). 응답이 JSON 한 번이라 행·비용·`retrieved`(검색이 돌려준 chunk_id)가 그 안에 있다.
  플래그가 꺼져 있으면 404, 하루 상한에 닿으면 429다. 둘 다 이 도구는 질문을 더 보내지 않고 종료 코드 2로 멈춘다.
- 순서: 문항·회차마다 세 갈래를 하나씩(동시 요청 없음) 부르고, 부르는 순서는 번갈아 뒤집는다(팀 -> same -> undivided, 다음 문항은 반대).

판정(사전 등록 62.41과 같은 정의)
- 공식 지표는 62.35와 같은 정답 쟁점 누락률(같은 팀, 근거 섹션 일치, `exp_review_v1.compute_review_metrics`). 정답은 팀장 초안(판정자 확인 전)이다.
- 기준선: 주 기준선 `same`, 보조 기준선 `undivided`. "팀이 낫다"는 팀의 누락률이 상대보다 0.10 이상 낮고 회차 모두 같은 방향일 때만 쓰고, 그 밖은 "차이 없음"(반대 방향도 같은 규칙).
- 62.39(라우팅) 분리: 팀 갈래는 분류를 지나므로 합동 검토로 분류되지 않은 런이 비교를 흐릴 수 있다. 그래서 두 가지를 모두 낸다.
  `all`(주 판정: 방식별 전체 30런, 팀이 합동 검토 경로에 닿지 않은 회차는 찾은 이슈 0건으로 셈)과 `paired`(보조: 팀이 합동 검토 경로에 닿은 문항·회차 쌍만, 세 갈래를 같은 쌍으로 맞춤)를 이 이름으로 함께 낸다(사용자 결정 2026-11-11).
- 비용 배수: 갈래별 런당 평균 비용(비용을 본 런만)의 팀 / 단일. 팀 비용은 `fill-cost`로 서버 로그에서 채운 뒤에만 쓸 수 있다(없으면 "미확인").
- 보조: 검색된 정답 섹션과 문장 기준 채점은 측정 뒤 0원 재계산(이 도구는 `retrieved`와 쟁점 문장을 행에 남기기만 한다).

규칙
- 로그인 정보는 환경 변수로만 받고 출력·저장하지 않는다. 일반 계정(팀 `/chat`): DEPLOY_LATENCY_BASE_URL, DEPLOY_LATENCY_LOGIN, DEPLOY_LATENCY_PASSWORD.
  관리자 계정(단일 호출, 쟁점표 행 읽기, 시험 건 반려): DEPLOY_CHECK_A_LOGIN, DEPLOY_CHECK_A_PASSWORD(필수: 없으면 질문을 보내기 전에 종료 코드 2).
- rows.jsonl에는 질문 원문 대신 문항 id만 적는다. 쟁점 문장(`issue`)과 `topic`은 쟁점 문장 기준 채점을 위해 남긴다(핸드북 근거 위의 모델 문장이고 요청 원문이 아니다).
- 비용 상한(`--max-cost`, 기본 1.0): 관찰한 비용 + 비용을 못 본 런과 다음 세 런의 추정(`EST_RUN_USD`)이 상한을 넘으면 다음 문항을 보내지 않고 종료 코드 3으로 멈춘다.

    PYTHONPATH=. python -m evals.agent.review_deploy --dataset evals/dataset_review_v1_gold_draft.jsonl --repeats 3 --revision <리비전> --commit <해시> --out <폴더> [--max-cost 1.0]
    PYTHONPATH=. python -m evals.agent.review_deploy fill-cost --out <폴더> --log-file <gcloud logging read 출력>

종료 코드: 0 완료, 2 환경·입력·접속 문제(플래그 꺼짐 404, 하루 상한 429 포함), 3 비용 상한으로 멈춤.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from evals.agent import exp_review_v1 as X
from evals.latency.deploy_latency import AttemptTimeout, iter_sse, normalize_as_of, percentile
from evals.safety.deploy_check import Creds, _with_csrf, login

ENV_B = ("DEPLOY_LATENCY_BASE_URL", "DEPLOY_LATENCY_LOGIN", "DEPLOY_LATENCY_PASSWORD")
ENV_A = ("DEPLOY_CHECK_A_LOGIN", "DEPLOY_CHECK_A_PASSWORD")
ARMS = ("team", "same", "undivided")
ARM_DIR = {"team": "team", "same": "single_same", "undivided": "single_undivided"}
EST_RUN_USD = {"team": 0.0075, "same": 0.005, "undivided": 0.005}   # 런 하나의 비용 상한 추정(F2 2차-7, 62.36 팀 쟁점표 런 최대 0.00709달러)
RETRY_STATUS = {502, 503, 504}
COMPACT_KEYS = ("team", "topic", "issue", "chunk_id", "rule_seq", "rule_title", "article", "section_path", "version_date", "stance", "confidence", "conflict")
PATH_OF_STATUS = {"pending_approval": "review_table", "clarify": "review_clarify", "no_issues": "review_no_issues"}
PATH_TO_STATUS = {"review_table": "pending_approval", "review_clarify": "clarify", "review_no_issues": "no_issues",
                  "review_team_failed": X.TEAM_FAILED, "error": "error", "other_route": "other_route"}
TEAM_ROUTED = {"review_table", "review_clarify", "review_no_issues", "review_team_failed"}   # 팀이 합동 검토 경로에 닿았다
NO_ISSUES_PREFIX = "쟁점 없음"
CLARIFY_HINTS = ("검토에 필요한 값이 요청에 없습니다", "검토할 업무 요청이 비어")
REJECT_COMMENT = "배포 측정 시험 건 반려(review_deploy)"
LOG_COST = re.compile(r"llm id=(\S+)\s.*?cost_usd=([0-9]+(?:\.[0-9]+)?)")
MARGIN = 0.10   # 사전 등록 62.41(62.35와 같은 판정 문구): 이 차이 이상이고 모든 회차가 같은 방향일 때만 이겼다고 쓴다


class Abort(Exception):
    """질문을 더 보내지 않고 멈춘다(플래그 꺼짐, 하루 상한, 로그인 실패)."""


# ---------------------------------------------------------------- 스트림 읽기와 분류(네트워크 없음)

def consume_review_stream(lines, *, t0: float, clock: Callable[[], float], deadline_s: float | None = None) -> dict[str, Any]:
    """`/chat` SSE를 읽어 합동 검토 측정에 필요한 값을 모은다. 끝은 `done`, `approval_request`, `error` 중 하나."""
    out: dict[str, Any] = {"status": "no_end", "first_token_s": None, "total_s": None, "answer": "", "citations": 0, "done": None, "approval": None, "error_code": None}

    def guarded(src):
        for ln in src:
            if deadline_s is not None and clock() - t0 > deadline_s:
                raise AttemptTimeout()
            yield ln

    for name, raw in iter_sse(guarded(lines)):
        now = clock() - t0
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        etype = name if name != "message" else (payload.get("type") or name)
        data = payload.get("data") or {}
        if etype == "token":
            if out["first_token_s"] is None:
                out["first_token_s"] = round(now, 3)
            out["answer"] += str(data.get("text") or "")
        elif etype == "citation":
            out["citations"] += 1
        elif etype == "error":
            out.update(status="error", error_code=str(data.get("code") or "unknown"), total_s=round(now, 3))
            return out
        elif etype == "approval_request":
            out.update(status="approval_request", total_s=round(now, 3), approval={k: data.get(k) for k in ("approval_id", "kind", "summary")})
            return out
        elif etype == "done":
            out.update(status="done", total_s=round(now, 3), done=data)
            return out
    return out


def classify_outcome(ev: dict[str, Any]) -> str:
    """팀 `/chat` 스트림 결과 -> 경로. review_table | review_clarify | review_no_issues | review_team_failed | other_route | error."""
    if ev.get("status") == "approval_request":
        kind = (ev.get("approval") or {}).get("kind")
        return "review_table" if kind == "issue_table" else "review_team_failed" if kind == "team_review_failed" else "other_route"
    if ev.get("status") != "done":
        return "error"
    d = ev["done"] or {}
    text = ev.get("answer") or ""
    if d.get("kind") == "clarify" and (d.get("refuse_stage") == "review" or any(h in text for h in CLARIFY_HINTS)):
        return "review_clarify"
    if d.get("kind") == "answer" and text.lstrip().startswith(NO_ISSUES_PREFIX):
        return "review_no_issues"
    return "other_route"


def observed_cost(ev: dict[str, Any]) -> tuple[float | None, str | None]:
    """팀 `done` 이벤트에서 본 비용. `usage.cost_usd`(질문 번역 제외, 서버 로그의 `cost_usd`와 같은 정의)를 쓴다. 단일 응답도 같은 정의라 배수가 같은 기준이다."""
    d = ev.get("done") or {}
    v = (d.get("usage") or {}).get("cost_usd")
    if isinstance(v, (int, float)):
        return float(v), "done.usage.cost_usd(번역 제외)"
    return None, None


def compact_rows(table: dict) -> tuple[list[dict], list[dict]]:
    rows = [{k: r.get(k) for k in COMPACT_KEYS} for r in (table.get("rows") or []) if isinstance(r, dict)]
    unrev = [{"team": u.get("team"), "reason": str(u.get("reason") or "")[:120]} for u in (table.get("unreviewed") or []) if isinstance(u, dict)]
    return rows, unrev


# ---------------------------------------------------------------- 네트워크

def post_chat(client, item: dict, request_id: str, timeout_s: float, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    import httpx

    body: dict[str, Any] = {"message": item["input"]}
    as_of = normalize_as_of(item.get("as_of"))
    if as_of:
        body["as_of"] = as_of
    t0 = clock()
    try:
        with client.stream("POST", "/chat", json=body, headers={"Accept": "text/event-stream", "X-Request-ID": request_id}) as resp:
            if resp.status_code != 200:
                resp.read()
                return {"status": f"http_{resp.status_code}", "total_s": round(clock() - t0, 3)}
            return consume_review_stream(resp.iter_lines(), t0=t0, clock=clock, deadline_s=timeout_s)
    except AttemptTimeout:
        return {"status": "timeout", "total_s": round(clock() - t0, 3)}
    except httpx.TimeoutException:
        return {"status": "timeout", "total_s": round(clock() - t0, 3)}
    except httpx.HTTPError as exc:
        return {"status": f"network_error:{type(exc).__name__}", "total_s": round(clock() - t0, 3)}


def post_single(admin, item: dict, search: str, request_id: str, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    import httpx

    body: dict[str, Any] = {"message": item["input"], "search": search}
    as_of = normalize_as_of(item.get("as_of"))
    if as_of:
        body["as_of"] = as_of
    t0 = clock()
    try:
        resp = admin.post("/admin/eval/review", json=body, headers={"Accept": "application/json", "X-Request-ID": request_id})
    except httpx.TimeoutException:
        return {"status": "timeout", "total_s": round(clock() - t0, 3)}
    except httpx.HTTPError as exc:
        return {"status": f"network_error:{type(exc).__name__}", "total_s": round(clock() - t0, 3)}
    total = round(clock() - t0, 3)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "total_s": total}
    try:
        return {"status": "ok", "total_s": total, "data": resp.json()}
    except ValueError:
        return {"status": "bad_json", "total_s": total}


def ask(call: Callable[[], dict], relogin: Callable[[], bool]) -> dict[str, Any]:
    """401·403이면 다시 로그인해 같은 문항을 다시 보내고, 네트워크 오류·타임아웃·502~504는 1회 더 보낸다(`deploy_latency.ask`와 같은 규칙)."""
    attempts, relogged = 0, False
    while True:
        res = call()
        st = str(res["status"])
        if st in ("http_401", "http_403") and not relogged:
            relogged = True
            if relogin():
                continue
            res["status"] = "login_failed"
            res["attempts"] = attempts + 1
            return res
        attempts += 1
        retryable = st == "timeout" or st.startswith("network_error") or st in {f"http_{c}" for c in RETRY_STATUS}
        if retryable and attempts < 2:
            continue
        res["attempts"] = attempts
        return res


def fetch_issue_table(admin, approval_id: str) -> dict | None:
    """관리자 계정으로 `GET /approvals`를 읽어 이 승인 건의 쟁점표를 찾는다. 못 찾으면 한 번 더 읽는다."""
    for attempt in (1, 2):
        r = admin.get("/approvals", headers={"Accept": "application/json"})
        if r.status_code == 200:
            try:
                for v in r.json():
                    if isinstance(v, dict) and v.get("approval_id") == approval_id and isinstance(v.get("issue_table"), dict):
                        return v["issue_table"]
            except ValueError:
                return None
        if attempt == 1:
            time.sleep(1.0)
    return None


def reject_item(admin, approval_id: str) -> bool:
    r = admin.post(f"/approvals/{approval_id}", json={"approve": False, "comment": REJECT_COMMENT}, headers={"Accept": "application/json"})
    return r.status_code == 200


# ---------------------------------------------------------------- 행 만들기

def team_row(it: dict, rep: int, rid: str, ev: dict, admin, *, reject: bool) -> dict[str, Any]:
    path = classify_outcome(ev)
    cost, cost_src = observed_cost(ev)
    d = ev.get("done") or {}
    row: dict[str, Any] = {
        "arm": "team", "id": it["id"], "repeat": rep, "kind": it["kind"], "as_of": normalize_as_of(it.get("as_of")), "request_id": rid, "path": path,
        "http_or_stream_status": ev["status"], "attempts": ev.get("attempts"), "latency_s": ev.get("total_s"), "error_code": ev.get("error_code"),
        "refuse_stage": d.get("refuse_stage"), "cost_usd_observed": cost, "cost_source": cost_src, "cost_by_step": d.get("cost_by_step"),
        "approval_id": (ev.get("approval") or {}).get("approval_id"), "approval_kind": (ev.get("approval") or {}).get("kind"),
        "clarify_text": (ev.get("answer") or "")[:300] if path == "review_clarify" else None,
        "issue_rows": None, "unreviewed": None, "rows_source": "unavailable", "rejected": None, "retrieved": None, "llm_calls": None, "at": now_iso(),
    }
    if path == "review_table" and row["approval_id"]:
        table = fetch_issue_table(admin, row["approval_id"])
        if table is not None:
            row["issue_rows"], row["unreviewed"] = compact_rows(table)
            row["rows_source"] = "GET /approvals"
        if reject:
            row["rejected"] = reject_item(admin, row["approval_id"])
    elif path in ("review_clarify", "review_no_issues"):
        row["issue_rows"], row["unreviewed"], row["rows_source"] = [], [], "none_expected"
    return row


def single_row(it: dict, rep: int, rid: str, arm: str, ev: dict) -> dict[str, Any]:
    data = ev.get("data") or {}
    status = str(data.get("status") or "")
    path = PATH_OF_STATUS.get(status, "error") if ev["status"] == "ok" else "error"
    usage = data.get("usage") or {}
    cost = usage.get("cost_usd")
    rows, unrev = compact_rows({"rows": data.get("issue_rows"), "unreviewed": data.get("unreviewed")}) if path != "error" else (None, None)
    return {
        "arm": arm, "id": it["id"], "repeat": rep, "kind": it["kind"], "as_of": normalize_as_of(it.get("as_of")), "request_id": rid, "path": path,
        "http_or_stream_status": ev["status"], "attempts": ev.get("attempts"), "latency_s": ev.get("total_s"), "server_latency_ms": data.get("latency_ms"),
        "error_code": None if path != "error" else ev["status"], "cost_usd_observed": float(cost) if isinstance(cost, (int, float)) else None,
        "cost_source": "response.usage.cost_usd(번역 제외)" if isinstance(cost, (int, float)) else None, "cost_by_step": data.get("cost_by_step"),
        "cost_by_step_total_usd": data.get("cost_by_step_total_usd"), "embed_cost_usd": data.get("embed_cost_usd"),
        "clarify_text": (data.get("clarify_question") or "")[:300] if path == "review_clarify" else None,
        "issue_rows": rows, "unreviewed": unrev, "rows_source": "response" if rows is not None else "unavailable", "rejected": None,
        "retrieved": data.get("retrieved"), "llm_calls": data.get("llm_calls"), "team_status": data.get("team_status"),
        "revision": data.get("revision"), "at": now_iso(),
    }


# ---------------------------------------------------------------- 채점과 요약(네트워크 없음)

def to_metric_row(r: dict) -> dict:
    """`exp_review_v1.compute_review_metrics`가 읽는 행 모양."""
    return {"id": r["id"], "repeat": r["repeat"], "kind": r["kind"], "arm": r["arm"], "status": PATH_TO_STATUS.get(r["path"], "error"),
            "issue_rows": r.get("issue_rows") or [], "unreviewed": r.get("unreviewed") or [], "saved_before_approval": None,
            "llm_calls": r.get("llm_calls") or 0, "latency_s": r.get("latency_s") or 0.0, "cost_usd": 0.0, "retrieval_errors": 0}


def rows_unknown(rows: list[dict]) -> int:
    """쟁점표가 나왔는데 행을 읽지 못한 런 수."""
    return sum(1 for r in rows if r["path"] == "review_table" and r.get("issue_rows") is None)


def _missed(rows: list[dict], items: dict[str, dict]) -> float | None:
    if not rows or rows_unknown(rows):
        return None
    m = X.compute_review_metrics([to_metric_row(r) for r in rows], items, allow_draft=True)
    v = m["missed_issue_rate"]
    return v if isinstance(v, (int, float)) else None


def _found(rows: list[dict], items: dict[str, dict]) -> tuple[int | None, int | None]:
    if not rows or rows_unknown(rows):
        return None, None
    m = X.compute_review_metrics([to_metric_row(r) for r in rows], items, allow_draft=True)
    return m["gold_found"], m["gold_total"]


def verdict(team_by_rep: dict[int, float | None], other_by_rep: dict[int, float | None], team_all: float | None, other_all: float | None) -> dict:
    """62.35와 같은 판정 문구. diff = 상대 - 팀(양수면 팀의 누락이 적다). 모든 회차가 같은 방향이고 전체 차이가 MARGIN 이상일 때만 이긴 쪽을 쓴다."""
    if team_all is None or other_all is None:
        return {"diff": None, "per_repeat": {}, "text": "미확인(쟁점표 행을 읽지 못한 런이 있거나 런이 없음)"}
    per = {rep: (None if team_by_rep.get(rep) is None or other_by_rep.get(rep) is None else round(other_by_rep[rep] - team_by_rep[rep], 6)) for rep in sorted(team_by_rep)}
    diff = round(other_all - team_all, 6)
    vals = [v for v in per.values()]
    if diff >= MARGIN and vals and all(v is not None and v > 0 for v in vals):
        text = "팀이 낫다(차이 0.10 이상, 모든 회차 같은 방향)"
    elif diff <= -MARGIN and vals and all(v is not None and v < 0 for v in vals):
        text = "단일이 낫다(차이 0.10 이상, 모든 회차 같은 방향)"
    else:
        text = "차이 없음(0.10 미만이거나 회차 방향이 갈림)"
    return {"diff": diff, "per_repeat": per, "text": text}


def _arm_stats(rows: list[dict], items: dict[str, dict]) -> dict:
    paths: dict[str, int] = {}
    for r in rows:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    lat = [r["latency_s"] for r in rows if r["path"] != "error" and r.get("latency_s") is not None]
    cost_rows = [r for r in rows if isinstance(r.get("cost_usd_observed"), (int, float)) or isinstance(r.get("cost_usd_log"), (int, float))]
    cost_vals = [r["cost_usd_observed"] if isinstance(r.get("cost_usd_observed"), (int, float)) else r["cost_usd_log"] for r in cost_rows]
    found, total = _found(rows, items)
    reps = sorted({r["repeat"] for r in rows})
    return {
        "n_runs": len(rows), "paths": dict(sorted(paths.items())), "rows_unknown": rows_unknown(rows),
        "gold_found": found, "gold_total": total, "missed_issue_rate": _missed(rows, items),
        "missed_by_repeat": {rep: _missed([r for r in rows if r["repeat"] == rep], items) for rep in reps},
        "latency_s": {"mean": round(sum(lat) / len(lat), 3) if lat else None, "p50": percentile(lat, 50), "p95": percentile(lat, 95), "max": max(lat) if lat else None},
        "cost": {"runs_with_cost": len(cost_rows), "runs_without_cost": len(rows) - len(cost_rows), "known_sum_usd": round(sum(cost_vals), 6),
                 "mean_usd": round(sum(cost_vals) / len(cost_vals), 6) if cost_vals else None},
        "llm_calls_mean": round(sum(r["llm_calls"] for r in rows if isinstance(r.get("llm_calls"), (int, float))) / max(1, sum(1 for r in rows if isinstance(r.get("llm_calls"), (int, float)))), 3)
        if any(isinstance(r.get("llm_calls"), (int, float)) for r in rows) else None,
    }


def paired_ids(by_arm: dict[str, list[dict]]) -> set[tuple]:
    """팀이 합동 검토 경로에 닿았고(분류 영향 없음) 단일 둘도 오류 없이 끝난 (문항, 회차) 쌍."""
    ok = {(r["id"], r["repeat"]) for r in by_arm["team"] if r["path"] in TEAM_ROUTED}
    for arm in ("same", "undivided"):
        ok &= {(r["id"], r["repeat"]) for r in by_arm[arm] if r["path"] != "error"}
    return ok


def compare_arms(by_arm: dict[str, list[dict]], items: dict[str, dict]) -> dict:
    out: dict[str, Any] = {}
    pairs = paired_ids(by_arm)
    for label, keep in (("all", None), ("paired", pairs)):
        sub = {a: [r for r in rs if keep is None or (r["id"], r["repeat"]) in keep] for a, rs in by_arm.items()}
        stats = {a: _arm_stats(rs, items) for a, rs in sub.items()}
        team = stats["team"]
        res: dict[str, Any] = {"n_pairs": len({(r["id"], r["repeat"]) for r in sub["team"]}), "arms": stats}
        for other, role in (("same", "main"), ("undivided", "aux")):
            res[f"team_vs_{other}"] = {"role": role, **verdict(team["missed_by_repeat"], stats[other]["missed_by_repeat"], team["missed_issue_rate"], stats[other]["missed_issue_rate"])}
            tm, om = team["cost"]["mean_usd"], stats[other]["cost"]["mean_usd"]
            res[f"cost_ratio_team_over_{other}"] = round(tm / om, 3) if tm and om else None
        out[label] = res
    out["pairs_excluded"] = {"team_not_routed": sum(1 for r in by_arm["team"] if r["path"] not in TEAM_ROUTED), "total_team_runs": len(by_arm["team"])}
    return out


def summarize(by_arm: dict[str, list[dict]], items: dict[str, dict], meta: dict) -> dict:
    return {"meta": meta, "comparison": compare_arms(by_arm, items),
            "per_item": [{"id": iid, "kind": items[str(iid)]["kind"],
                          **{a: [{"rep": r["repeat"], "path": r["path"], "rows": (len(r["issue_rows"]) if r.get("issue_rows") is not None else None)}
                                 for r in sorted(by_arm[a], key=lambda x: x["repeat"]) if r["id"] == iid] for a in ARMS}}
                         for iid in sorted({r["id"] for rs in by_arm.values() for r in rs}, key=lambda x: int(x) if str(x).isdigit() else str(x))]}


def _f(v: Any, nd: int = 3) -> str:
    return "-" if v is None else (v if isinstance(v, str) else f"{v:.{nd}f}")


def render_markdown(s: dict) -> str:
    meta, cmp_ = s["meta"], s["comparison"]
    L = [f"# 운영 합동 검토 공정 비교 ({meta['dataset']} {meta['n_items']}문항 x {meta['repeats']}회, 팀 / 단일 same / 단일 undivided)", "",
         f"- 대상: 리비전 {meta.get('revision') or '미기재'}, 커밋 {meta.get('commit') or '미기재'}. 측정 시각 {meta.get('started_at')} ~ {meta.get('finished_at')}",
         f"- 평가셋: {meta['dataset']} (sha256 {meta['dataset_sha256'][:12]}), 정답 쟁점은 초안(`{X.DRAFT_STATUS}`) 기준이다.",
         "- 방식: 문항·회차마다 세 갈래를 한 건씩(동시 요청 없음), 호출 순서를 번갈아 뒤집었다. 팀은 `POST /chat`, 단일은 `POST /admin/eval/review`다. 시간은 클라이언트 쪽 값이다.",
         "- 주 기준선은 same, 보조 기준선은 undivided. 판정 범위: 주 판정은 방식별 전체 30런(팀이 합동 검토 경로에 닿지 않은 회차는 찾은 이슈 0건으로 센다), 팀이 합동 검토 경로에 닿은 쌍만 본 값은 보조. 판정 문구는 62.35와 같다(0.10 이상이고 모든 회차가 같은 방향일 때만 이긴 쪽을 적는다).", ""]
    if meta.get("stopped_by"):
        L += [f"- 중단: {meta['stopped_by']} (부분 결과, 점수로 쓰지 않는다)", ""]
    for label, title in (("all", "주 판정: 방식별 전체 런(팀이 합동 검토 경로에 닿지 않은 회차는 찾은 이슈 0건)"), ("paired", "보조: 짝을 맞춘 런(팀이 합동 검토 경로에 닿은 문항·회차만, 62.39 분류 누락 제외)")):
        c = cmp_[label]
        L += [f"## {title} ({c['n_pairs']}쌍)", "", "| 갈래 | 런 | 정답 쟁점 찾음 | 누락률 | 회차별 누락률 | 시간 p50 | 시간 p95 | 런당 비용(달러) | 비용 본 런 |", "|---|---|---|---|---|---|---|---|---|"]
        for a in ARMS:
            st = c["arms"][a]
            by_rep = ", ".join(f"{rep}회 {_f(v)}" for rep, v in st["missed_by_repeat"].items())
            L.append(f"| {a} | {st['n_runs']} | {st['gold_found'] if st['gold_found'] is not None else '-'}/{st['gold_total'] if st['gold_total'] is not None else '-'} | {_f(st['missed_issue_rate'])} | {by_rep or '-'} | "
                     f"{_f(st['latency_s']['p50'])} | {_f(st['latency_s']['p95'])} | {_f(st['cost']['mean_usd'], 5)} | {st['cost']['runs_with_cost']}/{st['n_runs']} |")
        L += ["", "| 비교 | 기준선 | 누락률 차이(상대 - 팀, 양수면 팀이 적음) | 회차별 | 판정 | 비용 배수(팀 / 상대) |", "|---|---|---|---|---|---|"]
        for other in ("same", "undivided"):
            v = c[f"team_vs_{other}"]
            L.append(f"| 팀 대 {other} | {'주 기준선' if v['role'] == 'main' else '보조 기준선'} | {_f(v['diff'])} | {', '.join(f'{k}회 {_f(x)}' for k, x in v['per_repeat'].items()) or '-'} | {v['text']} | "
                     f"{_f(c[f'cost_ratio_team_over_{other}'], 2)} |")
        L += [""]
    ex = cmp_["pairs_excluded"]
    L += [f"- 팀이 합동 검토로 분류되지 않은 런: {ex['team_not_routed']}/{ex['total_team_runs']} (62.39 소관, 짝을 맞춘 표에서는 빼고 전체 표에는 넣었다).",
          "- 비용: 팀 런은 쟁점표 승인 대기로 끝나 응답에 비용이 없다. `fill-cost`로 서버 로그를 채우기 전의 팀 비용·배수는 '-'(미확인)다. 정의는 모두 번역 LLM을 뺀 그래프 합이다.",
          "- 한계: 쟁점 문장은 비교하지 않고 팀과 근거 섹션만 맞춘다(`exp_review_v1` 모듈 설명의 한계 1~6과 같다). 10문항 3회에서 1~2건 차이는 우연일 수 있다. "
          "정답은 팀 절 안에서 적혀 있어 undivided에 불리할 수 있다. 쟁점 문장 기준 채점과 검색된 정답 섹션 계산은 이 표에 없고 측정 뒤 0원 재계산으로 따로 낸다.", ""]
    return "\n".join(L)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def load_all(out: Path) -> dict[str, list[dict]]:
    return {a: load_rows(out / ARM_DIR[a] / "rows.jsonl") for a in ARMS}


def write_outputs(out: Path, items: dict[str, dict], meta: dict) -> dict:
    s = summarize(load_all(out), items, meta)
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(render_markdown(s), encoding="utf-8")
    return s


def arm_order(index: int) -> list[str]:
    """문항·회차마다 번갈아 뒤집는다: 짝수 번째는 팀 -> same -> undivided, 홀수 번째는 반대."""
    return list(ARMS) if index % 2 == 0 else list(reversed(ARMS))


def projected_cost(rows: list[dict], upcoming: list[str]) -> tuple[float, float]:
    known = sum((r.get("cost_usd_observed") or 0.0) for r in rows)
    unknown = sum(EST_RUN_USD[r["arm"]] for r in rows if not isinstance(r.get("cost_usd_observed"), (int, float)))
    return known, known + unknown + sum(EST_RUN_USD[a] for a in upcoming)


# ---------------------------------------------------------------- 실행

def run_cmd(args) -> int:
    missing = [n for n in (*ENV_B, *ENV_A) if not os.environ.get(n)]
    if missing:
        print("환경 변수가 없다: " + ", ".join(missing), file=sys.stderr)
        return 2
    import httpx

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print(f"평가셋 파일이 없다: {dataset_path}", file=sys.stderr)
        return 2
    try:
        items = X.load_review_dataset(dataset_path)
    except ValueError as exc:
        print(f"평가셋을 읽지 못했다: {exc}", file=sys.stderr)
        return 2
    if args.limit:
        items = items[: args.limit]
    by_id = {str(it["id"]): it for it in items}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if any((out / ARM_DIR[a] / "rows.jsonl").exists() and (out / ARM_DIR[a] / "rows.jsonl").stat().st_size > 0 for a in ARMS):
        print(f"{out}에 이전 결과가 있다. 폴더를 옮기거나 --out을 바꿔라.", file=sys.stderr)
        return 2
    for a in ARMS:
        (out / ARM_DIR[a]).mkdir(parents=True, exist_ok=True)
    base = os.environ["DEPLOY_LATENCY_BASE_URL"].rstrip("/")
    creds_b = Creds(os.environ["DEPLOY_LATENCY_LOGIN"], os.environ["DEPLOY_LATENCY_PASSWORD"])
    creds_a = Creds(os.environ["DEPLOY_CHECK_A_LOGIN"], os.environ["DEPLOY_CHECK_A_PASSWORD"])
    timeout = httpx.Timeout(30.0, read=args.timeout)
    client, admin = httpx.Client(base_url=base, timeout=timeout), httpx.Client(base_url=base, timeout=timeout)

    def do_login(c, creds, tag) -> bool:
        uid, why = login(c, creds)
        if not uid:
            print(f"  로그인 실패({tag}): {why}", file=sys.stderr)
            return False
        _with_csrf(c)
        return True

    try:
        h = client.get("/health")
        print(f"/health {h.status_code}")
    except httpx.HTTPError as exc:
        print(f"/health 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    if not do_login(client, creds_b, "B") or not do_login(admin, creds_a, "A"):
        return 2

    tag = uuid.uuid4().hex[:6]
    meta: dict[str, Any] = {
        "dataset": dataset_path.name, "dataset_path": dataset_path.as_posix(), "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(), "n_items": len(items),
        "repeats": args.repeats, "base_url": base, "revision": args.revision, "commit": args.commit, "timeout_s": args.timeout, "max_cost_usd": args.max_cost,
        "gold_draft": True, "rejected_enabled": not args.no_reject, "request_id_prefix": f"rvfair-{tag}-", "arms": list(ARMS), "started_at": now_iso(), "finished_at": None,
        "stopped_by": None, "note": "팀은 /chat, 단일은 /admin/eval/review. 시간은 클라이언트 측(요청 전송부터 마지막 이벤트나 응답까지), 로그인·CSRF 준비 시간 제외.",
    }
    rows: list[dict] = []
    stopped = None
    aborted = None
    leftover: list[str] = []
    files = {a: (out / ARM_DIR[a] / "rows.jsonl").open("a", encoding="utf-8") for a in ARMS}
    try:
        index = 0
        for rep in range(1, args.repeats + 1):
            for it in items:
                order = arm_order(index)
                index += 1
                known, proj = projected_cost(rows, order)
                if args.max_cost is not None and proj > args.max_cost:
                    stopped = (f"관찰 비용 {known:.4f}달러와 비용을 못 본 런·다음 세 런의 추정을 더한 {proj:.4f}달러가 상한 {args.max_cost}달러를 넘어 멈춘다({len(rows)}런 완료)")
                    raise StopIteration
                for arm in order:
                    rid = f"rvfair-{tag}-{arm}-{it['id']}-{rep}"
                    if arm == "team":
                        ev = ask(lambda: post_chat(client, it, rid, args.timeout), lambda: do_login(client, creds_b, "B"))
                        row = team_row(it, rep, rid, ev, admin, reject=not args.no_reject)
                        if row["approval_id"] and row["rejected"] is not True:
                            leftover.append(row["approval_id"])
                    else:
                        ev = ask(lambda: post_single(admin, it, arm, rid), lambda: do_login(admin, creds_a, "A"))
                        if ev["status"] == "http_404":
                            aborted = "평가용 단일 모드가 꺼져 있다(404). 서버 환경 변수 EVAL_REVIEW_SINGLE=1인 리비전에서 돌려라."
                            raise Abort(aborted)
                        if ev["status"] == "http_429":
                            aborted = "평가용 단일 모드의 비용 또는 하루 호출 상한에 닿았다(429)."
                            raise Abort(aborted)
                        row = single_row(it, rep, rid, arm, ev)
                    rows.append(row)
                    files[arm].write(json.dumps(row, ensure_ascii=False) + "\n")
                    files[arm].flush()
                    c = f" ${row['cost_usd_observed']:.4f}" if isinstance(row.get("cost_usd_observed"), (int, float)) else ""
                    print(f"  [{rep}회차] 문항 {it['id']:>2} {arm:<9} {row['path']:<18} {row['latency_s']}초 쟁점 행 {len(row['issue_rows']) if row['issue_rows'] is not None else '?'}{c}", flush=True)
    except StopIteration:
        print(stopped, flush=True)
    except Abort as exc:
        print(f"멈춘다: {exc}", file=sys.stderr)
    finally:
        for f in files.values():
            f.close()
    meta["finished_at"] = now_iso()
    meta["stopped_by"] = stopped or aborted
    meta["partial"] = bool(stopped or aborted)
    meta["pending_approvals_left"] = leftover
    if rows:
        s = write_outputs(out, by_id, meta)
        c = s["comparison"]["all"]
        print(f"끝: {len(rows)}런. 누락률 팀 {c['arms']['team']['missed_issue_rate']}, same {c['arms']['same']['missed_issue_rate']}, undivided {c['arms']['undivided']['missed_issue_rate']}")
    if leftover:
        print(f"주의: 운영에 승인 대기로 남은 시험 건 {len(leftover)}개(승인 번호는 summary.json의 meta.pending_approvals_left).")
    print(f"결과: {out}")
    return 2 if aborted else 3 if stopped else 0


def fill_cost_cmd(args) -> int:
    """gcloud 로그 출력에서 `llm id=<요청 ID> ... cost_usd=` 줄을 찾아 팀 rows.jsonl에 `cost_usd_log`로 채우고 요약을 다시 쓴다."""
    out = Path(args.out)
    path = out / ARM_DIR["team"] / "rows.jsonl"
    rows = load_rows(path)
    sj = out / "summary.json"
    if not rows or not sj.is_file():
        print(f"{out}에 팀 rows.jsonl 또는 summary.json이 없다", file=sys.stderr)
        return 2
    text = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    found: dict[str, float] = {}
    for m in LOG_COST.finditer(text.replace("\\n", "\n")):
        found[m.group(1).rstrip(",;\"'")] = float(m.group(2))
    n = 0
    for r in rows:
        v = found.get(r["request_id"])
        if v is not None:
            r["cost_usd_log"] = v
            n += 1
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    meta = json.loads(sj.read_text(encoding="utf-8"))["meta"]
    ds = Path(args.dataset) if args.dataset else Path(meta.get("dataset_path") or "")
    items = X.load_review_dataset(ds if ds.is_file() else X.EVALS / meta["dataset"])
    s = write_outputs(out, {str(it["id"]): it for it in items}, meta)
    team = s["comparison"]["all"]["arms"]["team"]["cost"]
    print(f"로그에서 비용을 찾은 팀 런 {n}/{len(rows)}. 비용을 본 팀 런 {team['runs_with_cost']}/{len(rows)}, 합 {team['known_sum_usd']}달러")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "fill-cost":
        ap = argparse.ArgumentParser(prog="review_deploy fill-cost")
        ap.add_argument("--out", required=True)
        ap.add_argument("--log-file", required=True)
        ap.add_argument("--dataset", default="")
        return fill_cost_cmd(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description="운영 합동 검토 공정 비교(팀 / 단일 same / 단일 undivided, 로그인 정보는 환경 변수로만)")
    ap.add_argument("--dataset", default=str(X.EVALS / "dataset_review_v1_gold_draft.jsonl"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--revision", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-cost", type=float, default=1.0, help="누적 비용 상한(달러). 관찰 비용 + 못 본 런·다음 세 런 추정이 넘으면 멈추고 종료 코드 3")
    ap.add_argument("--timeout", type=float, default=180.0, help="한 호출의 제한 시간(초)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N문항만(시험용)")
    ap.add_argument("--no-reject", action="store_true", help="시험 승인 건을 반려하지 않는다")
    return run_cmd(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
