# mock_erp/ : 업무시스템 목업

## 이 폴더가 하는 일

업무시스템(구매·배포 승인)이 플랫폼을 부르는 시연. 지금 있는 것은 Python 예제와 OpenAPI 명세이고, Spring Boot 목업과 SDK 자동 생성은 만들지 않았다(아래 표). 리콜 웹훅 서명을 검증하는 예제가 있다.

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
| Java(Spring Boot) 업무시스템 목업 | 만들지 않음 | `mock_erp/src/`에는 설명 문서만 있고 Java 코드가 없다. 이번 가산 보강 작업의 요청 범위(문서 정정, 자동화, 명세·Python 예제, Skill 비교)에 들어 있지 않아 시작하지 않았다. 일정 부족이나 기술적 장애로 판단한 기록은 없다 |
| 명세에서 SDK(Java·Python) 자동 생성 | 만들지 않음 | 생성기를 고르거나 돌린 적이 없다. 이번 요청 범위 밖이라 시작하지 않았다. 입력이 될 `docs/api/openapi.json`은 준비됐다 |

PRD P-03(`docs/PRD.md` 176줄)이 약속한 "자동 생성 SDK(Java·Python)"와 "Java 목업"은 위 두 줄이 남은 부분이다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | 만든 것과 만들지 않은 것 표 추가: OpenAPI 명세·Python 예제는 만들었고, Java(Spring Boot) 목업과 SDK 자동 생성은 이번 요청 범위 밖이라 만들지 않았음을 사실대로 적음 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
