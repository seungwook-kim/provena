"""멀티 에이전트 질문 그래프 (D-09, G4). Supervisor가 검색, 작성, 검증 하위 에이전트를 불러 단일 그래프(`build.py`)와 같은 일을 나눠 한다.

같은 코드를 쓴다. 이 파일에는 프롬프트, 검색, 인용 검사, 근거 판정, 저장 코드가 없다. `build_graph`가 만든 노드와 분기 함수를 그대로 꺼내
(`SingleParts`, 컴파일된 그래프의 `builder`) 하위 에이전트 안에 다시 배선한다. 그래서 단일의 노드를 고치면 멀티도 같이 바뀐다.

구조(허브와 스포크):

    START -> supervisor <-> retriever | writer | verifier | decision | review        (supervisor가 매번 다음 에이전트나 끝을 고른다)

| 주체 | 하는 일 (단일 그래프의 노드) | 보는 상태 칸 |
|---|---|---|
| Supervisor | 기억 불러오기(`load_memory`), 질의 분석(`classify`, LLM 1회), 다음 에이전트 고르기, 닫는 단계(`out_of_domain`, `give_up`) | 전체 |
| retriever(검색) | 재작성(`rewrite`) -> 검색(`search`) -> 근거 충분 판정(`judge`). 한 번 도는 것이 한 번의 (재)검색이다 | `RETRIEVER.reads` |
| writer(작성) | 답 작성(`write_answer`) | `WRITER.reads` |
| verifier(검증) | 인용 검사(`verify`) -> 근거 판정(`ground`) -> 저장(`save`) | `VERIFIER.reads` |
| decision(결정표, `decision_repo`를 줄 때만) | 값 뽑기(`decision_params`) -> 실행(`decision_run`) -> 답(`decision_answer`) | `DECISION.reads` |
| review(합동 검토, `review_graph`를 줄 때만) | 합동 검토 하위 그래프 전체. 사람 승인 interrupt에서 멈추고 같은 thread_id로 재개한다 | `REVIEW.reads` |

- 재검색 정책은 Supervisor가 가진다. retriever가 돌아오면 단일의 `after_judge`(재검색 2회 상한 `MAX_RESEARCH`)를 그대로 불러
  retriever를 다시 부르거나(재검색), writer로 가거나, `give_up`으로 닫는다. 단일과 같은 순서로 같은 노드가 같은 횟수 돈다.
- 컨텍스트 격리: 하위 에이전트는 자기 상태 스키마(`reads` + `writes`)에 있는 칸만 받는다. 다른 칸을 읽거나 쓰는 노드가 생기면 조용히 비지 않고 오류가 난다.
  Supervisor가 에이전트에서 받는 것은 `writes` 칸뿐이다.
- 질문 종류별 목적지는 단일 그래프의 분기 표를 그대로 읽는다. 결정표나 합동 검토를 연결하지 않으면 단일과 같이 정책 질문 경로로 간다.
- 허용 경로는 코드가 상태로 계산한다(`route_options`). 기본 라우터(`code`)는 질의 분석에 쓰는 LLM 호출이 단일 `classify`와 같은 1회이고, 라우팅 때문에 늘어나는 LLM 호출은 없다.
  `llm` 라우터(`build_multi_graph(router="llm")`, 환경 변수 `SUPERVISOR_ROUTER`)는 허용 경로가 2개 이상일 때만 그래프와 같은 모델을 1회 부른다. 입력은 코드가 계산한 값과 허용 경로뿐이고
  (`route_facts`), 문서 본문, 답, 질문 원문, 판정 사유 문장은 넣지 않는다. 응답이 허용 경로 밖이거나 읽을 수 없으면 코드 라우팅 결과로 돌아간다.
- 결과 상태 칸(`kind`, `answer`, `citations`, `retries`, `search_stats` ...)은 단일과 같고 평가 실행기(`evals/agent/run_eval.py`)가 그대로 읽는다.
  멀티에만 있는 칸: `agent_trace`(부른 에이전트 순서), `supervisor_log`(결정 기록. 항목마다 `router`, 대체했으면 `fallback`), `handoffs`(에이전트마다 받은 칸과 돌려준 칸).
"""
from __future__ import annotations

