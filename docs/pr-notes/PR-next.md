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

### K-23 로컬 데모 재시작 뒤 내 정보 503
- 작업자: 박진형 (jinyeong-731). 조장 11/15 목록 K-23(조장 지시로 처리). 운영 호출·DB·compose 실행 없음.

| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| 키 유지 | 로컬 데모에서 `PROFILE_ENC_KEYS`가 없으면 실행마다 새 키를 만들어, api를 재시작하면 DB에 남은 내 정보를 풀지 못하고 `/myinfo`가 503 | 한 번 만든 키를 키 파일에 두고 다시 읽는다. 자리는 `PROFILE_KEY_FILE`, 비우면 실행 사용자 홈 `~/.provena/local_demo_profile.key`(컨테이너는 `/home/app`, 저장소 밖). 로컬 데모가 아니면 키 파일을 읽지도 쓰지도 않는다 | [코드] `backend/services/profile_crypto.py:26, 62, 86, 130`, `backend/main.py:413`(고치지 않음). [실측] `test_local_demo_key_is_persisted_and_reused_after_restart`, `test_production_mode_never_reads_or_writes_a_key_file`, `test_main_app_local_demo_restart_keeps_key_and_production_writes_no_file` |
| 다시 입력 | 키가 바뀐 뒤 화면에는 "내 정보 저장소를 사용할 수 없습니다."만 보이고 칸이 비어 저장 버튼이 잠겨 있었다. 필수 칸을 채우면 버튼은 풀렸지만 그 안내가 없었고 AI 기억 칸은 잠겨 있었다 | 로컬 데모가 만든 키일 때만 서버가 404 `profile_reentry_required`와 안내문을 주고, 수정 화면이 빈 칸을 열어 다시 입력·저장하게 한다. `PUT`은 그대로다 | [코드] `backend/profile_api.py:192-196`, `web/react-app/src/pages/ProfileRequiredPage.jsx:96-107`. [실측] `test_local_demo_lost_key_asks_to_reenter_and_save_works`, `profile-reentry.test.jsx` 2개 |
| 운영 그대로 | 운영의 키 설정 오류가 '다시 입력'으로 바뀌면 되살릴 수 있는 정보를 덮어쓰게 된다 | `PROFILE_ENC_KEYS`로 받은 키는 `local_generated=False`라 503 그대로. 저장소 오류도 503 그대로 | [코드] `backend/services/profile_crypto.py:129`, `backend/profile_api.py:196, 199`. [실측] `test_configured_key_mismatch_stays_503_even_in_local_demo`, `test_local_demo_store_failure_is_still_503`, `test_configured_key_ignores_key_file_and_is_not_local_generated` |

**"운영에서도 같은가"에 대한 답(코드 기준, 운영 설정은 조회하지 않음)**
- 같지 않다. 운영은 무작위 키를 만드는 가지에 들어가지 않는다. 그 가지는 `is_local_demo()`(`PROVENA_ENV=local`이고 `PROVENA_DEV_MODE=1`, `backend/services/demo_seed.py:32-34`)일 때만 열린다(`backend/main.py:413`, `backend/services/profile_crypto.py:130`). [코드]
- `PROFILE_ENC_KEYS`가 있음: 그 키를 읽는다(`profile_crypto.py:127-129`). 값이 환경 변수라 재시작해도 같아 재시작만으로는 503이 되지 않는다. [코드]
- 없거나 형식이 틀림: `ProfileCryptoError`로 앱이 시작하지 않는다(`profile_crypto.py:132`, 형식 오류는 `parse_keys`). 503 화면이 아니라 새 리비전이 뜨지 못한다. [코드] `tests/test_profile_api.py:268` `test_main_app_refuses_start_without_key_outside_local`. 이때 Cloud Run이 이전 리비전을 계속 쓰는지는 확인하지 않았다. [추정]
- 키 교체: 새 번호를 더하고 옛 번호를 남기면 옛 줄은 줄의 `key_version` 키로 풀리고 새로 쓰는 줄은 가장 큰 번호로 잠근다(`profile_crypto.py:121, 140`, `test_old_key_version_still_decrypts_after_rotation`). 옛 번호를 빼거나 같은 번호의 값을 바꾸면 그 줄은 `GET /me/profile`이 503이다(`profile_crypto.py:142, 148`, `backend/profile_api.py:196`). 로컬 데모와 같은 증상은 운영에서 이 경우에만 난다. [코드]
- 그 상태에서도 `/me`의 `profile_completed`는 줄이 있는지만 봐서 true이고(`backend/main.py:405`), `PUT /me/profile`은 지금 키로 잠가 덮어쓴다(`backend/profile_api.py:177`). 이번에 바꾸지 않았다. [코드]
- 배포 서비스에 `PROFILE_ENC_KEYS`가 실제로 연결돼 있는지는 README가 미확인이라고 적고 있다(`README.md:218`). [문서]

**하지 않은 것(조장 판단 필요)**
- `docker-compose.yml`·`Dockerfile`·`.env.example`·`backend/main.py`·`README.md`는 고치지 않았다(TEAM_GUIDE 5장 주인·공용 파일 규칙). 그래서 컨테이너를 새로 만드는 경우(`docker compose down` 뒤 `up`, 이미지 다시 빌드)는 키 파일이 사라지고 '다시 입력' 안내로 넘어간다. 그 경우까지 키를 남기려면 `Dockerfile`에 `app` 소유 `/home/app/.provena` 폴더를 만들고 compose `api`에 이름 있는 볼륨을 그 자리에 붙이면 된다.
- 낡은 문장 3곳이 남는다: `.env.example:243`과 `backend/main.py:10-11`의 "실행마다 무작위 키(재시작하면 내 정보를 다시 입력)", `README.md` 환경 변수 표에 `PROFILE_KEY_FILE` 없음.
- compose를 실제로 띄워 재시작해 보지 않았다. `/home/app`에 `app`이 쓸 수 있다는 것은 `Dockerfile:19`(`--create-home --home-dir /home/app`)와 `:63`(`USER app`)에서 읽은 것이다. [코드]

**시험**
- `python -m pytest -q -p no:cacheprovider tests/test_profile_crypto.py tests/test_profile_api.py`: 84 통과(새 시험 11개 포함).
- 관련 9파일(`test_admin_api`, `test_decision_wiring`, `test_page_navigation`, `test_profile_store_pg`, `test_service_profile`, `test_deploy_hardening`, `test_startup_warmup`, `test_docs_switch`, `test_api_errors`): 146 통과, 5 건너뜀. 전체 pytest는 돌리지 않았다.
- `npx vitest run`(web/react-app): 444 통과(새 시험 2개 포함).
- 변이 8개(서버 6, 화면 2)를 하나씩 넣어 모두 새 시험이 실패했고, 끝난 뒤 원본으로 되돌렸다(변이 표시 0건, `git status` 확인). 환경은 로컬 Python 3.13 가상환경이다.
- `tests/test_profile_api.py::test_main_app_refuses_start_without_key_outside_local`은 이 시험만 따로 돌리면 실패한다(`backend.main`을 처음 불러올 때 모듈이 앱을 만들다 같은 오류가 먼저 난다). 이번 변경 전부터 그랬고 고치지 않았다. 파일 전체로 돌리면 통과한다.
