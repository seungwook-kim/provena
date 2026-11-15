"""채팅(SSE), 대화 목록, 장기 기억 라우터 (SDD 4-4, G4).

- `POST /chat`: 로그인과 CSRF. `{thread_id?, message, as_of?, org?}` -> SSE로 `AgentEvent`(token, citation, approval_request, error, done).
- `GET /threads`, `GET /threads/{thread_id}`: 로그인. 내 대화 목록과 상세(마지막 답 `last`, 체크포인트에서 되살린 대화 이력 `messages`: 질문·답·근거). 남의 것은 404 `not_found`.
- `GET /me/memory`: 로그인. `PATCH`, `DELETE /me/memory`: 로그인과 CSRF. 소속(affiliation)·직급(rank)·담당 서비스(service) 세 칸만 다룬다.

규칙
- 사용자 id는 로그인 쿠키에서만 얻는다(`create_current_user_dependency`). 본문의 `user_id`는 422(`extra="forbid"`), `?user_id=`는 읽지 않는다.
- 그래프와 체크포인트의 thread 이름은 `<user_id>:<thread_id>`다. 이벤트의 `thread_id`는 화면이 보낸(또는 서버가 만든) 바깥 이름으로 바꿔 내보낸다.
- 그래프, 체크포인터, Store, 승인함 저장소, 대화 목록 저장소는 앱 시작(lifespan)에서 `app.state`에 둔다(`backend/main.py`). 없으면 503 `not_configured`.
- 이벤트 data 키는 `backend/graph/stream.py`(SDD 6장 표)의 키에 이 계층에서 아래 키를 더한다. `backend/schemas/`는 바꾸지 않는다.
  - citation: `text`(인용 청크 본문, 화면 인용 패널용)
  - approval_request: `code = "approval_pending"`. 이 thread의 새 질문은 승인이 끝날 때까지 409 `approval_pending`이다.
  - error: `code`(`limit_exceeded` 또는 `internal_error`), 안내 `message`, `request_id`. 예외 원문은 로그에만 남긴다.
  - done: `kind`(answer | clarify | refuse), `as_of`, `usage`(토큰·비용), 거절이면 `code = "no_results"`, 답이면 `attribution`(출처 표시).
    측정용 칸(숫자와 코드만, 항상 켬, 기존 칸은 그대로): `cost_by_step`(단계별 calls·input_tokens·output_tokens·cost_usd·llm_s), `cost_by_step_total_usd`(질문 번역 LLM 포함 합. `usage.cost_usd`는 번역을 뺀 그래프 합),
    `embed_tokens`·`embed_calls`·`embed_cost_usd`(Voyage `usage.total_tokens` 합과 환산 비용, 호출이 없으면 0), 거절·되묻기면 `refuse_stage`(그 결과를 쓴 그래프 노드)·`refuse_reason`(사유 코드).
  - 검색 색인이 적재되지 않았으면(`index_not_ready`) error 대신 안내 문구 token과 거절 done(`code = "no_results"`)으로 끝낸다. 원인은 로그에만 남긴다.
- 이어 묻기(D-14, `docs/specs/question-graph.md`): 질문마다 그래프 입력에 `asked: [질문]`을 더한다. 그래프 상태의 `asked` 칸이 같은 thread(`<user_id>:<thread_id>`)의 체크포인트에 최근 질문을 쌓아,
  둘째 질문부터 그래프가 앞 질문을 본다(체크포인트를 따로 읽지 않는다). 그래프가 질문을 다시 썼을 때만 `done.understood_question`이 온다(`backend/graph/stream.py`).
  대화 이력(`messages`)의 질문 글은 사용자가 친 글이고, 다시 쓴 질문은 그 답 항목의 `understood_question`으로 준다. `CHAT_FOLLOWUP=0`이면 `asked`를 넘기지 않는다(기본 켬).
- 기억 값과 질문 내용은 로그에 쓰지 않는다. 대화 내용, 검색 결과, 답은 Store에 넣지 않는다(State와 Store의 경계, `backend/memory/profile.py`).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import threading
import time
import uuid
from datetime import date
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from backend.api.errors import ApiError
from backend.api.middleware import current_request_id, log_llm_usage
from backend.auth import AuthStore, AuthUser, TokenRevocationStore, create_current_user_dependency, require_csrf
from backend.graph.stream import CITATION_KEYS, stream_events
from backend.memory.profile import ALLOWED_FIELDS, delete_profile, get_profile, put_profile
from backend.schemas import AgentEvent
from backend.services import step_cost
from backend.services.llm import DEFAULT_ANTHROPIC_MODEL, finish_run, is_demo_mode, run_config

log = logging.getLogger(__name__)

THREAD_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
PING_SECONDS = 15
# 답에 원문을 보일 때의 출처 표시(SDD 8장, CC BY-SA 4.0). 답은 요약·재서술이라 "수정됨"으로 둔다
ATTRIBUTION = {
    "source": "GitLab Handbook",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "modified": True,
    "notice": "GitLab 핸드북 기반 데모이며 GitLab Inc.와 제휴·보증 관계가 없습니다.",
}
MSG_INTERNAL = "답을 만드는 중 오류가 났습니다. 잠시 후 다시 시도해 주세요."
MSG_LIMIT = "이번 질문의 LLM 비용 상한에 닿아 답을 멈췄습니다. 질문을 더 짧고 구체적으로 줄이거나 여러 개로 나누어 다시 물어봐 주세요."
MSG_PENDING = "승인 대기 중인 대화입니다. 관리자 승인이 끝난 뒤 이어 가세요."
MSG_INDEX_NOT_READY = "검색 색인이 아직 준비되지 않아 답할 수 없습니다."
COST_CAP_ERROR = "CostCapExceeded"
# 검색기(`backend/rag/retrieve/search.py`의 `Searcher._check_meta`)가 색인을 적재하지 않았을 때 내는 예외의 종류와 문구 앞부분.
# 이 경우만 오류가 아니라 거절(done, `no_results`)로 끝낸다. 장부 불일치 등 다른 예외는 그대로 `internal_error`다.
INDEX_NOT_READY_ERROR = "RuntimeError"
INDEX_NOT_READY_TEXT = "색인이 준비되지 않았다"


def index_not_ready(data: dict) -> bool:
    """`stream_events`의 error 이벤트 data가 검색 색인 미준비인가."""
    return data.get("code") == INDEX_NOT_READY_ERROR and str(data.get("message") or "").startswith(INDEX_NOT_READY_TEXT)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 본문의 user_id 등은 422
    thread_id: str | None = Field(default=None, pattern=THREAD_ID_PATTERN)  # 없으면 서버가 "t-" + 12자리로 만든다
    message: str = Field(min_length=1, max_length=4000)
    as_of: str | None = Field(default=None, pattern=DATE_PATTERN)
    org: str | None = Field(default=None, max_length=64)

    @field_validator("as_of")
    @classmethod
    def _real_date(cls, value: str | None) -> str | None:
        """`2026-02-30`처럼 형식만 맞고 없는 날짜는 422로 막는다. 검색기(`search.py`의 `check_query`)가 `date.fromisoformat`으로 멈추기 전에 걸러, SSE error 이벤트가 아니라 공통 422 봉투가 나가게 한다."""
        if value is not None:
            # 패턴의 \d는 전각·아랍 숫자도 받고, 그때 fromisoformat 오류 문구에는 입력값이 들어간다 → 고정 문구로 바꿔 입력값을 응답에 담지 않는다
            try:
                if not value.isascii():
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                raise ValueError("존재하지 않는 날짜입니다.") from None
        return value

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        """공백만 있는 질문은 422로 막는다(앞뒤 공백을 지운 뒤 비면 거절). 값은 그대로 두어 검색·녹화 재생의 입력 글자는 바뀌지 않는다."""
        if not value.strip():
            raise ValueError("질문은 공백만으로 보낼 수 없습니다.")
        return value


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 기억해도 되는 칸(affiliation, rank, service) 밖의 값은 422
    affiliation: str | None = Field(default=None, max_length=100)
    rank: str | None = Field(default=None, max_length=100)
    service: str | None = Field(default=None, max_length=100)  # 상한은 다른 두 칸과 같게 100자(화면 입력칸도 같은 한도)


def internal_thread(user_id: str, thread_id: str) -> str:
    return f"{user_id}:{thread_id}"


def model_name() -> str:
    return os.environ.get("LLM_MODEL") or ("demo" if is_demo_mode() else DEFAULT_ANTHROPIC_MODEL)


def _need(request: Request, name: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise ApiError(503, "not_configured", "질문 처리에 필요한 저장소를 사용할 수 없습니다.")
    return value


def pending_approval(repo: Any, internal: str) -> bool:
    """이 thread에 결정을 기다리는 승인 건이 있는가. 승인함 표(`approvals`)가 기준이다."""
    if repo is None:
        return False
    return any(rec.thread_id == internal for rec in repo.list_pending())


def _final_values(graph: Any, internal: str) -> dict:
    """그래프가 끝난 뒤의 상태 값. `stream_events`가 token, citation, done을 내기 시작하면 그래프는 이미 끝났다."""
    try:
        return dict(graph.get_state({"configurable": {"thread_id": internal}}).values or {})
    except Exception as exc:  # noqa: BLE001 - 체크포인트를 못 읽어도 스트림은 이어 간다(추가 키만 비는다)
        log.warning("최종 상태를 읽지 못함: %s", type(exc).__name__)
        return {}


def final_from_stream_enabled() -> bool:
    """사전 등록 62.16 `CHAT_FINAL_FROM_STREAM=1`: `/chat`이 그래프가 끝난 뒤 체크포인트에서 최종 상태를 다시 읽지(`get_state`) 않고, 스트림이 모은 노드 갱신을 쓴다.
    쓰는 칸(`kind`, `as_of`, `answer_id`, `citations`)은 질문마다 `load_memory`가 비우고 마지막으로 쓴 노드의 값이 남는 칸이라 두 값이 같다(시험이 대조한다). 기본 꺼짐."""
    return (os.environ.get("CHAT_FINAL_FROM_STREAM") or "").strip().lower() in {"1", "true", "yes", "on"}


def followup_enabled() -> bool:
    """이어 묻기(D-14) 스위치 `CHAT_FOLLOWUP`. 기본 켬이고 0, false, no, off이면 끈다(그래프에 `asked`를 넘기지 않아 앞 질문이 쌓이지도 쓰이지도 않는다)."""
    return (os.environ.get("CHAT_FOLLOWUP") or "").strip().lower() not in {"0", "false", "no", "off"}


def _messages(graph: Any, internal: str) -> list[dict]:
    """체크포인트 이력에서 대화 이력(질문·답·근거)을 오래된 순으로 되살린다. 화면이 새로고침 뒤 대화를 다시 그릴 때 쓴다.

    질문마다 그래프는 입력 체크포인트(`metadata.source == "input"`) 하나와 단계별 체크포인트를 남긴다. 승인 뒤 재개(`Command(resume=...)`)는
    입력 체크포인트 없이 같은 질문의 단계를 잇는다. 그래서 입력 체크포인트로 질문을 나누고 질문마다 마지막 체크포인트만 읽는다.
    입력 체크포인트의 값은 앞 질문의 상태라 질문 시각만 쓴다.
    - 끝난 질문(`next` 없음): 질문과 답 한 쌍. 거절(`kind == "refuse"`, `/chat`의 `no_results`)은 `no-evidence`. 인용은 답일 때만 `/chat`의 citation과 같은 키로 준다.
    - 승인을 기다리는 질문(interrupt): 질문과 빈 답(`approval`).
    - 오류로 멈췄거나 아직 도는 질문: 질문만. 남은 값이 앞 질문의 답일 수 있어 답으로 쓰지 않는다.
    못 읽으면 빈 목록이다(예외 종류만 로그에 남긴다).
    """
    try:
        turns: list[list] = []
        for snap in reversed(list(graph.get_state_history({"configurable": {"thread_id": internal}}))):  # 최신이 앞으로 온다
            if (snap.metadata or {}).get("source") == "input":
                turns.append([snap])
            elif turns:
                turns[-1].append(snap)
        out: list[dict] = []
        for first, *steps in turns:
            if not steps:   # 입력만 받고 아직 시작하지 않았다
                continue
            last = steps[-1]
            values = last.values or {}
            # 이어 묻기(D-14)로 다시 쓴 질문이면 `question`이 다시 쓴 질문(`understood_question`)과 같다. 화면에는 사용자가 친 글을 보인다.
            # 두 칸은 다음 질문까지 상태에 남으므로(다음 질문의 앞 질문으로 쓴다) `question`과 같을 때만 이 질문의 값이다
            understood = values.get("understood_question") if values.get("understood_question") and values.get("understood_question") == values.get("question") else None
            out.append({"role": "user", "text": (values.get("user_question") if understood else None) or values.get("question") or "", "timestamp": first.created_at})
            waiting = bool(last.next) and any(t.interrupts for t in last.tasks)
            if last.next and not waiting:
                continue
            kind = None if waiting else values.get("kind")
            cites = (values.get("citations") or []) if kind == "answer" else []
            out.append({
                "role": "assistant",
                "text": "" if waiting else values.get("answer") or "",
                "state": "approval" if waiting else "no-evidence" if kind == "refuse" else "done",
                "kind": kind,
                "answer_id": values.get("answer_id"),
                "as_of": values.get("as_of"),
                "citations": [{"id": c.get("chunk_id"), **{k: c.get(k) for k in CITATION_KEYS}, "text": c.get("text")}
                              for c in cites if isinstance(c, dict)],
                "timestamp": last.created_at,
                **({"understood_question": understood} if understood and not waiting else {}),
            })
            if kind == "refuse":
                # 거절 사유 코드(`/chat` done의 `refuse_reason`과 같은 규칙, `step_cost.refuse_meta`). 화면이 새로고침 뒤에도 사유에 맞는 안내만 붙이게 한다(H-34). 거절이 아니면 이 칸은 없다
                from backend.graph.build import REFUSE_REASON_BY_MESSAGE

                out[-1]["refuse_reason"] = step_cost.refuse_meta("", kind, values, REFUSE_REASON_BY_MESSAGE)["refuse_reason"]
        return out
    except Exception as exc:  # noqa: BLE001 - 이력을 못 읽어도 상세 조회는 이어 간다(이력만 빈다)
        log.warning("대화 이력을 읽지 못함: %s", type(exc).__name__)
        return []


async def iterate_in_one_thread(make: Callable[[], Iterator[dict]]) -> AsyncIterator[dict]:
    """동기 이벤트 생성기를 스레드 하나에서 끝까지 돌리고 이벤트를 차례로 넘긴다.

    기본 방식(`iterate_in_threadpool`)은 `next()`마다 다른 스레드와 다른 컨텍스트에서 돌아, 그래프 실행 중에 걸린 컨텍스트 변수가
    다음 `next()`에서 보이지 않을 수 있다. 연결이 끊겨도 그래프는 끝까지 돌고 생성기의 `finally`(비용 닫기, 대화 상태 정리)가 실행된다."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def put(kind: str, value: Any) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, value))
        except RuntimeError:   # 서버가 내려가 이벤트 루프가 닫혔다
            pass

    def produce() -> None:
        try:
            for item in make():
                put("item", item)
        except BaseException as exc:  # noqa: BLE001 - 받는 쪽에서 다시 던진다
            put("error", exc)
        finally:
            put("end", None)

    threading.Thread(target=contextvars.copy_context().run, args=(produce,), name="chat-stream", daemon=True).start()
    while True:
        kind, value = await queue.get()
        if kind == "end":
            return
        if kind == "error":
            raise value
        yield value