import logging
import os
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import ensure_config
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from backend.graph.answer_store import AnswerStore
from backend.graph.build import MAX_RESEARCH, _text, build_graph, resolve_max_research
from backend.graph.parsing import parse_json_obj
from backend.graph.state import AgentState
from backend.prompts import question as P
from backend.schemas import Chunk, SearchQuery
from backend.services.llm import CostCapExceeded, get_chat_model

log = logging.getLogger(__name__)

ROUTERS = ("code", "llm")
ROUTE_NODE = P.TASK_SUPERVISOR_ROUTE  # LLM 기록(`llm_trace`)에 남는 라우터의 노드 이름


class MultiState(AgentState, total=False):
    """단일 상태(`AgentState`)에 Supervisor의 기록 칸을 더한다."""

    next_agent: str  # supervisor의 마지막 결정: retriever | writer | verifier | decision | review | end
    agent_trace: list[str]  # 부른 하위 에이전트 순서. 재검색이면 retriever가 되풀이된다
    supervisor_log: list[dict]  # supervisor가 결정할 때마다 한 줄: 어디서 돌아왔고 어디로 보냈는지
    handoffs: list[dict]  # 에이전트마다 받은 칸과 돌려준 칸의 이름


@dataclass(frozen=True)
class AgentSpec:
    name: str
    nodes: tuple[str, ...]  # 단일 그래프의 노드 이름
    reads: frozenset[str]  # 에이전트가 Supervisor에게서 받는 상태 칸
    writes: frozenset[str]  # 에이전트가 Supervisor에게 돌려주는 상태 칸. 노드가 쓰는 칸은 모두 여기 있어야 한다

    @property
    def fields(self) -> frozenset[str]:
        return self.reads | self.writes


RETRIEVER = AgentSpec(
    "retriever",
    ("rewrite", "search", "judge"),
    reads=frozenset({"question", "profile", "org", "as_of", "as_of_given", "retries", "judge_reason", "search_query", "search_org", "chunks",
                     "search_cache", "search_stats", "skills_used", "judged_chunks", "judge_missing", "judge_query", "sub_queries", "next_section", "section_reads", "started_at",
                     "query_targets", "sub_research", "sub_research_phase", "judge_partial", "judge_checks_log"}),  # judge_partial: 가(`GRAPH_RESEARCH_SAME_PAGE`)가 재검색 방식을 고른다. query_targets: `GRAPH_QUERY_BRANCHES=1`일 때만 생기는 칸. 꺼져 있으면 상태에 없어 넘어가지 않는다
    writes=frozenset({"search_query", "search_org", "skills_used", "as_of", "sub_queries", "decompose_source", "kind", "answer", "citations",
                      "search_error", "chunks", "search_cache", "search_stats", "judge_reason", "judge_partial", "retries", "clarify_question",
                      "early_answer", "judged_chunks", "search_stalled", "judge_missing", "judge_query", "judge_scope", "next_section", "section_reads",
                      "query_targets", "sub_research", "sub_research_phase", "judge_none", "judge_checks_log", "judge_quote_ids"}),
)
WRITER = AgentSpec(
    "writer",
    ("write_answer",),
    reads=frozenset({"question", "chunks", "as_of", "skills_used", "judge_partial", "judge_scope", "early_answer", "route", "retries", "started_at", "query_targets", "judge_quote_ids"}),
    writes=frozenset({"answer", "raw_citations", "period_covered", "drafted", "skills_used", "answer_facts", "best2_log"}),
)
VERIFIER = AgentSpec(
    "verifier",
    ("verify", "ground", "save"),
    reads=frozenset({"question", "answer", "period_covered", "raw_citations", "chunks", "as_of", "skills_used", "user_id", "thread_id", "judge_partial", "dropped_citations", "route"}),
    writes=frozenset({"kind", "answer", "citations", "dropped_citations", "trimmed_citations", "refuse_reason", "grounding", "skills_used", "answer_id"}),
)
AGENTS = {a.name: a for a in (RETRIEVER, WRITER, VERIFIER)}
DECISION = AgentSpec(
    "decision",
    ("decision_params", "decision_run", "decision_answer"),
    reads=frozenset({"question", "decision_query"}),   # 분류 단계가 미리 뽑은 값이 있으면 값 뽑기가 다시 부르지 않는다
    writes=frozenset({"decision_query", "decision_result", "decision_error", "kind", "answer", "citations"}),
)
REVIEW = AgentSpec(
    "review",
    ("review",),
    reads=frozenset({"question", "user_id", "thread_id", "as_of"}),
    writes=frozenset({"kind", "answer", "clarify_question", "review_status", "issue_table"}),
)
CONNECTED_AGENTS = {a.name: a for a in (DECISION, REVIEW)}  # 저장소나 하위 그래프를 줄 때만 그래프에 들어간다. 안 주면 노드 자체가 없다

