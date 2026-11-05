"""그래프 조립 (G4). D4(11/5) 단일 에이전트 그래프 v1, `docs/specs/question-graph.md`.

흐름: 기억 불러오기 -> 질의 라우팅(도메인 밖이면 검색 없이 거절) -> (정책 질문) 질의 재작성 -> 검색 -> 문서 채점 -> 부족하면 재작성으로(재검색 최대 2회)
-> 답 작성(재검색 결과는 앞 결과에 합친다) -> 인용 검사(코드) -> 근거 판정(코드 규칙 + LLM) -> 저장.
결정표와 합동 검토 경로는 별도 Spec이다. 연결되기 전에는 분류 결과만 남기고 정책 질문으로 처리한다. 막다른 답을 내면 답이 있는 질문을 거절하게 된다.

D5(11/6)에 Supervisor와 서브에이전트로 나누고 같은 평가셋(v2)으로 다시 잰다.
시험하기 쉽게 검색기, 체크포인터, 채팅 모델을 인자로 받는다. 재검색 상한은 `MAX_RESEARCH` 한 곳에 있다.
검색 필터(`org`, `as_of`)는 검색 단계의 인자로만 넘기고 결과를 받은 뒤 거르지 않는다.
답 단계 근거 판정은 후처리 거절이므로 평가 실행기가 그 효과를 따로 보고한다(docs/GATES.md G5).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from backend.graph import grounding as G
from backend.graph.answer_store import AnswerStore
from backend.graph.citations import check_citations
from backend.graph.decompose import decompose_enabled, decompose_question
from backend.graph.parsing import parse_json_obj
from backend.graph.state import AgentState
from backend.memory.profile import get_profile
from backend.prompts import question as P
from backend.prompts.question import leaks_internal
from backend.rag.retrieve.embed import EmbedUnavailable
from backend.schemas import Chunk, SearchQuery
from backend.schemas.chunk import DEFAULT_K
from backend.services.llm import CostCapExceeded, get_chat_model, is_demo_mode
from backend.services.skills import load_skill, skills_enabled

log = logging.getLogger(__name__)

MAX_RESEARCH = 2  # 재검색 최대 횟수. 첫 검색까지 합쳐 검색은 최대 3번
MAX_CHUNKS = 10  # 재검색 결과를 합친 근거 목록의 최대 길이
SEARCH_K = DEFAULT_K  # 검색마다 요청하는 청크 수. 그래프와 MCP가 같은 상수(`backend/schemas/chunk.py`)를 쓴다(확정 조합 k=5)
MAX_CITATIONS = P.MAX_CITATIONS  # 답 하나가 인용할 수 있는 청크 수의 상한. 답 프롬프트와 같은 값이다
JSON_ATTEMPTS = 2  # LLM 응답 형식이 깨지면 1회 다시 요청한다 (Spec EC-06)
ROUTES = ("rule", "decision", "review", "out_of_domain")
LICENSE_NOTE = "출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MARK = re.compile(r"\[([0-9a-f]{16})\]")
# 질문에 시점이 드러나 있는지: 연도, 월, 분기, 회계연도, 상대 표현. 재작성이 낸 기준일은 이런 표현이 있을 때만 쓴다
_PERIOD_CUE = re.compile(r"(?:19|20)\d{2}|\d{1,2}\s*월|분기|\bQ[1-4]\b|\bFY\s*\d{2,4}|작년|올해|지난|이번|전년|내년|오늘|어제|\d+\s*(?:년|개월)\s*전", re.I)
_WHEN = re.compile(r"(?<!\d)(?:(?:19|20)\d{2}(?:[-./]\d{1,2}(?:[-./]\d{1,2})?)?|\d{1,2}\s*월)(?!\d)")  # 시점을 되묻는 말에 쓰는 연도, 날짜, 월

MSG_REFUSE = "핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다."
MSG_REFUSE_OUT_OF_DOMAIN = "핸드북과 관련 없는 질문이라 답하지 않습니다."
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


def _text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
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


def mentions_period(question: str) -> bool:
    """질문에 시점 표현이 있는지. 없는 질문에 재작성이 기준일을 채워 내면(오늘 날짜 등) 그 값은 쓰지 않는다."""
    return bool(_PERIOD_CUE.search(question or ""))


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
    """되묻기 문장에 숫자가 있는지. 시점을 묻는 연도, 날짜, 월 표기는 세지 않는다(수치를 말하는 되묻기를 거르는 규칙)."""
    return bool(re.search(r"\d", _WHEN.sub("", text or "")))


def _forget_search_trace() -> None:
    """이전 검색의 기록이 이번 검색의 것으로 읽히지 않게 비운다(`last_search_trace`는 컨텍스트 변수다)."""
    from backend.rag.retrieve.search import _last

    _last.set(None)


def _search_fallback_reason() -> str | None:
    from backend.rag.retrieve.search import last_search_trace

    tr = last_search_trace()
    return tr.fallback_reason if tr else None


def _default_retriever(q: SearchQuery) -> list[Chunk]:
    from backend.rag.retrieve import search

    return search(q)


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
):
    """컴파일된 질문 그래프를 만든다.

    - retriever: `SearchQuery -> list[Chunk]`. None이면 `backend.rag.retrieve.search`.
    - llm: `.invoke(messages)`를 가진 채팅 모델. None이면 `get_chat_model()`(키가 없으면 데모 모드).
    - store: 장기 기억 Store. None이면 InMemoryStore.
    - use_skills: None이면 환경변수 USE_SKILLS를 따른다. True/False는 켬과 끔 비교용이다.
    - grounding_llm: 근거 판정에 LLM을 쓸지. None이면 데모 모드가 아닐 때만 쓴다. 코드 규칙은 이 값과 무관하게 돈다.
    - decompose: 첫 검색 전에 한국어 원 질문을 LLM으로 나눌지. None이면 환경 변수 `SEARCH_DECOMPOSE=1`을 따른다(기본 끔).
      켜면 첫 검색은 원 질문과 하위 질문(`sub_queries`)을 넘기고, 재검색은 재작성 검색어만 분해 없이 넘긴다. 측정 전용 검색기(저장된 분해를 읽는다)는 끈다.
    """
    retrieve = retriever or _default_retriever
    llm = llm if llm is not None else get_chat_model()
    store = store if store is not None else InMemoryStore()

    def ask(system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        return _text(llm.invoke([SystemMessage(content=system), HumanMessage(content=user)]))

    def ask_json(system: str, user: str) -> tuple[dict | None, str]:
        raw = ""
        for _ in range(JSON_ATTEMPTS):
            raw = ask(system, user)
            obj = parse_json_obj(raw)
            if obj is not None:
                return obj, raw
        return None, raw

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
        chunks = [c.model_dump() for c in retrieve(q)]
        cache[key] = chunks
        stats["calls"] += 1
        return chunks, {"search_cache": cache, "search_stats": stats}

    # ---- 노드 ----
    def load_memory(state: AgentState) -> dict:
        user_id = state.get("user_id") or ""
        return {
            "profile": get_profile(store, user_id) if user_id else {},
            "as_of": state.get("as_of") or date.today().isoformat(),
            "as_of_given": bool(state.get("as_of")),
            "kind": "",
            "answer": "",
            "retries": 0,
            "judge_reason": "",
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

    def classify(state: AgentState) -> dict:
        obj, _ = ask_json(P.CLASSIFY_SYSTEM, P.classify_user(state["question"], state.get("profile", {})))
        route = (obj or {}).get("route")
        return {"route": route if route in ROUTES else "rule"}  # 모르면 일반 정책 질문

    def out_of_domain(state: AgentState) -> dict:
        """분명히 핸드북과 무관한 질문은 재작성과 검색 없이 거절한다."""
        return {"kind": "refuse", "answer": MSG_REFUSE_OUT_OF_DOMAIN, "citations": []}

    def rewrite(state: AgentState) -> dict:
        q = state["question"]
        gloss = skill("glossary")
        system = P.with_skills(P.REWRITE_SYSTEM, [("용어 Skill", gloss)])
        obj, _ = ask_json(system, P.rewrite_user(q, state.get("profile", {}), state.get("judge_reason") or None))
        obj = obj or {}
        query = obj["query"] if isinstance(obj.get("query"), str) and obj["query"].strip() else q
        org = state.get("org") or (obj["org"] if isinstance(obj.get("org"), str) and obj["org"].strip() else None)
        upd: dict = {
            "search_query": query,
            "search_org": org or scope_org(state),
            "skills_used": note_skills(state, *(["glossary"] if gloss else [])),
        }
        if _valid_date(obj.get("as_of")) and not state.get("as_of_given") and mentions_period(q):
            upd["as_of"] = obj["as_of"]
        return upd

    def search(state: AgentState) -> dict:
        # 질문 분해는 첫 검색에서만, 사용자가 쓴 한국어 원 질문으로 한다(측정과 같다). 하위 질문은 검색에 넘기고 검색은 질문을 LLM으로 나누지 않는다.
        # 재검색은 재작성 검색어 하나로 분해 없이 찾는다.
        first = state.get("retries", 0) == 0
        split = first and (decompose_enabled() if decompose is None else decompose)
        extra: dict = {}
        subs: list[str] = []
        if split:
            subs, source = decompose_question(ask, state["question"])
            extra = {"sub_queries": subs, "decompose_source": source}
        q = SearchQuery(query=state["question"] if split else state["search_query"], org=state.get("search_org"), as_of=state.get("as_of"),
                        k=SEARCH_K, sub_queries=subs or None)
        _forget_search_trace()
        try:
            found, memo = memo_search(state, q)
        except EmbedUnavailable as e:  # 임베딩 API가 잠깐 안 되는 경우: 죽지 않고 정해진 거절로 끝낸다(다시 시도하면 될 수 있다)
            log.warning("검색 임베딩 API 일시 오류: %s", e)
            return {**extra, "kind": "refuse", "answer": MSG_REFUSE_SEARCH_DOWN, "citations": [], "search_error": "unavailable"}
        if not found and _search_fallback_reason() == "no_key":  # 키 없는 데모: 같은 검색을 되풀이하지 않고 끝낸다
            return {**extra, **memo, "kind": "refuse", "answer": MSG_REFUSE_NO_KEY, "citations": [], "search_error": "no_key"}
        # 재검색은 앞 결과를 버리지 않고 합친다. 판단, 인용 검사, 근거 판정은 모두 이 합친 목록과 대조한다
        return {"chunks": merge_chunks(state.get("chunks", []), found), **memo, **extra}

    def judge(state: AgentState) -> dict:
        chunks = state.get("chunks", [])
        if not chunks:  # 자료가 없으면 LLM에 묻지 않고 부족으로 본다
            return {"judge_reason": "검색 결과 없음", "retries": state.get("retries", 0) + 1}
        obj, _ = ask_json(P.JUDGE_SYSTEM, P.judge_user(state["question"], chunks))
        obj = obj or {}
        if obj.get("sufficient") is True:  # 파싱 실패나 모호한 값은 부족으로 본다
            return {"judge_reason": ""}
        clarify = obj["clarify"] if isinstance(obj.get("clarify"), str) and obj["clarify"].strip() else None
        return {
            "judge_reason": str(obj.get("reason") or "근거 부족"),
            "clarify_question": clarify,
            "retries": state.get("retries", 0) + 1,
        }

    def after_judge(state: AgentState) -> str:
        if not state.get("judge_reason"):
            return "write_answer"
        return "rewrite" if state.get("retries", 0) <= MAX_RESEARCH else "give_up"

    def give_up(state: AgentState) -> dict:
        ask_back = state.get("clarify_question")
        if ask_back and not clarify_has_number(ask_back):  # 숫자를 담은 되묻기는 인용 없이 수치를 말하는 것이라 거절로 바꾼다
            return {"kind": "clarify", "answer": ask_back, "citations": []}
        return {"kind": "refuse", "answer": MSG_REFUSE, "citations": []}

    def write_answer(state: AgentState) -> dict:
        rules = skill("citation-rules")
        system = P.with_skills(P.ANSWER_SYSTEM, [("인용 규칙 Skill", rules)])
        used = note_skills(state, *(["citation-rules"] if rules else []))
        obj, raw = ask_json(system, P.answer_user(state["question"], state.get("chunks", []), state.get("as_of")))
        if obj is None:  # JSON이 아니면 인용을 알 수 없으므로 인용 검사가 거절한다
            return {"answer": raw, "raw_citations": [], "drafted": True, "skills_used": used}
        cites = obj.get("citations")
        return {
            "answer": str(obj.get("answer") or ""),
            "raw_citations": cites if isinstance(cites, list) else [],
            "period_covered": obj.get("period_covered") if isinstance(obj.get("period_covered"), bool) else None,
            "drafted": True,
            "skills_used": used,
        }

    def verify(state: AgentState) -> dict:
        if leaks_internal(state.get("answer", "")):
            return {"kind": "refuse", "answer": MSG_REFUSE_LEAK, "citations": [], "dropped_citations": []}
        missing = G.period_missing(state["question"], state.get("answer", ""), state.get("period_covered"))
        if missing:  # 요청한 기간의 자료가 없다고 스스로 밝힌 답은 가까운 기간 값을 인용했어도 답으로 내지 않는다
            info = {"rules": "skipped(period_missing)", "llm": "off", "reason": G.OUT_OF_PERIOD, "detail": missing}
            return {"kind": "refuse", "answer": MSG_REFUSE_BY_REASON[G.OUT_OF_PERIOD], "citations": [], "dropped_citations": [],
                    "refuse_reason": G.OUT_OF_PERIOD, "grounding": info}
        valid, dropped, cleaned = check_citations(state.get("raw_citations", []), state.get("chunks", []), state.get("answer", ""))
        if not valid or not cleaned:
            return {"kind": "refuse", "answer": MSG_REFUSE_CITATION, "citations": [], "dropped_citations": dropped}
        kept, trimmed, cleaned = select_citations(valid, cleaned)
        return {"kind": "answer", "answer": cleaned, "citations": kept, "dropped_citations": dropped, "trimmed_citations": [c["chunk_id"] for c in trimmed]}

    def after_verify(state: AgentState) -> str:
        return "ground" if state.get("kind") == "answer" else END

    def llm_verdict(question: str, answer: str, cited: list[dict], as_of: str | None, body: str) -> dict:
        """근거 판정 LLM 한 번. state는 grounded, ungrounded, inconclusive 중 하나다(명확히 거절한 경우만 ungrounded)."""
        out: dict = {"state": "inconclusive", "code": "", "detail": "", "claims": []}
        try:
            system = P.with_skills(P.GROUNDING_SYSTEM, [("근거 판정 Skill", body)])
            obj, _ = ask_json(system, P.grounding_user(question, answer, cited, as_of))
            obj = obj or {}
            if obj.get("grounded") is True:
                out["state"] = "grounded"
            elif obj.get("grounded") is False:
                code, claims = obj.get("reason_code"), obj.get("unsupported_sentences")
                out.update(
                    state="ungrounded",
                    code=code if code in G.REASONS else G.UNSUPPORTED,
                    detail=str(obj.get("reason") or ""),
                    claims=[c for c in claims if isinstance(c, str) and c.strip()] if isinstance(claims, list) else [],
                )
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
        if not valid or not cleaned or dropped or leaks_internal(cleaned):
            rec["result"] = "citation_check_failed"
            return None
        again = G.check_rules(question, valid, chunks)
        if not again.ok:
            rec["result"] = f"rules:{again.reason}"
            return None
        second = llm_verdict(question, cleaned, valid, as_of, body)
        info["rejudge"] = second["state"]
        if second["state"] != "grounded":  # 더 빼지 않는다. 결론이 없어도 거절 쪽으로 둔다
            rec["result"] = f"rejudge_{second['state']}"
            return None
        info.update(revised=True, draft_answer=state["answer"], removed=[{"sentence": x, "reason": verdict["detail"]} for x in pruned.removed])
        return {"kind": "answer", "answer": finish_answer(cleaned, valid, as_of), "citations": valid, "grounding": info, "skills_used": used}

    def ground(state: AgentState) -> dict:
        """인용 검사를 통과한 답이 검색된 근거로 받쳐지는지 본다. 코드 규칙이 먼저이고, 한쪽이라도 거절하면 거절한다.
        LLM이 일부 문장만 받쳐지지 않는다고 하면(`unsupported`) 그 문장만 빼고 답을 유지한다(`revise_answer`). 그 밖의 사유는 전체를 거절한다."""
        body = skill("grounding-check")
        as_of, cited = state.get("as_of"), state.get("citations", [])
        final = {"answer": finish_answer(state.get("answer", ""), cited, as_of)}
        if not body:  # USE_SKILLS를 끄면 건너뛴다
            return {**final, "grounding": {"llm": "off", "rules": "skipped(USE_SKILLS off)"}}
        used = note_skills(state, "grounding-check")
        v = G.check_rules(state["question"], cited, state.get("chunks", []))
        info: dict = {"rules": v.checks, "llm": "off"}
        reason, detail = v.reason, v.detail
        if v.ok and (grounding_llm if grounding_llm is not None else not is_demo_mode()):
            verdict = llm_verdict(state["question"], state.get("answer", ""), cited, as_of, body)
            info["llm"] = "ungrounded" if verdict["state"] == "ungrounded" else verdict["state"]
            if verdict.get("error"):
                info["llm_error"] = verdict["error"]
            if verdict["state"] == "ungrounded":
                reason, detail = verdict["code"], verdict["detail"]
                if reason == G.UNSUPPORTED and verdict["claims"]:
                    revised = revise_answer(state, cited, verdict, info, body, used)
                    if revised is not None:
                        return revised
        if reason:
            info.update(reason=reason, detail=detail)  # 판정 사유는 기록에만 둔다. 청크 id 같은 내부 값을 사용자에게 보이지 않는다
            return {
                "kind": "refuse",
                "answer": MSG_REFUSE_BY_REASON[reason],
                "citations": [],
                "refuse_reason": reason,
                "grounding": info,
                "skills_used": used,
            }
        return {**final, "grounding": info, "skills_used": used}

    def after_ground(state: AgentState) -> str:
        return "save" if state.get("kind") == "answer" else END

    def save(state: AgentState) -> dict:
        answer_id = uuid.uuid4().hex
        if answer_store is not None:
            answer_store.save(
                answer_id,
                state.get("user_id") or "",
                state.get("thread_id") or "",
                state["question"],
                state["answer"],
                state.get("as_of"),
                [Chunk(**c) for c in state.get("citations", [])],
            )
        return {"answer_id": answer_id}

    # ---- 배선 ----
    g = StateGraph(AgentState)
    for name, fn in (
        ("load_memory", load_memory),
        ("classify", classify),
        ("out_of_domain", out_of_domain),
        ("rewrite", rewrite),
        ("search", search),
        ("judge", judge),
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
    g.add_conditional_edges("classify", lambda s: s.get("route", "rule"), {"rule": "rewrite", "decision": "rewrite", "review": "rewrite", "out_of_domain": "out_of_domain"})
    g.add_edge("out_of_domain", END)
    g.add_edge("rewrite", "search")
    g.add_conditional_edges("search", lambda s: "end" if s.get("search_error") else "judge", {"end": END, "judge": "judge"})
    g.add_conditional_edges("judge", after_judge, {"write_answer": "write_answer", "rewrite": "rewrite", "give_up": "give_up"})
    g.add_edge("give_up", END)
    g.add_edge("write_answer", "verify")
    g.add_conditional_edges("verify", after_verify, {"ground": "ground", END: END})
    g.add_conditional_edges("ground", after_ground, {"save": "save", END: END})
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer, store=store)
