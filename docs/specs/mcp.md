# Spec — FastMCP 읽기 전용 도구 6개 (박진형, 업무 분담 6번 · 가산 MCP·Skill)

> 2026-11-06: 팀장 결정(결정 0062)으로 저장된 답의 근거 판정 기록(`get_grounding`) 도구 1개를 더했다(아래 "도구 6" 절). 도구 수가 강의 실습 목표(워크플로 도구 3~5개, AI Agent 4. MCP_Server 03강·07강)를 하나 넘는다(열린 항목 10). 다른 도구 5개의 약속은 그대로다.
> 2026-11-05: 조장 요청으로 결정표 실행 결과(`explain_decision`)·체크포인트 실행 단계(`get_agent_trace`) 도구 2개를 더했다(아래 "도구 4·5" 절). 검색 도구 3개의 약속은 그대로다.
> 2026-11-03판(구현과 같이 고침, 조장 확인 전, 당시 검색 도구 3개 기준이며 현재 도구는 6개). SDD 2-3절(도구 3개·쓰기 금지·`SEARCH_VIA_MCP`·토큰·Langfuse), 10장 "MCP 경로 결과 일치"(시험), 11-1 결정 3-4(섹션 조회), 11-3 "MCP 서버 위치"(같은 서비스)와 PRD 9장 기술 구성의 mcp 행(`fastmcp` 4.x)을 따른다. 설계 근거와 강의 출처는 박진형 설계안(개인 공부 폴더)에 있고, 여기에는 팀이 지킬 약속만 적는다. 기본값으로 정한 곳은 "(기본값, 리뷰에서 확인)"으로 표시했다.

## Why

- **페르소나**: 질문·리콜 그래프(김승욱), 그리고 "RAG 검색을 FastMCP 서버로 노출하고 에이전트가 MCP 클라이언트로 호출하는지"를 확인하는 평가자(가이드 p.20)
- **상황**: 검색(`search()`)·증분 수집(`changed_articles`)은 머지됐지만 서버 안 파이썬 함수로만 부를 수 있다. 리콜은 "같은 섹션의 개정 전후 원문"이 필요한데(SDD 11-1 결정 3-4) 섹션 하나를 통째로 돌려주는 함수가 없다.
- **문제**:
  1. 바깥 클라이언트(에이전트, Claude Code 같은 IDE)가 우리 검색을 표준 방식으로 부를 길이 없다. 가산 MCP·Skill의 인정 조건이다.
  2. DB 청크 글은 `머리말 + 앞 청크 끝 겹침 + 본문`이다(`chunk.make_chunk`). 겹침은 일반 글이면 최대 120자, 표 행 안에서 시작하면 그 행 처음부터 최대 400자다(`chunk.overlap_for`, `ROW_TAIL_MAX`). 그래서 그대로 이으면 겹친 글이 두 번 나온다. 섹션 원문을 되살리는 규칙이 정해져 있지 않다.
  3. 글만 돌려주는 도구는 "못 찾음"·"고장"을 그럴듯한 문장으로 감춘다. 에이전트가 다음 행동을 고를 상태값이 필요하다.
- **측정 지표**: MCP 경로와 직접 호출의 결과 일치(평가셋 v1 30문항, chunk_id 순서까지), `get_section` 원문 대조 일치 수(3건 이상), MCP 경로가 더하는 지연(p50·p95), 출력에 비공개 주소가 나온 수(0)

## Goal

- **해결 목표**: 검색·섹션 조회·바뀐 섹션 목록을 읽기 전용 MCP 도구로 연다(검색 3개로 시작해 현재 6개, 아래 "도구 4·5"·"도구 6" 절). 도구는 `backend/rag/` 함수를 감싸기만 하고 검색 로직을 다시 짜지 않는다. 쓰기·실행 도구는 내보내지 않는다.
- **성공 기준**
  - 도구는 정확히 6개(검색 `search_handbook`, `get_section`, `list_changed_sections` + `explain_decision`, `get_agent_trace`, `get_grounding`)이고 이름·입력 이름은 ASCII만 쓴다. 6개는 강의 실습 목표(AI Agent 4. MCP_Server 03강 학습 목표 "도구를 3~5개로 다시 설계했다."·07강 과제 "워크플로 단위 도구 3~5개")를 하나 넘는다. 강의는 도구 수보다 사용자 작업 단위와 같은 조건 A/B 평가로 판단하라고 한다(00강 "좋은 MCP 서버는 도구 수가 아니라, 사용자의 작업과 평가 결과로 판단합니다."·03강 "도구 수 축소가 선택을 개선하는지는 외부 사례가 아니라 같은 조건의 A/B로 확인합니다."). `get_grounding`은 팀장 결정(결정 0062)으로 더했고, 도구 선택이 나빠지는지는 열린 항목 10에서 본다. 더 늘리려면 다른 도구를 줄이거나 합칠지 먼저 본다.
  - MCP로 부른 `search_handbook` 결과 = `search()` 직접 호출 결과(chunk_id 순서까지, v1 30문항 30/30).
  - `get_section`이 되살린 본문은 청크마다 sha256이 `chunks.text_sha256`과 같고, 섹션 3개 이상을 파싱 결과와 글자 단위로 대조해 같다.
  - `list_changed_sections`를 불러도 `changed_articles`가 바뀌지 않는다(호출 전후 표 지문이 같음).
  - 빈 결과·틀린 입력·DB 끊김을 각각 다른 `status`로 돌려준다.
  - `MCP_TOKEN`이 비어 있으면 `/mcp`가 열리지 않고, 토큰 없이 부르면 401.
  - 토큰은 둘로 나눈다(2026-11-17): 서비스 자신의 검색(`SEARCH_VIA_MCP`)이 쓰는 내부 토큰 `MCP_TOKEN`은 호출 수 제한이 없고, 외부 MCP 클라이언트용 `MCP_EXTERNAL_TOKEN`(선택)으로 온 `tools/call`은 분당 `MCP_EXTERNAL_RATE_PER_MIN`(기본 30)·하루 `MCP_EXTERNAL_RATE_PER_DAY`(기본 500, KST 자정 기준)를 넘으면 429.
  - 외부 MCP 클라이언트 하나(Claude Code)에서 `search_handbook` 결과가 나온다(SDD 10장 "MCP 경로 결과 일치", 시연 영상용).
