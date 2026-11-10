# backend/graph/ : LangGraph 질문 처리 그래프

## 이 폴더가 하는 일

질문 분류, 재작성, 재검색, 답 작성, 인용 검사, 답변 저장. 상태(`state.py`)와 조립(`build.py`)을 둔다. 단일 그래프(D4)로 기준 점수를 재고 Supervisor 구조(D5)로 다시 잰다(G4).

- 주인: 김승욱
- 입력: 질문, 검색 결과
- 출력: 인용이 붙은 답, 이벤트(`events.py`)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (Claude Code) | 응답 시간 p95 단축 코드 스위치(사전 등록 62.14~62.19, 모두 기본 꺼짐, 측정 전이라 효과는 모른다): `ANSWER_SAVE_ONE_CONN`(`save`가 `PgAnswerStore.save_with_grounding`으로 연결 하나), `CHAT_FINAL_FROM_STREAM`(`stream_events(values_out=)`로 `/chat`이 끝난 뒤 `get_state`를 다시 읽지 않음). 서비스 설정 `SERVICE_ENV`는 그대로이고 후보(검색 hedge 등)는 `service_profile.CANDIDATE_ENV`와 `.env.example` 주석에만 둠. 시험 `tests/test_speed_p95_code.py`(꺼짐 동일성 포함, 핵심 줄 5곳을 깨뜨려 시험이 실패함을 확인) | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 근거 판정 단서 구제를 표마다 적용한 뒤 다수결을 세도록 바꿈(`grounding.caveat_only_vote`, `read_verdict`, `build.py`의 `llm_verdict`). 꼽은 문장과 답 문장의 일치를 공백·구두점·따옴표를 지운 부분 일치로 넓힘. 답 작성·다시 쓰기 프롬프트에 질문의 대상이 표의 행에 해당하는지를 자료 밖 자기 단서로 덧붙이지 않는 규칙을 더함(`prompts/question.py`). 시험 `tests/test_ground_caveat_votes.py` | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 응답 시간 p95 단축 시도(사전 등록 62.8). `build.py`에 스위치 `GRAPH_SPECULATE_GROUND`(코드 기본 꺼짐, 서비스 설정 `SERVICE_ENV`에서는 켬, `answer_fixes.py`의 `speculate_ground_enabled`)를 더했다. 답 후보가 나오는 대로 인용 검사(`verify`)를 거쳐 근거 판정 호출을 같은 입력으로 미리 부르고(`ground_ahead`), `ground_once`의 판정 호출(`verdict_for`)이 입력 해시가 같으면 그 결과를 쓴다. 판정 지침·기준·답 고르기는 그대로다. 로컬 OpenRouter 50건에서 p95 회차 평균이 끔 14.504초에서 켬 11.996초로 줄었으나 SPEC 10초에는 미달이고 사전 등록 통과 기준도 넘지 못했으나, 품질 지표가 끈 쪽과 같아 사용자 결정으로 `SERVICE_ENV`에 `GRAPH_SPECULATE_GROUND=1`을 넣었다(EVAL_REPORT 8장). 측정 뒤 미리 부르기 등록 시점을 고친 것은 재측정 전이다. 시험 `tests/test_speculate_ground.py` | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `answer_store.py`에 `PgAnswerStore`(`db/120_answers_recall.sql`)와 `count_by_articles`를 더하고, `find_by_article` 결과에 `thread_id`, `version_date`, `source_url`을 붙였다(리콜이 쓴다). 리콜 구현은 `recall/recall.md` | 미정 |
| 2026-11-05 | 김승욱 (Claude Code) | `build_graph` 설명의 `SEARCH_DECOMPOSE` 문구를 코드(기본 켬, `decompose_enabled()`)에 맞춤. 동작 변경 없음 | 미정 |
| 2026-11-02 | 김승욱 (Claude Code) | 단일 에이전트 그래프 v1: `build_graph`, 노드 10개, 재검색 2회 상한, 인용 검사, 근거 판정, 저장, `AgentEvent` 흐름 | 이번 PR |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
