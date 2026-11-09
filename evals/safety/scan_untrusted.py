"""정상 데이터에 대한 방어의 영향 전수 검사(비용 0원, 읽기만): 전체 코퍼스 오탐과 저장된 v2 최종 답 오프라인 검사.

`python -m evals.safety.scan_untrusted --chunks data/index/chunks.jsonl`
- (가) 코퍼스 청크의 본문·제목·절 제목에 입력 정화를 돌려 바뀌는 청크 필드 수(오탐. 0이어야 채택). 출력 검사용 의심 절이 든 청크 수도 센다.
- (나) 저장된 v2 최종 답(`agent_v2_q_d6151_r1~r3_bo2sda2_api`, `_h1_bo2sda2_api`의 단일·멀티 행)에 출력 검사를 적용해 바뀌는 답 수(0이어야 채택).
PREREGISTER 62.1, 62.5의 정상 답 영향 확인이다. 청크 파일이 없으면 (가)는 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.graph import untrusted as U

RUNS = ["agent_v2_q_d6151_r1_bo2sda2_api", "agent_v2_q_d6151_r2_bo2sda2_api", "agent_v2_q_d6151_r3_bo2sda2_api", "agent_v2_q_d6151_h1_bo2sda2_api"]


def scan_chunks(path: Path) -> dict:
    n = hits = suspect_chunks = 0
    examples: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            n += 1
            for field in ("text", "rule_title", "article"):
                v = c.get(field)
                if not v:
                    continue
                clean, removed = U.strip_instructions(str(v), cut_tail=field != "text")
                if removed:
                    hits += 1
                    examples.append({"chunk_id": c.get("chunk_id"), "field": field, "removed": [r[:200] for r in removed[:3]]})
                if field == "text" and U.split_suspects(clean)[1]:
                    suspect_chunks += 1
    return {"chunks": n, "changed_fields": hits, "suspect_chunks": suspect_chunks, "examples": examples[:20]}


def scan_answers(results: Path) -> dict:
    total = changed = chunk_rows = 0
    examples: list[dict] = []
    for run in RUNS:
        for arm in ("single", "multi"):
            for line in (results / run / f"{arm}.partial.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                answer = row.get("answer")
                if not answer:
                    continue
                total += 1
                ctx = row.get("context_chunks") or []
                new, removed = U.scrub_answer(answer, ctx, row.get("question", ""))
                if removed or new != answer:
                    changed += 1
                    examples.append({"run": run, "arm": arm, "id": row.get("id"), "removed": removed[:2]})
                if any(U.sanitize_chunk(ch) != ch for ch in ctx):
                    chunk_rows += 1
    return {"answers": total, "changed_answers": changed, "rows_with_changed_chunk_text": chunk_rows, "examples": examples[:20]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="방어가 정상 데이터에 주는 영향(오탐, 바뀐 답)")
    ap.add_argument("--chunks", default="data/index/chunks.jsonl")
    ap.add_argument("--results", default="evals/results")
    args = ap.parse_args(argv)
    out: dict = {}
    if Path(args.chunks).exists():
        out["corpus"] = scan_chunks(Path(args.chunks))
    else:
        print(f"청크 파일 없음: {args.chunks} (코퍼스 오탐 검사 건너뜀)", file=sys.stderr)
    out["answers"] = scan_answers(Path(args.results))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    bad = out.get("corpus", {}).get("changed_fields", 0) + out["answers"]["changed_answers"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
