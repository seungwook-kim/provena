"""합동 검토 팀 선택 켬/끔 한 회 측정. `evals/results/review_team_select_20261117/run_team_select.py`와 같은 측정기이고 스위치 값만 인자로 받는다.

    .venv\\Scripts\\python.exe evals/results/review_team_select_3run_20261117/run_one.py --config on --run 1 --max-cost 0.08

- 평가셋: `evals/dataset_review_v1_gold.jsonl`(확정 정답), 10문항 x 1회. `exp_review_v1`의 team 갈래(`make_arm`, `run_arms`, `compute_review_metrics`, `match_gold`).
- 서비스 설정(`service_profile`, 61.51)을 채운 뒤 `REVIEW_TEAM_SELECT`를 켬이면 `1`, 끔이면 `0`으로 준다. 검색은 MemoryStore(색인 스냅샷).
- 모델: Anthropic API Haiku 5.5. 키는 저장소 `.env`의 `LLM_API_KEY`를 프로세스 환경으로만 읽고 출력하지 않는다.
- 결과: `run{N}_{config}/rows.jsonl`, `run{N}_{config}/summary.json`.
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

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _env_value(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{name}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("\"'")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["on", "off"], required=True)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--max-cost", type=float, default=0.08)
    a = ap.parse_args()
    key = _env_value("LLM_API_KEY")
    if not key.startswith("sk-ant-"):
        raise SystemExit("Anthropic 키가 아니라 멈춘다")
    os.environ["ANTHROPIC_API_KEY"] = key
    for name in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "DATABASE_URL", "REVIEW_TEAM_SELECT"):
        os.environ.pop(name, None)
    from evals.agent import exp_review_v1 as E

    E.use_anthropic_env()
    os.environ["LLM_COST_CAP_USD"] = "0.08"
    from evals.agent import exp_confirmed_v1 as X
    from evals.agent import exp_service_v1 as S

    X.load_voyage_key()
    from backend.graph.service_profile import service_profile
    from backend.services.llm import get_chat_model, is_demo_mode
    from evals.agent import tracking

    dataset = ROOT / "evals" / "dataset_review_v1_gold.jsonl"
    state = E.frozen_state(dataset)
    items = E.load_review_dataset(dataset)
    by_id = {str(it["id"]): it for it in items}
    switch = "1" if a.config == "on" else "0"
    with service_profile(True):
        os.environ["REVIEW_TEAM_SELECT"] = switch
        if is_demo_mode():
            raise SystemExit("데모 모드라 멈춘다")
        from backend.graph.departments import review as R

        assert R.team_select_enabled() == (a.config == "on")
        searcher, setup = S.build_searcher()
        llm = get_chat_model()
        arm = E.make_arm("team", searcher.search, llm)
        run_id = tracking.new_run_id(f"review-team-select-{a.config}-r{a.run}")
        started = time.strftime("%Y-%m-%d %H:%M:%S")

        def show(_arm, row):
            sel = [t for t in E.T.TEAM_IDS if t in row["team_status"] and (row["team_status"][t] or {}).get("status") != R.NOT_SELECTED]
            print(f"[{a.config} r{a.run}] 문항 {row['id']}: {row['status']} 팀 {sel} 쟁점 {len(row['issue_rows'])}행 "
                  f"LLM {row['llm_calls']}회 {row['latency_s']}초 ${row['cost_usd']:.5f}" + (f" 오류 {row['error']}" if row["error"] else ""), flush=True)

        stopped = None
        try:
            rows = E.run_arms(items, [arm], run_id, on_row=show, repeats=1, max_cost=a.max_cost)["team"]
        except E.BudgetExceeded as e:
            stopped = str(e)
            rows = arm.rows
        metrics = E.compute_review_metrics(rows, by_id)
        not_sel = R.NOT_SELECTED
    for r in rows:
        r["selected_teams"] = [t for t in E.T.TEAM_IDS if t in r["team_status"] and (r["team_status"][t] or {}).get("status") != not_sel]
        it = by_id[str(r["id"])]
        r["gold_match"] = E.match_gold(it, r["issue_rows"]) if E.judged_state(it) == "ready" else None
    meta = {"dataset": dataset.name, "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(), "frozen": state,
            "config": a.config, "run": a.run, "switch": f"REVIEW_TEAM_SELECT={switch}", "service_profile": "61.51(backend/graph/service_profile.py)",
            "repeats": 1, "store": "MemoryStore", "search": setup,
            "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"]},
            "max_cost_usd": a.max_cost, "started": started, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stopped_by_budget": stopped, "run_id": run_id}
    d = OUT / f"run{a.run}_{a.config}"
    d.mkdir(exist_ok=True)
    (d / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps({"meta": meta, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("gold_total", "gold_found", "missed_issue_rate", "cost_usd", "cost_usd_mean",
                                               "latency_mean_s", "latency_p95_s", "errors")}, ensure_ascii=False))
    return 3 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
