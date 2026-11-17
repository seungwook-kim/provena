# /chat 멀티 그래프 전환: 단일 경로와의 기능 대조 (2026-11-17)

## 배경

2026-11-17 팀장 지시로 서비스 `/chat`이 단일 그래프(`backend/graph/build.py`의 `build_graph`) 대신 Supervisor 멀티 그래프(`backend/graph/multi.py`의 `build_multi_graph`, 코드 라우팅, 검색 → 작성 → 검증 에이전트)를 돌린다. 전환 전에는 `backend/main.py`의 `build_question_graph`가 단일 그래프만 만들었고, 멀티 그래프는 측정 실행기와 안전 평가에서만 썼다.

이 문서는 전환 전에 `/chat` 단일 경로가 하는 일을 항목별로 멀티 경로와 대조한 결과이다. 대조 방법은 코드 읽기(두 그래프의 노드, 분기, 상태 칸, `/chat` 어댑터)와 가짜 모델 비교 실행(서비스 설정 61.51을 채운 채 같은 입력을 두 그래프에 주고 최종 상태 전체를 비교)이다. 빠진 항목은 같은 노드와 함수를 다시 써서 채웠다.

## 전환 방식

- 스위치 `QUESTION_GRAPH_MODE`(`single` 또는 `multi`). 코드 기본은 `single`이고 서비스 값(`backend/graph/service_profile.py`의 `SERVICE_ENV`, `.env.example`)은 `multi`이다. 앱이 뜰 때 서비스 설정이 환경 변수로 채워지므로 운영·로컬 데모·키 없는 데모 모두 멀티 그래프로 돈다. 시험과 측정 실행기는 서비스 설정을 쓰지 않는 한 그대로 단일이다.
- 틀린 값이면 앱이 뜨지 않는다(`ValueError`). 운영에서 되돌리려면 환경 변수에 `single`이나 `off`를 준다(`off`는 빈 값이 되어 코드 기본 `single`).
- 멀티 그래프는 `build_question_graph`가 단일에 넘기던 인자(공유 모델 `SharedChatModel`, 체크포인터, Store, 답 저장소, 결정표 저장소, 합동 검토 하위 그래프, 서비스 검색 함수)를 그대로 받는다. 안쪽에서 같은 인자로 단일 그래프를 만들고 그 노드와 분기 함수를 꺼내 에이전트 안에 다시 배선한다(`SingleParts`). 프롬프트, 검색, 판정, 인용 검사, 저장 코드는 하나뿐이다.
- 라우터는 `SUPERVISOR_ROUTER`(비면 `code`)이다. 서비스 값에 넣지 않아 코드 라우팅이며, 라우팅 때문에 늘어나는 LLM 호출은 없다.

## 대조표

판정: 같음 = 전환 전부터 같은 코드가 같은 결과를 냄, 채움 = 멀티에 빠졌거나 달랐던 것을 이번에 맞춤, 다름 = 남은 차이(아래 "같게 만들 수 없던 것").

