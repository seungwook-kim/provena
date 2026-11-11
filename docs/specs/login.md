# 로그인 API 명세서

상태: `backend/auth.py` 인증 모듈 구현 완료, 팀 FastAPI·PostgreSQL·Graph 통합 미완료

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
- **Out of Scope**: 실제 PostgreSQL 사용자 DB·마이그레이션, 팀 `backend/main.py` 라우터 등록, Graph 호출 연결, 회원가입·비밀번호 재설정·Google OAuth, 분산 rate limiter.

## What

### Happy Path

1. 클라이언트는 `GET /auth/csrf`로 CSRF 쿠키를 받고, `POST /auth/login`에 `login_id`, `password`, `X-CSRF-Token`을 보낸다.
2. 서버는 주입된 `AuthStore`에서 사용자를 조회하고 bcrypt로 비밀번호를 검증한다.
3. 활성 `user` 또는 `admin`이면 UUID `user_id`, role, 만료 정보를 담은 JWT를 `provena_auth` HttpOnly 쿠키로 설정하고 200 `{user_id, role}`을 반환한다.
4. 보호 엔드포인트는 `Depends(current_user_id)`로 쿠키 JWT를 검증해 사용자 UUID 문자열을 얻는다. 최신 활성 상태·role 확인이 필요하면 `create_current_user_dependency()`를 사용한다.
5. Graph 통합 시 서버가 얻은 ID를 `AgentState.user_id: str`로 전달한다. 현재 실제 Graph 호출 연결은 미완료다.
6. `POST /auth/logout`은 CSRF 검증 뒤 인증·CSRF 쿠키를 삭제하고 204를 반환한다. `GET /me`는 현재 사용자 ID와 role을 반환한다.

### Edge Cases

| 상황 | 처리 |
|---|---|
| 없는 ID·틀린 비밀번호·비활성 계정·허용하지 않은 role | 같은 401 `로그인 정보가 올바르지 않습니다.` |
| 없는 ID | 사전에 준비한 bcrypt 더미 해시를 `verify_password()`로 검증한 뒤 401. 더미 계정·DB 레코드 생성과 요청별 해시 생성은 하지 않는다. 응답 시간 차이 완화 목적이며 완전한 상수 시간 보장은 아니다. |
| CSRF 쿠키·헤더 누락 또는 불일치 | 403 |
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
- 인증 쿠키: `provena_auth`, `HttpOnly`, `SameSite=Lax`, `Path=/`, 기본 30분. CSRF 쿠키는 `provena_csrf`이며 읽기 가능하다.
- 쿠키 `Secure` 기본값은 True이며, `PROVENA_ENV=local` 및 `PROVENA_DEV_MODE=1`일 때만 로컬 HTTP용 False를 허용한다.
- `current_user_id(request: Request) -> str`: 쿠키 JWT의 정규화된 UUID 문자열만 반환한다. 요청 본문·query string의 `user_id`는 신뢰하지 않으며 인증 실패는 401이다.
- `GET /me`는 JWT 검증 뒤 `AuthStore`에서 활성 상태와 role을 다시 확인한다.

### 로그인 제한과 운영 경계

- `LoginRateLimiter`는 프로세스 메모리에서 ID별·IP별 실패 시각을 별도로 저장한다. `backend/auth.py`의 `_client_ip()`는 헤더를 직접 파싱하지 않고 `request.client.host`를 사용하며, 주소가 없으면 `unknown`을 사용한다. 이 값은 ASGI 서버의 프록시 헤더 처리에 따라 달라지므로 항상 직접 peer IP인 것은 아니다. 이 문서의 IP별 제한은 모두 이 값을 기준으로 한다.
- 현재 `Dockerfile`은 Uvicorn을 `--no-proxy-headers`로 실행한다. 따라서 Uvicorn은 `X-Forwarded-For`, `X-Forwarded-Proto`를 반영하지 않고, `request.client.host`는 접속 peer 주소 그대로다. 이전 설정(`--proxy-headers --forwarded-allow-ips=*`)은 `X-Forwarded-For` 목록의 맨 앞 주소(요청하는 쪽이 임의로 적을 수 있는 값)를 client 주소로 써서 IP별 실패 제한을 피할 수 있었기 때문에 되돌렸다. `backend/main.py`는 별도의 IP 헤더 검증을 추가하지 않는다.
- 이 설정에서는 헤더로 IP 값을 위조할 수 없다. 다만 Cloud Run처럼 앞단 프록시 뒤에서 실행하면 접속 peer가 프록시 주소일 수 있어, 서로 다른 사용자가 같은 IP 키로 묶여 IP별 한도(60초/30회)를 함께 소진할 수 있다. 같은 ID의 실패는 IP와 무관하게 합산하므로 ID별 제한이 주된 방어이고 IP 제한은 보조 방어다. Cloud Run에서 `request.client.host`가 실제로 어떤 값이 되는지, 실제 접속 IP가 필요하면 프록시가 붙인 값만 믿는 처리를 로그인 코드에 둘지는 후속 검증 사항이다.
- Uvicorn 동작 참고: [공식 ProxyHeadersMiddleware 구현](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py).
- ID 키는 `login_id` 단독이며 기본 한도는 60초/5회다. IP 키는 `request.client.host` 기준 IP 단독이며 기본 한도는 60초/30회다. 두 한도 중 하나라도 소진되면 다음 요청부터 비밀번호 검증 전에 429를 반환하고, 해당 429 요청을 실패 기록에 추가하지 않는다.
- 성공 로그인은 해당 ID의 실패 기록만 초기화하며 IP 전체 실패 기록은 유지한다. 제한 검사와 실패 기록 시 양쪽 저장소에서 60초 이상 지난 기록과 빈 키를 정리하므로, 다시 요청되지 않는 ID·IP의 만료 기록도 다음 처리 시 정리된다.
- 프로세스 로컬 기록은 재시작 시 사라지고 Cloud Run 다중 인스턴스 간 공유되지 않는다. 공유 저장소 전환과 Cloud Run 실제 원본 IP 식별·신뢰 프록시 정책은 후속 검증 사항이다. PostgreSQL 사용자 DB 연동 시 Redis 또는 PostgreSQL 등의 공유 저장소 전환을 검토한다.
- 팀 저장소에는 자동 사용자 seed나 `backend/user_store.py`가 없다. 테스트는 `tests/test_auth_router_runtime.py`의 `FakeAuthStore`가 실행 중 생성한 UUID·비밀번호를 사용한다.

