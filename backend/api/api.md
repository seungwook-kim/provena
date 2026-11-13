# backend/api/ : 서비스 API 라우터

## 이 폴더가 하는 일

화면과 업무시스템이 부르는 REST·SSE 라우터와 공통 규약을 둔다(SDD 4-4). 오류 응답 규약(`errors.py`), 요청 ID와 요청 로그 미들웨어(`middleware.py`), 사용자별 대화 목록 저장소(`threads.py`), 채팅(`POST /chat`)·대화 목록(`/threads`)·장기 기억(`/me/memory`) 라우터(`routes.py`), 답변 리콜 라우터(`recalls.py`, `/recalls`), 변경 감시 라우터(`changes.py`, `GET /changes`)가 있다. 엔드포인트는 연결만 하고 로직은 `backend/graph/`·`backend/services/`에 둔다.

- 주인: 김승욱
- 입력: 화면·업무시스템 요청(로그인 쿠키, CSRF)
- 출력: JSON 응답, SSE 이벤트(`token`, `citation`, `approval_request`, `error`, `done`), 오류 규약 `{"error": {"code", "message", "request_id"}}`

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-13 | 박진형 (jinyeong-731) | `recalls.py` 날짜 칸 점검(조장 11/13 재확인 #3 같은 유형): `digest/flush`의 `day`, `impact-preview`의 `old_version_date`·`new_version_date`(changes·pages 둘 다), `POST /webhooks/regulation-updated`의 날짜 칸에 `2026-02-30`·`2025-02-29`·전각 숫자를 보내면 모두 200(웹훅은 202)으로 받고 결과가 조용히 틀렸음 → 이제 422 `validation_error`(`ChatRequest._real_date`와 같은 규칙, 입력값은 응답에 담지 않음). 이유: `notice.py`가 날짜를 문자열로 비교해 전각 숫자면 지난 답변이 전부 영향받음으로 잡히고, `digest/flush`는 없는 날짜가 `recall_digests.day`에 되돌릴 수 없게 저장되고 알림이 보냄 처리되며, 웹훅은 섹션을 못 읽어 사용자에게 가짜 "본문을 찾지 못했습니다" 검토 알림이 나감 | 미정 |
| 2026-11-13 | 박진형 (jinyeong-731) | `routes.py` `ChatRequest.as_of`에 실제 날짜 검사 추가(조장 11/13 재확인 #3): `2026-02-30`·`2026-13-45`처럼 형식만 맞는 날짜는 SSE error가 아니라 공통 422 `validation_error`. 원인은 검색기 `rag/retrieve/search.py` `check_query`의 `date.fromisoformat` ValueError. 시험 `tests/test_api_chat.py` | 미정 |
| 2026-11-11 | 박진형 (jinyeong-731) | `changes.py`에 `POST /admin/sync` 추가(C-14): 관리자·CSRF, 기본 `dry_run=true`는 계획만 돌려주고 `dry_run=false`는 프로세스를 띄우지 않고 501 `manual_sync_not_supported`를 낸다. `errors.py` 오류 표에 `manual_sync_not_supported`(501) 추가. 시험 `tests/test_api_changes.py`의 `test_manual_sync_*` 3개. 실제 수집 실행은 501 그대로 두고 정시 수집 workflow(`handbook-sync`)를 쓴다(2026-11-12 조장 리뷰(#132)에서 확정) | #132·#135 |
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
