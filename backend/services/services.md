# backend/services/ : 공용 서비스

## 이 폴더가 하는 일

LLM 호출(`llm.py`)은 여기 한 곳에서만 한다. 데모 모드 재생, Langfuse 트레이스, 비용 상한도 여기서 처리한다. 런타임 Skill 불러오기(`skills.py`)도 둔다.

- 주인: 김승욱
- 입력: 프롬프트, 설정(`.env`)
- 출력: 모델 응답, 트레이스

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-11 | 박진형 | 로컬(`PROVENA_ENV=local`)에서만 가입 인증번호를 서버 로그에 남김(`email_sender.py` 기록용 발송기, K-21). 시험 추가. | 이번 PR |
| 2026-11-02 | 김승욱 (Claude Code) | `llm.py` 재시도, 시간 제한, 폴백 모델(G-05), Skill 읽기 `skills.py` | 이번 PR |
| 2026-11-01 | 김승욱 (Claude Code) | LLM 호출 한 곳: `llm.py`(`get_chat_model`·`run_config`·`finish_run`), `demo_replay.py`·`demo_record.py`(녹화·재생), `cost.py`·`llm_prices.json`(비용 상한), `tracing.py`(Langfuse), `claude_cli_model.py`(개발용). Spec `docs/specs/llm.md`, 시험 `tests/test_llm*.py` 21건. 키 이름을 `LLM_API_KEY`·`LLM_PROVIDER`로 `.env.example`에 맞춤 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | `auth_store.py`(Postgres AuthStore), `demo_seed.py`(PROVENA_ENV=local, PROVENA_DEV_MODE=1일 때만 데모 계정 2개 시드)와 `tests/test_auth_store.py`. 가짜 연결로 시험하고, 진짜 Postgres 왕복 시험과 `docker compose` 로그인 흐름(CSRF, 로그인 200, 틀린 비밀번호 401, `/me`, 로그아웃 204)을 직접 돌려 확인 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
