"""CI용 평가 점수 비교. 키·네트워크 없이 저장소에 커밋된 결과 파일만 읽는다.

    python evals/ci_compare.py

1. 최종 측정 결과(EVAL_REPORT 4장 최종 행, `agent_v2_q_d6151_r{1,2,3}_bo2sda2_api/`)의
   single·multi summary.json을 3회 평균한다.
2. 결과 summary의 dataset_sha256이 `evals/FROZEN.json`의 현재 동결 해시와 같은 결과만 비교한다.
   해시가 다른 옛 결과(첫 동결 해시로 잰 값 등)는 비교에서 빼고 표에 적는다.
3. 통과선(README 목표 지표, EVAL_REPORT 4장)과 기준 결과(`evals/ci_baseline.json`)와 비교한다.
   통과선 미달이거나 기준보다 나빠지면 종료 코드 1.
4. 비교 표를 표준출력과 `$GITHUB_STEP_SUMMARY`에 쓴다.

통과선: 인용 정확도 0.85 이상, 정답 근거 인용률 0.85 이상, 비관련 질문 거절 0.90 이상, 전체 p95 10초 이하.
기준 결과 비교: 정답 근거·인용 정확도·거절은 기준보다 낮아지면, 오답 근거·과잉 거절·환각 위험은 기준보다
높아지면 실패. 응답 시간은 공급자에 따라 달라지므로 통과선만 본다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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
            verdict = "통과"
            if key in FLOORS and value < FLOORS[key] - EPS:
                verdict = "통과선 미달"
                failures.append(f"{arm} {label} {value} < 통과선 {FLOORS[key]}")
            elif key in CEILINGS and value > CEILINGS[key] + EPS:
                verdict = "통과선 초과"
                failures.append(f"{arm} {label} {value} > 통과선 {CEILINGS[key]}")
            elif key in HIGHER_IS_BETTER and ref is not None and value < ref - EPS:
                verdict = "기준보다 낮음"
                failures.append(f"{arm} {label} {value} < 기준 {ref}")
            elif key in LOWER_IS_BETTER and ref is not None and value > ref + EPS:
                verdict = "기준보다 높음"
                failures.append(f"{arm} {label} {value} > 기준 {ref}")
            gate = FLOORS.get(key)
            gate_text = f">= {gate}" if gate is not None else (f"<= {CEILINGS[key]}" if key in CEILINGS else "-")
            rows.append({"arm": arm, "label": label, "value": value, "baseline": ref, "gate": gate_text, "verdict": verdict})
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
    args = parser.parse_args(argv)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    dataset = baseline["dataset"]
    if dataset not in frozen:
        print(f"{dataset}이 {args.frozen.name}에 없습니다.")
        return 1

    collected = collect(args.results_dir, args.runs, frozen, dataset)
    rows, failures = evaluate(collected, baseline)
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
