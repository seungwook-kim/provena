# 아키텍처

조의 설계를 그림과 글로 남기는 자리입니다. 발표와 `EVAL_REPORT.md`가 이 문서를 가리킵니다. 아래는 출발점이고, 조의 구조에 맞게 고치세요.

## 요청 흐름 (출발점)

```mermaid
flowchart LR
    U[사용자] --> A[FastAPI]
    A --> SV{Supervisor: 질의 분석과 라우팅}
    SV --> RA[검색 에이전트]
    RA --> S[하이브리드 검색: BM25와 벡터]
    S --> K[리랭킹과 메타데이터 필터]
    K --> J[문서 채점]
    J -->|근거 부족| W[질의 재작성과 재검색]
    W --> S
    J -->|충분| WA[작성 에이전트: 근거를 붙인 답변]
    WA --> VA[검증 에이전트: 인용과 안전 검증]
    VA --> H{승인이 필요한 행동?}
    H -->|예| I[사람 승인 대기: interrupt]
    H -->|아니오| O[응답]
    I --> O
    D[(pgvector)] --> S
    P[문서 파싱과 청킹] --> D
    SV -.-> L[Langfuse 트레이스]
```

## 조가 채울 것

| 질문 | 답 |
|---|---|
| 왜 그래프인가(분기, 반복, 승인이 왜 필요한가) | |
| Supervisor와 서브에이전트는 각각 무엇을 책임지고, 무엇을 서로 모르게 하는가(컨텍스트 격리) | |
| 어디서 사람 승인(interrupt)을 받는가, 왜 거기인가 | |
| 체크포인트에서 무엇이 저장되고 어떻게 재개되는가 | |
| 로그인한 사용자 id가 thread와 Store namespace에 어떻게 들어가는가 | `backend/auth.py`의 `current_user_id()`를 FastAPI 의존성으로 사용한다. `Depends(current_user_id)`가 `provena_auth` HttpOnly JWT 쿠키를 읽고, `AUTH_SECRET` 환경변수와 HS256으로 서명·만료를 검증한다. 인증에 성공하면 JWT의 UUID `user_id`를 정규화된 문자열로 반환하며, 쿠키가 없거나 인증 정보가 유효하지 않거나 만료·위조된 경우 HTTP 401을 반환한다. 요청 본문이나 query string으로 클라이언트가 전달한 사용자 ID는 신뢰하지 않는다. 반환한 문자열은 Graph 입력의 `AgentState.user_id: str`로 전달하는 계약이다. 실제 Graph 호출 연결과 `thread_id`·Store namespace 분리는 아직 미완료이며, FastAPI 연결 후 통합 검증이 필요하다. |
| 무엇을 State에 두고 무엇을 Store에 두는가 | |
| 벡터DB는 무엇이고 왜 골랐는가(선택 이유와 한계) | |
| 신뢰 경계: 코퍼스 안의 지시문(간접 인젝션)은 어디서 막는가 | |

## 조원 간 계약서 (병렬로 일하기 전에 먼저 씁니다)

3명이 동시에 일하면 함수 시그니처만 맞춰서는 부족합니다. DART 실험에서 한쪽이 코퍼스 파일(242청크)에서 기업 목록을 만들어 두어, 코퍼스를 키우자 새 기업을 전부 "없는 기업"으로 거절할 구조가 되었습니다. 시그니처에 보이지 않는 의존이 문제였습니다.

