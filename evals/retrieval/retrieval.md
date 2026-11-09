# evals/retrieval/ : 검색 평가

## 이 폴더가 하는 일

Recall@5, MRR 측정. 한 줄 재현 명령을 남긴다.

- 주인: 박진형
- 입력: 평가셋, `search()`
- 출력: 검색 지표

## 재현 자료 (검색 회귀 고정 자료·v2 재현 시험 입력)

저장소에 올리지 않는 입력 두 가지를 여기 한 곳에 적는다. 둘 다 있어야 검색 회귀 고정 자료를 다시 만들 수 있다.

1. **재현 zip `재현 시험 입력 voyage-4 (2026-11-05).zip`** (89,107,582바이트, 약 89MB, 조장이 준 파일)
   - sha256 `8357b5a00e5ff23ed47c0ba1ea8577afdd2e33a1e6fc5c95b2f5d11120dc33a4`
   - 받는 곳: 팀 저장소 GitHub Release(주소는 조장 확인 뒤 기입)
   - 안의 파일(sha256은 zip 안 `README.txt`에도 있다):

     | 파일 | 내용 | sha256 |
     |---|---|---|
     | `voyage-4.npy` | 공개 핸드북 청크 23,095개의 voyage-4 문서 벡터(23,095 x 1024, float32) | `00bfb9faae9be68c520d4d407bcbc75edc89c7bbd09449141ccad53be1011531` |
     | `chunk_ids.json` | 벡터 순서의 청크 id 23,095개 | `0cdeaaab741d573ad5db44671f2c382762ae6414a89be98fb415ecca887718c2` |
     | `voyage-4.queries.json` | 평가셋 v2 50문항(v1 30 포함) 질문의 저장 벡터(한국어 `ko`, 영어 `en`) | `a3ae85faaa1d22db962e44d1d84beae354a38c498c4bb2bce95d510bfb074845` |
     | `README.txt` | 푸는 곳과 위 sha256 | |

   - 푼 폴더를 `REPRO_DIR`로 준다(기본 `data/index_exp/`, `.gitignore` 대상).
2. **`REPRO_DATA`**: `data/chunks/chunks.jsonl`과 `data/parsed/document_ir.jsonl`이 있는 폴더(기본 저장소 루트). 커밋하지 않고 저장소의 원문 스냅샷으로 다시 만든다(`data/data.md` "원문 스냅샷 쓰는 법"): `python -m backend.rag.ingest.parse` → `python -m backend.rag.ingest.chunk`(청크 23,095개). 2026-11-09에 이렇게 새로 만든 폴더로 `tests/test_search_v2_repro.py` 3건이 통과했고, `regress_fixture`가 만든 자료 4개가 커밋된 것과 sha256까지 같았다(`expected.json`은 `made_at`만 다름).

쓰는 곳

| 파일 | 쓰는 일 |
|---|---|
| `evals/retrieval/regress_fixture.py` | 검색 회귀 고정 자료 `tests/fixtures/search_regression/`과 기대값을 다시 만든다 |
| `tests/test_search_regression.py` | 위 고정 자료로 CI에서 돈다(입력 파일은 자료를 다시 만들 때만 필요) |
| `tests/test_search_v2_repro.py` | `search()` v2가 확정 조합 측정과 같은 청크를 돌려주는지. 입력이 없으면 건너뛴다 |
| `evals/retrieval/exp_linkkeep_v1.py` | 사전 등록 #26·#27 오프라인 비교 |

    REPRO_DIR=<zip 푼 폴더> REPRO_DATA=<data/chunks·data/parsed가 있는 폴더> python -m evals.retrieval.regress_fixture --n 10

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 박진형 (Claude Code) | "재현 자료" 절: 검색 회귀 고정 자료와 v2 재현 시험의 입력(재현 zip, `REPRO_DATA`)을 한 곳에 적고 쓰는 파일 4개의 머리 주석이 이 절을 가리키게 함(#94 리뷰 3) | |
| 2026-11-09 | 김승욱 (Claude Code) | `range_context.py`: 금액 구간 조회(사전 등록 62.7)의 검색만 재현(`demo`: 녹화 질문 틀 3 x 금액 5)과 회귀(`regress`: v2·검증 문항의 저장된 첫 검색 호출을 다시 검색해 수정 전후 문맥 비교, 금액 문구를 붙인 압박 점검 포함). LLM 호출 없음, 질문 벡터만 Voyage, 번역은 저장된 값. 결과 `evals/results/range_retrieval_62_7/` | 미정 |
| 2026-11-02 | 김승욱(팀장) | v1 30건에서 후보 12조합의 Haiku 5.5 답변 확인(EVAL_REPORT 3-0-1, `evals/results/retrieval_v1_answers_haiku/`). 중복 가중치 파일을 받지 않게 고침 | #38 |
| 2026-11-02 | 김승욱(팀장) | 비교 입구 `make_search`가 번역 실패 때 멈추도록 고침. 번역이 있으면 점수는 같음 | #37 |
| 2026-11-02 | 김승욱(팀장) | 2차 측정 계획 변경: `search()` 개발 뒤 그 경로로 재측정, 최종 1~2조합은 OpenRouter 번역으로 재확인, RAGAS는 50건으로 따로 측정 | #36 |
| 2026-11-02 | 김승욱(팀장) | 임베딩 후보에 voyage-4와 문서 voyage-4 + 질문 voyage-4-nano 추가, 11/6 2차 65조합. 근거는 EVAL_REPORT 3-0 "후보 추가" | #34 |
| 2026-11-02 | 김승욱(팀장) | 동결본 v1 베이스라인 측정. 조합은 `grid_baseline_v1.json`(`bge-m3`, `dense_ko`, 리랭커 없음), 결과는 `evals/results/baseline_v1/`, Recall@5 0.700, MRR 0.602 | #32 |
| 2026-11-02 | 김승욱(팀장) | `compare.py`가 결과 JSON에 `dataset_sha256`을 남기고 평가셋이 다르면 다시 재게 함(PR #32 리뷰 반영). 418조합 동결본 재채점 결과 `evals/results/retrieval_v1_round1_frozen/` | #33 |
| 2026-11-01 | 김승욱(팀장) | 검색 1차 비교 실행기 `experiment_v1.py`(임베딩 9 × 방식 6 × 리랭커 11 = 418조합, 사전 등록 #1)와 문서 100건 속도 측정 `speed100.py`·`speed100_rest.py`(GPU·CPU, 오프라인 강제). 결과 `evals/results/retrieval_v1_round1/`(조합별 JSON은 `results.tar.gz`), 요약 EVAL_REPORT 3-0 | #32 |
| 2026-10-31 | 김승욱(팀장) | 채점 도구: `gold.py`(정답 위치 -> 청크 맞추기, 청킹과 무관. 제목 경로·원본 줄 `#L`·대안 묶음 `\|`, Hugo 제목 앵커 `{#id}`는 무시), `metrics.py`(Recall@k·MRR·nDCG·비관련 거절·구간), `run.py`(`--search-fn 모듈:함수`), `compare.py`(임베딩·방식·리랭커 조합 표), 시험 `tests/test_eval_retrieval.py` | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
