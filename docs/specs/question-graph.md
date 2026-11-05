# Spec — 질문 그래프: 근거 답변 (김승욱, F-01 · G4)

> 초안(2026-10-29). D0(10/30)에서 계약과 숫자 기준이 정해지면 고친다. 설계 원문은 `docs/SDD.md` 4-3장, 숫자 기준은 `docs/PRD.md` 13-2장.

## Why

- **페르소나**: 장애 대응, 배포, 보안 검토 중인 개발자와 SRE·DevOps (`docs/TOPIC.md` 1절)
- **상황**: 런북과 엔지니어링 정책을 보고 절차, 담당, 기한을 정해야 한다. 핸드북은 영어이고 고른 절만 1,564쪽이다.
- **문제**:
  1. 범용 챗봇은 근거 섹션과 그 섹션의 판 날짜를 주지 않는다.
  2. 근거가 없을 때도 그럴듯하게 답한다("거의 맞는 답" 불만 66%, `docs/TOPIC.md` 근거 5).
  3. 핸드북은 매일 바뀌는데 답이 어느 판 기준인지 알 수 없다.
- **측정 지표**: 인용 정확도, 판 날짜 표시율, 비관련 질문 거절률, 응답 시간

## Goal

- **해결 목표**: 한국어 정책 질문에 핸드북 섹션을 인용한 한국어 답을 판 날짜, 출처 URL과 함께 준다. 근거가 부족하면 되묻거나 거절한다.
- **성공 기준** (`docs/PRD.md` 13-2, D0에 동결 전 초안):
  - 인용 정확도 0.85 이상
  - 판 날짜 표시 100%
  - 비관련 질문 거절 0.90 이상
  - 응답 시간 전체 p95 10초 이하
  - 인용 검사를 통과하지 못한 인용이 답에 0건
  - 재검색 최대 2회
- **Out of Scope**:
  - 결정표 실행과 승인(별도 Spec `decision-approval.md`)
  - 팀 합동 검토 F-03(별도 Spec `team-review.md`)
  - 답변 리콜 F-02(별도 Spec `recall.md`)
  - 사용자별 장기 기억 Store(별도 Spec `memory.md`). 이 Spec은 `thread_id`만 쓴다
  - 검색 내부(파싱, 청킹, 하이브리드 검색, 리랭킹은 `backend/rag/`)
  - 화면

## What

**Happy Path**
1. 사용자가 `/chat`에 질문을 보낸다. `thread_id`는 로그인한 사용자 id에 묶인다.
2. 질문 종류를 나눈다: 정책 질문 / 결정표 질문 / 합동 검토. 이 Spec은 정책 질문만 다룬다.
3. 질의 재작성: 한국어 질문을 핸드북 영어 용어 검색어로 바꾸고, 절과 기준일(`as_of`) 조건을 뽑는다.
4. 검색: `SearchQuery` → `list[Chunk]` (`backend/schemas/`)
5. 근거 충분 판정. 부족하면 3으로 돌아간다(최대 2회).
6. 답 작성: 문장마다 `[n]` 인용을 붙이고, 판 날짜, 출처 URL, CC BY-SA 4.0을 표시한다.
7. 인용 검사(코드, LLM 없음): 인용한 `chunk_id`가 이번 검색 결과에 있고 `version_id`가 맞는지 본다. 맞지 않는 인용은 지우고, 남은 근거가 없으면 거절한다.
8. 답과 인용을 저장한다(리콜이 쓰는 인용 기록). `AgentEvent`(token, citation, done)로 흘려보낸다.

