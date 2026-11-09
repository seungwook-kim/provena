# Spec — LLM 호출 한 곳 (`backend/services/llm.py`, 김승욱)

## Why

- **페르소나**: 질의 번역(검색), 답 작성·근거 판정(질문 그래프), 팀 에이전트를 만드는 우리 조, 키 없이 데모를 돌리는 평가자
- **상황**: 모든 LLM 호출은 `backend/services/llm.py` 한 곳을 거친다(SDD 447). 평가자에게는 키가 없고(G2, 가이드 p.19), 키는 조당 하나에 30달러 한도다(가이드 p.12).
- **문제**:
  1. 파트마다 모델을 직접 만들면 데모 모드·트레이스·비용 상한이 빠지는 곳이 생긴다.
  2. 키가 없으면 번역·답 작성이 죽어 `docker compose up` 데모가 깨진다.
- **측정 지표**: 데모 모드에서 외부 호출 0건, 트레이스가 남지 않는 실제 호출 0건, 질문당 비용 상한 초과 0건

## Goal

- **해결 목표**: LangChain 채팅 모델 하나(`get_chat_model()`)와 실행 설정(`run_config()`·`finish_run()`)으로 실제 호출, 녹화, 재생, 비용 상한, Langfuse 트레이스를 처리한다. LangGraph 노드는 이 모델을 그대로 쓴다.
- **성공 기준**: 키가 없거나 `DEMO_MODE=1`이면 외부 호출 없이 응답 / 같은 요청이면 같은 재생 응답 / 상한에 닿으면 다음 호출에서 멈춤 / Langfuse 키가 없어도 그대로 돈다
- **Out of Scope**: 생성 모델 최종 선택(SDD 11장), 채점용 LLM 호출(`evals/`)

## What

**Happy Path**
1. 노드가 `get_chat_model()`로 모델을 받는다. 키가 있고 `DEMO_MODE`가 1이 아니면 `LLM_PROVIDER`의 실제 모델, 아니면 재생 모델(`ReplayChatModel`)이다.
2. 그래프를 돌릴 때 `run_config(graph_name, thread_id=..., user_id=...)`를 `invoke`/`stream`에 넘긴다. 비용 집계와 Langfuse 핸들러(키가 있을 때)가 모든 호출에 따라간다.
3. 끝나면 `finish_run(config)`가 비용·토큰 합계를 돌려주고 트레이스에 `cost_usd` 점수를 남긴다.
4. `LLM_RECORD=1`이면 실제 응답을 요청 키로 `data/demo_replay/`에 녹화한다. 데모 모드는 같은 요청 키의 녹화를 재생한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 데모 모드인데 녹화가 없음 | 결정적 가짜 응답(검색된 근거 문장을 인용)으로 답한다. 죽지 않는다 |
| EC-02 | 질문당 비용 상한 도달 | 다음 호출에서 `CostCapExceeded`. 질문 그래프는 error 이벤트로 멈춘다(question-graph EC-09) |
| EC-03 | Langfuse 키 없음 | 트레이스 없이 그대로 돈다 |
| EC-04 | 알 수 없는 `LLM_PROVIDER` | 모델을 만들 때 `ValueError` |
| EC-05 | 모델 단가가 단가표에 없음 | `llm_prices.json`의 기본 단가로 센다 |

## How

| 파일 | 하는 일 |
|---|---|
| `backend/services/llm.py` | `get_chat_model`, `is_demo_mode`, `run_config`, `finish_run` |
| `backend/services/demo_replay.py` | 재생 모델, 녹화 래퍼, 요청 키 |
| `backend/services/demo_record.py` | 질문 목록으로 녹화 파일 만들기(질문 그래프가 생긴 뒤 쓴다) |
| `backend/services/cost.py`, `llm_prices.json` | 토큰·비용 집계, 상한, 단가표(PRD 기술 선택 표) |
| `backend/services/tracing.py` | Langfuse 핸들러와 점수 기록 |
| `backend/services/claude_cli_model.py` | `LLM_PROVIDER=claude_cli`: 로컬 Claude Code CLI를 모델로 씀(개발용) |

