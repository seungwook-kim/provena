-- 108_auth_privacy_hardening.sql
-- 인증 테이블은 서버(앱 DB 역할)만 읽고 쓴다. Supabase Data API 역할(anon, authenticated)에는
-- 접근 권한을 주지 않는다. 클라이언트 쪽 테이블 접근은 필요 없다.
--
-- anon·authenticated는 Supabase에만 있다. 일반 Postgres(docker compose의 pgvector 이미지)에는 없어
-- REVOKE ... FROM anon 을 그대로 쓰면 초기화가 role "anon" does not exist 로 멈춘다.
-- 그래서 106·109와 같은 방식으로 역할이 있을 때만 회수한다. 몇 번을 돌려도 같은 결과(멱등)다.
--
-- signup_requests 테이블의 PUBLIC 권한 회수는 db/106_signup_approval.sql 이 이미 한다.
-- 이 파일은 106이 다루지 않는 users 테이블과 signup_requests 의 id 시퀀스를 맡고,
-- 106을 적용하지 않은 DB를 위해 signup_requests 의 RLS 켜기와 역할 회수는 한 번 더 한다(멱등).
-- 적용 순서: 106 -> 107 -> 108 (docker compose 의 initdb 는 파일 이름 순서로 돌린다).

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE signup_requests ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE users FROM PUBLIC;
REVOKE ALL ON SEQUENCE signup_requests_request_id_seq FROM PUBLIC;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE users FROM %I', r);
            EXECUTE format('REVOKE ALL ON TABLE signup_requests FROM %I', r);
            EXECUTE format('REVOKE ALL ON SEQUENCE signup_requests_request_id_seq FROM %I', r);
        END IF;
    END LOOP;
END
$$;
