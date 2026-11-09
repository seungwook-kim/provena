# db/ : DB 초기화와 시드

## 이 폴더가 하는 일

pgvector 확장 생성(`01_init.sql`), 데모 계정 2개 시드. SQL 파일 번호대는 파트마다 100번대씩 나눈다.

- 주인: 김승욱
- 입력: 없음
- 출력: 스키마, 시드 데이터

## 운영 Supabase 인증 스키마 적용

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

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
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
