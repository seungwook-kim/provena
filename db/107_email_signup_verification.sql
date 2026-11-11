ALTER TABLE signup_requests
    ADD COLUMN IF NOT EXISTS email_verification_required boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS email_verified_at timestamptz,
    ADD COLUMN IF NOT EXISTS verification_code_hash text,
    ADD COLUMN IF NOT EXISTS verification_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS verification_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verification_send_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_verification_sent_at timestamptz;

CREATE INDEX IF NOT EXISTS signup_requests_verification_expiry
    ON signup_requests(verification_expires_at)
    WHERE email_verification_required AND email_verified_at IS NULL;

-- 113 이 이 색인을 거절 행을 뺀 signup_requests_login_id_lower_open_unique 로 바꾼다. 113 이 이미 적용된 DB 에서
-- 이 파일을 다시 돌릴 때(로컬 ensure_schema 는 시작할 때마다 돌린다) 옛 색인을 되살리지 않는다. 되살리면
-- 거절 행과 같은 이메일의 새 신청이 함께 있을 때 UniqueViolation 으로 멈춘다. 113 전 DB 에서는 전과 같이 만든다.
DO $$
BEGIN
    IF to_regclass('signup_requests_login_id_lower_open_unique') IS NULL THEN
        CREATE UNIQUE INDEX IF NOT EXISTS signup_requests_login_id_lower_unique
            ON signup_requests (lower(login_id))
            WHERE position('@' in login_id) > 0;
    END IF;
END
$$;
