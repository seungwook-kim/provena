# 실패 유형 표 (동결 판 `provena-api-00172-rex`, 커밋 `194dfd9a`)

`failure_types_provena-api-00047-wjn/`과 같은 규칙으로, 동결 판의 운영 측정 결과(v2 50건, 검증 20건, 새 검증 20건, 각 3회)를 문항 단위로 분류했다. 분류 규칙은 `evals/agent/failure_types.py` 머리말과 `EVAL_REPORT.md` 5-5절과 같다.

| 파일 | 내용 |
|---|---|
| `failure_types.md`, `failure_types.json` | 90문항 표와 문항별 회차별 유형(2026-11-17, 저장된 파일로 0원 계산, 모델 호출 없음) |
| `context.json` | 문항·회차별 "첫 검색 문맥에 든 정답 위치 수 / 정답 위치 수" (`{"이름:문항:회차": [든 수, 전체 수]}`), 운영 Langfuse 추적의 첫 `search` 관측에서 읽음(2026-11-16) |
| `context_final.json` | 같은 행의 마지막 검색 문맥 기준 값. 첫 검색과 다른 행은 `holdout_v2:515:2` 하나다 |
| `context.detail.json`, `context_final.detail.json` | 위 두 파일의 행별 상세 |

결과: 실패 문항(3회 중 2회 이상 틀림) 11개 / 90문항. 검색 실패 3(v2 38번, 검증 101번, 새 검증 515번), 근거 선택 3(v2 39번, 검증 108번, 새 검증 507번), 정답 밖 인용 5(새 검증 504·505·511·513·517번). 검증 109번은 3회차 1회만 정답 밖 인용이라 실패 문항으로 세지 않았다.

다시 만드는 명령(저장소 루트):

    python -m evals.agent.failure_types --qa v2=evals/results/deploy_latency_provena-api-00172-rex \
        --qa holdout=evals/results/deploy_latency_holdout_provena-api-00172-rex \
        --qa holdout_v2=evals/results/deploy_latency_holdout_v2_provena-api-00172-rex \
        --context evals/results/failure_types_provena-api-00172-rex/context.json --out evals/results/failure_types_provena-api-00172-rex

유형은 행의 값으로 나눈 추정이다. 새 검증 20건은 측정 전에 등록한 처음 보는 문항이라 v2·검증 20건과 달리 보고 고친 문항이 아니다.
