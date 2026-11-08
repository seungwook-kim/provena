# D6 채팅 프론트엔드 및 API 어댑터 Spec

> 상태: 구현 후 보완 문서
>
> 이 문서는 Spec-first 원칙에 따라 구현 전에 작성된 원본 Spec이 아니다. 현재 브랜치에 구현된 D6 프론트엔드 동작을 기준으로 계약과 범위를 명시한 보완 문서이며, 구현 전 합의가 필요한 항목과 아직 확인되지 않은 백엔드 계약을 구분한다.
>
> 기존 기능 목록과 전체 제품 기준은 [`docs/SPEC.md`](../SPEC.md)를 참조한다. 이 문서는 D6 React 채팅 화면과 프론트 어댑터의 세부 동작만 다룬다.

## Why

- **사용자**: 로그인한 사용자가 Provena의 실제 채팅 API 또는 데모 모드로 정책·런북 질문을 주고받는 사용자.
- **상황**: 기존 프리뷰 화면을 유지하면서 실제 백엔드의 대화 목록, 스트리밍 응답, 인용, 승인 대기 상태를 React 화면에 연결해야 한다.
- **문제**:
  1. 데모 어댑터와 실제 API 어댑터를 화면에서 구분해 직접 다루면 호출 계약이 분산된다.
  2. SSE 이벤트가 여러 청크로 나뉘거나 ping 주석을 포함할 수 있어 단순 청크 단위 처리가 안전하지 않다.
  3. 승인 대기 중인 대화만 입력을 막아야 하며, 다른 대화나 새 대화까지 잠기면 안 된다.
  4. `/threads`와 SSE 이벤트의 백엔드 계약이 아직 PR #60과 완전히 검증되지 않았다.
- **측정 기준**: 프론트 단위 테스트와 production build가 통과하고, PR #60 반영 후 실제 백엔드 통합 테스트에서 계약이 일치하는지 확인한다. 실제 API 통합 테스트는 현재 미완료다.

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
| `done` | 기본 상태는 `done`, `data.code === "no_results"`이면 `no-evidence`로 처리; attribution이 있으면 기존 citation과 중복 없이 출처에 반영 |

위 표는 현재 프론트 구현의 처리 기준이다. 백엔드가 각 이벤트의 정확한 `data` 중첩 위치, attribution의 상세 타입, 승인 완료·거절 이벤트를 공식적으로 확정했는지는 PR #60 반영 후 확인한다.

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
  - `approval_request`로 메시지 상태가 `approval`이면 “승인 대기 중”을 표시한다.
  - 현재 대화의 승인 대기 상태에 한해 입력과 전송을 비활성화한다.
  - 데모/실제 adapter 선택, 라우팅, 스트리밍, 중단 기능을 유지한다.
### 확인된 API 필드와 미확정 계약

현재 프론트가 기준으로 삼는 필드는 다음과 같다.

| 호출 | 확인된 프론트 기준 | 아직 확정하지 않은 항목 |
|---|---|---|
| `GET /threads` | `thread_id`, `title`, `updated_at` → `id`, `title`, `lastActivityAt` | 최상위 array/object 구조, 전체 메시지 구조 |
| `GET /threads/{id}` | thread 상세를 UI 대화로 변환 | 실제 상세 응답의 최상위 구조와 필드 중첩 |
| `POST /chat` | JSON 요청 및 text/event-stream 처리 | PR #60 반영 전의 최종 요청·이벤트 계약 |

백엔드에서 확인되지 않은 내용을 새 스키마로 만들지 않는다. PR #60의 변경 파일과 실제 백엔드 스키마를 반영한 뒤 통합 검증에서 확정한다.

### 검증 계획

- 현재 완료된 범위: 프론트 단위 테스트와 production build 검증.
- 현재 미완료 범위: 실제 백엔드와의 API 통합 테스트.
- PR #60 반영 후 검증할 항목:
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

### AC-07 대화별 승인 대기

- **GIVEN** 현재 대화의 메시지 상태가 approval이다.
- **WHEN** 사용자가 입력하거나 전송하려 한다.
- **THEN** 해당 대화의 입력과 전송만 비활성화된다.

### AC-08 대화 전환

- **GIVEN** 대화 A가 승인 대기이고 대화 B 또는 새 대화로 전환한다.
- **WHEN** 화면이 전환된다.
- **THEN** A의 차단 상태가 B 또는 새 대화에 잘못 상속되지 않는다.

### AC-09 실제 API 통합 검증 보류

- **GIVEN** PR #60이 아직 반영되지 않았다.
- **WHEN** D6 검증 결과를 보고한다.
- **THEN** 실제 백엔드 통합 테스트는 미완료이며, PR #60 반영 후 검증 예정이라고 명시한다.
