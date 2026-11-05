"""단일 대 멀티 에이전트 비교 측정 (D-09, G4, PRD 10장 "단일 대 멀티"). 코드만 있고 이 파일을 만든 시점에는 재지 않았다.

같은 평가셋(기본 동결 v2 50건), 같은 서비스 검색기(`exp_service_v1`의 `Searcher`), 같은 답변 모델, 같은 지표(`run_eval.compute_metrics`)로
단일 그래프(`backend.graph.build.build_graph`)와 멀티 그래프(`backend.graph.multi.build_multi_graph`)를 문항마다 번갈아 돌린다.
달라지는 것은 그래프 구조뿐이다: 노드, 프롬프트, 검색, 인용 검사, 근거 판정 코드는 같다(멀티는 단일의 노드를 꺼내 쓴다).

- 번갈아 돌리는 이유: 서비스 검색기의 질문 번역은 `MemoryStore`에서 프로세스 안에 기억된다. 한 쪽을 먼저 다 돌리면 뒤에 도는 쪽이 번역을 기억에서 받는다.
  문항마다 순서를 바꿔(짝수 번째는 단일 먼저, 홀수 번째는 멀티 먼저) 이 차이가 한 쪽으로 쏠리지 않게 하지만, 없애지는 못한다. `--store pg`는 번역을 DB에 저장하므로 두 쪽이 같은 값을 받는다.
- LLM 호출 수: 그래프의 채팅 모델 호출(`classify`, `rewrite`, `judge`, `answer`, `grounding`, 분해)을 `CountingLLM`이 센다. 검색기 안의 번역 호출은 세지 않는다(두 쪽이 같다).
- 비용: 평가 실행기가 문항마다 `cost_usd`를 낸다. 하위 에이전트 안의 호출도 같은 콜백에 잡힌다(`tests/test_multi_graph.py`가 확인한다).
- Anthropic API 키는 쓰지 않는다. 기본 모델은 로컬 Claude CLI(Haiku 5.5)이고 `VOYAGE_API_KEY`만 읽는다(`exp_confirmed_v1.fix_env`, `load_voyage_key`).
- `--llm openrouter`: 환경 변수 `OPENROUTER_API_KEY`로 OpenRouter의 Haiku 5.5를 부른다(`use_openrouter_env`). OpenRouter 형식이 아닌 키는 거부한다.

    python -m evals.agent.exp_multi_v2 run --out evals/results/agent_v2_single_vs_multi
    python -m evals.agent.exp_multi_v2 run --store pg --out evals/results/agent_v2_single_vs_multi_pg
    python -m evals.agent.exp_multi_v2 run --arms multi --out <폴더>            # 한 쪽만(점검용이 아니면 비교에 쓰지 않는다)
    python -m evals.agent.exp_multi_v2 run --ids 3,7,16 --out <폴더>            # 점검용(partial)

결과 폴더: `single/`, `multi/`(각각 `rows.jsonl`, `summary.json`)와 `compare.json`(두 쪽 지표, 차이, 달라진 문항 목록, LLM 호출 수).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.agent import exp_confirmed_v1 as X
from evals.agent import exp_service_v1 as S
from evals.agent.run_eval import compute_metrics, run_item, verify_frozen
from evals.retrieval import exp_decompose_v1 as D
from evals.retrieval.run import load_dataset, load_exclusions

ROOT = D.ROOT
DATASET = ROOT / "evals" / "dataset_v2.jsonl"
ARMS = ("single", "multi")
COMPARE_FIELDS = ("result", "answered", "cited", "gold_hit", "refuse_reason", "retries")  # 두 쪽 사이에서 달라졌는지 보는 문항 값


class CountingLLM:
    """채팅 모델을 감싸 `invoke` 호출 수를 센다. 호출은 그대로 넘기고 응답을 바꾸지 않는다."""

    def __init__(self, llm: Any):
        self.llm = llm
        self.calls = 0

    def invoke(self, *args, **kwargs):
        self.calls += 1
        return self.llm.invoke(*args, **kwargs)


OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"


def use_openrouter_env() -> None:
    """`--llm openrouter`의 환경을 고정한다. 키는 `OPENROUTER_API_KEY`에서만 가져오고 값은 출력하지 않는다.

    주소를 바꾸는 값과 다른 제공자 키를 지워 기본 OpenRouter 주소로만 나가게 한다.
    """
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key.startswith("sk-or-"):
        raise SystemExit("OPENROUTER_API_KEY가 없거나 OpenRouter 형식이 아니라 멈춘다")
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY", "DEMO_MODE", "LLM_RECORD"):
        os.environ.pop(name, None)
    os.environ["LLM_PROVIDER"] = "openrouter"
    os.environ["LLM_MODEL"] = OPENROUTER_MODEL
    os.environ["LLM_API_KEY"] = key


def build_arm_graph(arm: str, retriever: Callable, llm: Any, **kw):
    """`arm`의 그래프. 같은 인자(`retriever`, `llm`, `kw`)를 단일과 멀티에 그대로 넘긴다. 질문 분해는 서비스 경로처럼 `decompose=True`가 기본이다."""
    from backend.graph.build import build_graph
    from backend.graph.multi import build_multi_graph

    if arm not in ARMS:
        raise ValueError(f"알 수 없는 경로: {arm}")
    build = build_graph if arm == "single" else build_multi_graph
    return X.RecordingGraph(build(retriever, **{"decompose": True, **kw}, llm=llm))


@dataclass
class Arm:
    name: str
    graph: Any  # RecordingGraph
    rec: Any  # RecordingSearch (set_item, calls, errors)
    llm: CountingLLM
    rows: list[dict] = field(default_factory=list)


def run_arm_item(arm: Arm, item: dict, run_id: str) -> dict:
    """한 경로로 문항 하나를 돌려 행을 만든다. 단일과 멀티가 같은 행 칸을 낸다(멀티는 에이전트 기록이 더 붙는다)."""
    arm.rec.set_item(item)
    calls0 = arm.llm.calls
    row = run_item(arm.graph, item, run_id=f"{run_id}-{arm.name}")  # 경로마다 Langfuse 세션을 따로 둔다
    out = arm.graph.last or {}
    X.add_recorded(row, out)
    row["arm"] = arm.name
    row["llm_calls"] = arm.llm.calls - calls0
    row["sub_queries"] = out.get("sub_queries")
    row["decompose_source"] = out.get("decompose_source")
    row["retrieval_calls"] = arm.rec.calls
    row["first_searches"] = sum(c["kind"] == "first" for c in arm.rec.calls)
    row["requery_searches"] = sum(c["kind"] == "requery" for c in arm.rec.calls)
    if arm.name == "multi":
        row["agent_trace"] = out.get("agent_trace")
        row["supervisor_log"] = out.get("supervisor_log")
    return row


def run_arms(items: list[dict], arms: list[Arm], run_id: str, *, on_row: Callable[[Arm, dict], None] | None = None) -> dict[str, list[dict]]:
    """문항마다 모든 경로를 번갈아 돌린다(순서는 문항마다 바뀐다). 검색기 오류가 기록되면 멈춘다."""
    for i, item in enumerate(items):
        for arm in (arms if i % 2 == 0 else list(reversed(arms))):
            row = run_arm_item(arm, item, run_id)
            arm.rows.append(row)
            if on_row:
                on_row(arm, row)
            if arm.rec.errors:
                raise SystemExit(f"검색 오류로 중단({arm.name}, 문항 {item['id']}): {arm.rec.errors[-1]}")
    return {a.name: a.rows for a in arms}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compare(rows: dict[str, list[dict]]) -> dict:
    """단일과 멀티의 지표, 차이(멀티 - 단일), 달라진 문항, 호출 수. 한 쪽만 있으면 지표만 낸다."""
    metrics = {name: compute_metrics(r) for name, r in rows.items()}
    out: dict = {"metrics": metrics, "totals": {}}
    for name, r in rows.items():
        out["totals"][name] = {
            "items": len(r),
            "llm_calls": sum(x["llm_calls"] for x in r),
            "first_searches": sum(x["first_searches"] for x in r),
            "requery_searches": sum(x["requery_searches"] for x in r),
            "latency_mean_s": round(sum(x["latency_s"] for x in r) / len(r), 3) if r else None,
        }
    if set(ARMS) <= set(rows):
        s, m = metrics["single"], metrics["multi"]
        out["delta_multi_minus_single"] = {k: round(m[k] - s[k], 6) for k in s if _num(s[k]) and _num(m.get(k))}
        by_single = {x["id"]: x for x in rows["single"]}
        changed = []
        for x in rows["multi"]:
            y = by_single.get(x["id"])
            if y is None:
                continue
            diff = {f: {"single": y.get(f), "multi": x.get(f)} for f in COMPARE_FIELDS if y.get(f) != x.get(f)}
            if diff:
                changed.append({"id": x["id"], "kind": x["kind"], "changed": diff})
        out["changed_items"] = changed
        out["changed_count"] = len(changed)
        out["note"] = ("모델 응답은 같은 입력이어도 실행마다 달라질 수 있어 달라진 문항이 구조 때문이라고 단정하지 않는다. "
                       "차이가 1~4문항이면 이 목록을 EVAL_REPORT.md에 적는다(GATES G5). 개선이 없으면 없다고 적는다.")
    return out


def _write_arm(out: Path, name: str, rows: list[dict], meta: dict) -> None:
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps({"meta": {**meta, "arm": name}, "metrics": compute_metrics(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cmd(args) -> int:
    if args.llm == "openrouter":
        use_openrouter_env()
    else:
        X.fix_env()
    X.load_voyage_key()
    dataset = Path(args.dataset) if args.dataset else DATASET
    verify_frozen(dataset)
    from backend.services.llm import get_chat_model, is_demo_mode
    from evals.agent import tracking

    if is_demo_mode():
        raise SystemExit("데모 모드다: 실제 모델 설정이 아니라 멈춘다")
    names = [a for a in ARMS if a in args.arms.split(",")]
    if not names:
        raise SystemExit(f"--arms는 {','.join(ARMS)} 중에서 고른다")
    excluded = load_exclusions(ROOT / "evals" / "exclusions.json")
    items = [it for it in load_dataset(dataset) if str(it["id"]) not in excluded]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if str(it["id"]) in want]
    if not items:
        raise SystemExit("돌릴 문항이 없다")
    use_pg = args.store == "pg"
    searcher, setup = S.build_pg_searcher() if use_pg else S.build_searcher()
    arms = []
    for name in names:
        rec = S.RecordingSearch(searcher)
        llm = CountingLLM(get_chat_model())
        arms.append(Arm(name, build_arm_graph(name, rec, llm), rec, llm))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = tracking.new_run_id("question")

    def show(arm: Arm, row: dict) -> None:
        extra = f" 에이전트 {'>'.join(row['agent_trace'] or []) or '-'}" if arm.name == "multi" else ""
        print(f"[{arm.name}] 문항 {row['id']}: {row['result']} 재시도 {row['retries']} LLM {row['llm_calls']}회 검색 {row['first_searches']}+{row['requery_searches']} "
              f"{row['latency_s']}초{extra}", flush=True)

    rows = run_arms(items, arms, run_id, on_row=show)
    meta = {
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "service_path": S.SERVICE_PATH_PG if use_pg else S.SERVICE_PATH,
        "store": "PgStore" if use_pg else "MemoryStore",
        "search": {**setup, "first_search": "그래프가 원 질문(한국어)과 하위 질문을 `Searcher.search`에 넘긴다", "requery": "재작성 검색어(영어)를 분해 없이 넘긴다"},
        "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"], "anthropic_api_key": "unused"},
        "arms": names,
        "order": "문항마다 순서를 바꿔 번갈아 돌림(짝수 번째 단일 먼저, 홀수 번째 멀티 먼저)",
        "translation_cache": "MemoryStore는 프로세스 안에서 번역을 기억한다. 번갈아 돌려도 뒤에 도는 쪽이 번역을 기억에서 받을 수 있다" if not use_pg else "PgStore는 번역을 DB에 저장한다",
        "excluded": sorted(excluded),
        "partial": bool(args.ids),
        "run_id": run_id,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    for name in names:
        _write_arm(out, name, rows[name], meta)
    result = compare(rows)
    (out / "compare.json").write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in names:
        tracking.record_run_scores(f"{run_id}-{name}", {k: v for k, v in result["metrics"][name].items() if k != "n"})
    print(json.dumps({k: result[k] for k in ("totals", "delta_multi_minus_single", "changed_count") if k in result}, ensure_ascii=False, indent=2))
    if use_pg:
        searcher.store.pool.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="단일과 멀티를 같은 문항으로 번갈아 실행(서비스 Searcher, 기본 MemoryStore)")
    p.add_argument("--store", choices=("memory", "pg"), default="memory", help="검색 저장소. pg는 .env의 DATABASE_URL로 운영 DB를 읽는다")
    p.add_argument("--llm", choices=("claude_cli", "openrouter"), default="claude_cli", help="답변 모델 경로. openrouter는 환경 변수 OPENROUTER_API_KEY를 쓴다")
    p.add_argument("--dataset", help="평가셋 경로. 기본은 동결 v2이고, 동결된 파일만 돈다")
    p.add_argument("--arms", default=",".join(ARMS), help="돌릴 경로(쉼표). 기본 single,multi")
    p.add_argument("--ids", help="쉼표로 고른 문항만 돈다(partial, 점수로 쓰지 않는다)")
    p.add_argument("--out", required=True, help="single/, multi/, compare.json을 쓸 폴더")
    p.set_defaults(fn=run_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
