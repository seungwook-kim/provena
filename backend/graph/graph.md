# backend/graph/ : LangGraph 질문 처리 그래프

## 이 폴더가 하는 일

질문 분류, 재작성, 재검색, 답 작성, 인용 검사, 답변 저장. 상태(`state.py`)와 조립(`build.py`)을 둔다. 단일 그래프(D4)로 기준 점수를 재고 Supervisor 구조(D5)로 다시 잰다(G4). 그 밖의 파일: `citations.py`(인용 검사, 코드로 원문과 대조, LLM 없음), `decompose.py`(여러 사실을 묻는 질문을 하위 질문 2~3개로 나눔), `parsing.py`(LLM 출력을 견고하게 파싱, 실패하면 호출한 쪽이 안전 기본값), `mcp_retriever.py`(`SEARCH_VIA_MCP` 때 그래프 쪽 MCP 검색 연결).

- 주인: 김승욱
- 입력: 질문, 검색 결과
- 출력: 인용이 붙은 답, 이벤트(`events.py`)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) 근거 판정·분류·답 고르기 수정 묶음: 첫 판정이 '자료에 없음'이어도 표결이 만장일치일 때만 거절하고 갈리면 다시 검색해 판정(62.C, `build.py`, `answer_fixes.py`, 커밋 bce8181), 인용 확장 겹침을 값 줄 단위로 비교하고 청크 겹침 머리는 무시(62.B, fe2fa99), 다른 초안만 '자료에 없음'이라 할 때 답하는 초안을 고름(62.B2, 438fc36), out_of_domain을 주제가 아니라 '조직이 정한 것을 묻는가'로 분류(62.A, `build.py`, 8722491), 리뷰로 분류된 예·아니오 요구 질문을 정책 경로로 보냄(62.34, `query_plan.py`, 4af95cc), no_evidence 표는 바로 거절하고 out_of_period 구제는 기간 없는 질문에 한정(62.29 범위 축소, `grounding.py`, e768df2), 검색어 표 붙이기·제목 경로 더하기 장치와 스위치 삭제(결정 0101, `answer_fixes.py`·`multi.py`·`query_plan.py`·`service_profile.py`, e1e37e1), 단계별 비용·거절 단계를 `/chat` done 이벤트에 싣기(`build.py`·`stream.py`, 0a15fc2) | #119 |
| 2026-11-10 | 김승욱 (Claude Code) | 신뢰 경계 경로별 보강(사전 등록 62.26): 재작성 입력의 이미 찾은 제목에 입력 정화, 재작성 검색어와 되묻기 문장에 출력 검사(`build.py` `rewrite_reply`, `give_up`), 청크 절 이름(org) 정화, 제목 꼬리 토막을 출력 검사 의심 절로 처리(`untrusted.py`), `sanitize_cell` 추가 | - |
| 2026-11-10 | 김승욱 (Claude Code) | 근거 판정 단서 구제를 사유 out_of_period인 표에도 적용(운영 트레이스 bfd7bdbc, 1만 달러). 같은 단서 문장("현재 판의 값은 자료에서 확인할 수 없습니다")을 표마다 unsupported 또는 out_of_period로 달리 불러, 사유가 unsupported인 표에만 걸리던 `grounding.caveat_only_vote`가 out_of_period 표 둘에 걸리지 않아 2:1로 거절됐다. out_of_period 표도 꼽은 문장이 모두 단서 문장이고 답에 값 문장이 남아 있으며 질문 자체가 코드 규칙(`check_rules`의 기간 판정)으로 근거의 기간 밖이 아닐 때만 받쳐진 표로 센다(`build.py`가 인용·검색 청크를 `cited`, `retrieved`로 넘김). 질문이 기간 밖이거나 값 문장을 꼽은 표, 꼽은 문장 없이 NOTHING FOUND 요약만 있는 out_of_period 표는 그대로 거절이다. 시험 `tests/test_ground_caveat.py`(`test_other_reasons_are_not_affected` 기준 정정), `tests/test_ground_caveat_votes.py`(bfd7bdbc 재연) | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 응답 시간 p95 단축 코드 스위치(사전 등록 62.14~62.19, 모두 기본 꺼짐, 측정 전이라 효과는 모른다): `ANSWER_SAVE_ONE_CONN`(`save`가 `PgAnswerStore.save_with_grounding`으로 연결 하나), `CHAT_FINAL_FROM_STREAM`(`stream_events(values_out=)`로 `/chat`이 끝난 뒤 `get_state`를 다시 읽지 않음). 서비스 설정 `SERVICE_ENV`는 그대로이고 후보(검색 hedge 등)는 `service_profile.CANDIDATE_ENV`와 `.env.example` 주석에만 둠. 시험 `tests/test_speed_p95_code.py`(꺼짐 동일성 포함, 핵심 줄 5곳을 깨뜨려 시험이 실패함을 확인) | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 근거 판정 단서 구제를 표마다 적용한 뒤 다수결을 세도록 바꿈(`grounding.caveat_only_vote`, `read_verdict`, `build.py`의 `llm_verdict`). 꼽은 문장과 답 문장의 일치를 공백·구두점·따옴표를 지운 부분 일치로 넓힘. 답 작성·다시 쓰기 프롬프트에 질문의 대상이 표의 행에 해당하는지를 자료 밖 자기 단서로 덧붙이지 않는 규칙을 더함(`prompts/question.py`). 시험 `tests/test_ground_caveat_votes.py` | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 응답 시간 p95 단축 시도(사전 등록 62.8). `build.py`에 스위치 `GRAPH_SPECULATE_GROUND`(코드 기본 꺼짐, 서비스 설정 `SERVICE_ENV`에서는 켬, `answer_fixes.py`의 `speculate_ground_enabled`)를 더했다. 답 후보가 나오는 대로 인용 검사(`verify`)를 거쳐 근거 판정 호출을 같은 입력으로 미리 부르고(`ground_ahead`), `ground_once`의 판정 호출(`verdict_for`)이 입력 해시가 같으면 그 결과를 쓴다. 판정 지침·기준·답 고르기는 그대로다. 로컬 OpenRouter 50건에서 p95 회차 평균이 끔 14.504초에서 켬 11.996초로 줄었으나 SPEC 10초에는 미달이고 사전 등록 통과 기준도 넘지 못했으나, 품질 지표가 끈 쪽과 같아 사용자 결정으로 `SERVICE_ENV`에 `GRAPH_SPECULATE_GROUND=1`을 넣었다(EVAL_REPORT 8장). 측정 뒤 미리 부르기 등록 시점을 고친 것은 재측정 전이다. 시험 `tests/test_speculate_ground.py` | 미정 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #117) 근거 판정: 코드가 사유를 쥔 모델 표(인용이 있는 no_evidence, 질문에 기간이 없는 out_of_period)를 unsupported로 읽어 단서 구제를 거치게 함(`grounding.py`, `build.py`) | #117 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #116) 합친 표(DB 재정렬)에 맞춰 `answer_store.py`를 고침 | #116 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #101) 금액 질문 답의 단서 문장 거절과 구간 표 선택 흔들림 수정(`build.py`, `grounding.py`) | #101 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #100) 되묻기 메시지가 질문 속 지시 문장의 문자열을 인용하지 않게 함(`build.py`, `answer_fixes.py`, `untrusted.py`) | #100 |
| 2026-11-09 | 김승욱 (Claude Code) | `answer_store.py`에 `PgAnswerStore`(`db/120_answers_recall.sql`)와 `count_by_articles`를 더하고, `find_by_article` 결과에 `thread_id`, `version_date`, `source_url`을 붙였다(리콜이 쓴다). 리콜 구현은 `recall/recall.md` | 미정 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #97) 업무 종류를 못 뽑은 금액 질문이 결정표 거절로 끝나던 결함 수정: 분류 단계에서 업무 종류·금액을 먼저 뽑고 맞는 표가 없으면 일반 정책 경로로 보냄(`build.py`, `multi.py`) | #97 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #88) 간접 프롬프트 주입 방어를 문장 구조 판정으로 일반화하고 출력 검사를 입력 판정과 분리(`untrusted.py`) | #88 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #83) 프롬프트 인젝션 방어(입력 정화·출력 검사) 구현과 연결(`untrusted.py`, `build.py`) | #83 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #90) 빈 DB에서 인스턴스 여러 개가 동시에 뜰 때 체크포인트·Store 표 만들기(`open_persistence`)가 겹쳐 실패하지 않게 재시도 추가(`checkpoint.py`) | #90 |
| 2026-11-05 | 김승욱 (Claude Code) | `build_graph` 설명의 `SEARCH_DECOMPOSE` 문구를 코드(기본 켬, `decompose_enabled()`)에 맞춤. 동작 변경 없음 | 미정 |
| 2026-11-02 | 김승욱 (Claude Code) | 단일 에이전트 그래프 v1: `build_graph`, 노드 10개, 재검색 2회 상한, 인용 검사, 근거 판정, 저장, `AgentEvent` 흐름 | 이번 PR |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
