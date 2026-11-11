-- 112_signup_edges.sql
-- 이메일 가입의 모서리 두 가지를 DB 쪽에서 맞춘다. 몇 번을 돌려도 같은 결과(멱등)이고 일반 Postgres에서도 돈다
-- (anon·authenticated 역할을 쓰지 않는다). 적용 순서: 106 -> 107 -> 108 -> 112 (docker initdb 는 이름 순서로 돌린다).
--
-- 1) 거절된 이메일도 다시 가입 신청할 수 있게 한다.
--    106 의 signup_requests.login_id UNIQUE 와 107 의 lower(login_id) 유니크 색인은 거절된 행까지 막는다.
--    둘을 지우고 "거절되지 않은 행"에만 거는 부분 유니크 색인으로 바꾼다. 거절 행은 기록으로 남고,
--    같은 login_id 의 신청 중 거절되지 않은 것은 하나뿐이다. 코드는 ORDER BY request_id DESC LIMIT 1 로 가장 최근 행을 읽는다.
--    이메일 아이디는 대소문자 구분 없이(lower), 이메일이 아닌 아이디는 그대로(대소문자 구분) 유일하다.
-- 2) users 의 이메일 아이디를 소문자로 맞추고 소문자 기준 유니크 색인을 건다.
--    가입은 이메일을 소문자로 저장하고 로그인도 소문자로 찾지만, 그 규칙 전에 대문자로 저장된 계정은 로그인이 401이었다.
--    대소문자만 다른 이메일 계정이 이미 둘 이상 있으면 어느 것이 진짜인지 정할 수 없으므로 그 쌍은 건드리지 않고
--    (NOTICE 로 알린다) 그 경우에는 색인도 만들지 않는다. 사람이 정리한 뒤 이 파일을 다시 돌리면 된다.
--    비이메일 아이디(예: demo 계정 'Admin')는 대소문자를 구분하므로 바꾸지 않는다.

ALTER TABLE signup_requests DROP CONSTRAINT IF EXISTS signup_requests_login_id_key;
DROP INDEX IF EXISTS signup_requests_login_id_lower_unique;

CREATE UNIQUE INDEX IF NOT EXISTS signup_requests_login_id_open_unique
    ON signup_requests (login_id)
    WHERE status <> 'rejected';

CREATE UNIQUE INDEX IF NOT EXISTS signup_requests_login_id_lower_open_unique
    ON signup_requests (lower(login_id))
    WHERE position('@' in login_id) > 0 AND status <> 'rejected';

DO $$
DECLARE
    clash integer;
BEGIN
    -- 소문자로 바꿔도 다른 계정과 겹치지 않는 이메일 계정만 바꾼다
    UPDATE users u
       SET login_id = lower(u.login_id)
     WHERE position('@' in u.login_id) > 0
       AND u.login_id <> lower(u.login_id)
       AND NOT EXISTS (
            SELECT 1 FROM users o
             WHERE o.user_id <> u.user_id
               AND position('@' in o.login_id) > 0
               AND lower(o.login_id) = lower(u.login_id));

    SELECT count(*) INTO clash FROM (
        SELECT lower(login_id) FROM users
         WHERE position('@' in login_id) > 0
         GROUP BY lower(login_id) HAVING count(*) > 1) d;
    IF clash > 0 THEN
        RAISE NOTICE 'users: 대소문자만 다른 이메일 계정 % 쌍이 있어 소문자 유니크 색인을 만들지 않았습니다. 정리 뒤 112를 다시 실행하세요.', clash;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS users_login_id_lower_unique
            ON users (lower(login_id))
            WHERE position('@' in login_id) > 0;
    END IF;
END
$$;
