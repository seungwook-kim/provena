-- db/manual/109_retire_old.sql : DB 재정렬 2단계 "정리". 수동으로 한 번 실행한다(자동 적용 안 됨: compose 초기화와 시험은 db/ 바로 아래 파일만 실행한다).
-- 실행 시점: db/109_realign.sql(1단계)을 적용하고, 새 코드를 배포하고, 옛 리비전이 내려가 모든 요청이 새 코드로 간 뒤.
-- 하는 일: (1) 1단계와 같은 값 옮기기를 한 번 더 한다. 1단계와 새 코드 배포 사이에 옛 코드가 옛 표(answer_grounding, recall_feedback,
--   issue_table_rejections)에 쓴 행을 새 칸으로 옮기는 것이다. 새 칸에 이미 값이 있으면 덮어쓰지 않는다. (2) 옛 표를 지우지 않고 이름만
--   <이름>_old_20261110 으로 바꾼다. 이 파일을 실행한 뒤 옛 코드는 옛 표를 못 찾는다(되돌리려면 새 코드를 내리고 이름을 되돌린다).
-- 여러 번 실행해도 된다(옛 표가 이미 없거나 _old 이름이 이미 있으면 건너뛴다). 옛 표를 완전히 지우는 일은 db/manual/109_purge_old.sql 이다.
BEGIN;

-- 1. answer_grounding -> answers
DO $$
BEGIN
    IF to_regclass('public.answer_grounding') IS NOT NULL THEN
        IF to_regclass('public.answers') IS NOT NULL THEN
            UPDATE answers a SET grounding = g.grounding, skills_used = g.skills_used
              FROM answer_grounding g WHERE g.answer_id = a.answer_id AND a.grounding IS NULL;
        END IF;
        IF to_regclass('public.answer_grounding_old_20261110') IS NULL THEN
            ALTER TABLE answer_grounding RENAME TO answer_grounding_old_20261110;
        ELSE
            RAISE NOTICE 'answer_grounding_old_20261110 already exists; answer_grounding left in place';
        END IF;
    END IF;
END
$$;

-- 2. recall_feedback -> recall_notices
DO $$
DECLARE orphan integer;
BEGIN
    IF to_regclass('public.recall_feedback') IS NOT NULL THEN
        IF to_regclass('public.recall_notices') IS NOT NULL THEN
            UPDATE recall_notices n
               SET feedback_useful = f.useful, feedback_reason = f.reason, feedback_by = f.given_by, feedback_at = f.created_at
              FROM recall_feedback f WHERE f.notice_id = n.notice_id AND n.feedback_useful IS NULL;
            SELECT count(*) INTO orphan FROM recall_feedback f
             WHERE NOT EXISTS (SELECT 1 FROM recall_notices n WHERE n.notice_id = f.notice_id);
            IF orphan > 0 THEN
                RAISE NOTICE 'recall_feedback rows without a notice (kept only in the _old table): %', orphan;
            END IF;
        END IF;
        IF to_regclass('public.recall_feedback_old_20261110') IS NULL THEN
            ALTER TABLE recall_feedback RENAME TO recall_feedback_old_20261110;
        ELSE
            RAISE NOTICE 'recall_feedback_old_20261110 already exists; recall_feedback left in place';
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

COMMIT;
