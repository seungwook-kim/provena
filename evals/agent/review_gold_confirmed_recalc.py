"""확정 정답으로 저장된 운영 합동 검토 결과(00044, 00049)를 0원으로 다시 계산한다 (사전 등록 62.61, 결정 0117).

네트워크, 운영 DB, 유료 API를 쓰지 않는다. 이미 저장된 `rows.jsonl`(런별 쟁점표 행)을 읽어 같은 공식 지표(`review_deploy.summarize`,
같은 팀, 근거 섹션 일치)를 두 정답 파일로 각각 계산하고 결과를 나란히 적는다.
- 초안: `evals/dataset_review_v1_gold_draft.jsonl` (00044, 00049가 측정될 때의 정답)
- 확정: `evals/dataset_review_v1_gold.jsonl` (조원 2명 확인, 2026-11-13)
공식 지표가 쟁점 문장을 보지 않으므로 문장만 고친 7개는 값을 바꾸지 못한다. 이 도구는 그것을 숫자로 확인한다.

    PYTHONPATH=. python -m evals.agent.review_gold_confirmed_recalc --out evals/results/review_gold_confirmed_recalc_20261113
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.agent import exp_review_v1 as X
from evals.agent import review_deploy as R

RESULTS = X.EVALS / "results"
RUNS = {"00044": RESULTS / "review_deploy_provena-api-00044-49s", "00049": RESULTS / "review_deploy_provena-api-00049-nph"}
DRAFT = X.EVALS / "dataset_review_v1_gold_draft.jsonl"
CONFIRMED = X.EVALS / "dataset_review_v1_gold.jsonl"
ARMS = ("team", "same", "undivided")


def recompute(run_dir: Path, dataset: Path) -> dict:
    """한 측정 폴더의 저장된 행을 한 정답 파일로 다시 채점해 갈래별 찾음·누락률을 돌려준다."""
    items = {str(it["id"]): it for it in X.load_review_dataset(dataset)}
    by_arm = R.load_all(run_dir)
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["meta"]
    s = R.summarize(by_arm, items, meta)
    out = {}
    for label in ("all", "paired"):
        arms = s["comparison"][label]["arms"]
        out[label] = {a: {"found": arms[a]["gold_found"], "total": arms[a]["gold_total"], "missed_rate": arms[a]["missed_issue_rate"],
                          "missed_by_repeat": arms[a]["missed_by_repeat"]} for a in ARMS}
        out[label]["verdict_vs_same"] = s["comparison"][label]["team_vs_same"]["text"]
        out[label]["verdict_vs_undivided"] = s["comparison"][label]["team_vs_undivided"]["text"]
    return out


def issue_text_diff() -> list[dict]:
    """초안과 확정 정답 사이에 쟁점 문장이 다른 항목(문항 id, 번째)과 팀·근거 섹션이 같은지."""
    d = {str(it["id"]): it for it in X.load_review_dataset(DRAFT)}
    c = {str(it["id"]): it for it in X.load_review_dataset(CONFIRMED)}
    diffs = []
    for iid in sorted(c, key=lambda x: int(x) if x.isdigit() else x):
        gd, gc = d[iid]["gold_issues"], c[iid]["gold_issues"]
        assert len(gd) == len(gc), f"문항 {iid}: 쟁점 개수가 다르다"
        for i, (a, b) in enumerate(zip(gd, gc), 1):
            if a.get("issue") != b.get("issue"):
                key = lambda g: {k: g.get(k) for k in g if k != "issue"}
                diffs.append({"id": iid, "nth": i, "same_team_and_section": key(a) == key(b)})
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="확정 정답으로 00044, 00049 저장 결과를 0원 재계산")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"runs": {}, "text_diffs": issue_text_diff()}
    lines = ["# 확정 정답 0원 재계산 (사전 등록 62.61, 결정 0117)", "",
             "저장된 rows.jsonl을 초안 정답과 확정 정답으로 각각 같은 지표로 다시 채점했다. 네트워크, 운영 DB, 유료 API 호출 없음.", ""]
    same_all = True
    for name, d in RUNS.items():
        draft, conf = recompute(d, DRAFT), recompute(d, CONFIRMED)
        result["runs"][name] = {"draft": draft, "confirmed": conf}
        lines += [f"## {name}", "", "| 갈래 | 초안 찾음 | 확정 찾음 | 초안 누락률 | 확정 누락률 | 일치 |", "|---|---|---|---|---|---|"]
        for a in ARMS:
            x, y = draft["all"][a], conf["all"][a]
            ok = (x["found"], x["total"], x["missed_rate"]) == (y["found"], y["total"], y["missed_rate"])
            same_all &= ok and draft["paired"][a]["found"] == conf["paired"][a]["found"]
            lines.append(f"| {a} | {x['found']}/{x['total']} | {y['found']}/{y['total']} | {x['missed_rate']} | {y['missed_rate']} | {'같음' if ok else '다름'} |")
        lines += ["", f"- 판정 문구(확정, same 기준): {conf['all']['verdict_vs_same']}", f"- 판정 문구(초안, same 기준): {draft['all']['verdict_vs_same']}", ""]
    n_same = sum(1 for t in result["text_diffs"] if t["same_team_and_section"])
    lines += [f"## 쟁점 문장이 다른 항목", "", f"- {len(result['text_diffs'])}개(문항 id, 번째): " + ", ".join(f"{t['id']}-{t['nth']}" for t in result["text_diffs"]),
              f"- 이 중 팀과 근거 섹션이 초안과 같은 항목: {n_same}개", "",
              f"## 결론", "", f"- 모든 갈래의 찾음 수와 누락률이 초안과 확정에서 {'같다' if same_all else '다르다'}. 공식 지표는 팀과 근거 섹션만 맞추기 때문이다.", ""]
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if same_all else 1


if __name__ == "__main__":
    sys.exit(main())
