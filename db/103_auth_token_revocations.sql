-- Persistent JWT revocations for logout. Retain each JTI through its token
-- expiry so every API instance can reject an already-logged-out session.
-- This migration is idempotent and never alters or removes existing users.
CREATE TABLE IF NOT EXISTS token_revocations (
    jti        uuid PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz NOT NULL DEFAULT now()
);

-- (만료 행을 지우는 정리 작업이 코드에 없어 expires_at 색인은 두지 않는다. db/109_realign.sql 이 옛 DB의 색인을 지운다.
--  정리 작업을 만들 때 DELETE ... WHERE expires_at < now() 와 함께 색인을 다시 만든다)

ALTER TABLE token_revocations ENABLE ROW LEVEL SECURITY;
