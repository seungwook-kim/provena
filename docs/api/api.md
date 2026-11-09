# docs/api/ : 정적 OpenAPI 명세

## 이 폴더가 하는 일

`openapi.json`은 FastAPI 앱(`backend/main.py`)이 내는 REST API 명세를 파일로 뽑은 것이다. 업무시스템 쪽이 SDK나 클라이언트를 만들 때 입력으로 쓴다. `export_openapi.py`가 키와 DB 없이 앱 객체만 만들어(서버는 띄우지 않음) `app.openapi()`를 쓴다. 로그인 라우터는 `DATABASE_URL`이 있을 때만 붙으므로 스크립트가 빈 사용자 저장소를 꽂아 라우터를 붙인다. 라우터가 바뀌면 다시 만든다.

    python docs/api/export_openapi.py

- 주인: 김승욱
- 입력: `backend/main.py`의 앱
- 출력: `openapi.json`

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | `export_openapi.py`와 `openapi.json` 추가(35개 경로: 로그인, `/chat`, `/threads`, 결정표·승인, 리콜, 변경 감시, `/health` 등. `/mcp`는 명세에 나오지 않음) | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|