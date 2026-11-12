# PR 예정 — L-24 확인하지 못한 경로 로컬 실행
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 머지: 아직 안 함 / 기준: `origin/main` `601183c7`, 브랜치 `gap3-l24`

## 무엇을
- 2026-11-11 브라우저 E2E·API 점검이 확인하지 못한 11개 경로(브라우저 4, API 7)를 로컬 서버에서 실제로 돌려 결과를 적었다.
- `README.md` "키 없이 뜨는 데모 모드"의 L-24 항목에서 "확인한 결과가 없다"를 경로별 "로컬 확인(2026-11-12)"으로 바꿨다(조장 파일이라 그 항목 끝 문장만 고침).
- 코드는 고치지 않았다. 실행한 52행의 표는 이 문서 맨 아래 "로컬 실행 표"에 있다(통과 44, 실패 0, 못 함 4, 참고 4).

## 왜
- 조장 목록 L-24는 "두 점검이 실행하지 못한 경로를 동작한다고 적을 수 없다"는 확인 공백이다. 키 없이 로컬에서 돌릴 수 있는 경로는 돌려서 공백을 줄이고, 못 돌리는 경로는 이유와 함께 미확인으로 남기려는 것이다.

## 확인한 것(로컬)
근거 종류: [실측] 로컬 실행 결과. 운영 주소·LLM·키·네트워크 호출 없음.

| 경로 | 결과 | 비고 |
|---|---|---|
| 결정표 승인(화면) | 통과 | 승인 요청 대기 3건 표시, 승인 POST 200, 승인된 표 조회·실행 200. 초안은 스텁 모델이 만든 시드 |
| 합동 검토 쟁점표 승인·반려(화면) | 통과 | 반려는 사유가 비면 버튼 비활성, 확인 창 뒤 POST 200 rejected. 승인은 200 approved와 `issue_tables` 1행 저장. 쟁점표는 스텁 서버 |
| 리콜 알림 실데이터·피드백(화면) | 통과 | 규칙 판정과 합성 개정 사건(섹션 삭제)으로 알림 생성, 확인(미확인 3→2), "도움 됨" 의견 저장(집계 useful=2) |
| 되묻기 후속 문맥 | 통과·참고 | 되묻기 뒤 같은 대화에서 질문을 이어 가면 답이 붙고 대화 기록 4개. 후속 메시지는 앞 질문을 이어받지 않고 새 질문으로 처리됨 |
| 실제 세션 만료 | 통과 | 유효 시간만 6초로 줄임. POST /chat 401 → `/login?reason=expired`, 안내 문구, 재로그인 뒤 질문칸 유지 |
| SSE `approval_request`·`error` | 통과(스텁) / 못 함(LLM) | 스텁 서버에서 `approval_request` 하나로 끝, 같은 thread 새 질문 409, 모델 예외는 `error` 하나(내부 문구 숨김). 실제 LLM 경로는 못 함 |
| MCP `tools/list` 전체 | 통과 | 도구 6개, 토큰 없음·틀림·쿼리 토큰 401, `MCP_TOKEN` 없는 서버 `/mcp/` 404, 도구 호출 8종 상태값 확인 |
| SPA 폴백 | 통과·참고 | 빌드된 화면은 html 404(index)·json 404 한국어. dist 없는 서버는 `/` → `/login.html`, 화면 주소는 영어 `Not Found` 404 |
| Google 로그인 | 일부 통과 | 설정 없음 303 `/login?oauth_error=google_unavailable`, 가짜 값 설정 시 Google 인증 주소로 303(PKCE, `Secure` 쿠키), 콜백 거절 303. 실제 동의는 못 함 |
| 배포 쿠키 `Secure` | 일부 통과 | 개발 모드를 끈 로컬 서버에서 `provena_csrf`·`provena_auth` 모두 `Secure`. 배포 주소 응답은 못 함 |
| 결정표 convert의 실제 LLM | 못 함 | LLM 키 필요. 키 없는 데모의 예시 응답(201, `status=example`, 승인함에 안 올라감)은 통과 |
| 유지보수 후보 결정 | 통과 | 웹훅 개정 뒤 후보 50건, 일반 사용자 403·잘못된 값 422·틀린 CSRF 403·없는 id 404, 관리자 결정 200 |

