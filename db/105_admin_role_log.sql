-- 관리자 등록·해제 기록 (docs/specs/admin-roles.md, 요청 2번). 쓰기: backend/services/auth_store.py set_role (역할 변경과 한 트랜잭션).
-- 100번대 = 로그인·사용자(db/101_auth_users.sql:2, 김승욱 파트). 102는 결정표(PR #54), 103은 PR #53이 써서 105(11/5 조장 답). 내 정보는 db/104_user_profiles.sql.
-- 화면(최고 관리자)에서 한 일만 남긴다. create_account 명령으로 만든 계정은 여기 남지 않는다.
-- 칸은 누가·누구를·무엇을·언제만. 아이디 문자열·IP·브라우저 정보는 넣지 않는다. 여러 번 돌려도 된다.
CREATE TABLE IF NOT EXISTS admin_role_log (
    log_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at             timestamptz NOT NULL DEFAULT now(),
    by_user_id     uuid NOT NULL REFERENCES users(user_id),
    target_user_id uuid NOT NULL REFERENCES users(user_id),
    action         text NOT NULL CHECK (action IN ('promote', 'revoke'))
);
CREATE INDEX IF NOT EXISTS admin_role_log_at ON admin_role_log (at);
-- Supabase는 public 표를 Data API로 내보낸다(db/201_search.sql:90 설명과 같은 이유).
ALTER TABLE admin_role_log ENABLE ROW LEVEL SECURITY;