| 항목 | 내용 |
|---|---|
| 각자 수정할 수 있는 경로 | 예) A: `backend/rag/`, `data/`, B: `backend/graph/`, C: `evals/`, `docs/`<br>**3조 (안, D0 확정, `docs/TEAM_GUIDE.md` 5장)**<br>김승욱: `backend/graph/`, `backend/memory/`, `backend/prompts/`, `skills/`, `backend/main.py`, `backend/services/`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `db/`, `evals/agent/`, `evals/safety/`, `mock_erp/`<br>박진형: `backend/rag/`, `data/`, `evals/retrieval/`, `extras/mcp_skill/`<br>강경희: `backend/auth.py`, `web/`<br>공동(3명 승인): `backend/schemas/`, 평가셋 |
| 모듈 사이의 함수와 시그니처 | 예) `retrieve(question, k, ...) -> list[dict]`, `build_graph(retriever=None, checkpointer=None)`<br>**3조 (안, D0 확정)**<br>김승욱 제공: `build_graph(retriever=None, checkpointer=None)`. 그래프는 검색기와 체크포인터를 주입받는다(`docs/specs/question-graph.md`). 로그인 저장소: `PostgresAuthStore(dsn)`(`backend/services/auth_store.py`)가 강경희의 `AuthStore` Protocol(`get_by_login_id`, `get_by_user_id`)을 구현하고, `backend/main.py`가 `DATABASE_URL`이 있을 때 `create_auth_router(store=...)`로 붙인다<br>그래프가 받는 것: 검색 `retriever(SearchQuery) -> list[Chunk]`(박진형, 형식은 `backend/schemas/`), 로그인한 사용자 id를 꺼내는 함수(강경희). 두 줄은 D0에서 채운다<br>강경희 제공: 구현 함수는 `current_user_id(request: Request) -> str`이며 FastAPI 계약상 `current_user_id() -> str`로 사용한다(`user_id: str = Depends(current_user_id)`). 서명된 `provena_auth` 인증 쿠키에서 UUID 문자열을 추출하고, 인증 실패 시 HTTP 401을 반환한다. Graph에는 `AgentState.user_id: str`로 전달하며, 실제 Graph 연결은 아직 미완료다. |
| 의존하는 파일과 환경변수 | 코퍼스 경로, 모델 이름, `DEMO_MODE` 등. **코드가 읽는 파일을 빠짐없이**<br>**3조 (안, D0 확정)**<br>김승욱 파트: `DEMO_MODE`, LLM 키(`.env.example`), `DATABASE_URL`(체크포인터, 답·인용 저장, 로그인 users 조회), `LANGFUSE_*`. 로컬 데모 기동용: `PROVENA_ENV`, `PROVENA_DEV_MODE`, `DEMO_USER_LOGIN_ID`·`DEMO_USER_PASSWORD`, `DEMO_ADMIN_LOGIN_ID`·`DEMO_ADMIN_PASSWORD`(시드, `backend/services/demo_seed.py`), compose 포트 `API_PORT`. 파일: `skills/`의 런타임 Skill, 데모 모드 녹화 응답(경로는 D0), `db/101_auth_users.sql`(users 테이블), 화면 정적 파일 `web/`(`backend/main.py`가 내준다)<br>박진형 파트(코퍼스·색인 경로, 임베딩·리랭커 모델 이름), 강경희 파트: 파일 `backend/auth.py`; `AUTH_SECRET`(JWT 서명·검증에 필요한 환경변수), 쿠키 이름 `provena_auth`, JWT 알고리즘 `HS256`. 테스트 사용자는 `tests/test_auth_router_runtime.py`의 `FakeAuthStore`와 fixture에서 생성하며, `db/01_init.sql`에는 사용자 seed가 없다. |
| 오프라인 규칙 | 키 없이 돌 때 어떤 모델과 파일을 쓰는가<br>**3조 (안, D0 확정)**<br>LLM 키가 없으면 `DEMO_MODE=1`로 기록해 둔 응답을 재생한다. 그래프 시험은 가짜 검색기와 메모리 체크포인터로 키와 DB 없이 돈다. 로컬 데모 계정 2개는 `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1`이 모두 켜졌을 때만 시드하고 그 밖의 모드에서는 만들지 않는다(compose가 `.env.example`의 로컬 데모 계정 값을 읽는다. `AUTH_SECRET`은 저장소에 두지 않고, 비어 있으면 로컬 데모 모드에서만 실행마다 무작위로 만든다). 임베딩·리랭커 모델의 오프라인 실행(`HF_HUB_OFFLINE=1`)은 박진형 파트에서 D0에 채운다 |

## 결정 기록

바꿀 때마다 한 줄씩 남깁니다. `날짜 | 무엇을 | 왜 | 대안`

3조는 결정마다 이유와 버린 대안을 [`docs/decisions.md`](decisions.md)에 적는다.