- **Out of Scope**: 그래프 쪽 MCP 클라이언트와 `SEARCH_VIA_MCP` 스위치(김승욱, SDD 2-3절), 런타임 Skill과 Skill 유무 점수 비교(김승욱), 운영용 OAuth, MCP resource·prompt, 인젝션 시험(D7 인젝션 시험 문서에서)

## What

**Happy Path**
1. 앱이 뜰 때 `MCP_TOKEN`이 있으면 FastAPI 앱 `/mcp`에 MCP 서버를 붙인다(Streamable HTTP, `stateless_http=True`).
2. 클라이언트가 `Authorization: Bearer <MCP_TOKEN>`으로 도구 목록을 받는다. 도구 설명은 5요소(무엇을 / 언제 쓰고 언제 쓰지 말지 / 입력 / 출력 / 제약)를 담는다.
3. `search_handbook(query, org?, as_of?, k?)` → `SearchQuery`로 바꿔 `search()`를 부르고, `Chunk` 목록과 그 검색 기록의 `fallback_reason`(번역 실패로 한국어 벡터만 썼는지, 키가 없는지 `no_key` 등)을 돌려준다. 검색은 voyage-4 영어 문장 벡터·리랭커 없음·뒤 2자리 링크 확장(`docs/specs/search.md`). Voyage API 연결 오류·시간 초과는 `unavailable`(재시도 가능, note "임베딩 API 연결 실패"), 키·요청 오류(401·403·400)는 `error`. `sub_queries`(선택, 2~3개)를 주면 `SearchQuery.sub_queries`로 그대로 넘긴다 — 분해는 부르는 쪽(그래프)이 하고 서버는 분해 LLM을 부르지 않는다. 개수·길이가 틀리면 `search()` 전에 `invalid`(열린 항목 7).
4. `get_section(rule_seq, article, as_of?)` → `get_section()`이 판을 고르고(아래 How 2) 그 섹션 청크를 `seq` 순서로 읽어 겹침을 떼고 이어 붙인다.
5. `list_changed_sections(since, org?, limit?, offset?)` → `list_changed()`가 `changed_articles`에서 `new_version_date >= since`인 줄을 오래된 날짜부터 `limit`개까지 읽고, 마지막 성공 증분 실행(`sync_runs`)의 끝난 시각·커밋·`list_complete`를 함께 돌려준다. 더 있으면 `note`에 "더 있음: offset=N"을 적고, 클라이언트는 그 `offset`으로 이어 받는다(EC-16).
6. 세 도구 모두 같은 응답 모양(How 1)으로 돌려준다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 검색 결과 0개 | `status=not_found`. `ok` + 빈 목록으로 돌려주지 않는다 |
| EC-02 | `get_section`에 없는 섹션 이름 | `not_found` + 그 페이지 같은 판의 섹션 이름 후보(`seq` 순서, 최대 10개) |
| EC-03 | 날짜 형식이 틀림, `k`·`limit`·`offset` 범위 밖, 모르는 `org`, 글 입력(`query`·`sub_queries`·`article`·`table_id`·`answer_id`)에 제어문자(탭·줄바꿈·CR 제외)나 짝 없는 서로게이트 | `status=invalid`, `retryable=false`, `note`에 무엇이 틀렸는지. 가까운 값으로 고쳐서 돌리지 않는다 |
| EC-04 | DB 연결 실패(`ConnectionError`, psycopg `OperationalError`·풀 대기 초과)·시간 초과 | `status=unavailable`, `retryable=true`. 예외 글·DB 주소는 응답에 넣지 않고 서버 로그에 종류만 |
| EC-15 | 그 밖의 예외(내부 `ValueError`, 코드·설정 오류 등) | `status=error`, `retryable=false`, 고정 `note`("다시 불러도 같음"). 예외 글은 응답에 넣지 않는다. `invalid`는 서버가 입력을 검사해 직접 만든 오류(`Invalid`)만 — 안쪽에서 난 `ValueError`를 입력 오류로 보지 않는다 (#45 리뷰) |
| EC-16 | 바뀐 섹션이 `limit`보다 많음 | `status=ok` + 앞 `limit`개 + `note`에 "더 있음: offset=N". 한 줄 더 읽어 잘렸는지 안다. 정렬이 날짜·`rule_seq`·`article`·`change_type`·`event_id`로 고정이라 `offset`으로 이어 받으면 겹침·빠짐이 없다. 날짜로 이어 받지 않는 이유: 같은 날 줄이 겹치거나 빠진다 (#45 리뷰) |
| EC-05 | 되살린 본문 지문이 청크 `text_sha256`과 다름 | 틀린 원문을 돌려주지 않는다. `unavailable`이 아니라 `status=error`, `retryable=false`, 서버 로그에 chunk_id |
| EC-06 | 증분 실행 기록이 한 번도 없음 | `status=not_ready`. "바뀐 것 없음"(`ok` + 빈 목록 + 마지막 실행 시각)과 구분한다 |
| EC-07 | 마지막 성공 실행이 `list_complete=false`(삭제 보류) | 결과는 그대로 주고 `list_complete=false`를 응답에 표시한다. 사라진 섹션이 목록에 아직 없을 수 있다 |
| EC-08 | `as_of`가 가장 이른 판보다 앞 | `not_found`(그날 판 없음). 가장 가까운 판으로 바꾸지 않는다 |
| EC-09 | 토큰 없음·틀림·URL 쿼리로 보냄 | 401. 쿼리 토큰은 받지 않는다 |
| EC-10 | `MCP_TOKEN` 빈 값 | `/mcp`를 붙이지 않는다(정적 파일 쪽으로 넘어가 404·405). 앱의 나머지는 그대로 뜬다. `MCP_EXTERNAL_TOKEN`만 있어도 열지 않는다 |
| EC-17 | 외부 토큰(`MCP_EXTERNAL_TOKEN`)으로 온 `tools/call`이 분당·하루 한도를 넘음 | 429 + `Retry-After`(분 창은 남은 초, 하루 창은 다음 KST 자정까지 초), 본문 `{"error": "rate_limited", "error_description": <한국어 안내>}`(401 본문과 같은 꼴). 넘은 호출은 세지 않는다. `initialize`·`tools/list`는 세지 않고, 묶음 요청은 그 안의 `tools/call` 수만큼 센다. 내부 토큰 `MCP_TOKEN`은 세지 않는다. 외부 토큰이 비면 외부 토큰이 없을 뿐 `MCP_TOKEN`은 전과 같고, 두 값이 같으면 외부 토큰을 쓰지 않는다(경고 로그) |
| EC-11 | 비공개 주소(`internal.gitlab.com`)가 본문에 있는 청크 | 파싱은 표 칸 글자가 모두 비공개 주소 링크면 그 칸 번호만 기록하고 글자는 바꾸지 않는다(`parse.private_cell`이 판정하고 `parse.table_rows`가 `private_cells`에 기록). 공개 핸드북 본문에도 그 링크가 남아 있다(스냅샷 23,095청크 중 7개). `rule_title`·`article`·`source_url`에는 0개(11/4 스냅샷 전수). 도구가 내보낼 때 `text`·`source_url`과 `get_section`의 섹션 이름 후보(`note`)에서 링크·주소를 `[비공개 문서]`로 바꾼다(SDD 2-3절·9장). 검색 순위·섹션 지문 검사는 바꾸기 전 글로 한다. 가리는 함수는 그래프와 같은 `backend/rag/retrieve/privacy.py`의 `redact`를 쓴다 |
| EC-12 | 검색이 번역 실패 등으로 내려감 | `status=ok` + `note`에 `fallback_reason` |
| EC-13 | 쪽 통째 삭제(새 판 없음) | `changed_articles.new_version_date`가 빈 칸이다(`diff.py`). `since`와 비교할 날짜는 그 줄을 적은 날(`created_at`, UTC)로 본다. 안 그러면 사라진 쪽이 목록에 영영 안 나온다 |
| EC-14 | 긴 요소 하나가 청크 둘 이상으로 쪼개진 섹션 | 조각 경계에 줄바꿈이 하나 더 들어간다(글자는 같고 공백만 다름). DB에 청크별 요소 id가 없어 쪼갠 경계인지 알 수 없다. 스냅샷 15,901섹션 중 438개, 나머지 15,463개는 파싱 결과와 글자까지 같다(515acc3d 이전 기준, 표 행 겹침을 400자까지 바꾼 뒤에는 다시 세지 않았다) |

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
| `get_section(rule_seq, article, as_of=None) -> Section \| None` | `backend/rag/retrieve/section.py` | 판 고르기는 search와 같다: `as_of` 없으면 `valid_to IS NULL`, 있으면 `valid_from <= as_of < valid_to`. 그 판의 `(rule_seq, article)` 청크를 `seq` 순서로 읽고, 청크마다 머리말 줄을 떼고, 앞 청크 본문으로 `section.body_of`가 겹침을 뗀다. 기본은 `chunk.overlap_tail(prev, 120)`을 다시 계산해 떼고, 표 행 겹침(`chunk.overlap_for`, 행 처음부터 최대 400자, 길면 첫 칸 라벨을 앞에 붙임)이라 그 값과 본문 지문이 다르면 청크의 `text_sha256`과 같아지는 줄바꿈 자리를 찾아 뗀다(글자 어림 검색이 아니라 지문 일치로 정한다). 뗀 본문 sha256 = `text_sha256` 확인 뒤 `"\n"`으로 잇는다. `article`이 없는 페이지(제목 없음)는 `article=None`으로 부른다 |
| `section_names(rule_seq, as_of=None) -> list[str]` | 같은 파일 | EC-02 후보 |
| `list_changed(since, org=None, limit=200, store=None, offset=0) -> (list[ChangedArticle], LastRun \| None, more: bool)` | `backend/rag/ingest/changes.py` | `changed_articles` SELECT만(org는 `docs`로 거름). 기준 날짜 = `new_version_date`, 빈 칸(쪽 통째 삭제)이면 `created_at`의 UTC 날짜(EC-13). 정렬 기준 날짜·`rule_seq`·`article`·`change_type`·`event_id`(쪽 나눔이 흔들리지 않게). `limit + 1`개를 읽어 `more`를 정한다. `LastRun` = `sync_runs`(job `handbook-sync`) 중 `status IN ('succeeded','noop')`인 마지막 줄 |

**3. 서버** (`extras/mcp_skill/mcp_server/server.py`)

- `fastmcp==4.1.4`(PRD 9장 기술 구성의 mcp 행). 템플릿의 `from mcp.server.fastmcp import FastMCP`는 `from fastmcp import FastMCP`로 바꾼다.
- 입력 제한(기본값, 리뷰에서 확인): `query` 1~1,000자, `k` 1~20(기본 5 = `backend/schemas/chunk.py` `DEFAULT_K`, 그래프와 같은 상수), `limit` 1~200(기본 200), `offset` 0~1,000,000(기본 0), 날짜 `YYYY-MM-DD`, `org`는 `docs.org`에 있는 값, `rule_seq` 0~4,294,967,295.
- 도구 하나의 제한 시간 30초(기본값, 리뷰에서 확인). 번역 시간 초과가 15초(`translate.py` `TIMEOUT_S`)라 검색 한 번이 이 안에 끝나고, 로드밸런서 유휴 60초보다 짧다.
- `FastMCP.from_fastapi` 같은 자동 변환은 쓰지 않는다. 로그인·관리 경로까지 도구로 나가기 때문이다.
- 만들지 않는 도구와 이유는 `extras/mcp_skill/NOT_BUILT.md`에 적는다(결정 실행·승인·리콜 확인, `changed_articles.status` 바꾸기, 증분 실행, 아무 SQL, 아무 URL).

**4. 연결과 인증** (`backend/main.py` 몇 줄 — 김승욱 폴더라 리뷰 필요)

- `MCP_TOKEN`이 있을 때만 `app.mount("/mcp", mcp.http_app(path="/", stateless_http=True))`. MCP 앱의 lifespan을 앱 lifespan과 합친다.
- 인증은 Bearer 헤더 하나(정적 토큰. 코퍼스가 공개 핸드북이고 도구가 읽기 전용이라 이번 범위는 이것으로 한다. 운영 OAuth는 Out of Scope). fastmcp `StaticTokenVerifier`는 사전 찾기로 비교해서, 같은 일을 하되 `hmac.compare_digest`로 비교하는 `BearerTokenVerifier`를 `server.py`에 둔다. 외부 토큰이 있으면 두 토큰과 늘 비교해 어느 쪽이 맞았는지가 시간 차로 드러나지 않게 한다.
- 외부 토큰 호출 수 제한(`ExternalRateLimiter`, `ExternalRateLimitMiddleware`, `server.py`): MCP 앱 안쪽 미들웨어가 Authorization 헤더를 `hmac.compare_digest`로 외부 토큰과 비교하고, 맞으면 POST 본문의 JSON-RPC `tools/call` 수를 센다. 분당은 지난 60초 창, 하루는 KST 자정 기준이다. 세는 곳은 프로세스 메모리라 인스턴스마다 따로 세고 재시작하면 0부터 다시 센다. 하루 수를 둘 싼 DB 표가 없어(새 표는 마이그레이션이 필요) 메모리로 두었고, 운영은 최대 인스턴스 1개라 사실상 서비스 전체 값이다.
- 같은 컨테이너 안 그래프가 부를 때 주소는 `http://127.0.0.1:8000/mcp/`. 다른 compose 서비스에서 부르면 서비스 이름(`http://api:8000/mcp/`).

**환경 변수**

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `MCP_TOKEN` | (빈 값) | 비면 `/mcp`를 열지 않는다. 서비스 내부 검색용, 호출 수 제한 없음. `.env`에만 두고 `.env.example`에는 이름만 |
| `MCP_EXTERNAL_TOKEN` | (빈 값) | 외부 MCP 클라이언트용 토큰. 비면 외부 토큰이 없다. `MCP_TOKEN`과 다른 값이어야 한다. `.env`에만 |
| `MCP_EXTERNAL_RATE_PER_MIN` | 30 | 외부 토큰의 지난 60초 `tools/call` 수 상한. 0이면 이 창은 제한 없음, 틀린 값은 기본값 |
| `MCP_EXTERNAL_RATE_PER_DAY` | 500 | 외부 토큰의 KST 하루 `tools/call` 수 상한. 0이면 이 창은 제한 없음, 틀린 값은 기본값 |
| `DATABASE_URL` | (기존) | 검색과 같은 DB |

**파일**

| 파일 | 내용 | 주인 |
|---|---|---|
| `docs/specs/mcp.md` | 이 Spec | 박진형 |
| `backend/rag/retrieve/section.py`, `tests/test_retrieve_section.py` | `get_section`·`section_names` | 박진형 |
| `backend/rag/ingest/changes.py`, `tests/test_ingest_changes.py` | `list_changed` | 박진형 |
| `extras/mcp_skill/mcp_server/server.py`, `tests/test_mcp_server.py`, `NOT_BUILT.md`, `mcp_skill.md` | 도구 6개(시험은 CI가 도는 `tests/`에 둔다, `pytest.ini` testpaths) | 박진형 |
| `backend/main.py` | `/mcp` 붙이기 | 김승욱 리뷰 |
| `Dockerfile` | `COPY extras/ ./extras/` 한 줄(반영됨, 동결 코드 `194dfd9a`의 `Dockerfile` 62행) | 김승욱 리뷰 |
| `backend/requirements.txt`, `.env.example` | `fastmcp==4.1.4`, `MCP_TOKEN=` | 내 줄만 |
| `extras/mcp_skill/mcp_client/client.py`, `tests/test_mcp_client.py` | 클라이언트(아래 "클라이언트" 절). `requirements.txt`에 `langchain[mcp]==1.4.9` 한 줄 | 박진형 (그래프 연결은 김승욱) |
| `extras/mcp_skill/mcp_server/decision_tool.py`, `tests/test_mcp_decision_tool.py` | `explain_decision`(아래 "도구 4·5" 절) | 박진형 |
| `extras/mcp_skill/mcp_server/trace_tool.py`, `tests/test_mcp_trace_tool.py` | `get_agent_trace`(아래 "도구 4·5" 절) | 박진형 |
| `extras/mcp_skill/mcp_server/grounding_tool.py`, `tests/test_mcp_new_tools.py` | `get_grounding`(아래 "도구 6" 절). 기록은 `backend/graph/answer_store.py`(`save_grounding`·`get_grounding`)와 `backend/graph/grounding.py`(`public_grounding`) | 김승욱 |

**열린 항목**

1. ~~담당 나눔~~ 정함(11/3): 서버 = 박진형, 그래프 쪽 클라이언트·Skill·점수 비교 = 김승욱
2. ~~순서~~ 정함(11/3): 함수와 서버를 한 PR로 같이 낸다(11/6 가산 판단을 기다리지 않음)
3. `Section`을 계약 밖 모델로 둘지 (위 How 1)
4. MCP 도구 호출이 Langfuse 트레이스에 단계로 보이는지(SDD 2-3절): 그래프 쪽 LangChain 콜백으로 잡히면 서버는 기록을 더하지 않고, 안 잡히면 서버에 span을 더한다. 2026-11-16 운영 반영 뒤 컨테이너 접근 로그로 MCP 호출을 확인했고, 같은 날 운영 Langfuse 트레이스에서 MCP 도구 `search_handbook` 관측이 보이는 것을 확인했다(`EVAL_REPORT.md` 7장 그림 5, 6, 판 `provena-api-00065-q84`)
5. 배포 호출 제한(#45 리뷰): **구현(2026-11-17, 운영 배포 전).** 토큰을 내부 `MCP_TOKEN`(서비스 자신, 제한 없음)과 외부 `MCP_EXTERNAL_TOKEN`(선택, 분당 30회·하루 500회, 넘으면 429)으로 나눴다(EC-17, AC-11, `tests/test_mcp_external_rate.py`). 운영에 쓰려면 외부 토큰 비밀값을 따로 만들어 `MCP_EXTERNAL_TOKEN`으로 연결해야 하고, 외부 클라이언트에는 그 값만 준다. 남은 한계: 분당·하루 수는 프로세스 메모리에서 세므로 인스턴스를 늘리면 인스턴스마다 따로 세고 재시작하면 0부터 다시 센다. 내부 토큰이 새면 제한 없이 부를 수 있는 것은 전과 같다(토큰을 바꿔 막는다). **이전 정리(2026-11-16).** 운영에 `MCP_TOKEN`을 Secret Manager 비밀값으로 연결해 `/mcp/`를 열었다(토큰 없이 401). 접근은 `MCP_TOKEN` Bearer 토큰으로만 막고, 서비스는 최대 인스턴스 1개(max-instances 1)로 돈다. 클라이언트별 호출 수 제한은 따로 구현하지 않았다(코드에 `/mcp` 호출 수 상한이 없다). `search_handbook`은 호출마다 번역 LLM·Voyage 임베딩 비용이 들 수 있어 토큰이 새면 비용이 늘 수 있다는 점은 한계로 남는다(토큰을 바꿔 막는다). 처음 적은 내용: 지금 `/mcp`는 정적 토큰 하나이고 호출 제한이 없다. 배포에 `MCP_TOKEN`을 넣기 전에 정한다 — 후보: 토큰당 분당 호출 수 상한(앱 미들웨어), 번역 비용 상한(`LLM_COST_CAP_USD`)과 같은 장부 사용
6. 로그인 미들웨어와 `/mcp`(#45 리뷰): 로그인(`backend/auth.py`)을 `main.py`에 연결할 때 `/mcp`는 사람용 쿠키·CSRF 대상이 아니라 기계용 Bearer 토큰 경로다. 미들웨어가 `/mcp`를 건너뛰고 MCP 서버의 `BearerTokenVerifier`만 쓰는 안을 기본으로 하고, 연결 PR에서 확정한다. 확정: `/mcp`는 로그인 쿠키·CSRF 대상이 아니고 Bearer 토큰만 본다(`backend/main.py`의 `api_prefixes`에 `mcp`)

7. **닫음(2026-11-05, #51 리뷰 요청)**: `search_handbook`에 `sub_queries: list[str] | None`(2~3개, 각 1~1000자, 빈 목록 = 나누지 않음)을 더했고 클라이언트는 그대로 보낸다(`tests/test_mcp_server.py`·`test_mcp_client.py`). 그래프 연결은 김승욱(D5 PR 뒤). 아래는 처음 적은 문제: `search_handbook`에 `sub_queries` 칸이 없다(2026-11-05 클라이언트 작성 중 발견). 그래프는 질문 분해 결과를 `SearchQuery.sub_queries`로 `search()`에 넘기는데(PR #48), MCP로 부르면 이 칸을 보낼 곳이 없다. 클라이언트는 몰래 빼지 않고 `invalid`로 거절한다(빼면 직접 `search()`와 결과가 달라진다). `SEARCH_VIA_MCP`로 그래프를 연결하기 전에 서버 도구에 `sub_queries: list[str] | None`(2~3개, `search.check_query` 검사)을 더한다 — 서버 PR, 김승욱 확인
8. `get_agent_trace` 조회 범위(2026-11-05): 토큰 하나만 있으면 아무 thread_id나 조회할 수 있다. 칸을 화이트리스트로 줄여 대화 내용·사람 정보는 나가지 않지만, 그 대화가 있었다는 사실·진행 상태·시각은 드러난다. 사람 로그인과 thread를 묶는 `/chat` 연결 때 MCP 쪽도 사용자 범위를 둘지 정한다(지금 MCP 토큰은 기계 키 하나라 누가 묻는지 모른다)
9. 비용(2026-11-05): 체크포인트에 비용 칸이 없어 `get_agent_trace`의 `cost_usd`는 null이다. 서비스 경로에서 LLM 호출 비용을 남기려면(`llm_trace.py`를 켜거나 상태에 칸을 더하기) 그래프 쪽 결정이 먼저다
10. 도구 수: `get_grounding`을 더해 6개가 되어 강의 실습 목표(3~5개, MCP_Server 03강·07강 — 출처는 Goal 성공 기준)를 하나 넘는다(2026-11-06, 결정 0062). 같은 문항으로 도구 선택이 나빠지는지 본다

## 클라이언트 (그래프 쪽 MCP 호출, 2026-11-05 추가)

가산 MCP·Skill은 "에이전트가 MCP 클라이언트로 호출"해야 인정된다(가이드 p.20, PRD 6-4 "가산점 목표"의 MCP와 Skill 행). 서버를 부르는 쪽을 `extras/mcp_skill/mcp_client/client.py`에 둔다. 그래프에 붙이는 일(`SEARCH_VIA_MCP`, SDD 2-3절)은 김승욱이 `backend/graph/build.py`에서 한다 — 이 절은 `build.py`·`search.py`를 고치지 않는다.

- 라이브러리: `langchain[mcp]` 1.4.9(PRD 9장 mcp 행·SDD 2-3절, 베타). `langchain.mcp.MCPAdapter`가 FastMCP `Client` 위에서 MCP 도구를 LangChain `StructuredTool`로 바꾼다(결과의 `structured_content`는 `ToolMessage.artifact`). sandbox에서 `fastmcp==4.1.4`와 같이 설치되는 것을 확인했다(`langchain-core` 1.7.5 이상을 끌어온다). 공식 문서: https://docs.langchain.com/oss/python/langchain/mcp
- `load_tools(target, token)` → LangChain 도구 6개(서버 도구 전부). 에이전트가 도구를 직접 고르게 할 때.
- `search_via_mcp(q: SearchQuery, target, token) -> list[Chunk]` → `search(q)`와 같은 모양. 검색 노드가 `search()` 대신 부르면 된다. 이미 이벤트 루프 안이어도 부를 수 있다(새 스레드). 서버 note(`fallback_reason` 등)는 `last_mcp_note()`.
- `section_via_mcp(rule_seq, article, as_of?, target, token) -> dict | None` → `get_section` 도구를 부른다. 근거 판정이 섹션 읽기를 골랐을 때 그래프(`backend/graph/mcp_retriever.py`)가 쓴다. 섹션이 없으면 None이고, 실패 구분은 `search_via_mcp`와 같다.
- 상태 → 결과: `ok` = Chunk 목록, `not_found` = 빈 목록, `unavailable`·연결 실패·시간 초과 = `McpUnavailable`(재시도 가능, `ConnectionError` 하위), `invalid`·`error`·`not_ready` = `McpSearchError`(재시도 불가).
- 주소·토큰: `MCP_URL`(기본 `http://127.0.0.1:8000/mcp/`), `MCP_TOKEN`(Bearer). 문자열 주소는 http(s)만 받는다 — fastmcp는 문자열을 파일 경로로 먼저 읽어 `.py`면 실행하기 때문이다(langchain.mcp도 같은 이유로 막는다). 토큰이 비면 `ValueError`.
- 클라이언트 쪽 호출 시간 제한 35초(서버 도구 30초보다 길게 — 서버가 먼저 `unavailable`로 답하게).
- 운영 확인(2026-11-16): 같은 커밋(`0e4738ac`)의 트래픽 0% 판 `provena-api-00061-wuq`(태그 mcp)에 `MCP_TOKEN`을 연결하고 v2 50건 1회를 재서 인용 정확도 0.900, p95 8.368초, 실패 0(`evals/results/deploy_latency_mcp_provena-api-00061-wuq/`)으로 같은 커밋의 00059-pzr 3회 값(인용 정확도 0.880~0.917, 회차별 p95 8.514~8.843초) 범위 안임을 본 뒤 트래픽 100%로 올렸다. 최종 측정 판 `provena-api-00065-q84`의 컨테이너 안 접근 로그에 `POST /mcp/ 200` 1,170줄이 있다(검색 노드의 MCP 호출, `evals/results/mcp_prod_20261116/`). 최종 운영 배포판 `provena-api-00065-q84`와 같은 이미지의 당시 운영 판 `provena-api-00068-drb`도 `/mcp/`를 토큰 없이 부르면 401이고 `MCP_TOKEN`이 설정되어 있었다(`evals/results/mcp_prod_20261116/`). 그 뒤 운영 판 `provena-api-00075-5zk`(커밋 `eb7516ca`, 00065-q84 대비 `/chat` 오류 분류만 다름)와 당시 운영 판 `provena-api-00079-tmt`(커밋 `c565998d`, 2026-11-16 10:14 KST 배포, 현재 서비스 판은 `docs/GATES.md` G1 칸)의 배포 확인에서도 `/mcp/`를 토큰 없이 부르면 401이었고 `MCP_TOKEN`이 설정되어 있었다.

## 도구 4·5 — `explain_decision`, `get_agent_trace` (2026-11-05 추가, 조장 요청)

둘 다 읽기 전용이고 같은 응답 모양(How 1)이다. 저장소는 MCP 앱이 FastAPI lifespan보다 먼저 만들어지므로(`backend/main.py` `create_app`) `app.state`를 읽지 않는다. 시험은 `build_server(decision_repo=..., checkpointer=...)`로 넣고, 비우면 처음 부를 때 `DATABASE_URL`로 읽기용 풀(`server.pg_pool()`, autocommit·dict_row, 표를 만들지 않음) 위에 `PostgresDecisionRepo`·`PostgresSaver`를 만든다. `DATABASE_URL`이 없거나 표가 아직 없으면 `not_ready`("없다"가 아님).

**`explain_decision(task_type, amount_usd?, table_id?, band?)`** (`decision_tool.py`)
- 판단 코드를 따로 두지 않고 그래프·HTTP와 같은 실행기 `DecisionExecutor(repo).run(...)`을 부른다(그래프 `build.py` `make_execute_node`, HTTP `routes.py` `execute`). 경계 금액·겹치는 구간 거절·위 끝이 빈 구간 해석은 모두 `rules.py`를 따른다.
- 입력: `task_type` 필수 1~200자(HTTP `_parse_run`과 같다), `table_id`·`band` 1~200자 또는 비움, `amount_usd`는 JSON 숫자만(글 `"30000"`·`true`는 MCP 입력 검사에서 막힌다. 기본 float는 `true`를 1로 받아 실행했다 — 실측). 금액 값 검사는 실행기 `check_amount`.
- 출력: HTTP 실행 응답 `RunResponse`와 같은 칸(table_id, version_id, band_label, range_note, approvers, functional_approvers, financial_approvers, cooperating, source{rule_seq, category, band, article, source_url}) + `approved: true`. 승인한 관리자 id(`approved_by`)는 내보내지 않는다(HTTP 응답에도 없다). `source = decision_tables:<table_id>@<version_id>`, `as_of` = 고정해 둔 권한표 판 날짜(모르는 판이면 null).
- 실행기 오류 → 상태: `BadRequest`(400) → `invalid` / `NotFound`(404) → `not_found` / `NotApproved`(409) → `not_ready` / `AmbiguousTable`(409) 승인된 표 0개 → `not_ready`(note에 승인된 업무 종류 후보), 2개 이상 → `invalid`(note에 후보 table_id) / `AmbiguousBand`(422) → `not_found`(입력이 틀린 것이 아니고 band를 줘도 같다. 결정표가 그 금액에 답하지 않는다). note는 실행기 글만 쓴다.

**`get_agent_trace(thread_id)`** (`trace_tool.py`)
- Langfuse trace_id가 아니라 대화 `thread_id`로 LangGraph 체크포인트를 읽는다(조장 지시). 체크포인터의 `list()`만 부르고 쓰지 않는다.
- 체크포인트 모양(실측, 메모리 체크포인터로 실제 그래프를 돌려 확인): 바깥 그래프는 `checkpoint_ns=""`, 하위 그래프는 `"<노드>:<task id>"`(질문 그래프의 합동 검토 `review:…`, 멀티 그래프의 `retriever:…`·`writer:…`·`verifier:…`). 합동 검토 그래프를 단독으로 돌리면 검토 상태가 `""`에 있다. 하위 그래프 체크포인트 metadata `parents[""]`가 바깥 체크포인트 id다. metadata에는 `step`·`source`·`parents`만 있어 돈 노드는 앞뒤 체크포인트의 `versions_seen` 차이로 읽는다.
- 출력(마지막 실행 하나): 돈 노드 순서와 단계별 시각·걸린 시간(같은 그래프의 앞 체크포인트 `ts`와의 차이, 사람 승인을 기다린 단계는 `includes_human_wait`), `route`, 멀티 그래프의 `agent_trace`·`supervisor_log`(after·to·closed_by만), 합동 검토 `review_status`·팀별 상태와 시도 횟수·실패한 팀 id, 승인 대기 여부(`__interrupt__`가 있고 `__resume__`이 없음), `stopped_on_error`, 이 thread의 실행 수. `cost_usd`는 null(체크포인트에 비용 칸이 없고, `llm_trace.py`는 서비스 경로에서 켜지 않는다). 최신 체크포인트 200개까지 읽고 넘으면 `complete=false`.
- 내보내지 않음: 질문·답, user_id, 검색 청크, 쟁점표 행, 사람 결정의 comment·decided_by, 팀 결과의 rows·reason, Supervisor 지시 글. 칸을 지우지 않고 고른 칸만 옮긴다(이름은 식별자 모양만, 상태는 코드가 정한 값만).
- thread_id: 1~200자, 제어 문자 없음. 형식이 정해진 곳이 없어(SDD `/chat` `{thread_id, message}`) 길이만 막는다.

## 도구 6 — `get_grounding` (2026-11-06 추가, 팀장 결정)

**`get_grounding(answer_id)`** (`grounding_tool.py`)
- 저장된 답 하나의 근거 판정 기록을 읽기만 한다. 판정 코드를 MCP 안에 두지 않는다. 질문 그래프의 저장 노드(`build.py` save)가 `grounding.public_grounding`으로 고른 값만 답 저장소에 남기고(`answer_store.save_grounding`), 도구는 `get_grounding(answer_id)`로 그 기록을 읽는다.
- 입력: `answer_id` 1~64자.
- 출력: `results` = [기록 하나](`answer_id`, `grounding`(코드 규칙 건수, 판정 LLM 결과, 다시 쓰기 결과), `skills_used`, `citations`(`chunk_id`, `version_id`)). `source = answers`.
- 내보내지 않음: 질문, 답 본문, 초안, 뺀 문장, 판정 이유 문장, 질문에서 뽑은 말, 사용자 id, 인용 청크 본문. 거절된 답은 저장되지 않아 이 도구로 볼 수 없다.
- 저장소: 답 저장소는 앱 lifespan에서 열리므로 `build_server(answer_store_fn=...)`로 호출할 때 저장소를 돌려주는 함수를 받는다(`backend/main.py`는 `app.state.answer_store`를 읽는 함수를 넘긴다). 함수가 없거나 None을 돌려주거나 저장소에 `get_grounding`이 없으면 `not_ready`, 없는 답이면 `not_found`, 저장소 예외는 `error`(예외 글은 내보내지 않음).

## AC (Given-When-Then)

**AC-01 · 도구는 6개, 읽기 전용**
- GIVEN: `MCP_TOKEN`이 있는 앱
- WHEN: 도구 목록을 받는다
- THEN: 이름이 정확히 `search_handbook`·`get_section`·`list_changed_sections`·`explain_decision`·`get_agent_trace`·`get_grounding`이고 모두 ASCII·읽기 전용 표시. 쓰기·실행 도구가 없다(`explain_decision`은 승인된 표의 규칙을 계산만 한다. 표를 만들거나 승인하지 않는다)

**AC-D1 · 결정표 답 = 실행기 답** (`tests/test_mcp_decision_tool.py`)
- GIVEN: 2023 권한표 `Approving expense`를 승인한 메모리 저장소
- WHEN: 경계 금액 포함 9개 금액으로 `explain_decision`과 `DecisionExecutor.run`을 부른다
- THEN: 결과가 HTTP `RunResponse` 칸 그대로 같고(+`approved: true`), 출력 어디에도 승인자 id가 없다. $500,000(두 구간)은 `not_found`, 승인된 표 0개는 `not_ready`, 2개는 `invalid`, 초안 표는 `not_ready`

**AC-T1 · 체크포인트 단계와 상태** (`tests/test_mcp_trace_tool.py`)
- GIVEN: 가짜 모델로 돌린 질문 그래프+합동 검토 하위 그래프 / 합동 검토 단독(팀 실패) / 멀티 그래프, 메모리 체크포인터
- WHEN: 그 thread_id로 `get_agent_trace`
- THEN: 돈 노드 순서, 팀별 상태·시도 횟수, 승인 대기, Supervisor 결정이 맞고, `cost_usd`는 null, 출력에 user_id·질문·쟁점 글·사람 결정 사유가 없다. 체크포인터에 쓰지 않는다

**AC-G1 · 근거 판정 기록은 고른 칸만** (`tests/test_mcp_new_tools.py`)
- GIVEN: 답 하나와 판정 기록(초안·뺀 문장·판정 이유 문장 포함)을 저장한 메모리 답 저장소
- WHEN: 그 `answer_id`로 `get_grounding` / 없는 id로 / 저장소 없이
- THEN: 판정 결과·규칙 건수·쓴 Skill·인용 id만 오고 질문·답 본문·사용자 id·초안·판정 문장이 없다 / `not_found` / `not_ready`

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
- 운영 확인(2026-11-16): 최종 운영 배포판 `provena-api-00065-q84`에서 토큰 없이 `/mcp/` 호출 401(`evals/results/mcp_prod_20261116/`)

**AC-11 · 외부 토큰만 호출 수를 제한한다 (EC-17, `tests/test_mcp_external_rate.py`)**
- GIVEN: `MCP_TOKEN=inside`, `MCP_EXTERNAL_TOKEN=outside`인 앱 / 외부 토큰이 빈 앱
- WHEN: 틀린 토큰으로 부른다 / 내부 토큰으로 `tools/call`을 한도보다 많이 보낸다 / 외부 토큰으로 분당·하루 한도를 넘겨 보낸다 / 외부 토큰이 빈 앱에 `outside`로 부른다
- THEN: 401 / 모두 200 / 한도까지 200, 그다음 429(`rate_limited`, `Retry-After`), `initialize`·`tools/list`와 내부 토큰은 그대로 200 / 401이고 `MCP_TOKEN`은 전과 같이 제한 없이 200

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

**AC-C1 · 클라이언트가 도구 6개를 LangChain 도구로 받는다** (`tests/test_mcp_client.py`)
- GIVEN: 가짜 검색기를 넣은 서버(같은 프로세스)
- WHEN: `load_tools()`
- THEN: 이름이 정확히 여섯 개인 `BaseTool`이 오고, `search_handbook` 호출 결과의 `artifact.structured_content.status`가 `ok`다

**AC-C2 · `search_via_mcp` = 직접 `search()`**
- GIVEN: 같은 가짜 검색기, `query·org·as_of·k`를 채운 `SearchQuery`
- WHEN: `search_via_mcp(q)`와 직접 호출
- THEN: 같은 `Chunk`가 같은 순서로 온다. 서버에 간 입력 네 칸이 같다. `not_found`는 빈 목록. `sub_queries`는 빠짐없이 같은 순서로 서버까지 가고, 개수가 틀리면 서버가 `invalid`로 거절한다(열린 항목 7)

**AC-C3 · 실패를 재시도 가능과 불가로 나눈다**
- GIVEN: 검색기가 `ConnectionError` / `KeyError`를 낸다, 또는 서버 주소가 닫혀 있다
- WHEN: `search_via_mcp`
- THEN: `ConnectionError`·닫힌 주소 → `McpUnavailable`(retryable) / `KeyError` → `McpSearchError("error")`(retryable 아님)

**AC-C4 · HTTP Bearer 토큰**
- GIVEN: `mcp_http_app(token="abc")`를 ASGI로 붙인 HTTP 클라이언트(네트워크 없음)
- WHEN: 토큰 `abc` / `abd`로 검색
- THEN: `abc`는 결과를 받고, `abd`는 서버 인증이 401로 막는다(재시도 가능 실패로 바꾸지 않는다)
