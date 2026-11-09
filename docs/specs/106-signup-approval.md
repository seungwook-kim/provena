# DB 106: 회원가입 승인 요청안

이 문서는 회원가입 승인 기능의 스키마 제안이다. 실행용 migration이 아니며, 운영 DB나 Docker 초기화 과정에서 자동 적용하지 않는다.

기존 `db/101_auth_users.sql`의 `users` 표를 전제로 하며, 기존 `db/105_admin_role_log.sql`은 변경하지 않는다.

```sql
CREATE TABLE signup_requests (
    request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL UNIQUE REFERENCES users(user_id),
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    reviewed_by uuid REFERENCES users(user_id)
);
CREATE INDEX signup_requests_status_requested_at ON signup_requests(status, requested_at);
```

실제 적용은 owner/team 승인과 별도 migration 절차가 확정된 뒤 진행한다.
