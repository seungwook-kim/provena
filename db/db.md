# db/ : DB 초기화와 시드

## 이 폴더가 하는 일

pgvector 확장 생성(`01_init.sql`), 데모 계정 2개 시드. SQL 파일 번호대는 파트마다 100번대씩 나눈다.

- 주인: 김승욱
- 입력: 없음
- 출력: 스키마, 시드 데이터

## 운영 Supabase 인증 스키마 적용

회원가입 승인 기능은 `db/101_auth_users.sql` 적용 후 `db/106_signup_approval.sql`을 적용한다. 106은 비밀번호 해시 보호를 위해 RLS를 켜고 `PUBLIC`, `anon`, `authenticated`의 테이블 권한을 모두 회수한다. 이메일 가입 인증을 쓰는 앱을 배포하기 전에는 106 다음에 `db/107_email_signup_verification.sql`(인증 열과 색인), `db/108_auth_privacy_hardening.sql`(`users`·`signup_requests`와 id 시퀀스의 RLS, 권한 회수)을 이 순서로 적용한다. 107과 108은 몇 번을 돌려도 같은 결과이고, 108은 106·109처럼 `anon`·`authenticated` 역할이 있을 때만 해당 역할의 권한을 회수한다. 번호 107은 `docs/specs/107-user-profile-fields.md`(프로필 추가 칸 제안)와도 겹치지만 서로 다른 것이다. 그 제안은 SQL 파일이 없고 코드에 사용처(`role_enc`, `service_enc`)가 없어 적용하지 않는다. Google 로그인(`docs/specs/login.md`)을 켜려면 108 다음(파일 이름 순서상 마지막)에 `db/203_google_identities.sql`을 적용한다. `user_identities` 표를 만들고 `users`·`signup_requests`의 `password_hash`를 NULL 허용으로 바꾸며 `signup_requests.google_sub`를 더한다. 몇 번을 돌려도 같은 결과이고, `anon`·`authenticated` 권한 회수는 해당 역할이 있을 때만 한다(운영 적용은 팀장 승인 뒤).

일반 PostgreSQL(docker compose 등 Supabase가 아닌 환경)처럼 `anon`, `authenticated` 역할이 없으면 106은 해당 역할에 대한 권한 회수를 건너뛰고 RLS 활성화와 `PUBLIC` 권한 회수만 적용한다.

`ensure_schema()`는 `bootstrap_local_auth()`에서만 호출되며, `bootstrap_local_auth()` 자체가 `is_local_demo()`가 참인 로컬 데모 조건에서만 실행된다. 따라서 운영 환경에서는 앱 시작 시 인증 테이블이 자동으로 생성되지 않는다. 운영 Supabase에서는 아래 절차로 인증 SQL을 Supabase SQL Editor에서 수동 실행해야 한다.

1. `db/101_auth_users.sql`을 먼저 실행해 `users` 테이블을 만든다.
2. `db/103_auth_token_revocations.sql`을 두 번째로 실행해 `token_revocations` 테이블과 인덱스를 만든다. 이어서 `db/111_threads.sql`을 실행해 사용자별 대화 목록 `threads` 테이블(RLS 포함)을 만든다. 오래 걸리는 스키마 적용은 풀러가 아니라 직접 연결 문자열(`DATABASE_DIRECT_URL`)로 한다. 로컬 compose는 새 볼륨에서만 `db/` 바로 아래 SQL을 자동 적용하므로, 이미 만든 볼륨은 `docker compose down -v` 후 다시 올리거나 같은 SQL을 직접 실행한다(로컬 데모 모드에서는 앱이 시작할 때 `threads` 표를 만든다).
3. `101_auth_users.sql`을 이미 실행했거나 기존 DB에 `users` 테이블이 이미 있었다면, 다음 문장을 별도로 실행해 기존 테이블에도 RLS를 적용한다.

   ```sql
   ALTER TABLE users ENABLE ROW LEVEL SECURITY;
   ```

