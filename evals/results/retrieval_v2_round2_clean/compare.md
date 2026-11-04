# 검색 조합 비교: dataset_v2.jsonl

조합 13개, k=5. Recall 높은 순(같으면 MRR). 관련 채점 문항 수와 뺀 문항은 조합마다 같다(각 json의 summary).

| embedder | mode | rerank_top | reranker | Recall@5 | MRR | nDCG@5 | 비관련 거절 | 지연 p95 |
|---|---|---|---|---|---|---|---|---|
| voyage4-doc+nano-query | hybrid_ko_kw | 10 | int8 | 0.873 | 0.798 | 0.783 | 0/25 | 5.341512 |
| arctic-l-v2 | hybrid_ko_kw | 10 | int8 | 0.853 | 0.808 | 0.787 | 0/25 | 3.052894 |
| voyage4-doc+nano-query | dense_en | 10 | int8 | 0.837 | 0.830 | 0.787 | 0/25 | 4.781625 |
| voyage-4 | dense_en | 10 | int8 | 0.837 | 0.828 | 0.804 | 0/25 | 5.436032 |
| voyage-4-nano | dense_en | 10 | int8 | 0.837 | 0.810 | 0.786 | 0/25 | 2.91447 |
| voyage-4-nano | hybrid_ko_kw | 10 | int8 | 0.833 | 0.801 | 0.775 | 0/25 | 3.234329 |
| voyage-4 | hybrid_ko_kw | 10 | int8 | 0.823 | 0.787 | 0.760 | 0/25 | 5.866922 |
| arctic-l-v2 | dense_en | 10 | int8 | 0.817 | 0.790 | 0.771 | 0/25 | 3.554198 |
| qwen3-0.6b | hybrid_ko_kw | 10 | int8 | 0.813 | 0.787 | 0.762 | 0/25 | 2.957942 |
| e5-large | hybrid_ko_kw | 10 | int8 | 0.813 | 0.787 | 0.760 | 0/25 | 3.134958 |
| e5-large | dense_en | 10 | int8 | 0.807 | 0.733 | 0.737 | 0/25 | 5.987405 |
| qwen3-0.6b | dense_en | 10 | int8 | 0.793 | 0.820 | 0.785 | 0/25 | 2.680304 |
| none | bm25_kw | 10 | int8 | 0.700 | 0.728 | 0.669 | 0/25 | 6.088428 |
