# 검색 조합 비교: dataset_v1.jsonl

조합 1개, k=5. Recall 높은 순(같으면 MRR). 관련 채점 문항 수와 뺀 문항은 조합마다 같다(각 json의 summary).

| embedder | mode | rerank_top | reranker | Recall@5 | MRR | nDCG@5 | 비관련 거절 | 지연 p95 |
|---|---|---|---|---|---|---|---|---|
| bge-m3 | dense_ko | 0 | none | 0.700 | 0.602 | 0.601 | 0/15 | 0.001668 |
