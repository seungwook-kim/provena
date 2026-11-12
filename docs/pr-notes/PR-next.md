# PR-next — 놓친 것 목록 마무리 묶음 (F-16, F-08, H-21, K-16·A-14·I-06, R-03, 11/11 화면 수정 되살리기)
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 머지: 아직 안 함 / 기준: origin/main `601183c7` 위 묶음 브랜치 `pr-next-1112` (브랜치 5개를 `git merge`)
- 근거 종류 표기: [코드] `파일:줄` / [문서] 조장 목록·팀 문서 / [실측] 직접 돌린 결과 / [추정].
- 이 PR은 배포하지 않았다. 운영 호출은 배포 주소 `GET /health` 1회(A-14)뿐이다. 운영 DB 쓰기, LLM 호출 없음. F-08의 Voyage 임베딩 호출(약 0.003달러)은 로컬 임시 DB에만 썼다.

## 1. 닫는 항목
| 번호 | 상태 | 한 줄 |
|---|---|---|
| F-16 | 일부 | `data/pdf/` PDF 7건의 이용 조건 근거를 찾아 기록. PDF를 지목한 근거는 없음 → 유지·삭제는 팀 결정 |
| F-08 | 완료 | 증분 수집 `--once` 로컬 1회 실행 증거 |
| H-21 | 완료(화면) | 승인함에 관리자용 결정표 변환 폼 |
| K-16 | 일부 | 동결 전 비밀값·`.env.example`·README 점검(동결 직전 재확인 남음) |
| A-14 | 일부 | 배포 주소 생존 확인(11/12 1회) |
| I-06 | 확인 | `/health`를 정기 호출하는 주체 없음 |
| R-03 | 일부 | 포트폴리오 줄 번호·최종 배포 숫자·PR 수 갱신(#135 머지 뒤 한 번 더) |

## 2. 개발한 것
### H-21 결정표 변환 화면 (`web/`, 조장 지시 11/11로 진형이 맡음)
- 무엇: 백엔드에만 있던 `POST /decision-tables/convert`를 승인함 화면에서 부르는 폼. 관리자에게만 보인다.
- 파일: `web/react-app/src/components/DecisionConvertPanel.jsx`(새 파일), `lib/api.js`(`convertDecisionTable`), `lib/approvals-service.js`(응답·오류 해석), `pages/ApprovalsPage.jsx`(폼 넣기), `styles.css`, `decision-convert.test.jsx`(새 시험).
- 어떻게
  - 요청 본문은 `{category}`, CSRF 헤더를 붙인다 [코드: `backend/graph/decision/routes.py:224-230`, `:426` `require_admin`·`require_csrf`].
  - 키 없는 데모는 201과 `status: "example"`을 돌려준다(#132 L-23 조장 결정) [코드: `routes.py:272-278`]. 화면은 "예시"로 표시하고 승인함 목록을 다시 부르지 않는다. 실제 초안(대기)일 때만 목록을 다시 부른다.
  - 오류는 서버 공통 모양 `{detail, error:{code, message}}`을 읽어 이유별 합니다체 문구로 보여 준다 [코드: `backend/api/errors.py`]. 409는 서버 문구가 해라체라 그대로 보이지 않고 고정 문구 "이 업무 종류의 결정표가 이미 있거나 승인을 기다리고 있습니다"로 바꿨다. 같은 409가 '승인된 표 있음'과 '승인 대기 중' 두 이유로 나오기 때문이다 [코드: `routes.py:257-260`].
- 버린 대안: 화면에서 결과 표를 바로 편집 — 승인은 승인함에서 하는 흐름(`docs/specs/decision-approval.md`)이라 넣지 않았다.

### F-08 증분 수집 1회 실행 (`backend/rag/`)
- 무엇: 정시 실행이 꺼져 있어 증분 수집이 실제로 도는 증거가 없었다. 로컬에서 한 번 돌렸다.
- 어떻게: 23,095청크 스냅샷을 새 로컬 Postgres(127.0.0.1)에 올리고 `python -m backend.rag.ingest.schedule --once --slot manual-f08-1112` 실행. 운영 DB는 쓰지 않았다.
- 결과 [실측]: `succeeded`, 핸드북 `129243bc → d92556d4`. 추가 3, 수정 149, 서식만 152, 삭제 반영 2. 새 임베딩 436, 재사용 6,946. Voyage 4회 52,539토큰(약 0.003달러), 62.8초.
- 기록: `docs/specs/incremental.md` 결정 ①을 "했음"으로, `backend/rag/ingest/ingest.md` 기록 행. 원본 출력은 저장소 밖에 보관(키 없음).
- 덤으로 본 것: `sync_runs.started_at`과 `finished_at`이 같은 값으로 저장된다(코드가 같은 시각을 두 칸에 씀). 실행 시간이 DB에 안 남는 작은 결함이라 기록만 한다.

### main에 안 들어간 11/11 화면 수정 되살리기 (`web/`)
- 계기: 진형이 로컬 데모와 배포 주소에서 "이메일 인증 이어하기" 링크가 아직 있는 것을 발견(11/12). 11/11에 지운 커밋이 로컬 브랜치(`web-pr-1111`, `web-pr-1111-onmain`)에만 있고 PR에 실리지 않았다 [실측: `git merge-base --is-ancestor` → main에 없음, `git cherry` 4개 중 3개가 main에 없음].
- 가져온 것
  - `fb518934` 로그인·회원가입 화면의 고정 "이메일 인증 이어하기" 링크 제거. 미인증 로그인·회원가입 409일 때만 오류 칸 안 "인증번호 다시 받기" 링크. `backend/auth.py` 안내 문구 2곳, `docs/specs/login.md` AC-08, 시험 `signup-conflict.test.jsx`(새로)·`login-unverified.test.jsx`·`tests/test_email_signup.py`.
  - `bd49a0d0` 리콜·승인함 좁은 화면 깨짐. main에 같은 CSS 규칙 7개 중 5개가 없었다 [실측: `styles.css` 문자열 검색]. 시험 `styles-layout.test.js`(새로).
- 가져오지 않은 것: `1d149f71`(하루 요약 `digests`, 남의 알림 확인 버튼, 수집 상태 한국어). main에 이미 같은 동작이 있다 [코드: `recall-service.js:132`, `:295`, `RecallPage.jsx:52`, `ChangeMonitoringPage.jsx:13`].
- 충돌: `web/web.md`(기록 행), `styles.css`(파일 끝 규칙) — 양쪽 다 살림.
- 확인 [실측]: vitest 334개, 가입 pytest 10개, `vite build` 성공, 새로 띄운 로컬 서버 화면 빌드에 링크 문구 0건.

## 3. 확인·기록한 것
### F-16 PDF 7건 이용 조건 (`data/LICENSES/LICENSES.md`, 조장 폴더)
- 핸드북 사용 안내의 문장 "Our handbook falls under the Attribution-ShareAlike 4.0 International license." [문서: https://handbook.gitlab.com/handbook/about/handbook-usage/ , 11/12 확인]. 사이트 맨 아래는 "© 2026 GitLab All Rights Reserved"이고, 고정 커밋의 LICENSE는 MIT(소프트웨어 대상)라 PDF를 지목한 근거가 없다.
- PDF 7건 본문에 ©·Copyright·CC 문구 0건 [실측: pdftotext].
- 판정: 5건은 "팀 결정 전까지 유지, CC BY-SA를 적용했다고 쓰지 않음", `git-cheat-sheet.pdf`·`customer_dpa_5_1_26.pdf`는 제거 권장. 결정은 팀.

### K-16·A-14·I-06 (`docs/pr-notes/k16-a14-i06-check-1112.md`)
- 비밀값: main 단일 브랜치 새 clone 전체 기록을 gitleaks로 검사 → `.gitleaksignore` 적용 0건, 예외를 빼면 9건이고 모두 예외 목록의 가짜 값과 일치 [실측].
- `.env.example`: 외부 키는 모두 빈 값. 코드가 읽는 변수 138개 중 19개가 없음(기본 꺼짐 스위치·플랫폼 값) [실측]. 조장 파일이라 고치지 않고 추가 권고만.
- 배포: 11/12 14:38 `GET /health` → 200, 34.8초(콜드 스타트로 보임 [추정]) [실측].
- `/health` 정기 호출 주체: 없음. `/health`는 불릴 때만 `SELECT 1` [코드: `backend/main.py:387-398`], 정시 실행은 `handbook-sync.yml:9` 하나, README 배포 명령에 `--min-instances` 없음.

### R-03 포트폴리오 (`docs/deliverables/portfolio-박진형.md`)
- EVAL_REPORT 인용 줄 번호를 #133·#134 뒤 파일에 맞춤(숫자·줄 44쌍 스크립트 대조 통과) [실측].
- 운영 숫자를 최종 배포 `provena-api-00044-49s`로: 정답 근거 인용률 0.913, 인용 정확도 0.927, p95 11.524초(SPEC 10초 초과도 적음) [문서: `EVAL_REPORT.md:686-687, 892`]. 로컬 값(p95 9.806초)은 "로컬"로 분리.
- PR 수 32 → 37(`601183c7` 기준).

## 4. 진형이 결정한 것 (버린 대안 포함)
| 결정 | 무엇을 골랐나 | 왜 | 버린 대안 | 출처 |
|---|---|---|---|---|
| F-08 | 로컬 임시 DB에서 실제로 1회 돌림 | 비용 약 0.003달러, 운영 DB 영향 없음 | 운영 DB에서 실행(동결 전 운영 데이터가 바뀜), 문서로만 남김(실행 증거가 없음) | 진형 11/12 |
| B-12 | 하지 않음 | 수집 쪽(`sync_runs`·`changed_articles`)은 완료. 남은 리콜 판정 실패 목록은 리콜 담당이 없고 DB 표를 새로 만들어야 함 | 실패 목록 표 추가(DB 구조 변경, 3명 승인 필요) | 조장 목록 B-12, 진형 11/12 |
| F-09·D-11 | 하지 않음 | 링크 그래프 검색(가산 +3)은 동결 전 측정·사전 등록까지 할 시간이 없음 | 구현만 하고 측정 없이 올림(G5 규칙상 개선이라 쓸 수 없음) | 조장 목록 F-09·D-11, 진형 11/12 |
| S-02 | 하지 않음 | LLM 채점 사람 일치도는 사람 판정 데이터가 필요하고 시점 미정 | AI 판정으로 대신(사람 일치도가 아님) | 조장 목록 S-02, 진형 11/12 |
| S-08 | 하지 않음 | PDF 205청크를 적재하면 동결 평가셋(23,095청크) 결과가 바뀜 | 적재 후 재측정(동결 전 시간 부족, LLM 비용) | 조장 목록 S-08, 진형 11/12 |
| 담당 없음 중 뺀 것 | A-06·A-09·M-12·A-16·B-13·K-10·M-03 | GCP 콘솔·평가 계정·DB 권한·DB 구조 변경·LLM 비용·프론트 미완 | 진형이 맡아 진행(되돌리기 어렵거나 권한·비용 결정 필요) | 진형 11/12, 조장에게 담당 요청 |
| H-21 409 문구 | 세 이유를 다 덮는 고정 합니다체 문구 | 같은 `conflict` 코드가 세 이유로 나옴(`routes.py:257`, `:260`, `:445`), 서버 문구는 해라체 | 서버 문구 그대로(말투 섞임), 한 이유만 말하는 문구(다른 이유에서 틀린 안내) | 진형 11/12, 독립 검증 지적 |
| H-21 입력 방식 | 업무 종류를 직접 입력(예시 placeholder) | 백엔드가 이름을 정규화해 찾고 없으면 404로 알려 줌(`routes.py:233-241`). 권한표 업무 종류 목록 API가 없음(`GET /decision-tables`는 승인된 표만, `routes.py:420`) | 선택 목록(권한표 업무 종류 목록 API가 없음) | 진형 11/12 |
| H-21 확인창 | 변환 전에 확인창 | 키가 있으면 LLM을 부르고 승인함에 올라감(비용·기록이 남음) | 바로 실행(실수 클릭으로 LLM 호출) | 진형 11/12 |

### 제안(조장 승인 대기, 결정 아님)
- K-15: `handbook-sync`를 주말 11/14~15·동결 뒤까지 꺼 둔 채 유지. 버린 대안: 켜 둠(동결 뒤 자동으로 데이터가 바뀜). 승인되면 이 줄을 결정으로 옮긴다.

## 5. 확인한 것
| 대상 | 결과 |
|---|---|
| vitest 전체 | 334개 통과 [실측, 11/12 묶음 브랜치, 되살린 화면 수정 포함] |
| 결정표 변환 시험 | 18개 통과 [실측]. 변이: 409 분기 `approvals-service.js:204`(code 없는 409)를 끄면 1개 실패, 예시 판정(`status === 'example'`)을 깨면 3개 실패, `CONVERT_ERROR_MESSAGES.no_source`를 지우면 1개 실패. 503 `not_configured` 시험은 전용 문구(`approvals-service.js:196`)를 넣기 전에 실패해 "승인 저장소" 문구가 나오던 것을 잡았다 |
| `vite build` | 성공 [실측] |
| pytest | 묶음 브랜치는 백엔드 코드를 바꾸지 않았다. 전체 실행 결과는 올리기 전에 붙인다 |
| 독립 검증 | 작업자 결론 없이 브랜치 diff만 주고 두 번 따로 검증: F-16 인용 원문·커밋 날짜, F-08 숫자 9개, H-21 요청·응답·오류 코드 일치. 시험이 서버가 보내지 않는 오류 모양을 쓰던 것, 409 세 번째 이유, 남의 폴더 누락을 찾아 고침 |
| AI 표기 검사 | 커밋 메시지 0, 추가 줄 0(`ai_tools_log.md` 제외) |

## 6. 남의 폴더 (조장 확인 필요)
- `data/LICENSES/LICENSES.md`(조장, `TEAM_GUIDE.md:89`): F-16 기록.
- `docs/`(조장): `docs/docs.md` 기록 행, `docs/pr-notes/`(이 문서와 점검 노트), `docs/specs/decision-approval.md` 화면 한 줄과 AC-07, `docs/specs/incremental.md` 결정 ①(진형 파트 절).
- `docs/deliverables/`(조장): `ai_tools_log.md` 한 줄, `portfolio-박진형.md`(본인 제출물).
- `web/`(주인 강경희, 조장 지시 11/11로 진형이 맡음): H-21 화면·시험, 되살린 로그인·좁은 화면 수정, `web/web.md` 기록 행.
- `backend/auth.py`(조장): 가입 안내 문구 2곳(없는 링크를 가리키던 문구). `docs/specs/login.md` AC-08 같은 표현.
- `.env.example` 변수 추가는 조장 결정으로 남김.

## 7. 한계·남은 일
- H-21 브라우저 확인: 진형이 로컬 데모(`docker compose up`, 키 없음)에서 일반 사용자 폼 없음·관리자 폼·빈칸·확인창·예시 표시·없는 업무 종류 안내를 확인함(11/12). 409·502·503은 데모에서 만들 수 없어 시험으로만 확인.
- #135와 겹치는 파일: `docs/docs.md`, `docs/deliverables/ai_tools_log.md`(둘 다 기록 표 맨 위 행). #135가 먼저 머지되면 이 브랜치에서 `git merge origin/main`으로 두 표의 행을 모두 살린다.
- `session.test.jsx:785`가 전체 실행에서 한 번 불안정하게 실패(이 PR이 건드리지 않은 파일, 단독 실행 66/66 통과).
- K-16은 11/16 동결 직전에 gitleaks를 다시 돌린다.
- 포트폴리오는 #135 머지 뒤 변이 시험 18~33 추가와 줄 번호 재확인.
- 조장 결정 대기: K-15 승인, F-04 응답 속도, 발표 전 서버 깨우기, `.env.example` 변수, F-16 PDF 2건 삭제 여부.
