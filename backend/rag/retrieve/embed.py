"""임베딩 모델 불러오기와 질문·문서 앞말 (docs/specs/search.md). 문서 전체 임베딩(색인 만들기)은 index.py.

- 모델은 환경 변수 EMBED_MODEL(기본 voyage-4)로만 고르고, 판은 EMBEDDERS의 고정 커밋(EMBED_REVISION으로 바꿀 수 있음)만 쓴다.
- voyage-4는 Voyage AI REST API(확정 조합, docs/specs/search.md). 키는 환경 변수 VOYAGE_API_KEY를 부를 때 읽고 어디에도 찍지 않는다.
  연결 오류·시간 초과·429·5xx는 EmbedUnavailable(ConnectionError → MCP 재시도 가능), 키 없음은 EmbedNoKey(검색은 빈 결과),
  401·403·400은 EmbedConfigError. 시간 한도 10초·재시도 0번: MCP 도구 한도 30초에서 번역 한도 15초를 뺀 안쪽.
  응답의 `usage.total_tokens`는 `/chat` 요청 집계(`backend/services/step_cost.py`)에 더한다(`embed_tokens`). 요청 밖(기동 워밍업, 색인 만들기)이면 더하지 않는다.
- 앞말·길이·정규화는 1차 비교(evals/retrieval/experiment_v1.py `_encode`)와 같다: 명부에 앞말이 있으면 글 앞에 붙이고,
  없으면 모델 설정의 prompts(예: Qwen3 질문 지시문)를 쓴다. max_seq_length 512, batch 16, 길이 1로 정규화.
- fp32로 고정한다. 설정 기본값을 따르면 Qwen3는 bf16으로 불러져 모델 말고 정밀도도 달라진다(I-008).
- HF_HUB_OFFLINE=1(Spec 기본)이면 받지 않고 캐시만 본다. 캐시에 없으면 기동 때 바로 실패한다(Spec EC-07).
"""
from __future__ import annotations

import contextvars
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.services import step_cost

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
    api: bool = False                          # True면 내려받는 모델이 아니라 REST API(판 = "api:모델 이름")


