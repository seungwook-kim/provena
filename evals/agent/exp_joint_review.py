"""합동 검토(팀 에이전트 4개, `backend/graph/departments/review.py`) 대 단일 질문 그래프 측정 (사전 등록 62.9).

같은 입력 글 한 건을 두 경로에 넣고 문항(입력)과 회차마다 순서를 바꿔 번갈아 돌린다.

- single: 서비스 질문 그래프(`backend.graph.build.build_graph`, 서비스 설정 61.51)의 정책 질문 경로. 합동 검토를 연결하지 않으므로 입력이 `review`로 분류돼도 정책 질문으로 처리된다.
- joint: 합동 검토 그래프(`build_review_graph`)를 그대로 부른다. 질문 종류 판정(classify)은 거치지 않는다. 쟁점표를 합치고 사람 승인 `interrupt`에서 멈추는 데까지 잰다
  (승인 대기 시간과 저장은 재지 않는다. 승인함을 연결하지 않고 저장소에 쓰지 않는다).

같은 서비스 검색기(`Searcher`, 저장소만 DB 대신 색인 스냅샷 `data/index/`를 numpy로), 같은 채팅 모델 객체(Haiku 5.5, OpenRouter), 같은 서비스 환경(`service_profile`)을 쓴다.
공정을 위해 번역 장부와 질문 벡터 기억을 호출마다 비운다(두 경로 모두 매번 번역을 새로 부른다).

입력(8건): (가) 합동 검토 Spec의 입력 형태 "새 외부 SaaS 모니터링 도구를 연 N에 도입하려 한다." 6건(금액은 데모 녹화와 `evals/retrieval/range_context.py`가 쓴 1만, 3만, 5만, 10만, 30만 달러와
Spec 예시의 4만 달러). 정답 근거는 `range_context.py`에 손으로 적어 둔 금액 구간 행(Approving expense) 하나다. 4만 달러는 같은 표에서 3만과 5만이 속한 구간(>$25K up to $50K)에 든다.
(나) 동결 평가셋 v2 중 과거 측정에서 질문 종류 판정이 `review`로 분류한 7번, 38번(평가셋의 정답 그대로). 15번은 `decision`으로 분류돼 뺐다.

지표는 `evals/agent/run_eval.compute_metrics`를 그대로 쓰고(정답 근거 인용률, 정답 밖 인용, 과잉 거절, 인용 정확도), 응답 시간, 호출 수(번역 포함), 비용을 더한다. 두 경로 공통의 코드 대조 지표:
인용 통과율(코드가 청크와 대조해 통과한 인용 / (통과 + 탈락)), 인용한 청크가 속한 절 가운데 네 팀 절(security, infra, business-technology, finance)의 수.

    python -m evals.agent.exp_joint_review run --set main --out evals/results/joint_review_vs_single_2026-11-10/main --rounds 3
    python -m evals.agent.exp_joint_review run --set detail --out evals/results/joint_review_vs_single_2026-11-10/detail --rounds 3   (사전 등록 62.11, 상세 입력 6건)
환경 변수 `OPENROUTER_API_KEY`(sk-or-로 시작)와 `VOYAGE_API_KEY`는 호출하는 쪽이 프로세스 환경으로만 넘긴다. 값은 출력하거나 파일에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
import uuid
from itertools import combinations
from pathlib import Path
from typing import Any

from evals.agent import exp_confirmed_v1 as X
from evals.agent import exp_multi_v2 as M
from evals.agent.run_eval import compute_metrics, _as_of
from evals.retrieval.gold import GoldRef
from evals.retrieval.run import load_dataset
from evals.retrieval.range_context import AMOUNTS, EXPENSE

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "dataset_v2.jsonl"
INDEX = ROOT / "data" / "index"
TEAM_ORGS = ("security", "infra", "business-technology", "finance")
V2_IDS = (7, 38)
AMOUNT_ORDER = ("10K", "30K", "40K", "50K", "100K", "300K")
AMOUNT_TEXT = {"10K": "1만 달러", "30K": "3만 달러", "40K": "4만 달러", "50K": "5만 달러", "100K": "10만 달러", "300K": "30만 달러"}
BAND = {**{k: v[2] for k, v in AMOUNTS.items()}, "40K": AMOUNTS["30K"][2]}  # 4만 달러는 3만·5만과 같은 구간
REQUEST = "새 외부 SaaS 모니터링 도구를 연 {amount}에 도입하려 한다."
# 보완 입력(사전 등록 62.11): 같은 금액 입력에 합동 검토 Supervisor가 되물은 값(도구 종류, 벤더, 보낼 데이터, 계약 기간)을 처음부터 적은 글
REQUEST_DETAIL = "새 외부 SaaS 모니터링 도구를 연 {amount}에 1년 계약으로 도입하려 한다. 벤더는 외부 상용 업체이고, 서비스 로그와 메트릭만 외부로 보내며 고객 개인정보는 포함하지 않는다."
COST_STOP_USD = 2.0  # 측정 전체 비용 상한(사용자 승인 상한 3달러보다 낮은 중단선)


def build_items(set_name: str = "main") -> list[dict]:
    """`main`(사전 등록 62.9): 금액 입력 6건 + v2 7·38번. `detail`(62.11): 상세 입력 6건."""
    _, rows = _snapshot_rows()
    items: list[dict] = []
    for key in AMOUNT_ORDER:
        title = EXPENSE + BAND[key]
        row = next((r for r in rows if (r.get("article") or "") == title), None)
        if row is None:
            raise SystemExit(f"색인에서 금액 구간 행을 찾지 못했다: {title}")
        detail = set_name == "detail"
        items.append({"id": f"{'D' if detail else 'A'}-{key}", "group": "amount", "kind": "relevant",
                      "input": (REQUEST_DETAIL if detail else REQUEST).format(amount=AMOUNT_TEXT[key]), "as_of": None,
                      "gold": [GoldRef(chunk_id=row["chunk_id"], label=title)], "gold_label": title})
    if set_name == "main":
        v2 = {it["id"]: it for it in load_dataset(DATASET)}
        for i in V2_IDS:
            it = dict(v2[i])
            it["group"] = "v2"
            it["id"] = f"v2-{i}"
            it["gold_label"] = " || ".join(it.get("gold_chunks") or [])
            items.append(it)
    return items


def _snapshot_rows():
    from backend.rag.retrieve.search import snapshot_rows
    return snapshot_rows(INDEX)


class Rec:
    """검색기를 감싸 호출 기록과 돌려준 청크(id별)를 남긴다. 결과는 바꾸지 않는다. 팀 에이전트가 동시에 불러도 된다."""

    def __init__(self, searcher):
        self.searcher = searcher
        self.calls: list[dict] = []
        self.chunks: dict[str, Any] = {}
        self.errors: list[str] = []

    def reset(self) -> None:
        self.calls, self.chunks, self.errors = [], {}, []

    def __call__(self, q):
        t0 = time.perf_counter()
        try:
            out = self.searcher.search(q)
        except BaseException as e:  # noqa: BLE001
            self.errors.append(f"{type(e).__name__}: {e}")
            raise
        for c in out:
            self.chunks[c.chunk_id] = c
        self.calls.append({"kind": "search", "graph_query": q.query, "sub_queries": q.sub_queries, "org": q.org, "as_of": q.as_of, "k_requested": q.k,
                           "returned": [c.chunk_id for c in out], "wall_s": round(time.perf_counter() - t0, 3)})
        return out


def build_search():
    import dataclasses
    import numpy as np
    from backend.rag.retrieve import embed
    from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher

    meta, rows = _snapshot_rows()
    links = [json.loads(x) for x in (INDEX / "links.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(links) != len(rows) or any(a["chunk_id"] != b["chunk_id"] for a, b in zip(rows, links)):
        raise SystemExit("links.jsonl과 chunks.jsonl 줄이 다르다")
    for r, lk in zip(rows, links):
        r["link_targets"] = lk["targets"]
    store = MemoryStore(rows, np.load(INDEX / "vectors" / "voyage-4.npy"), "voyage-4", meta=meta)
    model = embed.load_model("voyage-4")
    cfg = SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none")
    searcher = Searcher(cfg, store, embedder=lambda texts: embed.encode_queries(model, texts), reranker=None, translator=None, check_meta=False)
    return searcher, store, {"rows": len(rows), "chunks_sha256": meta.get("chunks_sha256"), "config": dataclasses.asdict(cfg)}


def percentile(values: list[float], p: float) -> float | None:
    """최근접 순위(run_eval._p95와 같은 방식)."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p * len(s)) - 1)]


