단계별 (단일 150건, 괄호는 멀티 150건). 시간은 초, 비용은 달러/요청(그 단계가 없던 요청은 0으로 넣은 평균)

| 단계 | n | p50 | p95 | 요청당 비용 |
|---|---|---|---|---|
| 검색 | 126 (125) | 0.49 (0.47) | 1.11 (2.17) | 0.000000 (0.000000) |
| 판단(분류·분해·재작성·근거 충분 판정) | 150 (150) | 9.30 (9.82) | 27.02 (18.40) | 0.002180 (0.002053) |
| 생성(답 작성) | 121 (122) | 8.89 (8.63) | 24.02 (19.79) | 0.002412 (0.002319) |
| 검증(근거 판정·다시 쓰기) | 75 (75) | 2.85 (2.94) | 3.96 (4.23) | 0.000629 (0.000627) |
| 전체 | 150 (150) | 5.70 (5.72) | 9.77 (9.76) | 0.005222 (0.004998) |

전체 시간 합 중 몫(단일 / 멀티): 검색 8.8% / 11.3%, 판단 190.5% / 180.8%, 생성 147.5% / 140.4%, 검증 26.9% / 27.2%
회차마다 첫 요청을 뺀 값(SPEC 48줄 조건, 단일 / 멀티): 검색 p95 1.11 / 2.17, 전체 p95 9.77 / 9.76 (n 147 / 147)

| 값 | 단일 | 멀티 |
|---|---|---|
| 입력 토큰/요청 | 35040.0 | 33769.8 |
| 출력 토큰/요청 | 3435.2 | 3241.5 |
| 비용 합(단가표) | 0.783242 | 0.749664 |
| 비용 합(행의 cost_usd) | 0.783214 | 0.749664 |
| 행 비용과 이 계산의 최대 차이 | 0.000028 | 0.000000 |
| 비용 출처: 공급자 보고 / 단가표 추정 (호출 수) | 0 / 1532 | 0 / 1494 |
| 전체 - (검색 + LLM) p50 / 최소 / 최대 (초) | -13.142 / -56.382 / -1.555 | -13.870 / -56.905 / -1.540 |

검색 호출 하나의 안쪽 (ms, 호출 단일 143번, 멀티 141번)

| 검색 안 단계 | 단일 p50 | 단일 p95 | 멀티 p50 | 멀티 p95 |
|---|---|---|---|---|
| translate | 13.6 | 25.3 | 13.6 | 40.1 |
| embed | 222.0 | 388.5 | 221.4 | 525.4 |
| vector | 117.6 | 888.0 | 129.2 | 966.0 |
| link | 0.0 | 107.5 | 0.0 | 83.7 |
| total | 351.8 | 938.7 | 402.6 | 1296.5 |

번역 출처(단일): {'stored': 143} / 리랭커: {'none': 143}

회차별 전체 p95 (다시 센 값 = summary.json latency_p95_s)

| 회차 | 경로 | n | 다시 센 p95 | summary.json | 같음 |
|---|---|---|---|---|---|
| agent_v2_q_d6151_r1_bo2sda2_api | single | 50 | 9.750 | 9.750 | True |
| agent_v2_q_d6151_r1_bo2sda2_api | multi | 50 | 10.098 | 10.098 | True |
| agent_v2_q_d6151_r2_bo2sda2_api | single | 50 | 9.899 | 9.899 | True |
| agent_v2_q_d6151_r2_bo2sda2_api | multi | 50 | 9.457 | 9.457 | True |
| agent_v2_q_d6151_r3_bo2sda2_api | single | 50 | 9.769 | 9.769 | True |
| agent_v2_q_d6151_r3_bo2sda2_api | multi | 50 | 9.530 | 9.530 | True |

agent_v2_q_d6151_r1_bo2sda2_api: single p50 5.55 p95 9.75, multi p50 5.96 p95 10.10

agent_v2_q_d6151_r2_bo2sda2_api: single p50 5.96 p95 9.90, multi p50 5.39 p95 9.46

agent_v2_q_d6151_r3_bo2sda2_api: single p50 5.28 p95 9.77, multi p50 5.68 p95 9.53

단계별 토큰/요청 (입력 / 출력, 단일)

| 단계 | 입력 | 출력 |
|---|---|---|
| 검색 | 1 | 0 |
| 판단(분류·분해·재작성·근거 충분 판정) | 13587 | 1643 |
| 생성(답 작성) | 16549 | 1515 |
| 검증(근거 판정·다시 쓰기) | 4904 | 277 |

LLM step별 (단일, 호출 하나 기준)