def _last(values: dict, answer: str) -> dict:
    return {"kind": values.get("kind"), "answer": answer, "answer_id": values.get("answer_id"), "as_of": values.get("as_of")}


def _settle(request: Request, user_id: str, rec: dict) -> dict:
    """승인 대기로 남은 대화가 승인함에서 끝났으면, 재개된 답을 체크포인트에서 읽어 마지막 답과 상태를 맞춘다."""
    if rec.get("status") != "pending_approval":
        return rec
    internal = internal_thread(user_id, rec["thread_id"])
    if pending_approval(getattr(request.app.state, "decision_repo", None), internal):
        return rec
    graph, threads = getattr(request.app.state, "question_graph", None), request.app.state.thread_store
    values = _final_values(graph, internal) if graph is not None else {}
    last = _last(values, values.get("answer") or "") if values.get("kind") else None
    threads.thread_touch(user_id, rec["thread_id"], status="idle", last=last)
    return threads.thread_get(user_id, rec["thread_id"]) or rec


def create_api_router(
    *, store: AuthStore, secret: str | None = None, revocation_store: TokenRevocationStore | None = None
) -> APIRouter:
    """인증 라우터와 같은 `store`, `secret`을 넘긴다(로컬 데모의 무작위 서명 키도 같아야 한다)."""
    router = APIRouter()
    current_user = create_current_user_dependency(store=store, secret=secret, revocation_store=revocation_store)

    def chat_events(request: Request, user_id: str, thread_id: str, req: ChatRequest, request_id: str) -> Iterator[dict]:
        graph, threads = request.app.state.question_graph, request.app.state.thread_store
        internal = internal_thread(user_id, thread_id)
        cfg = run_config("question", user_id=user_id, thread_id=internal, configurable={"thread_id": internal})
        graph_input = {"question": req.message, "user_id": user_id, "thread_id": internal, "as_of": req.as_of, "org": req.org}
        # 이어 묻기(D-14): 이 대화의 질문 기록에 지금 질문을 더한다. 앞 질문은 같은 thread의 체크포인트에 쌓여 있다(따로 읽지 않는다).
        # 스위치가 꺼져 있어도 기록은 쌓고 `followup_off`로 다시 쓰기만 건너뛴다: 기록을 멈추면 이미 쌓인 대화에서 마지막 기록을 지금 질문으로 잘못 보고
        # 이어 묻기가 계속 돌았고, 다시 켰을 때는 꺼진 동안의 질문이 빠진 기록을 썼다. 질문마다 넘겨 체크포인트에 남은 앞 값이 쓰이지 않게 한다.
        graph_input["asked"] = [req.message]
        graph_input["followup_off"] = not followup_enabled()
        started = time.perf_counter()
        meter, meter_token = step_cost.begin()   # 요청 단위 집계(단계별 비용, Voyage 토큰). 숫자만 모으고 항상 켜 둔다
        text: list[str] = []
        final: dict | None = None
        closed = False
        status = "running"

        def step_fields(summary: dict) -> dict:
            """done 이벤트에 더하는 칸: cost_by_step, cost_by_step_total_usd, embed_tokens, embed_calls, embed_cost_usd. 기존 칸(usage 등)은 건드리지 않는다."""
            try:
                return meter.snapshot(summary.get("cost_by_step"))
            except Exception as exc:  # noqa: BLE001 - 집계 실패가 답을 막지 않는다
                log.warning("단계별 비용 집계 실패: %s", type(exc).__name__)
                return {}

        def close() -> dict:
            nonlocal closed
            closed = True
            summary = finish_run(cfg)
            log_llm_usage(model=model_name(), summary=summary, latency_ms=(time.perf_counter() - started) * 1000, route="/chat", request_id=request_id)
            return summary

        streamed: dict | None = {} if final_from_stream_enabled() else None   # 62.16: 켜면 get_state 없이 스트림 값을 쓴다
        try:
            for ev in stream_events(graph, graph_input, thread_id=internal, config=cfg, values_out=streamed):
                data = dict(ev.data)
                if ev.type == "error" and index_not_ready(data):
                    # 색인이 없는 새 환경(INDEX_URL 없음). 오류가 아니라 거절로 끝내고, 원인은 로그에만 남긴다
                    log.warning("chat 거절(색인 미준비) request_id=%s: %s", request_id, data.get("message"))
                    summary = close()
                    status = "idle"
                    threads.thread_touch(user_id, thread_id, status=status,
                                         last={"kind": "refuse", "answer": MSG_INDEX_NOT_READY, "answer_id": None, "as_of": req.as_of})
                    done = {"answer_id": None, "kind": "refuse", "as_of": req.as_of, "code": "no_results",
                            "usage": {k: summary.get(k) for k in ("input_tokens", "output_tokens", "cost_usd", "calls")},
                            "refuse_stage": "search", "refuse_reason": "index_not_ready", **step_fields(summary)}
                    for kind, payload in (("token", {"text": MSG_INDEX_NOT_READY}), ("done", done)):
                        out = AgentEvent(type=kind, thread_id=thread_id, data=payload)
                        yield {"event": out.type, "data": out.model_dump_json()}
                    continue
                if ev.type in ("token", "citation", "done") and final is None:
                    final = dict(streamed) if streamed is not None else _final_values(graph, internal)
                if ev.type == "token":
                    text.append(str(data.get("text") or ""))
                elif ev.type == "citation":
                    by_id = {c.get("chunk_id"): c for c in (final or {}).get("citations") or [] if isinstance(c, dict)}
                    data["text"] = (by_id.get(data.get("chunk_id")) or {}).get("text")
                elif ev.type == "approval_request":
                    status = "pending_approval"
                    threads.thread_touch(user_id, thread_id, status=status)
                    data["code"] = "approval_pending"
                    close()
                elif ev.type == "error":
                    log.error("chat 오류 request_id=%s %s: %s", request_id, data.get("code"), data.get("message"))
                    limit = data.get("code") == COST_CAP_ERROR
                    data = {"code": "limit_exceeded" if limit else "internal_error", "message": MSG_LIMIT if limit else MSG_INTERNAL,
                            "request_id": request_id}
                    status = "idle"
                    threads.thread_touch(user_id, thread_id, status=status)
                    close()
                elif ev.type == "done":
                    values = final or {}
                    summary = close()
                    data.update(kind=values.get("kind"), as_of=values.get("as_of"),
                                usage={k: summary.get(k) for k in ("input_tokens", "output_tokens", "cost_usd", "calls")})
                    data.update(step_fields(summary))
                    if values.get("kind") == "refuse":
                        data["code"] = "no_results"
                    elif values.get("kind") == "answer":
                        data["attribution"] = ATTRIBUTION
                    status = "idle"
                    threads.thread_touch(user_id, thread_id, status=status, last=_last(values, "".join(text)))
                out = AgentEvent(type=ev.type, thread_id=thread_id, data=data)
                yield {"event": out.type, "data": out.model_dump_json()}
        finally:
            if not closed:
                close()
            step_cost.end(meter_token)
            if status == "running":   # 연결이 끊겨 끝나지 못했다. 다음 질문을 받을 수 있게 되돌린다
                try:
                    threads.thread_touch(user_id, thread_id, status="idle")
                except Exception as exc:  # noqa: BLE001 - 정리 실패가 다른 오류를 덮지 않게 종류만 남긴다
                    log.warning("대화 상태 정리 실패: %s", type(exc).__name__)

    @router.post("/chat")
    def chat(req: ChatRequest, request: Request, user: AuthUser = Depends(current_user), _csrf: None = Depends(require_csrf)):
        """`{thread_id?, message}` -> SSE로 `AgentEvent`. 승인 대기 중인 thread의 새 질문은 409 `approval_pending`."""
        _need(request, "question_graph")
        threads = _need(request, "thread_store")
        user_id = str(user.user_id)
        thread_id = req.thread_id or "t-" + uuid.uuid4().hex[:12]
        if pending_approval(getattr(request.app.state, "decision_repo", None), internal_thread(user_id, thread_id)):
            raise ApiError(409, "approval_pending", MSG_PENDING)
        threads.thread_touch(user_id, thread_id, title=req.message, status="running")
        request_id = current_request_id()
        events = iterate_in_one_thread(lambda: chat_events(request, user_id, thread_id, req, request_id))
        return EventSourceResponse(events, headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"}, ping=PING_SECONDS)

    @router.get("/threads")
    def list_threads(request: Request, user: AuthUser = Depends(current_user)) -> dict:
        """내 대화 목록(최근 순). 다른 사용자의 thread는 나오지 않는다. 목록에는 마지막 답(`last`)을 넣지 않는다."""
        threads, user_id = _need(request, "thread_store"), str(user.user_id)
        repo = getattr(request.app.state, "decision_repo", None)
        waiting = {rec.thread_id for rec in repo.list_pending()} if repo is not None else set()
        items = []
        for rec in threads.threads_of(user_id):
            item = {k: v for k, v in rec.items() if k != "last"}
            if item["status"] == "pending_approval" and internal_thread(user_id, item["thread_id"]) not in waiting:
                item["status"] = "idle"    # 승인함에서 끝난 대화. 마지막 답은 상세 조회에서 맞춘다
            items.append(item)
        return {"threads": items}

    @router.get("/threads/{thread_id}")
    def get_thread(thread_id: str, request: Request, user: AuthUser = Depends(current_user)) -> dict:
        threads, user_id = _need(request, "thread_store"), str(user.user_id)
        rec = threads.thread_get(user_id, thread_id)
        if rec is None:
            raise ApiError(404, "not_found", "대화를 찾을 수 없습니다.")
        graph = getattr(request.app.state, "question_graph", None)
        messages = _messages(graph, internal_thread(user_id, thread_id)) if graph is not None else []
        return {**_settle(request, user_id, rec), "messages": messages}

    @router.get("/me/memory")
    def memory_get(request: Request, user: AuthUser = Depends(current_user)) -> dict:
        user_id = str(user.user_id)
        return {"user_id": user_id, "profile": get_profile(_need(request, "store"), user_id), "allowed_fields": list(ALLOWED_FIELDS)}

    @router.patch("/me/memory")
    def memory_patch(body: MemoryPatch, request: Request, user: AuthUser = Depends(current_user),
                     _csrf: None = Depends(require_csrf)) -> dict:
        if body.affiliation is None and body.rank is None and body.service is None:
            raise ApiError(422, "validation_error", "고칠 칸(affiliation, rank, service)이 없습니다.")
        user_id = str(user.user_id)
        profile = put_profile(_need(request, "store"), user_id, affiliation=body.affiliation, rank=body.rank,
                              service=body.service)
        return {"user_id": user_id, "profile": profile}

    @router.delete("/me/memory")
    def memory_delete(request: Request, user: AuthUser = Depends(current_user), _csrf: None = Depends(require_csrf)) -> dict:
        user_id = str(user.user_id)
        delete_profile(_need(request, "store"), user_id)
        return {"user_id": user_id, "profile": {}}

    return router
