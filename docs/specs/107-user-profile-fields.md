# DB 107: 사용자 프로필 추가 필드 제안

번호 107은 `db/107_email_signup_verification.sql`([107-email-signup-verification.md](./107-email-signup-verification.md))과 겹치지만 서로 다른 변경이다. 이 문서의 제안은 SQL 파일이 없고 코드에 사용처가 없어 적용하지 않으며, 이름은 바꾸지 않고 번호가 겹친다는 사실만 여기에 적는다. 실제 `db/107_*.sql`은 이메일 가입 인증이다.

이 문서는 사용자 프로필의 역할·담당 서비스 저장을 위한 스키마 제안이다. 실행용 migration이 아니며, 운영 DB나 Docker 초기화 과정에서 자동 적용하지 않는다.

기존 `db/104_user_profiles.sql`을 변경하지 않고 nullable 암호화 칸을 추가하는 안이다. 값은 기존 `ProfileCipher`의 `user_id|field-name` AAD와 key version 계약을 사용해야 하며 plaintext fallback이나 기존 칸에 JSON을 넣지 않는다.

```sql
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS role_enc bytea,
    ADD COLUMN IF NOT EXISTS service_enc bytea;
```

기존 행은 `NULL`로 남긴다. owner 승인 후 별도 migration 절차와 애플리케이션 저장 계약을 적용하며, rollout 이후 생성·수정되는 프로필부터 신규 필드를 요구한다.
