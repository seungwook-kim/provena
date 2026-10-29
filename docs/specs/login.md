# 로그인 API 명세서 초안

상태: 독립 MVP 복구 및 팀 인증 라우터 이식, 앱 통합 미완료
작성 범위: 독립 MVP의 검증 기록, 팀 backend/auth.py의 현재 계약, 향후 통합 계획
비고: 이 문서는 팀 통합 전 초안이다. 독립 MVP에서는 인메모리 저장소 기반 인증 API를 구현·검증했으며, 실제 PostgreSQL 스키마·마이그레이션·팀 통합은 아직 구현하지 않는다.

## 복구 상태와 구현 위치 (2026-10-30)

팀 저장소에 이 문서가 없었으므로 독립 MVP 문서의 Why / Goal / What / How / AC와 상세 설계를 복원했다. 아래 현재 계약을 우선 적용한다. 상세 절에서 “제안”, “향후”, “합의 필요”로 표시한 내용은 운영 목표이며 완료 주장이 아니다.

### 독립 MVP에서 구현 및 검증 완료 — 이전 기록

- 원본: `../provena-login-mvp`. 실행 대상은 해당 폴더에서 `uvicorn backend.main:app`이며 `main.py`의 모듈 수준 `app = create_app()`을 사용한다.
- `backend/main.py:create_app()`에 로그인·로그아웃·`/me`, CSRF 비교, 로그인 실패 제한, 민감 입력을 생략하는 검증 오류 처리가 있다. 같은 파일이 `/login.html`, `/login.css`, `/login.js`를 제공한다.
- `backend/auth.py`: bcrypt, JWT HS256, 최소 32바이트 AUTH_SECRET, 인증/CSRF 쿠키, 쿠키에서 UUID 추출. `backend/user_store.py`: UserRecord, InMemoryUserStore, 로컬 환경변수 계정 시드.
- 독립 MVP: pytest `29 passed, 1 skipped`. 미실행 1건은 Playwright 미설치로 인한 선택적 브라우저 자동화 테스트이며, Chrome 수동 로그인·로그아웃 검증은 완료했다.
- 원본은 사용자 생성 시 user/admin을 제한하고 `/me`에서 최신 활성 상태와 role을 조회한다. 별도 관리자 API 접근 제어와 사용자별 리소스 소유권 검사는 구현되지 않았다.

### 팀 저장소에 이번에 반영한 내용 — 현재 계약

