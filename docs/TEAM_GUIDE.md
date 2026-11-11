# 팀 작업 지침서 (D0 10/30 확정, 이후 PR로 갱신)

> **한 줄 요약**  
> 셋이 서로 기다리지 않고, 서로의 코드를 깨지 않고, AI 코딩 도구를 써도 정해진 틀을 벗어나지 않게 하는 규칙이다. 처음 읽을 때는 1~4장만 읽고, 작업을 시작할 때 5~9장을 본다.

---

## 1. 우리가 만드는 것

**Provena(프로베나)**: IT 조직의 정책·런북을 근거로 답하고, 정책이 바뀌면 예전 답을 다시 확인하는 엔지니어링 지식 AI 플랫폼이다. 시연 데이터는 GitLab 공개 핸드북(영어 Markdown, CC BY-SA 4.0)이다. 답에는 반드시 섹션 제목 경로와 판(커밋 날짜)을 붙이고, 근거가 없으면 거절한다.

| 순위 | 기능 | 설명 |
|---|---|---|
| 반드시 | F-01 근거 답변 | 핸드북 절·판에 맞는 섹션을 찾아 인용과 함께 한국어로 답한다 |
| 반드시 | F-04 결정표 | 승인 권한표(2023 권한표)를 결정표로 바꾸고, 관리자가 승인한 뒤에만 실행한다 |
| 반드시 | F-02 답변 리콜 | 정책이 개정되면 예전 답의 결론이 바뀌었는지 판정해 알린다 |
| 반드시 | F-03 팀 합동 검토 | 보안·인프라(SRE)·IT 운영·재무 관점 쟁점표 (가이드 G4 Supervisor + 서브에이전트) |
| 반드시 | 가산 3종 | 자동화, GraphRAG, MCP·Skill (가이드 p.20 인정 기준대로) |
| 필수 뒤 진행 | F-05~F-08 | 빼지 않는다(결정 0059, 0066). 2026-11-11 코드 기준 F-05 영향 미리보기, F-07 git 없는 변경 감지, F-08 알림 피로 줄이기는 구현됐고 F-06 문서 권한은 리콜 알림 쪽 확인(`backend/graph/recall/acl.py`)까지만이다(검색 단계 거르기 없음, `docs/SDD.md` 4-2) |
| 반드시 | 공통 | 로그인, 사용자별 대화·기억 분리, 사람 승인, 데모 모드, 배포, 평가 |

자세한 내용은 PRD를 본다.

## 2. 중요한 날짜

| 날짜 | 할 일 |
|---|---|
| 10/30 (D0) | 이 지침서·계약(`backend/schemas/`) 확정, 빈 서버 배포. 전원 README 조원 소개 표에 자기 줄 추가(브랜치 → PR → 리뷰 → merge, 템플릿 첫 과제). `docs/worklog.md`·`docs/decisions.md` 빈 파일 생성. GCP 결제 연결, API 활성화, 저장소 권한(가이드 p.5). 역할과 담당 축 확정(가이드 p.28) |
| 11/5 (D4)까지 | 에이전트 그래프로 질문 → 검색 → 인용 답이 한 줄로 이어진다(가이드 일정 D4 에이전트) |
| 11/6 (D5) | 중간 점검. 단일 대 멀티 재측정과 "무엇을 뺄 것인가" 확인(F-05, F-06은 결정 0059에 따라 유지), 로그인 방식 확정 |
| 11/9 (D6)까지 | 서비스화: 로그인(사용자별 thread·Store)과 compose 기동, 배포 주소에서 질문 → 인용 답이 동작(가이드 일정 D6 서비스와 운영) |
| 11/14~15 | 주말. 자동 실행이나 배포를 새로 두지 않는다. 필요하면 평가 파이프라인만 한 번(가이드 p.5) |
| 11/16 (D11) 24:00 | 코드 동결. 이후 코드는 고치지 않는다 |
| 11/17 (D12) 24:00 | 실패 사례 분석 글, 포트폴리오 1장, AI 코딩 도구 사용 기록, 발표 자료 제출(가이드 p.5) |
| 11/18 | 발표. 전원이 자기 파트를 발표한다(가이드 p.14) |

## 3. 누가 무엇을 하나 (D0에 확정)

> **조원이 고른 안 (2026-10-28)**  
> 각자 고른 일과 순서·날짜는 업무 분담, 일마다 중요도는 업무 중요도·난이도에 있다. 역할과 담당 축은 D0(10/30)에 이 안으로 확정한다(가이드 p.28). 5장 폴더 주인은 이 안을 옮긴 것이다.

원칙만 먼저 정한다: 다른 사람 일을 멈추게 할 수 있는 일(핵심 경로)은 팀장이 맡는다. 나머지는 정답이 분명하고 결과를 바로 확인할 수 있는 단위로 나눈다. 맡은 일이 끝나면 백로그 보드의 "다음 일" 칸에서 다음 일을 가져간다.

