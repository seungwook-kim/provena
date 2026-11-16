import json, sys
from pathlib import Path
SC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SC / "src"))
from evals.retrieval import run as R
REPO = Path(r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena")
ANA = SC / "ana"
corpus = R.load_chunks(REPO / "data/index/chunks.jsonl")
cby = {c.chunk_id: c for c in corpus}
which = sys.argv[1]
ids = [int(x) for x in sys.argv[2].split(",")]
runs_wanted = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "1").split(",")]
ds = {"v2": "ds_v2.jsonl", "holdout": "ds_ho.jsonl"}[which]
rd = {"v2": "deploy_latency_provena-api-00065-q84", "holdout": "deploy_latency_holdout_provena-api-00065-q84"}[which]
items = {it["id"]: it for it in R.load_dataset(ANA / ds)}
raw = {json.loads(l)["id"]: json.loads(l) for l in (ANA / ds).read_text(encoding="utf-8").splitlines() if l.strip()}
for i in ids:
    it = items[i]
    print("#" * 10, i, it["input"])
    print("  gold_chunks:", raw[i]["gold_chunks"])
    print("  expected:", raw[i].get("expected"))
    for n in runs_wanted:
        row = {json.loads(l)["id"]: json.loads(l) for l in (SC / "src/evals/results" / rd / f"run{n}" / "rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}[i]
        p = row.get("path") or {}
        print(f"  run{n} subs={p.get('sub_queries')} src={p.get('decompose_source')} stats={p.get('search_stats')} retries={p.get('retries')} cited={row.get('cited_chunk_ids')}")
        for pos, cid in enumerate(p.get("context_ids") or [], 1):
            c = cby.get(cid)
            hit = [j for j, g in enumerate(it["gold"]) if c is not None and g.matches(c)]
            pg = any(g.page_matches(c) for g in it["gold"]) if c is not None else False
            print(f"    {pos:>2} {'G'+str(hit) if hit else ('p' if pg else ' ')} {cid} seq={getattr(c,'rule_seq',None)} L{getattr(c,'line_start',None)}-{getattr(c,'line_end',None)} {str(getattr(c,'article',None))[:150]}")
