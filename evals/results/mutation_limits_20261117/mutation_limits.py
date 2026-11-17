"""새 상한 상수 변이 확인(2026-11-17). 상수 하나를 바꾸고 지정한 시험이 실패하는지 본다. LLM·네트워크 없음.

사용: python mutation_limits.py <저장소 루트> [번호 ...]
규칙은 tests/mutation_d5.py와 같다: 변이마다 try/finally로 원본을 복구하고, 원복을 바이트 단위로 확인한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()

# (번호, 파일, 원래 줄, 깨뜨린 줄, 확인할 시험 파일)
MUTATIONS = [
    ("L1", "backend/services/llm.py",
     "DEFAULT_LLM_MAX_TOKENS = 2500", "DEFAULT_LLM_MAX_TOKENS = 3000",
     ["tests/test_llm_max_tokens.py"]),
    ("L2", "backend/services/llm.py",
     'TASK_MAX_TOKENS: dict[str, int] = {"single": 4000}', 'TASK_MAX_TOKENS: dict[str, int] = {"single": 5000}',
     ["tests/test_llm_max_tokens.py"]),
    ("L3", "backend/api/daily_limit.py",
     "DEFAULT_DAILY_QUESTION_LIMIT = 50", "DEFAULT_DAILY_QUESTION_LIMIT = 60",
     ["tests/test_daily_limit.py"]),
    ("L4", "extras/mcp_skill/mcp_server/server.py",
     "DEFAULT_EXTERNAL_RATE_PER_MIN = 30", "DEFAULT_EXTERNAL_RATE_PER_MIN = 60",
     ["tests/test_mcp_external_rate.py"]),
    ("L5", "extras/mcp_skill/mcp_server/server.py",
     "DEFAULT_EXTERNAL_RATE_PER_DAY = 500", "DEFAULT_EXTERNAL_RATE_PER_DAY = 1000",
     ["tests/test_mcp_external_rate.py"]),
    ("L6", "extras/mcp_skill/mcp_server/server.py",
     '_rate_env("MCP_EXTERNAL_RATE_PER_DAY", DEFAULT_EXTERNAL_RATE_PER_DAY)', '_rate_env("MCP_EXTERNAL_RATE_PER_DAY", 0)',
     ["tests/test_mcp_external_rate.py"]),
    ("M2", "backend/graph/build.py",
     'merged = merge_chunks(state.get("chunks", []), found, limit=cap)', 'merged = merge_chunks([], found, limit=cap)',
     ["tests/test_question_graph.py::test_requery_keeps_first_search_chunks_so_their_citation_survives"]),
]


def run_tests(files: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in r.stdout.splitlines() if " passed" in ln or " failed" in ln or " error" in ln][-1:]
    return r.returncode, (tail[0] if tail else r.stdout[-200:])


def main(want: list[str]) -> int:
    bad = 0
    for num, rel, old, new, tests in MUTATIONS:
        if want and num not in want:
            continue
        path = ROOT / rel
        orig = path.read_bytes().decode("utf-8")
        if orig.count(old) != 1:
            print(f"{num} {rel}: 원래 줄이 {orig.count(old)}번 있어 변이하지 않음", flush=True)
            bad += 1
            continue
        base_code, base = run_tests(tests)
        try:
            path.write_bytes(orig.replace(old, new).encode("utf-8"))
            code, tail = run_tests(tests)
        finally:
            path.write_bytes(orig.encode("utf-8"))
        assert path.read_bytes().decode("utf-8") == orig, (num, "원복 실패")
        ok = base_code == 0 and code != 0
        bad += 0 if ok else 1
        print(f"{num} {rel}: `{old}` -> `{new}` / 변이 전 [{base}] / 변이 뒤 [{tail}] -> {'잡음' if ok else '못 잡음'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[2:]))
