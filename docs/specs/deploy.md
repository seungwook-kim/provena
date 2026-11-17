# Spec — 배포와 실행 모드 (현재 구현 기록)

이 Spec은 새로 만드는 기능이 아니라, 이미 있는 배포·실행 방식의 계약(어떤 파일에 기대고 어떤 환경변수를 읽는가)을 한곳에 적은 것이다(Q-07). 재배포 명령은 `README.md`의 "Cloud Run 재배포", 키 없는 데모 절차는 README "키 없이 뜨는 데모 모드"에 있다. 배포 환경변수, 재배포 플래그의 뜻, Google 로그인 설정, 운영 DB 적용 순서는 이 문서가 정본이고(`docs/SDD.md` 7장과 함께 읽는다), 표에는 코드에서 확인한 읽는 위치를 단다. 환경변수 값은 저장소에 적지 않는다.

## Why

- **페르소나**: 평가자(배포 주소와 `docker compose up`으로 확인), 배포를 올리는 조원
- **상황**: 실행 방식이 둘이다. 운영은 Cloud Run + Supabase, 데모는 `docker compose up`(키 없음, 녹화 재생)이다(`docs/SDD.md` 7장, `docs/GATES.md` G1·G2).
- **문제**: 배포가 기대는 파일과 환경변수가 README, SDD, 코드에 흩어져 있어 하나가 빠져도 알아채기 어렵다(검색 Spec `docs/specs/search.md`는 이미 표로 두었다).
- **측정 지표**: 위 두 게이트의 확인 기록(`docs/GATES.md`)

## Goal

- **해결 목표**: 배포·기동이 읽는 파일과 환경변수를 표 하나로 두고, 코드 줄을 달아 사라지거나 이름이 바뀌면 찾을 수 있게 한다.
- **성공 기준**: 아래 표의 모든 이름이 코드에서 grep으로 찾아지고, 배포 필수 변수가 모두 이 표에 있다(어긋남은 "남은 점"에 적는다).
- **Out of Scope**: 운영 값, 비밀값, 배포 명령의 변경(정본은 README), 부하·성능 목표

## What

**Happy Path**
1. 운영: `gcloud run deploy provena-api --source . ...`로 소스 배포한다(`README.md` "Cloud Run 재배포"). 컨테이너는 `Dockerfile`로 만들어져 `uvicorn backend.main:app`을 포트 8000에서 띄운다.
2. 앱이 시작할 때 `DATABASE_URL`·`AUTH_SECRET`·`PROFILE_ENC_KEYS` 등을 읽는다. 배포 모드(`PROVENA_ENV`가 local·demo가 아님)에서 `AUTH_SECRET`·`PROFILE_ENC_KEYS`가 없거나 틀리면 시작하지 않는다.
3. 데모: `docker compose up`이 db(pgvector) → loader(색인 적재) → api 순서로 띄운다. `.env`가 없어도 `.env.example`과 `DEMO_MODE=1` 기본값으로 뜬다.

**Edge Case**

| 번호 | 상황 | 기대 동작 |
|---|---|---|
| EC-01 | 배포에서 `AUTH_SECRET` 없음 | 시작하지 않는다(`backend/main.py:118` 부근). 로컬 데모에서만 무작위 키를 만든다 |
| EC-02 | 색인(`data/index/`, `data/index.tar.gz`, `INDEX_URL`)이 모두 없음 | loader는 건너뛰고 서버는 뜬다. 질문은 "색인이 준비되지 않아" 거절로 끝난다(`README.md`) |
| EC-03 | `VOYAGE_API_KEY` 없음 | 검색이 빈 결과(`no_key`)로 끝난다(아래 표) |

## How

### 의존 파일·환경변수

