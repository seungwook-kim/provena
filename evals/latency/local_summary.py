"""로컬 측정 갈래(끔, 켬 등)의 회차 결과 폴더를 묶어 표 하나로 만든다. 새로 호출하지 않고 저장된 `rows.jsonl`과 `summary.json`만 읽는다(사전 등록 62.8, 62.10).

갈래는 `이름=폴더1,폴더2,...` 인자로 준다(폴더는 `<결과 폴더>/single/rows.jsonl`을 가진다). 숫자는 모두 행에서 다시 센다.
- 응답 시간: 행의 `latency_s`. 회차 p95는 최근순위(ceil(0.95n)번째), 3회 평균은 회차별 p95의 평균, 합침 p95는 모든 행을 합쳐 센 값이다.
- 품질: 각 회차 `summary.json`의 `metrics`(정답 근거 인용률 `cited_correct_rate`, 인용 정확도 `citation_accuracy`, 비관련 거절 `correct_refusal_rate`, 과잉 거절 `over_refusal_rate`, 환각 위험 `hallucination_risk_rate`)의 회차 평균.
- 비용: 행의 `cost_usd` 합(`llm_trace` 호출 비용 기록. 질문이 끝난 뒤에 끝난 미리 부른 호출은 빠질 수 있다).
- `ground_ahead`: 관련 문항 행 가운데 미리 부른 근거 판정을 쓴 행 수(`grounding.ground_ahead`).

사용: python -m evals.latency.local_summary 끔=폴더1,폴더2 켬=폴더3,폴더4 --out 폴더/summary.json --md 폴더/summary.md
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

from evals.agent.run_eval import _p95

METRICS = ("cited_correct_rate", "citation_accuracy", "correct_refusal_rate", "over_refusal_rate", "hallucination_risk_rate")


def rows_of(folder: Path) -> list[dict]:
    return [json.loads(x) for x in (folder / "single" / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def metrics_of(folder: Path) -> dict:
    return json.loads((folder / "single" / "summary.json").read_text(encoding="utf-8"))["metrics"]


def arm(name: str, folders: list[Path]) -> dict:
    runs = []
    pooled: list[float] = []
    pooled_rel: list[float] = []
    for f in folders:
        rows = rows_of(f)
        lat = [float(r["latency_s"]) for r in rows]
        rel = [float(r["latency_s"]) for r in rows if r["kind"] == "relevant"]
        irr = [float(r["latency_s"]) for r in rows if r["kind"] != "relevant"]
        pooled += lat
        pooled_rel += rel
        m = metrics_of(f)
        runs.append({"folder": f.name, "n": len(rows), "p50": round(st.median(lat), 3), "p95": round(_p95(lat), 3), "max": round(max(lat), 3),
                     "relevant_p50": round(st.median(rel), 3), "irrelevant_p50": round(st.median(irr), 3),
                     "over_10s": sum(1 for x in lat if x >= 10),
                     "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
                     "ground_ahead_rows": sum(1 for r in rows if r["kind"] == "relevant" and (r.get("grounding") or {}).get("ground_ahead")),
                     "metrics": {k: (round(m[k], 4) if m.get(k) is not None else None) for k in METRICS},
                     "errors": m.get("errors")})
    mean_p95 = st.mean(r["p95"] for r in runs)
    return {"arm": name, "runs": runs, "mean_run_p95": round(mean_p95, 3), "pooled_p95": round(_p95(pooled), 3), "pooled_n": len(pooled),
            "pooled_over_10s": sum(1 for x in pooled if x >= 10), "pooled_relevant_p50": round(st.median(pooled_rel), 3),
            "mean_cost_per_question_usd": round(sum(r["cost_usd"] for r in runs) / sum(r["n"] for r in runs), 5),
            "mean_metrics": {k: round(st.mean(r["metrics"][k] for r in runs), 4) for k in METRICS}}


def to_md(arms: list[dict]) -> str:
    out = ["| 갈래 | 회차 | p50 | p95 | 최대 | 관련 p50 | 10초 이상 행 | 정답 근거 | 인용 정확도 | 비관련 거절 | 과잉 거절 | 환각 위험 | 비용(달러) | 미리 부른 판정 사용 행 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        for i, r in enumerate(a["runs"], 1):
            m = r["metrics"]
            out.append(f"| {a['arm']} | {i} ({r['folder']}) | {r['p50']} | {r['p95']} | {r['max']} | {r['relevant_p50']} | {r['over_10s']} | {m['cited_correct_rate']} | {m['citation_accuracy']} | "
                       f"{m['correct_refusal_rate']} | {m['over_refusal_rate']} | {m['hallucination_risk_rate']} | {r['cost_usd']} | {r['ground_ahead_rows']}/25 |")
        mm = a["mean_metrics"]
        out.append(f"| **{a['arm']} 평균** | {len(a['runs'])}회 | | 회차 p95 평균 {a['mean_run_p95']}, 합침 p95 {a['pooled_p95']} | | {a['pooled_relevant_p50']} | {a['pooled_over_10s']}/{a['pooled_n']} | "
                   f"{mm['cited_correct_rate']} | {mm['citation_accuracy']} | {mm['correct_refusal_rate']} | {mm['over_refusal_rate']} | {mm['hallucination_risk_rate']} | 요청당 {a['mean_cost_per_question_usd']} | |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("arms", nargs="+", help="이름=폴더1,폴더2")
    p.add_argument("--out")
    p.add_argument("--md")
    args = p.parse_args(argv)
    arms = []
    for spec in args.arms:
        name, _, folders = spec.partition("=")
        arms.append(arm(name, [Path(x) for x in folders.split(",") if x]))
    md = to_md(arms)
    print(md)
    if args.out:
        Path(args.out).write_text(json.dumps(arms, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