def summarize_trace(calls: list[dict]) -> dict:
    steps: dict[str, int] = {}
    for c in calls:
        steps[c.get("step") or c.get("task") or "?"] = steps.get(c.get("step") or c.get("task") or "?", 0) + 1
    cost = sum(c.get("cost_usd") or 0.0 for c in calls)
    return {"llm_calls": len(calls), "llm_calls_by_step": steps, "translation_calls": sum(1 for c in calls if "translate" in (c.get("step") or "")),
            "cost_usd": round(cost, 6), "cost_unknown_calls": sum(1 for c in calls if c.get("cost_usd") is None),
            "failed_calls": sum(1 for c in calls if c.get("ok") is False),
            "input_tokens": sum(c.get("input_tokens") or 0 for c in calls), "output_tokens": sum(c.get("output_tokens") or 0 for c in calls)}


def grade(item: dict, cited_chunks: list[Any]) -> dict:
    gold = item["gold"]
    return {"cited_on_gold": sum(any(g.matches(c) for g in gold) for c in cited_chunks), "gold_total": len(gold),
            "gold_hit": sum(any(g.matches(c) for c in cited_chunks) for g in gold)}


def base_row(item: dict, arm: str, rnd: int, seconds: float, trace: list[dict]) -> dict:
    return {"id": item["id"], "group": item["group"], "kind": item["kind"], "irrelevant_type": None, "question": item["input"], "expect_refusal": False,
            "arm": arm, "round": rnd, "latency_s": round(seconds, 3), "judge": None, **summarize_trace(trace),
            "llm_trace": [{k: c.get(k) for k in ("seq", "step", "node", "task", "start_s", "seconds", "ok", "cost_usd", "input_tokens", "output_tokens")} for c in trace]}


