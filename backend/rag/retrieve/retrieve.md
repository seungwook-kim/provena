# backend/rag/retrieve/ : 임베딩·하이브리드 검색·리랭킹

## 이 폴더가 하는 일

`embed.py`(다국어 로컬 임베딩), `search.py`(BM25 + 벡터, 판·절 필터, 한국어 질문을 영어 검색어로 변환), `rerank.py`(bge-reranker-v2-m3), `link_graph.py`(페이지 링크 그래프, 가산 GraphRAG). 필터는 검색 단계의 인자로 받는다. 바꾸기 전에 `evals/PREREGISTER.md`에 기대를 먼저 적는다.

- 주인: 박진형
- 입력: `SearchQuery`
- 출력: `Chunk` 목록 (`search()`를 D3에 김승욱에게 넘긴다)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-03 | 박진형 (jinyeong-731, Claude Code) | 섹션 원문 조회 `section.py`(`get_section`·`section_names`, docs/specs/mcp.md How 2): 판 고르기는 search와 같고, 청크마다 머리말 첫 줄과 `overlap_tail()`로 다시 계산한 겹침을 떼고 `text_sha256` 대조 뒤 잇는다(다르면 `SectionIntegrityError`). 스냅샷 23,095청크 지문 전부 통과, 파싱 결과와 15,463섹션 글자까지 같음·438섹션 공백만 다름(EC-14). 시험 `tests/test_retrieve_section.py` 13개(DB 1개 포함) | (이번 PR) |
| 2026-11-02 | 김승욱 (Claude Code) | 이미 영어인 질의는 번역 LLM을 부르지 않게 함(`search.md` EC-02-1). 평가셋 50건은 모두 한글이 있어 비교 점수에 영향이 없다 | 이번 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 판 날짜 UTC(I-011) 색인 반영: `index.py refresh`(지문·줄 순서가 같을 때만 청크 파일 교체, 벡터 그대로) + 테스트(본문·순서가 다르면 멈춤, 두 검사를 지우면 실패 확인). 실제 색인: 바뀐 칸 `version_date` 1,005행·`fetched_at` 23,095행(색인이 10/30 받은 날로 만들어져 있었음 → 10/31), 벡터 sha256 그대로. DB 사본에 `load_snapshot` 다시 적재(8.3초, generation 3): as_of 2026-10-27에 보이는 청크 23,076 → 23,095, 현재 판 23,095 그대로, 판 날짜 바뀐 판 68개, 벡터 빈 행 0 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 조장 답(11/2) 반영: 청크 열쇠 (chunk_id, version_id) 승인분 Spec 정리, 모델 판을 1차 비교 PC 캐시 커밋으로 확인(8개 모두 명부와 같음), 비교 입구 `make_search`(compare.py `--factory`, 서비스와 같은 Searcher·스냅샷 numpy·모델 하나씩·BM25 한 번), 번역 장부 파일(`index.py translations`), 줄 범위(`line_start`·`line_end`) 적재·반환, Docker(의존성·기본 모델 고정 판·`loader`·`SEARCH_WARMUP`·`INDEX_URL`). 재현(V3): 조장 동결본 재채점(PR #33)과 arctic·BM25만 × 리랭커 none·mMiniLM 9조합 문항별 상위 5가 같음(벡터만 Q1은 본문이 같은 두 청크의 동점), int8은 I-013 | 이 PR |
| 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | search() 1차 구현(docs/specs/search.md): `search.py`(판 유효 구간 필터·BM25·RRF·리랭킹·PgStore), `embed.py`·`rerank.py` 후보 명부(환경 변수로만 교체), `translate.py`(llm.py 경유·번역 장부), `index.py`·`load_snapshot.py`, `db/201_search.sql`, `tests/test_search.py` 54개(변이 3/3). 노트북 CPU 속도(무작위 벡터, 30문항×3): 합계 p95 1.9초 | PR 전 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| I-013 | 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | bge int8 리랭커(동적 양자화) 점수가 한 번에 계산하는 묶음 크기·구성에 따라 바뀜(같은 5문서 batch 16과 1의 순위가 다름, mMiniLM은 같음) | 1차 비교의 int8 결과는 점수 캐시(안 계산한 쌍만 묶음) 상태에 따라 달라 재현되지 않음(동결본 대비 int8 4조합 26~29문항 다름, 1조합 R@5 0.767→0.833). 11/6 비교의 int8 숫자에 흔들림 | 김승욱 | 열림 | | 원인 확인 스크립트·결과는 PR 본문 |
| I-012 | 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | chunk_id = sha(rule_seq:seq:본문)에 판이 없어 개정판의 안 바뀐 섹션은 옛 판과 id가 같다 | chunk_id 하나로 upsert하면 새 판이 옛 판 행을 덮어 as_of 검색이 깨진다 | 박진형 | 해결(sandbox) | 2026-11-01 | chunks 열쇠 (chunk_id, version_id), versions 열쇠 (rule_seq, version_id) |
| I-011 | 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | 판 날짜(%cs)가 커밋한 사람 시간대의 날짜 — infrastructure-security(19청크)가 10/28로 찍힘(UTC 10/27) | v1 as_of=2026-10-27 검색에서 그 쪽이 빠짐, UTC와 하루 다른 쪽 68개(청크 있는 쪽. 본문 없는 쪽까지 72쪽) | 박진형 | 해결 | 2026-11-02 | 조장 답 ⑥(별도 수집 PR). 판 날짜를 UTC로(`handbook.utc_day`), 다시 수집해 as_of 10/27 청크 23,076 → 23,095, 청크 id 그대로(`ingest.md` 작업 기록). 색인 청크 파일도 `index.py refresh`로 바꿔 DB 사본 다시 적재 → as_of 10/27 23,095(이 파일 작업 기록) |
| I-010 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 중간 저장(`parts/`) 키가 본문만 봐서, 같은 폴더에 모델·접두만 바꿔 다시 돌리면 옛 벡터를 그대로 씀 | 조용히 다른 모델 벡터가 섞임 | 박진형 | 해결 | 2026-10-29 | 키에 모델·판·문서 접두·정밀도 포함, `test_changed_settings_are_not_reused` |
| I-009 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | e5-small에 접두가 안 붙음: 설정 파일이 없어도 sentence-transformers가 `{'query': '', 'document': ''}` 를 채워 '설정에 접두 없음' 판정이 틀림 | e5가 권장 사용법 없이 측정돼 불리 | 박진형 | 해결 | 2026-10-29 | 200장 시험 manifest에서 발견, 빈 값은 없는 것으로 판정 + 테스트, 재시험 manifest `passage: `·`query: ` |
| I-008 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | Qwen3가 설정 기본값(bfloat16)으로 불러짐 — bge-m3는 fp32 | 모델 말고 정밀도도 달라져 단일 변수 비교가 아님, CPU에서 매우 느림 | 박진형 | 해결 | 2026-10-29 | 불러오기 경고에서 발견, `model_kwargs={'dtype': float32}` 고정·아니면 멈춤 |
