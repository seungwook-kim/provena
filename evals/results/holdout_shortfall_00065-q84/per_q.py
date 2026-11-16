"""Per-question analysis: production first-search top5 vs full context vs offline dense baseline. Read-only, local only."""
import json, sys
from pathlib import Path
SC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SC / "src"))
from evals.retrieval import run as R
from evals.retrieval.metrics import ranking_metrics
REPO = Path(r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena")
ANA = SC / "ana"
corpus = R.load_chunks(REPO / "data/index/chunks.jsonl")
cby = {c.chunk_id: c for c in corpus}
excl = R.load_exclusions(SC / "src/evals/exclusions.json")
from types import SimpleNamespace as NS


def objs(ids):
    return [cby.get(i, NS(chunk_id=i, rule_seq=None, article=None, line_start=None, line_end=None)) for i in ids]


def rows_of(d):
    out = {}
    for n in (1, 2, 3):
        p = d / f"run{n}" / "rows.jsonl"
        out[n] = {json.loads(x)["id"]: json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()}
    return out


res = {}
for name, ds, rec, rdir, cite in [("v2", "ds_v2.jsonl", "v2_recall.json", "deploy_latency_provena-api-00065-q84", "cite_v2.json"),
                                  ("holdout", "ds_ho.jsonl", "ho_recall.json", "deploy_latency_holdout_provena-api-00065-q84", "cite_ho.json")]:
    items = R.load_dataset(ANA / ds)
    rel = {it["id"]: it for it in items if it["kind"] == "relevant"}
    det = json.load(open(ANA / rec, encoding="utf-8"))["detail"]
    rows = rows_of(SC / "src/evals/results" / rdir) if (SC / "src/evals/results" / rdir).exists() else None
    cit = {(r["run"], r["id"]): r for r in json.load(open(ANA / cite, encoding="utf-8"))["rows"]}
    out = []
    for d in det:
        it = rel[d["id"]]
        g = it["gold"]
        m5 = ranking_metrics(g, objs(d["top5"]), 5)
        row = rows[d["run"]][d["id"]] if rows else None
        path = (row or {}).get("path") or {}
        ctx = path.get("context_ids") or []
        mctx = ranking_metrics(g, objs(ctx), max(len(ctx), 1)) if ctx else None
        cited = (row or {}).get("cited_chunk_ids") or []
        mcit = ranking_metrics(g, objs(cited), max(len(cited), 1)) if cited else None
        c = cit.get((d["run"], d["id"]), {})
        out.append({"run": d["run"], "id": d["id"], "n_gold": len(g), "rank": m5["first_hit_rank"], "rr": m5["rr"], "recall5": m5["recall@5"],
                    "ndcg5": m5["ndcg@5"], "n_sub": d.get("n_sub_queries"), "n_first": d.get("n_chunks_in_first_search"), "n_search_obs": d.get("n_search_obs_in_trace"),
                    "ctx_len": len(ctx), "ctx_recall": mctx["recall@%d" % len(ctx)] if mctx else None, "ctx_first": mctx["first_hit_rank"] if mctx else None,
                    "retries": path.get("retries"), "search_stats": path.get("search_stats"), "subs": path.get("sub_queries"),
                    "cited_recall": mcit["recall@%d" % len(cited)] if mcit else 0.0, "n_cited": len(cited),
                    "gold_cited": c.get("gold_cited"), "gold_hit": c.get("gold_hit"), "gold_total": c.get("gold_total"), "wrong_citation": c.get("wrong_citation"),
                    "cited_off_gold": c.get("cited_off_gold"), "file_recall": d.get("recall"), "file_rank": d.get("first_hit_rank")})
    res[name] = out

# offline dense baseline (round-2 grid, voyage-4 dense_en none), rescored with current gold
off = json.load(open(SC / "src/evals/results/retrieval_v2_improve/A/voyage-4__dense_en__none__0.json", encoding="utf-8"))
items = {it["id"]: it for it in R.load_dataset(ANA / "ds_v2.jsonl") if it["kind"] == "relevant"}
offr = []
for r in off["rows"]:
    if r["kind"] != "relevant":
        continue
    m = ranking_metrics(items[r["id"]]["gold"], objs(r["returned"]), 5)
    offr.append({"id": r["id"], "rank_now_gold": m["first_hit_rank"], "rr_now": m["rr"], "recall_now": m["recall@5"], "ndcg_now": m["ndcg@5"],
                 "rank_file": r.get("first_hit_rank"), "recall_file": r.get("recall@5"), "rr_file": r.get("rr"), "returned": r["returned"]})
res["offline_dense"] = offr
(ANA / "per_q.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok", {k: len(v) for k, v in res.items()})