# 경로 이름 -> (next_agent, Supervisor가 직접 닫는 노드). 라우터가 고르는 값은 이 표의 열쇠뿐이다
PATHS = {
    **{name: (name, "") for name in (*AGENTS, *CONNECTED_AGENTS)},
    "end": ("end", ""),
    "give_up": ("end", "give_up"),
    "out_of_domain": ("end", "out_of_domain"),
}
INTAKE_PATHS = {"rewrite": "retriever", "decision_params": "decision", "review": "review", "out_of_domain": "out_of_domain"}  # 단일의 classify 분기 목적지 -> 경로


class SingleParts:
    """`build_graph`가 만든 노드 함수와 분기 함수를 꺼내 쓰는 창구. 컴파일된 그래프의 `builder`를 읽는다(langgraph 1.2.x).

    `build.py`의 노드가 클로저라 따로 import할 수 없어서 이 길을 쓴다. 버전이 바뀌어 `builder`를 읽을 수 없으면 조용히 다르게 돌지 않고 여기서 멈춘다.
    """

    def __init__(self, compiled: Any):
        builder = getattr(compiled, "builder", None)
        nodes, branches = getattr(builder, "nodes", None), getattr(builder, "branches", None)
        if not isinstance(nodes, dict) or not isinstance(branches, dict):
            raise RuntimeError("단일 그래프에서 노드와 분기를 꺼낼 수 없다: langgraph 버전이 바뀌었는지 확인하라")
        self._nodes, self._branches = nodes, branches

    def node(self, name: str):
        """노드 실행체(Runnable). `.invoke(state)`가 단일 그래프의 노드와 같은 갱신 dict를 돌려준다."""
        if name not in self._nodes:
            raise KeyError(f"단일 그래프에 노드 {name!r}가 없다")
        return self._nodes[name].runnable

    def branch(self, source: str):
        """`source` 노드에서 나가는 조건 분기(BranchSpec). 단일 그래프는 노드마다 분기가 하나다."""
        found = list(self._branches.get(source, {}).values())
        if len(found) != 1:
            raise KeyError(f"단일 그래프의 노드 {source!r}에 조건 분기가 하나가 아니다({len(found)})")
        return found[0]

    def has(self, name: str) -> bool:
        return name in self._nodes

    def route(self, source: str, state: dict) -> str:
        return self.branch(source).path.invoke(state)

    def add_branch(self, graph: StateGraph, source: str) -> None:
        """단일 그래프와 같은 분기 함수와 목적지 표를 `graph`에도 단다."""
        br = self.branch(source)
        graph.add_conditional_edges(source, br.path, br.ends)


def _schema(spec: AgentSpec):
    hints = typing.get_type_hints(AgentState)
    missing = sorted(spec.fields - set(hints))
    if missing:
        raise KeyError(f"{spec.name} 에이전트가 AgentState에 없는 칸을 쓴다: {missing}")
    return TypedDict(f"{spec.name.capitalize()}State", {k: hints[k] for k in sorted(spec.fields)}, total=False)


