# CI의 두 가지 비교가 현재 코드의 회귀에서 실패하는 출력 (main `b541e97` 기준, 2026-11-13)

체크포인트 3조 코멘트(④)는 "CI 비교가 옛 측정 결과 파일만 읽어 현재 코드의 회귀를 못 잡는다"고 지적했다. 이에 두 가지를 바꾸었고, 일부러 깨뜨린 저장소 사본에서 두 비교가 실제로 실패하는 출력을 남겼다(키, 네트워크, LLM 호출 없음, 비용 0원). 저장소 작업 트리는 건드리지 않고 임시 폴더에 복사한 사본에서 실행했다. 실제 GitHub Actions에서 실패가 기록된 것은 아니다(Actions 무료 한도 소진으로 11/9 이후 멈춰 있고 로컬 실행 출력이 증거다, `EVAL_REPORT.md` 8장).

## 바꾼 것

| 구분 | 이전 | 이후 |
|---|---|---|
| (a) 현재 코드의 검색·그래프 변화 | `python -m pytest -q`는 `pytest.ini`의 `-m "not demo_replay"` 때문에 키 없는 데모의 녹화 대조(`tests/test_demo_replay_fresh.py`)를 건너뛰었다 | `.github/workflows/ci.yml`에 `python -m pytest -q -m demo_replay` 단계를 추가했다. Postgres(pgvector) 서비스를 곁에 띄우고, 시험이 건너뛰어지면 단계가 실패하도록 했다 |
| (b) 점수 비교의 입력 | `evals/ci_compare.py`가 고정된 이전 측정 폴더 `agent_v2_q_d6151_r{1,2,3}_bo2sda2_api`만 읽었다 | 같은 비교에 더해 `evals/results/deploy_latency_provena-api-*/` 중 평가셋 해시가 동결 해시와 같고 측정 종료 시각이 가장 늦은 폴더(현재 `provena-api-00047-wjn`)를 자동으로 골라 `evals/ci_baseline.json`의 `operating` 기준과 통과선에 견준다 |

(b)의 기준값은 `provena-api-00047-wjn`의 v2 50건 3회 평균이다: 정답 근거 인용률 0.942, 인용 정확도 0.950, 비관련 거절 1.000, 오답 근거 0.067, 과잉 거절 0, 회차별 p95 평균 8.510초. 이전 기준(평가 실행기로 잰 단일 0.996, 1.000)보다 낮은 값인데, 평가 실행기와 운영 배포 경로가 다른 경로이기 때문이다. 환각 위험 지표는 운영 측정에 없어 이 비교에서 뺐다.

## (a) 녹화 대조: 일부러 깨뜨린 사본의 결과

현재 코드(깨뜨리기 전)의 `python -m pytest -q -m demo_replay` 결과는 `a0_current_code_demo_replay_pass.txt`(2 passed)이다.

| 단계 | 사본에서 바꾼 것 | 파일 | 결과 |
|---|---|---|---|
| 1 | `backend/prompts/question.py`의 답 시스템 프롬프트 한 문장에서 "작성기다"를 "작성자다"로 | `a1_prompt_default_pytest_still_passes.txt` | 기본 실행(표지 없이)은 `2 passed, 2 deselected`, 종료 코드 0. 녹화 대조 2건은 선택되지 않아 회귀를 못 본다(이전 CI의 사각) |
| 2 | 같은 변경 | `a2_prompt_demo_replay_FAILED.txt` | `-m demo_replay`는 `1 failed`, 종료 코드 1. "녹화에 없는 요청이 있는 질문 8/9개 (역할: answer_fast)" |
| 3 | `backend/rag/retrieve/search.py`의 금액 구간 조회 기본값 `SEARCH_RANGE_N` 3을 2로 | `a3_search_range_default_pytest_still_passes.txt` | 기본 실행은 `2 passed, 2 deselected`, 종료 코드 0 |
| 4 | 같은 변경 | `a4_search_range_demo_replay_FAILED.txt` | `-m demo_replay`는 `1 failed`, 종료 코드 1. "녹화에 없는 요청이 있는 질문 3/9개 (역할: answer_fast, judge)" |
| 5 | 두 변경을 되돌림 | `a5_reverted_demo_replay_pass.txt` | `2 passed`, 종료 코드 0 |

## (b) 점수 비교: 일부러 깨뜨린 사본의 결과

사본에 측정 종료 시각이 더 늦은 가짜 운영 측정 폴더 `deploy_latency_provena-api-00099-regress`를 만들었다(00047 폴더를 복사하고 인용 정확도 한 값만 0.95에서 0.90으로 낮춤). 0.90은 통과선 0.85보다 높아서 통과선만 보는 비교로는 잡히지 않고, 기준값(0.95)과 견주어야 잡힌다.

| 단계 | 실행 | 파일 | 결과 |
|---|---|---|---|
| 1 | 이전 `ci_compare.py`(main `b541e97` 그대로) | `b1_old_ci_compare_still_passes.txt` | `결과: 통과`, 종료 코드 0. 새 측정 폴더를 읽지 않으므로 회귀를 못 본다 |
| 2 | 새 `ci_compare.py` | `b2_new_ci_compare_FAILED.txt` | `결과: 실패`, 종료 코드 1. "운영 provena-api-00099-regress 인용 정확도 0.9 < 기준 0.95" |

단위 시험은 `tests/test_ci_compare.py`(최신 폴더 자동 선택, 옛 측정은 읽지 않음, 기준 미달, 통과선 초과, 해시와 문항 수가 다른 측정 제외)와 `tests/test_ci_workflows.py`(녹화 대조 단계, DB 서비스, 건너뜀 검사)에 있다.
