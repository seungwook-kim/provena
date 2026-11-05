"""확정한 검색 조합을 단일 에이전트 그래프에 넣는 측정 전용 검색기 (D4 기준 점수 준비). 서비스 `search()`와 별개다.

확정 조합: `voyage-4`(문서 document, 질문 query), 영어 문장 벡터, 청크 800자·겹침 120자, 리랭커 없음, 질문 분해 + L1x2, k=5.
답변 모델은 로컬 Claude CLI(Haiku 5.5)이고 Anthropic API 키는 쓰지 않는다. 분해와 링크 확장 계산은 `evals/retrieval/exp_decompose_v1.py`를 그대로 쓴다.

검색기(`ConfirmedRetriever`)는 그래프의 `SearchQuery -> list[Chunk]` 자리에 들어간다. 항상 k=5를 돌려준다(`q.k`는 무시).
- 문항별 첫 검색: 그래프가 넘긴 재작성 질의가 아니라 그 문항의 원 질문으로 확정 조합을 그대로 돌린다. 저장한 분해(`decomposition.json`),
  하위 질문 벡터(`subq_vec_voyage.json`), 질문 벡터(`voyage-4.queries.json`)만 읽고 모델·API를 부르지 않는다. 저장값이 없으면 멈춘다.
- 재검색(같은 문항의 두 번째 호출부터): 재작성 질의(영어)를 Voyage `query` 벡터로 만들어 상위 5를 뽑고 L1x2를 적용한다. 분해하지 않는다.
  벡터는 파일 캐시(`data/index_exp/voyage-4.requery.json`)에 남겨 같은 질의는 다시 부르지 않는다.
- 필터: `q.org`, `q.as_of`를 벡터 후보와 링크 청크 양쪽에 건다(`search.valid_mask`와 같은 규칙).

    # 비용 없는 충실도 검사: 필터 없이 30문항 첫 검색이 저장된 dec+L1x2 결과와 같은지, 동결 as_of를 걸면 무엇이 달라지는지
    python -m evals.agent.exp_confirmed_v1 check
    # 그래프 실행(Claude CLI와 Voyage 질의 벡터 호출). --ids를 주면 점검용(partial)이고 점수로 쓰지 않는다
    python -m evals.agent.exp_confirmed_v1 run --ids 3,7,16 --out <폴더>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

from backend.rag.retrieve.search import RowMeta, index_dir, snapshot_rows, to_chunk, valid_mask
from backend.schemas.chunk import Chunk, SearchQuery
from evals.agent.run_eval import compute_metrics, verify_frozen
from evals.retrieval import exp_decompose_v1 as D
from evals.retrieval import experiment_v1 as ev
from evals.retrieval.run import evaluate, load_dataset, load_exclusions

ROOT = D.ROOT
DATASET = D.DATASET
K = 5
LINK_N = 2
REQUERY_CACHE = D.CACHE / "voyage-4.requery.json"
VOYAGE_TOKEN_CAP = 50_000  # 한 번 실행에서 재검색 질의 벡터에 쓸 토큰 상한(질의 하나가 수십 토큰)
STORED = {"recall@5": 0.967, "hit@5": 1.0, "rr": 0.88, "ndcg@5": 0.88}  # 질문 분해 비교에서 저장된 dec+L1x2 값(동결 30건)
COMBO = {"embedder": "voyage-4", "doc_input_type": "document", "query_input_type": "query", "query_vector": "english sentence",
         "chunk": "800/120", "reranker": "none", "decompose": True, "link": "L1x2", "k": K}


# ---------- 행과 청크 순서 ----------

def load_search_rows(ids: list[str]) -> tuple[list[dict], str]:
    """검색 결과로 돌려줄 청크 행(판 유효 구간 포함)을 `data/index_exp` 벡터와 같은 순서로 맞춰 돌려준다.

    스냅샷(`SEARCH_INDEX_DIR`, 기본 data/index)이 있으면 그것을, 없으면 스냅샷의 원본인 `data/chunks/chunks.jsonl`을 같은 규칙으로 읽는다.
    """
    index = index_dir()
    if (index / "meta.json").is_file():
        _, rows = snapshot_rows(index)
        source = f"snapshot:{index}"
    else:
        from backend.rag.retrieve.load_snapshot import versions_of

        raw = [json.loads(x) for x in D.CHUNKS.read_text(encoding="utf-8").splitlines() if x.strip()]
        valid = {(v["rule_seq"], v["version_id"]): v for v in versions_of(raw)}
        rows = [{**r, "valid_from": valid[(r["rule_seq"], r["version_id"])]["valid_from"],
                 "valid_to": valid[(r["rule_seq"], r["version_id"])]["valid_to"]} for r in raw]
        source = "data/chunks/chunks.jsonl"
    return align_rows(rows, ids), source


def align_rows(rows: list[dict], ids: list[str]) -> list[dict]:
    """행 순서가 벡터 색인(ids)과 같으면 그대로, chunk_id 집합이 같고 겹침이 없으면 chunk_id로 다시 세우고, 아니면 멈춘다."""
    got = [r["chunk_id"] for r in rows]
    if got == ids:
        return rows
    if len(set(got)) == len(got) == len(ids) and set(got) == set(ids):
        by_id = {r["chunk_id"]: r for r in rows}
        return [by_id[i] for i in ids]
    raise SystemExit(f"스냅샷 행과 벡터 색인의 chunk_id가 맞지 않는다(행 {len(got)}, 색인 {len(ids)}). 멈춘다")


def row_meta(rows: list[dict]) -> RowMeta:
    return RowMeta(keys=[(r["chunk_id"], r["version_id"]) for r in rows],
                   org=np.array([r["org"] for r in rows], dtype=object),
                   valid_from=np.array([r["valid_from"] for r in rows], dtype="datetime64[D]"),
                   valid_to=np.array([r.get("valid_to") or "NaT" for r in rows], dtype="datetime64[D]"), texts=[])


# ---------- 검색기 ----------

class ConfirmedRetriever:
    """확정 조합 검색기. 문항을 순차로 돌리는 실행기가 문항마다 `set_item`을 부른다(동시 실행 없음)."""

    def __init__(self, cell, rows: list[dict], dec: dict, sub_vec: dict, *, links=None, cache_path: Path = REQUERY_CACHE,
                 embed=None, rows_source: str = ""):
        raw, chunks, self.docs, self.qv = cell
        self.chunks = chunks
        self.rows = align_rows(rows, [c.chunk_id for c in chunks])
        self.rows_source = rows_source
        self.dec, self.sub_vec = dec, sub_vec
        self.links = links if links is not None else D.Links(raw, chunks)
        self.meta = row_meta(self.rows)
        self.cache_path = cache_path
        self.embed = embed or self._voyage_query
        self._masks: dict[tuple, np.ndarray] = {}
        self._vec_cache: dict | None = None
        self.item: dict | None = None
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self.voyage_tokens = 0  # 이 검색기가 쓴 총 Voyage 토큰(재검색 질의 벡터)

    # -- 문항 --

    def set_item(self, item: dict) -> None:
        """현재 문항을 정한다. 첫 검색에 필요한 저장값(분해, 하위 질문 벡터, 질문 벡터)이 없으면 조용히 넘기지 않고 멈춘다."""
        k = str(item["id"])
        if k not in self.dec:
            raise SystemExit(f"저장된 분해가 없다: 문항 {k}")
        if self.dec[k]["question"] != item["input"]:
            raise SystemExit(f"저장된 분해의 질문이 평가셋과 다르다: 문항 {k}")
        if ev.qkey(item["input"]) not in self.qv:
            raise SystemExit(f"저장된 질문 벡터가 없다: 문항 {k}")
        for s in self.dec[k]["sub_questions"]:
            if ev.qkey(s) not in self.sub_vec:
                raise SystemExit(f"저장된 하위 질문 벡터가 없다: 문항 {k}, {s!r}")
        self.item, self.calls = item, []

    # -- 필터 --

    def _mask(self, org: str | None, as_of: str | None) -> np.ndarray:
        key = (org, as_of)
        if key not in self._masks:
            self._masks[key] = valid_mask(self.meta, org, as_of)
        return self._masks[key]

    @staticmethod
    def _ranked(sims: np.ndarray, n: int, mask: np.ndarray | None) -> list[int]:
        """필터를 통과한 청크 가운데 점수 상위 n. 필터가 없으면 `experiment_v1._top`과 같다."""
        if mask is None:
            return list(ev._top(sims, n))
        masked = np.where(mask, sims, -np.inf).astype(np.float32)
        return [i for i in ev._top(masked, n) if mask[i]]

    def select(self, main_vec: np.ndarray, sub_vecs: list[np.ndarray], mask: np.ndarray | None) -> tuple[list[int], list[int]]:
        """상위 5와 링크로 더해진 청크. 분해 질문이 있으면 하위 질문별 상위를 번갈아 담고, 마지막에 L1x2를 건다."""
        en = self.docs @ main_vec
        if sub_vecs:
            top = D.roundrobin([self._ranked(self.docs @ v, D.POOL, mask) for v in sub_vecs], K)
        else:
            top = self._ranked(en, K, mask)[:K]
        link_sims = en if mask is None else np.where(mask, en, -np.inf).astype(np.float32)
        ext = self.links.pick(top, link_sims, LINK_N)
        if mask is not None:
            ext = [j for j in ext if mask[j]]  # 링크 청크도 같은 필터를 통과해야 한다
        return top[:K - len(ext)] + ext, ext

    # -- 검색 --

    def first_search(self, item: dict, org: str | None, as_of: str | None, *, apply_filter: bool = True) -> tuple[list[int], dict]:
        """문항의 원 질문으로 확정 조합을 실행한다(저장값만 사용). apply_filter=False는 충실도 검사용(필터 없음)."""
        k = str(item["id"])
        subs = self.dec[k]["sub_questions"]
        main = np.asarray(self.qv[ev.qkey(item["input"])]["en"], dtype=np.float32)
        sub_vecs = [np.asarray(self.sub_vec[ev.qkey(s)], dtype=np.float32) for s in subs]
        mask = self._mask(org, as_of) if apply_filter else None
        top, ext = self.select(main, sub_vecs, mask)
        return top, {"split": bool(subs), "sub_questions": list(subs), "link_added": [self.rows[j]["chunk_id"] for j in ext],
                     "n_filtered": int(mask.sum()) if mask is not None else len(self.rows), "voyage_tokens": 0, "vec_cached": None}

    def requery(self, query: str, org: str | None, as_of: str | None) -> tuple[list[int], dict]:
        """재작성 질의(영어)를 Voyage query 벡터로 바꿔 상위 5 + L1x2. 분해하지 않는다."""
        vec, tokens, cached = self.embed(query)
        mask = self._mask(org, as_of)
        top, ext = self.select(vec, [], mask)
        return top, {"split": False, "sub_questions": [], "link_added": [self.rows[j]["chunk_id"] for j in ext],
                     "n_filtered": int(mask.sum()), "voyage_tokens": tokens, "vec_cached": cached}

    def __call__(self, q: SearchQuery) -> list[Chunk]:
        if self.item is None:
            raise RuntimeError("set_item을 먼저 불러야 한다")
        first = not self.calls
        try:
            if first:
                top, info = self.first_search(self.item, q.org, q.as_of)
            else:
                top, info = self.requery(q.query, q.org, q.as_of)
        except BaseException as e:  # 조용히 넘기지 않는다: 실행기가 기록을 보고 멈춘다
            self.errors.append(f"{type(e).__name__}: {e}")
            raise
        out = [to_chunk(self.rows[i]) for i in top]
        self.calls.append({"n": len(self.calls) + 1, "kind": "first" if first else "requery", "graph_query": q.query,
                           "retrieval_query": self.item["input"] if first else q.query, "org": q.org, "as_of": q.as_of,
                           "k_requested": q.k, "returned": [c.chunk_id for c in out], **info})
        return out

    # -- 재검색 질의 벡터 (Voyage, 파일 캐시) --

    def _voyage_query(self, query: str) -> tuple[np.ndarray, int, bool]:
        if self._vec_cache is None:
            self._vec_cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}
        key = ev.qkey(query)
        if key in self._vec_cache:
            return np.asarray(self._vec_cache[key]["vec"], dtype=np.float32), 0, True
        used = [0]
        vec = ev._voyage([query], "query", used)[0]
        self.voyage_tokens += used[0]
        if self.voyage_tokens > VOYAGE_TOKEN_CAP:
            raise SystemExit(f"재검색 질의 벡터 토큰이 상한 {VOYAGE_TOKEN_CAP:,}을 넘었다")
        self._vec_cache[key] = {"text": query, "vec": vec.tolist()}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._vec_cache), encoding="utf-8")
        tmp.replace(self.cache_path)
        return vec, used[0], False


def build_retriever(cache_path: Path = REQUERY_CACHE) -> ConfirmedRetriever:
    cell = D.load_cell()
    rows, source = load_search_rows([c.chunk_id for c in cell[1]])
    dec = json.loads((D.DEC / "decomposition.json").read_text(encoding="utf-8"))["items"]
    sub_vec = json.loads((D.DEC / "subq_vec_voyage.json").read_text(encoding="utf-8"))["vec"]
    return ConfirmedRetriever(cell, rows, dec, sub_vec, cache_path=cache_path, rows_source=source)


# ---------- check: 비용 없는 충실도 검사 ----------

def _vals(s: dict) -> dict:
    return {k: (round(s[k]["value"], 4) if isinstance(s[k], dict) else round(s[k], 4)) for k in ("recall@5", "hit@5", "rr", "ndcg@5")}


def check(args) -> int:
    items = load_dataset(DATASET)
    retr = build_retriever()
    by_q = {it["input"]: it for it in items}
    exclusions = load_exclusions(ROOT / "evals" / "exclusions.json")
    corpus = retr.chunks

    def run(apply_filter: bool) -> dict:
        def search(q):
            it = by_q[q.query]
            top, _ = retr.first_search(it, q.org, q.as_of, apply_filter=apply_filter)
            return [to_chunk(retr.rows[i]) for i in top]
        res = evaluate(items, search, K, exclusions=exclusions, corpus=corpus)
        return {"summary": D.summary_brief(res["summary"]), "rows": res["rows"]}

    plain, dated = run(False), run(True)
    stored = json.loads((D.DEC / "voyage" / "dec+L1x2.json").read_text(encoding="utf-8"))
    old_vals, old_rows = _vals(stored["summary_frozen"]), {r["id"]: r for r in stored["rows_frozen"]}
    print(f"행 출처 {retr.rows_source}, 행 {len(retr.rows)}개")
    print(f"저장값(dec+L1x2.json) {old_vals}\n지침 값          {STORED}\n다시 계산(필터 없음) {plain['summary']}")
    same_vals = old_vals == plain["summary"] and {k: round(v, 3) for k, v in plain["summary"].items()} == STORED
    diff_set = [r["id"] for r in plain["rows"] if set(r["returned"]) != set(old_rows[r["id"]]["returned"])]
    diff_order = [r["id"] for r in plain["rows"] if r["returned"] != old_rows[r["id"]]["returned"] and r["id"] not in diff_set]
    print(f"지표 일치 {same_vals} / 청크 집합이 다른 문항 {diff_set} / 순서만 다른 문항 {diff_order}")
    changed = [r["id"] for r in dated["rows"] if set(r["returned"]) != set(old_rows[r["id"]]["returned"])]
    print(f"동결 as_of 적용 지표 {dated['summary']} / 필터 없을 때와 청크 집합이 달라지는 문항 {changed}")
    for r in dated["rows"]:
        if r["id"] in changed:
            o = old_rows[r["id"]]["returned"]
            print(f"  문항 {r['id']}: 빠진 {sorted(set(o) - set(r['returned']))} 들어온 {sorted(set(r['returned']) - set(o))}")
    return 0 if same_vals and not diff_set else 1


# ---------- run: 그래프 실행 ----------

class RecordingGraph:
    """그래프 출력을 문항마다 붙잡아 두는 얇은 덮개. 실행 동작은 바꾸지 않고 `invoke` 결과를 그대로 돌려준다."""

    def __init__(self, graph):
        self.graph = graph
        self.last: dict | None = None

    def invoke(self, *args, **kwargs):
        self.last = None
        out = self.graph.invoke(*args, **kwargs)
        self.last = out
        return out


RECORDED_FIELDS = ("grounding", "judge_reason", "clarify_question", "trimmed_citations")  # 점수에는 쓰지 않는 기록 칸


def add_recorded(row: dict, out: dict | None) -> dict:
    """그래프 출력의 판정 기록을 행에 더한다. 답 초안은 근거 판정이 거절하면 상태의 `answer`가 거절 문구로 덮이므로 남지 않는다."""
    out = out or {}
    for name in RECORDED_FIELDS:
        row[name] = out.get(name)
    return row


def make_graph(retr, **kw) -> RecordingGraph:
    """측정용 그래프. 이 검색기는 저장된 분해를 읽으므로 그래프의 질문 분해(LLM)는 끈다(`decompose=False`, 환경 변수가 있어도 켜지지 않는다)."""
    from backend.graph.build import build_graph

    return RecordingGraph(build_graph(retr, decompose=False, **kw))


def fix_env() -> None:
    """실행 환경을 코드에서 고정한다: 로컬 Claude CLI(Haiku 5.5). Anthropic API 키와 폴백 모델은 쓰지 않는다."""
    for name in ("LLM_API_KEY", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY", "DEMO_MODE", "LLM_RECORD"):
        os.environ.pop(name, None)
    os.environ["LLM_PROVIDER"] = "claude_cli"
    os.environ["LLM_MODEL"] = "claude-haiku-5-5"


def load_voyage_key() -> None:
    """VOYAGE_API_KEY만 환경 변수나 저장소 .env에서 읽는다. 값은 출력하지 않고 .env의 다른 값은 읽어 쓰지 않는다."""
    if os.environ.get("VOYAGE_API_KEY"):
        return
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*VOYAGE_API_KEY\s*=\s*(.*)$", line)
            if m and m.group(1).strip().strip("\"'"):
                os.environ["VOYAGE_API_KEY"] = m.group(1).strip().strip("\"'")
                return
    raise SystemExit("VOYAGE_API_KEY가 환경 변수와 .env에 없다")


def run_cmd(args) -> int:
    fix_env()
    load_voyage_key()
    verify_frozen(DATASET)
    from backend.services.llm import is_demo_mode
    from evals.agent import tracking
    from evals.agent.run_eval import run_item

    if is_demo_mode():
        raise SystemExit("데모 모드다: 실제 모델 설정이 아니라 멈춘다")
    excluded = load_exclusions(ROOT / "evals" / "exclusions.json")
    items = [it for it in load_dataset(DATASET) if str(it["id"]) not in excluded]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if str(it["id"]) in want]
    if not items:
        raise SystemExit("돌릴 문항이 없다")
    retr = build_retriever()
    graph = make_graph(retr)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = tracking.new_run_id("question")
    rows: list[dict] = []
    for it in items:
        retr.set_item(it)
        tok0 = retr.voyage_tokens
        row = run_item(graph, it, run_id=run_id)
        add_recorded(row, graph.last)
        row["retrieval_calls"] = retr.calls
        row["first_searches"] = sum(c["kind"] == "first" for c in retr.calls)
        row["requery_searches"] = sum(c["kind"] == "requery" for c in retr.calls)
        row["voyage_tokens"] = retr.voyage_tokens - tok0
        rows.append(row)
        (out / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"문항 {it['id']}: {row['result']} 재시도 {row['retries']} 첫 검색 {row['first_searches']} 재검색 {row['requery_searches']} "
              f"{row['latency_s']}초", flush=True)
        if retr.errors:
            raise SystemExit(f"검색기 오류로 중단(문항 {it['id']}): {retr.errors[-1]}")
    metrics = compute_metrics(rows)
    meta = {
        "dataset": DATASET.name,
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "search": {**COMBO, "first_search": "문항의 원 질문, 저장된 분해·하위 질문 벡터·질문 벡터(모델·API 호출 없음)",
                   "requery": "그래프가 넘긴 재작성 질의를 Voyage query 벡터로(분해 없음, 상위 5 + L1x2), 벡터는 파일 캐시",
                   "filter": "q.org, q.as_of를 벡터 후보와 링크 청크 양쪽에(valid_mask)", "rows_source": retr.rows_source},
        "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"], "anthropic_api_key": "unused"},
        "service_path": "not_service_search: 측정 전용 검색기이며 서비스 경로(backend.rag.retrieve.search) 값이 아니다",
        "excluded": sorted(excluded),
        "partial": bool(args.ids),
        "voyage_tokens": retr.voyage_tokens,
        "first_searches": sum(r["first_searches"] for r in rows),
        "requery_searches": sum(r["requery_searches"] for r in rows),
        "run_id": run_id,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tracking.record_run_scores(run_id, {k: v for k, v in metrics.items() if k != "n"})
    (out / "summary.json").write_text(json.dumps({"meta": meta, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="충실도 검사(저장값만 읽음, 비용 없음)").set_defaults(fn=check)
    p = sub.add_parser("run", help="그래프 실행(Claude CLI, Voyage 질의 벡터)")
    p.add_argument("--ids", help="쉼표로 고른 문항만 돈다(partial, 점수로 쓰지 않는다)")
    p.add_argument("--out", required=True, help="summary.json과 rows.jsonl을 쓸 폴더")
    p.set_defaults(fn=run_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