### 의존성과 검증

- `backend/requirements.txt`: `bcrypt>=4.2,<5`, `PyJWT>=2.9,<3`, FastAPI 등
- `backend/requirements-dev.txt`: 위 requirements와 `pytest>=8`, `httpx>=0.27`
- 로컬에서 pytest 9.2.0과 anyio 4.14.1은 pytest 플러그인 경고를 냈다. 현재 검증 환경은 pytest 8.4.2로 경고 없이 실행했다. 공용 의존성·CI의 pytest 상한 또는 pytest 9 호환 anyio 버전은 별도 결정이 필요하다.
- 로그인 보안 리뷰 후속 수정 검증 결과: `.venv/Scripts/python.exe -m pytest tests/test_auth_router_runtime.py -q` 인증 테스트 17개, `.venv/Scripts/python.exe -m pytest -q` 전체 테스트 51개 통과. `git diff --check` 통과.

## 백엔드 구현 및 연동 현황 (강경희)

- `backend/auth.py`에 FastAPI 일반 로그인, bcrypt 검증, HttpOnly JWT 쿠키, CSRF, ID·IP별 로그인 실패 제한과 현재 사용자·관리자 권한 검증 의존성을 구현했다.
- JWT에는 고유 `jti`를 넣고, `TokenRevocationStore` 계약으로 인증·로그아웃 시 폐기 여부를 확인한다. 폐기 저장·조회가 없거나 실패하면 503으로 차단한다. J-05(로그아웃 뒤 동일 JWT 재사용)는 PostgreSQL 공유 폐기 저장소와 `main.py` 연결 전까지 열림이다.
- Google OAuth 시작·콜백은 PKCE(S256), state·nonce, authorization code 교환, Google ID 토큰 서명·issuer·audience·만료 검증을 수행한다. 검증된 `google` provider·`sub`와 **`email_verified=true`인 이메일**만 Google 사용자 저장소 계약에 전달한다. 이메일은 아래 "Google 로그인 계정 연결"의 조건을 모두 만족할 때만 기존 계정을 찾는 데 쓰고, 이메일로 관리자 권한을 새로 주지는 않는다.
- Mock OAuth·인증·보안 계약 테스트 26건과 DB 환경변수를 제거한 Python 전체 테스트 **215 passed, 1 skipped**를 확인했다.
- 실제 PostgreSQL OAuth·JWT 폐기 저장소, `main.py` 운영 연결, Cloud Run callback 및 실제 Google 브라우저 로그인은 미완료·미검증이다.

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
- 스키마는 `db/203_google_identities.sql`: `user_identities(provider, subject, user_id, email, created_at, PK(provider, subject), UNIQUE(provider, user_id))`, `signup_requests.google_sub`(부분 유일 색인), `users`·`signup_requests`의 `password_hash` NULL 허용(+ `signup_requests`는 비밀번호 해시나 `google_sub` 중 하나 필수 CHECK). 기존 설계(`users`·`signup_requests`에 provider 칸 4개·유일 색인 2개·CHECK 4개)보다 `users`를 건드리지 않고 이메일 연결과 구글 전용 가입이 같은 표 하나로 풀려서 이쪽으로 정했다. 동시에 같은 구글 계정이 와도 기본키·유일키와 `ON CONFLICT DO NOTHING` 뒤 재조회로 한 줄만 남는다(Postgres 시험으로 확인). 113·203을 적용하기 전의 DB(운영은 109까지)에서도 앱은 돈다: 저장소가 `signup_requests.google_sub`·`user_identities`가 있는지 저장소마다 한 번 확인해(`information_schema`) 없으면 비밀번호 로그인·가입·승인 쿼리에서 `google_sub` 조건을 빼고 Google 로그인만 `/login?oauth_error=google_unavailable` 안내로 보낸다. 113이 없으면 거절된 이메일 재가입이 409일 뿐 오류는 없다. 203을 적용한 뒤에는 서버를 다시 시작해야 Google 로그인이 켜진다(확인 결과를 캐시함). 시험 `tests/test_auth_schema_compat.py`.
- `/auth/google/start`는 Google 키(환경 변수 3개 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`)가 하나라도 없으면 JSON 503 대신 `/login?oauth_error=google_unavailable`로 303 이동한다. 콜백 오류도 같은 `oauth_error` 방식이다. 로그인 화면(`web/react-app/src/pages/LoginPage.jsx`)이 승인 대기·거절·실패·사용 불가 문구를 보여 준다.
- 배포에 Google 키를 넣고 운영 DB에 마이그레이션을 적용하는 일, GCP 콘솔 설정은 조장이 한다(`README.md`의 "Google 로그인 설정"). 실제 Google 계정으로 한 브라우저 왕복은 하지 않았다(미검증).

## AC (Given-When-Then)

- **AC-01 로그인 성공**: GIVEN 활성 사용자와 올바른 비밀번호, WHEN `POST /auth/login`, THEN 200 `{user_id, role}`과 HttpOnly JWT 쿠키를 반환한다.
- **AC-02 실패 응답 통일**: GIVEN 존재하지 않는 ID·틀린 비밀번호·비활성 계정, WHEN 로그인, THEN 같은 401 응답을 반환한다.
- **AC-03 더미 해시**: GIVEN 존재하지 않는 ID, WHEN 로그인, THEN 사전 생성 bcrypt 더미 해시를 검증하고 로그인에 성공하지 않는다.
- **AC-04 CSRF**: GIVEN CSRF 쿠키·헤더가 없거나 다름, WHEN 로그인 또는 로그아웃, THEN 403을 반환한다.
- **AC-05 사용자 ID**: GIVEN 유효한 `provena_auth` 쿠키, WHEN `Depends(current_user_id)`, THEN 인증된 UUID 문자열을 반환한다. 쿠키 누락·만료·변조는 401이다.
- **AC-06 제한**: GIVEN 같은 ID 단독으로 60초 내 5회 실패하거나 같은 `request.client.host` 기준 IP 단독으로 60초 내 여러 ID의 실패가 합계 30회 누적됨, WHEN 다시 로그인, THEN 어느 한도라도 소진되었으면 429를 반환한다.
- **AC-07 이메일 대소문자**: GIVEN 대문자가 섞인 이메일로 저장된 옛 계정(`db/113`가 겹치지 않는 것은 소문자로 바꿈), WHEN 대소문자와 무관하게 입력해 로그인, THEN 같은 계정으로 200이다(로그인 입력과 저장소 조회 모두 이메일은 소문자 비교). 이메일이 아닌 아이디는 대소문자를 구분한다. 시험: `tests/test_signup_edges.py`.
- **AC-07 최신 사용자 상태**: GIVEN JWT 발급 뒤 사용자의 role 또는 활성 상태가 변경됨, WHEN `/me`, THEN `AuthStore`의 최신 상태를 반영한다.
- **AC-08 회귀 검증**: GIVEN 현재 인증 구현, WHEN 인증 테스트와 전체 테스트를 실행, THEN 각각 17개와 51개가 통과한다.
- **AC-09 같은 IP의 다른 ID**: GIVEN 한 IP에서 A ID의 실패가 5회이고 IP 실패 합계는 30회 미만, WHEN 같은 IP에서 실패 기록이 없는 B ID로 로그인, THEN A의 ID 제한으로 차단하지 않고 B의 인증 결과를 반환한다.
- **AC-10 IP 변경**: GIVEN 같은 ID의 실패가 여러 IP에 걸쳐 60초 내 5회 누적됨, WHEN 새 IP에서 같은 ID로 로그인, THEN 429를 반환한다.
- **AC-11 성공 시 기록**: GIVEN ID와 IP에 실패 기록이 있고 두 한도가 소진되지 않음, WHEN 해당 ID로 로그인 성공, THEN ID 기록만 초기화하고 IP 기록은 유지한다. 이후 IP 실패 합계가 30회에 도달하면 다음 요청은 올바른 비밀번호여도 429를 반환한다.
- **AC-12 만료**: GIVEN ID 5회 또는 IP 30회의 실패 기록이 같은 시각에 누적됨, WHEN 가짜 시계로 59.999초 뒤 제한을 검사하면, THEN 제한을 유지한다. WHEN 60초 또는 그 이후에 검사하면, THEN 해당 기록과 빈 키를 정리하고 제한을 해제한다.
