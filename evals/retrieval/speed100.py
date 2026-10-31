"""후보 모델 100건 속도: 임베딩(문서 100청크, 질문 30) GPU·CPU, 리랭커(질문 10 x 후보 10) GPU·CPU·int8. HF_HUB_OFFLINE=1로 실행.
실행(저장소 루트, 모델이 HF 캐시에 있어야 함):
    HF_HUB_OFFLINE=1 python -m evals.retrieval.speed100
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
from evals.retrieval.experiment_v1 import EMBEDDERS, RERANKERS, _encode  # noqa: E402
from sentence_transformers import CrossEncoder, SentenceTransformer  # noqa: E402

assert os.environ.get("HF_HUB_OFFLINE") == "1"
chunks = [json.loads(line) for line in open(ROOT / "data" / "chunks" / "chunks.jsonl", encoding="utf-8")]
docs = [c["text"] for c in chunks[:: len(chunks) // 100][:100]]
qs = [json.loads(line)["input"] for line in open(ROOT / "evals" / "dataset_v1.jsonl", encoding="utf-8") if line.strip()]
print(f"docs {len(docs)}, avg {sum(map(len, docs)) / len(docs):.0f} chars, queries {len(qs)}", flush=True)
out = {}
DEVICES = ["cuda", "cpu"] if torch.cuda.is_available() else ["cpu"]  # GPU가 없으면 CPU만 잰다


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def free():
    gc.collect()
    torch.cuda.empty_cache()


for name in ["arctic-l-v2", "voyage-4-nano", "qwen3-0.6b", "bge-m3"]:
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

cand = [(q, docs[i * 10:(i + 1) * 10]) for i, q in enumerate(qs[:10])]  # 질문 10개 x 후보 10
for label, dev, quant in [x for x in [("bge", "cuda", False), ("bge", "cpu", False), ("bge-int8", "cpu", True)] if x[1] in DEVICES]:
    t0 = time.perf_counter()
    m = CrossEncoder(RERANKERS["bge"], max_length=512, device=dev)
    if quant:
        torch.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
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
    out[f"rerank {label} {dev}"] = r
    print(label, dev, r, flush=True)
    del m
    free()

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

PRE = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. '
       'Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
SUF = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
INS = "Given a web search query, retrieve relevant passages that answer the query"
for dev in DEVICES:
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(RERANKERS["qwen3"], padding_side="left")
    lm = AutoModelForCausalLM.from_pretrained(RERANKERS["qwen3"], dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
    load = time.perf_counter() - t0

    def score(q, ds):
        texts = [f"{PRE}<Instruct>: {INS}\n<Query>: {q}\n<Document>: {d}{SUF}" for d in ds]
        for i in range(0, len(texts), 8):
            enc = tok(texts[i:i + 8], padding=True, truncation=True, max_length=1024, return_tensors="pt").to(dev)
            with torch.no_grad():
                lm(**enc)

    score(qs[0], docs[:2])
    sync()
    lat = []
    for q, ds in cand:
        t0 = time.perf_counter()
        score(q, ds)
        sync()
        lat.append(time.perf_counter() - t0)
    r = dict(load_s=round(load, 1), per_query_10cand_ms_p50=round(float(np.median(lat)) * 1000), p95=round(float(np.percentile(lat, 95)) * 1000))
    out[f"rerank qwen3 {dev}"] = r
    print("qwen3", dev, r, flush=True)
    del lm
    free()

json.dump(out, open(ROOT / "evals" / "results" / "speed100" / "speed100_1.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("cpu cores", os.cpu_count(), "torch threads", torch.get_num_threads(), "gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
