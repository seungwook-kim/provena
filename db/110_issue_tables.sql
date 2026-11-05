-- 합동 검토 쟁점표 저장 (F-03, B-11). 사람 승인(approve=true)이 들어온 뒤에만 한 줄이 생긴다. 승인 전·반려된 표는 여기에 넣지 않는다.
-- SQL 번호대 100번대는 김승욱 파트. 101은 users, 이 파일은 110으로 두어 결정표·승인함 테이블(다른 번호)과 겹치지 않게 한다.
-- 쟁점표 한 행의 모양(issue_rows 배열의 원소)은 backend/graph/departments/issue_table.py의 ROW_FIELDS가 정한다:
-- team, team_label, topic, issue, stance, confidence, chunk_id, rule_seq, rule_title, article, section_path, version_id, version_date, version_date_before, source_url, conflict.
-- 여러 번 돌려도 된다. 승인함(approvals)과 외래 키로 묶지 않는다: approvals는 다른 파일이 만들고, approval_id 문자열만 같은 값으로 맞춘다.
CREATE TABLE IF NOT EXISTS issue_tables (
    table_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id  text NOT NULL UNIQUE,           -- 같은 승인으로 두 번 저장되지 않는다(재개가 겹쳐도 한 줄)
    thread_id    text NOT NULL,
    user_id      text NOT NULL,                  -- 검토를 요청한 사용자
    request      text NOT NULL,                  -- 요청 원문
    as_of        date,                           -- 검색 기준일
    issue_rows   jsonb NOT NULL CHECK (jsonb_typeof(issue_rows) = 'array'),
    unreviewed   jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(unreviewed) = 'array'),  -- 검토하지 못한 팀과 이유
    approved_by  text,                           -- 승인한 관리자 user_id
    approved_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS issue_tables_thread_idx ON issue_tables (thread_id);
CREATE INDEX IF NOT EXISTS issue_tables_user_idx ON issue_tables (user_id, approved_at DESC);

-- 반려 기록. 쟁점표는 저장하지 않고 사유만 남긴다.
CREATE TABLE IF NOT EXISTS issue_table_rejections (
    approval_id  text PRIMARY KEY,
    thread_id    text NOT NULL,
    user_id      text NOT NULL,
    reason       text NOT NULL DEFAULT '',
    decided_by   text,
    decided_at   timestamptz NOT NULL DEFAULT now()
);

-- 앱은 DATABASE_URL 의 소유자 권한으로 읽고 쓴다(201_search.sql 과 같은 방침: RLS 를 켜고 정책을 두지 않아 공개 API 키로는 못 보게 잠근다)
ALTER TABLE issue_tables ENABLE ROW LEVEL SECURITY;
ALTER TABLE issue_table_rejections ENABLE ROW LEVEL SECURITY;