4. `token_revocations`에도 RLS를 활성화한다.

   ```sql
   ALTER TABLE token_revocations ENABLE ROW LEVEL SECURITY;
   ```

5. 내 정보·사용자 관리(`docs/specs/admin-roles.md`)를 쓰는 앱을 배포하기 전에 `db/104_user_profiles.sql`, `db/105_admin_role_log.sql`을 이 순서로 실행한다(둘 다 `users` 외래키, RLS 포함). `user_profiles`가 없으면 그 앱의 `/me`가 503이다.

적용 뒤에는 두 테이블의 존재 여부와 RLS 활성화 상태를 아래 SQL로 확인한다.

```sql
SELECT
    c.table_schema,
    c.table_name,
    c.table_type,
    (c.table_name = 'users') AS users_table,
    (c.table_name = 'token_revocations') AS token_revocations_table,
    cls.relrowsecurity AS rls_enabled
FROM information_schema.tables AS c
JOIN pg_class AS cls
  ON cls.relname = c.table_name
JOIN pg_namespace AS nsp
  ON nsp.oid = cls.relnamespace
 AND nsp.nspname = c.table_schema
WHERE c.table_schema = 'public'
  AND c.table_name IN ('users', 'token_revocations')
ORDER BY c.table_name;
```

앱이 실제로 접속하는 PostgreSQL 역할이 두 테이블의 소유자인지, 또는 RLS를 우회할 수 있는 역할(`rolbypassrls`)인지도 운영 DB에서 확인해야 한다. 앱 역할은 필요 이상의 권한을 갖지 않도록 확인하고, 해당 역할로 실제 로그인 요청을 보내 성공하는지와 잘못된 비밀번호가 거부되는지를 검증한다. RLS를 켰지만 앱 역할이 테이블 소유자도 RLS 우회 역할도 아니면서 필요한 정책이 없다면 로그인 조회가 실패할 수 있다.

```sql
SELECT
    cls.relname AS table_name,
    pg_get_userbyid(cls.relowner) AS table_owner,
    roles.rolname AS app_role,
    roles.rolbypassrls AS app_role_bypasses_rls
FROM pg_class AS cls
JOIN pg_namespace AS nsp ON nsp.oid = cls.relnamespace
LEFT JOIN pg_roles AS roles ON roles.rolname = current_user
WHERE nsp.nspname = 'public'
  AND cls.relname IN ('users', 'token_revocations');
```

운영 Supabase는 2026-11-09에 풀러 접속으로 읽기 전용 조회해 확인했다. public 스키마에 `users`, `threads`, `token_revocations`, `approvals`, `decision_tables`, `issue_tables`, `issue_table_rejections`, `docs`(1,512행), `chunks`(23,095행), `versions`, `index_meta`, `query_translations` 표가 있다. 따라서 인증 표(`users`, `token_revocations`)와 대화 표(`threads`, `111_threads.sql`)는 적용돼 있다. 같은 날 데모 계정 2개(일반 사용자 1개, 관리자 1개)를 `backend/services/auth_store.py`의 `upsert_user()`로 등록하고 다시 조회해 확인했다(비밀번호는 bcrypt 해시로만 저장). `threads`는 0행이어서 운영 경로로 대화한 적은 아직 없다. LangGraph 체크포인트·Store 표는 아직 없으며, `backend/graph/checkpoint.py`의 `setup()`이 앱 첫 기동 때 만든다. 위 SQL로 보는 RLS 활성화 상태, 앱 접속 역할의 소유 여부와 `rolbypassrls`, 운영 계정으로 한 실제 로그인은 확인하지 못했다(미확인).

## DB 재정렬 (`109_realign.sql`, 결정 0090)

구조 전체는 `docs/db/ERD.md`, 표별 칼럼·색인·권한은 `docs/db/TABLE_SPEC.md`에 있다.

