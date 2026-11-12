# Spec — 배포와 실행 모드 (현재 구현 기록)

이 Spec은 새로 만드는 기능이 아니라, 이미 있는 배포·실행 방식의 계약(어떤 파일에 기대고 어떤 환경변수를 읽는가)을 한곳에 적은 것이다(Q-07). 값과 절차의 정본은 `README.md`의 "Cloud Run 재배포"·"키 없이 뜨는 데모 모드"와 `docs/SDD.md` 7장이고, 여기서는 코드에서 확인한 읽는 위치만 적는다. 환경변수 값은 저장소에 적지 않는다.

## Why

- **페르소나**: 평가자(배포 주소와 `docker compose up`으로 확인), 배포를 올리는 조원
- **상황**: 실행 방식이 둘이다. 운영은 Cloud Run + Supabase, 데모는 `docker compose up`(키 없음, 녹화 재생)이다(`docs/SDD.md` 7장, `docs/GATES.md` G1·G2).
- **문제**: 배포가 기대는 파일과 환경변수가 README 표, SDD, 코드에 흩어져 있어 하나가 빠져도 알아채기 어렵다(검색 Spec `docs/specs/search.md`는 이미 표로 두었다).
- **측정 지표**: 위 두 게이트의 확인 기록(`docs/GATES.md`)

## Goal

- **해결 목표**: 배포·기동이 읽는 파일과 환경변수를 표 하나로 두고, 코드 줄을 달아 사라지거나 이름이 바뀌면 찾을 수 있게 한다.
- **성공 기준**: 아래 표의 모든 이름이 코드에서 grep으로 찾아지고, 표에 없는 배포 필수 변수가 README 표와 어긋나지 않는다(어긋남은 "남은 점"에 적는다).
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
| EC-03 | `VOYAGE_API_KEY` 없음 | 검색이 빈 결과(`no_key`)로 끝난다(`README.md` 환경변수 표) |

## How

### 의존 파일·환경변수

