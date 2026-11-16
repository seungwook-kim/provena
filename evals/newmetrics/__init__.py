"""새 지표 네 개(답변 리콜, 결정표 셀, 링크 추출, 함께 볼 정책 후보)의 정답 변환·검증·측정기 (2026-11-16).

정답은 `새 지표 정답 세트 작성 요청 (2026-11-16).md`의 표를 두 판정자가 채운 것이다. 측정기는 정답 파일을 읽기만 한다.
- `gold_convert`: 채운 md 표 -> `evals/recall_pairs.jsonl`, `decision_cells_gold.jsonl`, `link_gold.jsonl`, `maintenance_gold.jsonl`
- `gold_validate`: 위치만 기계로 확인한다(줄 번호·섹션·커밋). 내용은 고치지 않는다.
- `recall_prod`, `decision_prod`: 운영 배포판의 실제 경로(웹훅, 결정표 변환 API)로 잰다. 시험 계정 범위, 넣은 행은 지우고 0행을 확인한다.
- `link_eval`, `maintenance_eval`: 운영 DB 읽기 전용(또는 로컬 색인 파일).
요청 문서의 작성 예시(X1, X2, X)와 측정에서 뺀 커밋 `4667e540`은 어떤 지표에도 세지 않는다(`common.check_rows`).
"""