**단일 대 멀티** (`backend/graph/build.py` 권장 순서)
- D4(11/5) 단일: 한 그래프가 3~8을 차례로 한다. 이 점수가 기준이다.
- D5(11/6) 멀티: Supervisor가 검색, 작성, 검증 하위 에이전트를 불러 같은 일을 나눠 한다. 같은 평가셋으로 다시 재고, 차이는 문항 목록과 함께 `EVAL_REPORT.md` 4장에 적는다. 나아지지 않았으면 그대로 적는다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 재검색 2회 뒤에도 근거 부족 | 절이나 기간이 빠진 질문이면 되묻고, 아니면 거절 사유와 함께 거절한다 |
| EC-02 | 비관련 질문 4종(도메인 밖, 코퍼스에 없는 대상, 없는 항목, 기간이 다른 질문) | 거절. 어디서 거를지(검색 단계 / 답 단계)는 D0 안건. 답 단계에서 거르면 `docs/GATES.md` G5 규칙대로 그 효과를 따로 보고한다 |
| EC-03 | LLM이 검색 결과에 없는 `chunk_id`를 인용 | 인용 검사에서 지운다 |
| EC-04 | 질문에 기준일이 있음("2024년 기준") | `as_of`로 검색하고, 답에 그 판의 날짜를 표시한다 |
| EC-05 | 근거 충분 판정을 점수 하나로만 함 | 대상과 기간이 질문과 맞는지 보는 결정적 검사를 따로 둔다(`build.py` 주석의 DART 실패 사례) |
| EC-06 | LLM 응답 형식이 깨짐 | 1회 다시 요청한다. 그래도 깨지면 error 이벤트 없이 처리한다: 질문 종류는 정책 질문, 문서 채점은 근거 부족으로 본다. 답 작성은 인용 검사에서 거절한다. 근거 판정 LLM은 결론 없음으로 보고 코드 규칙 결과를 따른다(2026-11-02 변경, `docs/decisions.md`) |
| EC-07 | 키 없음(`DEMO_MODE=1`) | 기록해 둔 응답을 재생한다. 오류 없이 done 이벤트까지 간다(G2) |
| EC-08 | 검색 결과 본문 안의 지시문(간접 인젝션) | 본문은 데이터로만 다루고 지시로 따르지 않는다. 시험은 `evals/safety/` |
| EC-09 | 비용 상한 도달 | 멈추고 error 이벤트를 보낸다 |
| EC-10 | 질문 종류가 결정표나 합동 검토인데 해당 경로가 아직 없음 | 분류 결과는 남기고 정책 질문 경로로 처리한다(2026-11-02, `docs/decisions.md`) |

## How

- **파일**: `backend/graph/build.py`(조립), `backend/graph/state.py`(상태), `backend/prompts/`(프롬프트). LLM 호출은 `backend/services/llm.py` 한 곳으로만 한다(`docs/SCAFFOLD.md`).
- **조립 함수**: `build_graph(retriever=None, checkpointer=None)`. 검색기와 체크포인터를 주입받아, 검색 파트가 늦어도 가짜 검색기와 메모리 체크포인터로 키 없이 시험한다. 검색 호출 수를 셀 수 있어야 한다.
- **계약**: 입력 `SearchQuery`, `Chunk`, 출력 `AgentEvent` (`backend/schemas/`, `docs/SDD.md` 6장. D0에 동결)
- **체크포인터**: Postgres. 같은 `thread_id`로 재개된다.
- **상한**: 재검색 횟수는 상수 하나(2). 한 질문의 LLM 비용 상한은 환경변수로 둔다.
- **환경변수**: `.env.example`의 LLM 키, `DEMO_MODE`, `DATABASE_URL`, `LANGFUSE_*`. 새로 쓰는 변수는 `docs/ARCHITECTURE.md` 조원 간 계약서에 적는다.
- **런타임 Skill**: `citation-rules`(답 작성), `grounding-check`(인용 검사), `glossary`(질의 재작성) (`docs/SDD.md` 2-3장)

## AC (Given-When-Then)

**AC-01 · 인용과 판 날짜**
- GIVEN: 정답 섹션이 코퍼스에 있는 관련 질문
- WHEN: 그래프 실행
- THEN: 답의 문장마다 `[n]` 인용이 있고, 모든 인용에 판 날짜와 출처 URL이 있음

**AC-02 · 가짜 인용 제거**
- GIVEN: LLM이 검색 결과에 없는 `chunk_id`를 인용한 답
- WHEN: 인용 검사
- THEN: 그 인용이 최종 답에 없음

**AC-03 · 재검색 상한**
- GIVEN: 근거 부족 판정이 계속 나오는 가짜 검색기
- WHEN: 그래프 실행
- THEN: 검색이 정확히 3번(처음 1번 + 재검색 2번) 호출되고 되묻기나 거절로 끝남. 시험은 상수가 아니라 리터럴 3과 비교한다

**AC-04 · 비관련 질문 거절**
- GIVEN: 도메인 밖 질문(예: 사내 연봉 협상 방법)
- WHEN: 그래프 실행
- THEN: 거절 사유가 있고 인용은 0개

**AC-05 · 기준일**
- GIVEN: `as_of`가 있는 질문
- WHEN: 그래프 실행
- THEN: 모든 인용의 판 날짜가 `as_of`보다 늦지 않음

**AC-06 · 키 없이 동작**
- GIVEN: `DEMO_MODE=1`, LLM 키 없음
- WHEN: 질문 1건
- THEN: 오류 없이 done 이벤트까지 감

**AC-07 · 단일 대 멀티**
- GIVEN: 같은 평가셋
- WHEN: 단일 경로와 멀티 경로를 각각 실행
- THEN: 두 결과 파일이 남고, `EVAL_REPORT.md` 4장에 문항별 차이가 적힘

## 구현 상태 (2026-11-02)

