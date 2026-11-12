# 박진형 작업 정리 (D0~D8, 2026-10-28 ~ 2026-11-11)

기준: 팀 레포 `aihuman-7th/proj3-c` main `54f8e37`(PR #125 머지 직후, 2026-11-11 11:34 KST). 지시받은 기준 `c5ff52e`(PR #124)보다 PR #125 하나가 더 들어가 있음.
근거 표기: PR 번호는 GitHub API(PR JSON `user.login = jinyeong-731`), 커밋은 `git log origin/main`, 날짜는 KST(머지 시각 UTC+9). 값은 PR 본문·결과 파일에서 옮김. 파일에서 못 찾은 값은 "확인 못 함".
날짜 라벨: D0=10/30, D1=11/2, D2=11/3, D3=11/4, D4=11/5, D5=11/6, D6=11/9, D7=11/10, D8=11/11. 10/28·10/29·10/31·11/7·11/8은 D 라벨 밖.

## 1. 한 줄 요약

- main에 머지된 PR 32개(#3~#125 중 본인 작성). 작성 PR 34개 중 2개(#56·#118)는 머지 없이 닫음. 본인 일반 커밋 112개(커밋한 날 12일, 11/6·11/8은 커밋 없음, `git log --author=뽕뽕 --no-merges`).
- 영역: 핸드북 수집·파싱·청킹(#5~#23), 검색 `search()`·v2(#35·#39·#48), 증분 수집(#41·#42·#50), MCP 서버·클라이언트(#45·#51·#52·#58), 오프라인 측정(#57), 신뢰 경계 보강·배포 실측(#62·#68·#85), 웹·API 수정(#71·#74·#96·#109), 검색 회귀 CI(#94·#98), 8장 단계별 시간·승인 대기 실측(#123·#125).
- 아직 main에 없는 작업: 로컬 브랜치 9개(4절). 측정 결과 중 `study/class-3/` 안에만 있는 것이 많음(3절·별도 인벤토리).
- 팀 지침서 10장 기준 빠진 것: `docs/worklog.md`에 #58·#123·#125 언급 0건(`grep "#N"` 결과). 정리 md가 없는 측정 결과 위치는 `measurement-docs-inventory.md` 참고.

## 2. 일자별 표 (main 머지 PR)

각 PR은 해당 폴더 md 작업 기록·`ai_tools_log.md` 한 줄을 함께 올림(PR 파일 목록에 `docs/deliverables` 포함, `git diff --name-only <머지>^1 <머지>`). 숫자 칸의 "커밋"은 PR 안의 비머지 커밋 수, "파일·줄"은 머지 전후 diff `--shortstat`.

| 날짜(D) | 한 일 | PR | 근거(파일:줄 또는 결과 파일) | 숫자 |
|---|---|---|---|---|
| 10/28 | 팀원 정보 등록 | #3 | `README.md` | 2 커밋, 1파일 +2/-1 |
| 10/29 | 핸드북 수집 1/7: 고른 절 11개(폴더 17개)·고정 커밋·쪽 수 검사 | #5 | `backend/rag/ingest/handbook.py`, `docs/specs/collect.md`, PR #5 본문 | 3 커밋, 6파일 +249, 1,564쪽 검사 |
| 10/29 | 페이지 id(rule_seq) 최대 10자리로 축소(#5 리뷰) | #6 | `handbook.py`, `tests/test_ingest_handbook.py` | 3 커밋, 5파일 +6/-4 |
| 10/30 (D0) | 수집 2/7: git 원본 받기·저장 | #7 | `handbook.py`, `tests/test_ingest_handbook.py` | 2 커밋, 4파일 +149/-2 |
| 10/30 (D0) | 2023 권한표 수집, 개정 이력 수집(`history.py`), Hugo 단축코드 전처리, rule_seq는 DB에서 bigint | #11 | `history.py`, `parse.py`, `docs/specs/parse.md`, PR #11 본문 | 8 커밋, 9파일 +397/-10, 테스트 20 통과, 개정 이력 커밋 6,332건 검사 |
| 10/30 (D0) | Markdown → 요소 파싱(`markdown-it-py`·`beautifulsoup4`·`lxml`) | #12 | `parse.py`, `backend/requirements.txt` | 3 커밋, 5파일 +298, 테스트 28 통과 |
| 10/30 (D0) | 2023 권한표 파싱, 파싱 실행, 원문 대조표 `compare.py`, 원문 대조 4건 기록 | #13 | `parse.py`, `compare.py`, EVAL_REPORT 1장 | 5 커밋, 6파일 +354/-4, 요소 85,388개, 권한표 363칸, 테스트 32 통과 |
| 10/30 (D0) | 판 날짜를 페이지마다 마지막 커밋 날짜로 (I-001) | #18 | `handbook.py`, `docs/specs/collect.md` | 3 커밋, 5파일 +93/-4, 판 643종, 날짜 빠짐 0 |
| 10/31 | 권한표 표 밖 글(각주·정책 본문)을 요소로 파싱 (I-007) | #19 | `parse.py`(`parse_authz_prose`) | 3 커밋, 5파일 +51/-6, 103요소, 되찾기 실패 0 |
| 10/31 | 제목 단위 청킹(800자/겹침 120자)·manifest·원문 대조표, 평가셋 v1 정답 채움 | #23 | `chunk.py`, `evals/dataset_v1.jsonl`, `docs/specs/chunk.md` | 5 커밋, 9파일 +792/-32, 청크 23,095, 서로 다른 본문 지문 22,378, 빠진 요소 0 |
| 11/2 (D1) | `search()` 구현(판 유효 구간 필터·BM25·RRF·리랭킹·번역 장부), Docker 적재 | #35 | `backend/rag/retrieve/*`, `Dockerfile`, `db/201_search.sql` | 6 커밋, 22파일 +2,252/-10 |
| 11/2 (D1) | 판 날짜를 UTC 커밋 날짜로 (I-011) | #39 | `handbook.py`, `data/corpus.tar.gz`, `index.py` | 7 커밋, 12파일 +119/-18, 72쪽 날짜 하루 이동, as_of 10/27 청크 23,076→23,095 |
| 11/2 (D1) | 증분 수집 `diff.py`·`schedule.py`, 정시 실행 workflow(매일 UTC 18:07) | #41 | `db/202_sync.sql`, `.github/workflows/handbook-sync.yml` | 6 커밋, 10파일 +1,461/-1 |
| 11/2 (D1) | 삭제 보류 알림·재확인, 비교 실패는 failed (#41 리뷰 3번) | #42 | `schedule.py`, `handbook-sync.yml` | 3 커밋, 6파일 +173/-18 |
| 11/4 (D3) | FastMCP 읽기 전용 도구 3개(`search_handbook`·`get_section`·`list_changed_sections`), `MCP_TOKEN` 있을 때만 `/mcp` | #45 | `extras/mcp_skill/mcp_server/server.py`, `docs/specs/mcp.md` | 7 커밋, 18파일 +1,600/-21, 변이 시험 16/16 잡음(`study/class-3/bench/results/mcp-mutations-2026-11-04.json`, 같은 날 실행이라 이 PR 기준으로 봄, 추정) |
| 11/5 (D4) | 검색 v2: voyage-4 기본, `sub_queries`, 링크 확장 L1x2, k=5 (조장 요청 5건) | #48 | `search.py`, `links.py`, `docs/specs/search.md` | 6 커밋, 20파일 +1,014/-101, v1 30문항 청크 집합 30/30 일치·Recall@5 0.9667 시험 고정 |
| 11/5 (D4) | 증분 수집 표 `sync_runs`·`changed_articles` RLS | #50 | `db/202_sync.sql` | 1 커밋, 3파일 +7 |
| 11/5 (D4) | MCP 클라이언트(그래프가 MCP로 검색 호출) | #51 | `extras/mcp_skill/mcp_client/client.py` | 3 커밋, 7파일 +324 |
| 11/5 (D4) | MCP `search_handbook`에 `sub_queries` 칸, `.env.example` `MCP_URL` (#51 리뷰) | #52 | `server.py`, `client.py` | 3 커밋, 8파일 +43/-10 |
| 11/5 (D4) | link_keep_per_sub 0→2, 전수→HNSW 오프라인 측정(사전 등록 #26·#27 먼저 커밋 `9f82ea3`) | #57 | `evals/results/linkkeep_v1/linkkeep_v1.md`, `evals/retrieval/exp_linkkeep_v1.py` | 2 커밋, 7파일 +626, Recall@5 네 칸 모두 0.967 |
| 11/5 (D4) | MCP 도구 `explain_decision`·`get_agent_trace` | #58 | `decision_tool.py`, `trace_tool.py` | 1 커밋, 12파일 +990/-28, 시험 49개 추가, 변이 6/6 |
| 11/7 | warmup 실패 때 DB 풀 닫기, mcp.md 도구 수 출처 표기 | #62 | `search.py`, `docs/specs/mcp.md`, PR #62 본문 | 5 커밋, 5파일 +53/-7, 연결 누수 0→20(수정 전) → 0(수정 후), 변이 3/3 |
| 11/9 (D6) | D7 신뢰 경계 보강 G2~G4(청크 머리·되풀이 구분자 지우기, 유출 검사 정규화) | #68 | `backend/prompts/question.py`, `tests/test_safety_gaps.py` | 4 커밋, 2파일 +203/-5, 새 오탐 0건(저장 답 1,571개·청크 23,095개) |
| 11/9 (D6) | 새로고침·대화 목록 클릭 뒤 빈 화면 수정 | #71 | `backend/api/routes.py`, `web/react-app/src/pages/DemoChatPage.jsx` | 1 커밋, 9파일 +334/-16 |
| 11/9 (D6) | 관리자 사용자 관리·내 정보 API, 대화 목록 글자 잘림, 원문 링크 https만 | #74 | `backend/admin_api.py`, `backend/profile_api.py`, `db/104`·`105` | 2 커밋, 34파일 +2,644/-26 |
| 11/9 (D6) | D7 배포 실측 기록: 계정 A·B 섞임, 같은 승인 두 번 | #85 | `EVAL_REPORT.md:658-659`(6장 20·21행), 원자료 `study/class-3/d7-isolation-approval-1109.md` | 1 커밋, 2파일 +5/-2, 10/10 막힘, 6/6 막힘 |
| 11/9 (D6) | 검색 회귀 시험을 CI에 연결(키·DB 없이 고정 자료로 검색을 다시 돌림) | #94 | `tests/test_search_regression.py`, `tests/fixtures/search_regression/`, `evals/retrieval/regress_fixture.py` | 2 커밋, 7파일 +2,150, 고정 자료 1.8MB, 40문항, 시험 6개, 변이 4/6 실패 |
| 11/9 (D6) | 답 받는 중 하얀 화면, 세션 확인 깜빡임, 승인함 사유가 다른 건으로 넘어가던 문제 | #96 | `web/react-app/src/lib/chat-service.js`, `SessionProvider.jsx`, `ApprovalsPage.jsx`, `AppErrorBoundary.jsx` | 4 커밋, 12파일 +264/-10, 고치기 전 main에서 실패하는 시험 추가 |
| 11/10 (D7) | #94 리뷰 반영: `SEARCH_RANGE_N` 시험 포함, 시험·자료 갱신 규칙, 재현 자료 위치 기록 | #98 | `tests/test_search_regression.py`, `evals/retrieval/retrieval.md` | 2 커밋, 8파일 +53/-6, 6 통과·3 건너뜀(입력 주면 9 통과) |
| 11/10 (D7) | 운영 현황 API 연결, 결정표 탭, 내 정보·계정 팝업·로그아웃 화면 수정 6건 | #109 | `web/react-app/src/pages/AdminPage.jsx`, `lib/api.js` | 7 커밋, 11파일 +631/-51, vitest 222 통과 |
| 11/11 (D8) | 8장 표의 검색·생성 시간을 운영 `00035-h69` 값으로, 승인 대기 Postgres 실측, `stage_times.py` 음수 생성 시간 수정 | #123 | `evals/latency/stage_times.py`, `tests/test_stage_times.py`, `evals/results/d8_stage_report/approval_latency_postgres.json`, `EVAL_REPORT.md:704` | 2 커밋, 7파일 +2,090/-7, 검색 p95 1.22초, 생성 p95 9.45초, 승인 대기 29.6ms·55.3ms(n=20), 로컬 pytest 3,120 통과·84 건너뜀 |
| 11/11 (D8) | 운영 `00035-h69` 단계별 시간 정리 문서, 00020 대비 전후 | #125 | `evals/results/deploy_latency_provena-api-00035-h69/stage_times.md` | 1 커밋(`d76baf3`), 3파일 +72, 전체 p95 15.641→8.942초 |

머지 없이 닫은 PR:

| 날짜 | 내용 | PR | 근거 |
|---|---|---|---|
| 11/5 | 사전 등록 #26·#27만 먼저 올림. 닫음 | #56 | 같은 커밋 `9f82ea3`이 #57 안에 들어 있음(`git log`) |
| 11/10 | 웹 수정 묶음(49파일 +2,265/-149, 구글 로그인·비밀번호 변경·내 정보 저장 등). 닫음 | #118 | PR #118 본문. 쪼갠 뒤 어디로 갔는지는 확인 못 함(4절 브랜치와 겹칠 수 있음, 추정) |

참고:
- 본인이 쓴 커밋이 다른 사람 PR로 들어간 경우: 0건(`git log <머지>^1..<머지>^2`로 본인·박진형 작성 비머지 커밋을 센 결과 없음).
- 본인 계정(박진형) 머지 커밋 12개: 다른 사람 PR을 머지한 기록(#10·#16·#27·#31·#60·#65 등, `git log --first-parent`). 작업 산출물이 아님.
- 리뷰·승인은 `docs/worklog.md`에 날짜별로 기록돼 있음(예: 11/2 항목 "PR #19 리뷰·승인·머지"). 별도 집계는 안 함.

## 3. 측정·시험 결과 표

운영 = 배포 주소·운영 리비전 대상. 로컬 = 본인 PC·로컬 DB·가짜 모델. 결과 파일 경로 중 `study/class-3/`는 본인 PC 로컬이며 팀 레포에 없음. 숫자는 표의 결과 파일에서 옮김.

| 무엇을 쟀나 | 운영/로컬 | 결과 위치 | 숫자 | main |
|---|---|---|---|---|
| 배포 `00035-h69` 단계별 시간(Langfuse 64세션) | 운영(읽기만, 새 호출 없음) | `evals/results/deploy_latency_provena-api-00035-h69/stage_times.md:11-19` | 검색 p95 1.22초, 생성 p50 5.36 / p95 9.45초, 그래프 전체 p95 9.87초, 클라이언트 측 p95 10.14초 | #123·#125 |
| 00020 → 00035 전후 | 운영 | 같은 파일 `:26-34` | 생성 p95 15.26→9.45초, 그래프 15.28→9.87초, 검색 1.40→1.22초. 한계: 공급자(OpenRouter→직접 호출)와 코드가 같이 바뀌어 한 변경의 효과로 못 나눔(`:39`) | #125 |
| 리비전별 전체 응답 시간(50건×3회 평균) | 운영 | 같은 파일 `:42-53`, `EVAL_REPORT.md` 8장 표 | p95 15.641 / 11.153 / 8.473 / 8.942초(00020 / 00029 / 00032 / 00035), 요청당 비용 0.0050→0.0074달러 | #125 |
| 승인 대기 기계 시간(멈춤→재개→끝) | 로컬(Docker Postgres, 가짜 모델, n=20) | `evals/results/d8_stage_report/approval_latency_postgres.json` | 재개부터 끝까지 결정표 변환 p50 29.63ms, 합동 검토 55.31ms(파일에서 계산, `EVAL_REPORT.md:704`와 같음) | #123 |
| link_keep 0→2, 전수→HNSW | 로컬(pgvector, 운영 DB·LLM·Voyage 호출 없음) | `evals/results/linkkeep_v1/linkkeep_v1.md:44-51, 62-70` | Recall@5 네 칸 0.967 동일, 청크 집합이 바뀐 문항 5개(3·4·6·13·25번), HNSW 상위 5 일치 30/30, 질의 42/42, 30문항 검색 전수 8.4~9.0초 → HNSW 1.1~1.2초(노트북) | #57 |
| 검색 회귀 고정 자료 | 로컬(키·DB 없음) | `tests/fixtures/search_regression/`, 설명 `evals/retrieval/retrieval.md` | 40문항, recall@5 0.9133, 시험 6개, 변이(링크 확장 2→0) 6개 중 4개 실패 | #94·#98 |
| 배포 계정 A·B 대화·기억 섞임 | 운영 | `study/class-3/d7-isolation-approval-1109.md`, 원자료 `study/class-3/d7-iso/`, 기록 `EVAL_REPORT.md:658` | 10가지 모두 막힘(2026-11-09 15:51~15:53 KST) | 표만 main(#85), 원자료 없음 |
| 배포 같은 승인 두 번 | 운영 | 같은 문서, `EVAL_REPORT.md:659` | 6가지 모두 막힘. 00032 재측정 6/6(`EVAL_REPORT.md:659` 같은 행) | 표만 main |
| 배포 질문창 인젝션 30건×3회 | 운영(공격문을 질문창에 붙임, 코퍼스에 심은 것 아님) | `study/class-3/d7-deploy/summary.json`, `study/class-3/d7-deploy-injection-1109.md` | 회차마다 막힘 18·일부 1·뚫림 11, 서버가 지시를 따라 답을 바꾼 것 0(문서 §1), 비용 합 0.090달러(0.03036+0.02964+0.03025, `summary.json`), 실제 답까지 간 것 0건 | 없음 |
| 로컬 문서 인젝션 30건 | 로컬(개인 API 키, 가짜 검색기, 운영 모델과 공급자 다름 → 참고값) | `study/class-3/d7-injection-1110/README.md`, 결과 JSON 2개(안전 판정, 사용량) | 30건 막힘 30·일부 0·뚫림 0, LLM 호출 319회, HTTP 449회 모두 200, 입력 1,183,293·출력 139,912 토큰, 비용 약 0.188달러, 207.7초 | 없음 |
| 출처 유출 15개 길 | 로컬(PR #60 코드, 가짜 모델) | `study/class-3/d7-leak-test.md`, `study/class-3/d7-leak/results-main.jsonl` | main `9a0baf9`에서 15/15 막힘, 3회 모두 `15 passed` | 없음 |
| D7 G2~G4 오탐 | 로컬 | PR #68 본문 | 저장된 평가 답 1,571개·청크 23,095개에서 새로 걸린 정상 글 0건 | #68 본문만 |
| warmup 실패 시 DB 연결 누수 | 로컬 | PR #62 본문, `study/class-3/warmup-pool-leak.md` | search() 10번 실패 뒤 연결 0→20(수정 전) → 0(수정 후) | 수정 코드만 main |
| 배포 실패 유형 다시 세기 | 운영 저장 행(새 호출 없음) | 브랜치 `d9-fail`: `evals/results/fail_types_00035/fail_types.json`·`fail_types.md` | v2 관련 75행 중 정답 위치 하나도 인용 안 함 2, 일부만 인용 4, 정답 밖 인용 11/74 | 없음(4절) |
| MCP 오버헤드 | 로컬(메모리 클라이언트, HTTP 없음) | `study/class-3/bench/results/mcp-overhead-2026-11-03.json` | 30문항 순서 같음 30/30, 직접 p50 1583.5ms·mcp p50 1635.2ms, 추가 p50 16.8ms·p95 213.6ms | 없음 |
| 임베딩 속도 100건 | 로컬+API | `study/class-3/embed-speed.md`, `bench/results/embed_speed-2026-10-31*.json` | voyage-4 100개 3.8초(왕복 합), e5-large 65.1초, bge-m3 65.5초(배치 16) | 없음(조장 `evals/results/speed100/`는 별도 도구) |
| 새 clone 확인(MCP 열림 조건 등) | 로컬 | `study/class-3/fresh-clone-check.md` | 판정 표 있음(성공 때 "검색 준비 완료" 로그가 안 남는 것은 예상과 다름으로 기록) | 없음 |
| 로컬 Langfuse 점수 연결·2회차 상한 비교 | 로컬(개인 API 키) | `study/class-3/d8-report-1108.md` | 문항 점수 21/21, 세션 점수 12/12 연결, 재검색 상한 2→1은 38번 회귀로 HOLD | 없음. 11/11 규칙(운영에서 측정)에 따라 공식 값으로 안 씀 |

## 4. 아직 main에 없는 작업 (로컬 브랜치, push 안 함)

기준 main `54f8e37`(`git rev-list --count 54f8e37..<브랜치>`). `d8-md`는 `d76baf3` 그대로 #125로 머지돼 남은 커밋 0.

| 브랜치 | 커밋 | 무엇을 고치나 |
|---|---|---|
| `fix-admin-refresh` | 2 | 권한 관리·리콜·승인함 화면 새로고침 때 "서버 응답 형식이 올바르지 않습니다" 오류. 화면과 API 주소가 같아 브라우저가 HTML을 캐시하던 것. 서버는 `no-store`·`Vary: Accept`, 화면 fetch는 `cache: 'no-store'`(4파일 +22/-2) |
| `google-login-v2` | 1 | 구글 로그인: 인증된 같은 이메일이면 기존 계정에 연결(`user_identities`, `db/203_google_identities.sql`), 계정 없으면 가입 대기, 설정 없을 때 로그인 화면 안내(14파일 +778/-43) |
| `fix-signup-edges` | 1 | 이메일 가입 모서리 3건: 미인증 신청 덮어쓰기, 거절 뒤 재가입(`db/112_signup_edges.sql`), 대문자 이메일 로그인(13파일 +426/-73) |
| `fix-auth-wording` | 1 | 로그인 칸 이름 "이메일 또는 아이디", 인증번호 다시 받기 화면 문구(5파일 +30/-16) |
| `docs-db-113` | 1 | PR #113 DB 변경(이메일 가입 인증)을 DB 문서 3개에 반영, auth 줄 번호를 최신 main에 맞춤(5파일 +56/-27) |
| `pr-safe` | 4 | 시험·문서 보강: loader DB 재시도 시험 2개, MCP `section_via_mcp` 시험 6개, 검색 Spec 스위치 3개, ingest.md 파일 목록(동작 변경 없음, 변이 시험 포함). `d76baf3`은 #125로 이미 main에 있어 위 4커밋만 남음 |
| `d8-md` | 0 | #125로 머지 완료 |
| `d9-fail` | 1 | 배포 `00035-h69` 저장 행으로 실패 유형 다시 세기(`fail_types.py`, EVAL_REPORT 5장 5-1~5-3, 결과 json·md, 시험 `tests/test_fail_types.py`)(6파일 +588/-6) |
| `sync2` | 4 | 문서 현행화(강사 코멘트·가이드·PRD/SDD 대조), 포트폴리오 1장 초안, 키 없는 데모 모드 시작 경고·requirements, admin-roles Spec 시험 경로 정정(62파일 +588/-239) |

주의: `google-login-v2`·`fix-signup-edges`·`fix-auth-wording`·`fix-admin-refresh`는 구글 로그인·가입 업무라 경희 담당 영역과 겹칠 수 있음(조장 11/11 새벽 지시로 대신 진행, 근거 `memory/class-3.md` 33행. 지시 원문은 이 문서에서 확인 못 함).

## 5. 남은 일

| 일 | 근거 |
|---|---|
| 4절 브랜치 8개를 PR로 올릴지 정함(본문·시험 결과 포함). 구글 로그인 PR은 운영 DB `db/203_...sql` 적용과 Cloud Run 설정 선행 필요 | PR #118 본문 "구글 로그인은 이 PR을 머지해도 바로 켜지지 않음", 브랜치 `google-login-v2` 커밋 메시지 |
| `docs/worklog.md`에 #58·#123·#125 누락(조장이 씀) → 조장에게 알림 | worklog에서 `#58`·`#123`·`#125` 검색 결과 0건 |
| 개발·측정 PR마다 정리 md(무엇을·왜·전후 숫자·한계·운영/로컬) 결과 json 옆에 둠. 현재 없는 곳은 `measurement-docs-inventory.md` 참고 | 11/11 본인 규칙, 팀 지침서 10장 "실험 결과" 행(`docs/TEAM_GUIDE.md:347+`) |
| 운영 대상 측정이 없는 인젝션: 코퍼스에 심은 간접 인젝션 배포 실측 | EVAL_REPORT 6장 시험 대상 문단(`EVAL_REPORT.md:636`). 조장 측정 결과 폴더(`injection_corpus_deploy_*`)가 따로 있어 본인 몫이 남았는지는 확인 못 함 |
| 포트폴리오 1장 제출(`docs/deliverables/portfolio-박진형.md`), 초안은 `sync2`에만 있음 | `docs/deliverables/portfolio.md` 안내문, 커밋 `80d6ca6` |
| 평가용 계정 DM 11/16, 프로젝트 종료 11/18 | `memory/class-3.md` 6행, 프로젝트 기간 |