## 한계
- 합동 검토 쟁점표와 SSE 이벤트는 모델·검색기를 `tests/`의 합성 가짜로 바꾼 서버로만 확인했다. 실제 LLM이 만든 초안·쟁점표·판정 문장은 확인하지 못했다.
- 리콜 알림은 규칙 판정과 합성 개정 사건으로 만들었다. DB 색인에는 같은 쪽의 다른 판이 없어 '수정' 사건은 알림 0건이라 '삭제' 사건을 썼다.
- 만료는 대기 방식이 아니라 유효 시간 단축이다. 쿠키 `Secure`는 비로컬 모드 로컬 서버에서만 봤다.
- 되묻기 뒤 후속 메시지가 앞 질문을 이어받지 않는 것이 설계인지는 조장 판단이다(코드에 이어받는 곳은 없음).
- 시험이 끝난 뒤 임시 DB `app_l24`와 서버는 지웠고 worktree의 `node_modules` junction도 풀었다.

## 로컬 실행 표
**로컬 확인** 2026-11-12. 운영 주소·LLM·키·네트워크 호출 없음.

- 코드: 브랜치 `gap3-l24`(origin/main `601183c7`)의 worktree. 코드는 고치지 않았다(만료 시험은 서버 시작 스크립트에서 모듈 상수만 바꿈).
- DB: 로컬 `pr1-pg`의 임시 DB `app_l24`(`db/*.sql` 번호순 적용 오류 0건), 색인 적재 함(청크 23,095개, 17.9초, 디스크 약 124MB, C: 여유 11GB에서 진행).
- 주 서버: `uvicorn backend.main:app` 127.0.0.1:18241, `DEMO_MODE=1`, `PROVENA_DEV_MODE=1`, `LLM_API_KEY` 비움, `SEARCH_WARMUP=0`, `PROVENA_OWNER_LOGIN_ID=demo-admin`, `RECALL_STORE=postgres`. 이 서버에 `MCP_TOKEN`을 주면 검색이 MCP 경로로 바뀌어 채팅 검색이 막혀서, MCP 시험은 `MCP_TOKEN`을 준 별도 서버(18242)에서 했다.
- 스텁 서버(18247): 실제 앱(`create_app`, Postgres, 로그인, SSE, 승인함)을 띄우고 질문 그래프의 모델·검색기만 `tests/`의 합성 가짜(`team_review_fakes`, `fake_search`)로 바꾼 서버. 합동 검토 승인과 SSE 이벤트는 키 없이 실제 LLM으로는 만들 수 없어 이 서버로 확인했다. 표에서 "스텁"이라고 적은 행이다.
- 시드: 결정표 승인 건은 변환 그래프를 스텁 모델로 한 번 돌려 승인 대기로 올렸다(초안은 `rules_from_cells` 기준 규칙). 승인 이후 경로만 실제 코드로 확인한 것이다. 리콜 알림은 웹훅으로 합성 개정 사건(섹션 삭제)을 보내 규칙 판정으로 만들었다(DB 색인에 같은 쪽의 다른 판이 없어 '수정' 사건은 알림 0건이라 삭제 사건을 썼다).
- 브라우저: 시스템 Chrome(headless)을 npx 캐시의 playwright-core로 구동(프로젝트에 설치 없음, `web/react-app`은 다른 작업 폴더의 node_modules를 junction으로 걸어 `npm run build`).
- 절차 메모: 첫 실행에서 결정표 실행 요청 필드를 `amount`로 잘못 보내 400이 났고(올바른 이름은 `amount_usd`), `explain_decision`의 없는 업무 기대값을 `not_found`로 잘못 적었다(문서 `docs/specs/mcp.md`는 승인된 표 0개를 `not_ready`로 정함). 둘 다 시험 입력·기대값 오류로 고쳐 다시 돌렸고 제품 결함이 아니다.

집계: 통과 44, 실패 0, 못 함 4, 참고(판정 대상 아님) 4

