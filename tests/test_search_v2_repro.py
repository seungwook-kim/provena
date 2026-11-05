"""search() v2가 확정 조합 측정(evals/retrieval/exp_decompose_v1.py)과 같은 청크를 돌려주는지 (조장 요청 5, docs/specs/search.md).

같은 질문 벡터·하위 질문 벡터를 넣고(Voyage를 부르지 않는다) v1 30문항의 청크 집합을 저장된 결과와 대조한다.
  (a) 링크 대상(links.py) = 측정 코드 Links.target, 청크 전체
  (b) 나누지 않음 + L1x2 = evals/results/retrieval_fix_v1/voyage/L1x2.json
  (c) 하위 질문 + L1x2 = evals/results/retrieval_fix_v1/decompose/voyage/dec+L1x2.json, Recall@5 0.9667
점수가 거의 같은 청크는 순서만 바뀔 수 있어 측정 코드(check_stored)처럼 집합으로 비교한다.
측정은 필터 없이 전체 청크에서 찾았으므로(exp_decompose_v1 make_search) as_of·org를 비운다.

입력 파일이 없는 환경(CI·팀원 PC)에서는 실패하지 않고 건너뛴다(조장 지시). 저장소에 올리지 않는 파일:
  REPRO_DIR(기본 data/index_exp): voyage-4.npy, chunk_ids.json, voyage-4.queries.json  ← 조장이 준 zip
  REPRO_DATA(기본 저장소 루트): data/chunks/chunks.jsonl, data/parsed/document_ir.jsonl  ← 수집·파싱·청킹 결과
    REPRO_DIR=<zip 푼 폴더> REPRO_DATA=<data가 있는 폴더> pytest tests/test_search_v2_repro.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.rag.retrieve import links, translate
from backend.rag.retrieve.load_snapshot import versions_of
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher

ROOT = Path(__file__).resolve().parents[1]
REPRO = Path(os.environ.get("REPRO_DIR") or ROOT / "data" / "index_exp")
DATA = Path(os.environ.get("REPRO_DATA") or ROOT)
FIX = ROOT / "evals" / "results" / "retrieval_fix_v1"
NEED = [REPRO / "voyage-4.npy", REPRO / "chunk_ids.json", REPRO / "voyage-4.queries.json",
        DATA / "data" / "chunks" / "chunks.jsonl", DATA / "data" / "parsed" / "document_ir.jsonl",
        ROOT / "data" / "manifest.jsonl", FIX / "decompose" / "decomposition.json",
        FIX / "decompose" / "subq_vec_voyage.json", FIX / "decompose" / "voyage" / "dec+L1x2.json",
        FIX / "voyage" / "L1x2.json", ROOT / "evals" / "dataset_v1.jsonl"]
MISSING = [str(p) for p in NEED if not p.is_file()]
pytestmark = pytest.mark.skipif(bool(MISSING), reason=f"재현 입력 없음: {MISSING[:2]}")


@pytest.fixture(scope="module")
def cell():
    ex = pytest.importorskip("evals.retrieval.experiment_v1")
    dec_mod = pytest.importorskip("evals.retrieval.exp_decompose_v1")
    from evals.retrieval.run import load_dataset, load_exclusions
    raw = [json.loads(x) for x in (DATA / "data" / "chunks" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if json.loads((REPRO / "chunk_ids.json").read_text(encoding="utf-8")) != [r["chunk_id"] for r in raw]:
        pytest.fail("chunk_ids.json과 청크 파일 순서가 다르다(다른 청크 파일)")
    targets = links.build(raw, DATA / "data" / "parsed" / "document_ir.jsonl", ROOT / "data" / "manifest.jsonl")
    valid = {(v["rule_seq"], v["version_id"]): v for v in versions_of(raw)}
    rows = [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
             "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"], "link_targets": t}
            for r, t in zip(raw, targets)]
    docs = np.load(REPRO / "voyage-4.npy")
    qv = json.loads((REPRO / "voyage-4.queries.json").read_text(encoding="utf-8"))
    sub_vec = json.loads((FIX / "decompose" / "subq_vec_voyage.json").read_text(encoding="utf-8"))["vec"]
    dec = json.loads((FIX / "decompose" / "decomposition.json").read_text(encoding="utf-8"))["items"]
    items = load_dataset(ROOT / "evals" / "dataset_v1.jsonl")
    ns = [SimpleNamespace(**{k: v for k, v in r.items() if k in dec_mod.KEEP}) for r in raw]
    return SimpleNamespace(ex=ex, dec_mod=dec_mod, raw=raw, rows=rows, targets=targets, docs=docs, qv=qv, sub_vec=sub_vec,
                           dec=dec, items=items, ns=ns, excl=load_exclusions(ROOT / "evals" / "exclusions.json"))


def _searcher(c, calls):
    """번역은 원문 그대로(벡터를 원문으로 찾으려고), 임베딩은 저장된 벡터. 둘 다 유료 API를 부르지 않는다."""
    vec = {}
    for it in c.items:
        vec[it["input"]] = np.asarray(c.qv[c.ex.qkey(it["input"])]["en"], dtype=np.float32)
        for s in c.dec[str(it["id"])]["sub_questions"]:
            vec[s] = np.asarray(c.sub_vec[c.ex.qkey(s)], dtype=np.float32)

    def embedder(texts):
        calls.append(len(texts))
        return np.stack([vec[t] for t in texts])

    cfg = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none")
    assert (cfg.mode, cfg.rerank_model, cfg.link_n) == (SearchConfig.mode, SearchConfig.rerank_model, SearchConfig.link_n)
    return Searcher(cfg, MemoryStore(c.rows, c.docs, "voyage-4"), embedder=embedder, reranker=None,
                    translator=lambda q, kind: translate.Result(q, "stored"), check_meta=False)


def _run(c, use_dec: bool):
    from evals.retrieval.run import evaluate
    calls: list[int] = []
    s = _searcher(c, calls)
    subs = {it["input"]: (c.dec[str(it["id"])]["sub_questions"] or None) if use_dec else None for it in c.items}
    res = evaluate(c.items, lambda q: s.search(q.model_copy(update={"as_of": None, "sub_queries": subs[q.query]})), 5,
                   exclusions=c.excl, corpus=c.ns)
    return res, calls, subs


def _same_sets(res, stored_rows):
    assert [r["id"] for r in res["rows"]] == [r["id"] for r in stored_rows]
    diff = [a["id"] for a, b in zip(stored_rows, res["rows"]) if set(a["returned"]) != set(b["returned"])]
    assert diff == [], f"청크 집합이 다른 문항: {diff}"


def test_a_link_targets_equal_measurement(cell):
    m = cell.dec_mod
    old_ir, old_man = m.IR, m.MANIFEST
    m.IR, m.MANIFEST = DATA / "data" / "parsed" / "document_ir.jsonl", ROOT / "data" / "manifest.jsonl"
    try:
        want = m.Links(cell.raw, cell.ns).target
    finally:
        m.IR, m.MANIFEST = old_ir, old_man
    assert len(want) == len(cell.targets) == len(cell.raw)
    assert [{str(x) for x in t} for t in cell.targets] == want
    assert sum(1 for t in cell.targets if t) > 0


def test_b_no_split_l1x2_equals_stored(cell):
    stored = json.loads((FIX / "voyage" / "L1x2.json").read_text(encoding="utf-8"))
    res, calls, _ = _run(cell, use_dec=False)
    _same_sets(res, stored.get("rows_frozen") or stored["rows"])
    assert calls == [1] * len(cell.items)                  # 질문마다 임베딩 1번


def test_c_decompose_l1x2_equals_stored_and_recall(cell):
    stored = json.loads((FIX / "decompose" / "voyage" / "dec+L1x2.json").read_text(encoding="utf-8"))
    res, calls, subs = _run(cell, use_dec=True)
    _same_sets(res, stored["rows_frozen"])
    assert round(res["summary"]["recall@5"]["value"], 4) == 0.9667
    by_id = {r["id"]: r["recall@5"] for r in res["rows"] if r["kind"] == "relevant" and r.get("scored")}
    assert {i for i, v in by_id.items() if v < 1} == {3} and by_id[3] == 0.5
    # 나뉜 질문은 전체 + 하위 질문 벡터를 한 번에(요청 1번)
    assert calls == [1 + len(subs[it["input"]] or []) for it in cell.items]
    assert sum(1 for v in subs.values() if v) == 11
