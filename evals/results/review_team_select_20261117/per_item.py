import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from evals.agent import exp_review_v1 as E
items = {str(it["id"]): it for it in E.load_review_dataset(Path("evals/dataset_review_v1_gold.jsonl"))}
rows = [json.loads(l) for l in Path("evals/results/review_team_select_20261117/team/rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
base = [json.loads(l) for l in Path("evals/results/review_deploy_provena-api-00049-nph/team/rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
local = [json.loads(l) for l in Path("evals/results/review_v1_team_vs_single_62_36/team/rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out = []
tot_unsel = 0
for r in rows:
    it = items[str(r["id"])]
    gold_teams = sorted({t for t, _, _ in it["_gold"]}, key=E.T.TEAM_IDS.index)
    sel = r["selected_teams"]
    m = r["gold_match"]
    unsel_missed = sum(1 for d in (m["detail"] if m else []) if not d["found"] and d["team"] not in sel)
    tot_unsel += unsel_missed
    def found_of(rs):
        vals = [E.match_gold(it, x.get("issue_rows") or [])["found"] for x in rs if str(x["id"]) == str(r["id"])]
        return vals
    b = found_of(base) if m else []
    lo = found_of(local) if m else []
    out.append({"id": r["id"], "kind": it["kind"], "gold_teams": gold_teams, "selected": sel, "status": r["status"],
                "found": m["found"] if m else None, "total": m["total"] if m else None, "missed_unselected": unsel_missed,
                "base00049_found_3runs": b, "local6236_found_3runs": lo, "cost": r["cost_usd"], "llm_calls": r["llm_calls"]})
for o in out: print(json.dumps(o, ensure_ascii=False))
print("missed_due_to_unselected", tot_unsel)
bt = [E.match_gold(items[str(x["id"])], x.get("issue_rows") or []) for x in base if E.judged_state(items[str(x["id"])]) == "ready"]
print("base00049 confirmed", sum(m["found"] for m in bt), sum(m["total"] for m in bt))
lt = [E.match_gold(items[str(x["id"])], x.get("issue_rows") or []) for x in local if E.judged_state(items[str(x["id"])]) == "ready"]
print("local6236 confirmed", sum(m["found"] for m in lt), sum(m["total"] for m in lt))
Path("evals/results/review_team_select_20261117/per_item.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

