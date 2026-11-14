"""표·수치 청크 원문 대조를 새 청크로 한 명령에 다시 한다 (체크포인트 3조 코멘트 ②, 0원).

    python evals/recheck_table_number_chunks.py [--out evals/results/table_number_source_check_<오늘>_recheck]

하는 일: 로컬 `data/chunks/chunks.jsonl`(청킹 결과)과 `data/index/chunks.jsonl`(적재하는 색인의 청크 파일)이 같은 바이트인지 확인한 뒤,
`evals/results/table_number_source_check_20261113_corpus/check_corpus.py`(코퍼스 전체 청크 중 표·수치가 든 청크를 스냅샷 원문과 대조)를 그대로 돌린다.
- LLM·키·운영 호출·네트워크 없음. 저장소 파일은 읽기만 하고 결과는 `--out` 폴더에만 쓴다(이미 있는 결과 폴더는 덮어쓰지 않는다).
- 두 청크 파일이 `version_date` 밖의 칸에서 다르면(색인을 아직 풀지 않았거나 청킹 뒤 다시 풀지 않음) 멈춘다. 대조 스크립트는 `data/index/chunks.jsonl`을 읽기 때문이다.
  `version_date`만 다른 줄은 대조가 읽지 않는 칸이라 줄 수만 알리고 진행한다.
- 끝나면 `summary.json`의 핵심 값(불일치 수, 겹침 조각 중 표 행 중간에서 시작한 수, 앞 칸이 빠진 수)과 겹침 종류별 수(꼬리 그대로 / 라벨+꼬리 / 그 밖)를 출력한다.
  `mismatch`와 `structure_problems`는 대조 스크립트의 겹침 규칙이 "앞 청크 본문 꼬리 그대로"만 맞다고 보기 때문에, 긴 표 행에 첫 칸(라벨)을 붙인 겹침(`ROW_TAIL_MAX=400` 규칙)도 센다.
  그래서 `numbers_mismatch`·`rows_mismatch`(숫자, 표 행·열)와 `overlap_other`(둘 다 아닌 겹침)를 함께 읽는다.
기준 값(앞 대조 `table_number_source_check_20261113_corpus`, 재청킹 전): 불일치 3, 표 행 중간 겹침 724, 앞 칸 빠짐 610, 선택 청크 4,319.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "evals" / "results" / "table_number_source_check_20261113_corpus" / "check_corpus.py"
KEYS = ("total_chunks", "selected", "mismatch", "numbers_mismatch", "rows_mismatch", "structure_problems", "overlap_chunks", "table_row_mid", "first_cell_missing", "cells_lost_whole_ge1")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# 대조가 읽지 않는 칸. 두 파일이 이 칸만 다르면(예: 판 날짜 하루 차이) 대조는 그대로 하고 다른 줄 수를 알린다
TOLERATED = ("version_date",)


def chunk_files_problem(root: Path, notes: list[str] | None = None) -> str | None:
    """청킹 결과와 색인의 청크 파일이 없거나 `TOLERATED` 밖의 칸이 다르면 이유를, 아니면 None. 참고할 차이는 notes에 담는다."""
    a, b = root / "data" / "chunks" / "chunks.jsonl", root / "data" / "index" / "chunks.jsonl"
    for p in (a, b):
        if not p.is_file():
            return f"{p.relative_to(root)} 가 없습니다. 색인을 먼저 푸세요(python -m backend.rag.ingest.snapshot unpack-index)"
    if sha256_of(a) == sha256_of(b):
        return None
    ra, rb = _rows(a), _rows(b)
    if len(ra) != len(rb):
        return f"data/chunks/chunks.jsonl({len(ra)}줄)과 data/index/chunks.jsonl({len(rb)}줄)의 줄 수가 다릅니다. 새 청크를 색인으로 푼 뒤 다시 실행하세요"
    tolerated_only = 0
    for i, (x, y) in enumerate(zip(ra, rb), 1):
        diff = {k for k in set(x) | set(y) if x.get(k) != y.get(k)}
        if diff - set(TOLERATED):
            return f"{i}번째 줄에서 {sorted(diff - set(TOLERATED))} 칸이 다릅니다. 새 청크를 색인으로 푼 뒤 다시 실행하세요"
        tolerated_only += bool(diff)
    if notes is not None:
        notes.append(f"두 청크 파일은 {'/'.join(TOLERATED)} 칸만 {tolerated_only}줄 다릅니다(대조는 그 칸을 읽지 않으므로 그대로 진행)")
    return None


def build_command(root: Path, out: Path) -> list[str]:
    return [sys.executable, "-I", "-B", str(CHECKER), "--root", str(root), "--out", str(out)]


def key_numbers(summary: dict) -> dict:
    ov = summary.get("overlap") or {}
    return {k: summary.get(k, ov.get(k)) for k in KEYS}


def _body(c: dict) -> str:
    text, header = c["text"], c.get("header") or ""
    return (text[len(header):] if header and text.startswith(header) else text).lstrip("\n")


def overlap_classes(chunks: list[dict]) -> dict:
    """겹침이 있는 청크를 앞 청크 본문과 견줘 센다. tail = 앞 청크 본문 꼬리 그대로, label_plus_tail = 긴 표 행이라 첫 칸(라벨) + 꼬리(`ROW_TAIL_MAX` 규칙),
    other = 둘 다 아님. 대조 스크립트의 겹침 규칙은 tail만 맞다고 보므로 label_plus_tail이 `mismatch`와 `structure_problems`에 잡힌다(설계 동작)."""
    out = {"overlap_tail": 0, "overlap_label_plus_tail": 0, "overlap_other": 0}
    for prev, c in zip(chunks, chunks[1:]):
        n = c.get("overlap_chars") or 0
        if not n or prev["rule_seq"] != c["rule_seq"]:
            continue
        before, ov = _body(prev).rstrip(), _body(c)[:n].rstrip()
        if before.endswith(ov):
            out["overlap_tail"] += 1
        elif " | " in ov and before.endswith(ov.split(" | ", 1)[1].rstrip()) and ov.split(" | ", 1)[0] in before:
            out["overlap_label_plus_tail"] += 1
        else:
            out["overlap_other"] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="저장소 루트(기본: 이 파일의 저장소)")
    ap.add_argument("--out", type=Path, default=None, help="결과 폴더(기본: evals/results/table_number_source_check_<오늘>_recheck, 이미 있으면 거부)")
    a = ap.parse_args(argv)
    notes: list[str] = []
    problem = chunk_files_problem(a.root, notes)
    if problem:
        print("멈춤:", problem)
        return 2
    for n in notes:
        print("참고:", n)
    out = a.out or a.root / "evals" / "results" / f"table_number_source_check_{date.today():%Y%m%d}_recheck"
    if out.exists() and any(out.iterdir()):
        print(f"멈춤: 결과 폴더가 이미 있습니다(덮어쓰지 않음): {out}")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run(build_command(a.root, out), cwd=a.root).returncode
    if rc != 0:
        print(f"대조 스크립트가 종료 코드 {rc}로 끝났습니다")
        return rc
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    nums = {**key_numbers(summary), **overlap_classes(_rows(a.root / "data" / "chunks" / "chunks.jsonl"))}
    print(json.dumps(nums, ensure_ascii=False))
    (out / "recheck_key_numbers.json").write_text(json.dumps(nums, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
