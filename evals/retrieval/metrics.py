"""검색 지표 (순수 함수, 모델·네트워크 없음). `EVAL_REPORT.md` 2장 검색 지표에 쓴다.

k는 상위 몇 개까지 보는지, 결과 목록은 점수 내림차순이다.
- 정답 단위는 정답 위치 하나(`gold.GoldRef`). 같은 섹션이 청크 여러 개로 잘려도 한 번만 센다(청킹을 바꿔도 같은 기준).
- Recall@k = 상위 k개 안에서 찾은 정답 위치 수 / 정답 위치 수. 문항별 값의 평균(PRD 기준 Recall@5 0.80).
- hit@k = 상위 k개 안에 정답이 하나라도 있으면 1. page_hit@k = 정답 페이지가 하나라도 있으면 1(느슨한 하한 점검).
- MRR = 첫 정답 순위의 역수(k 안에 없으면 0) 평균. nDCG@k = 이진 이득(새 정답 위치를 찾을 때만 1/log2(i+1)).
- 비관련 거절 = 비관련 문항에서 검색이 아무것도 돌려주지 않은 비율(검색 단계 거절, PRD 기준 0.90). 구간은 Wilson 95%.
- 지연 p50·p95는 가장 가까운 순위 방식.
정답 위치가 코퍼스에 없는 관련 문항은 분모에서 빼고 건수로만 보고한다(`excluded`).
"""
from __future__ import annotations

import math
import random
from typing import Any, Sequence

PRD_RECALL_AT_5 = 0.80
PRD_IRRELEVANT_REJECTION = 0.90


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(max(1, math.ceil(pct / 100.0 * len(s))), len(s)) - 1]


def bootstrap_ci(values: Sequence[float], n: int = 2000, seed: int = 0) -> tuple[float, float] | None:
    """문항 부트스트랩 평균의 95% 구간. 값이 2개 미만이면 None."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def ranking_metrics(gold: Sequence[Any], retrieved: Sequence[Any], k: int) -> dict:
    """정답 위치 목록과 순위대로의 검색 결과 -> 한 문항의 지표. gold가 비면 ValueError."""
    if not gold:
        raise ValueError("정답 위치가 없는 문항은 순위 지표를 계산하지 않는다")
    found: set[int] = set()
    first: int | None = None
    dcg = 0.0
    page_hit = 0
    for rank, c in enumerate(list(retrieved)[:k], 1):
        cov = {j for j, g in enumerate(gold) if g.matches(c)}
        if cov and first is None:
            first = rank
        if cov - found:
            dcg += 1.0 / math.log2(rank + 1)
            found |= cov
        if any(g.page_matches(c) or g.matches(c) for g in gold):
            page_hit = 1
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(gold)) + 1))
    return {f"recall@{k}": len(found) / len(gold), f"hit@{k}": float(bool(found)), f"page_hit@{k}": float(page_hit),
            "rr": 1.0 / first if first else 0.0, f"ndcg@{k}": dcg / idcg, "first_hit_rank": first,
            "n_gold": len(gold), "n_found": len(found)}


def _mean(rows: Sequence[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if key in r]
    return sum(vals) / len(vals) if vals else None


def aggregate(rows: Sequence[dict], k: int) -> dict:
    """채점 행 -> 집계. 관련 행은 `scored`, 비관련 행은 `rejected`를 가진다."""
    rel = [r for r in rows if r["kind"] == "relevant" and r.get("scored")]
    irr = [r for r in rows if r["kind"] == "irrelevant"]
    out: dict[str, Any] = {"k": k, "n_relevant_scored": len(rel), "n_irrelevant": len(irr),
                           "excluded": [r["id"] for r in rows if r["kind"] == "relevant" and not r.get("scored")]}
    for key in (f"recall@{k}", f"hit@{k}", f"page_hit@{k}", "rr", f"ndcg@{k}"):
        vals = [r[key] for r in rel]
        ci = bootstrap_ci(vals)
        out[key] = {"value": _mean(rel, key), "ci95": list(ci) if ci else None}
    rej = sum(1 for r in irr if r["rejected"])
    w = wilson(rej, len(irr))
    out["irrelevant_rejection"] = {"value": rej / len(irr) if irr else None, "k": rej, "n": len(irr), "wilson95": list(w) if w else None}
    by_type: dict[str, dict] = {}
    for r in irr:
        t = by_type.setdefault(r.get("irrelevant_type") or "unknown", {"n": 0, "rejected": 0})
        t["n"] += 1
        t["rejected"] += int(r["rejected"])
    out["irrelevant_rejection_by_type"] = by_type
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    out["latency"] = {"n": len(lat), "p50_s": percentile(lat, 50), "p95_s": percentile(lat, 95)}
    return out
