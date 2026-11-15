"""검색 `search(SearchQuery) -> list[Chunk]` (docs/specs/search.md, 설계 study 쪽 design-search.md).

필터(org·as_of, 검색 전에) → 벡터 + BM25 각 SEARCH_POOL개 → RRF(k=60) → 상위 max(k, RERANK_TOP) 리랭킹 → 상위 k.
모델과 방식은 환경 변수로만 바꾼다(EMBED_MODEL, SEARCH_MODE, SEARCH_POOL, RERANK_MODEL, RERANK_TOP, QUERY_TRANSLATE, SEARCH_LINK_N).
기본(확정 조합, 2026-11-05): voyage-4 · dense_en(영어 문장 벡터) · 리랭커 없음 · k=5 · 링크 확장 L1x2.

하위 질문(SearchQuery.sub_queries, 그래프의 질문 분해): 하위 질문마다 위 과정으로 상위 k → 차례로 하나씩 번갈아 합쳐 상위 k.
k가 기본 자리 수(DEFAULT_K)보다 크면(그래프의 나뉜 질문 첫 검색 SPLIT_K) 하위 질문과 링크 확장으로 k-FULL_TAIL자리를 먼저 만들고 끝 FULL_TAIL자리를
전체 질문의 후보 목록에서 아직 없는 앞 청크로 채운다(사전 등록 62.38). k가 기본 자리 수 이하면 전체 질문 목록을 만들지 않는다(확정 조합 측정과 같다).
링크 확장(SEARCH_LINK_N=n, 0이면 끔): 상위 k 청크가 링크한 페이지의 청크(같은 org·as_of 필터) 중 상위 k에 없는 것을
전체 질문 벡터와 가까운 순으로 n개 → 뒤 n자리를 바꾼다. 둘 다 확정 조합 측정 코드(evals/retrieval/exp_decompose_v1.py)와 같다.
금액 구간 조회(SEARCH_RANGE_N=n, 기본 3, 0이면 끔, 사전 등록 62.7·62.13·62.27): 질문에 달러 금액이 있으면 상위 k가 든 페이지(질문을 나눴으면
전체 질문 벡터의 상위 k 페이지도)의 구간 행(제목 경로 끝이 '>$25K up to $50K' 같은 금액 구간) 중 그 금액이 속한 행을 표마다 하나씩 골라, 질문이 이름을 부른 표
(ranges.table_named: `approver`와 `Approving expense`처럼 같은 낱말)를 먼저, 그 안에서 전체 질문 벡터와 가까운 순으로 n개까지 뒤 자리를 바꾼다(ranges.py).

1차 비교(evals/retrieval/experiment_v1.py)와 같은 점수가 나오게 둔 것:
- BM25 토큰화 `_tokens`(소문자 [a-z0-9]+, 한 글자·불용어 뺌), 상위 고르기 `top_positions`(0점도 후보에 듦, numpy 순서 그대로).
- RRF 동점은 먼저 들어온 순서(벡터 목록 → BM25 목록). 리랭커 동점은 원래 순위.
- 벡터만 쓰는 방식은 상위 n = max(k, RERANK_TOP)개만, 하이브리드는 양쪽 SEARCH_POOL개씩.
다른 점: 벡터 동점(본문이 같은 청크)은 chunk_id 순으로 깬다(DB는 동점 순서를 정해 주지 않는다, rag3-12 Step 2).

판 유효 구간: as_of가 없으면 valid_to가 빈 현재 판, 있으면 valid_from <= as_of < valid_to (Spec Happy Path 2).
"""
from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from backend.rag.retrieve import hedge as hedge_mod
from backend.rag.retrieve import ranges
from backend.rag.retrieve.embed import EmbedNoKey
from backend.schemas.chunk import DEFAULT_K, Chunk, SearchQuery
from backend.services import llm_trace, step_cost

log = logging.getLogger(__name__)

MODES = ("hybrid_ko_kw", "dense_en", "bm25_kw", "dense_ko")
BM25_MODES = ("hybrid_ko_kw", "bm25_kw")     # BM25를 쓰는 방식. 내림(fallback)은 dense_ko로만 가므로 나머지는 BM25를 부르지 않는다
RRF_K = 60
_STOP = set("a an the of to in on for and or is are be by with what how when who which do does can if it at as from this that".split())
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- 설정 ----------

@dataclass(frozen=True)
class SearchConfig:
    embed_model: str
    mode: str = "dense_en"
    pool: int = 100
    rerank_model: str = "none"
    rerank_top: int = 10
    translate: bool = True
    link_n: int = 2          # 링크 확장으로 바꿀 뒤 자리 수(확정 조합 L1x2 = 2, PREREGISTER #8). 0이면 끔
    link_keep_per_sub: int = 2  # 나뉜 질문은 하위 질문마다 이만큼 자리를 지키고 남은 자리만 링크로 바꾼다. 0이면 지키지 않는다(#9 측정과 같음)
    range_n: int = 3         # 금액 구간 조회로 채울 뒤 자리 수 상한(사전 등록 62.7, 62.13에서 2→3). 질문에 금액이 없으면 쓰지 않는다. 0이면 끔(SEARCH_RANGE_N=0)
    hedge: bool = False      # 사전 등록 62.14 `SEARCH_HEDGE=1`: 질문 임베딩 + 벡터 질의가 hedge_s초 안에 안 오면 같은 일을 한 번 더 보내 먼저 온 결과를 쓴다. 기본 꺼짐
    hedge_s: float = 1.5     # `SEARCH_HEDGE_S`

    @classmethod
    def from_env(cls) -> "SearchConfig":
        from backend.rag.retrieve import embed, hedge, rerank
        cfg = cls(embed_model=embed.spec().name,
                  mode=os.environ.get("SEARCH_MODE") or "dense_en",
                  pool=int(os.environ.get("SEARCH_POOL") or 100),
                  rerank_model=rerank.model_name(),
                  rerank_top=int(os.environ.get("RERANK_TOP") or 10),
                  translate=(os.environ.get("QUERY_TRANSLATE") or "1") != "0",
                  link_n=int(os.environ.get("SEARCH_LINK_N") or 2),
                  range_n=int(os.environ.get("SEARCH_RANGE_N") or 3),  # 키 없는 데모도 서비스와 같은 3이다(녹화도 3으로 만든다)
                  hedge=hedge.enabled(), hedge_s=hedge.hedge_seconds())
        cfg.check()
        return cfg

    def check(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"모르는 SEARCH_MODE: {self.mode} (후보: {', '.join(MODES)})")
        if self.pool < 1 or self.rerank_top < 1:
            raise ValueError(f"SEARCH_POOL·RERANK_TOP은 1 이상: {self.pool}, {self.rerank_top}")
        if self.link_n < 0:
            raise ValueError(f"SEARCH_LINK_N은 0 이상: {self.link_n}")
        if self.range_n < 0:
            raise ValueError(f"SEARCH_RANGE_N은 0 이상: {self.range_n}")
        if not self.hedge_s > 0:
            raise ValueError(f"SEARCH_HEDGE_S는 0보다 커야 한다: {self.hedge_s}")


# ---------- 기록 ----------

@dataclass
class SearchTrace:
    """검색 한 번의 기록. 본문·프롬프트는 남기지 않는다(rag3-11). 그래프 쪽이 last_search_trace()로 읽어 트레이스에 붙인다."""
    embed_model: str
    rerank_model: str
    requested_mode: str
    mode: str = ""
    fallback: str | None = None          # dense_ko로 내렸으면 "dense_ko"
    fallback_reason: str | None = None   # translate_off | demo_no_record | invalid | timeout | error | cost_cap | no_key
    translation_source: str | None = None
    n_filtered: int = 0                  # 필터 뒤 대상 청크 수 (0이면 진짜 없음, rag4-09)
    n_dense: int = 0
    n_bm25: int = 0
    n_sub: int = 0                       # 하위 질문 수(0이면 나누지 않음)
    n_link: int = 0                      # 링크 확장으로 바꾼 자리 수
    n_range: int = 0                     # 금액 구간 조회로 바꾼 자리 수
    n_returned: int = 0
    hedged: bool = False                 # 사전 등록 62.14: 임베딩 + 벡터 질의에 같은 일을 한 번 더 보냈는가(`SEARCH_HEDGE=1`)
    hedge_winner: int = 0                # 이긴 시도(0 = 처음 보낸 것, 1 = 나중에 보낸 것)
    ms: dict = field(default_factory=dict)


_last: contextvars.ContextVar[SearchTrace | None] = contextvars.ContextVar("last_search_trace", default=None)


def last_search_trace() -> SearchTrace | None:
    return _last.get()


# ---------- 저장소 ----------

Key = tuple[str, str]   # (chunk_id, version_id)


@dataclass
class RowMeta:
    """BM25 색인과 필터 가면에 쓰는 행 정보(기동 때 한 번 읽는다)."""
    keys: list[Key]
    org: np.ndarray          # str
    valid_from: np.ndarray   # datetime64[D]
    valid_to: np.ndarray     # datetime64[D], 현재 판은 NaT
    texts: list[str]


class Store(Protocol):
    def meta(self) -> dict | None: ...
    def generation(self) -> int: ...
    def row_meta(self) -> RowMeta: ...
    def vector_top(self, qvec: np.ndarray, embedder: str, org: str | None, as_of: str | None, n: int) -> list[tuple[Key, float]]: ...
    def page_vector_top(self, qvec: np.ndarray, embedder: str, rule_seqs: list[int], org: str | None, as_of: str | None,
                        exclude: list[Key], n: int) -> list[tuple[Key, float]]: ...
    def fetch(self, keys: list[Key]) -> dict[Key, dict]: ...
    def get_translation(self, query_sha256: str, model: str) -> dict | None: ...
    def put_translation(self, query_sha256: str, model: str, kind: str, text: str) -> None: ...


