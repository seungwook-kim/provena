"""인용 없는 답의 건수와 비율, 분모 계산 (S-04). 저장된 결과(`rows.jsonl`)만 읽는다. LLM·네트워크 호출 없음.

    python evals/uncited_answers.py evals/results/agent_v1_final_cite [더 많은 결과 폴더 ...]

분모를 둘 다 적는다. 어느 쪽이 "인용 없는 답 비율"인지 숫자를 읽는 사람이 오해하지 않게 하려는 것이다.
- 답한 문항(`result == "answer"`): 인용 없는 답 = `cited`가 비어 있는 답. 이 비율이 "답 중 인용이 빠진 비율"이다.
- 전체 문항: 거절·되묻기까지 포함한 분모. 거절은 인용이 없는 것이 정상이라 이 비율은 인용 누락을 뜻하지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_rows(folder: Path) -> list[dict]:
    path = folder / "rows.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def uncited_stats(rows: list[dict]) -> dict:
    answered = [r for r in rows if r.get("result") == "answer"]
    uncited = [r for r in answered if not r.get("cited")]
    return {
        "total": len(rows),
        "answered": len(answered),
        "uncited_answers": len(uncited),
        "uncited_ids": [r.get("id") for r in uncited],
        "rate_of_answered": (len(uncited) / len(answered)) if answered else None,   # 답이 하나도 없으면 비율을 정하지 않는다(0으로 나누지 않는다)
        "rate_of_total": (len(uncited) / len(rows)) if rows else None,
        # 하위 질문이 둘 이상인 문항만 "하위 질문 하나 빼기"가 의미 있다. 저장된 결과에는 합친 뒤 목록(`retrieved`)만 있고 하위 질문별 목록은 없어서
        # 빼고 다시 계산할 수는 없다. 그 시험은 `merge_by_score`에 목록을 직접 넣어 한다(`tests/test_uncited_and_drop_one.py`).
        "multi_sub_query_rows": sum(1 for r in rows if len(r.get("sub_queries") or []) >= 2),
    }


def fmt(rate: float | None) -> str:
    return "해당 없음(분모 0)" if rate is None else f"{rate:.3f}"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        s = uncited_stats(load_rows(Path(arg)))
        print(f"{arg}: 전체 {s['total']}, 답 {s['answered']}, 인용 없는 답 {s['uncited_answers']} "
              f"(답 기준 {fmt(s['rate_of_answered'])}, 전체 기준 {fmt(s['rate_of_total'])}), 하위 질문 둘 이상 {s['multi_sub_query_rows']}문항 {s['uncited_ids'] or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