def run_single(item: dict, graph, rec: Rec, rnd: int) -> dict:
    from backend.schemas import Chunk
    from backend.services import llm_trace
    from evals.agent import tracking

    thread_id = f"jr-{item['id']}-{uuid.uuid4().hex[:6]}"
    with llm_trace.capture() as calls:
        cfg = tracking.eval_config("joint_review", item["id"], run_id=RUN_ID + "-single", thread_id=thread_id)
        t0 = time.perf_counter()
        out = graph.invoke({"question": item["input"], "user_id": "eval-user", "thread_id": thread_id, "as_of": _as_of(item)}, cfg)
        seconds = time.perf_counter() - t0
        tracking.finish_item(cfg)
    row = base_row(item, "single", rnd, seconds, list(calls))
    cites = out.get("citations", []) or []
    objs = [Chunk(**c) for c in cites]
    answered = out.get("kind") == "answer"
    dropped = list(out.get("dropped_citations", []) or [])
    row.update({"result": out.get("kind"), "route": out.get("route"), "answered": answered, "answer": out.get("answer") or "", "cited": [c["chunk_id"] for c in cites],
                "dropped": dropped, "drafted": bool(out.get("drafted")), "refuse_stage": "" if answered else ("answer_check" if out.get("refuse_reason") else "before_answer"),
                "refuse_reason": out.get("refuse_reason") or "", "clarify_question": out.get("clarify_question"), "retries": out.get("retries", 0),
                "shows_date": answered and all(c.get("version_date") in (out.get("answer") or "") for c in cites), "retrieval_calls": rec.calls,
                "cited_orgs": sorted({c.org for c in objs}), **grade(item, objs)})
    row["verified"], row["verify_den"] = len(cites), len(cites) + len(dropped)
    row["issue_count"] = None
    return row


