# evals/newmetrics/ : 새 지표 네 개 측정기

## 이 폴더가 하는 일

SPEC 3장에서 아직 재지 않은 네 지표(답변 리콜 재현율·정밀도, 결정표 셀 정확도, 링크 추출 정확도, 함께 볼 정책 후보 정밀도)를 운영 배포판에서 잽니다. 정답은 `새 지표 정답 세트 작성 요청 (2026-11-16).md`의 표를 두 판정자가 채운 것이고, 측정기는 정답 파일을 읽기만 합니다. 요청 문서의 작성 예시(X, X1, X2)와 측정에서 뺀 커밋 `4667e540`은 어떤 지표에도 세지 않습니다(`common.check_rows`).

- 주인: 김승욱
- 입력: `evals/recall_pairs.jsonl`, `evals/decision_cells_gold.jsonl`, `evals/link_gold.jsonl`, `evals/maintenance_gold.jsonl`(`gold_convert`가 채운 md 표에서 만든다)
- 출력: 지표별 결과 폴더의 `summary.json`, `summary.md`, `rows.jsonl`

| 파일 | 역할 |
|---|---|
| `gold_convert.py` | 채운 md 표를 정답 jsonl 네 개로 바꾼다. 칸 글자는 고치지 않는다. 같은 번호에 서로 다른 내용이 있으면 멈춘다 |
| `gold_validate.py` | 위치만 기계로 확인한다(근거 문장이 커밋 직전·커밋 판 파일에 있는지, 구간 줄·링크 줄·개정 페이지 주소가 그 줄에 있는지). 틀리면 작성자에게 다시 묻는다 |
| `recall_prod.py` | 답변 리콜. 시험 페이지(rule_seq 92억대)와 평가용 일반 계정의 답을 넣고 `POST /webhooks/regulation-updated`로 운영 리콜을 돌린 뒤, 넣은 행과 리콜이 만든 행을 지워 0행을 확인한다. 활성 웹훅 구독이 있으면 넣기 전에 멈춘다. SPEC 값은 LLM 판정 기준(`judge`)이고 알림 후보 전부(`notice`)와 사용자에게 보인 알림(`user`)을 함께 기록한다 |
| `decision_prod.py` | 결정표 셀 정확도. 평가용 관리자 계정으로 `POST /decision-tables/convert?draft_only=true`를 불러 8개 업무 종류의 초안을 받는다. 운영에 쓰지 않는다. 운영 판이 초안만 모드를 모르면 측정하지 않고 멈춘다 |
| `link_eval.py` | 링크 추출 정확도. 운영 DB 읽기 전용(`chunks.link_targets`)으로 섹션 간선 정밀도·재현율·F1 |
| `maintenance_eval.py` | 함께 볼 정책 후보 정밀도. 운영 코드 `find_candidates`를 읽기 전용 `PgLinks`로 돌린다 |
| `corpus_links.py`, `handbook_history.py`, `spec_tables.py`, `common.py`, `prod.py`, `fakes.py` | 공통 부분(청크 표, 커밋별 섹션 변경, 요청 문서의 배정 표, 비용 장부, 운영 로그인, 시험용 가짜 모델) |

시험은 `tests/test_newmetrics_*.py`이며 `data/corpus`가 없으면 그 시험만 건너뜁니다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-16 | 김승욱 (Claude Code) | 측정기와 시험을 만들었다. 리콜의 넣기·처리·정리·0행 확인은 버리는 로컬 Postgres에서 예행했다(가짜 판정 모델, 0원). 결정표는 초안만 모드로 8개 업무 종류를 잰다 | 미정 |
