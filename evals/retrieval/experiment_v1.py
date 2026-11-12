"""검색 1차 비교 실험 (`evals/PREREGISTER.md` #1). 서비스 `search()`(B-4)와 별개인 평가 전용 코드다.

임베딩 9종(로컬 7, Voyage API 1, 섞기 1) × 검색 방식 4종(+ BM25만 2종) × 리랭커 11종(없음, bge-reranker-v2-m3·Qwen3-Reranker-0.6B
각각 후보 10·15·30·50, bge int8 CPU 10, mMiniLM 10)을 같은 청크(PR #23)와 같은 평가셋으로 잰다. 결과는 `compare.py`가 표로 만든다.
후보를 추리는 1차 탐색이라 서비스 조건(로컬만, SDD 445)에 안 맞는 Voyage API도 비교용으로 넣는다.

    # 1) 색인·질문 벡터·영어 번역을 만든다(모델마다 한 번, GPU 권장). 번역은 로컬 Claude Code CLI(Haiku)
    python -m evals.retrieval.experiment_v1 prepare --dataset evals/dataset_v1.jsonl
    # 2) 조합 비교
    python -m evals.retrieval.compare --dataset evals/dataset_v1.jsonl --factory evals.retrieval.experiment_v1:make_search \\
        --grid evals/retrieval/grid_v1.json --chunks data/chunks/chunks.jsonl --out evals/results/retrieval_v1_round1

- 청크: `data/chunks/chunks.jsonl`(`python -m backend.rag.ingest.chunk`). 임베딩 글자는 청크 `text`(머리말 + 겹침 + 본문).
- 캐시: `data/index_exp/`(색인 벡터, 질문 벡터, 리랭커 점수). 다시 만들 수 있어 커밋하지 않는다.
- 영어 변환 두 가지(질문마다 한 번, Haiku): 영어 문장(`sentence`)과 영어 검색어(`keywords`). `evals/results/retrieval_v1_round1/
  translations.json`에 남겨 같은 변환으로 다시 잰다. 한글·메일 주소·지시문 되풀이가 있으면 버리고 다시 받는다(3번).
- 검색 방식(벡터 상위 100과 BM25 상위 100은 RRF k=60으로 합침):

  | 방식 | 벡터 쪽 질문 | BM25 쪽 질문 |
  |---|---|---|
  | `dense_ko` | 한국어 원문 | 없음 |
  | `dense_en` | 영어 문장 | 없음 |
  | `hybrid_ko_kw` | 한국어 원문 | 영어 검색어 |
  | `hybrid_en` | 영어 문장 | 영어 문장 |
  | `bm25_kw`, `bm25_en` (임베딩 `none`) | 없음 | 영어 검색어 / 영어 문장 |

- 리랭커는 한국어 원문 질문으로 후보(상위 `rerank_top`개)를 다시 매긴다.
- `voyage-4`: Voyage AI REST API(`VOYAGE_API_KEY`, 문서 input_type=document·질문 query, 무료 토큰 안에서 1천만 토큰 상한).
  `voyage4-doc+nano-query`: 문서는 voyage-4 색인, 질문은 로컬 voyage-4-nano 벡터 앞 1024칸(같은 임베딩 공간, 모델 카드).
- 기준일(`as_of`)로 판을 거르지 않는다. 고정 커밋 코퍼스는 쪽마다 판이 하나라 결과가 같다(2023 권한표는 따로 한 판).
- 비관련 질문도 상위 k개를 돌려준다(게이트 없음). 거절은 답 생성 단계의 일이라 이 실험의 거절 칸은 0이다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "chunks" / "chunks.jsonl"
CACHE = ROOT / "data" / "index_exp"
TRANSLATIONS = ROOT / "evals" / "results" / "retrieval_v1_round1" / "translations.json"

# 이름 -> (Hugging Face 모델, (질문 앞말, 문서 앞말) 또는 None=모델 설정의 prompts, 원격 코드 고정 커밋)
EMBEDDERS: dict[str, tuple[str, tuple[str, str] | None, str | None]] = {
    "bge-m3": ("BAAI/bge-m3", None, None),
    "e5-large": ("intfloat/multilingual-e5-large", ("query: ", "passage: "), None),  # 모델 카드의 앞말
    "voyage-4-nano": ("voyageai/voyage-4-nano", None, "5fb34e870f49f19e79c94d5e118f5ee730133279"),  # 원격 코드는 읽고 확인한 커밋만
    "qwen3-0.6b": ("Qwen/Qwen3-Embedding-0.6B", None, None),
    "kure-v1": ("nlpai-lab/KURE-v1", None, None),
    "e5-large-instruct": ("intfloat/multilingual-e5-large-instruct",
                          ("Instruct: Given a question, retrieve passages that answer the question\nQuery: ", ""), None),  # 모델 카드: 질문에만 지시문
    "arctic-l-v2": ("Snowflake/snowflake-arctic-embed-l-v2.0", None, None),
}
API_EMBEDDERS = {"voyage-4": "voyage-4"}
MIXED = {"voyage4-doc+nano-query": ("voyage-4", "voyage-4-nano")}  # 문서 색인 모델, 질문 모델
ALL_EMBEDDERS = (*EMBEDDERS, *API_EMBEDDERS, *MIXED)
RERANKERS = {"bge": "BAAI/bge-reranker-v2-m3", "qwen3": "Qwen/Qwen3-Reranker-0.6B", "int8": "BAAI/bge-reranker-v2-m3",
             "mminilm": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"}
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_MAX_TOKENS = 10_000_000
CLI_MODEL = "claude-haiku-5-5"
PROMPTS = {
    "sentence": ("Translate the user's Korean question into one natural English question for searching an English company handbook. "
                 "Output only the English question on one line, no explanation. Keep product names, codes and numbers as they are."),
    "keywords": ("Rewrite the user's Korean question as English search keywords for an English company handbook. "
                 "Output only the English keywords on one line, no explanation. Keep product names, codes and numbers as they are."),
}
MODES = ("dense_ko", "dense_en", "hybrid_ko_kw", "hybrid_en", "bm25_kw", "bm25_en")
RRF_K = 60
POOL = 100  # 하이브리드에서 벡터·BM25 각각 가져오는 후보 수
_STOP = set("a an the of to in on for and or is are be by with what how when who which do does can if it at as from this that".split())


def device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def qkey(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_chunks() -> list[SimpleNamespace]:
    keep = ("chunk_id", "rule_seq", "article", "line_start", "line_end", "text", "source_url", "kind")
    return [SimpleNamespace(**{k: v for k, v in json.loads(line).items() if k in keep})
            for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]


def questions(dataset: Path) -> list[str]:
    return [json.loads(line)["input"] for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- 영어 번역 (Claude Code CLI) ----------

def valid_english(text: str) -> bool:
    """번역으로 쓸 수 있나: 한글이 없고, 메일 주소가 없고, 지시문을 되풀이하지 않는다(예: "Translate the user's question ...")."""
    t, low = text.strip(), text.strip().lower()
    echo = low.startswith(("output only", "translate the user", "rewrite the user")) or "company handbook" in low
    return bool(t) and not re.search("[가-힣]", t) and not re.search(r"\S+@\S+\.\S+", t) and not echo


def _cli_translate(question: str, kind: str) -> tuple[str, float]:
    exe = shutil.which("claude") or shutil.which("claude.exe")
    if not exe:
        raise RuntimeError("claude CLI를 찾지 못했다")
    cmd = [exe, "-p", "--model", CLI_MODEL, "--output-format", "json", "--safe-mode", "--tools", "", "--no-session-persistence",
           "--system-prompt", PROMPTS[kind]]
    with tempfile.TemporaryDirectory(prefix="claude_cli_") as cwd:  # 빈 폴더: 프로젝트 설정이 닿지 않게
        out = subprocess.run(cmd, input=question, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, cwd=cwd)
    data = json.loads(out.stdout)
    text = str(data.get("result", "")).strip().splitlines()[0].strip() if data.get("result") else ""
    return text, float(data.get("total_cost_usd") or 0.0)


def translate_all(qs: list[str]) -> dict[str, dict[str, str]]:
    cache = json.loads(TRANSLATIONS.read_text(encoding="utf-8")) if TRANSLATIONS.is_file() else {"model": CLI_MODEL, "cost_usd": 0.0, "calls": 0, "items": {}}
    for q in qs:
        cur = cache["items"].setdefault(q, {})
        for kind in PROMPTS:
            if valid_english(cur.get(kind, "")):
                continue
            for _ in range(3):
                text, cost = _cli_translate(q, kind)
                cache["cost_usd"] = round(cache["cost_usd"] + cost, 6)
                cache["calls"] += 1
                if valid_english(text):
                    cur[kind] = text
                    break
            else:
                raise RuntimeError(f"영어 변환({kind}) 3번 실패: {q}")
    TRANSLATIONS.parent.mkdir(parents=True, exist_ok=True)
    TRANSLATIONS.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return cache["items"]


# ---------- 임베딩 ----------

def _encode(model, name: str, texts: list[str], role: str) -> np.ndarray:
    _, prefixes, _ = EMBEDDERS[name]
    kw: dict[str, Any] = {}
    if prefixes:
        texts = [prefixes[role == "document"] + t for t in texts]
    elif role in (getattr(model, "prompts", None) or {}):  # 예: Qwen3 질문 지시문. bge-m3는 앞말 없음
        kw["prompt_name"] = role
    return np.asarray(model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False, **kw), dtype=np.float32)


def _voyage(texts: list[str], role: str, used: list[int]) -> np.ndarray:
    import urllib.error
    import urllib.request

    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise SystemExit("VOYAGE_API_KEY가 없다")
    out = []
    for i in range(0, len(texts), 128):
        body = json.dumps({"input": texts[i:i + 128], "model": "voyage-4", "input_type": role}).encode("utf-8")
        for attempt in range(6):
            req = urllib.request.Request(VOYAGE_URL, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 5:
                    raise
                time.sleep(20 * (attempt + 1))  # 무료 등급 분당 한도
        used[0] += int(d.get("usage", {}).get("total_tokens", 0))
        if used[0] > VOYAGE_MAX_TOKENS:
            raise SystemExit(f"Voyage 토큰 상한 {VOYAGE_MAX_TOKENS:,} 넘음")
        out += [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]
    m = np.asarray(out, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def prepare_api(dataset: Path) -> None:
    """Voyage API 색인·질문 벡터. 토큰 수는 `data/index_exp/voyage-4.tokens.json`."""
    chunks, qs = load_chunks(), questions(dataset)
    en = translate_all(qs)
    docs, qfile, tfile = CACHE / "voyage-4.npy", CACHE / "voyage-4.queries.json", CACHE / "voyage-4.tokens.json"
    used = [json.loads(tfile.read_text(encoding="utf-8"))["tokens"] if tfile.is_file() else 0]
    if not docs.is_file():
        t0 = time.perf_counter()
        np.save(docs, _voyage([c.text for c in chunks], "document", used))
        print(f"voyage-4: 색인 {len(chunks)}청크 {time.perf_counter() - t0:.0f}초, 누적 토큰 {used[0]:,}", flush=True)
    have_q = json.loads(qfile.read_text(encoding="utf-8")) if qfile.is_file() else {}
    need_q = [q for q in qs if qkey(q) not in have_q]
    if need_q:
        ko, eng = _voyage(need_q, "query", used), _voyage([en[q]["sentence"] for q in need_q], "query", used)
        for q, a, b in zip(need_q, ko, eng):
            have_q[qkey(q)] = {"ko": a.tolist(), "en": b.tolist()}
        qfile.write_text(json.dumps(have_q), encoding="utf-8")
    tfile.write_text(json.dumps({"tokens": used[0]}), encoding="utf-8")


def prepare(dataset: Path) -> None:
    from sentence_transformers import SentenceTransformer

    CACHE.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    qs = questions(dataset)
    en = translate_all(qs)
    ids_file = CACHE / "chunk_ids.json"
    ids = [c.chunk_id for c in chunks]
    if ids_file.is_file() and json.loads(ids_file.read_text(encoding="utf-8")) != ids:
        raise SystemExit("청크가 바뀌었다: data/index_exp/를 지우고 다시 만든다")
    ids_file.write_text(json.dumps(ids), encoding="utf-8")
    for name, (hf, _, rev) in EMBEDDERS.items():
        docs, qfile = CACHE / f"{name}.npy", CACHE / f"{name}.queries.json"
        have_q = json.loads(qfile.read_text(encoding="utf-8")) if qfile.is_file() else {}
        need_q = [q for q in qs if qkey(q) not in have_q]
        if docs.is_file() and not need_q:
            continue
        kw = {"trust_remote_code": True, "revision": rev} if rev else {}
        t0 = time.perf_counter()
        model = SentenceTransformer(hf, device=device(), **kw)
        model.max_seq_length = 512
        if not docs.is_file():
            np.save(docs, _encode(model, name, [c.text for c in chunks], "document"))
            print(f"{name}: 색인 {len(chunks)}청크 {time.perf_counter() - t0:.0f}초", flush=True)
        if need_q:
            ko = _encode(model, name, need_q, "query")
            eng = _encode(model, name, [en[q]["sentence"] for q in need_q], "query")
            for q, a, b in zip(need_q, ko, eng):
                have_q[qkey(q)] = {"ko": a.tolist(), "en": b.tolist()}
            qfile.write_text(json.dumps(have_q), encoding="utf-8")
        del model
        _free_gpu()


def _free_gpu() -> None:
    try:
        import gc

        import torch

        gc.collect()
        torch.cuda.empty_cache()
    except ImportError:
        pass


# ---------- 리랭커 ----------

class _Scores:
    """(질문, 청크) 리랭커 점수 캐시. 같은 쌍은 임베딩·방식이 달라도 다시 계산하지 않는다."""

    def __init__(self, name: str) -> None:
        self.name, self.path = name, CACHE / f"rerank_{name}.json"
        self.data: dict[str, float] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        self._model = None

    def score(self, query: str, chunks: list[SimpleNamespace]) -> list[float]:
        if self.name == "int8":  # I-013: int8는 묶음에 따라 같은 쌍의 점수가 달라져 저장 값을 쓰지 않는다. 서비스처럼 후보 전체를 한 번에 계산한다
            return [float(s) for s in self._predict(query, [c.text for c in chunks])]
        keys = [f"{qkey(query)}:{c.chunk_id}" for c in chunks]
        todo = [(k, c) for k, c in zip(keys, chunks) if k not in self.data]
        if todo:
            for (k, _), s in zip(todo, self._predict(query, [c.text for _, c in todo])):
                self.data[k] = float(s)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return [self.data[k] for k in keys]

    def _predict(self, query: str, docs: list[str]) -> list[float]:
        if self.name == "bge":
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(RERANKERS["bge"], max_length=512, device=device())
        elif self.name == "int8":  # 같은 bge 리랭커를 CPU에서 Linear 층만 int8로(동적 양자화). GPU 없는 배포를 가정
            if self._model is None:
                import torch
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(RERANKERS["int8"], max_length=512, device="cpu")
                torch.quantization.quantize_dynamic(self._model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)  # 객체를 바꾸지 않고 층만 교체
        elif self.name == "mminilm":
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(RERANKERS["mminilm"], max_length=512, device=device())
        else:
            return self._qwen3(query, docs)
        return list(self._model.predict([(query, d) for d in docs], batch_size=16, show_progress_bar=False))

    def _qwen3(self, query: str, docs: list[str]) -> list[float]:
        """모델 카드 방식: 지시문·질문·문서를 넣고 마지막 토큰의 "yes" 대 "no" 확률을 점수로 쓴다."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if self._model is None:
            tok = AutoTokenizer.from_pretrained(RERANKERS["qwen3"], padding_side="left")
            dtype = torch.float16 if device() == "cuda" else torch.float32
            lm = AutoModelForCausalLM.from_pretrained(RERANKERS["qwen3"], torch_dtype=dtype).to(device()).eval()
            self._model = (tok, lm, tok.convert_tokens_to_ids("yes"), tok.convert_tokens_to_ids("no"))
        tok, lm, yes, no = self._model
        prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. "
                  "Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        instruct = "Given a web search query, retrieve relevant passages that answer the query"
        out: list[float] = []
        for i in range(0, len(docs), 8):
            texts = [f"{prefix}<Instruct>: {instruct}\n<Query>: {query}\n<Document>: {d}{suffix}" for d in docs[i:i + 8]]
            enc = tok(texts, padding=True, truncation=True, max_length=1024, return_tensors="pt").to(lm.device)
            with torch.no_grad():
                logits = lm(**enc).logits[:, -1, :]
            pair = torch.stack([logits[:, no], logits[:, yes]], dim=1).float()
            out += torch.softmax(pair, dim=1)[:, 1].tolist()
        return out


