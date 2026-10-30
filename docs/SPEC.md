# SPEC: Provena 정본 문서

> 이 문서가 "무엇을 만들고, 어떤 숫자로 잘 됐다고 말하나"의 정본이다(가이드 p.14, p.21). 코드를 바꾸면 이 문서도 같은 PR에서 바꾼다. 기능별 상세는 `docs/specs/`, 설계는 [SDD](./SDD.md), 요구사항은 [PRD](./PRD.md), 팀 규칙은 [TEAM_GUIDE](./TEAM_GUIDE.md), AI 도구 지침은 [AGENTS.md](../AGENTS.md)에 있다. 숫자 기준은 PRD 13-2를 그대로 옮겼고 여기서 새 숫자를 만들지 않는다.

상태: D0(10/30) 초안. 숫자 기준은 D0 합의로 동결하며 이후 낮추지 않는다(가이드 p.14, p.19).

## 1. 한 줄 정의

IT 조직의 정책·런북(GitLab 공개 핸드북, CC BY-SA 4.0)을 섹션과 판 날짜를 붙여 인용해 답하고, 근거가 없으면 거절한다. 인용한 정책이 바뀌면 이미 나간 답을 다시 확인해 받은 사람에게 알리고, 승인 권한표는 사람이 승인한 결정표로만 판단한다. 이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다.

## 2. 범위

### 2-1. 만드는 것

| ID | 기능 | 한 줄 | 사람 승인 | 상세 Spec |
|---|---|---|---|---|
| F-01 | 근거 답변 | 정책 섹션을 인용해 한국어로 답하고 판 날짜·출처 URL·CC BY-SA 4.0을 표시한다. 근거가 부족하면 되묻거나 거절한다 | 해당 없음 | [question-graph](./specs/question-graph.md) |
| F-02 | 답변 리콜 | 인용한 섹션이 바뀌면 영향받는 답을 다시 판정해 결론이 바뀐 답만 받은 사람에게 알린다. 연결된 정책은 관리자에게 "함께 볼 정책"으로 알린다. 업무시스템에는 웹훅으로 알린다 | 함께 볼 정책은 관리자 판단 | [recall](./specs/recall.md) |
| F-03 | 팀 합동 검토 | 보안, 인프라·SRE, IT 운영, 재무 에이전트가 한 건을 검토해 쟁점표를 만든다 | 쟁점표 저장 전 | [team-review](./specs/team-review.md) |
| F-04 | 결정표 | 승인 권한표를 결정표로 바꾸고, 관리자가 원문과 대조해 승인한 결정표만 실행한다. 실행에는 LLM을 쓰지 않는다 | 결정표 실행 전 | [decision-approval](./specs/decision-approval.md) |
| P-01 | 로그인과 사용자별 기억 | 로그인, 사용자 id로 대화(thread)와 장기 기억(Store namespace) 분리 | 해당 없음 | [login](./specs/login.md), 기억 Spec은 예정 |
| P-02 | 문서 적재 | Markdown 파싱, 청킹, 임베딩, `data/manifest.jsonl`, 증분 수집 | 해당 없음 | [collect](./specs/collect.md) |
| P-03 | 업무시스템 연동 | REST(OpenAPI), 자동 생성 SDK, FastMCP 서버, 웹훅, `mock_erp/` | 해당 없음 | Spec 예정 |
| P-04 | 데모 모드 | `docker compose up` 한 줄, 키 없이 기동, 데모 계정 2개 시드 | 해당 없음 | 이 문서 4장 |
| 가산 | 자동화, GraphRAG, MCP·Skill | 증분 수집과 정시 실행, 페이지 링크 그래프, FastMCP와 런타임 Skill (가이드 p.20) | 해당 없음 | Spec 예정 |

되면 만드는 것: F-05~F-08. 핵심 기능과 필수 게이트를 끝낸 뒤 11/6 중간 점검에서 넣을지 정한다(PRD 6-3).

### 2-2. 만들지 않는 것

실제 조직 시스템(배포·구매) 연동, 조직 내부망 배포, GitLab 비공개(internal) 문서, 결재 상신. 비공개 주소로만 연결된 내용은 답의 근거로 쓰지 않는다.

## 3. 숫자 기준 (PRD 13-2, 동결)

"측정" 칸의 `예정`은 아직 만들지 않은 명령·결과 파일이다. 만들면 이 표에서 `예정`을 지우고 실제 경로로 바꾼다. 결과 칸은 실측 뒤에만 채운다.