| 구분 | 이름 | 쓰는 곳 |
|---|---|---|
| 파일 | `Dockerfile` | 서비스 이미지. 웹 빌드(`node:22-alpine`) 뒤 `python:3.12-slim`에 `backend/`, `data/`, `web/`, `db/`, `skills/`, `extras/`, `mock_erp/`를 복사하고 이미지 안에서 원문·색인 스냅샷을 푼다. 실행은 `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`(`Dockerfile:60-65`) |
| 파일 | `docker-compose.yml` | 데모. `db`(`pgvector/pgvector:pg16`), `loader`(`python -m backend.rag.retrieve.load_snapshot`, `./data/index` 연결), `api`(포트 `${API_PORT:-8000}`). `.env.example`은 필수, `.env`는 있으면 덮는다 |
| 파일 | `.env.example` | 환경변수 이름·기본값 목록 |
| 파일 | `data/index.tar.gz`, `data/demo_replay/` | 검색 색인 스냅샷과 키 없는 데모의 녹화 재생(`docs/specs/search.md`, `data/data.md`) |
| 파일 | `db/*.sql` | 운영 DB 스키마. 운영에서는 사람이 적용한다(아래 "Google 로그인 설정"·"운영 DB 적용 순서", `db/db.md`) |
| 파일 | `.github/workflows/ci.yml` | `python -m pytest -q`, `python -m pytest -q -m demo_replay`(pgvector Postgres 서비스를 곁에 띄움, 건너뛰면 실패), `evals/ci_compare.py`를 Python 3.12에서 돌린다(키·네트워크 없음). 점수 비교는 가장 최근 운영 측정 폴더도 자동으로 읽는다 |
| 파일 | `backend/main.py` | 환경변수를 시작할 때 읽고 모드를 정한다 |
| 환경변수 | `DATABASE_URL` | 운영 Supabase 풀러 연결 문자열, 데모는 compose가 로컬 db로 넣는다(`backend/main.py:261, 331`). 이 값이 있어야 로그인, `/chat`, `/threads`, `/me/memory`가 붙는다 |
| 비밀값(Secret Manager) | `DATABASE_DIRECT_URL` | 직접 연결 문자열. 스키마 적용처럼 오래 걸리는 작업에만 쓰고 앱은 읽지 않는다(아래 "남은 점") |
| 환경변수 | `AUTH_SECRET` | 로그인 토큰 서명 키(32바이트 이상, `backend/main.py:118`). 없으면 배포 모드에서는 서버가 시작하지 않는다 |
| 환경변수 | `PROFILE_ENC_KEYS` | 내 정보(`/me/profile`) AES-256-GCM 키(`backend/services/profile_crypto.py:20`). 형식 `번호:base64(32바이트)`, 쉼표로 여러 개. 없거나 형식이 틀리면 배포 모드에서는 서버가 시작하지 않는다. 로컬 데모는 비워 두면 키를 한 번 만들어 키 파일(`PROFILE_KEY_FILE`, 기본 `~/.provena/local_demo_profile.key`, compose는 볼륨 `profilekey`)에 두고 재시작 때 다시 쓴다 |
| 환경변수 | `PROVENA_ENV`, `PROVENA_DEV_MODE`, `DEMO_MODE` | 로컬 데모 스위치. 배포에서는 설정하지 않는다(`backend/main.py:82, 160`, 아래 "운영 재배포") |
| 환경변수 | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | 생성 LLM과 키. 키가 없으면 가짜 모델(`backend/services/llm.py:576, 592`, `docs/specs/llm.md`) |
| 환경변수 | `VOYAGE_API_KEY` | 질문 임베딩(`docs/specs/search.md` 환경 변수 표). 없으면 검색은 빈 결과(`no_key`)로 끝난다 |
| 환경변수 | `SEARCH_DECOMPOSE` | 질문 분해(1이면 켬, `docs/specs/question-graph.md`) |
| 환경변수 | `SEARCH_WARMUP` | 시작 때 검색 준비를 기다릴지(`backend/main.py:143`). `1` 기다림, `0` 끔, `background` 기다리지 않고 스레드로. 비우면 운영(`PROVENA_ENV`가 local·demo가 아니고 DB와 LLM 키가 있음)에서는 `1`, 로컬 데모·키 없는 데모·DB 없음에서는 꺼짐. 기다리는 시간은 최대 60초이고 넘거나 실패해도 서버는 뜬다. compose는 비우면 `background` |
| 환경변수 | `PROVENA_OWNER_LOGIN_ID` | 최고 관리자 로그인 아이디(`backend/main.py:338`, `docs/specs/admin-roles.md`). 비었거나 그 계정이 admin·활성이 아니면 사용자 관리만 403이고 나머지는 정상 |
| 환경변수 | `EVAL_REVIEW_SINGLE`, `EVAL_REVIEW_SINGLE_MAX_PER_DAY` | 평가 전용 `POST /admin/eval/review`(관리자 전용, CSRF)를 여는 스위치. `1`이면 열리고 그 밖(비움 포함)은 404다. 서비스 값에 넣지 않으며 합동 검토 팀 대 단일 운영 측정 리비전(사전 등록 62.41, 62.47)에서만 켜고 측정이 끝나면 지운다. 하루 호출 상한 기본 200(`docs/SDD.md`) |
| 환경변수 | `PROVENA_DOCS_PUBLIC` | `0`이면 `/docs`·`/redoc`·`/openapi.json`을 끈다. 비우면 공개(`backend/main.py:372`) |
| 비밀값(Secret Manager) | `MCP_TOKEN` | 있어야 HTTP MCP를 붙인다(`backend/main.py:253`, `docs/specs/mcp.md`). 운영에 연결됨(2026-11-16) |
| 환경변수 | `TRUSTED_PROXY_HOPS` | 프록시 뒤 실제 접속 IP. 기본 0, Cloud Run은 1(`backend/auth.py:705`, `Dockerfile` 주석) |
| 환경변수 | `INDEX_URL`, `INDEX_SHA256` | 색인 압축이 저장소에 없을 때만 내려받는 주소와 해시(`backend/rag/retrieve/load_snapshot.py:204`) |
| 환경변수 | `SERVICE_API_KEY` | 규정 변경 웹훅 수신 서비스 키. 비면 항상 401(`backend/api/recalls.py:42`) |
| 환경변수 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google 로그인. 하나라도 비면 `/auth/google/start`가 `/login?oauth_error=google_unavailable`로 돌려보낸다(아래 "Google 로그인 설정", `docs/specs/login.md`) |
| 환경변수 | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | 트레이스. 키 두 개가 있으면 켜진다 |
| 환경변수 | `LLM_RESPONSE_CACHE`, `LLM_RESPONSE_CACHE_SIZE` | LLM 응답 캐시(G-08). 비우면 꺼진다. 운영과 최종 측정에서는 켜지 않는다(아래 "운영 재배포", `backend/services/services.md`) |
| 환경변수 | `LLM_MAX_TOKENS` | LLM 호출 1건의 출력 상한(`backend/services/llm.py:188`, 기본 2500, 평가 전용 단일 검토 경로만 4000). 운영 판 `provena-api-00202-rid`, `provena-api-00205-zit`(2026-11-17 16:58~18:50 KST), `provena-api-00217-kew`(18:50 KST 승격)와 지금 서비스 판 `provena-api-00149-cm2`에 `2500`으로 명시(결정 0129, 0131, 0134, 0137) |
| 환경변수 | `DAILY_QUESTION_LIMIT` | 사람당 하루 질문 한도(`backend/api/daily_limit.py:38`, 기본 50, 0이면 끔, KST 0시 기준, DB의 질문 기록으로 셈, 넘으면 `/chat` 429 `daily_limit`). 운영 판 `provena-api-00202-rid`, `provena-api-00205-zit`, `provena-api-00217-kew`는 남은 유료 측정 동안 `0`이었고, 2026-11-17 18:59 KST 무렵 `50`으로 바꿨다. 환경 변수를 바꾸면 새 리비전이 생기므로 지금 서비스 판은 00217-kew와 같은 이미지·코드·그 밖의 설정에 이 값만 다른 `provena-api-00149-cm2`다 |
| 비밀값(Secret Manager) | `MCP_EXTERNAL_TOKEN` | 외부 연동용 MCP 토큰(`extras/mcp_skill/mcp_server/server.py:532`). 이 토큰만 분당 30·하루 500회로 제한하고 넘으면 429 `rate_limited`와 `Retry-After`, 내부 `MCP_TOKEN`은 제한 없음(결정 0129). 한계: 세는 곳은 인스턴스마다의 프로세스 메모리라 재시작하면 0부터 다시 세고, 인스턴스가 N개면 실제 상한은 N배다. 운영 실행 설정은 `--max-instances 1`(00202-rid·00205-zit·00217-kew·00149-cm2 최대 인스턴스 1)이라 지금은 서비스 전체 값과 같다 |
| 환경변수 | `QUESTION_GRAPH_MODE` | `/chat` 질문 그래프 구조(`backend/main.py:279`). `single`(코드 기본) 또는 `multi`(서비스 값, `backend/graph/service_profile.py`), 다른 값이면 서버가 시작하지 않는다. 되돌리기는 `single` 또는 `off`(결정 0131). 2026-11-17 16:58 KST부터 서비스 판 `provena-api-00205-zit`, 18:50 KST에 승격한 `provena-api-00217-kew`, 지금 서비스 판 `provena-api-00149-cm2`는 `multi`이고, 그 전 서비스 판 `provena-api-00202-rid`는 이 스위치 전 코드다 |
| 환경변수 | `GRAPH_SPLIT_VOTE_WAIT_S` | 근거 충분 판정에서 충분·일부로 갈린 두 표 뒤 셋째 표를 기다리는 상한(초, `backend/graph/answer_fixes.py` `split_vote_wait_s`, 코드 기본 빈 값, 서비스 값 `1.0`, 서비스 판 `provena-api-00205-zit`, `provena-api-00217-kew`, `provena-api-00149-cm2`에 `1.0`). 결정 0132, `docs/specs/question-graph.md` 같은 이름의 절 |

