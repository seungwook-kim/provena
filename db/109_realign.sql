-- DB 재정렬 (2026-11-10, 결정 0090). 표 3개를 기존 표에 합치고, 쓰이지 않는 색인을 지우고, 공개 API 역할의 권한을 거둔다.
-- 번호 109: 107, 108(이메일 가입 인증, 개인정보 보호)은 PR #113이 쓰고, 110 이후는 기존 파일이 쓴다. 이 파일은 모든 단계가 "있을 때만" 움직여서
-- 어느 순서로 실행해도(새 DB에서 110·120보다 먼저 돌아도) 같은 결과가 되고, 여러 번 돌려도 된다. 새 DB의 모양은 110, 120, 105 파일이 이미 합친 구조로 만든다.
-- 이 파일이 하는 일은 "옛 모양으로 만들어진 DB(운영 Supabase)를 합친 구조로 올리는 것"이다.
--
--   1. answer_grounding  -> answers.grounding, answers.skills_used          (1:1 표 합침. /chat 한 번에 INSERT 한 문장이 준다)
--   2. recall_feedback   -> recall_notices.feedback_useful/_reason/_by/_at  (알림당 1줄 표 합침. 집계 색인은 부분 색인 하나)
--   3. issue_table_rejections -> approvals (comment, decided_by, decided_at)  (approvals 가 반려 사유·결정자·시각을 이미 갖는다)
--   4. 쓰이지 않은 색인 7개 지움: answers_user_idx, issue_tables_thread_idx, issue_tables_user_idx(세 열 색인 하나로 대체), admin_role_log_at,
--      token_revocations_expires_at, signup_requests_status_requested_at, recall_notices_review_idx. 색인 하나 추가: chunks_link_targets_gin(함께 볼 정책 찾기)
--   5. public 표·시퀀스에서 anon, authenticated 권한 회수(역할이 있을 때만). 앱은 소유자 역할로 접속하므로 영향이 없다.
--
-- 되돌리기: 옛 표는 지우지 않고 이름만 바꿔 둔다(<이름>_old_20261110, 데이터 그대로). 되돌릴 때는 새 코드를 내리고
--   ALTER TABLE answer_grounding_old_20261110 RENAME TO answer_grounding;  (recall_feedback, issue_table_rejections 도 같은 식)
-- 옛 표를 완전히 지우는 일은 db/manual/109_purge_old.sql 이다(되돌릴 일이 없다고 확인한 뒤 수동으로).
-- 색인을 되돌리려면 db/120_answers_recall.sql 이전 판의 CREATE INDEX 문을 다시 실행한다(이 파일의 단계 4 주석에 정의를 적어 둔다).

-- 1. answer_grounding -> answers
DO $$
BEGIN
    IF to_regclass('public.answers') IS NOT NULL THEN
        ALTER TABLE answers ADD COLUMN IF NOT EXISTS grounding   jsonb;
        ALTER TABLE answers ADD COLUMN IF NOT EXISTS skills_used jsonb;
        IF to_regclass('public.answer_grounding') IS NOT NULL THEN
            UPDATE answers a SET grounding = g.grounding, skills_used = g.skills_used
              FROM answer_grounding g WHERE g.answer_id = a.answer_id;
            IF to_regclass('public.answer_grounding_old_20261110') IS NULL THEN
                ALTER TABLE answer_grounding RENAME TO answer_grounding_old_20261110;
            ELSE
                RAISE NOTICE 'answer_grounding_old_20261110 already exists; answer_grounding left in place';
            END IF;
        END IF;
    END IF;
END
$$;

-- 2. recall_feedback -> recall_notices
DO $$
DECLARE orphan integer;
BEGIN
    IF to_regclass('public.recall_notices') IS NOT NULL THEN
        ALTER TABLE recall_notices ADD COLUMN IF NOT EXISTS feedback_useful boolean;
        ALTER TABLE recall_notices ADD COLUMN IF NOT EXISTS feedback_reason text;
        ALTER TABLE recall_notices ADD COLUMN IF NOT EXISTS feedback_by     text;
        ALTER TABLE recall_notices ADD COLUMN IF NOT EXISTS feedback_at     timestamptz;
        CREATE INDEX IF NOT EXISTS recall_notices_feedback_idx
            ON recall_notices (user_id, change_pattern, (changed ->> 'article'), ((changed ->> 'rule_seq')::bigint))
            WHERE feedback_useful IS NOT NULL;
        IF to_regclass('public.recall_feedback') IS NOT NULL THEN
            UPDATE recall_notices n
               SET feedback_useful = f.useful, feedback_reason = f.reason, feedback_by = f.given_by, feedback_at = f.created_at
              FROM recall_feedback f WHERE f.notice_id = n.notice_id;
            SELECT count(*) INTO orphan FROM recall_feedback f
             WHERE NOT EXISTS (SELECT 1 FROM recall_notices n WHERE n.notice_id = f.notice_id);
            IF orphan > 0 THEN
                RAISE NOTICE 'recall_feedback rows without a notice (kept only in the _old table): %', orphan;
            END IF;
            IF to_regclass('public.recall_feedback_old_20261110') IS NULL THEN
                ALTER TABLE recall_feedback RENAME TO recall_feedback_old_20261110;
            ELSE
                RAISE NOTICE 'recall_feedback_old_20261110 already exists; recall_feedback left in place';
            END IF;
        END IF;
    END IF;
