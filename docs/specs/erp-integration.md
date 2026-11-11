# Spec — 업무시스템 연동 (REST · SDK · 웹훅) (N-07, PRD P-03)

이 Spec은 업무시스템(구매·배포 승인 등)이 플랫폼을 부르고 플랫폼이 업무시스템을 부르는 길을 한 장에 모은다. 코드에 있는 것만 "있음"으로 적고, 아직 없는 것은 "예정"으로 표시한다(2026-11-11 기준).

## Why

- **페르소나**: 사내 업무시스템(구매·배포 승인)을 만드는 개발자.
- **상황**: 승인 화면 안에서 플랫폼의 인용 답을 보여 주고, 정책이 바뀌어 이미 나간 답이 틀려졌을 때 업무시스템이 그 사실을 받아야 한다.
- **문제**:
  1. 플랫폼 API를 부르려면 로그인·CSRF·SSE 읽기 순서를 알아야 하는데 문서에 한 장으로 모여 있지 않다.
  2. 웹훅 서명을 받는 쪽이 어떻게 검증해야 하는지 보내는 쪽 코드(`backend/graph/recall/webhook.py`)를 읽어야만 알 수 있다.
  3. PRD P-03은 REST·SDK·웹훅·목업을 약속했는데 어디까지 만들었는지 한 곳에 없다.
- **측정 지표**: 아래 AC의 시험 통과(`tests/test_mock_erp_example.py`, `tests/test_recall_webhook.py`)

## Goal

- **해결 목표**: 업무시스템이 REST API로 질문하고, 리콜 웹훅을 서명 검증해 받고, 같은 명세에서 클라이언트를 만들 수 있게 한다.
- **성공 기준**: REST 명세가 코드와 같다(`python docs/api/export_openapi.py`로 다시 만들어 비교) / 웹훅 서명 검증 예제가 보내는 쪽과 같은 서명을 낸다 / 웹훅 실패는 재시도하고 기록한다
- **Out of Scope**: 실제 회사 시스템(배포·구매) 연동, 결재 상신(README "만들지 않는 것"), Confluence·Notion 연결(PRD 범위 밖)

## What

**Happy Path**

REST(업무시스템 -> 플랫폼)
1. `GET /auth/csrf`로 `provena_csrf` 쿠키를 받는다.
2. `POST /auth/login`(헤더 `X-CSRF-Token`)으로 로그인한다. 성공하면 `provena_auth` 쿠키가 생긴다.
3. `POST /chat`(헤더 `X-CSRF-Token`, 본문 `message`, 선택 `thread_id`·`as_of`·`org`)을 부르고 SSE로 답을 읽는다.
4. 그 밖의 경로(`/recalls`, `/approvals`, `/decision-tables/*` 등)는 `docs/api/openapi.json`에 있다(47개 경로, `docs/api/api.md`).

SDK
5. 명세 `docs/api/openapi.json`이 SDK 생성기의 입력이다. 생성기로 만든 Java·Python SDK는 **예정(미착수, 담당·기한 없음)**이다(없음). 지금 있는 것은 손으로 쓴 Python 예제 `mock_erp/python_example/provena_client.py`와 모의 업무시스템 정적 화면 `mock_erp/erp_screen.html`(`mock_erp/serve_screen.py`로 같은 주소에 띄움)이다.

