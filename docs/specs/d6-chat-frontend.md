# D6 채팅 프론트엔드 및 API 어댑터 Spec

> 상태: 구현 후 보완 문서
>
> 이 문서는 Spec-first 원칙에 따라 구현 전에 작성된 원본 Spec이 아니다. 구현된 D6 프론트엔드 동작을 기준으로 계약과 범위를 명시한 보완 문서다. 작성 당시(2026-11-07)에는 백엔드 계약이 미확정이었으나 PR #60이 머지돼(`docs/worklog.md:228-230`) 백엔드 계약은 `docs/SDD.md` 4-4(`/chat`·`/threads` 표)와 6장 이벤트 표가 정한다. 아래 "미확정" 표기는 작성 당시 기록이며 각 곳에 현재 값을 덧붙였다.
>
> 기존 기능 목록과 전체 제품 기준은 [`docs/SPEC.md`](../SPEC.md)를 참조한다. 이 문서는 D6 React 채팅 화면과 프론트 어댑터의 세부 동작만 다룬다.

## Why

- **사용자**: 로그인한 사용자가 Provena의 실제 채팅 API 또는 데모 모드로 정책·런북 질문을 주고받는 사용자.
- **상황**: 기존 프리뷰 화면을 유지하면서 실제 백엔드의 대화 목록, 스트리밍 응답, 인용, 승인 대기 상태를 React 화면에 연결해야 한다.
- **문제**:
  1. 데모 어댑터와 실제 API 어댑터를 화면에서 구분해 직접 다루면 호출 계약이 분산된다.
  2. SSE 이벤트가 여러 청크로 나뉘거나 ping 주석을 포함할 수 있어 단순 청크 단위 처리가 안전하지 않다.
  3. 승인 대기 중인 대화만 입력을 막아야 하며, 다른 대화나 새 대화까지 잠기면 안 된다.
  4. (작성 당시) `/threads`와 SSE 이벤트의 백엔드 계약이 PR #60과 완전히 검증되지 않았다. 지금은 PR #60 머지로 계약이 확정됐다(`backend/api/routes.py` `/chat`, `/threads`, `docs/SDD.md` 4-4).
