"""그래프 조립 (G4). D4(11/5) 단일 에이전트 그래프 v1, `docs/specs/question-graph.md`.

흐름: 기억 불러오기 -> 질의 라우팅(도메인 밖이면 검색 없이 거절) -> (정책 질문) 질의 재작성 -> 검색 -> 문서 채점 -> 부족하면 재작성으로(재검색 최대 2회)
-> 답 작성(재검색 결과는 앞 결과에 합친다) -> 인용 검사(코드) -> 근거 판정(코드 규칙 + LLM) -> 저장.
재검색 뒤에도 근거가 모자란데 여러 사실을 묻는 질문의 일부에 자료가 직접 답하면(`judge_partial`) 그 부분만 답하고 나머지를 뺐다고 밝힌다.
근거 판정이 받쳐지지 않는 주장을 찾으면 답을 한 번 다시 쓰고(`redraft_answer`), 안 되면 그 문장을 빼 본다(`revise_answer`). 어느 쪽도 재판정을 통과해야 나가고, 아니면 거절한다.
결정표와 합동 검토 경로는 별도 Spec이다. 연결되기 전에는 분류 결과만 남기고 정책 질문으로 처리한다. 막다른 답을 내면 답이 있는 질문을 거절하게 된다.

D5(11/6)에 Supervisor와 서브에이전트로 나누고 같은 평가셋(v2)으로 다시 잰다.
시험하기 쉽게 검색기, 체크포인터, 채팅 모델을 인자로 받는다. 재검색 상한은 `MAX_RESEARCH` 한 곳에 있다.
검색 필터(`org`, `as_of`)는 검색 단계의 인자로만 넘기고 결과를 받은 뒤 거르지 않는다.
답 단계 근거 판정은 후처리 거절이므로 평가 실행기가 그 효과를 따로 보고한다(docs/GATES.md G5).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed, wait as wait_futures
from itertools import zip_longest
from datetime import date
from typing import Any

from langchain_core.runnables.config import var_child_runnable_config
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from backend.graph import grounding as G
from backend.graph import answer_fixes as AF
from backend.graph import query_plan as QP
from backend.graph.answer_store import AnswerStore
from backend.graph.citations import check_citations
from backend.graph.decision.execute import DecisionExecutor, decision_citation, format_decision_answer, make_execute_node
from backend.graph.decision.params import DECISION_PARAMS_SYSTEM, params_from_obj, params_user
from backend.graph.decompose import decompose_enabled, decompose_question, drop_company_prefix, gate_split
from backend.graph.mcp_retriever import default_retriever, default_section_reader, last_fallback_reason
from backend.graph.parsing import parse_json_obj
from backend.graph.service_profile import SharedChatModel
from backend.graph.state import AgentState
from backend.memory.profile import get_profile
from backend.prompts import question as P
from backend.graph import untrusted as U
from backend.prompts.question import leaks_internal
from backend.rag.retrieve import ranges
from backend.rag.retrieve.embed import EmbedUnavailable
from backend.rag.retrieve.privacy import redact_chunk
from backend.schemas import Chunk, SearchQuery
from backend.schemas.chunk import DEFAULT_K
from backend.services.demo_replay import ReplayChatModel, env_flag
from backend.services.llm import CostCapExceeded, get_chat_model, is_demo_mode
from backend.services.skills import load_skill, skills_enabled

log = logging.getLogger(__name__)

MAX_RESEARCH = 2  # 재검색 최대 횟수의 기본값이자 허용 상한. 첫 검색까지 합쳐 검색은 최대 3번. `SEARCH_MAX_RESEARCH`로 0~2를 고른다
SPEC_KEY = "__spec__"  # SP: `search_cache` 안에서 미리 돌린 첫 검색·판정의 열쇠를 두는 자리(문자열 하나)
INTAKE_KEY = "__intake__"  # `search_cache` 안에서 미리 받은 LLM 응답을 두는 자리. 검색 기억의 열쇠는 JSON 목록이라 겹치지 않고, 첫 검색까지 쓴 뒤에는 지운다
MAX_CHUNKS = 10  # 재검색 결과를 합친 근거 목록의 최대 길이
MAX_SECTION_CHARS = 6000  # 섹션을 통째로 읽어 넓힐 수 있는 본문 길이. 넘으면 넓히지 않는다
AUTHZ_TITLE = "Authorization Matrix"  # 현재 페이지와 고정 판(2023-05)의 공통 제목
SEARCH_K = DEFAULT_K  # 검색마다 요청하는 청크 수. 그래프와 MCP가 같은 상수(`backend/schemas/chunk.py`)를 쓴다(확정 조합 k=5)
SPLIT_K = 8  # 나뉜 질문(하위 질문 2개 이상)의 첫 검색 자리 수. 하위 질문과 링크 확장으로 7자리 + 끝 1자리는 원 질문 목록(`search.FULL_TAIL`). 나뉘지 않은 질문과 재검색은 `SEARCH_K` 그대로(사전 등록 62.38). 달러 금액이 든 질문은 나뉘어도 `SEARCH_K`(사전 등록 62.43, `split_k`)
MAX_CITATIONS = P.MAX_CITATIONS  # 답 하나가 인용할 수 있는 청크 수의 상한. 답 프롬프트와 같은 값이다
JSON_ATTEMPTS = 2  # LLM 응답 형식이 깨지면 1회 다시 요청한다 (Spec EC-06)
ROUTES = ("rule", "decision", "review", "out_of_domain")
# 한 실행 안에서만 뜻이 있는데 `load_memory`의 기본값에 없는 칸. 체크포인터가 있으면 앞 실행의 값이 남아 있으므로 새 질문에서 비운다.
# 남아 있을 때만 쓴다: 체크포인터 없는 실행의 결과에 없던 칸이 생기지 않는다
LEFTOVER_FIELDS = {"search_query": "", "search_org": None, "decision_query": {}, "decision_result": {}, "decision_error": {}, "review_status": "", "issue_table": {},
                   "early_answer": {}, "judged_chunks": 0, "search_stalled": False, "judge_missing": [], "judge_query": "", "judge_scope": "", "section_reads": 0,
                   "query_targets": [], "sub_research": "", "sub_research_phase": "", "judge_none": False}
MAX_MISSING = 4  # 판정이 적은 빠진 사실을 재작성에 넘기는 개수의 상한
REQUERY_NEW = 5  # SS: 페이지 재검색이 더하는 새 청크 수(문맥에 있는 청크는 세지 않는다). 61.10: 3이면 2번 7cd641이 4번째로 빠진 행이 있다
JUDGE_ANSWER_MODES = ("parallel", "parallel_all", "joint")  # `GRAPH_JUDGE_ANSWER`: 근거 충분 판정과 답 작성을 동시에 부르거나(parallel) 한 호출로 합친다(joint)
LICENSE_NOTE = "출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MARK = re.compile(r"\[([0-9a-f]{16})\]")
_ASKS_FACT = re.compile(r"누가|누구|언제|어디|어느|얼마|몇|무엇|뭐|어떻게|왜")
_REVIEW_WORD = re.compile(r"검토|리뷰|review|평가해|봐\s*줘|맡아|맡길", re.I)
# 규정상 필요한지·해야 하는지를 예·아니오로 묻는 말로 끝나는 질문("~가 필요한가요?", "~해야 하나요?", "~있어야 하나요?"). 이때 "검토"는 맡기는 일이 아니라 묻는 대상이다
_ASKS_NEED = re.compile(r"(필요|필수|의무|\S야\s*(하|되|돼|합|할|한))[^.!?\n]{0,8}(\?|가요|나요|까요|한가|하나|인가|니|냐|까)\s*\??\s*$")
_REVIEW_REQUEST = re.compile(r"(검토|리뷰|review|평가)[를을]?\s*(해\s*[줘주]|부탁|바랍|요청|맡)|봐\s*[줘주]|맡아|맡길", re.I)  # 검토를 해 달라고 맡기는 말
_ENDS_ASKING = re.compile(r"[?？]\s*$")  # 물음표로 끝나는 질문. 안건을 서술하고 아무것도 묻지 않는 합동 검토 요청은 평서문이다
_AMOUNT_WORD = re.compile(r"[천만억]\s*(?:달러|원|불)|구간|금액")
# 값이 아니라 이름 안의 숫자: 글자로 시작하는 S1, Sev1, IPv4와 숫자로 시작하는 2FA. USD500, 5K, 10MB, 3GB처럼 값과 단위인 것은 남긴다
_NAME_WITH_DIGIT = re.compile(r"(?<![$A-Za-z0-9.,])(?:(?!(?:USD|KRW|EUR|GBP|JPY)\d)[A-Za-z]+\d[A-Za-z0-9]*|\d+(?!(?:USD|KRW|EUR|GBP|JPY|KB|MB|GB|TB|PB|MS|SEC|MIN|HRS?|DAYS?)(?![A-Za-z0-9]))[A-Z]{2,}(?![A-Za-z0-9]))")
_WHEN = re.compile(r"(?<!\d)(?:(?:19|20)\d{2}(?:[-./]\d{1,2}(?:[-./]\d{1,2})?)?|\d{1,2}\s*월)(?!\d)")  # 시점을 되묻는 말에 쓰는 연도, 날짜, 월

MSG_REFUSE = "핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다."
MSG_REFUSE_OUT_OF_DOMAIN = "핸드북과 관련 없는 질문이라 답하지 않습니다."
MSG_PARTIAL_NOTE = "질문의 나머지 부분은 근거를 확인하지 못해 답에서 뺐습니다."
MSG_REFUSE_SEARCH_DOWN = "검색을 지금 쓸 수 없어 답하지 않습니다. 잠시 뒤에 다시 시도해 주세요."
MSG_REFUSE_NO_KEY = "검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다."
MSG_REFUSE_LEAK = "답에 내부 지시문이 섞여 있어 답하지 않습니다."
MSG_REFUSE_CITATION = "답에 쓸 근거 인용을 확인하지 못해 답하지 않습니다."
MSG_REFUSE_BY_REASON = {
    G.NO_EVIDENCE: "핸드북에서 질문에 답하는 근거를 찾지 못해 답하지 않습니다.",
    G.OUT_OF_PERIOD: "질문이 묻는 기간이나 시점의 판이 수집된 핸드북에 없어 답하지 않습니다.",
    G.NONEXISTENT_ENTITY: "질문이 묻는 대상이 검색된 핸드북 근거에 없어 답하지 않습니다.",
    G.UNSUPPORTED: "검색된 근거가 답의 주장을 받쳐 주지 못해 답하지 않습니다.",
}
# 상태에 `refuse_reason`이 없는 거절의 사유 코드(`/chat` done의 `refuse_reason`, step_cost.refuse_meta). `refuse_reason`이 있으면(no_evidence | out_of_period | nonexistent_entity | unsupported) 그 값이 먼저다
REFUSE_REASON_BY_MESSAGE = {
    MSG_REFUSE: "no_evidence",
    MSG_REFUSE_OUT_OF_DOMAIN: "out_of_domain",
    MSG_REFUSE_SEARCH_DOWN: "unavailable",
    MSG_REFUSE_NO_KEY: "no_key",
    MSG_REFUSE_LEAK: "leak",
    MSG_REFUSE_CITATION: "citation_check",
}


def asks_fact_not_review(question: str) -> bool:
    """합동 검토로 분류된 질문이 검토를 맡기는 요청이 아니라 사실을 묻는 질문인가.
    의문사로 묻고 검토라는 말이 없거나, 물음표로 끝나고 검토라는 말이 없거나, 규정상 필요 여부를 예·아니오로 묻고 검토를 해 달라는 말이 없으면 사실 질문이다."""
    if (_ASKS_FACT.search(question) or _ENDS_ASKING.search(question.strip())) and not _REVIEW_WORD.search(question):
        return True
    return bool(_ASKS_NEED.search(question.strip())) and not _REVIEW_REQUEST.search(question)


def route_of(obj: dict | None) -> str:
    """분류 응답에서 경로를 읽는다. 모르는 값은 일반 정책 질문(`rule`)이다.
    도메인 밖은 검색 없이 끝나므로, 질문이 이 조직이 정한 것이나 이 조직의 일을 묻는다고 모델이 스스로 적었으면(`org_specific`이 true) 따르지 않고 정책 경로로 보낸다.
    핸드북에 근거가 있는지는 검색 뒤의 판정이 정한다."""
    obj = obj if isinstance(obj, dict) else {}
    route = obj.get("route")
    if route not in ROUTES:
        return "rule"
    if route == "out_of_domain" and obj.get("org_specific") is True:
        return "rule"
    return route


def _text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):  # 블록 목록(Anthropic API가 생각 블록과 함께 돌려줄 때): 글 블록만 잇는다
        return "".join(b if isinstance(b, str) else str(b.get("text") or "") for b in c if isinstance(b, str) or (isinstance(b, dict) and b.get("type") == "text"))
    return c if isinstance(c, str) else str(c)


def _valid_date(value: object) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _version_label(c: dict) -> str:
    d = str(c.get("version_date") or "")
    return f"{d} 이전" if c.get("version_date_before") else d


def finish_answer(answer: str, citations: list[dict], as_of: str | None) -> str:
    """`[chunk_id]`를 `[n]`으로 바꾸고 기준일, 판 날짜, 출처 표시를 코드로 붙인다. 표시를 LLM에 맡기면 100%를 보장하지 못한다."""
    order = {c["chunk_id"]: i for i, c in enumerate(citations, 1)}
    body = _MARK.sub(lambda m: f"[{order[m.group(1)]}]" if m.group(1) in order else "", answer).strip()
    dates = ", ".join(dict.fromkeys(_version_label(c) for c in citations))
    return f"{body}\n\n기준일 {as_of or '미지정'} · 근거 판 날짜 {dates} · {LICENSE_NOTE}"


mentions_period = G.mentions_period  # 질문에 시점 표현이 있는지. 없는 질문에 재작성이 기준일을 채워 내면(오늘 날짜 등) 그 값은 쓰지 않는다. 근거 판정(grounding.recode_vote)과 같은 판별이다


def has_dollar_amount(question: str | None, sub_queries) -> bool:
    """질문이나 하위 질문에 달러 금액이 있는지. 검색기의 금액 구간 조회(`Searcher._range_expand`)가 쓰는 조건과 같다(`ranges.amounts_in`)."""
    return bool(ranges.amounts_in([question, *(sub_queries or ())]))


def split_k(question: str | None, sub_queries) -> int:
    """나뉜 질문(하위 질문 2개 이상)의 첫 검색 자리 수. 달러 금액이 든 질문은 금액 구간 조회가 정답 구간 행을 따로 넣으므로 넓히지 않고 `SEARCH_K`로 둔다(사전 등록 62.43)."""
    return SPLIT_K if len(sub_queries or ()) >= 2 and not has_dollar_amount(question, sub_queries) else SEARCH_K


def chunk_cap(sub_queries, question: str | None = None) -> int:
    """근거 목록의 최대 길이. 첫 검색이 `split_k`만큼 넓어진 나뉜 질문은 그만큼 상한을 올려야 재검색이 새 청크를 받는다."""
    return MAX_CHUNKS + split_k(question, sub_queries) - SEARCH_K


def core_chunks(state) -> list[dict]:
    """넓힌 첫 검색(나뉜 질문, `split_k` > `SEARCH_K`)의 문맥에서 앞 `SEARCH_K`자리. 넓히지 않았거나 재검색 뒤면 문맥 전체다."""
    chunks = state.get("chunks", [])
    if state.get("retries", 0) or split_k(state.get("question"), state.get("sub_queries")) <= SEARCH_K:
        return chunks
    return chunks[:SEARCH_K]


def merge_chunks(prev: list[dict], new: list[dict], limit: int = MAX_CHUNKS) -> list[dict]:
    """앞 검색 결과를 유지하고 새 청크를 뒤에 붙인다. 같은 청크(`chunk_id`, `version_id`)는 한 번만 두고, 길이는 `limit`까지만 둔다."""
    out = list(prev)[:limit]
    seen = {(c["chunk_id"], c.get("version_id")) for c in out}
    for c in new:
        if len(out) >= limit:
            break
        key = (c["chunk_id"], c.get("version_id"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def reads_authz(state: AgentState) -> bool:
    """권한표를 읽는 답인지. 분류가 결정표이거나, 분류와 상관없이 자료에 권한표 페이지가 있으면 그렇다.
    분류기는 권한표 질문도 `rule`로 보낼 수 있어(CLASSIFY_SYSTEM의 rule 설명) 분류만으로는 Skill이 빠진다."""
    return state.get("route") == "decision" or any(str(c.get("rule_title") or "").startswith(AUTHZ_TITLE) for c in state.get("chunks", []))


def pick_section(obj: dict, chunks: list[dict]) -> dict | None:
    """근거 판정이 고른 섹션 읽기. 자료에 있는 chunk_id만 받고, 이미 넓힌 청크와 다른 값은 None이다(재검색으로 간다)."""
    if obj.get("next_tool") != "get_section":
        return None
    c = next((x for x in chunks if x["chunk_id"] == obj.get("chunk_id")), None)
    if c is None or c.get("section_read"):
        return None
    return {"chunk_id": c["chunk_id"], "rule_seq": c["rule_seq"], "article": c.get("article")}


def expand_chunk(chunks: list[dict], chunk_id: str, section: dict | None) -> list[dict]:
    """그 청크의 본문을 같은 판의 섹션 전체로 바꾼다. id와 판은 그대로라 인용 검사가 같은 청크로 본다. 판이 다르거나 너무 길면 그대로 둔다."""
    text = str((section or {}).get("text") or "")
    out = []
    for c in chunks:
        if c["chunk_id"] == chunk_id:
            c = {**c, "section_read": True}
            if text and len(text) <= MAX_SECTION_CHARS and section.get("version_id") == c.get("version_id"):
                c["text"] = f"{str(c.get('text') or '').split(chr(10), 1)[0]}\n{text}"
        out.append(c)
    return out


def select_citations(valid: list[dict], answer: str, limit: int = MAX_CITATIONS) -> tuple[list[dict], list[dict], str]:
    """답이 실제로 쓴 청크만 인용으로 남긴다. 본문에 표시가 있는 청크를 처음 나온 순서로 `limit`개까지 두고(본문에 표시가 하나도 없으면 목록 순서),
    나머지는 잘린 인용으로 돌려준다. 잘린 청크의 표시는 본문에서 지운다. (남긴 인용, 잘린 인용, 정리한 답)"""
    by_id = {c["chunk_id"]: c for c in valid}
    used = list(dict.fromkeys(i for i in _MARK.findall(answer or "") if i in by_id))
    keep = (used or [c["chunk_id"] for c in valid])[:limit]
    kept = [by_id[i] for i in keep]
    trimmed = [c for c in valid if c["chunk_id"] not in keep]
    text = _MARK.sub(lambda m: m.group(0) if m.group(1) in keep else "", answer or "")
    return kept, trimmed, re.sub(r"[ \t]{2,}", " ", text).strip()


def clarify_has_number(text: str) -> bool:
    """되묻기 문장에 수치가 있는지. 시점을 묻는 연도, 날짜, 월 표기와 이름 안의 숫자(2FA, S1)는 세지 않는다(수치를 말하는 되묻기를 거르는 규칙)."""
    return bool(re.search(r"\d", _NAME_WITH_DIGIT.sub("", _WHEN.sub("", text or ""))))


def _forget_search_trace() -> None:
    """이전 검색의 기록이 이번 검색의 것으로 읽히지 않게 비운다(`last_search_trace`는 컨텍스트 변수다)."""
    from backend.rag.retrieve.search import _last

    _last.set(None)


def _search_fallback_reason() -> str | None:
    from backend.rag.retrieve.search import last_search_trace

    tr = last_search_trace()
    return tr.fallback_reason if tr else last_fallback_reason()  # MCP로 찾으면 검색 기록이 서버 쪽에 있어 note에서 읽는다


def resolve_max_research(value: int | None = None) -> int:
    """재검색 상한. 인자, 환경 변수 `SEARCH_MAX_RESEARCH`, 기본 2 순이다. 비어 있으면 기본값이고 0~2가 아니면 ValueError다."""
    raw: Any = value if value is not None else (os.environ.get("SEARCH_MAX_RESEARCH") or "").strip()
    if raw == "":
        return MAX_RESEARCH
    try:
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ValueError
        n = int(raw)
    except ValueError:
        raise ValueError(f"SEARCH_MAX_RESEARCH는 0~{MAX_RESEARCH} 정수다: {raw!r}") from None
    if not 0 <= n <= MAX_RESEARCH:
        raise ValueError(f"SEARCH_MAX_RESEARCH는 0~{MAX_RESEARCH} 정수다: {raw!r}")
    return n


def resolve_judge_answer(value: str | None = None) -> str:
    """판정과 답 작성을 묶는 방식. 인자, 환경 변수 `GRAPH_JUDGE_ANSWER` 순이다. 비어 있거나 off이면 꺼짐("")이고, parallel과 joint 밖의 값은 ValueError다."""
    raw = (value if value is not None else (os.environ.get("GRAPH_JUDGE_ANSWER") or "")).strip().lower()
    if raw in ("", "off"):
        return ""
    if raw not in JUDGE_ANSWER_MODES:
        raise ValueError(f"GRAPH_JUDGE_ANSWER는 {' 또는 '.join(JUDGE_ANSWER_MODES)}이다: {raw!r}")
    return raw


def build_graph(
    retriever: Callable[[SearchQuery], list[Chunk]] | None = None,
    checkpointer=None,
    *,
    llm=None,
    answer_store: AnswerStore | None = None,
    store=None,
    use_skills: bool | None = None,
    grounding_llm: bool | None = None,
    decompose: bool | None = None,
    decision_repo=None,
    review_graph=None,
    section_reader=None,
    parallel_intake: bool | None = None,
    brief_output: bool | None = None,
    max_research: int | None = None,
    judge_answer: str | None = None,
    skip_first_rewrite: bool | None = None,
    stop_stalled_search: bool | None = None,
    ground_skip_backed: bool | None = None,
    json_only: bool | None = None,
    page_search: Callable[..., list] | None = None,
    intro_search: Callable[..., list] | None = None,
):
    """컴파일된 질문 그래프를 만든다.

    - retriever: `SearchQuery -> list[Chunk]`. None이면 `backend.rag.retrieve.search`.
    - llm: `.invoke(messages)`를 가진 채팅 모델. None이면 `get_chat_model()`(키가 없으면 데모 모드).
    - store: 장기 기억 Store. None이면 InMemoryStore.
    - use_skills: None이면 환경변수 USE_SKILLS를 따른다. True/False는 켬과 끔 비교용이다.
    - grounding_llm: 근거 판정에 LLM을 쓸지. None이면 데모 모드가 아닐 때만 쓴다. 코드 규칙은 이 값과 무관하게 돈다.
    - review_graph: 합동 검토 하위 그래프(`backend.graph.departments.review.build_review_graph(...)`). 있으면 질문 종류가 review일 때 그쪽으로 보낸다.
      하위 그래프에는 체크포인터를 따로 주지 않는다(이 그래프의 체크포인터를 쓴다). 없으면 review도 정책 질문으로 처리한다.
      승인함에 올리려면 `build_review_graph(..., approvals=저장소)`로 만들고, 재개 경로의 `app.state.review_graph`에는 이 질문 그래프를 넣는다(대화 체크포인트가 이 그래프에 있다).
    - decompose: 첫 검색 전에 한국어 원 질문을 LLM으로 나눌지. None이면 환경 변수 `SEARCH_DECOMPOSE`를 따른다(`decompose_enabled()`: 기본 켬, 0, false, no, off이면 끔).
      켜면 첫 검색은 원 질문과 하위 질문(`sub_queries`)을 넘기고, 재검색은 재작성 검색어만 분해 없이 넘긴다. 측정 전용 검색기(저장된 분해를 읽는다)는 끈다.
    - parallel_intake: `classify`, 첫 `rewrite`, 첫 검색의 분해를 동시에 부를지. None이면 환경 변수 `GRAPH_PARALLEL_INTAKE`(기본 꺼짐). 세 호출의 입력은 질문과 프로필뿐이라 서로의 결과를 쓰지 않는다.
      정책 경로로 가지 않는 질문(도메인 밖, 연결된 결정표와 합동 검토)이면 나머지 결과를 버린다. 끄면 스레드를 쓰지 않고 호출 순서가 그대로다.
    - brief_output: 근거 충분 판정과 근거 판정의 이유 설명을 짧게 쓰게 할지. None이면 환경 변수 `LLM_BRIEF_OUTPUT`(기본 꺼짐). 코드가 읽는 칸은 그대로다.
    - max_research: 재검색 상한 0~2. None이면 환경 변수 `SEARCH_MAX_RESEARCH`(기본 2). 그 밖의 값은 ValueError.
    - judge_answer: None이면 환경 변수 `GRAPH_JUDGE_ANSWER`(기본 꺼짐). `parallel`은 첫 판정과 답 작성을 지금 프롬프트 그대로 동시에 부르고 판정이 충분일 때만 그 답을 쓴다.
      `joint`는 두 프롬프트를 합친 한 호출로 판정과 답을 같이 받는다. 어느 쪽도 부분 답(`judge_partial`)은 지금처럼 `write_answer`가 따로 쓴다.
    - skip_first_rewrite: None이면 환경 변수 `GRAPH_SKIP_FIRST_REWRITE`(기본 꺼짐). 분해를 켜면 첫 검색은 원 질문을 쓰므로 첫 재작성의 검색어가 쓰이지 않는다. 시점을 뽑을 일이 없으면 그 호출을 건너뛴다.
    - stop_stalled_search: None이면 환경 변수 `GRAPH_STOP_STALLED_SEARCH`(기본 꺼짐). 재검색이 근거를 더하지 못했거나 근거 목록이 `MAX_CHUNKS`로 찼으면 더 찾지 않고, 입력이 같은 판정은 다시 부르지 않는다.
    - ground_skip_backed: None이면 환경 변수 `GROUND_SKIP_BACKED`(기본 꺼짐). 답의 모든 문장에 값이 있고 그 값이 인용한 청크에 있으면(`grounding.values_backed`) 근거 판정 LLM을 건너뛴다. 코드 규칙과 인용 검사는 그대로 돈다.
    - json_only: None이면 환경 변수 `LLM_JSON_ONLY`(기본 꺼짐). 그래프의 호출에 `response_format=json_object`를 붙인다(OpenRouter, OpenAI 전용).
    """
    retrieve = retriever or default_retriever
    read_section = section_reader or default_section_reader
    llm = llm if llm is not None else get_chat_model()
    store = store if store is not None else InMemoryStore()
    # 키 없는 데모(녹화 재생)는 사용자 기억을 쓰지 않는다: 녹화는 기억이 없는 요청이라, 기억(소속)이 분류·재작성 입력과 검색 범위에 들어가면 녹화 키가 어긋나 녹화한 질문까지 거절된다(K-18).
    # 서버는 모델을 `SharedChatModel`(처음 부를 때 만드는 껍데기)로 감싸 넘기므로 요청 때 안쪽 모델을 본다. 만들 때 보면 모델을 앞당겨 만들게 된다.
    def replay_demo() -> bool:
        inner = llm.model() if isinstance(llm, SharedChatModel) else llm
        return isinstance(inner, ReplayChatModel)

    research_limit = resolve_max_research(max_research)
    run_parallel = env_flag("GRAPH_PARALLEL_INTAKE") if parallel_intake is None else bool(parallel_intake)
    brief = env_flag("LLM_BRIEF_OUTPUT") if brief_output is None else bool(brief_output)
    judge_system = P.JUDGE_SYSTEM_BRIEF if brief else P.JUDGE_SYSTEM
    judge_query_on = env_flag("GRAPH_JUDGE_QUERY")
    section_extra = env_flag("GRAPH_SECTION_KEEPS_RESEARCH")  # 섹션 읽기가 재검색 기회를 쓰지 않는다. 재검색 상한을 줄였을 때만 쓴다
    if judge_query_on:
        judge_system = P.judge_with_query(judge_system)
    grounding_system = P.GROUNDING_SYSTEM_BRIEF if brief else P.GROUNDING_SYSTEM
    structured = P.structured_stages()
    judge_quote = AF.judge_quote_enabled()  # 인용 먼저 판정(`GRAPH_JUDGE_QUOTE`, 기본 꺼짐): 사실마다 원문 구절을 먼저 복사하고 결론은 코드가 그 목록에서 정한다
    judge_retry_fast = AF.judge_retry_fast_enabled()  # JRF(`GRAPH_JUDGE_RETRY_FAST`, 기본 꺼짐): 나뉜 질문이고 앞 판정이 일부일 때, 재검색 뒤 판정만 추론을 끈다(단계 표지 judge_retry)
    revise_ahead_on = AF.revise_ahead_enabled()  # RA(`GRAPH_REVISE_AHEAD`, 기본 꺼짐, SG 필요): 답 다시 쓰기와 동시에 문장 빼기 뒤 재확인을 미리 부른다
    judge_vote = AF.judge_vote_enabled()  # 판정 다수결(`GRAPH_JUDGE_VOTE`, 기본 꺼짐): 판정과 근거 확인을 병렬 3번 부르고 2표가 같으면 확정한다
    if judge_quote:
        judge_system = P.judge_quoted(judge_system, query=judge_query_on)
    elif "judge" in structured:
        judge_system = P.judge_checked(judge_system, query=judge_query_on)
    grounding_quote = AF.grounding_quote_enabled()  # Q(`GRAPH_GROUNDING_QUOTE`, 기본 꺼짐): 구절 먼저 찾고 판정, 번역·말 바꿈과 제목 경로 간접 근거 인정
    if "grounding" in structured or grounding_quote:
        grounding_system = P.grounding_quoted(grounding_system) if grounding_quote else P.grounding_checked(grounding_system)
    requery_terms = env_flag("GRAPH_REQUERY_TERMS") and judge_query_on
    if requery_terms:
        judge_system = P.judge_terms(judge_system)
    answer_base = P.ANSWER_SYSTEM
    answer_system = P.answer_picked(answer_base) if "answer" in structured else answer_base
    # 첫 검색어 코드 보강(기본 꺼짐, query_plan.py). 끄면 검색어, 하위 질문, 답 입력이 #44 측정 구성과 같다
    query_branches = QP.branches_enabled()
    # 놓친 문항 해결안(기본 꺼짐, answer_fixes.py). 끄면 입력, 프롬프트, 인용이 #50 측정 구성과 같다
    cite_expand, cite_multi, team_last, keep_cites = AF.cite_expand_enabled(), AF.cite_multi_enabled(), AF.team_last_enabled(), AF.keep_cites_enabled()
    sub_research = AF.sub_research_enabled()
    page_research = AF.page_research_enabled() and page_search is not None  # page_search: (하위 질문, rule_seq 목록, org, as_of, k) -> 청크 목록
    unknown_name = AF.unknown_name_enabled()
    corpus = AF.corpus_text() if unknown_name else ""
    refuse_on_none = AF.refuse_on_none_enabled()  # R: 첫 판정이 전무면 재검색 없이 거절
    same_page = AF.research_same_page_enabled() and page_search is not None  # 가: 부분 판정 뒤 재검색을 문맥 페이지 안 검색으로 바꾼다
    cite_phrase = AF.cite_phrase_enabled()  # A1b: 인용 청크와 긴 문장을 그대로 공유하는 다른 페이지 청크를 인용에 더한다
    drop_scoped = AF.drop_scoped_enabled()  # P: 질문에 없는 한정어가 붙은 페이지만 인용한 문장을 뺀다
    intro_fill = AF.intro_fill_enabled() and intro_search is not None  # R3: 같은 페이지 청크가 3개 이상이면 그 페이지 도입부 절 청크 1개를 더한다
    scope_refuse = AF.scope_note_refuse_enabled()  # SN: 충분 판정의 scope_note가 범위 한정과 부재를 함께 말하면 거절한다
    skip_seen = AF.requery_skip_seen_enabled()  # SS: 페이지 재검색이 문맥에 이미 있는 청크를 건너뛰고 새 청크만 가져온다
    consensus = AF.consensus_enabled()  # CS: 한 문장의 인용 중 여러 페이지가 되풀이하는 문장을 공유하지 않는 인용을 뺀다
    pointer_refuse = AF.pointer_refuse_enabled()  # PT: 근거 구절이 모두 다른 자료를 가리키는 안내뿐이면 거절한다(Q 형식에서만 구절이 있다)
    unchanged_rejudge = AF.unchanged_rejudge_enabled()  # UR: 다시 쓴 답이 처음 답과 같으면 그 답을 한 번 더 판정한다
    facts_log = AF.facts_log_enabled()  # FL(진단): 판정 checks와 첫 답의 asked·picks를 상태에 남긴다. 답 경로는 그대로다
    best2 = AF.answer_best2_enabled()  # BO2: 답을 같은 입력으로 두 번 쓰고 판정 구절이 든 청크와 맞는 쪽을 고른다(`--judge-quote`와 함께)
    best2_samedoc = AF.best2_samedoc_enabled()  # BO2SD: BO2의 둘째 규칙에서 S 청크와 같은 문서인 S 밖 인용은 세지 않는다
    speculate = AF.speculate_enabled()  # SP: 분해를 기다리는 동안 원 질문으로 첫 검색과 판정을 미리 돌리고, 분해가 나누지 않으면 그 결과를 쓴다
    save_one_conn = env_flag("ANSWER_SAVE_ONE_CONN")  # 62.16: 답 저장과 근거 기록 저장을 연결 하나로(`PgAnswerStore.save_with_grounding`). 기본 꺼짐
    spec_runs: dict[str, tuple[str, Any]] = {}  # SP: 열쇠(search_cache[SPEC_KEY]) -> ("use" | "drop", 미리 돌린 결과 Future)
    spec_boxes: dict[str, dict] = {}  # SP: 열쇠 -> 미리 돌리기 상태(돌렸는지). 첫 검색 노드가 기록 표시를 쓰고 지운다
    spec_lock = threading.Lock()
    speculate_ground = AF.speculate_ground_enabled()  # SG: 답 후보가 나오는 대로 근거 판정을 미리 부르고, 같은 입력의 판정이 필요할 때 그 결과를 쓴다
    ground_runs: dict[str, tuple[float, Any]] = {}  # SG: 판정 입력의 해시 -> (시작 시각, 미리 돌린 판정 Future). 쓰면 꺼낸다
    ground_lock = threading.Lock()
    ground_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ground_ahead") if speculate_ground else None
    if AF.cite_pick_enabled():  # CP: 같은 사실을 여러 자료가 말할 때 근거 고르는 순서를 답 프롬프트에 더한다(추론 답, 빠른 답, 다시 쓰는 답)
        answer_base, answer_system = P._add_rule(answer_base, AF.CITE_PICK_RULE), P._add_rule(answer_system, AF.CITE_PICK_RULE)
    if cite_multi:  # `GRAPH_CITE_MULTI=1`: 같은 사실을 다른 페이지가 말하면 3개까지 표시한다
        answer_base, answer_system = AF.relax_one_source(answer_base), AF.relax_one_source(answer_system)
    if AF.requery_vocab_enabled() and judge_query_on:  # `GRAPH_REQUERY_VOCAB=1`: 재검색어가 하위 질문의 영어 용어를 지킨다
        judge_system = P._add_rule(judge_system, AF.REQUERY_VOCAB_RULE)
    # `GRAPH_ANSWER_WAIT_S`(초): 추론을 켠 답과 빠른 답을 같이 보내 추론 답을 이 시간까지 기다리고, 넘으면 빠른 답을 쓴다. 다시 쓰는 답은 빠른 쪽이다
    answer_wait = float(os.environ.get("GRAPH_ANSWER_WAIT_S") or 0)
    # `GRAPH_ANSWER_BUDGET_S`(초): 질문을 받은 뒤 이 시간이 지나면 추론 답을 기다리지 않는다. 앞 단계가 늦은 질문에서 대기를 줄여 전체 시간을 맞춘다
    answer_budget = float(os.environ.get("GRAPH_ANSWER_BUDGET_S") or 0) if answer_wait else 0.0
    # `GRAPH_DECOMPOSE_CAP_S`(초, 기본 꺼짐): 첫 검색의 질문 분해가 이 시간 안에 오지 않으면 원 질문 하나로 검색하고 늦은 분해는 버린다(출처 `capped`)
    decompose_cap = float(os.environ.get("GRAPH_DECOMPOSE_CAP_S") or 0)
    if answer_wait:
        answer_system = answer_system.replace("[[task:answer]]", "[[task:answer_fast]]", 1)
    together = resolve_judge_answer(judge_answer)
    joint_system = P.judge_answer_system(judge_system)
    skip_rewrite = env_flag("GRAPH_SKIP_FIRST_REWRITE") if skip_first_rewrite is None else bool(skip_first_rewrite)
    stop_stalled = env_flag("GRAPH_STOP_STALLED_SEARCH") if stop_stalled_search is None else bool(stop_stalled_search)
    skip_ground = env_flag("GROUND_SKIP_BACKED") if ground_skip_backed is None else bool(ground_skip_backed)
    call_options = {"response_format": {"type": "json_object"}} if (env_flag("LLM_JSON_ONLY") if json_only is None else json_only) else {}
    # 추론을 끄면 모델이 JSON 대신 글로 답해 그 호출을 통째로 다시 하는 일이 생긴다. 입력 끝에 형식을 다시 적으면 막힌다. `response_format`은 공급자가 지키지 않았다(측정 사전 확인). 기본 꺼짐
    json_reminder = f"\n\n{P.JSON_REMINDER}" if env_flag("LLM_JSON_REMINDER") else ""

    def ask(system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        system = P.at_head(system)  # 대조군 `GRAPH_PROMPTS_HEAD=1`일 때만 바뀐다(기본 꺼짐)
        return _text(llm.invoke([SystemMessage(content=system), HumanMessage(content=user + json_reminder)], **call_options))

    def ask_json(system: str, user: str) -> tuple[dict | None, str]:
        raw = ""
        for _ in range(JSON_ATTEMPTS):
            raw = ask(system, user)
            obj = parse_json_obj(raw)
            if obj is not None:
                return obj, raw
        return None, raw

    def voted(task: str, node: str, call: Callable[[], dict | None]) -> dict | None:
        """`GRAPH_JUDGE_VOTE=1`이면 같은 호출을 병렬로 3번 보내 다수결로 합친다(`answer_fixes.merge_votes`). 2표가 같으면 셋째를 기다리지 않는다.
        모두 실패하면 첫 오류를 그대로 올린다. 꺼져 있으면 한 번만 부른다."""
        if not judge_vote:
            return call()
        pool = ThreadPoolExecutor(max_workers=AF.VOTES, thread_name_prefix=f"vote_{task}")
        got: list[dict] = []
        errors: list[BaseException] = []
        try:
            for fut in as_completed([in_background(pool, node, call) for _ in range(AF.VOTES)]):
                try:
                    got.append(fut.result() or {})
                except CostCapExceeded:
                    raise
                except Exception as e:  # noqa: BLE001  한 표의 실패는 빈 표로 둔다
                    errors.append(e)
                    got.append({})
                if AF.votes_settled(task, [g for g in got if g]):
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if not any(got) and errors:
            raise errors[0]
        return AF.merge_votes(task, got) or None

    def ask_judge(system: str, user: str) -> dict | None:
        def once() -> dict | None:
            obj, _ = ask_json(system, user)
            return AF.judge_from_quotes(obj) if obj and judge_quote else obj

        return voted("judge", "judge", once)

    def skill(name: str) -> str:
        return load_skill(name, enabled=skills_enabled() if use_skills is None else use_skills)

    def note_skills(state: AgentState, *names: str) -> list[str]:
        return list(dict.fromkeys([*state.get("skills_used", []), *names]))

    def scope_org(state: AgentState) -> str | None:
        """검색 범위(절). 입력의 절, 사용자가 직접 정한 소속 순이다. 둘 다 없으면 전체 절이다."""
        return state.get("org") or (state.get("profile") or {}).get("affiliation") or None

    def memo_search(state: AgentState, q: SearchQuery) -> tuple[list[dict], dict]:
        """한 번의 실행 안에서 같은 검색(질의, 절, 기준일, k, 하위 질문)은 한 번만 한다. 하위 질문이 다르면 다른 검색이다."""
        key = json.dumps([q.query, q.org, q.as_of, q.k, q.sub_queries], ensure_ascii=False)
        cache = dict(state.get("search_cache") or {})
        stats = dict(state.get("search_stats") or {"calls": 0, "cache_hits": 0})
        if key in cache:
            stats["cache_hits"] += 1
            return cache[key], {"search_cache": cache, "search_stats": stats}
        chunks = [redact_chunk(c.model_dump()) for c in retrieve(q)]  # 직접 호출과 MCP가 같은 본문을 받는다
        cache[key] = chunks
        stats["calls"] += 1
        return chunks, {"search_cache": cache, "search_stats": stats}

    # ---- 노드 ----
    def load_memory(state: AgentState) -> dict:
        user_id = state.get("user_id") or ""
        return {
            **{k: v for k, v in LEFTOVER_FIELDS.items() if k in state},
            **({"started_at": time.monotonic()} if answer_budget else {}),
            "profile": get_profile(store, user_id) if user_id and not replay_demo() else {},
            "as_of": state.get("as_of") or date.today().isoformat(),
            "as_of_given": bool(state.get("as_of")),
            "kind": "",
            "answer": "",
            "retries": 0,
            "judge_reason": "",
            "judge_partial": False,
            "next_section": None,
            "clarify_question": None,
            "raw_citations": [],
            "citations": [],
            "dropped_citations": [],
            "trimmed_citations": [],
            "sub_queries": [],
            "decompose_source": "",
            "search_error": "",
            "chunks": [],
            "answer_id": None,
            "drafted": False,
            "period_covered": None,
            "refuse_reason": "",
            "grounding": {},
            "skills_used": [],
            "search_cache": {},
            "search_stats": {"calls": 0, "cache_hits": 0},
        }

    def split_first_search() -> bool:
        return decompose_enabled() if decompose is None else decompose

    def rewrite_reply(state: AgentState) -> dict:
        """재작성 LLM 응답. 첫 재작성에서 입력은 질문과 프로필뿐이다(앞선 판정 사유가 없다). 재검색이면 빠진 사실과 이미 찾은 문서 제목을 넘겨, 찾은 문서로 되돌아가는 검색어를 막는다."""
        system = P.with_skills(P.REWRITE_SYSTEM, [("용어 Skill", skill("glossary"))])
        reason = state.get("judge_reason") or None
        seen = P.seen_titles(state.get("chunks") or []) if reason else []
        obj, _ = ask_json(system, P.rewrite_user(state["question"], state.get("profile", {}), reason, missing=state.get("judge_missing") or (), seen=seen))
        obj = obj or {}
        query = obj.get("query")
        if reason and isinstance(query, str) and U.leaks_instruction(query, state.get("chunks") or [], state["question"]):
            # 출력 검사(사전 등록 62.26): 재작성 결과가 이미 찾은 문서의 지시에서 온 표식·문장을 옮겼으면 그 검색어는 쓰지 않고 원 질문으로 검색한다
            log.warning("재작성 검색어에서 원문 지시를 옮긴 부분을 찾아 원 질문으로 되돌린다")
            obj = {**obj, "query": state["question"]}
        return obj

    def in_background(pool: ThreadPoolExecutor, node: str, fn: Callable[[], Any]) -> Any:
        """지금의 실행 문맥(콜백, LLM 기록)을 옮겨 부른다. 기록에는 순차로 돌 때의 노드 이름으로 남긴다."""
        def call() -> Any:
            base = var_child_runnable_config.get() or {}
            var_child_runnable_config.set({**base, "metadata": {**(base.get("metadata") or {}), "langgraph_node": node}})
            return fn()

        return pool.submit(contextvars.copy_context().run, call)

    def start_split(state: AgentState) -> tuple[Any, ThreadPoolExecutor, float]:
        """분해 상한을 켰을 때 분해를 따로 된 일꾼에서 시작한다. 상한을 넘긴 분해를 기다리지 않고 나가려고 접수 일꾼과 나눈다."""
        own = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decompose")
        started = time.monotonic()
        return in_background(own, "search", lambda: decompose_question(ask, state["question"])), own, started

    def finish_split(handle: tuple[Any, ThreadPoolExecutor, float]) -> tuple[list[str], str]:
        """시작한 뒤 `decompose_cap`초까지 기다린다. 넘으면 하위 질문 없이(원 질문 하나로) 검색하고 늦게 온 결과는 버린다. 분해의 오류는 그대로 올린다."""
        future, own, started = handle
        try:
            return future.result(timeout=max(0.0, decompose_cap - (time.monotonic() - started)))
        except FutureTimeout:
            log.info("질문 분해 %.1f초 상한 초과: 원 질문으로 검색한다", decompose_cap)
            return [], "capped"
        finally:
            own.shutdown(wait=False, cancel_futures=True)

    def split_question(state: AgentState) -> tuple[list[str], str]:
        return finish_split(start_split(state)) if decompose_cap else decompose_question(ask, state["question"])

    def needs_rewrite_call(state: AgentState) -> bool:
        """재작성 LLM을 불러야 하는지. 재검색은 언제나 부른다. 분해가 켜진 첫 검색은 원 질문으로 찾으므로 재작성에서 쓰는 값은 기준 시점뿐이다(절은 입력과 프로필을 쓴다)."""
        if not skip_rewrite or state.get("retries", 0) or state.get("judge_reason"):
            return True
        return not split_first_search() or (mentions_period(state["question"]) and not state.get("as_of_given"))

    def takes_policy_path(route: str) -> bool:
        return route == "rule" or (route == "decision" and decision_repo is None) or (route == "review" and review_graph is None)

    def decision_ready(question: str) -> bool:
        """결정표는 금액이나 구간이 있어야 실행된다. 표가 하나도 없으면 실행할 것이 없다. 승인 대기 중인 표가 있으면 그 사유로 거절하도록 결정표 경로로 보낸다.
        저장소를 주지 않았으면 다음 단계에서 정책 경로로 간다."""
        if decision_repo is None:
            return True
        has_amount = bool(_AMOUNT_WORD.search(question or "")) or clarify_has_number(question or "")  # 날짜와 이름 속 숫자(2025년, SEV2)는 금액이 아니다
        return has_amount and bool(decision_repo.list_approved() or decision_repo.list_pending())

    def extract_decision_query(question: str) -> dict:
        """결정표 질문에서 업무 종류와 금액을 뽑는다(LLM 1회). 업무 종류는 승인된 목록 안의 값만(목록 밖 모델 글이 거절 문구로 나가지 않게)."""
        cats = sorted({t.cells[0]["category"] for t in decision_repo.list_approved() if t.cells})
        obj, _ = ask_json(DECISION_PARAMS_SYSTEM, params_user(question, cats))
        return params_from_obj(obj, cats)

    def classify(state: AgentState) -> dict:
        if P.only_asks_internal(state["question"]):   # 시스템 프롬프트를 내놓으라는 말뿐인 질문(번역·요약·인코딩 포함)은 모델을 부르지 않고 범위 밖으로 끝낸다
            return {"route": "out_of_domain"}
        picked: dict = {}   # 결정표 경로로 가기로 한 질문에서 분류 단계가 미리 뽑은 값. `decision_params`가 같은 값을 다시 뽑지 않고 쓴다

        def once() -> str:
            obj, _ = ask_json(P.CLASSIFY_SYSTEM, P.classify_user(state["question"], state.get("profile", {})))
            return route_of(obj)

        def decide() -> str:
            route = once()
            if route == "decision" and not decision_ready(state["question"]):  # 결정표를 실행할 수 없는 질문을 거절로 끝내지 않고 핸드북에서 찾는다
                return "rule"
            if route == "decision" and decision_repo is not None:
                query = extract_decision_query(state["question"])
                if query["task_type"] is None:  # 승인된 표 중 질문이 묻는 업무 종류가 없다(외부 SaaS 도입처럼 표 이름과 바로 맞지 않는 질문). 거절하지 않고 핸드북(금액 구간 검색 포함)에서 찾는다
                    return "rule"
                picked.update(query)
            if route == "review" and review_graph is not None and asks_fact_not_review(state["question"] or ""):  # 사실을 묻는 질문을 승인 대기로 멈추지 않는다
                return "rule"
            # 도메인 밖은 검색 없이 끝나 뒤 단계가 되돌릴 수 없다. 두 번 다 도메인 밖일 때만 따르고, 갈리면 일반 정책 경로로 보낸다
            if route == "out_of_domain" and once() != "out_of_domain":
                route = "rule"
            return route

        if not run_parallel:
            route = decide()
            return {"route": route, **({"decision_query": picked} if route == "decision" else {})}

        # 모두 끝난 뒤에 나간다: 답이 나간 뒤에 호출이 돌아 비용과 기록에 늦게 잡히는 일이 없다
        # 분해 상한을 켜면 분해는 접수 일꾼 밖에서 돈다: 상한을 넘긴 분해가 끝날 때까지 접수가 기다리지 않는다
        capped = start_split(state) if decompose_cap and split_first_search() else None
        spec = start_speculation(state) if speculate and split_first_search() and capped is None and not needs_rewrite_call(state) else None
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="intake") as pool:
                rewriting = in_background(pool, "rewrite", lambda: rewrite_reply(state)) if needs_rewrite_call(state) else None
                splitting = in_background(pool, "search", lambda: decompose_question(ask, state["question"])) if split_first_search() and capped is None else None
                route = decide()
                if spec is not None:
                    spec["route"] = route
                    spec["routed"].set()
        finally:
            if spec is not None:
                spec["routed"].set()
        if not takes_policy_path(route):  # 순차라면 부르지 않았을 호출이다. 결과와 오류를 모두 버린다
            if capped is not None:
                capped[1].shutdown(wait=False, cancel_futures=True)
            if spec is not None:  # SP: 예비 분해만 돌았다(판정 전에 경로를 본다). 끝날 때까지 기다려 늦은 호출을 남기지 않는다
                drain_speculation(spec["future"])
            return {"route": route, **({"decision_query": picked} if route == "decision" else {})}
        early = {"rewrite": rewriting.result()} if rewriting is not None else {}  # 순차와 같은 순서로 오류를 올린다: 분류, 재작성, 분해
        if splitting is not None:
            early["decompose"] = list(splitting.result())
        elif capped is not None:
            early["decompose"] = list(finish_split(capped))
        cache = {**(state.get("search_cache") or {}), INTAKE_KEY: early}
        if spec is not None:  # SP: 분해가 나누지 않았으면(미리 돌린 상태와 같으면) 미리 돌린 결과를 쓰고, 나눴으면 버린다(끝까지 기다려 기록에 남긴다)
            use = early.get("decompose") == [[], "llm"]
            if not use:
                spec["stop"].set()
            with spec_lock:
                spec_runs[spec["token"]] = ("use" if use else "drop", spec["future"])
                spec_boxes[spec["token"]] = spec
            cache[SPEC_KEY] = spec["token"]
        return {"route": route, "search_cache": cache}

    def start_speculation(state: AgentState) -> dict:
        """SP: 예비 분해(추론 수준은 `decompose_gate` 단계 값)를 부르고, 나누지 않는다고 하면 분류가 정책 경로로 정해진 뒤 원 질문으로 재작성·첫 검색·판정을 미리 돌린다.
        미리 돌리는 상태는 분해가 나누지 않았을 때 분류 노드가 내는 상태와 같다(같은 열쇠까지). 분해가 나누면 판정 전에 멈추고, 이미 판정 중이면 끝까지 돌린 뒤 버린다."""
        token = uuid.uuid4().hex
        box: dict = {"token": token, "routed": threading.Event(), "stop": threading.Event(), "route": ""}
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speculate")

        def as_node(node: str, fn: Callable[[], Any]) -> Any:
            base = var_child_runnable_config.get() or {}
            var_child_runnable_config.set({**base, "metadata": {**(base.get("metadata") or {}), "langgraph_node": node}})
            return fn()

        def chain() -> dict | None:
            if as_node("search", lambda: gate_split(ask, state["question"])) is not False:
                return None
            box["routed"].wait()
            if not takes_policy_path(box["route"]) or box["stop"].is_set():
                return None
            s: dict = {**state, "route": box["route"], "search_cache": {**(state.get("search_cache") or {}), INTAKE_KEY: {"decompose": [[], "llm"]}, SPEC_KEY: token}}
            out: dict = {}
            box["ran"] = True
            for node, fn in (("rewrite", rewrite), ("search", search), ("judge", judge)):
                if box["stop"].is_set():
                    return None
                out[node] = as_node(node, lambda fn=fn: fn(s))
                s = {**s, **out[node]}
                if node == "search" and s.get("search_error"):
                    break
            return out

        box["future"] = pool.submit(contextvars.copy_context().run, chain)
        pool.shutdown(wait=False)
        return box

    def drain_speculation(future: Any) -> None:
        """SP: 버린 미리 돌리기가 끝날 때까지 기다린다(답이 나간 뒤에 호출이 돌지 않게). 오류는 버리고 비용 상한만 올린다."""
        try:
            future.result()
        except Exception as e:  # noqa: BLE001
            if isinstance(e, CostCapExceeded):
                raise
            log.warning("미리 돌린 판정 실패(버림): %s", type(e).__name__)

    def spec_take(state: AgentState, node: str) -> dict | None:
        """SP: 이 노드의 미리 돌린 결과. 쓰는 것이 아니면 None(그 노드를 그대로 돌린다). 판정까지 꺼내면 자리를 지운다. 미리 돌리기의 오류는 그대로 올린다."""
        token = (state.get("search_cache") or {}).get(SPEC_KEY)
        if not token:
            return None
        with spec_lock:
            entry = spec_runs.get(token)
        if entry is None or entry[0] != "use":
            return None
        try:
            res = entry[1].result()
        except BaseException:
            with spec_lock:
                spec_runs.pop(token, None)
            raise
        if not res or node not in res:
            with spec_lock:
                spec_runs.pop(token, None)
            return None
        if node == "judge" or (node == "search" and "judge" not in res):
            with spec_lock:
                spec_runs.pop(token, None)
        return res[node]

    def spec_drop(state: AgentState) -> None:
        """SP: 버린 미리 돌리기가 있으면 끝날 때까지 기다리고 자리를 지운다."""
        token = (state.get("search_cache") or {}).get(SPEC_KEY)
        if not token:
            return
        with spec_lock:
            entry = spec_runs.get(token)
            if entry is None or entry[0] != "drop":
                return
            spec_runs.pop(token, None)
        drain_speculation(entry[1])

    def rewrite_node(state: AgentState) -> dict:
        got = spec_take(state, "rewrite")
        return got if got is not None else rewrite(state)

    def search_node(state: AgentState) -> dict:
        got = spec_take(state, "search")
        if got is not None:
            with spec_lock:
                spec_boxes.pop((state.get("search_cache") or {}).get(SPEC_KEY), None)
            return {**got, "search_stats": {**(got.get("search_stats") or {}), "speculated": "used"}}
        out = search(state)
        token = (state.get("search_cache") or {}).get(SPEC_KEY)
        with spec_lock:
            box = spec_boxes.pop(token, None) if token else None
        if box is not None and not state.get("retries", 0):  # 미리 돌리기를 쓰지 않은 까닭(분석용): 돌렸다가 버림 | 예비 분해가 나눔·실패해 돌리지 않음
            out = {**out, "search_stats": {**(out.get("search_stats") or state.get("search_stats") or {}), "speculated": "dropped" if box.get("ran") else "not_run"}}
        if out.get("search_error"):
            spec_drop(state)
        return out

    def judge_node(state: AgentState) -> dict:
        got = spec_take(state, "judge")
        if got is not None:
            return got
        out = judge(state)
        spec_drop(state)  # 이 판정이 끝난 뒤에 기다린다(버린 쪽이 먼저 시작해 대개 이미 끝났다)
        return out

    def decision_params(state: AgentState) -> dict:
        """결정표 질문에서 업무 종류와 금액을 뽑는다(LLM 1회). 분류 단계가 이미 뽑았으면(`decision_query`) 그 값을 쓴다. 실행은 다음 노드(LLM 없음)."""
        if state.get("decision_query"):   # 새 질문마다 `load_memory`가 비우므로 앞 질문의 값이 아니다
            return {}
        return {"decision_query": extract_decision_query(state["question"])}

    run_decision = make_execute_node(DecisionExecutor(decision_repo)) if decision_repo is not None else None

    def decision_answer(state: AgentState) -> dict:
        """실행 결과를 코드로 한국어 답으로 쓴다. 거절이면 이유를 그대로 알린다."""
        if state.get("decision_error"):
            return {"kind": "refuse", "answer": "결정표를 실행하지 않았습니다: " + state["decision_error"]["message"], "citations": []}
        return {"kind": "answer", "answer": format_decision_answer(state["decision_result"]), "citations": [decision_citation(state["decision_result"])]}

    def out_of_domain(state: AgentState) -> dict:
        """분명히 핸드북과 무관한 질문은 재작성과 검색 없이 거절한다."""
        return {"kind": "refuse", "answer": MSG_REFUSE_OUT_OF_DOMAIN, "citations": []}

    def rewrite(state: AgentState) -> dict:
        if state.get("next_section"):  # 판정이 찾은 섹션 읽기를 골랐다. 검색어를 새로 만들지 않는다(LLM 호출 없음)
            return {"search_query": state.get("search_query") or state["question"]}
        if state.get("sub_research_phase") == "due":  # B1, B4: 빠진 하위 질문을 원래 문구로 한 번 더 찾는다(LLM 호출 없음)
            return {"search_query": state["sub_research"], "sub_research_phase": "search"}
        from_judge = (state.get("judge_query") or "").strip() if judge_query_on and state.get("retries", 0) else ""
        if from_judge:  # 판정이 빠진 사실의 검색어까지 냈다. 재작성 LLM을 부르지 않는다
            return {"search_query": from_judge, "search_org": state.get("org") or scope_org(state), "judge_query": ""}
        q = state["question"]
        gloss = skill("glossary")
        early = (state.get("search_cache") or {}).get(INTAKE_KEY) or {}
        if "rewrite" not in early and not needs_rewrite_call(state):  # 부르지 않은 재작성의 용어 Skill은 쓴 것으로 적지 않는다
            obj, gloss = {}, ""
        else:
            obj = early["rewrite"] if "rewrite" in early else rewrite_reply(state)
        query = obj["query"] if isinstance(obj.get("query"), str) and obj["query"].strip() else q
        org = state.get("org") or (obj["org"] if isinstance(obj.get("org"), str) and obj["org"].strip() else None)
        upd: dict = {
            "search_query": query,
            "search_org": org or scope_org(state),
            "skills_used": note_skills(state, *(["glossary"] if gloss else [])),
        }
        if _valid_date(obj.get("as_of")) and not state.get("as_of_given") and mentions_period(q):
            upd["as_of"] = obj["as_of"]
        if "rewrite" in early:  # 미리 받은 응답은 한 번만 쓴다. 재검색의 재작성은 판정 사유를 받아 새로 부른다
            left = {k: v for k, v in early.items() if k != "rewrite"}
            kept = {k: v for k, v in state["search_cache"].items() if k != INTAKE_KEY}
            upd["search_cache"] = {**kept, INTAKE_KEY: left} if left else kept
        return upd

    def widen(state: AgentState, target: dict) -> dict:
        """찾은 청크를 섹션 전체로 넓힌다(`get_section`). 읽지 못하면 그대로 두고 다음 판정에 맡긴다."""
        found = None
        try:
            found = read_section(target["rule_seq"], target["article"], state.get("as_of"))
        except Exception as e:  # noqa: BLE001 - 섹션 읽기 실패가 답을 막지 않는다
            log.warning("섹션 읽기 실패: %s", type(e).__name__)
        stats = dict(state.get("search_stats") or {"calls": 0, "cache_hits": 0})
        stats["section_reads"] = stats.get("section_reads", 0) + 1
        fresh = {"judged_chunks": 0} if stop_stalled else {}  # 근거 수가 같아도 본문이 바뀌었으니 다시 판정한다
        # 섹션 본문이 늘어도 청크 수는 같을 수 있다. 판정이 새 본문을 다시 보게 앞 판정의 청크 수를 지운다
        return {"chunks": expand_chunk(state.get("chunks", []), target["chunk_id"], found), "next_section": None, "search_stats": stats, "judged_chunks": 0, **fresh}

    def sub_search(state: AgentState) -> dict:
        """B1(`GRAPH_SUB_RESEARCH`)은 그 하위 질문을 전체에서, B4(`GRAPH_PAGE_RESEARCH`)는 지금 문맥의 페이지 안에서 찾는다. 둘 다 켜면 번갈아 합친다.
        이때만 근거 목록 상한을 한 번 검색분(`SEARCH_K`) 늘린다. 검색이 안 되면 그대로 두고 판정에 넘긴다."""
        sub, chunks = state["sub_research"], state.get("chunks", [])
        upd: dict = {"sub_research_phase": "done"}
        lists: list[list[dict]] = []
        if sub_research:
            try:
                found, memo = memo_search(state, SearchQuery(query=sub, org=state.get("search_org"), as_of=state.get("as_of"), k=SEARCH_K))
                lists.append(found)
                upd.update(memo)
            except EmbedUnavailable as e:
                log.warning("하위 질문 재검색 실패: %s", e)
        if page_research:
            seqs = sorted({int(c["rule_seq"]) for c in chunks if c.get("rule_seq") is not None})
            try:
                got = page_search(sub, seqs, state.get("search_org"), state.get("as_of"), SEARCH_K) if seqs else []
                lists.append([redact_chunk(c.model_dump() if hasattr(c, "model_dump") else dict(c)) for c in got])
            except Exception as e:  # noqa: BLE001 - 페이지 범위 재검색 실패가 답을 막지 않는다
                log.warning("페이지 범위 재검색 실패: %s", type(e).__name__)
        mixed = [c for group in zip_longest(*lists) for c in group if c is not None]
        return {**upd, "chunks": merge_chunks(chunks, mixed, limit=chunk_cap(state.get("sub_queries"), state.get("question")) + SEARCH_K)}

    def page_requery(state: AgentState) -> dict:
        """가(`GRAPH_RESEARCH_SAME_PAGE`): 재검색어(`search_query`)로 지금 문맥에 든 페이지(rule_seq, 문맥 순서) 안에서만 찾는다. 전체 검색은 하지 않는다.
        결과는 재검색과 같이 앞 목록에 합친다. 검색이 안 되면 목록을 그대로 두고 판정에 넘긴다."""
        chunks = state.get("chunks", [])
        seqs = list(dict.fromkeys(int(c["rule_seq"]) for c in chunks if c.get("rule_seq") is not None))
        stats = dict(state.get("search_stats") or {"calls": 0, "cache_hits": 0})
        stats["page_requeries"] = stats.get("page_requeries", 0) + 1
        found: list[dict] = []
        have = {c.get("chunk_id") for c in chunks}
        try:
            want = SEARCH_K + len(have) if skip_seen else SEARCH_K  # SS: 문맥에 있는 청크만큼 더 받아 거르고 새 청크 REQUERY_NEW개만 쓴다
            got = page_search(state.get("search_query") or state["question"], seqs, state.get("search_org"), state.get("as_of"), want) if seqs else []
            found = [redact_chunk(c.model_dump() if hasattr(c, "model_dump") else dict(c)) for c in got]
            if skip_seen:
                found = [c for c in found if c.get("chunk_id") not in have][:REQUERY_NEW]
        except Exception as e:  # noqa: BLE001 - 페이지 범위 재검색 실패가 답을 막지 않는다
            log.warning("페이지 범위 재검색 실패: %s", type(e).__name__)
        return {"chunks": merge_chunks(chunks, found, limit=chunk_cap(state.get("sub_queries"), state.get("question"))), "search_stats": stats}

    def with_intro(state: AgentState, chunks: list[dict], query: str) -> list[dict]:
        """R3(`GRAPH_INTRO_FILL`): 첫 검색 문맥에 같은 페이지 판 청크가 3개 이상인 페이지의 도입부 절 청크(질문 벡터와 가장 가까운 1개, 절이 2개 이하 청크면 절 전체)를 뒤에 더한다.
        재검색(페이지 재검색, 하위 질문 재검색) 뒤에는 붙이지 않는다.
        query는 이 검색이 방금 임베딩한 질문이다(다시 임베딩하지 않는다). 이미 그 절이 문맥에 있으면 더하지 않으므로 여러 번 불러도 같다. 실패하면 그대로 둔다."""
        if not intro_fill or not chunks:
            return chunks
        try:
            got = intro_search(chunks, query, state.get("search_org"), state.get("as_of"))
        except Exception as e:  # noqa: BLE001 - 도입부 채우기 실패가 답을 막지 않는다
            log.warning("도입부 채우기 실패: %s", type(e).__name__)
            return chunks
        added = [redact_chunk(c.model_dump() if hasattr(c, "model_dump") else dict(c)) for c in got]
        return merge_chunks(chunks, added, limit=len(chunks) + len(added)) if added else chunks

    def search(state: AgentState) -> dict:
        if state.get("next_section"):
            return widen(state, state["next_section"])
        if state.get("sub_research_phase") == "search":
            return sub_search(state)
        if same_page and state.get("retries", 0) and state.get("judge_partial"):  # 가: 부분 판정 뒤 재검색은 문맥 페이지 안에서만 찾는다(횟수는 그대로)
            return page_requery(state)
        if unknown_name and not state.get("retries", 0):  # `GRAPH_UNKNOWN_NAME=1`: 코퍼스 어디에도 없는 영문 구를 묻는 질문은 검색 없이 되묻는다
            unknown = AF.unknown_phrases(state["question"], corpus)
            if unknown:
                return {"kind": "clarify", "answer": AF.unknown_name_message(AF.quotable_phrases(state["question"], corpus)), "citations": [], "search_error": "unknown_name"}
        # 질문 분해는 첫 검색에서만, 사용자가 쓴 한국어 원 질문으로 한다(측정과 같다). 하위 질문은 검색에 넘기고 검색은 질문을 LLM으로 나누지 않는다.
        # 재검색은 재작성 검색어 하나로 분해 없이 찾는다.
        first = state.get("retries", 0) == 0
        split = first and split_first_search()
        extra: dict = {}
        subs: list[str] = []
        early = (state.get("search_cache") or {}).get(INTAKE_KEY)
        cleared: dict = {}
        if early is not None:  # 미리 받은 분해 결과를 꺼내고 자리를 지운다
            state = {**state, "search_cache": {k: v for k, v in state["search_cache"].items() if k != INTAKE_KEY}}
            cleared = {"search_cache": state["search_cache"]}
        if split:
            subs, source = early["decompose"] if early is not None and "decompose" in early else split_question(state)
            extra = {"sub_queries": subs, "decompose_source": source}
        query = drop_company_prefix([state["question"]])[0] if split else state["search_query"]
        if split and query_branches:  # `GRAPH_QUERY_BRANCHES`(기본 꺼짐): 대상에 따라 절차가 갈리는 주제의 하위 질문을 대상마다 나눈다(query_plan.py)
            plan = QP.plan_first_search(state["question"], query, subs, branches=query_branches)
            query, subs = plan.query, plan.subs
            extra = {**extra, "sub_queries": subs, "query_targets": plan.targets}
        q = SearchQuery(query=query, org=state.get("search_org"), as_of=state.get("as_of"),
                        k=split_k(state["question"], subs) if first else SEARCH_K, sub_queries=subs or None)  # 나뉜 질문의 첫 검색만 SPLIT_K(달러 금액이 든 질문은 SEARCH_K)
        _forget_search_trace()
        try:
            found, memo = memo_search(state, q)
        except EmbedUnavailable as e:  # 임베딩 API가 잠깐 안 되는 경우: 죽지 않고 정해진 거절로 끝낸다(다시 시도하면 될 수 있다)
            log.warning("검색 임베딩 API 일시 오류: %s", e)
            return {**extra, **cleared, "kind": "refuse", "answer": MSG_REFUSE_SEARCH_DOWN, "citations": [], "search_error": "unavailable"}
        if not found and _search_fallback_reason() == "no_key":  # 키 없는 데모: 같은 검색을 되풀이하지 않고 끝낸다
            return {**extra, **memo, "kind": "refuse", "answer": MSG_REFUSE_NO_KEY, "citations": [], "search_error": "no_key"}
        # 재검색은 앞 결과를 버리지 않고 합친다. 판단, 인용 검사, 근거 판정은 모두 이 합친 목록과 대조한다
        merged = merge_chunks(state.get("chunks", []), found, limit=chunk_cap(subs if first else state.get("sub_queries"), state["question"]))
        return {"chunks": with_intro(state, merged, query) if first else merged, **memo, **extra}  # R3는 첫 검색에만 붙인다

    def judge(state: AgentState) -> dict:
        chunks = state.get("chunks", [])
        if not chunks:  # 자료가 없으면 LLM에 묻지 않고 부족으로 본다
            return {"judge_reason": "검색 결과 없음", "judge_partial": False, "retries": state.get("retries", 0) + 1}
        seen: dict = {"judged_chunks": len(chunks)} if stop_stalled else {}
        core_ids = [c["chunk_id"] for c in core_chunks(state)]
        widened = judge_quote and len(core_ids) < len(chunks)  # 넓힌 첫 검색이고 인용 먼저 판정일 때만(사전 등록 62.44)
        judge_input = P.judge_user(state["question"], chunks, state.get("sub_queries") or (), extra=[c["chunk_id"] for c in chunks[len(core_ids):]] if widened else ())
        guide = skill("chat-tool-guide")  # 켜져 있을 때만 판정이 다음 도구를 고른다. 호출 수는 그대로다
        terms = skill("search-terms") if requery_terms else ""  # `GRAPH_REQUERY_TERMS=1`일 때만 재검색어 용어표를 붙인다(기본 꺼짐)
        guided = P.with_skills(judge_system, [("도구 고르기 Skill", guide), ("용어 Skill", terms)])
        if judge_retry_fast and state.get("retries", 0) and state.get("judge_partial") and len(state.get("sub_queries") or []) >= 2:
            guided = P.judge_retry(guided)  # JRF: 나뉜 질문의 재검색 뒤 판정은 단계 표지만 바꿔 추론을 끈다. 본문과 입력은 그대로
        if widened:
            guided = P.judge_widened(guided)  # 넓힌 자리가 있는 판정에만 구절을 앞자리에서 먼저 찾게 하는 문장을 더한다
        names = [*(["chat-tool-guide"] if guide else []), *(["search-terms"] if terms else [])]
        used = {"skills_used": note_skills(state, *names)} if names else {}
        if stop_stalled and state.get("retries", 0) and state.get("judged_chunks") == len(chunks):  # 재검색이 근거를 더하지 못했다. 입력이 같으므로 앞 판정을 그대로 두고 더 찾지 않는다
            return {"search_stalled": True, "retries": state.get("retries", 0) + 1}
        early: dict | None = None
        writing = None
        if together == "joint":
            obj, early = judge_and_draft(state, chunks)
        elif together == "parallel_all" or (together == "parallel" and not state.get("retries", 0)):  # 근거가 충분한 질문은 대개 첫 판정에서 끝난다. 재검색 뒤에는 순차로 둬서 버리는 호출을 줄인다
            pool = ThreadPoolExecutor(max_workers=2 if best2 else 1, thread_name_prefix="draft")  # 기본은 모두 끝난 뒤에 나간다: 답이 나간 뒤에 호출이 돌아 비용과 기록에 늦게 잡히는 일이 없다
            try:
                writing = in_background(pool, "write_answer", lambda: timed_reply(state, core=bool(best2 and widened)))
                writing2 = in_background(pool, "write_answer", lambda: timed_reply(state)) if best2 else None  # BO2: 같은 입력으로 하나 더
                obj = ask_judge(guided, judge_input)
                if (obj or {}).get("sufficient") is True or (answer_wait and last_partial(state, obj or {})):
                    # 충분이면 같이 쓴 답을 쓴다(부족이면 순차라면 부르지 않았을 호출이라 결과와 오류를 모두 버린다).
                    # 기다리는 답을 켜고 재검색이 끝나 일부 답으로 가면 같이 쓴 답을 그대로 쓴다(새로 쓰는 시간을 아낀다)
                    early = writing.result() if writing2 is None else pick_two(writing, writing2, AF.quote_chunk_ids(obj, chunks), chunks, core_ids if widened else None)
            finally:
                pool.shutdown(wait=not answer_wait, cancel_futures=bool(answer_wait))  # 기다리는 답을 켜면 판정이 부족일 때 답을 기다리지 않는다
        else:
            obj = ask_judge(guided, judge_input)
        obj = obj or {}
        if best2:  # BO2: 판정 구절이 든 청크(나중에 따로 쓰는 답이 고를 때 쓴다)
            used = {**used, "judge_quote_ids": AF.quote_chunk_ids(obj, chunks)}
        if facts_log:  # FL: 판정 기록만 쌓는다(결론과 다음 단계는 그대로)
            used = {**used, "judge_checks_log": [*(state.get("judge_checks_log") or []), AF.judge_facts(obj, state.get("retries", 0))]}
        if scope_refuse and AF.scope_note_refuses(obj):
            # SN: 충분이라면서 자료가 다른 대상에 한정되고 질문한 것은 없다고 판정이 스스로 적었다. 충분으로 보지 않고 일부 근거로 바꿔 재검색 규칙을 따른다
            # (재검색이 끝나면 나뉜 질문은 일부 답, 아니면 거절). 충분 판정으로 같이 받은 답은 버린다
            note = str(obj.get("scope_note")).strip()
            missing0 = obj.get("missing") if isinstance(obj.get("missing"), list) else []
            obj = {**obj, "sufficient": False, "partial": True, "reason": note, "missing": [*missing0, note]}
            early = None
            used = {**used, "early_answer": {}}
        if obj.get("sufficient") is True:  # 파싱 실패나 모호한 값은 부족으로 본다
            return {"judge_reason": "", "judge_partial": False, "judge_missing": [], "judge_scope": "", "next_section": None, **seen, **used, **({"early_answer": early} if early else {})}
        clarify = obj["clarify"] if isinstance(obj.get("clarify"), str) and obj["clarify"].strip() else None
        missing = obj.get("missing") if isinstance(obj.get("missing"), list) else []
        scope = obj.get("scope_note")
        requeried = skip_seen and (state.get("search_stats") or {}).get("page_requeries")  # SS: 페이지 재검색으로 새 청크를 받은 뒤에는 섹션 읽기를 더 하지 않는다
        section = pick_section(obj, chunks) if guide and not (section_extra and state.get("section_reads", 0)) and not requeried else None
        out = {
            **({"early_answer": early} if early and answer_wait else {}),
            "judge_reason": str(obj.get("reason") or "근거 부족"),
            "judge_partial": obj.get("partial") is True,
            "judge_missing": [m.strip() for m in missing if isinstance(m, str) and m.strip()][:MAX_MISSING],
            "judge_query": obj["query"].strip() if isinstance(obj.get("query"), str) else "",
            "judge_scope": scope.strip() if isinstance(scope, str) else "",
            "clarify_question": clarify,
            "retries": state.get("retries", 0) + 1,
            "next_section": section,
            "section_reads": state.get("section_reads", 0) + (1 if section else 0),
            **seen,
            **used,
        }
        # R: 첫 판정이 전무면 섹션 읽기와 재검색 없이 거절한다. 다수결 표가 갈렸으면(충분이나 일부라고 한 표가 있다) 바로 거절하지 않고 재검색 뒤 다시 판정한다(사전 등록 62.33)
        if refuse_on_none and not state.get("retries", 0) and AF.judged_none(obj) and AF.votes_unanimous(obj):
            return {**out, "judge_none": True, "next_section": None, "section_reads": state.get("section_reads", 0)}
        return {**out, **due_sub_research(state, out)}

    def due_sub_research(state: AgentState, out: dict) -> dict:
        """B1, B4: 이번 판정으로 일부 근거 답(나뉜 질문)으로 끝나게 됐고 판정이 빠졌다고 한 사실에 맞는 하위 질문이 있으면, 그 하위 질문을 한 번 더 찾게 한다(질문당 한 번)."""
        if not (sub_research or page_research) or state.get("sub_research_phase") or not out.get("judge_partial"):
            return {}
        if after_judge({**state, **out}) != "write_answer":  # 재검색이 남았으면 그쪽이 먼저다
            return {}
        sub = AF.pick_missing_sub(state.get("sub_queries") or [], out.get("judge_missing") or [])
        return {"sub_research": sub, "sub_research_phase": "due"} if sub else {}

    def last_partial(state: AgentState, obj: dict) -> bool:
        """이번 판정이 부족이고 일부 답으로 끝나는지(재검색이 남지 않음). `after_judge`와 같은 규칙을 판정 결과로 미리 본다."""
        if obj.get("sufficient") is True or obj.get("partial") is not True:
            return False
        chunks = state.get("chunks", [])
        nxt = {**state, "judge_reason": str(obj.get("reason") or "근거 부족"), "judge_partial": True, "retries": state.get("retries", 0) + 1,
               "next_section": None, "judged_chunks": len(chunks)}
        return after_judge(nxt) == "write_answer"

    def after_judge(state: AgentState) -> str:
        if not state.get("judge_reason"):
            return "write_answer"
        if state.get("judge_none"):  # R(`GRAPH_REFUSE_ON_NONE`): 첫 판정이 전무
            return "give_up"
        if state.get("sub_research_phase") == "due":  # B1, B4: 빠진 하위 질문 한 번 더(그때만 재검색 상한 +1)
            return "rewrite"
        # 근거 목록이 차면 `merge_chunks`가 새 청크를 받지 못해 재검색이 아무것도 바꾸지 못한다
        stalled = stop_stalled and not state.get("next_section") and (state.get("search_stalled") or len(state.get("chunks", [])) >= chunk_cap(state.get("sub_queries"), state.get("question")))  # 섹션 읽기는 목록을 늘리지 않는다
        if state.get("retries", 0) <= research_limit + (state.get("section_reads", 0) if section_extra else 0) and not stalled:
            return "rewrite"
        # 재검색이 끝나도 일부 근거만 있으면 그 부분을 답한다. 나뉜 질문(사실 둘 이상)일 때만이다. 사실이 하나인 질문의 "일부"는 없는 대상을 비슷한 자료로 답하는 길이 된다
        return "write_answer" if state.get("judge_partial") and len(state.get("sub_queries") or []) >= 2 else "give_up"

    def give_up(state: AgentState) -> dict:
        ask_back = state.get("clarify_question")
        if ask_back and leaks_internal(ask_back):  # 되묻기 문장도 사용자에게 그대로 나가므로 답과 같은 유출 검사를 한다(verify를 거치지 않는 길)
            return {"kind": "refuse", "answer": MSG_REFUSE_LEAK, "citations": []}
        if ask_back and U.scrub_enabled():  # 출력 검사(사전 등록 62.26): 되묻기에도 원문 지시에서 온 표식·문장을 옮긴 문장이 없어야 한다. 남는 문장이 없으면 거절한다
            scrubbed, removed = U.scrub_answer(ask_back, state.get("chunks", []), state["question"])
            if removed:
                if not scrubbed.strip():
                    return {"kind": "refuse", "answer": MSG_REFUSE_LEAK, "citations": []}
                ask_back = scrubbed
        if ask_back and not clarify_has_number(ask_back):  # 숫자를 담은 되묻기는 인용 없이 수치를 말하는 것이라 거절로 바꾼다
            return {"kind": "clarify", "answer": ask_back, "citations": []}
        return {"kind": "refuse", "answer": MSG_REFUSE, "citations": []}

    def draft_fields(obj: dict | None, raw: str, used: list[str]) -> dict:
        if obj is None:  # JSON이 아니면 인용을 알 수 없으므로 인용 검사가 거절한다
            return {"answer": raw, "raw_citations": [], "drafted": True, "skills_used": used}
        cites = obj.get("citations")
        return {
            "answer": str(obj.get("answer") or ""),
            "raw_citations": cites if isinstance(cites, list) else [],
            "period_covered": obj.get("period_covered") if isinstance(obj.get("period_covered"), bool) else None,
            "drafted": True,
            "skills_used": used,
            **({"answer_facts": AF.answer_facts(obj)} if facts_log else {}),
        }

    def answer_blocks(state: AgentState) -> list[tuple[str, str]]:
        """답 작성에 붙이는 Skill. 권한표를 읽는 답이면 `delegation`도 붙인다(SDD 258줄). LLM 호출 수는 그대로다."""
        rules = skill("citation-rules")
        blocks = [("인용 규칙 Skill", AF.relax_skill(rules) if cite_multi else rules)]
        if reads_authz(state):
            blocks.append(("승인 권한표 Skill", skill("delegation")))
        return blocks

    def answer_skills_used(state: AgentState, blocks: list[tuple[str, str]]) -> list[str]:
        return note_skills(state, *[name for name, (_, body) in zip(("citation-rules", "delegation"), blocks) if body])

    def draft_reply(state: AgentState, careful: bool = False, abandoned: threading.Event | None = None, core: bool = False) -> dict:
        blocks = answer_blocks(state)
        system = P.with_skills(answer_base if careful else answer_system, blocks)
        used = answer_skills_used(state, blocks)
        chunks = core_chunks(state) if core else state.get("chunks", [])
        if team_last:  # `GRAPH_TEAM_LAST=1`: 질문이 팀을 말하지 않으면 팀 문서를 답 입력 뒤로 보낸다(빼지 않고 순서만)
            chunks = AF.team_docs_last(state["question"], chunks)
        user = P.answer_user(state["question"], chunks, state.get("as_of"), partial=bool(state.get("judge_partial")), scope_note=state.get("judge_scope") or "")
        targets = (state.get("query_targets") or []) if query_branches else []
        obj, raw = ask_json(system, user + QP.targets_note(targets))
        missing = QP.missing_targets(str((obj or {}).get("answer") or ""), targets) if obj is not None else []
        if missing:  # `GRAPH_QUERY_BRANCHES=1`: 답이 대상 하나를 빠뜨리면 빠진 대상을 적어 한 번 다시 쓴다. 다시 쓴 답이 JSON이 아니면 앞 답을 쓴다
            again, raw2 = ask_json(system, user + QP.targets_note(targets, missing))
            if again is not None:
                obj, raw = again, raw2
        out = draft_fields(obj, raw, used)
        if abandoned is None or not abandoned.is_set():  # 추론 답이 대기 시간을 넘겨 빠른 답으로 넘어갔으면 이 답의 근거 판정은 쓰이지 않으므로 미리 부르지 않는다
            ground_ahead(state, out)
        return out

    def verdict_key(question: str, draft: str, cited: list[dict], as_of: str | None, body: str, chunks: list[dict], partial: bool) -> str:
        """근거 판정 LLM 호출의 입력 전체를 하나의 해시로 만든다. 입력이 하나라도 다르면 다른 열쇠다."""
        raw = json.dumps([question, draft, cited, as_of, body, chunks, partial], ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verdict_for(question: str, draft: str, cited: list[dict], as_of: str | None, body: str, chunks: list[dict], partial: bool = False) -> dict:
        """근거 판정 LLM 한 번. SG가 같은 입력으로 미리 돌려 둔 판정이 있으면 그 결과를 쓰고(`ahead` 표시), 없으면 `llm_verdict`를 부른다."""
        if speculate_ground:
            with ground_lock:
                run = ground_runs.pop(verdict_key(question, draft, cited, as_of, body, chunks, partial), None)
            if run is not None:
                return {**run[1].result(), "ahead": True}
        return llm_verdict(question, draft, cited, as_of, body, chunks, partial=partial)

    def ground_ahead(state: AgentState, cand: dict) -> None:
        """SG: 답 후보(`cand`)가 나오는 대로 `verify`와 같은 검사를 거친 뒤 `ground_once`가 부를 근거 판정을 같은 입력으로 미리 부른다.
        나중에 뽑힌 답이 이 후보와 같으면 `verdict_for`가 그 결과를 받는다. 뽑히지 않은 후보의 판정은 쓰이지 않고 버려진다(비용만). 실패하면 아무 일도 없다(그때는 지금처럼 부른다)."""
        if not speculate_ground or ground_pool is None or not cand.get("raw_citations") or not cand.get("answer"):
            return

        def start() -> None:
            try:
                v = verify({**state, **cand})
                if v.get("kind") != "answer":
                    return
                body = skill("grounding-check")
                if not body:
                    return
                if reads_authz(state):  # ground_once와 같은 입력
                    body = f"{body}\n\n[승인 권한표 Skill]\n{skill('delegation')}"
                cited, draft, chunks = v.get("citations", []), v.get("answer", ""), state.get("chunks", [])
                partial = bool(state.get("judge_partial"))
                llm_on = grounding_llm if grounding_llm is not None else not is_demo_mode()
                if not llm_on or not G.check_rules(state["question"], cited, chunks).ok or (skip_ground and not partial and G.values_backed(draft, cited)):
                    return
                key = verdict_key(state["question"], draft, cited, state.get("as_of"), body, chunks, partial)
                now = time.monotonic()
                with ground_lock:
                    for old in [k for k, (t, _) in ground_runs.items() if now - t > 120.0]:
                        ground_runs.pop(old, None)
                    if key in ground_runs or len(ground_runs) >= 64:
                        return
                    ground_runs[key] = (now, in_background(ground_pool, "ground", lambda: llm_verdict(state["question"], draft, cited, state.get("as_of"), body, chunks, partial=partial)))
            except Exception as e:  # noqa: BLE001 - 미리 하는 일이 실패해도 답 경로는 그대로 간다
                log.debug("근거 판정 미리 부르기 실패: %s", type(e).__name__)

        start()  # 검사는 로컬 계산이라 답을 낸 쪽에서 바로 돈다. 그래야 판정이 등록된 뒤에 답이 다음 단계로 넘어가 같은 호출이 두 번 나가지 않는다

    def timed_reply(state: AgentState, core: bool = False) -> dict:
        """`GRAPH_ANSWER_WAIT_S`가 있으면 첫 답은 추론 답을 그 시간까지 기다리고, 늦거나 실패하면 같이 보낸 빠른 답을 쓴다. 재검색 뒤의 답은 시간이 모자라 빠른 답이다."""
        if not answer_wait or state.get("retries", 0):
            return draft_reply(state, core=core)
        wait_s = answer_wait
        if answer_budget and state.get("started_at"):
            wait_s = min(answer_wait, answer_budget - (time.monotonic() - state["started_at"]))
        if wait_s <= 0:
            return draft_reply(state, core=core)
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="answer")
        try:
            gave_up = threading.Event()  # 추론 답을 쓰지 않기로 하면 세운다. 늦게 끝난 추론 답이 쓰이지 않을 근거 판정을 부르지 않게 한다
            slow = in_background(pool, "write_answer", lambda: draft_reply(state, careful=True, abandoned=gave_up, core=core))
            fast = in_background(pool, "write_answer", lambda: draft_reply(state, core=core))
            done, _ = wait_futures([slow], timeout=wait_s)
            if done and slow.exception() is None and slow.result().get("raw_citations"):
                return slow.result()
            gave_up.set()
            return fast.result()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def judge_and_draft(state: AgentState, chunks: list[dict]) -> tuple[dict | None, dict | None]:
        """판정과 답을 한 호출로 받는다(`GRAPH_JUDGE_ANSWER=joint`). 충분인데 answer 칸이 없으면 답을 돌려주지 않아 `write_answer`가 따로 쓴다."""
        blocks = answer_blocks({**state, "chunks": chunks})
        system = P.with_skills(joint_system, [*blocks, ("도구 고르기 Skill", skill("chat-tool-guide"))])
        used = answer_skills_used(state, blocks)
        shown = AF.team_docs_last(state["question"], chunks) if team_last else chunks
        obj, raw = ask_json(system, P.answer_user(state["question"], shown, state.get("as_of")))
        return obj, (draft_fields(obj, raw, used) if obj and obj.get("sufficient") is True and "answer" in obj else None)

    def pick_core_first(first: Any, second: Any, quote_ids: list[str], core_ids: list[str]) -> dict:
        """넓힌 첫 검색의 답 고르기(사전 등록 62.44). 판정 구절이 든 청크가 모두 앞 5자리 안이고 앞자리 답이 인용을 가진 답이면 앞자리 답(첫 후보),
        아니면 전체 문맥 답(둘째 후보)이다. 앞자리 답이 실패하면 전체 문맥 답을 쓰고, 전체 문맥 답이 실패하면 앞자리 답을 쓴다. 고른 기록은 `best2_log`에 `rule=core_first`로 담는다."""
        def settle(future: Any) -> dict | None:
            try:
                return future.result()
            except Exception as e:  # noqa: BLE001
                if isinstance(e, CostCapExceeded):
                    raise
                log.warning("넓힌 문맥 답 후보 실패: %s", type(e).__name__)
                return None

        a, b = settle(first), settle(second)
        if a is None and b is None:
            first.result()  # 둘 다 실패하면 현행과 같이 첫 답의 오류를 올린다
        usable = bool(a and a.get("raw_citations") and not G.says_only_absence(str(a.get("answer") or "")))
        in_core = set(quote_ids or []) <= set(core_ids)
        pick = 0 if b is None or (usable and in_core) else 1
        why = "한쪽 후보 없음" if a is None or b is None else "판정 구절이 넓힌 자리에 있음" if not in_core else "앞자리 답 없음" if not usable else "판정 구절이 모두 앞자리"
        cited = [[c.get("chunk_id") if isinstance(c, dict) else c for c in (d or {}).get("raw_citations") or []] for d in (a, b)]
        log_row = {"quote_ids": list(quote_ids or []), "cands": [{"cited": cited[0]}, {"cited": cited[1]}], "pick": pick, "why": why, "rule": "core_first"}
        return {**(a if pick == 0 else b), "best2_log": log_row}

    def pick_two(first: Any, second: Any, quote_ids: list[str], chunks: list[dict], core_ids: list[str] | None = None) -> dict:
        """BO2: 두 답 Future 중 하나. 첫 답의 오류는 그대로 올리고(현행과 같다), 둘째 답이 실패하면 첫 답을 쓴다. 고른 기록은 best2_log 칸에 담는다.
        BO2SD면 문맥 청크의 rule_seq로 S 밖 인용이 S 청크와 같은 문서인지 본다."""
        if core_ids is not None:  # 사전 등록 62.44: 넓힌 첫 검색. 첫 후보는 앞 5자리만 보고 쓴 답, 둘째 후보는 전체 문맥으로 쓴 답이다
            return pick_core_first(first, second, quote_ids, core_ids)
        a = first.result()
        try:
            b = second.result()
        except Exception as e:  # noqa: BLE001
            log.warning("BO2 둘째 답 실패: %s", type(e).__name__)
            b = None
        doc_of = {c.get("chunk_id"): c.get("rule_seq") for c in chunks or [] if c.get("chunk_id")} if best2_samedoc else None
        chosen, why = AF.pick_best2(a, b, quote_ids, doc_of)
        return {**chosen, "best2_log": why}

    def write_answer(state: AgentState) -> dict:
        early = state.get("early_answer")  # 판정이 충분이라고 한 호출에서 이미 받은 답이 있으면 그대로 쓴다. 쓴 Skill 기록은 판정이 더한 것과 합친다
        if early:
            return {**early, "skills_used": note_skills(state, *early.get("skills_used", []))}
        if not best2:
            return timed_reply(state)
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="answer2")  # BO2: 같은 입력으로 두 번 쓰고 판정 구절이 든 청크와 맞는 쪽
        try:
            core_ids = [c["chunk_id"] for c in core_chunks(state)]
            widened = judge_quote and len(core_ids) < len(state.get("chunks", []))
            one = in_background(pool, "write_answer", lambda: timed_reply(state, core=widened))
            two = in_background(pool, "write_answer", lambda: timed_reply(state))
            return pick_two(one, two, state.get("judge_quote_ids") or [], state.get("chunks", []), core_ids if widened else None)
        finally:
            pool.shutdown(wait=True)

    def verify(state: AgentState) -> dict:
        if leaks_internal(state.get("answer", "")):
            return {"kind": "refuse", "answer": MSG_REFUSE_LEAK, "citations": [], "dropped_citations": []}
        if U.scrub_enabled():  # 출력 검사(GRAPH_SCRUB_OUTPUT, 기본 켬): 검색 원문의 지시 문장에서 온 표식·문장을 옮긴 답 문장을 뺀다. 남는 문장이 없으면 거절한다
            scrubbed, removed = U.scrub_answer(state.get("answer", ""), state.get("chunks", []), state["question"])
            if removed:
                if not scrubbed.strip():
                    return {"kind": "refuse", "answer": MSG_REFUSE_LEAK, "citations": [], "dropped_citations": []}
                state = {**state, "answer": scrubbed}
        missing = G.period_missing(state["question"], state.get("answer", ""), state.get("period_covered"))
        if missing:  # 요청한 기간의 자료가 없다고 스스로 밝힌 답은 가까운 기간 값을 인용했어도 답으로 내지 않는다
            info = {"rules": "skipped(period_missing)", "llm": "off", "reason": G.OUT_OF_PERIOD, "detail": missing}
            return {"kind": "refuse", "answer": MSG_REFUSE_BY_REASON[G.OUT_OF_PERIOD], "citations": [], "dropped_citations": [],
                    "refuse_reason": G.OUT_OF_PERIOD, "grounding": info}
        valid, dropped, cleaned = check_citations(state.get("raw_citations", []), state.get("chunks", []), state.get("answer", ""))
        if not valid or not cleaned:
            return {"kind": "refuse", "answer": MSG_REFUSE_CITATION, "citations": [], "dropped_citations": dropped}
        if G.says_only_absence(cleaned) and _MARK.search(cleaned):  # 자료에 없다는 말뿐이다. 근거 있는 사실이 없으므로 답이 아니다
            return {"kind": "refuse", "answer": MSG_REFUSE_CITATION, "citations": [], "dropped_citations": dropped}
        unmarked = G.unmark_absence(cleaned)
        kept, trimmed, cleaned = select_citations(valid, unmarked if _MARK.search(unmarked) else cleaned)  # 표시가 모두 사라지면 앞 문장을 받치던 표시다. 그대로 둔다
        return {"kind": "answer", "answer": cleaned, "citations": kept, "dropped_citations": dropped, "trimmed_citations": [c["chunk_id"] for c in trimmed]}

    def after_verify(state: AgentState) -> str:
        return "ground" if state.get("kind") == "answer" else END

    def llm_verdict(question: str, answer: str, cited: list[dict], as_of: str | None, body: str, retrieved: list[dict], partial: bool = False) -> dict:
        """근거 판정 LLM 한 번. state는 grounded, ungrounded, inconclusive 중 하나다(명확히 거절한 경우만 ungrounded).
        인용 청크를 자료로, 같은 페이지의 다른 검색 청크를 참고로 넘긴다. 값은 자료에 있어야 한다(`GROUNDING_SYSTEM`)."""
        out: dict = {"state": "inconclusive", "code": "", "detail": "", "claims": []}
        try:
            system = P.with_skills(grounding_system, [("근거 판정 Skill", body)])
            user = P.grounding_user(question, answer, cited, as_of, G.same_page_context(cited, retrieved), partial=partial)
            evidence = [*cited, *retrieved]
            eased: list[str] = []
            recoded: list[str] = []

            def one_vote() -> dict | None:
                # 값은 받쳐졌고 값을 말하지 않는 단서 문장만 받쳐지지 않는다고 한 표는, 다수결에 넣기 전에 받쳐진 표로 센다(`grounding.caveat_only_vote`).
                # 표마다 꼽은 문장이 달라 합친 목록이 비어도 단서 때문에 거절되지 않는다. 값을 말하는 문장을 꼽은 표는 그대로다
                # 질문에 시점 표현이 없는데 모델 표가 out_of_period를 내면 unsupported 표로 읽는다(`grounding.recode_vote`, 사전 등록 62.29).
                # 바로 거절하지 않고 단서 구제와 다시 쓰기·재판정을 거친다
                obj = G.recode_vote(ask_json(system, user)[0], question)
                if isinstance(obj, dict) and obj.get("_recoded"):
                    recoded.append(obj["_recoded"])
                sentences = G.caveat_only_vote(obj, answer, question, evidence, cited=cited, retrieved=retrieved)
                if sentences:
                    eased.extend(sentences)
                    return {**obj, "grounded": True, "_caveat_only": sentences}
                return obj

            obj = voted("grounding", "ground", one_vote) or {}
            out.update(G.read_verdict(obj, answer, question, evidence))
            if eased and out["state"] == "grounded" and not out.get("caveat_only"):
                out["caveat_only"] = eased
            if recoded:
                out["recoded"] = sorted(set(recoded))
        except CostCapExceeded:
            raise
        except Exception as e:  # noqa: BLE001  호출 실패는 결론 없음으로 두고 코드 규칙 결과를 따른다
            log.warning("근거 판정 LLM 호출 실패: %s: %s", type(e).__name__, e)
            out["error"] = type(e).__name__
        return out

    def revise_answer(state: AgentState, cited: list[dict], verdict: dict, info: dict, body: str, used: list[str]) -> dict | None:
        """받쳐지지 않는 문장만 빼고 답을 유지한다. 남은 답은 인용 검사, 누출 검사, 코드 근거 규칙, 판정 LLM 재판정을 다시 거친다.
        하나라도 통과하지 못하면 None을 돌려주고, 호출한 쪽이 원래 판정대로 답 전체를 거절한다."""
        as_of, question, chunks = state.get("as_of"), state["question"], state.get("chunks", [])
        pruned = G.prune_answer(state["answer"], verdict["claims"])
        rec: dict = {"claims": verdict["claims"], "result": "pruned" if pruned.ok else pruned.reason, "removed": pruned.removed}
        info["revise"] = rec
        if not pruned.ok:
            return None
        cited_ids = {c["chunk_id"] for c in cited}
        raw = [{"chunk_id": i} for i in dict.fromkeys(_MARK.findall(pruned.answer)) if i in cited_ids]
        valid, dropped, cleaned = check_citations(raw, chunks, pruned.answer)
        if not valid or not cleaned or dropped or leaks_internal(cleaned) or U.leaks_instruction(cleaned, chunks, question):
            rec["result"] = "citation_check_failed"
            return None
        again = G.check_rules(question, valid, chunks)
        if not again.ok:
            rec["result"] = f"rules:{again.reason}"
            return None
        second = verdict_for(question, cleaned, valid, as_of, body, chunks)  # RA가 미리 불렀으면 그 결과(같은 입력), 아니면 지금처럼 부른다
        info["rejudge"] = second["state"]
        if second["state"] != "grounded":  # 더 빼지 않는다. 결론이 없어도 거절 쪽으로 둔다
            rec["result"] = f"rejudge_{second['state']}"
            return None
        info.update(revised=True, draft_answer=state["answer"], removed=[{"sentence": x, "reason": verdict["detail"]} for x in pruned.removed])
        # 뺀 문장이 있으면 답이 일부만 남았다고 밝힌다. 말없이 빼면 질문 전체에 답한 것처럼 보인다
        return {"kind": "answer", "answer": finish_answer(f"{cleaned} {MSG_PARTIAL_NOTE}", valid, as_of), "citations": valid, "grounding": info, "skills_used": used}

    def revise_ahead(state: AgentState, cited: list[dict], verdict: dict, body: str) -> str | None:
        """RA: `revise_answer`가 부를 재확인(문장 빼기 뒤 답)을 답 다시 쓰기와 동시에 미리 시작한다. LLM이 없는 앞부분(문장 빼기, 인용 검사, 누출 검사, 코드 규칙)은
        `revise_answer`와 같은 계산을 먼저 하고, 모두 통과했을 때만 같은 입력으로 `llm_verdict`를 `ground_pool`에 넣는다(`ground_runs`에 등록). 돌려주는 값은 등록 열쇠(없으면 None).
        실패하면 아무 일도 없다(그때는 `revise_answer`가 지금처럼 부른다)."""
        if not revise_ahead_on or not speculate_ground or ground_pool is None or not verdict.get("claims"):
            return None
        try:
            as_of, question, chunks = state.get("as_of"), state["question"], state.get("chunks", [])
            pruned = G.prune_answer(state["answer"], verdict["claims"])
            if not pruned.ok:
                return None
            cited_ids = {c["chunk_id"] for c in cited}
            raw = [{"chunk_id": i} for i in dict.fromkeys(_MARK.findall(pruned.answer)) if i in cited_ids]
            valid, dropped, cleaned = check_citations(raw, chunks, pruned.answer)
            if not valid or not cleaned or dropped or leaks_internal(cleaned) or U.leaks_instruction(cleaned, chunks, question):
                return None
            if not G.check_rules(question, valid, chunks).ok:
                return None
            key = verdict_key(question, cleaned, valid, as_of, body, chunks, False)
            now = time.monotonic()
            with ground_lock:
                if key in ground_runs or len(ground_runs) >= 64:
                    return None
                ground_runs[key] = (now, in_background(ground_pool, "ground", lambda: llm_verdict(question, cleaned, valid, as_of, body, chunks)))
            return key
        except Exception as e:  # noqa: BLE001 - 미리 하는 일이 실패해도 답 경로는 그대로 간다
            log.debug("문장 빼기 재확인 미리 부르기 실패: %s", type(e).__name__)
            return None

    def drop_ahead(key: str | None) -> None:
        """RA: 다시 쓴 답이 쓰이게 되어 미리 부른 재확인이 필요 없다. 아직 시작 전이면 취소하고 등록을 지운다(이미 간 호출은 결과를 버린다)."""
        if key is None:
            return
        with ground_lock:
            run = ground_runs.pop(key, None)
        if run is not None:
            run[1].cancel()

    def redraft_answer(state: AgentState, verdict: dict, info: dict, body: str, used: list[str]) -> dict | None:
        """받쳐지지 않는 주장이 있으면 판정 사유를 주고 답을 한 번 다시 쓴다. 문장 빼기보다 먼저 한다. 빼면 틀린 말이 섞인 핵심 문장까지 사라져 질문에 답하지 못하는 말이 남을 수 있다.
        판정 기준은 그대로이고 다시 쓴 답은 처음 답과 같은 검사(누출, 기간, 인용, 코드 규칙, 판정 LLM)를 모두 통과해야 나간다. 하나라도 걸리면 None을 돌려준다."""
        as_of, question, chunks = state.get("as_of"), state["question"], state.get("chunks", [])
        rec: dict = {"result": ""}
        info["redraft"] = rec
        try:
            shown = AF.team_docs_last(question, chunks) if team_last else chunks
            user = P.redraft_user(question, shown, as_of, state.get("answer", ""), verdict["detail"], verdict["claims"])
            obj, _ = ask_json(P.with_skills(answer_system, answer_blocks(state)), user)
        except CostCapExceeded:
            raise
        except Exception as e:  # noqa: BLE001  호출 실패는 다시 쓰지 못한 것으로 보고 원래 판정대로 거절한다
            log.warning("답 다시 쓰기 호출 실패: %s: %s", type(e).__name__, e)
            rec["result"] = "error"
            return None
        obj = obj or {}
        text = str(obj.get("answer") or "")
        rec["answer"] = text
        if not text.strip():
            rec["result"] = "empty"
        elif G.same_text(text, state.get("answer", "")):  # 그대로면 판정 결과도 같다
            rec["result"] = "unchanged"
        elif leaks_internal(text) or U.leaks_instruction(text, chunks, question) or G.period_missing(question, text, obj.get("period_covered")):
            rec["result"] = "answer_check_failed"
        if rec["result"] == "unchanged" and unchanged_rejudge:
            # UR: 판정 사유를 받고도 다시 쓰는 답이 처음 답을 그대로 냈다(두 호출의 의견이 갈림). 처음 답을 같은 입력으로 한 번 더 판정하고 받쳐지면 그대로 낸다
            cited, partial = state.get("citations", []), bool(state.get("judge_partial"))
            second = llm_verdict(question, state.get("answer", ""), cited, as_of, body, chunks, partial=partial)
            rec["rejudge"] = second["state"]
            if second["state"] == "grounded" and not (pointer_refuse and AF.pointer_only(second.get("quotes"))):  # PT 기준은 그대로 적용한다
                info.update(rejudged_unchanged=True)
                draft = state.get("answer", "")
                return {"kind": "answer", "answer": finish_answer(f"{draft} {MSG_PARTIAL_NOTE}" if partial else draft, cited, as_of), "citations": cited, "grounding": info, "skills_used": used}
        if rec["result"]:
            return None
        raw = obj.get("citations")
        valid, dropped, cleaned = check_citations(raw if isinstance(raw, list) else [], chunks, text)
        if dropped:
            rec["dropped"] = dropped
        if not valid or not cleaned or dropped:
            rec["result"] = "citation_check_failed"
            return None
        if G.says_only_absence(cleaned) and _MARK.search(cleaned):
            rec["result"] = "citation_check_failed"
            return None
        unmarked = G.unmark_absence(cleaned)
        kept, trimmed, cleaned = select_citations(valid, unmarked if _MARK.search(unmarked) else cleaned)
        if keep_cites:  # `GRAPH_KEEP_CITES=1`: 처음 답에서 지적받지 않은 문장의 인용을 코드가 넘겨받는다. 아래 검사와 재판정을 그대로 거친다
            before = len(kept)
            cleaned, kept = AF.carry_citations(state.get("answer", ""), state.get("citations", []), verdict["claims"], cleaned, kept, cap=MAX_CITATIONS)
            if len(kept) > before:
                rec["carried"] = [c["chunk_id"] for c in kept[before:]]
        again = G.check_rules(question, kept, chunks)
        if not again.ok:
            rec["result"] = f"rules:{again.reason}"
            return None
        second = llm_verdict(question, cleaned, kept, as_of, body, chunks)
        rec["result"] = f"rejudge_{second['state']}"
        if second["state"] != "grounded":
            return None
        info.update(redrafted=True, draft_answer=state.get("answer", ""))
        text = f"{cleaned} {MSG_PARTIAL_NOTE}" if obj.get("partial") is True or state.get("judge_partial") else cleaned
        return {"kind": "answer", "answer": finish_answer(text, kept, as_of), "citations": kept, "trimmed_citations": [c["chunk_id"] for c in trimmed], "grounding": info, "skills_used": used}

    def without_off_topic(state: AgentState, cited: list[dict], claims: list[str], info: dict, partial: bool) -> dict | None:
        """받쳐지지만 묻지 않은 내용을 덧붙인 문장을 뺀다. 남은 문장은 이미 받쳐졌으므로 다시 판정하지 않는다. 뺄 수 없으면 None(답을 그대로 둔다)."""
        draft, chunks, question = state.get("answer", ""), state.get("chunks", []), state["question"]
        pruned = G.prune_answer(draft, claims)
        rec: dict = {"claims": claims, "result": "pruned" if pruned.ok else pruned.reason, "removed": pruned.removed}
        info["off_topic"] = rec
        if not pruned.ok:
            return None
        ids = set(_MARK.findall(pruned.answer))
        kept = [c for c in cited if c["chunk_id"] in ids]
        if not kept:
            rec["result"] = "no_citation_left"
            return None
        if not G.check_rules(question, kept, chunks).ok:
            rec["result"] = "rules_failed"
            return None
        info["draft_answer"] = draft
        gone = [c["chunk_id"] for c in cited if c["chunk_id"] not in ids]
        text = f"{pruned.answer} {MSG_PARTIAL_NOTE}" if partial else pruned.answer
        return {"answer": finish_answer(text, kept, state.get("as_of")), "citations": kept, "trimmed_citations": [*(state.get("trimmed_citations") or []), *gone]}

    def ground_once(state: AgentState) -> dict:
        """인용 검사를 통과한 답이 검색된 근거로 받쳐지는지 본다. 코드 규칙이 먼저이고, 한쪽이라도 거절하면 거절한다.
        LLM이 받쳐지지 않는 주장이 있다고 하면(`unsupported`) 답을 한 번 다시 쓰고(`redraft_answer`), 안 되면 그 문장만 빼 본다(`revise_answer`). 그 밖의 사유는 전체를 거절한다."""
        body = skill("grounding-check")
        if body and reads_authz(state):  # 답을 쓸 때와 같은 권한표 읽기로 판정한다. 아니면 구간 읽기를 받쳐지지 않았다고 본다
            body = f"{body}\n\n[승인 권한표 Skill]\n{skill('delegation')}"
        as_of, cited = state.get("as_of"), state.get("citations", [])
        partial = bool(state.get("judge_partial"))  # 일부 근거만 있어 그 부분만 쓴 답. 나머지를 뺐다고 코드가 밝힌다
        draft = state.get("answer", "")
        final = {"answer": finish_answer(f"{draft} {MSG_PARTIAL_NOTE}" if partial else draft, cited, as_of)}
        if not body:  # USE_SKILLS를 끄면 건너뛴다
            return {**final, "grounding": {"llm": "off", "rules": "skipped(USE_SKILLS off)"}}
        used = note_skills(state, "grounding-check")
        v = G.check_rules(state["question"], cited, state.get("chunks", []))
        info: dict = {"rules": v.checks, "llm": "off", **({"partial_route": True} if partial else {})}
        reason, detail = v.reason, v.detail
        llm_on = grounding_llm if grounding_llm is not None else not is_demo_mode()
        if v.ok and llm_on and skip_ground and not partial and G.values_backed(draft, cited):  # 값이 모두 인용 청크에 있다. 코드 규칙과 인용 검사는 이미 지났다
            info["llm"] = "skipped(values_backed)"
        elif v.ok and llm_on:
            verdict = verdict_for(state["question"], draft, cited, as_of, body, state.get("chunks", []), partial=partial)
            if verdict.get("ahead"):
                info["ground_ahead"] = True
            info["llm"] = "ungrounded" if verdict["state"] == "ungrounded" else verdict["state"]
            if verdict.get("error"):
                info["llm_error"] = verdict["error"]
            if verdict.get("caveat_only"):
                info["caveat_only"] = True
            if verdict.get("recoded"):
                info["recoded"] = verdict["recoded"]
            if verdict["state"] == "ungrounded":
                reason, detail = verdict["code"], verdict["detail"]
                revised = None
                if reason == G.UNSUPPORTED:
                    ahead_key = revise_ahead(state, cited, verdict, body)  # RA: 켜져 있을 때만 문장 빼기 재확인을 다시 쓰기와 동시에 시작한다
                    revised = redraft_answer(state, verdict, info, body, used)
                    if revised is not None:
                        drop_ahead(ahead_key)
                    if revised is None and verdict["claims"]:
                        revised = revise_answer(state, cited, verdict, info, body, used)
                    if revised is not None:
                        return revised
            elif verdict["state"] == "grounded" and pointer_refuse and AF.pointer_only(verdict.get("quotes")):
                # PT: 판정이 받친다고 한 구절이 모두 다른 자료를 가리키는 안내뿐이다. 질문한 내용은 자료에 없으므로 다시 쓰지 않고 거절한다
                reason, detail = G.UNSUPPORTED, "근거 구절이 다른 자료를 가리키는 안내뿐"
                info["pointer_only"] = True
            elif verdict["state"] == "grounded" and verdict.get("off_topic") and not reason:
                final = without_off_topic(state, cited, verdict["off_topic"], info, partial) or final
        if reason:
            info.update(reason=reason, detail=detail, draft_answer=draft)  # 판정 사유와 초안은 기록에만 둔다. 청크 id 같은 내부 값을 사용자에게 보이지 않는다
            return {
                "kind": "refuse",
                "answer": MSG_REFUSE_BY_REASON[reason],
                "citations": [],
                "dropped_citations": [*state.get("dropped_citations", []), *(info.get("redraft") or {}).get("dropped", [])],
                "refuse_reason": reason,
                "grounding": info,
                "skills_used": used,
            }
        return {**final, "grounding": info, "skills_used": used}

    def ground(state: AgentState) -> dict:
        """근거 판정(`ground_once`). `GRAPH_CITE_EXPAND=1`이면 판정이 끝난 답에 같은 값을 말하는 다른 청크의 인용을 코드가 더한다(LLM 호출 없음, 판정 입력은 그대로)."""
        out = ground_once(state)
        if not (cite_expand or cite_phrase or drop_scoped or consensus) or out.get("kind", state.get("kind")) != "answer":
            return out
        cited = out.get("citations", state.get("citations", []))
        body, sep, _ = str(out.get("answer") or "").rpartition("\n\n기준일 ")
        if not sep:
            return out
        info, more = dict(out.get("grounding") or {}), cited
        context = state.get("chunks", [])  # G가 뺀 청크도 다시 쓰기 뒤와 같이 A1, A1b가 볼 수 있다(지금 동작과 같게 둔다)
        if cite_expand:
            body, more = AF.expand_numbered(body, more, context, cap=MAX_CITATIONS)
            if len(more) > len(cited):
                info["cite_expand"] = [c["chunk_id"] for c in more[len(cited):]]
        if cite_phrase:  # A1b: A1 뒤에 문장 공유 규칙으로 더한다(A1이 더한 청크도 인용으로 본다)
            before = len(more)
            body, more = AF.expand_numbered(body, more, context, cap=MAX_CITATIONS, picker=AF.pick_phrase_extra)
            if len(more) > before:
                info["cite_phrase"] = [c["chunk_id"] for c in more[before:]]
        if drop_scoped:  # P: 질문에 없는 한정어가 붙은 페이지만 인용한 문장을 뺀다(A1, A1b가 더한 인용도 본다)
            got = AF.drop_scoped_cites(body, more, state["question"], MSG_PARTIAL_NOTE, context=state.get("chunks", []))
            if got:
                body, more, info["scoped_drop"] = got
        if consensus:  # CS: 한 문장에서 여러 페이지가 되풀이하는 문장 쪽 인용만 남긴다(A1, A1b가 더한 인용도 본다)
            got = AF.drop_odd_cites(body, more)
            if got:
                body, more, info["consensus_drop"] = got
        if more == cited:
            return out
        return {**out, "answer": finish_answer(body, more, state.get("as_of")), "citations": more, "grounding": info}

    def after_ground(state: AgentState) -> str:
        return "save" if state.get("kind") == "answer" else END

    def save(state: AgentState) -> dict:
        answer_id = uuid.uuid4().hex
        if answer_store is not None:
            fields = (
                answer_id,
                state.get("user_id") or "",
                state.get("thread_id") or "",
                state["question"],
                state["answer"],
                state.get("as_of"),
                [Chunk(**c) for c in state.get("citations", [])],
            )
            if save_one_conn and hasattr(answer_store, "save_with_grounding"):  # 사전 등록 62.16 `ANSWER_SAVE_ONE_CONN`: 같은 두 저장을 연결 하나로(저장 내용과 순서는 그대로)
                answer_store.save_with_grounding(*fields, G.public_grounding(state.get("grounding") or {}), state.get("skills_used") or [])
                return {"answer_id": answer_id}
            answer_store.save(*fields)
            if hasattr(answer_store, "save_grounding"):
                answer_store.save_grounding(answer_id, G.public_grounding(state.get("grounding") or {}), state.get("skills_used") or [])
        return {"answer_id": answer_id}

    # ---- 배선 ----
    g = StateGraph(AgentState)
    for name, fn in (
        ("load_memory", load_memory),
        ("classify", classify),
        ("out_of_domain", out_of_domain),
        ("rewrite", rewrite_node),
        ("search", search_node),
        ("judge", judge_node),
        ("give_up", give_up),
        ("write_answer", write_answer),
        ("verify", verify),
        ("ground", ground),
        ("save", save),
    ):
        g.add_node(name, fn)
    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "classify")
    # 결정표와 합동 검토를 연결하면 이 표의 목적지만 바꾼다
    if decision_repo is not None:   # 결정표 저장소가 있을 때만 결정표 경로를 따로 연다. 없으면 지금처럼 정책 질문으로 처리한다
        g.add_node("decision_params", decision_params)
        g.add_node("decision_run", run_decision)
        g.add_node("decision_answer", decision_answer)
        g.add_edge("decision_params", "decision_run")
        g.add_edge("decision_run", "decision_answer")
        g.add_edge("decision_answer", END)
    decision_target = "decision_params" if decision_repo is not None else "rewrite"
    g.add_conditional_edges("classify", lambda s: s.get("route", "rule"), {"rule": "rewrite", "decision": decision_target, "review": "review" if review_graph is not None else "rewrite", "out_of_domain": "out_of_domain"})
    g.add_edge("out_of_domain", END)
    if review_graph is not None:
        g.add_node("review", review_graph)  # 팀 합동 검토(F-03): 사람 승인 interrupt에서 멈추고 같은 thread_id로 재개한다
        g.add_edge("review", END)
    g.add_edge("rewrite", "search")
    g.add_conditional_edges("search", lambda s: "end" if s.get("search_error") else "judge", {"end": END, "judge": "judge"})
    g.add_conditional_edges("judge", after_judge, {"write_answer": "write_answer", "rewrite": "rewrite", "give_up": "give_up"})
    g.add_edge("give_up", END)
    g.add_edge("write_answer", "verify")
    g.add_conditional_edges("verify", after_verify, {"ground": "ground", END: END})
    g.add_conditional_edges("ground", after_ground, {"save": "save", END: END})
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer, store=store)
