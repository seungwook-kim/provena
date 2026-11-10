"""저장된 평가 결과(rows.jsonl)로 단계별 응답 시간과 요청당 비용을 다시 센다 (EVAL_REPORT 8장, 가이드 p.19). 새로 재지 않고 비용도 들지 않는다.

입력: `evals/agent/exp_multi_v2.py`가 남긴 `<결과 폴더>/{single,multi}/rows.jsonl`. 행마다 쓰는 칸:
- `latency_s`: 그래프 한 번(질문 한 건)의 전체 시간. 회차 p95는 `summary.json`의 `latency_p95_s`와 같아야 한다(아래 검사).
- `retrieval_calls[].wall_s`: `Searcher.search` 한 번의 시간(`exp_service_v1.RecordingSearch`). 번역 LLM이 이 안에서 돈다.
  `retrieval_calls[].trace.ms`: 그 안의 번역·임베딩·벡터·링크 시간(ms). 링크 확장을 건너뛴 호출은 `link` 칸이 없어 0으로 센다(`search.py` `_link_expand`).
- `llm_trace[]`: LLM 호출마다 `step`, `seconds`, `model`, `input_tokens`, `output_tokens`(`backend/services/llm_trace.py`).

단계 나누기(STEP_STAGE): 검색 = 검색 호출 시간의 합(번역 LLM 포함), 판단 = 질문 분류·분해·재작성·근거 충분 판정 LLM,
생성 = 답 작성 LLM, 검증 = 근거 판정과 다시 쓰기 LLM. 리랭킹은 리랭커를 쓰지 않아 없다(`docs/decisions.md` 2026-11-03).
표에 없는 `step`이 나오면 멈춘다(조용히 빼지 않는다).

비용: 호출에 공급자가 알려 준 비용(`llm_trace[].reported_cost_usd`, 캐시 할인 반영)이 있으면 그 값, 없으면 토큰 x 팀 단가표(`backend/services/cost.py` `cost_usd`,
`llm_prices.json`)로 낸 추정값이다(강의 rag 3주 11강: 실측 우선, 정가표는 검산용). 11/5 결과에는 보고값 칸이 없어 모두 추정값이고 결제액이 아니다.
Voyage 임베딩 비용은 행에 기록이 없어 넣지 않는다.
p50과 p95는 `run_eval._p95`와 같은 최근순위(nearest-rank) 방식이다: 정렬 뒤 ceil(q x n)번째 값.

사용:
  python -m evals.agent.stage_report                                   (기본: agent_v2_multi_pg, _r2, _r3)
  python -m evals.agent.stage_report --runs 폴더1 폴더2 --json 결과.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from backend.services.cost import cost_usd, load_prices
from evals.agent.run_eval import _p95

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS = ["evals/results/agent_v2_multi_pg", "evals/results/agent_v2_multi_pg_r2", "evals/results/agent_v2_multi_pg_r3"]
ARMS = ("single", "multi")
STEP_STAGE = {
    "translate_sentence": "search",          # Searcher.search 안에서 돈다: 시간은 wall_s에 이미 들어 있고 비용만 검색에 붙인다
    "classify/classify": "plan",
    "supervisor/classify": "plan",
    "search/decompose": "plan",
    "search/decompose_gate": "plan",         # 예비 분해(`--speculate-first`, 최종 측정 설정에서 켜짐)
    "rewrite/rewrite": "plan",
    "judge/judge": "plan",
    "write_answer/answer": "generate",
    "write_answer/answer_fast": "generate",  # 첫 답을 기다리지 않고 내는 빠른 답(최종 측정 설정)
    "ground/grounding": "verify",
    "ground/answer": "verify",               # 근거 판정 뒤 다시 쓰기
    "ground/answer_fast": "verify",          # 같은 다시 쓰기의 빠른 답
}
STAGES = ("search", "plan", "generate", "verify")
LABEL = {"search": "검색", "plan": "판단(분류·분해·재작성·근거 충분 판정)", "generate": "생성(답 작성)", "verify": "검증(근거 판정·다시 쓰기)"}
SEARCH_PARTS = ("translate", "embed", "vector", "link", "total")


def pct(values: list[float], q: float) -> float | None:
    """최근순위 백분위. q=0.95는 `run_eval._p95`와 같다."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def load_rows(run: Path, arm: str) -> list[dict]:
    with open(run / arm / "rows.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def row_stages(row: dict, prices: dict) -> dict:
    """한 행의 단계별 시간(초)·비용·토큰. 단계가 없던 행은 시간 None, 비용 0."""
    sec = {s: None for s in STAGES}
    cost = {s: 0.0 for s in STAGES}
    tok = {"input": 0, "output": 0}
    stok = {s: [0, 0] for s in STAGES}   # 단계별 (입력, 출력) 토큰
    src = {"reported": 0, "price_table": 0}
    calls = row.get("retrieval_calls") or []
    if calls:
        sec["search"] = sum(c["wall_s"] for c in calls)
    llm_s = 0.0
    for c in row.get("llm_trace") or []:
        stage = STEP_STAGE.get(c["step"])
        if stage is None:
            raise SystemExit(f"단계 표에 없는 LLM step: {c['step']} (문항 {row['id']})")
        i, o = int(c.get("input_tokens") or 0), int(c.get("output_tokens") or 0)
        rep = c.get("reported_cost_usd")   # 공급자가 알려 준 비용이 있으면 그 값(캐시 할인 반영), 없으면 단가표 추정
        cost[stage] += rep if rep is not None else cost_usd(c.get("model"), i, o, prices)
        src["reported" if rep is not None else "price_table"] += 1
        tok["input"] += i
        tok["output"] += o
        stok[stage][0] += i
        stok[stage][1] += o
        if stage != "search":
            sec[stage] = (sec[stage] or 0.0) + float(c["seconds"] or 0.0)
            llm_s += float(c["seconds"] or 0.0)
    residual = row["latency_s"] - (sec["search"] or 0.0) - llm_s
    return {"sec": sec, "cost": cost, "tok": tok, "stok": stok, "src": src, "residual": residual, "cost_diff": abs(sum(cost.values()) - (row.get("cost_usd") or 0.0))}


def summarize(rows: list[dict], prices: dict) -> dict:
    per = [row_stages(r, prices) for r in rows]
    n = len(rows)
    out: dict = {"n": n, "stages": {}}
    for s in STAGES:
        vals = [p["sec"][s] for p in per if p["sec"][s] is not None]
        out["stages"][s] = {"n": len(vals), "p50": pct(vals, 0.5), "p95": pct(vals, 0.95), "cost_per_request": sum(p["cost"][s] for p in per) / n,
                            "input_tokens_per_request": sum(p["stok"][s][0] for p in per) / n, "output_tokens_per_request": sum(p["stok"][s][1] for p in per) / n}
    lat = [r["latency_s"] for r in rows]
    for st in STAGES:   # 전체 시간 합 중 이 단계의 몫. 판단·생성·검증은 LLM 시간이고 검색은 검색 호출 시간이다
        out["stages"][st]["time_share"] = sum(p["sec"][st] or 0.0 for p in per) / sum(lat)
    out["total"] = {"n": n, "p50": pct(lat, 0.5), "p95": _p95(lat), "cost_per_request": sum(sum(p["cost"].values()) for p in per) / n,
                    "cost_sum": sum(sum(p["cost"].values()) for p in per), "recorded_cost_sum": sum(r.get("cost_usd") or 0.0 for r in rows),
                    "input_tokens_per_request": sum(p["tok"]["input"] for p in per) / n, "output_tokens_per_request": sum(p["tok"]["output"] for p in per) / n}
    res = sorted(p["residual"] for p in per)
    out["residual_s"] = {"p50": pct(res, 0.5), "min": res[0], "max": res[-1]}
    out["max_cost_diff_vs_row"] = max(p["cost_diff"] for p in per)
    out["cost_source_calls"] = {k: sum(p["src"][k] for p in per) for k in ("reported", "price_table")}
    calls = [c for r in rows for c in (r.get("retrieval_calls") or []) if c.get("trace")]
    out["search_parts_ms"] = {"n_calls": len(calls), **{k: {"p50": pct([c["trace"]["ms"].get(k, 0.0) for c in calls], 0.5),
                                                           "p95": pct([c["trace"]["ms"].get(k, 0.0) for c in calls], 0.95)} for k in SEARCH_PARTS}}
    out["search_parts_ms"]["translation_source"] = _count(c["trace"].get("translation_source") for c in calls)
    out["search_parts_ms"]["rerank_model"] = _count(c["trace"].get("rerank_model") for c in calls)
    steps: dict = {}
    for r in rows:
        for c in r.get("llm_trace") or []:
            steps.setdefault(c["step"], []).append(c)
    out["llm_steps"] = {k: {"calls": len(v), "seconds_sum": sum(float(c["seconds"] or 0) for c in v), "p50_s": pct([float(c["seconds"] or 0) for c in v], 0.5),
                            "p95_s": pct([float(c["seconds"] or 0) for c in v], 0.95), "output_tokens_mean": sum(int(c.get("output_tokens") or 0) for c in v) / len(v),
                            "input_tokens_mean": sum(int(c.get("input_tokens") or 0) for c in v) / len(v)} for k, v in sorted(steps.items())}
    # 평균이 아니라 개별 요청: 가장 느린 5건이 어느 단계에서 시간을 썼나(강의 rag 3주 11강 "이 요청이 왜 비쌌는지")
    slow = sorted(range(n), key=lambda k: -rows[k]["latency_s"])[:5]
    out["slowest"] = [{"run": rows[k].get("_run", ""), "id": rows[k]["id"], "latency_s": rows[k]["latency_s"],
                       **{s: per[k]["sec"][s] for s in STAGES}, "llm_calls": len(rows[k].get("llm_trace") or []),
                       "search_calls": len(rows[k].get("retrieval_calls") or []), "result": rows[k].get("result")} for k in slow]
    return out


def _count(values) -> dict:
    d: dict = {}
    for v in values:
        d[str(v)] = d.get(str(v), 0) + 1
    return d


def check_runs(runs: list[Path]) -> list[dict]:
    """회차·경로마다 전체 p95를 다시 세어 `summary.json`의 `latency_p95_s`와 비교한다. 다르면 멈춘다."""
    out = []
    for run in runs:
        for arm in ARMS:
            rows = load_rows(run, arm)
            mine = _p95([r["latency_s"] for r in rows])
            stored = json.loads((run / arm / "summary.json").read_text(encoding="utf-8"))["metrics"]["latency_p95_s"]
            ok = round(mine, 3) == round(stored, 3)
            out.append({"run": run.name, "arm": arm, "n": len(rows), "p95_recount": mine, "p95_summary": stored, "same": ok})
            if not ok:
                raise SystemExit(f"전체 p95가 summary.json과 다르다: {run.name}/{arm} {mine} != {stored}")
    return out


def _f(x: float | None, nd: int = 2) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def render(report: dict) -> str:
    s, m = report["arms"]["single"], report["arms"]["multi"]
    lines = [f"단계별 (단일 {s['n']}건, 괄호는 멀티 {m['n']}건). 시간은 초, 비용은 달러/요청(그 단계가 없던 요청은 0으로 넣은 평균)", "",
             "| 단계 | n | p50 | p95 | 요청당 비용 |", "|---|---|---|---|---|"]
    for st in STAGES:
        a, b = s["stages"][st], m["stages"][st]
        lines.append(f"| {LABEL[st]} | {a['n']} ({b['n']}) | {_f(a['p50'])} ({_f(b['p50'])}) | {_f(a['p95'])} ({_f(b['p95'])}) | "
                     f"{a['cost_per_request']:.6f} ({b['cost_per_request']:.6f}) |")
    a, b = s["total"], m["total"]
    lines.append(f"| 전체 | {a['n']} ({b['n']}) | {_f(a['p50'])} ({_f(b['p50'])}) | {_f(a['p95'])} ({_f(b['p95'])}) | "
                 f"{a['cost_per_request']:.6f} ({b['cost_per_request']:.6f}) |")
    lines.append("\n전체 시간 합 중 몫(단일 / 멀티): " + ", ".join(f"{LABEL[st].split('(')[0]} {s['stages'][st]['time_share']:.1%} / {m['stages'][st]['time_share']:.1%}" for st in STAGES))
    fs, fm = report["arms_skip_first"]["single"], report["arms_skip_first"]["multi"]
    lines.append(f"회차마다 첫 요청을 뺀 값(SPEC 48줄 조건, 단일 / 멀티): 검색 p95 {_f(fs['stages']['search']['p95'])} / {_f(fm['stages']['search']['p95'])}, "
                 f"전체 p95 {_f(fs['total']['p95'])} / {_f(fm['total']['p95'])} (n {fs['total']['n']} / {fm['total']['n']})")
    lines += ["", "| 값 | 단일 | 멀티 |", "|---|---|---|"]
    for key, lab in (("input_tokens_per_request", "입력 토큰/요청"), ("output_tokens_per_request", "출력 토큰/요청"), ("cost_sum", "비용 합(단가표)"),
                     ("recorded_cost_sum", "비용 합(행의 cost_usd)")):
        lines.append(f"| {lab} | {a[key]:.6f} | {b[key]:.6f} |" if "cost" in key else f"| {lab} | {a[key]:.1f} | {b[key]:.1f} |")
    lines.append(f"| 행 비용과 이 계산의 최대 차이 | {s['max_cost_diff_vs_row']:.6f} | {m['max_cost_diff_vs_row']:.6f} |")
    lines.append(f"| 비용 출처: 공급자 보고 / 단가표 추정 (호출 수) | {s['cost_source_calls']['reported']} / {s['cost_source_calls']['price_table']} | "
                 f"{m['cost_source_calls']['reported']} / {m['cost_source_calls']['price_table']} |")
    lines.append(f"| 전체 - (검색 + LLM) p50 / 최소 / 최대 (초) | {_f(s['residual_s']['p50'], 3)} / {_f(s['residual_s']['min'], 3)} / {_f(s['residual_s']['max'], 3)} | "
                 f"{_f(m['residual_s']['p50'], 3)} / {_f(m['residual_s']['min'], 3)} / {_f(m['residual_s']['max'], 3)} |")
    lines += ["", f"검색 호출 하나의 안쪽 (ms, 호출 단일 {s['search_parts_ms']['n_calls']}번, 멀티 {m['search_parts_ms']['n_calls']}번)", "",
              "| 검색 안 단계 | 단일 p50 | 단일 p95 | 멀티 p50 | 멀티 p95 |", "|---|---|---|---|---|"]
    for k in SEARCH_PARTS:
        lines.append(f"| {k} | {_f(s['search_parts_ms'][k]['p50'], 1)} | {_f(s['search_parts_ms'][k]['p95'], 1)} | "
                     f"{_f(m['search_parts_ms'][k]['p50'], 1)} | {_f(m['search_parts_ms'][k]['p95'], 1)} |")
    lines.append(f"\n번역 출처(단일): {s['search_parts_ms']['translation_source']} / 리랭커: {s['search_parts_ms']['rerank_model']}")
    lines += ["", "회차별 전체 p95 (다시 센 값 = summary.json latency_p95_s)", "", "| 회차 | 경로 | n | 다시 센 p95 | summary.json | 같음 |", "|---|---|---|---|---|---|"]
    for c in report["checks"]:
        lines.append(f"| {c['run']} | {c['arm']} | {c['n']} | {c['p95_recount']:.3f} | {c['p95_summary']:.3f} | {c['same']} |")
    for name, per in report["per_run"].items():
        lines.append(f"\n{name}: " + ", ".join(f"{arm} p50 {_f(v['p50'])} p95 {_f(v['p95'])}" for arm, v in per.items()))
    lines += ["", "단계별 토큰/요청 (입력 / 출력, 단일)", "", "| 단계 | 입력 | 출력 |", "|---|---|---|"]
    for st in STAGES:
        lines.append(f"| {LABEL[st]} | {s['stages'][st]['input_tokens_per_request']:.0f} | {s['stages'][st]['output_tokens_per_request']:.0f} |")
    lines += ["", "LLM step별 (단일, 호출 하나 기준)", "", "| step | 단계 | 호출 수 | 시간 합(초) | p50 | p95 | 입력 토큰 평균 | 출력 토큰 평균 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in sorted(s["llm_steps"].items(), key=lambda kv: -kv[1]["seconds_sum"]):
        lines.append(f"| {k} | {STEP_STAGE[k]} | {v['calls']} | {v['seconds_sum']:.1f} | {_f(v['p50_s'])} | {_f(v['p95_s'])} | {v['input_tokens_mean']:.0f} | {v['output_tokens_mean']:.0f} |")
    for arm in ARMS:
        lines += ["", f"가장 느린 5건 ({arm}, 초)", "", "| 회차 | 문항 | 결과 | 전체 | 검색 | 판단 | 생성 | 검증 | LLM 호출 | 검색 호출 |", "|---|---|---|---|---|---|---|---|---|---|"]
        for x in report["arms"][arm]["slowest"]:
            lines.append(f"| {x['run']} | {x['id']} | {x['result']} | {x['latency_s']:.2f} | {_f(x['search'])} | {_f(x['plan'])} | {_f(x['generate'])} | {_f(x['verify'])} | "
                         f"{x['llm_calls']} | {x['search_calls']} |")
    lines += ["", "무엇으로 잰 숫자인가 (summary.json meta)", ""]
    for mw in report["measured_with"]:
        lines.append(f"- {mw['run']}: {mw['run_id']} 끝 {mw['finished']}, {mw['dataset']} {str(mw['dataset_sha256'])[:12]}, {mw['store']}, "
                     f"LLM {mw['llm'].get('provider') if mw['llm'] else None}/{mw['llm'].get('model') if mw['llm'] else None}, 검색 {mw['search']}")
    return "\n".join(lines)


def measured_with(runs: list[Path]) -> list[dict]:
    """무엇으로 잰 숫자인가(원칙집 0장 12번): 회차마다 summary.json의 실행 번호, 끝난 시각, 평가셋 해시, LLM, 검색 설정."""
    out = []
    for run in runs:
        meta = json.loads((run / "single" / "summary.json").read_text(encoding="utf-8"))["meta"]
        out.append({"run": run.name, **{k: meta.get(k) for k in ("run_id", "finished", "dataset", "dataset_sha256", "store", "llm")},
                    "search": (meta.get("search") or {}).get("config")})
    return out


def build_report(runs: list[Path]) -> dict:
    prices = load_prices()
    checks = check_runs(runs)
    arms = {arm: summarize([{**r, "_run": run.name} for run in runs for r in load_rows(run, arm)], prices) for arm in ARMS}
    skip = {arm: summarize([r for run in runs for r in load_rows(run, arm)[1:]], prices) for arm in ARMS}   # 행은 실행 순서로 쌓인다
    per_run = {run.name: {arm: summarize(load_rows(run, arm), prices)["total"] for arm in ARMS} for run in runs}
    return {"runs": [str(r.relative_to(ROOT)).replace("\\", "/") if r.is_relative_to(ROOT) else str(r) for r in runs],
            "measured_with": measured_with(runs), "prices": prices, "arms": arms, "arms_skip_first": skip, "checks": checks, "per_run": per_run}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs="+", default=DEFAULT_RUNS)
    ap.add_argument("--json", help="결과를 JSON으로도 쓴다")
    args = ap.parse_args(argv)
    runs = [p if p.is_absolute() else ROOT / p for p in map(Path, args.runs)]
    report = build_report(runs)
    print(render(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