| 구분 | 이름 | 쓰는 곳 |
|---|---|---|
| 파일 | `Dockerfile` | 서비스 이미지. 웹 빌드(`node:22-alpine`) 뒤 `python:3.12-slim`에 `backend/`, `data/`, `web/`, `db/`, `skills/`, `extras/`, `mock_erp/`를 복사하고 이미지 안에서 원문·색인 스냅샷을 푼다. 실행은 `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`(`Dockerfile:60-65`) |
| 파일 | `docker-compose.yml` | 데모. `db`(`pgvector/pgvector:pg16`), `loader`(`python -m backend.rag.retrieve.load_snapshot`, `./data/index` 연결), `api`(포트 `${API_PORT:-8000}`). `.env.example`은 필수, `.env`는 있으면 덮는다 |
| 파일 | `.env.example` | 환경변수 이름·기본값 목록 |
| 파일 | `data/index.tar.gz`, `data/demo_replay/` | 검색 색인 스냅샷과 키 없는 데모의 녹화 재생(`docs/specs/search.md`, `data/data.md`) |
| 파일 | `db/*.sql` | 운영 DB 스키마. 운영에서는 사람이 적용한다(`README.md` "Google 로그인 설정"·내 정보 절, `db/db.md`) |
| 파일 | `.github/workflows/ci.yml` | `python -m pytest -q`와 `evals/ci_compare.py`를 Python 3.12에서 돌린다(키·네트워크 없음) |
| 파일 | `backend/main.py` | 환경변수를 시작할 때 읽고 모드를 정한다 |
| 환경변수 | `DATABASE_URL` | 운영 Supabase 풀러 연결 문자열, 데모는 compose가 로컬 db로 넣는다(`backend/main.py:261, 331`) |
| 환경변수 | `AUTH_SECRET` | 로그인 토큰 서명 키(`backend/main.py:118`) |
| 환경변수 | `PROFILE_ENC_KEYS` | 내 정보 암호화 키(`backend/services/profile_crypto.py:20`) |
| 환경변수 | `PROVENA_ENV`, `PROVENA_DEV_MODE`, `DEMO_MODE` | 로컬 데모 스위치. 배포에서는 설정하지 않는다(`backend/main.py:82, 160`, `README.md`) |
| 환경변수 | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | 생성 LLM과 키. 키가 없으면 가짜 모델(`backend/services/llm.py:576, 592`, `docs/specs/llm.md`) |
| 환경변수 | `VOYAGE_API_KEY` | 질문 임베딩(`docs/specs/search.md` 환경 변수 표) |
| 환경변수 | `SEARCH_WARMUP` | 시작 때 검색 준비를 기다릴지(`backend/main.py:143`). 운영 기본은 기다림, compose는 `background` |
| 환경변수 | `PROVENA_OWNER_LOGIN_ID` | 최고 관리자 로그인 아이디(`backend/main.py:338`, `docs/specs/admin-roles.md`) |
| 환경변수 | `PROVENA_DOCS_PUBLIC` | `0`이면 `/docs`·`/redoc`·`/openapi.json`을 끈다. 비우면 공개(`backend/main.py:372`) |
| 환경변수 | `MCP_TOKEN` | 있어야 HTTP MCP를 붙인다(`backend/main.py:253`, `docs/specs/mcp.md`) |
| 환경변수 | `TRUSTED_PROXY_HOPS` | 프록시 뒤 실제 접속 IP. 기본 0, Cloud Run은 1(`backend/auth.py:705`, `Dockerfile` 주석) |
| 환경변수 | `INDEX_URL`, `INDEX_SHA256` | 색인 압축이 저장소에 없을 때만 내려받는 주소와 해시(`backend/rag/retrieve/load_snapshot.py:204`) |
| 환경변수 | `SERVICE_API_KEY` | 규정 변경 웹훅 수신 서비스 키. 비면 항상 401(`backend/api/recalls.py:42`) |
| 환경변수 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google 로그인. 하나라도 비면 사용 불가 안내(`README.md`, `docs/specs/login.md`) |
| 환경변수 | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | 트레이스. 키 두 개가 있으면 켜진다(`README.md`) |

- 위 표는 코드에서 `os.getenv`·`os.environ`으로 읽는 이름 가운데 배포·기동에 직접 걸리는 것만 골랐다. 검색·LLM 세부 변수는 `docs/specs/search.md`, `docs/specs/llm.md` 표가 정본이다.

## 남은 점

- 배포 서비스에 실제로 어떤 환경변수가 들어 있는지, Secret Manager로 연결돼 있는지는 이 저장소에서 확인할 수 없다(`README.md`도 권장 사항이라고 적음). 확인 못 함.
- `DATABASE_DIRECT_URL`은 앱이 읽지 않고 스키마 적용 때만 쓴다고 README가 적었다. 2026-11-12 grep 결과 `backend/`의 파이썬 코드에는 읽는 곳이 없고 `.env.example`과 `tests/test_api_threads_store.py`에만 나온다.

## AC (Given-When-Then)

- **AC-01 새 clone 기동**: GIVEN `.env` 없는 새 clone, WHEN `docker compose up`, THEN db가 healthy가 되고 loader가 색인을 적재한 뒤 api가 `/health` 200을 낸다(`docs/GATES.md` G2의 실측 기록이 근거).
- **AC-02 배포 모드 필수 키**: GIVEN `PROVENA_ENV`가 local·demo가 아닌 실행, WHEN `AUTH_SECRET` 또는 `PROFILE_ENC_KEYS`가 없음, THEN 서버가 시작하지 않는다(`backend/main.py` 모듈 설명. 이 동작을 직접 확인하는 시험은 찾아 확인하지 못함).
- **AC-03 표와 코드 일치**: GIVEN 위 표, WHEN 각 이름을 `grep -rn`으로 찾음, THEN 코드 또는 `.env.example`에서 나온다.