EMBEDDERS: dict[str, EmbedderSpec] = {s.name: s for s in (
    # 판: 받은 날의 HF main 커밋(arctic 2026-11-01, Qwen3·e5 캐시, bge-m3 10/29 Colab과 같은 판, nano는 experiment_v1의 고정 커밋)
    EmbedderSpec("Snowflake/snowflake-arctic-embed-l-v2.0", "arctic-l-v2", "ac6544c8a46e00af67e330e85a9028c66b8cfd9a", 1024),
    EmbedderSpec("voyageai/voyage-4-nano", "voyage-4-nano", "5fb34e870f49f19e79c94d5e118f5ee730133279", 2048,
                 trust_remote_code=True),
    EmbedderSpec("Qwen/Qwen3-Embedding-0.6B", "qwen3-0.6b", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3", 1024),
    EmbedderSpec("intfloat/multilingual-e5-large", "e5-large", "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3", 1024,
                 prefixes=("query: ", "passage: ")),          # 모델 카드의 앞말
    EmbedderSpec("BAAI/bge-m3", "bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", 1024),   # 기준선
    # 확정 조합(retrieval_fix_v1). 문서 벡터는 1차 비교 때 만든 data/index_exp/voyage-4.npy, 질문은 input_type=query
    EmbedderSpec("voyage-4", "voyage-4", "api:voyage-4", 1024, api=True),
)}
DEFAULT_MODEL = "voyage-4"
LOCAL_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"     # 키 없는 비교용 로컬 모델. 서비스 이미지에는 넣지 않음 — Dockerfile --build-arg와 requirements-local-models.txt로

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_TIMEOUT_S = 10.0
VOYAGE_BATCH = 128
VOYAGE_PARALLEL_QUERIES = 8  # 질문 여러 개를 동시에 보내는 상한(`EMBED_KEEPALIVE=1`일 때)
QUERY_VECTOR_ROLE = "query_embedding"  # 데모 녹화에서 질문 벡터 줄의 역할(backend/services/demo_replay.py)


class EmbedUnavailable(ConnectionError):
    """잠깐 뒤 다시 하면 될 수 있는 실패(연결 오류·시간 초과·429·5xx). MCP는 unavailable·retryable로 보낸다."""


class EmbedNoKey(RuntimeError):
    """VOYAGE_API_KEY가 없다. 검색은 죽지 않고 빈 결과(fallback_reason=no_key, G2 키 없는 데모)."""


class EmbedConfigError(RuntimeError):
    """키가 틀렸거나(401·403) 요청이 잘못됐다(400). 다시 해도 같다."""


class VoyageClient:
    """voyage-4 REST 호출. sentence-transformers 모델 자리에 들어간다(encode가 갈라 부른다)."""

    def __init__(self, s: "EmbedderSpec", timeout: float = VOYAGE_TIMEOUT_S):
        self.spec, self.timeout = s, timeout
        self.pinned_name, self.pinned_revision = s.name, s.revision
        self._http = None
        self._http_lock = threading.Lock()

    def _reused(self):
        """연결을 재사용하는 클라이언트. 질문마다 새로 잇는 TLS 왕복을 없앤다."""
        with self._http_lock:
            if self._http is None:
                import httpx
                self._http = httpx.Client(timeout=self.timeout, limits=httpx.Limits(max_keepalive_connections=VOYAGE_PARALLEL_QUERIES, keepalive_expiry=120.0))
            return self._http

    def _post_reused(self, texts: list[str], role: str, key: str) -> list[list[float]]:
        import httpx
        try:
            r = self._reused().post(VOYAGE_URL, json={"input": texts, "model": self.spec.name, "input_type": role},
                                    headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as e:
            raise EmbedUnavailable(f"Voyage API 연결 실패: {type(e).__name__}") from None
        if r.status_code == 429 or r.status_code >= 500:
            raise EmbedUnavailable(f"Voyage API {r.status_code}")
        if r.status_code >= 400:
            raise EmbedConfigError(f"Voyage API {r.status_code}")
        try:
            body = r.json()
            got = [x["embedding"] for x in sorted(body["data"], key=lambda x: x["index"])]
        except (ValueError, KeyError, TypeError):
            raise EmbedUnavailable("Voyage API 응답 형식 오류") from None
        if len(got) != len(texts):
            raise EmbedUnavailable(f"Voyage API 응답 개수 {len(got)} ≠ 요청 {len(texts)}")
        step_cost.record_embed(step_cost.usage_tokens(body))   # 요청 단위 임베딩 토큰 합(`usage.total_tokens`). 요청 밖이면 아무 일도 하지 않는다
        return got

    def _embed_reused(self, texts: list[str], role: str, key: str) -> np.ndarray:
        """질문이 여럿이면 하나씩 동시에 보낸다. 측정에서 3개 묶음은 1~3초, 1개는 0.35초였다. 순서는 입력과 같다."""
        if role == "query" and 1 < len(texts) <= VOYAGE_PARALLEL_QUERIES:
            with ThreadPoolExecutor(max_workers=len(texts), thread_name_prefix="voyage") as pool:   # 요청 집계(`step_cost`)가 따라가도록 컨텍스트를 복사해 넘긴다
                out = list(pool.map(lambda t, ctx: ctx.run(lambda: self._post_reused([t], role, key)[0]), texts, [contextvars.copy_context() for _ in texts]))
        else:
            out = [v for i in range(0, len(texts), VOYAGE_BATCH) for v in self._post_reused(texts[i:i + VOYAGE_BATCH], role, key)]
        m = np.asarray(out, dtype=np.float32)
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def embed(self, texts: list[str], role: str) -> np.ndarray:
        """질문(role="query")은 데모 재생·녹화를 거친다(`_replayed`, `_recorded`). 문서(role="document")는 항상 API다."""
        if role == "query":
            got = self._replayed(texts)
            if got is not None:
                return got
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise EmbedNoKey("VOYAGE_API_KEY가 없다")
        m = self._embed_remote(texts, role, key)
        if role == "query":
            self._recorded(texts, m)
        return m

    def _query_key(self, text: str) -> str:
        from backend.services.demo_replay import request_key_for
        return request_key_for(QUERY_VECTOR_ROLE, [self.spec.name, text])

    def _replayed(self, texts: list[str]) -> np.ndarray | None:
        """데모 모드(키 없음 또는 DEMO_MODE=1)에서 질문 벡터를 `data/demo_replay/`의 녹화에서 찾는다. 하나라도 없으면 None(그러면 키가 있을 때만 API)."""
        import json
        from backend.services.demo_replay import get_store
        from backend.services.llm import is_demo_mode
        if not is_demo_mode():
            return None
        store = get_store()
        rows = [store.get(self._query_key(t)) for t in texts]
        if any(r is None for r in rows):
            return None
        m = np.asarray([json.loads(r["response"]) for r in rows], dtype=np.float32)
        if m.ndim != 2 or m.shape[1] != self.spec.dim:
            return None
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def _recorded(self, texts: list[str], m: np.ndarray) -> None:
        """녹화 모드(`LLM_RECORD=1`, 데모 아님)에서 실제 API가 돌려준 질문 벡터를 LLM 응답과 같은 폴더에 덧붙인다(소수 6자리)."""
        import json
        from backend.services.demo_replay import env_flag, get_store
        from backend.services.llm import is_demo_mode
        if not env_flag("LLM_RECORD") or is_demo_mode():
            return
        store = get_store()
        for t, v in zip(texts, m):
            store.add(self._query_key(t), QUERY_VECTOR_ROLE, self.spec.name, t, json.dumps([round(float(x), 6) for x in v]))

    def _embed_remote(self, texts: list[str], role: str, key: str) -> np.ndarray:
        import http.client
        import json
        import socket
        import urllib.error
        import urllib.request
        if os.environ.get("EMBED_KEEPALIVE") == "1":
            return self._embed_reused(texts, role, key)
        out: list[list[float]] = []
        for i in range(0, len(texts), VOYAGE_BATCH):
            body = json.dumps({"input": texts[i:i + VOYAGE_BATCH], "model": self.spec.name,
                               "input_type": role}).encode("utf-8")
            req = urllib.request.Request(VOYAGE_URL, data=body, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read())
            except urllib.error.HTTPError as e:            # URLError보다 먼저(하위 클래스)
                if e.code == 429 or e.code >= 500:
                    raise EmbedUnavailable(f"Voyage API {e.code}") from None
                raise EmbedConfigError(f"Voyage API {e.code}") from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError,
                    http.client.HTTPException) as e:       # 읽다 끊김(IncompleteRead)도 연결 실패
                raise EmbedUnavailable(f"Voyage API 연결 실패: {type(e).__name__}") from None
            except ValueError:                             # 200인데 JSON이 깨짐(잘린 응답) → 다시 하면 될 수 있다
                raise EmbedUnavailable("Voyage API 응답 형식 오류(JSON)") from None
            batch = texts[i:i + VOYAGE_BATCH]
            try:
                got = [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]
            except (KeyError, TypeError):
                raise EmbedUnavailable("Voyage API 응답 형식 오류(data 없음)") from None
            if len(got) != len(batch):                     # 개수가 다르면 질문과 벡터가 어긋난다 → 쓰지 않는다
                raise EmbedUnavailable(f"Voyage API 응답 개수 {len(got)} ≠ 요청 {len(batch)}")
            step_cost.record_embed(step_cost.usage_tokens(d))   # 요청 단위 임베딩 토큰 합(`usage.total_tokens`)
            out += got
        m = np.asarray(out, dtype=np.float32)
        return m / np.linalg.norm(m, axis=1, keepdims=True)   # 1차 비교 _voyage 와 같게 길이 1로


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


# model.safetensors와 같은 가중치를 pytorch_model.bin으로도 두는 저장소. bge-m3는 bin이 유일한 가중치라 넣지 않는다.
DUPLICATE_BIN = frozenset({"intfloat/multilingual-e5-large", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"})


def ignore_patterns(name: str) -> list[str]:
    """받지 않을 파일. 받을 때와 캐시를 확인할 때 같은 목록을 써야 오프라인 확인을 통과한다(Dockerfile도 같은 규칙)."""
    return ["onnx/*", "*.onnx*", "openvino/*"] + (["pytorch_model.bin"] if name in DUPLICATE_BIN else [])


def snapshot_dir(name: str, revision: str, local_files_only: bool) -> Path:
    """그 판의 캐시 폴더. 폴더 이름(= 커밋 해시)이 요청과 다르면 멈춘다(같은 이름 다른 판이 섞이지 않게).
    transformers 5는 불러온 판을 모델에 남기지 않아 폴더에서 직접 불러 판을 보장한다(10/30 확인)."""
    from huggingface_hub import snapshot_download
    path = Path(snapshot_download(name, revision=revision, local_files_only=local_files_only,
                                  ignore_patterns=ignore_patterns(name)))
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
    """고정 판·fp32로 불러온다. 불러온 판은 model.pinned_name·pinned_revision 에 남긴다. API 모델은 호출기를 돌려준다."""
    s = spec(name)
    if s.api:
        return VoyageClient(s)
    import torch
    from sentence_transformers import SentenceTransformer
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
    if isinstance(model, VoyageClient):
        vecs = model.embed(texts, role)
        check_norms(vecs)
        if vecs.shape[1] != s.dim:
            raise ValueError(f"차원이 다르다: {s.name} 명부 {s.dim}, 실제 {vecs.shape[1]}")
        return vecs
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
    if s.api:
        return {"query": "", "document": "", "source": "api_input_type"}
    if s.prefixes:
        return {"query": s.prefixes[0], "document": s.prefixes[1], "source": "registry"}
    p = getattr(model, "prompts", None) or {}
    return {"query": p.get("query", ""), "document": p.get("document", ""), "source": "model_config"}


def check_norms(vecs: np.ndarray) -> None:
    norms = np.linalg.norm(vecs, axis=1)
    bad = int((np.abs(norms - 1) > 1e-3).sum())
    if bad:
        raise ValueError(f"길이가 1이 아닌 벡터 {bad}개 — 정규화 실패")
