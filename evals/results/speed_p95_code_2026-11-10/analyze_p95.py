"""62.20 결과 집계: 모든 숫자를 rows.jsonl에서 다시 센다(compute_metrics 재계산, summary.json과 대조)."""
import json, math, statistics as st, sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"<임시 폴더>\pv_speed")
sys.path.insert(0, str(ROOT))
from evals.agent.run_eval import compute_metrics, _p95  # noqa: E402

OUT = ROOT / "evals" / "results" / "speed_p95_code_2026-11-10"
ARMS = {"a": "a 대조군(서비스 설정)", "b": "b 검색hedge+일찍검색+단계hedge", "c": "c b+답대기 4.0/6.5"}
ANS_WAIT = {"a": (5.5, 8.0), "b": (5.5, 8.0), "c": (4.0, 6.5)}


def rows_of(f):
    return [json.loads(x) for x in (OUT / f / "single" / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def fast_stats(rows, arm):
    """추론 답(answer) 호출과 빠른 답(answer_fast) 경쟁: 추론 답이 성공하고 소요 <= min(대기, 예산-시작)이면 추론 답, 아니면 빠른 답(근사)."""
    wait, budget = ANS_WAIT[arm]
    slow_used = fast_used = 0
    for r in rows:
        for c in r.get("llm_trace") or []:
            if c.get("task") != "answer":
                continue
            eff = min(wait, budget - float(c["start_s"]))
            if c.get("ok") and float(c["seconds"]) <= eff:
                slow_used += 1
            else:
                fast_used += 1
    return slow_used, fast_used


def hedge_stats(rows):
    sp = Counter((r.get("search_stats") or {}).get("speculated") for r in rows)
    sh = Counter()
    n = 0
    for r in rows:
        s = r.get("search_stats") or {}
        for k, v in s.items():
            if "hedge" in k.lower() and isinstance(v, (int, float)):
                sh[k] += v
        n += s.get("calls") or 0
    return sp, sh, n


def main():
    res = {}
    for arm in "abc":
        runs = []
        pooled = []
        for r in (1, 2, 3):
            f = f"{arm}_r{r}"
            if not (OUT / f / "single" / "rows.jsonl").is_file():
                continue
            rows = rows_of(f)
            m = compute_metrics(rows)
            summ = json.loads((OUT / f / "single" / "summary.json").read_text(encoding="utf-8"))["metrics"]
            lat = [float(x["latency_s"]) for x in rows]
            pooled += lat
            rel = [float(x["latency_s"]) for x in rows if not x["expect_refusal"]]
            import re
            raw = (OUT / f / "single" / "rows.jsonl").read_text(encoding="utf-8")
            sh_true, sh_all = len(re.findall(r'"hedged": true', raw)), len(re.findall(r'"hedged": (?:true|false)', raw))
            so = (OUT / "stdout" / f"{f}.txt").read_text(encoding="utf-8", errors="replace")
            llm_h = {t: len(re.findall(rf"stage={t} ", so)) for t in ("classify", "decompose_gate", "decompose", "judge", "answer", "grounding")}
            su, fu = fast_stats(rows, arm)
            sp, sh, ncalls = hedge_stats(rows)
            runs.append({"folder": f, "n": len(rows), "p50": round(st.median(lat), 3), "p95": round(_p95(lat), 3), "max": round(max(lat), 2),
                         "over10": sum(x >= 10 for x in lat), "rel_p50": round(st.median(rel), 3),
                         "cited_correct": round(m["cited_correct_rate"], 4), "cit_acc": round(m["citation_accuracy"], 4),
                         "corr_refusal": m["correct_refusal_rate"], "over_refusal": round(m["over_refusal_rate"], 4),
                         "hallu": m["hallucination_risk_rate"], "wrong_cit": round(m["wrong_citation_rate"], 4),
                         "errors": m["errors"], "cost": round(sum(float(x.get("cost_usd") or 0) for x in rows), 4),
                         "slow_used": su, "fast_used": fu, "spec": dict(sp), "search_hedged": f"{sh_true}/{sh_all}", "llm_hedge_by_stage": llm_h, "search_calls": ncalls,
                         "summary_match": all(abs((summ.get(k) or 0) - (m.get(k) or 0)) < 1e-9 for k in ("cited_correct_rate", "citation_accuracy", "wrong_citation_rate", "over_refusal_rate"))})
        if runs:
            tot_n = sum(r["n"] for r in runs)
            res[arm] = {"runs": runs, "mean_p95": round(st.mean(r["p95"] for r in runs), 3), "pooled_p95": round(_p95(pooled), 3), "pooled_n": len(pooled),
                        "pooled_over10": sum(x >= 10 for x in pooled), "cost_total": round(sum(r["cost"] for r in runs), 4), "cost_per_q": round(sum(r["cost"] for r in runs) / tot_n, 5),
                        "mean": {k: round(st.mean(r[k] for r in runs), 4) for k in ("cited_correct", "cit_acc", "corr_refusal", "over_refusal", "hallu", "wrong_cit", "p50")},
                        "fast_ratio": round(sum(r["fast_used"] for r in runs) / max(1, sum(r["fast_used"] + r["slow_used"] for r in runs)), 3)}
    (OUT / "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for arm, a in res.items():
        print(f"== {ARMS[arm]}  회차p95평균 {a['mean_p95']}  합침p95 {a['pooled_p95']} ({a['pooled_n']}행)  10초이상 {a['pooled_over10']}  비용 {a['cost_total']} (요청당 {a['cost_per_q']})  빠른답대체 {a['fast_ratio']}")
        print("   평균", a["mean"])
        for r in a["runs"]:
            print("  ", r)


if __name__ == "__main__":
    main()
