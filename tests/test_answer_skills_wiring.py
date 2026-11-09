"""`delegation`, `report-writing` 연결 시험 (미실행 초안). 가짜 모델과 가짜 검색기만 쓴다.

단일과 멀티에서 같은 Skill이 실제 시스템 프롬프트까지 가는지 본다. 멀티는 `route`를 reads에 넣지 않으면 조용히 빠지므로 따로 잰다.
호출 수가 늘지 않는 것도 여기서 확인한다.
"""
from __future__ import annotations

import pytest
from qgraph_fakes import ScriptedLLM, j, normal_llm
from team_review_fakes import RecordingLLM, Retriever, review_llm

from backend.graph.build import build_graph
from backend.graph.departments.review import build_review_graph
from backend.graph.departments.store import InMemoryIssueTableStore
from backend.graph.multi import build_multi_graph
from backend.schemas import Chunk

MARK = "[승인 권한표 Skill]"


class SystemsLLM(ScriptedLLM):
    def __init__(self, handlers):
        super().__init__(handlers)
        self.systems: dict[str, list[str]] = {}

    def invoke(self, messages, *a, **k):
        out = super().invoke(messages, *a, **k)
        self.systems.setdefault(self.calls[-1][0], []).append(messages[0].content)
        return out


def chunk(title: str = "Procurement") -> Chunk:
    return Chunk(chunk_id="a" * 16, org="finance", rule_seq=1, rule_title=title, article="Approving expense > 구간",
                 version_id="v1", version_date="2023-05-11", fetched_at="2026-11-02", kind="row", text="T > A\nDirector (functional approval): Approves",
                 source_url="https://handbook.gitlab.com/handbook/finance/authorization-matrix/")


def llm_for(route: str) -> SystemsLLM:
    base = normal_llm(classify=j(route=route), rewrite=j(query="approval", org="finance", as_of=None))
    return SystemsLLM(base.handlers)


def ask(graph):
    return graph.invoke({"question": "지출 승인자는 누구인가요?", "user_id": "u", "thread_id": "t"})


BUILDERS = {"single": build_graph, "multi": build_multi_graph}


@pytest.mark.parametrize("arm", BUILDERS)
def test_decision_question_gets_delegation_in_answer(arm):
    llm = llm_for("decision")
    state = ask(BUILDERS[arm](lambda q: [chunk()], llm=llm, use_skills=True, grounding_llm=False))
    assert MARK in llm.systems["answer"][0]
    assert "delegation" in state["skills_used"]


@pytest.mark.parametrize("arm", BUILDERS)
def test_rule_question_does_not_get_delegation(arm):
    llm = llm_for("rule")
    state = ask(BUILDERS[arm](lambda q: [chunk()], llm=llm, use_skills=True, grounding_llm=False))
    assert MARK not in llm.systems["answer"][0]
    assert "delegation" not in state["skills_used"]


@pytest.mark.parametrize("arm", BUILDERS)
@pytest.mark.parametrize("title", ["Authorization Matrix", "Authorization Matrix (2023-05)"])
def test_rule_route_with_authz_page_gets_delegation(arm, title):
    """분류기가 `rule`로 보내도 자료에 권한표가 있으면 붙는다. v1 30건은 route=decision이 0건이었다."""
    llm = llm_for("rule")
    state = ask(BUILDERS[arm](lambda q: [chunk(title)], llm=llm, use_skills=True, grounding_llm=False))
    assert MARK in llm.systems["answer"][0] and "delegation" in state["skills_used"]


@pytest.mark.parametrize("arm", BUILDERS)
def test_skills_off_removes_it(arm):
    llm = llm_for("decision")
    ask(BUILDERS[arm](lambda q: [chunk()], llm=llm, use_skills=False, grounding_llm=False))
    assert MARK not in llm.systems["answer"][0]


def test_same_llm_calls_with_and_without_delegation():
    """Skill을 붙여도 호출 수는 같다."""
    on, off = llm_for("decision"), llm_for("rule")
    ask(build_graph(lambda q: [chunk()], llm=on, use_skills=True, grounding_llm=False))
    ask(build_graph(lambda q: [chunk()], llm=off, use_skills=True, grounding_llm=False))
    assert [t for t, _ in on.calls] == [t for t, _ in off.calls]


def test_grounding_llm_reads_delegation_on_decision_route():
    llm = llm_for("decision")
    llm.handlers["grounding"] = j(grounded=True)
    ask(build_graph(lambda q: [chunk()], llm=llm, use_skills=True, grounding_llm=True))
    assert MARK in llm.systems["grounding"][0]


def _run_review(use_skills: bool) -> RecordingLLM:
    from langgraph.checkpoint.memory import InMemorySaver

    llm = review_llm()
    g = build_review_graph(Retriever(), InMemorySaver(), llm=llm, store=InMemoryIssueTableStore(), use_skills=use_skills)
    g.invoke({"question": "새 도구 도입", "user_id": "u", "thread_id": "r", "as_of": "2026-11-05"}, {"configurable": {"thread_id": "r"}})
    return llm


def test_report_writing_reaches_every_team():
    llm = _run_review(True)
    team_systems = [s for task, ss in llm.systems.items() if task.startswith("team") for s in ss]
    assert team_systems and all("[쟁점표 양식 Skill]" in s for s in team_systems)


def test_report_writing_off():
    llm = _run_review(False)
    assert not any("[쟁점표 양식 Skill]" in s for ss in llm.systems.values() for s in ss)


def test_report_writing_adds_no_llm_call(monkeypatch):
    from backend.graph.departments import teams as T

    on = _run_review(True)
    monkeypatch.setattr(T, "team_skills", T.load_team_skill)
    off = _run_review(True)
    assert sorted(t for t, _ in on.calls) == sorted(t for t, _ in off.calls)
