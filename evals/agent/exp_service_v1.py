"""서비스 검색기(`backend.rag.retrieve.search.Searcher`)로 단일 에이전트 그래프를 재는 측정 (PR #48 이후).

측정 전용 검색기(`exp_confirmed_v1.py`)는 저장된 분해, 하위 질문 벡터, 질문 벡터를 읽지만 이 실행기는 서비스와 같은 `Searcher`를 부른다.
- 저장소 기본값: `MemoryStore`(DB 왕복 없음). 문서 벡터는 `data/index_exp/voyage-4.npy`, 청크는 `data/chunks/chunks.jsonl`, 링크 대상은 `links.build` 결과.
- 저장소 `--store pg`: 운영 DB(`PgStore`). 주소는 저장소 .env의 `DATABASE_URL`만 읽어 이 저장소에만 넘기고, 프로세스 환경에 넣지 않으며 출력하지 않는다. 적재 장부 대조(`check_meta`)를 켠다.
- 질문 번역(영어 문장): 서비스 `translate.translate`가 로컬 Claude CLI(Haiku 5.5)를 부른다. `MemoryStore`는 번역 장부가 프로세스 안에만 있어 실행마다 새로 번역하고, `PgStore`는 `query_translations`에 저장해 다음 실행이 다시 쓴다.
- 질문 분해: 그래프가 첫 검색 전에 Claude CLI(Haiku 5.5)로 한다(`decompose=True`). 저장된 분해를 읽지 않는다.
- 질문 임베딩: 실제 Voyage API(`voyage-4`, input_type=query). 재검색도 같은 `Searcher.search`다.
- Anthropic API 키는 쓰지 않는다. `VOYAGE_API_KEY`만 환경 변수나 저장소 .env에서 읽고 출력하지 않는다.

    python -m evals.agent.exp_service_v1 run --out evals/results/agent_v1_service
    python -m evals.agent.exp_service_v1 run --store pg --out evals/results/agent_v1_service_pg
    python -m evals.agent.exp_service_v1 run --ids 3,7,16 --out <폴더>     # 점검용(partial)
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from backend.schemas.chunk import SearchQuery
from evals.agent import exp_confirmed_v1 as X
from evals.agent.run_eval import compute_metrics, verify_frozen
from evals.retrieval import exp_decompose_v1 as D
from evals.retrieval.run import load_dataset, load_exclusions

ROOT = D.ROOT
DATASET = D.DATASET
SERVICE_PATH = ("service_search_memory_store: 서비스 Searcher를 MemoryStore(DB 왕복 없음)로 돌린 값이다. "
                "측정 전용 검색기(exp_confirmed_v1) 값과 다르고, 운영 DB(PgStore) 값도 아니다")
SERVICE_PATH_PG = ("service_search_pg_store: 서비스 Searcher를 운영 DB(PgStore)로 돌린 값이다. "
                   "측정 전용 검색기(exp_confirmed_v1) 값과 다르고, 그래프는 평가 실행기가 불렀으므로 API 요청 경로 값은 아니다")


def database_url_from_env_file() -> str:
    """저장소 .env의 `DATABASE_URL`만 읽는다. 값은 출력하지 않고 프로세스 환경에도 넣지 않는다(그래프의 다른 부분이 DB를 쓰지 않게)."""
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "DATABASE_URL" and value.strip():
                return value.strip().strip('"')
    raise SystemExit(".env에 DATABASE_URL이 없다")


def build_pg_searcher(embedder=None, translator=None):
    """운영 DB(`PgStore`) 위에 서비스 `Searcher`를 만든다. 적재 장부가 voyage-4 ready가 아니면 `check_meta`가 멈춘다."""
    from backend.rag.retrieve import embed
    from backend.rag.retrieve.search import PgStore, SearchConfig, Searcher

    if embedder is None:
        model = embed.load_model("voyage-4")
        embedder = lambda texts: embed.encode_queries(model, texts)  # noqa: E731
    cfg = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none")
    store = PgStore(database_url_from_env_file())
    searcher = Searcher(cfg, store, embedder=embedder, reranker=None, translator=translator)
    return searcher, {"rows_source": "PgStore", "generation": store.generation(), "config": dataclasses.asdict(cfg)}


def build_searcher(embedder=None, translator=None):
    """`MemoryStore` 위에 서비스 `Searcher`를 만든다. embedder/translator는 시험에서 바꿔 끼우는 자리이고 None이면 실제(Voyage, Claude CLI)."""
    from backend.rag.retrieve import embed, links
    from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher

    raw, chunks, docs, _ = D.load_cell()
    rows, source = X.load_search_rows([c.chunk_id for c in chunks])
    targets = links.build(rows, D.IR, D.MANIFEST)
    rows = [{**r, "link_targets": t} for r, t in zip(rows, targets)]
    if embedder is None:
        model = embed.load_model("voyage-4")
        embedder = lambda texts: embed.encode_queries(model, texts)  # noqa: E731
    cfg = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none")
    store = MemoryStore(rows, docs, "voyage-4")
    searcher = Searcher(cfg, store, embedder=embedder, reranker=None, translator=translator, check_meta=False)
    return searcher, {"rows_source": source, "rows": len(rows), "links_with_targets": sum(1 for t in targets if t),
                      "config": dataclasses.asdict(cfg)}


def mcp_server_for(rec, use_pg: bool):
    """같은 프로세스의 FastMCP 서버. 앱과 네트워크를 쓰지 않는다. 기록기(`rec`)가 서버 안쪽에 있어 검색 기록을 그대로 남긴다.
    서버는 `org`를 DB에서 확인하는데 측정은 DB 주소를 `.env` 파일에서 읽으므로 저장소를 직접 넘긴다."""
    if not use_pg:
        raise SystemExit("--via-mcp는 --store pg로만 돈다")
    from backend.rag.retrieve.section import PgSectionStore
    from extras.mcp_skill.mcp_server.server import build_server

    return build_server(search_fn=rec, section_store=PgSectionStore(database_url_from_env_file()))


def section_reader_for(server, use_pg: bool):
    """측정의 섹션 읽기. 측정은 DB 주소를 `.env` 파일에서 읽어 그래프 기본값(환경 변수)으로는 열리지 않는다. 메모리 저장소면 읽지 않는다."""
    if server is not None:
        from backend.graph.mcp_retriever import make_mcp_section_reader
        return make_mcp_section_reader(server)
    if not use_pg:
        return lambda rule_seq, article, as_of: None
    from backend.rag.retrieve.privacy import redact_chunk
    from backend.rag.retrieve.section import PgSectionStore, get_section

    store = PgSectionStore(database_url_from_env_file())

    def read(rule_seq, article, as_of):
        found = get_section(rule_seq, article, as_of, store)
        return redact_chunk(found.model_dump()) if found else None

    return read


class RecordingSearch:
    """`Searcher.search`를 그대로 부르고 호출마다 입력과 돌려준 청크, 검색 기록(`last_search_trace`)을 남긴다. 결과는 바꾸지 않는다."""

    def __init__(self, searcher):
        self.searcher = searcher
        self.calls: list[dict] = []
        self.errors: list[str] = []

    def set_item(self, item: dict) -> None:
        self.calls = []

    def __call__(self, q: SearchQuery):
        from backend.rag.retrieve.search import last_search_trace

        first = not self.calls
        t0 = time.perf_counter()
        try:
            out = self.searcher.search(q)
        except BaseException as e:  # 조용히 넘기지 않는다: 실행기가 기록을 보고 멈춘다
            self.errors.append(f"{type(e).__name__}: {e}")
            raise
        tr = last_search_trace()
        self.calls.append({"n": len(self.calls) + 1, "kind": "first" if first else "requery", "graph_query": q.query, "sub_queries": q.sub_queries,
                           "org": q.org, "as_of": q.as_of, "k_requested": q.k, "returned": [c.chunk_id for c in out],
                           "trace": dataclasses.asdict(tr) if tr else None, "wall_s": round(time.perf_counter() - t0, 3)})
        return out


def run_cmd(args) -> int:
    X.fix_env()
    X.load_voyage_key()
    dataset = Path(args.dataset) if args.dataset else DATASET
    verify_frozen(dataset)
    from backend.graph.build import build_graph
    from backend.services.llm import is_demo_mode
    from evals.agent import tracking
    from evals.agent.run_eval import run_item

    if is_demo_mode():
        raise SystemExit("데모 모드다: 실제 모델 설정이 아니라 멈춘다")
    excluded = load_exclusions(ROOT / "evals" / "exclusions.json")
    items = [it for it in load_dataset(dataset) if str(it["id"]) not in excluded]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if str(it["id"]) in want]
    if not items:
        raise SystemExit("돌릴 문항이 없다")
    use_pg = args.store == "pg"
    searcher, setup = build_pg_searcher() if use_pg else build_searcher()
    rec = RecordingSearch(searcher)
    server = mcp_server_for(rec, use_pg) if args.via_mcp else None
    retriever = rec
    if server is not None:
        from backend.graph.mcp_retriever import make_mcp_retriever
        retriever = make_mcp_retriever(server)
    graph = X.RecordingGraph(build_graph(retriever, decompose=True, section_reader=section_reader_for(server, use_pg)))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = tracking.new_run_id("question")
    rows: list[dict] = []
    for it in items:
        rec.set_item(it)
        row = run_item(graph, it, run_id=run_id)
        X.add_recorded(row, graph.last)
        row["sub_queries"] = (graph.last or {}).get("sub_queries")
        row["decompose_source"] = (graph.last or {}).get("decompose_source")
        row["retrieval_calls"] = rec.calls
        row["first_searches"] = sum(c["kind"] == "first" for c in rec.calls)
        row["requery_searches"] = sum(c["kind"] == "requery" for c in rec.calls)
        rows.append(row)
        (out / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"문항 {it['id']}: {row['result']} 재시도 {row['retries']} 첫 검색 {row['first_searches']} 재검색 {row['requery_searches']} "
              f"분해 {len(row['sub_queries'] or [])} {row['latency_s']}초", flush=True)
        if rec.errors:
            raise SystemExit(f"검색 오류로 중단(문항 {it['id']}): {rec.errors[-1]}")
    metrics = compute_metrics(rows)
    traces = [c["trace"] for r in rows for c in r["retrieval_calls"] if c.get("trace")]
    meta = {
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "service_path": SERVICE_PATH_PG if use_pg else SERVICE_PATH,
        "store": "PgStore" if use_pg else "MemoryStore",
        "search": {**setup, "first_search": "그래프가 원 질문(한국어)과 하위 질문을 `Searcher.search`에 넘긴다. 번역은 서비스 translate(Claude CLI Haiku 5.5), 분해는 그래프(Claude CLI Haiku 5.5), 질문 임베딩은 Voyage API",
                   "requery": "재작성 검색어(영어)를 분해 없이 `Searcher.search`에 넘긴다"},
        "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"], "anthropic_api_key": "unused"},
        "excluded": sorted(excluded),
        "partial": bool(args.ids),
        "first_searches": sum(r["first_searches"] for r in rows),
        "requery_searches": sum(r["requery_searches"] for r in rows),
        "fallback_dense_ko": sum(1 for t in traces if t.get("fallback")),
        "fallback_reasons": sorted({t["fallback_reason"] for t in traces if t.get("fallback_reason")}),
        "decomposed_questions": sum(1 for r in rows if r["sub_queries"]),
        "run_id": run_id,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tracking.record_run_scores(run_id, {k: v for k, v in metrics.items() if k != "n"})
    (out / "summary.json").write_text(json.dumps({"meta": meta, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if use_pg:
        searcher.store.pool.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="그래프 실행(서비스 Searcher, 기본 MemoryStore)")
    p.add_argument("--store", choices=("memory", "pg"), default="memory", help="검색 저장소. pg는 .env의 DATABASE_URL로 운영 DB를 읽는다")
    p.add_argument("--dataset", help="평가셋 경로. 기본은 동결 v1이고, 동결된 파일만 돈다")
    p.add_argument("--ids", help="쉼표로 고른 문항만 돈다(partial, 점수로 쓰지 않는다)")
    p.add_argument("--via-mcp", action="store_true", help="검색을 같은 프로세스 MCP 서버로 부른다")
    p.add_argument("--out", required=True, help="summary.json과 rows.jsonl을 쓸 폴더")
    p.set_defaults(fn=run_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
