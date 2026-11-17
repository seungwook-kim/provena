# 새 인젝션 실제 모델 재시험 (2026-11-13)

| 실행 | 결과 파일 | 막힘 | 뚫림 | 오류 | LLM 호출 |
|---|---|---|---|---|---|
| 1차 | `newinj_real_default_retest1113.json`, 로그 `run_real_retest.log` | 15 | 0 | 0 | 124 |
| 2차 | `newinj_real_default_retest1113b.json` | 25 | 1 | 2 | 260 |
| 3차(오류 2건 재실행) | `newinj_real_default_retest1113c.json` | 2 | 0 | 0 | 8 |

- 2차 실행의 원시 로그는 저장소에 남기지 않는다(원시 로그 미보존, 11/17 정리). 숫자는 결과 파일의 집계와 같다.
- 기대 대조는 `evals/PREREGISTER.md` 62.48.
