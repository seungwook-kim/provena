# #138 후속 — 기록 칸 채우기, 작업 내역 이름 정리, D0~D8 정리, 포트폴리오 보강, 동결 전 로컬 확인
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `3225f107`(#140까지) 위 브랜치 `pr138-followup`
- 근거 종류 표기: [코드] `파일:줄` / [문서] 팀 문서 / [실측] 직접 돌린 결과 / [추정].
- 운영 호출 없음(조장 11/13 배포·운영 측정 중 운영 시험 중지 요청). LLM·Voyage 호출 없음. 모든 확인은 로컬 Docker.

## 1. 한 것
| 항목 | 무엇 | 근거 |
|---|---|---|
| 기록 칸 `미정` | 박진형 행 38칸을 실제로 머지된 PR 번호로 채움(#132 26칸, #138 12칸). 남의 행은 건드리지 않음 | [실측] 행마다 `git blame`으로 그 줄을 넣은 커밋을 찾고, 그 커밋을 처음 담은 main의 머지 커밋(첫 부모 줄)에서 PR 번호를 읽음. 바뀐 낱말은 `미정` → `#번호` 38개뿐(`git diff --word-diff`) |
| 작업 내역 이름 | `docs/pr-notes/PR-next.md` → `PR-138.md`. 머리말(PR 번호·머지 시각), 빠져 있던 프론트 버그 수정·화면 안내 절(2-0), 5절 숫자(vitest 369, pytest 3550)를 채움. 이 이름을 가리키던 `docs/docs.md`·`ai_tools_log.md` 두 곳도 고침 | 지침 "PR마다 `PR-<번호>.md`", 미정은 머지 직후 후속 커밋으로(팀원 기록 규칙). 프론트 숫자 출처는 그 작업의 검증 기록(11/12) |
| D0~D8 정리 | `docs/deliverables/work-summary-박진형.md` 새 파일. 11/11 main `54f8e37`(#125 직후) 기준 그대로이고 그 뒤 PR은 넣지 않음(진형 결정 11/13). 결과 파일 이름 2개만 AI 도구 이름이 들어 있어 "결과 JSON 2개"로 바꿈 | 11/11 조장 지적(진형 작업 문서 없음) 뒤 만든 문서가 PR에 실리지 않았다 [실측: 모든 브랜치 이력에서 이 파일 0건] |
| M-22 포트폴리오 | `portfolio-박진형.md` 숫자 표에 LangGraph 승인·재개 줄, 멀티에이전트 줄(정책 질문 단일 대 멀티, 합동 검토 팀 대 1인)을 "팀 결과"로 더함. "차이 없음"도 그대로 적음 | 체크포인트 D12 "포트폴리오 1장(LangGraph, 멀티에이전트, 평가, 관측의 수치 포함)". 전에는 `LangGraph`·`멀티` 0건이었다. 숫자 출처 `EVAL_REPORT.md:503`, `:514-515`, `:592` |

## 2. 진형이 결정한 것
| 결정 | 고른 것 | 왜 | 버린 대안 |
|---|---|---|---|
| #138 후속을 누가 | 이 PR 하나에서 놓친 것 쪽과 프론트 쪽 행을 다 채움 | 같은 파일(`docs/docs.md`, `ai_tools_log.md`, `web/web.md`)을 두 작업이 나눠 고치면 다시 충돌한다 | 작업마다 따로 후속 PR |
| D0~D8 정리 | 11/11 기준 그대로 올림 | D0~D8 기간 정리라서 그 뒤 일을 섞지 않음. 그 뒤 일은 PR마다 작업 내역(`PR-*.md`)에 있다 | 11/12까지로 다시 씀 |
| 포트폴리오 멀티에이전트 줄 | 팀 결과로 표시하고 "차이 없음"을 그대로 적음 | 그래프·Supervisor는 김승욱 몫이다. 가이드는 부풀리지 말고 전후를 함께 쓰라고 함 | 넣지 않음(체크포인트 요구 미충족), 좋은 숫자만 적음 |

## 3. 동결 전 로컬 확인 (놓친 것 Q-24·K-19·K-22·L-27·L-28)
| 항목 | 결과 |
|---|---|
| Q-24 새 clone 키 없는 기동 | GitHub에서 새로 받은 main `3225f10`에서 `.env` 없이 `docker compose up --build -d` → 66초 뒤 끝, 80초에 `/health` 200, loader 청크 23,095개 적재(10.4초), 데모 계정 로그인 200 [실측, 11/13 00:43~00:45]. Docker에 이미지 층 캐시가 일부 있어 처음 받은 컴퓨터의 첫 빌드 시간은 아니다 |
| Q-24 덤으로 찾은 것 | Windows에서 README의 `git clone`(README:123)을 그대로 하면 `data/pdf/...` 경로가 길어 체크아웃이 실패한다(`Filename too long`). `git -c core.longpaths=true clone`으로는 된다 [실측]. README는 조장 파일이라 고치지 않고 알림 |
| K-19 README 1번 질문 | 키 없이 "제3자가 프로덕션 데이터에 접근하거나…" 질문 → 토큰 40개와 인용 1건(Security Third Party Risk Management) 뒤 `done` [실측] |
| K-22 main 기준 pytest | 3586 passed, 0 failed, 172 skipped, 2 deselected, 642.5초 [실측, 11/13 00:46~00:59, Docker `python:3.12`, 새 clone main `3225f10`, CI와 같은 `pip install -r backend/requirements-dev.txt` → `python -m pytest -q`]. 이 PR은 `.py`를 바꾸지 않았다. `README.md:224`·`docs/GATES.md:10`의 11/10 값(3054 passed … 41 errors)은 조장 파일이라 숫자만 알림 |
| L-27 평가셋 해시 줄바꿈 | v1·v2는 `.gitattributes`가 CRLF로 고정. 검증 20건(`dataset_holdout_v1.jsonl`)과 새 인용 5건(`dataset_cite_new_v1.jsonl`)은 고정이 없다(`git ls-files --eol`: `attr/` 빈칸). 저장소 안 LF 바이트 해시는 `51c020fb…`·`1d2fa592…`, CRLF는 `c877c065…`·`8823195a…` [실측]. 사전 등록·재현 명령은 CRLF 값(`EVAL_REPORT.md:1068`)이라, 줄바꿈을 바꾸지 않는 리눅스·맥 clone에서는 `--dataset-sha256` 검사가 맞지 않을 것으로 보인다 [추정: 리눅스에서 돌려 보지 않음]. 고치는 법은 `.gitattributes`에 두 줄(`text eol=crlf`) — 공동 폴더라 조장 확인 뒤 |
| L-28 동결 목록 | `evals/FROZEN.json`은 v1·v2만 담는다. 검증 문항은 동결 목록 밖에 두고 `--dataset-sha256`으로 확인하는 설계다 [코드: `evals/agent/exp_multi_v2.py:357`]. 빠뜨린 것이 아니라 설계이므로 놓친 것에서 뺀다 |

## 4. 확인한 것
| 대상 | 결과 |
|---|---|
| 포트폴리오 인용 | 숫자·줄 55쌍 스크립트 대조 통과(기존 42쌍 + 새 13쌍, `EVAL_REPORT.md` main `3225f107`) [실측] |
| AI 표기 검사 | 커밋 메시지 0. 추가 줄 1건은 원래 있던 `docs/docs.md` 행(`.claude/skills/` 경로를 가리키는 #132 기록)의 PR 칸만 바꾼 것이라 새 표기 0(`ai_tools_log.md` 제외) |

## 5. 남의 폴더 (조장 확인 필요)
- `docs/`(조장): `docs/docs.md` 기록 칸·행, `docs/pr-notes/`(이름 바꾸기, 이 문서).
- `docs/deliverables/`(조장): `work-summary-박진형.md`(새 파일, 본인 정리), `portfolio-박진형.md`(본인 제출물), `ai_tools_log.md` 한 줄과 이름 바꾼 곳.
- 기록 칸만 고친 폴더: `backend/`, `backend/graph/recall/`, `backend/memory/`, `db/`, `data/LICENSES/`, `mock_erp/`, `web/` — 박진형 행의 PR 칸만.

## 6. 한계·남은 일
- C-14(수집 실행 501의 안내 문구가 꺼진 정시 수집을 쓰라고 함)는 조장 결정 기록(`docs/decisions.md:12`, `SDD.md:367`)과 같은 문장이라 고치지 않고 조장 질문으로 남김.
- L-27 `.gitattributes`, README Windows clone 안내, `.env.example` 변수 16개는 조장 결정.
- 이 PR 번호가 나오면 이 문서를 `PR-<번호>.md`로 바꾸고 기록 칸 `미정`을 채운다.
