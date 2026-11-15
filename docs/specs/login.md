# 로그인 API 명세서

상태: `backend/auth.py` 인증 모듈 구현 완료, 팀 `backend/main.py`에 라우터 등록·PostgreSQL 사용자 저장소(`backend/services/auth_store.py`)·토큰 폐기 저장소 연결 완료(2026-11-11 코드 기준). 실제 Google 브라우저 로그인은 미검증

## Why

- **페르소나**: Provena를 사용하는 일반 사용자와 관리자
- **상황**: 로그인 후 자신의 대화·기억·승인 권한만 사용할 수 있어야 한다.
- **문제**: 인증 주체를 요청 본문의 사용자 ID로 판단하면 타인 데이터에 접근할 수 있고, 로그인 실패 응답이나 처리 시간 차이로 계정 존재 여부가 노출될 수 있다.
- **목표 지표**: 인증 실패 경로를 같은 401 응답으로 유지하고, 인증 모듈 테스트를 재현 가능하게 통과한다.

## Goal

- `AuthStore`를 주입받는 FastAPI 인증 라우터로 `POST /auth/login`, `POST /auth/logout`, `GET /me`, `GET /auth/csrf` 계약을 제공한다.
- bcrypt 비밀번호 검증, JWT(HttpOnly 쿠키), CSRF 검증, 사용자 활성 상태·role 재확인을 제공한다.
- `Depends(current_user_id)`가 인증된 UUID 문자열을 제공하도록 한다.
- 로그인 ID 단독으로 60초 동안 실패 5회, `request.client.host` 기준 IP 단독으로 60초 동안 실패 30회를 독립 집계하고, 어느 하나라도 소진되면 다음 요청부터 HTTP 429를 반환한다.
- 같은 라우터가 `POST /auth/signup`(가입 신청, 관리자 승인 전까지 로그인 불가, 201)과 `GET /auth/google/start`·`GET /auth/google/callback`(Google 로그인)도 제공한다(`create_auth_router` 안 `signup` `backend/auth.py:1053`, `google_start` `:1152`, `google_callback` `:1193`). 가입 승인 쪽 규칙은 `admin-roles.md`.
- **Out of Scope**: 비밀번호 재설정, 분산 rate limiter.

## What

### Happy Path

1. 클라이언트는 `GET /auth/csrf`로 CSRF 쿠키를 받고, `POST /auth/login`에 `login_id`, `password`, `X-CSRF-Token`을 보낸다.
2. 서버는 주입된 `AuthStore`에서 사용자를 조회하고 bcrypt로 비밀번호를 검증한다.
3. 활성 `user` 또는 `admin`이면 UUID `user_id`, role, 만료 정보를 담은 JWT를 `provena_auth` HttpOnly 쿠키로 설정하고 200 `{user_id, role}`을 반환한다.
4. 보호 엔드포인트는 `Depends(current_user_id)`로 쿠키 JWT를 검증해 사용자 UUID 문자열을 얻는다. 최신 활성 상태·role 확인이 필요하면 `create_current_user_dependency()`를 사용한다.
5. 서버가 얻은 ID를 `AgentState.user_id: str`로 Graph에 전달한다(`backend/api/routes.py`의 `/chat`이 로그인 사용자로 동작).
6. `POST /auth/logout`은 CSRF 검증 뒤 인증·CSRF 쿠키를 삭제하고 204를 반환한다. `GET /me`는 현재 사용자 ID, role, 로그인 아이디(`login_id`)를 반환한다. 머리글 `X-Session-Optional: 1`을 붙이고 로그인 쿠키가 아예 없으면 401 대신 204(본문 없음)로 답한다. 화면의 첫 세션 확인이 로그아웃 상태마다 브라우저 콘솔에 401을 남기던 것을 없앤다(놓친 것 H-33). 쿠키가 있으면(만료·위조 포함) 머리글과 상관없이 예전처럼 검사한다(`tests/test_me_optional_session.py`).

### Edge Cases

