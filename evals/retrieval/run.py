"""검색 채점: 평가셋 × 검색 함수 -> Recall@k·MRR·nDCG·비관련 거절·지연.

    python -m evals.retrieval.run --dataset evals/dataset_v1.jsonl --search-fn backend.rag.retrieve.search:search \\
        --chunks data/index/chunks.jsonl --out evals/results/retrieval_v1.json

- `--search-fn`: `모듈:함수`. 함수는 `SearchQuery`를 받아 점수 내림차순 `list[Chunk]`(또는 같은 속성을 가진 객체)를 돌려준다.
  비관련 질문에 빈 목록을 돌려주면 거절로 센다.
- `--chunks`: 코퍼스 청크 파일(JSONL, `Chunk` 필드). 주면 정답 위치가 코퍼스에 없는 관련 문항을 찾아 분모에서 빼고 이유를 적는다.
- `evals/exclusions.json`이 있으면 거기 적힌 문항도 지표에서만 뺀다(`evals/README.md`).
- 동결 확인은 `evals/freeze.py --check`가 한다. 여기서는 동결 여부를 결과에 적기만 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from backend.schemas.chunk import SearchQuery
from evals.retrieval.gold import missing_in_corpus, parse_gold
from evals.retrieval.metrics import aggregate, ranking_metrics

ROOT = Path(__file__).resolve().parents[2]
SearchFn = Callable[[SearchQuery], list]


def load_dataset(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    for r in rows:
        r["gold"] = parse_gold(r.get("gold_chunks") or []) if r["kind"] == "relevant" else []
    return rows


def load_exclusions(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return {str(e["id"]): e["reason"] for e in json.loads(path.read_text(encoding="utf-8")).get("excluded", [])}


def load_chunks(path: Path) -> list[Any]:
    return [SimpleNamespace(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve_fn(spec: str) -> SearchFn:
    mod, _, name = spec.partition(":")
    return getattr(importlib.import_module(mod), name)


def evaluate(items: list[dict], search: SearchFn, k: int = 5, *, exclusions: dict[str, str] | None = None,
             corpus: list[Any] | None = None) -> dict:
    """문항마다 검색하고 채점한다. 결과: {summary, rows}."""
    exclusions = exclusions or {}
    rows = []
    for it in items:
        q = SearchQuery(query=it["input"], as_of=it.get("as_of") if len(it.get("as_of") or "") == 10 else None, k=k)
        t = time.perf_counter()
        got = list(search(q))
        row: dict[str, Any] = {"id": it["id"], "kind": it["kind"], "irrelevant_type": it.get("irrelevant_type"),
                               "latency_s": round(time.perf_counter() - t, 6), "returned": [c.chunk_id for c in got[:k]]}
        if it["kind"] == "irrelevant":
            row["rejected"] = not got
        else:
            reason = exclusions.get(str(it["id"]))
            if not reason and not it["gold"]:
                reason = "정답 위치 없음"
            if not reason and corpus is not None:
                miss = missing_in_corpus(it["gold"], corpus)
                if len(miss) == len(it["gold"]):
                    reason = f"정답 위치가 코퍼스에 없음: {miss}"
            row["scored"] = not reason
            if reason:
                row["excluded_reason"] = reason
            else:
                row.update(ranking_metrics(it["gold"], got, k))
        rows.append(row)
    return {"summary": aggregate(rows, k), "rows": rows}


def report_md(res: dict, title: str) -> str:
    s, k = res["summary"], res["summary"]["k"]

    def f(key):
        v = s[key]
        ci = f" [{v['ci95'][0]:.2f}, {v['ci95'][1]:.2f}]" if v.get("ci95") else ""
        return f"{v['value']:.3f}{ci}" if v["value"] is not None else "없음"

    rej = s["irrelevant_rejection"]
    lines = [f"# {title}", "", f"관련 채점 {s['n_relevant_scored']}건(뺀 문항 {s['excluded']}), 비관련 {s['n_irrelevant']}건, k={k}.", "",
             "| 지표 | 값 [95% 구간] |", "|---|---|",
             f"| Recall@{k} | {f(f'recall@{k}')} |", f"| hit@{k} | {f(f'hit@{k}')} |", f"| MRR | {f('rr')} |", f"| nDCG@{k} | {f(f'ndcg@{k}')} |",
             f"| 비관련 거절 | {rej['k']}/{rej['n']}" + (f" (Wilson {rej['wilson95'][0]:.2f}~{rej['wilson95'][1]:.2f})" if rej["wilson95"] else "") + " |",
             f"| 지연 p50 / p95 | {s['latency']['p50_s']} / {s['latency']['p95_s']}초 |"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.run")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--search-fn", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--chunks", type=Path, default=None)
    ap.add_argument("--exclusions", type=Path, default=ROOT / "evals" / "exclusions.json")
    ap.add_argument("--out", type=Path, required=True, help="결과 .json (옆에 같은 이름 .md)")
    a = ap.parse_args(argv)
    items = load_dataset(a.dataset)
    res = evaluate(items, resolve_fn(a.search_fn), a.k, exclusions=load_exclusions(a.exclusions),
                   corpus=load_chunks(a.chunks) if a.chunks else None)
    res["meta"] = {"dataset": a.dataset.as_posix(), "dataset_sha256": hashlib.sha256(a.dataset.read_bytes()).hexdigest(),
                   "search_fn": a.search_fn, "run_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    a.out.with_suffix(".md").write_text(report_md(res, f"검색 채점: {a.dataset.name}"), encoding="utf-8")
    print(report_md(res, f"검색 채점: {a.dataset.name}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
