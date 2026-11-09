-- 내 정보 (요청 1번, 2026-11-05 강경희 요청 / 박진형 초안). 조회·저장: backend/services/profile_store.py, 암호화: backend/services/profile_crypto.py.
-- 100번대 = 로그인·사용자(db/101_auth_users.sql:2) → 김승욱님과 맞춘다.
-- 평문 칸은 없다. 각 칸 = nonce(12바이트) + AES-256-GCM 암호문 + 태그(16바이트). AAD = "user_id|칸 이름".
-- 관리자 목록·로그인 조회는 이 표를 읽지 않는다(users 표와 따로 둔 이유). 다른 사람 내 정보를 주는 API는 없다.
-- 여러 번 돌려도 된다.
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id      uuid PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    name_enc     bytea NOT NULL,
    dept_enc     bytea NOT NULL,
    phone_enc    bytea NOT NULL,
    address_enc  bytea NOT NULL,
    key_version  smallint NOT NULL CHECK (key_version > 0),   -- 어느 키로 잠갔나 (키 교체용, PROFILE_ENC_KEYS)
    updated_at   timestamptz NOT NULL DEFAULT now()
);
