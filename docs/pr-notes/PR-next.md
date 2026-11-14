# 다음 묶음 — 조장 11/13 목록 남은 6건과 #157 후속 문서 정리
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `fde5ad2d`(#158까지)를 합친 브랜치 `next-1114`
- 근거 종류 표기: [코드] `파일:줄` / [문서] 팀 문서 / [실측] 직접 돌린 결과 / [추정].
- 운영 호출·DB 작업·LLM·Voyage 호출 없음.
- **다른 사람 폴더를 고쳤다(TEAM_GUIDE 4장 1번 예외).** 조장이 "놓친 것 목록을 다 해결하라"고 지시했고, 11/11에 프론트도 박진형에게 넘겼다(`web/web.md` "프론트를 박진형이 맡음 11/11"). 고친 폴더의 md마다 "조장 지시로 처리"라고 적었다. 폴더별 주인은 아래 3절.

## 1. 한 것 — 조장 11/13 목록 남은 6건
| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| 새로 발견 5 되묻기 `javascript:` | 되묻기 거름 `_ECHO_URL`이 `이름://` 꼴만 주소로 봐서 `javascript:alert(1)`이 되묻기 글에 따옴표로 인용됐다 | `backend/graph/answer_fixes.py` `_ECHO_URL`에 `//` 없는 스킴(`javascript` `vbscript` `data` `file` `blob` `mailto` 뒤 쌍점)을 더함. 일반 단어 뒤 쌍점(`Note:`)은 그대로 인용 | [실측] `tests/test_answer_fixes.py::test_reprompt_does_not_echo_schemes_without_slashes` 5건(실제 경로 `quotable_phrases` → `unknown_name_message`), `test_echo_safe_keeps_words_before_a_colon`. 추가한 줄을 빼면 5건 실패 |
| 새로 발견 8 가입 아이디 칸 | 가입 화면 아이디 칸이 이메일 형식이라 아이디 꼴은 화면에서 가입할 수 없음(조장: "설계 의도일 수 있음") | 코드는 바꾸지 않고 설계로 판정해 `docs/specs/106-signup-approval.md` Edge Cases와 `docs/decisions.md`에 적음 | [코드] 화면 가입은 인증번호 흐름(`SignupPage.jsx` `submit`이 `verification_expires_at`을 요구), 서버는 비이메일이면 `approval_pending`(`backend/auth.py` signup). 화면에 열면 인증 없는 신청 경로가 생김 |
| C-24 `HEAD /threads` 404 | `/threads`는 GET 전용이라 HEAD 경로가 없어 `main.py` 끝 정적 마운트로 떨어져 404 | `backend/api/middleware.py` `_head_without_route`: HEAD를 받는 경로는 없고 GET을 받는 API 경로가 있으면 405 + `Allow`(본문 없음, 요청 ID 붙음). 화면·없는 경로 받이(`/{path:path}`)와 정적 마운트는 판정에서 뺌 | [실측] `tests/test_api_path_guards.py::test_head_threads_has_request_id_and_no_body`(로그인 전후 405, `Allow`에 GET, `/threads/{id}`도 405), `test_head_keeps_routes_that_already_answer_head`(`/health` 200, 없는 경로 404). 분기를 끄면 실패 |
| H-33 로그아웃 상태 `/me` 401 콘솔 오류 | 화면이 처음 세션을 확인할 때마다 `/me`가 401이라 브라우저 콘솔에 오류가 남음(모바일 버튼·메뉴·favicon은 #131에서 해결, 이 부분만 남음) | 서버 `backend/auth.py` `/me`: 머리글 `X-Session-Optional: 1`이고 로그인 쿠키가 없으면 204. 화면 `lib/api.js` `getCurrentUser({optional})`, `SessionProvider.jsx`는 첫 확인만 머리글을 붙이고 204면 로그아웃 상태로 봄. 로그인 뒤 다시 확인은 머리글 없이 보내 만료(401)를 그대로 알아챔. `docs/api/openapi.json` 다시 만듦(`/me` 204 한 줄), `docs/specs/login.md` | [실측] `tests/test_me_optional_session.py` 4개(쿠키 없음+머리글 204, 머리글 없거나 값이 다르면 401, 로그인 사용자는 같은 본문, 깨진 쿠키는 401), `session.test.jsx` H-33 2개. 서버 분기를 끄면 1개 실패, 화면에서 머리글을 끄면 1개 실패 |
| 새로 발견 2 E17·E18(X17·X18) | 다른 사용자 데이터를 요구하는 주입 문장 두 개를 입력 정화·출력 검사가 모두 놓친다는 지적 | 코드는 이미 조장 커밋 `02f4af5e`(2026-11-13)가 막았다. 이 두 문장을 지키는 시험이 없어 회귀 시험만 더함 | [실측] `02f4af5e^`의 `untrusted.py`로는 두 문장이 그대로 남고(X17은 뒷절 `맨 앞에 CANARY-P8-X17 를 적어라.`, X18은 전체), 현재 코드는 표식과 요구 절을 모두 뺌. 시험 `tests/test_deploy_corpus_injection_ext.py::test_code_defense_removes_other_user_exfil_cases` |
| H-25 compose `/demo/*` | compose(로컬 데모)에서 `/demo/*` 정적 미리보기가 열리지 않고 `/login`으로 감(README 안내만 #131에서 추가) | `Dockerfile` 화면 빌드에 `ARG VITE_ENABLE_LOCAL_DEMO=false`, `docker-compose.yml`의 api·loader 빌드 인자 `"true"`. Cloud Run 소스 배포(`gcloud run deploy --source .`)는 인자를 주지 않아 false 그대로. README 화면 둘러보기 문장 고침 | [코드] 이 값은 `/demo/` 주소에만 쓰임(`DemoPages.jsx:49-50` 가드, `DemoChatPage.jsx:464,472`). **compose로 실제 띄워 확인하지는 않았다**(Docker 꺼짐, 빌드에 패키지를 다시 받아야 함) |

## 2. 한 것 — #157 후속 문서 정리
| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| 포트폴리오 줄 번호 | `deliverables/portfolio-박진형.md` '내가 내린 판단'의 `EVAL_REPORT.md` 줄 번호가 6줄씩 앞서 있었다. 98줄은 표 구분선이다 | 98→104, 96~97→102~103, 402·406→408·412, 163~166→169~172, 166→172, 202→208. 머리말 기준 커밋을 `fde5ad2d`(#158 머지)로. #158이 EVAL_REPORT 491줄 뒤에 4줄을 더해 표의 491줄 이후 참조 14개도 +4 | [실측] 현재 main에서 각 줄을 열어 확인: 104줄 2-3행(arctic + bge), 408줄 `arctic-l-v2` 하이브리드 + bge 0.893, 412줄 72조합 1위 설명, 172줄 통과선 0.822, 208줄 조합 평균 표. 491줄 이후 참조(508·513·524·525·602·733·734·756·873·874·892·942·969~973)도 내용 대조 |
| AI 도구 기록 형식 | `deliverables/ai_tools_log.md`: 강경희 11/10 행이 표 밖 '가장 크게 틀렸던 사례' 절 안(김승욱 두 문단 사이)에 끼어 문단으로 보였다. 박진형 사례가 7개였다(양식은 사람마다 1개) | 그 행을 표 안 강경희 11/10 행 아래로 옮겼다. 박진형 사례는 첫 번째만 남기고 6개를 파일 끝 '그 밖에 틀렸던 사례 (참고)' 절로 옮겼다. 김승욱 두 문단 사이에 빈 줄 | [실측] 고치기 전후 줄 집합 비교 같음(추가한 제목·안내 2줄 제외). 글 내용은 바꾸지 않았다 |
| PR-157 이름·기록 칸 | #157 작업 내역이 `PR-next.md`, 박진형 기록 칸 20개가 `미정`이었다 | `PR-157.md`로 바꾸고 머지 시각·커밋을 적음. 기록 칸 20개 `#157` | [실측] 줄마다 `git blame` 커밋이 `bb39832b`(#156)에는 없고 `fa98819a`(#157)에 들어 있음 |

## 3. 다른 사람 폴더 (TEAM_GUIDE 5장 주인)
| 폴더·파일 | 주인 | 바꾼 것 |
|---|---|---|
| `backend/auth.py` | 강경희 | `/me` 머리글 `X-Session-Optional` 분기(H-33). **경희님께 따로 알림 필요** |
| `web/` | 강경희(11/11부터 프론트는 박진형이 맡음) | `lib/api.js`, `components/SessionProvider.jsx`, `session.test.jsx`, `web.md` |
| `backend/graph/` | 김승욱 | `answer_fixes.py` `_ECHO_URL`(#5), `graph.md` |
| `backend/api/`, `main.py` 쪽 | 김승욱 | `middleware.py` HEAD 405(C-24), `api.md` |
| `docs/`, `README.md`, `Dockerfile`, `docker-compose.yml` | 김승욱 | Spec 2개, `decisions.md` 3행, `openapi.json`, 포트폴리오·AI 도구 기록, `/demo` 빌드 인자 |

## 4. 결정 (`docs/decisions.md`에 이유·버린 대안과 함께 적음)
- 가입 화면은 이메일 칸만 둔다(#8).
- GET 전용 API 경로의 HEAD는 405 + `Allow`(C-24). HEAD를 GET처럼 실행하는 안은 스트림 경로 위험으로 버림.
- `/me` 첫 확인은 머리글로 알린다(H-33). 주소 `?optional=1`은 화면 시험 15개 파일이 주소를 `'/me'`로 비교해 버림.

## 5. 시험
- 전체 vitest: `npx vitest run`(web/react-app) 40파일 442개 통과.
- 대상 pytest: `python -m pytest -q tests/test_answer_fixes.py tests/test_api_path_guards.py tests/test_me_optional_session.py tests/test_deploy_corpus_injection_ext.py tests/test_signup_edges.py tests/test_untrusted.py` 215 통과, 11 건너뜀.
- 전체 pytest: `python -m pytest -q` 4120 통과, 1 실패, 123 건너뜀(24분 18초). 실패한 `tests/test_llm_openrouter.py::test_real_transport_retries_a_stuck_attempt`는 시간 상한 시험(1.4초 안이어야 하는데 이 PC에서 4.5초)이고, 이 브랜치가 바꾸지 않은 `backend/services/`를 본다. 바꾸지 않은 main(`fa98819a`)에서도 같은 환경으로 단독 실행하면 똑같이 실패한다 [실측]. 11/14 Docker Python 3.12 전체 실행(main `fa98819a`)에서는 통과했으므로 이 PC·3.13 환경 탓으로 본다 [추정]
- **환경**: 팀 CI(Docker Python 3.12)가 아니라 로컬 Python 3.13 가상환경(`backend/requirements-dev.txt`)으로 돌렸다. Docker가 꺼져 있었고 매번 패키지를 다시 받아야 했다. PR CI가 3.12로 다시 돌린다. DB 시험은 DB가 없어 건너뜀.
- 변이: 고친 줄을 되돌리면 #5 시험 5개, C-24 시험 1개, H-33 서버 시험 1개, H-33 화면 시험 1개가 실패했고, 끝난 뒤 원본으로 되돌렸다(`if False` 0건 확인).

## 6. 하지 않은 것
- L-23(키 없는 데모의 합동 검토·리콜 알림 화면), L-24(점검이 못 본 경로)는 이번 묶음에 넣지 않았다. 운영 확인 또는 큰 작업이 필요하다.
- `ai_tools_log.md` '지킨 규칙'의 김승욱·강경희 칸, 강경희 '가장 크게 틀렸던 사례', 김승욱 사례 2개 중 하나 고르기 — 본인이 써야 한다.
- `EVAL_REPORT.md:143` MRR 0.733(결과 파일은 0.722), `:199` int8 Recall 0.758(로컬 30조합 기준 0.750) — 이번 묶음에 넣지 않았다.
- SDK(`mock_erp/sdk/`)는 다시 만들지 않았다. `/me` 메서드 이름이 그대로라 `test_sdk_matches_openapi`는 영향이 없다.
- compose로 `/demo/*`가 실제로 열리는지는 띄워 보지 않았다(1절 H-25).

### D-14 이어 묻기(팀장 결정 ①)
- 작업자: 박진형 (jinyeong-731). 팀장이 ①(앞 질문을 함께 넘겨 완전한 질문으로 다시 쓰고 "이렇게 이해했습니다"를 보임)을 골랐고 조장 지시로 처리했다. 버린 대안 ② 되묻기, ③ 동결 전 안 함은 `docs/decisions.md` 2026-11-15 행.
- **다른 사람 폴더를 고쳤다(TEAM_GUIDE 4장 1번 예외, 조장 지시)**: `backend/graph/`·`backend/prompts/`·`backend/api/`·`docs/`(김승욱), `web/`(강경희, 11/11부터 박진형이 맡음). `backend/schemas/`는 바꾸지 않았다.
- 실제 LLM·Voyage 호출, DB, 운영 호출 없음. 시험은 가짜 모델과 메모리 체크포인터다.

**설계 요약** (정본은 `docs/specs/question-graph.md` '이어 묻기' 절)
1. 앞 질문이 오는 곳: `/chat`이 질문마다 그래프 입력에 `asked: [질문]`을 더한다. 상태 칸 `asked`의 합치기 규칙이 같은 thread(`<user_id>:<thread_id>`)의 체크포인트에 최근 3개(지금 + 앞 2개)를 쌓는다. 그래프가 실행을 시작할 때 같이 열리므로 `/chat`은 체크포인트를 더 읽지 않는다.
2. 다시 쓰기: 앞 질문이 있을 때만 `load_memory` 다음에 `followup` 노드를 지난다. LLM 1회(`[[task:rewrite_followup]]`, `backend/services/llm.py`로 받은 같은 모델), 출력 `{"followup": bool, "question": "..."}`. 직전 질문을 다시 썼으면 다시 쓴 쪽을 앞 질문으로 넘긴다.
3. 실패 처리: 이어 묻기가 아님, JSON 아님, 빈 값, 4000자 초과, 호출 예외, 코드 검사(내부 표식·프롬프트 문장, 프롬프트 요구, 가짜 자료 구분자, 지시 문장)에 걸림 → 원 질문 그대로 답한다. 비용 상한 예외만 올린다. 형식이 깨져도 다시 묻지 않는다.
4. 안전: 앞 질문은 프롬프트에 넣기 전에 지시 문장·구분자·프롬프트 요구를 빼고 한 줄 500자로 자른다. 프롬프트 요구뿐인 지금 질문은 다시 쓰지 않아 `classify`가 친 글로 범위 밖 처리한다. 그 밖의 검사(범위 밖 분류, 시점 표현, 되묻기, 기간 검사)는 다시 쓴 질문으로 돈다.
5. 화면: 다시 썼을 때만 `done.understood_question`. 화면은 답 위에 "이렇게 이해했습니다: …". 대화 이력의 질문 글과 대화 제목은 친 글 그대로, 다시 쓴 질문은 그 답 항목의 `understood_question`.
6. 끄기: `CHAT_FOLLOWUP=0`(기본 켬). `.env.example`에는 넣지 않았다(서비스 값 묶음을 시험이 대조하는 파일이라 건드리지 않음).

| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| 앞 질문 전달 | 그래프 입력이 지금 질문 하나뿐이라 "고객은요?"가 새 질문으로 처리됨 | `backend/api/routes.py` `chat_events`가 `asked: [질문]`을 더함, `backend/graph/state.py` `asked` 칸(합치기 규칙 `keep_recent_questions`)과 `previous_questions` | [코드] `backend/api/routes.py:272-273`, `backend/graph/state.py:11-34,45` / [실측] `test_chat_passes_only_same_user_same_thread_questions`(앨리스 t1·t2, 밥 t1을 섞어 보내도 그 사용자의 그 대화 질문만, 최대 2개) |
| 다시 쓰기 노드 | 이어 묻는 질문을 완전한 질문으로 바꾸는 단계가 없음 | `backend/graph/build.py` `followup` 노드와 `load_memory`의 조건 분기, `backend/prompts/question.py` `FOLLOWUP_SYSTEM`·`followup_prev`·`followup_user`·`followup_question` | [코드] `backend/graph/build.py:546-564,1762-1764`, `backend/prompts/question.py:107-118,517-560` / [실측] `test_followup_question_is_rewritten_and_used_downstream`(분류·재작성·판정·답 입력이 다시 쓴 질문), `test_followup_question_reaches_first_search_when_decompose_is_on`(첫 검색 질의) |
| 첫 질문은 그대로 | 새 단계가 첫 질문과 평가 경로를 바꾸면 안 됨 | 앞 질문이 없으면 노드를 지나지 않음(호출 0, 노드 순서 `load_memory -> classify` 그대로) | [실측] `test_first_question_makes_no_followup_call_and_skips_the_node`, `test_chat_first_question_of_a_named_thread_makes_no_call`. 기존 시험 파일 31개 1,517개가 고치지 않고 통과 |
| DB 왕복 | 처음 설계(질문 전에 `get_state`로 앞 질문 읽기)는 사전 등록 62.16에서 없앤 체크포인트 읽기를 되살려 기존 시험 4개가 실패 | 상태 칸에 쌓는 방식으로 바꿔 `/chat`의 `get_state` 호출 수가 그대로 | [실측] 첫 설계에서 `tests/test_chat_final_from_stream_paths.py` 4개 실패 → 바꾼 뒤 통과, `test_chat_new_thread_reads_no_history`(`get_state` 0회) |
| 실패해도 답함 | 다시 쓰기 실패가 요청을 막으면 안 됨 | 모든 실패는 원 질문으로 진행, 비용 상한만 올림 | [실측] `test_bad_followup_reply_falls_back_to_the_original_question` 11가지, `test_cost_cap_is_not_swallowed` |
| 앞 질문 속 지시 | 앞 질문이 다시 쓰기 프롬프트에 지시로 들어가거나, 다시 쓴 질문(뒤 단계에서 사용자 질문으로 취급)에 옮겨질 수 있음 | 입력 정화(`followup_prev`)와 응답 검사(`followup_question`) | [실측] `test_instructions_in_previous_questions_never_reach_the_prompt` 3가지, `test_previous_questions_are_one_line_cut_and_cannot_fake_delimiters`, `test_rewritten_question_with_instruction_or_marker_is_dropped` 5가지, `test_prompt_request_is_not_rewritten` |
| 화면 전달 | 다시 쓴 질문을 사용자가 볼 길이 없음 | `backend/graph/stream.py` `done.understood_question`(이번 실행이 다시 썼을 때만), `routes.py` `_messages`(질문 글은 친 글, 답 항목에 `understood_question`), 화면 `lib/chat-service.js`·`pages/DemoChatPage.jsx`·`styles.css` | [코드] `backend/graph/stream.py:64-65`, `backend/api/routes.py:182-185,201` / [실측] `test_chat_done_has_understood_question_only_when_rewritten`, `test_thread_messages_keep_typed_text_and_carry_understood_question`, `test_next_question_does_not_inherit_understood_question`, `web/react-app/src/followup-understood.test.jsx` 4개 |
| 멀티 그래프 | Supervisor가 `load_memory`·`classify`를 직접 불러 새 분기를 타지 않음 | `backend/graph/multi.py` 첫 방문에서 같은 분기와 노드를 부름. 하위 에이전트 `reads`는 그대로(`question`만 읽는다) | [코드] `backend/graph/multi.py:361-362` / [실측] `test_multi_graph_rewrites_followup_like_single`(단일과 호출 순서·결과 같음), `test_stream_done_has_understood_question_only_when_rewritten[multi]` |
| 단계 이름·비용 | 새 호출이 단계별 비용과 Langfuse에 잡혀야 함 | 따로 등록할 목록이 없다: 단계 이름은 노드와 표지에서 자동으로 `followup/rewrite_followup` | [코드] `backend/services/llm_trace.py:130-133` / [실측] `test_step_name_follows_node_and_task` / [추정] Langfuse 화면에서 실제로 그 이름으로 보이는지는 띄워 보지 않았다 |

**평가·녹화 재생 영향**
- 평가 실행기(`evals/agent/run_eval.py:63-68`, `exp_review_v1.py:316`, `exp_joint_review.py:169,195`, `evals/ci_current_eval.py:206-208`)는 문항마다 새 thread로 `graph.invoke`를 직접 부르고 `asked`를 넘기지 않는다 → `followup` 노드를 지나지 않고 호출·입력·답이 그대로다. 달라지는 것은 상태에 빈 목록 `asked: []` 칸이 하나 더 생기는 것뿐이다 [코드]. 배포 응답 시간 측정(`evals/latency/deploy_latency.py`)은 `thread_id` 없이 문항마다 새 대화라 앞 질문이 없다 [코드: 같은 파일 12행 설명]. **평가셋 재측정은 하지 않았다**(유료 호출).
- 키 없는 데모: 녹화한 질문은 대화의 첫 질문이라 새 호출이 없고 요청 키가 그대로다. 같은 대화의 둘째 질문부터는 녹화에 없는 `rewrite_followup` 호출이라 재생 모델이 고정 문장을 돌려주고(JSON 아님) 원 질문 그대로 간다 [실측: `test_replay_model_keeps_the_original_question`, `tests/test_demo_replay.py`·`test_demo_replay_fresh.py`·`test_demo_record_roundtrip.py` 통과]. 다시 녹화하지 않았다.
- `docs/api/openapi.json`: 요청 모양과 응답 모델이 그대로라 바뀌지 않는다(`python docs/api/export_openapi.py` 뒤 diff 없음) [실측].

**확인하지 못한 것**
- 실제 모델이 이어 묻는 질문을 얼마나 정확히 가려내고 다시 쓰는지(가짜 모델로만 시험). 프롬프트 문구는 한 번도 실제 모델에 넣어 보지 않았다.
- 둘째 질문부터 늘어나는 LLM 호출 1회의 응답 시간·비용.
- 브라우저에서 실제 서버와 이은 화면(vitest의 가짜 fetch로만 확인).
- 이 기능 전에 만든 대화는 `asked`가 비어 있어 배포 뒤 첫 질문은 앞 질문 없이 처리된다(그다음 질문부터 이어진다) [코드].

**시험** (로컬 Python 3.13 가상환경, 키·DB 없음)
- 새 시험: `python -m pytest -q tests/test_followup_question.py` 45개 통과. `npx vitest run src/followup-understood.test.jsx` 4개 통과.
- 대상 pytest 32개 파일(새 파일 포함: 질문 그래프, 멀티, 채팅 API, 대화 이력, 스트림 최종값, 녹화 재생, 정화·안전, MCP 기록, 결정표·합동 검토, 속도 스위치, 평가 실행기): 1,562 통과, 2 건너뜀, 2 제외. 전체 pytest는 돌리지 않았다(합친 뒤 돌린다).
- 전체 vitest: `npx vitest run` 41개 파일 446개 통과.
- 변이 16개(앞 질문 전달, 다시 쓴 질문 쓰기, `done` 칸, 앞 질문 정화, 응답 검사 2, 예외 처리, 첫 질문 분기, 멀티, 최근 2개 상한, 다시 쓴 앞 질문, 대화 이력 글, 끄는 스위치, 화면 표시, 화면 값 받기, 다시 연 대화): 모두 새 시험이 실패로 잡았고, 끝난 뒤 원본 바이트 대조와 변이 표식 0건을 확인했다.
