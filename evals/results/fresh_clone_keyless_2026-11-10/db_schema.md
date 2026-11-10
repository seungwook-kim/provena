# DB 스키마 확인 (db/*.sql로 새로 만든 DB, 109 포함)

## 초기화 로그 (적용 순서, ERROR·FATAL 없음)

```text

db-1  | running bootstrap script ... ok
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/01_init.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/101_auth_users.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/102_decision_approvals.sql
db-1  | psql:/docker-entrypoint-initdb.d/102_decision_approvals.sql:29: NOTICE:  constraint "approvals_kind_check" of relation "approvals" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/102_decision_approvals.sql:33: NOTICE:  constraint "approvals_thread_id_kind_key" of relation "approvals" does not exist, skipping
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/103_auth_token_revocations.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/104_user_profiles.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/105_admin_role_log.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/106_signup_approval.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/109_realign.sql
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:82: NOTICE:  index "answers_user_idx" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:83: NOTICE:  index "issue_tables_thread_idx" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:84: NOTICE:  index "issue_tables_user_idx" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:85: NOTICE:  index "admin_role_log_at" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:89: NOTICE:  index "token_revocations_expires_at" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:90: NOTICE:  index "signup_requests_status_requested_at" does not exist, skipping
db-1  | psql:/docker-entrypoint-initdb.d/109_realign.sql:91: NOTICE:  index "recall_notices_review_idx" does not exist, skipping
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/110_issue_tables.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/111_threads.sql
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/120_answers_recall.sql
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:19: NOTICE:  column "grounding" of relation "answers" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:20: NOTICE:  column "skills_used" of relation "answers" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:84: NOTICE:  column "feedback_useful" of relation "recall_notices" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:85: NOTICE:  column "feedback_reason" of relation "recall_notices" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:86: NOTICE:  column "feedback_by" of relation "recall_notices" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/120_answers_recall.sql:87: NOTICE:  column "feedback_at" of relation "recall_notices" already exists, skipping
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/201_search.sql
db-1  | psql:/docker-entrypoint-initdb.d/201_search.sql:3: NOTICE:  extension "vector" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/201_search.sql:55: NOTICE:  column "line_start" of relation "chunks" already exists, skipping
db-1  | psql:/docker-entrypoint-initdb.d/201_search.sql:56: NOTICE:  column "line_end" of relation "chunks" already exists, skipping
db-1  | /usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/202_sync.sql
```

## answers 표 (합친 칸 grounding, skills_used 포함)

```text
                          Table "public.answers"
   Column    |           Type           | Collation | Nullable | Default  
-------------+--------------------------+-----------+----------+----------
 answer_id   | text                     |           | not null | 
 user_id     | text                     |           | not null | 
 thread_id   | text                     |           | not null | ''::text
 question    | text                     |           | not null | 
 answer      | text                     |           | not null | 
 as_of       | text                     |           |          | 
 created_at  | timestamp with time zone |           | not null | now()
 grounding   | jsonb                    |           |          | 
 skills_used | jsonb                    |           |          | 
Indexes:
    "answers_pkey" PRIMARY KEY, btree (answer_id)
Referenced by:
    TABLE "citations" CONSTRAINT "citations_answer_id_fkey" FOREIGN KEY (answer_id) REFERENCES answers(answer_id) ON DELETE CASCADE
Policies (row security enabled): (none)

 count 
-------
 23095
(1 row)
```

## 표 목록, 행 수

```text
                List of relations
 Schema |          Name          | Type  | Owner 
--------+------------------------+-------+-------
 public | admin_role_log         | table | app
 public | answers                | table | app
 public | approvals              | table | app
 public | change_monitoring      | table | app
 public | changed_articles       | table | app
 public | checkpoint_blobs       | table | app
 public | checkpoint_migrations  | table | app
 public | checkpoint_writes      | table | app
 public | checkpoints            | table | app
 public | chunks                 | table | app
 public | citations              | table | app
 public | decision_tables        | table | app
 public | docs                   | table | app
 public | index_meta             | table | app
 public | issue_tables           | table | app
 public | maintenance_candidates | table | app
 public | query_translations     | table | app
 public | recall_digests         | table | app
 public | recall_events          | table | app
 public | recall_notices         | table | app
 public | signup_requests        | table | app
 public | store                  | table | app
 public | store_migrations       | table | app
 public | sync_runs              | table | app
 public | threads                | table | app
 public | token_revocations      | table | app
 public | user_profiles          | table | app
 public | users                  | table | app
 public | versions               | table | app
 public | webhook_deliveries     | table | app
 public | webhook_subscriptions  | table | app
(31 rows)
 citations 
-----------
         0
(1 row)

 threads 
---------
      10
(1 row)

 users 
-------
     2
(1 row)

 count 
-------
     0
(1 row)

 table_name 
------------
(0 rows)
 answer_id | q | has_grounding | g 
-----------+---+---------------+---
(0 rows)
```