| step | 단계 | 호출 수 | 시간 합(초) | p50 | p95 | 입력 토큰 평균 | 출력 토큰 평균 |
|---|---|---|---|---|---|---|---|
| judge/judge | plan | 379 | 1125.4 | 3.02 | 5.01 | 4583 | 584 |
| write_answer/answer | generate | 253 | 781.2 | 2.88 | 5.77 | 4616 | 575 |
| write_answer/answer_fast | generate | 269 | 478.4 | 1.76 | 2.71 | 4887 | 304 |
| ground/grounding | verify | 156 | 228.5 | 1.41 | 1.94 | 4683 | 264 |
| search/decompose | plan | 150 | 189.4 | 1.09 | 2.15 | 572 | 119 |
| classify/classify | plan | 173 | 165.0 | 0.93 | 1.23 | 745 | 12 |
| search/decompose_gate | plan | 150 | 147.1 | 0.96 | 1.27 | 574 | 36 |
| ground/answer_fast | verify | 1 | 1.6 | 1.59 | 1.59 | 5047 | 331 |
| translate_sentence | search | 1 | 0.9 | 0.91 | 0.91 | 127 | 30 |

가장 느린 5건 (single, 초)

| 회차 | 문항 | 결과 | 전체 | 검색 | 판단 | 생성 | 검증 | LLM 호출 | 검색 호출 |
|---|---|---|---|---|---|---|---|---|---|
| agent_v2_q_d6151_r3_bo2sda2_api | 2 | answer | 13.83 | 0.61 | 32.25 | 19.46 | 3.15 | 17 | 2 |
| agent_v2_q_d6151_r2_bo2sda2_api | 2 | answer | 13.49 | 0.70 | 33.24 | 17.14 | 2.90 | 17 | 2 |
| agent_v2_q_d6151_r1_bo2sda2_api | 2 | answer | 12.59 | 0.65 | 29.92 | 17.92 | 3.11 | 17 | 2 |
| agent_v2_q_d6151_r2_bo2sda2_api | 31 | answer | 11.63 | 0.44 | 13.52 | 12.93 | 9.23 | 16 | 2 |
| agent_v2_q_d6151_r3_bo2sda2_api | 35 | answer | 9.99 | 1.15 | 17.76 | 19.76 | 3.94 | 19 | 4 |

가장 느린 5건 (multi, 초)

| 회차 | 문항 | 결과 | 전체 | 검색 | 판단 | 생성 | 검증 | LLM 호출 | 검색 호출 |
|---|---|---|---|---|---|---|---|---|---|
| agent_v2_q_d6151_r1_bo2sda2_api | 2 | answer | 12.56 | 0.67 | 30.83 | 17.04 | 2.88 | 17 | 2 |
| agent_v2_q_d6151_r1_bo2sda2_api | 4 | answer | 12.47 | 2.88 | 35.57 | 28.05 | 2.87 | 24 | 3 |
| agent_v2_q_d6151_r2_bo2sda2_api | 6 | answer | 10.94 | 5.68 | 15.37 | 14.41 | 3.90 | 12 | 4 |
| agent_v2_q_d6151_r1_bo2sda2_api | 40 | answer | 10.10 | 0.44 | 16.00 | 18.31 | 3.67 | 12 | 2 |
| agent_v2_q_d6151_r1_bo2sda2_api | 6 | answer | 9.86 | 2.07 | 30.38 | 29.38 | 3.43 | 19 | 4 |

무엇으로 잰 숫자인가 (summary.json meta)

- agent_v2_q_d6151_r1_bo2sda2_api: eval-question-20261108-221001 끝 2026-11-08 22:19:39, dataset_v2.jsonl 810d01f1c27d, PgStore, LLM anthropic/claude-haiku-5-5, 검색 {'embed_model': 'voyage-4', 'mode': 'dense_en', 'pool': 100, 'rerank_model': 'none', 'rerank_top': 10, 'translate': True, 'link_n': 2, 'link_keep_per_sub': 2}
- agent_v2_q_d6151_r2_bo2sda2_api: eval-question-20261108-222936 끝 2026-11-08 22:39:09, dataset_v2.jsonl 810d01f1c27d, PgStore, LLM anthropic/claude-haiku-5-5, 검색 {'embed_model': 'voyage-4', 'mode': 'dense_en', 'pool': 100, 'rerank_model': 'none', 'rerank_top': 10, 'translate': True, 'link_n': 2, 'link_keep_per_sub': 2}
- agent_v2_q_d6151_r3_bo2sda2_api: eval-question-20261108-224909 끝 2026-11-08 22:58:37, dataset_v2.jsonl 810d01f1c27d, PgStore, LLM anthropic/claude-haiku-5-5, 검색 {'embed_model': 'voyage-4', 'mode': 'dense_en', 'pool': 100, 'rerank_model': 'none', 'rerank_top': 10, 'translate': True, 'link_n': 2, 'link_keep_per_sub': 2}
