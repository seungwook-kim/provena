"""D5 이후 코드 변이 확인 (L-10, docs/GATES.md 18번~). 핵심 줄 하나를 깨뜨리고 지정한 시험이 실패하는지 본다. LLM·네트워크 없음.

사용: python -I tests/mutation_d5.py [번호 ...]   (저장소 루트에서. 번호를 안 주면 전부)
규칙: 변이마다 try/finally로 원본을 복구하고, 끝나면 변이 문자열이 파일에 남았는지 검사한다. `timeout`으로 감싸지 않는다(강제 종료는 finally를 건너뛴다).
pytest 파일 이름은 `tests/test_*.py`가 아니라서 pytest가 모으지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (번호, 파일, 원래 줄, 깨뜨린 줄, 확인할 시험 파일)
MUTATIONS = [
    (18, "backend/graph/decision/execute.py",
     'if table.status != "approved" or not (table.approved_by or "").strip():',
     "if False:",
     ["tests/test_decision_approval.py"]),
    (19, "backend/graph/multi.py",
     'if last == "writer":\n        return ("verifier",), "verifier"',
     'if last == "writer":\n        return ("end",), "end"',
     ["tests/test_multi_graph.py"]),
    (20, "backend/graph/multi.py",
     'if trace.count("retriever") <= max_research and view.get("retries", 0) <= max_research:',
     "if True:",
     ["tests/test_multi_graph.py"]),
    (21, "backend/graph/grounding.py",
     "if not all(_value_in_source(n, u, source) for n, u in pairs):",
     "if False:",
     ["tests/test_values_backed.py"]),
    (22, "backend/graph/grounding.py",
     'if period_covered is False:\n        return "period_covered=false"',
     'if False:\n        return "period_covered=false"',
     ["tests/test_question_graph.py", "tests/test_answer_fixes_graph.py", "tests/test_d7_fixes.py"]),
    (23, "backend/graph/grounding.py",
     "if len(drop) >= len(sentences):\n        return Pruned(False, reason=\"nothing_left\")",
     "if False:\n        return Pruned(False, reason=\"nothing_left\")",
     ["tests/test_question_graph.py", "tests/test_multi_graph.py"]),
    (24, "backend/graph/build.py",
     "if not chunks:  # 자료가 없으면 LLM에 묻지 않고 부족으로 본다",
     "if False:  # 자료가 없으면 LLM에 묻지 않고 부족으로 본다",
     ["tests/test_empty_evidence.py"]),
    (25, "backend/rag/retrieve/search.py",
     "for sub in lists[1:]:",
     "for sub in lists[2:]:",
     ["tests/test_uncited_and_drop_one.py"]),
    (26, "backend/graph/recall/digest.py",
     '"severity": "high" if high else "low",',
     '"severity": "high",',
     ["tests/test_digest_contract.py"]),
    (27, "backend/graph/recall/digest.py",
     'any(n.get("conclusion_changed") for n in ordered)',
     'all(n.get("conclusion_changed") for n in ordered)',
     ["tests/test_digest_contract.py"]),
    (28, "backend/graph/recall/impact.py",
     "answers_checked=len(seen_answers),",
     "answers_checked=0,",
     ["tests/test_impact_preview_contract.py"]),
    (29, "backend/graph/recall/impact.py",
     'lines += [""] + [f"> {n}" for n in report.notes] + ["", ATTRIBUTION]',
     'lines += [""] + [f"> {n}" for n in report.notes]',
     ["tests/test_impact_preview_contract.py"]),
    (30, "backend/graph/recall/impact.py",
     'old = {p["path"]: p["old"] for p in pages if p.get("old") is not None}',
     'old = {p["path"]: p["old"] for p in pages if p.get("old") is not None and p["path"].endswith("b.md")}',
     ["tests/test_impact_preview_contract.py"]),
    (31, "evals/retrieval/experiment_v1.py",
     'if self.name == "int8":  # I-013',
     'if False:  # I-013',
     ["tests/test_exp_int8_scores.py"]),
    (32, "backend/services/auth_store.py",
     '        if action == "approve":\n            if request.get("email_verification_required") and request.get("email_verified_at") is None:',
     '        if True:\n            if request.get("email_verification_required") and request.get("email_verified_at") is None:',
     ["tests/test_round_trip_app.py"]),
    (33, "backend/services/auth_store.py",
     '        if action == "approve":\n            if request.get("email_verification_required") and request.get("email_verified_at") is None:',
     '        if False:\n            if request.get("email_verification_required") and request.get("email_verified_at") is None:',
     ["tests/test_round_trip_app.py"]),
]


def run_tests(files: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in r.stdout.splitlines() if " passed" in ln or " failed" in ln or " error" in ln][-1:]
    return r.returncode, (tail[0] if tail else r.stdout[-200:])


def main(want: list[int]) -> int:
    bad = 0
    for num, rel, old, new, tests in MUTATIONS:
        if want and num not in want:
            continue
        path = ROOT / rel
        orig = path.read_bytes().decode("utf-8")
        if "\r\n" in orig:  # 윈도우 줄바꿈 파일은 여러 줄 문자열도 같은 줄바꿈으로 맞춘다
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        assert orig.count(old) == 1, (num, "원래 줄이 파일에 정확히 한 번 있어야 한다", orig.count(old))
        base_code, base = run_tests(tests)
        try:
            path.write_bytes(orig.replace(old, new).encode("utf-8"))
            code, tail = run_tests(tests)
        finally:
            path.write_bytes(orig.encode("utf-8"))
        assert path.read_bytes().decode("utf-8") == orig, (num, "원복 실패")
        ok = base_code == 0 and code != 0
        bad += 0 if ok else 1
        print(f"{num} {rel}: 변이 전 [{base}] / 변이 뒤 [{tail}] -> {'잡음' if ok else '못 잡음'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main([int(a) for a in sys.argv[1:]]))