| 상황 | 처리 |
|---|---|
| 없는 ID·틀린 비밀번호·비활성 계정·허용하지 않은 role | 같은 401 `로그인 정보가 올바르지 않습니다.` |
| 없는 ID | 사전에 준비한 bcrypt 더미 해시를 `verify_password()`로 검증한 뒤 401. 더미 계정·DB 레코드 생성과 요청별 해시 생성은 하지 않는다. 응답 시간 차이 완화 목적이며 완전한 상수 시간 보장은 아니다. |
| CSRF 쿠키·헤더 누락·불일치, 또는 서명이 틀린 토큰(서명 없는 임의 값을 쿠키·헤더에 같이 넣은 경우 포함) | 403 |
| 검증 입력 오류 | 민감한 입력값을 노출하지 않는 422 |
| 로그인 ID 단독의 60초 내 실패 5회 또는 `request.client.host` 기준 IP 단독의 60초 내 실패 30회 소진 | 다음 로그인 요청부터 429. 성공 로그인은 해당 ID 기록만 초기화하고 IP 기록은 유지한다. |
| 동일 IP에서 다른 ID로 로그인 | ID별 제한은 공유하지 않는다. 여러 ID의 실패는 해당 IP 기록에 합산되어 IP 한도를 소진하면 429를 반환한다. |
| 동일 ID가 IP를 변경하여 로그인 | IP와 무관하게 같은 ID의 실패를 합산하므로 ID별 제한을 우회할 수 없다. |
| 쿠키 누락·만료·변조 또는 인증 설정 오류 | `current_user_id()` 및 `/me`에서 401 |
| AuthStore 조회 오류 | 503 |

## How

### 인증·쿠키 계약

- 구현: `backend/auth.py`, 라우터: `create_auth_router(*, store, secret=None, cookie_secure=None, rate_limiter=None)`
- 비밀번호: bcrypt, 최소 8자·UTF-8 기준 최대 72바이트. 원문·hash·JWT를 응답이나 로그에 남기지 않는다.
- JWT: `HS256`, `user_id`, `role`, `iat`, `exp`를 포함하며 `AUTH_SECRET`은 최소 32바이트여야 한다.
- 인증 쿠키: `provena_auth`, `HttpOnly`, `SameSite=Lax`, `Path=/`, 수명 30분(`AUTH_TOKEN_EXPIRES_MINUTES = 30`, `AUTH_COOKIE_MAX_AGE = 30 * 60초`, `backend/auth.py:49-50`; JWT `exp`도 같은 값, `auth.py:238`). CSRF 쿠키는 `provena_csrf`이며 읽기 가능하다. 토큰은 `난수.HMAC-SHA256(AUTH_SECRET 파생 키, 난수)` 형식의 서명된 double-submit이고, `require_csrf`는 쿠키·헤더 일치와 서명을 모두 검사한다(J-14).
- 쿠키 `Secure` 기본값은 True이며, `PROVENA_ENV=local` 및 `PROVENA_DEV_MODE=1`일 때만 로컬 HTTP용 False를 허용한다.
- `current_user_id(request: Request) -> str`: 쿠키 JWT의 정규화된 UUID 문자열만 반환한다. 요청 본문·query string의 `user_id`는 신뢰하지 않으며 인증 실패는 401이다.
- `GET /me`는 JWT 검증 뒤 `AuthStore`에서 활성 상태와 role을 다시 확인한다.

### 로그인 제한과 운영 경계

