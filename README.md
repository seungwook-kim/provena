# Provena (프로베나)

**정책 변경을 추적하는 엔지니어링 지식 AI 플랫폼.** IT 조직의 정책·런북을 섹션과 판 날짜를 붙여 인용해 답하고, 근거가 없으면 거절한다. 인용한 정책이 바뀌면 이미 나간 답을 다시 확인해 받은 사람에게 알리고, 승인 권한표는 사람이 승인한 결정표로만 판단한다.

KDT AI Human 7기 3차 팀 프로젝트 · 3조 · 김승욱(팀장), 박진형, 강경희

이 저장소는 **3차 프로젝트 조별 공간**입니다. 조원 전원이 write 권한을 갖습니다.

## 팀 정보

| 항목 | 내용 |
|---|---|
| 프로젝트 | proj3-c |
| 저장소 | https://github.com/aihuman-7th/proj3-c |
| 조 | 3조 |
| 주제와 산업 | IT: 정책 변경을 추적하는 엔지니어링 지식 AI (GitLab 공개 핸드북 기반) |
| 배포 주소 | https://provena-api-cttaanqntq-du.a.run.app |
| 팀 작업 지침서 | [docs/TEAM_GUIDE.md](./docs/TEAM_GUIDE.md) |
| 정본 문서 (SPEC) | [docs/SPEC.md](./docs/SPEC.md) |
| 임베딩 측정 기록 | [docs/embedding_measurement.md](./docs/embedding_measurement.md) |

## 팀 (3조)

| 이름 | GitHub | 역할 |
|---|---|---|
| 김승욱 | @seungwook-kim | 팀장 · 테크 리드 · 풀스택 |
| 박진형 | @jinyeong-731 | 검색·데이터 담당 (수집·파싱·청킹·검색·FastMCP) |
| 강경희 | @kkh-hue | 서비스 담당 (로그인·웹 화면·첫 배포) |

GitHub와 역할 칸은 각자 자기 줄을 채운다(브랜치 → PR → 리뷰 → merge).

## 무엇을 만드나

**문제.** 개발·SRE·보안·IT 운영 담당자는 일하다가 회사 정책과 런북을 보고 승인권자, 절차, 기한을 판단한다(SaaS 도입, 배포, 장애 대응, 보안 검토). 답을 찾는 데 시간이 들고 담당자 답을 기다리며 흐름이 끊긴다. 정책이 바뀌어도 예전에 받은 답(AI 답 포함)은 그대로 남아 바뀐 절차를 모르고 일하게 된다.

**해결.** 질문하면 정책 원문에서 근거를 찾아 섹션과 판 날짜를 붙여 답한다. 근거가 없으면 거절한다. 정책이 바뀌면 그 섹션을 인용한 답을 찾아 결론이 바뀌었는지 다시 판정하고, 바뀐 답은 받은 사람과 업무시스템에 알린다.

```
질문   외부 SaaS 비용 3만 달러, 누구 승인이 필요한가?

답     업무 승인: (결정표가 고른 직위)
       재무 승인: (결정표가 고른 직위)
       근거  (핸드북 섹션) (판 날짜)

변경   해당 정책 섹션이 바뀜
       → 이 섹션으로 답을 받은 사람에게 "전에 받은 답의 결론이 바뀌었습니다" 알림과 새 근거
```

(위 출력은 형식 예시다. 실제 값은 승인된 결정표와 정책 원문에 따라 달라진다.)

**데이터.** GitLab이 회사 운영 문서로 공개한 핸드북(영어 Markdown, CC BY-SA 4.0)에서 IT·플랫폼 절을 고른다. 고정 커밋 `129243bc`(2026-10-27)에서 고른 1,564쪽과 2023 권한표, 문서 1,565건을 제목 단위로 잘라 청크 23,095개, 본문 sha256 기준 서로 다른 청크 22,378개다(`data/data.md`). 질문은 한국어로 하고 근거 문서는 영어여도 된다.

### 기존 제품과 다른 점