def valid_mask(meta: RowMeta, org: str | None, as_of: str | None) -> np.ndarray:
    """D3 필터. SQL(PgStore)과 같은 규칙을 numpy로."""
    if as_of is None:
        m = np.isnat(meta.valid_to)
    else:
        d = np.datetime64(as_of, "D")
        m = (meta.valid_from <= d) & (np.isnat(meta.valid_to) | (d < meta.valid_to))
    if org is not None:
        m &= meta.org == org
    return m


class MemoryStore:
    """numpy 저장소: 테스트와 DB 대조(V2)용. 필터·동점 규칙은 PgStore와 같다."""

    def __init__(self, rows: list[dict], vectors: np.ndarray, embedder: str, meta: dict | None = None):
        if len(rows) != len(vectors):
            raise ValueError(f"행 {len(rows)} ≠ 벡터 {len(vectors)}")
        self.rows = rows
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.embedder = embedder
        self._meta = meta
        self._gen = 1
        self.translations: dict[tuple[str, str], dict] = {}
        self._idx = {(r["chunk_id"], r["version_id"]): i for i, r in enumerate(rows)}
        self._rm = RowMeta(
            keys=[(r["chunk_id"], r["version_id"]) for r in rows],
            org=np.array([r["org"] for r in rows], dtype=object),
            valid_from=np.array([r["valid_from"] for r in rows], dtype="datetime64[D]"),
            valid_to=np.array([r.get("valid_to") or "NaT" for r in rows], dtype="datetime64[D]"),
            texts=[r["text"] for r in rows])
        self._seq = np.array([int(r["rule_seq"]) for r in rows], dtype=np.int64)

    def meta(self):
        return self._meta

    def generation(self):
        return self._gen

    def row_meta(self):
        return self._rm

    def vector_top(self, qvec, embedder, org, as_of, n):
        if embedder != self.embedder:
            raise ValueError(f"저장소 벡터는 {self.embedder}, 요청은 {embedder}")
        pos = np.flatnonzero(valid_mask(self._rm, org, as_of))
        if not len(pos):
            return []
        s = self.vectors[pos] @ np.asarray(qvec, dtype=np.float32)
        order = sorted(range(len(pos)), key=lambda j: (-s[j], self._rm.keys[pos[j]][0]))[:n]
        return [(self._rm.keys[pos[j]], float(s[j])) for j in order]

    def page_vector_top(self, qvec, embedder, rule_seqs, org, as_of, exclude, n):
        """그 페이지들의 청크 중(필터 안, exclude 밖) 질문과 가까운 n개. 동점은 chunk_id 순(vector_top과 같다)."""
        if embedder != self.embedder:
            raise ValueError(f"저장소 벡터는 {self.embedder}, 요청은 {embedder}")
        m = valid_mask(self._rm, org, as_of) & np.isin(self._seq, np.asarray(list(rule_seqs), dtype=np.int64))
        ex = set(exclude)
        pos = np.asarray([p for p in np.flatnonzero(m) if self._rm.keys[p] not in ex], dtype=np.int64)
        if not len(pos):
            return []
        s = self.vectors[pos] @ np.asarray(qvec, dtype=np.float32)
        order = sorted(range(len(pos)), key=lambda j: (-s[j], self._rm.keys[pos[j]][0]))[:n]
        return [(self._rm.keys[pos[j]], float(s[j])) for j in order]

    def band_headings(self, rule_seqs, org, as_of):
        """금액 구간 조회(`Searcher._range_expand`) 후보: 그 페이지들의 청크 중(필터 안) 제목 경로에 '$'가 든 것의 (키, 제목 경로), ord 순."""
        m = valid_mask(self._rm, org, as_of) & np.isin(self._seq, np.asarray(list(rule_seqs), dtype=np.int64))
        return [(self._rm.keys[i], self.rows[i].get("article") or "") for i in np.flatnonzero(m) if "$" in (self.rows[i].get("article") or "")]

    def key_scores(self, qvec, embedder, keys):
        """주어진 청크들의 질문 벡터 점수(내적, vector_top과 같은 값)."""
        if embedder != self.embedder:
            raise ValueError(f"저장소 벡터는 {self.embedder}, 요청은 {embedder}")
        q = np.asarray(qvec, dtype=np.float32)
        return {k: float(self.vectors[self._idx[k]] @ q) for k in keys if k in self._idx}

    def page_chunks(self, rule_seq, version_id):
        """한 페이지 판의 청크 (키, 절 제목) 목록, ord 순(없으면 행 순서). R3 도입부 채우기(`Searcher.intro_fill`)가 쓴다."""
        pos = [i for i, r in enumerate(self.rows) if int(r["rule_seq"]) == int(rule_seq) and r["version_id"] == version_id]
        pos.sort(key=lambda i: (int(self.rows[i].get("ord", i)), self.rows[i]["chunk_id"]))
        return [(self._rm.keys[i], self.rows[i].get("article")) for i in pos]

    def fetch(self, keys):
        return {k: self.rows[self._idx[k]] for k in keys if k in self._idx}

    def get_translation(self, query_sha256, model):
        return self.translations.get((query_sha256, model))

    def put_translation(self, query_sha256, model, kind, text):
        self.translations.setdefault((query_sha256, model), {})[kind] = text


_FILTER = """(%(org)s::text IS NULL OR d.org = %(org)s::text)
  AND (CASE WHEN %(as_of)s::date IS NULL THEN v.valid_to IS NULL
            ELSE v.valid_from <= %(as_of)s::date AND (v.valid_to IS NULL OR %(as_of)s::date < v.valid_to) END)"""
_JOIN = """FROM chunks c
JOIN versions v ON v.rule_seq = c.rule_seq AND v.version_id = c.version_id
JOIN docs d ON d.rule_seq = c.rule_seq"""


# HNSW 색인(db/manual/chunks_hnsw_voyage4.sql)이 있는 모델과 차원. chunks.embedding은 차원 없는 vector라 색인은 식 `embedding::halfvec(1024)`로 만들고,
# 질의도 같은 식을 써야 색인을 탄다. 다른 모델(다른 차원)은 이 식이 오류가 나므로 아래 목록에 있는 모델만 새 질의를 쓴다.
HNSW_DIMS = {"voyage-4": 1024}
HNSW_EF_SEARCH = 200      # 로컬 측정(2026-11-05): 200이면 필터가 넓을 때 색인, 좁을 때 계획이 전수 비교로 가서 둘 다 전수와 상위 5 일치
HNSW_ITERATIVE = "strict_order"   # 필터로 5개 미만이 되면 색인을 더 걷는다(pgvector 0.8). 순서 보장


