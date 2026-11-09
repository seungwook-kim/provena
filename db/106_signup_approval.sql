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
CREATE INDEX IF NOT EXISTS signup_requests_status_requested_at ON signup_requests(status, requested_at);
