# 운영 합동 검토 측정 (dataset_review_v1_gold_draft.jsonl 10문항 x 3회, 팀 경로만)

- 대상: 리비전 provena-api-00037-2jt, 커밋 c5ff52e. 측정 시각 2026-11-11T11:41:56+09:00 ~ 2026-11-11T11:47:02+09:00
- 평가셋: dataset_review_v1_gold_draft.jsonl (sha256 d0d1537f2767), 정답 쟁점은 초안(`팀장 검토 초안, 판정자 확인 전`) 기준이다. 되묻기 표시도 판정자 확인 전이다.
- 방식: 문항마다 새 대화로 `POST /chat`을 한 건씩 보냈다(동시 요청 없음). 시간은 요청 전송부터 마지막 이벤트(`done` 또는 `approval_request`)까지 클라이언트 쪽 값이다.
- 단일 비교 갈래는 운영에 없어 재지 않았다. 로컬 사전 확인(62.36)은 참고용이고 공식 기록은 이 운영 값이다.
- 쟁점표 행 읽기: 관리자 계정으로 GET /approvals; 시험 건 반려: 함

## 경로별 런 수

| 경로 | 런 수 |
|---|---|
| other_route | 12 |
| review_clarify | 7 |
| review_table | 11 |

review_table = 쟁점표(승인 대기), review_clarify = Supervisor 되묻기, review_no_issues = 쟁점 없음, other_route = 합동 검토로 분류되지 않음(정책 답 등), error = 오류·타임아웃.

## 지표 (운영, 팀 경로)

| 지표 | 운영 | 로컬 사전 확인 62.36 팀 갈래(참고) |
|---|---|---|
| 되묻기율 (되물을 문항 6런 중 되물음) | 100.0% (6/6) | 100.0% |
| 잘못 되물음 (그 밖의 문항 중 되물음) | 4.2% | 0.0% |
| 정답 쟁점 누락률 | 77.5% | 64.9% |
| 정답 쟁점 찾음 (찾음/전체) | 25/111 | 39/111 |
| 판 날짜 일치율 | 100.0% | 100.0% |
| 과잉 행 비율(정답과 안 맞은 행) | 81.9% | 81.1% |
| 쟁점 행 수 | 177 | 265 |
| 근거 섹션·판 날짜 포함률 | 100.0% | 100.0% |
| 전체 시간 평균(초) | 9.999 | 14.100 |
| 전체 시간 p95(초) | 24.609 | 19.567 |
| 오류 런 | 0 | 0 |

정답 지표 상태: 계산함(초안 정답 기준: 팀장 검토 초안, 판정자 확인 전)

## 시간 (초, 경로별)

| 경로 | 런 수 | 평균 | p50 | p95 | 최대 |
|---|---|---|---|---|---|
| review_table | 11 | 9.865 | 9.489 | 12.967 | 12.967 |
| review_clarify | 7 | 3.772 | 3.829 | 4.124 | 4.124 |
| other_route | 12 | 13.754 | 8.881 | 24.687 | 24.687 |

## 비용

- 비용을 본 런 19/30 (응답의 done 19런, 서버 로그 0런). 본 비용 합 0.1829달러.
- 비용을 못 본 런 11건. 상한 추정(못 본 런마다 0.0075달러 가산) 0.2654달러.
- `done`이 있는 런(되묻기, 쟁점 없음)은 응답에서 비용을 본다. 쟁점표 런은 `approval_request`로 끝나 응답에 비용이 없고 서버 로그(`fill-cost`)로만 볼 수 있다. 로그의 `cost_usd`는 질문 번역 LLM을 뺀 그래프 합이다. 비용을 못 본 런은 합에 넣지 않았고 상한 추정은 그 런마다 EST_RUN_USD를 더한 값이다.

## 문항별 (회차 순서)

| 문항 | 종류 | 경로 | 쟁점 행 수 | 정답 찾음/전체 |
|---|---|---|---|---|
| 1 | full | review_table, review_table, review_table | 14, 15, 13 | 2, 2, 2 / 6 |
| 2 | full | review_table, review_table, review_table | 18, 18, 17 | 2, 2, 2 / 7 |
| 3 | full | review_clarify, review_table, review_table | ?, 15, 17 | ?, 2, 2 / 6 |
| 4 | full | review_table, review_table, review_table | 16, 17, 17 | 3, 3, 3 / 7 |
| 5 | partial | other_route, other_route, other_route | ?, ?, ? | ?, ?, ? / 2 |
| 6 | partial | other_route, other_route, other_route | ?, ?, ? | ?, ?, ? / 4 |
| 7 | partial | other_route, other_route, other_route | ?, ?, ? | ?, ?, ? / 3 |
| 8 | clarify | review_clarify, review_clarify, review_clarify | ?, ?, ? | - |
| 9 | clarify | review_clarify, review_clarify, review_clarify | ?, ?, ? | - |
| 10 | low_issue | other_route, other_route, other_route | ?, ?, ? | ?, ?, ? / 2 |

한계: 쟁점 문장은 비교하지 않고 팀과 근거 섹션만 맞춘다(`exp_review_v1` 모듈 설명의 한계 1~6과 같다). 모델 응답은 실행마다 달라 문항 10건에서 1~2건 차이는 우연일 수 있다.
