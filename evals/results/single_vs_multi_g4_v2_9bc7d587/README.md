# 단일 그래프 대 멀티 구성 비교 (체크포인트 ③, 같은 문항 1회)

## 무엇을 쟀나

체크포인트 ③ 요청("현재 구성(/chat은 단일 그래프)과 멀티 구성의 차이를 같은 문항으로 한 번 재서 원시 결과")에 따라 그래프 구조 하나만 바꿔 동결 v2 50건을 1회씩 쟀다. 사전 등록 초안은 이 폴더의 `PREREGISTER_rows.md`(초안 번호 62.80, 측정 전 2026-11-17 09:40 작성)이다.

- 운영 판에서 바꿀 수 없는 이유: 서비스(`/chat`)에는 멀티를 고르는 환경 변수나 요청 칸이 없다. `backend/main.py`의 `build_question_graph`는 `build_graph`(단일)만 부르고, `build_multi_graph`는 측정 실행기만 부른다. 그래서 운영 판 `provena-api-00181-zub`의 이미지와 같은 커밋 `9bc7d587`의 코드(스냅숏)를 측정 실행기로 로컬에서 돌렸다.
- 갈래: 단일 그래프(`build_graph`) 대 Supervisor 멀티 그래프(`build_multi_graph`, 코드 라우팅). 같은 검색기, 같은 모델 객체, 같은 인자를 두 갈래에 넘기고 문항마다 순서를 바꿔 번갈아 돌렸다(짝수 번째 단일 먼저, 홀수 번째 멀티 먼저).
- 설정: 서비스가 앱 시작 때 채우는 서비스 설정 61.51(`backend/graph/service_profile.py`의 `SERVICE_ENV`, 68개 변수)을 같은 함수(`apply_service_profile`)로 채운 뒤, 61.51 측정 인자(`MEASURED_ARGS`)를 그대로 주었다. 검색은 운영 DB 색인(`--store pg`)을 읽기만 했다. 질문 번역 저장(`PgStore.put_translation`, INSERT)은 측정 쪽에서 막았다(막힌 호출 3회, 그 3개 검색어는 번역을 새로 받아 쓰고 저장하지 않았다).
- 모델: 로컬 Claude CLI의 `claude-haiku-5-5`(운영과 같은 모델, API 키는 쓰지 않음). 운영은 Anthropic API를 부르므로 응답 시간은 운영과 비교하지 않는다(CLI 시작 시간이 섞인다).
- 시각: 2026-11-17 09:47~10:17 KST. 09:45의 첫 시도는 단일 1번 문항에서 Voyage 임베딩 연결 시간 초과로 실행기가 멈춰 버리고 처음부터 다시 돌렸다. 이 폴더의 값은 두 번째 시도 전체다.
- 비용: LLM 청구 비용 0달러(로컬 CLI 구독). CLI가 보고한 API 환산값은 단일 대 멀티 1.044달러(그래프 호출 집계 단일 0.4041, 멀티 0.4045달러), 합동 검토 0.103달러이다. Voyage 질의 임베딩은 별도이다.

## 결과: 정책 질문 경로(v2 50건 x 1회)
문항별 짝(관련 문항, 정답 근거 인용률): 멀티 높음 0, 단일 높음 1, 같음 24. 결과 종류와 인용 청크 목록이 두 갈래에서 모두 같은 문항 46/50.

| 지표 | 단일 | 멀티 | 멀티 - 단일 |
|---|---|---|---|
| 인용 정확도 | 0.960 | 0.940 | -0.020 |
| 정답 근거 인용률 | 0.960 | 0.947 | -0.013 |
| 오답 근거 | 0.040 | 0.080 | 0.040 |
| 과잉 거절 | 0.000 | 0.000 | 0.000 |
| 올바른 거절 | 1.000 | 1.000 | 0.000 |
| 환각 위험 | 0.000 | 0.000 | 0.000 |
| p95(초, 로컬 CLI) | 37.345 | 37.449 | 0.104 |
| 비용 합(달러, CLI 보고 환산값) | 0.4041 | 0.4045 | 0.0005 |
| 문항당 LLM 호출 평균 | 14.72 | 14.82 | 0.10 |
| 오류 행 | 0 | 0 | |

멀티 갈래의 문항별 에이전트 경로(`agent_trace`) 분포: `retriever>writer>verifier` 25건, `retriever` 20건, `(없음)` 4건, `retriever>retriever` 1건.

