"""청크 크기 비교 (`evals/PREREGISTER.md` #4). 평가 전용 실험이며 서비스 `search()`와 별개다.

조건은 한국어 질문 벡터 검색, 리랭커 없음, k=5, 동결본 v1이다. 800자와 120자는 이미 있는 벡터로 다시 채점해
동결본 값과 같은지 먼저 확인한다. 다른 크기의 청크와 벡터는 `--work` 폴더에 만들고 `data/`는 건드리지 않는다.

    HF_HUB_OFFLINE=1 python -m evals.retrieval.exp_chunk_size_v1 --base-chunks <스냅샷>/chunks.jsonl --work <임시 폴더>
    # voyage 두 구성. .env의 VOYAGE_API_KEY를 쓴다
    python -m evals.retrieval.exp_chunk_size_v1 --base-chunks <스냅샷>/chunks.jsonl --work <임시 폴더> \\
        --names voyage-4 voyage4-doc+nano-query --result evals/results/retrieval_v1_chunk_size/summary_voyage.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from evals.retrieval.experiment_v1 import EMBEDDERS, MIXED, _encode, _free_gpu, _voyage, device, qkey
from evals.retrieval.run import evaluate, load_chunks, load_dataset, load_exclusions

EXP = Path("data/index_exp")
LOCAL = ["voyage-4-nano", "qwen3-0.6b", "arctic-l-v2", "e5-large"]
SIZES = [(500, 75), (1200, 180)]


def score(items, excl, chunks, docs, query_name):
    qmap = json.load(open(EXP / f"{query_name}.queries.json", encoding="utf-8"))

    def search(q):
        v = np.asarray(qmap[qkey(q.query)]["ko"], dtype=np.float32)[: docs.shape[1]]
        sims = docs @ (v / np.linalg.norm(v))
        top = np.argpartition(-sims, q.k)[: q.k]
        return [chunks[i] for i in top[np.argsort(-sims[top])]]

    r = evaluate(items, search, 5, exclusions=excl, corpus=chunks)
    rows = {str(x["id"]): x["recall@5"] for x in r["rows"] if x["kind"] == "relevant" and x.get("recall@5") is not None}
    return {"recall@5": r["summary"]["recall@5"]["value"], "mrr": r["summary"]["rr"]["value"], "관련": r["summary"]["n_relevant_scored"], "문항": rows}


def voyage_key() -> None:
    if os.environ.get("VOYAGE_API_KEY") or not Path(".env").is_file():
        return
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("VOYAGE_API_KEY="):
            os.environ["VOYAGE_API_KEY"] = line.split("=", 1)[1].strip().strip('"')


def names_of(name: str) -> tuple[str, str]:
    """임베딩 이름 -> (문서 벡터 이름, 질문 벡터 이름)."""
    return MIXED.get(name, (name, name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.exp_chunk_size_v1")
    ap.add_argument("--base-chunks", type=Path, required=True, help="data/index_exp 벡터와 순서가 같은 800자 청크 파일")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--names", nargs="+", default=LOCAL)
    ap.add_argument("--result", type=Path, default=Path("evals/results/retrieval_v1_chunk_size/summary.json"))
    a = ap.parse_args(argv)
    items = load_dataset(Path("evals/dataset_v1.jsonl"))
    excl = load_exclusions(Path("evals/exclusions.json"))
    a.result.parent.mkdir(parents=True, exist_ok=True)
    res = json.loads(a.result.read_text(encoding="utf-8")) if a.result.is_file() else {}

    def save() -> None:
        a.result.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    base = load_chunks(a.base_chunks)
    for name in a.names:
        doc, query = names_of(name)
        s = score(items, excl, base, np.load(EXP / f"{doc}.npy"), query)
        res.setdefault("800/120", {})[name] = s
        print("800/120", name, round(s["recall@5"], 3), round(s["mrr"], 3), flush=True)
    res.setdefault("청크 수", {})["800/120"] = len(base)
    save()
    for size, ov in SIZES:
        d = a.work / f"s{size}"
        if not (d / "chunks.jsonl").is_file():
            d.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-m", "backend.rag.ingest.chunk", "--parsed", "data/parsed", "--corpus", "data/corpus", "--out", str(d), "--size", str(size), "--overlap", str(ov)], check=True)
        res["청크 수"][f"{size}/{ov}"] = sum(1 for line in (d / "chunks.jsonl").open(encoding="utf-8") if line.strip())
    save()
    used = [0]
    for name in a.names:
        doc, query = names_of(name)
        model = None
        for size, ov in SIZES:
            key = f"{size}/{ov}"
            if name in res.get(key, {}):
                continue
            d = a.work / f"s{size}"
            chunks = load_chunks(d / "chunks.jsonl")
            f = d / f"{doc}.npy"
            t = time.perf_counter()
            if not f.is_file():
                tmp = d / f"{doc}.tmp.npy"
                if doc == "voyage-4":
                    voyage_key()
                    np.save(tmp, _voyage([c.text for c in chunks], "document", used))
                else:
                    from sentence_transformers import SentenceTransformer

                    if model is None:
                        hf, _, rev = EMBEDDERS[doc]
                        kw = {"trust_remote_code": True, "revision": rev} if rev else {}
                        model = SentenceTransformer(hf, device=device(), **kw)
                        model.max_seq_length = 512
                    np.save(tmp, _encode(model, doc, [c.text for c in chunks], "document"))
                tmp.replace(f)
            s = score(items, excl, chunks, np.load(f), query)
            s["색인_초"] = round(time.perf_counter() - t)
            res.setdefault(key, {})[name] = s
            if used[0]:
                res["voyage_토큰"] = used[0]
            save()
            print(key, name, round(s["recall@5"], 3), round(s["mrr"], 3), "관련", s["관련"], f"{s['색인_초']}초", flush=True)
        del model
        _free_gpu()
    print("끝", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