| 항목 | 단일 `/chat` 경로 | 멀티 경로 | 판정 | 근거(코드·시험) |
|---|---|---|---|---|
| SSE 이벤트(token, citation, approval_request, error, done) | `backend/graph/stream.py` `stream_events`가 그래프 갱신을 이벤트로 바꾼다 | 같은 어댑터. 이벤트 종류·순서·내용이 같다 | 같음 | `tests/test_chat_multi_switch.py` `test_chat_events_on_the_multi_graph_are_the_same_as_single`(답, 재검색 뒤 거절, 되묻기, 범위 밖, 가짜 인용 거절, 내부 설정 질문, 질문 속 출력 자리 지시 7가지) |
| done의 `refuse_stage`(거절·되묻기를 낸 노드) | 단일 노드 이름(`out_of_domain`, `give_up`, `verify`, `ground` 등) | 전환 전에는 에이전트 노드 이름(`supervisor`, `retriever`, `verifier`)이 나왔다 | 채움 | 멀티 상태 칸 `kind_node`(에이전트 안에서 결과 종류를 쓴 단일 노드 이름)를 `stream_events`가 읽는다. `test_refuse_stage_names_the_single_graph_node` |
| done의 `refuse_reason`, `code`, `attribution`, `usage` | `step_cost.refuse_meta`, `/chat` 어댑터 | 같은 함수, 같은 상태 칸 | 같음 | 위 이벤트 비교 시험 |
| done의 `path`(답 경로 기록) | `step_cost.path_meta`가 최종 상태를 읽는다 | 판정 다수결의 표 구성 기록 `judge_votes`가 검색 에이전트의 돌려주는 칸에 없어 비어 있었다 | 채움 | `RETRIEVER.reads`·`writes`에 `judge_votes`를 더했다. `test_judge_vote_record_is_kept_on_the_multi_graph`. 서비스 설정으로 두 그래프의 최종 상태 전체를 비교하면 남은 차이는 실행마다 새로 만드는 열쇠(`search_cache`의 미리 돌리기 열쇠)뿐이다 |
| done의 `cost_by_step`(단계별 비용)과 Langfuse 단계 이름 | LLM 기록이 `langgraph_node`(`classify` 등)로 단계를 나눈다 | Supervisor가 직접 부르는 노드(`load_memory`, `followup`, `classify`, `out_of_domain`, `give_up`)의 호출이 `supervisor`로 묶였다 | 채움 | `run_single_node`가 그 노드를 부를 때 설정의 노드 이름을 단일과 같은 이름으로 두고 문맥에 건다. `test_llm_calls_carry_the_single_node_names_and_the_run_metadata` |
| 단계 시간 기록(`path.timing`, 사전 등록 62.72) | 노드마다 `timed_node`가 시작·끝을 남긴다 | 같은 노드 실행체를 꺼내 쓰므로 같은 이름으로 남는다 | 같음 | `multi.py` `SingleParts.node` |
| 체크포인터와 대화 저장 | `PostgresSaver`(운영), thread 이름 `<user_id>:<thread_id>` | 바깥(멀티) 그래프가 같은 체크포인터로 컴파일된다 | 같음 | `test_service_graph_follows_the_switch_with_the_same_arguments` |
| 재시작 뒤 같은 대화 이어 가기 | 같은 체크포인터로 새 그래프를 만들어도 이력과 이어 묻기가 이어진다 | 같다 | 같음 | `test_thread_survives_a_new_graph_on_the_same_checkpointer`, `test_thread_history_is_the_same_on_both_graphs`, `tests/test_multi_graph.py` `test_review_resume_survives_a_new_graph_on_the_same_checkpointer` |
| `/threads/{id}` 대화 이력 되살리기 | 바깥 이름공간의 입력 체크포인트로 질문을 나눈다 | 같다(하위 에이전트 체크포인트는 하위 이름공간이라 섞이지 않는다) | 같음 | `test_thread_history_is_the_same_on_both_graphs` |
| 사용자 기억(`load_memory`, 프로필 소속, `/me/memory`) | `load_memory` 노드 | Supervisor가 첫 방문에 같은 노드를 부른다. 같은 Store | 같음 | `multi.py` `supervisor` |
| 이어 묻기(D-14, `followup`) | `load_memory` 뒤 분기 | 같은 분기 함수와 같은 노드 | 같음 | `tests/test_followup_question.py`(단일·멀티) |
| 되묻기(clarify) | 판정 뒤 `give_up`이 되묻기로 닫는다 | Supervisor가 같은 `give_up` 노드로 닫는다 | 같음 | 이벤트 비교 시험의 되묻기 사례 |
| 거절(재검색 상한 뒤), 범위 밖(`out_of_domain`) | 단일 노드 | Supervisor가 같은 노드로 직접 닫는다 | 같음 | 이벤트 비교 시험 |
| 합동 검토 라우팅(Supervisor + 4팀, 팀 선택 `REVIEW_TEAM_SELECT`) | 질문 그래프의 `review` 노드에 하위 그래프 | 같은 하위 그래프 객체를 `review` 에이전트로 부른다 | 같음 | `test_joint_review_events_are_the_same_as_single`, `test_joint_review_through_chat_on_the_multi_graph_waits_for_approval_and_resumes` |
| 사람 승인(interrupt)과 `/approvals` 재개 | 같은 thread에서 `Command(resume=...)` | 앱이 `app.state.review_graph`에 질문 그래프(멀티)를 두고 같은 방식으로 재개한다 | 같음 | `tests/test_multi_graph.py` `test_approval_route_resumes_when_app_state_review_graph_is_the_multi_graph`, `test_approval_route_retries_a_failed_save_through_the_multi_graph` |
| 결정표(승인된 결정표 실행) | `decision_params` → `decision_run` → `decision_answer` | 같은 3노드를 `decision` 에이전트로 부른다 | 같음 | `tests/test_multi_graph.py` `test_decision_route_goes_to_the_decision_agent_and_ends_exactly_like_single`, `tests/test_chat_final_from_stream_paths.py` |
| 입력 쪽 방어(신뢰하지 않는 자료 표시, 질문 속 지시 문장 처리) | 검색·분류·답 작성 노드 안 | 같은 노드 | 같음 | 이벤트 비교 시험의 내부 설정 질문 사례 |
| 출력 검사(답 문장 검사, 한국어 출력 자리 규칙 `output_ko`) | 답은 인용 검사·근거 판정 노드, 되묻기는 `give_up` 노드, 거절 사유는 판정·검색 노드에서 `untrusted`의 같은 함수(`scrub_answer`, `leaks_instruction`)를 부른다 | 같은 노드를 부른다(`give_up`·`out_of_domain`은 Supervisor가 `run_single_node`로, 판정·검색은 검색 에이전트 안에서). 멀티 전용 출력 경로는 없다. 따라서 `untrusted.py`의 검사를 되묻기·거절 글까지 넓히면 멀티에도 그대로 걸린다 | 같음 | 이벤트 비교 시험의 출력 자리 지시 사례(답, 되묻기 두 경우. 이어 붙인 문구가 든 문장이 두 경로 모두 빠진다), `test_every_single_graph_node_runs_on_the_multi_path`(단일 그래프에 노드가 새로 생기면 멀티 배선이 빠진 채로 통과하지 못한다) |
| 인용 후처리(`answer_fixes`: 인용 넓히기, 문장 공유 인용, 겹친 머리 바로잡기 등) | 답 작성·근거 판정 노드 안 | 같은 노드 | 같음 | `tests/test_answer_fixes_graph.py`(단일·멀티) |
| 판정 다수결과 셋째 표 대기 상한(`GRAPH_JUDGE_VOTE`, `GRAPH_NONE_VOTE_WAIT_S`, 함께 배포될 지연 수정 `GRAPH_SPLIT_VOTE_WAIT_S`) | `build_graph` 안의 `voted` 함수 | 멀티는 `build_graph`가 만든 같은 `judge` 노드를 쓰므로 같은 `voted` 함수가 돈다. 지연 수정이 `build.py`·`answer_fixes.py`에 들어가면 멀티에도 그대로 걸린다. 서비스 값 `GRAPH_SPLIT_VOTE_WAIT_S=1.0`은 `service_profile.SERVICE_ENV`와 `.env.example`에 넣었다 | 같음 | `multi.py` `SingleParts`, `tests/test_judge_vote.py`(단일·멀티) |
| 서비스 설정 61.51의 나머지 스위치(병렬 접수, 미리 돌리기, 답 두 번 쓰기 등) | 환경 변수를 읽는 노드 | 같은 노드, 같은 환경 변수 | 같음 | 서비스 설정을 채운 가짜 모델 비교 실행(최종 상태 전체 비교) |
| 비용 상한(`LLM_COST_CAP_USD`, `CostCapExceeded`) | `run_config`의 비용 집계 콜백, 예외는 `limit_exceeded` | 콜백이 Supervisor와 하위 에이전트 안 호출에 모두 전달되고 예외를 삼키지 않는다 | 같음 | `test_cost_cap_ends_with_limit_exceeded_on_both_graphs`(검색, 분류, 답 작성에서), `tests/test_multi_graph.py` `test_callbacks_reach_nodes_inside_sub_agents`, `test_cost_cap_passes_through_the_router` |
| 출력 토큰 상한(`LLM_MAX_TOKENS`, 기본 2500) | 모델을 만들 때 건다 | 같은 `SharedChatModel`을 넘긴다 | 같음 | `test_service_graph_follows_the_switch_with_the_same_arguments` |
| 하루 질문 한도(`DAILY_QUESTION_LIMIT`) | 바깥 이름공간의 입력 체크포인트 수 | 하위 에이전트 체크포인트는 하위 이름공간이라 세지 않는다. 질문 하나가 한 건 | 같음 | `test_daily_limit_counts_one_per_question_on_the_multi_graph` |
| Langfuse 추적(콜백, 사용자·세션 메타데이터, 실행 표지) | `run_config` | 같은 설정이 하위 에이전트 안 호출까지 간다 | 같음(추적 화면의 계층은 다름) | `test_llm_calls_carry_the_single_node_names_and_the_run_metadata` |
| 스트림 값으로 최종 상태 쓰기(`CHAT_FINAL_FROM_STREAM`) | 노드 갱신을 합친 값 | 같다 | 같음 | `tests/test_chat_final_from_stream_paths.py` |
| 키 없는 데모(녹화 재생) | 서비스 설정으로 같은 그래프 | 멀티로 돈다. 같은 노드가 같은 순서로 같은 프롬프트를 보내므로 녹화 열쇠가 같다 | 같음(재생 결과는 아래) | 아래 "검증" |
| LLM 호출 수 | 단일 그래프 노드의 호출 | 코드 라우팅은 호출을 더하지 않는다 | 같음 | `tests/test_multi_graph.py` `test_multi_ends_exactly_like_single`(호출 순서와 프롬프트 입력까지 비교) |