웹훅(두 방향, 서로 다른 것)
6. 수집 -> 플랫폼: `POST /webhooks/regulation-updated`. 서비스 키(`X-Service-Key` 또는 `Authorization: Bearer`, 환경변수 `SERVICE_API_KEY`)가 맞아야 하고 비어 있으면 항상 401. 성공은 202(`accepted`, `event_ids`).
7. 플랫폼 -> 업무시스템: 관리자가 `POST /webhook-subscriptions`로 주소와 `secret_ref`를 등록한다. 리콜 알림이 생기면 그 주소로 POST하고 헤더 `X-Signature: sha256=<HMAC-SHA256(비밀값, 원본 본문 bytes) 16진수>`를 붙인다(`backend/graph/recall/webhook.py`).
8. 받는 쪽은 받은 bytes 그대로 같은 방식으로 서명을 계산해 비교한다(`mock_erp/python_example/webhook_receiver.py`, 틀리면 401).
9. 전송 기록은 관리자가 `GET /webhook-deliveries`로 본다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | `SERVICE_API_KEY`가 비어 있다 | `/webhooks/regulation-updated`는 항상 401 |
| EC-02 | 웹훅 비밀값이 비어 있다 | 로컬 데모(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`)에서만 서명 없이 보낸다. 그 밖에는 보내지 않고 `failed`(`secret_missing`)로 기록 |
| EC-03 | 수신 쪽이 2xx가 아니거나 연결이 안 된다 | 최대 `RECALL_WEBHOOK_MAX_TRIES`번(기본 3), `RECALL_WEBHOOK_BACKOFF_S`(기본 1초)부터 두 배씩 기다려 재시도, 시도마다 기록 |
| EC-04 | 등록 주소가 http·https가 아니다. 배포 환경(strict)에서 http이거나 내부망·메타데이터 주소다 | 주소 검사가 ValueError로 막는다(SSRF 방지, `backend/graph/recall/webhook.py` 주소 검사 함수) |
| EC-05 | 받는 쪽이 본문을 JSON으로 읽고 다시 직렬화해 서명한다 | 서명이 달라져 검증 실패. 받은 원본 bytes로 계산해야 한다 |
| EC-06 | 로그인 없이 `/chat`을 부른다 | 예제 클라이언트는 요청을 보내기 전에 실패한다(`test_chat_without_login_fails_before_sending`) |
| EC-07 | Java(Spring Boot) 목업이 필요하다 | **예정(미착수, 담당·기한 없음)**. `mock_erp/src/`에는 설명 문서만 있고 Java 코드가 없다 |

## How

- 명세 파일: `docs/api/openapi.json`(FastAPI 앱에서 `python docs/api/export_openapi.py`로 생성, 키·DB 불필요). 경로 47개, `/mcp`와 화면 파일 경로는 빠진다(`docs/api/api.md`).
- 보내는 쪽 서명: `backend/graph/recall/webhook.py`의 `sign_payload`·`encode_body`. 받는 쪽 예제: `mock_erp/python_example/webhook_receiver.py`(같은 서명 방식).
- 예제 클라이언트: `mock_erp/python_example/provena_client.py`(로그인 -> CSRF -> `/chat` SSE).
- 웹훅 상세 형식과 알림 본문(`RecallNotice`)은 `docs/specs/recall.md`, MCP 서버(`/mcp`, 읽기 전용 도구 6개)는 `docs/specs/mcp.md`가 정한다. 이 문서는 그 둘을 다시 정하지 않고 연동 관점에서 모은 것이다.
- 환경변수: `SERVICE_API_KEY`, `RECALL_WEBHOOK_SECRET`(구독별 `RECALL_WEBHOOK_SECRET_<이름>`), `RECALL_WEBHOOK_MAX_TRIES`, `RECALL_WEBHOOK_BACKOFF_S`, `RECALL_WEBHOOK_TIMEOUT_S`(`.env.example`).
- 예정(미착수, 담당·기한 없음): SDK 자동 생성(Java·Python), Java(Spring Boot) 업무시스템 목업. 근거와 현재 상태는 `mock_erp/mock_erp.md`.

## AC (Given-When-Then)

**AC-01 · 예제 클라이언트가 로그인하고 질문한다**
- GIVEN: 플랫폼(또는 시험용 가짜 서버)이 떠 있고 계정이 있다
- WHEN: `ProvenaClient`가 CSRF를 받고 로그인한 뒤 `/chat`을 부른다
- THEN: SSE 이벤트를 읽어 답을 얻는다(`tests/test_mock_erp_example.py::test_login_csrf_chat_flow_against_local_fake_server`)

**AC-02 · 웹훅 서명이 보내는 쪽과 받는 쪽에서 같다**
- GIVEN: 같은 비밀값과 같은 본문 bytes
- WHEN: 보내는 쪽과 받는 쪽 예제가 각각 서명을 계산한다
- THEN: 값이 같고, 본문·비밀값·헤더 형식이 틀리면 검증이 실패한다(`tests/test_mock_erp_example.py::test_signature_matches_platform_sender`, `test_signature_rejects_tampered_body_wrong_secret_and_bad_header`)

**AC-03 · 웹훅은 실패하면 재시도하고 기록한다**
- GIVEN: 구독 주소가 등록되어 있다
- WHEN: 수신 쪽이 오류를 돌려준다
- THEN: 최대 시도 횟수까지 재시도하고 시도마다 `webhook_deliveries`에 남는다(`docs/specs/recall.md` AC-03, `tests/test_recall_webhook.py`)

**AC-04 · SDK와 Java 목업은 만들기 전까지 "예정"으로 남는다**
- GIVEN: 생성기를 고르거나 돌린 기록이 없고 `mock_erp/src/`에 Java 코드가 없다
- WHEN: 이 Spec이나 README가 연동 범위를 설명한다
- THEN: SDK와 Java 목업은 "예정"으로 적고 만들었다고 쓰지 않는다