| 차별점 | Provena | 기존 제품 |
|---|---|---|
| 답변 리콜 | 바뀐 섹션을 근거로 **이미 나간 답을 받은 사람에게** 예전 답을 다시 검증해 알린다 | Guru·Glean·Notion은 검증 기한이 지난 문서를 문서 담당자·소유자에게 알린다. 답을 받은 사람에게 다시 알린다는 내용은 문서에서 찾지 못했다 |
| 결정표 승인 | 승인 권한표를 결정표로 바꾸고 **사람이 승인한 뒤에만** 판단에 쓴다. 금액 판단은 코드가 한다 | Moveworks·ServiceNow는 금액별 결재 흐름 엔진이 있다. 정책에서 뽑은 표를 사람이 승인한 뒤 답에 쓰는 단계는 문서 기준으로 찾지 못했다 |

"찾지 못했다"는 확인한 문서 기준(2026-10-28)이고, 없다고 증명한 것은 아니다.

### 데모 (예정)

| 구간 | 보여주는 것 |
|---|---|
| 01 | 승인권자 질문: 외부 SaaS 금액 구간에 맞는 업무 승인·재무 승인 권한자와 근거 섹션·판 날짜 |
| 02 | 보안 검토·장애 대응 질문: 한국어 질문에 영어 핸드북 섹션을 인용한 답 |
| 03 | 답변 리콜: 정책 변경을 넣으면 그 섹션으로 답을 받은 사람과 업무시스템에 알림이 간다 |
| 04 | 결정표 승인: 승인 권한표를 결정표 초안으로 바꾸고, 사람이 승인한 뒤에만 판단에 쓴다 |
| 05 | 팀 합동 검토: 보안·인프라·IT 운영·재무 관점 쟁점표 (Supervisor + 팀 에이전트) |
| 06 | 거절: 근거가 없거나 비공개(internal) 문서, 고른 판 범위 밖 질문은 답하지 않는다 |

**만들지 않는 것:** 실제 회사 시스템(배포·구매) 연동, 회사 내부망 배포, GitLab 비공개(internal) 문서, 결재 상신.

### 목표 지표

기준값은 D0(10/30)에 합의해 동결했다. 측정한 지표는 값을 채웠고, "미측정"은 [EVAL_REPORT.md](./EVAL_REPORT.md)에 이 기준으로 잰 값이 아직 없는 지표다.

| 지표 | 기준 | 결과 |
|---|---|---|
| 검색 Recall@5 | 0.80 이상 | 미측정 |
| 인용 정확도 | 0.85 이상 | v2 50건 최종 3회 평균 단일 1.000, 멀티 0.992 ([EVAL_REPORT.md](./EVAL_REPORT.md) 4장) |
| 비관련 질문 거절 | 0.90 이상 | v2 50건 최종 3회 평균 단일·멀티 모두 1.000 (4장) |
| 판 날짜 표시 | 100% | 미측정 |
| 답변 리콜 | 재현율·정밀도 0.80 이상 | 미측정 |
| 결정표 | 승인 전 실행 0건, 셀 정확도 공개 | 미측정 |
| 신뢰 경계 | 결정표 기준 변경·승인 우회·유출 뚫림 0건 | 시험 30건 기본 모드 뚫림 0, 실제 모델(Haiku 5.5) 뚫림 0 (6장). 코드로 막지 못하는 경로는 6장에 한계로 적음 |
| 응답 시간 | 전체 p95 10초 이하 | v2 50건 최종 3회 평균 p95 단일 9.806초, 멀티 9.695초 (4장, Anthropic API로 측정. 배포 서비스의 공급자는 OpenRouter) |
| 비용 | 질문 1건 평균 $0.01 이하 | 50건 회당 단일 0.261달러, 멀티 0.250달러(4장). 질문 1건 평균은 약 0.005달러로 계산한 값 |

### 평가셋

| 버전 | 파일 | 동결 | 건수 |
|---|---|---|---|
| v1 | `evals/dataset_v1.jsonl` | 11/1 동결(기한 11/3 D2), sha256 `174996b9…f4332` | 30건 (관련 15, 비관련 15) |
| v2 | `evals/dataset_v2.jsonl` | 11/2 동결, 11/7 38번 정답 수정으로 재동결(결정 0075), sha256 `810d01f1…24d9f` | 50건 (관련 25, 비관련 25), v1 30건은 그대로 |

