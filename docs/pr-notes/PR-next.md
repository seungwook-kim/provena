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

## 1-2. 한 것 — 조장 11/15 새 목록
이 절은 D-15, H-34와 K-24 조사만 담는다(C-26, K-23은 다른 브랜치에서 처리).

| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| D-15 기준일이 전날로 나옴 | 기준일을 주지 않으면 서버(UTC) 날짜가 기본값이라 한국 00:00~09:00에는 전날이 나온다 | `backend/graph/state.py`에 `today_kst()`(고정 +9시간) 한 곳을 두고 사용자에게 보이는 기본 날짜 6곳이 이것을 쓴다(아래 '곳마다 판정'). 기존 시험 2개 파일의 `date.today()` 비교도 `today_kst()`로 바꿈(CI는 UTC라 15:00~24:00 UTC에 깨졌을 것) | [실측] `tests/test_today_kst.py` 13개: 2026-11-14 16:30 UTC → 2026-11-15, 14:59 UTC → 11-14, 15:00 UTC → 11-15, 12-31 16:00 UTC → 2027-01-01, 호출하는 곳 6개, 준 기준일은 그대로, 녹화 키 불변. 고친 줄 7개를 하나씩 되돌리면 7번 모두 시험 실패 |
| H-34 거절 안내가 사유와 무관하게 붙음 | 거절 말풍선에 "질문을 더 구체적으로 쓰거나 다른 표현으로 다시 물어봐 주세요."가 사유와 상관없이 붙는다(`DemoChatPage.jsx:155,171` 당시: 상태가 `no-evidence`이고 문장에 '다시'가 없으면 붙임) | 화면: `lib/chat-service.js`가 done의 `refuse_reason`(이미 있던 칸)과 이력의 `refuse_reason`을 `refuseReason`으로 담고, `pages/DemoChatPage.jsx` `showsNoEvidenceHint`가 `no_evidence`·`unsupported`·`citation_check`일 때만 붙인다. 사유를 모르면 붙이지 않는다. 서버: `backend/api/routes.py` `_messages`가 대화 이력의 거절 답에 같은 코드 `refuse_reason`을 싣는다(새로고침 뒤에도 같게) | [코드] 서버는 거절 done에 사유 코드를 이미 보낸다(`backend/graph/stream.py:64-66`, 코드 목록 `backend/graph/build.py:102-116`, `backend/services/step_cost.py:141-153`). [실측] `src/chat-notices.test.jsx` 붙는 경우 3건·붙지 않는 경우 7건·이력 1건, `src/lib/chat-service.test.js` 2건, `tests/test_api_thread_messages.py::test_refusal_history_carries_the_same_reason_code_as_the_chat_done_event` 2건. 고친 줄 5개를 하나씩 되돌리면 5번 모두 실패 |
| K-24 같은 데모 질문의 답이 실행마다 다름 (조사만) | 키 없는 데모에서 같은 녹화 질문이 실행마다 다른 답 글을 낸다 | 고치지 않았다(조사만). 원인 후보와 근거는 아래 'K-24 조사' | [실측] 녹화 저장소 모의 실행(그래프 전체 실행 아님, DB 없음) / [코드] |

**D-15 곳마다 판정** [코드]

| 곳 | 무엇 | 판정 |
|---|---|---|
| `backend/graph/build.py` 기본 기준일 | 답 끝 기준일 표시, 검색의 판 필터 | 한국 날짜로 바꿈 |
| `backend/graph/departments/review.py`, `single_review.py` | 팀 검토·단일 검토 기준일 | 한국 날짜로 바꿈 |
| `backend/api/changes.py` `since` 기본값 | 변경 목록 "최근 30일" 시작일 | 한국 날짜로 바꿈 |
| `backend/graph/recall/impact.py` `generated_on` | 영향 미리보기 보고서의 만든 날 | 한국 날짜로 바꿈 |
| `backend/graph/grounding.py` 기간 판정의 올해 | "2027년 기준" 같은 질문을 기간 밖으로 볼지 | 한국 날짜로 바꿈(해가 바뀌는 날 9시간) |
| `backend/api/eval_review.py:79` | 평가 검토 하루 호출 수 상한(프로세스 안 집계, 주석이 UTC 하루라고 적음) | 그대로(UTC). 사용자에게 날짜로 보이지 않음 |
| `backend/graph/recall/digest.py:32` | 리콜 하루 요약 날짜. 중복 방지 id와 웹훅 본문에 들어가고 CLI 도움말이 "오늘 UTC"라고 적음 | 그대로(UTC). 바꾸면 웹훅 받는 쪽 값이 바뀜. 사용자에게 보이는 날짜이긴 해서 후속 후보로 남김 |
| `backend/rag/ingest/handbook.py:267`, `rechunk_increments.py:335`, `hash_report.py:98`, `backend/rag/retrieve/index.py`, `backend/graph/decision/routes.py:277` | 수집일·저장 시각·결과 폴더 이름 | 그대로. 수집 메타데이터와 기술 시각 |