class PgStore:
    """pgvector 저장소. 기본은 전수 비교. SEARCH_HNSW=1이고 모델이 HNSW_DIMS에 있으면 HNSW 색인 질의(색인이 없어도 결과는 같고 느릴 뿐).
    값은 SQL 문장에 이어 붙이지 않고 자리(%(이름)s)로 넘긴다. Supabase transaction pooler 대비 prepare_threshold=None(rag3-12).
    풀러에서도 SET이 남지 않도록 색인 설정은 트랜잭션 안 set_config(.., true)(= SET LOCAL)로만 준다."""

    hnsw = False

    def __init__(self, url: str):
        from pgvector.psycopg import register_vector
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(url, min_size=1, max_size=4, open=True,
                                   kwargs={"prepare_threshold": None}, configure=register_vector)
        self.hnsw = os.environ.get("SEARCH_HNSW") == "1"

    @classmethod
    def from_env(cls) -> "PgStore":
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL이 없다")
        return cls(url)

    def close(self) -> None:
        """풀을 닫는다(연결·백그라운드 스레드 정리). warmup이 실패했을 때 부른다."""
        self.pool.close()

    def _all(self, sql: str, params=None) -> list[tuple]:
        """읽기 한 문장. BEGIN·COMMIT 왕복을 빼려고 이 문장 동안만 autocommit으로 둔다(바꾸기 자체는 통신이 없다).
        풀의 기본은 그대로라, 여러 문장을 한 트랜잭션으로 묶는 쪽의 동작은 바뀌지 않는다."""
        with self.pool.connection() as conn:
            conn.set_autocommit(True)
            try:
                return conn.execute(sql, params or {}).fetchall()
            finally:
                conn.set_autocommit(False)

    def meta(self):
        rows = self._all("SELECT embedder, revision, dim, prefixes, status, generation FROM index_meta WHERE id = 1")
        if not rows:
            return None
        e, r, d, p, s, g = rows[0]
        return {"embedder": e, "revision": r, "dim": d, "prefixes": p, "status": s, "generation": g}

    def generation(self):
        rows = self._all("SELECT generation FROM index_meta WHERE id = 1")
        return int(rows[0][0]) if rows else 0

    def row_meta(self, with_text: bool = True):
        """with_text=False면 본문을 읽지 않고 texts를 비워 둔다(BM25를 쓰지 않는 방식은 필터 가면만 쓴다)."""
        text = ", c.text" if with_text else ""
        rows = self._all(f"SELECT c.chunk_id, c.version_id, d.org, v.valid_from, v.valid_to{text} {_JOIN} ORDER BY c.ord, c.chunk_id")
        return RowMeta(keys=[(r[0], r[1]) for r in rows],
                       org=np.array([r[2] for r in rows], dtype=object),
                       valid_from=np.array([r[3] for r in rows], dtype="datetime64[D]"),
                       valid_to=np.array([r[4] if r[4] is not None else "NaT" for r in rows], dtype="datetime64[D]"),
                       texts=[r[5] for r in rows] if with_text else [])

    # 거리 식은 안쪽에서 한 번만 쓴다. SELECT와 ORDER BY에 따로 쓰면 행마다 TOAST 읽기와 거리 계산이 두 번 일어난다.
    # 안쪽에 LIMIT이 있어 계획기가 서브쿼리를 펼치지 않는다. 정렬 열쇠(거리, chunk_id)는 그대로이고 점수는 같은 거리의 부호만 바꾼 값이다.
    def vector_top(self, qvec, embedder, org, as_of, n):
        params = {"q": np.asarray(qvec, dtype=np.float32), "embedder": embedder, "org": org, "as_of": as_of, "n": n}
        dim = HNSW_DIMS.get(embedder) if self.hnsw else None
        if dim:
            # 색인 식과 같은 `embedding::halfvec(dim)`. 색인을 타려면 안쪽 정렬은 거리 하나뿐이어야 한다(chunk_id를 더하면 색인 순서를 그대로 못 쓴다).
            # 점수는 반정밀도 거리이고, 같은 거리의 동점은 바깥 ORDER BY가 chunk_id 순으로 깬다.
            # 전수 질의와 달리 안쪽 LIMIT에서 동점 경계가 갈릴 수 있다(색인은 근사라 어차피 보장하지 않는다).
            t = f"halfvec({int(dim)})"
            sql = f"""SELECT chunk_id, version_id, -dist AS score FROM (
SELECT c.chunk_id, c.version_id, c.embedding::{t} <#> %(q)s::{t} AS dist {_JOIN}
WHERE c.embedder = %(embedder)s AND {_FILTER}
ORDER BY dist LIMIT %(n)s) s
ORDER BY dist, chunk_id"""
            acquired = time.perf_counter()
            with self.pool.connection() as conn:     # 이 블록 하나가 트랜잭션(풀 기본. `_all`이 autocommit을 되돌려 둔다): 끝나면 COMMIT, 설정은 거기서 사라진다
                conn.execute("SELECT set_config('hnsw.ef_search', %(ef)s, true), set_config('hnsw.iterative_scan', %(it)s, true)",
                             {"ef": str(HNSW_EF_SEARCH), "it": HNSW_ITERATIVE})
                ran = time.perf_counter()
                rows = conn.execute(sql, params).fetchall()
                _note_db(ran - acquired, time.perf_counter() - ran)
            return [((r[0], r[1]), float(r[2])) for r in rows]
        sql = f"""SELECT chunk_id, version_id, -dist AS score FROM (
SELECT c.chunk_id, c.version_id, c.embedding <#> %(q)s::vector AS dist {_JOIN}
WHERE c.embedder = %(embedder)s AND {_FILTER}
ORDER BY dist, c.chunk_id LIMIT %(n)s) s
ORDER BY dist, chunk_id"""
        rows = self._all(sql, params)
        return [((r[0], r[1]), float(r[2])) for r in rows]

    def warm(self, embedder: str, as_of: str | None = None, n: int = 150) -> dict:
        """색인 페이지를 미리 읽는다. 표에 있는 벡터로 묻고 결과는 버린다(읽기 전용, 임베딩 API를 부르지 않는다). 첫 질의가 찬 캐시를 만나 몇 초 걸리는 것을 줄이고, 연결도 미리 연다."""
        if not self.hnsw:
            return {"queries": 0, "seconds": 0.0}
        t = time.perf_counter()
        rows = self._all("SELECT embedding::text FROM chunks WHERE embedder = %(e)s AND ord %% 211 = 3 LIMIT %(n)s", {"e": embedder, "n": n})
        vectors = [np.asarray(json.loads(r[0]), dtype=np.float32) for r in rows]
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="warm") as pool:
            list(pool.map(lambda v: self.vector_top(v, embedder, None, as_of, 5), vectors))
        return {"queries": len(vectors), "seconds": round(time.perf_counter() - t, 2)}

    def page_vector_top(self, qvec, embedder, rule_seqs, org, as_of, exclude, n):
        """링크 확장 후보: 그 페이지들의 청크 중 같은 필터(_FILTER)를 지나고 exclude에 없는 것, 거리순·동점 chunk_id."""
        if not rule_seqs:
            return []
        sql = f"""SELECT chunk_id, version_id, -dist AS score FROM (
SELECT c.chunk_id, c.version_id, c.embedding <#> %(q)s::vector AS dist {_JOIN}
WHERE c.embedder = %(embedder)s AND c.rule_seq = ANY(%(seqs)s::bigint[]) AND {_FILTER}
  AND NOT EXISTS (SELECT 1 FROM unnest(%(ex_i)s::text[], %(ex_v)s::text[]) AS x(chunk_id, version_id)
                  WHERE x.chunk_id = c.chunk_id AND x.version_id = c.version_id)
ORDER BY dist, c.chunk_id LIMIT %(n)s) s
ORDER BY dist, chunk_id"""
        rows = self._all(sql, {"q": np.asarray(qvec, dtype=np.float32), "embedder": embedder,
                               "seqs": [int(s) for s in rule_seqs], "org": org, "as_of": as_of,
                               "ex_i": [k[0] for k in exclude], "ex_v": [k[1] for k in exclude], "n": n})
        return [((r[0], r[1]), float(r[2])) for r in rows]

    def band_headings(self, rule_seqs, org, as_of):
        """금액 구간 조회 후보: 그 페이지들의 청크 중 같은 필터(_FILTER)를 지나고 제목 경로에 '$'가 든 것의 (키, 제목 경로), ord·chunk_id 순(MemoryStore와 같다)."""
        if not rule_seqs:
            return []
        sql = f"""SELECT c.chunk_id, c.version_id, c.article {_JOIN}
WHERE c.rule_seq = ANY(%(seqs)s::bigint[]) AND strpos(coalesce(c.article, ''), '$') > 0 AND {_FILTER}
ORDER BY c.ord, c.chunk_id"""
        return [((r[0], r[1]), r[2] or "") for r in self._all(sql, {"seqs": [int(s) for s in rule_seqs], "org": org, "as_of": as_of})]

    def key_scores(self, qvec, embedder, keys):
        """주어진 청크들의 질문 벡터 점수(`-(embedding <#> q)` = 내적, vector_top의 score와 같은 값)."""
        if not keys:
            return {}
        sql = """SELECT c.chunk_id, c.version_id, -(c.embedding <#> %(q)s::vector) AS score
FROM chunks c JOIN unnest(%(ids)s::text[], %(vers)s::text[]) AS k(chunk_id, version_id)
  ON k.chunk_id = c.chunk_id AND k.version_id = c.version_id
WHERE c.embedder = %(embedder)s"""
        rows = self._all(sql, {"q": np.asarray(qvec, dtype=np.float32), "embedder": embedder,
                               "ids": [k[0] for k in keys], "vers": [k[1] for k in keys]})
        return {(r[0], r[1]): float(r[2]) for r in rows}

    def page_chunks(self, rule_seq, version_id):
        """한 페이지 판의 청크 (키, 절 제목) 목록, ord·chunk_id 순(MemoryStore와 같다)."""
        sql = "SELECT c.chunk_id, c.version_id, c.article FROM chunks c WHERE c.rule_seq = %(s)s AND c.version_id = %(v)s ORDER BY c.ord, c.chunk_id"
        return [((r[0], r[1]), r[2]) for r in self._all(sql, {"s": int(rule_seq), "v": version_id})]

    def fetch(self, keys):
        if not keys:
            return {}
        sql = f"""SELECT c.chunk_id, c.version_id, d.org, c.rule_seq, d.title, c.article, v.version_date, d.fetched_at,
       c.kind, c.text, c.source_url, c.text_sha256, v.version_date_before, c.line_start, c.line_end, c.link_targets {_JOIN}
JOIN unnest(%(ids)s::text[], %(vers)s::text[]) AS k(chunk_id, version_id)
  ON k.chunk_id = c.chunk_id AND k.version_id = c.version_id"""
        rows = self._all(sql, {"ids": [k[0] for k in keys], "vers": [k[1] for k in keys]})
        cols = ("chunk_id", "version_id", "org", "rule_seq", "rule_title", "article", "version_date", "fetched_at",
                "kind", "text", "source_url", "text_sha256", "version_date_before", "line_start", "line_end", "link_targets")
        return {(r[0], r[1]): dict(zip(cols, r)) for r in rows}

    def get_translation(self, query_sha256, model):
        rows = self._all("SELECT keywords, sentence FROM query_translations WHERE query_sha256 = %(s)s AND model = %(m)s",
                         {"s": query_sha256, "m": model})
        return {"keywords": rows[0][0], "sentence": rows[0][1]} if rows else None

    def put_translation(self, query_sha256, model, kind, text):
        if kind not in ("keywords", "sentence"):
            raise ValueError(kind)
        with self.pool.connection() as conn:   # 같은 질문이 동시에 와도 한 줄만, 먼저 적힌 값을 남긴다
            conn.execute(f"""INSERT INTO query_translations (query_sha256, model, {kind}) VALUES (%(s)s, %(m)s, %(t)s)
ON CONFLICT (query_sha256, model) DO UPDATE SET {kind} = COALESCE(query_translations.{kind}, EXCLUDED.{kind})""",
                         {"s": query_sha256, "m": model, "t": text})


# ---------- 부품 ----------

