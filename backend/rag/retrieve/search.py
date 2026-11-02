"""검색 `search(SearchQuery) -> list[Chunk]` (docs/specs/search.md, 설계 study 쪽 design-search.md).

필터(org·as_of, 검색 전에) → 벡터 + BM25 각 SEARCH_POOL개 → RRF(k=60) → 상위 max(k, RERANK_TOP) 리랭킹 → 상위 k.
모델과 방식은 환경 변수로만 바꾼다(EMBED_MODEL, SEARCH_MODE, SEARCH_POOL, RERANK_MODEL, RERANK_TOP, QUERY_TRANSLATE).

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from backend.schemas.chunk import Chunk, SearchQuery

log = logging.getLogger(__name__)

MODES = ("hybrid_ko_kw", "dense_en", "bm25_kw", "dense_ko")
RRF_K = 60
_STOP = set("a an the of to in on for and or is are be by with what how when who which do does can if it at as from this that".split())
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- 설정 ----------

@dataclass(frozen=True)
class SearchConfig:
    embed_model: str
    mode: str = "hybrid_ko_kw"
    pool: int = 100
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_top: int = 10
    translate: bool = True

    @classmethod
    def from_env(cls) -> "SearchConfig":
        from backend.rag.retrieve import embed, rerank
        cfg = cls(embed_model=embed.spec().name,
                  mode=os.environ.get("SEARCH_MODE") or "hybrid_ko_kw",
                  pool=int(os.environ.get("SEARCH_POOL") or 100),
                  rerank_model=rerank.model_name(),
                  rerank_top=int(os.environ.get("RERANK_TOP") or 10),
                  translate=(os.environ.get("QUERY_TRANSLATE") or "1") != "0")
        cfg.check()
        return cfg

    def check(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"모르는 SEARCH_MODE: {self.mode} (후보: {', '.join(MODES)})")
        if self.pool < 1 or self.rerank_top < 1:
            raise ValueError(f"SEARCH_POOL·RERANK_TOP은 1 이상: {self.pool}, {self.rerank_top}")


# ---------- 기록 ----------

@dataclass
class SearchTrace:
    """검색 한 번의 기록. 본문·프롬프트는 남기지 않는다(rag3-11). 그래프 쪽이 last_search_trace()로 읽어 트레이스에 붙인다."""
    embed_model: str
    rerank_model: str
    requested_mode: str
    mode: str = ""
    fallback: str | None = None          # dense_ko로 내렸으면 "dense_ko"
    fallback_reason: str | None = None   # translate_off | demo_no_record | invalid | timeout | error | cost_cap
    translation_source: str | None = None
    n_filtered: int = 0                  # 필터 뒤 대상 청크 수 (0이면 진짜 없음, rag4-09)
    n_dense: int = 0
    n_bm25: int = 0
    n_returned: int = 0
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


class PgStore:
    """pgvector 저장소. 색인(HNSW) 없이 전수 비교 — 필터를 걸어도 결과가 줄지 않는다(rag3-12 Step 4).
    값은 SQL 문장에 이어 붙이지 않고 자리(%(이름)s)로 넘긴다. Supabase transaction pooler 대비 prepare_threshold=None(rag3-12)."""

    def __init__(self, url: str):
        from pgvector.psycopg import register_vector
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(url, min_size=1, max_size=4, open=True,
                                   kwargs={"prepare_threshold": None}, configure=register_vector)

    @classmethod
    def from_env(cls) -> "PgStore":
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL이 없다")
        return cls(url)

    def _all(self, sql: str, params=None) -> list[tuple]:
        with self.pool.connection() as conn:
            return conn.execute(sql, params or {}).fetchall()

    def meta(self):
        rows = self._all("SELECT embedder, revision, dim, prefixes, status, generation FROM index_meta WHERE id = 1")
        if not rows:
            return None
        e, r, d, p, s, g = rows[0]
        return {"embedder": e, "revision": r, "dim": d, "prefixes": p, "status": s, "generation": g}

    def generation(self):
        rows = self._all("SELECT generation FROM index_meta WHERE id = 1")
        return int(rows[0][0]) if rows else 0

    def row_meta(self):
        rows = self._all(f"SELECT c.chunk_id, c.version_id, d.org, v.valid_from, v.valid_to, c.text {_JOIN} ORDER BY c.ord, c.chunk_id")
        return RowMeta(keys=[(r[0], r[1]) for r in rows],
                       org=np.array([r[2] for r in rows], dtype=object),
                       valid_from=np.array([r[3] for r in rows], dtype="datetime64[D]"),
                       valid_to=np.array([r[4] if r[4] is not None else "NaT" for r in rows], dtype="datetime64[D]"),
                       texts=[r[5] for r in rows])

    def vector_top(self, qvec, embedder, org, as_of, n):
        sql = f"""SELECT c.chunk_id, c.version_id, -(c.embedding <#> %(q)s::vector) AS score {_JOIN}
WHERE c.embedder = %(embedder)s AND {_FILTER}
ORDER BY c.embedding <#> %(q)s::vector, c.chunk_id LIMIT %(n)s"""
        rows = self._all(sql, {"q": np.asarray(qvec, dtype=np.float32), "embedder": embedder,
                               "org": org, "as_of": as_of, "n": n})
        return [((r[0], r[1]), float(r[2])) for r in rows]

    def fetch(self, keys):
        if not keys:
            return {}
        sql = f"""SELECT c.chunk_id, c.version_id, d.org, c.rule_seq, d.title, c.article, v.version_date, d.fetched_at,
       c.kind, c.text, c.source_url, c.text_sha256, v.version_date_before, c.line_start, c.line_end {_JOIN}
JOIN unnest(%(ids)s::text[], %(vers)s::text[]) AS k(chunk_id, version_id)
  ON k.chunk_id = c.chunk_id AND k.version_id = c.version_id"""
        rows = self._all(sql, {"ids": [k[0] for k in keys], "vers": [k[1] for k in keys]})
        cols = ("chunk_id", "version_id", "org", "rule_seq", "rule_title", "article", "version_date", "fetched_at",
                "kind", "text", "source_url", "text_sha256", "version_date_before", "line_start", "line_end")
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


def check_query(q: SearchQuery) -> None:
    if not q.query or not q.query.strip():
        raise ValueError("빈 질문")
    if q.k < 1:
        raise ValueError(f"k는 1 이상: {q.k}")
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
        rm = self.store.row_meta()
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

    def _translate(self, query: str, kind: str, tr: SearchTrace) -> str | None:
        if not self.cfg.translate:
            tr.fallback_reason = "translate_off"
            return None
        from backend.rag.retrieve.translate import valid_english
        if valid_english(query):                                 # 그래프의 재작성 질의처럼 이미 영어면 LLM을 부르지 않는다
            tr.translation_source = "as_is"
            return query
        res = self.translator(query, kind)
        tr.translation_source = res.source
        if res.text is None:
            tr.fallback_reason = res.source
        return res.text

    def search(self, q: SearchQuery) -> list[Chunk]:
        check_query(q)
        self._refresh()
        cfg = self.cfg
        tr = SearchTrace(cfg.embed_model, cfg.rerank_model, cfg.mode)
        t0 = time.perf_counter()

        mode, keywords, sentence = cfg.mode, None, None
        if mode in ("hybrid_ko_kw", "bm25_kw"):
            keywords = self._translate(q.query, "keywords", tr)
        elif mode == "dense_en":
            sentence = self._translate(q.query, "sentence", tr)
        if mode != "dense_ko" and keywords is None and sentence is None:
            mode, tr.fallback = "dense_ko", "dense_ko"          # Spec EC-01·EC-02, QUERY_TRANSLATE=0
            log.info("검색 방식을 dense_ko로 내림: %s", tr.fallback_reason)
        tr.mode = mode
        tr.ms["translate"] = _ms(t0)

        rm, bm25 = self._rm, self._bm25
        mask = valid_mask(rm, q.org, q.as_of)
        tr.n_filtered = int(mask.sum())
        if tr.n_filtered == 0:                                   # Spec EC-03: 없는 org, 너무 이른 as_of
            _last.set(tr)
            return []
        n = max(q.k, cfg.rerank_top if self.reranker else 0)

        dense: list[Key] = []
        if mode != "bm25_kw":
            t = time.perf_counter()
            qvec = self.embed([sentence if mode == "dense_en" else q.query])[0]
            tr.ms["embed"] = _ms(t)
            t = time.perf_counter()
            dense = [k for k, _ in self.store.vector_top(qvec, cfg.embed_model, q.org, q.as_of,
                                                         cfg.pool if mode == "hybrid_ko_kw" else n)]
            tr.ms["vector"], tr.n_dense = _ms(t), len(dense)

        bm: list[Key] = []
        if mode in ("hybrid_ko_kw", "bm25_kw"):
            t = time.perf_counter()
            pos = np.flatnonzero(mask)
            scores = np.asarray(bm25.get_scores(tokens(keywords)), dtype=float)[pos]
            bm = [rm.keys[pos[i]] for i in top_positions(scores, cfg.pool if mode == "hybrid_ko_kw" else n)]
            tr.ms["bm25"], tr.n_bm25 = _ms(t), len(bm)

        if mode == "hybrid_ko_kw":
            cand = [k for k, _ in rrf([dense, bm])][:n]
        else:
            cand = (bm if mode == "bm25_kw" else dense)[:n]

        rows = self.store.fetch(cand)
        cand = [k for k in cand if k in rows]
        if self.reranker is not None and cand:
            t = time.perf_counter()
            sc = self.reranker.score(q.query, [rows[k]["text"] for k in cand])     # 질문은 한국어 원문(1차 비교와 같음)
            cand = [cand[i] for i in sorted(range(len(cand)), key=lambda i: -sc[i])]
            tr.ms["rerank"] = _ms(t)
        out = [to_chunk(rows[k]) for k in cand[: q.k]]
        tr.n_returned, tr.ms["total"] = len(out), _ms(t0)
        _last.set(tr)
        return out


def _ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)


# ---------- 서비스 입구 ----------

_searcher: Searcher | None = None
_init_lock = threading.Lock()


def warmup() -> Searcher:
    """서버 기동 때 한 번 부른다: 장부 대조 → 모델·리랭커·BM25 올리기 → 질문 하나 미리 돌리기."""
    global _searcher
    with _init_lock:
        if _searcher is None:
            s = Searcher(SearchConfig.from_env(), PgStore.from_env())
            s.embed(["warm-up"])
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