- `backend/auth.py:create_auth_router(*, store, secret=None, cookie_secure=None, rate_limiter=None) -> APIRouter`. 아직 앱에 등록되지 않았으므로 팀 서버에서 아래 URL을 사용할 수 있는 상태는 아니다.
- 현재 화면 `web/login.js`는 로그인 전에 `GET /auth/csrf`를 `credentials: same-origin`으로 호출하고, 정확히 204인 응답에서 새 쿠키를 읽어 `X-CSRF-Token`으로 전달한다. 204 응답에는 JSON 파싱을 시도하지 않는다. 로그인·네트워크 오류의 모든 종료 경로에서 비밀번호를 지우며, 버튼·Enter 중복 요청을 막는다. 로그아웃 뒤 재로그인하면 로그인 단계에서 CSRF 쿠키를 다시 발급받는다.
- `AuthStore`는 `get_by_login_id(str)`와 `get_by_user_id(UUID | str)` 조회 계약이다. 반환 모델 `AuthUser`는 user_id, login_id, password_hash, role, is_active이며 hash는 repr에서도 제외한다. 발견된 팀 파일에는 기존 AuthStore가 없었다. DB 초안이 기대하는 두 메서드와 모델 계약을 복원했다.
- 저장소는 필수 주입한다. 자동 인메모리 전환, DB 오류 후 임시 계정 전환, 계정 자동 시드는 없다. `secret`은 팀 앱 연결 시 명시적으로 주입하는 것을 계약으로 삼고, 현재 저수준 helper의 `AUTH_SECRET` 환경변수 fallback은 운영 통합 전 제거·금지 여부를 확정해야 한다. 향후 PostgresAuthStore를 검증한 뒤 주입한다. 저장소 연결과 수명 관리는 호출 측 책임이다.
- `GET /auth/csrf` → 204 및 읽기 가능한 CSRF 쿠키. MVP의 HTML 응답에서 하던 토큰 발급을 화면과 독립시켰다. 최초 로그인과 로그아웃 후 재로그인 전에 호출한다.
- `POST /auth/login`: JSON login_id/password 및 CSRF 쿠키와 X-CSRF-Token 필요. 성공 200 `{user_id, role}`와 HttpOnly JWT 쿠키. 없는 ID·틀린 비밀번호·비활성·허용하지 않은 role은 같은 401. 클라이언트 IP와 login_id 조합별 60초 내 실패 5회 후 429.
- `POST /auth/logout`: CSRF 필수, 204 및 인증/CSRF 쿠키 삭제. JWT 자체의 서버 측 폐기는 미구현이다.
- `GET /me`: 쿠키 JWT 검증 후 저장소에서 최신 활성 상태와 user/admin role 재확인. 성공 200 `{user_id, role}`, 인증 실패 401.
- 검증 입력 오류는 이 라우터의 AuthRoute에서 민감한 입력을 포함하지 않는 422로 바꾼다. CSRF 실패는 403, 로그인 제한은 429, 저장소 예외는 내부 메시지 없이 503이다. 비밀번호·hash·JWT를 JSON에 반환하지 않는다. 앱 전체의 로깅/오류 마스킹은 별도 통합 검증 대상이다.
- JWT HS256, 만료 30분, user_id/role/iat/exp, 인증 쿠키 provena_auth(HttpOnly), CSRF 쿠키 provena_csrf(읽기 가능), SameSite=Lax, Path=/를 유지한다. secret 누락/32바이트 미만은 라우터 생성 시 거부한다.
- Secure 기본값은 True. `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1` 두 환경변수를 모두 만족할 때만 False를 허용한다. 원본의 DEV_MODE 단독 조건보다 엄격하다. 저수준 쿠키 헬퍼는 원본 호출 계약을 유지하므로 직접 사용 시 호출자가 Secure를 명시해야 한다.
- `get_current_user_id(request, secret=...)`는 JWT에서 UUID만 추출한다. 최신 사용자 상태 확인에는 `get_current_user(request, store=..., secret=...)` 또는 `Depends(create_current_user_dependency(store=..., secret=...))`를 사용한다.
- 기존 인자 없는 `current_user_id() -> str`는 NotImplementedError TODO를 보존했다. 조사 범위 내 호출처는 없었다. 요청 없는 호출에 임의 사용자 ID를 반환하지 않는다. 하위 API 연결 시 호출 계약 합의가 필요하다.
- FastAPI 공식 참고: [APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/), [라우터별 APIRoute](https://fastapi.tiangolo.com/how-to/custom-request-and-route/).

### 아직 완료되지 않은 내용

- 실제 PostgreSQL 사용자 DB 연동. `../provena-login-db-lab/db/001_create_users.sql` 및 `backend/postgres_auth_store.py` 초안과 fake connection 테스트가 있다. 실제 DB 연결·마이그레이션 실행·통합 테스트 완료 증거는 없다. 이 초안의 AuthStore/AuthUser import 대상도 원래 누락되어 있었다.
- 인메모리는 독립 MVP 테스트 수단이며 최종 저장소가 아니다. DB 스키마 합의 → 별도 승인 범위에서 adapter 이식 → 실제 PostgreSQL 검증 → 저장소 명시 주입 순서로 전환한다. 실패 시 대체 계정/저장소로 전환하지 않는다.
- 실제 PostgreSQL 사용자 DB 연결, Google 로그인, 팀 main.py에서 include_router 연결, Vite + React + Tailwind 화면 전환, 운영 환경 통합 테스트.
- 관리자 API 권한 검사와 사용자별 thread/memory 분리·소유권 검사는 하위 기능 통합 과제다. 분산 rate limiter, JWT 즉시 폐기, HTTPS/프록시/로그 정책 검증도 남아 있다.
- 팀 requirements에는 bcrypt와 PyJWT가 없다. 별도 변경 승인 후 원본 선언 `bcrypt>=4.2,<5`, `PyJWT>=2.9,<3`의 팀 환경 호환성을 확인하고 추가해야 한다. 이번 작업에서는 requirements를 변경하지 않았다.

### 이번 PC 검증 상태

- 현재 `.venv-auth`에서 Python 3.13.15, bcrypt 4.3.0, PyJWT 2.15.1, FastAPI 0.162.0, httpx 0.28.1, pytest 9.2.0을 확인했다. `pip check`는 `No broken requirements found`였다.
- 팀 저장소의 인증 라우터 전용 Fake AuthStore 테스트(`tests/test_auth_router_runtime.py`)는 `6 passed`, 저장소 전체 pytest는 `18 passed, 1 warning`이었다. 테스트 앱에 `create_auth_router`를 등록해 CSRF 발급, 로그인·로그아웃·재로그인, `/me`, 401/403/422/429/503, 만료·변조 JWT, 비활성·role 변경, Secure 쿠키 정책, secret 오류를 검증했다. Python 문법 검사와 `node --check web/login.js`도 통과했다.
- Starlette의 `httpx` TestClient 사용 deprecation warning 1건이 남았다. 독립 MVP와 이번 팀 저장소 검증 결과는 위의 각 기록으로 구분한다.
- 현재 팀 requirements에는 bcrypt와 PyJWT가 등록되어 있지 않다. 담당자 승인 후 `bcrypt>=4.2,<5`, `PyJWT>=2.9,<3` 두 항목만 추가하고 기존 버전은 변경하지 않아야 한다.
- 원본 API 테스트는 `backend.main:create_app`에 연결되므로 팀 라우터 통과 증거가 아니다. 이번 검증은 별도 FastAPI 테스트 앱에서 명시적 Fake AuthStore를 주입해 수행했다.
- 이번 화면 보강에서 변경한 파일은 `web/login.js`와 이 문서다. 기존 `backend/auth.py`, `main.py`, db, Docker, schemas, requirements, 팀원이 수정한 파일, 원본 MVP는 변경하지 않았다. 팀 라우터 자체는 이전 복구 작업의 결과이며 이번 화면 작업에서 재수정하지 않았다. 팀 규칙의 SPEC/작업 로그 갱신도 요청 범위 밖이므로 수행하지 않았다.

---

아래 상세 절은 독립 MVP 기준과 향후 팀 설계를 보존한 것이다. 팀의 현재 동작·완료 상태는 위 계약과 검증 상태를 따른다.

## Why

로그인 화면 MVP를 향후 Provena 팀 서비스에 안전하게 연결하려면, 비밀번호 검증·토큰·쿠키·사용자 식별의 경계를 먼저 고정해야 한다. 현재 목표는 PostgreSQL을 변경하지 않고, 통합 가능한 인증 핵심 모듈과 FastAPI 로그인 API 3개를 테스트용 인메모리 저장소에 연결하는 것이다.

## Goal

- 독립 인증 모듈에서 bcrypt 해시·검증과 JWT 발급·검증을 제공한다.
- `POST /auth/login`, `POST /auth/logout`, `GET /me`를 FastAPI로 제공한다.
- 테스트용 인메모리 사용자 저장소로 활성 상태와 role을 검증한다.
- `PROVENA_ENV=local`이고 `PROVENA_DEV_MODE=1`인 경우에만 `testuser`와 `testadmin` 계정을 환경변수 비밀번호로 생성한다.
- JWT는 UUID 기반 `user_id`, `role`, `exp`를 포함하고 `AUTH_SECRET` 없이는 동작하지 않는다.
- 인증 쿠키는 HttpOnly와 SameSite=Lax를 사용하고 로컬/운영의 Secure 설정을 분리한다.
- 만료·변조·누락 토큰과 잘못된 비밀번호를 거부한다.
- 테스트 기준 9개를 자동화한다.

Out of Scope: PostgreSQL users 테이블 조회·스키마·마이그레이션, Google OAuth, 팀 저장소 통합, 배포와 재배포.

## What

### Happy Path

1. API 계층이 로그인 입력을 검증하고, 주입한 AuthStore에서 사용자 hash·role·활성 상태를 조회한다. 실제 DB 연결은 미완료다.
2. 인증 모듈이 bcrypt로 비밀번호를 검증한다.
3. 성공하면 API 계층이 UUID와 role로 JWT를 만들고 HttpOnly 쿠키를 설정한다.
4. 보호 요청에서는 쿠키의 JWT에서 서버가 `user_id`를 복원한다.

### Edge Case

- 빈 secret, 누락 쿠키, 잘못된 서명, 만료 토큰은 인증 실패로 처리한다.
- 잘못된 비밀번호는 검증 실패로 처리하고 원문을 저장하거나 로그에 남기지 않는다.
- 비활성 계정과 관리자 role의 최종 판단은 추후 DB 조회 계층에서 수행한다.
- 클라이언트가 전달한 `user_id`는 인증 주체로 사용하지 않는다.

## How

- 독립 MVP: `backend/auth.py`는 인증 핵심, `backend/main.py:create_app()`은 API 3개와 정적 화면 라우트를 담당한다. 팀 저장소: 인증 핵심과 `create_auth_router()`가 모두 `backend/auth.py`에 있고 팀 `main.py`는 변경하지 않았다.
- 사용자 저장소: `backend/user_store.py`의 인메모리 저장소를 테스트와 MVP 검증에만 사용한다. 팀 통합 시 PostgreSQL repository로 교체한다.
- 로컬 계정 시드: `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1`일 때만 `PROVENA_TESTUSER_PASSWORD`와 `PROVENA_TESTADMIN_PASSWORD`를 읽는다. 두 값은 실행 중 bcrypt hash로 바꾸고 저장소에는 hash만 보관한다.
- 의존성: 독립 MVP의 `backend/requirements.txt`와 `requirements-dev.txt`에 FastAPI, bcrypt, PyJWT, Starlette, httpx, pytest를 선언한다. 팀 저장소 requirements에는 해당 인증 라이브러리가 확인되지 않았으므로 통합 전에 팀 합의가 필요하다.
- provisional 설정: 쿠키 이름 `provena_auth`, 토큰 30분, HS256은 통합 전 팀 합의가 필요한 임시값이다.
- secret: `AUTH_SECRET` 환경변수에서만 읽고 누락 시 안전한 구성 오류를 낸다.
- 쿠키: `HttpOnly=True`, `SameSite=Lax`, 로컬 HTTP `Secure=False`, 운영 HTTPS 호출 시 `secure=True`를 명시한다.
- 테스트는 실행 중 생성한 secret과 UUID만 사용하고, 저장소에 실제 비밀번호·secret·토큰을 기록하지 않는다.

## AC

- Given 유효한 비밀번호 hash, When 올바른 비밀번호를 검증하면, Then 검증 결과가 성공이어야 한다.
- Given 유효한 비밀번호 hash, When 다른 비밀번호를 검증하면, Then 검증 결과가 실패해야 한다.
- Given 평문 비밀번호, When hash를 생성하면, Then 저장 결과가 평문과 달라야 한다.
- Given 유효한 secret과 UUID, When JWT를 발급·검증하면, Then 동일한 `user_id`와 role을 얻어야 한다.
- Given 만료된 JWT, When 검증하면, Then 인증 실패여야 한다.
- Given 서명이 변조된 JWT, When 검증하면, Then 인증 실패여야 한다.
- Given `AUTH_SECRET`가 없으면, When 토큰 발급을 시도하면, Then 안전한 구성 오류여야 한다.
- Given 인증 쿠키를 설정하면, Then HttpOnly·SameSite=Lax·Max-Age가 있어야 하고 로컬 Secure는 없어야 한다.
- Given 인증 쿠키 삭제를 요청하면, Then 같은 쿠키가 만료 처리되어야 한다.
- Given 테스트 저장소의 활성 사용자와 올바른 비밀번호, When `POST /auth/login`을 호출하면, Then 200과 HttpOnly 인증 쿠키가 반환되어야 한다.
- Given 잘못된 비밀번호·존재하지 않는 ID·비활성 계정, When `POST /auth/login`을 호출하면, Then 같은 401 실패 계약이어야 한다.
- Given 인증 쿠키가 없거나 유효하지 않으면, When `GET /me`를 호출하면, Then 401이어야 한다.
- Given 인증된 사용자가 `POST /auth/logout`을 호출하면, Then 쿠키가 삭제되고 이후 `GET /me`가 401이어야 한다.
- Given 테스트 저장소에 admin role 사용자가 있으면, When 로그인하면, Then `/me`가 서버 저장소의 admin role을 반환해야 한다.

## 1. 목적과 범위

### 목적

Provena의 자체 로그인 구조를 정의하고, 향후 화면과 FastAPI 백엔드가 연결될 때 사용할 최소 API 계약과 보안 경계를 정한다.

### 현재 범위

- 자체 로그인
- 독립 MVP의 인메모리 사용자 저장소 기반 사용자 조회
- FastAPI `POST /auth/login`, `POST /auth/logout`, `GET /me` 라우트
- bcrypt 기반 비밀번호 검증
- JWT를 HttpOnly 쿠키로 전달
- 인증 사용자와 관리자 권한 구분
- 사용자별 thread·memory 데이터 분리

### 현재 범위에서 제외

- 회원가입
- 비밀번호 재설정·변경
- 이메일 인증
- Google OAuth
- 실제 PostgreSQL 스키마 생성·마이그레이션·repository 구현
- 팀 저장소의 FastAPI 앱과 인증 모듈 통합

Google OAuth는 별도 확장 기능으로 나중에 계약을 추가한다.

## 2. 인증 방식

1. 클라이언트가 `login_id`와 `password`를 로그인 API에 전송한다.
2. 서버는 AuthStore의 활성 사용자 여부와 role을 확인하고 bcrypt로 비밀번호를 검증한다. PostgreSQL은 향후 저장소 구현이다.
3. 검증에 성공하면 서버가 JWT를 발급하고 HttpOnly 쿠키로 설정한다.
4. 이후 보호 API는 쿠키의 JWT를 서버에서 검증해 현재 사용자 ID와 role을 결정한다.
5. 비밀번호 원문은 저장하거나 로그에 남기지 않는다.

JWT를 `localStorage`나 `sessionStorage`에 저장하지 않는 것을 원칙으로 한다. 현재 로그인·로그아웃에는 double-submit CSRF를 적용하며 운영의 추가 방어 정책은 별도 합의한다.

## 3. 사용자 모델 초안

논리 모델은 다음과 같다. 실제 PostgreSQL 타입·제약조건·마이그레이션 도구는 팀 합의가 필요하다.

| 필드 | 제안 타입 | 제안 제약 | 설명 |
|---|---|---|---|
| `user_id` | UUID | primary key | 서버가 발급하는 사용자 식별자 |
| `login_id` | 문자열 | unique, not null | 로그인에 사용하는 ID |
| `password_hash` | 문자열 | not null | bcrypt 결과만 저장 |
| `role` | 열거값 또는 문자열 | `user` / `admin` | 권한 구분 |
| `is_active` | boolean | not null | 비활성 계정 로그인 차단 |
| `created_at` | timestamp | not null | 계정 생성 시각 |

비밀번호 원문, JWT 원문, secret 값은 사용자 모델이나 저장소에 저장하지 않는다.

## 4. API 계약 초안

### 4.1 `POST /auth/login`

로그인 ID와 비밀번호를 검증하고 인증 쿠키를 설정한다.

요청 JSON 제안:

```json
{
  "login_id": "사용자 입력값",
  "password": "사용자 입력값"
}
```

성공 동작:

- HTTP 상태 코드: `200` 제안
- 현재 응답 본문: `user_id`, `role`만 포함하는 JSON
- JWT를 HttpOnly 쿠키로 설정
- 비밀번호나 JWT 원문은 응답 본문에 포함하지 않음

실패 동작:

- HTTP 상태 코드: `401`
- 존재하지 않는 ID, 잘못된 비밀번호, 비활성 계정을 외부에서 구분하지 않음
- 로그인 실패 메시지는 하나로 통일하는 것을 제안한다. 예: `로그인 정보가 올바르지 않습니다.`

정확한 성공 응답 JSON, 오류 코드, 오류 JSON 형식은 팀 합의가 필요하다.

### 4.2 `POST /auth/logout`

현재 인증 쿠키를 제거한다.

- 인증 쿠키의 만료 또는 삭제 처리
- 현재 성공 상태 코드는 `204`다.
- 로그아웃 후 보호 API 호출은 `401`이어야 함
- 서버 측 JWT 폐기 목록을 둘지는 토큰 만료 정책과 함께 결정한다

### 4.3 `GET /me`

현재 인증된 사용자의 최소 식별 정보와 권한을 반환한다.

성공 응답 JSON 제안:

```json
{
  "user_id": "uuid",
  "role": "user"
}
```

- 현재 인증 성공: `200`
- 쿠키 누락·JWT 만료·서명 오류: `401`
- 비밀번호 hash나 내부 보안 필드는 반환하지 않음
- 응답 필드와 상태 코드는 팀 합의 필요

## 5. JWT 정책 초안

JWT payload에는 다음 항목을 포함하는 것을 제안한다.

- `user_id`: 사용자 UUID
- `role`: 발급 시점의 role
- `exp`: 만료 시각

현재 `iat`도 발급한다. `jti`와 refresh token은 미구현이며 팀 합의가 필요하다.

환경 및 쿠키 정책:

| 항목 | 초안 정책 |
|---|---|
| secret | `AUTH_SECRET` 환경변수에서만 읽음 |
| 쿠키 저장 방식 | HttpOnly 쿠키 |
| `HttpOnly` | `True` |
| `SameSite` | `Lax` 제안 |
| 로컬 HTTP | `Secure=False` |
| 운영 HTTPS | `Secure=True` |
| 쿠키 이름 | 팀 합의 필요 |
| access token 만료 시간 | 팀 합의 필요 |
| refresh token | 도입 여부 팀 합의 필요 |

JWT secret은 코드·문서·로그에 기록하지 않는다. role은 토큰에 포함하더라도 관리자 API 접근 시 서버의 최신 사용자 권한을 다시 조회해 검증하는 것을 원칙으로 한다.

## 6. 권한과 소유권 (하위 기능 통합 목표)

- `user`: 자신의 thread, memory, 답변 등 본인 데이터만 접근
- `admin`: 별도로 승인된 관리자 API에 접근
- 관리자 API는 요청의 JWT role만 믿지 않고 서버에서 현재 role을 재검증
- 다른 사용자의 ID나 리소스 ID를 요청에 넣어도 소유권 검사로 차단
- 인증된 `user_id`는 쿠키의 검증 결과에서 서버가 결정
- 클라이언트가 전달한 `user_id`는 인증 주체로 신뢰하지 않음

권한이 없는 요청은 일반적으로 `403`을 제안한다. 존재 여부를 노출하면 안 되는 리소스는 `404`로 숨길지 팀 합의가 필요하다.

## 7. 사용자별 데이터 분리 (미통합 설계)

로그인 API 자체는 사용자 ID를 요청으로 받지 않는다. 서버가 인증 쿠키에서 결정한 사용자 ID를 하위 기능에 전달한다.

- `thread_id`는 `user_id`와 함께 저장하고 조회 시 소유권을 확인한다.
- 장기 기억 namespace는 사용자별로 분리한다. 예: `memories/{user_id}`.
- `/me/memory` 계열 API는 현재 인증 사용자 namespace만 대상으로 한다.
- thread·memory·답변·리콜 알림 조회 시 사용자 조건을 항상 서버 쿼리에 포함한다.
- 관리자 전체 조회는 별도 권한 검사와 감사 로그 정책을 거친다.

## 8. 보안 정책 (MVP 구현 및 운영 목표)

- 비밀번호는 bcrypt로 해시하고 원문을 저장하지 않는다.
- 비밀번호와 JWT 원문을 애플리케이션 로그, 오류 로그, 분석 도구에 남기지 않는다.
- 로그인 실패 횟수 제한과 일정 시간 지연 또는 rate limit을 도입한다. 구체적인 기준은 팀 합의 필요다.
- 쿠키 기반 인증에 맞는 CSRF 방어 방식을 확정한다. 후보는 CSRF 토큰, Origin/Referer 검증, 보호 메서드 정책 조합이다.
- JWT를 localStorage, sessionStorage, URL query string에 저장하지 않는다.
- `is_active=false` 계정은 로그인할 수 없고, 이미 발급된 토큰을 계속 허용할지 즉시 차단할지는 팀 합의가 필요하다. 보안 우선 제안은 보호 API에서 사용자 상태를 재확인하는 것이다.
- 계정 존재 여부가 드러나지 않도록 ID 없음·비밀번호 오류·비활성 계정의 외부 메시지를 통일한다.
- `AUTH_SECRET`가 없거나 너무 약하면 운영 모드 기동을 거부하는 정책을 검토한다.
- 관리자 권한 변경과 로그인 실패 누적을 감사 로그에 남길지 팀 합의 필요다.

## 9. 데모 계정 정책

- 회원가입은 현재 범위에서 제외한다.
- 데모·평가 계정은 초기화 스크립트로 생성할 예정이다.
- 계정 비밀번호를 코드, 문서, 커밋, 테스트 출력에 기록하지 않는다.
- 초기화 시 환경변수 또는 실행 시 안전한 입력 방식으로 비밀번호를 받는다.
- 저장소에는 비밀번호가 아닌 필요한 환경변수 이름과 설정 방법만 둔다.
- 데모 계정의 role과 `is_active` 기본값은 팀 합의 후 고정한다.

## 10. 테스트 완료 기준

다음 시나리오를 자동 테스트와 수동 검증으로 나누어 확인한다.

- 정상 ID·비밀번호로 로그인 성공
- 잘못된 비밀번호 거부
- 존재하지 않는 ID와 비밀번호 오류의 메시지 통일
- 비활성 계정 로그인 거부
- 로그인 성공 후 `/me`에서 올바른 사용자 ID와 role 반환
- 로그아웃 후 보호 API 인증 거부
- 일반 사용자의 관리자 API 접근 거부
- 관리자만 승인된 관리자 API 접근 가능
- 사용자 A가 사용자 B의 thread·memory·답변을 조회하거나 수정할 수 없음
- JWT·비밀번호·secret이 응답·로그·저장소에 노출되지 않음
- 만료·변조된 JWT 거부
- CSRF 방어 정책이 보호 상태 변경 API에 적용됨
- 로그인 시도 제한이 정한 기준대로 동작함

## 11. 팀 합의 필요 사항

다음 항목은 이 초안에서 확정하지 않는다.

1. 쿠키 이름
2. JWT access token 만료 시간
3. refresh token 도입 여부와 저장 방식
4. 로그인 성공·실패 응답 JSON의 정확한 필드
5. `401`·`403`·`404` 사용 규칙
6. bcrypt cost 또는 라이브러리 선택
7. 로그인 rate limit 기준과 잠금 정책
8. CSRF 방어 방식
9. 비활성 계정의 기존 토큰 즉시 폐기 방식
10. PostgreSQL 마이그레이션 도구와 실행 책임
11. 데모 계정 초기화 시점·계정 수·role
12. 관리자 권한 변경과 인증 이벤트 감사 로그 보존 정책
13. Google OAuth를 별도 provider/API로 추가할 때의 계정 연결 방식

## 12. 통합 전 확인 사항

- 이 문서의 API 계약을 팀이 승인한 뒤 FastAPI 라우트와 DB 변경을 시작한다.
- `backend/schemas/` 또는 공용 응답 형식을 변경하면 팀 계약 변경 절차를 따른다.
- 실제 구현 시 비밀값을 `.env`에만 두고 `.env.example`에는 값 없는 변수명만 둔다.
- 로그인 화면은 현재 연결된 인증 API와 같은 출처로 동작하며, Google OAuth는 준비 중 상태로 유지한다.

## 13. MVP 보안 점검 결과

### 확인·수정한 항목

- 비밀번호는 bcrypt hash만 저장하고 API 응답에 `password_hash`를 포함하지 않는다.
- 비밀번호는 최소 8자, UTF-8 기준 최대 72바이트로 제한한다. bcrypt의 입력 길이 제한을 명시적으로 다룬다.
- JWT 알고리즘은 HS256으로 고정하고 `user_id`, `role`, `exp` 필수 클레임과 서명을 검증한다.
- `AUTH_SECRET`는 최소 32바이트를 요구하며 코드에 기본 secret을 두지 않는다.
- 인증 JWT 쿠키는 HttpOnly·SameSite=Lax·Path=/·Max-Age를 사용한다. `PROVENA_DEV_MODE=1` 로컬에서는 Secure를 끄고, 그 외 기본값은 Secure를 켠다.
- 로그인과 로그아웃에 double-submit CSRF 토큰을 적용한다. CSRF 토큰은 읽을 수 있는 별도 쿠키와 `X-CSRF-Token` 헤더를 비교하고, JWT 쿠키는 계속 HttpOnly로 유지한다.
- 로그인 실패는 동일한 401 메시지를 사용하고, 프로세스 단위 5회/60초 로그인 실패 제한을 둔다.
- `/me`는 JWT의 user ID를 저장소의 최신 사용자 role·활성 상태와 다시 대조한다. JWT의 role만으로 권한을 결정하지 않는다.
- `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1`이 모두 아니면 `testuser`·`testadmin`을 자동 생성하지 않는다.
- FastAPI가 로그인 화면을 같은 출처로 제공하고 `/docs`, `/redoc`, `/openapi.json`을 비활성화한다.
- 화면 JavaScript는 실제 form 제출 없이 클릭·Enter 처리로 JSON 요청을 보내고, 사용자 입력과 서버 메시지를 `textContent`로 표시하며, 비밀번호 입력값을 성공·실패 후 지운다.
- `/login.css`와 `/login.js`는 프로젝트 전체를 공개하지 않는 명시적 라우트로 제공한다.

### 남은 위험과 미검증 대책

- rate limit은 현재 프로세스 메모리 기반이다. 운영에서는 Redis 등 영구·분산 저장소와 IP·계정별 정책이 필요하다.
- 로그아웃은 브라우저 쿠키를 삭제하지만 이미 발급된 JWT 자체를 즉시 폐기하지 않는다. 즉시 폐기에는 짧은 만료 시간, token version 또는 서버 측 폐기 저장소가 필요하다.
- 사용자 role·`is_active` 조회는 현재 인메모리 저장소다. 운영 PostgreSQL repository와 트랜잭션·권한 검증으로 교체해야 한다.
- 로컬 테스트는 HTTP loopback이다. 운영에서는 HTTPS와 Secure 쿠키를 사용해야 한다.
- CSP, 보안 헤더, 운영 로그 마스킹, 감사 로그 보존 정책은 별도 운영 설정이 필요하다.
- 실제 브라우저 자동화 검증은 브라우저 접근 환경에 따라 별도로 수행해야 하며, API 테스트만으로 브라우저 UI 동작을 완료로 판단하지 않는다.
