"""질문 그래프 평가 실행기 (L-06, 가이드 p.17). 동결된 평가셋으로 그래프를 돌려 지표 5개를 나눠 낸다.

| 지표 | 정의 |
|---|---|
| cited_correct_rate (정답 근거 인용률) | 관련 문항에서 인용이 맞힌 정답 위치 수 / 정답 위치 수의 평균. 답하지 않으면 0 |
| wrong_citation_rate (오답 근거) | 답을 낸 관련 문항 중 정답 위치 밖의 청크를 하나라도 인용한 문항 비율 |
| over_refusal_rate (과잉 거절) | 관련 문항 중 거절, 되묻기, 미연결로 끝난 비율 |
| correct_refusal_rate (올바른 거절) | 비관련 문항 중 답을 내지 않은 비율 |
| hallucination_risk_rate (환각 위험) | 답 초안이 나온 문항 중 가짜 인용을 냈거나 비관련 문항에 답한 비율 |

분모가 0이면 값은 None이다. 답 단계 근거 판정은 후처리 거절이므로 그 단계 없는 값도 따로 낸다(GATES G5).
보조 값: 인용 정확도(인용한 청크 중 정답 위치에 맞는 비율, SPEC.md), 판 날짜 표시, 응답 시간 p95, 채점 LLM 점수.

사용:
  python -m evals.agent.run_eval --out evals/results/agent_v1_single                     (서비스 search, DB)
  python -m evals.agent.run_eval --embedder arctic-l-v2 --mode hybrid_ko_kw --reranker bge --rerank-top 10 --ids 1,16 --out 폴더
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any

from backend.schemas import Chunk
from backend.services import llm_trace
from backend.services.cost import CostCapExceeded
from evals.agent import tracking
from evals.agent.judge import judge_answer
from evals.retrieval.run import load_dataset, load_exclusions

EVALS = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = EVALS / "dataset_v1.jsonl"


def verify_frozen(path: Path) -> None:
    """평가셋이 evals/FROZEN.json의 sha256과 같아야 돈다."""
    entry = json.loads((EVALS / "FROZEN.json").read_text(encoding="utf-8")).get(path.name)
    if entry is None:
        raise SystemExit(f"동결되지 않은 평가셋입니다: {path.name}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise SystemExit(f"평가셋이 동결 뒤 바뀌었습니다: {path.name}")


def _as_of(item: dict) -> str | None:
    """평가셋의 as_of를 YYYY-MM-DD로 바꾼다. 월 단위(YYYY-MM)는 그 달의 마지막 날로 둔다(그 달 안에 유효했던 가장 늦은 판이 기준).
    형식이 맞지 않는 값은 None(기준일 없음, 그래프가 오늘로 채운다)."""
    v = item.get("as_of")
    if isinstance(v, str) and len(v) == 10:
        return v
    if isinstance(v, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
        return f"{v}-{calendar.monthrange(int(v[:4]), int(v[5:]))[1]:02d}"
    return None


def run_item(graph, item: dict, *, run_id: str, judge_llm: Any = None) -> dict:
    thread_id = f"eval-{item['id']}-{uuid.uuid4().hex[:6]}"
    with llm_trace.capture() as llm_calls:  # 호출별 시간(`llm_trace` 칸). 지표 계산에는 쓰지 않는다
        config = tracking.eval_config("question", item["id"], run_id=run_id, thread_id=thread_id)
        t0 = time.perf_counter()
        try:
            out = graph.invoke({"question": item["input"], "user_id": "eval-user", "thread_id": thread_id, "as_of": _as_of(item)}, config)
        except CostCapExceeded:
            tracking.finish_item(config)
            raise
        except Exception as e:  # noqa: BLE001  한 문항의 실패로 전체 측정을 잃지 않는다. 답을 못 낸 문항으로 세고 오류 수를 따로 보인다
            out = {"kind": "error", "answer": f"{type(e).__name__}: {e}"}
        row = _row(item, out, time.perf_counter() - t0)
    row["llm_trace"] = list(llm_calls)
    cost = tracking.finish_item(config, _item_scores(row))
    row["cost_usd"] = cost.get("cost_usd", 0.0)
    if judge_llm is not None and row["answered"] and item["kind"] == "relevant":
        evidence = [c.get("text", "") for c in out.get("chunks", []) if _hits(item, c)]
        row["judge"] = judge_answer(question=item["input"], answer=row["answer"], gold_evidence=evidence, judge_llm=judge_llm).to_dict()
    return row


def _hits(item: dict, chunk: dict) -> bool:
    c = Chunk(**chunk)
    return any(g.matches(c) for g in item["gold"])


def _row(item: dict, out: dict, seconds: float) -> dict:
    kind, cites = out.get("kind"), out.get("citations", [])
    gold = item["gold"]
    objs = [Chunk(**c) for c in cites]
    answered = kind == "answer"
    return {
        "id": item["id"],
        "kind": item["kind"],
        "irrelevant_type": item.get("irrelevant_type"),
        "question": item["input"],
        "expect_refusal": item["kind"] != "relevant",
        "result": kind,
        "route": out.get("route"),
        "answered": answered,
        "answer": out.get("answer") or "",
        "cited": [c["chunk_id"] for c in cites],
        "cited_on_gold": sum(any(g.matches(c) for g in gold) for c in objs),
        "gold_total": len(gold),
        "gold_hit": sum(any(g.matches(c) for c in objs) for g in gold),
        "dropped": list(out.get("dropped_citations", [])),
        "drafted": bool(out.get("drafted")),
        "refuse_stage": "" if answered else ("answer_check" if out.get("refuse_reason") else "before_answer"),
        "refuse_reason": out.get("refuse_reason") or "",
        "retries": out.get("retries", 0),
        "search_stats": out.get("search_stats", {}),
        "search_query": out.get("search_query"),
        "retrieved": [c["chunk_id"] for c in out.get("chunks", [])],
        "shows_date": answered and all(c.get("version_date") in (out.get("answer") or "") for c in cites),
        "latency_s": round(seconds, 3),
    }


def _item_scores(r: dict) -> dict[str, float | None]:
    if r["expect_refusal"]:
        return {"correct_refusal": 0.0 if r["answered"] else 1.0}
    return {
        "cited_correct": r["gold_hit"] / r["gold_total"] if r["answered"] and r["gold_total"] else 0.0,
        "over_refusal": 0.0 if r["answered"] else 1.0,
        "wrong_citation": (1.0 if r["cited_on_gold"] < len(r["cited"]) else 0.0) if r["answered"] else None,
    }


def _rate(num: float, den: int) -> float | None:
    return None if den == 0 else num / den


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def compute_metrics(rows: list[dict]) -> dict:
    relevant = [r for r in rows if not r["expect_refusal"]]
    irrelevant = [r for r in rows if r["expect_refusal"]]
    answered = [r for r in relevant if r["answered"]]
    drafted = [r for r in rows if r["drafted"]]
    risky = [r for r in drafted if r["dropped"] or (r["answered"] and r["expect_refusal"])]
    all_answered = [r for r in rows if r["answered"]]
    scores = [r["judge"]["score"] for r in rows if (r.get("judge") or {}).get("score") is not None]
    return {
        "n": len(rows),
        "errors": sum(r.get("result") == "error" for r in rows),
        "cited_correct_rate": _rate(sum(r["gold_hit"] / r["gold_total"] for r in answered if r["gold_total"]), len(relevant)),
        "wrong_citation_rate": _rate(sum(r["cited_on_gold"] < len(r["cited"]) for r in answered), len(answered)),
        "over_refusal_rate": _rate(len(relevant) - len(answered), len(relevant)),
        "correct_refusal_rate": _rate(sum(not r["answered"] for r in irrelevant), len(irrelevant)),
        "hallucination_risk_rate": _rate(len(risky), len(drafted)),
        "answer_check_refusals": sum(r["refuse_stage"] == "answer_check" for r in rows),
        "correct_refusal_rate_without_answer_check": _rate(sum(not r["answered"] and r["refuse_stage"] != "answer_check" for r in irrelevant), len(irrelevant)),
        "over_refusal_rate_without_answer_check": _rate(sum(not r["answered"] and r["refuse_stage"] != "answer_check" for r in relevant), len(relevant)),
        "citation_accuracy": _rate(sum(r["cited_on_gold"] / len(r["cited"]) for r in answered if r["cited"]), len(answered)),
        "as_of_shown_rate": _rate(sum(bool(r["shows_date"]) for r in all_answered), len(all_answered)),
        "latency_p95_s": _p95([r["latency_s"] for r in rows]),
        "judge_score": _rate(sum(scores), len(scores)),
        "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 6),
    }


def run_eval(graph, items: list[dict], *, judge_llm: Any = None, run_id: str | None = None) -> dict:
    run_id = run_id or tracking.new_run_id("question")
    rows = [run_item(graph, it, run_id=run_id, judge_llm=judge_llm) for it in items]
    metrics = compute_metrics(rows)
    tracking.record_run_scores(run_id, {k: v for k, v in metrics.items() if k != "n"})
    return {"metrics": metrics, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--embedder", help="주면 스냅샷 검색(make_search), 없으면 서비스 search")
    ap.add_argument("--mode", default="hybrid_ko_kw")
    ap.add_argument("--reranker", default="none")
    ap.add_argument("--rerank-top", type=int, default=0)
    ap.add_argument("--ids", help="쉼표로 고른 문항만 돈다. 점수로 쓰지 않는 점검용")
    ap.add_argument("--judge", action="store_true", help="채점 LLM 점수를 낸다(G-07)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    verify_frozen(a.dataset)
    from backend.graph.build import build_graph
    from backend.services.llm import get_chat_model

    retriever = None
    if a.embedder:
        from backend.rag.retrieve.search import make_search

        retriever = make_search(a.embedder, a.mode, a.reranker, a.rerank_top)
    excluded = load_exclusions(EVALS / "exclusions.json")
    items = [it for it in load_dataset(a.dataset) if str(it["id"]) not in excluded]
    if a.ids:
        want = {x.strip() for x in a.ids.split(",")}
        items = [it for it in items if str(it["id"]) in want]
    report = run_eval(build_graph(retriever), items, judge_llm=get_chat_model() if a.judge else None)
    report["meta"] = {
        "dataset": a.dataset.name,
        "dataset_sha256": hashlib.sha256(a.dataset.read_bytes()).hexdigest(),
        "search": {"embedder": a.embedder, "mode": a.mode, "reranker": a.reranker, "rerank_top": a.rerank_top} if a.embedder else "service",
        "excluded": sorted(excluded),
        "partial": bool(a.ids),
    }
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "summary.json").write_text(json.dumps({"meta": report["meta"], "metrics": report["metrics"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        (a.out / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in report["rows"]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
