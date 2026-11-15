# Spec — 질문 그래프: 근거 답변 (김승욱, F-01 · G4)

> 초안(2026-10-29)으로 시작해 D0 이후 구현·측정으로 갱신해 왔다(2026-11-11 기준 구현 완료, 이 파일의 EC-10·`save` 행도 현재 코드에 맞춤). 설계 원문은 `docs/SDD.md` 4-3장, 숫자 기준은 `docs/PRD.md` 13-2장.

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
- **성공 기준** (`docs/PRD.md` 13-2와 같은 값, 동결됨. 단 "재검색 최대 2회"는 코드 상한이고 서비스 기본은 1회다, `backend/graph/service_profile.py:54`):
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
6. 답 작성: 질문이 묻는 사실에만 답하고, 문장마다 `[n]` 인용을 붙이고(한 사실에 가장 직접적인 근거 하나), 판 날짜, 출처 URL, CC BY-SA 4.0을 표시한다.
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
| EC-10 | 질문 종류가 결정표나 합동 검토인데 해당 경로를 쓸 수 없음(결정표 저장소·승인된 표가 없거나 금액이 없음, 합동 검토 하위 그래프가 안 꽂힘) | 분류 결과는 남기고 정책 질문 경로로 처리한다(`backend/graph/build.py:561,579`). 경로 자체는 구현돼 있다: 결정표 `backend/graph/decision/`, 합동 검토 `backend/graph/departments/` |

## How

