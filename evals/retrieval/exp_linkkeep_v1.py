"""link_keep_per_sub 0↔2, 전수↔HNSW 오프라인 비교 (`evals/PREREGISTER.md` #26, #27). 평가 전용 실험이며 서비스 코드는 바꾸지 않는다.

조건은 확정 조합(`voyage-4` 영어 문장 벡터, 리랭커 없음, 저장된 분해, L1x2, k=5), 동결본 `evals/dataset_v1.jsonl` 30건, 필터 없음(#9와 같음)이다.
서비스 `Searcher`를 그대로 쓰고 번역과 질문 임베딩만 바꿔 끼운다: 번역은 원문을 그대로 돌려주고, 임베딩은 저장된 질문·하위 질문 벡터를 찾아 준다.
저장 벡터에 없는 글이 오면 멈춘다. LLM, Voyage, 운영 DB는 부르지 않는다. 저장소는 로컬 pgvector(`127.0.0.1:54331`)만 받는다.

    # 관문: ① MemoryStore keep=0 = 저장된 dec+L1x2 30/30·0.9667 ② 로컬 PgStore 전수 keep=0 = ① 30/30
    python -m evals.retrieval.exp_linkkeep_v1 gate
    # 4칸(keep 0·2 × 전수·HNSW) + 벡터 질의 42개 전수↔HNSW + 색인 질의 EXPLAIN 1회
    python -m evals.retrieval.exp_linkkeep_v1 grid --out evals/results/linkkeep_v1

한 줄 재현(로컬 DB에 스냅샷 적재와 `db/manual/chunks_hnsw_voyage4.sql`이 끝난 뒤):
    REPRO_DIR=<voyage-4 zip 푼 폴더> REPRO_DATA=<data/chunks·data/parsed가 있는 폴더> DATABASE_URL=<127.0.0.1:54331 로컬 DB> python -m evals.retrieval.exp_linkkeep_v1 grid --out evals/results/linkkeep_v1
입력 파일은 `tests/test_search_v2_repro.py`와 같다. `.env`는 읽지 않고 접속 주소와 비밀번호는 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.rag.retrieve import links, translate
from backend.rag.retrieve.load_snapshot import versions_of
from backend.rag.retrieve.search import (HNSW_EF_SEARCH, HNSW_ITERATIVE, MemoryStore, PgStore, SearchConfig, Searcher,
                                         last_search_trace)
from evals.retrieval import exp_decompose_v1 as D
from evals.retrieval.experiment_v1 import qkey
from evals.retrieval.run import evaluate, load_dataset, load_exclusions

ROOT = Path(__file__).resolve().parents[2]
REPRO = Path(os.environ.get("REPRO_DIR") or ROOT / "data" / "index_exp")
DATA = Path(os.environ.get("REPRO_DATA") or ROOT)
DEC = ROOT / "evals" / "results" / "retrieval_fix_v1" / "decompose"
MODEL, K = "voyage-4", 5


def local_url() -> str:
    """DATABASE_URL이 로컬 시험 컨테이너(127.0.0.1:54331)일 때만 돌려준다. 값은 출력하지 않는다."""
    from psycopg.conninfo import conninfo_to_dict
    url = os.environ.get("DATABASE_URL") or ""
    d = conninfo_to_dict(url) if url else {}
    if d.get("host") != "127.0.0.1" or str(d.get("port")) != "54331":
        raise SystemExit("DATABASE_URL이 로컬 127.0.0.1:54331이 아니다 — 멈춘다(운영 DB 금지)")
    return url


def load_cell() -> SimpleNamespace:
    raw = [json.loads(x) for x in (DATA / "data" / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if json.loads((REPRO / "chunk_ids.json").read_text(encoding="utf-8")) != [r["chunk_id"] for r in raw]:
        raise SystemExit("chunk_ids.json과 청크 파일 순서가 다르다")
    targets = links.build(raw, DATA / "data" / "parsed" / "document_ir.jsonl", ROOT / "data" / "manifest.jsonl")
    valid = {(v["rule_seq"], v["version_id"]): v for v in versions_of(raw)}
    rows = [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
             "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"], "link_targets": t} for r, t in zip(raw, targets)]
    qv = json.loads((REPRO / "voyage-4.queries.json").read_text(encoding="utf-8"))
    sub_vec = json.loads((DEC / "subq_vec_voyage.json").read_text(encoding="utf-8"))["vec"]
    dec = json.loads((DEC / "decomposition.json").read_text(encoding="utf-8"))["items"]
    items = load_dataset(ROOT / "evals" / "dataset_v1.jsonl")
    vec, subs = {}, {}
    for it in items:
        vec[it["input"]] = np.asarray(qv[qkey(it["input"])]["en"], dtype=np.float32)
        subs[it["input"]] = dec[str(it["id"])]["sub_questions"] or None
        for s in subs[it["input"]] or []:
            vec[s] = np.asarray(sub_vec[qkey(s)], dtype=np.float32)
    ns = [SimpleNamespace(**{k: v for k, v in r.items() if k in D.KEEP}) for r in raw]
    return SimpleNamespace(rows=rows, docs=np.load(REPRO / "voyage-4.npy"), vec=vec, subs=subs, items=items, ns=ns,
                           ids=[r["chunk_id"] for r in raw], excl=load_exclusions(ROOT / "evals" / "exclusions.json"))


def embedder(c):
    def run(texts):
        miss = [t for t in texts if t not in c.vec]
        if miss:
            raise SystemExit(f"저장 벡터에 없는 글 {len(miss)}개 — 멈춘다(Voyage를 부르지 않는다)")
        return np.stack([c.vec[t] for t in texts])
    return run


def run_cell(c, store, keep: int) -> dict:
    cfg = SearchConfig(embed_model=MODEL, mode="dense_en", rerank_model="none", link_keep_per_sub=keep)
    s = Searcher(cfg, store, embedder=embedder(c), reranker=None, translator=lambda q, kind: translate.Result(q, "stored"), check_meta=False)
    trace = {}

    def search(q):
        out = s.search(q.model_copy(update={"as_of": None, "sub_queries": c.subs[q.query]}))
        tr = last_search_trace()
        trace[q.query] = {"n_sub": tr.n_sub, "n_link": tr.n_link, "mode": tr.mode}
        return out
    t0 = time.perf_counter()
    res = evaluate(c.items, search, K, exclusions=c.excl, corpus=c.ns)
    for r, it in zip(res["rows"], c.items):
        r.update(trace[it["input"]])
    return {"keep": keep, "seconds": round(time.perf_counter() - t0, 2), "recall@5": res["summary"]["recall@5"]["value"], "rows": res["rows"]}


def pg(hnsw: bool) -> PgStore:
    st = PgStore(local_url())
    st.hnsw = hnsw
    m = st.meta() or {}
    if m.get("embedder") != MODEL or m.get("status") != "ready":
        raise SystemExit(f"로컬 DB 적재 상태가 아니다: {m.get('embedder')}, {m.get('status')}")
    return st


def same_sets(a: list[dict], b: list[dict]) -> list:
    return [x["id"] for x, y in zip(a, b) if set(x["returned"]) != set(y["returned"])]


def gate(c) -> dict:
    stored = json.loads((DEC / "voyage" / "dec+L1x2.json").read_text(encoding="utf-8"))["rows_frozen"]
    mem = run_cell(c, MemoryStore(c.rows, c.docs, MODEL), 0)
    st = pg(False)
    ex = run_cell(c, st, 0)
    st.pool.close()
    g = {"mem_vs_stored_diff": same_sets(stored, mem["rows"]), "mem_recall": round(mem["recall@5"], 4),
         "pg_exact_vs_mem_diff": same_sets(mem["rows"], ex["rows"]), "pg_exact_recall": round(ex["recall@5"], 4)}
    g["passed"] = g["mem_vs_stored_diff"] == [] and g["mem_recall"] == 0.9667 and g["pg_exact_vs_mem_diff"] == []
    return g


@contextlib.contextmanager
def recording(st: PgStore, sent: list):
    """PgStore가 실제로 보내는 SQL을 그대로 기록한다(EXPLAIN에 같은 문장을 쓰려고)."""
    orig = st.pool.connection

    @contextlib.contextmanager
    def conn_cm(*a, **kw):
        with orig(*a, **kw) as conn:
            class Rec:
                def __getattr__(self, n):
                    return getattr(conn, n)

                def execute(self, sql, params=None):
                    sent.append((sql, params))
                    return conn.execute(sql, params)
            yield Rec()
    st.pool.connection = conn_cm
    try:
        yield
    finally:
        st.pool.connection = orig


def grid(c, out: Path) -> dict:
    g = gate(c)
    print("관문", {k: v for k, v in g.items()})
    if not g["passed"]:
        raise SystemExit("관문 실패 — 측정하지 않는다")
    ex, hn = pg(False), pg(True)
    cells = {f"{n}_keep{k}": run_cell(c, st, k) for n, st in (("exact", ex), ("hnsw", hn)) for k in (0, 2)}
    queries = [(it["id"], "full", it["input"]) for it in c.items if not c.subs[it["input"]]]
    queries += [(it["id"], f"sub{j + 1}", s) for it in c.items for j, s in enumerate(c.subs[it["input"]] or [])]
    pos = {i: n for n, i in enumerate(c.ids)}
    vt = []
    for iid, kind, text in queries:
        q = c.vec[text]
        a = [k for k, _ in ex.vector_top(q, MODEL, None, None, K)]
        b = [k for k, _ in hn.vector_top(q, MODEL, None, None, K)]
        sc = lambda ks: {k[0]: round(float(c.docs[pos[k[0]]] @ q), 6) for k in ks}   # noqa: E731  float32 전수 점수
        vt.append({"id": iid, "query": kind, "exact": [k[0] for k in a], "hnsw": [k[0] for k in b], "same_set": set(a) == set(b),
                   "only_exact": sc([k for k in a if k not in b]), "only_hnsw": sc([k for k in b if k not in a])})
    sent: list = []
    with recording(hn, sent):
        hn.vector_top(c.vec[queries[0][2]], MODEL, None, None, K)
    setting, (sql, params) = sent[0], sent[1]
    with hn.pool.connection() as conn:
        conn.execute(setting[0], setting[1])
        plan = [re.sub(r"'\[[^\]]*\]'", "'[질문 벡터]'", r[0]) for r in conn.execute("EXPLAIN (COSTS OFF) " + sql, params).fetchall()]
        ver = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
    ex.pool.close()
    hn.pool.close()
    out.mkdir(parents=True, exist_ok=True)
    with (out / "cells.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for name, cell in cells.items():
            for r in cell["rows"]:
                f.write(json.dumps({"cell": name, **r}, ensure_ascii=False) + "\n")
    with (out / "vector_top.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in vt:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rec = lambda cell: {r["id"]: round(r["recall@5"], 4) for r in cell["rows"] if r["kind"] == "relevant" and r.get("scored")}  # noqa: E731
    summ = {"gate": g, "ef_search": HNSW_EF_SEARCH, "iterative_scan": HNSW_ITERATIVE, "pgvector": ver,
            "explain_query": f"item {queries[0][0]} {queries[0][1]}", "explain": plan, "index_used": any("chunks_emb_hnsw_half" in p for p in plan),
            "cells": {n: {"recall@5": round(x["recall@5"], 4), "seconds": x["seconds"], "recall_by_id": rec(x)} for n, x in cells.items()},
            "keep_diff_exact": same_sets(cells["exact_keep0"]["rows"], cells["exact_keep2"]["rows"]),
            "keep_diff_hnsw": same_sets(cells["hnsw_keep0"]["rows"], cells["hnsw_keep2"]["rows"]),
            "hnsw_diff_keep0": same_sets(cells["exact_keep0"]["rows"], cells["hnsw_keep0"]["rows"]),
            "hnsw_diff_keep2": same_sets(cells["exact_keep2"]["rows"], cells["hnsw_keep2"]["rows"]),
            "vector_top_same": sum(r["same_set"] for r in vt), "vector_top_n": len(vt)}
    (out / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return summ


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("gate", "grid"))
    ap.add_argument("--out", default="evals/results/linkkeep_v1")
    a = ap.parse_args(argv)
    c = load_cell()
    if a.cmd == "gate":
        g = gate(c)
        print(json.dumps(g, ensure_ascii=False))
        return 0 if g["passed"] else 1
    s = grid(c, Path(a.out))
    print(json.dumps({k: v for k, v in s.items() if k != "explain"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
