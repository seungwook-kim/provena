"""FastMCP 읽기 전용 도구 6개 (docs/specs/mcp.md). 가산 MCP·Skill의 서버 쪽.

도구는 backend/ 함수를 감싸기만 하고 검색·판단 로직을 다시 짜지 않는다. 쓰기·실행 도구는 없다(NOT_BUILT.md).
  search_handbook        → backend.rag.retrieve.search.search
  get_section            → backend.rag.retrieve.section.get_section
  list_changed_sections  → backend.rag.ingest.changes.list_changed
  explain_decision       → backend.graph.decision.execute.DecisionExecutor.run   (decision_tool.py)
  get_agent_trace        → LangGraph 체크포인터 list(thread_id) 읽기만             (trace_tool.py)
  get_grounding          → 답 저장소 get_grounding(answer_id) 읽기만              (grounding_tool.py)

여섯 도구는 같은 응답 모양(ToolResponse)을 돌려준다. 글만 돌려주면 "못 찾음"·"고장"이 그럴듯한 문장에 묻히므로
에이전트가 다음 행동을 고를 수 있게 status와 retryable을 따로 둔다(Spec How 1).

연결: backend/main.py가 MCP_TOKEN이 있을 때만 `/mcp`에 mcp_http_app()을 붙인다. 인증은 Bearer 헤더 하나(정적 토큰).
토큰은 둘로 나눈다: 내부 `MCP_TOKEN`(서비스 자신의 검색, 제한 없음)과 선택인 외부 `MCP_EXTERNAL_TOKEN`(분당·하루 호출 수 제한, 넘으면 429).
로컬 확인(stdio, 인증 없음 — 내 PC에서만): python -m extras.mcp_skill.mcp_server.server
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import os
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from backend.rag.retrieve.privacy import PRIVATE_MARK, redact  # noqa: F401 - decision_tool과 시험이 server.redact, server.PRIVATE_MARK를 읽는다
from backend.schemas.chunk import DEFAULT_K, SearchQuery

log = logging.getLogger(__name__)

TOOL_TIMEOUT_S = 30.0          # 번역 시간 초과 15초(translate.TIMEOUT_S)보다 길고 로드밸런서 유휴 60초보다 짧게
MAX_QUERY = 1000
MAX_K = 20
MAX_RULE_SEQ = 2**32 - 1       # rule_seq = 경로 sha256 앞 8자리(Chunk 계약 주석)
MAX_ARTICLE = 500
MAX_NAMES = 10
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# 비공개 주소(internal.gitlab.com)는 공개 핸드북 본문에도 링크로 남아 있다(스냅샷 23,095청크 중 `text` 7청크, 다른 칸 0, 515acc3d 이전 기준). 도구는 근거로 내보내지 않고
# "비공개 문서"로 표시한다(SDD 2-3장 "MCP 도구와 런타임 Skill", PRD 3장 비목표 "GitLab의 비공개 문서는 다루지 않는다").
# 검색 순위·섹션 지문 검사는 바꾸기 전 글로 하고, 내보낼 때만 바꾼다.
# 가리는 함수는 그래프와 같은 것을 쓴다(backend/rag/retrieve/privacy.py).


def _out(model: BaseModel) -> dict[str, Any]:
    d = model.model_dump()
    for key in ("text", "source_url"):
        if isinstance(d.get(key), str):
            d[key] = redact(d[key])
    return d


Status = Literal["ok", "not_found", "invalid", "unavailable", "not_ready", "error"]


class ToolResponse(BaseModel):
    status: Status
    retryable: bool
    results: list[dict[str, Any]]
    as_of: str | None
    source: str
    note: str | None = None
    usage: dict[str, int] | None = None   # search_handbook만: 이 검색이 쓴 임베딩 사용량 {"embed_tokens", "embed_calls"}. 다른 도구는 None


class Invalid(ValueError):
    """도구가 직접 거르는 틀린 입력(EC-03)."""


def _resp(status: Status, source: str, results=None, as_of=None, note=None, retryable=None) -> ToolResponse:
    if retryable is None:
        retryable = status == "unavailable"
    return ToolResponse(status=status, retryable=retryable, results=results or [], as_of=as_of, source=source, note=note)


class _Deps:
    """도구가 부르는 함수. 시험에서는 가짜를 넣는다(build_server 인자)."""

    def __init__(self, search_fn=None, section_store=None, changes_store=None):
        self._search_fn, self._section_store, self._changes_store = search_fn, section_store, changes_store

    def metered_search(self, q: SearchQuery):
        """(검색 결과, fallback_reason, 임베딩 사용량). 이 검색만의 요청 집계(`step_cost`)를 따로 열어 Voyage 사용량을 센다.
        /chat이 루프백으로 부르면 서버 쪽에는 /chat 집계가 없고, 같은 프로세스에서 바로 불러 /chat 집계가 따라와도 여기서 따로 세므로
        부른 쪽(`graph/mcp_retriever.py`)이 응답의 사용량을 한 번만 더한다."""
        from backend.services import step_cost
        meter, token = step_cost.begin()
        try:
            out, fallback = self.search(q)
        finally:
            step_cost.end(token)
        return out, fallback, {"embed_tokens": meter.embed_tokens, "embed_calls": meter.embed_calls}

    def search(self, q: SearchQuery):
        """검색 결과와 그 검색의 기록(fallback_reason). 기록은 contextvar라 같은 스레드에서 읽는다."""
        if self._search_fn is not None:
            out = self._search_fn(q)
            return out, getattr(self._search_fn, "last_trace", None)
        from backend.rag.retrieve.search import last_search_trace, search
        out = search(q)
        tr = last_search_trace()
        return out, (tr.fallback_reason if tr else None)

    def section_store(self):
        if self._section_store is not None:
            return self._section_store
        from backend.rag.retrieve.section import default_store
        return default_store()

    def changes_store(self):
        if self._changes_store is not None:
            return self._changes_store
        from backend.rag.ingest.changes import default_store
        return default_store()


_pg_lock = threading.Lock()
_pg = None


def pg_pool():
    """결정표 저장소·체크포인터를 읽을 연결 풀. DATABASE_URL이 없으면 None. 처음 부를 때 한 번 만든다(section.default_store와 같은 방식).

    모양은 두 쪽이 요구하는 autocommit·dict_row(repo.py PostgresDecisionRepo 주석, checkpoint.py open_persistence의 풀).
    prepare_threshold=None(준비된 문장 안 씀)은 section.PgSectionStore와 같다. 표를 만들지 않는다(setup 없음).
    """
    global _pg
    with _pg_lock:
        if _pg is None:
            url = (os.environ.get("DATABASE_URL") or "").strip()
            if not url:
                return None
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            _pg = ConnectionPool(url, min_size=1, max_size=2, open=True,
                                 kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    return _pg


def missing_table(exc: BaseException) -> bool:
    """표가 아직 없음(setup·SQL 적용 전). 고장이 아니라 '아직 없음'이므로 도구가 not_ready로 돌려준다."""
    try:
        from psycopg.errors import UndefinedTable
    except ImportError:            # pragma: no cover — requirements에 있음
        return False
    return isinstance(exc, UndefinedTable)


async def _run(fn: Callable, *args):
    """막는 함수(DB·모델)를 스레드에서, 제한 시간 안에."""
    return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=TOOL_TIMEOUT_S)


def _transient(exc: BaseException) -> str | None:
    """다시 부르면 될 수 있는 실패면 그 종류, 아니면 None. 시간 초과와 연결 실패만 해당한다."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "시간 초과"
    from backend.rag.retrieve.embed import EmbedUnavailable
    if isinstance(exc, EmbedUnavailable):                        # Voyage API 연결 오류·시간 초과·429·5xx (ConnectionError 하위)
        return "임베딩 API 연결 실패"
    if isinstance(exc, ConnectionError):
        return "저장소 연결 실패"
    try:
        import psycopg
    except ImportError:            # pragma: no cover — requirements에 있음
        return None
    return "저장소 연결 실패" if isinstance(exc, psycopg.OperationalError) else None   # PoolTimeout 포함


