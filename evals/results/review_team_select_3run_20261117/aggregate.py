"""6회 결과를 모아 `aggregate.json`을 만든다(0원 계산, 모델 호출 없음).

    .venv\\Scripts\\python.exe evals/results/review_team_select_3run_20261117/aggregate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from evals.agent import exp_review_v1 as E  # noqa: E402

ORDER = [("on", 1), ("off", 1), ("on", 2), ("off", 2), ("on", 3), ("off", 3)]
items = {str(it["id"]): it for it in E.load_review_dataset(ROOT / "evals" / "dataset_review_v1_gold.jsonl")}


def load(cfg: str, n: int):
    d = OUT / f"run{n}_{cfg}"
    rows = [json.loads(x) for x in (d / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    return rows, s


runs, per_item = [], {}
for cfg, n in ORDER:
    rows, s = load(cfg, n)
    m, meta = s["metrics"], s["meta"]
    unsel, false_clarify, false_clarify_missed = 0, [], 0
    for r in rows:
        it = items[str(r["id"])]
        g = E.match_gold(it, r["issue_rows"]) if E.judged_state(it) == "ready" else None
        # 되물어 팀이 아예 돌지 않은 런은 팀 선택 때문이 아니므로 따로 센다(`false_clarify_ids`)
        miss_unsel = 0 if r["status"] == "clarify" else sum(
            1 for d in (g["detail"] if g else []) if not d["found"] and d["team"] not in r["selected_teams"])
        unsel += miss_unsel
        if g and r["status"] == "clarify":
            false_clarify.append(r["id"])
            false_clarify_missed += g["total"] - g["found"]
        e = per_item.setdefault(str(r["id"]), {"id": r["id"], "kind": it["kind"],
                                               "gold_teams": sorted({t for t, _, _ in it["_gold"]}, key=E.T.TEAM_IDS.index) if g else [],
                                               "total": g["total"] if g else None, "on": [], "off": []})
        e[cfg].append({"run": n, "status": r["status"], "selected": r["selected_teams"], "found": g["found"] if g else None,
                       "missed_unselected": miss_unsel, "llm_calls": r["llm_calls"], "cost": r["cost_usd"], "latency_s": r["latency_s"]})
    runs.append({"config": cfg, "run": n, "started": meta["started"], "finished": meta["finished"], "found": m["gold_found"],
                 "total": m["gold_total"], "miss_rate": m["missed_issue_rate"], "cost_usd": m["cost_usd"], "cost_usd_mean": m["cost_usd_mean"],
                 "latency_mean_s": m["latency_mean_s"], "latency_p95_s": m["latency_p95_s"], "llm_calls_mean": m["llm_calls_mean"],
                 "errors": m["errors"], "clarify_asked": m["clarify_asked"], "false_clarify_rate": m["false_clarify_rate"],
                 "pre_approval_saved": m["pre_approval_saved"], "unreviewed_team_slots": m["unreviewed_team_slots"],
                 "missed_due_to_unselected": unsel, "false_clarify_ids": false_clarify, "missed_due_to_false_clarify": false_clarify_missed,
                 "stopped_by_budget": meta["stopped_by_budget"]})


def stat(cfg: str, key: str) -> dict:
    v = [r[key] for r in runs if r["config"] == cfg]
    return {"mean": sum(v) / len(v), "min": min(v), "max": max(v), "values": v}


summary = {c: {k: stat(c, k) for k in ("miss_rate", "found", "cost_usd", "cost_usd_mean", "latency_mean_s", "latency_p95_s", "llm_calls_mean",
                                        "missed_due_to_unselected")} for c in ("on", "off")}
diff = summary["on"]["miss_rate"]["mean"] - summary["off"]["miss_rate"]["mean"]
out = {"runs": runs, "summary": summary, "miss_rate_on_minus_off": diff,
       "stop_rule_triggered": diff > 0.05, "total_cost_usd": sum(r["cost_usd"] for r in runs),
       "per_item": [per_item[k] for k in sorted(per_item, key=int)]}
(OUT / "aggregate.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
for r in runs:
    print(json.dumps({k: r[k] for k in ("config", "run", "found", "total", "miss_rate", "cost_usd", "latency_mean_s", "latency_p95_s",
                                         "llm_calls_mean", "missed_due_to_unselected", "false_clarify_ids", "missed_due_to_false_clarify", "errors")}, ensure_ascii=False))
for c in ("on", "off"):
    print(c, {k: (round(v["mean"], 5), v["min"], v["max"]) for k, v in summary[c].items()})
print("diff", round(diff, 4), "stop_rule", diff > 0.05, "total_cost", round(out["total_cost_usd"], 5))
for e in out["per_item"]:
    print(e["id"], e["kind"], e["gold_teams"], e["total"], "ON", [(x["selected"], x["found"], x["missed_unselected"]) for x in e["on"]],
          "OFF", [x["found"] for x in e["off"]])
