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
3. 질문(과 `sub_queries`가 있으면 하위 질문)을 영어 문장으로 바꾼다(`QUERY_TRANSLATE=1`일 때, `backend/services/llm.py` 경유, 여럿이면 동시에). 이미 영어면 그대로 쓴다(EC-02-1).
4. 질문 벡터를 voyage-4 API로 한 번에 만든다(전체 질문 + 하위 질문, `input_type=query`).
5. `sub_queries`가 없으면 전체 질문 벡터로 상위 `k`개, 있으면 하위 질문마다 상위 `k`개를 뽑아 번갈아(이미 든 것은 건너뜀) `k`개로 합친다. 다만 `k`가 기본 자리 수 5보다 크면(질문 그래프의 나뉜 질문 첫 검색, `k=8`) 하위 질문과 링크 확장으로 7자리를 먼저 채우고 끝 1자리(`FULL_TAIL`)만 원 질문 후보 목록에서 아직 없는 앞 청크로 채운다(사전 등록 62.38). 합동 검토 팀 검색은 원 질문 없이 하위 질문 둘만 쓴다(사전 등록 62.41).
6. 링크 확장 L1x2: 그 `k`개가 링크한 다른 페이지(`chunks.link_targets`)의 청크 중 같은 `org`·`as_of` 필터를 지나고 아직 안 든 것을 **전체 질문 벡터**와 가까운 순으로 `SEARCH_LINK_N`(2)개 골라 뒤 자리를 바꾼다. 나뉜 질문은 하위 질문마다 2자리(`link_keep_per_sub`)를 지키고 남은 자리만 바꾼다(하위 질문 2개면 1자리, 3개면 바꾸지 않음). 리랭커는 기본 없음.
7. 금액 구간 조회(사전 등록 62.7): 질문(한국어 원문, 하위 질문, 영어 문장)에 달러 금액이 있으면(`ranges.amounts_in`) 위 `k`개가 든 페이지의 청크 중 제목 경로 끝이 금액 구간인 행(`ranges.parse_band`: `>$25K up to $50K`, `Up to $5K`, `$100K plus` 등)에서 그 금액이 속한 행을 표마다 하나씩(가장 좁은 구간) 고르고, 전체 질문 벡터(하위 질문 벡터는 쓰지 않는다. 하위 질문은 LLM이 회차마다 다르게 써서 표 선택이 흔들렸다, 사전 등록 62.13)와 가까운 순으로 `SEARCH_RANGE_N`(3)개까지 뒤 자리를 바꾼다. 이미 든 구간 행은 그대로 두고, 자리는 뒤에서부터 구간 행이 아닌 청크를 덜어낸다(`k`는 그대로). 금액이 없거나 위 `k`의 페이지에 구간 행이 없으면 바꾸지 않는다. 벡터는 "$30,000"이 어느 구간에 드는지 알지 못해 구간 행 일곱 개가 서로 비슷한 점수로 흩어지기 때문이다(EVAL_REPORT 5장).
8. 상위 `k`개를 `Chunk`로 돌려준다.

확정 조합(2026-11-05, `evals/results/retrieval_fix_v1/`): voyage-4 · `dense_en` · 리랭커 없음 · k=5 · 질문 분해 · L1x2 = v1 Recall@5 0.967(자리 지키기를 넣기 전 값, `link_keep_per_sub=0`). 링크 확장은 강사 확인을 받았다(조장 11/5). 분해 LLM은 그래프가 부르고 `sub_queries`로 넘긴다(MCP는 넘기지 않는다).

**검색 방식** (`SEARCH_MODE`, 1차 비교에서 남긴 두 방식과 비교용)

