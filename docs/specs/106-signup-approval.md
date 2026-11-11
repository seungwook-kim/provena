# 가입 승인 (DB 106 `signup_requests`)

상태: 구현됨(2026-11-11 코드 기준). 운영 적용 상태는 `db/db.md`를 따른다(113·114 미적용). 이 파일은 처음 DB 제안으로 시작했으나 지금은 가입 신청과 관리자 승인의 기능 spec이다. 관리자 쪽 권한·검사 순서는 `admin-roles.md`, 로그인 쪽은 `login.md`, 이메일 인증(PR #113)은 [107-email-signup-verification.md](./107-email-signup-verification.md)가 정한다.

## Why

- **페르소나**: 새로 쓰려는 사용자, 사용자를 받아 주는 최고 관리자
- **상황**: 누구나 계정을 만들 수 있으면 내부 정책 답변이 외부에 열린다. 관리자가 신청을 보고 받아 줘야 한다.
- **문제**: 신청 단계에서 `users` 행이 생기면 승인 전 계정이 로그인·권한 확인 경로에 섞이고, 비밀번호 해시가 응답이나 목록에 새면 안 된다.
- **목표 지표**: 승인 전에는 로그인이 안 된다. 승인 뒤에만 `users` 행이 생긴다. 목록 응답에 `password_hash`가 0번 나온다.

## Goal

- `POST /auth/signup`으로 가입을 신청하고(이메일 형식 아이디는 6자리 코드 확인을 거친다), 최고 관리자가 `GET /admin/signup-requests`로 보고 `POST /admin/signup-requests/{login_id}/{action}` 또는 `/by-id/{request_id}/{action}`(`approve`·`reject`)으로 처리한다.
- 신청은 `signup_requests`에만 남기고(`db/106_signup_approval.sql`), 승인할 때 저장해 둔 해시로 `users` 행을 만든다.
- **Out of Scope**: 이메일 인증의 코드 발송·확인 세부(107 spec), 비밀번호 재설정, 사용자 프로필 필드 추가(옛 107 제안은 쓰는 곳이 없어 만들지 않았다, `107-user-profile-fields.md`).

## What

### Happy Path

1. 클라이언트가 CSRF 쿠키를 받고 `POST /auth/signup`에 `login_id`, `password`, `password_confirmation`을 보낸다.
2. 서버는 입력을 확인하고 비밀번호를 bcrypt로 해시해 `status='pending'` 행을 저장한 뒤 201을 돌려준다. 이때 `users` 행·`user_id`는 만들지 않는다. 이메일 형식 아이디면 인증 코드를 메일로 보내고(응답에 만료·재발송 가능 시각이 붙는다), `POST /auth/signup/verify`로 코드를 확인해야 승인할 수 있다.
3. 최고 관리자가 목록(`login_id`, `requested_at`, `status`만)을 보고 승인 또는 거절한다.
4. 승인: 한 트랜잭션에서 신청 행을 잠그고 `users`(role `user`)를 만들고 `user_id`·`reviewed_at`·`reviewed_by`(처리한 최고 관리자의 `user_id`)를 채운다. 거절: 상태·처리 정보만 바꾸고 `users`는 만들지 않는다.
5. 승인된 사용자는 일반 로그인(`login.md`)으로 들어온다. 대기·거절 상태는 로그인이 되지 않는다.

### Edge Cases

| 상황 | 처리 |
|---|---|
| 비밀번호와 확인 값이 다름, 아이디가 비었거나 64자 초과·공백 포함 | 422 |
| 비밀번호 8자 미만 또는 72바이트 초과 | 422 |
| 이미 쓰는 아이디(`users` 또는 신청 표에 있음) | 409 |
| 신청 저장소를 쓸 수 없음 | 503(닫힌 채 실패) |
| 인증 메일 발송 실패, 이메일 공급자 미설정(로컬 아님) | 503. 가입 첫 발송이면 방금 만든 대기 신청을 지워 같은 이메일로 다시 가입할 수 있다 |
| 이메일 인증 전 승인 | 409(`users` 행 안 만듦) |
| 인증번호 만료 뒤 24시간 넘게 인증 안 한 신청과 같은 이메일로 재가입 | 옛 신청을 덮어쓰고 새로 진행(24시간 안이면 409) |
| CSRF 누락·불일치 | 403 |
| 이미 처리된 신청에 다시 승인·거절 | 200 `changed:false`, 상태·이력 그대로 |
| 없는 신청, 허용 안 된 `action` | 404, 422 |
| 일반 사용자·`admin`이 승인 API 호출 | 403(최고 관리자만, `admin-roles.md`) |

## How

- 라우트: `backend/auth.py:985-990`(`/auth/signup`), `:1015`(`/auth/signup/verify`), `:1036`(`/auth/signup/resend`), `backend/admin_api.py:221,225,268`(목록·처리·by-id 처리). 저장소: `backend/services/auth_store.py`(`create_pending_user`, `list_signup_requests`, `review_signup_request`, 메모리판과 `PostgresAuthStore`).
- 표: `request_id`(식별자), `user_id`(승인 뒤 연결, UNIQUE), `login_id`(UNIQUE), `password_hash`, `status`(pending·approved·rejected), `requested_at`, `reviewed_at`, `reviewed_by`. RLS를 켜고 `PUBLIC`·`anon`·`authenticated` 권한을 회수한다(해시를 Data API로 못 읽게). `status_requested_at` 색인은 `db/109_realign.sql`이 지웠다. 정본은 `db/106_signup_approval.sql`과 `docs/db/TABLE_SPEC.md`다.
- 적용 순서: `db/101_auth_users.sql` → `db/106_signup_approval.sql` → (이메일 인증을 쓰는 앱 배포 전) `db/107_email_signup_verification.sql` → `db/108_auth_privacy_hardening.sql`. 운영 DB에는 자동 적용하지 않고 팀장 승인 뒤 수동으로 적용한다.

## AC (Given-When-Then)

- **AC-01 신청**: GIVEN 새 아이디와 일치하는 비밀번호, WHEN `POST /auth/signup`, THEN 201이고 `users`에는 행이 없고 `signup_requests`에 `pending` 행이 있다.
- **AC-02 승인 전 로그인 불가**: GIVEN 대기·거절 신청, WHEN 로그인, THEN 성공하지 않는다. 승인된 계정만 성공한다(`tests/test_signup_approval.py`).
- **AC-03 중복**: GIVEN 이미 있는 아이디, WHEN 신청, THEN 409.
- **AC-04 승인**: GIVEN 대기 신청과 최고 관리자, WHEN `approve`, THEN `users` 행이 생기고 `reviewed_by`가 그 관리자의 `user_id`이며 응답은 `changed:true`다(`tests/test_signup_admin_api.py`).
- **AC-05 거절**: GIVEN 대기 신청, WHEN `reject`, THEN `users` 행이 생기지 않는다.
- **AC-06 재처리**: GIVEN 이미 처리된 신청, WHEN 다시 처리, THEN `changed:false`이고 이력이 바뀌지 않는다.
- **AC-07 목록 노출**: GIVEN 최고 관리자, WHEN `GET /admin/signup-requests`, THEN 응답에 `password_hash`가 없다.