def _failure(tool: str, source: str, exc: BaseException) -> ToolResponse:
    """예외 → 상태. 예외 글·DB 주소는 응답에 넣지 않고 로그에는 종류만(EC-04).

    invalid = 이 파일이 입력을 검사해 직접 만든 Invalid뿐(note는 우리가 쓴 글). 시간 초과·연결 실패 = unavailable(재시도 가능).
    그 밖의 예외(내부 ValueError·코드 오류 포함)는 error, retryable=false — 다시 불러도 같으므로 재시도시키지 않는다.
    """
    from backend.rag.retrieve.section import SectionIntegrityError
    if isinstance(exc, Invalid):
        return _resp("invalid", source, note=str(exc))
    if isinstance(exc, SectionIntegrityError):
        log.error("mcp %s: %s", tool, exc)                       # 메시지 = chunk_id만
        return _resp("error", source, note="섹션 원문 검사에 실패해 돌려주지 않았습니다. 다시 불러도 같습니다.")
    kind = _transient(exc)
    if kind:
        log.warning("mcp %s 실패: %s", tool, type(exc).__name__)
        return _resp("unavailable", source, note=f"{kind}. 잠시 뒤 다시 부르세요.")
    log.error("mcp %s 내부 오류: %s", tool, type(exc).__name__)
    return _resp("error", source, retryable=False, note="서버 내부 오류입니다. 다시 불러도 같으니 다른 방법으로 답하세요.")


