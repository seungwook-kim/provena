"""정상 데이터에 대한 방어의 영향 전수 검사(비용 0원, 읽기만): 전체 코퍼스 오탐과 저장된 v2 최종 답 오프라인 검사.

`python -m evals.safety.scan_untrusted --chunks data/index/chunks.jsonl`
- (가) 코퍼스 청크의 본문·제목·절 제목에 입력 정화를 돌려 바뀌는 청크 필드 수(오탐. 0이어야 채택). 출력 검사용 의심 절이 든 청크 수도 센다.
- (나) 저장된 v2 최종 답(`agent_v2_q_d6151_r1~r3_bo2sda2_api`, `_h1_bo2sda2_api`의 단일·멀티 행)에 출력 검사를 적용해 바뀌는 답 수(0이어야 채택).
(다) 권한표 칸(`data/parsed/authz_cells.jsonl`)에 칸 정화(`sanitize_cell`)와 결정표 변환 출력 검사를 돌려 바뀌는 칸 수(0이어야 채택, 사전 등록 62.26).
PREREGISTER 62.1, 62.5, 62.26의 정상 답 영향 확인이다. 청크 파일이 없으면 (가)는 건너뛴다. (가)는 절 이름(org)도 본다.
"""
from __future__ import annotations

import argparse
import json
import os
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
            for field in ("text", "rule_title", "article", "org"):
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


def scan_cells(path: Path) -> dict:
    """권한표 칸 전수: 모델 입력용 칸 정화(`sanitize_cell`)가 바꾸는 칸 수와, 칸 값을 그대로 옮긴 초안이 출력 검사에 걸리는 수. 둘 다 0이어야 한다."""
    from backend.graph.decision.convert import CELL_KEYS, draft_leaks

    cells = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    changed = sum(1 for c in cells for k in CELL_KEYS if U.sanitize_cell(c.get(k)) != c.get(k))
    by_cat: dict[str, list[dict]] = {}
    for c in cells:
        by_cat.setdefault(str(c.get("category")), []).append(c)
    leaked = 0
    for group in by_cat.values():   # 변환 모델이 칸 값을 그대로 옮긴 정상 초안
        rules = [{"approvers": [c.get("role")] if c.get("value") else [], "financial_approvers": [], "cooperating_depts": []} for c in group]
        leaked += bool(draft_leaks(rules, group))
    return {"cells": len(cells), "categories": len(by_cat), "changed_cells": changed, "leaked_drafts": leaked}


def prompt_inputs(chunks: list[dict], *, enabled: bool) -> tuple[str, list[str]]:
    """청크가 질문 그래프의 모델 입력에 들어가는 두 글: 자료 머리·본문(`format_materials`)과 재작성 입력의 이미 찾은 문서 제목(`seen_titles`).
    입력 정화 스위치를 켠 때(enabled=True)와 끈 때를 같은 청크로 만들어 비교한다."""
    from backend.prompts.question import format_materials, seen_titles

    old = os.environ.get("GRAPH_SANITIZE_INPUT")
    os.environ["GRAPH_SANITIZE_INPUT"] = "1" if enabled else "0"
    try:
        return format_materials(chunks), seen_titles(chunks)
    finally:
        if old is None:
            os.environ.pop("GRAPH_SANITIZE_INPUT", None)
        else:
            os.environ["GRAPH_SANITIZE_INPUT"] = old


def scan_answers(results: Path, index: dict[str, dict] | None = None) -> dict:
    """저장된 최종 답 340행(v2 50건 x 6회 + 검증 20건 x 2회). `index`(chunk_id -> 색인 청크)가 있으면 행이 가져온 청크를 색인에서 다시 찾아
    본문·제목·절 제목·절 이름 전부에 입력 정화를 돌린다(저장된 행에는 본문과 제목 한 줄만 있다). 임베딩 호출은 없다."""
    total = changed = chunk_rows = full_rows = full_changed = missing = input_rows = 0
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
                if index is not None:
                    found = [index[ch["chunk_id"]] for ch in ctx if ch.get("chunk_id") in index]
                    missing += len(ctx) - len(found)
                    if any(U.sanitize_chunk(c) != c for c in found):
                        full_rows += 1
                    if prompt_inputs(found, enabled=True) != prompt_inputs(found, enabled=False):   # 모델 입력이 켬과 끔에서 글자 하나라도 다른 행
                        input_rows += 1
                    if U.scrub_answer(answer, found, row.get("question", ""))[1]:   # 제목까지 든 색인 청크로 출력 검사를 다시 한다
                        full_changed += 1
    out = {"answers": total, "changed_answers": changed, "rows_with_changed_chunk_text": chunk_rows, "examples": examples[:20]}
    if index is not None:
        out.update(rows_with_changed_index_chunk=full_rows, changed_answers_with_index_chunks=full_changed, chunks_not_in_index=missing,
                   rows_with_changed_model_input=input_rows)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="방어가 정상 데이터에 주는 영향(오탐, 바뀐 답)")
    ap.add_argument("--chunks", default="data/index/chunks.jsonl")
    ap.add_argument("--results", default="evals/results")
    ap.add_argument("--cells", default="data/parsed/authz_cells.jsonl")
    args = ap.parse_args(argv)
    out: dict = {}
    if Path(args.chunks).exists():
        out["corpus"] = scan_chunks(Path(args.chunks))
    else:
        print(f"청크 파일 없음: {args.chunks} (코퍼스 오탐 검사 건너뜀)", file=sys.stderr)
    if Path(args.cells).exists():
        out["cells"] = scan_cells(Path(args.cells))
    index = None
    if Path(args.chunks).exists():
        with Path(args.chunks).open(encoding="utf-8") as f:
            index = {c["chunk_id"]: c for c in (json.loads(line) for line in f if line.strip()) if c.get("chunk_id")}
    out["answers"] = scan_answers(Path(args.results), index)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    bad = (out.get("corpus", {}).get("changed_fields", 0) + out["answers"]["changed_answers"] + out["answers"]["rows_with_changed_chunk_text"]
           + out["answers"].get("rows_with_changed_model_input", 0) + out["answers"].get("rows_with_changed_index_chunk", 0) + out["answers"].get("changed_answers_with_index_chunks", 0)
           + out.get("cells", {}).get("changed_cells", 0) + out.get("cells", {}).get("leaked_drafts", 0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
