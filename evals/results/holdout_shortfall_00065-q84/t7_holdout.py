"""검증 20건(관련 10문항) 최종 판 00065-q84 부족분 근거 정리(0원, 저장된 파일만).
입력: scratchpad/ana/per_q.json(per_q.py가 운영 Langfuse 첫 검색 상위 5개·행 기록으로 만든 문항별 값), 커밋된 rows.jsonl, citation_gold.json."""
import json, os, glob, math, statistics, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ANA = os.path.join(os.path.dirname(HERE), "ana")
S = os.path.join(HERE, "src", "evals", "results")
pq = json.load(open(os.path.join(ANA, "per_q.json"), encoding="utf-8"))
out = {}
for name in ("v2", "holdout"):
    rs = pq[name]
    by_q = collections.defaultdict(list)
    for r in rs: by_q[r["id"]].append(r)
    agg = {k: statistics.mean([r[k] for r in rs if r.get(k) is not None]) for k in ("recall5", "rr", "ndcg5", "ctx_recall", "cited_recall")}
    agg["n_rows"] = len(rs)
    agg["per_run_recall5"] = {n: statistics.mean([r["recall5"] for r in rs if r["run"] == n]) for n in (1, 2, 3)}
    agg["per_q"] = {q: {"recall5": [r["recall5"] for r in sorted(v, key=lambda r: r["run"])], "ctx_recall": [r["ctx_recall"] for r in sorted(v, key=lambda r: r["run"])],
                        "n_sub": [r["n_sub"] for r in sorted(v, key=lambda r: r["run"])], "ctx_len": [r["ctx_len"] for r in sorted(v, key=lambda r: r["run"])],
                        "gold": [f"{r['gold_hit']}/{r['gold_total']}+{r['cited_off_gold']}" for r in sorted(v, key=lambda r: r["run"])],
                        "subs_run1": sorted(v, key=lambda r: r["run"])[0]["subs"]} for q, v in sorted(by_q.items())}
    out[name] = agg
# 응답 시간: 검증 20건 60행, 10초 넘은 행
rows = []
for f in sorted(glob.glob(os.path.join(S, "deploy_latency_holdout_provena-api-00065-q84", "run*", "rows.jsonl"))):
    rows += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
def near(v, p):
    s = sorted(v); return s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))]
slow = []
for r in rows:
    if r["total_s"] > 10:
        p = r.get("path") or {}; g = p.get("grounding") or {}
        slow.append({"run": r["run"], "id": r["id"], "kind": r["dataset_kind"], "result": r["result"], "total_s": r["total_s"], "llm_calls": r.get("llm_calls"),
                     "ground_llm": g.get("llm"), "redraft": g.get("redraft"), "revised": g.get("revised"), "rejudge": g.get("rejudge"), "switch_failed": g.get("switch_failed"),
                     "timing": p.get("timing")})
ans = [r["total_s"] for r in rows if r["result"] == "answer"]
out["holdout_latency"] = {"n": len(rows), "p95_all_nearest": near([r["total_s"] for r in rows], 95), "p95_answered_nearest": near(ans, 95),
                          "per_run_p95": {n: near([r["total_s"] for r in rows if r["run"] == n], 95) for n in (1, 2, 3)},
                          "rows_over_10s": slow}
json.dump(out, open(os.path.join(HERE, "out", "holdout_shortfall.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
h = out["holdout"]
print("holdout", {k: round(v, 4) for k, v in h.items() if isinstance(v, float)}, h["per_run_recall5"])
print("v2", {k: round(v, 4) for k, v in out["v2"].items() if isinstance(v, float)})
for q, v in h["per_q"].items(): print(q, v["recall5"], v["ctx_recall"], v["n_sub"], v["ctx_len"], v["gold"])
print(json.dumps(out["holdout_latency"], ensure_ascii=False)[:1500])