- 문항 형식은 `evals/dataset_v1.jsonl`의 예시를 따른다. `kind` 칸으로 관련(`relevant`)과 비관련(`irrelevant`)을 나눈다.
- 정답은 초안 작성자가 아닌 두 사람(박진형, 강경희)이 따로 판정한다. 위치가 다른 문항은 두 판정자가 질문과 기대 답만 보고 합의해 `final_gold`에 적고, 팀장은 형식(정답 위치가 청크에 있는지)만 확인한 뒤 동결한다. 판정자에게는 검색 결과를 보여 주지 않는다.
- 동결: `python evals/freeze.py dataset_v1.jsonl` (sha256과 건수를 `evals/FROZEN.json`에 기록). 확인: `python evals/freeze.py --check`. PR마다 CI(`tests/test_frozen_evals.py`)가 동결한 파일이 바뀌었는지 검사한다.
- 동결한 평가셋은 고치지 않는다. 동결 파일은 글자 그대로 해시하므로 줄 순서나 공백만 바꿔도 바뀐 것으로 잡힌다.
- 검색이나 그래프를 바꾸기 전에 `evals/PREREGISTER.md`에 기대를 먼저 적는다. 자세한 규칙은 [evals/README.md](./evals/README.md).

## 실행 방법 (docker compose up)

평가자는 API 키가 없으므로 키 없이 뜨는 **데모 모드**가 기본이다. 필요한 것은 Docker(Compose v2)뿐이다.

```bash
git clone https://github.com/aihuman-7th/proj3-c.git
cd proj3-c
docker compose up          # .env 없이도 뜬다. 처음에는 이미지를 빌드해서 시간이 걸린다
```

1. 브라우저에서 http://localhost:8000 을 연다(로그인 화면으로 이동한다). 상태 확인은 http://localhost:8000/health 이다.
2. **로컬 데모 계정**으로 로그인한다. 아이디는 `demo-user`(일반 사용자), `demo-admin`(관리자)이다. 비밀번호는 [.env.example](./.env.example)의 `DEMO_USER_PASSWORD`, `DEMO_ADMIN_PASSWORD` 값이고, 바꾸려면 `.env`에 같은 이름으로 적는다([.env.example](./.env.example) 참고).
3. 끝내려면 `docker compose down`, 데이터까지 지우려면 `docker compose down -v`.

8000번 포트를 이미 쓰고 있으면 `.env`에 `API_PORT=8001`처럼 적고 그 포트로 연다.

검색 색인은 `data/index.tar.gz` 한 파일로 저장소에 들어 있고, 풀린 `data/index/`(`meta.json`, `chunks.jsonl`, `links.jsonl`, `vectors/`)는 커밋하지 않는다. `docker compose up`을 하면 압축이 자동으로 풀리고, `loader` 서비스가 `python -m backend.rag.retrieve.load_snapshot`으로 `data/index/`를 DB에 한 번 적재한 뒤 `api`가 뜬다.

- 새로 clone하면 `data/index.tar.gz`가 들어 있어 따로 넣을 것이 없다. loader는 `data/index/meta.json`이 없을 때 이 압축을 풀고 파일마다 `meta.json`의 sha256과 대조한다. 압축 파일이 없을 때만 `.env`에 `INDEX_URL`(색인 tar.gz 주소)과 `INDEX_SHA256`(그 파일의 sha256 64자)을 함께 적으면 loader가 받은 파일을 `INDEX_SHA256`과 대조한 뒤 `data/index/`에 푼다. 색인을 고치고 다시 압축하는 순서는 `data/data.md`의 "검색 색인 스냅샷 쓰는 법"에 있다.
- 색인을 직접 만들 때는 `python -m backend.rag.retrieve.index build`(임베딩 모델 필요)를, 비교 실험 캐시를 옮길 때는 `python -m backend.rag.retrieve.index import --from data/index_exp`를 쓴다(`backend/rag/retrieve/index.py`).
- 색인을 넣은 뒤 `docker compose up`을 다시 하면 loader가 적재한다. 같은 스냅샷이 이미 적재돼 있으면 몇 초 안에 끝난다.
- `data/index/`, `data/index.tar.gz`, `INDEX_URL`이 모두 없으면 loader는 적재를 건너뛰고 서버는 그대로 뜬다. 이때 질문은 오류 없이 "검색 색인이 아직 준비되지 않아 답할 수 없습니다."라는 거절로 끝난다.

