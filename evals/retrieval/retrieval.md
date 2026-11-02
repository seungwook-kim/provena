# evals/retrieval/ : 검색 평가

## 이 폴더가 하는 일

Recall@5, MRR 측정. 한 줄 재현 명령을 남긴다.

- 주인: 박진형
- 입력: 평가셋, `search()`
- 출력: 검색 지표

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-02 | 김승욱(팀장) | 동결본 v1 베이스라인 측정. 조합은 `grid_baseline_v1.json`(`bge-m3`, `dense_ko`, 리랭커 없음), 결과는 `evals/results/baseline_v1/`, Recall@5 0.700, MRR 0.602 | #32 |
| 2026-11-01 | 김승욱(팀장) | 검색 1차 비교 실행기 `experiment_v1.py`(임베딩 9 × 방식 6 × 리랭커 11 = 418조합, 사전 등록 #1)와 문서 100건 속도 측정 `speed100.py`·`speed100_rest.py`(GPU·CPU, 오프라인 강제). 결과 `evals/results/retrieval_v1_round1/`(조합별 JSON은 `results.tar.gz`), 요약 EVAL_REPORT 3-0 | #32 |
| 2026-10-31 | 김승욱(팀장) | 채점 도구: `gold.py`(정답 위치 -> 청크 맞추기, 청킹과 무관. 제목 경로·원본 줄 `#L`·대안 묶음 `\|`, Hugo 제목 앵커 `{#id}`는 무시), `metrics.py`(Recall@k·MRR·nDCG·비관련 거절·구간), `run.py`(`--search-fn 모듈:함수`), `compare.py`(임베딩·방식·리랭커 조합 표), 시험 `tests/test_eval_retrieval.py` | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