- `LoginRateLimiter`는 프로세스 메모리에서 ID별·IP별 실패 시각을 별도로 저장한다. `backend/auth.py`의 `_client_ip()`는 기본(`TRUSTED_PROXY_HOPS=0`)에서 `request.client.host`(주소가 없으면 `unknown`)만 쓰고 `X-Forwarded-For`를 무시한다. `TRUSTED_PROXY_HOPS=N`(N>0)이면 `X-Forwarded-For` 오른쪽에서 N번째 값만 믿고(Cloud Run은 실제 접속 주소를 마지막에 덧붙이므로 N=1), 헤더가 없거나 짧거나 IP 형식이 아니면 peer 주소로 돌아간다(`backend/auth.py:701-734`, `.env.example:215`). 이 문서의 IP별 제한은 모두 이 값을 기준으로 한다.
- 현재 `Dockerfile`은 Uvicorn을 `--no-proxy-headers`로 실행한다. 따라서 Uvicorn은 `X-Forwarded-For`, `X-Forwarded-Proto`를 반영하지 않고, `request.client.host`는 접속 peer 주소 그대로다. 이전 설정(`--proxy-headers --forwarded-allow-ips=*`)은 `X-Forwarded-For` 목록의 맨 앞 주소(요청하는 쪽이 임의로 적을 수 있는 값)를 client 주소로 써서 IP별 실패 제한을 피할 수 있었기 때문에 되돌렸다. `backend/main.py`는 별도의 IP 헤더 검증을 추가하지 않는다.
- 이 설정에서는 헤더로 IP 값을 위조할 수 없다. 다만 Cloud Run처럼 앞단 프록시 뒤에서 실행하면 접속 peer가 프록시 주소일 수 있어, 서로 다른 사용자가 같은 IP 키로 묶여 IP별 한도(60초/30회)를 함께 소진할 수 있다. 같은 ID의 실패는 IP와 무관하게 합산하므로 ID별 제한이 주된 방어이고 IP 제한은 보조 방어다. 실제 접속 IP가 필요하면 `TRUSTED_PROXY_HOPS`로 프록시가 붙인 값만 믿게 한다(`Dockerfile:61-65` 주석). 운영 Cloud Run에서 이 값이 실제로 어떻게 보이는지는 이 문서에서 확인하지 않았다.
- Uvicorn 동작 참고: [공식 ProxyHeadersMiddleware 구현](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py).
- ID 키는 `login_id` 단독이며 기본 한도는 60초/5회다. IP 키는 `request.client.host` 기준 IP 단독이며 기본 한도는 60초/30회다. 두 한도 중 하나라도 소진되면 다음 요청부터 비밀번호 검증 전에 429를 반환하고, 해당 429 요청을 실패 기록에 추가하지 않는다.
- 성공 로그인은 해당 ID의 실패 기록만 초기화하며 IP 전체 실패 기록은 유지한다. 제한 검사와 실패 기록 시 양쪽 저장소에서 60초 이상 지난 기록과 빈 키를 정리하므로, 다시 요청되지 않는 ID·IP의 만료 기록도 다음 처리 시 정리된다.
- Cloud Run용 `TRUSTED_PROXY_HOPS=1`은 재배포 때 추가할 설정으로 적혀 있다(`docs/worklog.md:153`). 배포 주소에서 IP별로 나뉘는지는 재지 않았고 로컬 시험(`tests/test_deploy_hardening.py`)만 있다(`EVAL_REPORT.md:746`).
- 로그인 실패 제한은 프로세스 메모리 기준이라 재시작 시 사라지고 인스턴스 사이에서 공유되지 않는다. 배포는 `--max-instances 1`이다(`README.md:172`, 설명은 `README.md:176`). 인스턴스를 늘리려면 공유 저장소(Redis 또는 PostgreSQL 등) 전환이 먼저다. 신뢰 프록시 정책(`TRUSTED_PROXY_HOPS`)은 구현돼 있고 배포 주소 실측만 남았다.
- 로컬 데모용 시드는 `backend/services/demo_seed.py`, 계정 생성은 `backend/services/create_account.py`, 운영 사용자 저장소는 `backend/services/auth_store.py`(`PostgresAuthStore`)다. 인증 라우터 시험은 `tests/test_auth_router_runtime.py`의 `FakeAuthStore`가 실행 중 생성한 UUID·비밀번호를 사용한다.

### 의존성과 검증

- `backend/requirements.txt`: `bcrypt>=4.2,<5`, `PyJWT>=2.9,<3`, FastAPI 등
- `backend/requirements-dev.txt`: 위 requirements와 `pytest>=8`, `httpx>=0.27`
- 로컬에서 pytest 9.2.0과 anyio 4.14.1은 pytest 플러그인 경고를 냈다. 현재 검증 환경은 pytest 8.4.2로 경고 없이 실행했다. 공용 의존성·CI의 pytest 상한 또는 pytest 9 호환 anyio 버전은 별도 결정이 필요하다.
- 로그인 보안 리뷰 후속 수정 검증 결과: `.venv/Scripts/python.exe -m pytest tests/test_auth_router_runtime.py -q` 인증 테스트 17개, `.venv/Scripts/python.exe -m pytest -q` 전체 테스트 51개 통과. `git diff --check` 통과.

## 백엔드 구현 및 연동 현황 (강경희)

