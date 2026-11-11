# backend/services/ : 공용 서비스

## 이 폴더가 하는 일

LLM 호출(`llm.py`)은 여기 한 곳에서만 한다. 데모 모드 재생, Langfuse 트레이스, 비용 상한도 여기서 처리한다. 런타임 Skill 불러오기(`skills.py`)도 둔다.

- 주인: 김승욱
- 입력: 프롬프트, 설정(`.env`)
- 출력: 모델 응답, 트레이스

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-11 | 박진형 (jinyeong-731) | G-08: `llm.py`에 `CachingChatModel`(같은 모델·메시지·호출 조건이면 응답 재사용). `LLM_RESPONSE_CACHE=1`일 때만 켜짐(기본 꺼짐), 평가 실행(`metadata.eval`)은 건너뜀, 데모·재생 모드는 그대로, 적중 응답은 사용량 0으로 돌려 비용 집계가 안 부풀음. 캐시 저장소는 모델 인스턴스(그래프 모델 1개) 안. 안쪽 모델은 `_generate`로 불러 비용 이중 집계를 막음. eval_config 경로만 우회, 다른 평가 스크립트는 LLM_RESPONSE_CACHE를 끄고(기본) 돌린다. 알려진 문제(고치지 않음): `FallbackChatModel`은 `invoke`로 안쪽 모델을 불러 콜백이 두 번 불림(비용 2배 집계, 실측 2/2000). 시험 `tests/test_llm_cache.py` | 미정 |
| 2026-11-11 | 박진형 (jinyeong-731) | 로컬(`PROVENA_ENV=local`)에서만 가입 인증번호를 서버 로그에 남김(`email_sender.py` 기록용 발송기, K-21). 시험 추가. | 이번 PR |
| 2026-11-02 | 김승욱 (Claude Code) | `llm.py` 재시도, 시간 제한, 폴백 모델(G-05), Skill 읽기 `skills.py` | 이번 PR |
| 2026-11-01 | 김승욱 (Claude Code) | LLM 호출 한 곳: `llm.py`(`get_chat_model`·`run_config`·`finish_run`), `demo_replay.py`·`demo_record.py`(녹화·재생), `cost.py`·`llm_prices.json`(비용 상한), `tracing.py`(Langfuse), `claude_cli_model.py`(개발용). Spec `docs/specs/llm.md`, 시험 `tests/test_llm*.py` 21건. 키 이름을 `LLM_API_KEY`·`LLM_PROVIDER`로 `.env.example`에 맞춤 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | `auth_store.py`(Postgres AuthStore), `demo_seed.py`(PROVENA_ENV=local, PROVENA_DEV_MODE=1일 때만 데모 계정 2개 시드)와 `tests/test_auth_store.py`. 가짜 연결로 시험하고, 진짜 Postgres 왕복 시험과 `docker compose` 로그인 흐름(CSRF, 로그인 200, 틀린 비밀번호 401, `/me`, 로그아웃 204)을 직접 돌려 확인 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
