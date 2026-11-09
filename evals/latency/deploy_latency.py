"""배포본 응답 시간 측정: 배포된 서비스에 평가셋 v2 50건을 문항마다 새 대화로 `POST /chat`에 보내 시간을 잰다 (강사 요청: "응답 시간은 배포본에서 3회").

재는 것(클라이언트 측, 요청을 보낸 시각부터)
- 첫 토큰까지 시간: 첫 `token` 이벤트를 받은 시각. 서버는 그래프가 끝난 뒤 token, citation, done을 내보내므로 전체 시간에 가깝다.
- 전체 시간: `done` 이벤트를 받은 시각.
- 결과 kind(answer | clarify | refuse), 인용 수(`citation` 이벤트 개수), 비용(`done.usage.cost_usd`, 있으면)과 토큰 수.

규칙
- 문항은 1번부터 순서대로 하나씩 보낸다(동시 요청 없음). thread_id를 주지 않으므로 서버가 문항마다 새 대화를 만든다.
- `as_of`는 평가셋의 값을 그대로 보낸다(`2023-05`처럼 달만 있으면 그 달 마지막 날). 최종 측정 때와 같은 기준일이다.
- 네트워크 오류, 타임아웃(기본 120초), 502·503·504는 1회 다시 보내고 그래도 실패하면 실패로 적고 계속한다. 401이면 다시 로그인해 같은 문항을 다시 보낸다.
- 시간 통계는 성공한 문항만으로 낸다. 실패는 개수와 사유를 따로 적는다.
- 계정 정보와 쿠키는 출력하지도 저장하지도 않는다. 로그인 정보는 환경 변수로만 받는다.

    환경 변수: DEPLOY_LATENCY_BASE_URL, DEPLOY_LATENCY_LOGIN, DEPLOY_LATENCY_PASSWORD (일반 평가용 계정)
    python -m evals.latency.deploy_latency --revision provena-api-00020 --commit 2c2d61d [--runs 3] [--resume] [--limit N]

결과: evals/results/deploy_latency_v2/run1~3/rows.jsonl, 같은 폴더의 summary.json, summary.md.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "evals" / "dataset_v2.jsonl"
DEFAULT_OUT = REPO / "evals" / "results" / "deploy_latency_v2"
ENV_REQUIRED = ("DEPLOY_LATENCY_BASE_URL", "DEPLOY_LATENCY_LOGIN", "DEPLOY_LATENCY_PASSWORD")
RETRY_STATUS = {502, 503, 504}


class AttemptTimeout(Exception):
    """한 번의 요청이 제한 시간 안에 끝나지 않았다."""


# ---------------------------------------------------------------- 순수 계산(네트워크 없음)

def percentile(values: list[float], pct: float) -> float | None:
    """가장 가까운 순위 방식(평가 실행기의 p95와 같다)."""
    if not values:
        return None
    s = sorted(values)
    return s[min(max(1, math.ceil(pct / 100.0 * len(s))), len(s)) - 1]


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "max": None}
    return {"mean": round(sum(values) / len(values), 3), "p50": percentile(values, 50), "p95": percentile(values, 95), "max": max(values)}


def normalize_as_of(value: str | None) -> str | None:
    """`YYYY-MM`이면 그 달 마지막 날로 바꾼다. `/chat`은 `YYYY-MM-DD`만 받는다."""
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}", value):
        y, m = int(value[:4]), int(value[5:])
        return f"{value}-{calendar.monthrange(y, m)[1]:02d}"
    return value


def iter_sse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """SSE 줄을 (이벤트 이름, data 문자열)로 묶는다. 빈 줄이 한 이벤트의 끝이고 `:`로 시작하는 줄(ping)은 버린다."""
    name, data = "message", []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                yield name, "\n".join(data)
            name, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:][1:] if line[5:].startswith(" ") else line[5:])
    if data:
        yield name, "\n".join(data)


def consume_chat_stream(lines: Iterable[str], *, t0: float, clock: Callable[[], float], deadline_s: float | None = None) -> dict[str, Any]:
    """`/chat`의 SSE 줄을 읽어 시간과 결과를 계산한다. `t0`는 요청을 보낸 시각(`clock()` 기준)."""
    out: dict[str, Any] = {"status": "no_done", "first_token_s": None, "total_s": None, "result": None, "citations": 0,
                           "cost_usd": None, "input_tokens": None, "output_tokens": None, "llm_calls": None, "error_code": None, "answer_chars": 0}

    def guarded(src: Iterable[str]) -> Iterator[str]:
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
            out["answer_chars"] += len(str(data.get("text") or ""))
        elif etype == "citation":
            out["citations"] += 1
        elif etype == "error":
            out.update(status="error", error_code=str(data.get("code") or "unknown"), total_s=round(now, 3))
            return out
        elif etype == "approval_request":
            out.update(status="approval_request", total_s=round(now, 3))
            return out
        elif etype == "done":
            usage = data.get("usage") or {}
            out.update(status="ok", total_s=round(now, 3), result=data.get("kind"), cost_usd=usage.get("cost_usd"),
                       input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"), llm_calls=usage.get("calls"))
            if out["first_token_s"] is None:   # 토큰 없이 끝난 경우(거절 등)는 done 시각을 첫 응답으로 본다
                out["first_token_s"] = round(now, 3)
            return out
    return out


def summarize_rows(rows: list[dict]) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    fails = [r for r in rows if r.get("status") != "ok"]
    costs = [r["cost_usd"] for r in ok if isinstance(r.get("cost_usd"), (int, float))]
    kinds: dict[str, int] = {}
    for r in ok:
        kinds[str(r.get("result"))] = kinds.get(str(r.get("result")), 0) + 1
    return {
        "n": len(rows), "n_ok": len(ok), "n_fail": len(fails),
        "first_token_s": stats([r["first_token_s"] for r in ok if r.get("first_token_s") is not None]),
        "total_s": stats([r["total_s"] for r in ok if r.get("total_s") is not None]),
        "kinds": dict(sorted(kinds.items())),
        "citations_mean": round(sum(r.get("citations") or 0 for r in ok) / len(ok), 2) if ok else None,
        "cost_usd_sum": round(sum(costs), 6) if costs else None,
        "cost_usd_per_question": round(sum(costs) / len(costs), 6) if costs else None,
        "cost_rows": len(costs),
        "failures": [{"run": r.get("run"), "id": r.get("id"), "status": r.get("status")} for r in fails],
    }


def build_summary(runs: dict[int, list[dict]], meta: dict[str, Any]) -> dict[str, Any]:
    all_rows = [r for n in sorted(runs) for r in runs[n]]
    rel = [r for r in all_rows if not r.get("expect_refusal")]
    irr = [r for r in all_rows if r.get("expect_refusal")]
    return {"meta": meta,
            "per_run": [{"run": n, **summarize_rows(runs[n])} for n in sorted(runs)],
            "all_runs": summarize_rows(all_rows),
            "relevant_only": summarize_rows(rel), "irrelevant_only": summarize_rows(irr)}


def _f(v: float | None, nd: int = 3) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def render_markdown(summary: dict[str, Any]) -> str:
    m = summary["meta"]
    lines = [f"# 배포본 응답 시간 (평가셋 v2 {m.get('n_questions')}건 x {len(summary['per_run'])}회)", "",
             f"- 대상: {m.get('base_url')}, 리비전 {m.get('revision') or '미기재'}, 커밋 {m.get('commit') or '미기재'}",
             f"- 측정 시각: {m.get('started_at')} ~ {m.get('finished_at')}",
             f"- 방식: 평가셋 순서대로 문항마다 새 대화로 `POST /chat`을 한 건씩 보내고, 요청을 보낸 시각부터 첫 `token`, `done` 이벤트까지 클라이언트 쪽에서 쟀다(네트워크 지연 포함, 동시 요청 없음, 제한 시간 {m.get('timeout_s')}초, `as_of`는 평가셋 값).",
             "- 시간 통계는 성공한 문항만으로 냈다. 비용은 `done`의 `usage.cost_usd`(서버가 센 LLM 호출 비용) 합이다.", "",
             "## 전체 시간과 첫 토큰 시간 (초)", "",
             "| 회차 | 성공/전체 | 전체 p50 | 전체 p95 | 전체 평균 | 전체 최대 | 첫 토큰 p50 | 첫 토큰 p95 | 비용 합(달러) |", "|---|---|---|---|---|---|---|---|---|"]

    def row(label: str, s: dict) -> str:
        t, f = s["total_s"], s["first_token_s"]
        return (f"| {label} | {s['n_ok']}/{s['n']} | {_f(t['p50'])} | {_f(t['p95'])} | {_f(t['mean'])} | {_f(t['max'])} | "
                f"{_f(f['p50'])} | {_f(f['p95'])} | {_f(s['cost_usd_sum'], 4)} |")

    lines += [row(f"{p['run']}회차", p) for p in summary["per_run"]]
    lines.append(row("3회 합" if len(summary["per_run"]) == 3 else f"{len(summary['per_run'])}회 합", summary["all_runs"]))
    a = summary["all_runs"]
    lines += ["", f"회차별 전체 시간 p95의 평균: {_f(_mean([p['total_s']['p95'] for p in summary['per_run']]))}초(평가 보고서 4장의 '3회 평균' 방식).", "",
              "## 결과 종류와 비용", "", "| 구분 | 성공/전체 | answer | clarify | refuse | 인용 평균 | 요청당 비용(달러) | 비용 합(달러) |", "|---|---|---|---|---|---|---|---|"]

    def kind_row(label: str, s: dict) -> str:
        k = s["kinds"]
        return (f"| {label} | {s['n_ok']}/{s['n']} | {k.get('answer', 0)} | {k.get('clarify', 0)} | {k.get('refuse', 0)} | "
                f"{_f(s['citations_mean'], 2)} | {_f(s['cost_usd_per_question'], 4)} | {_f(s['cost_usd_sum'], 4)} |")

    lines += [kind_row(f"{p['run']}회차", p) for p in summary["per_run"]]
    lines += [kind_row("합계", a), kind_row("관련 문항만", summary["relevant_only"]), kind_row("비관련 문항만", summary["irrelevant_only"]), "",
              "## 평가 보고서 8장 형식 (전체 단계만 잼, 단계별 분해는 클라이언트에서 알 수 없음)", "",
              "| 단계 | p50 | p95 | 요청당 비용 |", "|---|---|---|---|",
              f"| 전체(배포본, 클라이언트 측) | {_f(a['total_s']['p50'])}초 | {_f(a['total_s']['p95'])}초 | {_f(a['cost_usd_per_question'], 4)}달러 |"]
    if a["failures"]:
        lines += ["", "## 실패한 문항", "", "| 회차 | 문항 | 사유 |", "|---|---|---|"]
        lines += [f"| {f['run']} | {f['id']} | {f['status']} |" for f in a["failures"]]
    return "\n".join(lines) + "\n"


def _mean(values: list[float | None]) -> float | None:
    v = [x for x in values if x is not None]
    return round(sum(v) / len(v), 3) if v else None


# ---------------------------------------------------------------- 네트워크

def load_dataset(path: Path = DATASET, limit: int | None = None) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return items[:limit] if limit else items


def ask_once(client, item: dict, *, use_as_of: bool, timeout_s: float, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """한 번 보낸다. 실패 사유는 상태 문자열로 돌려주고(예외를 밖으로 내지 않음) 응답 본문은 남기지 않는다."""
    import httpx

    body: dict[str, Any] = {"message": item["input"]}
    as_of = normalize_as_of(item.get("as_of")) if use_as_of else None
    if as_of:
        body["as_of"] = as_of
    t0 = clock()
    try:
        with client.stream("POST", "/chat", json=body, headers={"Accept": "text/event-stream"}) as resp:
            if resp.status_code != 200:
                resp.read()
                return {"status": f"http_{resp.status_code}", "first_token_s": None, "total_s": round(clock() - t0, 3), "result": None, "citations": 0}
            return consume_chat_stream(resp.iter_lines(), t0=t0, clock=clock, deadline_s=timeout_s)
    except AttemptTimeout:
        return {"status": "timeout", "first_token_s": None, "total_s": round(clock() - t0, 3), "result": None, "citations": 0}
    except httpx.TimeoutException:
        return {"status": "timeout", "first_token_s": None, "total_s": round(clock() - t0, 3), "result": None, "citations": 0}
    except httpx.HTTPError as exc:
        return {"status": f"network_error:{type(exc).__name__}", "first_token_s": None, "total_s": round(clock() - t0, 3), "result": None, "citations": 0}


def ask(client, item: dict, relogin: Callable[[], bool], *, use_as_of: bool, timeout_s: float) -> dict[str, Any]:
    """401이면 다시 로그인해 같은 문항을 다시 보내고(시도 횟수에 넣지 않음), 네트워크 오류·타임아웃·502~504는 1회 더 보낸다."""
    attempts, relogged = 0, False
    while True:
        res = ask_once(client, item, use_as_of=use_as_of, timeout_s=timeout_s)
        if res["status"] in ("http_401", "http_403") and not relogged:
            relogged = True
            if relogin():
                continue
            res["status"] = "login_failed"
            res["attempts"] = attempts + 1
            return res
        attempts += 1
        retryable = res["status"] == "timeout" or res["status"].startswith("network_error") or res["status"] in {f"http_{c}" for c in RETRY_STATUS}
        if retryable and attempts < 2:
            continue
        res["attempts"] = attempts
        return res


def load_done_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def write_outputs(out: Path, runs: dict[int, list[dict]], meta: dict[str, Any]) -> None:
    summary = build_summary(runs, meta)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(render_markdown(summary), encoding="utf-8")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="배포본 응답 시간 측정(평가셋 v2, 로그인 정보는 환경 변수로만)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="결과 폴더(기본 evals/results/deploy_latency_v2)")
    ap.add_argument("--revision", default="", help="배포 리비전 이름(기록용, 예 provena-api-00020)")
    ap.add_argument("--commit", default="", help="배포 커밋(기록용, 예 2c2d61d)")
    ap.add_argument("--timeout", type=float, default=120.0, help="문항 하나의 제한 시간(초)")
    ap.add_argument("--resume", action="store_true", help="이미 성공한 문항은 건너뛰고 이어서 잰다")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N문항만(시험용)")
    ap.add_argument("--no-as-of", action="store_true", help="as_of를 보내지 않는다(서버 기본 기준일)")
    ap.add_argument("--pause", type=float, default=0.0, help="문항 사이에 쉬는 초")
    args = ap.parse_args(argv)

    missing = [n for n in ENV_REQUIRED if not os.environ.get(n)]
    if missing:
        print("환경 변수가 없다: " + ", ".join(missing), file=sys.stderr)
        return 2
    import httpx

    from evals.safety.deploy_check import Creds, _with_csrf, login

    base = os.environ["DEPLOY_LATENCY_BASE_URL"].rstrip("/")
    creds = Creds(os.environ["DEPLOY_LATENCY_LOGIN"], os.environ["DEPLOY_LATENCY_PASSWORD"])
    items = load_dataset(limit=args.limit or None)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not args.resume and any((out / f"run{n}" / "rows.jsonl").exists() for n in range(1, args.runs + 1)):
        print(f"{out}에 이전 결과가 있다. 이어서 하려면 --resume, 새로 하려면 폴더를 옮기거나 --out을 바꿔라.", file=sys.stderr)
        return 2

    client = httpx.Client(base_url=base, timeout=httpx.Timeout(30.0, read=args.timeout))

    def do_login() -> bool:
        uid, why = login(client, creds)
        if not uid:
            print(f"  로그인 실패: {why}", file=sys.stderr)
            return False
        _with_csrf(client)   # 로그인으로 바뀐 CSRF 쿠키와 헤더를 맞춘다
        return True

    t_h = time.perf_counter()
    try:
        health = client.get("/health")
        health_s, health_code = round(time.perf_counter() - t_h, 3), health.status_code
    except httpx.HTTPError as exc:
        print(f"/health 실패: {type(exc).__name__}", file=sys.stderr)
        return 3
    print(f"/health {health_code} ({health_s}초)")
    if not do_login():
        return 3

    meta: dict[str, Any] = {
        "dataset": DATASET.name, "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(), "n_questions": len(items),
        "base_url": base, "revision": args.revision, "commit": args.commit, "timeout_s": args.timeout, "as_of": "dataset" if not args.no_as_of else "none",
        "health_s": health_s, "started_at": now_iso(), "finished_at": None, "runs_requested": args.runs,
        "note": "클라이언트 측 시간(요청 전송부터 첫 token, done 이벤트까지). 로그인과 CSRF 준비 시간은 넣지 않았다.",
    }
    old = out / "summary.json"
    if args.resume and old.exists():   # 이어서 할 때 처음 시작 시각을 유지한다
        try:
            meta["started_at"] = json.loads(old.read_text(encoding="utf-8"))["meta"].get("started_at") or meta["started_at"]
        except (ValueError, KeyError):
            pass

    runs: dict[int, list[dict]] = {}
    for n in range(1, args.runs + 1):
        rdir = out / f"run{n}"
        rdir.mkdir(parents=True, exist_ok=True)
        rpath = rdir / "rows.jsonl"
        kept = [r for r in load_done_rows(rpath) if r.get("status") == "ok"] if args.resume else []
        with rpath.open("w", encoding="utf-8") as f:   # 성공한 줄만 다시 쓰고(실패 문항은 다시 잰다) 이어서 덧붙인다
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        done_ids = {r["id"] for r in kept}
        rows = list(kept)
        todo = [it for it in items if it["id"] not in done_ids]
        print(f"[{n}회차/{args.runs}] 남은 문항 {len(todo)}/{len(items)}" + (f" (이미 성공 {len(kept)}건 건너뜀)" if kept else ""))
        with rpath.open("a", encoding="utf-8") as f:
            for i, it in enumerate(todo, 1):
                res = ask(client, it, do_login, use_as_of=not args.no_as_of, timeout_s=args.timeout)
                row = {"run": n, "id": it["id"], "dataset_kind": it.get("kind"), "expect_refusal": it.get("kind") == "irrelevant",
                       "as_of": normalize_as_of(it.get("as_of")) if not args.no_as_of else None, **res, "at": now_iso()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                rows.append(row)
                cost = f" ${row['cost_usd']:.4f}" if isinstance(row.get("cost_usd"), (int, float)) else ""
                if row["status"] == "ok":
                    print(f"  [{n}회차] {len(done_ids) + i:>2}/{len(items)} 문항 id={it['id']:<3} 첫토큰 {row['first_token_s']:>6.2f}초 전체 {row['total_s']:>6.2f}초 {row['result']} 인용 {row['citations']}{cost}", flush=True)
                else:
                    print(f"  [{n}회차] {len(done_ids) + i:>2}/{len(items)} 문항 id={it['id']:<3} 실패: {row['status']} ({row['total_s']}초, 시도 {row['attempts']})", flush=True)
                if args.pause:
                    time.sleep(args.pause)
        rows.sort(key=lambda r: r["id"])
        runs[n] = rows
        meta["finished_at"] = now_iso()
        write_outputs(out, runs, meta)   # 회차마다 저장해 중간에 끊겨도 앞 회차 요약이 남는다
        s = summarize_rows(rows)
        print(f"[{n}회차 끝] 성공 {s['n_ok']}/{s['n']}, 전체 p50 {_f(s['total_s']['p50'])}초, p95 {_f(s['total_s']['p95'])}초, 평균 {_f(s['total_s']['mean'])}초, 비용 합 {_f(s['cost_usd_sum'], 4)}달러")
    print(f"결과: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