def build_agents(parts: SingleParts) -> dict[str, Any]:
    """하위 에이전트를 각자의 상태 스키마로 컴파일한다. 안의 노드와 분기는 단일 그래프의 것이다. 결정표와 합동 검토는 단일 그래프에 연결돼 있을 때만 만든다."""
    out: dict[str, Any] = {}

    g = StateGraph(_schema(RETRIEVER))
    for n in RETRIEVER.nodes:
        g.add_node(n, parts.node(n))
    g.add_edge(START, "rewrite")
    g.add_edge("rewrite", "search")
    parts.add_branch(g, "search")  # 검색을 쓸 수 없으면(search_error) 판정 없이 끝난다
    g.add_edge("judge", END)
    out["retriever"] = g.compile()

    g = StateGraph(_schema(WRITER))
    g.add_node("write_answer", parts.node("write_answer"))
    g.add_edge(START, "write_answer")
    g.add_edge("write_answer", END)
    out["writer"] = g.compile()

    g = StateGraph(_schema(VERIFIER))
    for n in VERIFIER.nodes:
        g.add_node(n, parts.node(n))
    g.add_edge(START, "verify")
    parts.add_branch(g, "verify")
    parts.add_branch(g, "ground")
    g.add_edge("save", END)
    out["verifier"] = g.compile()

    if parts.has("decision_params"):
        g = StateGraph(_schema(DECISION))
        for n in DECISION.nodes:
            g.add_node(n, parts.node(n))
        g.add_edge(START, "decision_params")
        g.add_edge("decision_params", "decision_run")
        g.add_edge("decision_run", "decision_answer")
        g.add_edge("decision_answer", END)
        out["decision"] = g.compile()
    if parts.has("review"):
        _schema(REVIEW)  # 칸 이름 확인. 하위 그래프는 자기 스키마(`ReviewState`)로 돈다
        out["review"] = parts.node("review")  # 체크포인터 없이 만든 하위 그래프다. 부르는 쪽의 체크포인터로 멈추고 재개한다
    return out


def resolve_router(router: str | None) -> str:
    """인자, 환경 변수 `SUPERVISOR_ROUTER`, 기본 `code` 순이다. 환경 변수가 비어 있으면 기본값이다. 그 밖의 값은 오류다."""
    value = router if router is not None else (os.environ.get("SUPERVISOR_ROUTER") or "code")
    if value not in ROUTERS:
        raise ValueError(f"SUPERVISOR_ROUTER는 {' 또는 '.join(ROUTERS)}이다: {value!r}")
    return value


def route_options(parts: SingleParts, view: dict, *, max_research: int = MAX_RESEARCH) -> tuple[tuple[str, ...], str]:
    """상태만 보고 (허용 경로, 코드 라우팅이 고르는 경로)를 낸다. 코드 경로는 단일의 분기 함수에서 나오고 언제나 허용 경로 안에 있다.

    허용 경로가 2개 이상인 곳은 retriever가 근거 부족으로 돌아온 때뿐이다. 근거 충분이면 작성으로만 가고, 근거 부족이면 일부 근거 경로일 때만 작성으로 갈 수 있다.
    """
    trace = view.get("agent_trace") or []
    last = trace[-1] if trace else None
    if last is None:
        path = INTAKE_PATHS[parts.branch("classify").ends[parts.route("classify", view)]]
        return (path,), path
    if last == "writer":
        return ("verifier",), "verifier"
    if last != "retriever" or view.get("search_error"):  # verifier, decision, review 뒤와 검색 불가(단일은 검색 단계에서 바로 끝난다)는 끝뿐이다
        return ("end",), "end"
    code = {"write_answer": "writer", "rewrite": "retriever", "give_up": "give_up"}[parts.route("judge", view)]
    if not view.get("judge_reason"):
        return ("writer",), "writer"
    allowed = []
    if trace.count("retriever") <= max_research and view.get("retries", 0) <= max_research:
        allowed.append("retriever")
    if parts.route("judge", {**view, "retries": max_research + 1}) == "write_answer":  # 재검색이 끝났을 때 단일이 작성으로 가는 경우(나뉜 질문의 일부 근거)
        allowed.append("writer")
    allowed.append("give_up")
    if code == "retriever" and "retriever" not in allowed and view.get("sub_research_phase") == "due":  # 빠진 하위 질문 한 번 더 찾기(`GRAPH_SUB_RESEARCH`, `GRAPH_PAGE_RESEARCH`, 기본 꺼짐)는 상한 밖의 한 번이다
        allowed.insert(0, "retriever")
    return tuple(allowed), code