**보조 담당** (가이드 p.15: 역할은 평가 축에 맞추고, 3인 조는 한 명이 두 역할을 겸하며, 모든 조원은 보조 담당 축을 하나 더 가진다)

| 주 담당 | 주 담당 축 | 이 축의 보조 담당 |
|---|---|---|
| 박진형 | ② 검색·데이터 | 김승욱 |
| 강경희 | ④ 서비스(화면·로그인) | 김승욱 |
| 김승욱 | ③ 에이전트, ①⑤ 평가·문서(겸임) | 박진형, 강경희 |

**백로그: 내 일이 끝나면 가져갈 다음 일** (가이드 p.14. 아침 스탠드업에서 고르고, 가져간 일은 이 표에서 지우고 작업 기록에 적는다)

| 누가 | 지금 일 | 끝나면 가져갈 다음 일 (후보, 위가 먼저) |
|---|---|---|
| 박진형 | 데모 색인(압축 한 파일로 커밋하고 자동으로 풀기, `docs/specs/search.md` 열린 항목 6)과 MCP 서버 | 인젝션 시험 문서 작성(D7, 11/10), 검색 실패 유형 분석(D9) |
| 강경희 | 화면과 API 연결([PR #61](https://github.com/aihuman-7th/proj3-c/pull/61), 채팅 API 어댑터와 SSE 스트리밍) | 운영 DB(Supabase) 연결과 Cloud Run 환경변수·최신 main 재배포(PR #60의 확인 요청 항목), 평가용 계정 A·B 만드는 절차, 가짜 API 응답으로 채팅·승인함 화면 뼈대, 대체재 비교용 범용 챗봇 답 수집(D9) |
| 김승욱 | v2 측정과 문서(`EVAL_REPORT.md`, `docs/GATES.md`, 결정 기록) | 멀티에이전트 분리(D5), 그래프 쪽 MCP 클라이언트와 런타임 Skill(가산), F-05, F-06 등 필수 뒤 작업(결정 0059, 0066). MCP 서버는 박진형(11/3 결정, `docs/specs/mcp.md` 열린 항목 1) |

## 4. 꼭 지킬 규칙 8개

1. **자기 폴더만 고친다.** 다른 사람 폴더를 고쳐야 하면 그 사람에게 요청한다(5장). 단, 팀장은 일정을 위해 모든 폴더를 직접 고칠 수 있다. 이때도 PR로 올리고, 고친 폴더의 `<폴더명>.md`에 팀장이 고쳤다고 한 줄 남긴다.
2. **`backend/schemas/`는 혼자 고치지 않는다.** 3명이 승인해야 한다.
3. **`main`에 바로 올리지 않는다.** 브랜치 → 작은 PR → 리뷰 → 머지.
4. **키·비밀번호를 저장소에 올리지 않는다.** `.env`에만 둔다. 실수로 올렸으면 즉시 팀장에게 알린다(키를 바로 폐기해야 한다).
5. **숫자는 실측만 쓴다.** 추정이면 "추정"이라고 쓰고 계산식을 붙인다.
6. **출처는 URL로 남긴다.** 데이터·자료를 구하면 URL을 데이터 출처 URL 형식으로 기록한다.
7. **30분 이상 막히면 바로 말한다.** 9장 양식으로 팀 채팅에 올린다. 혼자 하루를 쓰는 것이 가장 비싸다.
8. **폴더 md 파일에 기록한다.** 작업을 하면 그 폴더의 `<폴더명>.md`에 누가 무엇을 했는지 한 줄 남기고, 문제를 찾으면 문제 기록에 올린다. 고친 사람이 근거를 적고 직접 해결로 판정한다(5-1장).

---

## 5. 저장소와 폴더 주인

| 폴더 | 주인 | 내용 |
|---|---|---|
| `backend/schemas/` | 공동 (3명 승인) | 파트 사이 데이터 형식 (6장) |
| `backend/rag/`, `data/` | 박진형 (안) | 수집·파싱·청킹·적재(`backend/rag/ingest/`), 임베딩·검색·리랭킹(`retrieve/`). 수집은 로컬에서 한 번 하고 원문 스냅샷과 `data/manifest.jsonl`을 커밋한다(템플릿 SCAFFOLD) |
| `backend/graph/`, `backend/memory/`, `backend/prompts/`, `skills/` | 김승욱 (안) | 그래프, 부서 에이전트(security, infra(인프라·SRE), itops(IT 운영), finance), 결정표, 리콜, 장기 기억, 런타임 Skill (delegation = 권한표 해석) |
| `backend/main.py`, `backend/services/`, `Dockerfile`, `docker-compose.yml`, `db/`, `.github/workflows/` | 김승욱 (안) | FastAPI 라우트, LLM 호출(`services/llm.py` 한 곳), compose·seed·CI |
| `backend/auth.py` | 강경희 (안) | 로그인·사용자 식별. 첫 배포(`/health`)도 강경희 |
| `extras/mcp_skill/` | 박진형 (안) | FastMCP 서버 |
| `web/` | 강경희 (안) | 화면 (Vite + React + Tailwind, 빌드 결과를 FastAPI가 정적 파일로 내준다) |
| `evals/dataset_v1.jsonl`·v2, `evals/freeze.py` | 공동 | 평가셋 v1(30건)·v2(50건). 템플릿 자리 그대로 |
| `evals/retrieval/` | 박진형 (안) | Recall·MRR 측정 |
| `evals/agent/`, `evals/latency/`, `evals/ci_compare.py` | 김승욱 (안) | 에이전트 평가, 배포 응답 시간 측정, CI 점수 비교. 지표별 실행 명령은 SPEC 3장 (`evals/run_all.py`는 만들지 않았다) |
| `evals/safety/` | 김승욱 (안) | 인젝션 시험 문장과 결과, 범용 챗봇 비교 |
| `mock_erp/` | 김승욱 (안) | 업무시스템 목업. 계획은 Spring과 Python 예제, 현재는 Python 예제만 있다(`mock_erp/mock_erp.md`) |
| `data/LICENSES/` | 팀장 | 핸드북 원문 사용 시 CC BY-SA 4.0 고지와 출처. 원문 텍스트는 코드와 폴더를 나눈다 |
| 개발 도구 Skill 폴더, `.mcp.json` | 팀장 | 개발용 Skill·MCP (MCP·Skill 설계 4장). 2026-11-11 `git ls-files` 기준 저장소에 두 곳 모두 없다 |
| `docs/` | 팀장 (각자 자기 파트 절 작성) | SPEC.md, 리포트, 이 지침서 |

폴더 구조는 강사 템플릿(`docs/SCAFFOLD.md`)을 따른다. 템플릿의 `backend/rag/ingest.py`·`retrieve.py` 자리는 `backend/rag/ingest/`·`retrieve/` 폴더로, `backend/memory.py` 자리는 `backend/memory/` 폴더로 쓴다.

폴더로 나뉘지 않는 일의 담당:

| 일 | 담당 |
|---|---|
| Langfuse 연결 | 담당은 박진형으로 정했다(D0, 10/28 지침서). 구현은 커밋 이력 기준으로 강경희와 김승욱이 했다. `backend/services/tracing.py`는 김승욱이 처음 만들었고(1건, 11/1), 강경희가 3건(11/9)을 고쳤다. 커밋 제목은 "close CI approval and tracing privacy gaps", "preserve safe evaluation trace scoring", "address team review feedback"이다. 평가 점수 연결(`evals/agent/tracking.py`)은 김승욱이 만들고 강경희가 고쳤으며, 대시보드 스크린샷은 김승욱이 올렸다. 박진형의 커밋 가운데 Langfuse 코드를 바꾼 것은 없고, MCP Spec(`docs/specs/mcp.md`)에 Langfuse와의 관계를 적은 문서 커밋만 있다(`git log -S langfuse -i` 기준) |
| 골든셋 2인 독립 판정 (v1 D2, v2 D5) | 박진형, 강경희 |
| README, Langfuse 스크린샷 (G7) | 김승욱 (작성 이력 기준: README 커밋, `docs/images/langfuse/`) |
| 시연 영상 3분 (G7) | 아직 정하지 않음. 저장소에 영상이 없고 촬영은 D11(11/16) |
| 실패 사례 분석, 발표 자료 (각자 자기 파트) | 전원 |

### 5-0. 디렉토리 구조

하위 폴더마다 맨 위에 폴더 이름과 같은 md 파일을 둔다(5-1장). 오른쪽 이름이 그 파일이다.

```
repo/  (강사 템플릿 docs/SCAFFOLD.md 구조를 따른다. 2026-11-11 `ls` 기준으로 다시 썼다)
├─ README.md                 # 프로젝트 소개, 실행 방법, 데이터 출처·라이선스 표기 (루트에는 폴더 md를 두지 않는다)
├─ AGENTS.md, CLAUDE.md      # AI 코딩 도구 규칙 (CLAUDE.md는 AGENTS.md를 가리킨다)
├─ (개발 도구 Skill 폴더, .mcp.json: 계획만 있고 저장소에 아직 없음. 5장 표 참고)
├─ .github/                  # PR 양식, CI(ci.yml), 핸드북 동기화(handbook-sync.yml), 비밀값 검사(secret-scan.yml)
├─ pytest.ini                 # pytest 설정. 시험은 `pytest -q`, 평가는 `evals/` 아래 실행기(명령은 SPEC 3장). pyproject.toml과 Makefile은 두지 않는다
├─ Dockerfile, docker-compose.yml, .env.example
├─ EVAL_REPORT.md            # 개선 전후 지표 (제출물)
├─ MYINFO_SPEC.md            # 내 정보 화면 시안 (정식 spec은 docs/specs/initial-registration.md). 루트 파일 규칙에서 벗어남, 처리는 팀장 판단
│
├─ docs/   (TOPIC.md, SCAFFOLD.md, ARCHITECTURE.md, GATES.md, SPEC.md, PRD.md, SDD.md, TEAM_GUIDE.md, why_langgraph.md, decisions.md, worklog.md, embedding_measurement.md, api/, db/, specs/, deliverables/)
│
├─ backend/
│  ├─ backend.md
│  ├─ main.py                     # FastAPI 진입점(/health), 라우터 연결, /mcp 마운트(MCP_TOKEN이 있을 때)
│  ├─ auth.py                     # 로그인·가입 신청·Google 로그인·사용자 식별 (bcrypt + JWT 쿠키)
│  ├─ admin_api.py, profile_api.py   # 관리자 라우터(사용자 권한·가입 승인), 내 정보 `/me/profile`
│  ├─ api/          api.md        # /chat, /threads, /me/memory(routes.py), /recalls*(recalls.py), /changes*(changes.py), 오류·요청 ID(errors.py, middleware.py)
│  ├─ schemas/      schemas.md    # 파트 사이 데이터 형식 (3명 승인): chunk.py events.py approval.py recall.py decision.py
│  ├─ services/     services.md   # llm.py (LLM 호출은 여기 한 곳: 데모 모드, Langfuse, 비용 상한), skills.py (런타임 Skill 불러오기), auth_store.py, profile_store.py 등
│  ├─ rag/          rag.md
│  │  ├─ ingest/    ingest.md     # 템플릿 ingest.py 자리
│  │  │     handbook.py           # 핸드북 git 수집(고른 절만), 2023 권한표 판 고정
│  │  │     history.py            # git 커밋 이력에서 판 목록 (리콜 시험 데이터)
│  │  │     parse.py              # Markdown·Hugo 단축코드·HTML 표 파싱, 원문 대조
│  │  │     pdf.py                # PDF 파싱(서비스 색인 전용 청크)
│  │  │     chunk.py              # 제목(#) 단위 청킹, 긴 절은 문단으로 나눔, 120자 겹침
│  │  │     diff.py, changes.py  # 커밋 사이 섹션 비교, 바뀐 섹션 찾기
│  │  │     load.py               # 임베딩 적재, manifest, 스냅샷
│  │  │     snapshot.py           # 원문·색인 압축 스냅샷 pack·unpack(corpus.tar.gz, index.tar.gz)
│  │  │     compare.py            # 파싱 결과와 원본 줄 대조표(data/parsed/compare/, 커밋하지 않음)
│  │  │     schedule.py           # 증분 수집(새 커밋만), 정시 실행, 중복 실행 방지 (가산: 자동화)
│  │  │     snapshot_diff.py            # git 없는 변경 감지(F-07)
│  │  └─ retrieve/  retrieve.md   # 템플릿 retrieve.py 자리
│  │        embed.py              # 임베딩(기본 voyage-4 API, 로컬 모델은 비교용)
│  │        search.py             # 검색(기본 dense_en), 판·절 필터, 링크 확장, 금액 구간 조회
│  │        translate.py, ranges.py   # 한→영 질의 변환, 금액 구간 재료
│  │        rerank.py             # 리랭커 불러오기(기본은 쓰지 않음)
│  │        links.py              # 핸드북 페이지 링크 추출 (가산: GraphRAG)
│  ├─ graph/        graph.md      # 질문 처리 그래프(build.py의 build_graph로 조립), 상태, 라우팅, 인용 검사, 답변 저장, checkpoint.py(체크포인터·Store)
│  │  ├─ departments/ departments.md # Supervisor와 팀 에이전트 (보안·인프라·IT 운영·재무)
│  │  ├─ decision/  decision.md   # 권한표를 결정표로 변환·실행 (F-04)
│  │  └─ recall/    recall.md     # 리콜 판정·알림·웹훅·검토함·요약·영향 미리보기 (F-02, F-05, F-08)
│  ├─ memory/       memory.md     # Store 장기 기억 (현재 칸은 소속·직급·담당 서비스, docs/specs/memory.md). 템플릿 memory.py 자리
│  └─ prompts/      prompts.md
│
├─ skills/          skills.md     # 런타임 Skill 13개 (가산: MCP와 Skill)
│     ├─ delegation/SKILL.md      # 권한표 해석
│     ├─ security/ infra/ itops/ finance/   # 팀 관점 Skill 4개
│     ├─ citation-rules/ grounding-check/ glossary/   # 공통 Skill 3개
│     └─ report-writing/ chat-tool-guide/ mail-templates/ retrieval-slots/ search-terms/   # 조건부
├─ extras/mcp_skill/  mcp_skill.md   # 템플릿 가산 자리. mcp_server/server.py: 읽기 전용 도구 6개 search_handbook, get_section, list_changed_sections, explain_decision(decision_tool.py), get_agent_trace(trace_tool.py), get_grounding(grounding_tool.py). mcp_client/client.py, NOT_BUILT.md
├─ web/   web.md   (react-app/src/pages/: 로그인, 가입, 내 정보, 채팅, 승인함, 리콜, 변경 감시, 관리자, 사용자 관리, 기억 설정)
├─ mock_erp/ mock_erp.md   (python_example/. src/는 설명 문서뿐이라 Spring Boot 목업은 만들지 않음)
├─ db/    db.md    (01_init.sql, 101~120 앱 표 SQL, 201·202 검색·동기화 SQL, manual/. 데모 계정 2개는 앱 시작 때 시드. SQL 번호대는 100번대 로그인·그래프, 200번대 검색. 최초 작성자는 101·102·109~112·120 김승욱, 103·106~108 강경희, 104·105·113·114·201·202 박진형(`git log --follow` 이력 기준, 103은 처음 `102_auth_token_revocations.sql`이었다))
├─ data/  data.md  (corpus.tar.gz 원문 스냅샷, index.tar.gz, manifest.jsonl, chunks_index.jsonl, LICENSES/: CC BY-SA 4.0 고지와 출처, 코드와 폴더를 나눈다, 8장)
├─ evals/ evals.md (dataset_v1.jsonl·v2, freeze.py, FROZEN.json, PREREGISTER.md, ci_compare.py, retrieval/, agent/, safety/, latency/, results/)
└─ tests/
```

### 5-1. 폴더 md 파일: 작업 기록과 문제 판정

루트를 뺀 하위 폴더마다 맨 위에 폴더 이름과 같은 md 파일을 하나 둔다(예: `backend/rag/rag.md`, `backend/rag/ingest/ingest.md`, `backend/graph/departments/departments.md`). 그 폴더가 하는 일, 누가 무엇을 했는지, 어떤 문제가 있었고 해결됐는지를 이 파일 하나에서 본다.

- 필수: 루트 바로 아래 폴더와 기능 단위 폴더(예: `backend/graph/decision/`, `backend/rag/ingest/`). 그보다 아래와 `tests/`, 데이터·캐시 폴더는 선택이다.
- 루트에는 이 파일을 두지 않는다. 루트에는 `README.md`(소개), `AGENTS.md`(AI 도구 규칙)만 둔다.
- 폴더 목록과 각 md 파일 위치는 5-0장 디렉토리 구조를 따른다.

예시 (`backend/rag/ingest/ingest.md`):

```markdown
# backend/rag/ingest/ : 수집·파싱·청킹

## 이 폴더가 하는 일
핸드북 git 저장소에서 고른 절을 받아 파싱하고 청크로 나눠 DB에 넣는다. 청크는 제목 단위로 자르고 긴 절은 약 800자로 나누며, 앞 청크 끝 약 120자를 겹치고 청크 앞에 제목 경로를 붙인다. 청크 수(G3)는 겹침 없이 센다(PRD 8장). 입력, 출력, 실행 명령을 3줄로 적는다.

## 작업 기록 (최신이 위)
| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-02 | 김승욱 (wook) | 권한표 HTML 표 파서 추가, 원문 대조 3건 | #12 |

## 문제 기록 (최신이 위)
| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| I-003 | 2026-11-03 | 김승욱 | 권한표 CSS grid 칸이 한 칸씩 밀려 들어감 | F-04 결정표 오답 | 미정 | 열림 | | |
| I-002 | 2026-11-02 | 김승욱 | Hugo 단축코드가 본문에 남음 | 청크 23,095개 중 1개(0.004%, `enterprise-data/platform/tableau/embed-demo`의 `{{< performance-indicators ... />}}`, 2026-11-01 실측) | 김승욱 | 보류 | 2026-11-01 | 영향 1건이고 평가셋 정답 위치와 무관해 지금 고치지 않는다. 청킹을 다시 돌릴 때 전처리 목록에 `performance-indicators`를 더한다 |
```

예시의 표 내용은 형식을 보이기 위한 가상 예시다. 건수는 D1 실측으로 채운다.

파일은 `backend/rag/ingest/handbook.py`(핸드북 git 수집: 고른 절, 2023 권한표 판 고정)와 `backend/rag/ingest/history.py`(git 커밋 이력에서 판 목록을 만들어 리콜 시험 데이터로 씀)로 둔다. 구조는 5-0장을 따른다. 파싱 대상은 Markdown과 HTML 표(권한표의 CSS grid)다. 수집에 인증키는 필요 없다.

**문제 상태와 판정 규칙**

| 상태 | 뜻 |
|---|---|
| 열림 | 찾았고 아직 손대지 않음 |
| 진행 중 | 담당이 고치는 중 (PR 번호를 적는다) |
| 해결 | 고쳤고 확인까지 끝남 |
| 보류 | 지금은 고치지 않기로 함. 판정 근거에 이유를 적는다 |
| 해결 안 함 | 문제가 아니었거나 범위 밖. 판정 근거에 이유를 적는다 |

- **누가 썼는지 반드시 적는다.** 작업자·발견자·담당 칸에는 git id, 이름, 별칭 중 하나 이상을 쓴다. 빈칸이나 "AI", "Claude", "Codex" 같은 도구 이름만 쓰는 것은 안 된다. AI 도구로 작업했으면 그 도구를 돌린 사람을 적고, 필요하면 뒤에 도구를 덧붙인다(예: `wook (Claude Code)`). 같은 사람은 처음 정한 표기를 계속 쓴다.
- **고친 사람이 직접 "해결"로 바꾼다.** 따로 확인받지 않는다. 대신 판정 근거는 반드시 적는다.
- 판정 근거에는 확인 방법을 적는다: 테스트 이름, 재현 명령, 원문 대조 결과, PR 번호 중 하나 이상.
- 번호는 폴더 머리글자 + 일련번호다(ingest = I, rag = R, agents = A, api = P, web = W, deploy = D, evals = E).
- 자기 줄만 고친다. 새 기록은 표 맨 위에 한 줄 추가하고, 다른 사람이 쓴 줄은 고치지 않는다(상태·판정 칸은 예외).

**공용 파일 규칙**

| 파일 | 규칙 |
|---|---|
| `backend/requirements.txt` | 파트 구분 없이 한 파일이다(시험 도구 pytest·httpx는 `backend/requirements-dev.txt`). 자기 파트가 쓰는 줄만 더하고 남의 줄과 기존 버전은 바꾸지 않는다. Dockerfile과 CI(Python 3.12)가 이 파일로 설치한다 |
| `docker-compose.yml`, `.env.example` | 팀장만 고친다. 필요하면 이슈로 요청 |
| `db/` | SQL 파일 번호대를 파트마다 나눈다. 현재 100번대는 로그인·결정표·내 정보·가입·쟁점표·대화·답변과 리콜(`101`~`120`), 200번대는 검색·동기화(`201`, `202`), 처음 만드는 `01_init.sql`, 수동 적용은 `db/manual/`(`db/db.md`) |
| 설정 | 계획은 파트마다 자기 폴더의 `config.py`였으나 만들지 않았다(2026-11-11 `ls` 기준 `config.py` 0개). 설정은 환경 변수(`.env.example`)와 각 모듈이 읽는다 |

**Git**

- **브랜치는 한 사람당 하나, 자기 이름으로만 쓴다.** 예: `seunguk`. 다른 두 사람도 자기 이름 하나로 만든다(예: `jinhyeong`, `kyunghee`). 작업 종류별 브랜치(`feat/…`, `fix/…`)는 만들지 않는다. `main`에서 바로 작업하지 않고 자기 브랜치에 커밋·push한 뒤 PR로 합친다(README 협업 규칙과 같다).
- 자기 브랜치에서 `main`으로 PR을 올리고, 머지된 뒤에도 같은 브랜치를 계속 쓴다. 다음 작업 전에 `git switch seunguk && git pull origin main`으로 `main`을 받는다.
- PR 머지는 merge commit으로 한다(squash 쓰지 않음). 같은 브랜치를 계속 쓰기 때문에 squash로 합치면 다음 PR에서 이미 들어간 커밋이 다시 충돌한다.
- 다른 사람 브랜치에는 push하지 않는다.
- PR은 하루 1개 이상 올린다.
- 머지 전에 `main`을 받아 충돌을 자기 브랜치에서 푼다.
- 팀장이 자리를 비웠을 때는 크게 검토받을 일이 아니면 승인한 사람이 바로 머지한다. `backend/schemas/`처럼 3명 승인이 필요한 PR은 기다린다.
- **커밋 순서(가이드 p.14):** SPEC·평가셋 커밋이 첫 구현 커밋보다 앞서야 한다. 구현 코드는 SPEC·평가셋을 커밋한 뒤에 올린다.

## 6. 파트 사이 계약 (`backend/schemas/`, D0 확정 전 초안)

```python
# backend/schemas/chunk.py  (검색 → 에이전트)
class Chunk(BaseModel):
    chunk_id: str          # sha256 앞 16자
    org: str               # 핸드북 절 (예: "security", "finance")
    rule_seq: int          # 페이지 id (경로 sha256 앞 8자리 16진수를 정수로, 0..4294967295, DB는 BIGINT. `handbook.py:rule_seq`)
    rule_title: str        # 페이지 제목
    article: str | None    # 제목 경로 (예: "Incident Management > Severities")
    version_id: str        # 커밋 기반 판 id (SDD 5장 versions, citations와 같은 값)
    version_date: str      # 이 판(커밋)의 날짜 YYYY-MM-DD
    fetched_at: str        # 수집일 YYYY-MM-DD
    kind: Literal["article", "annex", "row", "buchik", "pre"]  # article(섹션), row(권한표 행) 위주. 나머지 값은 남겨 둠
    text: str
    source_url: str        # 핸드북 페이지 URL
    text_sha256: str | None = None   # 본문 sha256 (SDD 11-1 3-6)
    version_date_before: bool = False   # True면 판 날짜를 정확히 모르고 version_date 이전이라는 뜻(얕은 이력, I-001). 화면은 "YYYY-MM-DD 이전"으로 보인다
    line_start: int | None = None   # 원본 페이지 줄 범위(1부터, 끝 포함). 평가셋 `경로#L523` 정답 대조와 출처 링크용. 3명 승인 사항이었고 `backend/schemas/chunk.py`에 반영됨
    line_end: int | None = None

class SearchQuery(BaseModel):
    query: str
    org: str | None = None     # 절
    as_of: str | None = None   # 이 날짜 기준 핸드북 판(커밋)만
    k: int = 5                 # DEFAULT_K (확정 조합 k=5, docs/specs/search.md)
    sub_queries: list[str] | None = None   # 질문 분해 결과(2~3개), 있으면 하위 질문마다 검색

# backend/schemas/events.py  (에이전트 → 화면)
class AgentEvent(BaseModel):
    type: Literal["token", "citation", "approval_request", "error", "done"]
    thread_id: str
    data: dict  # type별 키는 SDD 6장 "AgentEvent.data" 표

# backend/schemas/approval.py  (에이전트 ↔ 화면)
class ApprovalItem(BaseModel):
    approval_id: str
    kind: Literal["decision_table", "issue_table"]
    summary: str
    created_at: datetime   # JSON에는 ISO 8601 문자열

class Decision(BaseModel):
    approval_id: str
    approve: bool
    comment: str = ""
    decided_by: str | None = None   # 승인한 관리자, 서버가 로그인 사용자로 채움 (SDD 11-1 3-3)

# backend/schemas/recall.py  (수집 → 에이전트 → 화면)
class ChangedArticle(BaseModel):   # 바뀐 섹션 (같은 페이지의 두 커밋 비교)
    rule_seq: int
    article: str
    old_version_date: str
    new_version_date: str
    change_type: Literal["added", "removed", "modified"]   # SDD 11-1 3-5

class RecallNotice(BaseModel):
    answer_id: str
    user_id: str
    changed: ChangedArticle
    conclusion_changed: bool
    explanation: str

class MaintenanceCandidate(BaseModel):   # 연결 정책 개정 → 관리자 "함께 볼 정책" (F-02)
    candidate_id: str
    upper_rule: str        # 개정된 정책 페이지 (링크로 연결된 쪽)
    upper_version_id: str
    rule_seq: int          # 영향받는 다른 정책 페이지
    article: str
    reason: str            # 페이지 링크 그래프에서 찾은 근거
```

- **IT 전환에서 필드 구조는 바꾸지 않고 뜻만 바꿨다** (SDD 6장). 이름 바꾸기(예: `org` → `section`)는 계약 변경이라 기본값은 그대로 둔다.
- 필드 추가는 PR 하나로 3명 승인. 이름 변경·삭제는 회의에서만 정한다.
- 기다리지 않는 법: 주는 쪽은 D1에 고정 응답을 돌려주는 가짜 함수(`search()`, `run()`)를 먼저 올린다.

## 7. AI 코딩 도구 쓰는 규칙

Claude Code·Codex·Cursor 등을 써도 된다. 도구에 주는 규칙은 저장소 루트의 [AGENTS.md](../AGENTS.md)에 있다(`CLAUDE.md`는 이 파일을 가리킨다).

**데이터·라이선스 규칙.** 핸드북 본문은 CC BY-SA 4.0이다. 코드와 원문 텍스트는 폴더를 나누고, 원문 폴더(`data/LICENSES/` 포함)에만 라이선스와 출처를 적는다. 답에 원문을 보일 때는 페이지 URL, CC BY-SA 4.0 링크, 수정 여부를 함께 표시한다. README와 발표에는 "GitLab Inc.와 제휴·보증 관계 없음"을 적는다. 자세한 내용은 SDD 8장.

**개발용 Skill·MCP.** 계획은 저장소의 개발 도구 Skill 폴더와 `.mcp.json`을 `git pull`로 받아 모두 같은 것을 쓰는 것이다(2026-11-11 현재 저장소에 이 파일들은 아직 없다). 필수·조건부 목록은 MCP·Skill 설계 4장에 있다. 새 외부 Skill은 팀장이 내용을 확인한 뒤 넣는다.

**AI 결과를 그대로 믿지 않는다.** 범용 챗봇 비교에서도 확인했듯이 AI 도구는 없는 섹션이나 정책 이름을 지어낼 수 있다. PR을 올리기 전에 직접 실행해 보고, 데이터·섹션은 핸드북 원문과 대조한다.

## 8. 작업 하나를 끝냈다고 말하는 기준

PR을 올릴 때 아래를 모두 체크한다.

- [ ] 자기 폴더만 고쳤다 (`backend/schemas/`, 공용 파일 변경 없음)
- [ ] 첫 PR이면: SPEC·평가셋 커밋이 구현 커밋보다 앞서 있다 (가이드 p.14)
- [ ] 기능 작업이면 `docs/specs/{기능}.md`(Why, Goal, What, How, AC)를 먼저 썼다
- [ ] 실험이면 `evals/PREREGISTER.md`에 바꿀 것 하나와 기대를 먼저 적었다
- [ ] `pytest -q` 통과 결과를 붙였다
- [ ] 새로 구한 데이터·자료는 출처 URL을 남겼다
- [ ] 숫자는 실행 결과에서 나온 값이고, 실행 명령을 함께 적었다
- [ ] 파싱·검색 결과는 원문과 3건 이상 대조했다 (해당될 때)
- [ ] 키·비밀번호가 없다
- [ ] AI 도구를 썼으면 `docs/deliverables/ai_tools_log.md`에 한 줄 남겼다
- [ ] 폴더 `<폴더명>.md`에 작업 기록 한 줄을 남겼다. 작업자 칸에 git id, 이름, 별칭 중 하나를 적었다. 고친 문제가 있으면 판정 근거를 적고 "해결"로 바꿨다

**파트별 첫 일** (전체 순서는 업무 분담):

| 사람 | 첫 일 | 언제 |
|---|---|---|
| 전원 | README 조원 소개 표에 자기 줄 추가 (첫 PR) | D0 (10/30) |
| 강경희 | 빈 FastAPI를 Cloud Run에 배포하고 `/health` 주소 공유 | D0 (10/30) |
| 김승욱 | 평가셋 설계 시작, 폴더 뼈대·`.env.example` | D0 (10/30) |
| 박진형 | 핸드북 git 수집(고른 절, 고정 커밋), 파싱·청킹, 저녁에 청크 수 공유 | D1 (11/2) |

## 9. 막혔을 때 올리는 양식

```
[막힘] 무엇을 하려고 했나: 
어디서 막혔나 (파일·명령): 
에러 메시지 (마지막 몇 줄): 
해 본 것: 
언제까지 필요한가: 
```

## 10. 기록 규칙

| 무엇 | 어디에 | 형식 |
|---|---|---|
| 폴더별 작업·문제 | 각 하위 폴더 `<폴더명>.md` | 5-1장 표. 해결 판정은 고친 사람이 근거와 함께 |
| 매일 한 일 | `docs/worklog.md` | 날짜·사람별로 한 일 2~3줄, 막힌 것, 다음 할 일. **팀장이 `main`을 받을 때 새로 머지된 PR을 기준으로 세 사람 것을 한꺼번에 쓴다.** 조원은 따로 쓰지 않고, 빠지거나 틀린 내용은 팀장에게 알린다 |
| 결정 | `docs/decisions.md` | 무엇을 정했나, 이유, 버린 대안. 이유와 버린 대안이 없으면 결정으로 치지 않는다 |
| 기능 Spec | `docs/specs/{기능}.md` | Why, Goal, What, How, AC 다섯 칸. 구현 전에 쓴다 (`docs/specs/_example.md`) |
| 실험 사전 등록 | `evals/PREREGISTER.md` | 바꿀 것 하나와 기대를 먼저 적는다 |
| 실험 결과 | `evals/` 아래 결과 파일 + 한 줄 재현 명령 | 바꾼 것은 한 번에 하나만 |
| 평가셋 동결 | `evals/FROZEN.json` (`python evals/freeze.py`) | v1 D2, v2 D5. 동결 뒤 정답을 고치지 않는다 |
| 개선 전후 지표 | `EVAL_REPORT.md` | 숫자, 원인, 시도한 것. 버린 시도도 적는다 |
| AI 도구 사용 기록 | `docs/deliverables/ai_tools_log.md` | 쓸 때마다 한 줄. D12 제출물 |
| 실패 사례 분석, 포트폴리오 | `docs/deliverables/failure_analysis.md`, `portfolio.md` | D12 제출물 |
| 데이터 출처 | 출처 URL 표 | URL, 받은 날짜, 이용 조건 |
