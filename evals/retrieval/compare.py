"""임베딩·검색 방식·리랭커 조합 비교 (가이드 p.12 "임베딩 둘 이상 비교", EVAL_REPORT 선택 근거 표).

    python -m evals.retrieval.compare --dataset evals/dataset_v2.jsonl --factory backend.rag.retrieve.search:make_search \\
        --grid evals/retrieval/grid.json --chunks data/index/chunks.jsonl --out evals/results/compare_v2

- `--factory`: `모듈:함수`. 조합 하나의 설정(dict)을 키워드 인자로 받아 검색 함수(`SearchQuery -> list[Chunk]`)를 돌려준다.
  임베딩 모델을 바꾸면 색인도 그 모델로 만들어 둬야 한다(factory가 설정에 맞는 색인을 고른다).
- `--grid`: JSON. `{"키": [값, ...]}`이면 모든 곱, `[{...}, {...}]`이면 그 목록 그대로. 예:
  `{"embedder": ["bge-m3", "intfloat/multilingual-e5-large"], "mode": ["dense", "hybrid"], "translate": ["glossary", "llm"],
    "reranker": ["none", "bge-reranker-v2-m3"], "rerank_top": [10, 30, 50]}`
- 조합마다 `<out>/<번호>.json`에 저장하고, 이미 있는 조합은 건너뛴다(중간에 멈춰도 이어서 돈다).
- `<out>/compare.md`: 조합별 Recall@k·MRR·nDCG·비관련 거절·지연 p95 표와 상위 조합. 버린 조합도 모두 남긴다(결정의 "버린 대안").
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

from evals.retrieval.run import evaluate, load_chunks, load_dataset, load_exclusions, resolve_fn

ROOT = Path(__file__).resolve().parents[2]


def expand(grid) -> list[dict]:
    if isinstance(grid, list):
        return [dict(g) for g in grid]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def key_of(cfg: dict) -> str:
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def table(results: list[tuple[dict, dict]], k: int) -> str:
    cols = sorted({c for cfg, _ in results for c in cfg})
    head = "| " + " | ".join(cols) + f" | Recall@{k} | MRR | nDCG@{k} | 비관련 거절 | 지연 p95 |"
    lines = [head, "|" + "---|" * (len(cols) + 5)]
    for cfg, s in sorted(results, key=lambda x: (-(x[1][f"recall@{k}"]["value"] or 0), -(x[1]["rr"]["value"] or 0))):
        rej = s["irrelevant_rejection"]
        lines.append("| " + " | ".join(str(cfg.get(c, "")) for c in cols)
                     + f" | {s[f'recall@{k}']['value']:.3f} | {s['rr']['value']:.3f} | {s[f'ndcg@{k}']['value']:.3f} | {rej['k']}/{rej['n']} | {s['latency']['p95_s']} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.compare")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--factory", required=True)
    ap.add_argument("--grid", type=Path, required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--chunks", type=Path, default=None)
    ap.add_argument("--exclusions", type=Path, default=ROOT / "evals" / "exclusions.json")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    items = load_dataset(a.dataset)
    corpus = load_chunks(a.chunks) if a.chunks else None
    excl = load_exclusions(a.exclusions)
    factory = resolve_fn(a.factory)
    a.out.mkdir(parents=True, exist_ok=True)
    results = []
    for cfg in expand(json.loads(a.grid.read_text(encoding="utf-8"))):
        path = a.out / f"{key_of(cfg)}.json"
        if path.is_file():
            res = json.loads(path.read_text(encoding="utf-8"))
        else:
            res = evaluate(items, factory(**cfg), a.k, exclusions=excl, corpus=corpus)
            res["config"] = cfg
            path.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"{cfg}: Recall@{a.k} {res['summary'][f'recall@{a.k}']['value']:.3f}", flush=True)
        results.append((cfg, res["summary"]))
    md = [f"# 검색 조합 비교: {a.dataset.name}", "", f"조합 {len(results)}개, k={a.k}. Recall 높은 순(같으면 MRR). "
          "관련 채점 문항 수와 뺀 문항은 조합마다 같다(각 json의 summary).", "", table(results, a.k), ""]
    (a.out / "compare.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