def tokens(text: str) -> list[str]:
    """experiment_v1._tokens 와 같다."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in _STOP]


def top_positions(scores: np.ndarray, n: int) -> list[int]:
    """experiment_v1._top 과 같다(상위 n, 점수 내림차순)."""
    if len(scores) == 0 or n <= 0:
        return []
    idx = np.argpartition(-scores, min(n, len(scores) - 1))[:n]
    return [int(i) for i in idx[np.argsort(-scores[idx])]]


def rrf(rankings: list[list[Key]], k: int = RRF_K) -> list[tuple[Key, float]]:
    """r위(1부터)에 1/(k+r). 점수 내림차순, 동점은 먼저 들어온 순서(앞 목록 먼저)."""
    fused: dict[Key, float] = {}
    for ranking in rankings:
        for r, key in enumerate(ranking, 1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + r)
    return sorted(fused.items(), key=lambda x: -x[1])


MAX_SUB_QUERIES = 3       # 측정 분해 규칙: 서로 다른 사실이 둘 이상일 때만, 최대 3개(exp_decompose_v1.py)
# 나뉜 질문을 기본 자리 수(DEFAULT_K)보다 넓혀 찾을 때 전체 질문의 후보 목록이 받는 끝자리 수(사전 등록 62.38).
# 전체 질문 목록을 번갈아 합치기의 첫 목록으로 두면 k=8에서 하위 질문마다 2자리만 남는다. 사전 등록 평가셋에서는 두 위치가 같았다:
# 첫 검색 문맥의 정답 위치가 v2 36/37, 검증 14/16이고 분해 표본 8개 합도 v2 270/296, 검증 104/128로 같아, 평가셋은 두 방식을 가르지 못했다.
# 동점을 가른 것은 평가셋 밖의 데모 질문 "5만 달러 승인"이다(정답인 승인 권한표 행 둘이 하위 질문 목록 3~5위라 첫 목록으로 두면 둘 다 빠졌고(0/2), 끝 1자리 방식은 2/2).
# 그 데모 질문은 달러 금액이 있어 결정 0105(사전 등록 62.43)로 k=5가 되므로 지금은 이 끝자리 규칙을 타지 않는다. 이 규칙은 달러 금액이 없는 나뉜 질문의 k=8 첫 검색에만 쓰이고, 끝 1자리를 고른 근거는 그 데모 사례 하나다
FULL_TAIL = 1
MAX_QUERY_CHARS = 1000    # MCP 도구 입력 한도와 같다(extras/mcp_skill/mcp_server/server.py MAX_QUERY)


def roundrobin(lists: list[list[Key]], k: int) -> list[Key]:
    """목록들을 차례로 하나씩 번갈아 합친다. 이미 든 것은 건너뛴다(exp_decompose_v1.roundrobin과 같다)."""
    out: list[Key] = []
    r, longest = 0, max((len(x) for x in lists), default=0)
    while len(out) < k and r < longest:
        for x in lists:
            if r < len(x) and x[r] not in out:
                out.append(x[r])
                if len(out) == k:
                    break
        r += 1
    return out


def fill_tail(top: list[Key], lists: list[list[Key]], k: int) -> list[Key]:
    """`top` 뒤를 k개가 될 때까지 채운다. 목록을 앞에서부터 차례로 쓰고(앞 목록을 다 본 뒤 다음 목록), 이미 든 것은 건너뛴다."""
    out = list(top)
    for x in lists:
        for key in x:
            if len(out) >= k:
                return out
            if key not in out:
                out.append(key)
    return out


def sub_merge_enabled() -> bool:
    """`SEARCH_SUB_MERGE=1`일 때만 분해 검색 합치기를 바꾼다(조사 해법, Ammann 2025). 기본 꺼짐이고 끄면 하위 질문만 번갈아 합친다."""
    return (os.environ.get("SEARCH_SUB_MERGE") or "").strip() == "1"


def merge_by_score(lists: list[list[Key]], scores: dict[Key, float], k: int) -> list[Key]:
    """lists[0]은 전체 질문, lists[1:]은 하위 질문의 상위 목록이다. 하위 질문마다 아직 안 든 첫 청크로 한 자리씩 먼저 채우고,
    남은 자리는 모든 목록(전체 질문 포함)의 후보를 점수(질의 벡터와의 유사도 중 큰 값) 순으로 채운다. 점수가 없는 후보는 뒤에, 같은 점수는 먼저 나온 순이다."""
    out: list[Key] = []
    for sub in lists[1:]:
        first = next((x for x in sub if x not in out), None)
        if first is not None and len(out) < k:
            out.append(first)
    pool: list[Key] = []
    for x in roundrobin(lists, sum(len(x) for x in lists)):
        if x not in out:
            pool.append(x)
    pool.sort(key=lambda x: -scores.get(x, float("-inf")))  # 안정 정렬이라 같은 점수는 번갈아 나온 순서를 지킨다
    return (out + pool)[:k]


SIBLING_POOL = 300  # 형제 절 후보를 고를 때 그 페이지들에서 질문과 가까운 순으로 볼 청크 수


def _path(row: dict) -> tuple[str, ...]:
    return tuple(p.strip() for p in (row.get("article") or "").split(" > ") if p.strip())


def sibling_firsts(context: list[dict], rows: list[dict], scores: dict[Key, float], n: int) -> list[Key]:
    """(나) 형제 절(parent-document 방식): 문맥 청크와 같은 페이지, 같은 상위 제목 아래, 같은 깊이의 다른 절마다 첫 청크(가장 앞 줄) 하나를 후보로 하고,
    질의 유사도가 높은 순으로 n개를 고른다. 문맥에 이미 든 절과 청크는 빼고, 제목 경로가 없는 청크(페이지 첫머리)는 형제를 만들지 않는다."""
    have = {(c["chunk_id"], c["version_id"]) for c in context}
    have_sec = {(c["rule_seq"], _path(c)) for c in context}
    want = {(c["rule_seq"], _path(c)[:-1], len(_path(c))) for c in context if _path(c)}
    first: dict[tuple, dict] = {}
    for r in rows:
        p = _path(r)
        sec = (r["rule_seq"], p)
        if not p or sec in have_sec or (r["rule_seq"], p[:-1], len(p)) not in want:
            continue
        cur = first.get(sec)
        if cur is None or (r.get("line_start") or 0) < (cur.get("line_start") or 0):
            first[sec] = r
    keys = [(r["chunk_id"], r["version_id"]) for r in first.values()]
    keys = [k for k in keys if k not in have]
    keys.sort(key=lambda k: -scores.get(k, float("-inf")))
    return keys[:n]


def check_query(q: SearchQuery) -> None:
    if not q.query or not q.query.strip():
        raise ValueError("빈 질문")
    if q.k < 1:
        raise ValueError(f"k는 1 이상: {q.k}")
    subs = q.sub_queries or []                    # None과 []는 "나누지 않음"
    if subs:
        if not 2 <= len(subs) <= MAX_SUB_QUERIES:
            raise ValueError(f"sub_queries는 2~{MAX_SUB_QUERIES}개: {len(subs)}개")
        for s in subs:
            if not isinstance(s, str) or not s.strip() or len(s) > MAX_QUERY_CHARS:
                raise ValueError(f"sub_queries 항목은 1~{MAX_QUERY_CHARS}자 글")
    if q.as_of is not None:
        if not _DATE.match(q.as_of):
            raise ValueError(f"as_of는 YYYY-MM-DD: {q.as_of!r}")
        dt.date.fromisoformat(q.as_of)   # 2026-02-30 같은 날짜도 멈춘다


def to_chunk(row: dict) -> Chunk:
    return Chunk(chunk_id=row["chunk_id"], org=row["org"], rule_seq=int(row["rule_seq"]), rule_title=row["rule_title"],
                 article=row.get("article"), version_id=row["version_id"], version_date=str(row["version_date"]),
                 fetched_at=str(row["fetched_at"]), kind=row["kind"], text=row["text"], source_url=row["source_url"],
                 text_sha256=row.get("text_sha256"), version_date_before=bool(row.get("version_date_before", False)),
                 line_start=row.get("line_start"), line_end=row.get("line_end"))


# ---------- 검색기 ----------

class Searcher:
    """기동 때 한 번 만든다(모델·BM25 색인 올리기). search()는 여러 요청이 함께 불러도 된다."""

    def __init__(self, cfg: SearchConfig, store: Store, embedder=None, reranker=None, translator=None,
                 check_meta: bool = True, bm25: tuple[RowMeta, object] | None = None):
        """embedder: (질문들 -> 벡터) 함수. reranker: .score(질문, 본문들) 를 가진 객체 또는 None.
        translator: (질문, kind) -> translate.Result 함수. 주지 않으면 실제 모델·llm.py를 쓴다.
        bm25: 같은 행으로 이미 만든 (RowMeta, BM25 색인). make_search가 조합마다 다시 만들지 않으려고 넘긴다."""
        cfg.check()
        self.cfg, self.store = cfg, store
        if check_meta:
            self._check_meta()
        if embedder is None:
            from backend.rag.retrieve import embed
            model = embed.load_model(cfg.embed_model)
            used = embed.used_prefixes(model, embed.spec(cfg.embed_model))
            m = store.meta() or {}
            if check_meta and (m.get("prefixes") or {}).get("query", used["query"]) != used["query"]:
                raise RuntimeError(f"질문 앞말이 색인 장부와 다르다: 장부 {m.get('prefixes')}, 지금 {used}")
            embedder = lambda texts: embed.encode_queries(model, texts)  # noqa: E731
        self.embed = embedder
        if reranker is None and cfg.rerank_model != "none":
            from backend.rag.retrieve import rerank
            reranker = rerank.load_reranker(cfg.rerank_model)
        self.reranker = reranker if cfg.rerank_model != "none" else None
        if translator is None:
            from backend.rag.retrieve import translate
            translator = lambda query, kind: translate.translate(query, kind, store)  # noqa: E731
        self.translator = translator
        self._lock = threading.Lock()
        self._qvecs: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()  # (방식, 질문) -> 벡터. R3가 같은 질문을 다시 임베딩하지 않게 한다
        if bm25 is None:
            self._build_bm25()
        else:
            rm, index = bm25
            if rm.keys != store.row_meta().keys:
                raise ValueError("넘겨받은 BM25 색인과 저장소 행이 다르다")
            self._rm, self._bm25, self._gen = rm, index, store.generation()

    def _check_meta(self) -> None:
        """D8 장부 대조: 적재가 끝났고(ready) 지금 모델·판·차원과 같아야 뜬다."""
        from backend.rag.retrieve import embed
        m = self.store.meta()
        if not m or m.get("status") != "ready":
            raise RuntimeError(f"색인이 준비되지 않았다(index_meta {m and m.get('status')}). load_snapshot을 먼저 돌린다")
        s = embed.spec(self.cfg.embed_model)
        want = {"embedder": s.name, "revision": embed.revision_for(s), "dim": s.dim}
        got = {k: m.get(k) for k in want}
        if got != want:
            raise RuntimeError(f"색인 장부와 지금 설정이 다르다: 장부 {got}, 설정 {want}")

    def _build_bm25(self) -> None:
        from rank_bm25 import BM25Okapi
        t = time.perf_counter()
        # DB에서는 BM25를 쓰는 방식일 때만 본문 전체를 읽는다. MemoryStore(비교 입구)는 조합끼리 색인을 같이 쓰므로 그대로 만든다.
        lean = isinstance(self.store, PgStore) and self.cfg.mode not in BM25_MODES
        rm = self.store.row_meta(with_text=False) if lean else self.store.row_meta()
        bm25 = BM25Okapi([tokens(x) for x in rm.texts]) if rm.texts else None
        self._rm, self._bm25, self._gen = rm, bm25, self.store.generation()
        log.info("BM25 색인 %d행 %.1f초 (generation %s)", len(rm.texts), time.perf_counter() - t, self._gen)

    def _refresh(self) -> None:
        """증분 수집이 표를 바꿨으면(generation이 다르면) BM25를 다시 만든다."""
        g = self.store.generation()
        if g != self._gen:
            with self._lock:
                if g != self._gen:
                    self._build_bm25()

    def _translate_one(self, query: str, kind: str) -> tuple[str | None, str | None, str | None]:
        """(번역문, 출처, 내린 이유). 하위 질문을 동시에 번역하려고 기록(tr)을 직접 고치지 않는다."""
        if not self.cfg.translate:
            return None, None, "translate_off"
        from backend.rag.retrieve.translate import valid_english
        if valid_english(query):                                 # 그래프의 재작성 질의처럼 이미 영어면 LLM을 부르지 않는다
            return query, "as_is", None
        res = self.translator(query, kind)
        return res.text, res.source, (res.source if res.text is None else None)

    def _translate_all(self, texts: list[str], kind: str, tr: SearchTrace) -> list[str | None]:
        """전체 질문 + 하위 질문. 둘 이상이면 동시에 번역해 기다림을 한 번 분량으로(번역 한도 15초씩, translate.py)."""
        if len(texts) == 1:
            got = [self._translate_one(texts[0], kind)]
        else:
            with ThreadPoolExecutor(max_workers=len(texts)) as ex:
                got = list(ex.map(step_cost.bind(llm_trace.bind(lambda t: self._translate_one(t, kind))), texts))
        tr.translation_source = got[0][1]
        reasons = [r for _, _, r in got if r]
        if reasons:
            tr.fallback_reason = reasons[0]
        return [t for t, _, _ in got]

    def _ranked(self, text: str, trans: str | None, qvec, mode: str, q: SearchQuery, mask: np.ndarray, n: int,
                tr: SearchTrace, scores: dict[Key, float] | None = None) -> tuple[list[Key], dict[Key, dict]]:
        """질문 하나의 상위 k(벡터·BM25 → RRF → 리랭킹). 하위 질문마다 같은 과정을 돈다."""
        cfg, rm, bm25 = self.cfg, self._rm, self._bm25
        dense: list[Key] = []
        if mode != "bm25_kw":
            t = time.perf_counter()
            hits = self.store.vector_top(qvec, cfg.embed_model, q.org, q.as_of, cfg.pool if mode == "hybrid_ko_kw" else n)
            dense = [k for k, _ in hits]
            if scores is not None:                               # SEARCH_SUB_MERGE에서만 쓴다(질의마다 따로 된 dict)
                scores.update({k: float(s) for k, s in hits})
            with _TRACE_LOCK:
                tr.ms["vector"] = round(tr.ms.get("vector", 0) + _ms(t), 1)
                tr.n_dense += len(dense)

        bm: list[Key] = []
        if mode in ("hybrid_ko_kw", "bm25_kw"):
            t = time.perf_counter()
            pos = np.flatnonzero(mask)
            scores = np.asarray(bm25.get_scores(tokens(trans)), dtype=float)[pos]
            bm = [rm.keys[pos[i]] for i in top_positions(scores, cfg.pool if mode == "hybrid_ko_kw" else n)]
            tr.ms["bm25"] = round(tr.ms.get("bm25", 0) + _ms(t), 1)
            tr.n_bm25 += len(bm)

        if mode == "hybrid_ko_kw":
            cand = [k for k, _ in rrf([dense, bm])][:n]
        else:
            cand = (bm if mode == "bm25_kw" else dense)[:n]

        rows = self.store.fetch(cand)
        cand = [k for k in cand if k in rows]
        if self.reranker is not None and cand:
            t = time.perf_counter()
            sc = self.reranker.score(text, [rows[k]["text"] for k in cand])     # 질문은 한국어 원문(1차 비교와 같음)
            cand = [cand[i] for i in sorted(range(len(cand)), key=lambda i: -sc[i])]
            tr.ms["rerank"] = round(tr.ms.get("rerank", 0) + _ms(t), 1)
        return cand[: q.k], rows

    def _link_expand(self, top: list[Key], rows: dict[Key, dict], qvec, q: SearchQuery, tr: SearchTrace) -> list[Key]:
        """L1x2: 상위 k가 링크한 페이지의 청크(같은 필터, 상위 k 밖)를 전체 질문 벡터와 가까운 순으로 link_n개 → 뒤 자리를 바꾼다."""
        n = self.cfg.link_n
        if tr.n_sub:
            n = min(n, max(0, q.k - self.cfg.link_keep_per_sub * tr.n_sub))
        if not n or q.k <= n or qvec is None or not top:
            return top
        t = time.perf_counter()
        seqs = sorted({int(s) for k in top for s in (rows[k].get("link_targets") or [])})
        ext = [k for k, _ in self.store.page_vector_top(qvec, self.cfg.embed_model, seqs, q.org, q.as_of, top, n)] if seqs else []
        if ext:
            rows.update(self.store.fetch(ext))
            ext = [k for k in ext if k in rows]
        tr.n_link, tr.ms["link"] = len(ext), _ms(t)
        return top[: q.k - len(ext)] + ext if ext else top

    def _range_expand(self, top: list[Key], rows: dict[Key, dict], qvecs, texts: list[str | None], q: SearchQuery,
                      tr: SearchTrace) -> list[Key]:
        """금액 구간 조회(사전 등록 62.7, 62.13, 62.27): 질문에 달러 금액이 있으면, 상위 k가 든 페이지의 구간 행(제목 경로 끝이 ">$25K up to $50K" 같은 금액 구간인
        청크) 중 그 금액이 속한 행을 표(제목 경로에서 구간 단계를 뺀 앞부분)마다 하나씩 고르고, 질문이 이름을 부른 표(`ranges.table_named`)를 먼저, 그 안에서
        전체 질문 벡터(하위 질문은 쓰지 않는다)와 가까운 순으로 range_n개까지 뒤 자리를 바꾼다. 벡터는 "$30,000"이 어느 구간인지 알지 못해 구간 행들이 서로
        거의 같은 점수로 흩어지기 때문이다. 질문을 나눴으면 전체 질문 벡터의 상위 k 페이지도 후보 페이지에 넣는다(하위 질문만으로 만든 상위 k에 표 페이지가
        없는 회차가 생기지 않게). 상위 k에 이미 든 구간 행은 그대로 두고 자리만 센다. 금액이 없거나, 후보 페이지에 구간 행이 없거나, 저장소가 이 조회를 모르면 그대로 돌려준다."""
        n = self.cfg.range_n
        if not n or qvecs is None or not top:
            return top
        amounts = ranges.amounts_in(texts)
        find, score = getattr(self.store, "band_headings", None), getattr(self.store, "key_scores", None)
        if not amounts or find is None or score is None:
            return top
        t = time.perf_counter()
        seqs = {int(rows[k]["rule_seq"]) for k in top}
        if tr.n_sub:
            # 질문을 나눴으면 상위 k는 하위 질문만으로 만든 것이라, 하위 질문 문장(LLM이 회차마다 다르게 쓴다)에 따라 표 페이지가 상위 k에서 빠질 수 있다.
            # 전체 질문 벡터의 상위 k 페이지를 후보에 더한다(벡터 질의 1회, 임베딩은 이미 있다). 표를 고르는 점수는 아래와 같이 전체 질문 벡터다
            whole = [k for k, _ in self.store.vector_top(qvecs[0], self.cfg.embed_model, q.org, q.as_of, q.k)]
            missing = [k for k in whole if k not in rows]
            if missing:
                rows.update(self.store.fetch(missing))
            seqs |= {int(rows[k]["rule_seq"]) for k in whole if k in rows}
        covering = ranges.covering(find(sorted(seqs), q.org, q.as_of), amounts)
        picks = [k for k, _ in covering]
        if not picks:
            return top
        # 전체 질문 벡터 하나로만 고른다. 하위 질문은 LLM이 회차마다 다르게 쓰고 번역도 달라져, 금액이 속한 표가 여럿일 때 어느 표가 남는지가 회차마다 바뀌었다
        # (운영 트레이스 2026-11-09: 같은 질문 3회에서 지출 승인 행이 빠진 회차가 있었다).
        # 질문이 이름을 부른 표(예: "approver"와 "Approving expense")를 먼저 둔다. 금액이 여러 표에 들면 구간 행끼리 점수가 0.03 안에 몰려, 질문의 금액과
        # 글자가 겹치는 다른 표의 행("$10,000"과 "Up to $10K")이 질문이 부른 표를 밀어냈다(운영 재연 2026-11-10, 사전 등록 62.27).
        best = score(qvecs[0], self.cfg.embed_model, picks)
        named = {k for k, table in covering if ranges.table_named(table, texts)}
        chosen = sorted(picks, key=lambda k: (k not in named, -best.get(k, float("-inf"))))[:n]   # 안정 정렬: 같은 점수는 제목 순서
        new = [k for k in chosen if k not in top]
        if new:
            rows.update(self.store.fetch(new))
            new = [k for k in new if k in rows]
        tr.n_range, tr.ms["range"] = len(new), _ms(t)
        if not new:
            return top
        out, drop = list(top), len(new)
        for i in range(len(out) - 1, -1, -1):          # 뒤에서부터 구간 행이 아닌 것을 덜어낸다(링크 확장 청크가 먼저 빠진다)
            if not drop:
                break
            if out[i] not in chosen:
                del out[i]
                drop -= 1
        return out + new

    def search(self, q: SearchQuery) -> list[Chunk]:
        check_query(q)
        self._refresh()
        cfg = self.cfg
        tr = SearchTrace(cfg.embed_model, cfg.rerank_model, cfg.mode)
        t0 = time.perf_counter()
        subs = list(q.sub_queries or [])
        # 전체 질문이 하위 질문과 같은 문장이면(합동 검토 팀 검색: 요청+보조어, 사전 등록 62.41) 그 문장은 이미 하위 질문이다. 한 번만 번역·임베딩·질의하고
        # 전체 질문 목록을 따로 만들지 않는다(원 질문 끝자리 없음). 서비스 질문 그래프의 분해는 원 질문과 다른 문장이라 이 경로를 타지 않는다
        full_is_sub = q.query in subs
        if full_is_sub:
            subs = [s for s in subs if s != q.query]
        texts = [q.query, *subs]                                # 0 = 전체 질문, 1.. = 하위 질문(full_is_sub면 0이 하위 질문도 겸한다)
        tr.n_sub = len(q.sub_queries or [])

        mode = cfg.mode
        kind = {"hybrid_ko_kw": "keywords", "bm25_kw": "keywords", "dense_en": "sentence"}.get(mode)
        trans = self._translate_all(texts, kind, tr) if kind else [None] * len(texts)
        if mode != "dense_ko" and any(t is None for t in trans):
            mode, tr.fallback = "dense_ko", "dense_ko"          # Spec EC-01·EC-02, QUERY_TRANSLATE=0
            log.info("검색 방식을 dense_ko로 내림: %s", tr.fallback_reason)
        tr.mode = mode
        tr.ms["translate"] = _ms(t0)

        mask = valid_mask(self._rm, q.org, q.as_of)
        tr.n_filtered = int(mask.sum())
        if tr.n_filtered == 0:                                   # Spec EC-03: 없는 org, 너무 이른 as_of
            _last.set(tr)
            return []
        n = max(q.k, cfg.rerank_top if self.reranker else 0)

        merge = sub_merge_enabled() and len(texts) > 1
        # 나뉜 질문을 기본 자리 수보다 넓혀 찾으면(q.k > DEFAULT_K) 전체 질문(0번)의 후보 목록도 만들어 끝 FULL_TAIL자리를 준다(사전 등록 62.38).
        # 기본 자리 수 이하는 하위 질문으로만 후보를 만든다(측정과 같음). SEARCH_SUB_MERGE면 전체 질문도 후보에 넣어 점수로 합친다
        tail = FULL_TAIL if len(texts) > 1 and not merge and not full_is_sub and q.k > DEFAULT_K else 0
        idx = range(len(texts)) if merge or tail or full_is_sub else range(1, len(texts)) if len(texts) > 1 else range(1)
        rows: dict[Key, dict] = {}
        lists = []

        def vector_stage(trace: SearchTrace):
            """질문 임베딩 + 하위 질문마다 벡터 질의(+ 방식에 따라 BM25, 리랭킹). 읽기뿐이라 같은 입력이면 몇 번을 돌려도 결과가 같다.
            `trace`에 이 시도의 시간·개수를 모은다(hedge가 켜지면 시도마다 따로 모았다가 이긴 쪽만 `tr`에 합친다)."""
            qv = None
            if mode != "bm25_kw":
                t = time.perf_counter()
                qv = self.embed([trans[i] if mode == "dense_en" else texts[i] for i in range(len(texts))])    # 전체 + 하위 질문 벡터를 한 번에(API면 요청 1번)
                trace.ms["embed"] = _ms(t)
                for i, text in enumerate(texts):
                    self._remember(mode, text, qv[i])
            smaps: dict[int, dict[Key, float]] = {i: {} for i in idx}

            def one(i: int):
                return self._ranked(texts[i], trans[i], None if qv is None else qv[i], mode, q, mask, n, trace,
                                    smaps[i] if merge else None)

            token = _db_ms.set(trace.ms)
            try:
                # 하위 질문은 서로 독립이다. 결과는 하위 질문 순서대로 합치므로 동시에 찾아도 순위가 같다. 벡터만 쓰는 방식에서만 켠다(BM25와 리랭커는 프로세스 안 계산이라 빨라지지 않는다)
                if parallel_subs_enabled() and len(idx) >= 2 and mode in VECTOR_ONLY_MODES and self.reranker is None:
                    with ThreadPoolExecutor(max_workers=len(idx), thread_name_prefix="subq") as pool:
                        out = list(pool.map(lambda i, ctx: ctx.run(one, i), idx, [contextvars.copy_context() for _ in idx]))
                else:
                    out = [one(i) for i in idx]
            finally:
                _db_ms.reset(token)
            return qv, out, smaps

        try:
            if cfg.hedge:   # 사전 등록 62.14: 시도마다 따로 된 기록에 모으고, 이긴 시도의 기록만 합친다(진 시도가 개수·시간을 부풀리지 않게)
                def attempt_stage(attempt: int):
                    own = SearchTrace(cfg.embed_model, cfg.rerank_model, mode)
                    return (*vector_stage(own), own)
                (qvecs, done, score_maps, own), winner, sent = hedge_mod.hedged(attempt_stage, cfg.hedge_s)
                tr.ms.update(own.ms)
                tr.n_dense += own.n_dense
                tr.n_bm25 += own.n_bm25
                tr.hedged, tr.hedge_winner = sent, winner
            else:
                qvecs, done, score_maps = vector_stage(tr)
        except EmbedNoKey:                                       # 키 없는 데모: 죽지 않고 빈 결과(그래프는 근거 없음으로 거절)
            tr.fallback_reason, tr.ms["total"] = "no_key", _ms(t0)
            log.warning("임베딩 API 키가 없어 검색하지 않음(no_key)")
            _last.set(tr)
            return []
        for got, r in done:
            lists.append(got)
            rows.update(r)
        if merge:
            best: dict[Key, float] = {}
            for m in score_maps.values():
                for key, s in m.items():
                    best[key] = max(s, best.get(key, float("-inf")))
            top = merge_by_score(lists, best, q.k)
        elif tail:
            # lists[0]은 전체 질문, lists[1:]은 하위 질문이다. 하위 질문만 번갈아 합친 k-tail자리에 링크 확장까지 한 뒤(전체 질문 목록이 없는 검색의 k-tail 결과와 같다),
            # 끝자리를 전체 질문 목록의 아직 없는 앞 청크로 채운다. 전체 질문 목록에 새 청크가 없으면 하위 질문 목록의 다음 청크가 든다
            inner = q.model_copy(update={"k": q.k - tail})
            head = self._link_expand(roundrobin(lists[1:], inner.k), rows, None if qvecs is None else qvecs[0], inner, tr)
            top = fill_tail(head, [lists[0], roundrobin(lists[1:], sum(len(x) for x in lists[1:]))], q.k)
        else:
            top = lists[0] if len(lists) == 1 else roundrobin(lists, q.k)
        if not tail:
            top = self._link_expand(top, rows, None if qvecs is None else qvecs[0], q, tr)
        top = self._range_expand(top[: q.k], rows, qvecs, [*texts, *trans], q, tr)
        out = [to_chunk(rows[k]) for k in top[: q.k]]
        tr.n_returned, tr.ms["total"] = len(out), _ms(t0)
        _last.set(tr)
        return out

    def sibling_sections(self, query: str, chunk_ids: list[str], org: str | None = None, as_of: str | None = None, n: int = 2) -> list[Chunk]:
        """(나) `GRAPH_SIBLING_SECTIONS=1`(기본 꺼짐) 전용. 문맥 청크(chunk_ids)가 든 페이지에서 형제 절의 첫 청크를 질문과 가까운 순으로 n개 돌려준다.
        기본 검색(`search`)의 k, 합치기, 링크 확장은 그대로다. 벡터를 쓰지 않는 방식이거나 번역이 없으면 빈 목록이다."""
        self._refresh()
        cfg = self.cfg
        if not chunk_ids or n <= 0 or not (query or "").strip() or cfg.mode not in VECTOR_ONLY_MODES:
            return []
        qvec = self.query_vector(query)
        if qvec is None:
            return []
        ids = set(chunk_ids)
        seqs = sorted({int(r["rule_seq"]) for r in self._rows_by_id(ids, org, as_of)})
        if not seqs:
            return []
        hits = self.store.page_vector_top(qvec, cfg.embed_model, seqs, org, as_of, [], SIBLING_POOL)
        rows = self.store.fetch([k for k, _ in hits])
        context = [r for r in rows.values() if r["chunk_id"] in ids]
        keys = sibling_firsts(context, list(rows.values()), dict(hits), n)
        return [to_chunk(rows[k]) for k in keys]

    def _rows_by_id(self, ids: set[str], org, as_of) -> list[dict]:
        """chunk_id로 페이지 번호를 찾는다(판 번호를 모를 때). 메모리 저장소는 행 목록에서, 운영 DB는 chunks 표에서 읽는다."""
        if isinstance(self.store, PgStore):
            got = self.store._all("SELECT DISTINCT rule_seq FROM chunks WHERE chunk_id = ANY(%(ids)s::text[])", {"ids": sorted(ids)})
            return [{"rule_seq": r[0]} for r in got]
        return [r for r in getattr(self.store, "rows", []) if r.get("chunk_id") in ids]

    def search_pages(self, query: str, rule_seqs: list[int], org: str | None = None, as_of: str | None = None, k: int = DEFAULT_K) -> list[Chunk]:
        """페이지 범위 재검색(그래프 `GRAPH_PAGE_RESEARCH=1`, 기본 꺼짐) 전용. 주어진 페이지(rule_seq) 안의 청크 중 질문과 가까운 k개다.
        링크 확장과 같은 페이지 벡터 질의(`page_vector_top`, 같은 필터)를 쓰고, 기본 검색(`search`)의 후보, 합치기, 링크 확장은 거치지 않는다.
        벡터를 쓰지 않는 방식이거나 번역이 없으면 빈 목록이다."""
        self._refresh()
        cfg = self.cfg
        if not rule_seqs or not (query or "").strip() or cfg.mode not in VECTOR_ONLY_MODES:
            return []
        qvec = self.query_vector(query)  # 같은 질문을 방금 검색했으면 그 벡터를 다시 임베딩하지 않는다(사전 등록 62.55의 같은 페이지 보충). 없으면 지금처럼 번역·임베딩한다
        if qvec is None:
            return []
        keys = [key for key, _ in self.store.page_vector_top(qvec, cfg.embed_model, [int(s) for s in rule_seqs], org, as_of, [], k)]
        rows = self.store.fetch(keys) if keys else {}
        return [to_chunk(rows[key]) for key in keys if key in rows]

    def _remember(self, mode: str, text: str, vec) -> None:
        with self._lock:
            self._qvecs[(mode, text)] = np.asarray(vec, dtype=np.float32)
            self._qvecs.move_to_end((mode, text))
            while len(self._qvecs) > QVEC_CACHE:
                self._qvecs.popitem(last=False)

    def query_vector(self, query: str):
        """질문 벡터. 이 검색기가 방금 찾은 질문이면 다시 임베딩하지 않는다. 벡터를 쓰지 않는 방식이거나 번역이 없으면 None."""
        mode = self.cfg.mode
        if mode not in VECTOR_ONLY_MODES or not (query or "").strip():
            return None
        with self._lock:
            got = self._qvecs.get((mode, query))
        if got is not None:
            return got
        text: str | None = query
        if mode == "dense_en":
            text, _, _ = self._translate_one(query, "sentence")
            if not text:
                return None
        vec = self.embed([text])[0]
        self._remember(mode, query, vec)
        return np.asarray(vec, dtype=np.float32)

    def prev_chunk(self, chunk) -> Chunk | None:
        """사전 등록 62.58: 같은 페이지 판(rule_seq, version_id)에서 `chunk` 바로 앞 청크(ord 순) 1개. 첫 청크이거나 못 찾으면 None. DB 읽기(`page_chunks`, `fetch`) 각 1번이다."""
        self._refresh()
        d = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
        top = getattr(self.store, "page_chunks", None)
        if top is None or d.get("rule_seq") is None or not d.get("version_id"):
            return None
        page = [k for k, _ in top(int(d["rule_seq"]), d["version_id"])]
        me = (d["chunk_id"], d["version_id"])
        if me not in page or page.index(me) == 0:
            return None
        key = page[page.index(me) - 1]
        rows = self.store.fetch([key])
        return to_chunk(rows[key]) if key in rows else None

    def intro_fill(self, chunks: list, query: str, org: str | None = None, as_of: str | None = None) -> list[Chunk]:
        """R3 도입부 채우기(그래프 `GRAPH_INTRO_FILL=1`, 기본 꺼짐) 전용. 문맥(`chunks`)에 같은 페이지 판(rule_seq, version_id)의 청크가 `INTRO_MIN`개 이상이면
        그 페이지 첫 청크의 첫 절(h2, 절 제목의 첫 ' > ' 앞) 청크 중 질문 벡터와 가장 가까운 1개를 돌려준다. 그 절이 청크 `INTRO_WHOLE`개 이하면 절 전체(ord 순)다.
        그 절의 청크가 이미 문맥에 있으면 그 페이지는 건너뛴다.
        기본 검색(`search`)은 바꾸지 않는다. 문항 id나 페이지 이름은 쓰지 않는다."""
        self._refresh()
        pages: dict[tuple[int, str], list[dict]] = {}
        for c in chunks or []:
            d = c.model_dump() if hasattr(c, "model_dump") else dict(c)
            if d.get("rule_seq") is None or not d.get("version_id"):
                continue
            pages.setdefault((int(d["rule_seq"]), d["version_id"]), []).append(d)
        want = [(pk, mem) for pk, mem in pages.items() if len(mem) >= INTRO_MIN]
        top = getattr(self.store, "page_chunks", None)
        if not want or top is None:
            return []
        have = {(d["chunk_id"], d["version_id"]) for mem in pages.values() for d in mem}
        picks: list[Key] = []
        qvec = None
        for (seq, ver), mem in want:
            page = top(seq, ver)
            if not page:
                continue
            first = _h2(page[0][1])
            if any(_h2(d.get("article")) == first for d in mem):
                continue
            section = [k for k, a in page if _h2(a) == first]
            cand = {k for k in section if k not in have and k not in picks}
            if not cand:
                continue
            if len(section) <= INTRO_WHOLE:  # 도입부 절이 청크 2개 이하면 한 문단이 나뉜 것이라 절 전체를 ord 순으로 더한다(벡터 순위를 쓰지 않는다)
                picks += [k for k in section if k in cand]
                continue
            if qvec is None:
                qvec = self.query_vector(query)
                if qvec is None:
                    return []
            ranked = self.store.page_vector_top(qvec, self.cfg.embed_model, [seq], org, as_of, list(have), len(page))
            best = next((k for k, _ in ranked if k in cand), None)
            if best is not None:
                picks.append(best)
        rows = self.store.fetch(picks) if picks else {}
        return [to_chunk(rows[k]) for k in picks if k in rows]


_TRACE_LOCK = threading.Lock()
QVEC_CACHE = 512   # 질문 벡터 기억 상한(R3용)
INTRO_MIN = 3      # R3: 같은 페이지 판의 청크가 이만큼 문맥에 있어야 도입부를 채운다
INTRO_WHOLE = 2    # R3: 도입부 절의 청크가 이 수 이하면 절 전체를 더한다


def _h2(article) -> str:
    """절 제목의 첫 단계(h2). 'A > B'면 'a'."""
    return str(article or "").split(" > ")[0].strip().lower()

_db_ms: contextvars.ContextVar[dict | None] = contextvars.ContextVar("search_db_ms", default=None)
VECTOR_ONLY_MODES = ("dense_en", "dense_ko")


def parallel_subs_enabled() -> bool:
    """`SEARCH_PARALLEL_SUBS=1`일 때만 하위 질문을 동시에 찾는다. 기본 꺼짐."""
    return (os.environ.get("SEARCH_PARALLEL_SUBS") or "").strip() == "1"


def _note_db(acquire_s: float, query_s: float) -> None:
    """벡터 질의의 시간 나누기. `db_wait`는 연결 받기와 색인 설정 왕복, `db_query`는 질의 왕복이다. 질의 왕복 안의 네트워크와 실행은 나누지 못한다."""
    ms = _db_ms.get()
    if ms is not None:
        with _TRACE_LOCK:
            ms["db_wait"] = round(ms.get("db_wait", 0) + acquire_s * 1000, 1)
            ms["db_query"] = round(ms.get("db_query", 0) + query_s * 1000, 1)


def _ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)


# ---------- 서비스 입구 ----------

_searcher: Searcher | None = None
_init_lock = threading.Lock()


def warmup() -> Searcher:
    """서버 기동 때 한 번 부른다: 장부 대조 → 모델·리랭커·BM25 올리기 → 질문 하나 미리 돌리기."""
    global _searcher
    from backend.rag.retrieve import embed
    with _init_lock:
        if _searcher is None:
            cfg = SearchConfig.from_env()
            store = PgStore.from_env()
            try:
                s = Searcher(cfg, store)
                if isinstance(s.store, PgStore):                # 색인 페이지와 연결을 미리 연다. HNSW를 쓸 때만 하고 임베딩 API는 부르지 않는다
                    s.store.warm(s.cfg.embed_model)
                if not embed.spec(s.cfg.embed_model).api:           # API 모델은 미리 부를 것이 없고, 부르면 돈이 든다
                    s.embed(["warm-up"])
            except BaseException:
                store.close()       # 실패하면 방금 연 풀을 닫는다. 안 닫으면 다음 search()의 재시도마다 풀이 하나씩 쌓인다
                raise
            _searcher = s
    return _searcher


def search(q: SearchQuery) -> list[Chunk]:
    """계약 함수. 처음 부르면 warmup()을 한다(그래서 첫 요청은 지연 측정에서 뺀다)."""
    return (_searcher or warmup()).search(q)


# ---------- 비교 입구: evals/retrieval/compare.py --factory backend.rag.retrieve.search:make_search ----------
# 조합 하나(임베딩·방식·리랭커·후보 수)를 받아 검색 함수를 돌려준다. 서비스와 같은 Searcher를 쓰고 저장소만 DB 대신
# 스냅샷(data/index/)을 numpy로 읽는다(DB = numpy는 V2에서 30/30 확인). 이름은 1차 비교(experiment_v1)의 짧은 이름도 받는다.
# 노트북 메모리를 생각해 임베딩 모델·리랭커는 하나씩만 올려 두고, 청크·BM25 색인·번역 장부는 조합끼리 같이 쓴다.

def index_dir() -> Path:
    return Path(os.environ.get("SEARCH_INDEX_DIR") or "data/index")


def embedder_name(name: str) -> str | None:
    """'arctic-l-v2' 같은 짧은 이름이나 EMBED_MODEL 값 → EMBED_MODEL 값. 'none'(BM25만)은 None."""
    from backend.rag.retrieve import embed
    if name == "none":
        return None
    for s in embed.EMBEDDERS.values():
        if name in (s.name, s.short):
            return s.name
    raise ValueError(f"모르는 임베딩: {name} (후보: {', '.join(s.short for s in embed.EMBEDDERS.values())}, none)")


def reranker_name(name: str) -> str:
    """'mminilm' 같은 짧은 이름이나 RERANK_MODEL 값 → RERANK_MODEL 값."""
    from backend.rag.retrieve import rerank
    if name == rerank.NONE:
        return name
    for s in rerank.RERANKERS.values():
        if name in (s.name, s.short):
            return s.name
    raise ValueError(f"모르는 리랭커: {name} (후보: {', '.join(s.short for s in rerank.RERANKERS.values())}, none)")


def snapshot_rows(index: Path) -> tuple[dict, list[dict]]:
    """스냅샷 청크 + 판 유효 구간(적재와 같은 규칙, load_snapshot.versions_of). 청크 파일 sha256을 meta와 대조한다."""
    from backend.rag.retrieve.index import file_sha, load_rows
    from backend.rag.retrieve.load_snapshot import versions_of
    meta = json.loads((index / "meta.json").read_text(encoding="utf-8"))
    path = index / meta["chunks_file"]
    if file_sha(path) != meta["chunks_sha256"]:
        raise RuntimeError(f"청크 파일이 meta.json과 다르다: {path}")
    rows = load_rows(path)
    valid = {(v["rule_seq"], v["version_id"]): v for v in versions_of(rows)}
    return meta, [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
                   "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"]} for r in rows]


def seed_translations(index: Path, meta: dict) -> dict[tuple[str, str], dict]:
    """스냅샷의 번역 장부 파일(index.py translations가 만든 것)을 저장소 장부 형식으로. 없으면 빈 장부."""
    from backend.rag.retrieve.index import file_sha
    tr = meta.get("query_translations")
    if not tr:
        return {}
    if file_sha(index / tr["file"]) != tr["sha256"]:
        raise RuntimeError("번역 장부 파일이 meta.json과 다르다")
    out: dict[tuple[str, str], dict] = {}
    for line in (index / tr["file"]).read_text(encoding="utf-8").splitlines():
        if line.strip():
            x = json.loads(line)
            out[(x["query_sha256"], x["model"])] = {"keywords": x.get("keywords"), "sentence": x.get("sentence")}
    return out


def _load_embedder(name: str, entry: dict):
    """질문 임베딩 함수. 앞말이 색인 장부와 다르면 멈춘다(Searcher와 같은 대조). 테스트는 이 함수를 바꿔 끼운다."""
    from backend.rag.retrieve import embed
    model = embed.load_model(name)
    used = embed.used_prefixes(model, embed.spec(name))
    if (entry.get("prefixes") or {}).get("query", used["query"]) != used["query"]:
        raise RuntimeError(f"질문 앞말이 색인 장부와 다르다: 장부 {entry.get('prefixes')}, 지금 {used}")
    return lambda texts: embed.encode_queries(model, texts)


def _load_reranker(name: str):
    from backend.rag.retrieve import rerank
    return rerank.load_reranker(name)


class _EvalCache:
    index: Path | None = None
    meta: dict | None = None
    rows: list[dict] | None = None
    bm25: tuple[RowMeta, object] | None = None
    translations: dict | None = None
    embedder: tuple[str | None, MemoryStore, object] | None = None
    reranker: tuple[str, object] | None = None


def _eval_base(index: Path) -> type[_EvalCache]:
    c = _EvalCache
    if c.index != index:
        c.meta, c.rows = snapshot_rows(index)
        c.translations = seed_translations(index, c.meta)
        c.index, c.bm25, c.embedder, c.reranker = index, None, None, None
    return c


def _eval_embedder(c: type[_EvalCache], name: str | None):
    """(저장소, 질문 임베딩 함수). 모델은 한 번에 하나만 메모리에 둔다(experiment_v1 _state와 같은 방식)."""
    if c.embedder is None or c.embedder[0] != name:
        c.embedder = None
        if name is None:            # BM25만: 벡터 검색을 하지 않으니 모델·벡터를 올리지 않는다
            vecs, fn = np.zeros((len(c.rows), 1), dtype=np.float32), None
        else:
            from backend.rag.retrieve import embed
            from backend.rag.retrieve.index import file_sha
            s, ent = embed.spec(name), (c.meta.get("embedders") or {}).get(name)
            if not ent:
                raise RuntimeError(f"스냅샷에 {name} 벡터가 없다(index.py build 또는 import로 먼저 만든다)")
            if file_sha(c.index / ent["file"]) != ent["sha256"]:
                raise RuntimeError(f"벡터 파일이 meta.json과 다르다: {ent['file']}")
            if ent.get("revision") != embed.revision_for(s) or ent.get("dim") != s.dim:
                raise RuntimeError(f"색인 장부와 명부가 다르다: 장부 {ent.get('revision')}/{ent.get('dim')}, "
                                   f"명부 {embed.revision_for(s)}/{s.dim}")
            vecs = np.load(c.index / ent["file"])
            fn = _load_embedder(name, ent)
        store = MemoryStore(c.rows, vecs, name or "none", meta=c.meta)
        store.translations = c.translations      # 조합끼리 같은 장부(새로 받은 번역도 다음 조합이 그대로 쓴다)
        c.embedder = (name, store, fn)
    return c.embedder[1], c.embedder[2]


def _eval_reranker(c: type[_EvalCache], name: str):
    if name == "none":
        return None
    if c.reranker is None or c.reranker[0] != name:
        c.reranker = None
        c.reranker = (name, _load_reranker(name))
    return c.reranker[1]


def _strict_translator(store):
    """비교용 번역: 실패하면 dense_ko로 내려가지 않고 멈춘다. 내려가면 표에 적힌 조합과 다른 방식을 재게 된다."""
    from backend.rag.retrieve import translate

    def run(query: str, kind: str):
        res = translate.translate(query, kind, store)
        if res.text is None:
            raise RuntimeError(f"번역 실패로 비교를 멈춘다({kind}, {res.source}, 질문 sha256 {translate.query_sha(query)[:12]}). "
                               "번역 장부를 채우거나 LLM_PROVIDER를 정한 뒤 다시 돌린다")
        return res
    return run


def make_search(embedder: str, mode: str, reranker: str = "none", rerank_top: int = 0):
    """조합 하나 → 검색 함수(SearchQuery -> list[Chunk]). BM25만은 embedder="none"·mode="bm25_kw"(experiment_v1과 같은 규칙).
    리랭커가 없으면 rerank_top은 쓰지 않는다(후보 수 = k)."""
    name, rr = embedder_name(embedder), reranker_name(reranker)
    if (name is None) != (mode == "bm25_kw"):
        raise ValueError(f"BM25만(bm25_kw)일 때만 embedder=none: {embedder}, {mode}")
    cfg = SearchConfig(embed_model=name or "none", mode=mode, rerank_model=rr,
                       rerank_top=rerank_top if rr != "none" else SearchConfig.rerank_top)
    cfg.check()
    c = _eval_base(index_dir())
    store, fn = _eval_embedder(c, name)
    rr_obj = _eval_reranker(c, rr)
    s = Searcher(cfg, store, embedder=fn or _no_embed, reranker=rr_obj, translator=_strict_translator(store),
                 check_meta=False, bm25=c.bm25)
    c.bm25 = (s._rm, s._bm25)
    return s.search


def _no_embed(texts):
    raise RuntimeError("BM25만 방식에서 질문 임베딩을 부르면 안 된다")
