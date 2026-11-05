# link_keep_per_sub 0↔2, 전수↔HNSW 오프라인 측정 (사전 등록 #26, #27)

측정 2026-11-05. 사전 등록 커밋 `9f82ea3`(측정 전) 뒤에 잰 값이다. 운영 DB, LLM, Voyage API는 부르지 않았다.

## 조건

- 코드: `9f82ea3`(= main `d2af1c2` + 사전 등록 행). `backend/rag/retrieve/`는 `84cd02d`와 같다.
- 실행기: `evals/retrieval/exp_linkkeep_v1.py`. 서비스 `Searcher`를 그대로 쓰고 번역은 원문 그대로, 임베딩은 저장 벡터만 쓴다.
- 평가셋: 동결 v1 30건(관련 15, 비관련 15), k=5, 필터 없음(#9와 같음).
- 조합: `voyage-4` 영어 문장 벡터(`dense_en`), 리랭커 없음, 저장된 분해(11건), L1x2.
- 저장소: 로컬 pgvector 0.8.7 컨테이너(`127.0.0.1:54331`) 새 DB `app_linkkeep`. 적재는 `load_snapshot`(generation 1)이고, 색인은 `db/manual/chunks_hnsw_voyage4.sql`로 만들었다.
- HNSW 설정: `hnsw.ef_search=200`, `iterative_scan=strict_order`. 코드 값 그대로다(`search.py:225~226`).

입력 sha256:

| 파일 | sha256 |
|---|---|
| `chunks.jsonl` (23,095청크) | `0244da138fc9a8c1f04fd4a56ff6244e2dc4cdc28392482e3a196a9435498c38` |
| `voyage-4.npy` (23,095 × 1024) | `00bfb9faae9be68c520d4d407bcbc75edc89c7bbd09449141ccad53be1011531` |
| `chunk_ids.json` | `0cdeaaab741d573ad5db44671f2c382762ae6414a89be98fb415ecca887718c2` |
| `voyage-4.queries.json` | `a3ae85faaa1d22db962e44d1d84beae354a38c498c4bb2bce95d510bfb074845` |
| `links.jsonl` (링크 있는 청크 2,661) | `3a3e112b19a851e40b3b1dff626e31b84f580f329023733f9286ee47e9ebd180` |
| `decompose/decomposition.json` | `1451ebc0c7aa4d1a8677c86df2d46bf9dc8752b8944471f292fa0c75529c7241` |
| `decompose/subq_vec_voyage.json` | `1710831070b262036ca090d886a7e7e92d073a059d2e79107de8a5c0d6c8dd6e` |

## 실행 명령

```bash
# 로컬 DB 준비(한 번)
docker exec provena-search-test psql -U app -d postgres -c "CREATE DATABASE app_linkkeep"
DATABASE_URL=<127.0.0.1:54331/app_linkkeep> python -m backend.rag.retrieve.load_snapshot --index <스냅샷 폴더> --embedder voyage-4
docker exec -i provena-search-test psql -U app -d app_linkkeep < db/manual/chunks_hnsw_voyage4.sql
# 관문과 측정
REPRO_DIR=<voyage-4 zip 푼 폴더> REPRO_DATA=<data/chunks·data/parsed가 있는 폴더> DATABASE_URL=<127.0.0.1:54331/app_linkkeep> python -m evals.retrieval.exp_linkkeep_v1 grid --out evals/results/linkkeep_v1
```

## 관문 (측정 전에 통과)

| 관문 | 결과 |
|---|---|
| ① `MemoryStore` keep=0 = 저장된 `dec+L1x2.json` | 청크 집합 다른 문항 0/30, Recall@5 0.9667 |
| ② 로컬 `PgStore` 전수 keep=0 = ① | 청크 집합 다른 문항 0/30, Recall@5 0.9667 |

## 결과: 4칸 Recall@5

| | keep=0 | keep=2 |
|---|---|---|
| 전수 | 0.967 | 0.967 |
| HNSW | 0.967 | 0.967 |

문항별 Recall@5는 네 칸 모두 같다. 3번만 0.5이고 나머지 14문항은 1.0이다.

## #26 keep 0 → 2 (전수, HNSW 모두 같음)

돌려준 청크 집합이 달라진 문항은 5개(3, 4, 6, 13, 25번)다. 나머지 25개는 같다. 바뀐 문항의 Recall@5는 하나도 달라지지 않았다.

| 문항 | 하위 질문 | 링크 자리 0→2 | 빠진 청크 | 들어온 청크 | Recall@5 |
|---|---|---|---|---|---|
| 3 | 2 | 2→1 | `d9ef01e8e25a78ce` | `fdf65877060c7bcb` | 0.5 → 0.5 |
| 4 | 2 | 2→1 | `f678984bd785fa91` | `98f3fd335aae5cb7` | 1.0 → 1.0 |
| 6 | 3 | 2→0 | `22def68e5c59fb95`, `9dd4348116a6d6e1` | `ad90d6d2909cd348`, `d94ab75bde0309c2` | 1.0 → 1.0 |
| 13 | 2 | 2→1 | `c0a22fe276575084` | `cf5b883111a1901a` | 1.0 → 1.0 |
| 25(비관련) | 2 | 2→1 | `11a94145fcf2cf30` | `e168f8d52bb8ebff` | — |

- 6번의 keep=2 결과는 저장된 분해만 쓴 결과(`decompose/voyage/dec.json`)와 청크 집합이 같다.
- 30문항 전체에서 링크로 바꾼 자리는 keep=0 28개, keep=2 22개다.

## #27 전수 → HNSW

| 지표 | 결과 |
|---|---|
| 최종 상위 5 집합 일치(keep=0) | 30/30 |
| 최종 상위 5 집합 일치(keep=2) | 30/30 |
| 벡터 질의 42개 `vector_top` 상위 5 집합 일치 | 42/42 |
| Recall@5 차이 | 0 (두 keep 모두) |
| 색인 사용 | `EXPLAIN`(7번 문항 전체 질문)에 `Index Scan using chunks_emb_hnsw_half` 있음 |

벡터 질의 42개는 나뉘지 않은 19문항의 전체 질문 19개와 하위 질문 23개다. 다른 문항이 없으므로 빠지거나 들어온 청크와 점수 차는 적을 것이 없다.

## 소요 시간 (노트북, Ryzen 5 7530U)

| 단계 | 시간 |
|---|---|
| 스냅샷 적재 23,095행 | 8.8초 (명령 전체 12초) |
| HNSW 색인 만들기 | 14초 (`maintenance_work_mem` 부족 안내가 23,046행에서 나옴) |
| 관문 ①② | 22초 |
| 측정(관문 + 4칸 + 42 질의 + EXPLAIN) | 51초 |
| 칸별 30문항 검색 | 전수 8.4~9.0초, HNSW 1.1~1.2초 |

같은 명령을 두 번 돌렸다. 두 번 모두 지연 시간을 뺀 원시 결과가 같았다.

## 파일

- `summary.json`: 관문, 4칸 Recall@5와 문항별 값, 달라진 문항 목록, 42 질의 일치 수, EXPLAIN
- `cells.jsonl`: 칸 × 문항 120줄(돌려준 청크, 지표, `n_sub`, `n_link`)
- `vector_top.jsonl`: 벡터 질의 42줄(전수와 HNSW 상위 5, 한쪽에만 있는 청크와 float32 점수)

## 한계

- 평가셋은 v1 30건 하나이고 필터가 없다. `as_of`나 `org`로 좁히면 계획이 전수 비교로 갈 수 있는데, 이번 측정은 그 경우를 재지 않았다.
- HNSW 색인은 한 번 만든 것으로 쟀다.
- 4칸의 Recall@5가 같으므로 이 30건으로는 keep=2와 HNSW의 효과를 점수로 구분할 수 없다.