| 문항 | 종류 | 단일 결과 | 멀티 결과 | 단일 정답 근거 | 멀티 정답 근거 | 단일 인용 정확도 | 멀티 인용 정확도 | LLM 호출 단일 / 멀티 | 멀티 에이전트 경로 | 같음 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 21 | retriever>writer>verifier | 예 |
| 2 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 17 | retriever>writer>verifier | 아니오 |
| 3 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 21 | retriever>writer>verifier | 예 |
| 4 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 21 | retriever>writer>verifier | 예 |
| 5 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 23 | retriever>writer>verifier | 예 |
| 6 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 21 | retriever>writer>verifier | 예 |
| 7 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 8 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 15 | retriever>writer>verifier | 예 |
| 9 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 23 | retriever>writer>verifier | 예 |
| 10 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 23 | retriever>writer>verifier | 예 |
| 11 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 15 / 17 | retriever>writer>verifier | 예 |
| 12 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 13 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 21 | retriever>writer>verifier | 예 |
| 14 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 15 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 16 | 비관련 | refuse | refuse | - | - | - | - | 9 / 4 |  | 예 |
| 17 | 비관련 | refuse | refuse | - | - | - | - | 4 / 4 |  | 예 |
| 18 | 비관련 | refuse | refuse | - | - | - | - | 4 / 4 |  | 예 |
| 19 | 비관련 | refuse | refuse | - | - | - | - | 4 / 4 |  | 예 |
| 20 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 21 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 22 | 비관련 | refuse | refuse | - | - | - | - | 15 / 14 | retriever | 예 |
| 23 | 비관련 | clarify | clarify | - | - | - | - | 4 / 4 | retriever | 예 |
| 24 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 25 | 비관련 | clarify | clarify | - | - | - | - | 4 / 4 | retriever | 예 |
| 26 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 27 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 28 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 29 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 30 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 31 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 21 | retriever>writer>verifier | 예 |
| 32 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 33 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 15 | retriever>writer>verifier | 아니오 |
| 34 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 17 / 17 | retriever>writer>verifier | 예 |
| 35 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 23 | retriever>writer>verifier | 예 |
| 36 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 21 | retriever>writer>verifier | 예 |
| 37 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 21 / 23 | retriever>writer>verifier | 예 |
| 38 | 관련 | answer | answer | 0.000 | 0.000 | 0.000 | 0.000 | 23 / 23 | retriever>writer>verifier | 예 |
| 39 | 관련 | answer | answer | 1.000 | 0.667 | 1.000 | 0.500 | 23 / 23 | retriever>writer>verifier | 아니오 |
| 40 | 관련 | answer | answer | 1.000 | 1.000 | 1.000 | 1.000 | 23 / 21 | retriever>writer>verifier | 아니오 |
| 41 | 비관련 | refuse | refuse | - | - | - | - | 9 / 11 | retriever | 예 |
| 42 | 비관련 | refuse | refuse | - | - | - | - | 4 / 23 | retriever>retriever | 예 |
| 43 | 비관련 | refuse | refuse | - | - | - | - | 9 / 11 | retriever | 예 |
| 44 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 45 | 비관련 | refuse | refuse | - | - | - | - | 11 / 9 | retriever | 예 |
| 46 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 47 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 48 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 49 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |
| 50 | 비관련 | refuse | refuse | - | - | - | - | 11 / 11 | retriever | 예 |

판정(사전 등록 기대와 대조): 정답 근거 인용률 차이 -0.013은 기대("0.02 안")와 맞다. 인용 정확도 차이 -0.020은 경계값으로, "0.02 안"을 0.02 미만으로 읽으면 맞지 않는다. 실행기가 두 갈래에서 달라졌다고 표시한 문항은 7개(`compare.json`의 `changed_items`)이다: 인용 목록이 달라진 관련 문항 2, 33, 39, 40번, 인용 순서만 다른 36번, 재시도 횟수만 다른 비관련 16, 42번이다. 정답 근거 인용률이 달라진 문항은 39번 하나(단일 3/3, 멀티 2/3)이다. 문항당 LLM 호출 수 차이는 0.10회로 기대("1회 안")와 맞다. 결과 종류(답·거절·되묻기)가 달라진 문항은 없다. 이 1회 비교로는 멀티 구성이 단일보다 낫다고도, 못하다고도 말할 수 없다(문항 하나의 흔들림이 0.02~0.04이다).

멀티 갈래의 문항별 에이전트 경로: 답한 관련 25건은 모두 `retriever > writer > verifier`, 비관련 문항은 검색 뒤 거절이 20건(`retriever`), 검색 없이 Supervisor가 바로 닫은 문항 4건(16~19번, 경로 없음), 재검색 1건(42번, `retriever > retriever`)이다. 문항별 Supervisor 결정 기록은 `items.json`의 `multi_supervisor_log`와 `multi/rows.jsonl`의 `supervisor_log`에 있다.

## 결과: 합동 검토 경로(팀 에이전트 4개 대 에이전트 하나, `evals/dataset_review_v1_gold.jsonl` 10건 x 1회)

