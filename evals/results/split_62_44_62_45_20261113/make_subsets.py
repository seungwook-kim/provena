"""측정안용 부분 평가셋을 만든다(0원, 평가셋 줄을 그대로 골라 담는다). 실행: python make_subsets.py <repo> <out_dir>"""
import hashlib, json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
REPO, OUT = Path(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
R = REPO / "evals/results"
res = json.load(open(OUT.parent / "out" / "result.json", encoding="utf-8"))
PLAN = {
    "widened_v2.jsonl": ("evals/dataset_v2.jsonl", "deploy_latency_", set(res["attribution"]["v2"]["widened"]["ids"])),
    "widened_holdout.jsonl": ("evals/dataset_holdout_v1.jsonl", "deploy_latency_holdout_", set(res["attribution"]["holdout"]["widened"]["ids"])),
    "changed_v2.jsonl": ("evals/dataset_v2.jsonl", "deploy_latency_", {3, 6, 38, 39}),
    "changed_holdout.jsonl": ("evals/dataset_holdout_v1.jsonl", "deploy_latency_holdout_", {101, 104, 109}),
}
for name, (ds, pre, ids) in PLAN.items():
    lines = [l for l in open(REPO / ds, encoding="utf-8", newline="") if l.strip() and json.loads(l)["id"] in ids]
    (OUT / name).write_bytes("".join(lines).encode("utf-8"))
    cost = calls = n = 0
    for run in (1, 2, 3):
        for l in open(R / f"{pre}provena-api-00047-wjn/run{run}/rows.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r["id"] in ids:
                cost += r["cost_usd"]; calls += r["llm_calls"]; n += 1
    print(f"{name}: {len(lines)}문항 {sorted(ids)}, sha256 {hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:12]}, 00047 3회 기준 {n}행 비용 {cost:.4f}달러, LLM 호출 {calls}회")
