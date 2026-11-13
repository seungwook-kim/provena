# mock_erp/ : 업무시스템 목업

## 이 폴더가 하는 일

업무시스템(구매·배포 승인)이 플랫폼을 부르는 시연. 지금 있는 것은 Python 예제와 OpenAPI 명세이고, Spring Boot 목업은 만들지 않았다(아래 표). SDK는 `sdk/`에 자동 생성했다. 리콜 웹훅 서명을 검증하는 예제가 있다.

- 주인: 김승욱
- 입력: 플랫폼 API, 웹훅
- 출력: 사전 확인 화면

## 만든 것과 만들지 않은 것 (2026-11-09 기준)

| 항목 | 상태 | 비고 |
|---|---|---|
| REST API 정적 명세 | 만듦 | `docs/api/openapi.json`, 내보내기 `python docs/api/export_openapi.py`(키·DB 없이 앱 객체에서 생성) |
| Python 예제: 로그인, CSRF, `/chat` SSE 읽기 | 만듦 | `mock_erp/python_example/provena_client.py` |
| Python 예제: 리콜 웹훅 서명 검증 | 만듦 | `mock_erp/python_example/webhook_receiver.py`, 서명 방식은 `backend/graph/recall/webhook.py`와 같음 |
| 예제 시험 | 만듦 | `tests/test_mock_erp_example.py`(외부 네트워크 없음) |
| 모의 업무시스템 화면(정적 HTML) | 만듦 | `mock_erp/erp_screen.html`, 띄우기 `mock_erp/serve_screen.py`, 시험 `tests/test_mock_erp_screen.py` |
| Java(Spring Boot) 업무시스템 목업 | 예정(미착수, 담당·기한 없음) | `mock_erp/src/`에는 설명 문서만 있고 Java 코드가 없다. 이번 가산 보강 작업의 요청 범위(문서 정정, 자동화, 명세·Python 예제, Skill 비교)에 들어 있지 않아 시작하지 않았다. 일정 부족이나 기술적 장애로 판단한 기록은 없다 |
| 명세에서 SDK(Java·Python) 자동 생성 | 만듦(2026-11-12) | openapi-generator 7.26.0, 산출물 `mock_erp/sdk/`, 재생성 `bash mock_erp/sdk/generate.sh`, 설명 `mock_erp/sdk/sdk.md`. Python은 `/health` 호출을 로컬 서버에서 확인, Java는 컴파일만 확인(PR 노트) |

PRD P-03(`docs/PRD.md` 176줄)이 약속한 것 가운데 "Java 목업"만 남았다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-13 | 박진형 (jinyeong-731) | SDK README의 깨진 상대 링크 231개(Java 142·Python 89, 가리키는 `docs/*.md`가 `apiDocs·modelDocs=false`로 안 만들어져 404) 정리(놓친 것 C-26): `sdk/strip_dead_links.py`가 없는 파일로 가는 링크를 글자만 남기고 풀고 `generate.sh` 끝에서 부름. 링크 검사 231 → 0, SDK 소스는 안 건드림 | 미정 |
| 2026-11-12 | 박진형 (jinyeong-731) | `sdk/` 추가(놓친 것 C-15·P-07): openapi-generator 7.26.0로 `docs/api/openapi.json`에서 Python·Java SDK 생성, 재생성 스크립트와 `sdk/sdk.md`. 위 표의 SDK 줄을 '만듦'으로 고침 | #135 |
| 2026-11-11 | 박진형 (jinyeong-731) | 모의 업무시스템 화면 프록시(`serve_screen.py`) 보강(검증 지적): `/`로 시작하지 않는 경로는 400으로 거절(`upstream + path`가 다른 호스트를 가리키던 것), 3xx는 따라가지 않고 그대로 돌려줌, API로는 `provena_` 쿠키만 넘김. 시험 2개 추가·1개 보강 | 미정 |
| 2026-11-11 | 박진형 (jinyeong-731) | 모의 업무시스템 화면 추가(놓친 것 H-07): `erp_screen.html`(HTML·JS만, 빌드·npm 없음)이 로그인(`/auth/login`), 결정표 목록·실행(`/decision-tables`, `/decision-tables/run`), 웹훅 구독·전달 기록(`/webhook-subscriptions`, `/webhook-deliveries`)을 부른다. 화면 머리에 '모의 업무시스템'을 표시하고 입력란 값은 예시로 적었다. API에 CORS가 없어 `serve_screen.py`(표준 라이브러리 프록시)가 화면과 API를 같은 주소로 내준다: `PROVENA_BASE_URL=http://localhost:8000 python mock_erp/serve_screen.py` 뒤 `http://localhost:8765/`. 시험 `tests/test_mock_erp_screen.py` 3개(표시 문구, 화면이 부르는 경로가 `backend/` 라우트에 있는지, 프록시의 쿠키·CSRF 전달). 리콜 웹훅 수신은 브라우저가 못 하므로 `python_example/webhook_receiver.py`가 맡는다. 화면을 실제 서버에 붙여 본 확인은 하지 않았다 | 미정 |
| 2026-11-11 | 박진형 (jinyeong-731) | Java 목업과 SDK 자동 생성 칸의 "만들지 않음"을 `docs/specs/erp-integration.md`와 같은 "예정(미착수, 담당·기한 없음)"으로 통일(N-07 검증 후속). 내용은 그대로 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 만든 것과 만들지 않은 것 표 추가: OpenAPI 명세·Python 예제는 만들었고, Java(Spring Boot) 목업과 SDK 자동 생성은 이번 요청 범위 밖이라 만들지 않았음을 사실대로 적음 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