- 합친 표: `answer_grounding`은 `answers.grounding`, `answers.skills_used`로, `recall_feedback`은 `recall_notices.feedback_*` 칸으로, `issue_table_rejections`는 `approvals.comment`, `decided_by`, `decided_at`으로 옮겼다. 새 DB는 `105`, `110`, `120`이 처음부터 합친 모양으로 만든다.
- `109_realign.sql`(1단계)은 옛 모양 DB를 올린다. 합칠 칸을 더하고 값을 복사만 하며 옛 표는 건드리지 않아서 옛 코드가 그대로 돈다. 쓰이지 않는 색인 7개(`answers_user_idx`, `issue_tables_thread_idx`, `issue_tables_user_idx`, `admin_role_log_at`, `token_revocations_expires_at`, `signup_requests_status_requested_at`, `recall_notices_review_idx`)를 지우고 `issue_tables_thread_user_idx`, `recall_notices_feedback_idx`, `chunks_link_targets_gin`을 만든다. `anon`, `authenticated` 역할이 있을 때만 public 표·뷰·시퀀스의 권한을 회수하고 앞으로 만드는 표의 기본 권한도 회수한다. 여러 번 실행해도 된다.
- 2단계 `db/manual/109_retire_old.sql`은 새 코드가 배포되고 옛 리비전이 내려간 뒤 사람이 직접 실행한다. 1단계 뒤에 옛 표에 쌓인 값을 새 칸으로 한 번 더 옮기고 옛 표 3개를 `<이름>_old_20261110`으로 이름만 바꾼다(되돌림은 이름을 되돌리면 된다). 이름이 바뀐 옛 표는 `db/manual/109_purge_old.sql`로 지운다. 백업 확인 뒤 직접 실행하며, 되돌릴 수 없다.
- 운영 적용 순서: 백업, `109_realign.sql`(옛 코드가 그대로 돈다), 새 코드 배포, 옛 리비전 내림, `manual/109_retire_old.sql`, 두어 날 뒤 `manual/109_purge_old.sql`. 1단계 뒤 새 코드가 뜨기 전까지 옛 코드가 옛 표에 쓴 값은 2단계가 옮긴다. 새 코드가 뜬 뒤 2단계 전까지 옛 리비전이 아직 요청을 받으면 그 요청이 쓴 값이 새 칸에 안 보일 수 있다(2단계가 채운다).
- 바꾸지 않은 것: LangGraph가 만드는 6개 표(구조 변경 금지), `users.groups`와 `chunks.acl`(문서 권한 F-06 연결 지점), `threads` 등의 `user_id` text 타입(결정 0091), 옛 판 `chunks` 행(결정 0092).

## 작업 기록 (최신이 위)

