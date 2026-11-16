"""00065-q84 v2 150행의 단계별 비용 표(서버 집계 done.cost_by_step)를 summary.json과 rows.jsonl에서 다시 센다(0원)."""
import json, os, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "src", "evals", "results", "deploy_latency_provena-api-00065-q84")
summ = json.load(open(os.path.join(D, "summary.json"), encoding="utf-8"))
cbs = summ["all_runs"]["cost_by_step"]
rows = []
for f in sorted(glob.glob(os.path.join(D, "run*", "rows.jsonl"))):
    rows += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
n = len(rows)
# rows.jsonl에서 다시 합쳐 summary와 대조
agg = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    for k, v in (r.get("cost_by_step") or {}).items():
        agg[k]["calls"] += v.get("calls", 0); agg[k]["in"] += v.get("input_tokens", 0); agg[k]["out"] += v.get("output_tokens", 0)
        agg[k]["cost"] += v.get("cost_usd", 0.0); agg[k]["llm_s"] += v.get("llm_s", 0.0)
lines = ["| 단계 | 요청당 호출 | 호출 수 | 입력 토큰 | 출력 토큰 | 요청당 비용(달러) | 비용 합(달러) | LLM 호출 시간 합(초, 겹침 포함) |", "|---|---|---|---|---|---|---|---|"]
for k, v in sorted(cbs.items(), key=lambda kv: -kv[1]["cost_usd"]):
    a = agg[k]
    assert a["calls"] == v["calls"] and a["in"] == v["input_tokens"] and abs(a["cost"] - v["cost_usd"]) < 1e-6, k
    lines.append(f"| {k} | {v['calls'] / n:.2f} | {v['calls']:,} | {v['input_tokens']:,} | {v['output_tokens']:,} | {v['cost_usd'] / n:.6f} | {v['cost_usd']:.6f} | {v['llm_s']:.1f} |")
tot = sum(r.get("cost_usd") or 0 for r in rows); calls = sum(r.get("llm_calls") or 0 for r in rows)
emb = sum(r.get("embed_tokens") or 0 for r in rows)
ref = collections.Counter(f"{r.get('refuse_stage')}/{r.get('refuse_reason')}" for r in rows if r.get("result") != "answer")
cache = sum((v.get("cache_read_tokens") or 0) for r in rows for v in (r.get("cost_by_step") or {}).values())
print("\n".join(lines))
print(f"rows {n} cost_sum {tot:.4f} per_req {tot / n:.4f} llm_calls {calls} per_req {calls / n:.2f} embed_tokens {emb} cache_read_tokens {cache}")
print(dict(ref))
open(os.path.join(HERE, "out", "cost_by_step_00065.md"), "w", encoding="utf-8").write("\n".join(lines) + f"\n\n행 {n}, 비용 합 {tot:.4f}달러, 요청당 {tot / n:.4f}달러, LLM 호출 {calls}회(요청당 {calls / n:.2f}회), 임베딩 토큰 기록 {emb}, 캐시 읽기 토큰 {cache:,}\n거절·되묻기: {dict(ref)}\n")
