# extras/mcp_skill/ : MCP 서버 (가산)

## 이 폴더가 하는 일

검색을 읽기 전용 MCP 도구 3개(`search_handbook`, `get_section`, `list_changed_sections`)로 연다. 도구는 `backend/rag/`의 함수를 감싸기만 한다. 가산은 MCP와 Skill을 둘 다 해야 인정된다(가이드 p.20).

- 주인: 박진형
- 입력: `SearchQuery`, 페이지 id
- 출력: `Chunk`, 섹션 원문, `ChangedArticle`

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-05 | 박진형 (jinyeong-731, Claude Code) | MCP 클라이언트 `mcp_client/client.py`(조장 요청, 그래프 연결 전 단계): `langchain[mcp]` 1.4.9 `MCPAdapter`로 도구 3개를 LangChain 도구로(`load_tools`), `search_via_mcp`가 `search()`와 같은 `list[Chunk]`로 돌려줌, `unavailable`·연결 실패는 `McpUnavailable`(재시도 가능), `sub_queries`는 서버 칸이 없어 거절(Spec 열린 항목 7). 시험 `tests/test_mcp_client.py` 12개(같은 프로세스 서버·ASGI로 Bearer 401 확인), 변이 2/2. `build.py`·`search.py`는 안 건드림 | 미정 |
| 2026-11-04 | 박진형 (jinyeong-731, Claude Code) | #45 리뷰 반영: `list_changed_sections`가 limit에서 잘리면 note "더 있음: offset=N"과 `offset` 입력(정렬 끝에 `event_id`), 실패를 unavailable(시간 초과·연결 실패만)·error(그 밖, retryable=false, 예외 글 없음)·invalid(서버 입력 검사만)로 나눔, 섹션 이름 후보도 비공개 주소 가림, Spec EC-15·16·열린 항목 5·6. 시험 3파일 78개(DB 포함), 변이 16/16 | #45 |
| 2026-11-03 | 박진형 (jinyeong-731, Claude Code) | FastMCP 4.1.4 읽기 전용 도구 3개(`search_handbook`·`get_section`·`list_changed_sections`), 공통 응답 모양(status·retryable), 비공개 주소 `[비공개 문서]` 표시, Bearer 토큰(`hmac.compare_digest`), `MCP_TOKEN` 있을 때만 `/mcp/`, `NOT_BUILT.md`. 시험 `tests/test_mcp_server.py` 36개 + 변이 확인 | (이번 PR) |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