### 키 없이 뜨는 데모 모드

- `DEMO_MODE=1`(기본)이면 LLM 키 없이 기록해 둔 응답(`data/demo_replay/`)을 재생하고, 기록이 없는 호출은 결정적 가짜 응답으로 대신한다. 검색 색인은 위 절차대로 `loader`가 `data/index.tar.gz`(없으면 `INDEX_URL`)를 풀어 적재하며, 색인이 없으면 질문은 거절로 끝난다(상태는 [docs/GATES.md](./docs/GATES.md) G2).
- 녹화는 LLM 응답과 질문 임베딩(voyage-4 벡터) 두 가지다. 키가 없으면 새 질문의 벡터를 만들 수 없으므로, **녹화한 질문만 키 없이 답이 나온다.** 녹화에 없는 질문은 "검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다."라는 거절로 끝난다. 다른 질문을 시험하려면 `.env`에 `LLM_API_KEY`와 `VOYAGE_API_KEY`를 넣고 `DEMO_MODE=0`으로 바꾼다.
- 키 없이 인용 답이 나오는 질문(녹화 2026-11-09, `data/demo_replay/recorded.jsonl`). 글자가 같아야 재생된다(공백 차이는 무시).
  - 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?
  - CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?
  - 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?
  - EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?
  - 외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요? (데모 구간 01, 승인 권한표 2023-05판 인용)
- 키 없이 거절이 나오는 질문(녹화에도 거절): "구매 승인에는 어떤 승인자가 필요한가요?"(핸드북에 승인자 근거가 없다), "오늘 점심 메뉴 추천해줘"(범위 밖). 구간 01의 금액만 바꾼 질문(3만 달러, 10만 달러)도 녹화했으나 근거를 찾지 못해 거절로 끝난다.
- 재생하는 답은 같은 색인(`data/index.tar.gz`)에서 녹화한 것이다. 색인이나 프롬프트를 바꾸면 다시 녹화한다: 새 DB(`docker compose down -v` 뒤)에서 키를 넣은 `.env`에 `DEMO_MODE=0`, `LLM_RECORD=1`을 적고 서버를 띄워 같은 질문을 `/chat`으로 보낸다(서버가 쓰는 프롬프트 그대로 `data/demo_replay/recorded.jsonl`에 쌓인다. 이미 있으면 지우고 시작한다).
- DB는 compose가 띄우는 로컬 pgvector 컨테이너이고 Supabase 계정이 필요 없다.
- 로그인은 필수이므로 데모 모드에는 **데모 전용 계정 2개**(user, admin)가 들어 있다. `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1`이 모두 켜진 로컬 실행에서만 시작할 때 만들어지고, 그 밖의 모드(배포)에서는 만들지 않는다.
- 데모 계정 값은 내 PC용 공개 데모 값이다. 서명 키(`AUTH_SECRET`)는 저장소에 두지 않고, 비워 두면 로컬 데모 모드에서만 실행할 때마다 무작위로 만든다(재시작하면 다시 로그인). 배포(Cloud Run)와 제출하는 평가용 계정은 이 값과 다르고 저장소에 적지 않는다.
- 실제 모델로 호출하려면 `.env`에 키를 넣고 `DEMO_MODE=0`으로 바꾼다. 키는 `.env`에만 둔다(커밋 금지).

### Cloud Run 재배포

배포 서비스는 Google Cloud Run의 `provena-api`이다. 프로젝트는 `provena-team`, 리전은 `asia-northeast3`, 컨테이너 포트는 8000이고 소스 배포로 올린다. 배포 담당 조원이 알려 준 재배포 명령은 다음과 같다.