def route_facts(view: dict, *, max_research: int = MAX_RESEARCH) -> dict:
    """라우터 LLM에 넘기는 값. 코드가 계산한 값만 담는다. `judge_reason`과 `clarify_question`은 문서를 읽은 LLM이 쓴 문장이라 넣지 않는다."""
    trace = view.get("agent_trace") or []
    verdict = "sufficient" if not view.get("judge_reason") else "partial" if view.get("judge_partial") else "insufficient"
    return {
        "route": view.get("route"),
        "after": trace[-1] if trace else "intake",
        "retries": view.get("retries", 0),
        "max_research": max_research,
        "searches": trace.count("retriever"),
        "judge": verdict,
        "split_question": len(view.get("sub_queries") or []) >= 2,
        "chunks": len(view.get("chunks") or []),
        "has_clarify": bool(view.get("clarify_question")),
    }


def ask_router(llm: Any, view: dict, allowed: tuple[str, ...], *, max_research: int = MAX_RESEARCH) -> tuple[str | None, str]:
    """라우터 LLM을 1회 부른다. (고른 경로, 대체 사유). 고르지 못하면 경로가 None이고 응답 문장은 어디에도 옮기지 않는다. 비용 상한만 그대로 올린다."""
    messages = [SystemMessage(content=P.SUPERVISOR_ROUTE_SYSTEM), HumanMessage(content=P.supervisor_route_user(route_facts(view, max_research=max_research), allowed))]
    # LLM 기록은 `langgraph_node`를 노드 이름으로 읽는다. Supervisor 노드 안의 호출이지만 라우팅 호출을 따로 볼 수 있게 이름만 바꾼다
    config = {"metadata": {**ensure_config().get("metadata", {}), "langgraph_node": ROUTE_NODE}}
    try:
        raw = _text(llm.invoke(messages, config=config))
    except CostCapExceeded:
        raise
    except Exception as e:  # noqa: BLE001  라우터 실패가 답을 막지 않는다. 코드 라우팅으로 돌아간다
        log.warning("Supervisor 라우터 호출 실패: %s", type(e).__name__)
        return None, "llm_error"
    obj = parse_json_obj(raw)
    if obj is None:
        return None, "unreadable"
    picked = obj.get("next")
    return (picked, "") if isinstance(picked, str) and picked in allowed else (None, "not_allowed")


def _agent_node(spec: AgentSpec, agent: Any) -> Callable[[dict], dict]:
    def run(state: dict) -> dict:
        view = {k: state[k] for k in spec.reads if k in state}
        out = agent.invoke(view)
        back = {k: out[k] for k in spec.writes if k in out}
        handoff = {"agent": spec.name, "received": sorted(view), "returned": sorted(back)}
        return {**back, "agent_trace": [*state.get("agent_trace", []), spec.name], "handoffs": [*state.get("handoffs", []), handoff]}

    return run


