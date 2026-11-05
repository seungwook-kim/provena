# db/ : DB 초기화와 시드

## 이 폴더가 하는 일

pgvector 확장 생성(`01_init.sql`), 데모 계정 2개 시드. SQL 파일 번호대는 파트마다 100번대씩 나눈다.

- 주인: 김승욱
- 입력: 없음
- 출력: 스키마, 시드 데이터

## 운영 Supabase 인증 스키마 적용

`ensure_schema()`는 `bootstrap_local_auth()`에서만 호출되며, `bootstrap_local_auth()` 자체가 `is_local_demo()`가 참인 로컬 데모 조건에서만 실행된다. 따라서 운영 환경에서는 앱 시작 시 인증 테이블이 자동으로 생성되지 않는다. 운영 Supabase에서는 아래 절차로 인증 SQL을 Supabase SQL Editor에서 수동 실행해야 한다.

1. `db/101_auth_users.sql`을 먼저 실행해 `users` 테이블을 만든다.
2. `db/103_auth_token_revocations.sql`을 두 번째로 실행해 `token_revocations` 테이블과 인덱스를 만든다.
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

운영 Supabase에 위 SQL을 아직 적용하지 않았으므로, 운영 DB의 테이블 존재·RLS·접속 역할·실제 로그인은 미적용·미검증 상태이다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-05 | 김승욱 (Claude Code) | `manual/chunks_hnsw_voyage4.sql` 추가: voyage-4 HNSW 색인 수동 실행 파일(`SEARCH_HNSW=1`일 때만 코드가 사용). 하위 폴더라 db 초기화와 `load_snapshot`이 적용하지 않는다. `201_search.sql`은 경로 주석만 고침 | 미정 |
| 2026-11-05 | 강경희 (kyunghee) | 운영 Supabase에서는 `ensure_schema()`가 실행되지 않는 조건과 `101_auth_users.sql` → `103_auth_token_revocations.sql` 수동 적용·RLS·접속 역할·로그인 검증 절차를 문서화했다. 운영 DB는 미적용·미검증으로 기록 | 미정 |
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | `202_sync.sql`: `sync_runs`·`changed_articles`에 RLS 켜기(정책 없음, `201_search.sql` 91~95줄과 같은 방식). 조장 요청 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | `201_search.sql`(검색 파트 200번대): `docs`·`versions`(판 유효 구간 `valid_from`·`valid_to`, `version_date_before`)·`chunks`(열쇠 (chunk_id, version_id), 줄 범위, 차원 없는 `vector`)·`index_meta`(색인 장부)·`query_translations`(번역 장부). 모두 `IF NOT EXISTS`라 compose 첫 기동(initdb)과 `loader`가 두 번 돌려도 같다 | 이 PR |
| 2026-10-30 | 김승욱 (Claude Code) | `101_auth_users.sql`(users 테이블, SQL 번호대 100번대는 김승욱 파트로 잡음) 추가. 데모 계정은 SQL이 아니라 앱 시작 때 환경변수로 시드한다 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