- `zoneinfo` 대신 고정 +9시간을 쓴 이유: `tzdata`가 `backend/requirements.txt`에 직접 없고 `psycopg`를 따라 들어온다 [실측: 시험 가상환경 `pip show tzdata`의 Required-by]. Docker `python:3.12-slim`에서 `ZoneInfo("Asia/Seoul")`가 되는지는 확인하지 않았다. 한국은 서머타임이 없어 고정 값으로 충분하다.
- 키 없는 데모 녹화와의 관계: 요청 키는 프롬프트 맨 앞 `기준일: YYYY-MM-DD` 줄의 날짜를 지우고 만든다(`backend/services/demo_replay.py:57,74-75`). 기준일이 들어가는 프롬프트(답·다시 쓰기·근거 확인, 팀 검토)는 모두 이 줄 꼴이라 D-15로 날짜가 달라져도 키는 같다 [실측: `test_replay_request_key_ignores_the_default_date_in_prompts`]. 녹화 191줄의 `user_preview`에 든 기준일은 2026-11-11·12·13으로 이미 여러 날이다 [실측].

**K-24 조사** (고치지 않음)

- 가장 유력한 원인 [실측 + 코드]: 재생 저장소가 같은 요청 키의 응답 변형을 "부를 때마다 차례로" 내는데(`backend/services/demo_replay.py:144-155` `pick_ranked`), 차례 카운터(`_turn`)가 프로세스에 계속 남고 질문이 끝나도 0으로 돌아가지 않는다. 한 실행이 그 키를 부르는 횟수가 변형 수의 배수가 아니면 다음 실행은 다른 변형부터 시작한다. 녹화에는 변형 6개짜리 근거 확인 키가 1개 있고(질문 "제3자가 프로덕션 데이터에 접근하거나…"), 근거 확인은 한 번에 3표를 부른다(`backend/graph/build.py:457-480`, `answer_fixes.py:703`). 이 키를 실행마다 3번씩 뽑아 다수결(`merge_votes`)로 합치면 실행 1·3은 `grounded=False`(2표), 실행 2·4는 `grounded=True`(3표)로 번갈아 나온다. 근거 확인이 실패하면 답을 다시 쓰거나 문장을 빼므로 답 글이 달라진다. 재현: 저장소 밖 스크립트로 `ReplayStore("data/demo_replay")`에서 키마다 4회 실행을 모의(순차 호출이라 스레드 경쟁은 뺀 값). 판정 키 10개 중 밀리는 키 1개는 결과가 같았고, 답 키 20개는 밀리지 않았다.
- 두 번째 후보 [코드]: 같은 키를 동시에 부르는 스레드가 변형을 가져가는 순서는 스레드 경쟁이다. 답 두 번 쓰기(`build.py:1059-1068`)에서 어느 스레드가 0번 변형을 받는지에 따라 동률일 때 뽑히는 답이 바뀔 수 있다. 재생은 변형 순번만큼 0.05초씩 늦춰 끝나는 순서를 맞추지만(`demo_replay.py:298-303`) 변형을 나눠 갖는 순서 자체는 맞추지 않는다. 추론 답과 빠른 답의 경쟁(`build.py:1281-1301`)도 예산(`GRAPH_ANSWER_BUDGET_S` 6.5초)에 걸리면 검색이 느린 실행만 빠른 답으로 간다.
- 세 번째 후보 [추정]: 녹화가 현재 코드와 어긋나 일부 요청이 결정적 가짜 응답으로 내려가는 것(K-22). 마지막 녹화 커밋 `40eea1f6`(11/13 03:43) 뒤로 `backend/prompts/question.py`(+105줄), `backend/graph/untrusted.py`(+406줄), `data/index.tar.gz`가 바뀌었다 [실측: `git diff --stat 40eea1f6 HEAD`]. 가짜 응답은 같은 입력에 같은 글이라 그 자체로는 실행마다 달라지지 않지만, 녹화에 있는 요청과 없는 요청이 섞이면 위 두 원인과 겹친다. 실제로 몇 건이 어긋났는지는 `python -m pytest -m demo_replay`(Postgres 필요)로만 알 수 있어 **확인하지 못했다**.
- 무작위 추출, 집합·사전 순서, 프롬프트 속 오늘 날짜는 원인이 아니다 [코드]: 가짜 응답은 입력만으로 정해지고(`demo_fallback`), 날짜 줄은 키에서 지운다.
- 고칠 방향(제안만): 변형 차례를 질문 실행 단위로 0부터 세기(실행 id별 카운터), 또는 다시 녹화. 어느 쪽이든 Postgres로 `-m demo_replay`를 돌려 확인해야 해서 이번에는 손대지 않았다.

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
| `backend/graph/` (11/15 목록) | 김승욱 | `state.py` `today_kst`, `build.py`·`grounding.py`·`departments/review.py`·`departments/single_review.py`·`recall/impact.py` 기본 날짜(D-15), `graph.md`·`departments.md`·`recall.md` |
| `backend/api/` (11/15 목록) | 김승욱 | `changes.py` 기본 `since`(D-15), `routes.py` 이력 `refuse_reason`(H-34), `api.md` |
| `web/` (11/15 목록) | 강경희(11/11부터 프론트는 박진형이 맡음) | `lib/chat-service.js`, `lib/chat-preview.js`, `pages/DemoChatPage.jsx`, 시험 2개, `web.md`(H-34) |
| `docs/` (11/15 목록) | 김승욱 | `specs/question-graph.md`, `specs/d6-chat-frontend.md`, `decisions.md` 2행, `docs.md`, `deliverables/ai_tools_log.md` 1행 |

