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

CREATE UNIQUE INDEX IF NOT EXISTS signup_requests_login_id_lower_unique
    ON signup_requests (lower(login_id))
    WHERE position('@' in login_id) > 0;