```bash
gcloud run deploy provena-api --source . --project provena-team --region asia-northeast3 --port 8000 --allow-unauthenticated --max-instances 1
```

- `--allow-unauthenticated`는 서비스 주소를 인증 없이 열어 두는 설정이다. 사용자 구분은 앱의 로그인(`/auth/login`)이 한다.
- `--max-instances 1`은 인스턴스를 최대 1개로 제한한다. 승인 결정(`POST /approvals/{approval_id}`)의 동시 요청 잠금은 Postgres 자문 잠금이라 인스턴스가 여럿이어도 막힌다(로컬에서 같은 DB를 보는 서버 프로세스 2개로 시험, `tests/test_decision_multi_instance.py`). 다만 배포 서비스에서 2개 이상으로 시험한 적은 없고, 로그인 실패 제한 같은 프로세스 안 기록은 인스턴스 사이에서 공유되지 않으므로([docs/specs/login.md](./docs/specs/login.md)) 이 값을 올리기 전에 그 부분을 따로 확인한다.
- `.gcloudignore`가 없어 소스 업로드 대상은 `.gitignore`를 따른다. `.env`는 `.gitignore`에 있어 올라가지 않으므로 값은 서비스의 환경변수로 따로 넣는다.
- `PROVENA_ENV`, `PROVENA_DEV_MODE`는 배포에서 설정하지 않는다(로컬 데모 전용 스위치, `.env.example`).
- 운영 DB(Supabase)의 스키마와 2026-11-09 확인 결과는 [db/db.md](./db/db.md)를 따른다. LangGraph 체크포인트·Store 표는 앱 첫 기동 때 만들어진다.

배포에 필요한 환경변수 이름은 다음과 같다. 값은 이 저장소에 적지 않는다.

| 이름 | 용도 |
|---|---|
| `AUTH_SECRET` | 로그인 토큰 서명 키(32바이트 이상). 없으면 배포 모드에서는 서버가 시작하지 않는다 |
| `DATABASE_URL` | 운영 Supabase 풀러 연결 문자열. 이 값이 있어야 로그인, `/chat`, `/threads`, `/me/memory`가 붙는다 |
| `DATABASE_DIRECT_URL` | 직접 연결 문자열. 스키마 적용처럼 오래 걸리는 작업에만 쓰고 앱은 읽지 않는다 |
| `LLM_PROVIDER`, `LLM_API_KEY` | LLM 호출 방식과 키. 키가 없으면 가짜 모델을 쓴다 |
| `VOYAGE_API_KEY` | 질문 임베딩 키. 없으면 검색은 빈 결과(`no_key`)로 끝난다 |
| `SEARCH_DECOMPOSE` | 질문 분해(1이면 켬) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google 로그인(OAuth). 셋 중 하나라도 비면 Google 로그인은 설정 오류가 된다 |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Langfuse 트레이스. 키 두 개가 있으면 켜진다 |
| `PROFILE_ENC_KEYS` | 내 정보(`/me/profile`) AES-256-GCM 키(`backend/services/profile_crypto.py`). 형식 `번호:base64(32바이트)`, 쉼표로 여러 개. 없거나 형식이 틀리면 배포 모드에서는 서버가 시작하지 않는다 |
| `PROVENA_OWNER_LOGIN_ID` | 최고 관리자 로그인 아이디(`/admin/users`, `docs/specs/admin-roles.md`). 비었거나 그 계정이 admin·활성이 아니면 사용자 관리만 403이고 나머지는 정상 |

내 정보·사용자 관리를 쓰려면 배포 전에 운영 DB에 `db/104_user_profiles.sql`, `db/105_admin_role_log.sql`을 적용한다. `user_profiles` 표가 없으면 `/me`가 503이 되어 로그인 뒤 화면이 열리지 않는다.