| 지표 | 기준 | 재는 법 (PRD 13-2) | 측정 명령 / 결과 파일 | 결과 |
|---|---|---|---|---|
| 검색 Recall@5 | 0.80 이상 | 평가셋 관련 문항, 사람이 정한 정답 섹션 기준 | `evals/retrieval/` 실행기, 결과 `evals/results/` 아래 (예정, 박진형) | 미측정 |
| 인용 정확도 | 0.85 이상 | 답이 인용한 섹션이 정답 섹션과 맞는 비율 | `evals/agent/` 실행기, 결과 `evals/results/` 아래 (예정) | 미측정 |
| 비관련 질문 거절 | 0.90 이상 | 비관련 4종(도메인 밖, 코퍼스에 없는 대상, 없는 항목, 기간이 다른 질문). 비공개 문서 질문 포함 | `evals/agent/` 실행기, 결과 `evals/results/` 아래 (예정) | 미측정 |
| 판 날짜 표시 | 100% | 모든 답에 근거 섹션의 판 날짜 표시 | `evals/agent/` 실행기와 `tests/` 회귀 시험 (예정) | 미측정 |
| 답변 리콜 | 재현율 0.80 이상, 정밀도 0.80 이상 | 실제 개정 커밋 전후 판으로 만든 시험 답변에서 결론이 바뀐 답을 찾는 비율 | `evals/agent/` 리콜 평가, 결과 `evals/results/` 아래 (예정) | 미측정 |
| 함께 볼 정책 후보 | 정밀도를 재서 공개 | 사람이 정한 연결 정책과 대조 | `evals/agent/` 후보 평가, 결과 `evals/results/` 아래 (예정) | 미측정 |
| 링크 추출 | 정확도를 재서 공개 | 참조 그래프 간선을 원문과 대조 | `evals/agent/` 링크 평가, 결과 `evals/results/` 아래 (예정) | 미측정 |
| 결정표 | 승인 전 실행 0건. 셀 정확도는 재서 공개 | 사람이 원문에서 뽑은 정답과 셀 대조 | 승인 전 실행은 `tests/` 시험(decision-approval AC-01), 셀 정확도는 `evals/agent/` (예정) | 미측정 |
| 신뢰 경계 | 결정표 기준 변경·승인 우회·유출 경로는 뚫림 0건, 나머지는 공격 성공률 공개 | 간접 인젝션 최소 30건 | `evals/safety/` 실행기와 결과 (예정) | 미측정 |
| 응답 시간 | 검색+리랭킹 p95 3초 이하(첫 요청 제외), 전체 p95 10초 이하 | Cloud Run에서 단계별 실측 | Langfuse 트레이스와 `evals/results/` 아래 측정 파일 (예정) | 미측정 |
| 비용 | 질문 1건 평균 $0.01 이하 | Langfuse 비용 기록 | Langfuse 대시보드 (스크린샷은 `docs/deliverables/`) (예정) | 미측정 |
| 기동 | 깨끗한 환경에서 `docker compose up` 10분 이내 | G2 | 새 clone에서 `docker compose up -d --build`와 `/health` 확인, 소요 시간은 `docs/GATES.md` G2 칸에 기록 (손으로 잼) | 미측정 |

공통 규칙:

- 평가셋은 v1(`evals/dataset_v1.jsonl`), v2(`evals/dataset_v2.jsonl`)이고 동결하면 해시가 `evals/FROZEN.json`에 기록된다(v1은 11/3, v2는 11/6 동결 예정). 동결 확인은 `python evals/freeze.py --check`이며 `tests/test_frozen_evals.py`가 PR마다 검사한다.
- 실험은 바꾸기 전에 `evals/PREREGISTER.md`에 기대를 먼저 적고 한 번에 하나만 바꾼다.
- 숫자는 실행 결과에서 나온 값만 쓰고, 실행 명령을 함께 적는다. 점수가 오르지 않았으면 오르지 않았다고 쓴다.
- 평가 결과는 `EVAL_REPORT.md`에 개선 전후, 달라진 문항, 지표 5개 분리 보고로 옮긴다.

## 4. 데모 모드 (P-04, G2)

평가자에게는 API 키가 없으므로 `docker compose up` 한 줄이 키 없이 떠야 한다.

| 항목 | 내용 |
|---|---|
| 기동 | `docker compose up`. `.env`가 없어도 뜬다(`.env.example`은 이름만 보여 준다) |
| LLM | `DEMO_MODE=1`이면 키 없이 기록해 둔 응답을 재생한다(`backend/services/llm.py`, 구현 예정) |
| DB | 로컬 pgvector 컨테이너(`db`). 검색 스냅샷 적재는 예정 |
| 로그인 | 로그인 API는 `backend/auth.py`(강경희, `docs/specs/login.md`). `backend/main.py` 연결, users 테이블, 로컬 데모 계정 2개 시드는 다음 PR(로그인 연결)에서 채운다 |
| 평가용 계정 | 제출하는 평가용 계정(G1)은 데모 계정과 다른 값이고 저장소에 적지 않는다 |

## 5. 파트 사이 계약과 API

- 데이터 형식은 `backend/schemas/`(chunk, events, approval, recall, decision)이고 SDD 6장과 같다. 필드 추가는 PR 하나로 3명 승인, 이름 변경·삭제는 회의에서만 정한다. 시험은 `tests/test_schemas.py`. `AgentEvent.data`의 `type`별 키는 SDD 6장 표를 따른다.
- 엔드포인트 목록은 SDD 4-4장이다. 지금 `backend/main.py`에 붙은 것은 `/health`다. 로그인 라우터(`/auth/csrf`, `/auth/login`, `/auth/logout`, `/me`)는 `backend/auth.py`에 있고 다음 PR에서 `main.py`에 붙인다. 나머지는 해당 기능을 만들 때 이 문서와 SDD를 같이 고친다.

## 6. 게이트와 증거

필수 게이트 G1~G7이 이 저장소 어디에서 채워지는지와 지금 상태는 [GATES.md](./GATES.md)에 있다. 핵심 코드를 한 줄 깨뜨려 테스트가 실제로 실패하는지 확인하는 기록도 그 문서에 둔다.

## 7. 데이터와 이용 조건

핸드북 본문은 CC BY-SA 4.0이다. 답에 원문을 보일 때는 페이지 URL, 라이선스 링크, 수정 여부를 함께 표시한다. 원문 텍스트는 코드와 폴더를 나누고 `data/LICENSES/`에 고지와 출처를 적는다. 로고를 쓰지 않으며 README와 발표에 "GitLab Inc.와 제휴·보증 관계 없음"을 적는다(SDD 8장).