- **측정 기준**: 프론트 단위 테스트와 production build가 통과하고, 실제 백엔드 통합 테스트에서 계약이 일치하는지 확인한다. (PR #60은 머지됐다. 화면과 실제 백엔드를 브라우저로 이은 통합 검증 기록은 이 spec·`web/web.md`에서 찾지 못했다. 배포 서비스의 API 수준 실측은 `EVAL_REPORT.md` 6장·`docs/deliverables/ai_tools_log.md` 11/9 행에 있다.)

## Goal

- 채팅 화면이 `createApiChatAdapter`와 기존 preview adapter를 동일한 서비스 경계로 사용한다.
- `/threads` 응답의 확인된 필드만 UI 형식으로 변환한다.
- `/chat` SSE의 확인된 이벤트를 누락·중복 없이 처리하고 중단 요청을 지원한다.
- 현재 대화에 승인 대기 메시지가 있으면 해당 대화의 입력과 전송만 비활성화한다.

### Out of Scope

- 백엔드 라우트·스키마·이벤트 계약의 변경
- 승인 완료·거절을 프론트가 임의로 감지하거나 승인 상태를 해제하는 기능
- 관리자 승인 화면과 승인 결정 API
- 회원가입·로그인·Google OAuth의 동작 변경
- PR #60의 변경을 이 브랜치에 병합하는 작업

## What

### Happy Path

1. 라우팅이 실제 모드이면 `createApiChatAdapter`를 선택하고, 데모 모드이면 기존 preview adapter를 선택한다.
2. 실제 어댑터가 `GET /threads`를 호출한다.
3. 확인된 `thread_id`, `title`, `updated_at`을 각각 UI의 `id`, `title`, `lastActivityAt`으로 변환한다.
4. 사용자가 메시지를 보내면 `POST /chat` 요청을 시작하고, 새 대화에서 `thread_id`가 `null`이면 요청 JSON에서 해당 필드를 생략한다.
5. 응답 스트림은 `event:`와 `data:` 필드를 읽고, 빈 줄을 이벤트 경계로 처리한다. 여러 청크에 나뉜 이벤트를 누적하며 `:`로 시작하는 ping 주석은 무시한다.
6. 이벤트에 따라 토큰, citation, 승인 대기, 오류, 종료 상태를 현재 메시지에 반영한다.
7. 사용자가 중단하면 `AbortController`로 현재 스트림을 취소하고 기존 `stopMessage` 계약을 유지한다.

### 이벤트 처리

프론트는 현재 다음 이벤트 이름을 처리한다.

| 이벤트 | 현재 프론트 처리 |
|---|---|
| `token` | 응답 텍스트에 data의 토큰을 누적 |
| `citation` | 기존 citation 목록과 중복되지 않게 인용을 반영 |
| `approval_request` | 메시지 상태를 `approval`로 표시하고 승인 대기 UI를 노출 |
| `error` | 일반 오류와 `data.code === "limit_exceeded"`를 구분할 수 있는 오류 상태로 처리 |
| `done` | 기본 상태는 `done`, `data.code === "no_results"`이면 `no-evidence`로 처리하고 `data.refuse_reason`(거절 사유 코드)을 메시지에 담는다. 사유가 근거 부족(`no_evidence`, `unsupported`, `citation_check`)일 때만 "질문을 더 구체적으로 쓰거나 다른 표현으로 다시 물어봐 주세요." 안내를 붙인다(H-34. 대화 이력의 거절 답도 `refuse_reason`으로 같게 판정, 사유가 없으면 붙이지 않음); attribution이 있으면 기존 citation과 중복 없이 출처에 반영 |

위 표는 현재 프론트 구현의 처리 기준이다. 백엔드가 각 이벤트의 정확한 `data` 중첩 위치, attribution의 상세 타입, 승인 완료·거절 이벤트를 공식적으로 확정했는지는 확인해야 한다. 이벤트 `data` 구조는 `docs/SDD.md` 6장 표(`backend/api/routes.py`·`backend/graph/stream.py`)가 정본이다.

### Edge Cases

| # | 상황 | 처리 기준 |
|---|---|---|
| EC-01 | SSE 이벤트가 여러 네트워크 청크로 분할됨 | 불완전한 줄과 이벤트를 버퍼에 보관하고 빈 줄을 만났을 때만 dispatch |
| EC-02 | `:`로 시작하는 SSE ping 주석 | 이벤트로 dispatch하지 않고 무시 |
| EC-03 | `data:`가 여러 줄로 옴 | SSE 이벤트 data 규칙에 맞춰 누적한 뒤 JSON 파싱을 시도 |
| EC-04 | 새 대화의 `thread_id`가 `null` | 요청 body에서 `thread_id` 키를 생략 |
| EC-05 | `/threads` 항목에 마지막 답만 있음 | 목록 항목을 만들 수 있는 확인된 식별자·제목·갱신 시각만 사용하고, 없는 상세 메시지는 추측하지 않음 |
| EC-06 | 현재 대화가 승인 대기 | 현재 대화의 입력·전송만 비활성화; 다른 대화는 사용 가능 |
| EC-07 | 대화를 전환하거나 새 대화를 생성 | 선택된 대화 기준으로 승인 대기 상태를 다시 계산하고 이전 대화의 차단 상태를 재사용하지 않음 |
| EC-08 | 승인 완료·거절 이벤트 계약이 확인되지 않음 | 임의로 입력을 다시 활성화하지 않음; 백엔드 계약 확인 필요 |
| EC-09 | API 응답 최상위가 array인지 object인지 불명확 | 확인된 필드만 처리하고 새로운 응답 스키마를 추측해 만들지 않음; PR #60 확인 필요 |
| EC-10 | 답 본문 `[n]`이 근거 목록 순서와 달라 `[1][3][2]`처럼 나옴(H-32) | 화면이 본문에 처음 나온 순서대로 `[n]`을 다시 매기고 근거 칩·패널 순서도 같이 바꿈(`renumberByAppearance`). 서버 값은 그대로이고 본문에 없는 근거는 뒤에 둠. 생성 중 답은 건드리지 않음 |
| EC-11 | 같은 제목의 대화가 목록에 둘 이상(같은 질문을 새 대화로 다시 물음, H-32) | 서버는 대화마다 `thread_id`가 달라 중복 버그가 아님. 목록에 지난 날짜에도 `YYYY.MM.DD HH:MM`으로 시각을 붙여 구분 |
| EC-12 | 답을 받는 중 다른 메뉴로 이동(화면이 내려가 연결을 끊음) | 서버는 끊겨도 답을 끝까지 만들어 저장한다(`backend/api/routes.py` `iterate_in_one_thread`). 끊은 대화 id를 탭 안(`sessionStorage`)에 남기고, 채팅으로 돌아오면 그 대화를 열어 서버 상태가 `running`인 동안 3초마다(최대 3분) 다시 받는다. 그동안 그 대화의 입력은 잠근다 |
| EC-13 | 새 말풍선·답 도착 때 사용자가 위로 올려 읽는 중 | 맨 아래에서 80px 안이면 따라 내려가고, 그 밖이면 스크롤 위치를 바꾸지 않는다. 질문을 보내거나 대화를 열면 맨 아래로 간다 |
| EC-14 | 여러 줄 질문 | 입력칸이 글에 맞춰 최대 208px(약 8줄)까지 늘어나고, 그 뒤로는 칸 안에서 스크롤한다 |
| EC-15 | 대화를 연 채로 새로고침 | 연 대화 id를 탭 안(`sessionStorage`)에 남겨, 새로고침 뒤 그 대화를 서버에서 다시 받아 연다. 목록에 없는 id(지워졌거나 다른 계정)는 무시하고 새 대화 화면을 보인다. "+ 새 대화"를 누르면 지운다 |
| EC-16 | 새 대화에서 첫 질문을 보내고 답을 기다림 | 답은 그래프가 끝난 뒤 한 번에 오므로(`backend/graph/stream.py`) 그때까지 대화 id가 없다. 화면이 보낸 질문과 확인 중 말풍선을 먼저 그리고, 답이 오면 서버 대화로 바꾼다 |

## How

### 프론트 서비스 경계

- `web/react-app/src/lib/chat-service.js`
  - `createApiChatAdapter`가 실제 API 호출을 캡슐화한다.
  - `listThreads()`와 `getThread()`가 UI가 사용하는 thread 형식으로 변환한다.
  - `streamChatMessage()`가 이벤트별 메시지 상태를 갱신한다.
  - `stopMessage()`는 스트림 중단 계약을 유지한다.
- `web/react-app/src/lib/api.js`
  - HTTP 요청, 오류 변환, `POST /chat` 스트림 획득과 SSE 파싱을 담당한다.
  - `body.error?.message`, `body.error?.code`를 우선 사용하고 기존 `body.detail` 처리도 유지한다.
  - `event:`와 `data:`를 청크 경계와 무관하게 처리한다.
- `web/react-app/src/pages/DemoChatPage.jsx`
  - `approval_request`로 메시지 상태가 `approval`이면 고정 안내 “담당자 승인을 기다리고 있습니다. 승인 단계가 끝나면 결과가 이 대화에 붙습니다. 이 화면으로 다시 돌아오거나 새로고침하면 보입니다. 다른 질문은 새 대화에서 해 주세요.”를 표시한다(2026-11-12, 승인 뒤 결과는 같은 대화에 남는다: `backend/graph/departments/review.py` finalize, 화면은 창으로 돌아올 때 다시 받는다).
  - 답을 기다리는 동안 “근거를 찾고 답을 확인하는 중입니다 · N초 지남”을 표시한다. 서버는 그래프가 끝난 뒤에만 답을 보내므로(`backend/graph/stream.py`) 단계 대신 지난 시간만 보여 준다(2026-11-12).
  - 출처·라이선스 안내는 서버 `attribution.modified`가 true이면 “원문을 요약·재서술함(수정됨)”을 함께 표시한다(TEAM_GUIDE 7장 수정 여부, 2026-11-12).
  - 현재 대화의 승인 대기 상태에 한해 입력과 전송을 비활성화한다.
  - 데모/실제 adapter 선택, 라우팅, 스트리밍, 중단 기능을 유지한다.
### 확인된 API 필드와 미확정 계약

현재 프론트가 기준으로 삼는 필드는 다음과 같다.

| 호출 | 확인된 프론트 기준 | 아직 확정하지 않은 항목 |
|---|---|---|
| `GET /threads` | `thread_id`, `title`, `updated_at` → `id`, `title`, `lastActivityAt` | 확정(작성 당시 미확정): 최상위는 `{"threads": [{thread_id, title, status, created_at, updated_at}]}`(`backend/api/routes.py`의 `list_threads`, SDD 4-4). 목록에는 메시지가 없다 |
| `GET /threads/{id}` | thread 상세를 UI 대화로 변환 | 확정: 최상위에 thread 필드와 `messages`(질문 체크포인트에서 되살린 대화 이력)를 평평하게 둔다(`backend/api/routes.py`의 `get_thread`) |
| `POST /chat` | JSON 요청 및 text/event-stream 처리 | 확정: 요청 `{thread_id?, message, as_of?, org?}`, 이벤트 `AgentEvent`(`{type, thread_id, data}`), 승인 대기 중 새 질문은 409 `approval_pending`(`backend/api/routes.py`의 `chat`이 `pending_approval`을 검사, SDD 6장) |

백엔드에서 확인되지 않은 내용을 새 스키마로 만들지 않는다. 위 표의 "확정" 값은 PR #60 머지 뒤 백엔드 코드에서 확인한 값이다.

### 의존 파일·환경변수

| 구분 | 이름 | 쓰는 곳 |
|---|---|---|
| 파일 | `web/react-app/src/lib/chat-service.js`, `web/react-app/src/lib/api.js` | 위 "프론트 서비스 경계"의 실제 API adapter, 요청·SSE 처리 |
| 파일 | `web/react-app/src/pages/DemoChatPage.jsx` | 대화 화면, 승인 대기 표시 |
| 파일 | `web/react-app/vite.config.js` | 개발 서버가 `/auth`, `/me` 등을 백엔드로 넘기는 프록시 |
| 빌드 변수 | `VITE_API_BASE_URL` | API 기본 주소. 비우면 같은 origin(`src/lib/api.js:1`, `web/react-app/README.md`) |
| 빌드 변수 | `VITE_API_PROXY_TARGET` | 개발 서버 프록시 대상. 비우면 Docker 안에서는 `http://host.docker.internal:8000`, 아니면 `http://127.0.0.1:8000`(`vite.config.js`의 `proxyTarget`) |
| 빌드 변수 | `VITE_ENABLE_MOCK_SESSION` | `'true'`면 로그인 없이 시험용 세션을 쓴다(`SessionProvider.jsx`의 `isMockSessionEnabled`, `App.jsx`의 `/` 경로) |
| 빌드 변수 | `VITE_ENABLE_LOCAL_DEMO` | `'true'`면 개발 모드가 아니어도 `/demo/` 경로의 미리보기를 허용한다(`DemoChatPage.jsx`의 `DemoOnlyChat`·`DemoAdminBlocked`) |
| 서버 환경변수 | `LLM_MODEL`, `CHAT_FINAL_FROM_STREAM` | `/chat` 응답의 모델 이름과 최종 답 처리 방식(`backend/api/routes.py`의 `model_name`·`final_from_stream_enabled`) |

### 검증 계획

- 현재 완료된 범위: 프론트 단위 테스트와 production build 검증.
- 작성 당시 미완료 범위: 실제 백엔드와의 API 통합 테스트(PR #60 머지 뒤의 브라우저 통합 검증 기록은 찾지 못함, 팀 확인 필요).
- PR #60 머지 뒤 검증할 항목:
  1. `GET /threads` 및 `GET /threads/{id}` 실제 응답 매핑
  2. `POST /chat` 요청 body와 SSE event/data 구조
  3. `error`, `done`, `attribution`, `approval_request`의 실제 data 구조
  4. 승인 대기 중 HTTP 409와 승인 완료·거절 이후 상태 전이

## AC

### AC-01 실제·데모 adapter 선택

- **GIVEN** 실제 모드 또는 데모 모드가 선택되어 있다.
- **WHEN** 채팅 서비스가 생성된다.
- **THEN** 실제 모드에서는 `createApiChatAdapter`, 데모 모드에서는 기존 preview adapter를 사용한다.

### AC-02 thread 목록 매핑

- **GIVEN** `GET /threads` 응답에 `thread_id`, `title`, `updated_at`이 있다.
- **WHEN** `listThreads()`를 호출한다.
- **THEN** UI에는 `id`, `title`, `lastActivityAt`으로 변환된 목록이 제공된다.

### AC-03 새 대화 요청

- **GIVEN** 새 대화이고 `thread_id`가 `null`이다.
- **WHEN** 메시지를 전송한다.
- **THEN** 요청 JSON에 `thread_id` 키가 포함되지 않는다.

### AC-04 청크 분할 SSE

- **GIVEN** 하나의 SSE 이벤트가 여러 청크로 분할되고 ping 주석이 섞여 있다.
- **WHEN** 스트림을 파싱한다.
- **THEN** 이벤트는 한 번만 처리되고 ping 주석은 무시된다.

### AC-05 이벤트별 상태 처리

- **GIVEN** token, citation, approval_request, error, done 이벤트가 순서대로 도착한다.
- **WHEN** 스트림을 처리한다.
- **THEN** 토큰은 누적되고 citation은 중복 없이 반영되며 approval은 승인 대기 상태가 되고 오류·종료 상태가 각 코드에 맞게 표시된다.

### AC-06 no-results와 attribution

- **GIVEN** done 이벤트의 `data.code`가 `no_results`이거나 attribution이 포함되어 있다.
- **WHEN** done 이벤트를 처리한다.
- **THEN** 메시지 상태는 `no-evidence`가 되고 attribution은 기존 citation과 중복 없이 출처에 반영된다.
- **GIVEN** 거절 done의 `data.refuse_reason`(또는 대화 이력 거절 답의 `refuse_reason`)이 `out_of_domain`·`out_of_period`·`nonexistent_entity`·`leak`·`no_key`·`index_not_ready`이거나 없다. **THEN** 다시 물어보라는 안내를 붙이지 않는다. `no_evidence`·`unsupported`·`citation_check`이면 붙인다(H-34, `src/chat-notices.test.jsx`).

### AC-07 대화별 승인 대기

- **GIVEN** 현재 대화의 메시지 상태가 approval이다.
- **WHEN** 사용자가 입력하거나 전송하려 한다.
- **THEN** 해당 대화의 입력과 전송만 비활성화된다.

### AC-08 대화 전환

- **GIVEN** 대화 A가 승인 대기이고 대화 B 또는 새 대화로 전환한다.
- **WHEN** 화면이 전환된다.
- **THEN** A의 차단 상태가 B 또는 새 대화에 잘못 상속되지 않는다.

### AC-10 다른 메뉴에 갔다 와도 답 이어 받기

- **GIVEN** 대화에서 답을 받는 중이다.
- **WHEN** 다른 메뉴로 갔다가 채팅으로 돌아온다.
- **THEN** 그 대화가 열리고, 서버가 답을 끝낼 때까지 "다른 화면에 있는 동안 이어서 만든 답을 불러오는 중입니다." 표시와 입력 잠금이 있다가 끝난 답이 보인다. 답을 다 받은 뒤 갔다 오면 아무 대화도 저절로 열지 않는다(`web/react-app/src/chat-ux.test.jsx`).

### AC-11 맨 아래로 따라가기와 입력칸 높이

- **GIVEN** 대화가 열려 있다.
- **WHEN** 질문을 보내 답이 오거나, 여러 줄을 입력한다.
- **THEN** 메시지 영역이 맨 아래로 간다(위로 올려 읽는 중이면 그대로). 입력칸은 최대 208px까지 늘어난다(`web/react-app/src/chat-ux.test.jsx`).

### AC-12 새로고침해도 연 대화 유지

- **GIVEN** 대화 A를 열어 두었다.
- **WHEN** 브라우저를 새로고침한다.
- **THEN** 새 대화 화면이 아니라 대화 A가 다시 열린다(`web/react-app/src/front-fixes.test.jsx`).

### AC-13 새 대화 첫 질문도 말풍선으로 안내

- **GIVEN** 새 대화 화면이다(서버가 아직 대화 id를 주지 않음).
- **WHEN** 첫 질문을 보낸다.
- **THEN** 두 번째 질문과 같이 보낸 질문 말풍선과 '근거를 찾고 답을 확인하는 중입니다 · N초 지남' 말풍선이 바로 보이고, 답이 오면 그 대화로 바뀐다(`web/react-app/src/followup-1113.test.jsx`).

### AC-09 실제 API 통합 검증 보류

- **GIVEN** 화면과 실제 백엔드를 브라우저로 이은 통합 검증 기록이 없다.
- **WHEN** D6 검증 결과를 보고한다.
- **THEN** 그 통합 검증은 미완료라고 명시한다. (PR #60은 머지됐으므로 "PR #60 반영 후"는 더 이상 조건이 아니다. 기록이 생기면 이 AC를 "완료"로 바꾼다.)
