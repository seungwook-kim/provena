# PR #(번호 미정) — 놓친 것 목록(11/11 점검 50개) 남은 35개: 보안·API, 화면 마감, 수집·문서, 기록 표기
- 작업자: 박진형 (jinyeong-731) / 머지: 아직 안 함 / 기준: `origin/main` `a611610`, 통합 브랜치 `integ-1111` HEAD `6c24c0a` / 파일 이름 `PR-next.md`는 번호가 나오면 `PR-<번호>.md`로 바꿈

## 배포 상태 (맨 위 확인)
| 대상 | 상태 | 근거 |
|---|---|---|
| #127·#129 | 배포됨 | 진형 직접 확인: 구글 로그인 → 비밀번호 입력 → 인증 → 관리자 승인 → 로그인 됨(11/11, 화면 캡처 없음) |
| #130 | **배포 안 됨** | 배포 번들(`index-DvEEAMqg.js`)에 #130 코드(`approval_pending`, `findLastIndex`)가 없음. 배포 실측(11/11 19:32) |
| 이 PR | 배포 안 됨 | 아직 머지 전 |

- 판정: 배포는 #129 수준. 이 문서의 모든 시험·측정 값은 로컬 시험이고, 배포에서 안 본 것은 "배포 미확인"으로 적었다.
- 배포 수정 전 값(배포 실측 11/11 19:32, `https://provena-api-cttaanqntq-du.a.run.app`): HEAD `/health` 처음 000(응답 없음), 다시 두 번 재면 404 / HEAD `/threads` 404 / `/favicon.ico` 404 / `/zz-no-such-page` 404(전부 JSON) / `/recalls/zz` 401 / `/threads/%00` 401 / `/me` 401. 이 값이 아래 H-27·C-24·C-16 "머지 뒤 확인" 행의 비교 기준이다.