- **파일**: `backend/graph/build.py`(조립), `backend/graph/state.py`(상태), `backend/prompts/`(프롬프트). LLM 호출은 `backend/services/llm.py` 한 곳으로만 한다(`docs/SCAFFOLD.md`).
- **조립 함수**: `build_graph(retriever=None, checkpointer=None)`. 검색기와 체크포인터를 주입받아, 검색 파트가 늦어도 가짜 검색기와 메모리 체크포인터로 키 없이 시험한다. 검색 호출 수를 셀 수 있어야 한다.
- **계약**: 입력 `SearchQuery`, `Chunk`, 출력 `AgentEvent` (`backend/schemas/`, `docs/SDD.md` 6장. D0에 동결)
- **체크포인터**: Postgres. 같은 `thread_id`로 재개된다. `open_persistence()`는 `setup` 직후 LangGraph 표 6개(`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`, `store`, `store_migrations`)에 RLS를 켜고 정책은 두지 않는다. 공개 키 역할은 막히고, 표 소유자인 앱은 그대로 쓴다.
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
| `save` | 답과 인용 저장(`InMemoryAnswerStore`와 DB판 `PgAnswerStore`, 표는 `db/120_answers_recall.sql`의 `answers`·`citations`) | `backend/graph/answer_store.py:49,123` |

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
| 도메인 밖 라우팅 | `classify`의 `out_of_domain` 경로. 두 번 모두 도메인 밖일 때만 따르고, 갈리면 일반 정책 경로로 보낸다 | #14, #23 |
| 인용 범위 | `ANSWER_SYSTEM`, `citation-rules`, `select_citations`. 묻는 사실에만 답하고 한 사실에 근거 하나, 주제 전용 섹션을 우선한다. 인용 수 상한(`MAX_CITATIONS` 4, #17)은 사전 등록 62.72로 없앴다 | #17, #23 |
| 근거 판정의 부분 제거 | `GROUNDING_SYSTEM`, `grounding.prune_answer`, `ground` 노드. 뺀 문장이 있으면 답에 밝힌다(`MSG_PARTIAL_NOTE`) | #18, #23 |
| 요청 기간 자료 없음은 거절 | `grounding.period_missing`, 답 JSON의 `period_covered` | #19 |
| 기준일 | `rewrite`의 `mentions_period`, 평가 실행기 `_as_of` | #20 |
| 질문 분해의 그래프 연결 | `backend/graph/decompose.py`, `search` 노드. 검색어 맨 앞의 회사 이름을 뗀다(`drop_company_prefix`) | #21, #23 |

**인용 범위 (AC-08)**
- GIVEN: 답이 본문에서 청크 5개를 인용하고 검색 결과에는 더 많은 청크가 있다
- WHEN: `verify`가 인용을 정리한다
- THEN: 본문에 표시가 있는 청크만 처음 나온 순서로 모두 인용으로 남긴다(사전 등록 62.72 뒤로 수 상한 없음). 본문에 표시가 없는 청크는 `trimmed_citations`에 기록하며 가짜 인용으로 세지 않는다

**근거 판정의 부분 제거 (AC-09)**
- GIVEN: 판정 LLM이 `unsupported`(근거 없는 주장)로 판정하고 받쳐지지 않는 문장을 원문 그대로 돌려준다
- WHEN: `ground`가 `prune_answer`로 그 문장을 뺀다
- THEN: 남은 답이 인용 검사, 내부 표현 누출 검사, 코드 근거 규칙, 판정 LLM 재판정을 모두 통과하면 남은 답에 일부를 뺐다는 안내를 붙여 내고, 하나라도 통과하지 못하면 원래 판정대로 답 전체를 거절한다. 문장의 절반을 넘게 빼야 하거나 문장이 답과 일치하지 않거나 모두 빠지면 거절한다. 두 번째 제거는 하지 않는다. `unsupported` 외의 사유(수치 불일치 등)는 부분 제거 없이 거절한다

**요청 기간 자료 없음은 거절 (AC-10)**
- GIVEN: 질문에 연도나 월 표현이 있고, 답이 `period_covered`를 false로 하거나 질문의 기간 표현과 "없다" 계열 표현을 한 문장에 함께 쓴다
- WHEN: `verify`가 `period_missing`을 검사한다
- THEN: 가까운 기간의 값을 인용했더라도 답 단계 거절(`out_of_period`)로 끝낸다. 질문에 기간 표현이 없으면 이 규칙은 돌지 않는다

**기준일 (AC-11)**
- GIVEN: 사용자가 기준일을 주지 않았고, 질문에 시점 표현이 없다
- WHEN: `rewrite`가 기준일을 돌려준다
- THEN: 그 기준일은 버리고 오늘 날짜를 쓴다. 오늘은 서버(UTC) 날짜가 아니라 한국 날짜다(`backend/graph/state.py` `today_kst`, 고정 +9시간. 2026-11-14 16:30 UTC이면 2026-11-15, 놓친 것 D-15). 평가 실행기는 `YYYY-MM` 형태의 평가 기준일을 그 달의 마지막 날로 바꿔 넘긴다

## 질문 분해의 그래프 연결 (4단계 `search` 노드)

질문 분해(LLM)는 검색이 아니라 그래프의 `search` 노드가 첫 검색 전에 한 번 합니다. `SearchQuery.sub_queries`(PR #48)에 결과를 넣어 검색에 넘기고, 검색은 분해를 하지 않습니다.

| 항목 | 규칙 |
|---|---|
| 입력 | 사용자가 쓴 한국어 원 질문(재작성한 영어 검색어가 아니다) |
| 프롬프트와 응답 읽기 | `evals/retrieval/exp_decompose_v1.py`와 같은 본문(`decompose.SYSTEM`)과 같은 JSON 읽기 규칙. 시험이 두 코드의 본문 일치를 확인한다 |
| 측정 코드와 다른 점 | ① 프롬프트 맨 앞에 노드 표지(`[[task:decompose]]`)를 붙인다. ② 응답이 깨지면 1회만 다시 묻는다(최대 2번, 측정은 최대 3번). ③ 하위 질문이 1000자를 넘으면 나누지 않은 것으로 본다(검색의 `check_query` 규칙). ④ 하위 질문 맨 앞의 `GitLab`을 뗀다. `GitLab.com`처럼 이어진 말은 그대로 둔다. ⑤ 원 질문이 두 문장 이상이고 마지막 문장 앞의 문장(전제)이 물음이 아닌데 그 내용어가 어느 하위 질문에도 없으면, 모든 하위 질문 앞에 전제 문장을 붙인다(`keep_premise`, 사전 등록 62.45). 앞 문장이 물음이면 붙이지 않는다 |
| 넘기는 값 | 하위 질문 2~3개이면 `sub_queries`로 넘긴다. 1개이거나 규칙을 어기면 넘기지 않는다(`None`). 4개 이상이면 앞 3개만 쓴다 |
| k | `DEFAULT_K`(5) 상수(`SEARCH_K`). 나뉜 질문도 첫 검색과 재검색 모두 5이고 근거 목록 상한은 10이다(`MAX_CHUNKS`). 나뉜 질문 첫 검색 넓힘(`SPLIT_K`=8, 근거 상한 +3, 사전 등록 62.38)과 달러 금액 질문 구분(62.43)은 사전 등록 62.72로 코드째 제거했다(설계에 평가 정답을 봤으므로) |
| 첫 검색 | 원 질문(한국어, 맨 앞의 `GitLab`은 뗀다)과 `sub_queries`. 영어 번역은 검색 서비스가 한다. 나뉜 질문은 하위 질문 결과를 번갈아 합친다. 끝 1자리를 원 질문 결과로 채우던 규칙은 62.72로 제거했다(제거 전 0원 계산은 `evals/results/tail_slot_rule_20261113/report.md`) |
| 답 근거와 답 후보 | 판정 입력에는 자리 표시가 없다. 답 후보 둘(`GRAPH_ANSWER_BEST2`)은 모두 문맥 전체로 쓰고, 판정 구절이 든 청크를 더 많이 인용한 후보, 같으면 그 밖 인용이 적은 후보를 쓴다(사전 등록 61.45, 기록 `rule="s_in,s_out"`). 넓힌 자리의 `[보충]` 표시와 앞 5자리 답 후보(62.44), 같은 문서 이웃 절 예외(61.47) 등은 사전 등록 62.72로 제거했다 |
| 첫 검색 뒤 | 첫 검색 결과를 그대로 문맥으로 쓴다. 도입부 채우기(61.5, 62.51), 같은 페이지 보충(62.55), 제목 경로 청크 추가와 검색어 덧붙임(62.69), 앞자리 인용끼리 비교(62.59)는 사전 등록 62.72로 제거했다 |
| 인용 후처리 | 코드가 근거 확인 뒤 인용을 바꾸지 않는다. 겹친 머리 바로잡기(62.52, 62.58, `head_owner_cites`, `prev_chunk`), 인용을 더하는 장치(인용 더하기, 문장 공유 더하기, 인용 추가 보정, 62.56·62.57·62.70), 한정어·되풀이 문장 기준으로 인용을 빼는 장치는 사전 등록 62.72로 제거했다. 일부 답에서 판정 구절 청크 밖 인용만 단 문장 빼기(62.66 `drop_unjudged_cites`)는 남는다 |
| 재검색 | 재작성한 영어 검색어 하나, 분해 없이 |
| 검색 기억 | 같은 실행 안의 검색 기억 열쇠에 `sub_queries`를 넣는다. 하위 질문이 다르면 다른 검색이다 |
| 실패 처리 | 분해 호출 오류나 응답 형식 오류이면 원 질문 하나로 검색한다(답은 멈추지 않는다). 비용 상한 초과 예외는 그대로 올린다 |
| 임베딩 오류 | `EmbedUnavailable`이면 예외를 올리지 않고 고정 문구의 거절로 끝낸다(`search_error=unavailable`) |
| 키 없음 | 검색 결과가 비었고 `fallback_reason=no_key`이면 같은 검색을 되풀이하지 않고 고정 문구의 거절로 끝낸다(`search_error=no_key`) |
| 켜는 곳 | `build_graph(decompose=True 또는 False)`로 정한다. `None`(기본)이면 환경 변수 `SEARCH_DECOMPOSE`를 따른다. 기본은 켬이다. 값이 없거나 비어 있어도 켜지고, `0`, `false`, `no`, `off`이면 끈다 |
| 측정 경로 | `exp_confirmed_v1`은 저장된 분해를 읽으므로 `decompose=False`로 그래프를 만든다. 환경 변수가 켜져 있어도 분해 호출이 없고 측정 값이 바뀌지 않는다(시험이 확인한다) |

**질문 분해 연결 (AC-12)**
- GIVEN: 분해를 켠 그래프와 가짜 모델, 가짜 검색기
- WHEN: 두 가지 사실을 묻는 한국어 질문을 넣는다
- THEN: 첫 검색은 원 질문과 하위 질문 2개, k=8(나뉘지 않은 질문과 달러 금액이 든 질문은 k=5)로 호출되고, 재검색은 재작성한 검색어로 `sub_queries` 없이 호출된다. 분해가 깨졌을 때 첫 검색은 `sub_queries` 없이 호출되며 답은 정상으로 끝난다

**검색 불가 처리 (AC-13)**
- GIVEN: 검색기가 `EmbedUnavailable`을 던지거나 `fallback_reason=no_key`로 빈 결과를 돌려준다
- WHEN: 그래프를 실행한다
- THEN: 예외 없이 고정 문구의 거절로 끝나고, 판단과 답 작성 단계는 호출되지 않는다

측정 조건 기록: 그래프가 재검색에 넘기는 재작성 영어 검색어(키워드 형태)는 측정에서 쓰던 영어 문장과 형태가 다르다. 이 차이는 고치지 않고 `EVAL_REPORT.md` 3-3-1에 측정 조건으로 적었다.

## 이어 묻기: 같은 대화의 앞 질문으로 완전한 질문 만들기 (D-14, 2026-11-15, 팀장 결정 ①)

**Why**
- 같은 대화에서 "고객은요?"처럼 주어·대상이 빠진 뒤 질문은 새 질문으로 처리됐다. 그래프 입력이 지금 질문 하나뿐이었기 때문이다(`backend/api/routes.py`의 `graph_input`, `backend/graph/build.py`의 `load_memory`). 검색어가 "고객"만 남아 엉뚱한 근거를 찾거나 거절했다.
- 팀장 결정(①): 같은 대화의 앞 질문을 함께 넘기고, 지금 질문이 이어 묻는 질문이면 완전한 질문으로 다시 써서 답하고, 화면에 "이렇게 이해했습니다: <다시 쓴 질문>"을 보인다. 버린 대안은 `docs/decisions.md` 2026-11-15 행.

**Goal**
- 이어 묻는 질문은 앞 질문의 빠진 말을 채운 질문으로 분류, 검색, 판정, 답 작성을 한다.
- 새 대화와 대화의 첫 질문은 호출 수, 노드 순서, 입력 글자가 그대로다(추가 LLM 호출 0). 평가 실행기는 문항마다 새 thread로 그래프를 직접 부르고 `asked`를 넘기지 않으므로 호출과 답이 그대로다(상태에 빈 목록 `asked: []` 칸만 더 생긴다).
- 다시 쓰기가 실패해도 요청은 실패하지 않는다(원 질문으로 그대로 답한다).
- Out of Scope: 앞 답의 내용을 이어 받는 대화(답 요약, 인용 재사용), 대화 전체 이력 요약, 다시 쓴 질문의 품질 측정(실제 모델 호출이 필요해 이번 작업에서 하지 않았다).

**What**

| 항목 | 규칙 |
|---|---|
| 앞 질문이 오는 곳 | `/chat`이 질문마다 그래프 입력에 `asked: [질문]`을 더한다(`backend/api/routes.py`). 상태의 `asked` 칸에는 합치기 규칙(`backend/graph/state.py`의 `keep_recent_questions`)이 있어, 같은 thread의 체크포인트에 최근 질문 3개(지금 질문과 앞 질문 2개)가 쌓인다. 그래프가 실행을 시작하며 체크포인트를 열 때 같이 오므로 `/chat`은 앞 질문을 찾으려고 체크포인트를 따로 읽지 않는다(사전 등록 62.16의 왕복 줄이기 그대로). 체크포인트 thread 이름은 `<user_id>:<thread_id>`라 같은 사용자의 같은 대화 질문만 쌓인다 |
| 넘기는 양 | 직전 질문과 그 앞 질문까지 최대 2개(`state.MAX_PREV_QUESTIONS`, `state.previous_questions`). 앞 질문마다 이어 묻기로 다시 쓴 기록(`understood_by_asked`, 친 글 -> 다시 쓴 글, 최근 3줄, `state.remember_understood`)이 있으면 다시 쓴 쪽을 넘긴다(혼자서 뜻이 통해, 이어 묻기 사이에 다른 질문이 끼어도 대상이 남는다). 다시 쓰지 않은 질문은 같은 글의 옛 줄을 지운다(`state.forget_understood`). 다시 쓴 질문에 새로 들어온 글자·숫자(공백·문장부호 제외, 원 질문과 맞대어 넣기·바꾸기 쪽, `prompts.question.followup_new_letters`)가 4개 미만이면(조사·접속사만 바뀐 응답) 쓰지 않는다(`FOLLOWUP_MIN_GAIN`). 프롬프트에는 질문마다 앞 500자만 넣는다(`prompts.question.PREV_QUESTION_CHARS`). 앞 답은 넘기지 않는다: 답에는 검색 원문에서 온 글이 섞여 인젝션 표면과 토큰이 늘고, 빠진 주어·대상은 질문에 있다 |
| `asked`에 쌓이는 것 | `/chat`이 그래프에 넘긴 질문(사용자가 친 글). 바로 앞과 같은 글(다시 시도)은 다시 쌓지 않는다. 승인 대기 중이라 409로 막힌 질문은 그래프에 가지 않아 쌓이지 않는다. `asked`를 넘기지 않는 실행(평가 실행기, 그래프 직접 호출)의 상태에는 빈 목록 `asked: []`만 생긴다 |
| 노드 | `followup`(`load_memory` 다음, `classify` 앞). 앞 질문이 있을 때만 지난다(`load_memory`의 조건 분기가 `previous_questions`를 본다). 없으면 지금처럼 `load_memory -> classify`다 |
| LLM 호출 | 1회, `backend/services/llm.py`로 받은 같은 모델. 프롬프트 `backend/prompts/question.py`의 `FOLLOWUP_SYSTEM`(표지 `[[task:rewrite_followup]]`), 입력 `followup_user`. 출력 JSON `{"followup": true 또는 false, "question": "..."}`. 형식이 깨져도 다시 묻지 않는다(앞 단계라 지연을 늘리지 않는다) |
| 다시 쓴 질문을 쓰는 조건 | `followup`이 `true`이고 `question`이 비지 않은 문자열이고 4000자 이하(`/chat` 질문 상한과 같다)이고 원 질문과 다르고, 코드 검사(내부 표식·프롬프트 문장 `leaks_internal`, 프롬프트 요구 `asks_internal`, 가짜 자료 구분자, 지시 문장 `untrusted.strip_instructions`)에 걸리지 않을 때만 |
| 그 밖의 모든 경우 | 원 질문 그대로 간다: 이어 묻기가 아님, 응답 형식 오류, LLM 예외, 빈 값, 너무 긴 값, 코드 검사에 걸림. 비용 상한 예외(`CostCapExceeded`)만 그대로 올린다 |
| 다시 썼을 때 상태 | `question` = 다시 쓴 질문(분류, 재작성, 분해, 검색, 판정, 답, 근거 판정, 저장이 모두 이 값을 쓴다), `user_question` = 사용자가 친 글, `understood_question` = 다시 쓴 질문. 다시 쓰지 않으면 두 칸은 `None`이다. 두 칸은 다음 질문이 앞 질문으로 읽을 수 있게 상태에 남고, 다음 질문의 `followup` 노드가 다시 쓴다. 그래서 `done`은 이번 실행의 노드 갱신에서만 읽고, 대화 이력은 `understood_question`이 그 질문의 `question`과 같을 때만 그 질문의 값으로 본다 |
| 안전 검사가 보는 글 | 프롬프트 요구만 있는 질문(`only_asks_internal`)은 사용자가 친 글로 먼저 보고, 걸리면 다시 쓰지 않아 `classify`가 지금처럼 범위 밖으로 끝낸다. 범위 밖 분류, 시점 표현(`mentions_period`), 되묻기, 답의 기간 검사는 다시 쓴 질문으로 본다(빠진 대상·시점이 채워진 글이어야 판정이 맞다). 출력 검사(`scrub_answer`, `leaks_instruction`)가 "질문에 있던 말"로 보는 글도 다시 쓴 질문이다. 그래서 앞 질문은 프롬프트에 넣기 전에 지시 문장을 빼고, 다시 쓴 질문에 지시 문장이 남으면 쓰지 않는다 |
| 앞 질문 정화 | `followup_prev`: 가짜 자료 구분자와 프롬프트 요구 문장을 빼고(`question_for_prompt`), 지시 문장을 문장째 빼고(`strip_instructions(whole_sentence=True)`), 한 줄로 접고, 500자로 자른다. 비거나 프롬프트 요구뿐인 앞 질문은 버린다. 남는 앞 질문이 없으면 LLM을 부르지 않는다 |
| 화면 전달 | 다시 썼을 때만 `done.data.understood_question`(`backend/graph/stream.py`). `GET /threads/{id}`의 `messages`는 질문 글을 사용자가 친 글로 주고, 그 답 항목에 `understood_question`을 더한다. 대화 제목은 지금처럼 첫 질문의 사용자가 친 글이다 |
| 답 저장 | 저장되는 질문은 다시 쓴 질문이다(리콜이 다시 판정할 때 혼자서 뜻이 통해야 한다) |
| 멀티 그래프 | Supervisor가 첫 방문에서 `load_memory` 다음에 같은 분기와 같은 노드를 부른다(`backend/graph/multi.py`). 하위 에이전트는 이미 `question`을 읽으므로 `reads`는 그대로다 |
| 키 없는 데모(녹화 재생) | 녹화한 질문은 대화의 첫 질문이라 이 호출이 없다. 같은 대화의 둘째 질문부터는 녹화에 없는 호출이라 재생 모델이 고정 문장을 돌려주고(JSON 아님) 원 질문으로 그대로 간다 |
| 비용·단계 이름 | 단계 이름은 노드와 표지에서 자동으로 `followup/rewrite_followup`이 된다(`llm_trace.step_of`). `done.cost_by_step`과 Langfuse에 그 이름으로 잡힌다. 추론 수준은 기본값(단계별 목록에 넣지 않았다) |
| 끄는 법 | 환경 변수 `CHAT_FOLLOWUP=0`(기본 켬). 꺼도 `/chat`은 `asked`를 넘겨 질문 기록을 쌓고(다시 켰을 때 꺼진 동안의 질문이 빠지지 않게), 질문마다 `followup_off`를 넘긴다. 그래프는 `followup_off`면 `followup`을 지나지 않는다(`backend/api/routes.py`, `backend/graph/build.py`) |

**한계**
- 대화의 둘째 질문부터 LLM 호출 1회가 늘어난다(이어 묻기가 아닌 질문도). 실제 모델 켬·끔 비교에서 같은 대화의 이어 묻기가 아닌 둘째 질문은 켬이 약 2초 느렸다(7.1·7.8초 대 5.7·5.4초, `docs/pr-notes/PR-162.md` 8절, 로컬 값). 비용은 따로 재지 않았다. DB 왕복은 늘지 않는다.
- 이 기능을 넣기 전에 만든 대화는 `asked`가 비어 있어, 넣은 뒤 첫 질문은 앞 질문 없이 처리되고 그다음 질문부터 이어진다.
- 다시 쓴 질문의 정확도는 실제 모델 켬·끔 비교 한 번(이어 묻는 질문 5개 x 2회)으로만 보았다: 맞는 답이 켬 10회 중 10회, 끔 10회 중 2회(`docs/pr-notes/PR-162.md` 8절). 운영에서는 재지 않았다.
- 지시 문장 검사는 규칙 목록이라 목록에 없는 말투는 놓친다(`backend/graph/untrusted.py` 한계와 같다). 앞 질문은 같은 사용자가 같은 대화에서 친 글이다.

**AC (시험 `tests/test_followup_question.py`)**

**AC-14 · 첫 질문은 그대로**
- GIVEN: 앞 질문이 없는 입력(새 대화, `asked`를 넘기지 않는 평가 실행기)
- WHEN: 그래프 실행
- THEN: `rewrite_followup` 호출 0회, 노드 순서에 `followup`이 없고, 분류 입력의 질문 글자가 그대로다(`test_first_question_makes_no_followup_call_and_skips_the_node`, `test_chat_first_question_of_a_named_thread_makes_no_call`). `/chat`은 앞 질문 때문에 체크포인트를 더 읽지 않는다(`test_chat_new_thread_reads_no_history`: `get_state` 0회)

**AC-15 · 이어 묻기는 완전한 질문으로**
- GIVEN: 앞 질문이 있고 가짜 모델이 `followup=true`와 다시 쓴 질문을 낸다
- WHEN: 그래프 실행
- THEN: 분류·검색·답 입력이 다시 쓴 질문이고, 상태에 `user_question`(친 글)과 `understood_question`이 남는다(`test_followup_question_is_rewritten_and_used_downstream`). 멀티 그래프도 같은 결과다(`test_multi_graph_rewrites_followup_like_single`)

**AC-16 · 이어 묻기가 아니면 그대로**
- GIVEN: 앞 질문이 있고 가짜 모델이 `followup=false`를 낸다
- THEN: 질문은 그대로이고 `understood_question`이 없다(`test_not_a_followup_keeps_the_question`)

**AC-17 · 실패해도 답한다**
- GIVEN: 다시 쓰기 호출이 예외, 빈 응답, JSON 아님, 빈 질문, 4000자 초과, 문자열 아님
- THEN: 원 질문으로 답이 끝까지 나온다(`test_bad_followup_reply_falls_back_to_the_original_question`). 비용 상한 예외는 그대로 올라간다(`test_cost_cap_is_not_swallowed`)

**AC-18 · 앞 질문의 지시는 프롬프트에 들어가지 않는다**
- GIVEN: 앞 질문에 지시 문장, 자료 구분자, 프롬프트 요구가 있다
- THEN: 다시 쓰기 입력에 그 글이 없다(`test_instructions_in_previous_questions_never_reach_the_prompt`). 다시 쓴 질문에 내부 표식이나 지시 문장이 있으면 쓰지 않는다(`test_rewritten_question_with_instruction_or_marker_is_dropped`). 프롬프트 요구뿐인 지금 질문은 다시 쓰지 않는다(`test_prompt_request_is_not_rewritten`)

**AC-19 · 같은 사용자의 같은 대화만**
- GIVEN: 앨리스의 t1, 앨리스의 t2, 밥의 t1에 서로 다른 질문이 있다
- WHEN: 각 대화에 둘째 질문을 보낸다
- THEN: 다시 쓰기 입력에는 그 사용자의 그 대화 질문만, 최대 2개 있다(`test_chat_passes_only_same_user_same_thread_questions`, `test_asked_keeps_the_current_and_two_previous_questions`, `test_previous_questions_drop_the_current_one_and_prefer_the_understood_question`)

**AC-20 · 화면 전달**
- THEN: `done.understood_question`은 다시 썼을 때만 있고(`test_chat_done_has_understood_question_only_when_rewritten`), 대화 이력의 질문 글은 친 글 그대로이며 답 항목에 `understood_question`이 붙는다(`test_thread_messages_keep_typed_text_and_carry_understood_question`). 다음 질문에서는 앞 질문의 값이 남지 않는다(`test_next_question_does_not_inherit_understood_question`)

**AC-21 · 녹화 재생과 끄기**
- THEN: 재생 모델로 둘째 질문을 보내도 원 질문으로 끝난다(`test_replay_model_keeps_the_original_question`). `CHAT_FOLLOWUP=0`이면 앞 질문이 쌓이지 않고 다시 쓰기 호출이 없다(`test_switch_off_passes_no_history`)

## 사전 등록 62.72: 평가 정답을 본 장치 제거와 실행 기록에서 고른 세 가지 (2026-11-15)

### Why
- 설계 단계에서 평가셋의 정답(정답 청크, 기대 답)을 보고 만든 장치는 처음 보는 질문에서 통한다는 근거가 없다. 그래서 감사(2026-11-15)에서 그렇게 만든 것으로 분류한 장치를 코드, 시험, 문서에서 함께 제거했다.
- 남은 속도 꼬리와 쓰이지 않는 호출은 정답을 보지 않은 운영 실행 기록(00056~00057)만으로 찾았다.

### What
- 제거(코드째, 스위치와 시험 포함): 검색어 용어표와 덧붙임(`GRAPH_QUERY_TERMS`), 제목 경로 추가·알림·절 이름 구(`GRAPH_HEADING_TERMS`, `GRAPH_HEADING_MARK`, `GRAPH_HEADING_HEADS`), 대상별 나누기(`GRAPH_QUERY_BRANCHES`, `query_plan.py` 삭제), 인용 더하기(`GRAPH_CITE_EXPAND`), 문장 공유 더하기(`GRAPH_CITE_PHRASE`), 같은 페이지 재검색(`GRAPH_RESEARCH_SAME_PAGE`), 한정어 인용 빼기(`GRAPH_DROP_SCOPED_CITES`), 도입부 채우기(`GRAPH_INTRO_FILL`), 되풀이 문장 쪽 인용만(`GRAPH_CITE_CONSENSUS`), 페이지 재검색 새 청크만(`GRAPH_REQUERY_SKIP_SEEN`), 근거 고르는 순서 프롬프트(`GRAPH_CITE_PICK`), 두 답 고르기 같은 문서 예외(`GRAPH_BEST2_SAMEDOC`), 나뉜 질문 첫 검색 넓힘(`SPLIT_K`, `FULL_TAIL`, 근거 상한 +3), 넓힌 문맥 앞자리 우선(`core_chunks`, `[보충]`, 앞자리 답 후보), 같은 페이지 보충(`page_fill`), 인용 추가 보정(`GRAPH_CITE_ADD_GUARD`).
- 같은 이유로 함께 제거(사용자 결정): 범위 메모 거절(`GRAPH_SCOPE_NOTE_REFUSE`, 정규식 `_SCOPE_LIMITED`·`_SCOPE_ABSENT`), 안내 구절 거절(`GRAPH_POINTER_REFUSE`, `_POINTER`, `pointer_only`), 팀 문서 뒤로(`GRAPH_TEAM_LAST`, `team_docs_last`, `_TEAM_TITLE`), 겹친 머리 인용 바로잡기(62.52·62.58, `head_owner_cites`, `head_overlap`, 앞 청크 읽기 `prev_chunk`·`page_chunks`), 근거 확인 구절 형식(`GROUNDING_QUOTE_RULES`)의 제목 경로(적용 범위) 간접 근거 문장, 인용 수 상한(`MAX_CITATIONS`=4, 코드 자르기와 답 프롬프트의 "4개 이하" 문장).
- 제거한 뒤 동작: 나뉜 질문도 k=5, 근거 목록 상한 10. 일부 판정 뒤 재검색은 전체 검색이다. 코드가 근거 확인 뒤 인용을 더하거나 빼거나 바꾸지 않는다(62.66 일부 답 문장 빼기만 남는다). 답 후보 둘은 61.45 규칙으로 고른다. 충분 판정은 범위 메모가 있어도 그대로 충분이고, 받쳐진 답은 구절이 안내 문장이어도 그대로 나간다. 답 입력의 자료 순서는 검색 순서 그대로다. 본문에 표시한 인용은 수 제한 없이 모두 남는다. 구절 형식(주장마다 받치는 영어 구절 복사, 없으면 NOTHING FOUND)과 번역·말 바꿈 기준은 그대로다.
- 새 스위치 둘(코드 기본 꺼짐, 서비스 설정 `SERVICE_ENV`에서 켬):
  - `GRAPH_NONE_VOTE_WAIT_S`(초, 서비스 값 `1.0`): 판정 다수결(`GRAPH_JUDGE_VOTE`)에서 먼저 온 두 표가 모두 "근거 없음"(충분도 일부도 아님)이면 셋째 표를 이 초까지만 기다린다. 오지 않으면 두 표로 확정하고 `judge_votes`에 `how="none_capped"`를 남긴다. 빈 값이면 지금처럼 셋째 표를 끝까지 기다리고, 숫자가 아니거나 음수면 시작할 때 오류다. 근거: 첫 두 표가 모두 근거 없음인 143행 중 셋째 표가 달랐던 것은 비관련 질문 1행(재검색 뒤 거절)이고 관련 질문은 0행이었다.
  - `GRAPH_SPEC_STOP_GROUND`(서비스 값 `1`): 분해가 질문을 나눠 미리 돌리기(`GRAPH_SPECULATE_FIRST`)를 버리기로 하면, 그 미리 돌리기 안에서 나온 답 후보는 근거 확인을 미리 부르지 않고 기록(`grounding.candidates`)에 `verdict="skipped_spec_dropped"`만 남긴다. 쓰는 미리 돌리기와 본 경로는 그대로다. 버림 표시는 늦게 끝나는 답 작성 일꾼도 보도록 바로 지우지 않고 2분 뒤 청소한다.
- 단계 시간 기록(스위치 없음, 기록만): 요청 집계(`step_cost.begin`) 안에서 `done.path`에 노드별 초 합 `timing`(`classify`, `search`, `judge`, `answer_pick`, `ground`, `save`. 노드 안 배경 호출은 더하지 않는다)과 판정 표마다 걸린 초 `vote_s`를 싣는다. `search_stats`에는 검색 단계 시간 `ms_translate`, `ms_embed`, `ms_vector`, `ms_link`(밀리초)를 더한다. 기록이 실패해도 답은 그대로다.

### AC
- GIVEN 다수결이 켜져 있고 `GRAPH_NONE_VOTE_WAIT_S=0.1`이다. WHEN 앞 두 표가 근거 없음이고 셋째 표가 1.5초 뒤에 온다. THEN 셋째 표를 기다리지 않고 거절하며 `how="none_capped"`다(`tests/test_blind_6272.py::test_two_none_votes_settle_when_the_third_is_later_than_the_cap`). 상한 안에 온 셋째 표, 충분·일부 두 표, 스위치 끔은 지금과 같다(같은 파일의 나머지 다수결 시험).
- GIVEN 미리 돌리기와 미리 부르는 근거 확인이 켜져 있다. WHEN 분해가 질문을 나눠 미리 돌리기를 버린다. THEN `GRAPH_SPEC_STOP_GROUND`를 켜면 근거 확인 호출이 끈 때보다 1건 적고 답은 같다(`test_dropped_speculation_does_not_ground_ahead`). 미리 돌리기를 쓰는 실행은 호출 수가 같다(`test_used_speculation_still_grounds_ahead`).
- GIVEN 옛 스위치 이름(`GRAPH_SCOPE_NOTE_REFUSE`, `GRAPH_POINTER_REFUSE`)을 켠다. THEN 충분 판정과 받쳐진 답은 그대로 답으로 간다(`tests/test_d7_fixes.py::test_scope_note_never_turns_a_sufficient_judgement_into_a_refusal`, `test_pointer_quote_does_not_refuse_a_grounded_answer`). 구절이 겹친 머리에만 있어도 인용은 그대로다(`tests/test_trace_fixes_1113.py::test_graph_keeps_the_citation_when_the_quote_is_only_in_the_copied_head`). 본문에 표시한 인용 6개가 모두 남는다(`tests/test_question_graph.py::test_no_citation_cap_keeps_every_body_mark_in_body_order`).
- GIVEN 요청 집계 안이다. THEN `path_meta`에 `timing`과 `vote_s`가 있고(`test_path_meta_has_node_timing_and_vote_seconds_inside_a_request`), 기록이 실패해도 답과 인용이 같다(`test_recording_failures_do_not_change_the_answer`).
