# D8 로컬 pytest 출력 (2026-11-11)

이 폴더는 체크포인트 D8의 "pytest 실행 기록(CI 실행 기록 또는 로컬 pytest 출력)" 가운데 **로컬 pytest 출력**입니다. GitHub Actions 실행 기록이 아닙니다. 저장소 조직의 결제 한도 문제로 Actions 실행이 시작되지 않아(`EVAL_REPORT.md` 8장), 체크포인트가 허용한 로컬 출력으로 남깁니다.

## 실행 조건

| 항목 | 값 |
|---|---|
| 커밋 | `c5ff52edde4821effd2243308f48f67a8097ad2d` (origin/main, 새 clone, 작업 브랜치 `d8-pytest-record`, 코드 변경 없음) |
| 실행 시각 | 2026-11-11 09:38 ~ 09:44 (+09:00) |
| 환경 | Windows, Python 3.13.15, pytest 9.2.0. CI는 Ubuntu Python 3.12이므로 환경이 다름 |
| 환경 변수 | `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`, `LANGFUSE_*`를 이 프로세스에서 지우고 실행. 키, 네트워크, 운영 주소를 쓰지 않음 |
| 가린 것 | 개인 경로는 `<HOME>`으로 바꿈. 비밀값은 출력에 없음 |

## 결과

| 파일 | 명령 | 결과 | 종료 코드 |
|---|---|---|---|
| `pytest_full.txt` | `python -m pytest -q -p no:cacheprovider` (CI의 `python -m pytest -q`와 같은 시험 전체) | 3,158건 통과, 0건 실패, 101건 건너뜀, 1건 제외(`demo_replay` 표시, `pytest.ini`가 기본 실행에서 뺌). 6분 41초 | 0 |
| `pytest_ci_regression.txt` | `python -m pytest tests/test_ci_compare.py tests/test_ci_workflows.py -v` | 19건 통과, 0건 실패, 0.68초 | 0 |
| `ci_compare_run.txt` | `python evals/ci_compare.py` (`.github/workflows/ci.yml`의 CI 점수 비교 단계와 같은 명령) | 단일·멀티 14개 지표 모두 통과 | 0 |
| `ci_compare_run_module.txt` | `python -m evals.ci_compare` (같은 도구를 모듈로 실행) | 위와 같은 결과 | 0 |

`pytest_ci_regression.txt`에는 기준 미달이면 실패하는 것을 확인하는 시험이 들어 있습니다: `test_fails_below_the_spec_floor`(통과선 미달), `test_fails_when_a_metric_drops_below_the_baseline_even_above_the_floor`(기준값보다 낮아짐), `test_fails_when_a_lower_is_better_metric_rises`, `test_fails_when_p95_exceeds_the_spec_ceiling`. 커밋된 최종 결과가 커밋된 기준값을 통과하는지 보는 `test_committed_final_results_pass_against_the_committed_baseline`도 통과했습니다. 이 시험들은 "미달이면 실패하도록 작성된 시험이 통과함"을 보이며, 실제 Actions에서 실패가 기록된 것은 아닙니다.

## 한계

- 시험 전체의 건너뜀 101건은 시험 코드의 건너뜀 표시에 따른 것이며, 사유를 이번에 따로 분석하지 않았습니다.
- 이 출력은 로컬 실행이며 Actions 실행 기록이 아닙니다.