비밀값(`AUTH_SECRET`, `DATABASE_URL`, `DATABASE_DIRECT_URL`, `LLM_API_KEY`, `VOYAGE_API_KEY`, `GOOGLE_CLIENT_SECRET`, `LANGFUSE_SECRET_KEY`, `PROFILE_ENC_KEYS`)은 Secret Manager에 두고 서비스에 연결하는 방식을 권장한다. 권장 사항이며, 현재 배포 서비스가 그렇게 설정돼 있는지와 서비스의 현재 상태(환경변수 설정, 최신 `main` 반영 여부)는 2026-11-09에 확인하지 못했다(미확인).

### 테스트

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
pytest -q
```

## 데이터 출처와 라이선스

시연 데이터는 GitLab이 공개한 핸드북(https://handbook.gitlab.com, 소스 https://gitlab.com/gitlab-com/content-sites/handbook)이다. 핸드북 본문은 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)으로 공개되어 있고, 이 저장소의 원문 스냅샷은 `data/` 아래에 코드와 폴더를 나눠 두며 고지와 출처는 `data/LICENSES/`에 있다. 답에 원문을 보일 때는 페이지 URL, 라이선스, 수정 여부를 함께 표시한다.

**이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다.** GitLab 로고를 쓰지 않으며 "GitLab 핸드북 기반 데모"라는 사실만 밝힌다.

## 조원 소개: 첫 과제

**조원 각자가 자기 행을 브랜치 → PR → 리뷰 → merge로 직접 추가하세요.** (전원 필수)
이 첫 PR이 협업 흐름 연습입니다. 같은 표를 여러 명이 수정하면 충돌이 날 수 있는데, 그것까지가 연습입니다(아래 "충돌이 났을 때" 참고).

| 이름 | GitHub | 역할 | 맡는 축 | 한마디 |
|---|---|---|---|---|
| 김승욱(팀장) | [@seungwook-kim](https://github.com/seungwook-kim) | 테크 리드 · 풀스택 | ③ 에이전트 | |
| 강경희 | [@kkh-hue](https://github.com/kkh-hue) | 서비스 (로그인·웹 화면·첫 배포) 담당 | 서비스 개발 | 잘 부탁드립니다. |
| 박진형 | [@jinyeong-731](https://github.com/jinyeong-731) | 검색·데이터 (수집·파싱·청킹·검색·FastMCP) 담당 | ② RAG 품질 | 잘 부탁드립니다. |

## 일정

| 날짜 | 해야 할 일 |
|---|---|
| 10/29(목) | 주제서 1장 제출 (강사에게 별도 DM. 제출한 내용을 `docs/TOPIC.md`로 옮겨 둔다) |
| 10/30(금) 오후 | 킥오프(D0). 빈 FastAPI가 compose로 뜨고 배포 주소가 열린다 |
| 11/3(화) | 평가셋 v1 30건 사람 판정과 동결, 베이스라인 점수 |
| 11/6(금) | 평가셋 v2 50건 이상 동결, Supervisor와 서브에이전트 분리, 중간 점검 |
| 11/16(월) 24:00 | 코드와 설정 동결 |
| 11/17(화) 24:00 | 최종 제출 |
| 11/18(수) | 발표와 수료식 |

일별 목표는 3차 프로젝트 가이드의 일정 표를 따릅니다. 이 표는 이 저장소에서 꼭 지켜야 할 날짜만 뽑았습니다.

## 필수 게이트 (못 지키면 해당 점수만큼 고정 감점)

| 번호 | 조건 | 감점 |
|---|---|---:|
| G1 | 배포된 주소가 있고 평가용 계정으로 핵심 시나리오를 끝까지 볼 수 있다(또는 영상) | -5 |
| G2 | `docker compose up` 한 줄로 10분 안에 뜬다(키 없이 뜨는 데모 모드 포함) | -5 |
| G3 | 서로 다른 청크 1만 개 이상, 서로 다른 문서 50건 이상, 문서 파싱 1종 이상 | -10 |
| G4 | LangGraph 상태 그래프, 멀티에이전트 최소형(Supervisor와 서브에이전트 2개 이상), 체크포인트, 사람 승인(interrupt), 로그인과 사용자별 기억 | -10 |
| G5 | 평가셋 50건 이상으로 개선 전후를 두 번 이상 재서 회귀를 숫자로 보인다 | -10 |
| G6 | Langfuse(또는 동급)로 트레이스가 남고 평가 점수가 연결된다 | -5 |
| G7 | README, `.env.example`, 비밀값 커밋 없음, 3분 이내 시연 영상(정상 경로와 실패 경로) | -5 |

각 게이트를 이 저장소 어디에서 채우는지는 **[docs/GATES.md](./docs/GATES.md)**에 있습니다. 정의의 정본은 3차 프로젝트 가이드입니다.

## 협업 규칙 (필독)

1. **`main`에 직접 push 금지**: 모든 변경은 브랜치 → PR로만 합칩니다.
2. **`main`에서 바로 작업하지 않고, 자기 브랜치에 커밋하고 push합니다.** 브랜치는 한 사람당 하나, 자기 이름으로 만듭니다(예: `seunguk`). 작업 종류별 브랜치는 만들지 않습니다. 자세한 규칙은 [docs/TEAM_GUIDE.md](./docs/TEAM_GUIDE.md) 5장.
3. PR은 **조원 1명 이상의 approve를 받은 뒤** merge합니다. 리뷰 없는 merge는 감사 리포트에 잡힙니다.
4. **제출물 = 마감 시점의 `main`**: 마감 시각에 강사가 전체 조 저장소에 태그를 일괄 생성합니다. 태그 이후 커밋은 평가 대상이 아닙니다.
5. **커밋은 본인 계정으로**: 자기가 한 작업은 자기 계정으로 커밋해야 이 저장소가 본인 포트폴리오 증빙이 됩니다. 함께 작업했다면 커밋 메시지에 `Co-authored-by:`를 추가하세요.
6. 다른 조 저장소도 읽을 수 있습니다. 보고 배우는 것은 권장, 복사 제출은 금지입니다.
7. **동결한 평가셋은 고치지 않습니다.** v1과 v2를 동결한 뒤에 정답을 바꾸면 측정이 아니라 맞추기가 됩니다(`evals/README.md`).

## 폴더 구조

```
backend/              FastAPI 서버
  main.py, auth.py      진입점(/health)과 라우트, 로그인                    (G4)
  schemas/              파트 사이 데이터 형식 (3명 승인)
  graph/                질문 그래프, Supervisor와 팀 에이전트, 결정표, 리콜  (G4)
  rag/ingest/           수집, 파싱, 청킹, 증분 수집                         (G3)
  rag/retrieve/         임베딩, 하이브리드 검색, 리랭킹                      (G3)
  memory/               사용자별 장기 기억 (Store namespace)                (G4)
  services/llm.py       LLM 호출은 여기 한 곳. 데모 모드 재생도 여기       (G2, G6)
