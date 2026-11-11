# 이 저장소에 미리 들어 있는 것

> 현재 상태(2026-11-11): 이 문서는 강사 템플릿이 처음 준 뼈대 설명이라 아래 파일 이름 중 일부는 3조 저장소와 다르다. `backend/rag/ingest.py`·`retrieve.py`는 `backend/rag/ingest/`·`backend/rag/retrieve/` 폴더로, `backend/memory.py`는 `backend/memory/profile.py`로, `db/init.sql`은 `db/01_init.sql`과 번호 SQL 파일들로 나뉘었고, `backend/`에는 `api/`·`schemas/`·`prompts/` 등이 더 있다. 지금 구조는 각 폴더의 `<폴더>.md`와 `docs/ARCHITECTURE.md`를 본다.

처음 열면 낯선 폴더가 여럿 보일 겁니다. **전부 비어 있는 뼈대**이고, 여러분이 채우는 자리입니다.
"어디에 둬야 하나"를 고민하는 데 시간을 쓰지 말라고 미리 잡아 두었습니다.
쓰지 않는 것은 **지워도 됩니다.** 폴더를 남겨두는 것 자체로 점수를 받지는 않습니다.

2차 프로젝트 서비스를 이어서 만든다면 LLM 호출부, compose 틀, Langfuse 설정은 그대로 가져오고, 아래 뼈대 위에 RAG와 LangGraph를 얹는 범위를 `docs/TOPIC.md`에 적으세요.

---

## 한눈에

```
backend/
  main.py             FastAPI 진입점 (/health 있음)
  graph/              LangGraph                                   ← G4
    state.py            그래프 상태 정의
    build.py            그래프 조립 (Supervisor, 서브에이전트, 체크포인트, interrupt)
  rag/                RAG                                         ← G3
    ingest.py           문서 파싱, 청킹, manifest 기록
    retrieve.py         하이브리드 검색, 리랭킹, 메타데이터 필터
  auth.py             로그인, 사용자 식별                          ← G4
  memory.py           사용자별 장기 기억                           ← G4
  services/llm.py     LLM 호출을 모으는 자리                       ← 중요
data/                 corpus/(원문 스냅샷), manifest               ← G3
evals/                평가셋 v1, v2, freeze.py, PREREGISTER.md     ← G5
tests/                회귀 테스트                                  ← CI
db/init.sql           pgvector 확장
docs/                 TOPIC, ARCHITECTURE, GATES, deliverables/, specs/
EVAL_REPORT.md        개선 전후 지표                               ← 제출물
extras/mcp_skill/     MCP 서버와 Skill                             ← 가산 선택
Dockerfile, docker-compose.yml, .env.example
```

---

## 파일별로 무엇을 하나

### `backend/services/llm.py` ← 가장 중요합니다

**LLM 호출은 전부 이 파일 하나로 모으세요.** 라우터나 그래프 노드가 `openai`를 직접 import하지 않게만 해도 충분합니다.

이유가 있습니다. 여기서 세 가지를 한 곳에서 처리해야 하기 때문입니다.

1. **Langfuse 트레이스**: 호출마다 입출력, 모델, 토큰, 지연, 비용이 남아야 합니다(G6).
2. **데모 모드**: `DEMO_MODE=1`이면 키 없이 기록해 둔 응답을 재생합니다(G2). 평가자는 키가 없습니다.
3. **비용 상한**: 키는 조당 하나이고 한도가 있습니다. 재시도와 루프에 상한을 두는 곳이 여기입니다.

### `backend/graph/`

LangGraph 상태 그래프가 들어갑니다. 11/5(D4)에 단일 에이전트 그래프를 만들어 기준 점수를 재고, 11/6(D5)에 Supervisor와 서브에이전트로 나눠 같은 평가셋으로 다시 잽니다. **단일을 건너뛰면 멀티가 나았다는 걸 증명할 기준이 없습니다.** 개선이 없었다면 없었다고 `EVAL_REPORT.md`에 적으세요.