단일 에이전트 그래프 v1을 구현했습니다. Supervisor와 서브에이전트, 사람 승인, Postgres 체크포인터는 D5 범위라 넣지 않았습니다.

| 노드 | 하는 일 | 파일 |
|---|---|---|
| `load_memory` | 사용자 프로필 읽기 | `backend/graph/build.py`, `backend/memory/profile.py` |
| `classify` | 질의 라우팅 | `backend/graph/build.py` |
| `rewrite` | 질의 재작성(영어 검색어) | `backend/graph/build.py` |
| `search` | `search()` 호출 | `backend/graph/build.py` |
| `judge`, `give_up` | 문서 채점, 재검색 2회 뒤 되묻기나 거절 | `backend/graph/build.py` |
| `write_answer` | 답 작성, 기준일과 판 날짜, 라이선스 표시 | `backend/graph/build.py`, `backend/graph/citations.py` |
| `verify` | 인용 검사(코드) | `backend/graph/citations.py` |
| `ground` | 근거 판정 | `backend/graph/grounding.py` |
| `save` | 답과 인용 저장(지금은 메모리 구현, DB 표는 B-05) | `backend/graph/answer_store.py` |

- 프롬프트는 `backend/prompts/question.py`, 런타임 Skill은 `skills/`의 `citation-rules`, `grounding-check`, `glossary`입니다.
- 비관련 질문(EC-02)은 답 단계에서 거릅니다.
- 평가 실행기는 `python -m evals.agent.run_eval`입니다.
- 단일 기준 점수는 v1 30건으로 2026-11-05에 3회 쟀습니다(`EVAL_REPORT.md` 3장 3-3). 이 조합의 v2 50건 측정은 D5에 합니다.

## 수정 이력 (2026-11-05)

측정 결과를 본 뒤 단일 에이전트 그래프에 다음 수정을 넣었습니다. 각 수정은 `evals/PREREGISTER.md`에 기대를 먼저 적고 한 번에 하나씩 넣었습니다. 통과선은 인용 정확도 0.85, 정답 근거 인용률 0.85, 비관련 거절 0.90입니다.

| 수정 | 바꾼 곳 | 사전 등록 |
|---|---|---|
| 재검색 결과 합치기 | `backend/graph/build.py` `search` 노드, `MAX_CHUNKS` 10 | #12 |
| 되묻기 제한 | `JUDGE_SYSTEM`, `clarify_has_number` | #13 |
| 도메인 밖 라우팅 | `classify`의 `out_of_domain` 경로 | #14 |
| 인용 범위 | `ANSWER_SYSTEM`, `select_citations`, `MAX_CITATIONS` 4 | #17 |
| 근거 판정의 부분 제거 | `GROUNDING_SYSTEM`, `grounding.prune_answer`, `ground` 노드 | #18 |
| 요청 기간 자료 없음은 거절 | `grounding.period_missing`, 답 JSON의 `period_covered` | #19 |
| 기준일 | `rewrite`의 `mentions_period`, 평가 실행기 `_as_of` | #20 |
| 질문 분해의 그래프 연결 | `backend/graph/decompose.py`, `search` 노드 | #21 |

**인용 범위 (AC-08)**
- GIVEN: 답이 본문에서 청크 5개를 인용하고 검색 결과에는 더 많은 청크가 있다
- WHEN: `verify`가 인용을 정리한다
- THEN: 본문에 표시가 있는 청크만 처음 나온 순서로 최대 4개(`MAX_CITATIONS`)를 인용으로 남기고, 잘린 청크의 표시는 본문에서 지운다. 잘린 청크는 `trimmed_citations`에 기록하며 가짜 인용으로 세지 않는다

**근거 판정의 부분 제거 (AC-09)**
- GIVEN: 판정 LLM이 `unsupported`(근거 없는 주장)로 판정하고 받쳐지지 않는 문장을 원문 그대로 돌려준다
- WHEN: `ground`가 `prune_answer`로 그 문장을 뺀다
- THEN: 남은 답이 인용 검사, 내부 표현 누출 검사, 코드 근거 규칙, 판정 LLM 재판정을 모두 통과하면 남은 답을 내고, 하나라도 통과하지 못하면 원래 판정대로 답 전체를 거절한다. 문장의 절반을 넘게 빼야 하거나 문장이 답과 일치하지 않거나 모두 빠지면 거절한다. 두 번째 제거는 하지 않는다. `unsupported` 외의 사유(수치 불일치 등)는 부분 제거 없이 거절한다

