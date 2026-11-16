# 실패 경로 확인: main `9bc7d587` 이미지 (provena-api-00181-zub, 2026-11-17)

체크포인트 D11 "실패 경로 점검(키 한도, 0건, 시간 초과)과 사용자 안내"를 현재 main 코드(`9bc7d587`, 이미지 `sha256:1a49f9e3…`, 트래픽 0% 판 `provena-api-00181-zub`)에서 다시 확인한 기록이다. 이전 확인은 `provena-api-00075-5zk`(커밋 `eb7516ca`)에서 했다([failure_paths_after_fix_20261116/](../failure_paths_after_fix_20261116/)). 방법과 도구는 그때와 같고(일반 평가용 계정 B, 평가셋 v2 1번 질문, `/chat` SSE 응답의 코드와 문구를 서버 상수와 대조), 운영 트래픽은 시작부터 끝까지 `provena-api-00178-max` 100%였다.

## 결과

| 경로 | 재현 조건 | 판 | 시각(KST) | 기대 코드 | 받은 응답 | 사용자에게 보이는 문구 | 판정 |
|---|---|---|---|---|---|---|---|
| 검색 0건 | 없는 조직(`org=no-such-org-1116`)으로 질문 | `provena-api-00181-zub`(기존 0% 태그 `c1117b`) | 03:53:56 | `no_results` | HTTP 200, SSE `done`, kind `refuse`, code `no_results`, 거절 사유 `no_evidence`, 3.8초 | "핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다." | 통과(문구 일치) |
| 키 비용 상한 | 00181 설정에 `LLM_COST_CAP_USD=0.0001`만 더한 0% 판 | `provena-api-fpcap1117`(태그 `fpcap`, 같은 이미지) | 03:54:48 | `limit_exceeded` | HTTP 200, SSE `error`, code `limit_exceeded`, 3.6초 | "이번 질문의 LLM 비용 상한에 닿아 답을 멈췄습니다. 질문을 더 짧고 구체적으로 줄이거나 여러 개로 나누어 다시 물어봐 주세요." | 통과(문구 일치) |
| 시간 초과 | 00181 설정에 `LLM_DEADLINE_S=0.01`, `LLM_MAX_RETRIES=0`만 더한 0% 판 | `provena-api-fptime1117`(태그 `fptime`, 같은 이미지) | 04:00:41 | `timeout` | HTTP 200, SSE `error`, code `timeout`, 0.5초 | "답을 만드는 시간이 제한을 넘어 중단했습니다. 질문을 더 짧게 줄이거나 여러 개로 나누어 잠시 뒤 다시 물어봐 주세요." | 통과(문구 일치) |
| 제공자 한도·잔액 부족 | 운영에서 재현하지 않음(요청 한도·잔액 부족을 안전하게 만들 방법과 시험용 스위치가 없음) | - | - | `provider_limit` | - | 서버 문구 `MSG_PROVIDER_LIMIT`(`backend/api/routes.py:76`) | 코드와 단위 시험으로만 확인: `backend/api/routes.py:98-108` `chat_error`, `PROVIDER_LIMIT_ERRORS`(81행), `tests/test_api_chat.py:157`, `:188` |

- 화면 문구: 웹 채팅은 서버가 보낸 문구를 그대로 보여 주고, 서버 문구가 빠졌을 때만 `web/react-app/src/lib/chat-service.js`의 `CHAT_ERROR_FALLBACK`을 쓴다. 대체 문구는 `limit_exceeded`, `provider_limit`, `timeout` 세 가지 모두 서버 문구와 같다(`failure_paths.json`의 `web_fallback_equals_server_message`). 브라우저 화면 캡처는 하지 않았다. 태그 주소의 채팅 화면은 로그인이 필요하고, 이 확인에서는 평가용 계정 비밀번호를 브라우저에 입력하지 않기로 했기 때문이다. 화면 쪽 근거는 위 API 응답과 문구 대조다.
- 판정 단계(judge)는 서비스 값 `LLM_DEADLINE_BY_TASK=judge=12`(`backend/graph/service_profile.py:109`)라 시간 상한 0.01초를 받지 않는다. 시간 초과는 그 앞 단계의 LLM 호출에서 났다(0.5초에 끝남).
- 비용: 0.000747달러(검색 0건 1건만 LLM 호출, 나머지 둘은 호출 전·첫 호출에서 멈춤).

## 판 관리 (`run_state.json`)

- 시작 전 확인: 운영 트래픽 `provena-api-00178-max` 100%, 서비스 템플릿이 `provena-api-00181-zub`(이미지 `sha256:1a49f9e3…`)이고 세 변수가 템플릿에 없음.
- 임시 판은 템플릿에 변수만 더해 `--no-traffic`으로 만들었고 태그 주소로만 열었다. 쓴 뒤 그 태그만 뗐다(`--remove-tags`, 다른 태그는 건드리지 않음). 시작과 끝의 태그 목록은 `c1117`, `c1117b`, `fix1117`, `lf1116`, `p1116`으로 같다.
- 끝난 뒤 템플릿의 세 변수를 지웠다. 이때 0% 판 `provena-api-fprest1117`이 하나 생겼다. 임시 판 `provena-api-fpcap1117`, `provena-api-fptime1117`은 지웠다. `provena-api-fprest1117`은 "가장 최근에 만든 판은 직접 지울 수 없다"(`FAILED_PRECONDITION`)로 지워지지 않아 트래픽 0%, 태그 없이 남아 있다. 이 판은 `provena-api-00181-zub`와 이미지 digest, 환경 변수(이름·값·비밀 참조), CPU·메모리, 최대 인스턴스, 동시 요청 수가 모두 같다(2026-11-17 04:03 KST 대조). 다음 배포가 생기면 그 뒤에 지울 수 있다.
- 운영 트래픽은 끝에도 `provena-api-00178-max` 100%였다.

## 파일

| 파일 | 내용 |
|---|---|
| `failure_paths.md`, `failure_paths.json` | 경로별 결과 표, 서버 문구, 화면 대체 문구 대조, 합계 비용 |
| `probe_zero_results.json`, `probe_cost_cap.json`, `probe_timeout.json` | 경로별 요청 조건과 응답(코드, 문구, 걸린 시간, request id) |
| `run_state.json` | 시작·끝 트래픽과 태그, 임시 판 이름과 이미지, 지운 판, 남은 판과 설정 대조 |
