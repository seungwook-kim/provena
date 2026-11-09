# backend/rag/retrieve/ : 임베딩·하이브리드 검색·리랭킹

## 이 폴더가 하는 일

`embed.py`(임베딩 모델 선택, 기본 voyage-4 API), `index.py`(색인 만들기), `search.py`(BM25 + 벡터, 판·절 필터, 한국어 질문을 영어 검색어로 변환, 링크 확장 `_link_expand`), `translate.py`(질문 번역), `rerank.py`(리랭커 후보, 기본은 없음), `links.py`(청크가 가리키는 다른 페이지 목록, 링크 확장 재료, 가산 GraphRAG). 필터는 검색 단계의 인자로 받는다. 바꾸기 전에 `evals/PREREGISTER.md`에 기대를 먼저 적는다. `privacy.py`(비공개 주소 가리기, MCP 서버와 그래프가 같은 함수를 씀).

- 주인: 박진형
- 입력: `SearchQuery`
- 출력: `Chunk` 목록 (`search()`를 D3에 김승욱에게 넘긴다)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) 요청 단위 임베딩 토큰 집계: `embed.py`가 Voyage 응답의 `usage.total_tokens`를 `step_cost`에 더하고 `translate.py`의 번역 호출 비용도 그 요청 집계에 합침(커밋 0a15fc2). `search.py`에서 검색어 표 붙이기·제목 경로 더하기 장치(`search_headings`, `closest_to_query`)와 그 스위치를 지움(결정 0101, e1e37e1) | #119 |
| 2026-11-10 | 김승욱 (Claude Code) | 금액 구간 조회의 표 고르기 수정(사전 등록 62.27). 운영 00032 금액 15건 중 1만 달러 3/3 거절의 검색 쪽 원인: 금액이 드는 표 5개의 구간 행 점수가 0.03 안에 몰려 상한 3에서 질문의 "$10,000"과 글자가 겹치는 `Bad debt write off > Up to $10K`가 들고 3만~10만 달러가 함께 인용하던 `Approving Payment` 행은 빠졌다(저장된 운영 첫 검색 14건 0원 재현, 정답 행 자체는 14/14 들었다). (가) 질문 글(원문·번역·하위 질문)에 표 이름의 낱말이 같은 어간으로 있는 표(`ranges.table_named`, "approver"와 "Approving expense")를 먼저 두고 그 안에서 전체 질문 벡터 점수 순. (나) 질문을 나눴으면 전체 질문 벡터의 상위 k 페이지도 구간 행 후보 페이지에 넣는다(벡터 질의 1회). 금액이 없는 질문은 그대로. 시험 `tests/test_range_search.py` | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 검색 hedge(사전 등록 62.14, 기본 꺼짐 `SEARCH_HEDGE=1`, 대기 `SEARCH_HEDGE_S` 기본 1.5초): `Searcher.search`의 질문 임베딩 + 벡터 질의 단계를 `vector_stage`로 떼어 내고, 켜면 대기 시간 안에 안 끝날 때 같은 일을 한 번 더 보내 먼저 성공한 결과를 쓴다(`hedge.py`). 번역(LLM)은 범위 밖이라 한 번만 돌고 결과는 같다. 검색 기록은 시도마다 따로 모아 이긴 시도만 합치고 `SearchTrace.hedged`·`hedge_winner`를 남긴다. 꺼짐 동작은 그대로(시험 `tests/test_speed_p95_code.py`) | 미정 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #107) 키 없는 데모에서 5만 달러 질문이 발췌형 가짜 응답으로 나오던 결함 수정(`search.py`) | #107 |
| 2026-11-10 | 박진형 (jinyeong-731) | PR #95가 `load_snapshot.py`에 더한 DB 접속 재시도(`_connect`)에 시험이 없어 2개 추가(`tests/test_index_snapshot.py`, 가짜 시계·가짜 `psycopg.connect`, DB 없음): 접속을 받을 때까지 2초 간격 재시도·60초 뒤 마지막 오류·접속 오류가 아닌 예외는 바로 올림·`prepare_threshold=None` 유지. 변이 3/3(재시도 없앰·`prepare_threshold` 뺌·모든 예외 재시도). Spec `search.md` 파일 표의 `load_snapshot.py` 줄에 재시도 규칙 적음. 동작 변경 없음 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 금액 구간 조회(사전 등록 62.7): 데모 녹화 1번 구간에서 5만 달러만 구간 행(`>$25K up to $50K`)이 근거로 들고 3만·10만 달러는 충분 판정이 NOTHING FOUND가 된 원인을 확인. 구간 행 일곱 개가 청크 하나씩이고 제목과 역할 줄뿐이라 벡터가 비슷하고(청킹과 표 머리는 정상), voyage-4 벡터가 "$30,000"이 어느 구간인지 몰라 "$50,000"과 "$50K"처럼 글자가 겹친 경우만 상위에 들었음. `ranges.py`(금액·구간 읽기, 순수 함수)와 `Searcher._range_expand`(금액이 있을 때 구간 행으로 뒤 자리 최대 2개 교체, `SEARCH_RANGE_N=0`이면 끔), 저장소 `band_headings`·`key_scores`. 검색만 재현(LLM 없음): 데모 15칸 정답 구간 행이 문맥에 든 칸 1 → 14, v2 50·검증 20의 첫 검색 문맥 회귀 나빠진 문항 0. 시험 `tests/test_range_search.py` | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | "이 폴더가 하는 일"을 현재 파일에 맞춤: 없는 `link_graph.py` 대신 `links.py`와 `search.py`의 `_link_expand`, 임베딩 기본 voyage-4 API, 리랭커 기본 없음. 동작 변경 없음 | 미정 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #95) db 상태 검사를 TCP로 바꿈에 맞춰 `load_snapshot.py` DB 접속에 최대 60초 재시도 추가 | #95 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #81) 키 없는 데모에서 질문 벡터 재생 지원(`embed.py`) | #81 |
| 2026-11-05 | 김승욱 (Claude Code) | `search.py` 주석의 HNSW SQL 위치를 `db/manual/chunks_hnsw_voyage4.sql`로 고침. 동작 변경 없음 | 미정 |
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | 검색 v2 = 확정 조합(조장 요청 5건): 기본값 voyage-4(API, `VoyageClient`, 실패 분류 EmbedUnavailable·EmbedConfigError·EmbedNoKey)·`dense_en`·리랭커 없음·k=5(`DEFAULT_K`, 그래프·MCP 같은 상수). `SearchQuery.sub_queries`(하위 질문마다 상위 k → 번갈아 합침), 링크 확장 L1x2(`links.py`, `chunks.link_targets`, 적재·증분 반영, 링크 후보도 org·as_of 필터). 재현 시험: 측정과 같은 벡터로 v1 30문항 청크 집합 30/30·Recall@5 0.9667, 링크 대상 23,095청크 일치. 변이 9/9 | 이번 PR |
| 2026-11-03 | 박진형 (jinyeong-731, Claude Code) | 섹션 원문 조회 `section.py`(`get_section`·`section_names`, docs/specs/mcp.md How 2): 판 고르기는 search와 같고, 청크마다 머리말 첫 줄과 `overlap_tail()`로 다시 계산한 겹침을 떼고 `text_sha256` 대조 뒤 잇는다(다르면 `SectionIntegrityError`). 스냅샷 23,095청크 지문 전부 통과, 파싱 결과와 15,463섹션 글자까지 같음·438섹션 공백만 다름(EC-14). 시험 `tests/test_retrieve_section.py` 13개(DB 1개 포함) | (이번 PR) |
| 2026-11-02 | 김승욱 (Claude Code) | 이미 영어인 질의는 번역 LLM을 부르지 않게 함(`search.md` EC-02-1). 평가셋 50건은 모두 한글이 있어 비교 점수에 영향이 없다 | 이번 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 판 날짜 UTC(I-011) 색인 반영: `index.py refresh`(지문·줄 순서가 같을 때만 청크 파일 교체, 벡터 그대로) + 테스트(본문·순서가 다르면 멈춤, 두 검사를 지우면 실패 확인). 실제 색인: 바뀐 칸 `version_date` 1,005행·`fetched_at` 23,095행(색인이 10/30 받은 날로 만들어져 있었음 → 10/31), 벡터 sha256 그대로. DB 사본에 `load_snapshot` 다시 적재(8.3초, generation 3): as_of 2026-10-27에 보이는 청크 23,076 → 23,095, 현재 판 23,095 그대로, 판 날짜 바뀐 판 68개, 벡터 빈 행 0 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 조장 답(11/2) 반영: 청크 열쇠 (chunk_id, version_id) 승인분 Spec 정리, 모델 판을 1차 비교 PC 캐시 커밋으로 확인(8개 모두 명부와 같음), 비교 입구 `make_search`(compare.py `--factory`, 서비스와 같은 Searcher·스냅샷 numpy·모델 하나씩·BM25 한 번), 번역 장부 파일(`index.py translations`), 줄 범위(`line_start`·`line_end`) 적재·반환, Docker(의존성·기본 모델 고정 판·`loader`·`SEARCH_WARMUP`·`INDEX_URL`). 재현(V3): 조장 동결본 재채점(PR #33)과 arctic·BM25만 × 리랭커 none·mMiniLM 9조합 문항별 상위 5가 같음(벡터만 Q1은 본문이 같은 두 청크의 동점), int8은 I-013 | 이 PR |
| 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | search() 1차 구현(docs/specs/search.md): `search.py`(판 유효 구간 필터·BM25·RRF·리랭킹·PgStore), `embed.py`·`rerank.py` 후보 명부(환경 변수로만 교체), `translate.py`(llm.py 경유·번역 장부), `index.py`·`load_snapshot.py`, `db/201_search.sql`, `tests/test_search.py` 54개(변이 3/3). 노트북 CPU 속도(무작위 벡터, 30문항×3): 합계 p95 1.9초 | PR 전 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| I-014 | 2026-11-09 | 김승욱 (Claude Code) | 금액 구간 표(권한표의 `>$25K up to $50K` 등)에서 질문의 금액이 속한 구간 행이 검색 상위에 들지 않는다 | 데모 녹화 1번 구간: 5만 달러만 구간 행이 근거로 들었고 3만·10만 달러는 충분 판정 NOTHING FOUND로 거절 | 김승욱 | 해결(검색 단계) | 2026-11-09 | `Searcher._range_expand`, 검색만 재현 데모 15칸 구간 행 문맥 1 → 14, 시험 `tests/test_range_search.py`. 답변까지는 LLM 3회 측정 전이라 미확인(62.7). 남은 한계(2026-11-10 수정 전): 금액이 들어맞는 표가 여럿이면(Authorization Matrix는 같은 금액에 5개 표) 하위 질문 벡터까지 섞은 점수로 2개만 골라, 하위 질문 문장이 회차마다 달라지면 지출 승인 표를 놓침(운영 트레이스 15건 중 2건, 검색 재연 70칸 중 15칸). 수정: 표 고르기를 전체 질문 벡터 하나로 하고 상한을 3으로 올림(사전 등록 62.13). 같은 70칸 재연 70/70, 데모 15칸 15/15. 질문에 금액이 없으면 영향이 없다 |
| I-013 | 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | bge int8 리랭커(동적 양자화) 점수가 한 번에 계산하는 묶음 크기·구성에 따라 바뀜(같은 5문서 batch 16과 1의 순위가 다름, mMiniLM은 같음) | 1차 비교의 int8 결과는 점수 캐시(안 계산한 쌍만 묶음) 상태에 따라 달라 재현되지 않음(동결본 대비 int8 4조합 26~29문항 다름, 1조합 R@5 0.767→0.833). 11/6 비교의 int8 숫자에 흔들림 | 김승욱 | 열림 | | 원인 확인 스크립트·결과는 PR 본문 |
| I-012 | 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | chunk_id = sha(rule_seq:seq:본문)에 판이 없어 개정판의 안 바뀐 섹션은 옛 판과 id가 같다 | chunk_id 하나로 upsert하면 새 판이 옛 판 행을 덮어 as_of 검색이 깨진다 | 박진형 | 해결(sandbox) | 2026-11-01 | chunks 열쇠 (chunk_id, version_id), versions 열쇠 (rule_seq, version_id) |
| I-011 | 2026-11-01 | 박진형 (jinyeong-731, Claude Code) | 판 날짜(%cs)가 커밋한 사람 시간대의 날짜 — infrastructure-security(19청크)가 10/28로 찍힘(UTC 10/27) | v1 as_of=2026-10-27 검색에서 그 쪽이 빠짐, UTC와 하루 다른 쪽 68개(청크 있는 쪽. 본문 없는 쪽까지 72쪽) | 박진형 | 해결 | 2026-11-02 | 조장 답 ⑥(별도 수집 PR). 판 날짜를 UTC로(`handbook.utc_day`), 다시 수집해 as_of 10/27 청크 23,076 → 23,095, 청크 id 그대로(`ingest.md` 작업 기록). 색인 청크 파일도 `index.py refresh`로 바꿔 DB 사본 다시 적재 → as_of 10/27 23,095(이 파일 작업 기록) |
| I-010 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 중간 저장(`parts/`) 키가 본문만 봐서, 같은 폴더에 모델·접두만 바꿔 다시 돌리면 옛 벡터를 그대로 씀 | 조용히 다른 모델 벡터가 섞임 | 박진형 | 해결 | 2026-10-29 | 키에 모델·판·문서 접두·정밀도 포함, `test_changed_settings_are_not_reused` |
| I-009 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | e5-small에 접두가 안 붙음: 설정 파일이 없어도 sentence-transformers가 `{'query': '', 'document': ''}` 를 채워 '설정에 접두 없음' 판정이 틀림 | e5가 권장 사용법 없이 측정돼 불리 | 박진형 | 해결 | 2026-10-29 | 200장 시험 manifest에서 발견, 빈 값은 없는 것으로 판정 + 테스트, 재시험 manifest `passage: `·`query: ` |
| I-008 | 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | Qwen3가 설정 기본값(bfloat16)으로 불러짐 — bge-m3는 fp32 | 모델 말고 정밀도도 달라져 단일 변수 비교가 아님, CPU에서 매우 느림 | 박진형 | 해결 | 2026-10-29 | 불러오기 경고에서 발견, `model_kwargs={'dtype': float32}` 고정·아니면 멈춤 |
