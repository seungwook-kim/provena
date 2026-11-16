# 실패 유형 표 (실패 문항 11 / 문항 90)

- 입력: v2=evals/results/deploy_latency_provena-api-00172-rex, holdout=evals/results/deploy_latency_holdout_provena-api-00172-rex, holdout_v2=evals/results/deploy_latency_holdout_v2_provena-api-00172-rex, 문맥 evals/results/failure_types_provena-api-00172-rex/context.json
- 실패 문항은 틀린 회차가 2회 이상인 문항이고, 한 문항은 주 유형 하나에만 센다. 유형은 행의 값으로 나눈 추정이다.

| 유형 | 문항 수 | 문항 | 뜻 |
|---|---|---|---|
| 검색 실패 | 3 | v2 38, holdout 101, holdout_v2 515 | 놓친 정답 위치가 첫 검색 문맥에 없음 |
| 근거 선택 | 3 | v2 39, holdout 108, holdout_v2 507 | 정답 위치가 첫 검색 문맥에 다 있는데 답이 인용하지 않음 |
| 정답 밖 인용 | 5 | holdout_v2 504, holdout_v2 505, holdout_v2 511, holdout_v2 513, holdout_v2 517 | 정답 위치는 모두 인용하고 정답 밖 청크를 더 인용함 |
| 합계 | 11 | 실패 문항 수 11와 같음 | |

| 문항 | 주 유형 | 틀린 회차 | 회차별 |
|---|---|---|---|
| v2 38 | 검색 실패 | 3/3 | 검색 실패 / 검색 실패 / 검색 실패 |
| holdout 101 | 검색 실패 | 3/3 | 검색 실패 / 검색 실패 / 검색 실패 |
| holdout_v2 515 | 검색 실패 | 3/3 | 검색 실패 / 검색 실패 / 검색 실패 |
| v2 39 | 근거 선택 | 3/3 | 근거 선택 / 근거 선택 / 근거 선택 |
| holdout 108 | 근거 선택 | 3/3 | 근거 선택 / 근거 선택 / 근거 선택 |
| holdout_v2 507 | 근거 선택 | 3/3 | 근거 선택 / 근거 선택 / 근거 선택 |
| holdout_v2 504 | 정답 밖 인용 | 3/3 | 정답 밖 인용 / 정답 밖 인용 / 정답 밖 인용 |
| holdout_v2 505 | 정답 밖 인용 | 3/3 | 정답 밖 인용 / 정답 밖 인용 / 정답 밖 인용 |
| holdout_v2 511 | 정답 밖 인용 | 3/3 | 정답 밖 인용 / 정답 밖 인용 / 정답 밖 인용 |
| holdout_v2 513 | 정답 밖 인용 | 3/3 | 정답 밖 인용 / 정답 밖 인용 / 정답 밖 인용 |
| holdout_v2 517 | 정답 밖 인용 | 3/3 | 정답 밖 인용 / 정답 밖 인용 / 정답 밖 인용 |

틀린 회차가 2회 미만이라 실패 문항으로 세지 않은 문항:

| 문항 | 틀린 회차 | 회차별 |
|---|---|---|
| holdout 109 | 1/3 | 맞음 / 맞음 / 정답 밖 인용 |
