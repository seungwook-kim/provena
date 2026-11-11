# Provena 테이블 정의서 (재정렬 후, 2026-11-10)

이 문서는 DB 재정렬(결정 0090) 뒤의 `public` 스키마 표를 하나씩 정의한다. 기준은 `db/*.sql`의 현재 내용(작업 트리)이다. 구조 그림은 [ERD.md](ERD.md)에 있다.

## 1. 읽는 법

- 표마다 목적, 만든 마이그레이션 파일, 쓰는 코드, RLS와 권한, 칼럼 표, 색인 표를 적는다.
- 코드 위치는 `파일:줄` 또는 `파일:함수`이며 2026-11-10 작업 트리에서 `grep`으로 확인했다. 찾지 못한 것은 "코드에서 찾지 못함"이라고 적었다.
- 칼럼 표의 "키" 칸은 PK(기본키), FK(외래 키), UK(고유 제약)이다. "NULL" 칸의 `NO`는 NOT NULL이다.
- 색인 표의 "그 이유가 되는 질의"는 그 색인이 받쳐 주는 조건이나 정렬을 가진 SQL의 위치다. 제약이 만드는 색인(기본키, UNIQUE)의 이름은 PostgreSQL 기본 규칙에 따른 이름이며, 이 문서는 운영 DB에서 이름을 확인하지 않았다.
- 표마다 색인의 "이유가 되는 질의"는 `docs/db/QUERY_INDEX.md`의 질의-색인 대조표(코드의 SQL 약 150문장)와 같다. 대조 결과 색인이 없어 문제가 되는 질의는 없고, 쓰이지 않는 색인은 109가 지웠다.
- RLS와 권한은 모든 앱 표가 같다. 각 SQL 파일이 `ENABLE ROW LEVEL SECURITY`를 실행하고 정책(`CREATE POLICY`)은 어디에도 없다. 앱은 `DATABASE_URL`의 소유자 역할로 접속하므로 RLS의 영향을 받지 않는다(`db/120_answers_recall.sql:160-161`). `anon`, `authenticated` 역할의 표 권한은 `db/109_realign.sql` 단계 5(109:108-131)가 회수한다. 일반 PostgreSQL처럼 두 역할이 없으면 건너뛴다. 표마다 RLS를 켠 위치만 적는다. `signup_requests`는 106이 `PUBLIC`까지 포함해 따로 회수한다.
- 재정렬 뒤 `public` 표는 31개다. 앱 표 25개(4장)와 LangGraph 표 6개(5장)다. `db/109_realign.sql`(1단계)을 적용한 DB에는 여기에 옛 표 3개가 원래 이름으로 남고, 2단계 `db/manual/109_retire_old.sql`을 실행하면 이름이 `_old_20261110`으로 바뀌며, `db/manual/109_purge_old.sql`을 실행해야 사라진다(2-3). 운영 DB에는 1단계(2026-11-10 밤), 2단계(2026-11-11 00:42), 옛 표 삭제(2026-11-11)를 모두 적용했고, 삭제 뒤 운영 `public` 표는 이 문서와 같은 31개(앱 25 + LangGraph 6)다(적용 기록은 2-3).

## 2. 요약

"2026-11-10 운영 조회" 열은 같은 날 읽기 전용으로 조회한 운영 Supabase의 행 수와 총 크기(표와 색인과 TOAST 합)다. 조회 시점은 109 적용 전이어서 `answers`, `recall_notices`, `approvals`에는 합쳐진 칼럼의 값이 아직 없다(운영 DB에는 이후 2026-11-10 밤부터 2026-11-11까지 109를 적용했다. 2-3). 이 열 외에 운영 값은 이 문서에 쓰지 않았다.

### 2-1. 앱 표 26개

| 표 이름 | 영역 | 만든 파일 | 한 줄 설명 | 2026-11-10 운영 조회 (행 / 크기) |
|---|---|---|---|---|
| `users` | 인증 | `db/101_auth_users.sql` | 로그인 계정(아이디, 비밀번호 해시, 역할, 활성, 문서 권한 그룹) | 2행 / 48 KB |
| `signup_requests` | 인증 | `db/106_signup_approval.sql` | 회원가입 요청과 관리자 승인 기록(승인 전에는 `users` 행이 없다) | 1행 / 80 KB |
| `user_identities` | 인증 | `db/114_google_identities.sql` | 구글 계정(`sub`)과 `users` 행의 연결 | 운영 미적용(114 적용 전) |
| `user_profiles` | 인증 | `db/104_user_profiles.sql` | 내 정보(이름, 소속, 전화, 주소)의 AES-256-GCM 암호문 | 2행 / 32 KB |
| `admin_role_log` | 인증 | `db/105_admin_role_log.sql` | 화면에서 한 관리자 등록·해제 기록(쓰기만 한다) | 2행 / 48 KB |
| `token_revocations` | 인증 | `db/103_auth_token_revocations.sql` | 로그아웃한 JWT 식별자(`jti`)와 만료 시각 | 35행 / 40 KB |
| `decision_tables` | 승인 | `db/102_decision_approvals.sql` | 권한표 한 업무 종류의 결정표(셀 JSON)와 승인 상태 | 5행 / 48 KB |
| `approvals` | 승인 | `db/102_decision_approvals.sql` | 그래프가 사람 승인에서 멈춘 한 번 = 한 줄. 결정표, 쟁점표, 팀 검토 실패 알림을 `kind`로 나눈다. 반려 사유와 결정자와 결정 시각도 여기에 쓴다 | 11행 / 80 KB |
| `issue_tables` | 승인 | `db/110_issue_tables.sql` | 사람 승인을 받은 합동 검토 쟁점표 | 3행 / 136 KB |
| `threads` | 대화 | `db/111_threads.sql` | 사용자별 대화 목록(제목, 상태, 마지막 답) | 850행 / 792 KB |
| `answers` | 답변과 리콜 | `db/120_answers_recall.sql` | 답과 질문. 인용 검사 결과(`grounding`, `skills_used`)도 이 표의 칼럼이다 | 315행 / 344 KB |
| `citations` | 답변과 리콜 | `db/120_answers_recall.sql` | 답과 근거 판(청크, 판)을 묶는 인용. 리콜이 영향받는 답을 찾는 근거다 | 559행 / 304 KB |
| `recall_events` | 답변과 리콜 | `db/120_answers_recall.sql` | 바뀐 섹션 하나의 리콜 처리 기록. 같은 개정은 한 번만 판정한다 | 318행 / 160 KB |
| `recall_notices` | 답변과 리콜 | `db/120_answers_recall.sql` | 리콜 알림(답 하나와 개정 하나당 한 줄). 사용자 의견(`feedback_*`)도 이 표의 칼럼이다 | 3행 / 96 KB |
| `maintenance_candidates` | 답변과 리콜 | `db/120_answers_recall.sql` | 함께 볼 정책 후보(링크로 이어진 다른 정책)와 관리자 판단 | 964행 / 584 KB |
| `webhook_subscriptions` | 답변과 리콜 | `db/120_answers_recall.sql` | 업무시스템 웹훅 구독(비밀값은 저장하지 않고 환경변수 이름만 둔다) | 0행 / 16 KB |
| `webhook_deliveries` | 답변과 리콜 | `db/120_answers_recall.sql` | 웹훅 전송 기록(시도마다 상태 코드, 오류 종류, 시각) | 0행 / 24 KB |
| `recall_digests` | 답변과 리콜 | `db/120_answers_recall.sql` | 하루 요약(`RECALL_DIGEST=daily`)과 웹훅으로 보낸 JSON | 0행 / 24 KB |
| `change_monitoring` | 답변과 리콜 | `db/120_answers_recall.sql` | 변경 감시 스위치(한 줄). `paused`이면 증분 수집이 쉰다 | 1행 / 32 KB |
| `docs` | 검색 | `db/201_search.sql` | 코퍼스 페이지(조직, 제목, 주소) | 1,516행 / 416 KB |
| `versions` | 검색 | `db/201_search.sql` | 페이지의 판과 유효 구간 `[valid_from, valid_to)` | 1,798행 / 368 KB |
| `chunks` | 검색 | `db/201_search.sql` | 판별 청크 본문, 벡터, 문서 권한 그룹, 링크 대상 | 30,171행 / 264.1 MB |
| `index_meta` | 검색 | `db/201_search.sql` | 색인 장부(지금 적재된 임베딩 모델, 상태, generation) | 1행 / 32 KB |
| `query_translations` | 검색 | `db/201_search.sql` | 질문 번역 장부(같은 질문과 모델이면 LLM을 다시 부르지 않는다) | 692행 / 432 KB |
| `sync_runs` | 증분 수집 | `db/202_sync.sql` | 정해진 시각 증분 수집 한 번의 실행 기록 | 1행 / 64 KB |
| `changed_articles` | 증분 수집 | `db/202_sync.sql` | 리콜에 넘길 바뀐 섹션 | 318행 / 152 KB |

운영 조회 시점의 데이터베이스 전체 크기는 340.6 MB였다.

### 2-2. LangGraph 표 6개

| 표 이름 | 영역 | 만든 곳 | 한 줄 설명 | 2026-11-10 운영 조회 (행 / 크기) |
|---|---|---|---|---|
| `checkpoints` | LangGraph | 라이브러리 `.setup()` | 그래프 체크포인트 본체(`checkpoint` jsonb, 메타데이터) | 7,495행 / 15.2 MB |
| `checkpoint_blobs` | LangGraph | 라이브러리 `.setup()` | 채널 값 바이너리 | 20,813행 / 13.2 MB |
| `checkpoint_writes` | LangGraph | 라이브러리 `.setup()` | 체크포인트에 딸린 중간 쓰기 | 54,942행 / 31.9 MB |
| `checkpoint_migrations` | LangGraph | 라이브러리 `.setup()` | 체크포인트 표 마이그레이션 버전 | 10행 / 24 KB |
| `store` | LangGraph | 라이브러리 `.setup()` | Store 항목. `backend/memory/profile.py`가 사용자 프로필(소속과 직급)을 넣는다 | 0행 / 56 KB |
| `store_migrations` | LangGraph | 라이브러리 `.setup()` | Store 표 마이그레이션 버전 | 4행 / 24 KB |

### 2-3. 합쳐진 옛 표 3개 (1단계 뒤 원래 이름으로 남고, 2단계 뒤 이름만 바뀌며, `db/manual/109_purge_old.sql` 뒤에 사라진다)

`db/109_realign.sql`(1단계)은 새 칸에 값을 복사만 하고 옛 표를 건드리지 않아서, 옛 코드가 계속 돈다. 새 코드를 배포하고 옛 리비전이 내려간 뒤 `db/manual/109_retire_old.sql`(2단계)이 그 사이에 옛 표에 쌓인 값을 새 칸으로 한 번 더 옮기고 옛 표 이름을 바꾼다. 새 코드는 이 표를 읽지도 쓰지도 않는다.

**운영 DB 적용 기록(2026-11-10~11-11).** 1단계는 2026-11-10 밤에 적용했고, 새 칸 9개와 색인 3개가 생겼으며 `answers.grounding`은 371행 중 371행이 채워졌다. 새 코드를 배포하고 옛 리비전을 내린 뒤 2단계를 2026-11-11 00:42에 실행했다. 옛 표 3개의 이름이 `_old_20261110`으로 바뀌었고 이때 `public` 표는 34개였으며 `answers`는 519행 중 519행이 채워졌고 오류 로그는 0건이었다. 옛 표는 2026-11-11에 삭제했다. 삭제 전에 옛 표의 행이 새 칸에 빠진 것이 0건임을 확인했고, 삭제 뒤 `public` 표는 31개, 오류 로그 0건, `/health` 200이었다. 코드가 쓰지 않아 지우기로 한 색인 7개가 삭제된 것도 확인했다.