같은 모델·같은 검색기로 `evals.agent.exp_review_v1`을 돌려(2026-11-17 09:46~09:53 KST) 문항마다 돈 팀과 노드를 남겼다. 정답 쟁점은 조원 2명이 확인한 확정본이다. team 갈래는 합동 검토 Supervisor(LLM 1회)가 되물을지 정하고, 되묻지 않으면 팀 에이전트 4개(security, infra, itops, finance)가 팀마다 한 번 검색하고 쟁점을 낸다. single 갈래는 같은 검색 4번을 차례로 하고 쟁점 호출 1번으로 네 관점을 한꺼번에 검토한다.
| 지표 | 팀 에이전트 4개(team) | 에이전트 하나(single) |
|---|---|---|
| 정답 쟁점 누락률 | 0.649 | 0.568 |
| 맞힌 정답 쟁점 수 | 13.000 | 16.000 |
| 정답 쟁점 수 | 37.000 | 37.000 |
| 쟁점 행 합 | 84.000 | 90.000 |
| 되물어야 할 문항 중 되물은 비율 | 1.000 | 0.500 |
| 그 밖의 문항 중 되물은 비율 | 0.125 | 0.000 |
| 근거 섹션 포함률 | 1.000 | 1.000 |
| 검토하지 못한 팀 자리 | 0.000 | 0.000 |
| 승인 전 저장된 쟁점표 | 0.000 | - |
| 문항당 LLM 호출 | 3.800 | 1.000 |
| 평균 시간(초, 로컬 CLI) | 15.573 | 28.670 |
| 비용 합(달러, CLI 보고 환산값) | 0.0505 | 0.0527 |
| 오류 | 0.000 | 0.000 |

| 문항 | 종류 | team 결과 | team에서 돈 팀(검토 상태) | team LLM 호출 / 검색 | team 쟁점 행 | single 결과 | single LLM 호출 / 검색 | single 쟁점 행 |
|---|---|---|---|---|---|---|---|---|
| 1 | full | clarify | (팀 호출 없음, Supervisor가 되물음) | 1 / 0 | 0 | pending_approval | 1 / 4 | 12 |
| 2 | full | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 18 | pending_approval | 1 / 4 | 13 |
| 3 | full | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 12 | pending_approval | 1 / 4 | 9 |
| 4 | full | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 15 | pending_approval | 1 / 4 | 12 |
| 5 | partial | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 12 | pending_approval | 1 / 4 | 9 |
| 6 | partial | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 14 | pending_approval | 1 / 4 | 9 |
| 7 | partial | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 7 | pending_approval | 1 / 4 | 8 |
| 8 | clarify | clarify | (팀 호출 없음, Supervisor가 되물음) | 1 / 0 | 0 | pending_approval | 1 / 4 | 12 |
| 9 | clarify | clarify | (팀 호출 없음, Supervisor가 되물음) | 1 / 0 | 0 | clarify | 1 / 4 | 0 |
| 10 | low_issue | pending_approval | finance:reviewed, infra:reviewed, itops:reviewed, security:reviewed | 5 / 4 | 6 | pending_approval | 1 / 4 | 6 |

판정(사전 등록 기대와 대조): 되물을 값이 빠진 문항(8, 9번)에서 team 갈래는 둘 다 되물었고 팀 4개를 부르지 않았다. 나머지 8건 중 7건은 팀 4개가 모두 검토(`reviewed`)했고, 1번(종류 full)에서는 Supervisor가 되물어 팀을 부르지 않았다. 따라서 "그 밖의 문항은 팀 4개가 돈다"는 1번에서 맞지 않는다. single 갈래는 9번에서만 되물었다. 정답 쟁점 누락률은 team 0.649, single 0.568로 이 1회에서는 single이 낮지만, team은 1번에서 쟁점표를 내지 않았으므로 그 몫이 누락으로 들어 있다.

## 원자료

- `single/rows.jsonl`, `multi/rows.jsonl`: 문항별 원시 행(질문, 결과, 답, 인용 청크, 정답 위치 대조, LLM 호출 기록, 멀티의 `agent_trace`·`supervisor_log`).
- `single/summary.json`, `multi/summary.json`, `compare.json`: 실행기가 낸 지표와 달라진 문항 목록(`changed_items`).
- `items.json`: 이 README의 문항별 표를 결과 행에서 다시 계산한 값.
- `review_team_vs_single/`: 합동 검토 두 갈래의 원시 행(`team/rows.jsonl`의 `team_status`, `retrieval_calls`), 지표(`compare.json`), 문항별 경로 표(`route.json`).
- `run_meta.json`: 실행 조건(커밋, 인자, 서비스 설정의 실제 값, 막은 번역 저장 횟수, CLI 환산 비용).

## 한계

- 운영 판(Cloud Run)의 값이 아니라 같은 커밋 코드의 로컬 실행기 값이다. 서비스 경로에서 멀티를 고를 방법이 없어서이다. 운영에만 있는 경로(`/chat` 스트림 처리, 답 저장소, 체크포인트 저장)는 들어 있지 않다.
- 각 1회다. 결과 행의 모델 응답은 같은 입력에서도 달라진다.
