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
- 로그인 ID와 직접 peer IP별로 60초 동안 5회 실패를 제한한다.
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
| 로그인 ID 또는 직접 peer IP의 60초 내 실패 5회 | 429. 성공 로그인은 해당 ID 기록만 초기화하고 IP 기록은 유지한다. |
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

- `LoginRateLimiter`는 프로세스 메모리에서 ID별·IP별 실패 시각을 별도로 저장한다. 현재 IP는 `request.client.host`의 직접 peer만 사용하며, 신뢰 프록시 정책이 없으므로 `X-Forwarded-For`를 사용하지 않는다.
- Cloud Run 다중 인스턴스에서는 메모리 기록이 공유되지 않고, 실제 원본 IP 식별도 별도 프록시 정책이 필요하다. PostgreSQL 사용자 DB 연동 시 Redis 또는 PostgreSQL 등의 공유 저장소 전환을 검토한다.
- 팀 저장소에는 자동 사용자 seed나 `backend/user_store.py`가 없다. 테스트는 `tests/test_auth_router_runtime.py`의 `FakeAuthStore`가 실행 중 생성한 UUID·비밀번호를 사용한다.

### 의존성과 검증

- `backend/requirements.txt`: `bcrypt>=4.2,<5`, `PyJWT>=2.9,<3`, FastAPI 등
- `backend/requirements-dev.txt`: 위 requirements와 `pytest>=8`, `httpx>=0.27`
- 로컬에서 pytest 9.2.0과 anyio 4.14.1은 pytest 플러그인 경고를 냈다. 현재 검증 환경은 pytest 8.4.2로 경고 없이 실행했다. 공용 의존성·CI의 pytest 상한 또는 pytest 9 호환 anyio 버전은 별도 결정이 필요하다.
- 최신 실행 결과: 인증 테스트 11개, 전체 테스트 24개 통과. `python -m compileall -q backend/auth.py tests/test_auth_router_runtime.py`와 `git diff --check` 통과.

## AC (Given-When-Then)

- **AC-01 로그인 성공**: GIVEN 활성 사용자와 올바른 비밀번호, WHEN `POST /auth/login`, THEN 200 `{user_id, role}`과 HttpOnly JWT 쿠키를 반환한다.
- **AC-02 실패 응답 통일**: GIVEN 존재하지 않는 ID·틀린 비밀번호·비활성 계정, WHEN 로그인, THEN 같은 401 응답을 반환한다.
- **AC-03 더미 해시**: GIVEN 존재하지 않는 ID, WHEN 로그인, THEN 사전 생성 bcrypt 더미 해시를 검증하고 로그인에 성공하지 않는다.
- **AC-04 CSRF**: GIVEN CSRF 쿠키·헤더가 없거나 다름, WHEN 로그인 또는 로그아웃, THEN 403을 반환한다.
- **AC-05 사용자 ID**: GIVEN 유효한 `provena_auth` 쿠키, WHEN `Depends(current_user_id)`, THEN 인증된 UUID 문자열을 반환한다. 쿠키 누락·만료·변조는 401이다.
- **AC-06 제한**: GIVEN 같은 ID 또는 같은 직접 peer IP에서 60초 내 5회 실패, WHEN 다시 로그인, THEN 429를 반환한다. 성공 로그인은 ID 기록만 초기화한다.
- **AC-07 최신 사용자 상태**: GIVEN JWT 발급 뒤 사용자의 role 또는 활성 상태가 변경됨, WHEN `/me`, THEN `AuthStore`의 최신 상태를 반영한다.
- **AC-08 회귀 검증**: GIVEN 현재 인증 구현, WHEN 인증 테스트와 전체 테스트를 실행, THEN 각각 11개와 24개가 통과한다.