- `backend/auth.py`에 FastAPI 일반 로그인, bcrypt 검증, HttpOnly JWT 쿠키, CSRF, ID·IP별 로그인 실패 제한과 현재 사용자·관리자 권한 검증 의존성을 구현했다.
- JWT에는 고유 `jti`를 넣고, `TokenRevocationStore` 계약으로 인증·로그아웃 시 폐기 여부를 확인한다. 폐기 저장·조회가 없거나 실패하면 503으로 차단한다. J-05(로그아웃 뒤 동일 JWT 재사용)용 PostgreSQL 폐기 저장소(`PostgresTokenRevocationStore`, `db/103_auth_token_revocations.sql`)는 `DATABASE_URL`이 있으면 `main.py:299-300`에서 만들어 `main.py:347-348`로 앱에 연결된다. 로그아웃 뒤 같은 JWT는 401임을 `tests/test_auth_revocation.py::test_same_user_logins_issue_unique_jti_and_logout_revokes_only_one_session`이 확인한다(가짜 저장소 기준). 운영 DB에서 한 로그아웃 뒤 재사용 시험 기록은 없다.
- Google OAuth 시작·콜백은 PKCE(S256), state·nonce, authorization code 교환, Google ID 토큰 서명·issuer·audience·만료 검증을 수행한다. 검증된 `google` provider·`sub`와 **`email_verified=true`인 이메일**만 Google 사용자 저장소 계약에 전달한다. 이메일은 아래 "Google 로그인 계정 연결"의 조건을 모두 만족할 때만 기존 계정을 찾는 데 쓰고, 이메일로 관리자 권한을 새로 주지는 않는다.
- Mock OAuth·인증·보안 계약 테스트 26건과 DB 환경변수를 제거한 Python 전체 테스트 **215 passed, 1 skipped**를 확인했다.
- Google 로그인의 사용자 저장소 `get_or_create_google_user`는 `PostgresAuthStore`·`MemoryAuthStore`에 있다(`backend/services/auth_store.py:161,522`, 아래 "Google 로그인 계정 연결"). Cloud Run callback과 실제 Google 브라우저 로그인은 미검증이다.

### Google 로그인 계정 연결 (2026-11-11, 방식 A)

- 저장소 계약은 `get_or_create_google_user(provider, sub, email)`이다(`PostgresAuthStore`·`MemoryAuthStore`, `backend/services/auth_store.py`). 한 트랜잭션에서 다음 순서로 본다.
  1. `user_identities`에 (`google`, `sub`)가 있으면 그 계정으로 로그인한다(이메일 칸만 갱신). 구글 쪽에서 이메일이 바뀌어도 같은 계정이다.
  2. 없으면 구글이 인증한 이메일을 앞뒤 공백 제거·소문자로 바꾼 값이 `users.login_id`와 **정확히 같은** 계정을 찾는다. 다음을 모두 만족할 때만 `user_identities`에 한 줄을 더해 연결한다. 하나라도 어긋나면 연결하지 않고 `/login?oauth_error=google_login_failed`로 보낸다(계정이 있는지 알려 주지 않는다).
     - 계정이 활성(`is_active`)이다.
     - 같은 이메일로 이메일 인증을 마치고 승인된 가입 기록이 있다: `signup_requests`에 `user_id`가 그 계정이고 `status='approved'`, `email_verified_at IS NOT NULL`. 시드·`create_account`로 만든 계정처럼 가입 기록이 없는 계정은 이메일 소유 증명이 없어 연결하지 않는다.
     - 그 계정에 이미 다른 구글 계정이 연결돼 있지 않다(`UNIQUE (provider, user_id)`).
  3. 계정이 없으면 `signup_requests`에 가입 신청(`pending`, `login_id`=이메일, `google_sub`, 비밀번호 해시 없음, `email_verified_at`=지금)을 만들고 **승인 대기** 안내(`/login?oauth_error=google_signup_pending`)로 보낸다. 같은 이메일의 가입 신청(비밀번호 가입 포함)이 이미 대기·거절 상태면 새 신청을 만들지 않고 같은 안내를 한다. 최고 관리자가 `/admin/signup-requests`에서 승인하면 `users`(비밀번호 없음, role `user`)와 `user_identities`가 한 트랜잭션으로 만들어진다.