| 옛 표 이름 (바뀐 이름) | 합친 곳 | 109 적용 전 운영 조회 (행 / 크기) | 1단계 적용 시점 행 수 |
|---|---|---|---|
| `answer_grounding` (`answer_grounding_old_20261110`) | `answers.grounding`, `answers.skills_used` | 315행 / 152 KB | 371행 |
| `recall_feedback` (`recall_feedback_old_20261110`) | `recall_notices.feedback_*` | 1행 / 48 KB | 1행 |
| `issue_table_rejections` (`issue_table_rejections_old_20261110`) | `approvals.comment`, `approvals.decided_by`, `approvals.decided_at` | 2행 / 32 KB | 2행 |

### 2-4. 마이그레이션 파일

`db/` 바로 아래 `.sql`만 compose 초기화와 시험이 이름 순서로 실행한다. `db/manual/` 아래는 사람이 직접 실행한다(`db/manual/chunks_hnsw_voyage4.sql:2-3`, `db/manual/109_retire_old.sql:1`, `db/manual/109_purge_old.sql:2`). 번호대는 100번대가 인증·승인·대화·답변·리콜, 200번대가 검색·데이터다(`db/101_auth_users.sql:2`, `db/201_search.sql:1`).

| 파일 | 만드는 것 |
|---|---|
| `db/01_init.sql` | 확장 `vector` |
| `db/101_auth_users.sql` | `users` |
| `db/102_decision_approvals.sql` | `decision_tables`, `approvals` |
| `db/103_auth_token_revocations.sql` | `token_revocations` |
| `db/104_user_profiles.sql` | `user_profiles` |
| `db/105_admin_role_log.sql` | `admin_role_log` |
| `db/106_signup_approval.sql` | `signup_requests` |
| `db/109_realign.sql` | 새 표를 만들지 않는다. 옛 모양 DB에 합친 칸을 더하고 값을 복사하며 색인을 정리한다(1단계, 3장) |
| `db/manual/109_retire_old.sql` | 2단계. 1단계 뒤에 옛 표에 쌓인 값을 새 칸으로 옮기고 옛 표 3개의 이름을 `_old_20261110`으로 바꾼다 |
| `db/110_issue_tables.sql` | `issue_tables` |
| `db/111_threads.sql` | `threads` |
| `db/112_approval_resume_log.sql` | 새 표를 만들지 않는다. `approvals`에 칸 4개(`resume_count`, `duplicate_ignored_count`, `last_resumed_at`, `last_resume_result`)를 더한다. 승인 결정이 그래프를 재개한 횟수와 같은 결정의 재전송이 무시된 횟수를 `GET /approvals/{approval_id}`로 읽는다. 적용 전에도 앱은 동작하고 재개 기록만 남지 않는다 |
| `db/120_answers_recall.sql` | `answers`, `citations`, `recall_events`, `recall_notices`, `maintenance_candidates`, `webhook_subscriptions`, `webhook_deliveries`, `recall_digests`, `change_monitoring` |
| `db/201_search.sql` | `docs`, `versions`, `chunks`, `index_meta`, `query_translations` |
| `db/202_sync.sql` | `sync_runs`, `changed_articles` |
| `db/114_google_identities.sql` | `user_identities`(새 표), `signup_requests.google_sub` 칸, `users`·`signup_requests`의 `password_hash` NULL 허용 |
| `db/manual/chunks_hnsw_voyage4.sql` | `chunks` 부분 HNSW 색인 `chunks_emb_hnsw_half` |
| `db/manual/109_purge_old.sql` | 이름이 바뀐 옛 표 3개를 `DROP TABLE IF EXISTS`로 지운다 |

번호 107, 108은 이 브랜치에 없다. PR #113(미머지)이 이메일 가입 인증용으로 쓸 예정이라고 `db/109_realign.sql:2-3`에 적혀 있다.

## 3. 재정렬 변경 요약

### 3-1. 합친 표 3개

재정렬 전 `public` 표는 34개(앱 표 28 + LangGraph 6)였고 후에는 31개(앱 표 25 + LangGraph 6)다. 합친 표는 아래 3개다.

| 옛 표 | 합친 곳 | 옮기는 방법 | 코드 쪽 |
|---|---|---|---|
| `answer_grounding` | `answers.grounding`, `answers.skills_used` (둘 다 jsonb, NULL 허용) | 109 단계 1(109:21-33)이 칼럼을 더하고 `answer_id`로 값을 복사한다(새 칸이 NULL인 줄만). 옛 표 이름은 2단계(`109_retire_old.sql`)가 바꾼다 | `backend/graph/answer_store.py:152-159, 196-207`. NULL은 "아직 기록하지 않음"이며 옛 표에 줄이 없던 것과 같다(`db/120_answers_recall.sql:15`) |
| `recall_feedback` | `recall_notices.feedback_useful`, `feedback_reason`, `feedback_by`, `feedback_at` | 109 단계 2(109:35-59)가 칼럼과 부분 색인 `recall_notices_feedback_idx`를 만들고 `notice_id`로 복사한다(새 칸이 NULL인 줄만). 알림이 없는 의견 행은 옛 표에만 남고 `NOTICE`로 알린다(109:51-55) | `backend/graph/recall/store.py:353-368` |
| `issue_table_rejections` | `approvals.comment`, `approvals.decided_by`, `approvals.decided_at` (칼럼은 102가 이미 갖고 있었다) | 109 단계 3(109:61-75)이 `approval_id`와 `kind = 'issue_table'`이 같은 줄에 사유(`comment`가 빈 문자열일 때), 결정자, 시각을 채운다 | `backend/graph/departments/store.py:77-85` |

1단계는 옛 표와 옛 칸을 건드리지 않아서 옛 코드를 다시 배포하면 되돌아간다(109:15). 2단계가 옛 표를 `<이름>_old_20261110`으로 이름만 바꾸며(데이터 그대로), 같은 이름이 이미 있으면 바꾸지 않고 `NOTICE`만 낸다. 2단계 뒤에 되돌리려면 새 코드를 내리고 이름을 원래대로 바꾼다(109:16-17). 완전히 지우는 파일은 `db/manual/109_purge_old.sql`이며, 되돌릴 수 없으므로 백업 뒤에 수동으로 실행한다(같은 파일 5-6줄).

새 DB는 110, 120, 105 파일이 이미 합친 구조로 만든다. 109는 모든 단계가 "있을 때만" 움직여서 어느 순서로 실행해도, 여러 번 실행해도 같은 결과가 된다(109:4-5).

### 3-2. 색인 변화

| 구분 | 색인 | 정의 | 이유 |
|---|---|---|---|
| 삭제 | `answers_user_idx` | `answers (user_id, created_at DESC)` | `answers`를 `user_id`로 찾는 질의가 코드에 없다(`db/120_answers_recall.sql:21`) |
| 삭제 | `issue_tables_thread_idx` | `issue_tables (thread_id)` | 세 열 색인 하나로 대체 |
| 삭제 | `issue_tables_user_idx` | `issue_tables (user_id, approved_at DESC)` | 세 열 색인 하나로 대체 |
| 삭제 | `admin_role_log_at` | `admin_role_log (at)` | 이 표를 읽는 질의가 코드에 없다(`db/105_admin_role_log.sql:12`) |
| 삭제 | `token_revocations_expires_at` | `token_revocations (expires_at)` | 만료 행을 지우는 코드가 없고 조회는 `jti` 기본키로 한다(`auth_store.py:402`). 정리 작업을 만들 때 다시 만든다 |
| 삭제 | `signup_requests_status_requested_at` | `signup_requests (status, requested_at)` | `status`로 거르는 질의가 없다. 목록(`auth_store.py:298`)은 조건 없이 전체를 읽는다 |
| 삭제 | `recall_notices_review_idx` | `recall_notices (created_at DESC) WHERE review_status = 'pending'` | 검토함은 `notices_all()`로 전부 읽어 앱에서 거른다(`recalls.py:181-185`). 쓰는 질의가 없다 |
| 추가 | `chunks_link_targets_gin` | `chunks USING gin (link_targets)` | 함께 볼 정책 찾기 `maintenance.py:62-69`가 `link_targets @> ARRAY[대상]`로 찾는다. 로컬 합성 데이터(chunks 30,171행)에서 chunks 전체 훑기 8.969 ms, 버퍼 26,159에서 GIN 비트맵 스캔 버퍼 56으로 줄었다(`docs/db/QUERY_INDEX.md`) |
| 추가 | `issue_tables_thread_user_idx` | `issue_tables (thread_id, user_id, approved_at DESC)` | 유일한 조회 `PgIssueTableStore.get_by_thread`의 조건과 정렬을 받는다(`backend/graph/departments/store.py:89-90`) |
| 추가 | `recall_notices_feedback_idx` | `recall_notices (user_id, change_pattern, (changed ->> 'article'), ((changed ->> 'rule_seq')::bigint)) WHERE feedback_useful IS NOT NULL` | 의견 집계 질의 `feedback_counts`(`backend/graph/recall/store.py:357-362`). 의견이 있는 알림만 색인한다 |

삭제 근거는 109:77에 "운영 조회 2026-11-10, 통계 초기화 2026-10-29 이후 `idx_scan` 0이고 코드에 그 열로 찾는 질의가 없다"로 적혀 있다. 색인을 되돌리려면 위 정의를 다시 실행한다(109:19, 78-91).

### 3-3. 권한 회수

- `db/109_realign.sql` 단계 5(109:108-131)가 `public`의 표, 파티션 표, 뷰, 구체화 뷰, 시퀀스에서 `anon`과 `authenticated`의 권한을 모두 회수하고, 이후 만들어지는 표와 시퀀스의 기본 권한도 회수한다. 두 역할이 없는 일반 PostgreSQL에서는 건너뛴다.
- 회수한 이유는 109:108-109에 적혀 있다. 운영 Supabase가 `public`의 모든 표에 두 역할 권한을 열어 두었고(RLS가 막고 있었다), RLS에 더해 권한도 거두어 이중으로 잠그는 것이다. 앱은 소유자 역할로 접속하므로 영향이 없다(109:13).
- `ALTER DEFAULT PRIVILEGES`는 그 문장을 실행한 역할이 이후 만드는 객체에 적용되는 PostgreSQL 규칙이다. LangGraph 표를 만드는 앱 접속 역할이 109를 실행한 역할과 같은지는 코드에서 알 수 없다.
- `signup_requests`는 비밀번호 해시를 담아서 106이 먼저 `PUBLIC`, `anon`, `authenticated`의 권한을 회수한다(`db/106_signup_approval.sql:14-28`).

## 4. 앱 표 25개

### 4-1. 인증

#### 4-1-1. `users`

