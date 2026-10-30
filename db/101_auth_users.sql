-- 사용자 계정 (SDD 5장 users). 로그인: backend/auth.py (bcrypt 해시 + JWT 쿠키), 조회: backend/services/auth_store.py.
-- SQL 번호대 100번대는 김승욱 파트(로그인·사용자). 200번대는 검색·데이터(박진형), 300번대는 서비스(강경희)에 남겨 둔다.
-- 계정 값(아이디·비밀번호)은 이 파일에 쓰지 않는다. 로컬 데모 계정은 앱이 시작할 때 환경변수로 해시해 넣는다
-- (backend/services/demo_seed.py, PROVENA_ENV=local 이고 PROVENA_DEV_MODE=1 일 때만).
-- 여러 번 돌려도 된다.
CREATE TABLE IF NOT EXISTS users (
    user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    login_id      text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role          text NOT NULL CHECK (role IN ('user', 'admin')),
    is_active     boolean NOT NULL DEFAULT true,
    groups        text[] NOT NULL DEFAULT '{}',  -- 문서 권한 그룹 (SDD 5장). F-06을 넣을 때까지 쓰지 않는다
    created_at    timestamptz NOT NULL DEFAULT now()
);
