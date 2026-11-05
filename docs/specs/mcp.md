# Spec — FastMCP 읽기 전용 도구 3개 (박진형, 업무 분담 6번 · 가산 MCP·Skill)

> 2026-11-03판(구현과 같이 고침, 조장 확인 전). SDD 2-3절(도구 3개·쓰기 금지·`SEARCH_VIA_MCP`·토큰·Langfuse), 486줄(시험), 501줄(섹션 조회), 529줄(같은 서비스)과 PRD 319줄(`fastmcp` 4.x)을 따른다. 설계 근거와 강의 출처는 박진형 설계안(개인 공부 폴더)에 있고, 여기에는 팀이 지킬 약속만 적는다. 기본값으로 정한 곳은 "(기본값, 리뷰에서 확인)"으로 표시했다.

## Why

- **페르소나**: 질문·리콜 그래프(김승욱), 그리고 "RAG 검색을 FastMCP 서버로 노출하고 에이전트가 MCP 클라이언트로 호출하는지"를 확인하는 평가자(가이드 p.20)
- **상황**: 검색(`search()`)·증분 수집(`changed_articles`)은 머지됐지만 서버 안 파이썬 함수로만 부를 수 있다. 리콜은 "같은 섹션의 개정 전후 원문"이 필요한데(SDD 501줄 3-4) 섹션 하나를 통째로 돌려주는 함수가 없다.
- **문제**:
  1. 바깥 클라이언트(에이전트, Claude Code 같은 IDE)가 우리 검색을 표준 방식으로 부를 길이 없다. 가산 MCP·Skill의 인정 조건이다.
  2. DB 청크 글은 `머리말 + 앞 청크 끝 겹침(최대 120자) + 본문`이라(`chunk.py:95`) 그대로 이으면 겹친 글이 두 번 나온다. 섹션 원문을 되살리는 규칙이 정해져 있지 않다.
  3. 글만 돌려주는 도구는 "못 찾음"·"고장"을 그럴듯한 문장으로 감춘다. 에이전트가 다음 행동을 고를 상태값이 필요하다.
- **측정 지표**: MCP 경로와 직접 호출의 결과 일치(평가셋 v1 30문항, chunk_id 순서까지), `get_section` 원문 대조 일치 수(3건 이상), MCP 경로가 더하는 지연(p50·p95), 출력에 비공개 주소가 나온 수(0)

## Goal

- **해결 목표**: 검색·섹션 조회·바뀐 섹션 목록을 읽기 전용 MCP 도구 3개로 연다. 도구는 `backend/rag/` 함수를 감싸기만 하고 검색 로직을 다시 짜지 않는다. 쓰기·실행 도구는 내보내지 않는다.
- **성공 기준**
  - 도구는 정확히 3개(`search_handbook`, `get_section`, `list_changed_sections`)이고 이름·입력 이름은 ASCII만 쓴다.
  - MCP로 부른 `search_handbook` 결과 = `search()` 직접 호출 결과(chunk_id 순서까지, v1 30문항 30/30).
  - `get_section`이 되살린 본문은 청크마다 sha256이 `chunks.text_sha256`과 같고, 섹션 3개 이상을 파싱 결과와 글자 단위로 대조해 같다.
  - `list_changed_sections`를 불러도 `changed_articles`가 바뀌지 않는다(호출 전후 표 지문이 같음).
  - 빈 결과·틀린 입력·DB 끊김을 각각 다른 `status`로 돌려준다.
  - `MCP_TOKEN`이 비어 있으면 `/mcp`가 열리지 않고, 토큰 없이 부르면 401.
  - 외부 MCP 클라이언트 하나(Claude Code)에서 `search_handbook` 결과가 나온다(SDD 486줄, 시연 영상용).
- **Out of Scope**: 그래프 쪽 MCP 클라이언트와 `SEARCH_VIA_MCP` 스위치(김승욱, SDD 78줄), 런타임 Skill과 Skill 유무 점수 비교(김승욱), 운영용 OAuth, MCP resource·prompt, 인젝션 시험(D7 인젝션 시험 문서에서)

