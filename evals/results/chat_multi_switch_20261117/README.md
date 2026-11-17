# /chat 멀티 그래프 전환의 0원 검증 기록 (2026-11-17)

2026-11-17 팀장 지시로 서비스 `/chat`이 Supervisor 멀티 그래프를 돌리도록 스위치 `QUESTION_GRAPH_MODE`를 더하고 서비스 값을 `multi`로 두었다. 이 폴더는 전환 전 기능 대조(`PARITY.md`), 유료 재측정 전 기대값과 멈춤 규칙(`PREREGISTER.md`), 그리고 키 없이 돌린 검증 결과이다.

- 코드: main `43adf3ed` 위의 커밋 전 작업 트리. 같은 시각 다른 작업(판정 대기 지연 수정 `build.py`·`answer_fixes.py`, CI·문서 일부)의 변경도 작업 트리에 있는 상태에서 돌렸다. 결과 파일의 `commit` 칸은 HEAD 값이다. 2026-11-17 오후에 같은 단계를 깨끗한 커밋 `c47ce921`(분리한 작업 트리, 커밋 전 변경 없음)에서 다시 돌렸다(아래 "깨끗한 커밋에서 다시 돌림").
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

## 깨끗한 커밋에서 다시 돌림 (c47ce921, 2026-11-17 15:42~16:11 KST)

seunguk의 커밋 `c47ce921`(PR #183의 head, 멀티 전환 `7a52ef87`과 출력 자리 요청 판정 `e822fb1e` 포함)을 분리한 작업 트리로 꺼내 위와 같은 단계를 돌렸다. 시작 전과 끝난 뒤 작업 트리의 커밋 전 변경은 0줄이다. 비용 0원, Postgres는 같은 방식의 로컬 임시 컨테이너. 로그는 `clean_c47ce921/`이다(로컬 경로는 가림).

| 단계 | 종료 코드 | 결과 |
|---|---|---|
| 색인 풀기 | 0 | 청크 23,095개, meta.json sha256 일치 |
| 현재 코드 0원 평가(`--require-v2`) | 0 | 두 경로 모두 데모 질문 9개 인용 답 7/7·거절 2/2, v2 50건 관련 25건 중 인용 답 24·비관련 25건 중 거절 24·녹화에 없는 요청 0·발췌형 대체 답 0 |
| 평가 점수 비교(`ci_compare.py --current`) | 0 | 통과 |
| 키 없는 데모 녹화 대조(`-m demo_replay`) | 0 | 6 통과, 건너뜀 0 |
| 전체 시험(`pytest -q`) | 1 | 4,827 통과, 1 실패, 124 건너뜀. 실패 1건은 `tests/test_team_failure_restart.py`의 `test_process_killed_while_retrying_continues_without_new_notice_or_rerunning_passed_teams[alone]`(프로세스를 강제로 끝낸 뒤 재개하는 시험) |
| 실패 시험 다시 돌림 | - | `c47ce921`에서 시험 파일 3번: 실패 2, 통과 1. 멀티 전환 전 main `1dfc3608`에서 같은 시험 3번: 3번 모두 같은 경우가 실패. 이번 PR의 코드 변경 전부터 이 로컬 환경에서 나는 실패이고 원인은 확인하지 못했다(`rerun_team_failure_restart*.log.txt`) |

변이 확인(코드를 한 곳 바꿔 시험이 잡는지 보고 되돌림, `docs/GATES.md` 변이 표 40~42):

| 번호 | 바꾼 곳 | 시험 | 원래 코드 | 바꾼 코드 |
|---|---|---|---|---|
| 40 | `backend/main.py` `build_question_graph`가 스위치와 관계없이 단일 그래프를 만들게 | `tests/test_chat_multi_switch.py` | 30 통과 | 1 실패 |
| 41 | `backend/graph/build.py` `two_split`이 항상 거짓 | `tests/test_split_vote_wait.py` | 19 통과 | 2 실패 |
| 42 | `backend/graph/untrusted.py` `_OutputRequest.search`의 판정 결과를 항상 없음으로 | `tests/test_output_request_1117.py` | 32 통과 | 3 실패 |

## 키 없는 데모(녹화 재생)를 멀티로 두는 이유

멀티 그래프는 단일 그래프의 노드를 같은 순서로 불러 같은 프롬프트를 보내고, 코드 라우팅은 LLM 호출을 더하지 않는다. 녹화 열쇠는 요청 내용이라 두 경로의 열쇠가 같다. 위 재생에서 녹화에 없는 요청이 0건이고 결과가 기준값과 같으므로, 데모 모드도 서비스와 같이 멀티로 둔다(따로 단일로 고정하지 않는다).

## 읽는 법

- 50건 재생은 녹화 당시의 모델 응답을 다시 쓰는 회귀 검사이다. 멀티 경로가 단일 경로와 같은 요청을 같은 순서로 보낸다는 확인이며, 모델 품질을 새로 잰 값이 아니다.
- 품질·응답 시간은 운영 판 유료 재측정(v2 50건 3회, holdout_v2 20건 3회)으로 확인한다. 기대 범위와 멈춤 규칙은 `PREREGISTER.md`이다.