def run_joint(item: dict, graph, rec: Rec, rnd: int) -> dict:
    from backend.services import llm_trace
    from evals.agent import tracking

    thread_id = f"jr-{item['id']}-{uuid.uuid4().hex[:6]}"
    with llm_trace.capture() as calls:
        cfg = tracking.eval_config("joint_review", item["id"], run_id=RUN_ID + "-joint", thread_id=thread_id)
        t0 = time.perf_counter()
        out = graph.invoke({"question": item["input"], "user_id": "eval-user", "thread_id": thread_id, "as_of": _as_of(item)}, cfg)
        seconds = time.perf_counter() - t0
        tracking.finish_item(cfg)
    row = base_row(item, "joint", rnd, seconds, list(calls))
    state = graph.get_state(cfg).values
    interrupts = out.get("__interrupt__") or []
    payload = interrupts[0].value if interrupts else {}
    kind = payload.get("kind") if isinstance(payload, dict) else None
    table = payload.get("table") if kind == "issue_table" else None
    status = out.get("review_status") or state.get("review_status") or ""
    results = state.get("team_results") or {}
    rows = (table or {}).get("rows") or []
    if table is not None:
        result = "issue_table"
    elif kind:
        result = kind  # team_review_failed
    else:
        result = status or "none"  # clarify | no_issues
    ids = list(dict.fromkeys(r["chunk_id"] for r in rows))
    objs = [rec.chunks[i] for i in ids if i in rec.chunks]
    dropped = sum(int((results.get(t) or {}).get("dropped") or 0) for t in results)
    drafted = bool(rows) or dropped > 0
    row.update({"result": result, "route": None, "answered": bool(rows), "answer": "", "cited": ids, "dropped": [None] * dropped, "drafted": drafted,
                "refuse_stage": "" if rows else "before_answer", "refuse_reason": status if not rows else "", "clarify_question": state.get("clarify_question"),
                "retries": 0, "shows_date": bool(rows) and all(r.get("version_date") for r in rows), "retrieval_calls": rec.calls,
                "cited_orgs": sorted({c.org for c in objs}), **grade(item, objs)})
    row["verified"], row["verify_den"] = len(rows), len(rows) + dropped
    row["issue_count"] = len(rows)
    row["issues"] = [{k: r.get(k) for k in ("team", "topic", "issue", "stance", "confidence", "chunk_id", "section_path", "version_date", "conflict")} for r in rows]
    row["conflict_rows"] = sum(1 for r in rows if r.get("conflict"))
    row["team_status"] = {t: {"status": v.get("status"), "rows": len(v.get("rows") or []), "dropped": v.get("dropped"), "reason": v.get("reason"),
                              "private_excluded": v.get("private_excluded"), "attempts": v.get("attempts"), "seconds": v.get("seconds")} for t, v in results.items()}
    row["unreviewed"] = [u.get("team") for u in (table or {}).get("unreviewed", [])]
    row["table_summary"] = payload.get("summary") if isinstance(payload, dict) else None
    return row


