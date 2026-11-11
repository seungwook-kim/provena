# 놓친 것 목록 묶음 4: 시험 공백·변이 확인·측정 코드
- 작업자: 박진형 (jinyeong-731) / 머지: 아직 안 함 / 기준: `origin/main` `d6e658ac`(PR #131 머지 뒤), 브랜치 `fix-b4-tests`
- 이 문서의 시험·변이 값은 모두 **로컬**(DB·키·네트워크·Docker 없음, 가짜 모델)이다. 배포에서 확인한 것은 없다.
- 번호 주의: 목록 파일(놓친 것 목록 2026-11-11)의 행은 변이 확인 = L-10, 근거 비워도 답하는지 = S-03, 질의 하나 빼기·인용 없는 답 분모 = S-04, bge int8 캐시 = S-07이다. 아래는 목록 행 기준으로 적었다.

## 먼저 확인한 것: main이 이미 해결한 부분
| 항목 | 판정 | 근거 |
|---|---|---|
| L-08 채팅 HTTP 오류 프런트 시험 | 이미 해결 | 코드: `web/react-app/src/lib/chat-service.test.js:218-` `createApiChatAdapter HTTP errors (H-08)`(409·503 거절, 스트림 끊김, 오류 이벤트). 새로 안 만듦 |
| L-08 하루 요약 계약 시험 | 일부 | 코드: `tests/test_recall_alert_fatigue.py:124` 한 건(정렬·id 안정)뿐. 칸 관계 시험은 없어 추가 |
| L-08 영향 미리보기 시험 | 일부 | 코드: `tests/test_api_recalls.py:378-403`은 HTTP 겉(드라이런·400)만. `changes_from_pages`·`preview_impact` 직접 시험은 없어 추가 |
| L-08 번들+백엔드 한 바퀴 | 일부 | 코드: 가입 승인(`test_signup_admin_api.py:41`)·프로필(`test_profile_api.py`)·채팅(`test_api_*`)이 따로 있고 한 앱에서 이어 부르는 시험은 없음 |
| L-10 변이 | 미해결 | 문서: `docs/GATES.md` 변이 표가 17번(11/5)까지, 목록 L-10 행 "D5 이후 코드 변이 행 없음" |
| S-03 근거 비움 | 미해결 | 코드: `tests/`에서 검색 결과가 빈 채 판정이 "충분"이라 답하는 경우를 막는 시험 없음(`grep` 기준, 추정은 아님) |
| S-04 | 미해결 | 코드: `evals/`에 인용 없는 답 분모 계산 파일 없음 |
| S-07 bge int8 | 미해결 | 코드: 병합 전 `evals/retrieval/experiment_v1.py` `_Scores.score`가 int8도 저장 값을 씀. 문서: `docs/embedding_measurement.md:361` "수정안은 `experiment_v1.py`에 반영하지 않았다" |

## L-08 시험 공백
### 무엇을 바꿨나
- `tests/test_digest_contract.py`(4개): 하루 요약의 건수 합·중요도·`conclusion_changed`·설명 길이·id 순서 무관.
- `tests/test_impact_preview_contract.py`(9개): `changes_from_pages`의 수정·추가·삭제 분류와 서식만 바뀐 섹션 제외, `preview_impact` 요약 숫자 관계, 답 저장소 불변, 마크다운에 사용자 id 없음·출처 문구 있음.
- `tests/test_round_trip_app.py`(2개): 실제 `create_app` 한 개에 가입 대기 → 승인 전 로그인 거절 → 소유자 승인 → 로그인 → `/chat` → `/threads`, 그리고 거절된 사용자는 로그인 불가·익명 `/chat` 401.
### 왜
- 목록 L-08 행의 "남음" 목록(하루 요약·영향 미리보기 diff 계약, 번들+백엔드 한 바퀴, 채팅 HTTP 오류). 근거 종류: 문서(목록 행)·코드.
### 확인한 것 (로컬)
- 새 시험 통과: digest 4, impact 9, round trip 2.
- 변이(`tests/mutation_d5.py`): 26 요약 중요도 고정 → 1 실패, 27 `any`→`all` → 1, 28 `answers_checked=0` → 1, 29 출처 문구 제거 → 1, 30 옛 본문 모음 조건 → 2, 32 거절도 계정 생성 → 1, 33 승인해도 계정 없음 → 1.
### 한계
- 내 정보(`/me/profile`)는 DB 없이 조립한 앱에 열리지 않아(`backend/main.py` `profile_store`) 한 바퀴에 못 넣었다(시험은 `test_profile_api.py`가 따로 봄).
- 만들어진 화면 번들은 서빙하지 않았다(빌드에 npm 필요). Google 시작 화면·긴 SSE 시험은 이 묶음에서 만들지 않았다.
- 승인은 `MemoryAuthStore`라 Postgres 경로는 `test_signup_postgres_integration.py`(DB 필요)가 맡는다.

## L-10 변이 확인 (+ S-03·S-04 시험의 변이)
### 무엇을 바꿨나
- `tests/mutation_d5.py`: 변이 18~33번. 변이마다 원본을 임시 보관하고 `try/finally`로 복구, 복구 뒤 바이트 비교. `timeout`으로 감싸지 않음. 변이 전 통과·변이 뒤 실패 수를 출력.
- `tests/test_values_backed.py`(3개): `grounding.values_backed`(값이 표시한 청크에 없으면 False).
- `docs/GATES.md` 변이 표에 18~33번(16행) 추가. G7 행은 안 건드림.
### 왜
- 목록 L-10 행: D5 이후 코드(멀티, 승인 재개, 판정 단계)에 변이 행 없음. 대상 줄은 직접 열어 고름: `backend/graph/decision/execute.py`(승인 재개 조건), `backend/graph/multi.py`(writer 다음 단계, 재조사 한도), `backend/graph/grounding.py`(`values_backed`, 기간 미포함, 전부 지움).
### 확인한 것 (로컬, 변이 전 통과 → 변이 뒤 실패 수)
| 번호 | 변이 | 변이 뒤 실패 |
|---|---|---|
| 18 | 승인 재개 조건 `False` | 3 (52개 중) |
| 19 | multi writer→end | 118 (650개 중) |
| 20 | multi 재조사 한도 항상 참 | 20 |
| 21 | values_backed 검사 건너뜀 | 1 (`test_values_backed.py` 단독) |
| 22 | 기간 미포함 거절 건너뜀 | 3 |
| 23 | 전부 지움 거절 건너뜀 | 1 |
- 실행 뒤 변이 문자열을 `grep`해 남은 것 0건, `git status`의 추적 파일 변경은 의도한 것만.
### 한계
- 18~23번은 기존 시험이 잡은 것이라 시험을 새로 만들지 않았고, 21번만 시험(`test_values_backed.py`)을 보강했다.
- 변이는 줄 하나씩이라 같은 함수의 다른 줄은 보장하지 않는다. 목록의 "3건"은 넘겼지만 전체 코드 변이 점수는 아니다.

## S-03 근거를 비운 입력 회귀 시험
### 무엇을 바꿨나
- `tests/test_empty_evidence.py`(6개): 검색이 빈 목록을 돌려주고 판정 모델이 "충분"이라 답하며 가짜 인용·무인용·평문 답을 지어내도 단일·멀티 그래프 모두 `kind != "answer"`, 인용 없음, 지어낸 값(15분)이 응답에 없음, 판정·답 작성 모델 호출 0회, 답 저장소 비어 있음.
### 왜
- 목록 S-03 행(강의 3주 02). 막는 곳: `backend/graph/build.py`의 `if not chunks:`(자료가 없으면 LLM에 묻지 않고 부족으로 봄). 근거: 코드.
### 확인한 것 (로컬)
- 통과 6개. 변이 24번(`if not chunks:`→`if False:`) 뒤 6개 모두 실패.
### 한계
- 가짜 모델 시험이다. 실제 모델이 빈 근거에서 어떻게 답하는지는 보지 않았다(LLM 호출 금지).

## S-04 인용 없는 답 분모 + 질의 하나 빼기
### 무엇을 바꿨나
- `evals/uncited_answers.py`: 저장된 `rows.jsonl`만 읽어 전체·답·인용 없는 답·답 기준 비율·전체 기준 비율·하위 질문 둘 이상 문항 수를 낸다. 답이 0이면 비율을 정하지 않음(0 나눗셈 없음).
- `tests/test_uncited_and_drop_one.py`(5개): 분모 계산, 답 0건, 저장된 `agent_v1_final_cite`는 인용 없는 답 0건, `merge_by_score`에서 하위 질문 하나를 빼도 1등이 그대로인지(대조 시험 포함).
### 왜
- 목록 S-04 행(강의 1주 13, 1주 01). 근거: 문서(목록)·코드(`backend/rag/retrieve/search.py:483` `merge_by_score`).
### 확인한 것 (로컬)
- 실행 결과(실측, 저장된 결과): `agent_v1_final_cite` 전체 30·답 13·인용 없는 답 0, `agent_v1_fix2_pg` 30·15·0, `agent_v1_service_pg` 30·15·0. 시험 통과 5개. 변이 25번(`lists[1:]`→`lists[2:]`) 뒤 2개 실패.
### 한계
- 저장된 결과에는 하위 질문을 합친 뒤 목록(`retrieved`)만 있고 하위 질문별 목록이 없어서, **실제 결과로 "하나 빼고 다시 계산"은 못 한다**. 하나 빼기 시험은 `merge_by_score`에 만든 목록을 넣은 것이다.
- 비율 0은 이 평가셋 30건에서 답 13~15건의 값이다. 모집단 전체 주장은 아니다.

## S-07·L-04 bge int8 점수 캐시 (I-013)
### 무엇을 바꿨나
- 판정: main은 해결 안 함. `evals/retrieval/experiment_v1.py`의 `_Scores.score`가 int8일 때 저장 값을 읽지도 쓰지도 않고 후보 전체를 한 번에 계산하게 함(서비스 방식과 같음). 다른 리랭커는 그대로 저장 값 재사용.
- `tests/test_exp_int8_scores.py`(3개), `docs/embedding_measurement.md` 한계 문장 정정(수정안 중 int8 부분 반영, v1 값은 다시 재지 않음).
### 왜
- 목록 S-07 행. 근거: 문서 `docs/embedding_measurement.md:326`(묶음에 따라 점수가 달라짐), `:361`(반영 안 함), `backend/rag/retrieve/retrieve.md:37` I-013 상태 "열림". 확정 조합이 리랭커 없음이라 서비스 영향 없음은 목록의 판단이다.
- 지시서의 "L-04"는 이 항목을 가리킨 것으로 보고 처리했다. 목록의 L-04 행(`exclusions.json`, 재현 명령)은 따로 보지 않았다.
### 확인한 것 (로컬)
- 시험 3개 통과, 변이 31번(int8 분기 끔) 뒤 2개 실패.
### 한계
- 이미 낸 v1 418조합의 int8 값은 다시 재지 않았다(재측정은 모델 실행이 필요). `retrieve.md` I-013 상태 칸은 담당(김승욱)이 닫을 항목이라 바꾸지 않았다.
