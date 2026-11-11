"""실패 유형 표(EVAL_REPORT 5장). 저장된 측정 결과만 읽어 실패 문항을 유형으로 묶는다. 모델 호출이 없다.

입력
- 질문 답변 측정 폴더(`--qa 이름=폴더`): `evals/latency/deploy_citation_gold.py`가 만든 `citation_gold.json`의 `rows`
  (`run`, `id`, `expect_refusal`, `answered`, `gold_total`, `gold_hit`, `cited_off_gold`, `refuse_stage`, `refuse_reason`).
- 합동 검토 측정 폴더(`--review 이름=폴더`, 선택): `evals/agent/review_deploy.py`가 만든 `rows.jsonl`(`id`, `repeat`, `kind`, `path`).
- 첫 검색 문맥 파일(`--context`, 선택): `{"이름:문항": [문맥에 든 정답 위치 수, 정답 위치 수]}` 또는 회차별 `{"이름:문항:회차": [...]}`(회차 키가 먼저다).
  배포 측정 행에는 검색 문맥이 없으므로 정답 위치를 놓친 행이 검색 단계의 실패인지 답 단계의 실패인지는 이 파일이 있을 때만 가른다.
  파일은 검색만 다시 돌린 결과(문항 단위) 또는 운영 Langfuse 추적(`evals/latency/lf_context.py`, 회차 단위)에서 만든다.
  없으면 "정답 위치 누락(검색·선택 미구분)"으로 둔다.

규칙
- 행(한 문항의 한 회차)이 틀린 경우: 오류, 비관련 질문에 답함, 관련 질문을 거절·되물음, 정답 위치를 일부라도 놓침, 정답 밖 청크를 인용함.
  합동 검토 행은 합동 검토 경로로 가지 않음, 되물을 요청을 되묻지 않음, 되묻지 않을 요청을 되물음.
- 실패 문항: 틀린 회차가 `--min-wrong`(기본 2) 이상인 문항. 3회 측정이면 3회 중 2회 이상이다.
- 한 문항은 유형 하나에만 센다(주 유형). 틀린 회차의 유형 가운데 가장 많은 것을 고르고, 같으면 처리 순서가 앞선 단계(`TYPES`의 순서)를 고른다.
  그래서 유형별 문항 수의 합은 실패 문항 수와 같다.
- 유형은 행의 값으로 나눈 것이라 원인의 추정이다. 원인은 추적 기록으로 확인한다.

    python -m evals.agent.failure_types --qa v2=evals/results/deploy_latency_<리비전> --qa holdout=evals/results/deploy_latency_holdout_<리비전> \
        --review review=evals/results/review_deploy_<리비전> --context <문맥 파일> --out evals/results/failure_types_<리비전>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ERROR = "오류"
ROUTING = "라우팅 오분류"
ANSWERED_IRRELEVANT = "비관련 질문에 답함"
OVER_REFUSAL = "과잉 거절"
SEARCH = "검색 실패"
SELECTION = "근거 선택"
GOLD_MISS = "정답 위치 누락(검색·선택 미구분)"
OFF_GOLD = "정답 밖 인용"
FALSE_CLARIFY = "잘못 되물음"
MISSED_CLARIFY = "되묻기 누락"

# 처리 순서(앞 단계가 먼저). 주 유형이 같은 수로 갈리면 앞 단계를 고른다.
TYPES = (ERROR, ROUTING, FALSE_CLARIFY, MISSED_CLARIFY, ANSWERED_IRRELEVANT, OVER_REFUSAL, SEARCH, GOLD_MISS, SELECTION, OFF_GOLD)

NOTES = {
    ERROR: "응답이 오류로 끝남",
    ROUTING: "질문 종류 판정이 틀려 다른 경로로 감(관련 질문을 도메인 밖으로 거절, 합동 검토 요청이 합동 검토로 가지 않음)",
    FALSE_CLARIFY: "되묻지 않을 합동 검토 요청을 되물음",
    MISSED_CLARIFY: "되물을 합동 검토 요청을 되묻지 않음",
    ANSWERED_IRRELEVANT: "거절이나 되묻기를 기대한 질문에 답함",
    OVER_REFUSAL: "관련 질문을 근거 부족 등으로 거절하거나 되물음",
    SEARCH: "놓친 정답 위치가 첫 검색 문맥에 없음",
    GOLD_MISS: "정답 위치를 놓쳤으나 검색 문맥 기록이 없어 단계를 가르지 못함",
    SELECTION: "정답 위치가 첫 검색 문맥에 다 있는데 답이 인용하지 않음",
    OFF_GOLD: "정답 위치는 모두 인용하고 정답 밖 청크를 더 인용함",
}


def classify_qa(row: dict, ctx: list[int] | None = None) -> str | None:
    """질문 답변 행이 틀렸으면 유형, 맞으면 None. ctx는 [첫 검색 문맥에 든 정답 위치 수, 정답 위치 수]."""
    if row.get("status", "ok") != "ok" or row.get("result") == "error":
        return ERROR
    if row["expect_refusal"]:
        return ANSWERED_IRRELEVANT if row["answered"] else None
    if not row["answered"]:
        return ROUTING if "out_of_domain" in (row.get("refuse_stage"), row.get("refuse_reason")) else OVER_REFUSAL
    if row["gold_total"] and row["gold_hit"] < row["gold_total"]:
        if ctx is None:
            return GOLD_MISS
        return SEARCH if ctx[0] < ctx[1] else SELECTION
    return OFF_GOLD if row.get("cited_off_gold", 0) > 0 else None


def classify_review(row: dict) -> str | None:
    """합동 검토 행이 틀렸으면 유형, 맞으면 None."""
    if row.get("error_code"):
        return ERROR
    if row["path"] == "other_route":
        return ROUTING
    asked = row["path"] == "review_clarify"
    if row["kind"] == "clarify":
        return None if asked else MISSED_CLARIFY
    return FALSE_CLARIFY if asked else None


def primary(types: list[str]) -> str:
    """틀린 회차의 유형 가운데 가장 많은 것. 같으면 처리 순서가 앞선 것."""
    count = Counter(types)
    return min(count, key=lambda t: (-count[t], TYPES.index(t)))


def analyze(sets: list[dict], min_wrong: int = 2) -> dict:
    """sets: [{"name", "rows": [(문항, 회차, 유형 또는 None)]}]. 문항마다 틀린 회차를 세고 실패 문항을 주 유형으로 묶는다."""
    failed, unstable, n_items = [], [], 0
    for s in sets:
        by_item: dict[int, dict[int, str | None]] = defaultdict(dict)
        for item, run, kind in s["rows"]:
            by_item[item][run] = kind
        n_items += len(by_item)
        for item in sorted(by_item):
            runs = by_item[item]
            wrong = [runs[r] for r in sorted(runs) if runs[r]]
            if not wrong:
                continue
            entry = {"set": s["name"], "id": item, "wrong": len(wrong), "runs": len(runs), "by_run": [runs[r] for r in sorted(runs)]}
            if len(wrong) >= min_wrong:
                failed.append({**entry, "type": primary(wrong)})
            else:
                unstable.append(entry)
    by_type = {t: [f for f in failed if f["type"] == t] for t in TYPES}
    by_type = {t: v for t, v in by_type.items() if v}
    return {"min_wrong": min_wrong, "n_items": n_items, "n_failed": len(failed), "type_sum": sum(len(v) for v in by_type.values()),
            "largest": max(by_type, key=lambda t: len(by_type[t])) if by_type else None, "by_type": by_type, "below_threshold": unstable}


def label(entry: dict) -> str:
    return f"{entry['set']} {entry['id']}"


def to_markdown(res: dict, sources: list[str]) -> str:
    L = [f"# 실패 유형 표 (실패 문항 {res['n_failed']} / 문항 {res['n_items']})", "",
         f"- 입력: {', '.join(sources)}",
         f"- 실패 문항은 틀린 회차가 {res['min_wrong']}회 이상인 문항이고, 한 문항은 주 유형 하나에만 센다. 유형은 행의 값으로 나눈 추정이다.", "",
         "| 유형 | 문항 수 | 문항 | 뜻 |", "|---|---|---|---|"]
    for t, items in res["by_type"].items():
        L.append(f"| {t} | {len(items)} | {', '.join(label(i) for i in items)} | {NOTES[t]} |")
    L += [f"| 합계 | {res['type_sum']} | 실패 문항 수 {res['n_failed']}와 {'같음' if res['type_sum'] == res['n_failed'] else '다름'} | |", "",
          "| 문항 | 주 유형 | 틀린 회차 | 회차별 |", "|---|---|---|---|"]
    for items in res["by_type"].values():
        L += [f"| {label(i)} | {i['type']} | {i['wrong']}/{i['runs']} | {' / '.join(k or '맞음' for k in i['by_run'])} |" for i in items]
    if res["below_threshold"]:
        L += ["", f"틀린 회차가 {res['min_wrong']}회 미만이라 실패 문항으로 세지 않은 문항:", "", "| 문항 | 틀린 회차 | 회차별 |", "|---|---|---|"]
        L += [f"| {label(i)} | {i['wrong']}/{i['runs']} | {' / '.join(k or '맞음' for k in i['by_run'])} |" for i in res["below_threshold"]]
    return "\n".join(L) + "\n"


def named(value: str) -> tuple[str, Path]:
    name, sep, path = value.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError("이름=폴더 꼴로 적는다")
    return name, Path(path)


def load_sets(qa: list[tuple[str, Path]], review: list[tuple[str, Path]], context: dict) -> list[dict]:
    sets = []
    for name, folder in qa:
        rows = json.loads((folder / "citation_gold.json").read_text(encoding="utf-8"))["rows"]
        sets.append({"name": name, "rows": [(r["id"], r["run"], classify_qa(r, context.get(f"{name}:{r['id']}:{r['run']}", context.get(f"{name}:{r['id']}")))) for r in rows]})
    for name, folder in review:
        rows = [json.loads(line) for line in (folder / "rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        sets.append({"name": name, "rows": [(r["id"], r["repeat"], classify_review(r)) for r in rows]})
    return sets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=named, action="append", default=[], help="이름=질문 답변 측정 폴더(citation_gold.json)")
    ap.add_argument("--review", type=named, action="append", default=[], help="이름=합동 검토 측정 폴더(rows.jsonl)")
    ap.add_argument("--context", type=Path, default=None, help="첫 검색 문맥에 든 정답 위치 수 파일")
    ap.add_argument("--min-wrong", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if not a.qa and not a.review:
        ap.error("--qa나 --review를 하나 이상 준다")
    context = json.loads(a.context.read_text(encoding="utf-8")) if a.context else {}
    res = analyze(load_sets(a.qa, a.review, context), a.min_wrong)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "failure_types.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        sources = [f"{n}={p.as_posix()}" for n, p in a.qa + a.review] + ([f"문맥 {a.context.as_posix()}"] if a.context else [])
        (a.out / "failure_types.md").write_text(to_markdown(res, sources), encoding="utf-8")
    print(f"실패 문항 {res['n_failed']} / 문항 {res['n_items']}: " + ", ".join(f"{t} {len(v)}" for t, v in res["by_type"].items()))
    return 0 if res["type_sum"] == res["n_failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