- 위 표는 코드에서 `os.getenv`·`os.environ`으로 읽는 이름 가운데 배포·기동에 직접 걸리는 것만 골랐다. 검색·LLM 세부 변수는 `docs/specs/search.md`, `docs/specs/llm.md` 표가 정본이다.

### 운영 재배포

명령은 `README.md`의 "Cloud Run 재배포"에 있다(`gcloud run deploy provena-api --source . --project provena-team --region asia-northeast3 --port 8000 --allow-unauthenticated --max-instances 1`).

- `--allow-unauthenticated`는 서비스 주소를 인증 없이 열어 두는 설정이다. 사용자 구분은 앱의 로그인(`/auth/login`)이 한다.
- `--max-instances 1`은 인스턴스를 최대 1개로 제한한다. 승인 결정(`POST /approvals/{approval_id}`)의 동시 요청 잠금은 Postgres 자문 잠금이라 인스턴스가 여럿이어도 막힌다(로컬에서 같은 DB를 보는 서버 프로세스 2개로 시험, `tests/test_decision_multi_instance.py`). 배포 서비스에서 2개 이상으로 시험한 적은 없고, 로그인 실패 제한 같은 프로세스 안 기록은 인스턴스 사이에서 공유되지 않으므로(`docs/specs/login.md`) 이 값을 올리기 전에 그 부분을 따로 확인한다.
- `.gcloudignore`가 없어 소스 업로드 대상은 `.gitignore`를 따른다. `.env`는 `.gitignore`에 있어 올라가지 않으므로 값은 서비스의 환경변수와 Secret Manager로 따로 넣는다.
- `PROVENA_ENV`, `PROVENA_DEV_MODE`는 배포에서 설정하지 않는다(로컬 데모 전용 스위치, `.env.example`).
- `LLM_RESPONSE_CACHE`는 운영과 최종 측정에서 켜지 않는다. 운영 `/chat` 측정은 `metadata.eval`이 없어 캐시를 건너뛰지 않으므로 켜면 적중 때 응답 시간·토큰 집계(적중 응답은 토큰 0)가 바뀌어 측정값이 오염된다(2026-11-12 조장 리뷰(#132)에서 확정).
- 비밀값(`AUTH_SECRET`, `DATABASE_URL`, `DATABASE_DIRECT_URL`, `LLM_API_KEY`, `VOYAGE_API_KEY`, `GOOGLE_CLIENT_SECRET`, `LANGFUSE_SECRET_KEY`, `PROFILE_ENC_KEYS`, `MCP_TOKEN`)은 Secret Manager에 두고 서비스에 연결한다. 운영 서비스의 연결 상태는 아래 "남은 점"에 적었다.
- 운영 DB(Supabase)의 스키마와 확인 결과는 `db/db.md`를 따른다. LangGraph 체크포인트·Store 표는 앱 첫 기동 때 만들어진다.

### Google 로그인 설정

코드는 구현돼 있다(`backend/auth.py`의 OAuth 흐름, `backend/services/auth_store.py`의 `get_or_create_google_user`, `db/114_google_identities.sql`). **아래 설정과 운영 마이그레이션 적용은 조장이 한다.** 저장소의 코드 변경만으로는 배포에서 Google 로그인이 켜지지 않는다.

1. Google Cloud 콘솔 > API 및 서비스 > 사용자 인증 정보에서 OAuth 클라이언트 ID(웹 애플리케이션)를 만든다.
2. 승인된 리디렉션 URI에 배포 주소 뒤 `/auth/google/callback`(배포)과 `http://localhost:8000/auth/google/callback`(로컬) 두 개를 넣는다.
3. OAuth 동의 화면이 "테스트" 상태이면 **테스트 사용자**에 로그인할 Google 계정을 추가한다(없으면 그 계정은 동의 화면에서 막힌다).
4. Cloud Run에 환경 변수 3개를 넣는다: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`(Secret Manager), `GOOGLE_REDIRECT_URI`(위 배포 URI와 같은 값). 로컬은 같은 3개를 `.env`에 둔다(`GOOGLE_REDIRECT_URI`는 로컬 URI).
5. 운영 DB에 `db/114_google_identities.sql`을 적용한다(`101`·`106` 다음. 다시 돌려도 된다). 적용 전에는 Google 로그인 버튼이 "지금은 사용할 수 없습니다" 안내로 가고 비밀번호 로그인·가입·승인은 그대로 된다. 적용한 뒤 서버를 다시 시작한다.
6. 계정 연결 조건(같은 이메일의 인증·승인된 계정에 연결, 없으면 관리자 승인 대기 `google_signup_pending`)은 `docs/specs/login.md`의 "Google 로그인 계정 연결"을 따른다.

### 운영 DB 적용 순서

- 내 정보·사용자 관리를 쓰려면 배포 전에 운영 DB에 `db/104_user_profiles.sql`, `db/105_admin_role_log.sql`을 적용한다. `user_profiles` 표가 없으면 `/me`가 503이 되어 로그인 뒤 화면이 열리지 않는다.
- Google 로그인은 위 5번의 `db/114_google_identities.sql`이 필요하다. 그 밖의 적용 기록은 `db/db.md`에 있다.

## 남은 점

- 운영 서비스의 환경변수는 2026-11-16 `gcloud run services describe provena-api`로 이름만 읽어 확인했다(당시 운영 판 `provena-api-00079-tmt`, 값은 읽지 않음. 동결 판 `provena-api-00172-rex`와 2026-11-17 00:45 KST부터 09:15 KST 무렵까지의 서비스 판 `provena-api-00178-max`는 같은 이미지·같은 환경 변수 이름이고 00178-max는 LLM 키 비밀값만 새 비밀값으로 바꿨다. 2026-11-17 09:15 KST 무렵부터의 서비스 판 `provena-api-00181-zub`(main 코드 `9bc7d587`)는 00178-max와 이미지 digest·`commit` 라벨·빌드 주석만 다르고 환경 변수·비밀 참조·스케일·동시성은 같다(`evals/results/deploy_check_provena-api-00181-zub/describe_diff.txt`, 승격 기록 `evals/results/promote_provena-api-00181-zub/`)). 모두 27개이고 Secret Manager 참조가 13개(`AUTH_SECRET`, `DATABASE_URL`, `DATABASE_DIRECT_URL`, `LLM_API_KEY`, `VOYAGE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `SERVICE_API_KEY`, `RECALL_WEBHOOK_SECRET`, `PROFILE_ENC_KEYS`, `GOOGLE_CLIENT_SECRET`, `GMAIL_APP_PASSWORD`, `MCP_TOKEN`), 일반 값이 14개다. 모델을 고르는 변수는 `LLM_PROVIDER`(값 `anthropic`)뿐이고 `LLM_MODEL`, `EMBED_MODEL`, `RERANK_MODEL`은 없어 코드 기본값(`claude-haiku-5-5`, `voyage-4`, 리랭커 없음)을 쓴다(README "사용 모델").
- `DATABASE_DIRECT_URL`은 앱이 읽지 않고 스키마 적용 때만 쓴다. 2026-11-12 grep 결과 `backend/`의 파이썬 코드에는 읽는 곳이 없고 `.env.example`과 `tests/test_api_threads_store.py`에만 나온다.

## AC (Given-When-Then)

- **AC-01 새 clone 기동**: GIVEN `.env` 없는 새 clone, WHEN `docker compose up`, THEN db가 healthy가 되고 loader가 색인을 적재한 뒤 api가 `/health` 200을 낸다(`docs/GATES.md` G2의 실측 기록이 근거).
- **AC-02 배포 모드 필수 키**: GIVEN `PROVENA_ENV`가 local·demo가 아닌 실행, WHEN `AUTH_SECRET` 또는 `PROFILE_ENC_KEYS`가 없음, THEN 서버가 시작하지 않는다(`backend/main.py` 모듈 설명. 이 동작을 직접 확인하는 시험은 찾아 확인하지 못함).
- **AC-03 표와 코드 일치**: GIVEN 위 표, WHEN 각 이름을 `grep -rn`으로 찾음, THEN 코드 또는 `.env.example`에서 나온다.
