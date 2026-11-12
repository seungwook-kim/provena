# PR-next — 놓친 것 목록 후속 묶음 작업 내역
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 머지: 아직 안 함 / 기준: `origin/main` `601183c7` (7개 브랜치를 합친 통합 브랜치 `integ-1112`)

## 배포 상태
**배포 안 함, 모든 확인은 로컬이다.** 시험·변이는 DB·키·네트워크·Docker 없이 가짜 모델로(묶음 4) 운영 주소·운영 DB·실제 LLM 호출은 하지 않았다.

## 닫는 항목
| 번호 | 상태 | 절 |
|---|---|---|
| L-04, L-08, L-10, S-03, S-04, S-07 (묶음 4) | 시험·변이 확인·측정 코드 추가 (한계는 절에 기록) | 1 |
| C-14, L-23, E-04, G-08 (#132 조장 결정 반영) | 문서에 확정으로 반영 | 2 |
| K-19 | 확인만, 해결 판정 (코드 변경 없음) | 3 |
| C-15, P-07 | SDK 생성 | 4 |
| K-11, S-05 | 로컬 실측 | 5 |
| K-15 (제안) | 조장 승인 대기 | 6 |
| J-01, J-02, J-03, L-09, O-16 | 한계 기록 (구현 안 함) | 6 |
| L-24 | 확인하지 못한 경로 로컬 실행 (통과 44, 못 함 4, 참고 4) | 7 |

## 조장 확인 필요
- K-15 주말 11/14~15와 동결(11/16 24:00) 뒤 정책 제안(`handbook-sync` 비활성 유지, 새 자동 실행·배포 없음) 승인 (6절). 조장 목록의 재가동 기한 "늦어도 11/13(금)"이 남아 있다.
- 11/17 제출 문서(실패 사례 분석 등)는 동결(코드) 뒤에도 가이드 일정대로 낼 수 있다는 해석 (6절).
- `handbook-sync`의 `disabled_manually` 상태는 GitHub 설정이라 저장소에서 확인되지 않았다. 오늘 상태 확인 (6절).
- 되묻기 뒤 후속 메시지가 앞 질문을 이어받지 않는 것이 설계인지 (7절).


## 1. 묶음 4: 시험 공백·변이 확인·측정 코드 (L-04 L-08 L-10 S-03 S-04 S-07)
- 작업자: 박진형 (jinyeong-731) / 머지: 아직 안 함 / 기준: `origin/main` `d6e658ac`(PR #131 머지 뒤), 브랜치 `fix-b4-tests`
- 번호 주의: 목록 파일(놓친 것 목록 2026-11-11)의 행은 변이 확인 = L-10, 근거 비워도 답하는지 = S-03, 질의 하나 빼기·인용 없는 답 분모 = S-04, bge int8 캐시 = S-07이다. 아래는 목록 행 기준으로 적었다.

### 먼저 확인한 것: main이 이미 해결한 부분
| 항목 | 판정 | 근거 |
|---|---|---|
| L-08 채팅 HTTP 오류 프런트 시험 | 이미 해결 | 코드: `web/react-app/src/lib/chat-service.test.js:218-` `createApiChatAdapter HTTP errors (H-08)`(409·503 거절, 스트림 끊김, 오류 이벤트). 새로 안 만듦 |
| L-08 하루 요약 계약 시험 | 일부 | 코드: `tests/test_recall_alert_fatigue.py:124` 한 건(정렬·id 안정)뿐. 칸 관계 시험은 없어 추가 |
| L-08 영향 미리보기 시험 | 일부 | 코드: `tests/test_api_recalls.py:378-403`은 HTTP 겉(드라이런·400)만. `changes_from_pages`·`preview_impact` 직접 시험은 없어 추가 |
| L-08 번들+백엔드 한 바퀴 | 일부 | 코드: 가입 승인(`test_signup_admin_api.py:41`)·프로필(`test_profile_api.py`)·채팅(`test_api_*`)이 따로 있고 한 앱에서 이어 부르는 시험은 없음 ; 긴 SSE(`api.test.js:71-77`)·Google 시작 화면(`session.test.jsx:480-498`, `signup-fixes.test.jsx:29`) 프런트 시험은 이미 main에 있음 |
| L-10 변이 | 미해결 | 문서: `docs/GATES.md` 변이 표가 17번(11/5)까지, 목록 L-10 행 "D5 이후 코드 변이 행 없음" |
| S-03 근거 비움 | 미해결 | 코드: `tests/`에서 검색 결과가 빈 채 판정이 "충분"이라 답하는 경우를 막는 시험 없음(`grep` 기준, 추정은 아님) |
| S-04 | 미해결 | 코드: `evals/`에 인용 없는 답 분모 계산 파일 없음 |
| S-07 bge int8 | 미해결 | 코드: 병합 전 `evals/retrieval/experiment_v1.py` `_Scores.score`가 int8도 저장 값을 씀. 문서: `docs/embedding_measurement.md:361` "수정안은 `experiment_v1.py`에 반영하지 않았다" |

### L-08 시험 공백
#### 무엇을 바꿨나
- `tests/test_digest_contract.py`(4개): 하루 요약의 건수 합·중요도·`conclusion_changed`·설명 길이·id 순서 무관.
- `tests/test_impact_preview_contract.py`(9개): `changes_from_pages`의 수정·추가·삭제 분류와 서식만 바뀐 섹션 제외, `preview_impact` 요약 숫자 관계, 답 저장소 불변, 마크다운에 사용자 id 없음·출처 문구 있음.
- `tests/test_round_trip_app.py`(2개): 실제 `create_app` 한 개에 `POST /auth/signup` → 기록용 발송기(`RecordingEmailSender.deliveries`)에서 인증번호를 읽어 `POST /auth/signup/verify` → 승인 전 로그인 거절 → 소유자 승인 → 로그인 → `/chat` → `/threads`(목록 행의 순서 가입·인증·승인·로그인·채팅; `/me/profile`은 제외), 그리고 거절된 사용자는 로그인 불가·익명 `/chat` 401.
#### 왜
- 목록 L-08 행의 "남음" 목록(하루 요약·영향 미리보기 diff 계약, 번들+백엔드 한 바퀴, 채팅 HTTP 오류). 근거 종류: 문서(목록 행)·코드.
#### 확인한 것 (로컬)
- 새 시험 통과: digest 4, impact 9, round trip 2.
- 변이(`tests/mutation_d5.py`): 26 요약 중요도 고정 → 1 실패, 27 `any`→`all` → 1, 28 `answers_checked=0` → 1, 29 출처 문구 제거 → 1, 30 옛 본문 모음 조건 → 2, 32 거절도 계정 생성 → 1, 33 승인해도 계정 없음 → 1. 인증 단계 변이(`email_verified_at` 기록을 지움) → 1 실패(승인이 409), 원본 복구 확인.
#### 한계
- 내 정보(`/me/profile`)는 DB 없이 조립한 앱에 열리지 않아(`backend/main.py` `profile_store`) 한 바퀴에 못 넣었다(시험은 `test_profile_api.py`가 따로 봄).
- 만들어진 화면 번들은 서빙하지 않았다(빌드에 npm 필요). 긴 SSE와 Google 시작 화면 시험은 main에 이미 있어 새로 만들지 않았다(아래 표기).
- 긴 SSE: 이미 해결 in main. 코드: `web/react-app/src/lib/api.test.js:71-77` `streamChatMessage many events (H-17)`(30000개 이벤트를 한 덩어리로 받아도 콜백이 겹쌓이지 않음, 80행에서 30000개 확인).
- Google 시작 화면: 이미 해결 in main. 코드: `web/react-app/src/session.test.jsx:480-498`(`/auth/google/start` 링크, `oauth_error` 한국어 안내와 모르는 코드 무시, OAuth 복귀 경로가 채팅으로 감)과 `web/react-app/src/signup-fixes.test.jsx:29` H-09(인증 코드 단계에서 Google 링크 숨김).
- 승인은 `MemoryAuthStore`라 Postgres 경로는 `test_signup_postgres_integration.py`(DB 필요)가 맡는다.

### L-10 변이 확인 (+ S-03·S-04 시험의 변이)
#### 무엇을 바꿨나
- `tests/mutation_d5.py`: 변이 18~33번. 변이마다 원본을 임시 보관하고 `try/finally`로 복구, 복구 뒤 바이트 비교. `timeout`으로 감싸지 않음. 변이 전 통과·변이 뒤 실패 수를 출력.
- `tests/test_values_backed.py`(3개): `grounding.values_backed`(값이 표시한 청크에 없으면 False).
- `docs/GATES.md` 변이 표에 18~33번(16행) 추가. G7 행은 안 건드림.
#### 왜
- 목록 L-10 행: D5 이후 코드(멀티, 승인 재개, 판정 단계)에 변이 행 없음. 대상 줄은 직접 열어 고름: `backend/graph/decision/execute.py`(승인 재개 조건), `backend/graph/multi.py`(writer 다음 단계, 재조사 한도), `backend/graph/grounding.py`(`values_backed`, 기간 미포함, 전부 지움).
#### 확인한 것 (로컬, 변이 전 통과 → 변이 뒤 실패 수)
| 번호 | 변이 | 변이 뒤 실패 |
|---|---|---|
| 18 | 승인 재개 조건 `False` | 3 (52개 중) |
| 19 | multi writer→end | 118 (650개 중) |
| 20 | multi 재조사 한도 항상 참 | 20 |
| 21 | values_backed 검사 건너뜀 | 1 (`test_values_backed.py` 단독) |
| 22 | 기간 미포함 거절 건너뜀 | 3 |
| 23 | 전부 지움 거절 건너뜀 | 1 |
- 실행 뒤 변이 문자열을 `grep`해 남은 것 0건, `git status`의 추적 파일 변경은 의도한 것만.
#### 한계
- 18~23번은 기존 시험이 잡은 것이라 시험을 새로 만들지 않았고, 21번만 시험(`test_values_backed.py`)을 보강했다.
- 변이는 줄 하나씩이라 같은 함수의 다른 줄은 보장하지 않는다. 목록의 "3건"은 넘겼지만 전체 코드 변이 점수는 아니다.

### S-03 근거를 비운 입력 회귀 시험
#### 무엇을 바꿨나
- `tests/test_empty_evidence.py`(6개): 검색이 빈 목록을 돌려주고 판정 모델이 "충분"이라 답하며 가짜 인용·무인용·평문 답을 지어내도 단일·멀티 그래프 모두 `kind != "answer"`, 인용 없음, 지어낸 값(15분)이 응답에 없음, 판정·답 작성 모델 호출 0회, 답 저장소 비어 있음.
#### 왜
- 목록 S-03 행(강의 3주 02). 막는 곳: `backend/graph/build.py`의 `if not chunks:`(자료가 없으면 LLM에 묻지 않고 부족으로 봄). 근거: 코드.
#### 확인한 것 (로컬)
- 통과 6개. 변이 24번(`if not chunks:`→`if False:`) 뒤 6개 모두 실패.
#### 한계
- 가짜 모델 시험이다. 실제 모델이 빈 근거에서 어떻게 답하는지는 보지 않았다(LLM 호출 금지).

### S-04 인용 없는 답 분모 + 질의 하나 빼기
#### 무엇을 바꿨나
- `evals/uncited_answers.py`: 저장된 `rows.jsonl`만 읽어 전체·답·인용 없는 답·답 기준 비율·전체 기준 비율·하위 질문 둘 이상 문항 수를 낸다. 답이 0이면 비율을 정하지 않음(0 나눗셈 없음).
- `tests/test_uncited_and_drop_one.py`(6개): 분모 계산, 답 0건, 저장된 `agent_v1_final_cite`는 인용 없는 답 0건, `merge_by_score`에서 하위 질문 하나를 빼도 1등이 그대로인지(대조 시험 포함).
#### 왜
- 목록 S-04 행(강의 1주 13, 1주 01). 근거: 문서(목록)·코드(`backend/rag/retrieve/search.py:483` `merge_by_score`).
#### 확인한 것 (로컬)
- 실행 결과(실측, 저장된 결과): `agent_v1_final_cite` 전체 30·답 13·인용 없는 답 0, `agent_v1_fix2_pg` 30·15·0, `agent_v1_service_pg` 30·15·0. 시험 통과 6개(커밋 `280e798c` 메시지의 5개는 잘못 센 값). 변이 25번(`lists[1:]`→`lists[2:]`) 뒤 2개 실패.
#### 한계
- 저장된 결과에는 하위 질문을 합친 뒤 목록(`retrieved`)만 있고 하위 질문별 목록이 없어서, **실제 결과로 "하나 빼고 다시 계산"은 못 한다**. 하나 빼기 시험은 `merge_by_score`에 만든 목록을 넣은 것이다.
- 비율 0은 이 평가셋 30건에서 답 13~15건의 값이다. 모집단 전체 주장은 아니다.

### S-07·L-04 bge int8 점수 캐시 (I-013)
#### 무엇을 바꿨나
- 판정: main은 해결 안 함. `evals/retrieval/experiment_v1.py`의 `_Scores.score`가 int8일 때 저장 값을 읽지도 쓰지도 않고 후보 전체를 한 번에 계산하게 함(서비스 방식과 같음). 다른 리랭커는 그대로 저장 값 재사용.
- `tests/test_exp_int8_scores.py`(3개), `docs/embedding_measurement.md` 한계 문장 정정(수정안 중 int8 부분 반영, v1 값은 다시 재지 않음 = 수치 재측정 안 함).
- 서비스 영향 없음: 바뀐 곳은 실험 스크립트 `evals/retrieval/experiment_v1.py`뿐이다. 서비스의 확정 조합은 리랭커가 없다: `docs/decisions.md:46`(2026-11-03 "리랭커 없음"으로 확정)·`:175`(팀장 확정), `backend/rag/retrieve/rerank.py:43` `DEFAULT_MODEL = NONE`(켜려면 환경변수 `RERANK_MODEL`).
#### 왜
- 목록 S-07 행. 근거: 문서 `docs/embedding_measurement.md:326`(묶음에 따라 점수가 달라짐), `:361`(반영 안 함), `backend/rag/retrieve/retrieve.md:37` I-013 상태 "열림". 확정 조합이 리랭커 없음이라 서비스 영향 없음은 목록의 판단이다.
- 지시서의 "L-04"는 이 항목을 가리킨 것으로 보고 처리했다. 목록의 L-04 행(`exclusions.json`, 재현 명령)은 따로 보지 않았다.
#### 확인한 것 (로컬)
- 시험 3개 통과, 변이 31번(int8 분기 끔) 뒤 2개 실패.
#### 한계
- 이미 낸 v1 418조합의 int8 값은 다시 재지 않았다(재측정은 모델 실행이 필요). `retrieve.md` I-013 상태 칸은 담당(김승욱)이 닫을 항목이라 바꾸지 않았다.

### L-04 exclusions.json 형식 시험과 재현 명령 안내
#### 무엇을 바꿨나
- `tests/test_exclusions_schema.py`(12개): `evals/exclusions.json`이 JSON이고 `as_of`·`excluded` 키가 있는지, 항목마다 id가 `evals/dataset_v1.jsonl` 또는 `dataset_v2.jsonl`의 `id`에 있는지, `reason`이 비지 않은 문자열인지, id 중복이 없는지 본다. 항목 0건이면 통과. 검사 함수가 경로를 받아 임시 파일로 나쁜 입력을 시험한다. 실제 파일과 평가셋은 바꾸지 않았다.
- `EVAL_REPORT.md` 9장 첫 명령 앞에 한 줄 추가: `--chunks data/chunks/chunks.jsonl`은 커밋하지 않은 파일이며 `python -m backend.rag.ingest.chunk`로 만들거나 `data/index.tar.gz`를 푼 `data/index/chunks.jsonl`을 쓴다. 명령과 숫자는 그대로. **`EVAL_REPORT.md`는 조장 파일**이라 이 한 줄은 조장이 확인하고 받을 부분이다.
- `evals/evals.md`, `docs/docs.md` 기록 표에 한 줄씩.
#### 왜
- 목록 L-04 행. 근거: 코드 `evals/retrieval/run.py:38-41`(`load_exclusions`는 `id`·`reason`을 읽기만 하고 검증은 없음), 문서 `evals/README.md:55-62`(형식과 "사유를 공개"가 조건), 사실 `evals/exclusions.json`은 `{"as_of": null, "excluded": []}`로 시험이 파일을 보는 곳이 없었다.
- 안내 한 줄의 근거(코드·문서): `.gitignore:40`이 `data/chunks/`를 막음, `backend/rag/ingest/chunk.py:285` 출력 기본값 `data/chunks`와 `docs/specs/chunk.md:49`(출력 `data/chunks/chunks.jsonl`, 커밋 안 함), `backend/rag/retrieve/index.py:92-94`가 `chunks.jsonl`을 `shutil.copyfile`로 `data/index/chunks.jsonl`에 그대로 복사(같은 형식), `data/index.tar.gz` 안에 `chunks.jsonl`이 있음(`tar -tzf`로 확인), `docs/specs/eval-retrieval.md:23`이 같은 안내를 이미 적음.
#### 확인한 것 (로컬)
- 시험 12개 통과(실제 파일 1, 0건 1, 정상 항목 1, 나쁜 입력 9). 나쁜 입력 9가지는 모두 문제를 돌려줘 실패로 잡힌다: JSON 깨짐, `as_of` 없음, `excluded` 없음, 평가셋에 없는 id, reason 빈 문자열, reason 공백, reason 없음, id 없음, id 중복.
- 변이(코드를 망가뜨려 보기)는 따로 돌리지 않았다. 나쁜 입력 사례가 검사 함수의 각 분기를 직접 지나가는 것으로 대신했다.
#### 한계
- 시험이 평가셋 id 존재만 본다. 제외 사유가 사실인지, 코퍼스가 바뀐 문항이 맞는지는 보지 않는다(사람 판단).
- `load_exclusions`(run.py)가 이 검사를 호출하지는 않는다. 형식이 틀린 파일은 CI 시험에서 잡히고 실행 시점에는 잡히지 않는다.
- 안내 한 줄은 명령을 직접 새 저장소에서 다시 돌려 확인한 것이 아니라 위 코드·문서 근거로 쓴 것이다(`chunk.py`는 `data/corpus.tar.gz`를 자동으로 푸는 코드가 있으나 이 작업에서 실행하지 않음).

### 리뷰 반영
- L-08 한 바퀴 시험: `store.create_pending_user` 직접 삽입을 없애고 `POST /auth/signup` → 인증번호 읽기 → `POST /auth/signup/verify` → 승인 → 로그인 → `/chat`·`/threads` 순으로 바꿈. 거절 사용자 시험은 유지.
- L-08 한계: "Google 시작 화면·긴 SSE 시험은 안 만들었다" 문장을 지우고 둘 다 main에 이미 있다고 근거(파일:줄)와 함께 적음. 요약 표의 L-08 행에도 반영.
- S-07: 변경은 실험 스크립트뿐이고 서비스 확정 조합은 리랭커 없음이라 서비스 영향 없음을 근거와 함께 적음. "수치 재측정 안 함" 명시.

## 2. #132 조장 리뷰 결정 반영 (C-14 L-23 E-04 G-08)
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: `origin/main` `601183c7` 위 브랜치 `fix-132-decisions`
- 근거 종류: [조장] 2026-11-12 #132 리뷰 전달문 / [코드] 파일:줄 / [실측] 로컬 grep.

### 무엇을 바꿨나
#132에서 "팀장 판단 필요"·"방식 미정"으로 열어 둔 C-14·L-23·E-04와 G-08·`.env.example` 문장을 확정 상태로 고쳤다. 코드·숫자는 바꾸지 않았다.

| 파일:줄 | 바꾼 내용 |
|---|---|
| `docs/specs/memory.md:83` | E-04 제목을 "충족 판정: 2026-11-12 조장 리뷰(#132)에서 확정"으로, 본문은 충족 판정 이유로 |
| `docs/specs/recall.md:100` | `POST /admin/sync` 설명의 "방식 미정"을 "확정: 정시 수집 workflow 사용"으로 |
| `docs/SDD.md:318`, `:367` | 같은 "방식 미정"을 "수동 실행은 두지 않고 정시 수집 workflow 사용"으로 |
| `docs/api/api.md:30` | openapi 재생성 행에 501 유지 확정 표기 |
| `backend/api/api.md:15` | "실제 수집 실행 방식은 팀장 결정"을 501 유지·정시 수집 workflow로 |
| `backend/graph/decision/decision.md:15` | L-23 201 `status=example` 그대로 확정 |
| `backend/services/services.md:15` | G-08 응답 캐시는 운영·최종 측정에서 켜지 않음, `.env.example` 새 변수 4개는 이미 `.env.example`에 있다(`:134`·`:136`·`:290-291`, 조장이 넣음) |
| `README.md:145` | L-23 201 `status=example` 그대로 확정 |
| `README.md:179` | `LLM_RESPONSE_CACHE`는 운영·최종 측정에서 켜지 않는 이유, `.env.example` 새 변수 4개는 이미 있음 |
| `docs/decisions.md:9-11` | C-14·L-23·E-04 세 행 추가, 결정자 김승욱 (조장), 2026-11-12 |
| `docs/pr-notes/PR-132.md:18, 23, 58, 69, 77, 92` | 열린 질문 문장을 확정 표기로 |
| `docs/pr-notes/PR-132.md:203-` | "13. 조장 리뷰 결정(2026-11-12)" 절 추가, 답 없는 항목 목록 |
| `docs/docs.md:15` | 이 작업 행 추가(PR 미정) |

### 왜 (근거)
- [조장] "승인. G-08 ... 운영과 최종 측정에서는 켜지 않음(운영 /chat 측정은 metadata.eval이 없어 켜면 측정값 오염)". 해당 문장은 위 표의 `README.md:179`, `services.md:15`.
- [실측] `.env.example` 새 변수 4개: 확인 결과 origin/main에 이미 있음(`.env.example:134`·`:136`·`:290-291`, 조장이 넣음). 설명 줄 `:133`이 "운영·측정에서는 끈다"라고 적어 추가 한계 없음.
- [조장] "C-14 ... 501 그대로, 정시 수집 workflow를 쓰는 것으로 문서대로" → `recall.md:100`, `SDD.md:318·367`, `api.md:30`, `backend/api/api.md:15`, `decisions.md` decisions.md 행.
- [조장] "L-23 201 status=example 그대로" → `decision.md:15`, `README.md:145`.
- [조장] "E-04 ... 그래프 thread가 `<user_id>:<thread_id>`이고 남의 thread는 404라 기준의 목적(사용자 분리) 충족" → `memory.md:83`. 코드 근거는 이미 `memory.md`에 있던 `backend/api/routes.py:77, 90-91`, `tests/test_api_isolation.py:12`.

### 확인한 것
- [실측] 변경 파일은 모두 `.md`이고 `.env.example`·코드는 변경 0개(`git diff --stat`).
- [실측] 열린 표현 재검색(`팀장 판단|방식 미정|조장 결정|판단 필요`)에서 C-14·L-23·E-04 관련 남은 곳이 없음을 확인했다. 남은 "조장 결정" 문장은 다른 항목(J·M2 등)이다.

### 한계
- 답이 없는 항목은 그대로 뒀다: I-08 MR 댓글 질문 발췌, O-23 db 번호대, J-09 결정 확정 여부, `.dockerignore` 제안, `FallbackChatModel` 비용 이중 집계, L-23 예시 응답을 Spec에 쓸지.
- PR-132.md의 `파일:줄` 인용은 이 브랜치 기준이다. 코드 변경 없음, 시험 없음.

## 3. K-19 키 없는 데모에서 질문 1이 녹화 답으로 나오는가
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: `origin/main` `601183c7`, 브랜치 `gap3-k19b`
- 결과: 코드 변경 없음, 확인만 했다. 근거 종류: [코드] 파일:줄 / [실측] 로컬 실행.

### 무엇을 확인했나
1. 재생 키에 프롬프트 본문이 들어가는지. 들어가면 `ed5ef330`(11/12 01:40)의 `CLASSIFY_SYSTEM` 변경이 녹화(11/11 20:44)와 어긋났을 수 있다.
2. 키 없이(`DEMO_MODE=1`, LLM·Voyage 키 없음) 데모 질문 9개(README 인용 답 5, 거절 2, 금액만 바꾼 거절 2)를 현재 그래프로 돌려 녹화에 없는 요청이 있는지.
3. 첫 화면 추천 질문 3개가 인용 답 질문과 같은 글자인지.

### 근거 (파일:줄, 시험 수, 재생 결과)
- [코드] 키는 sha256(역할 + 정규화한 메시지 전체)이라 프롬프트 본문이 키에 들어간다(`backend/services/demo_replay.py:11`, `:94`). 정규화는 공백 접기와 `기준일:` 날짜 삭제뿐이다.
- [실측] 현재 `CLASSIFY_SYSTEM`으로 만든 분류 요청 키가 `data/demo_replay/recorded.jsonl`에 9/9 있다(`LLM_JSON_REMINDER=1`, `.env.example:72`). 녹화는 새 분류 프롬프트로 떴다. 녹화 줄 시각은 2026-11-11 20:44~20:46 KST다.
- [실측] 기본 시험 `test_demo_replay_fresh.py`, `test_demo_replay.py`, `test_demo_record_roundtrip.py`, `test_main_demo_warning.py`: 22 passed.
- [실측] `python -m pytest -m demo_replay tests/test_demo_replay_fresh.py`(새 Postgres에 `db/*.sql`과 색인 적재, 키·네트워크 없음): 2 passed. 두 경로(추론 답을 보냄 / 건너뜀)에서 질문 9개 모두 녹화에 없는 요청 0건이다.
- 이 시험이 질문마다 확인하는 것: 인용 답 5개는 `kind=answer`, 인용 1개 이상, 발췌 대체 문구 없음, 인용 청크가 녹화 답에 있음. 거절 4개는 `kind=refuse`.

| 질문 | 결과 | 녹화에 없는 요청 |
|---|---|---|
| Q1 제3자 프로덕션 데이터 | 인용 답(녹화 LLM 답) | 0 |
| Q2 CVSS 9.0 | 인용 답 | 0 |
| Q3 CUD 계약 승인자 | 인용 답 | 0 |
| Q4 EOC 에스컬레이션 | 인용 답 | 0 |
| Q5 외부 SaaS 5만 달러 | 인용 답 | 0 |
| 구매 승인(근거 없음) | 거절 | 0 |
| 점심 메뉴(범위 밖) | 거절 | 0 |
| 3만 달러 | 거절 | 0 |
| 10만 달러 | 거절 | 0 |

- 첫 화면 추천 3개는 Q1·Q3·Q5와 같은 글자이고 시험(`test_first_screen_suggestions_are_readme_keyless_answer_questions`)이 통과해 같은 결과다.
- 결론: K-19 해결. 질문 1은 녹화한 LLM 답으로 나온다.

### 한계
- 가짜 응답이나 실제 LLM이 아니라 녹화 재생만 확인했다. LLM·네트워크 호출은 하지 않았다.
- 재생은 색인 `data/index.tar.gz`와 `SEARCH_RANGE_N` 비움 조건에서 확인했다. 검색 코드나 프롬프트를 바꾸면 다시 확인해야 한다.
- 시험은 API가 아니라 질문 그래프를 직접 돌린다. 화면(SSE)과 브라우저 경로는 보지 않았다.

## 4. OpenAPI에서 Java·Python SDK 생성 (C-15, P-07)
- 작업자: 박진형 (jinyeong-731) / 머지: 아직 안 함 / 기준: origin/main `601183c7` 위 브랜치 `gap3-sdk`

### 무엇을
| 항목 | 내용 |
|---|---|
| 도구 | openapi-generator-cli **7.26.0** (Maven Central `org.openapitools:openapi-generator-cli`, 2026-10-06 공개, 2주 이상 지난 최신판. 7.27.0은 11/02 공개라 제외) |
| jar 검증 | SHA-256 `1760050094997b9cc790cc1350be095f15da8c08a996b184d3eadc4ccda5e35e` (SHA-1은 Maven Central과 일치). jar는 저장소에 넣지 않는다 |
| 위치 | `mock_erp/sdk/` (`mock_erp/` 안: TEAM_GUIDE 5장 폴더 주인표에 `mock_erp/`는 업무시스템 목업, SDD 디렉토리 트리도 `mock_erp/` 아래. 새 최상위 폴더를 만들지 않음) |
| 파일 | `generate.sh`(고정 버전·SHA 확인·고정 옵션), `sdk.md`(폴더 문서), `python/`(패키지 `provena_sdk`), `java/`(패키지 `com.provena.sdk`, `native` 라이브러리, `pom.xml`) |
| 문서 | PRD P-03, SDD 5장·11장·디렉토리 트리, SPEC P-03, `specs/erp-integration.md`, `mock_erp.md`, `docs/docs.md`의 SDK 문구를 "생성함, 도구는 openapi-generator 7.26.0"으로 고침 |
| 생성 크기 | Python 57파일 795,325바이트, Java 55파일 716,817바이트, 합계 112파일 1,512,142바이트(약 1.5MB). gradle 래퍼(바이너리 `gradle-wrapper.jar` 포함)와 미사용 gradle·sbt 파일, 생성기가 내는 CI 설정(`.github/`, `.gitlab-ci.yml`, `.travis.yml`)과 `AndroidManifest.xml`은 `generate.sh`가 지워 저장소에 바이너리가 없다(`git diff --name-only origin/main..HEAD`에서 .jar·.class 0건). 기준(2MB)보다 작아 생성 코드를 커밋한다. 시험·모델 문서 파일은 만들지 않게 해서 줄였다 |
| 재생성 | `bash mock_erp/sdk/generate.sh` |

### 왜 (근거)
- 조장 목록 C-15 "OpenAPI에서 Java·Python SDK 생성"(근거 칸 PRD:176, SDD:533)과 P-07 "SDK 생성 도구, 미정"(SDD:533, 기한 11/16). [문서] `놓친 것 목록 (2026-11-11) (1).md`의 `| C-15 |`, `| P-07 |` 행.
- PRD P-03: "자동 생성 SDK(Java·Python)"를 제공한다고 적혀 있다. [문서] `docs/PRD.md:176`.
- SDD: SDK는 "OpenAPI 명세에서 자동 생성한 Java·Python SDK (생성 도구는 11장)"로 적혀 있고(`docs/SDD.md:56`), 11장에 "SDK 생성 도구 … 선택 기록을 저장소에서 찾지 못했다"(`docs/SDD.md:661`)와 "후보를 D0에 정한다"(`docs/SDD.md:702`)가 있었다. 조장 목록의 "SDD:533"은 옛 줄 번호이고 현재 판에서는 위 세 줄이다. 이 두 줄(661·702)을 도구 확정으로 고쳤다.
- 도구 선택은 진형이 정했다(11/11): Java·Python을 한 도구로 만들 수 있어서 openapi-generator.

### 확인한 것(로컬)
| 확인 | 결과 | 근거 종류 |
|---|---|---|
| 생성 | Python·Java 모두 오류 없이 생성 (명세 `docs/api/openapi.json` OpenAPI 3.1.0, 48경로) | 실측 |
| Python 동작 수 | `DefaultApi`의 공개 동작 메서드 **54개** = 명세의 54 operations | 실측 |
| Python 실제 호출 | 이 저장소 앱(`backend.main:app`)을 키·DB 없이 `127.0.0.1:8765`에 uvicorn으로 띄우고 `DefaultApi.health_health_get()` 호출 → `{'status': 'ok'}`, 서버 로그 `GET /health status=200` | 실측 |
| Java 컴파일 | JDK 26 `javac`, Jackson 2.17.2(core·annotations·databind·jsr310)와 jakarta.annotation-api 2.1.1을 Maven Central에서 내려받아 클래스패스에 두고 컴파일: 소스 47개 → 클래스 108개, 오류 0 | 실측 |
| 커밋 규칙 | 커밋 메시지·본문의 AI 도구 표기 0건 | 실측 |

### 한계
- Java는 컴파일만 확인했다. 실제 HTTP 호출은 하지 않았다. 컴파일에 쓴 jar는 저장소 밖에 두었고, Maven/Gradle이 없어 `pom.xml` 빌드는 해 보지 않았다(`pom.xml`의 Jackson 버전은 2.21.x, 컴파일은 2.17.2로 함).
- Java 생성기 7.26.0은 `HTTPValidationError.error.details`의 `anyOf`(배열 | 객체)에서 컴파일 안 되는 코드(`List<ValidationError>.class`)를 낸다. 그래서 `generate.sh`가 Java 생성에만 그 한 칸을 자유 형식 객체로 바꾼 임시 명세를 쓴다. 저장소의 명세는 그대로이고, 그 한 칸만 Java SDK에서 타입이 느슨하다. 명세 쪽에서 `details`를 한 가지 모양으로 정하면 이 보정은 필요 없다.
- 모든 API가 `default` 태그라 클래스가 `DefaultApi` 하나고 메서드 이름이 `health_health_get`처럼 길다. 고치려면 `backend/`의 라우트에 `tags`·`operation_id`를 줘야 해서(김승욱 폴더) 이번에는 건드리지 않았다.
- 로그인·CSRF 쿠키 흐름과 `/chat` SSE는 SDK가 자동으로 처리하지 않는다. `mock_erp/python_example/provena_client.py`가 보여 준다. Java 목업은 여전히 없다.
- `mock_erp/`와 `docs/`는 김승욱·팀장 폴더다. 이 변경은 PR로 올려 주인 확인을 받는다. 명세가 바뀌면 SDK도 `generate.sh`로 다시 만들어야 한다(자동 검사는 없다).

## 5. 이미지 크기·compose 기동 시간 로컬 실측 (K-11, S-05)

**로컬 실측** 2026-11-12 (KST), 기준 커밋 `601183c7`(origin/main). 운영 주소·LLM 호출 없음, Dockerfile·docker-compose.yml·.env.example 수정 없음.

### 무엇을 쟀나

1. 저장소 Dockerfile 그대로 `docker build -t provena-local:k11 .` 한 번: 빌드 시간, 이미지 크기, 층별 크기.
2. 이미지 안에 원문(코퍼스)·색인이 두 벌 들어 있는지: `docker run --rm --entrypoint sh`로 큰 파일 경로·크기·sha256 대조.
3. `docker compose -p k11measure up -d --build`를 `.env` 없이(키 없는 데모) 실행해 명령 시작부터 `/health` 200까지 시간. 끝나면 `docker compose -p k11measure down -v`.

### 왜 (놓친 것 목록 행)

- K-11: 비 root 실행·`.dockerignore`는 이미 있음(Dockerfile `USER app`, uid 10001 / `.dockerignore`). 이미지 안에 원문이 두 벌인지는 확인되지 않았던 항목.
- S-05: 조합별 이미지 크기, `docker compose up` 시간, 실제 CPU 응답 시간이 재지 않았던 항목(`docs/embedding_measurement.md` 한계 절). 이번에는 이미지 크기와 compose 기동 시간만 쟀다. CPU 응답 시간은 범위 밖.

### 결과 (로컬 실측)

| 항목 | 값 | 명령·근거 |
|---|---|---|
| 빌드 시간 | 262초 (4분 22초) | `docker build --progress=plain -t provena-local:k11 .` 앞뒤 `date`. 빌드 캐시 2단계 적중(Docker 캐시가 있던 PC) |
| 이미지 크기 | 디스크 1.17GB, 압축 내용 354MB | `docker images`, `docker image inspect`. 층 21개 |
| 큰 층 | pip 설치 404MB, 풀린 색인 130MB, `COPY data/` 106MB, 풀린 코퍼스 22.7MB, 화면(web) 약 15MB, 파이썬 기본 이미지 위 apt·파이썬 41MB 등 | `docker history --no-trunc` |
| 실행 사용자 | uid 10001 `app` (root 아님) | `docker run ... id` |
| compose 명령 | 53.1초 | `up -d --build` 시작부터 종료. 이미지는 위 빌드 캐시로 즉시 만들어짐 |
| compose 첫 `/health` 200 | 67.5초 | 명령 시작부터 폴링(`urllib`, 1초 간격). `db` healthy 후 `loader` 적재(청크 적재 포함) 후 `api` 시작 |
| compose가 만든 이미지 | `api`·`loader` 둘 다 같은 Dockerfile, 각 1.17GB로 표시 | 층을 공유해 실제 추가 디스크는 한 벌분 |
| DB 이미지 | `pgvector/pgvector:pg16` 621MB(디스크 표시) | `docker images` |

#### 원문 두 벌인가 (K-11)

판정: **같은 내용이 압축본과 풀린 본, 두 형태로 이미지에 들어 있다. 같은 형태 두 벌은 아니다.**

| 경로 | 크기 | 설명 |
|---|---|---|
| `/app/data/index.tar.gz` | 94.5MB | 색인 압축본(커밋된 원본 그대로) |
| `/app/data/index/` | 124MB (벡터 92MB, chunks.jsonl 32.5MB) | 빌드 중 `snapshot unpack-index`로 풀린 본 |
| `/app/data/corpus.tar.gz` | 4.6MB | 원문 스냅샷 압축본 |
| `/app/data/corpus/` | 22MB (handbook 18.7MB, history 2.6MB, pages.jsonl 0.8MB) | 빌드 중 `snapshot unpack`으로 풀린 본 |
| `/app/data/chunks_index.jsonl` | 5.0MB | 청크 메타(본문 없음, 글자 수만) |

- 압축본 두 개 합계 약 99MB가 풀린 본(약 146MB)과 겹친다. 이미지 1.17GB의 약 8%.
- `index/chunks.jsonl`(32.5MB)은 청크 본문 텍스트이고 `corpus/`(22MB)는 마크다운 원문이라, 원문 텍스트가 가공된 형태로 한 번 더 있다. sha256은 파일마다 달라(`chunks_index.jsonl` 25177ae7…, `index/chunks.jsonl` 86e6c26c…, `pages.jsonl` 80f9c2b7…) 바이트 단위로 같은 파일은 없다.
- 압축본을 지우지 못하는 이유(코드·문서 근거): compose의 `loader`가 호스트 `./data/index`를 연결하고, 그 폴더가 비어 있으면 이미지 안의 `data/index.tar.gz`를 다시 푼다(`docker-compose.yml` loader 주석, `Dockerfile` unpack-index 주석). 그래서 압축본 제거는 이 흐름을 바꾸는 일이라 이번에 하지 않았다.
- 층 관점: `COPY data/`(106MB)에 압축본이 들어가고 `RUN unpack`, `RUN unpack-index` 층(22.7MB, 130MB)이 따로 쌓여 압축본과 풀린 본이 각각 다른 층에 있다.

#### 조합별 이미지 크기 (S-05)

- 측정한 것은 **기본 조합 하나**(voyage-4 API, 로컬 모델 없음, `SEARCH_EMBED_MODEL`·`SEARCH_RERANK_MODEL` 빈 값)뿐이다. 1.17GB.
- 로컬 임베딩·리랭커 조합은 `--build-arg`로 `requirements-local-models.txt`(torch CPU판 등)와 모델을 받아야 해 이번에 만들지 않았다. 값 없음(미측정).

### 한계

- 조합별 이미지 크기는 기본 조합만 쟀다. 로컬 모델 조합(torch·sentence-transformers·모델 파일)은 빌드하지 않았다. 디스크 여유가 빌드 후 약 5GB로 줄어 추가 빌드를 하지 않았다.
- 빌드 시간은 Docker 빌드 캐시(2단계 적중)가 있는 PC 값이다. 완전히 새 PC의 첫 빌드(npm ci, pip 다운로드 전부)는 더 걸릴 수 있다.
- compose 시간은 이미지가 이미 빌드된 상태에서 쟀다(compose의 `--build`는 캐시 적중). 새 PC에서는 첫 빌드 시간이 더해진다. 같은 PC에서 한 번만 쟀다(반복 평균 아님).
- 실제 CPU 응답 시간은 재지 않았다(범위 밖).
- 이 PC에서 다른 컨테이너·작업이 동시에 Docker를 쓰고 있었다. 시간에 영향이 있을 수 있다.
- 정리: 내가 만든 이미지 3개(`provena-local:k11`, `k11measure-api`, `k11measure-loader`)와 compose 프로젝트(`k11measure`, 볼륨 포함)는 삭제했다. 빌드 캐시는 다른 작업과 섞여 있어 지우지 않았다.

## 6. 주말 동결 제안(K-15)과 ACL 알려진 한계 기록 (J-01 J-02 J-03 L-09 O-16)
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `601183c7` 위 브랜치 `gap3-docs2`
- 문서만 바꿨다. 코드, workflow, `.env.example`, `docker-compose.yml`, `backend/schemas/`는 건드리지 않았다. 배포·운영 DB·LLM·Voyage 호출 없음.

### 무엇을
| 번호 | 바꾼 곳 | 내용 |
|---|---|---|
| K-15 (I-06, P-09, F-08 관련) | `docs/decisions.md` 결정 표 2026-11-12 행 중 4번째(#132 결정 3행 다음) | "(제안, 조장 승인 대기)" 주말 11/14~15와 동결(11/16 24:00) 뒤: 새 자동 실행·배포 없음, `handbook-sync`는 `disabled_manually` 유지, 동결 뒤 코드 변경 없음 |
| K-15 | `docs/TEAM_GUIDE.md` 일정 표 11/14~15 행 | `handbook-sync`는 꺼 둔 채 둔다는 제안과 `decisions.md` 가리킴 |
| J-01, J-02, J-03, L-09, O-16 | `EVAL_REPORT.md` 6장 "아직 막지 못한 것" (7) | 문서 권한 검색 전 거르기를 동결 전에 만들지 않는 알려진 한계 |
| 같은 번호 | `docs/SDD.md` 문서 권한(F-06) 줄 | "미구현 부분" 문장 끝에 2026-11-11 진형 결정과 EVAL_REPORT 6장 연결 |

### 왜 (근거)
- [문서] 주말 자동 실행·배포 금지: `docs/PRD.md:378`, `docs/TEAM_GUIDE.md:32`, 동결 `TEAM_GUIDE.md:33`, 가이드 p.5(조장 목록 K-15 행).
- [코드] workflow 상태: `.github/workflows/handbook-sync.yml:9` 정시 `cron "7 18 * * *"`(켜면 매일 한국 03:07, 운영 DB와 Voyage 사용, 파일 머리 주석 `:3-4`). `disabled_manually`는 조장 목록 K-15·F-08 행과 `docs/specs/incremental.md:111`.
- [문서] 정시 실행 3회 실패·원인 미확인, 결제 한도로 러너 미기동: `docs/specs/incremental.md:112-113`.
- [코드] ACL: `backend/graph/recall/acl.py:6`("그룹을 채우는 정책 파일과 검색 단계 거르기는 검색 파트 몫"), `backend/rag/retrieve/search.py`에 `acl`·`allowed_groups` 0건(grep), `SDD.md:235`가 이미 미구현이라고 적음.
- [결정] 진형 2026-11-11: 검색 결과와 평가 점수가 바뀌므로 동결 전에 검색 전 ACL 거르기를 만들지 않는다.

### 확인한 것
- `.github/workflows/`는 `ci.yml`, `handbook-sync.yml`, `secret-scan.yml` 3개, 주말에 도는 다른 정시 실행은 없음(`schedule:`은 handbook-sync에만, grep).
- `handbook-sync`를 언급하는 문서: `SDD.md:318`, `TEAM_GUIDE.md:114`, `specs/incremental.md:107-113`, `specs/mcp.md:84`. 이번에 바꾼 곳과 모순 없음.
- 일정이 주말을 적은 곳은 `PRD.md:378`과 `TEAM_GUIDE.md:32`뿐이다. PRD는 가이드 문구 그대로라 두고 `TEAM_GUIDE.md`만 고쳤다.
- 줄 번호 인용은 이 브랜치 파일에서 직접 다시 읽어 확인했다.

### 한계
- K-15는 제안이다. 조장이 승인하기 전에는 확정이 아니다. 조장 목록의 "다시 켜기 전, 늦어도 11/13(금)" 기한이 남아 있다.
- `disabled_manually` 상태는 GitHub 설정이라 저장소에서 확인되지 않고 조장 목록(11/11 `gh run list`)을 따랐다. 오늘 상태는 다시 보지 않았다.
- ACL은 기록만 했다. 문서 권한이 필요한 청크가 생기면 검색·인용에 그대로 나온다(지금 코퍼스 `acl`은 전부 비어 있어 영향 없음). 사용자 그룹을 채우는 로그인 경로(J-02)와 정책 파일(J-03)도 열려 있다.
- 11/17 제출 문서(실패 사례 분석 등)는 동결(코드) 뒤에도 가이드 일정대로 낼 수 있다고 보았다. 이 해석은 조장 확인이 필요하다.

## 7. L-24 확인하지 못한 경로 로컬 실행
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 머지: 아직 안 함 / 기준: `origin/main` `601183c7`, 브랜치 `gap3-l24`

### 무엇을
- 2026-11-11 브라우저 E2E·API 점검이 확인하지 못한 11개 경로(브라우저 4, API 7)를 로컬 서버에서 실제로 돌려 결과를 적었다.
- `README.md` "키 없이 뜨는 데모 모드"의 L-24 항목에서 "확인한 결과가 없다"를 경로별 "로컬 확인(2026-11-12)"으로 바꿨다(조장 파일이라 그 항목 끝 문장만 고침).
- 코드는 고치지 않았다. 실행한 52행의 표는 이 문서 맨 아래 "로컬 실행 표"에 있다(통과 44, 실패 0, 못 함 4, 참고 4).

### 왜
- 조장 목록 L-24는 "두 점검이 실행하지 못한 경로를 동작한다고 적을 수 없다"는 확인 공백이다. 키 없이 로컬에서 돌릴 수 있는 경로는 돌려서 공백을 줄이고, 못 돌리는 경로는 이유와 함께 미확인으로 남기려는 것이다.

### 확인한 것(로컬)
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

### 한계
- 합동 검토 쟁점표와 SSE 이벤트는 모델·검색기를 `tests/`의 합성 가짜로 바꾼 서버로만 확인했다. 실제 LLM이 만든 초안·쟁점표·판정 문장은 확인하지 못했다.
- 리콜 알림은 규칙 판정과 합성 개정 사건으로 만들었다. DB 색인에는 같은 쪽의 다른 판이 없어 '수정' 사건은 알림 0건이라 '삭제' 사건을 썼다.
- 만료는 대기 방식이 아니라 유효 시간 단축이다. 쿠키 `Secure`는 비로컬 모드 로컬 서버에서만 봤다.
- 되묻기 뒤 후속 메시지가 앞 질문을 이어받지 않는 것이 설계인지는 조장 판단이다(코드에 이어받는 곳은 없음).
- 시험이 끝난 뒤 임시 DB `app_l24`와 서버는 지웠고 worktree의 `node_modules` junction도 풀었다.

### 로컬 실행 표
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

#### 못 한 것과 이유

| 경로 | 이유 |
|---|---|
| 결정표 변환의 실제 LLM 초안 | LLM 키가 필요하다. 키 없는 데모는 예시 응답만 낸다 |
| 실제 LLM 경로의 SSE `approval_request`·`error` | 질문 분류가 LLM 호출이라 키 없는 데모는 합동 검토로 들어가지 못한다(검토 요청 문장 3개 모두 검색 단계 거절). 이벤트 모양은 스텁 서버로만 확인 |
| 실제 LLM 판정의 리콜 알림 | 규칙 판정으로만 확인(LLM 판정 문장은 확인하지 못함) |
| Google 실제 동의·토큰 교환 | 외부 Google 서버와 계정이 필요 |
| 배포 쿠키 `Secure`의 실제 응답 | 운영 주소 호출 금지. 비로컬 모드 로컬 서버에서만 확인 |
| 30분 실제 대기 만료 | 유효 시간만 6초로 줄여 만료 경로 확인(대기 방식은 아님) |

#### 참고로 남기는 관찰(고치지 않음)

- 화면(dist)을 빌드하지 않은 서버는 `/login`·`/chat` 같은 화면 주소와 `/favicon.ico`가 영어 `Not Found` JSON 404다(옛 화면 폴더로 떨어지는 경로). `Dockerfile`이 `npm run build` 결과를 이미지에 넣으므로(5~8, 48줄) 빌드 없이 서버만 띄운 개발 상태 한정이다.
- 되묻기 뒤 후속 메시지는 앞 질문을 이어받지 않고 새 질문으로 처리된다. 설계인지는 조장 판단이다.
