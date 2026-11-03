"""메타데이터 필터 비교 (`evals/PREREGISTER.md` #3). LLM과 DB를 쓰지 않는다.

한국어 질문 벡터 검색, 리랭커 없음, k=5, 동결본 v1에서 필터 없음, `as_of`, `as_of`와 `org`를 잰다.
`org`는 정답 위치의 절을 그대로 넣으므로 실제 사용의 상한이다. 정답 절이 둘 이상인 문항에는 넣지 않는다.

    python -m evals.retrieval.exp_filter_v1 --index <스냅샷 폴더>
"""
from __future__ import annotations

import argparse
import collections
import glob
import importlib
import json
from pathlib import Path

import numpy as np

from backend.rag.retrieve import translate
from evals.retrieval.metrics import ranking_metrics
from evals.retrieval.run import evaluate, load_chunks, load_dataset, load_exclusions

S = importlib.import_module("backend.rag.retrieve.search")  # 패키지가 search 함수를 같은 이름으로 내보낸다
EXP = Path("data/index_exp")
OUT = Path("evals/results/retrieval_v1_filter")
COMBOS = [("bge-m3", "bge-m3", "bge-m3"), ("arctic-l-v2", "arctic-l-v2", "arctic-l-v2"), ("voyage-4-nano", "voyage-4-nano", "voyage-4-nano"), ("qwen3-0.6b", "qwen3-0.6b", "qwen3-0.6b"),
          ("e5-large", "e5-large", "e5-large"), ("voyage-4", "voyage-4", "voyage-4"), ("voyage4-doc+nano-query", "voyage-4", "voyage-4-nano")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.exp_filter_v1")
    ap.add_argument("--index", type=Path, required=True)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    items = load_dataset(Path("evals/dataset_v1.jsonl"))
    excl = load_exclusions(Path("evals/exclusions.json"))
    corpus = load_chunks(a.index / "chunks.jsonl")
    org_of, multi = {}, {}
    for it in items:
        if it["kind"] != "relevant":
            continue
        orgs = collections.Counter(getattr(c, "org", None) for c in corpus if ranking_metrics(it["gold"], [c], 5).get("hit@5"))
        if len(orgs) == 1:
            org_of[it["input"]] = next(iter(orgs))
        else:
            multi[str(it["id"])] = sorted(map(str, orgs))
    meta, rows = S.snapshot_rows(a.index)
    ledger = S.seed_translations(a.index, meta)
    frozen = [json.load(open(p, encoding="utf-8")) for p in glob.glob("evals/results/retrieval_v1_round1_frozen/*.json")]
    arms = {"필터 없음": lambda q: q.model_copy(update={"as_of": None, "org": None}), "as_of": lambda q: q,
            "as_of와 org": lambda q: q.model_copy(update={"org": org_of.get(q.query)})}
    bm25, res = None, {}
    for name, doc, query in COMBOS:
        vecs = np.load(EXP / f"{doc}.npy")
        qmap = json.load(open(EXP / f"{query}.queries.json", encoding="utf-8"))
        dim = vecs.shape[1]

        def qvec(texts, qmap=qmap, dim=dim):
            out = []
            for t in texts:
                v = np.asarray(qmap[translate.query_sha(t)[:16]]["ko"], dtype=np.float32)[:dim]
                out.append(v / np.linalg.norm(v))
            return np.stack(out)

        store = S.MemoryStore(rows, vecs, name)
        store.translations = ledger
        cfg = S.SearchConfig(embed_model=name, mode="dense_ko", rerank_model=S.reranker_name("none"))
        s = S.Searcher(cfg, store, embedder=qvec, reranker=None, translator=S._strict_translator(store), check_meta=False, bm25=bm25)
        bm25 = (s._rm, s._bm25)
        old = [x for x in frozen if x["config"]["embedder"] == name and x["config"]["mode"] == "dense_ko" and x["config"].get("reranker", "none") == "none"][0]["summary"]
        res[name] = {"동결본": {"recall@5": old["recall@5"]["value"], "mrr": old["rr"]["value"]}}
        for arm, f in arms.items():
            r = evaluate(items, lambda q, f=f, s=s: s.search(f(q)), 5, exclusions=excl, corpus=corpus)
            rs = {str(x["id"]): x for x in r["rows"] if x["kind"] == "relevant"}
            res[name][arm] = {"recall@5": r["summary"]["recall@5"]["value"], "mrr": r["summary"]["rr"]["value"], "문항": {i: x["recall@5"] for i, x in rs.items()}}
            print(name, arm, round(res[name][arm]["recall@5"], 3), round(res[name][arm]["mrr"], 3), flush=True)
    (OUT / "summary.json").write_text(json.dumps({"org_없는_문항": multi, "결과": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("끝")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