## 닫는 항목
| 구분 | 번호 | 수 |
|---|---|---|
| 이 PR이 닫는 것 | H-10·H-11·H-12·H-13·H-16·H-18·H-19·H-20·H-21·H-22·H-23·H-26·H-27·H-29·H-30·H-31·H-32·H-33 (18) / J-11·J-12·J-13·J-14 (4) / C-16~C-25 (10) / O-47·L-22 (2) | 34 |
| 기록만 | L-24 (점검이 못 본 경로 11개를 README에 "미확인"으로 적음, 실행 확인 아님) | 1 |
| **합계** | 50개 중 35개 | 35 |
| 이미 main(#127·#130) | H-08·H-09·H-14·H-15·H-17·H-24·H-25·H-28·J-15·K-17·K-18·K-21·L-23 | 13 |
| 따로 처리 | K-19(별도 PR), K-20(조장 PR #126에 같은 기능) | 2 |

- 같은 PR에 든 목록 밖 항목: R-07·F-11·A-07·K-03·F-08·F-17(수집·검색 담당 항목 기록 포함).

## 1. 기록 정리 (records-1111)
### 무엇을 바꿨나
| 번호 | 고친 것 | 파일 | 시험 |
|---|---|---|---|
| - | #127·#129·#130 `ai_tools_log` 행과 폴더 md PR 칸 채움, 작성자 칸 35곳에서 도구 표기 제거 | `docs/deliverables/ai_tools_log.md`, 폴더별 md, `docs/pr-notes/PR-127·129·130.md` | - |
### 왜 (근거)
- 팀 지침서가 정한 기록 위치(10장)를 맞추고, 작성자 칸은 git id로 통일. 근거: 커밋 `f5147c4`·`5751d24`·`035c877`·`7566db5` 메시지.
### 확인한 것
- 문서 변경이라 시험 없음. `ai_tools_log`는 PR 하나당 표 한 줄만 남김(같은 내용 문단 3개 삭제, `035c877`).
### 한계
- 도구 표기는 `ai_tools_log`에만 남음(작성자 칸 35곳은 git id).

## 2. 보안·API (J-11~J-14, C-16~C-25)
### 무엇을 바꿨나
| 번호 | 고친 것 | 파일 | 시험 |
|---|---|---|---|
| J-11 | 되묻기가 주소(스킴·www·도메인·IPv4)·SQL 꼴 구·긴 영문 문장을 되풀이하지 않음. 판정은 TLD 목록 대신 주소 꼴로 | `backend/graph/` answer_fixes | `test_answer_fixes` |
| J-12 | 웹훅 주소를 DNS로 풀어 비공인 IP 차단(등록·전송 둘 다, 리다이렉트 안 따라감). 전송은 검사한 IP로 직접 연결, Host·SNI는 원래 이름(IDN은 punycode, SNI 끝 점 제거) | `backend/graph/recall/webhook.py` | `test_recall_webhook`(재시도·하루 요약 포함) |
| J-13 | 웹훅 본문에서 user_id·질문·답 발췌 등 개인 칸 5개 제거 | 같은 파일 | `test_recall_webhook` |
| J-14 | CSRF를 서명된 double-submit으로(난수 + HMAC-SHA256, `AUTH_SECRET` 파생 키) | `backend/auth.py` 등, `docs/specs/login.md` | `test_auth_router_runtime`, 시험 지원 코드 6파일 |
| C-16·C-17 | NUL 문자가 든 경로를 미들웨어에서 404 오류 봉투로 | `backend/main.py` 쪽 미들웨어 | `test_api_path_guards` |
| C-18 | 승인·대화 목록에서 깨진 행은 건너뛰고 로그만 | `backend/graph/decision/repo` | 관련 시험 |
| C-19 | 내 정보 422가 빈 message 대신 오류 봉투(칸별 이유 `details.fields`) | `backend/api/errors.py` | `test_profile_api` |
| C-20 | 422 명세를 실제 봉투에 맞춤(details는 배열 또는 객체), openapi 재생성 | `docs/api/openapi.json` | `test_profile_api` |
| C-21 | 인증번호 재발송 본문에서 code 제거 | `backend/auth.py` | `test_email_signup_hardening` |
| C-22 | 리콜 피드백 `useful`은 진짜 불리언만 받음 | `backend/api/recalls.py` | `test_api_recalls` |
| C-23 | 결정표를 업무 종류로 실행할 때 권한표에 없는 업무 종류는 404 `not_found` | `backend/graph/decision/routes.py`(+13줄) | `test_decision_routes`(+12줄) |
| C-24·C-25 | 코드 수정 없음. HEAD `/threads` 404 원인을 "GET 전용 경로 + 정적 마운트"로 정정해 기록, 동작은 시험으로 고정 | `backend/backend.md` | `test_api_path_guards` |
### 왜 (근거)
- J-12: 이름을 검사한 뒤 다시 풀면 바뀐 IP로 나갈 수 있어(DNS 재바인딩) 검사한 IP로 직접 연결한다. 근거: 커밋 `0df6576`·`a1ed50b` 메시지.
- J-14: 쿠키와 헤더가 같기만 하면 통과하던 것을 서명 검사로 바꿈. 근거: 커밋 `cf1e4b9`. 서명 검사를 빼는 변이에서 새 시험 ①③이 실패.
- C-16: 라우터에 닿으면 500이 나는 앱으로 단위 시험을 만들어 거름 줄이 실제로 막는지 증명. 근거: 커밋 `d58e82e`.
- C-24: 처음 기록한 원인이 틀려 정정(코드 동작 그대로). 근거: 커밋 `4ae10e5`.
### 확인한 것
- J-14: 로컬 pytest 649 통과(해당 묶음), 서명 검사를 빼는 변이에서 새 시험 ①③ 실패.
- J-11·J-12·C-16: 고친 줄을 되돌리면 시험 실패(PR③ 초안 기록, 로컬 시험).
### 한계·남은 것
- J-12: 서버에 `HTTPS_PROXY`가 있으면 인증서 이름이 안 맞아 웹훅이 안 나감(막히는 쪽 실패, 운영 프록시 사용 여부 미확인). 공인 IP가 여럿이면 첫 IP만 씀.
- 바뀌는 기본 동작: NUL 경로 항상 404 / 웹훅 개인 칸 제거 / 배포에서 웹훅 주소가 안 풀리면 등록 400 / 되묻기에서 `config.yml`·`Node.js` 같은 이름도 걸려 일반 안내로 되물음.
- 웹훅 NAT64 주소(`64:ff9b::/96`)는 아직 막지 않는다.
- 웹훅 주소에 IDN(ß 등)이 있으면 검사할 때와 연결할 때의 이름이 달라 TLS가 실패할 수 있다(SSRF는 아님).
- C-23 권한표 파일에 깨진 줄이 있으면 500이 난다.
- CSRF 서명 키 우선순위가 발급(라우터 secret)과 검사(AUTH_SECRET 우선)에서 다르다. 운영은 `main.py`가 둘을 같게 맞춰 영향 없음.
- CSRF 토큰이 세션에 묶여 있지 않다(참고).
- 전부 로컬 시험, 배포 미확인.

## 3. 수집·검색·문서 스위치 (R-07·F-11·A-07, 기록 K-03·F-08·F-17)
### 무엇을 바꿨나
| 번호 | 고친 것 | 파일 | 시험 |
|---|---|---|---|
| R-07 | 부르는 곳 없는 템플릿 `ingest()` 삭제 | `backend/rag/ingest/` | `test_ingest_handbook` |
| F-11 | `--follow-renames` 옵션 추가(기본 꺼짐, 운영은 여전히 `--no-renames`), 폴더 밖에서 옮겨 온 파일(I-006)의 이름 바뀜 잇기, `old_path` 쓰는 곳 연결. 켠 전체 실행 1회 실측을 한계 문구에 기록 | `backend/rag/ingest/ingest.md`, `docs/specs/collect.md` | `test_ingest_handbook` |
| A-07 | `PROVENA_DOCS_PUBLIC=0`이면 `/docs`·`/redoc`·`/openapi.json` 끔. 기본 공개(지금 동작). `.env.example` 변경은 팀장 전용이라 빼고 요청으로 기록 | `backend/main.py`(+4/−1) | `test_docs_switch` |
| K-03·F-08·F-17 | 코드 없음. 결정 기록: K-03 의존성 버전 차이는 "어긋남 기록"으로, F-08 정시 실행 실패 원인은 추정으로 표기하고 Actions 결제 한도 결정 한 줄, F-17 재임베딩 단위(쪽 단위, 해시 단위 아님) | `docs/specs/incremental.md`, `docs/docs.md` | - |
### 왜 (근거)
- F-11: 개정 이력의 이름 바뀜을 따라가는 옵션. 커밋 `d04ec6d`·`e7f93c0`·`de3dfc3`.
- A-07: 쓰기·관리 API가 전부 인증·CSRF 뒤이고 정적 `openapi.json`이 이미 공개라 기본은 공개 유지. 근거: 커밋 `97564ac`, 진형 결정(11/11).
### 확인한 것(로컬)
- F-11 켠 전체 실행: 로컬 수집기로 1회, 이름 바뀜 1,163건, `prev_sha` 연결 1,090/1,163 = 93.7%, 커밋 6,878개, 25분 11초(로컬, 배포 미확인).
### 한계·남은 것
- F-11 기본은 꺼짐 유지. 판 날짜 표시 연결은 아직(아래 결정 ②).
- F-08: 정시 실행은 여전히 disabled, 성공 기록 없음(원인은 추정).
- K-03: `docs/PRD.md` 314·317줄을 코드에 맞게 고쳐 달라고 요청(조장 문서).

## 4. 화면 마감 (H-10~H-13·H-16·H-18~H-23·H-26·H-27·H-29~H-31·H-33)
### 무엇을 바꿨나
| 번호 | 고친 것 | 파일 | 시험 |
|---|---|---|---|
| H-10 | 영향 미리보기 입력을 서버 계약에 맞춤, 숫자가 아닌 `rule_seq`는 보내기 전에 막고 안내 | `web/react-app/src/` recall 화면 | recall 화면 시험 |
| H-11 | 하루 요약이 늘 비던 것(응답 칸 `digests`), 남의 알림에는 확인 버튼 대신 안내 | 같은 곳 | recall 화면 시험 |
| H-12·H-13·H-30 | 계정 메뉴에 내 정보·기억 설정(`/onboarding`) 링크, UUID 대신 로그인 아이디(`/me`에 `login_id`), AI 기억에 담당 서비스(`service`) 칸 | `backend/auth.py`, `web/` 계정 메뉴, `docs/specs/login·admin-roles`, `openapi.json` | `test_auth_store`·`test_auth_user_isolation`·`test_google_oauth`(기대값), session·api 시험 |
| H-13 후속 | 분류·재작성 프롬프트에는 측정 때와 같은 기억 칸(affiliation·rank)만 넣고 `service`는 저장만 | `backend/prompts/question.py` | `test_question_graph`(+11줄) |
| H-12 후속 | 내 정보 화면이 한글 소속 팀을 AI 기억 `affiliation`으로 보내지 않게 함(검색 범위가 없는 절로 좁혀져 0건 되는 것 방지) | `web/` | session 시험 |
| H-16·H-22·H-31 | 관리자 회원 화면: 미완성 탭(개인정보 열람 승인) 숨김, 가입 신청은 승인 대기 우선·기본 대기만(전체 보기 선택), 승인·반려 팝업 구분, 검토 결과 한글, 탭 이동 때 성공 문구 지움 | `web/` admin 화면 | admin-users 시험 |
| H-21 | 인증 재설정 버튼(최고 관리자만), 리콜 화면에 하루 요약·처리 대기 수동 실행(확인창), 웹훅 구독 목록·추가 | `RecallPage.jsx`, `recall-service.js`, `api.js` | `recall-routes.test.jsx`(+76줄) |
| H-23 | 계정 메뉴가 소속 팀을 가린 보기(`GET /me/profile`)로 읽음, 근거 패널의 중복 '최종 수정일' 삭제 | `web/` | DemoChatPage·session 시험 |
| H-18·H-19 | CSRF 토큰 요청 합치기·재시도, 만료 세션 로그아웃 때 로컬 세션 정리 | `web/react-app/src/lib/` | api·session 시험 |
| H-20 | 로컬 프록시 `/admin`·`/approvals` 새로고침 통과 | `web/` 프록시 설정 | 관련 시험 |
| H-26 | 640px 이하에서 대화 검색칸·대화 목록·근거 패널 열기 | `web/` styles·DemoChatPage | DemoChatPage 시험 |
| H-27 | 없는 주소는 404 화면, HEAD `/health` 200, API 404 문구 한국어 통일, 서버 연결 실패를 한국어 안내로 | `backend/main.py`, `web/` | `test_deploy_surface` |
| H-29 | 세션 만료 안내, 쓰던 질문 임시 저장(계정별 키, 계정이 바뀌거나 로그아웃하면 지움), 로그인 잠금 남은 시간 | `web/` 로그인·채팅 | session 시험 |
| H-33 | 좁은 화면 상단 메뉴 줄바꿈·권한 표 버튼 보이기. 로그인 전 `/me` 401 콘솔 문구는 브라우저가 찍는 것이라 코드로 못 끔 | `web/` styles | - |
| H-32 | ① 답 본문 인용 번호를 나온 순서로 다시 매김(화면) ② 같은 제목 대화는 버그가 아님, 지난 날짜에도 시각 표시 ③ 데모 3초 고정 지연은 코드에 없음, 지연 없음을 지키는 시험 추가 | `chat-service.js`(+22), `DemoChatPage.jsx`, `docs/specs/d6-chat-frontend.md` | `DemoChatPage.test.jsx`(+39), `test_demo_replay`(+15) |
| - | 흔들리는 웹 시험 3개의 기다림 보강 | `DemoChatPage.test.jsx`, `recall-routes.test.jsx` | 단독 20회 통과, 전체 3회 실패 0 |
### 왜 (근거)
- H-11: 응답 칸 이름이 서버(`digests`)와 달라 늘 비었다. 근거: 커밋 `4795173` 메시지.
- H-12(소속): 검색은 조직 코드 정확 일치(`backend/rag/retrieve/search.py:255`)라 한글 팀 이름으로는 범위가 빈다. 근거: 커밋 `d54231b` 메시지.
- H-13 후속: 측정 때 프롬프트와 다른 칸이 들어가면 측정값이 서비스에 안 맞는다. 근거: 커밋 `d47f68d`.
- H-32 ②: 같은 제목은 대화가 따로 생긴 정상 동작이라 고치지 않고 시각으로 구분. ③: 데모 재생 코드에 고정 지연이 없고 `STAGGER_S`를 바꾸는 변이에서 새 시험이 실패. 근거: 커밋 `bd44035`. 3초의 출처는 못 찾음.
- 흔들림: recall 시험이 고치기 전 20회 중 2회 실패해 재현됨. 근거: 커밋 `20a8986`(PR④ 리뷰 6번).
### 확인한 것(로컬 시험)
- 통합 6c24c0a: vitest 23파일 300 통과, `npm run build` 성공.
- 흔들리는 시험: 고친 뒤 단독 20회 통과, 전체 3회 실패 0.
- 고친 줄을 되돌리면 시험 실패(PR④ 초안 기록: H-29 최대 4개, H-22 1개).
### 한계·남은 것
- H-21 일부: 웹훅 삭제는 서버에 경로가 없고, 결정표 변환(`/decision-tables/convert`)은 LLM 호출과 새 결정표 화면이 필요해 연결하지 않음.
- H-13: 계정 메뉴에 email 칸 없음(로그인 아이디가 이메일이라 같은 값이 보임).
- H-32 ③: 3초 고정 지연의 출처 미상.
- H-27·H-33·H-26 등은 로컬 시험이고 배포 주소 확인 전.

## 5. 문서·기록 보강 (O-47·L-22·L-24, gap-docs)
### 무엇을 바꿨나
| 번호 | 고친 것 | 파일 |
|---|---|---|
| O-47 | GATES G7 칸을 `EVAL_REPORT` 10장 대체재 비교표가 있다는 사실로 정정, '없는 것'에서 뺌 | `docs/GATES.md`, `docs/docs.md` |
| L-22 | 11/10 로컬 실제 모델 인젝션 시험 행, 명세 의존 파일·환경변수 절, 측정 옆 설명 문서 | `docs/` (커밋 `160e33c`·`349d2bf`·`0eb7567`) |
| L-24 | 점검이 못 본 경로 11개를 README 키 없는 데모 절에 "미확인"으로 기록(실행 확인 아님) | `README.md` |
| - | 문서 현행화: 강사 코멘트·가이드·PRD/SDD 대조(`d99ddc0`), PR #113 DB 변경을 DB 문서 3개에, 검색 Spec #67 스위치, ingest.md·SDD에 compare 반영, 시험 파일 경로 정정, 5장 실패 유형 다시 세기, 포트폴리오 1장 초안 | `docs/` |
### 확인한 것
- 통합할 때 gap-docs 줄 번호 인용 표본 10개 중 5개가 틀려, 통합 코드 기준으로 15파일의 줄 번호를 다시 맞춤(`1eba0dc`).
- 틀린 숫자·인용 7건을 검증에서 찾아 고침(`0eb7567`).
- 로컬 시험·측정 값을 배포처럼 쓴 17곳에 "로컬/배포 미확인"을 붙임(`b2fbb9a`, `6c24c0a`).
### 한계·남은 것
- TEAM_GUIDE 5·6장 수정은 `d99ddc0`(문서 현행화, 문서 갈래)에서 왔다. 조장님 놓친 것 목록 몇 번 지시인지 커밋 메시지·로그에서 못 찾음 — 조장 확인 필요.
- `docs/specs/admin-roles.md`의 오래된 줄 번호는 전수 검증하지 않음(표본만).
- L-24는 기록만이고 그 11개 경로는 아직 실행 확인 전.

## 시험 결과 (통합 6c24c0a, 로컬 시험)
| 시험 | 결과 |
|---|---|
| vitest | 23파일 300 통과(6c24c0a 기준), 마무리 뒤 전체 재실행 23파일 301 통과 |
| build | 성공 |
| pytest | 3422 통과 / 10 실패 / 21 건너뜀 / 8 error. 실패 판정: 우리가 낸 2건(test_profile_api, `06bf3aa`에서 고쳐 54 통과) / 로컬 DB 환경 15건(db/120 적용한 새 DB에서 63 통과) / 기존 1건(main에서도 실패) |
| 추가 시험(마무리) | pytest `tests/test_approval_latency.py` 5 통과(새 `test_http_bench_passes_signed_csrf` 포함, 고치기 전 코드에서는 실패 확인), vitest `DemoChatPage.test.jsx` 13 통과(전체 301)(새 시험 1개, 고친 줄을 되돌리면 실패 확인) |

- `test_db_init_roles_integration.py:120`은 main에서도 실패하는 기존 문제다(108이 users SELECT를 회수했기 때문으로 추정). 시험 주인 확인 필요.
- 로컬 시험 DB에 `db/120`이 없으면 `test_recall_pg`가 실패한다(9dbd784 이후 `TEST_DATABASE_URL`로도 돌기 때문). CI는 시험 DB가 없어 건너뜀(`ci.yml`).

## 남의 폴더를 고친 곳
| 폴더 | 주인 | 고친 내용 |
|---|---|---|
| `docs/`(GATES·PRD 요청·specs·deliverables 등), `README.md` | 조장 | 기록·현행화(O-47·L-22·L-24, gap-docs 줄 번호), `docs/specs/login·admin-roles·decision-approval` |
| `web/` | 경희님 | H-10~H-33 화면 마감, 시험 |
| `backend/graph/`(answer_fixes·recall/webhook·decision/routes·repo·service·build 쪽) | 조장 | J-11·J-12·J-13·C-18·C-23 |
| `backend/services/`, `backend/main.py`(A-07 +4/−1, C-16·H-27) | 조장 | 보안·스위치·404 |
| `backend/prompts/question.py` | 조장 | H-13 후속 |
| `evals/agent/approval_latency.py`, `tests/test_approval_latency.py` | 김승욱님 | J-14로 깨진 승인 지연 HTTP 측정 줄을 서명된 CSRF 토큰으로 고침(조장 지시 11/11 목록 작업 중), `evals/agent/agent.md`에 한 줄 |
| `db/` | 조장 | 이 PR에서 변경 없음(113·114는 #127) |
| 팀장 전용 `.env.example`·`docker-compose.yml` | 팀장 | 건드리지 않음(A-07 설명 줄은 요청으로 기록) |

## 머지·재배포 뒤 배포 주소에서 확인할 항목
| 항목 | 확인할 내용 | LLM 호출 |
|---|---|---|
| 배포 번들 | 재배포 뒤 번들에 `approval_pending`·`findLastIndex`(#130)가 생겼는지 | 없음 |
| H-27·H-33·C-24 | HEAD `/health` 200(지금 404), 없는 화면 주소는 404 화면, API 404 한국어 JSON, `/favicon.ico`, HEAD `/threads` | 없음 |
| C-16·C-17 | `/threads/%00`이 404 봉투인지(지금 401, Cloud Run 앞단 포함) | 없음 |
| J-12·J-13 | 웹훅 구독 등록: 내부 IP 400, 공인 주소 허용. 실제 전송·`HTTPS_PROXY` | 전송은 있음 |
| J-14 | 로그인 뒤 변경 요청이 서명된 CSRF로 통과, 서명 없는 값은 거절 | 없음 |
| H-29 | 로그인 429 Retry-After, 세션 만료 안내·쓰던 질문 보존(별도 계정) | 없음 |
| H-21 | 리콜 화면 digest flush, process-pending, 웹훅 구독 목록·추가 | process-pending 있음 |
| H-12·H-13·H-23·H-30 | 계정 메뉴 login_id·소속, 내 정보 저장 | 없음 |
| H-16·H-22·H-31·H-26 | 관리자 회원 화면 탭·필터·팝업, 640px 이하 | 없음 |
| H-32 | 답 본문 인용 번호가 나온 순서, 같은 제목 대화 시각 표시 | 있음(답 생성) |
| C-22·H-10 | feedback `useful`에 문자열 422, 영향 미리보기 `rule_seq` | 확인 필요 |
| C-23 | 권한표에 없는 업무 종류로 결정표 실행 시 404 | 없음 |

## 정해 달라는 결정
- ① `/onboarding`이 소속에 보내는 한글 팀 이름을 조직 코드로 바꾸는 매핑 표를 둘지(경희님·조장님).
- ② README·SPEC "판 날짜 표시"는 main의 "미측정"을 유지하고 로컬 1.000은 넣지 않음(로컬 값, 배포 미확인).