def build_multi_graph(
    retriever: Callable[[SearchQuery], list[Chunk]] | None = None,
    checkpointer=None,
    *,
    llm=None,
    answer_store: AnswerStore | None = None,
    store=None,
    use_skills: bool | None = None,
    grounding_llm: bool | None = None,
    decompose: bool | None = None,
    section_reader=None,
    decision_repo=None,
    review_graph=None,
    router: str | None = None,
    parallel_intake: bool | None = None,
    brief_output: bool | None = None,
    max_research: int | None = None,
    judge_answer: str | None = None,
    skip_first_rewrite: bool | None = None,
    stop_stalled_search: bool | None = None,
    ground_skip_backed: bool | None = None,
    json_only: bool | None = None,
    page_search=None,
    intro_search=None,
):
    """컴파일된 멀티 에이전트 질문 그래프. 라우팅 방식(`router`)을 뺀 인자와 뜻은 `build_graph`와 같다(그대로 넘긴다).

    - decision_repo, review_graph: 주면 결정표와 합동 검토를 에이전트로 등록한다. 안 주면 그 노드가 없고 단일 `build_graph`처럼 정책 질문 경로로 간다.
      합동 검토의 체크포인트는 이 그래프의 체크포인터에 있다. 재개는 이 그래프에 `Command(resume=...)`로 한다.
    - router: `code` 또는 `llm`. None이면 환경 변수 `SUPERVISOR_ROUTER`, 비어 있으면 `code`. 그 밖의 값은 ValueError. `llm` 라우터는 이 그래프가 받은 모델을 같이 쓴다.
    - parallel_intake, brief_output, max_research, judge_answer, skip_first_rewrite, stop_stalled_search, ground_skip_backed, json_only: `build_graph`의 속도 스위치. 노드를 단일에서 꺼내 쓰므로 단일과 똑같이 걸린다. 허용 경로 계산도 같은 재검색 상한을 따른다.
    """
    router = resolve_router(router)
    research_limit = resolve_max_research(max_research)
    if router == "llm" and llm is None:
        llm = get_chat_model()
    store = store if store is not None else InMemoryStore()
    single = build_graph(retriever, None, llm=llm, answer_store=answer_store, store=store, use_skills=use_skills,
                         grounding_llm=grounding_llm, decompose=decompose, section_reader=section_reader, decision_repo=decision_repo, review_graph=review_graph,
                         parallel_intake=parallel_intake, brief_output=brief_output, max_research=research_limit, judge_answer=judge_answer,
                         skip_first_rewrite=skip_first_rewrite, stop_stalled_search=stop_stalled_search, ground_skip_backed=ground_skip_backed, json_only=json_only, page_search=page_search, intro_search=intro_search)
    parts = SingleParts(single)
    agents = build_agents(parts)
    specs = {name: {**AGENTS, **CONNECTED_AGENTS}[name] for name in agents}

    def supervisor(state: dict) -> dict:
        upd: dict = {}
        view = dict(state)
        log = list(state.get("supervisor_log") or [])
        # 체크포인터가 있으면 앞 실행의 기록이 남아 있다. 앞 실행이 끝났거나(`end`) 에이전트 도중에 멈춘 채로(결정 수와 부른 수가 다르다) 여기로 들어오면 새 질문이다.
        # 재개는 멈춘 에이전트에서 이어 가므로 결정 수와 부른 수가 같아진 뒤에 여기로 돌아온다
        if state.get("next_agent") == "end" or len(log) != len(state.get("agent_trace") or []):
            log = []

        def apply(delta: dict) -> None:
            upd.update(delta)
            view.update(delta)

        if not log:  # 첫 방문: 기억 불러오기와 질의 분석(단일의 load_memory, classify)
            apply({"agent_trace": [], "handoffs": []})  # 에이전트를 한 번도 부르지 않고 끝나도 기록 칸은 있다
            apply(parts.node("load_memory").invoke(dict(view)))
            apply(parts.node("classify").invoke(dict(view)))
        trace = view.get("agent_trace") or []
        last = trace[-1] if trace else None
        allowed, code_path = route_options(parts, view, max_research=research_limit)
        path, note = code_path, {"router": "code"}
        if router == "llm" and len(allowed) >= 2:
            picked, why = ask_router(llm, view, allowed, max_research=research_limit)
            if picked is None:
                note = {"router": "code", "code_choice": code_path, "fallback": why}
            else:
                path, note = picked, {"router": "llm", "code_choice": code_path}
        nxt, closer = PATHS[path]
        if closer:  # 에이전트를 부르지 않고 Supervisor가 직접 닫는다(거절과 되묻기는 코드다)
            apply(parts.node(closer).invoke(dict(view)))
        log.append({"after": last or "intake", "to": nxt, **({"closed_by": closer} if closer else {}), "retries": view.get("retries", 0), **note})
        return {**upd, "next_agent": nxt, "supervisor_log": log}

    g = StateGraph(MultiState)
    g.add_node("supervisor", supervisor)
    for name, spec in specs.items():
        g.add_node(name, _agent_node(spec, agents[name]))
        g.add_edge(name, "supervisor")
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next_agent"], {**{name: name for name in specs}, "end": END})
    return g.compile(checkpointer=checkpointer, store=store)
