# 실패 경로 운영 확인 (2026-11-16)

운영 판 `provena-api-00068-drb`, 커밋 `5a8c6527`. 계정 B, 질문은 평가셋 v2 1번. 0% 판은 태그 주소로 한 번에 하나만 열고 닫았다.

| 경로 | 재현 조건 | 기대 코드 | 결과 | 받은 코드 | 문구 일치 | 거절 사유 | 판 | 비용(달러) |
|---|---|---|---|---|---|---|---|---|
| cost_cap | 0% 판 LLM_COST_CAP_USD=0.0001 | `limit_exceeded` | 통과 | limit_exceeded | 통과 | - | provena-api-00081-qaz | 0.0 |
| zero_results | 운영 판, org=no-such-org-1116 | `no_results` | 통과 | no_results | 통과 | no_evidence | provena-api-00068-drb | 0.00056217 |
| timeout | 0% 판 LLM_DEADLINE_S=0.01, LLM_MAX_RETRIES=0 | `timeout` | 실패 | internal_error | 실패 | - | provena-api-00083-gum | 0.0 |
| provider_limit | 운영 재현 안 함(요청 한도·잔액 부족은 안전하게 만들 수 없음, 시험용 스위치 없음) | `provider_limit` | 코드·단위 시험으로만 확인 | - | - | - | - | - |

화면 대체 문구(`chat-service.js` CHAT_ERROR_FALLBACK)와 서버 문구 일치: limit_exceeded 통과, provider_limit 통과, timeout 통과

합계 비용 0.000562달러. provider_limit 근거: backend/api/routes.py:97-108 chat_error; backend/api/routes.py:76-84 MSG_PROVIDER_LIMIT·PROVIDER_LIMIT_*; tests/test_api_chat.py:142-157 test_provider_limit_and_timeout_get_their_own_code_and_next_action