def jaccard_stability(rows: list[dict]) -> float | None:
    """같은 문항의 회차끼리 인용 청크 집합의 쌍별 자카드 평균(문항 평균의 평균). 둘 다 빈 집합이면 1."""
    by: dict[str, list[set]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(set(r["cited"]))
    vals = []
    for sets in by.values():
        pair = [1.0 if not (a | b) else len(a & b) / len(a | b) for a, b in combinations(sets, 2)]
        if pair:
            vals.append(sum(pair) / len(pair))
    return round(sum(vals) / len(vals), 4) if vals else None


def arm_summary(rows: list[dict]) -> dict:
    m = compute_metrics(rows)
    lat = [r["latency_s"] for r in rows]
    amount = [r for r in rows if r["group"] == "amount"]
    v2 = [r for r in rows if r["group"] == "v2"]
    den = sum(r["verify_den"] for r in rows)
    out = {
        "runs": len(rows), "errors": m["errors"],
        "latency_p50_s": percentile(lat, 0.5), "latency_p95_s": percentile(lat, 0.95), "latency_mean_s": round(statistics.mean(lat), 3), "latency_max_s": max(lat),
        "llm_calls_mean": round(statistics.mean(r["llm_calls"] for r in rows), 2), "llm_calls_min": min(r["llm_calls"] for r in rows), "llm_calls_max": max(r["llm_calls"] for r in rows),
        "translation_calls_mean": round(statistics.mean(r["translation_calls"] for r in rows), 2),
        "cost_usd_total": round(sum(r["cost_usd"] for r in rows), 6), "cost_usd_mean_per_run": round(statistics.mean(r["cost_usd"] for r in rows), 6),
        "cost_unknown_calls": sum(r["cost_unknown_calls"] for r in rows), "failed_llm_calls": sum(r["failed_calls"] for r in rows),
        "completed_rate": round(sum(1 for r in rows if r["answered"]) / len(rows), 4),
        "results": {k: sum(1 for r in rows if r["result"] == k) for k in sorted({r["result"] for r in rows})},
        "citation_verify_rate": round(sum(r["verified"] for r in rows) / den, 4) if den else None,
        "citations_mean_per_run": round(statistics.mean(len(r["cited"]) for r in rows), 2),
        "team_section_coverage_mean": round(statistics.mean(len(set(r["cited_orgs"]) & set(TEAM_ORGS)) for r in rows), 3),
        "team_section_coverage_by_run": [len(set(r["cited_orgs"]) & set(TEAM_ORGS)) for r in rows],
        "amount_band_hit_rate": round(sum(r["gold_hit"] / r["gold_total"] for r in amount) / len(amount), 4) if amount else None,
        "v2_gold_hit_rate": round(sum(r["gold_hit"] / r["gold_total"] for r in v2) / len(v2), 4) if v2 else None,
        "stability_jaccard_across_rounds": jaccard_stability(rows),
        "per_round_p95_s": {str(n): percentile([r["latency_s"] for r in rows if r["round"] == n], 0.95) for n in sorted({r["round"] for r in rows})},
        "existing_metrics": m,
    }
    issues = [r["issue_count"] for r in rows if r.get("issue_count") is not None]
    if issues:
        out["issue_count_mean"] = round(statistics.mean(issues), 2)
        out["issue_count_min"], out["issue_count_max"] = min(issues), max(issues)
        out["conflict_rows_total"] = sum(r.get("conflict_rows") or 0 for r in rows)
        out["runs_with_unreviewed_team"] = sum(1 for r in rows if r.get("unreviewed"))
    return out


RUN_ID = "eval-joint-review"


def run_cmd(args) -> int:
    global RUN_ID
    M.use_openrouter_env()
    X.load_voyage_key()
    os.environ["LLM_COST_CAP_USD"] = str(args.run_cost_cap)
    from backend.graph.service_profile import SharedChatModel, service_profile
    from backend.services.llm import is_demo_mode
    from evals.agent import tracking

    RUN_ID = tracking.new_run_id("joint-review")
    with service_profile(True):
        if is_demo_mode():
            raise SystemExit("데모 모드다: 실제 모델 설정이 아니라 멈춘다")
        from langgraph.checkpoint.memory import InMemorySaver

        from backend.graph.build import build_graph
        from backend.graph.departments.review import build_review_graph
        from backend.graph.departments.store import InMemoryIssueTableStore

        items = build_items(args.set)
        if args.ids:
            want = {x.strip() for x in args.ids.split(",")}
            items = [it for it in items if it["id"] in want]
        searcher, store, setup = build_search()
        rec = Rec(searcher)
        llm = SharedChatModel()
        pages = {"page_search": M.PageSearch(searcher, rec)}
        single = M.X.RecordingGraph(build_graph(rec, None, llm=llm, decompose=True, section_reader=lambda rule_seq, article, as_of: None, **pages))
        joint = build_review_graph(rec, InMemorySaver(), llm=llm, store=InMemoryIssueTableStore(), approvals=None)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        part = out / "partial.jsonl"
        if part.exists():
            part.unlink()
        rows: dict[str, list[dict]] = {"single": [], "joint": []}
        spent = 0.0

        def fresh() -> None:
            store.translations.clear()   # 번역 장부를 비운다(스냅샷에서 받은 번역도 쓰지 않는다). 두 경로 모두 번역을 새로 부른다
            searcher._qvecs.clear()
            rec.reset()

        def one(arm: str, item: dict, rnd: int, record: bool) -> None:
            nonlocal spent
            fresh()
            row = (run_single(item, single, rec, rnd) if arm == "single" else run_joint(item, joint, rec, rnd))
            spent += row["cost_usd"]
            print(f"[{arm}] 회차 {rnd} {item['id']}: {row['result']} {row['latency_s']}초 LLM {row['llm_calls']}회(번역 {row['translation_calls']}) ${row['cost_usd']:.4f} "
                  f"인용 {len(row['cited'])} 팀 절 {len(set(row['cited_orgs']) & set(TEAM_ORGS))}", flush=True)
            if rec.errors:
                raise SystemExit(f"검색 오류로 중단({arm}, {item['id']}): {rec.errors[-1]}")
            if row["failed_calls"]:
                print(f"  주의: 실패한 LLM 호출 {row['failed_calls']}건", flush=True)
            if record:
                rows[arm].append(row)
                with part.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            if spent > COST_STOP_USD:
                raise SystemExit(f"비용이 중단선 ${COST_STOP_USD}를 넘어 멈춘다: ${spent:.3f}")

        if not args.no_warmup:  # 모델 연결, 임베딩 모델 올리기를 첫 문항 시간에 섞지 않는다. 점수에 넣지 않는다
            print("워밍업(점수에 넣지 않음)", flush=True)
            for arm in ("single", "joint"):
                one(arm, items[0], 0, False)
        t_start = time.strftime("%Y-%m-%d %H:%M:%S")
        for rnd in range(1, args.rounds + 1):
            for i, item in enumerate(items):
                order = ("single", "joint") if (i + rnd) % 2 == 0 else ("joint", "single")
                for arm in order:
                    one(arm, item, rnd, True)
        meta = {
            "preregister": "evals/PREREGISTER.md " + ("62.11" if args.set == "detail" else "62.9"), "set": args.set, "items": [{"id": it["id"], "group": it["group"], "input": it["input"], "as_of": it.get("as_of"), "gold": it["gold_label"]} for it in items],
            "rounds": args.rounds, "order": "문항 번호와 회차의 합이 짝수면 single 먼저, 홀수면 joint 먼저", "warmup": not args.no_warmup, "started": t_start, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "store": "MemoryStore(색인 스냅샷 data/index, 링크 대상 포함)", "search": setup, "cache": "호출마다 번역 장부와 질문 벡터 기억을 비움",
            "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"]}, "service_profile": "61.51(backend/graph/service_profile.py)",
            "run_cost_cap_usd": args.run_cost_cap, "total_cost_usd_incl_warmup": round(spent, 6), "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
            "single": "build_graph(서비스 설정, decompose=True, 합동 검토·결정표 미연결 = 정책 질문 경로)", "joint": "build_review_graph(체크포인터 메모리, 승인함 없음, 쟁점표와 승인 interrupt까지)",
            "run_id": RUN_ID,
        }
        for arm in rows:
            d = out / arm
            d.mkdir(parents=True, exist_ok=True)
            (d / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows[arm]), encoding="utf-8")
            (d / "summary.json").write_text(json.dumps({"meta": {**meta, "arm": arm}, "summary": arm_summary(rows[arm])}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        compare = {"meta": meta, "single": arm_summary(rows["single"]), "joint": arm_summary(rows["joint"])}
        (out / "compare.json").write_text(json.dumps(compare, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({a: {k: v for k, v in compare[a].items() if k not in ("existing_metrics", "team_section_coverage_by_run")} for a in ("single", "joint")}, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="단일 대 합동 검토를 같은 입력으로 번갈아 실행")
    p.add_argument("--out", required=True)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--set", choices=("main", "detail"), default="main", help="main = 사전 등록 62.9의 입력 8건, detail = 62.11의 상세 입력 6건")
    p.add_argument("--ids", help="쉼표로 고른 입력만(점검용, 점수로 쓰지 않는다)")
    p.add_argument("--no-warmup", action="store_true")
    p.add_argument("--run-cost-cap", type=float, default=0.08, help="호출 한 건(그래프 한 번)의 비용 상한(달러)")
    p.set_defaults(fn=run_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
