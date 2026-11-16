# 표·수치 청크 원문 재대조 다시 실행 (2026-11-16)

- 날짜: 2026-11-16
- 기준 커밋: origin/main `eb8c9aac`
- 비용: 0원. LLM·키·운영 호출·네트워크 없음(공개 원문 GET인 `--fetch`는 쓰지 않음).
- 대상 색인: 로컬 `data/index/chunks.jsonl`(sha256 `19d9a8f82f0b94d6…`, 23,095줄, 운영 DB 적재본 `data/index.tar.gz` `a7e24ab4…`를 푼 파일), 원문 스냅샷 `data/corpus.tar.gz`(sha256 `51227fb1842f9eda…`).

## 실행한 것

1. 코퍼스 전체의 표·수치 청크: `python -B evals/recheck_table_number_chunks.py --out <임시 폴더>`(안에서 `evals/results/table_number_source_check_20261113_corpus/check_corpus.py`를 그대로 돌림). 결과 `corpus/`.
2. 정답 근거 청크의 표·수치: `python -B evals/results/table_number_source_check_20261113/check.py --sets v1,v2,holdout,cite_new --out <임시 폴더>`(스냅샷 대조만). 결과 `gold_chunks/`. 보고서 제목의 날짜(2026-11-13)는 스크립트에 고정된 문구이고 실행일은 2026-11-16이다.

## 결과

| 대조 | 대상 | 숫자 불일치 | 표 행 불일치 | 그 밖 |
|---|---|---|---|---|
| 코퍼스 전체 | 23,095청크 중 표 또는 수치가 든 4,318개 | 0 | 0 | 겹침 7,107개 중 앞 청크 꼬리 그대로 7,022, 라벨+꼬리 85, 그 밖 0. 표 행 중간에서 시작한 겹침 0, 첫 칸 빠짐 0. 대조 프로그램 시험(값을 일부러 바꿈) 2,000건 중 1,997건 잡음 |
| 정답 근거 청크 | v1·v2·검증·새 인용 관련 55문항의 정답 위치 청크 123개 중 표·수치가 든 60개 | 0 (60개 모두 일치) | 0 | 현재 공개 원문 대조는 하지 않음 |

- 코퍼스 전체 결과 12개 파일은 같은 날 앞서 커밋된 `evals/results/recheck_tables_20261116/`과 줄바꿈을 맞추면 내용이 모두 같다. 그 뒤 색인이 바뀌지 않았다는 뜻이다.
- `summary.json`의 `mismatch` 80과 `structure_problems` 85는 대조 스크립트의 겹침 규칙이 "앞 청크 본문 꼬리 그대로"만 맞다고 보아 긴 표 행에 첫 칸(라벨)을 붙인 겹침(결정 0115의 `ROW_TAIL_MAX=400` 규칙)도 세는 값이다. 값 대조는 `numbers_mismatch`, `rows_mismatch`, `overlap_other`로 읽는다(`evals/recheck_table_number_chunks.py` 머리말).
- `data/chunks/chunks.jsonl`과 `data/index/chunks.jsonl`은 `version_date` 칸만 1,005줄 다르고 대조는 그 칸을 읽지 않는다(원인은 `evals/results/version_date_mismatch_20261116/`).

## 한계

- 프로그램 대조이고 이번 실행에서 눈으로 읽은 표본은 없다(11/13 표본 30개는 `evals/results/table_number_source_check_20261113_corpus/manual_read.md`).
- 원문은 고정 스냅샷이다. 현재 공개 본문과의 대조는 하지 않았다.
