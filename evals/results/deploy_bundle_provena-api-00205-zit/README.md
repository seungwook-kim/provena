# 멀티 판 묶음 측정 (provena-api-00205-zit, 커밋 e822fb1e)

2026-11-17 16:14:15~16:36:38 KST, 트래픽 0% 태그 판 `provena-api-00205-zit`(태그 `c1117m`, `/chat` 멀티 그래프, `GRAPH_SPLIT_VOTE_WAIT_S=1.0`)에 측정 계정으로 동결 v2 50건 3회와 새 검증 20건(`evals/dataset_holdout_v2.jsonl`, 501~520번) 3회를 보냈다(`evals.latency.deploy_latency`, 문항마다 새 대화, 동시 요청 없음, 제한 120초). 채점은 `evals.latency.deploy_citation_gold`(코퍼스 스냅샷 `snap_9bc7d587`)이다. 측정 동안 트래픽은 `provena-api-00202-rid` 100%로 바뀌지 않았다(`run_log.txt`의 PRECHECK·END 줄). 이 판은 같은 날 16:58 KST에 트래픽 100%로 올렸다.

사전 등록 62.90의 멈춤 규칙 1(v2 1회차 뒤 인용 정확도·오답 근거·실패 행)은 `run_log.txt`의 STOP1 줄에서 걸리지 않았다(1회차 인용 정확도 0.960·오답 근거 0.040, 기준 00202-rid 1회 0.960·0.040, 실패 행 0).

## 결과

| 묶음 | 회차 | 성공 | 인용 정확도 | 오답 근거 | 정답 근거 인용률 | 과잉 거절 | 올바른 거절 | 전체 p95 | 답한 질문 p95 | 문항당 LLM 호출 |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 50건 | 1 | 50/50 | 0.960 | 0.040 | 0.947 | 0.000 | 1.000 | 8.201초 | 8.970초 | 16.38 |
| v2 50건 | 2 | 50/50 | 0.960 | 0.040 | 0.947 | 0.000 | 1.000 | 9.668초 | 10.323초 | 16.48 |
| v2 50건 | 3 | 50/50 | 0.960 | 0.040 | 0.947 | 0.000 | 1.000 | 8.632초 | 9.096초 | 16.36 |
| v2 50건 | 3회 | 150/150 | 평균 0.960 | 0.040 | 0.947 | 0.000 | 1.000 | 3회 합 8.970초(회차 평균 8.834초) | 3회 합 9.935초 | 16.41 |
| 새 검증 20건 | 1 | 20/20 | 0.756 | 0.462 | 0.929 | 0.071 | 1.000 | 9.670초 | 9.670초 | 21.9 |
| 새 검증 20건 | 2 | 20/20 | 0.702 | 0.500 | 0.929 | 0.000 | 1.000 | 9.931초 | 10.154초 | 21.5 |
| 새 검증 20건 | 3 | 20/20 | 0.718 | 0.462 | 0.857 | 0.071 | 1.000 | 9.234초 | 10.176초 | 20.6 |
| 새 검증 20건 | 3회 | 60/60 | 평균 0.726(0.702~0.756) | 0.474(0.462~0.500) | 0.905(0.857~0.929) | 0.048 | 1.000 | 3회 합 9.931초(회차 평균 9.612초) | 3회 합 9.931초 | 21.33 |

- v2 결과 종류는 세 회차 모두 answer 25, refuse 24, clarify 1이다. 새 검증 20건은 answer 13·refuse 7, answer 14·refuse 6, answer 13·refuse 7이다.
- 새 검증 20건의 과잉 거절은 515번이 1회차와 3회차에 근거 없음으로 거절된 행이다.
- 근거 충분 판정의 방식(`judge_votes`의 `how`): v2 3회 합 `two_agree` 74, `majority` 51, `none_capped` 2, `split_capped` 0. 새 검증 20건 3회 합 `two_agree` 40, `majority` 19, `split_capped` 2(1회차 1, 2회차 1), `none_capped` 1.
- 비용: 워밍업 0.007504달러, v2 3회 0.799015달러(요청당 0.0053달러), 새 검증 20건 3회 0.458188달러(요청당 0.0076달러).
- 5xx: v2 1회차 창(07:12:16~07:20:34 UTC) 0건, `/chat` POST 51건. 2회차부터 끝까지의 창(07:17:41~07:38:30 UTC) 0건, `/chat` POST 172건.

## 비교 기준

| 기준 | 인용 정확도 | 오답 근거 | 정답 근거 인용률 | 전체 p95 | 답한 질문 p95 | 근거 |
|---|---|---|---|---|---|---|
| v2: 같은 날 단일 판 `provena-api-00202-rid` 1회 | 0.960 | 0.040 | 0.960 | 8.232초 | 9.059초 | `evals/results/deploy_check_provena-api-00202-rid/v2/` |
| 새 검증 20건: 단일 판 `provena-api-00172-rex` 3회 | 0.661 | 0.500 | 0.857 | 3회 합 9.941초 | 3회 합 11.323초 | `evals/results/deploy_latency_holdout_v2_provena-api-00172-rex/` |

비교 원자료는 `compare_00205-zit_vs_00172-rex.json`과 `run_log.txt`의 FINAL·CHECK 줄에 있다.

## 파일

- `run_log.txt`: 실행기 기록(KST). 첫 줄(15:41:59)은 배포 기록 파일이 없어 시작 전에 멈춘 기록이다(`evals/results/deploy_check_provena-api-00205-zit/README.md`).
- `bundle_status.json`, `warmup.log`, `v2.log`, `holdout_v2.log`, `gold.log`: 단계별 상태와 로그
- `c1117m_summary.json`: 회차별 요약
- `compare_00205-zit_vs_00172-rex.json`: 00172-rex 3회와의 비교
- `errors_5xx_v2_run1.json`, `errors_5xx_v2_run2_3_holdout_v2.json`: 5xx·요청 수 감사
- 행 원자료: `evals/results/deploy_latency_provena-api-00205-zit/`, `evals/results/deploy_latency_holdout_v2_provena-api-00205-zit/`(대화 id는 가림), 워밍업 `evals/results/deploy_warmup_provena-api-00205-zit/`
