# backend/ : FastAPI 서버

## 이 폴더가 하는 일

API 진입점(`main.py`), 로그인(`auth.py`), 그래프 조립(`app.py`), 체크포인터·Store 연결(`persistence.py`)을 둔다. 엔드포인트는 연결만 하고 로직은 하위 폴더에 둔다.

- 주인: 김승욱 (로그인 `auth.py`와 첫 배포 `/health`는 강경희)
- 입력: 화면·업무시스템 요청
- 출력: SSE 응답, 승인, 리콜 알림, 웹훅

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-10-30 | 강경희 | 인증 1~3번: `current_user_id()` FastAPI 의존성, 로그인 ID·IP별 60초/5회 제한, 존재하지 않는 ID의 bcrypt 더미 해시 검증을 추가했다. 인증 테스트 11개·전체 pytest 24개, `compileall`, `git diff --check` 통과. 추후 PostgreSQL 사용자 DB 연동 시 인메모리 로그인 실패 기록을 공유 저장소로 전환하고, Cloud Run의 실제 IP 식별·로그인 API 및 Graph 사용자 ID 연동을 통합 검증할 예정. | 미정 |
| 2026-10-30 | 강경희 | bcrypt·JWT·HttpOnly 쿠키·CSRF와 FastAPI 로그인·로그아웃·사용자 조회 라우터를 `AuthStore` 주입 구조로 이식했다. Fake AuthStore 인증 테스트 6개와 팀 전체 pytest 18개를 통과시켰다. PostgreSQL과 팀 `main.py` 통합은 미완료다. | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
