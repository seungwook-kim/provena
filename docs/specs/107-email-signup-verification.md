# Email signup verification

## Why

신규 회원의 이메일 소유를 확인한 뒤 기존 관리자 승인 흐름에 넣는다. 기존 비이메일 `login_id` 계정과 migration 이전 가입 신청은 중단하지 않는다.

## Goal

- 신규 이메일 가입은 6자리 코드 확인 뒤에만 관리자 승인 가능
- 코드는 5분 만료, 실패 5회, 재발송 60초 간격 및 발송 5회 제한
- 기존 `login_id` 로그인·승인·거절·CSRF·Google OAuth 호환

Out of Scope: 기존 계정의 이메일 변환, 운영 DB 적용, 메일 공급자별 템플릿 관리.

## What

Happy path: 이메일·비밀번호 제출 → 코드 발송 → 코드 확인 → 관리자 승인 → 이메일 로그인.

Edge cases: 만료 코드, 잘못된 코드, 재사용 코드, 재발송 제한, 기존 비이메일 계정, 이전 migration 신청, 발송 서비스 미설정.

## How

- 신규 이메일은 공백 제거·소문자화한 값을 기존 `login_id`에 저장한다.
- `signup_requests`에 인증 필요 여부, 코드 HMAC, 만료·시도·발송 상태를 추가한다.
- `EmailSender`는 Gmail SMTP, Resend, 기록 전용 테스트 구현으로 분리한다. Gmail/Resend를 선택했는데 필수 설정이 없으면 Recording sender로 내리지 않고 실패한다.
- 적용 순서: `db/101_auth_users.sql` → `db/106_signup_approval.sql` → `db/107_email_signup_verification.sql` → `db/108_auth_privacy_hardening.sql`.
- `signup_requests`의 RLS 및 anon/authenticated 권한 회수는 유지한다.

## AC

- Given 신규 이메일 신청, When 인증 전 승인, Then 409로 거부되고 사용자는 생성되지 않는다.
- Given 신규 이메일 신청과 유효한 코드, When 코드 확인, Then 인증 시각이 기록되고 코드는 재사용되지 않는다.
- Given 인증 완료 신청, When 관리자가 승인, Then `users.login_id`가 정규화 이메일로 생성된다.
- Given 기존 비이메일 사용자, When 기존 아이디와 비밀번호로 로그인, Then 정상 로그인한다.
- Given Resend 설정 부재, When 신규 가입, Then 기록 전용 sender만 사용하며 실제 발송 성공으로 보고하지 않는다.
- Given Gmail 또는 Resend 선택과 필수 설정 누락, When 서버가 sender를 구성, Then 명확한 설정 오류로 중단하고 Recording sender로 대체하지 않는다.
- Given 인증 완료 또는 승인 완료 신청, When 재발송 요청, Then `{"status":"unavailable"}`이고 추가 발송은 없다.
# Implemented API and provider contract

- Verification codes expire after **5 minutes**. Resends are limited to one
  every **60 seconds** and at most **5 sends**. The PostgreSQL store enforces
  these checks atomically under a row lock.
- `POST /auth/signup/verify` accepts `{"login_id": string, "code": string}`.
  A valid or already-completed verification returns `200 {"status":"verified"}`.
  Invalid input is `422`, an expired code is `410`, too many attempts is `429`,
  an incorrect code is `400`, and unavailable storage is `503`.
- `POST /auth/signup/resend` accepts the same request shape. A successful
  resend returns `200` with `status: "sent"`, expiry, and next-available
  timestamps. Missing, non-pending, already verified, rate-limited, and
  send-limit-exhausted requests all return `200 {"status":"unavailable"}`.
  Invalid email input is `422`; other storage or delivery failures are `503`.
- Gmail uses `smtp.gmail.com:587`, STARTTLS, and a Gmail app password.
  Resend uses `https://api.resend.com/emails` with `RESEND_API_KEY` and
  `EMAIL_FROM`. Local development and tests may use `RecordingEmailSender`.
  Missing or unsupported provider settings warn and use the recording sender
  only in local development; outside local development they raise a startup
  configuration error. Delivery errors are generic and do not expose secrets
  or verification codes.
- Successful verification clears the code and expiry and resets attempts; the
  signup request remains pending for separate administrator approval.
