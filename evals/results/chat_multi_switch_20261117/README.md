# /chat 멀티 그래프 전환의 0원 검증 기록 (2026-11-17)

2026-11-17 팀장 지시로 서비스 `/chat`이 Supervisor 멀티 그래프를 돌리도록 스위치 `QUESTION_GRAPH_MODE`를 더하고 서비스 값을 `multi`로 두었다. 이 폴더는 전환 전 기능 대조(`PARITY.md`), 유료 재측정 전 기대값과 멈춤 규칙(`PREREGISTER.md`), 그리고 키 없이 돌린 검증 결과이다.

- 코드: main `43adf3ed` 위의 커밋 전 작업 트리. 같은 시각 다른 작업(판정 대기 지연 수정 `build.py`·`answer_fixes.py`, CI·문서 일부)의 변경도 작업 트리에 있는 상태에서 돌렸다. 결과 파일의 `commit` 칸은 HEAD 값이다.
- 비용: 0원. LLM·Voyage·운영 DB 호출 없음. 배포 없음.
- Postgres: CI와 같은 이미지 `pgvector/pgvector:pg16`을 로컬 임시 컨테이너로 띄우고(접속 정보는 CI 파일과 같은 시험용 값, 포트만 다름) 끝난 뒤 지웠다.

## 실행한 명령과 결과

| 단계 | 명령 | 종료 코드 | 결과 |
|---|---|---|---|
| 색인 풀기 | `python -m backend.rag.ingest.snapshot unpack-index` | 0 | 청크 23,095개, meta.json sha256 일치 |
| 현재 코드 0원 평가(멀티 경로) | `python evals/ci_current_eval.py --out evals/results/chat_multi_switch_20261117/ci_current_result.json --require-v2` | 0 | 서비스 설정을 채워 `build_question_graph`가 멀티 그래프를 만든 상태로 재생. 데모 질문 9개: 인용 답 7/7, 거절 2/2. v2 50건: 관련 25건 중 인용 답 24, 비관련 25건 중 거절 24(되묻기 1), 녹화에 없는 요청 0, 발췌형 대체 답 0. 추론 답 경로와 빠른 답 경로 모두 같은 값 |
| 평가 점수 비교 | `python evals/ci_compare.py --current evals/results/chat_multi_switch_20261117/ci_current_result.json` | 0 | 결과: 통과. 4개 지표가 두 경로 모두 기준값(`evals/ci_baseline.json`, 단일 경로로 만든 값)과 같다 |
| 키 없는 데모 녹화 대조 | `python -m pytest -q -m demo_replay -rs` | 0 | 6 통과, 4,918 선택 제외, 건너뜀 0 (`demo_replay.log.txt`) |
| 전체 시험 | `python -m pytest -q` | 1 | 4,811 통과, 1 실패, 106 건너뜀. 실패 1건은 `test_router_call_is_in_the_llm_trace_under_its_own_node_name`의 기대값으로, 분류 호출이 이번 수정으로 단일 그래프와 같은 노드 이름(`classify/classify`)으로 기록되어 옛 이름(`supervisor/classify`)과 달랐다. 기대값을 고친 뒤 그 파일과 서비스 설정·문서 시험 등 관련 파일을 다시 돌려 1,401 통과(건너뜀 5) |

로그는 `.log.txt` 이름으로 남겼다(`.gitignore`의 `*.log` 규칙). 개인 경로·키가 없는지 확인했고 gitleaks(`dir --redact`)로 바꾼 파일과 이 폴더를 검사해 누출 0건이다.

## 키 없는 데모(녹화 재생)를 멀티로 두는 이유

멀티 그래프는 단일 그래프의 노드를 같은 순서로 불러 같은 프롬프트를 보내고, 코드 라우팅은 LLM 호출을 더하지 않는다. 녹화 열쇠는 요청 내용이라 두 경로의 열쇠가 같다. 위 재생에서 녹화에 없는 요청이 0건이고 결과가 기준값과 같으므로, 데모 모드도 서비스와 같이 멀티로 둔다(따로 단일로 고정하지 않는다).

## 읽는 법

- 50건 재생은 녹화 당시의 모델 응답을 다시 쓰는 회귀 검사이다. 멀티 경로가 단일 경로와 같은 요청을 같은 순서로 보낸다는 확인이며, 모델 품질을 새로 잰 값이 아니다.
- 품질·응답 시간은 운영 판 유료 재측정(v2 50건 3회, holdout_v2 20건 3회)으로 확인한다. 기대 범위와 멈춤 규칙은 `PREREGISTER.md`이다.
