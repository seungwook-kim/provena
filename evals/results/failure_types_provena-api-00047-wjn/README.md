# 실패 유형 표 (운영 배포판 `provena-api-00047-wjn`, 2026-11-13)

체크포인트 3조 코멘트(②)의 "새 판의 검색 실패 유형 표가 없다"에 맞춰 5장 5-5절 표를 00047 측정 결과로 다시 분류한 근거 파일이다. 분류 규칙은 개선 후(`provena-api-00044-49s`)와 같다(`evals/agent/failure_types.py` 머리말, EVAL_REPORT 5-5절 규칙).

| 파일 | 내용 |
|---|---|
| `failure_types.md`, `failure_types.json` | 70문항(v2 50건과 검증 20건, 각 3회) 표와 문항별 회차별 유형 |
| `context.json` | 문항·회차별 "첫 검색 문맥에 든 정답 위치 수 / 정답 위치 수" (`{"이름:문항:회차": [든 수, 전체 수]}`) |
| `context.detail.json` | `context.json`의 행별 상세. 첫 검색 문맥과 마지막 검색 문맥이 다른 행이 2개 있다 |

입력 측정 결과: `evals/results/deploy_latency_provena-api-00047-wjn/`(v2 50건), `evals/results/deploy_latency_holdout_provena-api-00047-wjn/`(검증 20건), 각각의 `citation_gold.json` 행.
첫 검색 문맥은 운영 Langfuse 추적의 첫 `search` 관측에서 읽었다(읽기 전용, 짝짓지 못한 행 0, 모델 호출 없음, 비용 0원). 새 인용 5문항은 `evals/results/failure_types_provena-api-00047-wjn_extra/`에 따로 센다. 합동 검토는 00047에서 다시 재지 않았다.

다시 만드는 명령(저장소 루트, Langfuse 읽기 키를 환경 변수로 줄 때):

    python -m evals.latency.lf_context --set v2 evals/results/deploy_latency_provena-api-00047-wjn evals/dataset_v2.jsonl \
        --set holdout evals/results/deploy_latency_holdout_provena-api-00047-wjn evals/dataset_holdout_v1.jsonl \
        --out evals/results/failure_types_provena-api-00047-wjn/context.json
    python -m evals.agent.failure_types --qa v2=evals/results/deploy_latency_provena-api-00047-wjn \
        --qa holdout=evals/results/deploy_latency_holdout_provena-api-00047-wjn \
        --context evals/results/failure_types_provena-api-00047-wjn/context.json --out evals/results/failure_types_provena-api-00047-wjn

유형은 행의 값으로 나눈 추정이다. 개선 후와 최신은 문맥의 출처(운영 Langfuse 추적)가 같아 직접 비교할 수 있다.