# ---------- 검색 ----------

def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in _STOP]


class _State:
    chunks: list[SimpleNamespace] | None = None
    bm25 = None
    vectors: dict[str, np.ndarray] = {}
    queries: dict[str, dict] = {}
    rerankers: dict[str, _Scores] = {}
    english: dict[str, dict[str, str]] = {}


def _state(embedder: str) -> _State:
    s = _State
    if s.chunks is None:
        s.chunks = load_chunks()
        if json.loads((CACHE / "chunk_ids.json").read_text(encoding="utf-8")) != [c.chunk_id for c in s.chunks]:
            raise SystemExit("색인과 청크가 다르다: prepare를 다시 돌린다")
        from rank_bm25 import BM25Okapi

        s.bm25 = BM25Okapi([_tokens(c.text) for c in s.chunks])
        s.english = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))["items"]
    if embedder != "none" and embedder not in s.vectors:
        doc_model, q_model = MIXED.get(embedder, (embedder, embedder))
        docs = np.load(CACHE / f"{doc_model}.npy")
        qs = json.loads((CACHE / f"{q_model}.queries.json").read_text(encoding="utf-8"))
        if q_model != doc_model:  # 질문 벡터를 문서 차원으로 자르고 길이 1로
            dim = docs.shape[1]
            cut = lambda v: (np.asarray(v[:dim]) / np.linalg.norm(v[:dim])).tolist()
            qs = {k: {"ko": cut(v["ko"]), "en": cut(v["en"])} for k, v in qs.items()}
        s.vectors, s.queries = {embedder: docs}, {embedder: qs}  # 한 번에 한 모델만 메모리에
    return s