**환경 변수** (`.env.example`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `DEMO_MODE` | `1` | 1이면 키가 있어도 재생 |
| `LLM_PROVIDER` | 코드 기본값 `anthropic`, `.env.example`은 `openrouter` | `anthropic`, `openai`, `openrouter`, `claude_cli` |
| `LLM_MODEL` | anthropic `claude-haiku-5-5`, openrouter `anthropic/claude-haiku-5.5` | |
| `LLM_API_KEY` | 없음 | 없으면 데모 모드 |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | openrouter일 때만 |
| `LLM_COST_CAP_USD` | `0.05` | 질문 하나의 비용 상한 |
| `LLM_RECORD`, `DEMO_REPLAY_DIR` | 끔, `data/demo_replay` | 녹화 |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | 없음 | 키가 있으면 트레이스 설정을 읽음 |
| `LANGFUSE_TRACING_ENABLED` | 비움(켜짐), `false`(끔) | Langfuse 연동 전체 스위치 |
| `LANGFUSE_CONTENT_CAPTURE_ENABLED` | `false` | 일반 요청의 입력·출력·식별자 캡처는 명시적으로 켠 경우에만 허용 |

**제공자 전환**: 로컬 개발은 Claude Code CLI(`LLM_PROVIDER=claude_cli`, `claude-haiku-5-5`, 키 불필요, 컨테이너 안에서는 동작하지 않음), 운영 배포는 OpenRouter 키(`LLM_PROVIDER=openrouter`, `anthropic/claude-haiku-5.5`)로 같은 모델을 쓴다. 환경 변수만 바꾸고 코드는 그대로다. 비용 단가는 OpenRouter 이름도 같은 단가표 항목으로 찾는다(`cost.normalize_model_id`).

## Langfuse privacy and production configuration

The Langfuse integration has two independent gates:

- `LANGFUSE_TRACING_ENABLED=false` disables Langfuse completely.
- `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are both required. `LANGFUSE_HOST` is optional and defaults to `https://cloud.langfuse.com`.
- `LANGFUSE_CONTENT_CAPTURE_ENABLED` defaults to `false`. Without it, ordinary requests do not create a Langfuse callback or attach user/session identifiers; application execution continues with cost tracking only.
- Set `LANGFUSE_CONTENT_CAPTURE_ENABLED=true` only in an approved environment. The Langfuse callback may record model inputs, outputs, and trace metadata, so this setting requires the operator's privacy and retention approval.
- Evaluation runs are explicitly marked with `metadata["eval"]` and may record evaluation traces and scores without changing the ordinary-request fail-closed policy.
- `LANGFUSE_SAFE_EVENTS_ENABLED=true` enables aggregate-only events. These events contain only the allowlisted aggregate fields and never include prompt, response, user, session, or thread identifiers.

For production, configure the keys through deployment secrets and configure the flags through deployment environment settings. `.env.example` contains only the non-secret default `LANGFUSE_CONTENT_CAPTURE_ENABLED=false`; never add actual keys or enable content capture there. If the keys or content-capture flag are absent, the service remains operational without Langfuse content tracing.

## AC (Given-When-Then)

**AC-01 · 키 없이 동작**
- GIVEN: `LLM_API_KEY` 없음
- WHEN: `get_chat_model().invoke(...)`
- THEN: 외부 호출 없이 응답한다 (`tests/test_llm.py`)

**AC-02 · 제공자 분기**
- GIVEN: `LLM_PROVIDER`가 openrouter·openai·anthropic 중 하나, 키 있음, `DEMO_MODE=0`
- WHEN: `get_chat_model()`
- THEN: 네트워크 없이 그 제공자의 모델 객체가 만들어지고, openrouter는 기본 모델·주소를 쓴다 (`tests/test_llm_openrouter.py`, `tests/test_llm_providers.py`)

**AC-03 · 재생과 비용 상한** (질문 그래프가 생긴 뒤 시험을 더한다)
- GIVEN: 녹화한 요청, 상한에 닿은 실행
- WHEN: 같은 요청을 데모 모드로, 상한 넘은 실행에서 다음 호출을
- THEN: 녹화 응답을 돌려주고, `CostCapExceeded`가 난다