**요청 기간 자료 없음은 거절 (AC-10)**
- GIVEN: 질문에 연도나 월 표현이 있고, 답이 `period_covered`를 false로 하거나 질문의 기간 표현과 "없다" 계열 표현을 한 문장에 함께 쓴다
- WHEN: `verify`가 `period_missing`을 검사한다
- THEN: 가까운 기간의 값을 인용했더라도 답 단계 거절(`out_of_period`)로 끝낸다. 질문에 기간 표현이 없으면 이 규칙은 돌지 않는다

**기준일 (AC-11)**
- GIVEN: 사용자가 기준일을 주지 않았고, 질문에 시점 표현이 없다
- WHEN: `rewrite`가 기준일을 돌려준다
- THEN: 그 기준일은 버리고 오늘 날짜를 쓴다. 평가 실행기는 `YYYY-MM` 형태의 평가 기준일을 그 달의 마지막 날로 바꿔 넘긴다

## 질문 분해의 그래프 연결 (4단계 `search` 노드)

질문 분해(LLM)는 검색이 아니라 그래프의 `search` 노드가 첫 검색 전에 한 번 합니다. `SearchQuery.sub_queries`(PR #48)에 결과를 넣어 검색에 넘기고, 검색은 분해를 하지 않습니다.

| 항목 | 규칙 |
|---|---|
| 입력 | 사용자가 쓴 한국어 원 질문(재작성한 영어 검색어가 아니다) |
| 프롬프트와 응답 읽기 | `evals/retrieval/exp_decompose_v1.py`와 같은 본문(`decompose.SYSTEM`)과 같은 JSON 읽기 규칙. 시험이 두 코드의 본문 일치를 확인한다 |
| 측정 코드와 다른 점 | ① 프롬프트 맨 앞에 노드 표지(`[[task:decompose]]`)를 붙인다. ② 응답이 깨지면 1회만 다시 묻는다(최대 2번, 측정은 최대 3번). ③ 하위 질문이 1000자를 넘으면 나누지 않은 것으로 본다(검색의 `check_query` 규칙) |
| 넘기는 값 | 하위 질문 2~3개이면 `sub_queries`로 넘긴다. 1개이거나 규칙을 어기면 넘기지 않는다(`None`). 4개 이상이면 앞 3개만 쓴다 |
| k | 검색마다 `DEFAULT_K`(5) 상수(`SEARCH_K`) |
| 첫 검색 | 원 질문(한국어)과 `sub_queries`. 영어 번역은 검색 서비스가 한다 |
| 재검색 | 재작성한 영어 검색어 하나, 분해 없이 |
| 검색 기억 | 같은 실행 안의 검색 기억 열쇠에 `sub_queries`를 넣는다. 하위 질문이 다르면 다른 검색이다 |
| 실패 처리 | 분해 호출 오류나 응답 형식 오류이면 원 질문 하나로 검색한다(답은 멈추지 않는다). 비용 상한 초과 예외는 그대로 올린다 |
| 임베딩 오류 | `EmbedUnavailable`이면 예외를 올리지 않고 고정 문구의 거절로 끝낸다(`search_error=unavailable`) |
| 키 없음 | 검색 결과가 비었고 `fallback_reason=no_key`이면 같은 검색을 되풀이하지 않고 고정 문구의 거절로 끝낸다(`search_error=no_key`) |
| 켜는 곳 | `build_graph(decompose=True)` 또는 환경 변수 `SEARCH_DECOMPOSE=1`. 기본은 끔이다 |
| 측정 경로 | `exp_confirmed_v1`은 저장된 분해를 읽으므로 `decompose=False`로 그래프를 만든다. 환경 변수가 켜져 있어도 분해 호출이 없고 측정 값이 바뀌지 않는다(시험이 확인한다) |

**질문 분해 연결 (AC-12)**
- GIVEN: 분해를 켠 그래프와 가짜 모델, 가짜 검색기
- WHEN: 두 가지 사실을 묻는 한국어 질문을 넣는다
- THEN: 첫 검색은 원 질문과 하위 질문 2개, k=5로 호출되고, 재검색은 재작성한 검색어로 `sub_queries` 없이 호출된다. 분해가 깨졌을 때 첫 검색은 `sub_queries` 없이 호출되며 답은 정상으로 끝난다

**검색 불가 처리 (AC-13)**
- GIVEN: 검색기가 `EmbedUnavailable`을 던지거나 `fallback_reason=no_key`로 빈 결과를 돌려준다
- WHEN: 그래프를 실행한다
- THEN: 예외 없이 고정 문구의 거절로 끝나고, 판단과 답 작성 단계는 호출되지 않는다

측정 조건 기록: 그래프가 재검색에 넘기는 재작성 영어 검색어(키워드 형태)는 측정에서 쓰던 영어 문장과 형태가 다르다. 이 차이는 고치지 않고 `EVAL_REPORT.md` 3-3-1에 측정 조건으로 적었다.