| 경로 | 요청/조작 | 기대 | 실제(상태코드·화면 문구) | 판정 |
|---|---|---|---|---|
| 유지보수 후보 목록 | 웹훅(링크 대상 페이지 개정) 후 GET /maintenance-candidates | 200 + 후보 1건 이상(pending) | 웹훅 202, 후보 50건, 첫 후보 needed: 참조 그래프: How to Perform CMOC Duties의 'Things to Know > How to Page the CMOC?' 섹션이 | 통과 |
| 유지보수 후보 결정 | 일반 사용자가 POST /maintenance-candidates/{id} needed | 403 | 403 {"detail":"관리자 권한이 필요합니다.","error":{"code":"forbidden","message":"관리자 권한이 필요합니다. | 통과 |
| 유지보수 후보 결정 | 관리자, status=bogus | 422 | 422 {"detail":"요청 형식이 올바르지 않습니다.","error":{"code":"validation_error","message":"요청 형식이 올바르지 않습니다.","requ | 통과 |
| 유지보수 후보 결정 | 관리자, 틀린 CSRF 헤더 | 403 | 403 | 통과 |
| 유지보수 후보 결정 | 관리자 POST needed | 200, status=needed, decided_by=관리자 | 200 status=needed decided_by=demo-admin | 통과 |
| 유지보수 후보 결정 | GET ?status=needed | 방금 결정한 후보 포함 | 200 1건 | 통과 |
| 유지보수 후보 결정 | 없는 후보 id | 404 | 404 {"detail":"함께 볼 정책 후보를 찾을 수 없습니다.","error":{"code":"not_found","message":"함께 볼 정 | 통과 |
| 결정표 convert(키 없는 데모) | 관리자 POST /decision-tables/convert Legal Contracts | 201, status=example, 저장·승인 대기 없음 | 201 status=example summary=예시 응답: Legal Contracts 결정표 초안 (키 없는 데모, 저장·승인되지 않음) 구간=6 | 통과 |
| 결정표 convert(키 없는 데모) | 그 뒤 GET /approvals | Legal Contracts 승인 건 없음 | 0건 | 통과 |
| 결정표 convert(실제 LLM) | LLM 키로 초안 생성 | 초안이 승인함에 올라감 | 키 없이는 실행 불가(키가 없으면 데모 고정 응답으로 내려감) | 못 함(LLM 필요) |
| 결정표 승인 뒤 | GET /decision-tables | 승인한 Approving expense 표 1개 | [('Approving expense', 'approved', 7)] | 통과 |
| 결정표 승인 뒤 | POST /decision-tables/run 30000달러 | 200 + 승인자 결과 | 200 {"table_id":"dt_cae43e4f0ca248a6","version_id":"0a3de8337541","band_label":"$25,000 초과 $50,000 이하","range_note":null,"approvers":["Director","PAO or VP Finance"],"functional_approvers":["Director"],"f | 통과 |
| MCP tools/list 전체 | Bearer 토큰으로 tools/list | 도구 6개 | 200 ['search_handbook', 'get_section', 'list_changed_sections', 'explain_decision', 'get_agent_trace', 'get_grounding'] | 통과 |
| MCP tools/list 전체 | 토큰 없음 | 401 | 401 | 통과 |
| MCP tools/list 전체 | 틀린 토큰 | 401 | 401 | 통과 |
| MCP tools/list 전체 | URL 쿼리 토큰 | 401 | 401 | 통과 |
| MCP tools/list 전체 | MCP_TOKEN 없는 서버(18241)의 /mcp/ | 열리지 않음(404·405) | 404 | 통과 |
| MCP 도구 호출 | get_section(Authorization Matrix) | status=ok + 원문 | 200 status=ok note=None keys=['status', 'retryable', 'results', 'as_of', 'source', 'note'] | 통과 |
| MCP 도구 호출 | get_section(없는 섹션) | status=not_found | 200 status=not_found | 통과 |
| MCP 도구 호출 | get_section(as_of 형식 오류) | status=invalid | 200 status=invalid as_of는 YYYY-MM-DD 형식의 실제 날짜: 'bad-date' | 통과 |
| MCP 도구 호출 | list_changed_sections | status=not_ready(증분 기록 없음, 빈 결과로 위장하지 않음) | 200 status=not_ready | 통과 |
| MCP 도구 호출 | search_handbook(키 없음) | status≠ok 이어도 이유(note)를 돌려줌 | 200 status=not_found note=fallback_reason=no_key n=0 | 참고 |
| MCP 도구 호출 | explain_decision(승인된 표, 3만 달러) | status=ok | 200 status=ok {'status': 'ok', 'retryable': False, 'results': [{'table_id': 'dt_cae43e4f0ca248a6', 'version_id': '0a3de8337541', 'approved': True, 'band_l | 통과 |
| MCP 도구 호출 | explain_decision(승인된 표가 없는 업무) | not_ready(문서: 승인된 표 0개는 '없다'가 아니라 not_ready) | 200 status=not_ready 업무 종류 '없는 업무'로 승인된 결정표가 0개라 실행하지 않는다 (정확히 1개일 때만 실행). 승인된 결정표가 아직 없거나 업무 종류 이름이  | 통과 |
| MCP 도구 호출 | get_agent_trace(실제 대화) | status=ok + 실행 단계 | 200 id=user:thread status=ok 단계 시간(duration_ms) = 같은 그래프(graph)의 앞 체크포인트와 이 체크포인트의 저장 시각(ts) 차이(노드 실행 + 저장).  keys=['status', 'retryable', 'results', 'as_of', 'source', 'note'] | 통과 |
| MCP 도구 호출 | get_grounding(실제 답) | status=ok 또는 not_found | 200 status=ok {'status': 'ok', 'retryable': False, 'results': [{'answer_id': '6e2b56208c68463da581081cbf7bf65b', 'grounding': {'llm':  | 통과 |
| SSE approval_request(스텁 모델) | POST /chat 합동 검토 요청 | 이벤트 approval_request 하나로 끝(done 없음), kind=issue_table, code=approval_pending | 200 text/event-stream; charset=utf-8 이벤트=['approval_request'] kind=issue_table code=approval_pending | 통과 |
| SSE approval_request(스텁 모델) | 승인 대기 중인 같은 thread에 새 질문 | 409 approval_pending | 409 {"detail":"승인 대기 중인 대화입니다. 관리자 승인이 끝난 뒤 이어 가세요.","error":{"code":"approval_pending","message":"승인 대기 중인 대화입니다. 관리자 승인이 끝 | 통과 |
| SSE error(스텁 모델 예외) | POST /chat 중 모델 예외 | 이벤트 error 하나(done 없음), 내부 오류 문구는 숨김 | 200 이벤트=['error'] code=internal_error message=답을 만드는 중 오류가 났습니다. 잠시 후 다시 시도해 주세요. | 통과 |
| SSE approval_request·error(실제 LLM) | 실제 모델의 분류·검토 | - | 키 없는 데모는 질문 분류(LLM)가 항상 정책 질문(rule)이라 합동 검토에 들어가지 못함(검토 요청 문장 3개 모두 search·no_key 거절 확인) | 못 함(LLM 필요) |
| 승인함 화면(관리자) | /approvals 로그인 후 열기 | 대기 3건(결정표 1, 쟁점표 2) | 3건 표시. 결정표 상세에 원문 대조표(원문 칸 77개, 전부 일치) | 통과(결정표 초안은 시드 스텁) |
| 쟁점표 상세 화면 | 쟁점표 건 선택 | 요청문과 쟁점 4행(팀·쟁점·입장·확신도·근거) | 표시됨. 제목에 '비공개 문서 1건은 근거에서 뺌' 표기 | 통과(스텁 모델) |
| 쟁점표 반려 | 사유 비움 → 사유 입력 후 반려하기 → 확인 창 확인 | 사유 없으면 버튼 비활성, 입력 뒤 POST 200 rejected | 버튼 비활성 true. POST /approvals/5c3f71c2… 200 status=rejected. 목록 3건→2건 | 통과 |
| 쟁점표 승인 | 승인하기 → 확인 | POST 200 approved + table_id | POST 200 approved, table_id 발급. DB issue_tables 1행 저장, approvals 상태 approved 1·rejected 1 | 통과 |
| 결정표 승인 | 승인하기 → 확인 | POST 200 approved, 목록 비면 안내문 | POST /approvals/ap_c67f… 200 approved. 목록 0건, '왼쪽 목록에서 승인 요청을 선택하면 상세 내용이 표시됩니다.' 표시 | 통과 |
| 리콜 알림 화면(실데이터) | 사용자 로그인 후 /recalls | 알림 카드와 변경 전후 원문 | 미확인 3건. 카드: 섹션명·질문·중요·결론 변경·확신도 90%·판정 설명·변경 전후 원문·원문 보기. 알림은 규칙 판정(RuleJudge)과 합성 개정 사건(섹션 삭제)으로 생성 | 통과(규칙 판정, LLM 아님) |
| 리콜 확인 | 확인 버튼 | 미확인 건수 감소 | 미확인 3건 → 2건(헤더 배지 '리콜 알림2') | 통과 |
| 리콜 피드백 | 도움 됨 버튼 | 안내문과 집계 반영 | '도움 됨으로 의견을 남겼습니다.' GET /recalls/feedback-stats useful=2(시험 2회 합계), not_useful=0. '필요 없음'은 누르지 않음 | 통과 |
| 리콜 다시 질문하기 | 다시 질문하기 클릭 | 채팅 화면으로 이동 | /chat 으로 이동 확인. 질문칸이 채워지는지는 읽지 않음 | 참고 |
| 되묻기 후속(키 없는 데모) | 새 대화 'Quuxbar Wombatron 승인 절차가 어떻게 돼?' 뒤 녹화 질문을 같은 화면에서 | 되묻기 문장 뒤 같은 대화에 인용 답 | 되묻기 '질문의 \'Quuxbar Wombatron\'은(는) 핸드북 자료에서 찾지 못했습니다…' → 같은 대화에 답과 [1] 인용·출처 안내. API로도 같은 thread_id 4개 메시지 확인 | 통과 |
| 되묻기 후속(합동 검토, 스텁) | 금액 빠진 요청 → 금액 넣은 요청, 같은 thread | 되묻기 뒤 승인 대기로 진행 | 1번째 clarify '검토에 필요한 값이 요청에 없습니다: 금액…', 2번째 approval_request. 대화 상태 pending_approval, 메시지 4개 | 통과(스텁 모델) |
| 되묻기 후속(앞 질문 이어받기) | 되묻기 뒤 '연 4만 달러야.'만 보냄 | 앞 질문을 이어받는지 | 이어받지 않고 새 질문으로 처리됨(스텁은 정책 질문으로 답함). 코드에 이전 질문을 합치는 곳이 없음(build.py에 '후속·history' 검색 0건). 실제 LLM 분류가 달리 볼 수는 없는지는 미확인 | 참고(설계 확인 필요) |
| 실제 세션 만료 | 토큰 유효 시간을 6초로 줄여(모듈 상수만 바꿈, 코드 수정 없음) 로그인 → 8초 뒤 질문 전송 → 다시 로그인 | 401 → /login?reason=expired, 안내 문구, 질문 유지 | POST /chat 401, URL /login?reason=expired, '로그인 시간이 만료되어 다시 로그인이 필요합니다. 쓰던 질문은 로그인 후 그대로 남아 있습니다.' 표시. 재로그인 뒤 /chat 질문칸 값 유지 | 통과(만료 시간만 단축) |
| Google 로그인 시작(설정 없음) | GET /auth/google/start (로컬 서버, GOOGLE_* 없음) | 303 → /login 안내 | 303 /login?oauth_error=google_unavailable | 통과 |
| Google 로그인 시작(가짜 클라이언트 값) | 비로컬 모드 서버에 가짜 GOOGLE_CLIENT_ID·SECRET·REDIRECT_URI | 303 → accounts.google.com 인증 주소(PKCE S256, state, nonce) + 요청 쿠키 | 303 https://accounts.google.com/o/oauth2/v2/auth?client_id=…&response_type=code&scope=openid…&code_challenge_method=S256. 쿠키 provena_google_oauth: HttpOnly; Max-Age=600; Path=/auth/google/callback; SameSite=lax; Secure | 통과(Google 호출 없음) |
| Google 로그인 콜백 거절 | GET /auth/google/callback?code=x&state=y, 인자 없음 | 303 → /login?oauth_error=google_login_failed | 두 요청 모두 303 /login?oauth_error=google_login_failed | 통과 |
| Google 로그인 실제 승인·토큰 교환 | 실제 Google 계정으로 동의 → 콜백 | 로그인·가입 대기 흐름 | Google 서버 접속과 계정이 필요해 실행하지 않음 | 못 함(외부 Google 필요) |
| 쿠키 Secure(비로컬 모드) | PROVENA_DEV_MODE 끈 서버에서 GET /auth/csrf, POST /auth/login | csrf·인증 쿠키에 Secure | provena_csrf: Max-Age=1800; Path=/; SameSite=lax; Secure. provena_auth: HttpOnly; Max-Age=1800; Path=/; SameSite=lax; Secure. 로컬 모드에서는 Secure 없음(코드 설계 그대로) | 통과(로컬 비로컬 모드, 배포 서버 아님) |
| 쿠키 Secure(실제 배포 주소) | 배포 주소의 Set-Cookie | Secure | 운영 주소 호출 금지라 실행하지 않음 | 못 함(운영 호출 금지) |
| SPA 폴백(화면 빌드됨) | /, /login, /chat, /recalls, /admin/users (Accept: text/html) | 200 React index | 모두 200 text/html(577B, root 있음). /favicon.ico 200 svg | 통과 |
| SPA 폴백(화면 빌드됨, 없는 주소) | /zz-no-such-page, /assets/zz.js (text/html), /api/zz·/zz-no-such-page (json) | html은 404+index, json은 404 한국어 JSON | html 404 text/html(index). json 404 {'detail':'요청한 경로를 찾을 수 없습니다.'…} | 통과 |
| SPA 폴백(화면 dist 없음) | dist를 치우고 서버 기동 후 / , /login.html , /login , /chat , /favicon.ico | 옛 화면으로 안내, 없는 화면은 404 | / 307 → /login.html(200, 옛 로그인 화면 1795B). /login·/chat·/favicon.ico·없는 주소는 404 JSON {'detail':'Not Found'…}(영어 문구, 한국어 오류 문구가 아님). /health 200 | 참고(영어 404 문구, dist 없는 개발 상태에서만) |

### 못 한 것과 이유

| 경로 | 이유 |
|---|---|
| 결정표 변환의 실제 LLM 초안 | LLM 키가 필요하다. 키 없는 데모는 예시 응답만 낸다 |
| 실제 LLM 경로의 SSE `approval_request`·`error` | 질문 분류가 LLM 호출이라 키 없는 데모는 합동 검토로 들어가지 못한다(검토 요청 문장 3개 모두 검색 단계 거절). 이벤트 모양은 스텁 서버로만 확인 |
| 실제 LLM 판정의 리콜 알림 | 규칙 판정으로만 확인(LLM 판정 문장은 확인하지 못함) |
| Google 실제 동의·토큰 교환 | 외부 Google 서버와 계정이 필요 |
| 배포 쿠키 `Secure`의 실제 응답 | 운영 주소 호출 금지. 비로컬 모드 로컬 서버에서만 확인 |
| 30분 실제 대기 만료 | 유효 시간만 6초로 줄여 만료 경로 확인(대기 방식은 아님) |

### 참고로 남기는 관찰(고치지 않음)

- 화면(dist)을 빌드하지 않은 서버는 `/login`·`/chat` 같은 화면 주소와 `/favicon.ico`가 영어 `Not Found` JSON 404다(옛 화면 폴더로 떨어지는 경로). `Dockerfile`이 `npm run build` 결과를 이미지에 넣으므로(5~8, 48줄) 빌드 없이 서버만 띄운 개발 상태 한정이다.
- 되묻기 뒤 후속 메시지는 앞 질문을 이어받지 않고 새 질문으로 처리된다. 설계인지는 조장 판단이다.
