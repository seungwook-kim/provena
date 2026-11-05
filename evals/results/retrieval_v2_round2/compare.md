# 검색 조합 비교: dataset_v2.jsonl

조합 72개, k=5. Recall 높은 순(같으면 MRR). 관련 채점 문항 수와 뺀 문항은 조합마다 같다(각 json의 summary).

| embedder | mode | rerank_top | reranker | Recall@5 | MRR | nDCG@5 | 비관련 거절 | 지연 p95 |
|---|---|---|---|---|---|---|---|---|
| arctic-l-v2 | hybrid_ko_kw | 10 | bge | 0.893 | 0.836 | 0.813 | 0/25 | 2.164703 |
| voyage4-doc+nano-query | hybrid_ko_kw | 10 | bge | 0.873 | 0.821 | 0.801 | 0/25 | 0.197305 |
| voyage4-doc+nano-query | hybrid_ko_kw | 10 | int8 | 0.873 | 0.816 | 0.797 | 0/25 | 0.443551 |
| voyage4-doc+nano-query | hybrid_ko_kw | 10 | mminilm | 0.863 | 0.775 | 0.772 | 0/25 | 0.144078 |
| voyage-4-nano | hybrid_ko_kw | 10 | bge | 0.853 | 0.821 | 0.794 | 0/25 | 0.680795 |
| voyage4-doc+nano-query | hybrid_ko_kw | 10 | qwen3 | 0.853 | 0.795 | 0.776 | 0/25 | 0.19534 |
| qwen3-0.6b | hybrid_ko_kw | 10 | qwen3 | 0.853 | 0.788 | 0.775 | 0/25 | 0.435158 |
| voyage-4 | dense_en |  | none | 0.843 | 0.838 | 0.814 | 0/25 | 0.001626 |
| voyage4-doc+nano-query | dense_en | 10 | bge | 0.837 | 0.853 | 0.806 | 0/25 | 0.284083 |
| voyage4-doc+nano-query | dense_en | 10 | int8 | 0.837 | 0.850 | 0.805 | 0/25 | 0.513338 |
| voyage-4-nano | dense_en | 10 | bge | 0.837 | 0.833 | 0.800 | 0/25 | 0.979112 |
| voyage-4 | dense_en | 10 | bge | 0.837 | 0.833 | 0.801 | 0/25 | 0.28914 |
| voyage-4 | dense_ko |  | none | 0.837 | 0.828 | 0.795 | 0/25 | 0.001964 |
| voyage-4 | dense_en | 10 | int8 | 0.837 | 0.828 | 0.798 | 0/25 | 0.360749 |
| voyage-4-nano | dense_en | 10 | int8 | 0.837 | 0.823 | 0.797 | 0/25 | 1.854103 |
| voyage4-doc+nano-query | dense_en | 10 | mminilm | 0.837 | 0.823 | 0.792 | 0/25 | 0.021475 |
| voyage-4-nano | dense_en |  | none | 0.837 | 0.811 | 0.781 | 0/25 | 0.003883 |
| voyage-4-nano | dense_en | 10 | mminilm | 0.837 | 0.810 | 0.790 | 0/25 | 0.086948 |
| voyage-4 | dense_en | 10 | mminilm | 0.837 | 0.803 | 0.787 | 0/25 | 0.038482 |
| arctic-l-v2 | hybrid_ko_kw | 10 | int8 | 0.833 | 0.817 | 0.786 | 0/25 | 3.985026 |
| voyage-4-nano | hybrid_ko_kw | 10 | int8 | 0.833 | 0.817 | 0.787 | 0/25 | 1.040785 |
| qwen3-0.6b | hybrid_ko_kw | 10 | int8 | 0.833 | 0.808 | 0.782 | 0/25 | 1.379065 |
| arctic-l-v2 | hybrid_ko_kw | 10 | qwen3 | 0.833 | 0.797 | 0.771 | 0/25 | 1.561314 |
| voyage-4-nano | hybrid_ko_kw | 10 | qwen3 | 0.833 | 0.790 | 0.766 | 0/25 | 0.496284 |
| arctic-l-v2 | hybrid_ko_kw | 10 | mminilm | 0.833 | 0.765 | 0.760 | 0/25 | 0.308091 |
| voyage4-doc+nano-query | dense_en |  | none | 0.823 | 0.833 | 0.781 | 0/25 | 0.002026 |
| voyage-4 | hybrid_ko_kw | 10 | int8 | 0.823 | 0.808 | 0.776 | 0/25 | 0.539076 |
| qwen3-0.6b | dense_en | 10 | qwen3 | 0.823 | 0.773 | 0.760 | 0/25 | 0.373781 |
| voyage-4-nano | hybrid_ko_kw | 10 | mminilm | 0.823 | 0.761 | 0.752 | 0/25 | 0.154711 |
| arctic-l-v2 | dense_en | 10 | bge | 0.817 | 0.810 | 0.783 | 0/25 | 1.212551 |
| arctic-l-v2 | dense_en | 10 | int8 | 0.817 | 0.810 | 0.784 | 0/25 | 2.259654 |
| voyage4-doc+nano-query | dense_en | 10 | qwen3 | 0.817 | 0.793 | 0.756 | 0/25 | 0.271666 |
| voyage-4-nano | dense_en | 10 | qwen3 | 0.817 | 0.773 | 0.751 | 0/25 | 0.678556 |
| voyage-4 | dense_en | 10 | qwen3 | 0.817 | 0.773 | 0.751 | 0/25 | 0.281598 |
| arctic-l-v2 | dense_en | 10 | mminilm | 0.817 | 0.753 | 0.752 | 0/25 | 0.110603 |
| e5-large | hybrid_ko_kw | 10 | bge | 0.813 | 0.820 | 0.784 | 0/25 | 0.881264 |
| e5-large | hybrid_ko_kw | 10 | int8 | 0.813 | 0.820 | 0.785 | 0/25 | 1.703639 |
| qwen3-0.6b | hybrid_ko_kw | 10 | bge | 0.813 | 0.803 | 0.774 | 0/25 | 0.54728 |
| e5-large | dense_en |  | none | 0.813 | 0.771 | 0.749 | 0/25 | 0.002001 |
| e5-large | hybrid_ko_kw | 10 | mminilm | 0.813 | 0.767 | 0.756 | 0/25 | 0.171719 |
| e5-large | hybrid_ko_kw | 10 | qwen3 | 0.813 | 0.760 | 0.748 | 0/25 | 0.677993 |
| qwen3-0.6b | dense_en |  | none | 0.813 | 0.738 | 0.736 | 0/25 | 0.002493 |
| e5-large | dense_en | 10 | bge | 0.807 | 0.800 | 0.776 | 0/25 | 0.889814 |
| e5-large | dense_en | 10 | int8 | 0.807 | 0.800 | 0.777 | 0/25 | 1.774042 |
| e5-large | dense_en | 10 | mminilm | 0.807 | 0.727 | 0.732 | 0/25 | 0.073666 |
| voyage-4 | hybrid_ko_kw | 10 | bge | 0.803 | 0.803 | 0.768 | 0/25 | 0.259286 |
| voyage-4 | hybrid_ko_kw | 10 | qwen3 | 0.803 | 0.780 | 0.748 | 0/25 | 0.25389 |
| qwen3-0.6b | dense_en | 10 | mminilm | 0.803 | 0.775 | 0.761 | 0/25 | 0.039949 |
| qwen3-0.6b | hybrid_ko_kw | 10 | mminilm | 0.803 | 0.757 | 0.741 | 0/25 | 0.163683 |
| voyage-4 | hybrid_ko_kw | 10 | mminilm | 0.803 | 0.757 | 0.746 | 0/25 | 0.140278 |
| arctic-l-v2 | dense_en | 10 | qwen3 | 0.797 | 0.760 | 0.738 | 0/25 | 1.001779 |
| voyage-4-nano | hybrid_ko_kw |  | none | 0.797 | 0.717 | 0.688 | 0/25 | 0.167344 |
| qwen3-0.6b | dense_en | 10 | bge | 0.793 | 0.820 | 0.785 | 0/25 | 0.647047 |
| qwen3-0.6b | dense_en | 10 | int8 | 0.793 | 0.820 | 0.785 | 0/25 | 1.630552 |
| voyage-4 | hybrid_ko_kw |  | none | 0.790 | 0.755 | 0.703 | 0/25 | 0.138565 |
| e5-large | dense_en | 10 | qwen3 | 0.787 | 0.767 | 0.743 | 0/25 | 0.646703 |
| voyage-4-nano | dense_ko |  | none | 0.783 | 0.793 | 0.744 | 0/25 | 0.005157 |
| voyage4-doc+nano-query | hybrid_ko_kw |  | none | 0.783 | 0.727 | 0.695 | 0/25 | 0.142906 |
| voyage4-doc+nano-query | dense_ko |  | none | 0.777 | 0.729 | 0.703 | 0/25 | 0.001656 |
| arctic-l-v2 | hybrid_ko_kw |  | none | 0.773 | 0.733 | 0.700 | 0/25 | 0.135455 |
| arctic-l-v2 | dense_en |  | none | 0.763 | 0.800 | 0.743 | 0/25 | 0.001905 |
| arctic-l-v2 | dense_ko |  | none | 0.757 | 0.783 | 0.735 | 0/25 | 0.001652 |
| bge-m3 | dense_ko |  | none | 0.753 | 0.721 | 0.696 | 0/25 | 0.00176 |
| qwen3-0.6b | hybrid_ko_kw |  | none | 0.747 | 0.691 | 0.648 | 0/25 | 0.142102 |
| qwen3-0.6b | dense_ko |  | none | 0.717 | 0.660 | 0.639 | 0/25 | 0.001572 |
| e5-large | dense_ko |  | none | 0.710 | 0.748 | 0.690 | 0/25 | 0.00191 |
| e5-large | hybrid_ko_kw |  | none | 0.703 | 0.700 | 0.651 | 0/25 | 0.152753 |
| none | bm25_kw | 10 | bge | 0.700 | 0.743 | 0.672 | 0/25 | 0.806337 |
| none | bm25_kw | 10 | int8 | 0.700 | 0.738 | 0.670 | 0/25 | 1.533218 |
| none | bm25_kw | 10 | qwen3 | 0.700 | 0.693 | 0.648 | 0/25 | 0.655217 |
| none | bm25_kw | 10 | mminilm | 0.680 | 0.660 | 0.623 | 0/25 | 0.162522 |
| none | bm25_kw |  | none | 0.647 | 0.553 | 0.527 | 0/25 | 0.136416 |
