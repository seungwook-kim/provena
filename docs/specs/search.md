# Spec — 검색 `search()` (B-4, 작성 김승욱, 구현 박진형)

## Why

- **페르소나**: 질문 그래프·팀 에이전트·MCP 도구(`search_handbook`)를 만드는 우리 조, 검색 선택 근거를 확인하는 평가자
- **상황**: 한국어 질문으로 영어 핸드북(청크 23,095개, PR #23)에서 근거 섹션을 찾아야 한다. 임베딩·리랭커 최종 선택은 11/6 평가셋 v2(50건)로 정한다(2026-11-01 팀 결정. 1차 비교 결과는 평가셋 v1 동결 뒤 `docs/decisions.md`·EVAL_REPORT 3-0에 올린다). 가이드 일정상 하이브리드·리랭킹은 D3(11/4)에 넘긴다.
- **문제**:
  1. 모델이 11/6에 정해지는데 그때부터 만들면 D3 인계와 v2 측정에 늦는다.
  2. 영어 문서라 한국어 질문을 BM25에 그대로 넣으면 단어가 맞지 않는다.
  3. 필터를 검색 뒤에 걸면 상위 k가 비거나 다른 판이 섞인다(체크포인트 함정 2).
  4. 의존 파일·환경 변수가 계약에 없으면 다른 파트가 숨은 의존에 걸린다(체크포인트 함정 4).
- **측정 지표**: Recall@5·MRR(섹션 단위, `evals/retrieval/`), 검색+리랭킹 p95(SPEC 3장 3초 이하, 첫 요청 제외)

## Goal

- **해결 목표**: `search(SearchQuery) -> list[Chunk]` 하나로 필터 → 벡터 + BM25 → RRF → 리랭킹 → 상위 k를 돌려준다. 모델과 방식은 환경 변수로 바꾸고 코드는 바꾸지 않는다.
- **성공 기준**: 같은 입력이면 같은 결과(chunk_id 순서, 번역은 저장한 값을 다시 씀) / `org`·`as_of` 밖 청크 0개 / 모델을 환경 변수만 바꿔 후보 6종이 모두 돈다(voyage 두 후보는 열린 항목 7의 지원을 더한 뒤) / `HF_HUB_OFFLINE=1`에서 기동 / 데모 모드(키 없음)에서 죽지 않는다
- **Out of Scope**: 최종 모델 선택(11/6 v2), 문서 권한 필터 F-06(`acl`, 별도 Spec), GraphRAG(가산), MCP 서버(`extras/mcp_skill/`), 답 생성

## What

**Happy Path**
1. 호출자가 `SearchQuery(query="외부 SaaS 3만 달러 도입은 누가 승인하나", org=None, as_of=None, k=5)`를 넘긴다.
2. `org`·`as_of`로 대상 청크를 먼저 거른다. 판마다 유효 구간 `[valid_from, valid_to)`를 둔다(`valid_from` = 판 날짜, `valid_to` = 같은 페이지의 다음 판 날짜, 마지막 판은 비움). `as_of`가 없으면 `valid_to`가 빈 현재 판만, 있으면 `valid_from <= as_of < valid_to`인 판만 남긴다(SDD 4-2, SDD 11장 4-5 "기준일이 없으면 최신 판"). 증분 수집 뒤에도 옛 판과 새 판이 함께 나오지 않는다.
3. 질문을 영어 검색어로 바꾼다(`QUERY_TRANSLATE=1`일 때, `backend/services/llm.py` 경유).
4. 벡터 검색은 한국어 질문 그대로, BM25는 영어 검색어로 각각 상위 `SEARCH_POOL`개를 뽑아 RRF(k=60)로 합친다(`SEARCH_MODE=hybrid_ko_kw`).
5. 합친 상위 `RERANK_TOP`개를 리랭커로 다시 줄 세운다.
6. 상위 `k`개를 `Chunk`로 돌려준다.

**검색 방식** (`SEARCH_MODE`, 1차 비교에서 남긴 두 방식과 비교용)

| 값 | 벡터에 넣는 질문 | BM25에 넣는 질문 | 용도 |
|---|---|---|---|
| `hybrid_ko_kw` (기본) | 한국어 원문 | 영어 검색어 | 1차 상위 조합 |
| `dense_en` | 영어 문장 | 없음 | 2차 후보 |
| `bm25_kw` | 없음 | 영어 검색어 | 비교용(임베딩 없음) |
| `dense_ko` | 한국어 원문 | 없음 | 기준선, 데모 모드에서 번역 기록이 없을 때 |

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 데모 모드인데 그 질문의 번역 기록이 없음 | `dense_ko`로 내려 검색하고 Langfuse 트레이스에 `fallback=dense_ko`를 남긴다. 죽지 않는다 |
| EC-02 | 번역 LLM 호출 실패·시간 초과 | 재시도 1회 뒤 EC-01과 같이 처리. 비교 입구 `make_search`는 내려가지 않고 멈춘다(내려가면 표에 적힌 조합과 다른 방식을 재게 된다) |
| EC-03 | 필터 결과가 0개(없는 `org`, 너무 이른 `as_of`) | 빈 목록을 돌려준다. 호출자가 "근거 없음"으로 거절한다 |
| EC-04 | 필터 결과가 `k`보다 적음 | 있는 만큼만 돌려준다. 채우려고 필터 밖 청크를 넣지 않는다 |
| EC-05 | `RERANK_MODEL=none` | 리랭킹 없이 RRF 순서로 상위 `k` |
| EC-06 | 같은 섹션이 여러 청크로 잘림 | 청크 단위로 돌려준다. 섹션 합치기는 호출자 몫(채점도 섹션 위치로 맞춤, `docs/specs/eval-retrieval.md`) |
| EC-07 | 모델 파일이 이미지에 없음 | `HF_HUB_OFFLINE=1`이라 기동 때 바로 실패한다. 내려받기로 넘어가지 않는다 |

## How

```python
# backend/rag/retrieve/search.py
def search(q: SearchQuery) -> list[Chunk]: ...   # 입력·출력 형식은 backend/schemas/chunk.py 그대로
```

- **`Chunk` 출력 칸 추가 (3명 승인, PR #37, 열린 항목 8)**: `line_start: int | None`, `line_end: int | None` — 원본 페이지 줄 범위(1부터, 끝 포함). 스냅샷 `chunks.jsonl`에 이미 있는 값을 `chunks` 표에 싣고 그대로 돌려준다. 평가셋의 `경로#L523` 정답은 채점기(`evals/retrieval/gold.py`)가 이 두 칸으로 맞추므로, 없으면 그 문항은 늘 0점이다(v1 Q15).

**파일** (체크포인트 함정 4: 숨은 의존 없이 여기 적힌 것만 쓴다)

| 파일 | 하는 일 |
|---|---|
| `backend/rag/retrieve/search.py` | `search()`, 필터, RRF, 방식 분기. 비교 입구 `make_search(embedder, mode, reranker, rerank_top)`: `evals/retrieval/compare.py --factory backend.rag.retrieve.search:make_search` 가 조합마다 부른다. 서비스와 같은 검색 코드를 쓰고 저장소만 DB 대신 `data/index/` 스냅샷(numpy)을 읽는다. 이름은 1차 비교(`experiment_v1`)의 짧은 이름도 받고, BM25만은 `embedder="none"`·`bm25_kw` |
| `backend/rag/retrieve/embed.py` | 임베딩 모델 불러오기, 질문·문서 앞말(모델별 prefix) |
| `backend/rag/retrieve/rerank.py` | 리랭커 불러오기, int8(CPU) 선택 |
| `backend/rag/retrieve/translate.py` | 한국어 질문 → 영어 검색어·영어 문장. LLM은 `backend/services/llm.py`로만 부른다. 번역은 질문 sha256과 모델 이름을 키로 `query_translations` 표에 저장하고, 같은 키가 있으면 LLM을 다시 부르지 않는다 |
| `backend/rag/retrieve/index.py` | 색인 만들기(오프라인, 모델 필요): `data/chunks/chunks.jsonl`에서 `data/index/`(`meta.json`: 임베더·차원·청크 수·원본 sha256, `chunks.jsonl`, `vectors.npy`)를 만든다. 가이드 p.12 4-3 "인덱스는 오프라인에서 만들어 벡터DB에 적재"와 해시가 바뀐 청크만 다시 임베딩. `refresh`: 청크 id·판·본문(지문)과 줄 순서가 같고 다른 칸(판 날짜 등)만 바뀐 청크 파일로 갈아 끼운다. 벡터는 본문과 모델로만 정해지므로 다시 계산하지 않고, 지문이나 순서가 다르면 멈춘다(I-011). 청크 sha256이 바뀌므로 `load_snapshot`이 다시 적재한다. `translations --from <1차 비교 translations.json>` 은 번역을 `data/index/query_translations.jsonl`(meta.json에 sha256)로 옮긴다 — `load_snapshot` 이 DB 장부에, `make_search` 가 메모리 장부에 넣어 1차 비교와 같은 번역으로 돈다(번역은 부를 때마다 달라 재현의 근거가 된다) |
| `backend/rag/retrieve/load_snapshot.py` | 적재(모델 불필요): `data/index/`를 DB에 넣는다. `docker compose up`의 `loader` 서비스가 db가 뜬 뒤 한 번 돌린다. chunk_id로 upsert(멱등), 배치마다 커밋, 이미 같은 스냅샷이면 건너뛴다(줄 범위 칸이 빈 옛 DB는 다시 넣는다) |
| `backend/schemas/chunk.py` | `SearchQuery`, `Chunk` (바꾸지 않는다. 필드 추가는 SDD 6장 절차. `line_start`·`line_end` 추가는 열린 항목 8, 승인 대기) |
| `data/chunks/chunks.jsonl` | 색인 입력(PR #23) |
| `data/index/` | 색인 스냅샷. 23,095청크 × 1024차원 float32 `vectors.npy`가 약 95MB다. 모델을 정하기 전(11/6)까지는 저장소에 넣지 않는다(`.gitignore`). 나눠 주는 방법은 "열린 항목" 6 |
| `db/2xx_*.sql` | 검색 파트 SQL은 200번대(`db/101_auth_users.sql`이 100번대). 표는 SDD 5장 `docs`·`versions`·`chunks` 정의를 따르고, 벡터 칸 차원은 아래 "열린 항목" 2. `versions`에 `version_date_before boolean NOT NULL DEFAULT false`를 더해 `Chunk.version_date_before`(I-001, "YYYY-MM-DD 이전" 판)를 그대로 싣는다. `chunks`에 원본 줄 범위 `line_start`·`line_end integer`(열린 항목 8, 승인 대기). 번역 저장 표 `query_translations(query_sha256, model, keywords, sentence, created_at)`. 표마다 RLS를 켠다(Supabase Data API 차단, 앱은 표 소유자로 접속) |
| `tests/test_search.py` | AC 시험 |
| `backend/rag/retrieve/__init__.py` | `from backend.rag.retrieve import search` 로 계약 함수를 내보낸다(그래프·`services/demo_record.py`가 이렇게 부른다) |
| `backend/requirements.txt` | 검색 의존성: torch(CPU판, `--extra-index-url .../whl/cpu`), sentence-transformers, transformers, huggingface-hub, numpy. 팀 규칙대로 한 파일에 자기 파트 줄만 더한다(TEAM_GUIDE 213) |
| `Dockerfile` | 기본 임베딩·리랭커를 고정 판으로 빌드 때 받는다(`SEARCH_*` 빌드 인자, `HF_HOME=/app/.hf`, `HF_HUB_OFFLINE=1`). 코드 복사보다 앞에 두어 코드만 바꾸면 다시 받지 않는다. 폴더 주인 김승욱 리뷰 |
| `docker-compose.yml` | `loader` 서비스(`load_snapshot`, `./data/index` 연결)를 더하고 api는 `loader`가 성공으로 끝난 뒤 뜬다. 폴더 주인 김승욱 리뷰 |
| `backend/main.py` | `SEARCH_WARMUP=1`이면 시작할 때 검색 준비를 백그라운드로(`start_search_warmup`). 폴더 주인 김승욱 리뷰 |
| `.gitignore`, `.dockerignore` | `data/index/`를 저장소·이미지에서 뺀다(이미지는 compose가 연결한 폴더를 읽는다) |
| `.env.example` | 검색 환경 변수(아래 표) 목록 |

**환경 변수**

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `EMBED_MODEL` | `Snowflake/snowflake-arctic-embed-l-v2.0` | 후보: 이 값, `voyageai/voyage-4-nano`, `Qwen/Qwen3-Embedding-0.6B`, `intfloat/multilingual-e5-large`, `voyage-4`(API), 문서 `voyage-4` + 질문 `voyageai/voyage-4-nano`. voyage 두 후보는 인계 뒤 지원을 더한다(열린 항목 7). 기준선 `BAAI/bge-m3` |
| `EMBED_REVISION` | 모델별 고정 커밋 | 재현용. 1차 비교를 돌린 PC 캐시의 커밋(11/2 조장 확인): bge-m3 `5617a9f6`, arctic-l-v2 `ac6544c8`, voyage-4-nano `5fb34e87`, Qwen3-Embedding `97b0c614`, e5-large `3d7cfbda`, bge-reranker `953dc6f6`, Qwen3-Reranker `e61197ed`, mMiniLM `1427fd65`(전체 해시는 `embed.py`·`rerank.py` 명부). 1차 비교는 임베딩 로드 정밀도를 지정하지 않아 기록이 없다(config: nano·Qwen3 bfloat16, 나머지 float32). 서비스는 float32로 고정한다(I-008). Qwen3 리랭커는 GPU fp16·CPU fp32, int8은 CPU |
| `SEARCH_MODE` | `hybrid_ko_kw` | 위 표 |
| `SEARCH_POOL` | `100` | 벡터·BM25 각각 가져오는 후보 수 |
| `RERANK_MODEL` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | 후보: 이 값, `BAAI/bge-reranker-v2-m3`, `bge-int8`(bge를 CPU int8로), `Qwen/Qwen3-Reranker-0.6B`, `none`. 기본값은 CPU에서 SPEC 3초를 지키는 유일한 후보(후보 10개 p95 0.59초)로 두고, 최종은 11/6에 정한다. bge는 CPU p95 7.0초라 GPU가 있을 때만 |
| `RERANK_TOP` | `10` | 리랭킹할 후보 수 |
| `QUERY_TRANSLATE` | `1` | `0`이면 번역 없이 `dense_ko` |
| `HF_HUB_OFFLINE` | `1` | 모델은 이미지 빌드 때 받고 실행 중에는 받지 않는다(Dockerfile `SEARCH_*` 빌드 인자 = 기본 임베딩·리랭커의 고정 판) |
| `INDEX_URL`, `INDEX_SHA256` | 비움 | `data/index/`가 없을 때 `loader`가 받을 색인(tar.gz) 주소와 sha256. sha256이 없거나 다르면 받지 않는다. 둘 다 비우면 적재를 건너뛰고 검색은 준비되지 않은 채 뜬다 |
| `INDEX_REQUIRED` | 비움 | `1`이면 색인이 없을 때 `loader`가 실패로 끝나 api가 뜨지 않는다(배포용) |
| `SEARCH_WARMUP` | compose `1` | `1`이면 `main.py`가 시작할 때 검색 준비를 백그라운드로 한다. 실패해도 서버는 뜨고 첫 검색 때 다시 시도한다 |
| `SEARCH_INDEX_DIR` | `data/index` | `make_search`(비교 입구)가 읽는 스냅샷 폴더 |
| `DATABASE_URL`, `DEMO_MODE`, `LLM_PROVIDER`, `LLM_API_KEY` | `.env.example` | 기존 값 그대로 |

- 고정값: RRF k=60, 임베딩 `max_seq_length` 512, 정규화한 벡터의 내적. 1차 비교와 같게 둔다.
- 번역 프롬프트는 1차 비교의 `keywords`·`sentence` 두 가지를 그대로 쓴다(`experiment_v1.py`의 `PROMPTS`). 데모 모드는 `llm.py`가 입력 해시로 기록을 재생한다.
- 응답 시간 참고(노트북 CPU, 후보 10): 질문 임베딩 86~215ms, 리랭킹 bge 5.3초·int8 2.3초·Qwen3 12.2초·mMiniLM 0.42초. CPU에서 3초를 지키는 조합은 11/6에 정한다. 측정 스크립트와 결과는 평가셋 v1 동결 뒤 올린다.

**열린 항목** (정할 때까지 기본값으로 만든다)

| # | 항목 | 기본값 | 정할 때 |
|---|---|---|---|
| 1 | `Chunk`에 점수 칸이 없다. SDD 4-2와 MCP `search_handbook`은 점수를 내보낸다 | `score: float \| None = None` 추가를 이 Spec PR에서 제안. 3명 승인 뒤 스키마 PR로 반영(SDD 6장) | D3 전 |
| 2 | 벡터 차원이 모델마다 다르다(voyage-4-nano 2048, 나머지 1024). pgvector `vector` 칸의 HNSW 색인은 2,000차원까지다 | 칸 차원은 `EMBED_MODEL`에서 정하고 색인 없이 전수 비교(23,095개). nano가 뽑히면 `halfvec` 또는 차원 줄이기를 그때 정한다 | 11/6 |
| 3 | BM25를 메모리(`rank_bm25`)로 할지 Postgres 전문 검색으로 할지 | 메모리. 1차 비교와 같은 토큰화(`experiment_v1.py`의 `_tokens`) | D3 |
| 4 | 번역에 쓸 LLM | 로컬은 `LLM_PROVIDER=claude_cli`, 운영은 `openrouter`(`anthropic/claude-haiku-5.5`). 번역 저장 키의 모델 이름은 같은 값(`claude-haiku-5-5`)으로 맞추므로 두 제공자가 저장된 번역을 함께 쓴다. 운영 경로를 다시 잴 때는 저장된 번역을 비우고 시작한다 | 정함 |
| 5 | SDD 11장의 리랭커 속도 기준이 2초로 남아 있다. SPEC 3장은 3초 | SPEC 3초를 따른다. SDD 11장도 3초로 고쳤다 | 이 Spec |
| 6 | 색인 스냅샷(`data/index/`, 벡터 약 95MB·폴더 약 130MB)을 나눠 주는 방법. CPU로 새로 만들면 수 시간이라 `docker compose up` 10분(G2) 안에 못 만든다. 저장소가 비공개라 Docker 빌드·`loader`가 토큰 없이 Release를 받을 수 없다(11/2 조장) | 모델을 정하기 전(11/6 전): `data/index/`는 `.gitignore`, 로컬 `data/index/`로 개발하고 받을 주소는 `INDEX_URL`·`INDEX_SHA256` 환경 변수로 둔다(11/2 조장 답). 모델을 정한 뒤: 저장소에 한 번 커밋하고 `meta.json`의 sha256으로 대조한다(이때 `.gitignore` 줄을 뺀다. 모델을 바꿔 다시 커밋하면 기록에 쌓인다). `loader`는 `data/index/meta.json`이 있으면 그것을 쓰고 없을 때만 `INDEX_URL`을 본다 | 11/6 뒤 커밋 |
| 7 | voyage 두 후보는 문서와 질문의 모델이 다르거나 질문에 키가 필요하다 | 11/4 인계 범위에는 넣지 않는다. 인계 뒤 김승욱이 `EMBED_QUERY_MODEL`, `VOYAGE_API_KEY` 지원을 작은 PR로 더해 후보 6개를 같은 경로로 잰다. voyage-4가 뽑히면 키 없는 새 질문에 안내를 돌려주는 처리와 Voyage 학습 사용 거부 설정도 더한다 | 인계 뒤 |
| 8 | Spec에 없던 변경 두 가지: ① 청크 열쇠를 `chunk_id` 하나에서 `(chunk_id, version_id)`로(개정판에서 안 바뀐 섹션은 옛 판과 chunk_id가 같다) — **11/2 조장 승인**(`load_snapshot` upsert 기준도 같이, `Chunk` 계약은 그대로) ② `Chunk`에 `line_start`·`line_end` 추가(평가셋 `#L` 정답 채점용, 출처 링크에도 쓸 수 있다) — 박진형 제안, 김승욱·강경희 승인(11/2, PR #37, SDD 6장) | 둘 다 넣어 두고 PR 본문에 적는다. ②가 거절되면 칸을 빼고 채점기 쪽에서 청크 파일로 줄 범위를 찾는다 | PR 리뷰 |

## AC (Given-When-Then)

**AC-01 · 필터는 검색 전에**
- GIVEN: `org="security"`, `as_of="2024-01-01"`
- WHEN: `search()`를 부른다
- THEN: 돌려준 청크가 모두 `org=="security"`이고 그 날짜에 유효한 판이다. 결과가 `k`보다 적어도 필터 밖 청크는 없다

**AC-01b · 기준일이 없으면 현재 판만**
- GIVEN: 같은 페이지에 옛 판과 새 판 청크가 함께 적재됨, `as_of=None`
- WHEN: `search()`를 부른다
- THEN: 새 판(`valid_to`가 빈 판) 청크만 나온다. `version_date_before=True`인 판은 결과에서도 True다

**AC-02 · 같은 입력, 같은 결과**
- GIVEN: 같은 `SearchQuery`와 같은 환경 변수, 첫 호출의 번역이 `query_translations`에 저장됨
- WHEN: 두 번 부른다
- THEN: chunk_id 순서가 같다

**AC-03 · 모델은 환경 변수로만**
- GIVEN: `EMBED_MODEL`·`RERANK_MODEL`을 후보 값으로 하나씩 바꾼다(voyage 두 후보는 지원을 더한 뒤, 열린 항목 7)
- WHEN: 같은 질문으로 부른다
- THEN: 코드 수정 없이 모두 결과를 돌려준다

**AC-04 · 키 없이 동작**
- GIVEN: `DEMO_MODE=1`, `LLM_API_KEY` 없음, 번역 기록 없는 질문
- WHEN: `search()`를 부른다
- THEN: 예외 없이 `dense_ko` 결과를 돌려주고 트레이스에 `fallback=dense_ko`가 남는다

**AC-05 · 오프라인 기동**
- GIVEN: `HF_HUB_OFFLINE=1`, 모델이 이미지에 있음
- WHEN: 앱을 띄운다
- THEN: 네트워크 없이 모델을 불러온다

**AC-06 · 채점기에 그대로 붙음**
- GIVEN: 평가셋이 동결된 뒤
- WHEN: `python -m evals.retrieval.run --search-fn backend.rag.retrieve.search:search ...`
- THEN: 지표 파일이 나온다. 판정자는 판정 파일을 낸 뒤에만 평가셋 질문으로 돌린다(정답 독립성)
