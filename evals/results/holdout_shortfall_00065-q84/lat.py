import json, sys, math
from pathlib import Path
SC = Path(__file__).resolve().parent.parent
rd = SC / "src/evals/results" / sys.argv[1]
print(json.dumps(json.load(open(rd / "summary.json", encoding="utf-8")), ensure_ascii=False)[:1500])
rows = []
for n in (1, 2, 3):
    for l in (rd / f"run{n}" / "rows.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
ans = [r for r in rows if r.get("result") == "answer"]
ts = sorted(r["total_s"] for r in ans)
def pct(v, p):
    k = (len(v) - 1) * p; f = math.floor(k); c = math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)
print("answered n", len(ans), "p50", round(pct(ts, .5), 3), "p95", round(pct(ts, .95), 3), "max", ts[-1])
print("all n", len(rows), "results", {x: sum(1 for r in rows if r.get('result') == x) for x in set(r.get('result') for r in rows)})
for r in sorted(rows, key=lambda r: -r["total_s"])[:14]:
    p = r.get("path") or {}
    jv = p.get("judge_votes") or []
    print(f"run{r['run']} id{r['id']} {r['dataset_kind'][:3]} {r.get('result')} total={r['total_s']} first_tok={r.get('first_token_s')} llm_calls={r.get('llm_calls')} retries={p.get('retries')} subs={len(p.get('sub_queries') or [])} timing={p.get('timing')} judge_rounds={len(jv)} how={[j.get('how') for j in jv]} ground={((p.get('grounding') or {}).get('llm'))} cands={len((p.get('grounding') or {}).get('candidates') or [])}")
    print("     steps:", {k: (v['calls'], v['llm_s']) for k, v in (r.get('cost_by_step') or {}).items()})
