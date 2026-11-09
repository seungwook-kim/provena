-- Proposal only. Do not execute without owner/team approval.
-- Existing db/101_auth_users.sql and db/105_admin_role_log.sql remain unchanged.
CREATE TABLE signup_requests (
    request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL UNIQUE REFERENCES users(user_id),
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    reviewed_by uuid REFERENCES users(user_id)
);
CREATE INDEX signup_requests_status_requested_at ON signup_requests(status, requested_at);
