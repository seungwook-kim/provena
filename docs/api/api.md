# docs/api/ : 정적 OpenAPI 명세

## 이 폴더가 하는 일

`openapi.json`은 FastAPI 앱(`backend/main.py`)이 내는 REST API 명세를 파일로 뽑은 것이다. 업무시스템 쪽이 SDK나 클라이언트를 만들 때 입력으로 쓴다. `export_openapi.py`가 키와 DB 없이 앱 객체만 만들어(서버는 띄우지 않음) `app.openapi()`를 쓴다. 로그인 라우터는 `DATABASE_URL`이 있을 때만 붙으므로 스크립트가 빈 사용자 저장소를 꽂아 라우터를 붙인다. 내 정보 라우터(`/me/profile`)는 앱이 실제 사용자 저장소와 짝일 때만 붙이므로 스크립트가 빈 저장소와 임시 암호 키로 직접 붙인다. 라우터가 바뀌면 다시 만든다.

    python docs/api/export_openapi.py

- 주인: 김승욱
- 입력: `backend/main.py`의 앱
- 출력: `openapi.json`

## 명세에 들어가지 않는 경로

2026-11-11 현재 명세는 경로 46개, 동작 51개이며 `backend/`의 경로 데코레이터 55개에서 아래를 뺀 수와 같다.

| 경로 | 이유 |
|---|---|
| `GET /`, `GET /{path:path}`, `POST /{path:path}`, `POST /threads`(`backend/main.py`) | 화면 파일을 내주거나 화면 쪽 오류 응답을 위한 경로라 `include_in_schema=False`로 뺐다 |
| `/mcp` | FastMCP 앱을 마운트한 것이라 OpenAPI에 나오지 않는다. 도구 목록은 `docs/specs/mcp.md` |

경로 수가 코드와 다르면 먼저 `python docs/api/export_openapi.py`를 다시 돌려 파일이 낡았는지 본다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-11 | 김승욱 (Claude Code) | `python docs/api/export_openapi.py`로 명세를 다시 만들었다(42개에서 46개 경로). `POST /admin/signup-requests/by-id/{request_id}/reset-verification`이 더해졌고, `GET /admin/signup-requests` 응답에 `request_id`·`email_verified`, 검토·초기화 응답에 `request_id`가 들어갔다. 손으로 고쳐 두었던 오류 응답 설명(401·403·404·409·503, `/auth/signup/verify`·`/auth/signup/resend`의 설명)은 생성 때 사라지므로 라우트 데코레이터(`description`, `responses`)와 응답 모델로 옮겨 코드에서 만들어지게 했다 | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 명세를 다시 만들어 35개 경로에서 42개 경로로 늘렸다. 더해진 것은 `/admin/signup-requests`(+`/{login_id}/{action}`), `/admin/users`(+`/{login_id}/promote`, `/{login_id}/revoke`), `/auth/signup`, `/me/profile`이다(앞의 명세는 11/9 생성본이라 이 라우터들이 없었다). 앱이 `/me/profile`을 실제 사용자 저장소가 있을 때만 붙여서 `export_openapi.py`가 이 라우터를 직접 붙이도록 고쳤다 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `export_openapi.py`와 `openapi.json` 추가(35개 경로: 로그인, `/chat`, `/threads`, 결정표·승인, 리콜, 변경 감시, `/health` 등. `/mcp`는 명세에 나오지 않음) | [#82](https://github.com/aihuman-7th/proj3-c/pull/82) |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
