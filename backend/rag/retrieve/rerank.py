"""리랭킹: 검색 후보를 (질문, 청크) 한 쌍씩 다시 채점해 순서를 고친다 (docs/specs/search.md).

후보는 환경 변수 RERANK_MODEL로만 고른다. 채점 방식은 1차 비교(evals/retrieval/experiment_v1.py `_Scores`)와 같다.
- 기본은 리랭커 없음(none, 확정 조합). CrossEncoder 셋(mMiniLM, bge, bge-int8): max_length 512, batch 16, 모델 기본 출력(순위에만 쓴다).
- bge-int8: 같은 bge를 CPU에서 Linear 층만 int8로(동적 양자화). GPU 없는 배포를 가정한 후보.
- Qwen3-Reranker: 모델 카드 방식 — 지시문·질문·문서를 넣고 마지막 토큰의 "yes" 대 "no" 확률. max_length 1024, batch 8.
- 질문은 한국어 원문 그대로 넣는다(1차 비교와 같음). 점수는 모델마다 척도가 달라 절대값에 기준선을 두지 않는다.
- bge·Qwen3는 CPU에서 p95 7초·12초(Spec 응답 시간 참고)라 GPU가 없으면 경고만 남긴다(막지는 않는다).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from backend.rag.retrieve.embed import device, offline, snapshot_dir

log = logging.getLogger(__name__)
MAX_LENGTH = 512
QWEN_MAX_LENGTH = 1024


@dataclass(frozen=True)
class RerankerSpec:
    name: str          # RERANK_MODEL 값
    short: str         # experiment_v1.RERANKERS 의 이름
    hf: str
    revision: str      # 받은 날의 HF 커밋(bge·Qwen3는 10/30 고정 판, mMiniLM은 캐시). 1차 비교 판은 조장 확인 중(Q3)
    kind: str          # cross | int8 | qwen3
    needs_gpu: bool = False


RERANKERS: dict[str, RerankerSpec] = {s.name: s for s in (
    RerankerSpec("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "mminilm", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
                 "1427fd652930e4ba29e8149678df786c240d8825", "cross"),
    RerankerSpec("BAAI/bge-reranker-v2-m3", "bge", "BAAI/bge-reranker-v2-m3",
                 "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "cross", needs_gpu=True),
    RerankerSpec("bge-int8", "int8", "BAAI/bge-reranker-v2-m3", "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "int8"),
    RerankerSpec("Qwen/Qwen3-Reranker-0.6B", "qwen3", "Qwen/Qwen3-Reranker-0.6B",
                 "e61197ed45024b0ed8a2d74b80b4d909f1255473", "qwen3", needs_gpu=True),
)}
NONE = "none"
DEFAULT_MODEL = NONE   # 확정 조합(retrieval_fix_v1)은 리랭커 없음. 켜려면 RERANK_MODEL
BAKED_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"   # 비교용 리랭커. 서비스 이미지에는 넣지 않음 — Dockerfile --build-arg와 requirements-local-models.txt로

QWEN_PREFIX = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. "
               "Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
QWEN_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query"


def model_name() -> str:
    name = os.environ.get("RERANK_MODEL") or DEFAULT_MODEL
    if name != NONE and name not in RERANKERS:
        raise ValueError(f"모르는 리랭커: {name} (후보: {', '.join(RERANKERS)}, {NONE})")
    return name


class Reranker:
    """score(질문, 본문들) -> 점수 목록. 모델은 처음 만들 때 한 번만 올린다."""

    def __init__(self, s: RerankerSpec, dev: str | None = None):
        import torch
        self.spec = s
        path = snapshot_dir(s.hf, s.revision, offline())
        self.device = "cpu" if s.kind == "int8" else (dev or device())
        if s.needs_gpu and self.device == "cpu":
            log.warning("리랭커 %s 를 CPU에서 돌린다 — Spec 기준 p95 3초를 넘을 수 있다(GPU가 있을 때만 권장)", s.name)
        if s.kind == "qwen3":
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(str(path), padding_side="left", local_files_only=True)
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self.lm = AutoModelForCausalLM.from_pretrained(str(path), dtype=dtype, local_files_only=True).to(self.device).eval()
            self.yes, self.no = self.tok.convert_tokens_to_ids("yes"), self.tok.convert_tokens_to_ids("no")
        else:
            from sentence_transformers import CrossEncoder
            self.ce = CrossEncoder(str(path), max_length=MAX_LENGTH, device=self.device, local_files_only=True,
                                   model_kwargs={"dtype": torch.float32})
            if s.kind == "int8":
                torch.quantization.quantize_dynamic(self.ce.model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        if self.spec.kind == "qwen3":
            return self._qwen3(query, texts)
        return [float(x) for x in self.ce.predict([(query, t) for t in texts], batch_size=16, show_progress_bar=False)]

    def _qwen3(self, query: str, texts: list[str]) -> list[float]:
        import torch
        out: list[float] = []
        for i in range(0, len(texts), 8):
            batch = [f"{QWEN_PREFIX}<Instruct>: {QWEN_INSTRUCT}\n<Query>: {query}\n<Document>: {d}{QWEN_SUFFIX}"
                     for d in texts[i:i + 8]]
            enc = self.tok(batch, padding=True, truncation=True, max_length=QWEN_MAX_LENGTH, return_tensors="pt").to(self.lm.device)
            with torch.no_grad():
                logits = self.lm(**enc).logits[:, -1, :]
            pair = torch.stack([logits[:, self.no], logits[:, self.yes]], dim=1).float()
            out += torch.softmax(pair, dim=1)[:, 1].tolist()
        return out


def load_reranker(name: str | None = None) -> Reranker | None:
    """RERANK_MODEL=none 이면 None(리랭킹 없이 RRF 순서, Spec EC-05)."""
    name = name or model_name()
    if name == NONE:
        return None
    if name not in RERANKERS:
        raise ValueError(f"모르는 리랭커: {name}")
    return Reranker(RERANKERS[name])


def order(scores: list[float]) -> list[int]:
    """점수 내림차순 위치. 같은 점수는 원래 순서 유지(1차 비교의 안정 정렬과 같음)."""
    return sorted(range(len(scores)), key=lambda i: -scores[i])
