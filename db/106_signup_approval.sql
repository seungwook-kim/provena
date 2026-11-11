-- 운영 적용은 팀장 승인 뒤
CREATE TABLE IF NOT EXISTS signup_requests (
    request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid UNIQUE REFERENCES users(user_id),
    login_id text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    reviewed_by uuid REFERENCES users(user_id)
);
-- (status 로 거르는 질의가 코드에 없어(목록은 전체를 읽는다) status_requested_at 색인은 두지 않는다. db/109_realign.sql 이 옛 DB의 색인을 지운다)

-- password_hash를 포함하므로 Supabase Data API의 public 접근을 막는다.
ALTER TABLE signup_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE signup_requests FROM PUBLIC;
-- anon·authenticated는 Supabase에만 있다. 일반 Postgres(docker compose의 pgvector 이미지)에는 없어
-- REVOKE ... FROM anon 을 그대로 쓰면 초기화가 role "anon" does not exist 로 멈추므로, 역할이 있을 때만 회수한다.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON TABLE signup_requests FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON TABLE signup_requests FROM authenticated';
    END IF;
END
$$;