### `backend/rag/`

문서 파싱(PDF, 표, 스캔 중 1종 이상), 청킹, 인덱싱, 하이브리드 검색, 리랭킹이 들어갑니다. 인덱스를 만들 때마다 `data/manifest.jsonl`에 청크와 문서 목록이 남아야 G3를 증명할 수 있습니다.

### `backend/auth.py`, `backend/memory.py`

로그인한 사용자 id로 대화(thread)와 장기 기억(Store namespace)을 나눕니다. 평가자는 평가용 계정 2개로 로그인해 두 사용자의 대화와 기억이 섞이지 않는지 봅니다(G4).

### `data/`

수집은 로컬에서 한 번 하고 **스냅샷(원문과 manifest)을 저장소에 커밋**하세요. 서버에서 호출이 막히는 소스를 피할 수 있고, 평가자가 같은 코퍼스로 재현할 수 있습니다. 파일이 수십 MB를 넘으면 강사에게 먼저 물어보세요.

### `evals/`

평가셋 v1(30건, 11/3 동결)과 v2(50건 이상, 11/6 동결)가 들어갑니다. 동결은 `python evals/freeze.py`로 sha256을 기록하는 것입니다. 바꾸기 전에 `PREREGISTER.md`에 "무엇을 바꾸고 어떤 지표가 얼마나 오를 것으로 기대하는지"를 먼저 적습니다.

### `tests/`와 CI

PR마다 `pytest`가 돌아갑니다. 평가 회귀 테스트(예: 핵심 질문 5개가 근거를 붙여 답하는지)를 여기에 넣으면 ④ 항목의 근거가 됩니다. GitHub Actions 무료 한도가 있으니, 무거운 평가 전체를 PR마다 돌리지 말고 샘플만 돌리세요.

### `EVAL_REPORT.md`

제출물이자 평가 근거 문서입니다. 숫자가 나빠도 괜찮습니다. **재고, 원인을 알고, 무엇을 시도했는지**가 평가 대상입니다. 버린 시도도 적으세요.

### `docker-compose.yml`

`api`(FastAPI)와 `db`(pgvector가 들어 있는 Postgres)가 들어 있습니다. 기본값은 `DEMO_MODE=1`이라 키 없이 뜹니다.

```bash
cp .env.example .env   # 실제 키는 .env에만
docker compose up      # 한 줄
```

> Apple Silicon(M1~M4)에서 이미지가 안 뜨면 `docker-compose.yml`의 `platform: linux/amd64` 주석을 해제해 보세요.

### `extras/mcp_skill/`

가산 선택(MCP와 Skill 통합)입니다. 둘 다 해야 인정되고, 3차에서 새로 한 통합만 인정됩니다. 하지 않을 조는 폴더를 지우세요.

---

## 이미 있던 것 (1차, 2차와 동일)

| 파일 | 역할 |
|---|---|
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 열 때 자동으로 뜨는 양식 |
| `.github/workflows/secret-scan.yml` | 키가 커밋되면 CI가 잡습니다 |
| `AGENTS.md`, `CLAUDE.md` | AI 에이전트 공통 지침 |
| `docs/specs/_example.md` | 기능을 에이전트에게 시키기 전 Spec을 쓰는 자리 |

---

## 처음 할 일

1. **README의 조원 소개 표에 자기 행을 추가**: 브랜치 → PR → 리뷰 → merge로. 첫 PR이 협업 흐름 연습입니다.
2. `cp .env.example .env` 후 `docker compose up`으로 `/health`가 뜨는지 확인
3. 주제서는 10/29까지 강사에게 별도 DM으로 제출하고, `docs/TOPIC.md`로 옮겨 둡니다
4. D0(10/30)에 빈 FastAPI를 Cloud Run에 올려 배포 주소 확보. 배포가 막히면 팀 전체가 멈춥니다.
5. 평가셋 v1 30건 만들기 (11/3 동결)
