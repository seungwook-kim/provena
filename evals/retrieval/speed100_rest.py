"""나머지 모델 100건 속도(speed100.py와 같은 문서·질문·방식): 임베딩 e5-large, e5-large-instruct, KURE-v1 GPU·CPU,
리랭커 mMiniLM GPU·CPU, voyage-4 API(문서 100, 질문 30, 토큰 수).
실행(저장소 루트, 모델이 HF 캐시에 있어야 함):
    HF_HUB_OFFLINE=1 python -m evals.retrieval.speed100_rest
"""
import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evals.retrieval.experiment_v1 import EMBEDDERS, RERANKERS, _encode, _voyage  # noqa: E402
from sentence_transformers import CrossEncoder, SentenceTransformer  # noqa: E402

assert os.environ.get("HF_HUB_OFFLINE") == "1"
chunks = [json.loads(line) for line in open(ROOT / "data" / "chunks" / "chunks.jsonl", encoding="utf-8")]
docs = [c["text"] for c in chunks[:: len(chunks) // 100][:100]]
qs = [json.loads(line)["input"] for line in open(ROOT / "evals" / "dataset_v1.jsonl", encoding="utf-8") if line.strip()]
out = {}
DEVICES = ["cuda", "cpu"] if torch.cuda.is_available() else ["cpu"]  # GPU가 없으면 CPU만 잰다


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def free():
    gc.collect()
    torch.cuda.empty_cache()


for name in ["e5-large", "e5-large-instruct", "kure-v1"]:
    hf, _, rev = EMBEDDERS[name]
    for dev in DEVICES:
        kw = {"trust_remote_code": True, "revision": rev} if rev else {}
        t0 = time.perf_counter()
        m = SentenceTransformer(hf, device=dev, **kw)
        m.max_seq_length = 512
        load = time.perf_counter() - t0
        _encode(m, name, docs[:4], "document")
        sync()
        t0 = time.perf_counter()
        _encode(m, name, docs, "document")
        sync()
        d = time.perf_counter() - t0
        lat = []
        for q in qs:
            t0 = time.perf_counter()
            _encode(m, name, [q], "query")
            sync()
            lat.append(time.perf_counter() - t0)
        r = dict(load_s=round(load, 1), docs100_s=round(d, 2), per_10k_min=round(d * 100 / 60, 1),
                 query_ms_p50=round(float(np.median(lat)) * 1000), query_ms_p95=round(float(np.percentile(lat, 95)) * 1000))
        out[f"emb {name} {dev}"] = r
        print(name, dev, r, flush=True)
        del m
        free()

cand = [(q, docs[i * 10:(i + 1) * 10]) for i, q in enumerate(qs[:10])]
for dev in DEVICES:
    t0 = time.perf_counter()
    m = CrossEncoder(RERANKERS["mminilm"], max_length=512, device=dev)
    load = time.perf_counter() - t0
    m.predict([(qs[0], docs[0])])
    sync()
    lat = []
    for q, ds in cand:
        t0 = time.perf_counter()
        m.predict([(q, d) for d in ds], batch_size=16, show_progress_bar=False)
        sync()
        lat.append(time.perf_counter() - t0)
    r = dict(load_s=round(load, 1), per_query_10cand_ms_p50=round(float(np.median(lat)) * 1000), p95=round(float(np.percentile(lat, 95)) * 1000))
    out[f"rerank mminilm {dev}"] = r
    print("mminilm", dev, r, flush=True)
    del m
    free()

if os.environ.get("VOYAGE_API_KEY"):
    used = [0]
    t0 = time.perf_counter()
    _voyage(docs, "document", used)
    d = time.perf_counter() - t0
    doc_tokens = used[0]
    lat = []
    for q in qs:
        t0 = time.perf_counter()
        _voyage([q], "query", used)
        lat.append(time.perf_counter() - t0)
    r = dict(docs100_s=round(d, 2), per_10k_min=round(d * 100 / 60, 1), docs100_tokens=doc_tokens, per_10k_tokens=doc_tokens * 100,
             query_ms_p50=round(float(np.median(lat)) * 1000), query_ms_p95=round(float(np.percentile(lat, 95)) * 1000), total_tokens=used[0])
    out["emb voyage-4 api"] = r
    print("voyage-4 api", r, flush=True)

json.dump(out, open(ROOT / "evals" / "results" / "speed100" / "speed100_2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done")
