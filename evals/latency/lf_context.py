"""운영 Langfuse의 search 관측에서 문항별 '첫 검색 문맥에 든 정답 위치 수'를 꺼내 실패 유형 표의 `--context` 파일을 만든다 (읽기 전용, 유료 호출 없음).

    python -m evals.latency.lf_context --set v2 evals/results/deploy_latency_<리비전> evals/dataset_v2.jsonl \\
        --set holdout evals/results/deploy_latency_holdout_<리비전> evals/dataset_holdout_v1.jsonl \\
        --out evals/results/failure_types_<리비전>/context.json [--scope first|final] [--observations-json <파일>]

환경 변수(키는 출력·저장하지 않는다): LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
저장소 루트에서 실행한다. 저장소는 읽기만 한다. `evals.latency.lf_recall`의 짝짓기(행의 thread_id == sessionId 뒤쪽)와 파서를 그대로 쓴다.

출력 형식: `{"이름:문항:회차": [문맥에 든 정답 위치 수, 정답 위치 수]}`. `python -m evals.agent.failure_types --context`가 읽는다.
정답 위치 수 = 평가셋 문항의 `gold_chunks` 개수, 든 위치 수 = 그 위치 가운데 문맥 청크 어느 하나라도 `GoldRef.matches`로 맞는 것
(`evals/latency/deploy_citation_gold.py`가 인용 청크로 `gold_hit`을 세는 규칙과 같다. 그래서 문맥 값은 인용 값과 같은 잣대로 비교된다).

문맥의 정의(--scope)
- first(기본): 한 대화(= `/chat` 한 번)에서 시작 시각이 가장 이른 `search` 관측 output의 `chunks` 전부.
  사전 등록 62.72 이전 기록의 나뉜 질문은 넓힌 첫 검색 8개와 도입부 채우기로 붙은 청크까지다(앞 5개만 자르지 않는다). 62.72 뒤에는 나뉜 질문도 검색 결과 5개 그대로다. 판정과 답 작성이 처음 받은 문맥이고,
  `failure_types`의 "첫 검색 문맥"과 00037 기준선(서비스 검색기를 그대로 다시 돌린 첫 검색 결과 전체)과 같은 정의다.
- final: 그 대화의 마지막 `search` 관측 output의 `chunks`(재검색 결과를 합친 목록, 증거 상한 MAX_CHUNKS 10, 사전 등록 62.72 이전 기록의 나뉜 질문은 13). 답 작성이 실제로 받은 문맥에 가깝다.
  재검색이 정답을 가져왔는데 답이 인용하지 않은 경우를 `first`는 검색 실패로, `final`은 근거 선택으로 센다. 두 값 차이는 `<out>.detail.json`에 같이 남는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from evals.latency import lf_recall as L
from evals.retrieval import run as official_run

REPO_ROOT = Path(__file__).resolve().parents[2]


def gold_hits(gold: list, chunks: list[dict]) -> int:
    """정답 위치 중 문맥 청크 하나라도 맞는 위치의 수 (`deploy_citation_gold.score_row`의 gold_hit과 같은 규칙)."""
    objs = [L.to_chunk_obj(c) for c in chunks]
    return sum(any(g.matches(o) for o in objs) for g in gold)


def _scope_chunks(trace_obs: list[dict], scope: str, corpus_by_id: dict | None) -> tuple[list[dict], str]:
    """한 trace의 search 관측(시작 순) -> (문맥 청크 dict 목록, 파서 방식). final은 청크가 있는 마지막 관측."""
    parsed_all = [L.parse_search_output(o.get("output")) for o in trace_obs]
    if scope == "final":
        idx = max((i for i, p in enumerate(parsed_all) if p["chunks"]), default=0)
    else:
        idx = 0
    p = parsed_all[idx]
    chunks = p["chunks"]
    if p["mode"] == "regex" and corpus_by_id:
        chunks = L.enrich_regex_chunks(chunks, corpus_by_id)
    return chunks, p["mode"]


def build_context(name: str, runs: dict[int, list[dict]], items: list[dict], observations: list[dict], *, scope: str = "first",
                  known_sessions: set[str] | None = None, exclusions: dict | None = None, corpus_by_id: dict | None = None) -> tuple[dict, list[dict]]:
    """한 평가셋: (context 항목 {"이름:문항:회차": [든 수, 전체 수]}, 행별 상세)."""
    exclusions = exclusions or {}
    traces = L.first_search_per_trace(observations)
    obs_by_trace: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        if o.get("name") == "search" and o.get("traceId"):
            obs_by_trace[o["traceId"]].append(o)
    for v in obs_by_trace.values():
        v.sort(key=lambda o: (L._ts(o["startTime"]), o.get("id", "")))
    items_by_id = {it["id"]: it for it in items}
    ctx: dict[str, list[int]] = {}
    detail: list[dict] = []
    for n, rows in sorted(runs.items()):
        for p in L.pair_by_thread(rows, traces, known_sessions):
            r = p["row"]
            it = items_by_id.get(r["id"])
            if it is None or it["kind"] != "relevant" or not it["gold"] or str(it["id"]) in exclusions:
                continue
            total = len(it["gold"])
            d = {"set": name, "run": n, "id": r["id"], "thread_id": r.get("thread_id"), "status": p["status"], "gold_total": total}
            if p["status"] == "paired":
                trace_obs = obs_by_trace[p["trace"]["obs"]["traceId"]]
                chunks, mode = _scope_chunks(trace_obs, scope, corpus_by_id)
                other, _ = _scope_chunks(trace_obs, "final" if scope == "first" else "first", corpus_by_id)
                hit = gold_hits(it["gold"], chunks)
                ctx[f"{name}:{r['id']}:{n}"] = [hit, total]
                other_hit = gold_hits(it["gold"], other)
                d.update(scope=scope, hit=hit, other_scope_hit=other_hit, n_chunks=len(chunks), n_search_obs=len(trace_obs), parse=mode,
                         chunk_ids=[c["chunk_id"] for c in chunks], differs=hit != other_hit,
                         cited_in_trace=L.cited_consistency(r, p["trace"]))
            elif p["status"] == "no_search":   # 서비스가 검색하지 않음: 문맥이 비어 있다 (lf_recall과 같은 처리)
                ctx[f"{name}:{r['id']}:{n}"] = [0, total]
                d.update(scope=scope, hit=0, n_chunks=0, chunk_ids=[])
            detail.append(d)
    return ctx, detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", dest="sets", nargs=3, metavar=("NAME", "RUN_DIR", "DATASET"), action="append", required=True,
                    help="이름, 측정기 결과 폴더(run1~3/rows.jsonl), 그 측정에 쓴 평가셋. failure_types의 --qa 이름과 같게 준다")
    ap.add_argument("--out", type=Path, required=True, help="context 파일. 상세는 같은 이름의 .detail.json")
    ap.add_argument("--scope", choices=("first", "final"), default="first")
    ap.add_argument("--observations-json", type=Path, default=None, help="Langfuse search 관측 data 배열(오프라인 시험용)")
    ap.add_argument("--known-sessions-json", type=Path, default=None, help="오프라인 시험용: thread id 목록")
    ap.add_argument("--chunks", type=Path, default=None, help="코퍼스 청크 파일(기본 data/index/chunks.jsonl). 깨진 output의 청크 위치를 채우는 데만 쓴다")
    ap.add_argument("--allow-missing", action="store_true", help="짝지을 수 없는 행이 있어도 있는 행만으로 파일을 만든다")
    a = ap.parse_args(argv)

    exclusions = official_run.load_exclusions(REPO_ROOT / "evals" / "exclusions.json")
    chunks_path = a.chunks or REPO_ROOT / "data" / "index" / "chunks.jsonl"
    corpus_by_id = {c.chunk_id: vars(c) for c in official_run.load_chunks(chunks_path)} if chunks_path.is_file() else None

    loaded = []
    for name, run_dir, dataset in a.sets:
        runs = L.load_rows(Path(run_dir))
        if not runs:
            print(f"{run_dir}에 run*/rows.jsonl이 없다", file=sys.stderr)
            return 2
        miss = sum(1 for rows in runs.values() for r in rows if not r.get("thread_id"))
        if miss:
            print(f"{name}: 행 {miss}건에 thread_id가 없다. 정확한 짝짓기 불가 -> 멈춘다", file=sys.stderr)
            return 3
        loaded.append((name, runs, official_run.load_dataset(Path(dataset))))

    windows = [L.row_window(runs) for _, runs, _ in loaded]
    lo, hi = min(w[0] for w in windows), max(w[1] for w in windows)
    known = None
    if a.observations_json:
        obs = json.loads(a.observations_json.read_text(encoding="utf-8"))
        if a.known_sessions_json:
            known = set(json.loads(a.known_sessions_json.read_text(encoding="utf-8")))
    else:
        lf = L.Langfuse.from_env()
        obs = lf.search_observations(lo, hi)
        known = lf.thread_ids(lo, hi)

    ctx: dict[str, list[int]] = {}
    detail: list[dict] = []
    for name, runs, items in loaded:
        c, d = build_context(name, runs, items, obs, scope=a.scope, known_sessions=known, exclusions=exclusions, corpus_by_id=corpus_by_id)
        ctx.update(c)
        detail += d

    problems = [f"{d['set']}:{d['id']}:{d['run']}={d['status']}" for d in detail if d["status"] not in ("paired", "no_search")]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(ctx, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    detail_path = a.out.with_suffix(".detail.json")
    detail_path.write_text(json.dumps({"scope": a.scope, "n_rows": len(detail), "unpaired": problems, "rows": detail}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_diff = sum(1 for d in detail if d.get("differs"))
    print(f"context {len(ctx)}행 (범위 {a.scope}), 짝짓지 못한 행 {len(problems)}, 첫/마지막 검색 값이 다른 행 {n_diff} -> {a.out.as_posix()}")
    if problems:
        print(f"짝짓지 못한 행: {problems[:10]}", file=sys.stderr)
        if not a.allow_missing:
            print("--allow-missing 없이는 실패로 끝낸다(Langfuse 누락이면 이 옵션을 더하고, 빠진 행은 failure_types에서 '정답 위치 누락(검색·선택 미구분)'으로 남는다)", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
