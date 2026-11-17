# 결과: 하위 에이전트 체크포인트 끄기 — 0원 로컬 확인에서 멈춤 (2026-11-17)

사전 등록: 같은 폴더 `PREREGISTER.md`(`17fff26c`, 보충 `794ddd1e`). 코드는 커밋하지 않았고, 배포와 유료 측정은 하지 않았다(비용 0).

## 결론

사전 등록한 변경(검색·작성·검증·결정표 하위 에이전트를 `compile(checkpointer=False)`)은 재개 시험 1건이 실패해, 사전 등록한 멈춤 규칙("재개·승인·합동 검토·멀티 그래프 시험 중 하나라도 실패하면 이 변경을 버린다")에 따라 버렸다. 운영 판은 그대로 `provena-api-00205-zit`다.

## 코드 수정 전 확인

- 네 에이전트 안의 노드(rewrite, search, judge, write_answer, verify, ground, save, decision_params, decision_run, decision_answer)는 `interrupt()`, `Command(resume=...)`, `get_state`를 쓰지 않는다. `interrupt()`는 합동 검토(`backend/graph/departments/review.py`)와 결정표 변환 그래프(`backend/graph/decision/convert.py`, 질문 그래프 밖)에만 있다.
- 하위 이름공간 체크포인트를 읽는 곳: 하루 질문 한도와 대화 이력은 바깥 이름공간만 읽는다. 다만 MCP 읽기 도구 `get_agent_trace`(`extras/mcp_skill/mcp_server/trace_tool.py`, 명세 `docs/specs/mcp.md` AC-T1)가 하위 이름공간을 읽어 에이전트 안의 노드 단계를 보여 준다. 분석 메모의 "이를 읽는 곳은 없다"는 이 도구를 빠뜨린 것이다.

## 0원 로컬 확인 (가짜 모델·가짜 검색기, 로컬 Postgres 컨테이너 `postgres:17`, 질문 1건: 검색 -> 작성 -> 검증, 3회)

| | 바꾸기 전 | 사전 등록 변경(`checkpointer=False`) | 참고: 등록하지 않은 대안(하위 에이전트 실행만 `durability="exit"`) |
|---|---|---|---|
| 체크포인터 호출 | 45 (바깥 19, 하위 26) | 19 (바깥 19, 하위 0) | 22 (바깥 19, 하위 3: 에이전트마다 시작 때 읽기 1) |
| 하위 호출 내역 | 읽기 3, put 13, put_writes 10 | 0 | 읽기 3 |
| 남은 체크포인트 | 바깥 9, 하위 13 | 바깥 9 | 바깥 9 |
| 결과 종류·답 해시·인용·agent_trace | answer, 기준 | 같음 | 같음 |
| 로컬 그래프 실행 시간 | 0.079~0.087초 | 0.042~0.050초 | 0.044~0.055초 |

## 시험

| 묶음 | 사전 등록 변경 | 참고 대안 |
|---|---|---|
| 멀티·재개·승인·합동 검토·결정표·MCP trace 시험 13개 파일(1,041개) | 2 실패, 1,038 통과, 1 건너뜀 | `test_multi_graph.py`, `test_mcp_trace_tool.py`만 돌림: 1 실패, 675 통과 |
| `test_multi_graph.py::test_resume_after_an_interrupt_inside_an_agent_is_not_a_new_question` | 실패: 에이전트 안 interrupt 뒤 재개하면 에이전트를 처음부터 다시 돌아 재작성 LLM 호출이 1회 늘었다(기대 classify, rewrite, judge, answer) | 통과 |
| `test_mcp_trace_tool.py::test_multi_graph_supervisor_decisions_and_agents` | 실패: 에이전트 안 노드 단계가 사라진다(알려진 대가) | 실패(같은 이유) |

전체 pytest는 멈춤 규칙에 걸린 뒤라 돌리지 않았다.

## 남은 판단 (메인 세션)

- 참고 대안은 재개 시험을 통과하고 하위 호출 26회 중 23회를 없앤다. 사전 등록하지 않은 변경이라 쓰려면 새로 등록하고 승인을 받아야 한다. MCP `get_agent_trace`의 에이전트 안 노드 단계가 사라지는 대가는 두 방식에 같다.
- 로컬 DB 왕복은 1ms 안팎이라 운영 효과(약 0.2초 추정)는 로컬 숫자로 확인되지 않는다. 운영 효과는 트래픽 0% 판 측정으로만 확인된다.