def _check_text(value: str, name: str) -> None:
    """제어문자(탭·줄바꿈·캐리지리턴 제외)가 든 글은 거절한다. NUL은 psycopg가 DataError로 막아 error로 새므로 미리 invalid로(Spec EC-03)."""
    if any((ord(ch) < 32 and ch not in "\t\n\r") or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise Invalid(f"{name}에 제어문자가 들어 있습니다")


def _check_org(org: str | None, deps: _Deps) -> None:
    if org is None:
        return
    known = deps.section_store().orgs()
    if org not in known:
        raise Invalid(f"모르는 org: {org!r}. 가능한 값: {', '.join(sorted(known))}")


def _check_date(value: str | None, name: str) -> None:
    from backend.rag.retrieve.section import check_date
    try:
        check_date(value, name)
    except ValueError as e:
        raise Invalid(f"{name}는 YYYY-MM-DD 형식의 실제 날짜: {value!r}") from e


def build_server(search_fn=None, section_store=None, changes_store=None, auth: TokenVerifier | None = None,
                 decision_repo=None, checkpointer=None, answer_store_fn=None) -> FastMCP:
    deps = _Deps(search_fn, section_store, changes_store)
    mcp = FastMCP("provena-handbook", auth=auth, instructions=(
        "읽기 전용 도구 6개. GitLab 공개 핸드북(고정 커밋) 검색 3개(search_handbook, get_section, list_changed_sections), "
        "승인된 결정표 실행 결과 explain_decision, 대화(thread_id)의 에이전트 실행 단계 get_agent_trace, "
        "저장된 답(answer_id)의 근거 판정 기록 get_grounding. "
        "답에는 결과의 source_url·version_date를 인용한다. "
        "status가 ok가 아니면 note를 읽고 다음 행동을 고른다(invalid=입력을 고쳐 다시, unavailable=잠시 뒤 다시, "
        "not_ready=아직 없음이지 '없다'가 아님, error=다시 부르지 말고 이 도구 없이 답)."))

    @mcp.tool(annotations=READ_ONLY)
    async def search_handbook(query: str, org: str | None = None, as_of: str | None = None, k: int = DEFAULT_K,
                              sub_queries: list[str] | None = None, sub_query_alts: list[str] | None = None) -> ToolResponse:
        """GitLab 핸드북에서 질문과 관련된 청크(섹션 조각)를 찾는다. 질문을 영어 문장으로 바꿔 voyage-4 벡터로 찾은 상위 k개이고
        (리랭커 없음), k가 3 이상이면 뒤 2자리는 상위 결과가 링크한 다른 페이지의 청크다(링크 확장, 같은 org·as_of 필터).

        언제 쓰나: 핸드북 정책·절차·권한에 대한 질문의 근거를 찾을 때. 한국어 질문도 된다(영어 문장으로 바꿔 찾는다).
        언제 쓰지 않나: 섹션 하나를 통째로 읽을 때는 get_section, 최근 바뀐 섹션 목록은 list_changed_sections.
        입력: query 1~1000자 / org = 핸드북 절(예: security, finance, engineering), 모르면 비움 /
              as_of = YYYY-MM-DD, 그날 유효했던 판만(비우면 현재 판) / k = 1~20, 기본 5 /
              sub_queries = 질문을 나눈 하위 질문 2~3개(선택). 주면 하위 질문마다 찾아 번갈아 합친다. 나누지 않으면 비움 /
              sub_query_alts = sub_queries와 같은 자리의 다른 표현(선택, 빈 글은 그 자리 없음). 주면 그 자리는 두 문장으로 찾아 번갈아 합친다(자리 수 k는 그대로).
        출력: results = Chunk 목록(chunk_id, rule_seq, article, text, source_url, version_date ...). 첫 줄은 제목 경로.
              비공개 주소 링크는 [비공개 문서]로 바꿔 보낸다 — 그 링크 너머 내용은 근거가 아니다.
              usage = 이 검색이 쓴 임베딩 사용량(embed_tokens, embed_calls). 비용 집계용이며 답의 근거가 아니다.
        제약: 결과가 없으면 status=not_found(빈 ok가 아님). note에 검색이 내려간 이유(번역 실패, 임베딩 키 없음 no_key 등)가
              올 수 있다. 임베딩 API 연결 실패·시간 초과는 status=unavailable(잠시 뒤 다시).
        """
        src = "handbook"
        try:
            if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
                raise Invalid(f"query는 1~{MAX_QUERY}자(지금 {len(query or '')}자)")
            _check_text(query, "query")
            if not 1 <= k <= MAX_K:
                raise Invalid(f"k는 1~{MAX_K}: {k}")
            _check_date(as_of, "as_of")
            subs = sub_queries or None                           # None과 []는 "나누지 않음"(search.check_query와 같다)
            if subs is not None:
                from backend.rag.retrieve.search import MAX_SUB_QUERIES
                if not 2 <= len(subs) <= MAX_SUB_QUERIES or not all(
                        isinstance(s, str) and s.strip() and len(s) <= MAX_QUERY for s in subs):
                    raise Invalid(f"sub_queries는 2~{MAX_SUB_QUERIES}개, 각 1~{MAX_QUERY}자(지금 {len(subs)}개)")
                for sub in subs:
                    _check_text(sub, "sub_queries")
            alts = sub_query_alts or None
            if alts is not None:
                if subs is None or len(alts) != len(subs) or not all(isinstance(a, str) and len(a) <= MAX_QUERY for a in alts):
                    raise Invalid(f"sub_query_alts는 sub_queries와 같은 수, 각 0~{MAX_QUERY}자(지금 {len(alts)}개)")
                for alt in alts:
                    if alt:
                        _check_text(alt, "sub_query_alts")
            await _run(_check_org, org, deps)
            try:
                q = SearchQuery(query=query, org=org, as_of=as_of, k=k, sub_queries=subs)
            except ValueError as e:                              # pydantic 검사 — 위 검사와 어긋날 때만
                raise Invalid("검색 입력이 형식에 맞지 않습니다(query·org·as_of·k).") from e
            if alts:   # 원 하위 질문은 검색 계약(SearchQuery) 밖의 힌트로 넘긴다(backend/rag/sub_alts.py). `asyncio.to_thread`가 문맥을 옮긴다
                from backend.rag import sub_alts

                with sub_alts.given(subs, alts):
                    chunks, fallback, usage = await _run(deps.metered_search, q)
            else:
                chunks, fallback, usage = await _run(deps.metered_search, q)
        except Exception as e:  # noqa: BLE001 — 상태로 돌려준다
            return _failure("search_handbook", src, e)
        note = f"fallback_reason={fallback}" if fallback else None
        if not chunks:
            return _resp("not_found", src, as_of=as_of, note=note or "조건에 맞는 청크가 없습니다.").model_copy(update={"usage": usage})
        return _resp("ok", src, [_out(c) for c in chunks], as_of=as_of, note=note).model_copy(update={"usage": usage})

    @mcp.tool(annotations=READ_ONLY)
    async def get_section(rule_seq: int, article: str | None = None, as_of: str | None = None) -> ToolResponse:
        """페이지 한 섹션의 원문을 통째로 돌려준다(청크를 순서대로 잇고 겹침을 뗀 것). 개정 전후 대조에 쓴다.

        언제 쓰나: search_handbook 결과 청크가 잘려 앞뒤 문맥이 필요할 때, 같은 섹션의 옛 판과 지금 판을 비교할 때.
        언제 쓰지 않나: 어떤 섹션인지 모를 때(먼저 search_handbook).
        입력: rule_seq = 결과 청크의 rule_seq(페이지 id) / article = 결과 청크의 article(제목 경로), 제목 없는 페이지 머리는 비움 /
              as_of = YYYY-MM-DD, 그날 유효했던 판(비우면 현재 판).
        출력: results = [Section] 하나(text, version_id, version_date, source_url, line_start, line_end, chunk_ids).
        제약: 섹션이 없으면 not_found와 note에 그 판의 섹션 이름 후보(최대 10개). 원문 지문 검사에 실패하면 error.
        """
        src = "handbook"
        try:
            if not 0 <= rule_seq <= MAX_RULE_SEQ:
                raise Invalid(f"rule_seq는 0~{MAX_RULE_SEQ}: {rule_seq}")
            if article is not None and (not article.strip() or len(article) > MAX_ARTICLE):
                raise Invalid(f"article은 1~{MAX_ARTICLE}자 또는 비움")
            if article is not None:
                _check_text(article, "article")
            _check_date(as_of, "as_of")
            from backend.rag.retrieve import section
            st = deps.section_store()
            sec = await _run(section.get_section, rule_seq, article, as_of, st)
            if sec is None:
                names = await _run(section.section_names, rule_seq, as_of, st)
        except Exception as e:  # noqa: BLE001
            return _failure("get_section", src, e)
        if sec is None:
            if not names:
                return _resp("not_found", src, as_of=as_of,
                             note="그 페이지가 없거나 그날(as_of) 유효한 판이 없습니다. 가장 가까운 판으로 바꾸지 않았습니다.")
            shown = [redact(n) if n is not None else "(제목 없음: article 비움)" for n in names[:MAX_NAMES]]
            return _resp("not_found", src, as_of=as_of,
                         note="그 판에 없는 섹션입니다. 섹션 이름 후보: " + " | ".join(shown))
        return _resp("ok", src, [_out(sec)], as_of=as_of)

    @mcp.tool(annotations=READ_ONLY)
    async def list_changed_sections(since: str, org: str | None = None, limit: int = 200,
                                    offset: int = 0) -> ToolResponse:
        """증분 수집이 찾은 '바뀐 섹션' 목록(추가·수정·삭제)을 읽는다. 아무것도 바꾸지 않는다.

        언제 쓰나: 어느 날 이후 개정된 정책이 무엇인지, 지난 답이 인용한 섹션이 바뀌었는지 볼 때.
        언제 쓰지 않나: 바뀐 내용 자체를 읽을 때는 get_section(as_of로 전후 판).
        입력: since = YYYY-MM-DD(이날 이후 새 판, 쪽 통째 삭제는 기록한 날 기준) / org = 핸드북 절, 모르면 비움 / limit = 1~200 /
              offset = 앞에서 건너뛸 개수(기본 0). note에 "더 있음"이 오면 그 offset으로 다시 불러 이어 받는다.
        출력: results = ChangedArticle 목록(rule_seq, article, old_version_date, new_version_date, change_type).
              as_of = 마지막 성공 증분 실행이 끝난 시각, source = sync_runs:<run_id>@<커밋>.
        제약: 증분 실행이 한 번도 없으면 not_ready("바뀐 것 없음"과 다름). 마지막 실행이 삭제를 보류했으면 note에 표시.
              오래된 날짜부터 정렬한다. limit에서 잘리면 note에 "더 있음: offset=N" — 받지 않으면 최근 변경을 놓친다.
        """
        src = "sync_runs"
        try:
            if not isinstance(since, str):
                raise Invalid("since는 YYYY-MM-DD")
            _check_date(since, "since")
            if not 1 <= limit <= 200:
                raise Invalid(f"limit는 1~200: {limit}")
            from backend.rag.ingest.changes import MAX_OFFSET
            if not 0 <= offset <= MAX_OFFSET:
                raise Invalid(f"offset은 0~{MAX_OFFSET}: {offset}")
            await _run(_check_org, org, deps)
            from backend.rag.ingest.changes import list_changed
            items, last, more = await _run(list_changed, since, org, limit, deps.changes_store(), offset)
        except Exception as e:  # noqa: BLE001
            return _failure("list_changed_sections", src, e)
        if last is None:
            return _resp("not_ready", src, retryable=False,
                         note="증분 수집 실행 기록이 아직 없습니다. 바뀐 것이 없다는 뜻이 아닙니다.")
        src = f"sync_runs:{last.run_id}@{last.to_commit}"
        notes = []
        if more:
            notes.append(f"더 있음: 목록이 limit({limit})에서 잘렸습니다. offset={offset + len(items)}로 다시 불러 이어 받으세요.")
        if last.list_complete is False:
            notes.append("마지막 실행이 파일 목록을 끝까지 받지 못해 삭제를 보류했습니다. 사라진 섹션이 아직 목록에 없을 수 있습니다.")
        return _resp("ok", src, [a.model_dump() for a in items], as_of=last.finished_at, note=" / ".join(notes) or None)

    from extras.mcp_skill.mcp_server import decision_tool, grounding_tool, trace_tool   # 세 모듈이 이 파일을 import하므로 여기서 불러 순환을 피한다
    decision_tool.register(mcp, repo=decision_repo)
    trace_tool.register(mcp, saver=checkpointer)
    grounding_tool.register(mcp, store_fn=answer_store_fn)   # 답 저장소는 앱 lifespan에서 열리므로 호출할 때 읽는 함수로 받는다
    return mcp


# ---------- HTTP 연결 (backend/main.py) ----------

INTERNAL_CLIENT = "provena-mcp"              # MCP_TOKEN: 서비스 자신(SEARCH_VIA_MCP)이 쓰는 내부 토큰, 호출 수 제한 없음
EXTERNAL_CLIENT = "provena-mcp-external"     # MCP_EXTERNAL_TOKEN: 외부 MCP 클라이언트용 토큰, 분당·하루 호출 수 제한
DEFAULT_EXTERNAL_RATE_PER_MIN = 30
DEFAULT_EXTERNAL_RATE_PER_DAY = 500
KST = timezone(timedelta(hours=9), "KST")


class BearerTokenVerifier(TokenVerifier):
    """정적 토큰 둘(내부 `MCP_TOKEN`, 선택인 외부 `MCP_EXTERNAL_TOKEN`). 비교는 hmac.compare_digest(글자 수가 같을 때 시간 차로
    토큰을 알아내지 못하게). 외부 토큰이 있으면 두 토큰과 늘 비교해 어느 쪽이 맞았는지가 시간 차로 드러나지 않게 한다."""

    def __init__(self, token: str, external_token: str | None = None):
        super().__init__()
        self._token = token.encode("utf-8")
        self._external = (external_token or "").encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        got = token.encode("utf-8")
        internal = hmac.compare_digest(got, self._token)
        external = hmac.compare_digest(got, self._external) if self._external else False
        if internal:
            return AccessToken(token="", client_id=INTERNAL_CLIENT, scopes=[])
        if external:
            return AccessToken(token="", client_id=EXTERNAL_CLIENT, scopes=[])
        return None


def _rate_env(name: str, default: int) -> int:
    """0 이상의 정수. 0이면 그 창은 제한하지 않는다. 비었거나 틀린 값은 기본값(경고 로그)."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        log.warning("%s 값이 0 이상의 정수가 아니어서 기본값 %d을 씁니다", name, default)
        return default
    return value


class ExternalRateLimiter:
    """외부 토큰의 도구 호출 수 제한. 분당은 지난 60초 창, 하루는 KST 자정 기준이다.
    세는 곳은 프로세스 메모리라 인스턴스마다 따로 세고 재시작하면 0부터 다시 센다(docs/specs/mcp.md 열린 항목 5:
    이 값을 둘 싼 DB 표가 없어 메모리로 둔다. 운영은 최대 인스턴스 1개라 사실상 서비스 전체 값이다)."""

    def __init__(self, per_min: int, per_day: int, clock: Callable[[], float] = time.time):
        self.per_min, self.per_day, self._clock = per_min, per_day, clock
        self._lock = threading.Lock()
        self._minute: deque[float] = deque()
        self._day: date | None = None
        self._day_count = 0

    def try_acquire(self, n: int = 1) -> tuple[str, int] | None:
        """n번 호출을 셀 수 있으면 세고 None. 넘으면 세지 않고 (창 이름 "minute"|"day", 다시 시도할 수 있는 초)."""
        now = self._clock()
        with self._lock:
            today = datetime.fromtimestamp(now, KST).date()
            if today != self._day:
                self._day, self._day_count = today, 0
            while self._minute and self._minute[0] <= now - 60:
                self._minute.popleft()
            if self.per_day and self._day_count + n > self.per_day:
                midnight = datetime.combine(today + timedelta(days=1), datetime.min.time(), KST)
                return "day", max(1, math.ceil(midnight.timestamp() - now))
            if self.per_min and len(self._minute) + n > self.per_min:
                oldest = self._minute[0] if self._minute else now
                return "minute", max(1, math.ceil(oldest + 60 - now))
            self._minute.extend([now] * n)
            self._day_count += n
            return None


def _tool_calls(body: bytes) -> int:
    """JSON-RPC 본문 속 `tools/call` 수(묶음 요청이면 그 안의 수). 읽지 못하면 0 — 그런 요청은 MCP 서버가 오류로 돌려준다."""
    try:
        msg = json.loads(body or b"null")
    except (ValueError, UnicodeDecodeError):
        return 0
    items = msg if isinstance(msg, list) else [msg]
    return sum(1 for m in items if isinstance(m, dict) and m.get("method") == "tools/call")


def _limit_message(window: str, limiter: ExternalRateLimiter, retry_after: int) -> str:
    if window == "day":
        return f"외부 MCP 호출 한도(하루 {limiter.per_day}회)를 넘었습니다. 내일(KST 0시 이후) 다시 이용해 주세요."
    return f"외부 MCP 호출 한도(분당 {limiter.per_min}회)를 넘었습니다. {retry_after}초 뒤 다시 시도해 주세요."


class ExternalRateLimitMiddleware:
    """외부 토큰으로 온 POST의 `tools/call`만 센다(initialize·tools/list는 비용이 없어 세지 않는다). 내부 토큰과 그 밖의 요청은
    그대로 넘긴다. 넘으면 429 + `Retry-After`. 본문 모양은 /mcp의 401(`{"error": "invalid_token", "error_description": ...}`)과 같은 꼴로
    `{"error": "rate_limited", "error_description": ...}`이다(코드 이름은 backend/api/errors.py 표의 `rate_limited`)."""

    def __init__(self, app, external_token: str, limiter: ExternalRateLimiter):
        self.app = app
        self._expected = f"Bearer {external_token}".encode("utf-8")
        self.limiter = limiter

    def _is_external(self, scope) -> bool:
        for key, value in scope.get("headers") or ():
            if key == b"authorization":
                return hmac.compare_digest(value.strip(), self._expected)
        return False

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST" or not self._is_external(scope):
            await self.app(scope, receive, send)
            return
        chunks, more = [], True
        while more:
            message = await receive()
            if message["type"] != "http.request":          # 끊김(http.disconnect)은 그대로 넘긴다
                await self.app(scope, _replay([], message, receive), send)
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        calls = _tool_calls(body)
        over = self.limiter.try_acquire(calls) if calls else None
        if over is not None:
            window, retry_after = over
            log.info("외부 MCP 호출 한도 window=%s calls=%d", window, calls)
            payload = json.dumps({"error": "rate_limited", "error_description": _limit_message(window, self.limiter, retry_after)},
                                 ensure_ascii=False).encode("utf-8")
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                    (b"content-length", str(len(payload)).encode()),
                                    (b"retry-after", str(retry_after).encode())]})
            await send({"type": "http.response.body", "body": payload})
            return
        await self.app(scope, _replay([{"type": "http.request", "body": body, "more_body": False}], None, receive), send)


def _replay(first: list[dict], tail: dict | None, receive):
    """이미 읽은 본문을 한 번 다시 내주고, 그다음부터는 원래 receive를 쓴다."""
    queue = list(first) + ([tail] if tail else [])

    async def again():
        return queue.pop(0) if queue else await receive()
    return again


def mcp_http_app(token: str | None = None, external_token: str | None = None, **deps):
    """MCP_TOKEN(또는 token)이 있으면 Streamable HTTP 앱, 비어 있으면 None(EC-10). path="/" — main.py가 /mcp에 붙인다.
    MCP_EXTERNAL_TOKEN(또는 external_token)이 있으면 그 토큰도 받고 호출 수를 제한한다(MCP_EXTERNAL_RATE_PER_MIN 기본 30,
    MCP_EXTERNAL_RATE_PER_DAY 기본 500). 비어 있으면 외부 토큰이 없을 뿐 MCP_TOKEN은 전과 같다."""
    token = os.getenv("MCP_TOKEN", "") if token is None else token
    if not token.strip():
        return None
    external = (os.getenv("MCP_EXTERNAL_TOKEN", "") if external_token is None else external_token).strip()
    if external and hmac.compare_digest(external.encode("utf-8"), token.strip().encode("utf-8")):
        log.warning("MCP_EXTERNAL_TOKEN이 MCP_TOKEN과 같아 외부 토큰을 쓰지 않습니다(같은 값이면 제한을 걸 수 없음)")
        external = ""
    app = build_server(auth=BearerTokenVerifier(token.strip(), external or None), **deps).http_app(path="/", stateless_http=True)
    if external:
        limiter = ExternalRateLimiter(_rate_env("MCP_EXTERNAL_RATE_PER_MIN", DEFAULT_EXTERNAL_RATE_PER_MIN),
                                      _rate_env("MCP_EXTERNAL_RATE_PER_DAY", DEFAULT_EXTERNAL_RATE_PER_DAY))
        app.add_middleware(ExternalRateLimitMiddleware, external_token=external, limiter=limiter)
    return app


if __name__ == "__main__":
    build_server().run()      # stdio. 인증이 없으니 내 PC에서만