def _top(scores: np.ndarray, n: int) -> list[int]:
    idx = np.argpartition(-scores, min(n, len(scores) - 1))[:n]
    return [int(i) for i in idx[np.argsort(-scores[idx])]]


def make_search(embedder: str, mode: str, reranker: str = "none", rerank_top: int = 0):
    """조합 하나 -> 검색 함수(`SearchQuery -> list[청크]`). `compare.py --factory`가 부른다. BM25만은 `embedder="none"`."""
    bm25_only = mode.startswith("bm25_")
    if mode not in MODES or reranker not in ("none", *RERANKERS) or (embedder == "none") != bm25_only or (embedder not in ALL_EMBEDDERS and not bm25_only):
        raise ValueError(f"모르는 조합: {embedder}, {mode}, {reranker}")
    s = _state(embedder)
    if reranker != "none" and reranker not in s.rerankers:
        s.rerankers[reranker] = _Scores(reranker)

    def search(q) -> list[SimpleNamespace]:
        n = max(q.k, rerank_top if reranker != "none" else 0)
        en = s.english[q.query]
        bm_text = {"hybrid_ko_kw": en["keywords"], "bm25_kw": en["keywords"], "hybrid_en": en["sentence"], "bm25_en": en["sentence"]}.get(mode)
        bm = np.asarray(s.bm25.get_scores(_tokens(bm_text))) if bm_text else None
        if bm25_only:
            cand = _top(bm, n)
        else:
            vec = s.queries[embedder][qkey(q.query)]
            dense = s.vectors[embedder] @ np.asarray(vec["en" if mode in ("dense_en", "hybrid_en") else "ko"], dtype=np.float32)
            if bm is None:
                cand = _top(dense, n)
            else:
                fused: dict[int, float] = {}
                for ranked in (_top(dense, POOL), _top(bm, POOL)):
                    for r, i in enumerate(ranked, 1):
                        fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
                cand = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])[:n]]
        hits = [s.chunks[i] for i in cand]
        if reranker != "none":
            sc = s.rerankers[reranker].score(q.query, hits)
            hits = [h for _, h in sorted(zip(sc, hits), key=lambda x: -x[0])]
        return hits[: q.k]

    return search


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.experiment_v1")
    ap.add_argument("command", choices=["prepare", "prepare-api"])
    ap.add_argument("--dataset", type=Path, default=ROOT / "evals" / "dataset_v1.jsonl")
    a = ap.parse_args(argv)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # 모델은 미리 받아 둔다(G2)
    (prepare_api if a.command == "prepare-api" else prepare)(a.dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
