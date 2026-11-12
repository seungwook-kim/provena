# pytest가 기준 미달에 실제로 실패하는 출력 (main 4c8d8bc, 2026-11-13)

CI의 두 번째 단계 `python evals/ci_compare.py`는 저장된 최종 점수가 기준 파일(`evals/ci_baseline.json`)보다 낮으면 종료 코드 1로 끝난다. 같은 비교를 pytest가 지키는지, 기준값만 올렸을 때 실제로 FAILED로 끝나는지 확인했다(키·네트워크·LLM 없음, 비용 0원).

- 커밋: `4c8d8bc2c43eee29814033267803c1f526bd00d3`(별도 clone 사본에서 실행, 작업 폴더는 건드리지 않음)
- 시험: `python -m pytest tests/test_ci_compare.py -q` 중 `test_committed_final_results_pass_against_the_committed_baseline`(`tests/test_ci_compare.py` 109~112줄)
- 바꾼 것: `evals/ci_baseline.json`의 `arms.single.cited_correct_rate` 한 값만 0.996에서 0.999로 올렸다. 저장된 결과 값은 0.996이므로 "결과가 기준보다 낮다"는 상황이 된다. 소스 코드와 결과 파일은 바꾸지 않았다.

| 단계 | 파일 | 결과 |
|---|---|---|
| 0. 바꾸기 전 | `0_before_pass.txt`, `0_before_pass.exitcode.txt` | 11 passed, 종료 코드 0 |
| 1. 기준값만 올린 diff | `1_diff.patch`, `1_status_mutated.txt` | 변경 파일은 `evals/ci_baseline.json` 하나 |
| 2. 올린 뒤 | `2_after_mutation_FAILED.txt`, `2_after_mutation_FAILED.exitcode.txt` | **1 failed, 10 passed, 종료 코드 1.** 출력에 `single 정답 근거 인용률 0.996 < 기준 0.999`와 `FAILED tests/test_ci_compare.py::test_committed_final_results_pass_against_the_committed_baseline` |
| 3. 되돌린 뒤 작업 트리 | `3_status_after_revert.txt` | 비어 있음(변경 없음) |
| 4. 되돌린 뒤 | `4_after_revert_pass.txt`, `4_after_revert_pass.exitcode.txt` | 11 passed, 종료 코드 0 |

되돌리기는 올리기 전에 따로 복사해 둔 원본 파일을 덮어쓰는 방식이었다.

이 출력은 pytest 안에서 기준 비교가 실패하는 것을 보인다. `ci_compare.py`를 직접 실행했을 때의 종료 코드 1은 `evals/results/ci_compare_fail_demo/`에 있다. 실제 GitHub Actions에서 실패가 기록된 것은 아니다(Actions는 실행되지 않았다, `EVAL_REPORT.md` 8장).
