"""검색 회귀 시험(tests/test_search_regression.py)의 작은 고정 자료를 만든다 (D8 ⑦ 평가 회귀 테스트를 CI에).

CI에는 voyage-4 문서 벡터(23,095 × 1024, 약 95MB)와 Voyage 키가 없다. 그래서 전체 색인으로 한 번 돌린 결과를 기대값으로 동결하고,
그 검색이 실제로 읽은 청크(질문 벡터마다 상위 N, 링크 확장 후보 상위 N)와 정답 청크 일부만 떼어 float16으로 저장한다.
시험은 이 자료만 MemoryStore에 넣고 서비스 search() 경로를 그대로 돌려 기대값과 비교한다.

문항: 동결 v1 30건(관련 15·비관련 15) + v2 관련 중 v1에 없는 10건(31~40) = 40건. v2 관련 25건 = v1 관련 15 + 이 10건.
하위 질문: v1은 확정 조합 측정의 저장 분해(retrieval_fix_v1/decompose, 11건 나뉨), v2 새 10건은 실험 B의 저장 하위 검색어
(retrieval_v2_improve/B/subqueries.json, 2~3개인 6건만. 1개면 나누지 않음). 질문 벡터는 모두 저장된 것만 쓴다(Voyage를 부르지 않는다).
조합: SearchConfig 기본값(voyage-4 · dense_en · 리랭커 없음 · k=5 · L1x2 · 하위 질문마다 2자리 지킴), 필터 없음(as_of·org 비움, #9 측정과 같음).
입력 파일(재현 zip의 이름·sha256·받는 곳, REPRO_DATA 만드는 법)은 evals/retrieval/retrieval.md "재현 자료"에 있다.

    REPRO_DIR=<voyage-4 재현 zip 푼 폴더> REPRO_DATA=<data/chunks·data/parsed가 있는 폴더> \
      python -m evals.retrieval.regress_fixture --n 10 --out tests/fixtures/search_regression
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.rag.retrieve import links, translate
from backend.rag.retrieve.load_snapshot import versions_of
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, last_search_trace
from backend.schemas.chunk import DEFAULT_K, SearchQuery
from evals.retrieval.run import evaluate, load_dataset, load_exclusions

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "evals" / "results" / "retrieval_fix_v1" / "decompose"
B = ROOT / "evals" / "results" / "retrieval_v2_improve" / "B"
EMBEDDER = "voyage-4"
ROW_KEYS = ("chunk_id", "version_id", "org", "rule_seq", "rule_title", "article", "version_date", "fetched_at", "kind",
            "source_url", "text_sha256", "version_date_before", "line_start", "line_end", "valid_from", "valid_to", "link_targets")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fixture_sha(p: Path) -> str:
    """자료 파일 지문. 글 파일(json·jsonl)은 줄바꿈을 LF로 맞춰 잰다 — Windows autocrlf로 받으면 CRLF가 되어
    바이트 sha256이 달라진다(.gitattributes I-003과 같은 문제). 벡터(.npy)는 바이너리라 그대로."""
    data = p.read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if p.suffix in (".json", ".jsonl") else data).hexdigest()


def qkey(text: str) -> str:
    """experiment_v1.qkey와 같다(저장 질문 벡터의 열쇠)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_fixture(d: Path) -> tuple[list[dict], np.ndarray, dict[str, np.ndarray], dict, dict]:
    """(행, 문서 벡터 float32, 질문 글 → 벡터, queries.json, expected.json).
    본문은 저장하지 않는다(dense_en 점수는 벡터만 쓴다). Searcher가 BM25 색인을 만들 수 있게 제목 경로를 본문 자리에 둔다."""
    rows = [json.loads(x) for x in (d / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [{**r, "text": f"{r['rule_title']} > {r.get('article') or ''}"} for r in rows]
    q = json.loads((d / "queries.json").read_text(encoding="utf-8"))
    vec = dict(zip(q["texts"], np.load(d / "query_vecs.npy").astype(np.float32)))
    exp = json.loads((d / "expected.json").read_text(encoding="utf-8"))
    return rows, np.load(d / "doc_vecs.npy").astype(np.float32), vec, q, exp


def items_and_subs() -> tuple[list[dict], dict[int, list[str] | None], dict[str, str]]:
    """(문항, id → 하위 질문, 출처 설명). 문항은 동결 평가셋 파일에서 읽는다."""
    v1 = load_dataset(ROOT / "evals" / "dataset_v1.jsonl")
    v2 = load_dataset(ROOT / "evals" / "dataset_v2.jsonl")
    seen = {it["input"] for it in v1}
    new = [it for it in v2 if it["kind"] == "relevant" and it["input"] not in seen]
    dec = json.loads((FIX / "decomposition.json").read_text(encoding="utf-8"))["items"]
    bsq = json.loads((B / "subqueries.json").read_text(encoding="utf-8"))["items"]
    subs: dict[int, list[str] | None] = {}
    for it in v1:
        subs[it["id"]] = dec[str(it["id"])]["sub_questions"] or None
    for it in new:
        en = [s["en"] for s in bsq[str(it["id"])]["subqueries"]]
        subs[it["id"]] = en if len(en) >= 2 else None
    for it in v1:
        it["set"] = "v1"
    for it in new:
        it["set"] = "v2"
    return v1 + new, subs, {"v1": "retrieval_fix_v1/decompose/decomposition.json", "v2": "retrieval_v2_improve/B/subqueries.json (en, 2~3개만)"}


def query_vectors(repro: Path, items: list[dict], subs: dict) -> dict[str, np.ndarray]:
    """질문 글 → 저장된 voyage-4 질문 벡터(float32). 전체 질문은 영어 번역문 벡터(en), 하위 질문은 저장 벡터."""
    qv = json.loads((repro / "voyage-4.queries.json").read_text(encoding="utf-8"))
    sv = json.loads((FIX / "subq_vec_voyage.json").read_text(encoding="utf-8"))["vec"]
    bv = json.loads((B / "voyage_subq_embeddings.json").read_text(encoding="utf-8"))
    bmap = dict(zip(bv["texts"], bv["vectors"]))
    out: dict[str, np.ndarray] = {}
    for it in items:
        out[it["input"]] = np.asarray(qv[qkey(it["input"])]["en"], dtype=np.float32)
        for s in subs[it["id"]] or []:
            out[s] = np.asarray(sv[qkey(s)] if it["set"] == "v1" else bmap[s], dtype=np.float32)
    return out


class RecordingStore(MemoryStore):
    """검색이 부른 질의를 같은 인자로 상위 pad개까지 더 읽어 그 청크를 적어 둔다. 돌려주는 값은 MemoryStore와 같다."""

    def __init__(self, *a, pad: int, **kw):
        super().__init__(*a, **kw)
        self.pad, self.seen = pad, set()

    def vector_top(self, qvec, embedder, org, as_of, n):
        got = super().vector_top(qvec, embedder, org, as_of, max(n, self.pad))
        self.seen.update(k for k, _ in got)
        return got[:n]

    def page_vector_top(self, qvec, embedder, rule_seqs, org, as_of, exclude, n):
        got = super().page_vector_top(qvec, embedder, rule_seqs, org, as_of, exclude, max(n, self.pad))
        self.seen.update(k for k, _ in got)
        return got[:n]


def make_searcher(rows, vecs, vec_of: dict[str, np.ndarray], store_cls=MemoryStore, cfg: SearchConfig | None = None, **kw):
    """번역은 원문 그대로(벡터를 원문으로 찾으려고), 임베딩은 저장 벡터. 둘 다 유료 API를 부르지 않는다(tests/test_search_v2_repro.py와 같다).
    cfg를 주지 않으면 SearchConfig 기본값(확정 조합)."""
    def embedder(texts):
        return np.stack([vec_of[t] for t in texts])
    cfg = cfg or SearchConfig(embed_model=EMBEDDER)
    store = store_cls(rows, vecs, EMBEDDER, **kw)
    return Searcher(cfg, store, embedder=embedder, reranker=None,
                    translator=lambda q, kind: translate.Result(q, "stored"), check_meta=False), store


def run(search_fn, items, subs, exclusions, corpus=None) -> tuple[dict, dict[int, dict]]:
    """평가 + 문항별 검색 기록(하위 질문 수·링크 자리)."""
    by_q = {it["input"]: it["id"] for it in items}
    traces: dict[int, dict] = {}

    def fn(q: SearchQuery):
        i = by_q[q.query]
        out = search_fn(q.model_copy(update={"as_of": None, "org": None, "sub_queries": subs[i]}))
        tr = last_search_trace()
        traces[i] = {"n_sub": tr.n_sub, "n_link": tr.n_link, "mode": tr.mode}
        return out
    return evaluate(items, fn, DEFAULT_K, exclusions=exclusions, corpus=corpus), traces


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.regress_fixture")
    ap.add_argument("--n", type=int, default=10, help="질의마다 떼어 둘 상위 후보 수(k 이상)")
    ap.add_argument("--gold-per-ref", type=int, default=2, help="정답 표기마다 더 넣을 정답 청크 수(전체 질문 벡터와 가까운 순)")
    ap.add_argument("--dtype", default="float16")
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "search_regression")
    a = ap.parse_args(argv)
    repro = Path(os.environ.get("REPRO_DIR") or ROOT / "data" / "index_exp")
    data = Path(os.environ.get("REPRO_DATA") or ROOT)
    t0 = time.perf_counter()

    raw = [json.loads(x) for x in (data / "data" / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if json.loads((repro / "chunk_ids.json").read_text(encoding="utf-8")) != [r["chunk_id"] for r in raw]:
        raise SystemExit("chunk_ids.json과 청크 파일 순서가 다르다(다른 청크 파일)")
    targets = links.build(raw, data / "data" / "parsed" / "document_ir.jsonl", ROOT / "data" / "manifest.jsonl")
    valid = {(v["rule_seq"], v["version_id"]): v for v in versions_of(raw)}
    rows = [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
             "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"], "link_targets": t}
            for r, t in zip(raw, targets)]
    docs = np.load(repro / "voyage-4.npy")
    items, subs, sub_src = items_and_subs()
    vec_of = query_vectors(repro, items, subs)
    excl = load_exclusions(ROOT / "evals" / "exclusions.json")
    corpus = [SimpleNamespace(**{k: r.get(k) for k in ("chunk_id", "rule_seq", "article", "line_start", "line_end")}) for r in raw]

    # 1) 전체 색인(23,095청크, float32)으로 기준 결과. 이것이 기대값이 된다.
    full, store = make_searcher(rows, docs, vec_of, store_cls=RecordingStore, pad=a.n)
    ref, ref_tr = run(full.search, items, subs, excl, corpus)

    # 2) 정답 청크: 표기마다 맞는 청크 중 현재 판(as_of 없음 필터)에서 전체 질문 벡터와 가까운 것 gold-per-ref개
    cur = {i for i, r in enumerate(rows) if not r.get("valid_to")}
    keep = set(store.seen)
    n_gold_added = 0
    for it in items:
        q = vec_of[it["input"]]
        for g in it["gold"]:
            pos = [i for i in cur if g.matches(corpus[i])]
            pos.sort(key=lambda i: (-float(docs[i] @ q), rows[i]["chunk_id"]))
            for i in pos[: a.gold_per_ref]:
                k = (rows[i]["chunk_id"], rows[i]["version_id"])
                if k not in keep:
                    keep.add(k)
                    n_gold_added += 1
    idx = [i for i, r in enumerate(rows) if (r["chunk_id"], r["version_id"]) in keep]   # 코퍼스 순서 그대로

    # 3) 저장
    a.out.mkdir(parents=True, exist_ok=True)
    sub_rows = [{k: rows[i].get(k) for k in ROW_KEYS} for i in idx]
    with (a.out / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in sub_rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    np.save(a.out / "doc_vecs.npy", docs[idx].astype(a.dtype))
    texts = list(vec_of)
    np.save(a.out / "query_vecs.npy", np.stack([vec_of[t] for t in texts]).astype(a.dtype))
    queries = [{"id": it["id"], "set": it["set"], "kind": it["kind"], "input": it["input"], "sub_queries": subs[it["id"]]} for it in items]
    (a.out / "queries.json").write_text(json.dumps({"texts": texts, "items": queries}, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8", newline="\n")

    # 4) 같음 검증: 떼어 낸 자료(float16)로 다시 돌려 기준 결과와 문항별 대조
    (a.out / "expected.json").write_text("{}", encoding="utf-8")
    fx_rows, fx_docs, fx_vec, _, _ = load_fixture(a.out)
    fx, _ = make_searcher(fx_rows, fx_docs, fx_vec)
    got, got_tr = run(fx.search, items, subs, excl, None)
    same = []
    for r0, r1 in zip(ref["rows"], got["rows"]):
        same.append({"id": r0["id"], "same_order": r0["returned"] == r1["returned"],
                     "overlap": len(set(r0["returned"]) & set(r1["returned"])),
                     "only_full": sorted(set(r0["returned"]) - set(r1["returned"])),
                     "only_fixture": sorted(set(r1["returned"]) - set(r0["returned"]))})

    rec = f"recall@{DEFAULT_K}"
    expected = {
        "made_by": "python -m evals.retrieval.regress_fixture --n %d --gold-per-ref %d --dtype %s" % (a.n, a.gold_per_ref, a.dtype),
        "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # 무엇으로 쟀는지(rag 3주 06강 baseline의 checked_with, 04강 corpus_id): 코퍼스 판·청크 수·질문 벡터 모델
        "checked_with": {"corpus_version": sorted({it.get("corpus_version") for it in items if it.get("corpus_version")}),
                         "n_chunks": len(raw), "query_vectors": "voyage-4 저장 벡터(재현 zip, B 실험 하위 검색어)",
                         "reference": "전체 색인 MemoryStore(float32). 로컬 PgStore 전수와 40/40 같음(2026-11-07)"},
        "config": {"embed_model": EMBEDDER, "mode": SearchConfig.mode, "rerank_model": SearchConfig.rerank_model, "k": DEFAULT_K,
                   "link_n": SearchConfig.link_n, "link_keep_per_sub": SearchConfig.link_keep_per_sub, "as_of": None, "org": None},
        "fixture": {"n": a.n, "gold_per_ref": a.gold_per_ref, "dtype": a.dtype, "n_rows": len(idx), "n_gold_added": n_gold_added,
                    "n_query_texts": len(texts), "sub_queries_from": sub_src},
        "inputs_sha256": {"voyage-4.npy": sha(repro / "voyage-4.npy"), "chunk_ids.json": sha(repro / "chunk_ids.json"),
                          "voyage-4.queries.json": sha(repro / "voyage-4.queries.json"),
                          "chunks.jsonl": sha(data / "data" / "chunks" / "chunks.jsonl"),
                          "dataset_v1.jsonl": sha(ROOT / "evals" / "dataset_v1.jsonl"),
                          "dataset_v2.jsonl": sha(ROOT / "evals" / "dataset_v2.jsonl")},
        "files_sha256": {p: fixture_sha(a.out / p) for p in ("rows.jsonl", "doc_vecs.npy", "query_vecs.npy", "queries.json")},
        "summary": {rec: ref["summary"][rec]["value"], "n_scored": ref["summary"]["n_relevant_scored"]},
        "rows": [{"id": r["id"], "set": it["set"], "kind": r["kind"], "returned": r["returned"], "scored": r.get("scored"),
                  rec: r.get(rec), "first_hit_rank": r.get("first_hit_rank"), **ref_tr[r["id"]]}
                 for r, it in zip(ref["rows"], items)],
    }
    (a.out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    report = {"same": same, "full_recall": ref["summary"][rec]["value"], "fixture_recall": got["summary"][rec]["value"],
              "fixture_traces": got_tr, "seconds": round(time.perf_counter() - t0, 1)}
    print(json.dumps({"n_rows": len(idx), "n_gold_added": n_gold_added, "same_order": sum(s["same_order"] for s in same),
                      "same_set": sum(s["overlap"] == DEFAULT_K or (not s["only_full"] and not s["only_fixture"]) for s in same),
                      "n": len(same), **{k: v for k, v in report.items() if k != "same" and k != "fixture_traces"}}, ensure_ascii=False))
    diff = [s for s in same if s["only_full"] or s["only_fixture"]]
    if diff:
        print("다른 문항:", json.dumps(diff, ensure_ascii=False))
    out_report = os.environ.get("REGRESS_REPORT")
    if out_report:
        Path(out_report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
