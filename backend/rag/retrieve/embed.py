"""임베딩 모델 불러오기와 질문·문서 앞말 (docs/specs/search.md). 문서 전체 임베딩(색인 만들기)은 index.py.

- 모델은 환경 변수 EMBED_MODEL(기본 arctic)로만 고르고, 판은 EMBEDDERS의 고정 커밋(EMBED_REVISION으로 바꿀 수 있음)만 쓴다.
- 앞말·길이·정규화는 1차 비교(evals/retrieval/experiment_v1.py `_encode`)와 같다: 명부에 앞말이 있으면 글 앞에 붙이고,
  없으면 모델 설정의 prompts(예: Qwen3 질문 지시문)를 쓴다. max_seq_length 512, batch 16, 길이 1로 정규화.
- fp32로 고정한다. 설정 기본값을 따르면 Qwen3는 bf16으로 불러져 모델 말고 정밀도도 달라진다(I-008).
- HF_HUB_OFFLINE=1(Spec 기본)이면 받지 않고 캐시만 본다. 캐시에 없으면 기동 때 바로 실패한다(Spec EC-07).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAX_SEQ_LENGTH = 512
BATCH = 16


@dataclass(frozen=True)
class EmbedderSpec:
    name: str                      # Hugging Face 모델 이름 = EMBED_MODEL 값
    short: str                     # experiment_v1.EMBEDDERS 의 이름 (같은 설정인지 테스트가 대조)
    revision: str                  # 고정 커밋. 1차 비교 때 판은 조장 확인 중(설계 9절 Q3) → 지금은 받은 날의 커밋
    dim: int
    prefixes: tuple[str, str] | None = None   # (질문 앞말, 문서 앞말). None이면 모델 설정의 prompts
    trust_remote_code: bool = False            # 원격 코드는 판을 고정했을 때만


EMBEDDERS: dict[str, EmbedderSpec] = {s.name: s for s in (
    # 판: 받은 날의 HF main 커밋(arctic 2026-11-01, Qwen3·e5 캐시, bge-m3 10/29 Colab과 같은 판, nano는 experiment_v1의 고정 커밋)
    EmbedderSpec("Snowflake/snowflake-arctic-embed-l-v2.0", "arctic-l-v2", "ac6544c8a46e00af67e330e85a9028c66b8cfd9a", 1024),
    EmbedderSpec("voyageai/voyage-4-nano", "voyage-4-nano", "5fb34e870f49f19e79c94d5e118f5ee730133279", 2048,
                 trust_remote_code=True),
    EmbedderSpec("Qwen/Qwen3-Embedding-0.6B", "qwen3-0.6b", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3", 1024),
    EmbedderSpec("intfloat/multilingual-e5-large", "e5-large", "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3", 1024,
                 prefixes=("query: ", "passage: ")),          # 모델 카드의 앞말
    EmbedderSpec("BAAI/bge-m3", "bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", 1024),   # 기준선
)}
DEFAULT_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"


def spec(name: str | None = None) -> EmbedderSpec:
    name = name or os.environ.get("EMBED_MODEL") or DEFAULT_MODEL
    if name not in EMBEDDERS:
        raise ValueError(f"모르는 임베딩 모델: {name} (후보: {', '.join(EMBEDDERS)})")
    return EMBEDDERS[name]


def revision_for(s: EmbedderSpec) -> str:
    """EMBED_REVISION이 있으면 그 판, 없으면 고정 판. 환경 변수는 지금 고른 모델에만 적용한다."""
    env = os.environ.get("EMBED_REVISION")
    return env if env and s.name == (os.environ.get("EMBED_MODEL") or DEFAULT_MODEL) else s.revision


def offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "1") == "1"


def snapshot_dir(name: str, revision: str, local_files_only: bool) -> Path:
    """그 판의 캐시 폴더. 폴더 이름(= 커밋 해시)이 요청과 다르면 멈춘다(같은 이름 다른 판이 섞이지 않게).
    transformers 5는 불러온 판을 모델에 남기지 않아 폴더에서 직접 불러 판을 보장한다(10/30 확인)."""
    from huggingface_hub import snapshot_download
    path = Path(snapshot_download(name, revision=revision, local_files_only=local_files_only,
                                  ignore_patterns=["onnx/*", "*.onnx*", "openvino/*"]))
    if path.name != revision:
        raise ValueError(f"모델 판이 다르다: {name} 요청 {revision}, 캐시 폴더 {path.name}")
    return path


def device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def load_model(name: str | None = None, dev: str | None = None):
    """고정 판·fp32로 불러온다. 불러온 판은 model.pinned_name·pinned_revision 에 남긴다."""
    import torch
    from sentence_transformers import SentenceTransformer
    s = spec(name)
    rev = revision_for(s)
    path = snapshot_dir(s.name, rev, offline())
    model = SentenceTransformer(str(path), device=dev or device(), trust_remote_code=s.trust_remote_code,
                                local_files_only=True, model_kwargs={"dtype": torch.float32})
    dtype = next(model.parameters()).dtype
    if dtype != torch.float32:
        raise ValueError(f"fp32가 아니다: {s.name} {dtype}")
    model.max_seq_length = MAX_SEQ_LENGTH
    model.pinned_name, model.pinned_revision = s.name, rev
    return model


def _texts_and_kwargs(model, s: EmbedderSpec, texts: list[str], role: str) -> tuple[list[str], dict]:
    """experiment_v1._encode 와 같은 규칙. role은 "query" 또는 "document"."""
    if s.prefixes:
        return [s.prefixes[role == "document"] + t for t in texts], {}
    if role in (getattr(model, "prompts", None) or {}):
        return texts, {"prompt_name": role}
    return texts, {}


def encode(model, texts: list[str], role: str, s: EmbedderSpec | None = None) -> np.ndarray:
    s = s or spec(getattr(model, "pinned_name", None))
    texts, kw = _texts_and_kwargs(model, s, texts, role)
    vecs = np.asarray(model.encode(texts, batch_size=BATCH, normalize_embeddings=True,
                                   show_progress_bar=False, **kw), dtype=np.float32)
    check_norms(vecs)
    if vecs.shape[1] != s.dim:
        raise ValueError(f"차원이 다르다: {s.name} 명부 {s.dim}, 실제 {vecs.shape[1]}")
    return vecs


def encode_queries(model, texts: list[str]) -> np.ndarray:
    return encode(model, texts, "query")


def encode_docs(model, texts: list[str]) -> np.ndarray:
    return encode(model, texts, "document")


def used_prefixes(model, s: EmbedderSpec) -> dict:
    """장부(meta.json·index_meta)에 남길 실제 앞말. 무엇으로 잰 벡터인지 기록한다."""
    if s.prefixes:
        return {"query": s.prefixes[0], "document": s.prefixes[1], "source": "registry"}
    p = getattr(model, "prompts", None) or {}
    return {"query": p.get("query", ""), "document": p.get("document", ""), "source": "model_config"}


def check_norms(vecs: np.ndarray) -> None:
    norms = np.linalg.norm(vecs, axis=1)
    bad = int((np.abs(norms - 1) > 1e-3).sum())
    if bad:
        raise ValueError(f"길이가 1이 아닌 벡터 {bad}개 — 정규화 실패")