END
$$;

-- 3. issue_table_rejections -> approvals
DO $$
BEGIN
    IF to_regclass('public.issue_table_rejections') IS NOT NULL THEN
        IF to_regclass('public.approvals') IS NOT NULL THEN
            UPDATE approvals a
               SET comment    = CASE WHEN a.comment = '' THEN r.reason ELSE a.comment END,
                   decided_by = COALESCE(a.decided_by, r.decided_by),
                   decided_at = COALESCE(a.decided_at, r.decided_at)
              FROM issue_table_rejections r
             WHERE r.approval_id = a.approval_id AND a.kind = 'issue_table';
        END IF;
        IF to_regclass('public.issue_table_rejections_old_20261110') IS NULL THEN
            ALTER TABLE issue_table_rejections RENAME TO issue_table_rejections_old_20261110;
        ELSE
            RAISE NOTICE 'issue_table_rejections_old_20261110 already exists; issue_table_rejections left in place';
        END IF;
    END IF;
END
$$;

-- 4. 색인 정리 (근거: 운영 조회 2026-11-10, 통계 초기화 2026-10-29 이후 idx_scan 0이고 코드에 그 열로 찾는 질의가 없다)
--   answers_user_idx            ON answers (user_id, created_at DESC)
--   issue_tables_thread_idx     ON issue_tables (thread_id)
--   issue_tables_user_idx       ON issue_tables (user_id, approved_at DESC)
--   admin_role_log_at           ON admin_role_log (at)
DROP INDEX IF EXISTS answers_user_idx;
DROP INDEX IF EXISTS issue_tables_thread_idx;
DROP INDEX IF EXISTS issue_tables_user_idx;
DROP INDEX IF EXISTS admin_role_log_at;
--   token_revocations_expires_at  ON token_revocations (expires_at)             (만료 행을 지우는 코드가 없다)
--   signup_requests_status_requested_at ON signup_requests (status, requested_at) (status 로 거르는 질의가 없다)
--   recall_notices_review_idx     ON recall_notices (created_at DESC) WHERE review_status = 'pending' (검토함은 전체를 읽어 앱에서 거른다)
DROP INDEX IF EXISTS token_revocations_expires_at;
DROP INDEX IF EXISTS signup_requests_status_requested_at;
DROP INDEX IF EXISTS recall_notices_review_idx;
-- 추가: chunks.link_targets GIN (maintenance.py linked_from 의 `link_targets @> ARRAY[대상]`. 합성 데이터에서 chunks 전체 훑기 8.969 ms 를 대체)
DO $$
BEGIN
    IF to_regclass('public.chunks') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS chunks_link_targets_gin ON chunks USING gin (link_targets);
    END IF;
END
$$;
DO $$
BEGIN
    IF to_regclass('public.issue_tables') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS issue_tables_thread_user_idx ON issue_tables (thread_id, user_id, approved_at DESC);
    END IF;
END
$$;

-- 5. 공개 API 역할 권한 회수. 운영 Supabase는 public 의 모든 표에 anon, authenticated 권한을 열어 두었다(RLS 가 막고 있었다).
--    RLS 에 더해 권한도 거두어 이중으로 잠근다. 일반 Postgres(역할 없음)에서는 건너뛴다. 앞으로 만들어지는 표도 같게 된다(기본 권한).
DO $$
DECLARE
    r record;
    roles text;
BEGIN
    SELECT string_agg(quote_ident(rolname), ', ') INTO roles FROM pg_roles WHERE rolname IN ('anon', 'authenticated');
    IF roles IS NULL THEN
        RETURN;
    END IF;
    FOR r IN
        SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
    LOOP
        IF r.relkind = 'S' THEN
            EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM %s', r.relname, roles);
        ELSE
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %s', r.relname, roles);
        END IF;
    END LOOP;
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %s', roles);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %s', roles);
END
$$;