## 4. 결정 (`docs/decisions.md`에 이유·버린 대안과 함께 적음)
- 가입 화면은 이메일 칸만 둔다(#8).
- GET 전용 API 경로의 HEAD는 405 + `Allow`(C-24). HEAD를 GET처럼 실행하는 안은 스트림 경로 위험으로 버림.
- `/me` 첫 확인은 머리글로 알린다(H-33). 주소 `?optional=1`은 화면 시험 15개 파일이 주소를 `'/me'`로 비교해 버림.
- 사용자에게 보이는 기본 날짜는 한국 날짜, 고정 +9시간 한 곳(D-15). `zoneinfo`, 컨테이너 `TZ`, 화면이 날짜를 보내는 안은 버림.
- 거절 안내는 근거 부족 사유 허용 목록일 때만, 사유를 모르면 붙이지 않음(H-34). 제외 목록, 문장 글자 비교, 화면만 고치는 안은 버림.

## 5. 시험
- 전체 vitest: `npx vitest run`(web/react-app) 40파일 442개 통과.
- 대상 pytest: `python -m pytest -q tests/test_answer_fixes.py tests/test_api_path_guards.py tests/test_me_optional_session.py tests/test_deploy_corpus_injection_ext.py tests/test_signup_edges.py tests/test_untrusted.py` 215 통과, 11 건너뜀.
- 전체 pytest: `python -m pytest -q` 4120 통과, 1 실패, 123 건너뜀(24분 18초). 실패한 `tests/test_llm_openrouter.py::test_real_transport_retries_a_stuck_attempt`는 시간 상한 시험(1.4초 안이어야 하는데 이 PC에서 4.5초)이고, 이 브랜치가 바꾸지 않은 `backend/services/`를 본다. 바꾸지 않은 main(`fa98819a`)에서도 같은 환경으로 단독 실행하면 똑같이 실패한다 [실측]. 11/14 Docker Python 3.12 전체 실행(main `fa98819a`)에서는 통과했으므로 이 PC·3.13 환경 탓으로 본다 [추정]
- **환경**: 팀 CI(Docker Python 3.12)가 아니라 로컬 Python 3.13 가상환경(`backend/requirements-dev.txt`)으로 돌렸다. Docker가 꺼져 있었고 매번 패키지를 다시 받아야 했다. PR CI가 3.12로 다시 돌린다. DB 시험은 DB가 없어 건너뜀.
- 변이: 고친 줄을 되돌리면 #5 시험 5개, C-24 시험 1개, H-33 서버 시험 1개, H-33 화면 시험 1개가 실패했고, 끝난 뒤 원본으로 되돌렸다(`if False` 0건 확인).
- **11/15 목록(1-2절) 시험**
  - 전체 vitest: `npx vitest run`(web/react-app) 40파일 454개 통과.
  - 대상 pytest 17개 파일: `python -m pytest -q tests/test_today_kst.py tests/test_multi_graph.py tests/test_question_graph.py tests/test_api_changes.py tests/test_api_thread_messages.py tests/test_impact_preview_contract.py tests/test_impact_empty_section.py tests/test_team_review.py tests/test_exp_review.py tests/test_ground_caveat.py tests/test_ground_caveat_votes.py tests/test_ground_partial_ahead.py tests/test_demo_replay.py tests/test_demo_replay_fresh.py tests/test_api_chat.py tests/test_api_threads_store.py tests/test_graph_search_wiring.py` 1077 통과, 1 건너뜀, 2 제외(`demo_replay` 표지, Postgres 필요). 같은 로컬 Python 3.13 가상환경.
  - 전체 pytest는 이 절 작업에서는 돌리지 않았다(세 브랜치를 합친 뒤 한 번 돌린다).
  - 변이: D-15 7개(도우미 1, 호출하는 곳 6), H-34 5개(서버 이력 1, 화면 판정 2, 화면 사유 담기 2)를 하나씩 되돌려 12번 모두 시험이 실패했고, 끝난 뒤 원본으로 되돌렸다(변이 표식 0건, `git status`는 의도한 파일만).
  - `python docs/api/export_openapi.py`를 다시 돌려도 `docs/api/openapi.json`은 바뀌지 않았다(대화 이력 `messages`는 형식을 선언하지 않은 응답).

## 6. 하지 않은 것
- (11/15 목록) K-24는 조사만 했다. 키 없는 데모를 Postgres로 실제 돌려 답이 달라지는 것을 재현하지는 않았다(DB 작업 금지). `-m demo_replay` 시험도 같은 이유로 돌리지 못해 녹화가 현재 코드와 맞는지(K-22)는 모른다.
- (11/15 목록) 리콜 하루 요약 날짜(`recall/digest.py`)는 UTC 그대로 뒀다. 거절 말풍선의 머리표 "근거 부족"은 핸드북 밖 질문에도 그대로 나온다(H-34는 안내 문장만 다룸).
- (11/15 목록) `docs/SPEC.md`에는 기본 기준일과 거절 안내를 적은 곳이 없어 바꾸지 않았다(기능 Spec 2개만 고침).
- L-23(키 없는 데모의 합동 검토·리콜 알림 화면), L-24(점검이 못 본 경로)는 이번 묶음에 넣지 않았다. 운영 확인 또는 큰 작업이 필요하다.
- `ai_tools_log.md` '지킨 규칙'의 김승욱·강경희 칸, 강경희 '가장 크게 틀렸던 사례', 김승욱 사례 2개 중 하나 고르기 — 본인이 써야 한다.
- `EVAL_REPORT.md:143` MRR 0.733(결과 파일은 0.722), `:199` int8 Recall 0.758(로컬 30조합 기준 0.750) — 이번 묶음에 넣지 않았다.
- SDK(`mock_erp/sdk/`)는 다시 만들지 않았다. `/me` 메서드 이름이 그대로라 `test_sdk_matches_openapi`는 영향이 없다.
- compose로 `/demo/*`가 실제로 열리는지는 띄워 보지 않았다(1절 H-25).
