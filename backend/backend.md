# backend/ : FastAPI 서버

## 이 폴더가 하는 일

API 진입점(`main.py`), 로그인(`auth.py`), 그래프 조립(`graph/build.py`의 `build_graph`), 체크포인터·Store 연결(`persistence.py`)을 둔다. 엔드포인트는 연결만 하고 로직은 하위 폴더에 둔다.

- 주인: 김승욱 (로그인 `auth.py`와 첫 배포 `/health`는 강경희)
- 입력: 화면·업무시스템 요청
- 출력: SSE 응답, 승인, 리콜 알림, 웹훅

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-05 | 김승욱 (Claude Code) | `requirements.txt`의 langgraph에 상한 `<1.3`을 둠. `graph/multi.py`가 컴파일된 그래프의 내부 구조를 읽어, 시험한 1.2.18과 같은 1.2 판까지만 받는다 | 미정 |
| 2026-11-02 | kkh-hue | Google OAuth Authorization Code + PKCE 시작·콜백, state/nonce 요청 쿠키 검증, Google JWK ID 토큰 검증, 주입형 OAuth 사용자 저장소·토큰 교환기 경계와 기존 JWT 쿠키 발급을 `auth.py`에 추가했다. 저장소 또는 RS256 검증 의존성이 없으면 503으로 차단하며 실제 DB·Cloud Run 검증은 하지 않았다. OAuth·기존 인증 관련 테스트와 전체 Python 테스트는 각각 53 passed, 214 passed·1 skipped였다. | #43 |
| 2026-11-01 | 강경희 | `require_admin`·주입용 팩터리와 `require_csrf`를 구현하고, 실제 Supabase PostgreSQL 인증 저장소에서 승인된 `public.users` 생성·RLS·API 역할 권한 회수 및 A(user)·B(admin) 계정을 확인했다. 별도 프로세스에서 데모·자동 스키마·시드를 차단한 로그인·실패·`/me`·권한·CSRF·Secure/HttpOnly 쿠키·로그아웃·A/B 전환 검사 26개와 보안 테스트 28개를 수행했다. 로그아웃 뒤 동일 JWT 재사용이 `/me` 200으로 재현된 J-05 후속으로 `jti`·폐기 저장소 인터페이스·조회 장애 503 차단·폐기 저장 확인 로그아웃을 구현했다. 당시 전체 Python은 189 passed, 1 skipped였고 J-05 후속은 206 passed, 1 skipped였다. 프로세스 간 계약 시험은 임시 SQLite 어댑터이며 PostgreSQL 공유 폐기 저장소·`main.py` 연결과 운영 재사용 차단 검증은 미완료라 J-05는 열림으로 유지한다. | #43 |
| 2026-10-30 | 강경희 | 로그인 보안 리뷰 후속: ID 단독 60초/5회·IP 단독 60초/30회 실패 제한으로 분리하고 만료된 키를 정리했다. 성공 시 ID만 초기화하고 IP 기록은 유지한다. `.venv/Scripts/python.exe -m pytest tests/test_auth_router_runtime.py -q` 17개, `.venv/Scripts/python.exe -m pytest -q` 51개 통과. | #15 |
| 2026-10-30 | 강경희 | 인증 1~3번: `current_user_id()` FastAPI 의존성, 로그인 ID·IP별 60초/5회 제한, 존재하지 않는 ID의 bcrypt 더미 해시 검증을 추가했다. 인증 테스트 11개·전체 pytest 24개, `compileall`, `git diff --check` 통과. 추후 PostgreSQL 사용자 DB 연동 시 인메모리 로그인 실패 기록을 공유 저장소로 전환하고, Cloud Run의 실제 IP 식별·로그인 API 및 Graph 사용자 ID 연동을 통합 검증할 예정. | #14 |
| 2026-10-30 | 강경희 | bcrypt·JWT·HttpOnly 쿠키·CSRF와 FastAPI 로그인·로그아웃·사용자 조회 라우터를 `AuthStore` 주입 구조로 이식했다. Fake AuthStore 인증 테스트 6개와 팀 전체 pytest 18개를 통과시켰다. PostgreSQL과 팀 `main.py` 통합은 미완료다. | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| J-05 | 2026-11-01 | 강경희 | 로그아웃은 쿠키만 삭제하여 이전에 발급된 동일 JWT를 다시 넣으면 실제 Supabase 저장소의 `/me`가 200을 반환함 | 탈취·복사된 JWT의 로그아웃 후 재사용 가능 | 강경희 / 김승욱(공유 저장소·main·DB 연결) | 열림 | | 실제 DB 읽기 전용 재현: 로그인 200 → `/me` 200 → 로그아웃 204 → 쿠키 없음 401 → 동일 JWT 복원 후 200. `jti`·차단 코드와 모의/SQLite 테스트는 구현했으나 PostgreSQL 공유 폐기 저장소 구현·운영 연결 및 동일 JWT 401 검증 전에는 해결로 판정하지 않음 |
