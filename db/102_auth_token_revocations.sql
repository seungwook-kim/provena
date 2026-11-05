-- Persistent JWT revocations for logout. Retain each JTI through its token
-- expiry so every API instance can reject an already-logged-out session.
-- This migration is idempotent and never alters or removes existing users.
CREATE TABLE IF NOT EXISTS token_revocations (
    jti        uuid PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS token_revocations_expires_at
    ON token_revocations (expires_at);
