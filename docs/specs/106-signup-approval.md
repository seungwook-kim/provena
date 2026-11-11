# DB 106: 회원가입 승인 요청

현재 스키마는 `login_id`, `password_hash`, 상태, 신청 시각, 승인 시각, 승인자와 승인 후 연결되는 `user_id`를 기록한다. 신청 단계에서는 `users` 행을 만들지 않고, 승인 시 저장된 해시를 그대로 재사용한다. `db/106_signup_approval.sql`은 RLS를 활성화하고 Supabase Data API의 `PUBLIC`, `anon`, `authenticated` 역할에 대한 테이블 권한을 회수한다.

운영 적용 순서는 `db/101_auth_users.sql` → `db/106_signup_approval.sql`이며, 운영 DB에는 자동 적용하지 않는다. 106 다음에는 이메일 가입 인증용 `db/107_email_signup_verification.sql`과 `db/108_auth_privacy_hardening.sql`을 순서대로 적용한다([107-email-signup-verification.md](./107-email-signup-verification.md)). 프로필 추가 칸 제안([107-user-profile-fields.md](./107-user-profile-fields.md))은 번호만 같은 다른 문서이며 SQL 파일이 없고 코드에 사용처가 없어 적용하지 않는다.

이 문서는 회원가입 승인 기능의 스키마 제안이다. 실행용 migration이 아니며, 운영 DB나 Docker 초기화 과정에서 자동 적용하지 않는다.

기존 `db/101_auth_users.sql`의 `users` 표를 전제로 하며, 기존 `db/105_admin_role_log.sql`은 변경하지 않는다.

```sql
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

ALTER TABLE signup_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE signup_requests FROM PUBLIC;
REVOKE ALL ON TABLE signup_requests FROM anon, authenticated;
```

실제 적용은 owner/team 승인과 별도 migration 절차가 확정된 뒤 진행한다.