## 같게 만들 수 없던 것

| 항목 | 차이 | 영향 |
|---|---|---|
| 체크포인트 행 수 | 하위 에이전트(검색, 작성, 검증, 결정표)가 바깥 그래프의 체크포인터를 물려받아 자기 단계 체크포인트를 하위 이름공간(`retriever:<task id>` 등)에 따로 남긴다. 정책 질문 하나에 바깥 체크포인트 외에 하위 체크포인트가 더 쌓인다 | 저장 행이 늘어난다. 하루 한도, 대화 이력, 재개는 바깥 이름공간만 읽어 결과가 같다. 응답 시간 영향은 유료 재측정에서 확인한다(사전 등록 메모의 p95 기준) |
| 상태 칸 | 멀티에만 `next_agent`, `agent_trace`, `supervisor_log`, `handoffs`, `kind_node`가 있다 | `/chat` 응답에는 싣지 않는다. 체크포인트와 MCP 실행 기록 도구(`get_trace`)에만 남는다 |
| Langfuse 추적의 계층 | 에이전트 노드(`supervisor`, `retriever`, `writer`, `verifier`)가 한 단계 더 보인다 | 단계별 비용 이름(`cost_by_step`)은 단일과 같다 |
| 재개 스트림의 `as_of` | 승인 뒤 재개를 스트림으로 보내면 인터럽트 앞 노드가 쓴 칸이 스트림 값에 없다 | 단일과 같은 알려진 한계이다. `/chat`은 재개를 스트림으로 보내지 않는다(`tests/test_chat_final_from_stream_paths.py`) |

## 검증

- 새 시험: `tests/test_chat_multi_switch.py`(스위치 기본값과 서비스 값, 틀린 값 오류, 같은 인자 전달, `/chat` 이벤트 7가지 사례 대조, 거절 단계 이름, 재시작 뒤 대화, 대화 이력, 합동 검토 승인 대기와 재개, 비용 상한 3곳, 하루 한도, LLM 기록의 노드 이름과 실행 표지, 판정 표 기록).
- 고친 시험: `tests/test_service_profile.py`(서비스 값에 `QUESTION_GRAPH_MODE=multi`, 서비스 앱이 멀티 그래프를 만들고 승인 재개 그래프가 같은 객체인지), `tests/test_multi_graph.py`(멀티 전용 칸 목록에 `kind_node`).
- 전체 시험, 키 없는 데모 녹화 대조, 50건 재생 비교 결과는 이 폴더의 `README.md`에 적는다.
