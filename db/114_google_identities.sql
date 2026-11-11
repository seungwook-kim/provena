-- 운영 적용은 팀장 승인 뒤
-- Google 로그인 계정 연결. 101·106 다음에 적용한다(번호: 인증 파트 100번대, 113 다음 114).
-- 방식: 구글이 인증한(email_verified=true) 이메일이 기존 계정의 login_id(이메일)와 정확히 같으면 그 계정에 연결한다.
-- 연결은 user_identities 한 줄이고 users 의 role·is_active 는 바꾸지 않는다. 계정이 없으면 signup_requests 에 대기 신청을 만든다.
-- 여러 번 돌려도 된다. 일반 PostgreSQL 에서도 통과한다(anon·authenticated 는 역할이 있을 때만 쓴다).

CREATE TABLE IF NOT EXISTS user_identities (
    provider   text        NOT NULL CHECK (provider IN ('google')),
    subject    text        NOT NULL,                                          -- 구글 sub (구글 쪽 고유 번호)
    user_id    uuid        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    email      text        NOT NULL,                                          -- 마지막으로 본 구글 이메일(참고용, 계정 찾기에는 sub 만 쓴다)
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, subject),
    UNIQUE (provider, user_id)                                                -- 한 계정에 구글 계정은 하나
);

-- 구글로만 만든 계정은 비밀번호가 없다.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE signup_requests ALTER COLUMN password_hash DROP NOT NULL;

-- 구글 가입 신청은 승인 전에 sub 를 들고 있다가, 승인할 때 user_identities 로 옮긴다.
ALTER TABLE signup_requests ADD COLUMN IF NOT EXISTS google_sub text;
CREATE UNIQUE INDEX IF NOT EXISTS signup_requests_google_sub_key ON signup_requests (google_sub) WHERE google_sub IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'signup_requests_secret_or_google') THEN
        ALTER TABLE signup_requests ADD CONSTRAINT signup_requests_secret_or_google
            CHECK (password_hash IS NOT NULL OR google_sub IS NOT NULL);
    END IF;
END $$;

-- 인증 표는 서버(앱 DB 역할)만 읽고 쓴다(108과 같은 방식).
ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE user_identities FROM PUBLIC;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE user_identities FROM %I', r);
        END IF;
    END LOOP;
END
$$;