| 값 | 벡터에 넣는 질문 | BM25에 넣는 질문 | 용도 |
|---|---|---|---|
| `hybrid_ko_kw` | 한국어 원문 | 영어 검색어 | 1차 상위 조합 |
| `dense_en` (기본) | 영어 문장 | 없음 | 확정 조합 |
| `bm25_kw` | 없음 | 영어 검색어 | 비교용(임베딩 없음) |
| `dense_ko` | 한국어 원문 | 없음 | 기준선, 데모 모드에서 번역 기록이 없을 때 |

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 데모 모드인데 그 질문의 번역 기록이 없음 | `dense_ko`로 내려 검색하고 Langfuse 트레이스에 `fallback=dense_ko`를 남긴다. 죽지 않는다 |
| EC-02-1 | 질의가 이미 영어(한글 없음, `valid_english` 통과). 그래프의 재작성 질의가 그렇다 | 번역 LLM을 부르지 않고 그대로 검색어·문장으로 쓴다. 트레이스 `translation_source=as_is`. 평가셋 50건은 모두 한글이 있어 비교 점수에 영향이 없다 |
| EC-02 | 번역 LLM 호출 실패·시간 초과 | 재시도 1회 뒤 EC-01과 같이 처리. 비교 입구 `make_search`는 내려가지 않고 멈춘다(내려가면 표에 적힌 조합과 다른 방식을 재게 된다) |
| EC-03 | 필터 결과가 0개(없는 `org`, 너무 이른 `as_of`) | 빈 목록을 돌려준다. 호출자가 "근거 없음"으로 거절한다 |
| EC-04 | 필터 결과가 `k`보다 적음 | 있는 만큼만 돌려준다. 채우려고 필터 밖 청크를 넣지 않는다 |
| EC-05 | `RERANK_MODEL=none` | 리랭킹 없이 RRF 순서로 상위 `k` |
| EC-06 | 같은 섹션이 여러 청크로 잘림 | 청크 단위로 돌려준다. 섹션 합치기는 호출자 몫(채점도 섹션 위치로 맞춤, `docs/specs/eval-retrieval.md`) |
| EC-07 | 모델 파일이 이미지에 없음 | `HF_HUB_OFFLINE=1`이라 기동 때 바로 실패한다. 내려받기로 넘어가지 않는다 |
| EC-08 | Voyage API 연결 오류·시간 초과(10초)·429·5xx | 재시도 없이 `EmbedUnavailable`(ConnectionError). MCP는 `unavailable`·`retryable=true`. 401·403·400은 `EmbedConfigError` → MCP `error`. 오류 글에 키를 넣지 않는다 |
| EC-09 | `VOYAGE_API_KEY` 없음 | 빈 목록 + 트레이스 `fallback_reason=no_key`. 죽지 않는다(G2). 질문 벡터 장부(키 없이 재생)는 다음 PR |
| EC-10 | `sub_queries`가 1개·4개 이상·빈 글·1000자 초과 | `ValueError`. `None`·`[]`은 나누지 않음 |
| EC-11 | 상위 결과에 링크가 없음·링크 대상이 필터 밖 | 바꾸지 않고(있는 만큼만 바꾸고) 그대로 돌려준다. `k <= SEARCH_LINK_N`이면 확장하지 않는다 |
| EC-12 | 질문에 금액이 없음, 통화 표시 없는 숫자(15분, SEV2), 상위 결과의 페이지에 구간 행이 없음, 구간 행이 필터(`org`·`as_of`) 밖 | 바꾸지 않는다. 원화 금액은 읽지 않는다. 구간 제목이 겹치는 표(Non Billable Expenses `>$5K`와 `>$50K`)는 아래 끝이 큰 쪽을 고른다 |

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
| `backend/rag/retrieve/embed.py` | 임베딩 모델 불러오기, 질문·문서 앞말(모델별 prefix). voyage-4는 REST 호출(`VoyageClient`, 시간 한도 10초·재시도 0번 = MCP 30초 − 번역 15초 안쪽). 응답의 `usage.total_tokens`는 `/chat` 요청 집계에 더해 done의 `embed_tokens`·`embed_cost_usd`로 나간다(`backend/services/step_cost.py`, docs/SDD.md 6장) |
| `backend/rag/retrieve/links.py` | 링크 확장 재료: 청크 `element_ids` → 파싱 결과 `links` → 청크 주소 기준 urljoin → '#'·끝 '/' 뗌 → manifest 주소로 rule_seq. 자기 쪽·코퍼스 밖 제외. 측정 코드 `exp_decompose_v1.Links`와 같은 규칙(AC-07에서 23,095청크 대조) |
| `backend/rag/retrieve/ranges.py` | 금액 구간 조회 재료(순수 함수, 모델·LLM 없음): `amounts_in`(질문의 달러 금액: `$30,000`, `$30K`, `30,000 dollars`, `3만 달러`), `parse_band`(제목 경로 끝의 금액 구간 6가지 표기), `covering`(표마다 금액이 속한 가장 좁은 구간 행). `search.py`의 `Searcher._range_expand`와 저장소의 `band_headings`·`key_scores`가 쓴다. 시험 `tests/test_range_search.py`, 재현·회귀 `evals/retrieval/range_context.py` |
| `backend/rag/retrieve/rerank.py` | 리랭커 불러오기, int8(CPU) 선택 |
| `backend/rag/retrieve/translate.py` | 한국어 질문 → 영어 검색어·영어 문장. LLM은 `backend/services/llm.py`로만 부른다. 번역은 질문 sha256과 모델 이름을 키로 `query_translations` 표에 저장하고, 같은 키가 있으면 LLM을 다시 부르지 않는다 |
| `backend/rag/retrieve/index.py` | 색인 만들기(오프라인, 모델 필요): `data/chunks/chunks.jsonl`에서 `data/index/`(`meta.json`: 임베더·차원·청크 수·원본 sha256, `chunks.jsonl`, `vectors.npy`)를 만든다. 가이드 p.12 4-3 "인덱스는 오프라인에서 만들어 벡터DB에 적재"와 해시가 바뀐 청크만 다시 임베딩. `refresh`: 청크 id·판·본문(지문)과 줄 순서가 같고 다른 칸(판 날짜 등)만 바뀐 청크 파일로 갈아 끼운다. 벡터는 본문과 모델로만 정해지므로 다시 계산하지 않고, 지문이나 순서가 다르면 멈춘다(I-011). 청크 sha256이 바뀌므로 `load_snapshot`이 다시 적재한다. `translations --from <1차 비교 translations.json>` 은 번역을 `data/index/query_translations.jsonl`(meta.json에 sha256)로 옮긴다 — `load_snapshot` 이 DB 장부에, `make_search` 가 메모리 장부에 넣어 1차 비교와 같은 번역으로 돈다(번역은 부를 때마다 달라 재현의 근거가 된다). `links`: 청크마다 링크 대상 페이지 → `data/index/links.jsonl`(줄 순서 = chunks.jsonl, meta.json에 sha256) |
| `backend/rag/retrieve/load_snapshot.py` | 적재(모델 불필요): `data/index/`를 DB에 넣는다. `docker compose up`의 `loader` 서비스가 db가 뜬 뒤 한 번 돌린다. DB가 아직 접속을 받지 않으면(새 DB 첫 기동의 초기화 중) 2초 간격으로 60초까지 다시 접속하고, 그 뒤에도 안 되면 마지막 접속 오류로 끝난다. 접속 오류(`OperationalError`)가 아닌 예외는 다시 시도하지 않는다(`_connect`, PR #95, `tests/test_index_snapshot.py`). chunk_id로 upsert(멱등), 배치마다 커밋, 이미 같은 스냅샷이면 건너뛴다(줄 범위 칸이 빈 옛 DB, 링크를 아직 안 실은 DB는 다시 넣는다). 링크는 `chunks.link_targets bigint[]`, 장부 `index_meta.links_sha256`. 증분(`schedule.py`)도 새 판 청크에 같은 규칙으로 링크를 넣는다. 스냅샷을 새로 만드는 순서는 `index import --from data/index_exp --embedder voyage-4`, `index links`, `load_snapshot`이다. 배치 사이의 커밋을 넘어 임시 표(`chunks_in`)를 쓰므로 Supabase에 적재할 때는 세션 포트(5432)로 접속한다. 2026-11-05에 이 방법으로 23,095청크를 20.7초에 적재했고(generation 1), 트랜잭션 포트(6543)로 적재하는 경우는 시험하지 않았다. 검색 자체는 6543에서 동작을 확인했다 |
| `backend/schemas/chunk.py` | `SearchQuery`, `Chunk` (바꾸지 않는다. 필드 추가는 SDD 6장 절차. `line_start`·`line_end` 추가는 열린 항목 8, 승인 대기) |
| `data/chunks/chunks.jsonl` | 색인 입력(PR #23) |
| `data/index/` | 색인 스냅샷. 23,095청크 × 1024차원 float32 `vectors.npy`가 약 95MB다. 압축 한 파일 `data/index.tar.gz`(약 94.5MB)로 저장소에 커밋하고(2026-11-07), 풀린 `data/index/`는 커밋하지 않는다(`.gitignore`). 쓰는 법과 고치는 순서는 `data/data.md`의 "검색 색인 스냅샷 쓰는 법", 정한 내용은 "열린 항목" 6 |
| `db/2xx_*.sql` | 검색 파트 SQL은 200번대(`db/101_auth_users.sql`이 100번대). 표는 SDD 5장 `docs`·`versions`·`chunks` 정의를 따르고, 벡터 칸 차원은 아래 "열린 항목" 2. `versions`에 `version_date_before boolean NOT NULL DEFAULT false`를 더해 `Chunk.version_date_before`(I-001, "YYYY-MM-DD 이전" 판)를 그대로 싣는다. `chunks`에 원본 줄 범위 `line_start`·`line_end integer`(열린 항목 8, 승인 대기). 번역 저장 표 `query_translations(query_sha256, model, keywords, sentence, created_at)`. 표마다 RLS를 켠다(Supabase Data API 차단, 앱은 표 소유자로 접속) |
| `tests/test_search.py` | AC 시험 |
| `backend/rag/retrieve/__init__.py` | `from backend.rag.retrieve import search` 로 계약 함수를 내보낸다(그래프·`services/demo_record.py`가 이렇게 부른다) |
| `backend/requirements.txt` | 검색 의존성: numpy. 로컬 모델용 torch(CPU판, `--extra-index-url .../whl/cpu`), sentence-transformers, transformers, huggingface-hub는 비교용이라 `backend/requirements-local-models.txt`에 두고 서비스 이미지에는 넣지 않는다. 팀 규칙대로 한 파일에 자기 파트 줄만 더한다(TEAM_GUIDE 213) |
| `Dockerfile` | 비교용 로컬 임베딩·리랭커는 서비스 이미지에 넣지 않는다(`SEARCH_*_MODEL` 빌드 인자 기본값 비움). 비교할 때만 `--build-arg`로 모델 이름을 주면 `requirements-local-models.txt`를 설치하고 고정 판으로 받는다(`HF_HOME=/app/.hf`, `HF_HUB_OFFLINE=1`). 코드 복사보다 앞에 두어 코드만 바꾸면 다시 받지 않는다. 폴더 주인 김승욱 리뷰 |
| `docker-compose.yml` | `loader` 서비스(`load_snapshot`, `./data/index` 연결)를 더하고 api는 `loader`가 성공으로 끝난 뒤 뜬다. 폴더 주인 김승욱 리뷰 |
| `backend/main.py` | 시작할 때 검색 준비를 기다려 끝낸다(`run_startup_warmup`, 운영 기본). `SEARCH_WARMUP=background`는 스레드로(`start_search_warmup`). 폴더 주인 김승욱 리뷰 |
| `.gitignore`, `.dockerignore` | 풀린 `data/index/`를 저장소·이미지에서 뺀다. 커밋하는 것은 `data/index.tar.gz` 한 파일이고, Docker 빌드가 이미지 안에서 풀며 `loader`는 compose가 연결한 폴더가 비어 있으면 시작할 때 다시 푼다 |
| `.env.example` | 검색 환경 변수(아래 표) 목록 |

**환경 변수**

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `EMBED_MODEL` | `voyage-4` | API(1024차원, 키 `VOYAGE_API_KEY`). 비교 후보: `Snowflake/snowflake-arctic-embed-l-v2.0`(비교용 로컬 모델, 서비스 이미지에는 넣지 않음 — `--build-arg`와 `requirements-local-models.txt`로), `voyageai/voyage-4-nano`, `Qwen/Qwen3-Embedding-0.6B`, `intfloat/multilingual-e5-large`, 기준선 `BAAI/bge-m3` |
| `VOYAGE_API_KEY` | 비움 | voyage-4 질문 임베딩. 부를 때 읽고 어디에도 찍지 않는다. 없으면 EC-09 |
| `SEARCH_LINK_N` | `2` | 링크 확장으로 바꿀 뒤 자리 수. `0`이면 끈다 |
| `SEARCH_RANGE_N` | `3` | 금액 구간 조회로 바꿀 뒤 자리 수 상한. `0`이면 끈다. 키 없는 데모(키 없음 또는 `DEMO_MODE=1`)도 같은 기본값 3이고 녹화도 3으로 만든다(사전 등록 62.46) |
| `EMBED_REVISION` | 모델별 고정 커밋 | 재현용. 1차 비교를 돌린 PC 캐시의 커밋(11/2 조장 확인): bge-m3 `5617a9f6`, arctic-l-v2 `ac6544c8`, voyage-4-nano `5fb34e87`, Qwen3-Embedding `97b0c614`, e5-large `3d7cfbda`, bge-reranker `953dc6f6`, Qwen3-Reranker `e61197ed`, mMiniLM `1427fd65`(전체 해시는 `embed.py`·`rerank.py` 명부). 1차 비교는 임베딩 로드 정밀도를 지정하지 않아 기록이 없다(config: nano·Qwen3 bfloat16, 나머지 float32). 서비스는 float32로 고정한다(I-008). Qwen3 리랭커는 GPU fp16·CPU fp32, int8은 CPU |
| `SEARCH_MODE` | `dense_en` | 위 표 |
| `SEARCH_POOL` | `100` | 벡터·BM25 각각 가져오는 후보 수 |
| `SEARCH_HNSW` | 꺼짐 | `1`일 때만 `PgStore`가 `HNSW_DIMS`에 있는 모델(voyage-4)에 HNSW 색인 질의를 쓴다. 그 밖에는 전수 비교다. 서비스 설정(61.51, `backend/graph/service_profile.py`)이 켠다. 색인 없이 켜면 느리다. 색인은 `db/manual/chunks_hnsw_voyage4.sql`을 수동으로 실행해 만든다. 색인이 없는 DB(로컬 compose 등)에서는 `SEARCH_HNSW=off`로 끈다 |
| `SEARCH_SUB_MERGE` | 꺼짐 | `1`이면 분해 검색에서 전체 질문도 후보에 넣고, 하위 질문 목록을 번갈아 합치는 대신 질의별 점수 중 가장 높은 값(`merge_by_score`)으로 합친다. 서비스 설정은 켜지 않는다 |
| `SEARCH_PARALLEL_SUBS` | 꺼짐 | `1`이면 하위 질문을 동시에 찾는다. 합치는 순서는 하위 질문 순서 그대로라 순위는 같다. 벡터만 쓰는 방식이고 리랭커가 없을 때만 동시에 한다(BM25·리랭커는 프로세스 안 계산이라 빨라지지 않는다). 서비스 설정이 켠다 |
| `EMBED_KEEPALIVE` | 꺼짐 | `1`이면 voyage-4 질문 임베딩이 HTTP 연결을 다시 쓰고(httpx), 질문이 2~8개면 하나씩 동시에 보낸다(`VOYAGE_PARALLEL_QUERIES`). 순서는 입력과 같다. 서비스 설정이 켠다 |
| `RERANK_MODEL` | `none` | 확정 조합은 리랭커 없음. 비교 후보: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`(비교용, 서비스 이미지에는 넣지 않음 — `--build-arg`와 `requirements-local-models.txt`로, CPU p95 0.59초), `BAAI/bge-reranker-v2-m3`, `bge-int8`, `Qwen/Qwen3-Reranker-0.6B`. bge는 CPU p95 7.0초라 GPU가 있을 때만 |
| `RERANK_TOP` | `10` | 리랭킹할 후보 수 |
| `QUERY_TRANSLATE` | `1` | `0`이면 번역 없이 `dense_ko` |
| `HF_HUB_OFFLINE` | `1` | 로컬 모델은 이미지 빌드 때 받고 실행 중에는 받지 않는다. 서비스 이미지에는 넣지 않고, 비교할 때만 Dockerfile `SEARCH_*` 빌드 인자(`--build-arg`, 판 = 명부의 고정 판)로 넣는다 |
| `INDEX_URL`, `INDEX_SHA256` | 비움 | `data/index/`와 `data/index.tar.gz`가 모두 없을 때 `loader`가 받을 색인(tar.gz) 주소와 sha256. sha256이 없거나 다르면 받지 않는다. 둘 다 비우면 적재를 건너뛰고 검색은 준비되지 않은 채 뜬다 |
| `INDEX_REQUIRED` | 비움 | `1`이면 색인이 없을 때 `loader`가 실패로 끝나 api가 뜨지 않는다(배포용) |
| `SEARCH_WARMUP` | 운영 `1`(비우면), compose `background` | `1`이면 `main.py`가 시작할 때 검색 준비를 끝날 때까지 기다린다(최대 60초). `0`은 끔, `background`는 기다리지 않고 스레드로 한다. 비우면 운영(`PROVENA_ENV`가 local·demo가 아니고 DB와 LLM 키가 있음)에서만 `1`이고 로컬 데모·키 없는 데모·DB 없음에서는 끈다. 넘거나 실패해도 서버는 뜨고 첫 검색 때 다시 시도한다 |
| `SEARCH_INDEX_DIR` | `data/index` | `make_search`(비교 입구)가 읽는 스냅샷 폴더 |
| `DATABASE_URL`, `DEMO_MODE`, `LLM_PROVIDER`, `LLM_API_KEY` | `.env.example` | 기존 값 그대로 |

- 고정값: RRF k=60, 임베딩 `max_seq_length` 512, 정규화한 벡터의 내적. 1차 비교와 같게 둔다.
- 그래프 전용 보조 검색(#67, 각각 그래프 `GRAPH_*` 스위치로 켜고 기본 검색 `search()`의 결과는 바꾸지 않는다): `search_pages`(페이지 범위 재검색), `sibling_sections`(형제 절), `intro_fill`(도입부 채우기, 같은 페이지 청크 `INTRO_MIN`=3개 이상일 때)(`backend/rag/retrieve/search.py:873, 846, 917`). `closest_to_query`(질문 벡터와 가까운 순)와 `search_headings`(제목 경로 검색)는 결정 0101(커밋 `e1e37e1`)에서 스위치와 함께 지워 현재 코드에 없다. 저장소가 `page_chunks`를 모르면 `intro_fill`은 빈 목록이다(`search.py:930-932`).
- 질문 벡터 기억: 검색기 하나가 (방식, 질문) → 벡터를 최대 `QVEC_CACHE`=512개 프로세스 안에 기억해, 같은 질문을 보조 검색에서 다시 임베딩하지 않는다. 프로세스를 다시 띄우면 비워진다(질문 벡터 장부와는 별개).
- 번역 프롬프트는 1차 비교의 `keywords`·`sentence` 두 가지를 그대로 쓴다(`experiment_v1.py`의 `PROMPTS`). 데모 모드는 `llm.py`가 입력 해시로 기록을 재생한다.
- 응답 시간 참고(노트북 CPU, 후보 10): 질문 임베딩 86~215ms, 리랭킹 bge 5.3초·int8 2.3초·Qwen3 12.2초·mMiniLM 0.42초. CPU에서 3초를 지키는 조합은 11/6에 정한다. 측정 스크립트와 결과는 평가셋 v1 동결 뒤 올린다.

**열린 항목** (정할 때까지 기본값으로 만든다)

| # | 항목 | 기본값 | 정할 때 |
|---|---|---|---|
| 1 | `Chunk`에 점수 칸이 없다. SDD 4-2와 MCP `search_handbook`은 점수를 내보낸다 | `score: float \| None = None` 추가를 이 Spec PR에서 제안. 3명 승인 뒤 스키마 PR로 반영(SDD 6장) | D3 전 |
| 2 | 벡터 차원이 모델마다 다르다(voyage-4-nano 2048, 나머지 1024). pgvector `vector` 칸의 HNSW 색인은 2,000차원까지다 | 칸 차원은 `EMBED_MODEL`에서 정하고 색인 없이 전수 비교(23,095개). nano가 뽑히면 `halfvec` 또는 차원 줄이기를 그때 정한다 | 11/6 |
| 3 | BM25를 메모리(`rank_bm25`)로 할지 Postgres 전문 검색으로 할지 | 메모리. 1차 비교와 같은 토큰화(`experiment_v1.py`의 `_tokens`) | D3 |
| 4 | 번역에 쓸 LLM | 로컬은 `LLM_PROVIDER=claude_cli`, 운영은 `anthropic`(`claude-haiku-5-5`, 2026-11-10 결정 0086. OpenRouter에서 바꿈). 번역 저장 키의 모델 이름은 같은 값(`claude-haiku-5-5`)으로 맞추므로 두 제공자가 저장된 번역을 함께 쓴다. 운영 경로를 다시 잴 때는 저장된 번역을 비우고 시작한다 | 정함 |
| 5 | SDD 11장의 리랭커 속도 기준이 2초로 남아 있다. SPEC 3장은 3초 | SPEC 3초를 따른다. SDD 11장도 3초로 고쳤다 | 이 Spec |
| 6 | 색인 스냅샷(`data/index/`, 벡터 약 95MB·폴더 약 130MB)을 나눠 주는 방법. CPU로 새로 만들면 수 시간이라 `docker compose up` 10분(G2) 안에 못 만든다. 저장소가 비공개라 Docker 빌드·`loader`가 토큰 없이 Release를 받을 수 없다(11/2 조장) | **정함(2026-11-07, 김승욱):** 원문 스냅샷(`data/corpus.tar.gz`, 결정 0021)과 같은 방식으로 색인을 압축 한 파일(`data/index.tar.gz`)로 만들어 저장소에 한 번 커밋하고, Docker 빌드와 `loader` 시작 때 자동으로 푼 뒤 `meta.json`의 sha256으로 대조한다(풀린 `data/index/`는 `.gitignore`에 둔다. 모델을 바꿔 다시 커밋하면 기록에 쌓인다). `loader`는 `data/index/meta.json`이 있으면 그것을 쓰고, 없으면 압축 파일을 풀고, 압축 파일도 없을 때만 `INDEX_URL`·`INDEX_SHA256` 환경 변수로 받는다 | 정함(2026-11-07), `data/index.tar.gz` 커밋 |
| 7 | voyage 두 후보는 문서와 질문의 모델이 다르거나 질문에 키가 필요하다 | **닫음(11/5)**: 확정 조합 voyage-4를 기본으로 지원(`embed.py` `VoyageClient`, 문서 벡터는 1차 비교 캐시 `index import --embedder voyage-4`). 질문 모델이 다른 `voyage4-doc+nano-query`는 넣지 않았다. 키 없는 질문은 EC-09(빈 결과), 질문 벡터 장부와 Voyage 학습 사용 거부 설정은 다음 PR | 11/5 |
| 9 | L1x2를 잰 조건 밖: `k≠5`, 리랭커 켬, `org` 지정, 증분으로 새로 생긴 페이지를 가리키는 옛 청크의 링크(다시 계산하지 않음) | 같은 규칙으로 돌지만 점수는 재지 않았다. 링크 대상은 페이지(rule_seq)라 대상 페이지가 개정돼도 `as_of`에 맞는 판을 고른다 | v2 측정 때 |
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
- (voyage-4, 11/5) `VOYAGE_API_KEY`도 없으면 예외 없이 빈 목록, 트레이스 `fallback_reason=no_key`(EC-09). 기동 때 미리 부르기(warmup)는 API 모델이면 건너뛴다

**AC-07 · 확정 조합 재현 (11/5, `tests/test_search_v2_repro.py`)**
- GIVEN: 측정과 같은 질문 벡터·하위 질문 벡터(유료 API를 부르지 않음), v1 30문항, 필터 없음(측정은 전체 청크에서 찾았다)
- WHEN: `search()`를 부른다
- THEN: 링크 대상이 측정 코드 `Links.target`과 23,095청크 모두 같고, 문항마다 돌려준 청크 집합이 `voyage/L1x2.json`·`decompose/voyage/dec+L1x2.json`과 30/30 같으며 Recall@5 0.9667(`link_keep_per_sub=0`으로 저장된 측정 조건을 재현). 입력 파일(`data/index_exp/`, 청크·파싱 결과)이 없으면 건너뛴다

**AC-05 · 오프라인 기동**
- GIVEN: `HF_HUB_OFFLINE=1`, 모델이 이미지에 있음
- WHEN: 앱을 띄운다
- THEN: 네트워크 없이 모델을 불러온다

**AC-06 · 채점기에 그대로 붙음**
- GIVEN: 평가셋이 동결된 뒤
- WHEN: `python -m evals.retrieval.run --search-fn backend.rag.retrieve.search:search ...`
- THEN: 지표 파일이 나온다. 판정자는 판정 파일을 낸 뒤에만 평가셋 질문으로 돌린다(정답 독립성)