- 목적: 로그인 계정. 비밀번호는 bcrypt 해시로 저장하고(`db/101_auth_users.sql:1`) 역할은 `user`와 `admin` 둘뿐이다.
- 만든 파일: `db/101_auth_users.sql:6-16`.
- 쓰는 코드: `backend/services/auth_store.py`의 `PostgresAuthStore`(192줄) — `get_by_login_id` 207-208, `get_by_user_id` 210-215, `upsert_user` 230-242(로컬 데모 시드, 호출은 `backend/services/demo_seed.py:53`), `create_user` 244-252, `set_password` 254-259, `review_signup_request`의 승인 시 `_insert_user` 304-343, `list_users` 345-351, `set_role` 353-380, `ensure_schema` 382-386.
- `groups`: 읽는 SELECT를 코드에서 찾지 못했다. `auth_store.py:29`의 조회 칼럼 목록(`_COLUMNS`)에 `groups`가 없고, 인증 객체 `AuthUser.groups`(`backend/auth.py:500`)는 기본값 `()`이다. 이 값을 쓰는 곳은 `backend/api/recalls.py:126, 128`과 `backend/graph/recall/service.py:163-173`(알림 가시성)이다.
- RLS와 권한: RLS 켬(`db/101_auth_users.sql:16`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `user_id` | `uuid` | NO | `gen_random_uuid()` | PK | 사용자 id |
| `login_id` | `text` | NO | | UK | 로그인 아이디 |
| `password_hash` | `text` | NO(114 적용 뒤 YES) | | | bcrypt 해시. 구글로만 만든 계정은 NULL |
| `role` | `text` | NO | | | `user` 또는 `admin`(CHECK) |
| `is_active` | `boolean` | NO | `true` | | 활성 여부 |
| `groups` | `text[]` | NO | `'{}'` | | 문서 권한 그룹. F-06(문서 권한) 연결 지점이다 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `users_pkey` | `PRIMARY KEY (user_id)` | `auth_store.py:215`(`WHERE user_id = %s`), `375`(`UPDATE ... WHERE user_id = %s`) |
| `users_login_id_key` | `UNIQUE (login_id)` | `auth_store.py:208`, `235-237`(`ON CONFLICT (login_id)`), `250`, `265`, `321`, `365` |
| `users_login_id_lower_unique` | `UNIQUE (lower(login_id)) WHERE position('@' in login_id) > 0` (`db/113`, 대소문자만 다른 이메일 계정이 이미 있으면 만들지 않음) | `get_by_login_id`·`create_pending_user`의 이메일 조회(`lower(login_id) = lower(%s)`) |

#### 4-1-2. `signup_requests`

- 목적: 회원가입 요청과 관리자 승인 기록. 승인 전에는 `users` 행이 없어서 `user_id`가 NULL이다(`auth_store.py:278-282`). 비밀번호 해시를 담는다.
- 만든 파일: `db/106_signup_approval.sql:2-12`(표와 색인), `:15`(RLS), `:16-28`(권한 회수).
- 쓰는 코드: `backend/services/auth_store.py` — `get_signup_by_login_id` 217-228, `create_pending_user` 261-276, `get_signup_status` 278-293, `list_signup_requests` 295-302, `review_signup_request` 304-332. `ensure_schema`(382-386)는 106 파일도 실행한다.
- 주석: PR #113(미머지)이 이 표에 이메일 인증 칸을 더하고 `db/107`, `db/108` 파일을 쓸 예정이다. 이 브랜치에는 그 칸과 파일이 없다.
- RLS와 권한: RLS 켬(`db/106_signup_approval.sql:15`), 정책 없음. `PUBLIC`, `anon`, `authenticated` 권한을 106이 회수한다(16-28).

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `request_id` | `bigint` | NO | `GENERATED ALWAYS AS IDENTITY` | PK | 요청 번호 |
| `user_id` | `uuid` | YES | | FK `users(user_id)`, UK | 승인되어 `users` 행이 생긴 뒤에만 채운다 |
| `login_id` | `text` | NO | | UK | 요청한 로그인 아이디 |
| `password_hash` | `text` | NO(114 적용 뒤 YES) | | | 요청 때 받은 비밀번호 해시. 구글 가입 신청은 NULL |
| `status` | `text` | NO | | | `pending`, `approved`, `rejected`(CHECK) |
| `requested_at` | `timestamptz` | NO | `now()` | | 요청 시각 |
| `reviewed_at` | `timestamptz` | YES | | | 검토 시각 |
| `reviewed_by` | `uuid` | YES | | FK `users(user_id)` | 검토한 관리자 |
| `google_sub` | `text` | YES | | UK(부분) | 114가 더한 칸. 구글 가입 신청의 sub. 승인하면 `user_identities`로 옮긴다. `password_hash`와 둘 중 하나는 있어야 한다(CHECK `signup_requests_secret_or_google`) |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `signup_requests_pkey` | `PRIMARY KEY (request_id)` | `auth_store.py:329`(`WHERE request_id = %s`), `225`, `313`(`ORDER BY request_id DESC`) |
| `signup_requests_user_id_key` | `UNIQUE (user_id)` | `auth_store.py:290`(`WHERE user_id = %s AND status = 'approved'`) |
| `signup_requests_login_id_open_unique` | `UNIQUE (login_id) WHERE status <> 'rejected'` (`db/113`가 `signup_requests_login_id_key`를 대체) | `auth_store.py`의 `create_pending_user`(중복 아이디를 UNIQUE 위반으로 감지), `get_signup_by_login_id`·`review_signup_request`(`ORDER BY request_id DESC`) |
| `signup_requests_login_id_lower_open_unique` | `UNIQUE (lower(login_id)) WHERE position('@' in login_id) > 0 AND status <> 'rejected'` (`db/113`가 107의 `signup_requests_login_id_lower_unique`를 대체. 이 색인이 있으면 107을 다시 돌려도 옛 색인을 되살리지 않는다) | 이메일 대소문자 중복 가입 방지 |

#### 4-1-2a. `user_identities`

- 목적: 구글 계정(`sub`)과 `users` 행의 연결. 구글이 인증한 이메일이 기존 계정 로그인 아이디와 정확히 같을 때 한 줄을 더하고, 구글 가입 신청을 승인할 때도 한 줄을 더한다. 로그인할 때는 `(provider, subject)`로만 계정을 찾고 `email`은 참고용이다.
- 만든 파일: `db/114_google_identities.sql`(표, RLS, 권한 회수).
- 쓰는 코드: `backend/services/auth_store.py` — `get_or_create_google_user`, `_google_resolve`, `review_signup_request`(구글 신청 승인).
- RLS와 권한: RLS 켬, 정책 없음. `PUBLIC`과(역할이 있을 때만) `anon`, `authenticated` 권한을 114가 회수한다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `provider` | `text` | NO | | PK, UK, CHECK(`google`) | 로그인 방식 |
| `subject` | `text` | NO | | PK | 구글 `sub` |
| `user_id` | `uuid` | NO | | UK, FK `users(user_id)` `ON DELETE CASCADE` | 연결된 계정 |
| `email` | `text` | NO | | | 마지막으로 본 구글 이메일 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `user_identities_pkey` | `PRIMARY KEY (provider, subject)` | 로그인 때 `WHERE provider = %s AND subject = %s`, 동시 첫 로그인의 `ON CONFLICT` |
| `user_identities_provider_user_id_key` | `UNIQUE (provider, user_id)` | 한 계정에 구글 계정 하나만 연결(다른 구글 계정의 연결 시도 차단) |

#### 4-1-3. `user_profiles`

- 목적: 내 정보. 이름, 소속, 전화, 주소를 각각 nonce 12바이트 + AES-256-GCM 암호문 + 태그 16바이트로 저장하며 평문 칸은 없다(`db/104_user_profiles.sql:3`). 관리자 목록과 로그인 조회는 이 표를 읽지 않는다(104:4).
- 만든 파일: `db/104_user_profiles.sql:6-16`.
- 쓰는 코드: `backend/services/profile_store.py`의 `PostgresProfileStore`(57줄) — `ensure_schema` 65-67, `get` 69-72, `exists` 74-76, `upsert` 78-89. 암호화는 `backend/services/profile_crypto.py`, API는 `backend/profile_api.py:179, 194`. 생성은 `backend/main.py:286`.
- RLS와 권한: RLS 켬(`db/104_user_profiles.sql:16`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `user_id` | `uuid` | NO | | PK, FK `users(user_id)` `ON DELETE CASCADE` | 사용자 id |
| `name_enc` | `bytea` | NO | | | 이름 암호문 |
| `dept_enc` | `bytea` | NO | | | 소속 암호문 |
| `phone_enc` | `bytea` | NO | | | 전화 암호문 |
| `address_enc` | `bytea` | NO | | | 주소 암호문 |
| `key_version` | `smallint` | NO | | | 어느 키로 잠갔나(`key_version > 0` CHECK, 키 교체용 `PROFILE_ENC_KEYS`) |
| `updated_at` | `timestamptz` | NO | `now()` | | 수정 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `user_profiles_pkey` | `PRIMARY KEY (user_id)` | `profile_store.py:71`, `76`, `83`(`ON CONFLICT (user_id)`) |

#### 4-1-4. `admin_role_log`

- 목적: 화면(최고 관리자)에서 한 관리자 등록·해제 기록. 누가, 누구를, 무엇을, 언제만 남긴다. `create_account` 명령으로 만든 계정은 남지 않는다(`db/105_admin_role_log.sql:3-4`).
- 만든 파일: `db/105_admin_role_log.sql:5-14`.
- 쓰는 코드: 쓰기 `backend/services/auth_store.py:376-379`(`set_role` 안, 역할 변경과 한 트랜잭션). 이 표를 읽는 질의는 코드에서 찾지 못했다.
- RLS와 권한: RLS 켬(`db/105_admin_role_log.sql:14`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `log_id` | `bigint` | NO | `GENERATED ALWAYS AS IDENTITY` | PK | 기록 번호 |
| `at` | `timestamptz` | NO | `now()` | | 시각 |
| `by_user_id` | `uuid` | NO | | FK `users(user_id)` | 바꾼 관리자 |
| `target_user_id` | `uuid` | NO | | FK `users(user_id)` | 대상 사용자 |
| `action` | `text` | NO | | | `promote` 또는 `revoke`(CHECK) |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `admin_role_log_pkey` | `PRIMARY KEY (log_id)` | 코드에서 찾지 못함. 읽는 질의가 없고 기본키는 표 정의에 따른 것이다 |

`at` 색인(`admin_role_log_at`)은 109가 지웠다(3-2).

#### 4-1-5. `token_revocations`

- 목적: 로그아웃한 JWT의 `jti`를 토큰 만료까지 보관해서, 모든 API 인스턴스가 이미 로그아웃한 세션을 거부한다(`db/103_auth_token_revocations.sql:1-2`).
- 만든 파일: `db/103_auth_token_revocations.sql:4-13`.
- 쓰는 코드: `backend/services/auth_store.py`의 `PostgresTokenRevocationStore`(389줄) — `is_revoked` 399-405, `revoke` 407-413. 생성은 `backend/main.py:283`.
- RLS와 권한: RLS 켬(`db/103_auth_token_revocations.sql:13`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `jti` | `uuid` | NO | | PK | JWT 식별자 |
| `expires_at` | `timestamptz` | NO | | | 토큰 만료 시각 |
| `revoked_at` | `timestamptz` | NO | `now()` | | 폐기 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `token_revocations_pkey` | `PRIMARY KEY (jti)` | `auth_store.py:402`(`WHERE jti = %s AND expires_at > now()`), `410-411`(`ON CONFLICT (jti)`) |

### 4-2. 승인

#### 4-2-1. `decision_tables`

- 목적: 권한표 한 업무 종류(행 묶음)의 결정표. `cells`는 `DecisionRule` 목록(JSON, `backend/schemas/decision.py`)이다. 승인된 표만 실행한다(J-07). 승인자 없는 `approved`는 DB가 거부한다(`db/102_decision_approvals.sql:7-8`).
- 만든 파일: `db/102_decision_approvals.sql:9-19`.
- 쓰는 코드: `backend/graph/decision/repo.py`의 `PostgresDecisionRepo`(213줄) — `queue_draft`의 INSERT 259-261, `decide`의 SELECT 279와 UPDATE 284-285, `get_table` 327-331, `list_approved` 336-337, `find_approved` 339-340.
- RLS와 권한: RLS 켬(`db/102_decision_approvals.sql:46`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `table_id` | `text` | NO | | PK | 결정표 id |
| `rule_seq` | `bigint` | NO | | | 권한표 페이지 id. `docs.rule_seq`와 같은 값이며 `201`보다 먼저 만들어져 외래 키는 걸지 않았다(102:11) |
| `version_id` | `text` | NO | | | 권한표 판(커밋 앞 12자) |
| `cells` | `jsonb` | NO | | | `DecisionRule` 목록 |
| `status` | `text` | NO | `'draft'` | | `draft`, `approved`, `rejected`(CHECK) |
| `approved_by` | `text` | YES | | | 승인한 관리자 `user_id`. `draft`, `rejected`에서는 비어 있다. CHECK `(status = 'approved') = (approved_by IS NOT NULL)` |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `decision_tables_pkey` | `PRIMARY KEY (table_id)` | `repo.py:279`, `328`, `284-285`(`WHERE table_id = %s`) |
| `decision_tables_status` | `(status)` | `repo.py:337`(`WHERE status = 'approved' ORDER BY table_id`) |

#### 4-2-2. `approvals`

- 목적: 승인 건. 그래프가 `interrupt`로 멈춘 한 번이 한 줄이고 `thread_id`로 같은 대화를 재개한다. `kind`로 결정표(`decision_table`), 쟁점표(`issue_table`), 팀 검토 실패 알림(`team_review_failed`)을 나눈다(102:29-30). 재정렬 뒤에는 쟁점표 반려 사유(`comment`), 결정자(`decided_by`), 결정 시각(`decided_at`)도 이 표가 갖는다.
- 만든 파일: `db/102_decision_approvals.sql:22-43`(표 22-28, `kind` 제약 29-30, 고유 색인 34-35, 칼럼 추가 37-41, 대기 색인 42, `status` 설명 43). `comment`, `decided_by`, `decided_at` 칼럼은 102에 이미 있었고, 109 단계 3(109:61-75)이 옛 `issue_table_rejections`의 값을 옮겼다.
- 쓰는 코드: `backend/graph/decision/repo.py` — `queue_draft` 248-265, `decide` 267-286, `queue_review_item` 288-302, `decide_review_item` 304-319, `get_approval` 321-325, `list_pending` 333-334. `backend/graph/departments/store.py:77-85`(`record_rejection`)이 반려 사유를 쓴다. 같은 승인 건의 결정을 하나씩 처리하는 자문 잠금(`decision_lock`, repo.py:231-246)은 이 표의 행이 아니라 `approval_id` 문자열로 건다.
- RLS와 권한: RLS 켬(`db/102_decision_approvals.sql:47`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `approval_id` | `text` | NO | | PK | 승인 건 id |
| `kind` | `text` | NO | | | `decision_table`, `issue_table`, `team_review_failed`(CHECK `approvals_kind_check`) |
| `thread_id` | `text` | NO | | | 그래프 thread 이름 `<user_id>:<thread_id>`(`backend/api/routes.py:312`) |
| `status` | `text` | NO | `'pending'` | | `pending`, `approved`, `rejected`(CHECK). `team_review_failed`의 읽는 법은 `COMMENT ON COLUMN`(102:43)에 있다 |
| `decided_by` | `text` | YES | | | 결정한 사용자 id |
| `summary` | `text` | NO | `''` | | 승인함 화면(`ApprovalItem`) 요약 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |
| `comment` | `text` | NO | `''` | | 결정 사유. 쟁점표 반려 사유가 여기에 쓰인다 |
| `decided_at` | `timestamptz` | YES | | | 결정 시각 |
| `target_id` | `text` | YES | | | 승인 대상 id. 결정표면 `table_id`, 쟁점표면 승인 전 `approval_id`와 승인 뒤 저장된 `table_id`, 팀 실패 알림이면 `approval_id`(102:41) |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `approvals_pkey` | `PRIMARY KEY (approval_id)` | `repo.py:272`, `310`(`FOR UPDATE`), `322`, `282`, `317-318` |
| `approvals_decision_thread` | `UNIQUE (thread_id) WHERE kind = 'decision_table'` | `repo.py:255`(`WHERE thread_id = %s AND kind = %s`). 재개 때 노드가 다시 돌아도 결정표 승인 건이 대화마다 1건이 되게 한다(102:31) |
| `approvals_review_pending` | `UNIQUE (thread_id) WHERE kind <> 'decision_table' AND status = 'pending'` | `repo.py:293`, `297`(`WHERE thread_id = %s AND kind <> %s`). 합동 검토는 대화마다 대기 건이 1건이게 한다(102:32) |
| `approvals_pending` | `(created_at) WHERE status = 'pending'` | `repo.py:334`(`WHERE status = 'pending' ORDER BY created_at`) |

#### 4-2-3. `issue_tables`

- 목적: 합동 검토 쟁점표 저장(F-03, B-11). 사람 승인(`approve=true`)이 들어온 뒤에만 한 줄이 생기고, 승인 전이거나 반려된 표는 넣지 않는다(`db/110_issue_tables.sql:1`). `approvals`와 외래 키로 묶지 않고 `approval_id` 문자열을 같은 값으로 맞춘다(110:5).
- 만든 파일: `db/110_issue_tables.sql:6-20`.
- 쓰는 코드: `backend/graph/departments/store.py`의 `PgIssueTableStore`(59줄) — `save` 65-75, `get_by_thread` 87-99. 생성은 `backend/graph/decision/routes.py:487`.
- RLS와 권한: RLS 켬(`db/110_issue_tables.sql:26`), 정책 없음.
- `user_id`는 text이며 `users.user_id`(uuid)에 대한 외래 키가 없다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `table_id` | `uuid` | NO | `gen_random_uuid()` | PK | 쟁점표 id |
| `approval_id` | `text` | NO | | UK | 같은 승인으로 두 번 저장되지 않는다(재개가 겹쳐도 한 줄) |
| `thread_id` | `text` | NO | | | 대화 이름 |
| `user_id` | `text` | NO | | | 검토를 요청한 사용자 |
| `request` | `text` | NO | | | 요청 원문 |
| `as_of` | `date` | YES | | | 검색 기준일 |
| `issue_rows` | `jsonb` | NO | | | 쟁점 행 배열(CHECK `jsonb_typeof = 'array'`). 한 행의 모양은 `backend/graph/departments/issue_table.py`의 `ROW_FIELDS`가 정한다(110:3-4) |
| `unreviewed` | `jsonb` | NO | `'[]'::jsonb` | | 검토하지 못한 팀과 이유(배열 CHECK) |
| `approved_by` | `text` | YES | | | 승인한 관리자 `user_id` |
| `approved_at` | `timestamptz` | NO | `now()` | | 승인 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `issue_tables_pkey` | `PRIMARY KEY (table_id)` | `table_id`로 찾는 SQL은 코드에서 찾지 못함 |
| `issue_tables_approval_id_key` | `UNIQUE (approval_id)` | `store.py:69`(`ON CONFLICT (approval_id)`) |
| `issue_tables_thread_user_idx` | `(thread_id, user_id, approved_at DESC)` | `store.py:89-90`(`WHERE thread_id = %s AND user_id = %s ORDER BY approved_at DESC LIMIT 1`) |

### 4-3. 대화

#### 4-3-1. `threads`

- 목적: 사용자별 대화(thread) 목록(G4, SDD 4-4 `/threads`). 대화 내용 전체는 여기에 두지 않고 LangGraph 체크포인트에 있다. `last`는 마지막 답 `{kind, answer, answer_id, as_of}` 하나다(`db/111_threads.sql:4`). 모든 조회에 `user_id` 조건을 붙여 남의 대화는 보이지 않는다(111:2).
- 만든 파일: `db/111_threads.sql:6-16`.
- 쓰는 코드: `backend/api/threads.py`의 `PostgresThreadStore`(99줄) — `ensure_schema` 116-119(로컬 데모만), `thread_touch` 121-131, `thread_get` 133-135, `threads_of` 137-139. 호출은 `backend/api/routes.py:217, 255, 272, 281, 293, 301, 314`, 생성은 `backend/main.py:250`.
- RLS와 권한: RLS 켬(`db/111_threads.sql:19`), 정책 없음.
- `user_id`는 text이며 `users.user_id`(uuid)에 대한 외래 키가 없다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `user_id` | `text` | NO | | PK | 로그인한 사용자 `user_id`(쿠키에서만 얻는다) |
| `thread_id` | `text` | NO | | PK | 화면이 보냈거나 서버가 만든 바깥 이름. 그래프와 체크포인트에는 `<user_id>:<thread_id>`를 쓴다 |
| `title` | `text` | NO | `''` | | 첫 질문 앞 80자 |
| `status` | `text` | NO | `'idle'` | | `idle`, `running`, `pending_approval`(CHECK) |
| `last` | `jsonb` | YES | | | 마지막 답. 아직 없으면 NULL |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |
| `updated_at` | `timestamptz` | NO | `now()` | | 수정 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `threads_pkey` | `PRIMARY KEY (user_id, thread_id)` | `threads.py:129`(`ON CONFLICT (user_id, thread_id)`), `134` |
| `threads_user_updated_idx` | `(user_id, updated_at DESC)` | `threads.py:138`(`WHERE user_id = %s ORDER BY updated_at DESC, created_at DESC`) |

### 4-4. 답변과 리콜

앱은 `RECALL_STORE=postgres`일 때만 이 영역의 표를 쓴다. 비우면 메모리 저장소다(`db/120_answers_recall.sql:3`). 로컬 데모 모드에서는 앱이 시작할 때 120을 실행하고(`backend/graph/recall/runtime.py:29`), 운영 Supabase에서는 `db/db.md` 절차대로 직접 실행한다.

#### 4-4-1. `answers`

- 목적: 답. `as_of`는 질문의 기준일(YYYY-MM-DD, 없으면 NULL = 그때의 현재 판)이다. `thread_id`는 그래프 이름 `<user_id>:<thread_id>` 그대로다(`db/120_answers_recall.sql:6`). 재정렬 뒤에는 옛 `answer_grounding`의 인용 검사 결과를 `grounding`, `skills_used`로 갖는다.
- 만든 파일: `db/120_answers_recall.sql:7-20`(표 7-17, 칼럼 추가 19-20), 옛 DB 이전 `db/109_realign.sql:21-33`.
- 쓰는 코드: `backend/graph/answer_store.py`의 `PgAnswerStore`(123줄) — `save` 138-150, `save_with_grounding` 152-159, `_insert_answer` 174-194, `save_grounding` 196-199, `get_grounding` 201-207, `get` 209-219, `find_by_article` 221-228. 호출은 `backend/graph/build.py:1449-1454`, 생성은 `backend/graph/recall/runtime.py:39`.
- `grounding`: 인용 검사 결과(밖으로 낼 수 있는 값만). MCP 도구 `get_grounding`이 읽는다(`answer_store.py:201-207`, 읽을 때 `grounding IS NOT NULL` 조건). NULL은 아직 기록하지 않았다는 뜻이며 옛 `answer_grounding`에 줄이 없던 것과 같다. 검사 결과를 JSON으로 만들 수 없으면 그 칼럼만 비우고 답과 인용은 남긴다(`answer_store.py:155`).
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:162`), 정책 없음.
- `user_id`는 text이며 `users.user_id`(uuid)에 대한 외래 키가 없다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `answer_id` | `text` | NO | | PK | 답 id |
| `user_id` | `text` | NO | | | 질문한 사용자 |
| `thread_id` | `text` | NO | `''` | | 그래프 thread 이름 |
| `question` | `text` | NO | | | 질문 |
| `answer` | `text` | NO | | | 답 |
| `as_of` | `text` | YES | | | 질문의 기준일. 없으면 NULL |
| `created_at` | `timestamptz` | NO | `now()` | | 저장 시각 |
| `grounding` | `jsonb` | YES | | | 인용 검사 결과. NULL = 아직 기록하지 않음 |
| `skills_used` | `jsonb` | YES | | | 쓴 Skill 목록. NULL = 아직 기록하지 않음 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `answers_pkey` | `PRIMARY KEY (answer_id)` | `answer_store.py:142`(`ON CONFLICT (answer_id)`), `199`, `202`, `210`, `224` |

#### 4-4-2. `citations`

- 목적: 인용. 답과 근거 판(커밋)을 묶어 둔다. 리콜은 `(rule_seq, article)`로 영향받는 답을 찾는다(`db/120_answers_recall.sql:23`).
- 만든 파일: `db/120_answers_recall.sql:24-34`.
- 쓰는 코드: `backend/graph/answer_store.py` — INSERT 146-149와 189-194, SELECT 205와 215-216, `find_by_article` 223-225, `count_by_articles` 230-238(호출은 `backend/api/changes.py:82`).
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:163`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `answer_id` | `text` | NO | | PK, FK `answers(answer_id)` `ON DELETE CASCADE` | 답 id |
| `chunk_id` | `text` | NO | | PK | 인용한 청크. `chunks`와 외래 키가 없다 |
| `version_id` | `text` | NO | | PK | 인용한 판 |
| `rule_seq` | `bigint` | NO | | | 페이지 id |
| `article` | `text` | YES | | | 섹션 제목 경로 |
| `version_date` | `text` | YES | | | 판 날짜 |
| `source_url` | `text` | YES | | | 근거 주소 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `citations_pkey` | `PRIMARY KEY (answer_id, chunk_id, version_id)` | `answer_store.py:148`, `192`(`ON CONFLICT DO NOTHING`), `205`, `215-216`(`WHERE answer_id = %s`) |
| `citations_article_idx` | `(rule_seq, article)` | `answer_store.py:223-225`(`WHERE c.rule_seq = %s AND c.article = %s`), `233-234`(`LEFT JOIN citations c ON c.rule_seq = ... AND c.article = ...`) |

#### 4-4-3. `recall_events`

- 목적: 리콜 처리 기록. 한 줄이 바뀐 섹션 하나이고 `event_key`는 `changed_articles.event_id`와 같은 규칙이다. 같은 개정은 한 번만 판정한다(EC-06, `db/120_answers_recall.sql:36`).
- 만든 파일: `db/120_answers_recall.sql:37-48`.
- 쓰는 코드: `backend/graph/recall/store.py`의 `PgRecallStore`(263줄) — `claim_event` 305-311, `finish_event` 313-318, `event_get` 320-322.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:164`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `event_key` | `text` | NO | | PK | `changed_articles.event_id`와 같은 값 |
| `changed` | `jsonb` | NO | | | 변경 섹션(`ChangedArticle`) |
| `status` | `text` | NO | | | `running`, `done`, `failed`(CHECK) |
| `notices` | `integer` | NO | `0` | | 만든 알림 수 |
| `review` | `integer` | NO | `0` | | 검토함으로 간 알림 수 |
| `judge_failures` | `integer` | NO | `0` | | 판정 실패 수 |
| `candidates` | `integer` | NO | `0` | | 함께 볼 정책 후보 수 |
| `error_kind` | `text` | YES | | | 오류 종류 |
| `started_at` | `timestamptz` | NO | `now()` | | 시작 시각 |
| `finished_at` | `timestamptz` | YES | | | 끝난 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `recall_events_pkey` | `PRIMARY KEY (event_key)` | `store.py:307-309`(`ON CONFLICT (event_key)`), `316`, `321` |

#### 4-4-4. `recall_notices`

- 목적: 리콜 알림. 같은 답, 같은 개정은 한 줄이다(`UNIQUE (answer_id, event_key)`). `review_status`는 확신도가 낮거나 의견 규칙으로 눌린 알림이 `pending`(관리자 검토함)이고, 사용자에게는 `released`이거나 NULL인 것만 보인다. `digest_status`는 `RECALL_DIGEST=daily`일 때 요약 대기(`pending`)에서 요약 보냄(`sent`)으로 간다(`db/120_answers_recall.sql:50-52`). 재정렬 뒤에는 옛 `recall_feedback`의 사용자 의견을 `feedback_*` 네 칼럼으로 갖는다.
- 만든 파일: `db/120_answers_recall.sql:53-90`(표 53-82, 의견 칼럼 추가 83-87, 색인 88-90), `:134-138`(의견 색인), 옛 DB 이전 `db/109_realign.sql:35-59`.
- 쓰는 코드: `backend/graph/recall/store.py`의 `PgRecallStore` — `notice_add` 325-333, `notice_get` 335-337, `notices_all` 339-341, `notice_update` 343-345, `digest_pending` 347-349, `feedback_put` 353-355, `feedback_counts` 357-362, `feedback_list` 364-368. API 쪽 읽기는 `backend/api/recalls.py:177, 181, 185`.
- 의견: 사용자 의견(도움 됨 true / 필요 없음 false). 아직 없으면 NULL이다. 알림당 한 줄이며 다시 보내면 덮어쓴다(`db/120_answers_recall.sql:77`, `store.py:352`).
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:165`), 정책 없음.
- `user_id`는 text이며 `users.user_id`(uuid)에 대한 외래 키가 없다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `notice_id` | `text` | NO | | PK | 알림 id |
| `event_key` | `text` | NO | | UK(`answer_id`와 함께) | 개정 하나의 키 |
| `answer_id` | `text` | NO | | UK(`event_key`와 함께) | 영향받은 답. `answers`와 외래 키가 없다 |
| `user_id` | `text` | NO | | | 답을 받은 사용자 |
| `thread_id` | `text` | YES | | | 그래프 thread 이름 |
| `question` | `text` | YES | | | 질문 |
| `answer_excerpt` | `text` | YES | | | 답 발췌 |
| `changed` | `jsonb` | NO | | | 변경 섹션 |
| `conclusion_changed` | `boolean` | NO | | | 결론이 바뀌었나 |
| `explanation` | `text` | NO | | | 설명 |
| `severity` | `text` | NO | | | `high` 또는 `low`(CHECK) |
| `confidence` | `double precision` | YES | | | 확신도. NULL이거나 0 이상 1 이하(CHECK) |
| `change_pattern` | `text` | NO | `''` | | 변경 유형. 의견 집계 키 |
| `review_status` | `text` | YES | | | `pending`, `released`, `dismissed`(CHECK) |
| `review_reason` | `text` | YES | | | 검토함으로 간 이유 |
| `digest_status` | `text` | YES | | | `pending`, `sent`(CHECK) |
| `judge_failed` | `boolean` | NO | `false` | | 판정 실패 여부 |
| `acked` | `boolean` | NO | `false` | | 사용자가 확인했나 |
| `acked_at` | `timestamptz` | YES | | | 확인 시각 |
| `source_url` | `text` | YES | | | 근거 주소 |
| `old_text` | `text` | YES | | | 개정 전 본문 |
| `new_text` | `text` | YES | | | 개정 뒤 본문 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |
| `feedback_useful` | `boolean` | YES | | | 사용자 의견. NULL = 의견 없음 |
| `feedback_reason` | `text` | YES | | | 의견 사유 |
| `feedback_by` | `text` | YES | | | 의견을 낸 사용자 |
| `feedback_at` | `timestamptz` | YES | | | 의견 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `recall_notices_pkey` | `PRIMARY KEY (notice_id)` | `store.py:336`, `344`, `354-355` |
| `recall_notices_answer_id_event_key_key` | `UNIQUE (answer_id, event_key)` | `store.py:328`(`ON CONFLICT (answer_id, event_key)`), `331-332` |
| `recall_notices_user_idx` | `(user_id, created_at DESC)` | `store.py:340-341`(`WHERE user_id = ... ORDER BY created_at DESC`) |
| `recall_notices_digest_idx` | `(created_at) WHERE digest_status = 'pending'` | `store.py:348-349`(`WHERE digest_status = 'pending' ... ORDER BY created_at`) |
| `recall_notices_feedback_idx` | `(user_id, change_pattern, (changed ->> 'article'), ((changed ->> 'rule_seq')::bigint)) WHERE feedback_useful IS NOT NULL` | `store.py:359-360`(`feedback_counts`, 식이 색인 식과 같아야 색인을 탄다), `365-368`(`feedback_list`의 `WHERE feedback_useful IS NOT NULL`) |

#### 4-4-5. `maintenance_candidates`

- 목적: 함께 볼 정책 후보(링크로 연결된 다른 정책). 관리자가 확인 필요(`needed`)와 불필요(`not_needed`)를 판단한다(`db/120_answers_recall.sql:92`). 후보는 `chunks.link_targets`로 찾는다(`backend/graph/recall/maintenance.py:61-69`).
- 만든 파일: `db/120_answers_recall.sql:93-106`.
- 쓰는 코드: `backend/graph/recall/store.py` — `candidates_add` 382-383, `candidates` 385-387, `candidate_get` 389-391, `candidate_decide` 393-396.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:166`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `candidate_id` | `text` | NO | | PK | 후보 id |
| `event_key` | `text` | NO | | | 어느 개정에서 나온 후보인가 |
| `upper_rule` | `text` | NO | | | 바뀐 정책 |
| `upper_version_id` | `text` | NO | | | 바뀐 정책의 판 |
| `rule_seq` | `bigint` | NO | | | 연결된 정책 페이지 id |
| `article` | `text` | NO | | | 연결된 섹션 |
| `reason` | `text` | NO | | | 후보 이유 |
| `status` | `text` | NO | `'pending'` | | `pending`, `needed`, `not_needed`(CHECK) |
| `decided_by` | `text` | YES | | | 판단한 관리자 |
| `decided_at` | `timestamptz` | YES | | | 판단 시각 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `maintenance_candidates_pkey` | `PRIMARY KEY (candidate_id)` | `store.py:383`(`ON CONFLICT (candidate_id)`), `390`, `394` |
| `maintenance_candidates_status_idx` | `(status, created_at DESC)` | `store.py:386-387`(`WHERE status = ... ORDER BY created_at DESC, candidate_id`) |

#### 4-4-6. `webhook_subscriptions`

- 목적: 업무시스템 웹훅 구독. `secret_ref`는 비밀값이 든 환경변수 이름(`RECALL_WEBHOOK_SECRET` 또는 `RECALL_WEBHOOK_SECRET_<이름>`)이며 값은 저장하지 않는다(`db/120_answers_recall.sql:108`).
- 만든 파일: `db/120_answers_recall.sql:109-116`.
- 쓰는 코드: `backend/graph/recall/store.py` — `subs` 399-401, `sub_add` 403-404.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:167`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `sub_id` | `text` | NO | | PK | 구독 id |
| `url` | `text` | NO | | | 전송할 주소 |
| `secret_ref` | `text` | NO | `'RECALL_WEBHOOK_SECRET'` | | 비밀값이 든 환경변수 이름 |
| `active` | `boolean` | NO | `true` | | 활성 여부 |
| `created_by` | `text` | YES | | | 등록한 사용자 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `webhook_subscriptions_pkey` | `PRIMARY KEY (sub_id)` | `sub_id`로 찾는 SQL은 코드에서 찾지 못함. `store.py:400`은 목록 읽기, `404`는 INSERT |

#### 4-4-7. `webhook_deliveries`

- 목적: 웹훅 전송 기록. 시도마다 `attempts`에 상태 코드, 오류 종류, 시각을 남긴다(EC-05, AC-03). 재시도는 `backend/graph/recall/webhook.py`가 한다.
- 만든 파일: `db/120_answers_recall.sql:119-132`.
- 쓰는 코드: `backend/graph/recall/store.py` — `delivery_add` 406-407, `delivery_update` 409-410, `deliveries` 412-414.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:168`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `delivery_id` | `text` | NO | | PK | 전송 id |
| `sub_id` | `text` | NO | | | 구독 id. `webhook_subscriptions`와 외래 키가 없다 |
| `notice_id` | `text` | NO | | | 알림 id. `kind`가 `digest`이면 요약 id(`digest_id`) |
| `kind` | `text` | NO | `'notice'` | | `notice` 또는 `digest`(CHECK) |
| `status` | `text` | NO | | | `pending`, `success`, `failed`(CHECK) |
| `tries` | `integer` | NO | `0` | | 시도 횟수 |
| `last_status_code` | `integer` | YES | | | 마지막 HTTP 상태 코드 |
| `last_error` | `text` | YES | | | 마지막 오류 |
| `attempts` | `jsonb` | NO | `'[]'::jsonb` | | 시도별 기록 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |
| `updated_at` | `timestamptz` | NO | `now()` | | 수정 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `webhook_deliveries_pkey` | `PRIMARY KEY (delivery_id)` | `store.py:410`(`WHERE delivery_id = %s`) |
| `webhook_deliveries_notice_idx` | `(notice_id)` | `store.py:413-414`(`WHERE ... notice_id = ...`) |

#### 4-4-8. `recall_digests`

- 목적: 하루 요약(`RECALL_DIGEST=daily`). `payload`는 웹훅으로 보낸 요약 JSON(알림 목록 포함)이다(`db/120_answers_recall.sql:140`). 알림을 요약으로 묶는 곳은 `backend/graph/recall/digest.py`(`flush_digests`)다.
- 만든 파일: `db/120_answers_recall.sql:141-150`.
- 쓰는 코드: `backend/graph/recall/store.py` — `digest_add` 371-375, `digests` 377-379.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:169`), 정책 없음.
- `user_id`는 text이며 `users.user_id`(uuid)에 대한 외래 키가 없다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `digest_id` | `text` | NO | | PK | 요약 id |
| `user_id` | `text` | NO | | | 받는 사용자 |
| `day` | `text` | NO | | | 요약 날짜 |
| `count` | `integer` | NO | | | 알림 수 |
| `notice_ids` | `jsonb` | NO | `'[]'::jsonb` | | 묶은 알림 id 목록 |
| `payload` | `jsonb` | NO | | | 웹훅으로 보낸 요약 JSON |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `recall_digests_pkey` | `PRIMARY KEY (digest_id)` | `store.py:372`(`ON CONFLICT (digest_id)`), `375` |
| `recall_digests_user_idx` | `(user_id, created_at DESC)` | `store.py:378-379`(`WHERE ... user_id = ... ORDER BY created_at DESC`) |

#### 4-4-9. `change_monitoring`

- 목적: 변경 감시 스위치(한 줄). `paused`이면 증분 수집(`backend/rag/ingest/schedule.py`)이 아무것도 하지 않고 `noop(paused)`로 끝낸다(`db/120_answers_recall.sql:152`).
- 만든 파일: `db/120_answers_recall.sql:153-158`.
- 쓰는 코드: `backend/graph/recall/monitor.py`의 `PgChangeStore.monitoring_get` 184-188, `monitoring_set` 190-195. `backend/rag/ingest/schedule.py:307-314`(`monitoring_paused`)가 읽는다.
- RLS와 권한: RLS 켬(`db/120_answers_recall.sql:170`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `id` | `smallint` | NO | `1` | PK | 항상 1(CHECK `id = 1`) |
| `status` | `text` | NO | `'active'` | | `active` 또는 `paused`(CHECK) |
| `updated_by` | `text` | YES | | | 바꾼 사용자 |
| `updated_at` | `timestamptz` | NO | `now()` | | 바꾼 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `change_monitoring_pkey` | `PRIMARY KEY (id)` | `monitor.py:187`, `193-194`(`ON CONFLICT (id)`), `schedule.py:313` |

### 4-5. 검색

검색 영역의 표는 `backend/rag/retrieve/load_snapshot.py`(처음 적재와 재적재)와 `backend/rag/ingest/schedule.py`(증분 수집)가 쓰고, `backend/rag/retrieve/search.py`와 `section.py`가 읽는다.

#### 4-5-1. `docs`

- 목적: 페이지. `rule_seq`는 페이지 경로의 sha256 앞 8자리를 정수로 바꾼 값으로, 32비트를 넘어 `bigint`다(`db/201_search.sql:5`).
- 만든 파일: `db/201_search.sql:6-13`.
- 쓰는 코드: 쓰기 `load_snapshot.py:109-113`, `schedule.py:237-239`. 읽기 `search.py:272-274`(`JOIN docs d`), `section.py:169-174, 194`, `backend/graph/recall/maintenance.py:65, 72`, `backend/graph/recall/monitor.py:114`, `backend/rag/ingest/changes.py:71`, `schedule.py:226`.
- RLS와 권한: RLS 켬(`db/201_search.sql:92`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `rule_seq` | `bigint` | NO | | PK | 페이지 id |
| `org` | `text` | NO | | | 조직(절). 검색 필터 `d.org` |
| `title` | `text` | NO | | | 페이지 제목 |
| `fmt` | `text` | NO | `'md'` | | 형식 |
| `source_url` | `text` | NO | | | 페이지 주소(청크 주소의 `#L…`를 뗀 것) |
| `fetched_at` | `date` | NO | | | 받은 날짜 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `docs_pkey` | `PRIMARY KEY (rule_seq)` | `load_snapshot.py:111`, `schedule.py:238`(`ON CONFLICT (rule_seq)`), `search.py:274`, `section.py:171`(`d.rule_seq` 조인) |

#### 4-5-2. `versions`

- 목적: 페이지의 판. `version_id`는 커밋 앞 12자라 여러 페이지가 같은 값을 쓰므로 열쇠가 `(rule_seq, version_id)`다. 유효 구간 `[valid_from, valid_to)`에서 `valid_from`은 판 날짜, `valid_to`는 같은 페이지 다음 판 날짜이고 현재 판은 비어 있다(`db/201_search.sql:15-16`). 한 페이지에 현재 판은 하나뿐이어서, 옛 판을 닫지 않고 새 판을 넣으면 DB가 거부한다(201:28).
- 만든 파일: `db/201_search.sql:17-29`.
- 쓰는 코드: 쓰기 `load_snapshot.py:115-119`, `schedule.py:241-246, 263-269`. 읽기 `search.py:273`(`JOIN versions v`), `section.py:169-174`, `maintenance.py:64`, `schedule.py:233`.
- RLS와 권한: RLS 켬(`db/201_search.sql:93`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `rule_seq` | `bigint` | NO | | PK, FK `docs(rule_seq)` | 페이지 id |
| `version_id` | `text` | NO | | PK | 판 id(커밋 앞 12자) |
| `version_date` | `date` | NO | | | 판 날짜 |
| `version_date_before` | `boolean` | NO | `false` | | "YYYY-MM-DD 이전" 판(I-001) |
| `valid_from` | `date` | NO | | | 유효 시작 |
| `valid_to` | `date` | YES | | | 유효 끝. NULL = 현재 판. CHECK `valid_to IS NULL OR valid_to >= valid_from` |
| `file_sha256` | `text` | YES | | | 원본 파일 해시 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `versions_pkey` | `PRIMARY KEY (rule_seq, version_id)` | `schedule.py:233`, `load_snapshot.py:117`(`ON CONFLICT (rule_seq, version_id)`), `search.py:273`(조인) |
| `versions_one_current` | `UNIQUE (rule_seq) WHERE valid_to IS NULL` | `schedule.py:241-242, 263-264, 267-269`(`WHERE rule_seq = %s AND valid_to IS NULL`로 현재 판을 닫는다), `277`(현재 판이 둘인 경우는 이 색인이 막는다는 주석), `section.py:172`, `maintenance.py:64` |

#### 4-5-3. `chunks`

- 목적: 청크. `chunk_id`는 `sha(rule_seq:seq:본문)`이라 개정판에서 안 바뀐 섹션은 옛 판과 id가 같으므로 열쇠가 `(chunk_id, version_id)`다(`db/201_search.sql:31`). `embedding`은 차원 없는 `vector`로 모델마다 1024차원이나 2048차원이며, 한 번에 한 모델의 벡터만 둔다. `embedder`는 그 행의 벡터를 만든 모델이다(201:32). `acl`은 문서 권한 그룹으로 F-06 연결 지점이며 지금은 비워 둔다(201:48). `link_targets`는 본문 링크가 가리키는 코퍼스 안 다른 페이지(`rule_seq`)로 링크 확장(L1x2)이 읽는다(201:57-59).
- 만든 파일: `db/201_search.sql:35-60`(표 35-53, 줄 범위 칼럼 추가 55-56, `link_targets` 추가 59, `chunks_page` 60). 부분 HNSW 색인은 `db/manual/chunks_hnsw_voyage4.sql:14-16`.
- 쓰는 코드: 쓰기 `load_snapshot.py:122-135`(임시 표 `chunks_in`을 거쳐 `INSERT ... ON CONFLICT (chunk_id, version_id)`), `186`(`link_targets` 갱신), `schedule.py:248-254`(증분 수집). 읽기 `search.py:272-274, 333, 350-369, 376, 383-388, 399-413, 422, 431, 880`, `section.py:182-183, 189-190`, `backend/graph/recall/maintenance.py:63-67`, `backend/graph/recall/acl.py:40-41`(`SELECT DISTINCT g FROM chunks c, unnest(c.acl)`), `schedule.py:190, 229, 256`.
- `acl`: `backend/graph/recall/acl.py:40-41`가 읽는다. 문서 권한 그룹을 채우는 정책 파일과 검색 단계 거르기는 아직 없다(`acl.py:3-6`: 지금 코퍼스는 모두 비어 있어 기본 공개).
- 옛 판 청크가 남는 이유: 증분 수집은 옛 판을 지우지 않고 `valid_to`로 닫는다. 그래야 `as_of` 검색과 동결 평가셋이 그대로 남는다(`db/202_sync.sql:1-3`). `schedule.py:240-242`가 새 판을 넣기 전에 같은 페이지의 현재 판을 `valid_to`로 닫고, `245-254`가 새 판과 새 청크를 넣으며, 사라진 페이지는 `263-269`에서 닫기만 한다. 청크 행을 지우는 `DELETE`는 `backend/`에서 찾지 못했다(`backend/`의 `DELETE FROM`/`TRUNCATE`는 `load_snapshot.py:127, 180`의 임시 표 비우기뿐이고, 시험용 행 삭제는 `evals/safety/deploy_corpus_injection_check.py:221-225`). 그래서 `chunks`에는 현재 판과 닫힌 옛 판의 청크가 함께 있다.
- 검색이 현재 판만 보는 조건: `valid_to`는 `chunks`가 아니라 `versions`에 있다. `backend/rag/retrieve/search.py:269-271`의 `_FILTER`가 `as_of`가 없으면 `v.valid_to IS NULL`, 있으면 `v.valid_from <= as_of AND (v.valid_to IS NULL OR as_of < v.valid_to)`를 건다. 질의는 `chunks`와 `versions`를 `(rule_seq, version_id)`로 조인하고(`search.py:272-274`) 이 필터를 벡터 검색(`352`, `365`), 링크 확장(`388`), 제목 경로(`404`), 금액 구간(`413`) 질의에 붙인다. 링크 후보를 고르는 `maintenance.py:64`도 `v.valid_to IS NULL`로 현재 판만 본다.
- HNSW 부분 색인: `db/manual/chunks_hnsw_voyage4.sql:14-16`이 `chunks_emb_hnsw_half`를 `((embedding::halfvec(1024)) halfvec_ip_ops) WITH (m = 16, ef_construction = 128) WHERE embedder = 'voyage-4'`로 만든다. 자동으로 적용되지 않는 수동 파일이다. 환경변수 `SEARCH_HNSW=1`이고 모델이 `HNSW_DIMS`(`search.py:279`)에 있을 때만 `search.py:344-354`가 이 색인의 식을 쓰는 질의를 보낸다(`search.py:296`). 색인에는 `valid_to` 조건이 없으므로, 필터로 결과가 줄 때를 위해 질의마다 `hnsw.ef_search = 200`과 `hnsw.iterative_scan = strict_order`를 준다(`search.py:280-281, 357-358`).
- RLS와 권한: RLS 켬(`db/201_search.sql:94`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `chunk_id` | `text` | NO | | PK | 청크 id |
| `version_id` | `text` | NO | | PK, FK `versions(rule_seq, version_id)` | 판 id |
| `rule_seq` | `bigint` | NO | | FK `versions(rule_seq, version_id)` | 페이지 id |
| `seq` | `integer` | NO | | | 페이지 안 순번 |
| `ord` | `integer` | NO | | | 스냅샷 `chunks.jsonl`의 줄 순서. BM25 색인 순서를 1차 비교와 같게 둔다 |
| `article` | `text` | YES | | | 섹션 제목 경로 |
| `kind` | `text` | NO | | | 청크 종류 |
| `text` | `text` | NO | | | 본문 |
| `source_url` | `text` | NO | | | 청크 주소 |
| `text_sha256` | `text` | YES | | | 본문 해시 |
| `line_start` | `integer` | YES | | | 원본 페이지 줄 범위 시작(1부터) |
| `line_end` | `integer` | YES | | | 줄 범위 끝(끝 포함) |
| `acl` | `text[]` | NO | `'{}'` | | 문서 권한 그룹. F-06 연결 지점이다 |
| `embedding` | `vector` | YES | | | 차원 없는 벡터 |
| `embedder` | `text` | YES | | | 벡터를 만든 모델 |
| `link_targets` | `bigint[]` | NO | `'{}'` | | 본문 링크가 가리키는 페이지 `rule_seq` 목록 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `chunks_pkey` | `PRIMARY KEY (chunk_id, version_id)` | `load_snapshot.py:134-135`(`ON CONFLICT (chunk_id, version_id)`), `search.py:422`(`JOIN unnest(ids, vers) AS k(chunk_id, version_id)`) |
| `chunks_page` | `(rule_seq, version_id)` | `section.py:182-183, 189-190`(`WHERE rule_seq = ... AND version_id = ...`), `schedule.py:256-257`, `search.py:431` |
| `chunks_link_targets_gin` | `USING gin (link_targets)` | `maintenance.py:62-69`(`WHERE c.link_targets @> ARRAY[%s]::bigint[]`). `db/201_search.sql`이 만들고 `db/109_realign.sql`이 옛 DB에 더한다 |
| `chunks_emb_hnsw_half` | `USING hnsw ((embedding::halfvec(1024)) halfvec_ip_ops) WITH (m = 16, ef_construction = 128) WHERE embedder = 'voyage-4'` (수동, `db/manual/chunks_hnsw_voyage4.sql`) | `search.py:350-354`(`ORDER BY dist LIMIT`, `SEARCH_HNSW=1`일 때만) |

#### 4-5-4. `index_meta`

- 목적: 색인 장부(한 줄 = 지금 적재된 모델). `status`가 `ready`일 때만 API가 뜬다(`db/201_search.sql:62`). `generation`은 적재와 증분 반영마다 1씩 늘어나며 API가 BM25를 다시 만들 때 본다(201:74).
- 만든 파일: `db/201_search.sql:63-78`(`links_sha256`은 78 `ALTER`).
- 쓰는 코드: `load_snapshot.py:80-98, 164, 191`, `schedule.py:154, 278`, `search.py:320, 327`.
- RLS와 권한: RLS 켬(`db/201_search.sql:95`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `id` | `smallint` | NO | `1` | PK | 항상 1(CHECK `id = 1`) |
| `embedder` | `text` | NO | | | 임베딩 모델 이름 |
| `revision` | `text` | YES | | | 모델 판 |
| `dim` | `integer` | NO | | | 벡터 차원 |
| `prefixes` | `jsonb` | NO | `'{}'` | | 질의·문서 접두어 |
| `max_seq_length` | `integer` | YES | | | 최대 입력 길이 |
| `n_chunks` | `integer` | NO | | | 적재한 청크 수 |
| `chunks_sha256` | `text` | NO | | | 청크 파일 해시 |
| `vectors_sha256` | `text` | NO | | | 벡터 파일 해시 |
| `status` | `text` | NO | | | `loading` 또는 `ready`(CHECK) |
| `generation` | `bigint` | NO | `0` | | 적재와 증분 반영마다 +1 |
| `loaded_at` | `timestamptz` | NO | `now()` | | 적재 시각 |
| `links_sha256` | `text` | YES | | | 링크 파일(`data/index/links.jsonl`) 해시 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `index_meta_pkey` | `PRIMARY KEY (id)` | `search.py:320`, `327`(`WHERE id = 1`), `schedule.py:154`, `278`, `load_snapshot.py:81`, `92`(`ON CONFLICT (id)`) |

#### 4-5-5. `query_translations`

- 목적: 번역 장부. 같은 질문, 같은 모델이면 LLM을 다시 부르지 않는다. `model`은 `cost.normalize_model_id`로 맞춘 이름이다(`db/201_search.sql:80`).
- 만든 파일: `db/201_search.sql:81-88`.
- 쓰는 코드: `search.py:447-448`(SELECT), `455`(INSERT), `load_snapshot.py:159`(스냅샷의 번역을 미리 적재).
- RLS와 권한: RLS 켬(`db/201_search.sql:96`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `query_sha256` | `text` | NO | | PK | 질문 해시 |
| `model` | `text` | NO | | PK | 번역에 쓴 모델 |
| `keywords` | `text` | YES | | | 키워드 번역 |
| `sentence` | `text` | YES | | | 문장 번역 |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `query_translations_pkey` | `PRIMARY KEY (query_sha256, model)` | `search.py:447-448`(`WHERE query_sha256 = ... AND model = ...`) |

### 4-6. 증분 수집

#### 4-6-1. `sync_runs`

- 목적: 실행 기록. 한 줄이 정해진 시각 실행 한 번이다. `UNIQUE (job, slot)`이라 같은 슬롯은 한 번만 시작한다(중복 실행 방지, rag3-19). `slot`은 하루 1회면 UTC 날짜이고 손으로 한 번 더 돌리면 `manual-<시각>`이다(`db/202_sync.sql:5, 9`).
- 만든 파일: `db/202_sync.sql:6-29`.
- 쓰는 코드: `backend/rag/ingest/schedule.py` — `claim` 127-128, `last_commit` 136, `pending_holds` 145, `finish` 296-300, 실행 시작 334. `backend/rag/ingest/snapshot_diff.py:103`, `backend/graph/recall/monitor.py:170`, `backend/rag/ingest/changes.py:78`.
- RLS와 권한: RLS 켬(`db/202_sync.sql:49`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `run_id` | `bigserial` | NO | 시퀀스 | PK | 실행 번호 |
| `job` | `text` | NO | | UK(`slot`과 함께) | 작업 이름 |
| `slot` | `text` | NO | | UK(`job`과 함께) | 실행 슬롯 |
| `trigger` | `text` | NO | | | `schedule` 또는 `manual`(CHECK) |
| `status` | `text` | NO | | | `running`, `succeeded`, `noop`, `failed`(CHECK) |
| `started_at` | `timestamptz` | NO | | | 시작 시각 |
| `finished_at` | `timestamptz` | YES | | | 끝난 시각 |
| `from_commit` | `text` | YES | | | 비교 시작 커밋 |
| `to_commit` | `text` | YES | | | 비교 끝 커밋 |
| `list_complete` | `boolean` | YES | | | 목록을 끝까지 받았나(아니면 삭제 보류, rag4-13) |
| `added` | `integer` | YES | | | 추가된 쪽 수 |
| `modified` | `integer` | YES | | | 바뀐 쪽 수 |
| `format_only` | `integer` | YES | | | 링크 주소와 공백만 바뀐 쪽(리콜에 안 보냄) |
| `removed_seen` | `integer` | YES | | | 사라진 것으로 본 쪽 |
| `removed_applied` | `integer` | YES | | | 실제로 닫은 쪽(목록이 불완전하면 0) |
| `articles` | `integer` | YES | | | 리콜에 넘긴 바뀐 섹션 수 |
| `embedded` | `integer` | YES | | | 새로 임베딩한 청크 |
| `reused` | `integer` | YES | | | 같은 글이라 벡터를 재사용한 청크 |
| `detail` | `jsonb` | NO | `'{}'` | | 쪽별 결과(경로 목록, 오류, 검토 대기) |
| `error_kind` | `text` | YES | | | 오류 종류 |
| `error_detail` | `text` | YES | | | 오류 내용 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `sync_runs_pkey` | `PRIMARY KEY (run_id)` | `schedule.py:300, 334`(`WHERE run_id = %s`) |
| `sync_runs_job_slot_key` | `UNIQUE (job, slot)` | `schedule.py:128`(`ON CONFLICT (job, slot)`). `schedule.py:136, 145`와 `monitor.py:170`, `changes.py:78`의 `WHERE job = ...`도 이 색인의 앞 열과 같은 열을 쓴다 |

#### 4-6-2. `changed_articles`

- 목적: 리콜에 넘길 바뀐 섹션. 칼럼 이름은 계약 `ChangedArticle`(`backend/schemas/recall.py`)과 같다. `event_id`는 `(rule_seq, article, new_version_date, change_type)`의 sha256 앞 16자리라 같은 개정은 다시 돌려도 한 줄이다(`db/202_sync.sql:31-33`, `backend/rag/ingest/schedule.py:66-68`).
- 만든 파일: `db/202_sync.sql:34-45`.
- 쓰는 코드: 쓰기 `schedule.py:271-275`, `snapshot_diff.py:108-110`, `backend/graph/recall/monitor.py:182`(`set_status`). 읽기 `monitor.py:111-114, 147-182`(대기 건 읽기 174-177), `backend/rag/ingest/changes.py:67-75`.
- RLS와 권한: RLS 켬(`db/202_sync.sql:50`), 정책 없음.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `event_id` | `text` | NO | | PK | 개정 하나의 키 |
| `run_id` | `bigint` | NO | | FK `sync_runs(run_id)` | 만든 실행 |
| `rule_seq` | `bigint` | NO | | | 페이지 id. `docs`와 외래 키가 없다 |
| `article` | `text` | NO | | | 섹션 |
| `old_version_date` | `text` | NO | | | 이전 판 날짜 |
| `new_version_date` | `text` | NO | | | 새 판 날짜 |
| `change_type` | `text` | NO | | | `added`, `removed`, `modified`(CHECK) |
| `status` | `text` | NO | `'pending'` | | `pending`, `sent`, `failed`(CHECK) |
| `created_at` | `timestamptz` | NO | `now()` | | 만든 시각 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| `changed_articles_pkey` | `PRIMARY KEY (event_id)` | `schedule.py:273`, `snapshot_diff.py:109`(`ON CONFLICT (event_id)`), `monitor.py:164`, `182` |
| `changed_articles_pending` | `(status) WHERE status = 'pending'` | `monitor.py:177`(`WHERE ca.status = 'pending' ORDER BY ca.created_at ... LIMIT`) |

## 5. LangGraph 표 6개

- 목적과 관리: 체크포인트 세 표와 마이그레이션 기록 두 표는 `langgraph-checkpoint-postgres`의 `PostgresSaver.setup()`이, `store`와 `store_migrations`는 `PostgresStore.setup()`이 만든다. **라이브러리가 만들고 관리하는 표이며 구조(칼럼, 색인, 제약)를 바꾸지 않는다. 정리가 필요하면 행을 삭제하는 SQL만 쓴다.** 이 저장소의 `db/*.sql`에는 정의가 없다.
- 만드는 코드: `backend/graph/checkpoint.py` — 표 이름 목록 `LANGGRAPH_TABLES` 30, 두 `setup()`과 RLS를 부딪힘 재시도와 함께 실행하는 `setup_tables` 63-86, 앱 시작 때 여는 `open_persistence` 89-142(`PostgresSaver`/`PostgresStore` 생성 119-137, `setup_tables` 호출 139).
- RLS와 권한: 대화 내용이 들어가므로 만든 직후 `enable_rls`(`checkpoint.py:49-60`)가 6개 표에 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`를 실행한다. 정책은 없다. `FORCE`를 쓰지 않아 표 소유자인 앱은 막히지 않는다. 표가 없으면 라이브러리 버전이 바뀐 것이므로 조용히 넘어가지 않고 멈춘다. `anon`, `authenticated` 권한 회수는 109 단계 5가 이미 있는 표에 적용한다(3-3의 `ALTER DEFAULT PRIVILEGES` 주의 참고).
- 정의 출처: 아래 칼럼과 색인은 라이브러리가 실제로 만든 DB를 읽기 전용으로 조회한 결과(칼럼 타입, NULL, 기본값, 기본키, 색인 정의)와 위 코드 위치를 근거로 적었다. 칼럼 설명은 라이브러리 문서가 아니라 이름과 이 저장소 코드에서 확인한 범위만 적었다.
- 이 저장소 코드에 이 표를 직접 읽거나 지우는 SQL은 없다. 표 이름이 나오는 곳은 `checkpoint.py:30`(RLS 목록)과 `checkpoint.py:56`(`pg_class` 조회)뿐이다.
- 이 표들의 행은 `thread_id`로 같은 대화를 가리키지만 외래 키는 없다. 값 규칙은 [ERD.md](ERD.md) 4장 L5, L6, L20이다.

### 5-1. `checkpoints`

체크포인트 본체. 사람 승인에서 멈춘 그래프를 서버를 다시 띄운 뒤에도 같은 `thread_id`로 이어 가게 하는 저장소다(`checkpoint.py:3`).

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `thread_id` | `text` | NO | | PK | 그래프 thread 이름 `<user_id>:<thread_id>`(`backend/api/routes.py:86-87, 231`) |
| `checkpoint_ns` | `text` | NO | `''` | PK | 체크포인트 네임스페이스 |
| `checkpoint_id` | `text` | NO | | PK | 체크포인트 id |
| `parent_checkpoint_id` | `text` | YES | | | 이전 체크포인트 id |
| `type` | `text` | YES | | | 직렬화 종류 |
| `checkpoint` | `jsonb` | NO | | | 체크포인트 내용 |
| `metadata` | `jsonb` | NO | `'{}'` | | 메타데이터 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |
| `checkpoints_thread_id_idx` | `btree (thread_id)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

### 5-2. `checkpoint_blobs`

채널 값 바이너리.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `thread_id` | `text` | NO | | PK | thread 이름 |
| `checkpoint_ns` | `text` | NO | `''` | PK | 네임스페이스 |
| `channel` | `text` | NO | | PK | 채널 이름 |
| `version` | `text` | NO | | PK | 채널 값 버전 |
| `type` | `text` | NO | | | 직렬화 종류 |
| `blob` | `bytea` | YES | | | 값 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (thread_id, checkpoint_ns, channel, version)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |
| `checkpoint_blobs_thread_id_idx` | `btree (thread_id)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

### 5-3. `checkpoint_writes`

체크포인트에 딸린 중간 쓰기.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `thread_id` | `text` | NO | | PK | thread 이름 |
| `checkpoint_ns` | `text` | NO | `''` | PK | 네임스페이스 |
| `checkpoint_id` | `text` | NO | | PK | 체크포인트 id |
| `task_id` | `text` | NO | | PK | 작업 id |
| `idx` | `integer` | NO | | PK | 작업 안 순번 |
| `channel` | `text` | NO | | | 채널 이름 |
| `type` | `text` | YES | | | 직렬화 종류 |
| `blob` | `bytea` | NO | | | 값 |
| `task_path` | `text` | NO | `''` | | 작업 경로 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |
| `checkpoint_writes_thread_id_idx` | `btree (thread_id)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

### 5-4. `checkpoint_migrations`

체크포인트 표 마이그레이션 버전 기록. 라이브러리가 쓴다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `v` | `integer` | NO | | PK | 적용한 마이그레이션 번호 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (v)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

### 5-5. `store`

LangGraph Store 항목. `backend/memory/profile.py`가 장기 기억으로 사용자 프로필(소속 `affiliation`, 직급 `rank`)을 넣는다. namespace는 `(user_id, "profile")`, 키는 `"me"`이다(`profile.py:14, 19-22`). 대화 내용과 질문과 검색 결과는 넣지 않는다(`profile.py:2-9`).

- 쓰는 코드: `backend/memory/profile.py` — `get_profile` 25, `put_profile` 33(TTL을 지정하는 호출은 이 파일에서 찾지 못함), `delete_profile` 44. 호출은 `backend/graph/build.py:451`, `backend/api/routes.py:346`(조회), `354`(수정), `360`(삭제)이다. 생성은 `checkpoint.py:120, 137`의 `PostgresStore`다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `prefix` | `text` | NO | | PK | namespace에서 만들어진 접두어. 문자열 형식은 라이브러리 구현이라 확인하지 못함 |
| `key` | `text` | NO | | PK | 항목 키 |
| `value` | `jsonb` | NO | | | 항목 값 |
| `created_at` | `timestamptz` | YES | `CURRENT_TIMESTAMP` | | 만든 시각 |
| `updated_at` | `timestamptz` | YES | `CURRENT_TIMESTAMP` | | 수정 시각 |
| `expires_at` | `timestamptz` | YES | | | 만료 시각(TTL을 쓸 때) |
| `ttl_minutes` | `integer` | YES | | | TTL 분 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (prefix, key)` | 라이브러리 내부 질의(`store.get`, `store.put`, `store.delete`가 이 키로 접근하는 것으로 보이나 라이브러리 소스는 확인하지 않음) |
| `store_prefix_idx` | `btree (prefix text_pattern_ops)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |
| `idx_store_expires_at` | `btree (expires_at) WHERE expires_at IS NOT NULL` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

### 5-6. `store_migrations`

Store 표 마이그레이션 버전 기록. 라이브러리가 쓴다.

| 칼럼명 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| `v` | `integer` | NO | | PK | 적용한 마이그레이션 번호 |

| 색인 이름 | 정의 | 그 이유가 되는 질의 |
|---|---|---|
| (기본키 색인) | `PRIMARY KEY (v)` | 라이브러리 내부 질의. 이 저장소 코드에서 찾지 못함 |

## 6. 다른 문서와 다른 점, 확인하지 못한 항목

다른 문서와 다른 점은 이 문서에서 고치지 않았다.

- `docs/SDD.md` 5장(385-403줄)은 합쳐진 칼럼을 이미 반영했다. 그러나 `rule_links`(390줄)는 `db/*.sql`에 정의가 없고, `signup_requests`, `user_profiles`, `admin_role_log`, `token_revocations`, `issue_tables`, `threads`, `index_meta`, `query_translations`, `sync_runs`, `changed_articles`는 5장 표에 없다.
- `db/db.md`는 재정렬 절(73-80줄)을 갖고 있다. 다만 71줄(2026-11-09 운영 확인 문단)은 `issue_table_rejections`를 표 목록에 넣고 있고, 91줄(작업 기록)은 `120_answers_recall.sql`이 `answer_grounding`, `recall_feedback`을 만든다고 적고 있다. 둘 다 당시 기록이다.
- `users.groups`를 읽는 SQL은 코드에서 찾지 못했다(4-1-1). `chunks.acl`은 `backend/graph/recall/acl.py:40-41`이 읽는다.
- `issue_tables.thread_id`가 화면용 바깥 이름인지 그래프 이름 `<user_id>:<thread_id>`인지는 확인하지 못했다. 쓰는 값은 그래프 상태의 `thread_id`(`backend/graph/departments/review.py:316`)이고, 그 값이 어느 쪽인지는 호출부까지 따라가지 않았다.
- 운영 DB에서 HNSW 색인 `chunks_emb_hnsw_half`가 있는지는 확인하지 못했다. 2026-11-10 운영 조회 요약에는 `chunks`의 색인 수만 있고 색인 이름은 없다.
- 운영 DB에는 `db/109_realign.sql`(1단계, 2026-11-10 밤)과 2단계(2026-11-11 00:42), 옛 표 삭제(2026-11-11)를 적용했다(2-3). 2-1의 운영 조회 열은 적용 전 값이다.
- 제약 색인의 이름(`users_pkey`, `users_login_id_key` 등)은 PostgreSQL 기본 규칙에 따라 적었고 운영 DB에서 대조하지 않았다.
- `token_revocations`의 만료 행 정리와 `admin_role_log` 읽기 질의는 코드에서 찾지 못했다(각각 4-1-5, 4-1-4).
