"""평가셋 v2 38번의 정답 기준이 바뀐 영향을 저장된 결과로 다시 계산한다 (비용 0원, LLM·검색 호출 없음).

v2는 2026-11-02에 동결했고 2026-11-07에 38번 정답만 고쳐 다시 동결했다(결정 0075). 이 도구는 저장된 결과 행(`rows.jsonl`)의
인용 청크 id를 코드로 정답 위치와 맞춰, 38번 한 문항만 이전 정답(첫 동결본)과 현재 정답(`evals/dataset_v2.jsonl`)으로 각각 채점한 뒤
정답 근거 인용률, 인용 정확도, 오답 근거 비율을 다시 낸다. 38번 밖의 49문항은 저장된 값을 그대로 쓴다. 채점 정의는
`evals/agent/run_eval.py`의 `compute_metrics`와 같다(LLM 판정이 들어가는 지표는 다루지 않는다).

검산: 각 결과의 38번 행을 그 결과가 쟀을 때의 정답 기준(저장된 `gold_total`로 판별)으로 다시 채점해 저장된 `gold_hit`, `cited_on_gold`와 같은지 보고,
현재 정답 기준으로 쟀던 결과는 다시 낸 지표가 `summary.json`의 값과 같은지도 본다.

    python -m evals.agent.rescore_v2_item38 --chunks data/index/chunks.jsonl --out evals/results/v2_item38_rescore/rescore.json

`data/index/chunks.jsonl`은 `data/index.tar.gz`를 푼 파일이다.
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from types import SimpleNamespace

from evals.retrieval.gold import parse_gold

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
ITEM = 38
# 첫 동결본(2026-11-02, 커밋 2321e02)의 38번 정답 위치 4개. 2026-11-07에 마지막 절(SaaS Okta SSO 요건)을 빼고 요청 시작 대안을 묶었다.
OLD_GOLD = [
    "business-technology/enterprise-applications/guides/zip-guide/_index.md > Zip - Getting Started > How to initiate a new request?",
    "business-technology/enterprise-applications/guides/zip-guide/_index.md > Zip - Getting Started > How to request a new vendor? | finance/procurement/tips-for-submitting-a-zip-request.md > Other Tips for Submitting Requests",
    "security/security-assurance/security-risk/third-party-risk-management.md > What Triggers a TPRM Assessment?",
    "security/security-assurance/security-risk/third-party-risk-management.md > Security Considerations for Vendor Selection",
]
KEYS = ("cited_correct_rate", "citation_accuracy", "wrong_citation_rate")


def _rate(num: float, den: int) -> float | None:
    return None if den == 0 else num / den


def metrics(rows: list[dict]) -> dict:
    """`run_eval.compute_metrics`의 세 지표와 같은 정의."""
    relevant = [r for r in rows if not r["expect_refusal"]]
    answered = [r for r in relevant if r["answered"]]
    return {
        "cited_correct_rate": _rate(sum(r["gold_hit"] / r["gold_total"] for r in answered if r["gold_total"]), len(relevant)),
        "wrong_citation_rate": _rate(sum(r["cited_on_gold"] < len(r["cited"]) for r in answered), len(answered)),
        "citation_accuracy": _rate(sum(r["cited_on_gold"] / len(r["cited"]) for r in answered if r["cited"]), len(answered)),
    }


def rescore(row: dict, gold: list, chunks: dict) -> dict:
    objs = [chunks[c] for c in row["cited"]]
    out = dict(row)
    out["gold_total"] = len(gold)
    out["gold_hit"] = sum(any(g.matches(c) for c in objs) for g in gold)
    out["cited_on_gold"] = sum(any(g.matches(c) for g in gold) for c in objs)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chunks", type=Path, default=ROOT / "data" / "index" / "chunks.jsonl")
    ap.add_argument("--dataset", type=Path, default=ROOT / "evals" / "dataset_v2.jsonl")
    ap.add_argument("--out", type=Path, default=RESULTS / "v2_item38_rescore" / "rescore.json")
    args = ap.parse_args(argv)

    new_entries = next(json.loads(l)["gold_chunks"] for l in args.dataset.read_text(encoding="utf-8").splitlines() if l.strip() and json.loads(l)["id"] == ITEM)
    old_gold, new_gold = parse_gold(OLD_GOLD), parse_gold(new_entries)

    found: list[tuple[Path, list[dict]]] = []
    for p in sorted(glob.glob(str(RESULTS / "agent_v2*" / "*" / "rows.jsonl"))):
        rows = [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(r["id"] == ITEM for r in rows):
            found.append((Path(p), rows))
    wanted = {c for _, rows in found for r in rows if r["id"] == ITEM for c in r["cited"]}
    chunks: dict[str, SimpleNamespace] = {}
    for line in args.chunks.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d["chunk_id"] in wanted:
            chunks[d["chunk_id"]] = SimpleNamespace(**d)
    missing = wanted - set(chunks)
    if missing:
        raise SystemExit(f"청크 파일에 없는 인용 id가 있다: {sorted(missing)}")

    results = []
    for path, rows in found:
        r38 = next(r for r in rows if r["id"] == ITEM)
        basis = {len(old_gold): "old", len(new_gold): "new"}.get(r38["gold_total"], "unknown")
        recomputed = rescore(r38, old_gold if basis == "old" else new_gold, chunks)
        row_ok = (recomputed["gold_hit"], recomputed["cited_on_gold"]) == (r38["gold_hit"], r38["cited_on_gold"])
        rows_old = [rescore(r, old_gold, chunks) if r["id"] == ITEM else r for r in rows]
        rows_new = [rescore(r, new_gold, chunks) if r["id"] == ITEM else r for r in rows]
        m_old, m_new = metrics(rows_old), metrics(rows_new)
        summary = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))["metrics"]
        stored_basis_metrics = m_old if basis == "old" else m_new
        summary_ok = all(abs(stored_basis_metrics[k] - summary[k]) < 1e-9 for k in KEYS)
        a38 = {"answered": r38["answered"], "cited": len(r38["cited"]),
               "old": [rescore(r38, old_gold, chunks)[k] for k in ("gold_hit", "gold_total", "cited_on_gold")],
               "new": [rescore(r38, new_gold, chunks)[k] for k in ("gold_hit", "gold_total", "cited_on_gold")]}
        results.append({"folder": str(path.parent.relative_to(RESULTS)).replace("\\", "/"), "measured_with_gold": basis,
                        "item38_row_matches_stored": row_ok, "metrics_match_summary_json": summary_ok,
                        "item38_hit_total_on_gold": a38, "old_gold": m_old, "new_gold": m_new})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"item": ITEM, "old_gold": OLD_GOLD, "new_gold": new_entries, "results": results}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    bad = [r["folder"] for r in results if not (r["item38_row_matches_stored"] and r["metrics_match_summary_json"])]
    print(f"{len(results)}개 결과 폴더를 다시 계산했다 -> {args.out}")
    if bad:
        print("검산이 맞지 않는 폴더:", *bad, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
