"""배포본 측정 결과의 실패 유형 세기 (EVAL_REPORT 5장 5-1 표의 배포본용). LLM 호출도 운영 접속도 없다.

    python -m evals.retrieval.fail_types [--out evals/results/fail_types_00035]

`deploy_latency.py`가 저장한 행(`run*/rows.jsonl`)의 `cited_chunk_ids`를 평가셋 정답 위치와 맞춰 센다.
채점 규칙은 `evals/latency/deploy_citation_gold.py`(= `evals/retrieval/gold.py`의 `GoldRef.matches`)를 그대로 쓴다.

5장 5-1 표와 다른 점 (이름을 일부러 다르게 했다)
- 배포본 행에는 답 단계로 넘어간 청크(`retrieved`)가 없고 **인용한 청크 id만** 있다. 그래서 5-1의 "정답이 문맥에 없음(검색)"과
  "정답이 문맥에 다 있는데 일부만 인용"은 가를 수 없다. 대신 "정답 위치를 하나도 인용하지 않음", "정답 위치 일부만 인용"으로 센다.
  앞쪽은 검색 실패일 수도, 문맥에는 있었는데 인용하지 않은 판정·작성 실패일 수도 있다.
- 행에 `route`가 없다. 분류 오류는 `refuse_stage == out_of_domain`으로 거절된 관련 행(도메인 밖 분류로 거절)만 센다.
  사실 질문이 승인·검토 경로로 간 오분류(v2 7, 15, 38번 유형)는 행으로 알 수 없어 세지 않는다.
- 정답 밖 인용: 답한 관련 행 중 정답 위치 밖 청크를 하나라도 인용한 행 (5-1과 같은 정의, 다른 칸과 겹칠 수 있다).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.latency.deploy_citation_gold import load_corpus, load_runs, score_runs
from evals.retrieval.run import load_dataset, load_exclusions

REPO = Path(__file__).resolve().parents[2]
REV = "provena-api-00035-h69"
MEASURES = [
    ("v2 50건", f"deploy_latency_{REV}", "dataset_v2.jsonl"),
    ("검증 20건", f"deploy_latency_holdout_{REV}", "dataset_holdout_v1.jsonl"),
    ("새 인용 5건", f"deploy_latency_cite_new_{REV}", "dataset_cite_new_v1.jsonl"),
]


def classify(scored: list[dict]) -> dict[str, Any]:
    """채점된 행 -> 실패 유형별 건수와 문항별 행 수. 칸이 서로 겹치지 않게 관련 행은 한 칸에만 센다(정답 밖 인용 제외)."""
    rel = [r for r in scored if not r["expect_refusal"]]
    irr = [r for r in scored if r["expect_refusal"]]
    ans = [r for r in rel if r["answered"]]
    refused = [r for r in rel if not r["answered"]]
    zero = [r for r in ans if r["gold_total"] and r["gold_hit"] == 0]
    partial = [r for r in ans if 0 < r["gold_hit"] < r["gold_total"]]
    off = [r for r in ans if r["cited_off_gold"] > 0]
    stages = Counter(f"{r['result']}/{r['refuse_stage']}" for r in refused)

    def by_q(rows: list[dict]) -> dict[str, int]:
        c = Counter(str(r["id"]) for r in rows)
        return dict(sorted(c.items(), key=lambda kv: int(kv[0])))

    return {
        "relevant_rows": len(rel),
        "answered_relevant": len(ans),
        "refused_relevant": len(refused),
        "refused_by_stage": dict(stages),
        "refused_out_of_domain": sum(r["refuse_stage"] == "out_of_domain" for r in refused),
        "no_gold_cited": len(zero),
        "partial_gold_cited": len(partial),
        "off_gold_cited": len(off),
        "answered_for_off_gold": len(ans),
        "irrelevant_rows": len(irr),
        "irrelevant_answered": sum(r["answered"] for r in irr),
        "irrelevant_refused": sum(r["result"] == "refuse" for r in irr),
        "irrelevant_clarified": sum(r["result"] == "clarify" for r in irr),
        "questions": {
            "refused_relevant": by_q(refused), "no_gold_cited": by_q(zero),
            "partial_gold_cited": by_q(partial), "off_gold_cited": by_q(off),
            "refused_out_of_domain": by_q([r for r in refused if r["refuse_stage"] == "out_of_domain"]),
        },
    }


def measure(label: str, results: Path, dataset: Path, corpus: list[Any], exclusions: dict[str, str]) -> dict[str, Any]:
    runs = load_runs(results)
    res = score_runs(runs, load_dataset(dataset), corpus, exclusions)
    per_run: dict[int, list[dict]] = defaultdict(list)
    for r in res["rows"]:
        per_run[r["run"]].append(r)
    return {"measure": label, "results": results.as_posix(), "dataset": dataset.name, "rows_total": len(res["rows"]),
            "rows_without_chunk_ids": sum(not r["has_chunk_ids"] for r in res["rows"]),
            "unresolved_citations": sum(len(r["unresolved"]) for r in res["rows"]),
            "pooled": classify(res["rows"]), "per_run": {str(n): classify(rows) for n, rows in sorted(per_run.items())}}


def render(out: list[dict]) -> str:
    head = ("| 측정 | 관련 행 | 정답 위치를 하나도 인용하지 않음 | 정답 위치 일부만 인용 | 거절·되묻기 (단계) | 정답 밖 인용 (답한 행 중) | 도메인 밖 분류로 거절 | 비관련 행 / 그중 답함 |\n"
            "|---|---|---|---|---|---|---|---|")
    lines = [head]
    for m in out:
        p, q = m["pooled"], m["pooled"]["questions"]

        def qs(k: str) -> str:
            return ", ".join(f"{i}번 {n}행" for i, n in q[k].items()) or "-"

        stages = ", ".join(f"{k} {v}" for k, v in p["refused_by_stage"].items()) or "-"
        lines.append(f"| {m['measure']} | {p['relevant_rows']} | {p['no_gold_cited']} ({qs('no_gold_cited')}) | {p['partial_gold_cited']} ({qs('partial_gold_cited')}) | "
                     f"{p['refused_relevant']} ({stages}; {qs('refused_relevant')}) | {p['off_gold_cited']} / {p['answered_for_off_gold']} ({qs('off_gold_cited')}) | "
                     f"{p['refused_out_of_domain']} ({qs('refused_out_of_domain')}) | {p['irrelevant_rows']} / {p['irrelevant_answered']} (거절 {p['irrelevant_refused']}, 되묻기 {p['irrelevant_clarified']}) |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.fail_types", description="배포본 저장 행으로 실패 유형 세기(키·네트워크 없음)")
    ap.add_argument("--out", type=Path, default=REPO / "evals" / "results" / "fail_types_00035")
    ap.add_argument("--chunks", type=Path, default=None, help="코퍼스 청크 JSONL(기본 data/index.tar.gz 안의 파일)")
    a = ap.parse_args(argv)
    corpus, _meta, source = load_corpus(a.chunks)
    excl = load_exclusions(REPO / "evals" / "exclusions.json")
    out = [measure(lb, REPO / "evals" / "results" / rd, REPO / "evals" / ds, corpus, excl) for lb, rd, ds in MEASURES]
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "fail_types.json").write_text(json.dumps({"revision": REV, "corpus": source, "measures": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = render(out)
    (a.out / "fail_types.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
