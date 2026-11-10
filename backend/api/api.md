# backend/api/ : 서비스 API 라우터

## 이 폴더가 하는 일

화면과 업무시스템이 부르는 REST·SSE 라우터와 공통 규약을 둔다(SDD 4-4). 오류 응답 규약(`errors.py`), 요청 ID와 요청 로그 미들웨어(`middleware.py`), 사용자별 대화 목록 저장소(`threads.py`), 채팅(`POST /chat`)·대화 목록(`/threads`)·장기 기억(`/me/memory`) 라우터(`routes.py`), 답변 리콜 라우터(`recalls.py`, `/recalls`), 변경 감시 라우터(`changes.py`, `GET /changes`)가 있다. 엔드포인트는 연결만 하고 로직은 `backend/graph/`·`backend/services/`에 둔다.

- 주인: 김승욱
- 입력: 화면·업무시스템 요청(로그인 쿠키, CSRF)
- 출력: JSON 응답, SSE 이벤트(`token`, `citation`, `approval_request`, `error`, `done`), 오류 규약 `{"error": {"code", "message", "request_id"}}`

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) `routes.py`: `/chat` done 이벤트에 단계별 비용·Voyage 토큰(`cost_by_step`, `embed_tokens` 등)과 거절·되묻기의 `refuse_stage`·`refuse_reason`을 더함. 기존 칸은 그대로이고 항상 켬(커밋 0a15fc2) | #119 |
| 2026-11-10 | 김승욱 (기록: 박진형) | `routes.py` 수정: 응답 시간 p95 단축 코드 스위치(`CHAT_FINAL_FROM_STREAM` 등, 모두 기본 꺼짐)에 맞춰 `/chat` 처리를 고침 (커밋 acd9a45) | #110 (보충) |
| 2026-11-09 | 김승욱 (기록: 박진형) | `GET /changes`의 응답 칸을 pydantic 모델로 적어 OpenAPI에 `total`·`counts`가 보이게 함 (커밋 a118f4d) | #82 (보충) |
| 2026-11-09 | 김승욱 (기록: 박진형) | `GET /changes` 응답에 `total`·`counts` 추가(`changes.py`) (커밋 f607ab3) | #80 (보충) |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충) 리콜 알림·변경 감시 라우터 `recalls.py`·`changes.py` 추가 (커밋 7fb294b) | #72 |
| 2026-11-09 | 박진형 | 새로고침·대화 목록 클릭 뒤 빈 화면 수정: 대화 상세에 이력(`messages`)을 담아 줌 (커밋 c90f210) | #71 |
| 2026-11-06 | 김승욱 (기록: 박진형) | (보충) D6 API 추가: `/chat`(SSE), `/threads`, `/me/memory`, 오류 규약, 요청 ID 미들웨어 (커밋 4ae8be7) | #60 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