- `role`은 연결할 때 바꾸지 않는다(admin 계정에 연결해도 admin 그대로). 구글 로그인으로는 admin이 만들어지지 않고, 새 계정은 항상 `user`다.
- 구글로만 만든 계정은 비밀번호가 없어 비밀번호 로그인이 안 된다(`password_hash` NULL → 더미 해시로 검증해 401, `set_password`·`upsert_user`는 비밀번호가 있는 계정에만 적용).
- 스키마는 `db/114_google_identities.sql`: `user_identities(provider, subject, user_id, email, created_at, PK(provider, subject), UNIQUE(provider, user_id))`, `signup_requests.google_sub`(부분 유일 색인), `users`·`signup_requests`의 `password_hash` NULL 허용(+ `signup_requests`는 비밀번호 해시나 `google_sub` 중 하나 필수 CHECK). 기존 설계(`users`·`signup_requests`에 provider 칸 4개·유일 색인 2개·CHECK 4개)보다 `users`를 건드리지 않고 이메일 연결과 구글 전용 가입이 같은 표 하나로 풀려서 이쪽으로 정했다. 동시에 같은 구글 계정이 와도 기본키·유일키와 `ON CONFLICT DO NOTHING` 뒤 재조회로 한 줄만 남는다(Postgres 시험으로 확인). 113·114를 적용하기 전의 DB(운영은 109까지)에서도 앱은 돈다: 저장소가 `signup_requests.google_sub`·`user_identities`가 있는지 저장소마다 한 번 확인해(`information_schema`) 없으면 비밀번호 로그인·가입·승인 쿼리에서 `google_sub` 조건을 빼고 Google 로그인만 `/login?oauth_error=google_unavailable` 안내로 보낸다. 113이 없으면 거절된 이메일 재가입이 409일 뿐 오류는 없다. 114를 적용한 뒤에는 서버를 다시 시작해야 Google 로그인이 켜진다(확인 결과를 캐시함). 시험 `tests/test_auth_schema_compat.py`.
- `/auth/google/start`는 Google 키(환경 변수 3개 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`)가 하나라도 없으면 JSON 503 대신 `/login?oauth_error=google_unavailable`로 303 이동한다. 콜백 오류도 같은 `oauth_error` 방식이다. 로그인 화면(`web/react-app/src/pages/LoginPage.jsx`)이 승인 대기·거절·실패·사용 불가 문구를 보여 준다.

Google OAuth의 상태 구분: 같은 이메일에 `pending` 신청이 있으면 승인 대기 오류로 안내하고, `rejected` 신청이면 `google_signup_rejected`로 구분해 안내한다. 이미 인증·승인된 이메일형 계정에 연결할 때는 기존 `role`과 `is_active`를 바꾸지 않는다. 113·114가 없는 DB에서는 호환 경로를 유지하고 Google 로그인만 `google_unavailable`로 닫는다.
- 배포에 Google 키를 넣고 운영 DB에 마이그레이션을 적용하는 일, GCP 콘솔 설정은 조장이 한다(`README.md`의 "Google 로그인 설정"). 실제 Google 계정으로 한 브라우저 왕복은 하지 않았다(미검증).
- 콜백이 성공하면 `/`로 보낸다(`backend/auth.py` `google_callback`, 303 `Location: /`). 화면은 `/`에서 세션 확인(`/me`)이 끝나기 전에는 랜딩을 그리지 않고 확인 중 안내를 보인 뒤, 로그인돼 있으면 `/chat`(또는 `/myinfo`)으로 보낸다. 확인 전에 랜딩이 잠깐 보였다가 채팅으로 넘어가던 것을 고쳤다(2026-11-13, 경희님 화면 점검).

## AC (Given-When-Then)

- **AC-01 로그인 성공**: GIVEN 활성 사용자와 올바른 비밀번호, WHEN `POST /auth/login`, THEN 200 `{user_id, role}`과 HttpOnly JWT 쿠키를 반환한다.
- **AC-02 실패 응답 통일**: GIVEN 존재하지 않는 ID·틀린 비밀번호·비활성 계정, WHEN 로그인, THEN 같은 401 응답을 반환한다.
- **AC-03 더미 해시**: GIVEN 존재하지 않는 ID, WHEN 로그인, THEN 사전 생성 bcrypt 더미 해시를 검증하고 로그인에 성공하지 않는다.
- **AC-04 CSRF**: GIVEN CSRF 쿠키·헤더가 없거나 다름, WHEN 로그인 또는 로그아웃, THEN 403을 반환한다.
- **AC-05 사용자 ID**: GIVEN 유효한 `provena_auth` 쿠키, WHEN `Depends(current_user_id)`, THEN 인증된 UUID 문자열을 반환한다. 쿠키 누락·만료·변조는 401이다.
- **AC-06 제한**: GIVEN 같은 ID 단독으로 60초 내 5회 실패하거나 같은 `request.client.host` 기준 IP 단독으로 60초 내 여러 ID의 실패가 합계 30회 누적됨, WHEN 다시 로그인, THEN 어느 한도라도 소진되었으면 429를 반환한다.
- **AC-07 이메일 대소문자**: GIVEN 대문자가 섞인 이메일로 저장된 옛 계정(`db/113`가 겹치지 않는 것은 소문자로 바꿈), WHEN 대소문자와 무관하게 입력해 로그인, THEN 같은 계정으로 200이다(로그인 입력과 저장소 조회 모두 이메일은 소문자 비교). 이메일이 아닌 아이디는 대소문자를 구분한다. 시험: `tests/test_signup_edges.py`.
- **AC-08 이메일 인증 전 로그인**: GIVEN 이메일 인증을 마치지 않은 대기 신청, WHEN 맞는 비밀번호로 로그인, THEN 403이고 오류 code는 `signup_unverified`, 문구는 "이메일 인증을 먼저 마쳐 주세요. 아래 '인증번호 다시 받기'에서 인증번호를 다시 받을 수 있습니다."이고, 화면은 오류 칸 안에 "인증번호 다시 받기"(`/signup?resume=1`) 링크를 보인다(관리자 승인 대기 문구와 구분). 로그인·회원가입 화면 아래의 고정 "이메일 인증 이어하기" 링크는 2026-11-11 없앴고, 회원가입 409(이미 신청한 이메일)일 때만 같은 링크를 오류 칸에 보인다. 인증을 마친 뒤에는 기존 승인 대기 문구(code `forbidden`). 비밀번호가 틀리면 401로 신청 상태를 알려 주지 않는다. 시험: `tests/test_signup_edges.py::test_login_before_email_verification_says_verify_first`.
- **AC-09 비이메일 아이디 대소문자**: 가입은 모든 아이디를 소문자로 저장한다. 로그인은 입력 그대로 먼저 찾고, 없으면 가입과 같은 규칙(앞뒤 공백 제거·소문자)으로 다시 찾는다. 그래서 가입으로 만든 `kim`은 `Kim`·` KIM `으로도 로그인되고, 소문자 규칙 전에 만든 대문자 계정(데모 시드·`create_account`의 `Admin` 등)은 그대로 `Admin`으로 로그인된다(`admin`으로 열리지는 않음). 로그인 시도 제한 키와 대기 신청 조회도 소문자 아이디다. 시험: `tests/test_signup_edges.py`.
- **AC-07 최신 사용자 상태**: GIVEN JWT 발급 뒤 사용자의 role 또는 활성 상태가 변경됨, WHEN `/me`, THEN `AuthStore`의 최신 상태를 반영한다.
- **AC-08 회귀 검증**: GIVEN 현재 인증 구현, WHEN 인증 테스트와 전체 테스트를 실행, THEN 모두 통과한다. (작성 시점 2026-11-01 값은 인증 17개·전체 51개였다. 지금 `tests/`의 test 함수는 2,017개이고 `test_auth_router_runtime.py`는 15개 함수(매개변수 확장 제외)라 그 숫자는 더 이상 기준이 아니다. 실행 결과는 EVAL_REPORT·PR 본문의 최신 값을 따른다.)
- **AC-09 같은 IP의 다른 ID**: GIVEN 한 IP에서 A ID의 실패가 5회이고 IP 실패 합계는 30회 미만, WHEN 같은 IP에서 실패 기록이 없는 B ID로 로그인, THEN A의 ID 제한으로 차단하지 않고 B의 인증 결과를 반환한다.
- **AC-10 IP 변경**: GIVEN 같은 ID의 실패가 여러 IP에 걸쳐 60초 내 5회 누적됨, WHEN 새 IP에서 같은 ID로 로그인, THEN 429를 반환한다.
- **AC-11 성공 시 기록**: GIVEN ID와 IP에 실패 기록이 있고 두 한도가 소진되지 않음, WHEN 해당 ID로 로그인 성공, THEN ID 기록만 초기화하고 IP 기록은 유지한다. 이후 IP 실패 합계가 30회에 도달하면 다음 요청은 올바른 비밀번호여도 429를 반환한다.
- **AC-12 만료**: GIVEN ID 5회 또는 IP 30회의 실패 기록이 같은 시각에 누적됨, WHEN 가짜 시계로 59.999초 뒤 제한을 검사하면, THEN 제한을 유지한다. WHEN 60초 또는 그 이후에 검사하면, THEN 해당 기록과 빈 키를 정리하고 제한을 해제한다.
