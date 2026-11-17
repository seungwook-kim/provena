# G2 키 없는 새 clone 핵심 시나리오 확인 (2026-11-17 10:15 KST)

체크포인트 게이트 G2의 남은 확인 항목("새 clone에서 키 없이 기동해 핵심 시나리오가 인용 답을 내는지")에 대한 증거이다. 저장소 README의 "실행 방법 (docker compose up)"과 "키 없이 뜨는 데모 모드" 절차를 그대로 따랐다. 로컬 실행이며 운영 서비스·유료 API 호출은 없고, 모든 요청의 LLM 호출 수는 0, 비용은 0달러이다(`api_container_log.txt`의 `calls=0 cost_usd=0.000000`).

## 대상

| 항목 | 값 |
|---|---|
| 저장소 | `aihuman-7th/proj3-c` main |
| clone 커밋 | `e53713d8d9bbade3d383857d3a4992dfd1d9094d` (2026-11-17 09:25 KST, PR #179 머지) |
| `.env` | 없음. compose가 `.env.example`만 읽는다(`LLM_API_KEY`, `VOYAGE_API_KEY` 등 키 칸은 모두 빈 값) |
| 실행 모드 | `DEMO_MODE=1`(기본), `PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`(compose 기본값) |
| 실행 셸 환경 | 시작 전 키·비밀번호 이름이 든 환경 변수를 모두 지움(`compose_log.txt` 첫 줄, 남은 변수 0개) |

## 절차

1. 빈 폴더에 `git clone`을 실행했다. 첫 시도는 Windows 경로 길이 제한으로 체크아웃이 실패했다(`Filename too long`). README의 Windows 안내(`core.longpaths true`)대로 `git -c core.longpaths=true clone`으로 다시 받아 성공했다(`timing.txt` 첫 줄).
2. clone 폴더에서 `docker compose up -d`를 실행하고 `http://localhost:8000/health`가 200을 줄 때까지 0.5초 간격으로 확인했다.
3. README 2단계대로 로컬 데모 계정 `demo-user`로 로그인했다(`GET /auth/csrf` 뒤 `POST /auth/login`, 비밀번호는 README가 안내하는 `.env.example` 값을 스크립트가 파일에서 읽음, 화면·로그에 출력하지 않음).
4. README "키 없이 뜨는 데모 모드"에 적힌 질문 9개(인용 답 7개, 거절 2개)를 글자 그대로 `POST /chat`(SSE)으로 보내 `citation`·`done` 이벤트를 기록했다(`ask_demo.py`, 결과 `answers.jsonl`).
5. 브라우저로 `http://localhost:8000/`을 열어 첫 화면을 한 장 찍었다(`web_home.jpg`, 로그인하지 않은 상태, 비밀번호 입력 없음).
6. `docker compose down -v`로 컨테이너·볼륨·네트워크를 지웠다(`compose_log.txt` 끝).

## 기동 시간

| 구간 | 값 | 근거 |
|---|---|---|
| clone(두 번째 시도) | 55초 | `timing.txt` |
| `docker compose up -d` 시작 → 명령 반환 | 57.4초 | `timing.txt` |
| `docker compose up -d` 시작 → `/health` 200 | **63.4초** | `timing.txt` |
| `/` 응답 | 200 | `timing.txt` |
| 색인 적재(loader) | 청크 23,095개, 4.8초 | 기동 중 loader 컨테이너 로그로 확인(파일로 남기지 않음) |

빌드 레이어 캐시가 있는 상태였다(의존성 설치 레이어 `CACHED`, `compose_log.txt`). 빌드 캐시가 없는 PC에서는 이보다 오래 걸린다.

## 질문별 결과

인용 칸의 출처는 모두 GitLab 핸드북 주소(`handbook.gitlab.com` 또는 `gitlab.com`의 핸드북 원본 파일)이고, 모든 인용에 판 날짜(`version_date`)가 있다. 인용 답 7개는 모두 `done` 이벤트에 출처 표시(GitLab Handbook, CC BY-SA 4.0)가 붙었고, 답 본문 끝에 "근거 판 날짜"와 "출처: GitLab Handbook"이 들어 있다. 시간은 요청 전송부터 SSE `done` 수신까지 클라이언트에서 잰 값이다.

| # | 질문 | README 기대 | HTTP | 결과 | 인용 수 | 판 날짜 | 인용 섹션 | 비용(달러) | 초 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요? | 인용 답 | 200 | answer | 1 | 2026-09-13 | Security Third Party Risk Management > What Triggers a TPRM Assessment? | 0.0 | 0.47 |
| 2 | CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해? | 인용 답 | 200 | answer | 1 | 2026-04-09 | Vulnerability Resolution SLAs > Vulnerability Management SLAs and Labels | 0.0 | 0.40 |
| 3 | 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해? | 인용 답 | 200 | answer | 1 | 2023-05-11 | Authorization Matrix (2023-05) > Authorization Matrix | 0.0 | 0.38 |
| 4 | EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면? | 인용 답 | 200 | answer | 3 | 2026-08-18 | Incident Management > Incident Manager Escalation 외 1개 섹션 | 0.0 | 0.43 |
| 5 | 외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요? | 인용 답 | 200 | answer | 2 | 2023-05-11 | Authorization Matrix (2023-05) > Approving expense > >$25K up to $50K 외 1개 | 0.0 | 0.66 |
| 6 | 외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요? | 인용 답 | 200 | answer | 2 | 2023-05-11 | Authorization Matrix (2023-05) > Approving expense > >$25K up to $50K 외 1개 | 0.0 | 0.64 |
| 7 | 외부 SaaS 구매 비용이 10만 달러라면 업무 승인자와 재무 승인자는 누구인가요? | 인용 답 | 200 | answer | 4 | 2023-05-11 | Authorization Matrix (2023-05) > Approving expense > >$50K up to $250K 외 3개 | 0.0 | 0.66 |
| 8 | 구매 승인에는 어떤 승인자가 필요한가요? | 거절 | 200 | refuse(`no_evidence`) | 0 | - | - | 0.0 | 0.53 |
| 9 | 오늘 점심 메뉴 추천해줘 | 거절 | 200 | refuse(`out_of_domain`) | 0 | - | - | 0.0 | 0.04 |

인용 청크 id, 섹션 전체 목록, 원문 주소, 답 본문은 `answers.jsonl`에 있다. 5·6번은 README 설명대로 `>$25K up to $50K` 행을 인용해 업무 승인자 Director, 재무 승인자 PAO 또는 VP Finance를 답했고, 7번은 `>$50K up to $250K` 행을 인용해 답하며 계약 체결 전 법무 검토가 필요하다는 점을 덧붙였다.

## 결론

- 커밋 `e53713d8`을 새로 clone해 `.env`와 키 없이 `docker compose up -d`로 기동했고, `/health` 200까지 63.4초가 걸렸다(빌드 레이어 캐시 있음).
- README의 인용 답 질문 **7개 중 7개**가 HTTP 200으로 인용 답을 냈고, 모든 인용에 핸드북 출처 주소와 판 날짜가 있었다. 거절 질문 2개는 README 설명대로 거절했다. 9개 모두 README 설명과 같다.
- 모든 요청의 LLM 호출 수와 비용은 0이다. 키 없는 데모는 `data/demo_replay/`의 녹화 응답을 재생하므로 README에 적힌 질문에 한해 인용 답이 나온다(README 설명과 같음). 서버 로그에는 데모 재생 모듈이 "추론 답 녹화가 없어 빠른 답을 씁니다"라는 안내를 한 번 남겼다(`api_container_log.txt`).
- Windows에서 깊은 폴더에 clone하면 `core.longpaths` 설정 없이는 체크아웃이 실패한다는 점을 다시 확인했다. README에 이미 안내가 있다.

## 파일

| 파일 | 내용 |
|---|---|
| `timing.txt` | clone·compose·`/health` 시각과 구간 시간, `.env` 유무 |
| `compose_log.txt` | 환경 변수 정리 결과, `docker compose up -d` 빌드·기동 출력, `docker compose ps`, `docker compose down -v` 출력 |
| `api_log.txt` | `/health`, `/auth/csrf`, `/auth/login` 응답 코드 |
| `api_container_log.txt` | api 컨테이너 로그(요청별 상태 코드, LLM 호출 수·비용) |
| `answers.jsonl` | 질문별 HTTP 상태, 결과 종류, 인용 목록(섹션·판 날짜·원문 주소), 출처 표시, 비용, 시간, 답 본문 |
| `ask_demo.py` | 4단계에 쓴 스크립트(표준 라이브러리만 사용) |
| `web_home.jpg` | 로그인 전 첫 화면 캡처 |
