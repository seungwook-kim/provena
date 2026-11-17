# 50건 재생 CI 단계의 로컬 실행 기록 (2026-11-17)

체크포인트 3조 코멘트 ④ "50건 재생의 실제 실행 기록이 없습니다"에 대한 기록이다. `.github/workflows/ci.yml`의 두 단계(현재 코드 0원 평가, 평가 점수 비교)와 같은 명령을 로컬에서 키 없이 돌리고 출력과 종료 코드를 그대로 남겼다. GitHub Actions는 무료 한도 소진으로 11/9 이후 멈춰 있어 로컬 실행 출력이 증거다.

- 실행 시각: 2026-11-17 09:53:26 ~ 09:55:30 KST (결과 파일 `finished_at` 2026-11-17T09:55:29+09:00)
- 코드: main `e53713d8`. 작업 트리에는 커밋 전 변경(같은 날 진행 중인 다른 수정 포함)이 있는 상태에서 돌렸다. 결과 파일의 `commit` 칸은 HEAD 값이다.
- 비용: 0원. LLM·Voyage·운영 DB 호출 없음(`ci_current_eval.py`가 프로세스에서 키를 지우고 녹화 재생으로 돈다).
- Postgres: CI의 서비스 컨테이너와 같은 이미지 `pgvector/pgvector:pg16`을 로컬 임시 컨테이너로 띄우고(접속 정보는 CI 파일과 같은 시험용 값, 포트만 55432), 끝난 뒤 지웠다. 도구가 그 안에 임시 DB를 만들어 색인 스냅샷을 적재하고 끝나면 지운다.

## 실행한 명령

```
PROVENA_D5_PG_URL=postgresql://app:<시험용>@127.0.0.1:55432/postgres python evals/ci_current_eval.py --out evals/results/ci_replay_local_20261117/ci_current_result.json --require-v2
python evals/ci_compare.py --current evals/results/ci_replay_local_20261117/ci_current_result.json
```

## 결과

| 단계 | 종료 코드 | 출력 파일 | 결과 |
|---|---|---|---|
| 현재 코드 0원 평가(`--require-v2`) | 0 | `ci_current_eval.log.txt`, `ci_current_result.json`, `ci_current_eval.exitcode.txt` | 데모 질문 9개: 인용 답 7/7, 거절 2/2, 녹화에 없는 요청 0, 발췌형 대체 답 0. 평가셋 v2 50건: 관련 25건 중 인용 답 24, 비관련 25건 중 거절 24(되묻기 1), 녹화에 없는 요청 0, 발췌형 대체 답 0. 추론 답 경로와 빠른 답 경로 모두 같은 값 |
| 평가 점수 비교 | 0 | `ci_compare.log.txt`, `ci_compare.exitcode.txt` | 결과: 통과. 50건 재생 4개 지표(관련 질문 중 인용 답 24, 비관련 질문 중 거절 24, 녹화에 없는 요청 0, 발췌형 대체 답 0)가 두 경로 모두 기준값(`evals/ci_baseline.json`)과 같음. 운영 최근 측정 `provena-api-00172-rex` 비교도 모든 지표 통과 |

로그 파일은 `.gitignore`의 `*.log` 규칙 때문에 같은 내용을 `.log.txt` 이름으로 복사해 커밋했다(내용 변경 없음, 개인 경로·키 없음 확인).

## 읽는 법

- 50건 재생은 녹화(`evals/ci_replay_v2/`)를 만든 시점의 모델 응답을 다시 쓰는 회귀 검사다. 프롬프트·검색·입력이 바뀌면 "녹화에 없는 요청"이 0보다 커져 실패한다. 모델 품질을 새로 잰 값이 아니다.
- 관련 24/25, 비관련 24/25는 녹화 당시 응답이 그대로 재생된 값이고 기준값과 같다.