## What

**Happy Path**
1. 앱이 뜰 때 `MCP_TOKEN`이 있으면 FastAPI 앱 `/mcp`에 MCP 서버를 붙인다(Streamable HTTP, `stateless_http=True`).
2. 클라이언트가 `Authorization: Bearer <MCP_TOKEN>`으로 도구 목록을 받는다. 도구 설명은 5요소(무엇을 / 언제 쓰고 언제 쓰지 말지 / 입력 / 출력 / 제약)를 담는다.
3. `search_handbook(query, org?, as_of?, k?)` → `SearchQuery`로 바꿔 `search()`를 부르고, `Chunk` 목록과 그 검색 기록의 `fallback_reason`(번역 실패로 한국어 벡터만 썼는지, 키가 없는지 `no_key` 등)을 돌려준다. 검색은 voyage-4 영어 문장 벡터·리랭커 없음·뒤 2자리 링크 확장(`docs/specs/search.md`). Voyage API 연결 오류·시간 초과는 `unavailable`(재시도 가능, note "임베딩 API 연결 실패"), 키·요청 오류(401·403·400)는 `error`. MCP는 `sub_queries`를 넘기지 않는다(분해 LLM을 부르지 않음).
4. `get_section(rule_seq, article, as_of?)` → `get_section()`이 판을 고르고(아래 How 2) 그 섹션 청크를 `seq` 순서로 읽어 겹침을 떼고 이어 붙인다.
5. `list_changed_sections(since, org?, limit?, offset?)` → `list_changed()`가 `changed_articles`에서 `new_version_date >= since`인 줄을 오래된 날짜부터 `limit`개까지 읽고, 마지막 성공 증분 실행(`sync_runs`)의 끝난 시각·커밋·`list_complete`를 함께 돌려준다. 더 있으면 `note`에 "더 있음: offset=N"을 적고, 클라이언트는 그 `offset`으로 이어 받는다(EC-16).
6. 세 도구 모두 같은 응답 모양(How 1)으로 돌려준다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 검색 결과 0개 | `status=not_found`. `ok` + 빈 목록으로 돌려주지 않는다 |
| EC-02 | `get_section`에 없는 섹션 이름 | `not_found` + 그 페이지 같은 판의 섹션 이름 후보(`seq` 순서, 최대 10개) |
| EC-03 | 날짜 형식이 틀림, `k`·`limit`·`offset` 범위 밖, 모르는 `org` | `status=invalid`, `retryable=false`, `note`에 무엇이 틀렸는지. 가까운 값으로 고쳐서 돌리지 않는다 |
| EC-04 | DB 연결 실패(`ConnectionError`, psycopg `OperationalError`·풀 대기 초과)·시간 초과 | `status=unavailable`, `retryable=true`. 예외 글·DB 주소는 응답에 넣지 않고 서버 로그에 종류만 |
| EC-15 | 그 밖의 예외(내부 `ValueError`, 코드·설정 오류 등) | `status=error`, `retryable=false`, 고정 `note`("다시 불러도 같음"). 예외 글은 응답에 넣지 않는다. `invalid`는 서버가 입력을 검사해 직접 만든 오류(`Invalid`)만 — 안쪽에서 난 `ValueError`를 입력 오류로 보지 않는다 (#45 리뷰) |
| EC-16 | 바뀐 섹션이 `limit`보다 많음 | `status=ok` + 앞 `limit`개 + `note`에 "더 있음: offset=N". 한 줄 더 읽어 잘렸는지 안다. 정렬이 날짜·`rule_seq`·`article`·`change_type`·`event_id`로 고정이라 `offset`으로 이어 받으면 겹침·빠짐이 없다. 날짜로 이어 받지 않는 이유: 같은 날 줄이 겹치거나 빠진다 (#45 리뷰) |
| EC-05 | 되살린 본문 지문이 청크 `text_sha256`과 다름 | 틀린 원문을 돌려주지 않는다. `unavailable`이 아니라 `status=error`, `retryable=false`, 서버 로그에 chunk_id |
| EC-06 | 증분 실행 기록이 한 번도 없음 | `status=not_ready`. "바뀐 것 없음"(`ok` + 빈 목록 + 마지막 실행 시각)과 구분한다 |
| EC-07 | 마지막 성공 실행이 `list_complete=false`(삭제 보류) | 결과는 그대로 주고 `list_complete=false`를 응답에 표시한다. 사라진 섹션이 목록에 아직 없을 수 있다 |
| EC-08 | `as_of`가 가장 이른 판보다 앞 | `not_found`(그날 판 없음). 가장 가까운 판으로 바꾸지 않는다 |
| EC-09 | 토큰 없음·틀림·URL 쿼리로 보냄 | 401. 쿼리 토큰은 받지 않는다 |
| EC-10 | `MCP_TOKEN` 빈 값 | `/mcp`를 붙이지 않는다(정적 파일 쪽으로 넘어가 404·405). 앱의 나머지는 그대로 뜬다 |
| EC-11 | 비공개 주소(`internal.gitlab.com`)가 본문에 있는 청크 | 파싱은 권한표 칸만 "비공개"로 바꾼다(`parse.py:149`). 공개 핸드북 본문에도 그 링크가 남아 있다(스냅샷 23,095청크 중 7개). `rule_title`·`article`·`source_url`에는 0개(11/4 스냅샷 전수). 도구가 내보낼 때 `text`·`source_url`과 `get_section`의 섹션 이름 후보(`note`)에서 링크·주소를 `[비공개 문서]`로 바꾼다(SDD 76줄). 검색 순위·섹션 지문 검사는 바꾸기 전 글로 한다 |
| EC-12 | 검색이 번역 실패 등으로 내려감 | `status=ok` + `note`에 `fallback_reason` |
| EC-13 | 쪽 통째 삭제(새 판 없음) | `changed_articles.new_version_date`가 빈 칸이다(`diff.py`). `since`와 비교할 날짜는 그 줄을 적은 날(`created_at`, UTC)로 본다. 안 그러면 사라진 쪽이 목록에 영영 안 나온다 |
| EC-14 | 긴 요소 하나가 청크 둘 이상으로 쪼개진 섹션 | 조각 경계에 줄바꿈이 하나 더 들어간다(글자는 같고 공백만 다름). DB에 청크별 요소 id가 없어 쪼갠 경계인지 알 수 없다. 스냅샷 15,901섹션 중 438개, 나머지 15,463개는 파싱 결과와 글자까지 같다 |

## How

**1. 응답 모양** (세 도구 공통)

```
{
  "status": "ok" | "not_found" | "invalid" | "unavailable" | "not_ready" | "error",
  "retryable": bool,
  "results": [...],        # search_handbook: Chunk 목록 / get_section: Section 하나 또는 [] / list_changed_sections: ChangedArticle 목록
  "as_of": str | null,     # 이 결과가 기준한 날짜(입력 as_of, 또는 현재 판이면 null). 목록 도구는 마지막 성공 실행 끝난 시각
  "source": str,           # 검색·섹션: "handbook" / 목록: "sync_runs:<run_id>@<to_commit>"
  "note": str | null       # fallback_reason, 틀린 입력 설명, list_complete=false 안내, 섹션 이름 후보
}
```

`Section`(섹션 원문 하나)은 계약(`backend/schemas/`)에 넣지 않고 `section.py` 안 모델로 둔다(기본값, 리뷰에서 확인): `rule_seq`, `rule_title`, `article`, `version_id`, `version_date`, `version_date_before`, `text`, `source_url`, `line_start`, `line_end`, `chunk_ids`.

**2. 함수**

| 함수 | 파일 | 하는 일 |
|---|---|---|
| `get_section(rule_seq, article, as_of=None) -> Section \| None` | `backend/rag/retrieve/section.py` | 판 고르기는 search와 같다: `as_of` 없으면 `valid_to IS NULL`, 있으면 `valid_from <= as_of < valid_to`. 그 판의 `(rule_seq, article)` 청크를 `seq` 순서로 읽고, 청크마다 머리말 줄을 떼고, 앞 청크 본문으로 `chunk.overlap_tail(prev, 120)`을 다시 계산해 뗀다(겹침을 어림으로 찾지 않는다). 뗀 본문 sha256 = `text_sha256` 확인 뒤 `"\n"`으로 잇는다. `article`이 없는 페이지(제목 없음)는 `article=None`으로 부른다 |
| `section_names(rule_seq, as_of=None) -> list[str]` | 같은 파일 | EC-02 후보 |
| `list_changed(since, org=None, limit=200, store=None, offset=0) -> (list[ChangedArticle], LastRun \| None, more: bool)` | `backend/rag/ingest/changes.py` | `changed_articles` SELECT만(org는 `docs`로 거름). 기준 날짜 = `new_version_date`, 빈 칸(쪽 통째 삭제)이면 `created_at`의 UTC 날짜(EC-13). 정렬 기준 날짜·`rule_seq`·`article`·`change_type`·`event_id`(쪽 나눔이 흔들리지 않게). `limit + 1`개를 읽어 `more`를 정한다. `LastRun` = `sync_runs`(job `handbook-sync`) 중 `status IN ('succeeded','noop')`인 마지막 줄 |

**3. 서버** (`extras/mcp_skill/mcp_server/server.py`)

- `fastmcp==4.1.4`(PRD 319줄). 템플릿의 `from mcp.server.fastmcp import FastMCP`는 `from fastmcp import FastMCP`로 바꾼다.
- 입력 제한(기본값, 리뷰에서 확인): `query` 1~1,000자, `k` 1~20(기본 5 = `backend/schemas/chunk.py` `DEFAULT_K`, 그래프와 같은 상수), `limit` 1~200(기본 200), `offset` 0~1,000,000(기본 0), 날짜 `YYYY-MM-DD`, `org`는 `docs.org`에 있는 값, `rule_seq` 0~4,294,967,295.
- 도구 하나의 제한 시간 30초(기본값, 리뷰에서 확인). 번역 시간 초과가 15초(`translate.py` `TIMEOUT_S`)라 검색 한 번이 이 안에 끝나고, 로드밸런서 유휴 60초보다 짧다.
- `FastMCP.from_fastapi` 같은 자동 변환은 쓰지 않는다. 로그인·관리 경로까지 도구로 나가기 때문이다.
- 만들지 않는 도구와 이유는 `extras/mcp_skill/NOT_BUILT.md`에 적는다(결정 실행·승인·리콜 확인, `changed_articles.status` 바꾸기, 증분 실행, 아무 SQL, 아무 URL).

**4. 연결과 인증** (`backend/main.py` 몇 줄 — 김승욱 폴더라 리뷰 필요)

- `MCP_TOKEN`이 있을 때만 `app.mount("/mcp", mcp.http_app(path="/", stateless_http=True))`. MCP 앱의 lifespan을 앱 lifespan과 합친다.
- 인증은 Bearer 헤더 하나(정적 토큰. 코퍼스가 공개 핸드북이고 도구가 읽기 전용이라 이번 범위는 이것으로 한다. 운영 OAuth는 Out of Scope). fastmcp `StaticTokenVerifier`는 사전 찾기로 비교해서, 같은 일을 하되 `hmac.compare_digest`로 비교하는 `BearerTokenVerifier`(10줄)를 `server.py`에 둔다.
- 같은 컨테이너 안 그래프가 부를 때 주소는 `http://127.0.0.1:8000/mcp/`. 다른 compose 서비스에서 부르면 서비스 이름(`http://api:8000/mcp/`).

**환경 변수**

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `MCP_TOKEN` | (빈 값) | 비면 `/mcp`를 열지 않는다. `.env`에만 두고 `.env.example`에는 이름만 |
| `DATABASE_URL` | (기존) | 검색과 같은 DB |

**파일**

| 파일 | 내용 | 주인 |
|---|---|---|
| `docs/specs/mcp.md` | 이 Spec | 박진형 |
| `backend/rag/retrieve/section.py`, `tests/test_retrieve_section.py` | `get_section`·`section_names` | 박진형 |
| `backend/rag/ingest/changes.py`, `tests/test_ingest_changes.py` | `list_changed` | 박진형 |
| `extras/mcp_skill/mcp_server/server.py`, `tests/test_mcp_server.py`, `NOT_BUILT.md`, `mcp_skill.md` | 도구 3개(시험은 CI가 도는 `tests/`에 둔다, `pytest.ini` testpaths) | 박진형 |
| `backend/main.py` | `/mcp` 붙이기 | 김승욱 리뷰 |
| `Dockerfile` | `COPY extras/ ./extras/` 한 줄(지금 이미지에 `extras/`가 없다) | 김승욱 리뷰 |
| `backend/requirements.txt`, `.env.example` | `fastmcp==4.1.4`, `MCP_TOKEN=` | 내 줄만 |
| `extras/mcp_skill/mcp_client/client.py`, `tests/test_mcp_client.py` | 클라이언트(아래 "클라이언트" 절). `requirements.txt`에 `langchain[mcp]==1.4.9` 한 줄 | 박진형 (그래프 연결은 김승욱) |

**열린 항목**

1. ~~담당 나눔~~ 정함(11/3): 서버 = 박진형, 그래프 쪽 클라이언트·Skill·점수 비교 = 김승욱
2. ~~순서~~ 정함(11/3): 함수와 서버를 한 PR로 같이 낸다(11/6 가산 판단을 기다리지 않음)
3. `Section`을 계약 밖 모델로 둘지 (위 How 1)
4. MCP 도구 호출이 Langfuse 트레이스에 단계로 보이는지(SDD 79줄): 그래프 쪽 LangChain 콜백으로 잡히면 서버는 기록을 더하지 않고, 안 잡히면 서버에 span을 더한다
5. 배포 호출 제한(#45 리뷰): 지금 `/mcp`는 정적 토큰 하나이고 호출 제한이 없다. `search_handbook`은 호출마다 번역 LLM·Voyage 임베딩 비용이 들 수 있다. 배포에 `MCP_TOKEN`을 넣기 전에 정한다 — 후보: 토큰당 분당 호출 수 상한(앱 미들웨어), 번역 비용 상한(`LLM_COST_CAP_USD`)과 같은 장부 사용. 넣기 전까지 배포에서는 `MCP_TOKEN`을 비워 `/mcp`를 열지 않는다(EC-10)
6. 로그인 미들웨어와 `/mcp`(#45 리뷰): 로그인(`backend/auth.py`)을 `main.py`에 연결할 때 `/mcp`는 사람용 쿠키·CSRF 대상이 아니라 기계용 Bearer 토큰 경로다. 미들웨어가 `/mcp`를 건너뛰고 MCP 서버의 `BearerTokenVerifier`만 쓰는 안을 기본으로 하고, 연결 PR에서 확정한다

7. `search_handbook`에 `sub_queries` 칸이 없다(2026-11-05 클라이언트 작성 중 발견). 그래프는 질문 분해 결과를 `SearchQuery.sub_queries`로 `search()`에 넘기는데(PR #48), MCP로 부르면 이 칸을 보낼 곳이 없다. 클라이언트는 몰래 빼지 않고 `invalid`로 거절한다(빼면 직접 `search()`와 결과가 달라진다). `SEARCH_VIA_MCP`로 그래프를 연결하기 전에 서버 도구에 `sub_queries: list[str] | None`(2~3개, `search.check_query` 검사)을 더한다 — 서버 PR, 김승욱 확인

## 클라이언트 (그래프 쪽 MCP 호출, 2026-11-05 추가)

가산 MCP·Skill은 "에이전트가 MCP 클라이언트로 호출"해야 인정된다(가이드 p.20, PRD 194줄). 서버를 부르는 쪽을 `extras/mcp_skill/mcp_client/client.py`에 둔다. 그래프에 붙이는 일(`SEARCH_VIA_MCP`, SDD 2-3절)은 김승욱이 `backend/graph/build.py`에서 한다 — 이 절은 `build.py`·`search.py`를 고치지 않는다.

- 라이브러리: `langchain[mcp]` 1.4.9(PRD 319줄·SDD 77줄, 베타). `langchain.mcp.MCPAdapter`가 FastMCP `Client` 위에서 MCP 도구를 LangChain `StructuredTool`로 바꾼다(결과의 `structured_content`는 `ToolMessage.artifact`). sandbox에서 `fastmcp==4.1.4`와 같이 설치되는 것을 확인했다(`langchain-core` 1.7.5 이상을 끌어온다). 공식 문서: https://docs.langchain.com/oss/python/langchain/mcp
- `load_tools(target, token)` → LangChain 도구 3개. 에이전트가 도구를 직접 고르게 할 때.
- `search_via_mcp(q: SearchQuery, target, token) -> list[Chunk]` → `search(q)`와 같은 모양. 검색 노드가 `search()` 대신 부르면 된다. 이미 이벤트 루프 안이어도 부를 수 있다(새 스레드). 서버 note(`fallback_reason` 등)는 `last_mcp_note()`.
- 상태 → 결과: `ok` = Chunk 목록, `not_found` = 빈 목록, `unavailable`·연결 실패·시간 초과 = `McpUnavailable`(재시도 가능, `ConnectionError` 하위), `invalid`·`error`·`not_ready` = `McpSearchError`(재시도 불가).
- 주소·토큰: `MCP_URL`(기본 `http://127.0.0.1:8000/mcp/`), `MCP_TOKEN`(Bearer). 문자열 주소는 http(s)만 받는다 — fastmcp는 문자열을 파일 경로로 먼저 읽어 `.py`면 실행하기 때문이다(langchain.mcp도 같은 이유로 막는다). 토큰이 비면 `ValueError`.
- 클라이언트 쪽 호출 시간 제한 35초(서버 도구 30초보다 길게 — 서버가 먼저 `unavailable`로 답하게).

## AC (Given-When-Then)

**AC-01 · 도구는 3개, 읽기 전용**
- GIVEN: `MCP_TOKEN`이 있는 앱
- WHEN: 도구 목록을 받는다
- THEN: 이름이 정확히 `search_handbook`·`get_section`·`list_changed_sections`이고 모두 ASCII. 쓰기·실행 도구가 없다

**AC-02 · MCP 결과 = 직접 호출 결과**
- GIVEN: 평가셋 v1 30문항, 같은 검색 설정
- WHEN: 같은 질문을 MCP `search_handbook`과 `search()`로 부른다
- THEN: chunk_id 순서까지 30/30 같다. CI에서는 가짜 검색기로, DB가 있으면(`TEST_DATABASE_URL`) 진짜로 돈다

**AC-03 · 실패를 상태로 말한다**
- GIVEN: 결과 0개 질문 / 틀린 날짜 / 예외를 내는 가짜 저장소
- WHEN: 각 도구를 부른다
- THEN: 차례로 `not_found` / `invalid`(`retryable=false`) / `unavailable`(`retryable=true`). 응답에 예외 글·DB 주소가 없다

**AC-04 · 섹션 원문을 정확히 되살린다**
- GIVEN: 적재된 DB
- WHEN: 청크가 2개 이상인 섹션 3개를 `get_section`으로 부른다
- THEN: 청크마다 뗀 본문 sha256 = `text_sha256`, 이어 붙인 글 = 파싱 결과의 같은 섹션 요소 글(원문 대조 3건)

**AC-05 · 기준일이면 옛 판**
- GIVEN: 개정 전후 판이 둘 다 있는 섹션(리콜 시험 커밋 `4667e540`, 공개 기한 30→90일)
- WHEN: 개정 전 날짜로 `as_of`를 주고 부른다
- THEN: 옛 판 본문(30일)이 나오고, `as_of` 없이 부르면 새 판(90일)

**AC-06 · 목록 도구는 아무것도 바꾸지 않는다**
- GIVEN: `changed_articles`에 `pending` 줄이 있다
- WHEN: `list_changed_sections`를 두 번 부른다
- THEN: 두 결과가 같고, 호출 전후 표 지문(전체 줄의 `event_id, status` 해시)이 같다

**AC-07 · "아직 모름"과 "바뀐 것 없음"을 가른다**
- GIVEN: (가) `sync_runs`가 빈 DB / (나) 성공 실행은 있고 `since` 뒤 바뀐 섹션 0 / (다) 마지막 성공 실행이 `list_complete=false`
- WHEN: `list_changed_sections`를 부른다
- THEN: (가) `not_ready` / (나) `ok` + 빈 목록 + 마지막 실행 시각 / (다) `note`에 삭제 보류 표시

**AC-08 · 토큰 없이는 못 연다**
- GIVEN: `MCP_TOKEN=abc`인 앱 / `MCP_TOKEN` 빈 앱
- WHEN: 헤더 없이, 틀린 토큰으로, URL 쿼리(`?token=abc`)로 `/mcp`를 부른다 / 빈 앱의 `/mcp`를 부른다
- THEN: 세 경우 모두 401 / MCP 응답이 아니다(정적 파일 쪽으로 넘어가 404·405)

**AC-09 · 비공개 주소를 내보내지 않는다**
- GIVEN: 적재된 DB
- WHEN: 비공개 링크가 있던 페이지(권한표 등)의 섹션을 `get_section`으로 부르고, 전체 청크를 `search_handbook`으로 훑는다
- THEN: 출력 어디에도 `internal.gitlab.com`이 없고 그 자리에 `[비공개 문서]`가 있다

**AC-10 · 시험이 진짜로 잡는다 (변이 확인, `docs/GATES.md` 방식)**
- GIVEN: 겹침 떼기 삭제 / `>=`를 `>`로 / 빈 결과를 `ok`로 / 토큰 비어도 `/mcp` 열기 / 목록 도구가 `status`를 `sent`로 쓰기
- WHEN: 하나씩 넣고 시험을 돌린다
- THEN: 다섯 개 모두 시험이 실패한다

**AC-11 · 외부 클라이언트에서 보인다**
- GIVEN: 로컬 `docker compose up`, `MCP_TOKEN` 설정
- WHEN: Claude Code에 `claude mcp add --transport http` 로 `/mcp/`를 등록하고 핸드북 질문을 한다
- THEN: `search_handbook`이 불리고 청크·출처 URL이 화면에 나온다(시연 영상 캡처)

**AC-C1 · 클라이언트가 도구 3개를 LangChain 도구로 받는다** (`tests/test_mcp_client.py`)
- GIVEN: 가짜 검색기를 넣은 서버(같은 프로세스)
- WHEN: `load_tools()`
- THEN: 이름이 정확히 세 개인 `BaseTool`이 오고, `search_handbook` 호출 결과의 `artifact.structured_content.status`가 `ok`다

**AC-C2 · `search_via_mcp` = 직접 `search()`**
- GIVEN: 같은 가짜 검색기, `query·org·as_of·k`를 채운 `SearchQuery`
- WHEN: `search_via_mcp(q)`와 직접 호출
- THEN: 같은 `Chunk`가 같은 순서로 온다. 서버에 간 입력 네 칸이 같다. `not_found`는 빈 목록, `sub_queries`가 있으면 `invalid`로 거절한다(열린 항목 7)

**AC-C3 · 실패를 재시도 가능과 불가로 나눈다**
- GIVEN: 검색기가 `ConnectionError` / `KeyError`를 낸다, 또는 서버 주소가 닫혀 있다
- WHEN: `search_via_mcp`
- THEN: `ConnectionError`·닫힌 주소 → `McpUnavailable`(retryable) / `KeyError` → `McpSearchError("error")`(retryable 아님)

**AC-C4 · HTTP Bearer 토큰**
- GIVEN: `mcp_http_app(token="abc")`를 ASGI로 붙인 HTTP 클라이언트(네트워크 없음)
- WHEN: 토큰 `abc` / `abd`로 검색
- THEN: `abc`는 결과를 받고, `abd`는 서버 인증이 401로 막는다(재시도 가능 실패로 바꾸지 않는다)
