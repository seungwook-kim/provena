"""CI용 평가 점수 비교. 키·네트워크 없이 저장소에 커밋된 결과 파일만 읽는다.

    python evals/ci_compare.py

1. 최종 측정 결과(EVAL_REPORT 4장 최종 행, `agent_v2_q_d6151_r{1,2,3}_bo2sda2_api/`)의
   single·multi summary.json을 3회 평균한다.
2. 결과 summary의 dataset_sha256이 `evals/FROZEN.json`의 현재 동결 해시와 같은 결과만 비교한다.
   해시가 다른 옛 결과(첫 동결 해시로 잰 값 등)는 비교에서 빼고 표에 적는다.
3. 통과선(docs/SPEC.md 3장 기준, EVAL_REPORT 4장)과 기준 결과(`evals/ci_baseline.json`)와 비교한다.
   통과선 미달이거나 기준보다 나빠지면 종료 코드 1.
4. 기준 파일에 `operating` 항목이 있으면 가장 최근 운영 배포판 측정도 같은 방식으로 비교한다.
   `evals/results/deploy_latency_provena-api-*/`(배포 응답 시간 측정과 그 정답 근거 대조 `citation_gold.json`) 중
   평가셋 해시가 현재 동결 해시와 같은 것 가운데 측정 종료 시각이 가장 늦은 폴더를 자동으로 고른다.
   새 운영 측정을 커밋하면 이 비교가 그 결과를 읽으므로 코드가 바뀐 뒤의 운영 점수 하락이 여기서 드러난다.
   운영 측정에는 환각 위험 지표가 없어 그 지표는 이 비교에서 뺀다.
5. `--current <결과 파일>`을 주면(CI는 줌) `evals/ci_current_eval.py`가 현재 코드로 돌린 0원(키 없는 데모 재생, 오프라인) 평가 결과를 기준 파일의 `current` 항목과 견준다.
   커밋된 옛 측정 파일은 코드가 바뀌어도 그대로라 현재 코드의 회귀를 못 잡으므로, 이 항목이 그 구멍을 맡는다. 파일을 주지 않으면 이 비교를 하지 않는다.
   평가셋 v2 50건 녹화(`data/demo_replay/v2_recorded.json`)가 있으면 결과 파일에 `v2` 요약이 들어 있고, 기준 파일 `current.v2_metrics`와 같은 방식(인용 답·거절은 낮아지면, 녹화에 없는 요청·대체 답은 많아지면 실패)으로 견준다.
   녹화가 없으면 데모 질문 9개만 견준다.
6. 비교 표를 표준출력과 `$GITHUB_STEP_SUMMARY`에 쓴다.

통과선: 인용 정확도 0.85 이상, 정답 근거 인용률 0.85 이상, 비관련 질문 거절 0.90 이상, 전체 p95 10초 이하.
기준 결과 비교: 정답 근거·인용 정확도·거절은 기준보다 낮아지면, 오답 근거·과잉 거절·환각 위험은 기준보다
높아지면 실패. 응답 시간은 공급자에 따라 달라지므로 통과선만 본다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
FROZEN = EVALS / "FROZEN.json"
BASELINE = EVALS / "ci_baseline.json"

ARMS = ("single", "multi")
DEFAULT_RUNS = tuple(f"agent_v2_q_d6151_r{i}_bo2sda2_api" for i in (1, 2, 3))

# (지표 이름, 표시 이름)
LABELS = {
    "citation_accuracy": "인용 정확도",
    "cited_correct_rate": "정답 근거 인용률",
    "correct_refusal_rate": "비관련 질문 거절",
    "wrong_citation_rate": "오답 근거",
    "over_refusal_rate": "과잉 거절",
    "hallucination_risk_rate": "환각 위험",
    "latency_p95_s": "응답 시간 p95(초)",
}
# 통과선: 지표 -> 최소값
FLOORS = {"citation_accuracy": 0.85, "cited_correct_rate": 0.85, "correct_refusal_rate": 0.90}
# 통과선: 지표 -> 최대값
CEILINGS = {"latency_p95_s": 10.0}
# 기준 결과 대비: 낮아지면 실패 / 높아지면 실패
HIGHER_IS_BETTER = ("citation_accuracy", "cited_correct_rate", "correct_refusal_rate")
LOWER_IS_BETTER = ("wrong_citation_rate", "over_refusal_rate", "hallucination_risk_rate")

EPS = 1e-9

# 운영 배포판 측정 폴더(`evals/latency/deploy_latency.py`와 `deploy_citation_gold.py`의 결과). 검증 20건·새 인용 5건 폴더는 이름이 달라 들지 않는다.
OPERATING_GLOB = "deploy_latency_provena-api-*"
# 운영 측정에서 구할 수 있는 지표(환각 위험은 운영 측정에 없다)
OPERATING_KEYS = ("citation_accuracy", "cited_correct_rate", "correct_refusal_rate", "wrong_citation_rate", "over_refusal_rate", "latency_p95_s")


def load_summary(results_dir: Path, run: str, arm: str) -> dict | None:
    path = results_dir / run / arm / "summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def collect(results_dir: Path, runs, frozen: dict, dataset: str) -> dict:
    """arm별로 현재 동결 해시와 일치하는 결과, 뺀 결과, 이유를 모은다."""
    want = frozen.get(dataset, {})
    out = {}
    for arm in ARMS:
        used, excluded = [], []
        for run in runs:
            summary = load_summary(results_dir, run, arm)
            if summary is None:
                excluded.append((run, "summary.json 없음"))
                continue
            meta = summary.get("meta", {})
            if meta.get("dataset") != dataset:
                excluded.append((run, f"평가셋이 {meta.get('dataset')}"))
            elif meta.get("dataset_sha256") != want.get("sha256"):
                excluded.append((run, "동결 해시와 다름(옛 결과)"))
            elif summary.get("metrics", {}).get("n") != want.get("count"):
                excluded.append((run, f"문항 수 {summary.get('metrics', {}).get('n')}건(동결 {want.get('count')}건)"))
            else:
                used.append((run, summary["metrics"]))
        out[arm] = {"used": used, "excluded": excluded}
    return out


def average(metrics_list: list[dict]) -> dict:
    keys = list(LABELS)
    return {k: round(sum(m[k] for m in metrics_list) / len(metrics_list), 3) for k in keys}


def _verdict(key: str, label: str, value: float, ref) -> tuple[str, str | None]:
    """한 지표의 판정과 실패 사유(있으면)를 돌려준다. 사유에는 구성 이름을 붙이지 않는다."""
    if key in FLOORS and value < FLOORS[key] - EPS:
        return "통과선 미달", f"{label} {value} < 통과선 {FLOORS[key]}"
    if key in CEILINGS and value > CEILINGS[key] + EPS:
        return "통과선 초과", f"{label} {value} > 통과선 {CEILINGS[key]}"
    if key in HIGHER_IS_BETTER and ref is not None and value < ref - EPS:
        return "기준보다 낮음", f"{label} {value} < 기준 {ref}"
    if key in LOWER_IS_BETTER and ref is not None and value > ref + EPS:
        return "기준보다 높음", f"{label} {value} > 기준 {ref}"
    return "통과", None


def _gate_text(key: str) -> str:
    gate = FLOORS.get(key)
    return f">= {gate}" if gate is not None else (f"<= {CEILINGS[key]}" if key in CEILINGS else "-")


def find_latest_operating(results_dir: Path, frozen: dict, dataset: str) -> dict | None:
    """평가셋 해시가 현재 동결 해시와 같은 운영 측정 폴더 중 측정 종료 시각이 가장 늦은 것의 지표(회차 평균)를 돌려준다. 없으면 None."""
    want = frozen.get(dataset, {})
    found = []
    for folder in sorted(results_dir.glob(OPERATING_GLOB)):
        summary_path, gold_path = folder / "summary.json", folder / "citation_gold.json"
        if not (summary_path.is_file() and gold_path.is_file()):
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        meta = summary.get("meta", {})
        if meta.get("dataset") != dataset or meta.get("dataset_sha256") != want.get("sha256"):
            continue
        gold_runs = gold.get("summary", {}).get("per_run", [])
        time_runs = summary.get("per_run", [])
        if not gold_runs or len(gold_runs) != len(time_runs) or any(r.get("n") != want.get("count") for r in gold_runs):
            continue
        metrics = {
            key: round(sum(r[key] for r in gold_runs) / len(gold_runs), 3)
            for key in OPERATING_KEYS if key != "latency_p95_s"
        }
        metrics["latency_p95_s"] = round(sum(r["total_s"]["p95"] for r in time_runs) / len(time_runs), 3)
        stamp = datetime.fromisoformat(meta["finished_at"])
        found.append((stamp, folder.name, {"folder": folder.name, "revision": meta.get("revision"), "commit": meta.get("commit"),
                                          "finished_at": meta["finished_at"], "runs": len(gold_runs), "metrics": metrics}))
    if not found:
        return None
    return max(found, key=lambda x: (x[0], x[1]))[2]


def evaluate_operating(latest: dict | None, baseline: dict) -> tuple[list[dict], list[str]]:
    """가장 최근 운영 측정을 기준 파일의 `operating` 항목과 통과선에 견준다."""
    rows, failures = [], []
    if latest is None:
        failures.append("운영: 동결 해시와 일치하는 운영 측정 결과(deploy_latency_provena-api-*)가 없어 비교할 수 없습니다")
        return rows, failures
    base = baseline["operating"]
    arm = f"운영 {latest['revision']}"
    if latest["revision"] != base.get("revision"):
        rows.append({"arm": arm, "note": f"기준 파일은 {base.get('revision')} 측정, 가장 최근 측정은 {latest['revision']}({latest['finished_at']})"})
    if latest["runs"] < len(DEFAULT_RUNS):
        rows.append({"arm": arm, "note": f"{latest['runs']}회 평균(기준은 {len(DEFAULT_RUNS)}회)"})
    for key in OPERATING_KEYS:
        label, value, ref = LABELS[key], latest["metrics"][key], base["metrics"].get(key)
        verdict, reason = _verdict(key, label, value, ref)
        if reason:
            failures.append(f"{arm} {reason}")
        rows.append({"arm": arm, "label": label, "value": value, "baseline": ref, "gate": _gate_text(key), "verdict": verdict})
    return rows, failures


def evaluate(collected: dict, baseline: dict) -> tuple[list[dict], list[str]]:
    """표 행과 실패 사유 목록을 돌려준다."""
    rows, failures = [], []
    for arm in ARMS:
        used = collected[arm]["used"]
        for run, reason in collected[arm]["excluded"]:
            rows.append({"arm": arm, "note": f"제외: {run} ({reason})"})
        if not used:
            failures.append(f"{arm}: 동결 해시와 일치하는 결과가 없어 비교할 수 없습니다. 현재 평가셋으로 다시 재야 합니다")
            continue
        if len(used) < len(DEFAULT_RUNS):
            rows.append({"arm": arm, "note": f"{len(used)}회 평균(기준은 {len(DEFAULT_RUNS)}회)"})
        avg = average([m for _, m in used])
        base = baseline["arms"][arm]
        for key, label in LABELS.items():
            value, ref = avg[key], base.get(key)
            verdict, reason = _verdict(key, label, value, ref)
            if reason:
                failures.append(f"{arm} {reason}")
            rows.append({"arm": arm, "label": label, "value": value, "baseline": ref, "gate": _gate_text(key), "verdict": verdict})
    return rows, failures


CURRENT_LABELS = {"answers_ok": "인용 답이 나온 질문", "refusals_ok": "거절이 나온 질문", "missed_calls": "녹화에 없는 요청", "fake_answers": "발췌형 대체 답"}


def evaluate_current(result: dict, baseline: dict) -> tuple[list[dict], list[str]]:
    """현재 코드의 0원 평가 결과(`ci_current_eval.py`)를 기준 파일의 `current` 항목과 견준다. 두 경로(추론 답을 보냄, 빠른 답만 보냄) 모두 본다.
    인용 답·거절 수는 기준보다 낮아지면, 녹화에 없는 요청·발췌형 대체 답은 기준보다 많아지면 실패한다."""
    rows, failures = [], []
    base = baseline["current"]["metrics"]
    commit = result.get("meta", {}).get("commit") or "?"
    paths = result.get("paths") or {}
    if not paths:
        return rows, ["현재 코드 평가: 결과 파일에 경로별 결과가 없습니다"]
    for label, body in paths.items():
        arm, s = f"현재 코드 {commit} {label}", body["summary"]
        if s.get("n_questions") != base.get("n_questions"):
            failures.append(f"{arm} 질문 수 {s.get('n_questions')} != 기준 {base.get('n_questions')}")
        for key, text in CURRENT_LABELS.items():
            value, ref = s[key], base[key]
            bad = value < ref if key in ("answers_ok", "refusals_ok") else value > ref
            verdict = "기준보다 " + ("낮음" if key in ("answers_ok", "refusals_ok") else "많음") if bad else "통과"
            if bad:
                failures.append(f"{arm} {text} {value} vs 기준 {ref}" + (f" (녹화가 오래된 질문: {len(s.get('stale_questions', []))}개)" if key == "missed_calls" else ""))
            rows.append({"arm": arm, "label": text, "value": value, "baseline": ref, "gate": "-", "verdict": verdict})
    v2_rows, v2_failures = evaluate_current_v2(result, baseline)
    return rows + v2_rows, failures + v2_failures


V2_LABELS = {"relevant_answered": "50건: 관련 질문 중 인용 답", "irrelevant_refused": "50건: 비관련 질문 중 거절", "missed_calls": "50건: 녹화에 없는 요청", "fake_answers": "50건: 발췌형 대체 답"}


def evaluate_current_v2(result: dict, baseline: dict) -> tuple[list[dict], list[str]]:
    """평가셋 v2 50건을 현재 코드로 재생한 결과(`paths.<경로>.v2`)를 기준 파일의 `current.v2_metrics`와 견준다. 녹화(`data/demo_replay/v2_recorded.json`)가 없으면 둘 다 없어 건너뛴다.
    결과에만 있고 기준이 없으면(녹화를 올렸는데 기준을 안 올림), 기준에만 있고 결과에 없으면(녹화 manifest가 사라지거나 평가셋과 어긋남) 실패한다."""
    rows, failures = [], []
    base = baseline["current"].get("v2_metrics")
    commit = result.get("meta", {}).get("commit") or "?"
    problem = result.get("meta", {}).get("v2_problem")
    if problem:
        failures.append(f"현재 코드 50건 평가: {problem}")
    for label, body in (result.get("paths") or {}).items():
        arm, s = f"현재 코드 {commit} {label}", body.get("v2")
        if s is None:
            if base is not None and not problem:
                failures.append(f"{arm} 50건 평가 결과가 없다(기준 파일에는 current.v2_metrics가 있다): data/demo_replay/v2_recorded.json 확인")
            continue
        if base is None:
            failures.append(f"{arm} 기준 파일에 current.v2_metrics가 없다(50건 녹화를 올렸으면 기준도 같은 PR에서 올려야 한다)")
            continue
        if s.get("n_questions") != base.get("n_questions"):
            failures.append(f"{arm} 50건 평가 질문 수 {s.get('n_questions')} != 기준 {base.get('n_questions')}")
        for key, text in V2_LABELS.items():
            value, ref = s[key], base[key]
            low_bad = key in ("relevant_answered", "irrelevant_refused")
            bad = value < ref if low_bad else value > ref
            verdict = "기준보다 " + ("낮음" if low_bad else "많음") if bad else "통과"
            if bad:
                failures.append(f"{arm} {text} {value} vs 기준 {ref}" + (f" (녹화가 오래된 질문: {len(s.get('stale_questions', []))}개)" if key == "missed_calls" else ""))
            rows.append({"arm": arm, "label": text, "value": value, "baseline": ref, "gate": "-", "verdict": verdict})
    return rows, failures


def render(rows: list[dict], failures: list[str], runs, dataset: str, sha: str) -> str:
    lines = [
        "## 평가 점수 비교 (저장소에 커밋된 결과 파일, 키·네트워크 없음)",
        "",
        f"평가셋 `{dataset}` 동결 해시 `{sha[:12]}`, 결과 폴더 `{runs[0]}` 등 {len(runs)}개의 3회 평균",
        "",
        "| 구성 | 지표 | 이번 값 | 기준 결과 | 통과선 | 판정 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "note" in r:
            lines.append(f"| {r['arm']} | {r['note']} | | | | |")
        else:
            base = "-" if r["baseline"] is None else f"{r['baseline']}"
            lines.append(f"| {r['arm']} | {r['label']} | {r['value']} | {base} | {r['gate']} | {r['verdict']} |")
    lines.append("")
    lines.append("결과: **실패**" if failures else "결과: **통과**")
    for f in failures:
        lines.append(f"- {f}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--runs", nargs="+", default=list(DEFAULT_RUNS))
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--frozen", type=Path, default=FROZEN)
    parser.add_argument("--current", type=Path, default=None, help="`evals/ci_current_eval.py`가 현재 코드로 낸 0원 평가 결과 파일. 주면 기준 파일의 `current` 항목과 비교한다")
    args = parser.parse_args(argv)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    dataset = baseline["dataset"]
    if dataset not in frozen:
        print(f"{dataset}이 {args.frozen.name}에 없습니다.")
        return 1

    collected = collect(args.results_dir, args.runs, frozen, dataset)
    rows, failures = evaluate(collected, baseline)
    if "operating" in baseline:
        op_rows, op_failures = evaluate_operating(find_latest_operating(args.results_dir, frozen, dataset), baseline)
        rows += op_rows
        failures += op_failures
    if args.current is not None:
        if "current" not in baseline:
            failures.append("현재 코드 평가: 기준 파일에 current 항목이 없습니다")
        elif not args.current.is_file():
            failures.append(f"현재 코드 평가: 결과 파일 {args.current}이 없습니다(evals/ci_current_eval.py를 먼저 돌려야 합니다)")
        else:
            cur_rows, cur_failures = evaluate_current(json.loads(args.current.read_text(encoding="utf-8")), baseline)
            rows += cur_rows
            failures += cur_failures
    text = render(rows, failures, args.runs, dataset, frozen[dataset]["sha256"])

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