| 2026-11-10 | 강경희 (kyunghee) | `106_signup_approval.sql`의 `signup_requests`에 RLS를 활성화하고 `PUBLIC`, `anon`, `authenticated`의 테이블 권한을 회수하는 보안 설정을 반영. `101` 다음에 106을 적용함을 기록. 같은 줄의 "107 프로필 필드는 사용하지 않음"은 프로필 추가 칸 제안(`docs/specs/107-user-profile-fields.md`)을 가리키며, 같은 번호의 `107_email_signup_verification.sql`은 이메일 가입 인증에 쓰여 적용 대상이다(위 절 참고) | 미정 |

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-11 | 김승욱 (Claude Code) | `108_auth_privacy_hardening.sql`의 `REVOKE ... FROM anon, authenticated`를 역할이 있을 때만 실행하는 `DO` 블록으로 바꾸고 106과 겹치는 줄을 정리했다. 새 Postgres 16 컨테이너에 `db/`의 SQL을 compose와 같은 순서로 전부 실행해 오류 0, 108 뒤의 109 이후 파일까지 실행됨을 확인했고, 108을 한 번 더 돌리고 `anon`·`authenticated` 역할을 만든 뒤에도 돌려 오류 없이 권한 0건임을 확인했다. 운영 DB의 107·108 적용 여부는 이 저장소에서 확인하지 못했고 운영에는 적용하지 않았다(미적용) | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | `109_realign.sql`(표 3개 합침, 색인 정리, `anon`·`authenticated` 권한 회수), `manual/109_purge_old.sql` 추가, `105`·`110`·`120`을 합친 모양으로 수정, `docs/db/ERD.md`, `TABLE_SPEC.md` 추가. 운영에는 적용하지 않았다(미적용) | 미정 |
| 2026-11-09 | 박진형 (jinyeong-731) | `104_user_profiles.sql`(내 정보 암호문 표 `user_profiles`, `users` 외래키, RLS)과 `105_admin_role_log.sql`(관리자 등록·해제 기록 `admin_role_log`, RLS) 추가. 둘 다 `IF NOT EXISTS`라 다시 돌려도 된다. 운영 Supabase에는 적용하지 않았다(미적용) — `101` 다음에 104·105를 앱 재배포 전에 적용해야 한다(104가 없으면 `/me`가 503) | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `120_answers_recall.sql` 추가: `answers`, `citations`, `answer_grounding`, `recall_events`, `recall_notices`, `maintenance_candidates`, `webhook_subscriptions`, `webhook_deliveries`, `recall_feedback`, `recall_digests`, `change_monitoring`(모두 `IF NOT EXISTS`, RLS). 로컬 pgvector 컨테이너에 `01_init`, 1xx, 201, 202, 120 순으로 적용하고 120을 한 번 더 적용해 확인했고, `tests/test_recall_pg.py`가 저장소 SQL을 그 DB에서 시험한다. 운영 Supabase에는 적용하지 않았다(미적용) | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 운영 Supabase를 풀러 접속으로 읽기 전용 조회해 표 목록과 행 수(`docs` 1,512행, `chunks` 23,095행, `threads` 0행)를 확인하고, 데모 계정 2개 등록 뒤 `users` 2행을 확인하고, "운영 Supabase 인증 스키마 적용" 절의 미적용·미검증 서술을 확인 결과로 고쳤다. SQL은 실행하지 않았다 | 미정 |
| 2026-11-06 | 김승욱 (Claude Code) | `111_threads.sql` 추가: 사용자별 대화 목록 `threads`(PK `(user_id, thread_id)`, 인덱스 `(user_id, updated_at DESC)`, RLS). 운영 Supabase에는 적용하지 않았다(미적용) | 미정 |
| 2026-11-05 | 김승욱 (Claude Code) | `manual/chunks_hnsw_voyage4.sql` 추가: voyage-4 HNSW 색인 수동 실행 파일(`SEARCH_HNSW=1`일 때만 코드가 사용). 하위 폴더라 db 초기화와 `load_snapshot`이 적용하지 않는다. `201_search.sql`은 경로 주석만 고침 | 미정 |
| 2026-11-05 | 강경희 (kyunghee) | 운영 Supabase에서는 `ensure_schema()`가 실행되지 않는 조건과 `101_auth_users.sql` → `103_auth_token_revocations.sql` 수동 적용·RLS·접속 역할·로그인 검증 절차를 문서화했다. 운영 DB는 미적용·미검증으로 기록 | 미정 |
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | `202_sync.sql`: `sync_runs`·`changed_articles`에 RLS 켜기(정책 없음, `201_search.sql` 91~95줄과 같은 방식). 조장 요청 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | `201_search.sql`(검색 파트 200번대): `docs`·`versions`(판 유효 구간 `valid_from`·`valid_to`, `version_date_before`)·`chunks`(열쇠 (chunk_id, version_id), 줄 범위, 차원 없는 `vector`)·`index_meta`(색인 장부)·`query_translations`(번역 장부). 모두 `IF NOT EXISTS`라 compose 첫 기동(initdb)과 `loader`가 두 번 돌려도 같다 | 이 PR |
| 2026-10-30 | 김승욱 (Claude Code) | `101_auth_users.sql`(users 테이블, SQL 번호대 100번대는 김승욱 파트로 잡음) 추가. 데모 계정은 SQL이 아니라 앱 시작 때 환경변수로 시드한다 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
