"""최종 판 provena-api-00065-q84의 첫 검색 상위 5개로 MRR@5, nDCG@5, 적중@5, 쪽 적중@5, Recall@5를 다시 낸다 (0원, 오프라인, 읽기 전용).

    python evals/results/lf_recall_provena-api-00065-q84/recompute_mrr_ndcg.py

입력: 이미 저장한 `recall_langfuse.json`의 문항·회차별 첫 검색 상위 5개 청크 id(`detail[].top5`, 운영 Langfuse의 첫 `search` 관측에서 읽은 값),
코퍼스 청크 파일 `data/index/chunks.jsonl`(`data/index.tar.gz`를 푼 것), 평가셋(`evals/dataset_v2.jsonl`, `evals/dataset_holdout_v1.jsonl`), 제외 목록 `evals/exclusions.json`.
채점은 `evals/latency/lf_recall.py`의 `score_run`(공식 `evals/retrieval/run.evaluate`)과 공식 `aggregate`(부트스트랩 2000회, 시드 0)를 그대로 부른다.
Langfuse·LLM·Voyage 호출은 없다. Recall@5는 저장된 값과 같게 나오는지 함께 확인한다(`recall_reproduce`, `row_mismatches`).
출력: 이 폴더의 `mrr_ndcg.json`(v2 50건 관련 25문항 x 3회 = 75행)과 `evals/results/recall_holdout_00065-q84/mrr_ndcg.json`(검증 20건 관련 10문항 x 3회 = 30행).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from evals.retrieval import run as R  # noqa: E402
from evals.retrieval.metrics import aggregate  # noqa: E402
from evals.latency.lf_recall import score_run  # noqa: E402

K = 5
KEYS = [f"recall@{K}", "rr", f"ndcg@{K}", f"hit@{K}", f"page_hit@{K}"]
SETS = [("v2", "evals/results/lf_recall_provena-api-00065-q84", "evals/dataset_v2.jsonl"),
        ("holdout", "evals/results/recall_holdout_00065-q84", "evals/dataset_holdout_v1.jsonl")]


def main() -> int:
    corpus = R.load_chunks(REPO / "data/index/chunks.jsonl")
    cby = {c.chunk_id: vars(c) for c in corpus}
    excl = R.load_exclusions(REPO / "evals/exclusions.json")
    for name, folder, ds in SETS:
        rep = json.loads((REPO / folder / "recall_langfuse.json").read_text(encoding="utf-8"))
        items = R.load_dataset(REPO / ds)
        runs = sorted({d["run"] for d in rep["detail"]})
        per_run, pooled, mism, missing_ids = {}, [], [], 0
        for n in runs:
            retrieved = {}
            for d in rep["detail"]:
                if d["run"] != n:
                    continue
                ch = []
                for cid in d.get("top5") or []:
                    if cid not in cby:
                        missing_ids += 1
                    ch.append({**cby.get(cid, {}), "chunk_id": cid})
                retrieved[d["id"]] = ch
            res = score_run(items, retrieved, k=K, exclusions=excl, corpus=corpus)
            s = res["summary"]
            per_run[n] = {k: {"value": s[k]["value"], "ci95": s[k]["ci95"]} for k in KEYS}
            per_run[n]["n_scored"] = s["n_relevant_scored"]
            pooled += res["rows"]
            orig = {d["id"]: d for d in rep["detail"] if d["run"] == n}
            for row in res["rows"]:
                o = orig.get(row["id"])
                if o and (o.get("recall") != row.get(f"recall@{K}") or o.get("first_hit_rank") != row.get("first_hit_rank")):
                    mism.append([n, row["id"], o.get("recall"), row.get(f"recall@{K}"), o.get("first_hit_rank"), row.get("first_hit_rank")])
        s = aggregate(pooled, K)
        allr = {k: {"value": s[k]["value"], "ci95": s[k]["ci95"]} for k in KEYS}
        allr["n_scored"] = s["n_relevant_scored"]
        orig_sum = rep["summary"]
        repro = {"per_run": {n: [orig_sum["per_run"][str(n)]["recall"], per_run[n][f"recall@{K}"]["value"]] for n in runs},
                 "all": [orig_sum["all_runs"]["recall"], allr[f"recall@{K}"]["value"]],
                 "all_ci_file": orig_sum["all_runs"]["ci95"], "all_ci_recomputed": allr[f"recall@{K}"]["ci95"]}
        out = {"set": name, "revision": "provena-api-00065-q84", "k": K, "source": f"{folder}/recall_langfuse.json (detail[].top5)", "dataset": ds,
               "bootstrap": "evals/retrieval/metrics.aggregate (2000회, 시드 0)", "metric_note": "rr의 평균이 MRR@5다",
               "per_run": per_run, "all_runs": allr, "recall_reproduce": repro, "row_mismatches": mism, "top5_ids_missing_in_corpus": missing_ids,
               "pooled_rows": [{k: r.get(k) for k in ["id", "scored", "n_gold", "n_found", "first_hit_rank"] + KEYS} for r in pooled]}
        (REPO / folder / "mrr_ndcg.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        a = allr
        print(name, "n", a["n_scored"], " | ".join(f"{k} {a[k]['value']:.3f} {[round(x, 3) for x in a[k]['ci95']]}" for k in KEYS),
              "missing", missing_ids, "mismatch", len(mism))
    return 0


if __name__ == "__main__":
    sys.exit(main())
