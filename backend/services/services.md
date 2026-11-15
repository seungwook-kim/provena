# backend/services/ : 공용 서비스

## 이 폴더가 하는 일

LLM 호출(`llm.py`)은 여기 한 곳에서만 한다. 데모 모드 재생, Langfuse 트레이스, 비용 상한도 여기서 처리한다. 런타임 Skill 불러오기(`skills.py`)도 둔다. 그 밖의 파일: `step_cost.py`(요청 한 건의 단계별 비용·Voyage 토큰 집계), `tracing.py`(Langfuse 트레이스 콜백), `claude_cli_model.py`(키 없이 Claude Code CLI를 채팅 모델로 쓰는 어댑터, 측정용), `auth_store.py`(Postgres `users` 읽는 AuthStore), `create_account.py`(배포판 첫 계정 만드는 일회용 명령), `demo_seed.py`(로컬 데모 계정 시드), `profile_crypto.py`·`profile_store.py`(내 정보 암호화와 `user_profiles` 저장).

- 주인: 김승욱
- 입력: 프롬프트, 설정(`.env`)
- 출력: 모델 응답, 트레이스

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-15 | 박진형 (jinyeong-731) | 놓친 것 K-24(조장 지시로 처리): 키 없는 데모에서 같은 녹화 질문의 답 글이 실행마다 달라지던 것. 재생 저장소가 같은 요청 키의 응답 변형을 돌려 내는 차례(`_turn`)를 프로세스 전체로 세서, 다음 실행이 다른 변형부터 시작해 근거 확인 다수결이 바뀌었다. `run_config`가 데모 모드에서만 실행마다 metadata `replay_run`(새 uuid)을 붙이고, `ReplayChatModel`이 그 값을 `pick_ranked(key, run=...)`에 넘겨 차례를 실행 안에서 0부터 센다(녹화는 질문마다 한 번 돈 것이라 실행마다 0번부터 내야 녹화와 같다). 실행 표지가 없으면 예전 동작, 기억하는 실행은 최근 256개. 판정 다수결·답 두 번 쓰기는 문맥을 복사한 스레드(`build.py` `in_background`)라 같은 실행으로 센다(시험으로 확인). 실제 모델 실행에는 표지를 붙이지 않는다. 시험 `tests/test_demo_replay_run_turns.py` 6개. 고친 줄 3곳을 하나씩 되돌리면 3번 모두 실패 | #160 |
| 2026-11-15 | 박진형 (jinyeong-731) | 놓친 것 K-23(조장 지시로 처리, `profile_crypto.py`는 박진형이 만든 파일): 로컬 데모에서 `PROFILE_ENC_KEYS`가 없으면 실행마다 새 키를 만들던 것을, 한 번 만든 키를 키 파일에 두고 다음 실행에 다시 읽게 함(`load_or_create_local_key`). 키 파일은 `PROFILE_KEY_FILE`, 비우면 실행 사용자 홈 `~/.provena/local_demo_profile.key`(저장소 밖, 컨테이너는 `/home/app`), 권한 0600, 형식은 `PROFILE_ENC_KEYS`와 같음. 파일이 깨졌으면 새로 만들고, 못 쓰면 이번 실행만 쓰는 키로 돈다. 로컬 데모가 아니면 키 파일을 읽지도 쓰지도 않고 전처럼 시작을 막는다. 로컬에서 만든 키로 도는 암호기는 `local_generated=True`(내 정보 API의 다시 입력 안내 조건). `backend/main.py`는 고치지 않음(이미 `allow_ephemeral=is_local_demo()`로 넘김). 시험 `tests/test_profile_crypto.py` 7개 추가·1개 수정, `tests/conftest.py`에 시험 중 키 파일 자리를 임시 폴더로 돌리는 고정 장치. 변이 4개(파일 다시 안 읽음, 파일에 안 적음, 로컬 데모 밖에서도 씀, 받은 키도 로컬 표시) 모두 실패로 잡힘. compose 실제 기동은 안 함 | #160 |
| 2026-11-11 | 박진형 (jinyeong-731) | G-08: `llm.py`에 `CachingChatModel`(같은 모델·메시지·호출 조건이면 응답 재사용). `LLM_RESPONSE_CACHE=1`일 때만 켜짐(기본 꺼짐), 평가 실행(`metadata.eval`)은 건너뜀, 데모·재생 모드는 그대로, 적중 응답은 사용량 0으로 돌려 비용 집계가 안 부풀음. 캐시 저장소는 모델 인스턴스(그래프 모델 1개) 안. 안쪽 모델은 `_generate`로 불러 비용 이중 집계를 막음. eval_config 경로만 우회, 다른 평가 스크립트는 LLM_RESPONSE_CACHE를 끄고(기본) 돌린다. 알려진 문제(고치지 않음): `FallbackChatModel`은 `invoke`로 안쪽 모델을 불러 콜백이 두 번 불림(비용 2배 집계, 실측 2/2000). 시험 `tests/test_llm_cache.py`. 조장 확인(2026-11-12 조장 리뷰(#132)에서 확정): 응답 캐시는 운영과 최종 측정에서 켜지 않는다(운영 `/chat` 측정은 `metadata.eval`이 없어 켜면 측정값이 오염됨). `.env.example`의 새 변수는 이미 `.env.example`에 있다(`:134`·`:136`·`:290-291`, 조장이 넣음) | #132·#135 |
| 2026-11-11 | 박진형 (jinyeong-731) | 놓친 것 H-32 ③: 키 없는 데모의 응답이 약 3초로 고정된다는 지적을 확인했다. 재생 코드(`demo_replay.py`)에 고정 지연은 없고 같은 요청의 n번째 변형만 n*0.05초 늦출 뿐이다(녹화 완료 순서 재현). 질문당 0.1~0.6초는 11/10 새 clone 로컬 compose 실측(`docs/GATES.md` G2)과 같다. 코드는 그대로 두고 고정 지연이 없음을 지키는 시험(`test_replay_adds_no_fixed_delay`)을 추가했다. 3초 근거는 찾지 못했고, 보인 지연이 있었다면 검색 모델 첫 적재나 CLI 기동 때문일 수 있다(추정). | #131 |
| 2026-11-11 | 박진형 (jinyeong-731) | 로컬(`PROVENA_ENV=local`)에서만 가입 인증번호를 서버 로그에 남김(`email_sender.py` 기록용 발송기, K-21). 시험 추가. | 이번 PR |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) 단계별 비용: `step_cost.py` 신설(요청 단위 집계), `cost.py`의 `CostTracker`에 단계별 합(`by_step`), `llm.py`·`llm_trace.py`·`llm_prices.json`(Voyage 임베딩 단가)을 연결(커밋 0a15fc2). 데모 녹화: `demo_record.py`가 서버 그래프·서비스 설정·Postgres 검색으로 돌게 고침(그전엔 없는 모듈을 불러 동작하지 않았음, 3c9a1ad), `demo_replay.py`가 추론 응답의 텍스트 블록만 녹화하고(ed404c4) 같은 키의 변형을 녹화된 완료 순서로 재생(0fe3635) | #119 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #110) `llm.py`에서 단계별 LLM hedge 시간(`LLM_HEDGE_BY_TASK`)을 뺌(효과가 없어 되돌림, 커밋 51cdfdc) | #110 |
| 2026-11-10 | 강경희 (기록: 박진형) | (보충, PR #102) 회원가입 승인 리뷰 반영(`auth_store.py`) | #102 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #89) 서버 시작 때 LLM 모듈 적재를 끝내고 LLM 지연·재시도 로그를 운영 로그에 남김(`llm.py`) | #89 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #81) 키 없는 데모에서 질문 벡터 재생과 녹화 파일(`demo_replay.py`), 녹화 요청 키를 gitleaks 오탐에서 제외 | #81 |
| 2026-11-02 | 김승욱 (Claude Code) | `llm.py` 재시도, 시간 제한, 폴백 모델(G-05), Skill 읽기 `skills.py` | 이번 PR |
| 2026-11-01 | 김승욱 (Claude Code) | LLM 호출 한 곳: `llm.py`(`get_chat_model`·`run_config`·`finish_run`), `demo_replay.py`·`demo_record.py`(녹화·재생), `cost.py`·`llm_prices.json`(비용 상한), `tracing.py`(Langfuse), `claude_cli_model.py`(개발용). Spec `docs/specs/llm.md`, 시험 `tests/test_llm*.py` 21건. 키 이름을 `LLM_API_KEY`·`LLM_PROVIDER`로 `.env.example`에 맞춤 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | `auth_store.py`(Postgres AuthStore), `demo_seed.py`(PROVENA_ENV=local, PROVENA_DEV_MODE=1일 때만 데모 계정 2개 시드)와 `tests/test_auth_store.py`. 가짜 연결로 시험하고, 진짜 Postgres 왕복 시험과 `docker compose` 로그인 흐름(CSRF, 로그인 200, 틀린 비밀번호 401, `/me`, 로그아웃 204)을 직접 돌려 확인 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| S-002 | 2026-11-15 | 김승욱 | 키 없는 데모에서 같은 녹화 질문의 답 글이 실행마다 달라짐(놓친 것 K-24) | 시연·평가 중 같은 질문을 다시 물으면 답이 바뀌어 재현이 안 됨 | 박진형 | 해결 | 2026-11-15 | `tests/test_demo_replay_run_turns.py`의 `test_same_question_gives_the_same_grounding_vote_every_run`(변형 6개·3표 모양에서 실행 4번 다수결이 같음, 표지 없는 예전 동작은 실행마다 바뀜), `test_model_reads_the_run_from_config_metadata_also_in_worker_threads`, `test_run_config_adds_a_fresh_run_mark_only_in_demo_mode`. 녹화가 현재 코드와 어긋나 생기는 거절(K-22)은 다시 녹화해야 하며 이 수정과 별개 |
| S-001 | 2026-11-15 | 김승욱 | 로컬 데모에서 api를 재시작하면 내 정보 암호화 키가 바뀌어 `/myinfo`가 503이 되고 다시 입력할 길도 안내되지 않음(놓친 것 K-23) | 평가자가 재시작 뒤 내 정보 화면에서 막힘 | 박진형 | 해결 | 2026-11-15 | `tests/test_profile_crypto.py`의 `test_local_demo_key_is_persisted_and_reused_after_restart`·`test_production_mode_never_reads_or_writes_a_key_file`·`test_broken_key_file_is_replaced_with_a_new_key`, `tests/test_profile_api.py`의 `test_local_demo_lost_key_asks_to_reenter_and_save_works`·`test_configured_key_mismatch_stays_503_even_in_local_demo`·`test_main_app_local_demo_restart_keeps_key_and_production_writes_no_file`, 화면 `profile-reentry.test.jsx` 2개. 컨테이너를 새로 만드는 경우(`docker compose down` 뒤 `up`, 이미지 다시 빌드)는 키 파일이 사라져 '다시 입력' 안내로 넘어간다(볼륨 추가는 조장 판단, `docs/pr-notes/PR-160.md` K-23) |
