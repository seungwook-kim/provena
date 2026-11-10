"""로컬 측정 결과(`evals/agent/exp_multi_v2.py run`의 `<폴더>/single/rows.jsonl`)에서 응답 시간의 단계별 구성을 다시 센다. 새로 호출하지 않고 비용도 들지 않는다.

행의 `llm_trace[]`(`step`, `start_s`, `seconds`)와 `latency_s`로 질문 한 건의 시간을 다섯 구간으로 나눈다.
- 준비: 0초부터 첫 판정·답 호출이 시작될 때까지(분류, 분해, 첫 검색). 첫 `judge/judge` 호출의 시작 시각.
- 판정·답: 첫 판정 호출 시작부터 `ground/grounding`(근거 판정) 첫 호출 시작까지. 판정 3표와 답(추론 답, 빠른 답, 둘째 답)을 기다리는 구간이며 재검색이 있으면 그 판정까지 들어 있다.
- 근거 판정 뒤: 근거 판정 첫 호출 시작부터 끝까지(`latency_s` - 근거 판정 시작).
- 근거 판정을 거치지 않은 행(거절, 되묻기)은 `judge` 호출이 있으면 끝 시각까지를 판정·답으로 센다.
회차 p95는 `run_eval._p95`와 같은 최근순위(ceil(0.95n)번째)다.

사용: python -m evals.latency.local_stages <결과 폴더> [<결과 폴더> ...] [--json 파일]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

from evals.agent.run_eval import _p95


def load(folder: Path) -> list[dict]:
    path = folder / "single" / "rows.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def stages(row: dict) -> dict:
    trace = sorted(row.get("llm_trace") or [], key=lambda c: c["start_s"])
    judges = [c for c in trace if c["step"] == "judge/judge"]
    grounds = [c for c in trace if c["step"] == "ground/grounding"]
    total = float(row["latency_s"])
    ground_start = min((c["start_s"] for c in grounds), default=None)
    prep = min((c["start_s"] for c in judges), default=None)
    out = {"id": row["id"], "kind": row["kind"], "result": row["result"], "total": total, "llm_calls": len(trace),
           "ground_ahead": bool((row.get("grounding") or {}).get("ground_ahead")), "judge_rounds": len({round(c["start_s"], 0) for c in judges if c["start_s"] > 0}) if judges else 0}
    if prep is not None:
        out["prep"] = prep
        if ground_start is not None:
            out["judge_answer"] = ground_start - prep
            out["after_judge"] = total - ground_start
        else:
            out["judge_answer"] = total - prep
            out["after_judge"] = 0.0
    return out


def summarize(folder: Path) -> dict:
    rows = [stages(r) for r in load(folder)]
    totals = [r["total"] for r in rows]
    rel = [r for r in rows if r["kind"] == "relevant"]

    def q(values: list[float], f) -> float | None:
        return round(f(values), 3) if values else None

    out = {"folder": folder.name, "rows": len(rows), "p50": q(totals, st.median), "p95": q(totals, _p95), "max": max(totals),
           "relevant": len(rel), "relevant_p50": q([r["total"] for r in rel], st.median), "relevant_p95": q([r["total"] for r in rel], _p95)}
    for key in ("prep", "judge_answer", "after_judge"):
        vals = [r[key] for r in rel if key in r]
        out[f"relevant_{key}_p50"], out[f"relevant_{key}_p95"] = q(vals, st.median), q(vals, _p95)
    out["relevant_ground_ahead_rows"] = sum(1 for r in rel if r["ground_ahead"])
    out["over_10s"] = sorted(((r["id"], round(r["total"], 2)) for r in rows if r["total"] >= 10), key=lambda x: -x[1])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folders", nargs="+")
    p.add_argument("--json")
    args = p.parse_args(argv)
    result = [summarize(Path(f)) for f in args.folders]
    for r in result:
        print(json.dumps(r, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
