# 새 clone 키 없는 기동 확인 요약 (2026-11-10)

## 대상과 조건

| 항목 | 내용 |
|---|---|
| 대상 커밋 | `e8b8059188478900d39aff3fbcc6bb95fbf98a83` (main, PR #117 병합 커밋. PR #116의 `db/109`도 포함) |
| 확인 시각 | 2026-11-10 20:35 ~ 20:58 (KST) |
| `.env` | 없음 |
| 외부 호출 | LLM, Voyage, 운영 서버 호출 0건 (모든 응답의 `usage.cost_usd`가 0.0, `calls`가 0) |
| compose 프로젝트 이름 | `provena-freshclone` (기존 컨테이너는 건드리지 않음) |
| 시험 환경 | pytest는 LLM 키 환경 변수를 지운 프로세스에서 실행 |

## 단계별 결과

| 단계 | 결과 |
|---|---|
| compose 기동 (`docker compose up`, README 순서) | 성공. db healthy, loader가 청크 23,095개를 4.6초에 적재, api 기동. 시작부터 `/health` 200까지 약 2분 20초 |
| `/health` | 200 `{"status":"ok"}` |
| 웹 화면 | `/` 200 (HTML과 `/assets/*` 모두 200), `/login` 200, `/docs` 200, 비로그인 `/me` 401 |
| 데모 계정 로그인 | 일반 사용자 200, 관리자 200 (`/me`의 role이 admin), `/threads` 200, 틀린 비밀번호 401 |
| 인용 질문 5개 | 5개 모두 200이며 인용이 붙은 `kind=answer`. 인용 섹션, 판 날짜, 출처 안내는 정상. 다만 답 본문은 녹화 재생이 아니라 "검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다)"라는 대체 문장 |
| 거절 질문 | 점심 메뉴, 구매 승인, 3만 달러 질문 모두 README 설명과 같은 거절. 녹화에 없는 질문은 "검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다." 거절 |
| `db/*.sql`로 새 DB 생성 (`db/109` 포함) | 성공. 01_init, 101~106, 109_realign, 110, 111, 120, 201, 202 순서로 실행되고 ERROR, FATAL 없음. 합쳐서 없어진 옛 표(`answer_grounding`, `recall_feedback`, `issue_table_rejections`)는 없고 `answers.grounding`, `answers.skills_used`(jsonb)가 있음 (`db_schema.md`) |
| `python -m pytest -q` 전체 (제외 없음) | 3054 passed, 94 skipped, 1 xfailed, 41 errors (4분 57초). 41건은 코드 실패가 아니라 시험용 Postgres 컨테이너의 고정 이름이 기존 컨테이너와 겹쳐 준비 단계에서 실패한 것 |
| 위 41건 재실행 (임시 Postgres 지정) | 72 passed |
| `python evals/ci_compare.py` | 통과. 단일, 멀티 14개 지표 모두 통과 |
| 정리 | `docker compose -p provena-freshclone down -v` 완료 (컨테이너, 볼륨, 네트워크 제거). 임시 Postgres 컨테이너도 제거. 기존 컨테이너는 그대로 |

## README와 다른 점

1. 녹화 미적중: README는 "LLM 키 없이 기록해 둔 응답을 재생"한다고 적었으나, 5개 질문 모두 답 본문이 대체 문장이었다. 원인은 커밋 `4f03a8d`가 `ANSWER_SYSTEM`과 `redraft_user`에 규칙을 추가해 2026-11-09 녹화의 요청 키와 맞지 않게 된 것이다. 질문 벡터 녹화는 맞아서 검색과 인용은 정상이다. 조치는 재녹화이다. 녹화가 현재 코드와 맞는지는 `python -m pytest -m demo_replay`(`tests/test_demo_replay_fresh.py`)로 키 없이 확인하고, 실패하면 `python -m backend.services.demo_record --questions data/demo_replay/questions.txt`로 다시 녹화한다.
2. 시험용 컨테이너 이름: 그 뒤 같은 브랜치에서 시험용 Postgres 컨테이너 이름을 무작위로 바꾸어, 전체 pytest의 errors가 0건이 되었다. 위 41 errors는 이 변경 전 main의 결과이다.
3. 답 저장소: 기본 compose는 `RECALL_STORE`가 비어 있어 답 저장소가 메모리이다. 질문 5건을 보내도 `answers` 표는 0행이고 `threads`만 늘어난다. 표 구조(`answers.grounding` 등)는 확인했으나, 답을 저장할 때 `grounding`이 채워지는지는 이 키 없는 기본 구성으로는 확인하지 못했다.

## 같은 폴더의 다른 파일

| 파일 | 내용 |
|---|---|
| `responses_summary.md` | 질문 10개(인용 5, 거절 4, 녹화 밖 1)의 응답 요약 |
| `db_schema.md` | `db/*.sql` 실행 순서와 `answers` 표 구조 |