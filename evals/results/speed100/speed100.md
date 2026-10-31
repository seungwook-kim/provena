# 임베딩·리랭커 속도 (문서 100건 실측)

가이드 p.12 4-3과 체크포인트 "Before D1" 1번: 조 코퍼스 100건으로 임베딩 시간을 재고 1만 청크로 환산해 일정에 반영한다.

| 날짜 | 작성자 | 내용 |
|---|---|---|
| 2026-11-01 | 김승욱(팀장) | 후보 임베딩 8종(로컬 7, API 1)과 리랭커 4종을 같은 문서·질문으로 GPU·CPU 실측. 결과 `speed100_1.json`, `speed100_2.json` |

## 조건

- 문서: `data/chunks/chunks.jsonl` 23,095청크에서 고르게 뽑은 100청크(청크 본문 그대로, 최대 800자)
- 질문: 평가셋 v1 질문 30건(문장만 썼다. 검색 결과·정답은 쓰지 않았다)
- 리랭커: 질문 10건 × 후보 10개, 질문 하나당 시간
- 기계: Intel Core Ultra 5 225H(메모리 31GB), NVIDIA GeForce RTX 4050 Laptop GPU. `HF_HUB_OFFLINE=1`(모델은 캐시에서만 읽음)
- 1만 청크 환산 = 100청크 시간 × 100. 모델 불러오기 시간은 빼고 따로 적었다

## 임베딩

| 모델 | 1만 청크 GPU | 1만 청크 CPU | 질문 1건 CPU p50 / p95 |
|---|---|---|---|
| `Snowflake/snowflake-arctic-embed-l-v2.0` | 17.8분 | 67.9분 | 117 / 183ms |
| `voyageai/voyage-4-nano` | 3.4분 | 37.6분 | 92 / 164ms |
| `Qwen/Qwen3-Embedding-0.6B` | 7.6분 | 81.7분 | 215 / 327ms |
| `BAAI/bge-m3` | 18.1분 | 60.8분 | 86 / 139ms |
| `intfloat/multilingual-e5-large` | 17.7분 | 61.4분 | 88 / 151ms |
| `intfloat/multilingual-e5-large-instruct` | 4.0분 | 65.0분 | 140 / 205ms |
| `nlpai-lab/KURE-v1` | 19.1분 | 64.8분 | 89 / 192ms |
| `voyage-4` (API) | 2.3분 | - | 351 / 708ms (네트워크 포함) |

- API 비용은 토큰 수로 기록했다: 100청크 11,095토큰, 1만 청크 약 111만 토큰.
- 코퍼스 전체(23,095청크)는 위 1만 청크 시간의 약 2.3배다. CPU만 쓰면 모델 하나에 약 1.5~3시간이 걸리므로 색인은 오프라인에서 한 번 만들어 적재한다(`docs/specs/search.md` 열린 항목 6).

## 리랭커 (질문 1건, 후보 10개)

| 모델 | GPU p50 / p95 | CPU p50 / p95 |
|---|---|---|
| `BAAI/bge-reranker-v2-m3` | 1.41 / 1.86초 | 5.35 / 7.04초 |
| 같은 모델 CPU int8 | - | 2.25 / 3.12초 |
| `Qwen/Qwen3-Reranker-0.6B` | 1.00 / 1.19초 | 12.21 / 14.17초 |
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | 0.15 / 0.20초 | 0.42 / 0.59초 |

- SPEC 3장의 응답 시간 기준(3초) 안에 CPU로 드는 리랭커는 mMiniLM뿐이다. 그래서 검색 Spec의 기본 리랭커를 mMiniLM으로 두었다(`docs/specs/search.md`).

## 재현

```bash
HF_HUB_OFFLINE=1 python -m evals.retrieval.speed100        # speed100_1.json: arctic, voyage-4-nano, qwen3, bge-m3, 리랭커 bge·int8·qwen3
HF_HUB_OFFLINE=1 python -m evals.retrieval.speed100_rest   # speed100_2.json: e5-large, e5-large-instruct, KURE-v1, mMiniLM, voyage-4 API(VOYAGE_API_KEY가 있을 때만)
```

모델은 미리 HF 캐시에 받아 두어야 한다. GPU가 없으면 CPU 줄만 잰다.