skills/               런타임 Skill (가산)
extras/mcp_skill/     FastMCP 서버 (가산)
web/                  화면
mock_erp/             업무시스템 목업
data/                 corpus.tar.gz 원문 스냅샷, manifest, LICENSES/      (G3)
evals/                평가셋(dataset_v1·v2.jsonl), freeze.py·FROZEN.json, 사전 등록, 평가 실행기 (G5)
tests/                회귀 테스트 (CI가 PR마다 실행)
db/                   pgvector 확장, 데모 계정 시드
docs/                 주제서, 아키텍처, 게이트 점검, 제출물, Spec, 팀 작업 지침서
EVAL_REPORT.md        개선 전후 지표 (제출물)
Dockerfile, docker-compose.yml   `docker compose up` 한 줄 실행
```

파일 단위 전체 트리와 폴더 주인은 [docs/TEAM_GUIDE.md](./docs/TEAM_GUIDE.md) 5장에 있습니다. 템플릿 자리(`docs/SCAFFOLD.md`)를 따르되, `rag/ingest.py`·`retrieve.py`와 `memory.py`는 폴더로 나눴습니다.

### 에이전트 구조와 한계

- 서비스(`/chat`)가 쓰는 그래프는 단일 질문 그래프(`backend/graph/build.py`의 `build_graph`) 하나다. 질의 분석(`classify`)이 질문을 정책 질문, 결정표, 팀 합동 검토, 도메인 밖 거절로 갈라 보낸다(`backend/main.py`의 `build_question_graph`).
- Supervisor와 서브에이전트 3개(검색·작성·검증)로 나눈 멀티 그래프(`backend/graph/multi.py`)는 정책 질문 경로에서 **단일 그래프와 같은 노드와 프롬프트를 Supervisor 아래에 다시 연결한 형태**다. 노드를 복사하지 않고 단일 그래프에서 꺼내 쓰며, 같은 입력에서 최종 상태·LLM 입력·검색 호출이 단일과 같은지 시험이 확인한다(`tests/test_multi_graph.py`의 `test_multi_ends_exactly_like_single`, `test_agents_use_the_single_graph_nodes_not_copies`). 그래서 이 경로에서 역할을 나눈 것이 답을 바꾸도록 설계된 것은 아니며, 단일 대 멀티 측정에서도 차이는 같은 조건 3회의 흔들림 안이었다([EVAL_REPORT.md](./EVAL_REPORT.md) 4장). `backend/` 안에서 `build_multi_graph`를 부르는 코드는 없고 측정 실행기와 시험이 쓴다.
- 역할이 실제로 나뉜 경로는 **팀 합동 검토**다. 보안·인프라·IT 운영·재무 팀 에이전트 4개가 팀마다 다른 프롬프트와 검색어로 쟁점을 내고 한 표로 합친다(`backend/graph/departments/`). 이 경로는 단일 그래프 대비 측정이 없다.

## 시크릿 규칙 (위반 시 전원에게 노출됩니다)

- API 키와 비밀번호는 **`.env` 파일에만** 두세요. `.env`는 `.gitignore`에 이미 등록되어 커밋되지 않습니다.
- 코드나 문서에 키를 직접 적으면 안 됩니다. 이 org는 상호 공개라 **커밋된 키는 7기 전원이 볼 수 있습니다.**
- 평가용 계정의 비밀번호도 이 저장소에 적지 않습니다. 강사에게 별도 DM으로 제출합니다.
- 모든 push는 **Secret Scan**(GitHub Actions)이 자동 검사합니다. 검사가 실패하면 키가 커밋된 것입니다. 즉시 강사에게 알리고 **해당 키를 재발급**하세요. 히스토리에서 지워도 유출된 것으로 간주합니다.
- 필요한 키 목록은 `.env.example`에 값 없이 적어 공유하세요.
- LLM 키는 조당 하나이고 한도가 있습니다. 코드에서 무한 재시도하는 루프가 한도를 소진시키지 않게 상한을 두세요.

## 작업 흐름

```bash
# 1. 자기 이름 브랜치로 이동하고 최신 main 받기 (main에서 바로 작업하지 않는다)
git switch -c seunguk               # 처음 한 번만. 이후에는 git switch seunguk
git pull origin main

# 2. 작업 후 커밋과 push
git add .
git commit -m "feat: 하이브리드 검색 추가"
git push -u origin seunguk          # 자기 브랜치로 push

# 3. GitHub에서 seunguk → main PR 생성 → 조원 리뷰 → approve 후 merge (merge commit, squash 쓰지 않음)
```

## 충돌(conflict)이 났을 때

PR 화면에 "This branch has conflicts"가 뜨면:

```bash
git switch main && git pull          # 최신 main 받기
git switch seunguk                   # 자기 이름 브랜치
git merge main                       # 충돌 발생 지점이 파일에 표시됨
# 파일 열어 <<<<<<< ======= >>>>>>> 사이에서 남길 내용 선택 후 저장
git add . && git commit              # 충돌 해결 커밋
git push                             # PR이 자동 갱신됨
```

당황하지 마세요. 충돌은 사고가 아니라 협업의 일상입니다. 막히면 조원 또는 강사를 부르세요.

## 질문

강사 확인이 필요한 질문은 이 저장소의 **Issues**에 남기고 강사를 멘션하세요.
