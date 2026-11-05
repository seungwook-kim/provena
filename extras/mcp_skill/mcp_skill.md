# extras/mcp_skill/ : MCP 서버 (가산)

## 이 폴더가 하는 일

검색을 읽기 전용 MCP 도구 3개(`search_handbook`, `get_section`, `list_changed_sections`)로 연다. 도구는 `backend/rag/`의 함수를 감싸기만 한다. 가산은 MCP와 Skill을 둘 다 해야 인정된다(가이드 p.20).
더해서 승인된 결정표 실행 결과(`explain_decision`, 결정표 실행기 그대로)와 대화의 에이전트 실행 단계(`get_agent_trace`, 체크포인트 읽기)를 읽기 전용으로 연다. 모두 5개.

- 주인: 박진형
- 입력: `SearchQuery`, 페이지 id, 업무 종류·금액, thread_id
- 출력: `Chunk`, 섹션 원문, `ChangedArticle`, 결정표 실행 결과(HTTP 실행 응답과 같은 칸), 실행 단계 요약

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | 읽기 전용 도구 2개 추가(조장 요청, 도구 5개): `explain_decision`(`decision_tool.py`, 그래프·HTTP와 같은 `DecisionExecutor.run`을 그대로 부르고 HTTP `RunResponse` 칸만 내보냄, 승인자 id 없음, 실행기 오류 → 상태)·`get_agent_trace`(`trace_tool.py`, thread_id로 체크포인트를 읽기만 해 노드 순서·단계 시간·Supervisor 결정·합동 검토 팀 상태·승인 대기, 비용은 기록이 없어 null). 저장소는 `DATABASE_URL`로 처음 부를 때 연다(`server.pg_pool`). 시험 `test_mcp_decision_tool.py` 32개·`test_mcp_trace_tool.py` 17개(실제 그래프·메모리 체크포인터), 변이 6/6. `build.py`·`search.py`·조장 파일은 안 건드림 | 이 PR |
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | #51 리뷰 반영: 서버 `search_handbook`에 `sub_queries`(선택, 2~3개, 개수·길이가 틀리면 `invalid`) 칸, 클라이언트는 그대로 보냄(열린 항목 7 닫음). `.env.example`에 `MCP_URL` | 이 PR |
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | MCP 클라이언트 `mcp_client/client.py`(조장 요청, 그래프 연결 전 단계): `langchain[mcp]` 1.4.9 `MCPAdapter`로 도구 3개를 LangChain 도구로(`load_tools`), `search_via_mcp`가 `search()`와 같은 `list[Chunk]`로 돌려줌, `unavailable`·연결 실패는 `McpUnavailable`(재시도 가능), `sub_queries`는 서버 칸이 없어 거절(Spec 열린 항목 7). 시험 `tests/test_mcp_client.py` 12개(같은 프로세스 서버·ASGI로 Bearer 401 확인), 변이 2/2. `build.py`·`search.py`는 안 건드림 | 미정 |
| 2026-11-04 | 박진형 (jinyeong-731, Claude Code) | #45 리뷰 반영: `list_changed_sections`가 limit에서 잘리면 note "더 있음: offset=N"과 `offset` 입력(정렬 끝에 `event_id`), 실패를 unavailable(시간 초과·연결 실패만)·error(그 밖, retryable=false, 예외 글 없음)·invalid(서버 입력 검사만)로 나눔, 섹션 이름 후보도 비공개 주소 가림, Spec EC-15·16·열린 항목 5·6. 시험 3파일 78개(DB 포함), 변이 16/16 | #45 |
| 2026-11-03 | 박진형 (jinyeong-731, Claude Code) | FastMCP 4.1.4 읽기 전용 도구 3개(`search_handbook`·`get_section`·`list_changed_sections`), 공통 응답 모양(status·retryable), 비공개 주소 `[비공개 문서]` 표시, Bearer 토큰(`hmac.compare_digest`), `MCP_TOKEN` 있을 때만 `/mcp/`, `NOT_BUILT.md`. 시험 `tests/test_mcp_server.py` 36개 + 변이 확인 | (이번 PR) |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
