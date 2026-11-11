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
- 적용 순서: `db/101_auth_users.sql` → `db/106_signup_approval.sql` → `db/107_email_signup_verification.sql` → `db/108_auth_privacy_hardening.sql` → `db/113_signup_edges.sql`. 번호 107은 [107-user-profile-fields.md](./107-user-profile-fields.md)(프로필 추가 칸 제안, 적용하지 않음)와 겹치지만 별개다. 운영 DB에는 아직 적용하지 않았다.
- `signup_requests`의 RLS 및 anon/authenticated 권한 회수는 유지한다.

## AC

- Given 신규 이메일 신청, When 인증 전 승인, Then 409로 거부되고 사용자는 생성되지 않는다.
- Given 신규 이메일 신청과 유효한 코드, When 코드 확인, Then 인증 시각이 기록되고 코드는 재사용되지 않는다.
- Given 인증 완료 신청, When 관리자가 승인, Then `users.login_id`가 정규화 이메일로 생성된다.
- Given 기존 비이메일 사용자, When 기존 아이디와 비밀번호로 로그인, Then 정상 로그인한다.
- Given 로컬 개발(`PROVENA_ENV=local`)에서 `EMAIL_PROVIDER` 미지정, When 신규 가입, Then 기록 전용 sender만 사용하며 실제 발송 성공으로 보고하지 않는다.
- Given 로컬이 아닌 환경(`PROVENA_ENV` 비어 있음 포함)에서 `EMAIL_PROVIDER` 미지정, When 서버가 시작, Then 서버는 뜨고 오류를 로그에 남기며, 이메일 가입과 재발송은 `503`(`이메일 인증 기능을 사용할 수 없습니다.`)으로 답한다. 기록 전용 sender로 내려가지 않고 로그인·채팅 등 다른 기능은 영향받지 않는다.
- Given 메일 발송 실패, When 신규 가입의 첫 발송, Then `503`이고 방금 만든 미인증 대기 신청을 지워 같은 이메일로 다시 가입할 수 있다. When 재발송, Then `503`이고 신청과 발송 횟수는 그대로다.
- Given 인증하지 않은 대기 신청(인증번호가 만료됐든 아니든), When 같은 이메일로 다시 가입, Then 같은 행을 새 비밀번호로 덮어쓰고 인증번호를 새로 보낸다(옛 비밀번호·옛 코드는 쓸 수 없다). 이메일을 실제로 받는 사람만 인증을 끝낼 수 있으므로 남이 이메일을 선점하지 못한다. 단 그 신청이 재발송 제한(60초 간격, 5회)에 걸려 있으면 비밀번호를 바꾸기 전에 `429`로 답하고 신청은 그대로 둔다. 덮어쓰는 중 메일 발송이 실패하면 `503`이고 기존 신청은 지우지 않는다(처음 만든 신청만 지운다). 이전의 "만료 24시간 뒤에만 덮어쓰기" 규칙은 이 규칙이 대체한다.
- Given 인증을 마친 대기 신청, 승인된 신청, 또는 이미 있는 계정, When 같은 이메일로 가입, Then `409`이고 아무것도 바꾸지 않는다.
- Given 거절된 신청, When 같은 이메일로 다시 가입, Then 새 신청이 만들어지고(거절 행은 기록으로 남음) 가장 최근 행이 그 이메일의 신청 상태다. `db/113_signup_edges.sql`이 `signup_requests`의 `login_id` UNIQUE를 "거절되지 않은 행"에만 거는 부분 유니크 색인으로 바꾼다.
- Given 대문자가 섞인 이메일로 저장된 옛 계정, When 소문자 또는 대문자로 로그인, Then 정상 로그인한다. `113`이 겹치지 않는 이메일 `users.login_id`를 소문자로 바꾸고 소문자 기준 유니크 색인(`users_login_id_lower_unique`)을 걸며, 저장소는 이메일을 대소문자 구분 없이 찾는다. 비이메일 아이디는 계속 대소문자를 구분한다. 대소문자만 다른 이메일 계정이 이미 둘 이상이면 그 쌍은 건드리지 않고 색인도 만들지 않으며 NOTICE로 알린다.
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
  `EMAIL_FROM`. Local development (`PROVENA_ENV=local`) and tests may use
  `RecordingEmailSender`. A selected provider with missing settings, or an
  unsupported provider, warns and uses the recording sender only in local
  development; outside local development it raises a startup configuration
  error. When `EMAIL_PROVIDER` is not set outside local development (including
  an empty `PROVENA_ENV`), the server still starts and logs an error; signup
  and resend return `503` instead of falling back to the recording sender.
  Delivery errors are generic and do not expose secrets or verification codes.
- A delivery failure on signup returns `503` and removes the pending request
  just created. On resend it returns `503` and leaves the request and send
  count unchanged. An unverified pending request whose code expired more than
  24 hours ago (or that was requested more than 24 hours ago without a code)
  is replaced when the same email signs up again.
- Successful verification clears the code and expiry and resets attempts; the
  signup request remains pending for separate administrator approval.
