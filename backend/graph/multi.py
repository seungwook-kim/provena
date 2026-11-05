"""멀티 에이전트 질문 그래프 (D-09, G4). Supervisor가 검색, 작성, 검증 하위 에이전트를 불러 단일 그래프(`build.py`)와 같은 일을 나눠 한다.

같은 코드를 쓴다. 이 파일에는 프롬프트, 검색, 인용 검사, 근거 판정, 저장 코드가 없다. `build_graph`가 만든 노드와 분기 함수를 그대로 꺼내
(`SingleParts`, 컴파일된 그래프의 `builder`) 하위 에이전트 안에 다시 배선한다. 그래서 단일의 노드를 고치면 멀티도 같이 바뀐다.

구조(허브와 스포크):

    START -> supervisor <-> retriever | writer | verifier        (supervisor가 매번 다음 에이전트나 끝을 고른다)

| 주체 | 하는 일 (단일 그래프의 노드) | 보는 상태 칸 |
|---|---|---|
| Supervisor | 기억 불러오기(`load_memory`), 질의 분석(`classify`, LLM 1회), 다음 에이전트 고르기, 닫는 단계(`out_of_domain`, `give_up`) | 전체 |
| retriever(검색) | 재작성(`rewrite`) -> 검색(`search`) -> 근거 충분 판정(`judge`). 한 번 도는 것이 한 번의 (재)검색이다 | `RETRIEVER.reads` |
| writer(작성) | 답 작성(`write_answer`) | `WRITER.reads` |
| verifier(검증) | 인용 검사(`verify`) -> 근거 판정(`ground`) -> 저장(`save`) | `VERIFIER.reads` |

- 재검색 정책은 Supervisor가 가진다. retriever가 돌아오면 단일의 `after_judge`(재검색 2회 상한 `MAX_RESEARCH`)를 그대로 불러
  retriever를 다시 부르거나(재검색), writer로 가거나, `give_up`으로 닫는다. 단일과 같은 순서로 같은 노드가 같은 횟수 돈다.
- 컨텍스트 격리: 하위 에이전트는 자기 상태 스키마(`reads` + `writes`)에 있는 칸만 받는다. 다른 칸을 읽거나 쓰는 노드가 생기면 조용히 비지 않고 오류가 난다.
  Supervisor가 에이전트에서 받는 것은 `writes` 칸뿐이다.
- Supervisor는 코드다. 질의 분석에 쓰는 LLM 호출은 단일 `classify`와 같은 1회이고, 라우팅 때문에 늘어나는 LLM 호출은 없다.
- 결과 상태 칸(`kind`, `answer`, `citations`, `retries`, `search_stats` ...)은 단일과 같고 평가 실행기(`evals/agent/run_eval.py`)가 그대로 읽는다.
  멀티에만 있는 칸: `agent_trace`(부른 에이전트 순서), `supervisor_log`(결정 기록), `handoffs`(에이전트마다 받은 칸과 돌려준 칸).
"""
from __future__ import annotations

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from backend.graph.answer_store import AnswerStore
from backend.graph.build import build_graph
from backend.graph.state import AgentState
from backend.schemas import Chunk, SearchQuery


class MultiState(AgentState, total=False):
    """단일 상태(`AgentState`)에 Supervisor의 기록 칸을 더한다."""

    next_agent: str  # supervisor의 마지막 결정: retriever | writer | verifier | end
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
                     "search_cache", "search_stats", "skills_used"}),
    writes=frozenset({"search_query", "search_org", "skills_used", "as_of", "sub_queries", "decompose_source", "kind", "answer", "citations",
                      "search_error", "chunks", "search_cache", "search_stats", "judge_reason", "judge_partial", "retries", "clarify_question"}),
)
WRITER = AgentSpec(
    "writer",
    ("write_answer",),
    reads=frozenset({"question", "chunks", "as_of", "skills_used", "judge_partial"}),
    writes=frozenset({"answer", "raw_citations", "period_covered", "drafted", "skills_used"}),
)
VERIFIER = AgentSpec(
    "verifier",
    ("verify", "ground", "save"),
    reads=frozenset({"question", "answer", "period_covered", "raw_citations", "chunks", "as_of", "skills_used", "user_id", "thread_id", "judge_partial", "dropped_citations"}),
    writes=frozenset({"kind", "answer", "citations", "dropped_citations", "trimmed_citations", "refuse_reason", "grounding", "skills_used", "answer_id"}),
)
AGENTS = {a.name: a for a in (RETRIEVER, WRITER, VERIFIER)}


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
    """하위 에이전트 세 개를 각자의 상태 스키마로 컴파일한다. 안의 노드와 분기는 단일 그래프의 것이다."""
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
    return out


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
):
    """컴파일된 멀티 에이전트 질문 그래프. 인자와 뜻은 `build_graph`와 같다(그대로 넘긴다)."""
    store = store if store is not None else InMemoryStore()
    single = build_graph(retriever, None, llm=llm, answer_store=answer_store, store=store, use_skills=use_skills,
                         grounding_llm=grounding_llm, decompose=decompose)
    parts = SingleParts(single)
    agents = build_agents(parts)

    def supervisor(state: dict) -> dict:
        upd: dict = {}
        view = dict(state)
        log = list(state.get("supervisor_log") or [])

        def apply(delta: dict) -> None:
            upd.update(delta)
            view.update(delta)

        if not log:  # 첫 방문: 기억 불러오기와 질의 분석(단일의 load_memory, classify)
            apply({"agent_trace": [], "handoffs": []})  # 에이전트를 한 번도 부르지 않고 끝나도 기록 칸은 있다
            apply(parts.node("load_memory").invoke(dict(view)))
            apply(parts.node("classify").invoke(dict(view)))
        trace = view.get("agent_trace") or []
        last = trace[-1] if trace else None
        closer = ""
        if last is None:
            if parts.route("classify", view) == "out_of_domain":
                nxt, closer = "end", "out_of_domain"
            else:
                nxt = "retriever"
        elif last == "retriever":
            if view.get("search_error"):  # 단일은 검색 단계에서 바로 끝난다
                nxt = "end"
            else:
                after = parts.route("judge", view)
                nxt = {"write_answer": "writer", "rewrite": "retriever", "give_up": "end"}[after]
                closer = "give_up" if after == "give_up" else ""
        elif last == "writer":
            nxt = "verifier"
        else:
            nxt = "end"
        if closer:  # 에이전트를 부르지 않고 Supervisor가 직접 닫는다(거절과 되묻기는 코드다)
            apply(parts.node(closer).invoke(dict(view)))
        log.append({"after": last or "intake", "to": nxt, **({"closed_by": closer} if closer else {}), "retries": view.get("retries", 0)})
        return {**upd, "next_agent": nxt, "supervisor_log": log}

    g = StateGraph(MultiState)
    g.add_node("supervisor", supervisor)
    for name, spec in AGENTS.items():
        g.add_node(name, _agent_node(spec, agents[name]))
        g.add_edge(name, "supervisor")
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next_agent"], {"retriever": "retriever", "writer": "writer", "verifier": "verifier", "end": END})
    return g.compile(checkpointer=checkpointer, store=store)
