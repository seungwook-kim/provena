"""키 없는 데모의 추가 시나리오(팀 합동 검토, 리콜)가 녹화(`data/demo_replay/recorded_scenarios.jsonl`)와 맞는지 보는 시험 (2026-11-16, 0원).

`demo_replay` 표지(기본 실행에서 뺀다. `python -m pytest -m demo_replay`). DB 고르기와 적재는 `test_demo_replay_fresh.py`와 같다.
- 합동 검토: README 데모 구간의 검토 요청(`data/demo_replay/scenarios.json`의 review)을 서버와 같은 질문 그래프로 키 없이 돌리면 LLM 요청·질문 벡터가
  모두 녹화에 있고, 쟁점표 승인 요청(interrupt)에서 멈추며, 관리자 승인으로 재개하면 쟁점표가 저장된다.
- 리콜: 리콜 대상 질문 두 개를 두 답 경로(추론 답 보냄/건너뜀)로 돌려 저장된 답마다, 데모 가상 개정에 대한 판정 요청이 녹화에 있다(ReplayJudge가 규칙 판정으로 내려가지 않는다).
"""
from __future__ import annotations

import importlib
import json
import uuid

import pytest
from langgraph.types import Command
from test_decision_approval import pg_admin_url  # noqa: F401
from test_demo_replay_fresh import _ENV_CLEAR, REPLAY_DIR, keyless_db  # noqa: F401

SCENARIOS = json.loads((REPLAY_DIR / "scenarios.json").read_text(encoding="utf-8"))


@pytest.fixture
def replay_env(keyless_db, monkeypatch):  # noqa: F811
    from backend.services import demo_replay as dr

    search = importlib.import_module("backend.rag.retrieve.search")
    for name in _ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", keyless_db)
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(REPLAY_DIR))
    monkeypatch.setenv("PROVENA_ENV", "local")      # backend.main을 처음 불러올 때 앱을 만든다. 로컬 데모 모드는 서명·암호 키를 이번 실행용으로 만든다
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    missed: list[str] = []

    class SpyStore(dr.ReplayStore):
        def get(self, key):
            row = super().get(key)
            if row is None:
                missed.append("query_embedding")
            return row

    monkeypatch.setitem(dr._stores, str(REPLAY_DIR), SpyStore(REPLAY_DIR))
    monkeypatch.setattr(dr, "_warned", True)
    real_role = dr.message_role

    def spy_fallback(messages, _orig=dr.demo_fallback):
        missed.append(real_role(messages))
        return _orig(messages)

    monkeypatch.setattr(dr, "demo_fallback", spy_fallback)
    monkeypatch.setattr(search, "_searcher", None)
    try:
        yield missed
    finally:
        s = search._searcher
        if s is not None and hasattr(s.store, "close"):
            s.store.close()


def _graph(answer_store=None):
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.answer_store import InMemoryAnswerStore
    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.main import build_question_graph

    st = SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                         store=InMemoryStore(), answer_store=answer_store if answer_store is not None else InMemoryAnswerStore())
    return build_question_graph(st), st


def _run(graph, value, tid):
    from backend.services.llm import finish_run, run_config

    cfg = run_config("demo_replay_scenario", thread_id=tid, configurable={"thread_id": tid})
    try:
        return graph.invoke(value, cfg)
    finally:
        finish_run(cfg)


@pytest.mark.demo_replay
def test_joint_review_replays_to_the_approval_interrupt_and_resumes(replay_env, monkeypatch):
    from backend.graph.service_profile import service_profile

    monkeypatch.setenv("GRAPH_ANSWER_BUDGET_S", "1000")
    with service_profile():
        graph, st = _graph()
        tid = "demo-review-" + uuid.uuid4().hex[:8]
        out = _run(graph, {"question": SCENARIOS["review"]["question"], "user_id": "demo-review", "thread_id": tid, "org": None, "as_of": None}, tid)
        assert not replay_env, f"녹화에 없는 요청: {sorted(set(replay_env))}"
        intr = out.get("__interrupt__")
        assert intr, f"승인 요청에서 멈추지 않았다: kind={out.get('kind')}"
        req = intr[0].value
        assert req["kind"] == "issue_table" and req["table"], req
        _run(graph, Command(resume={"approve": True, "comment": "데모 승인", "decided_by": "admin"}), tid)
        assert not replay_env, f"재개 중 녹화에 없는 요청: {sorted(set(replay_env))}"
        saved = st.issue_store.get_by_thread(tid, "demo-review")
        assert saved is not None and saved["rows"], "승인한 쟁점표가 저장되지 않았다"


@pytest.mark.demo_replay
@pytest.mark.parametrize("budget", ["1000", "0.001"], ids=["reasoning_answer_in_time", "reasoning_answer_skipped"])
def test_recall_verdicts_of_the_demo_revision_are_recorded(replay_env, monkeypatch, budget):
    from backend.graph.answer_store import InMemoryAnswerStore
    from backend.graph.recall.demo_change import changed_of, load_demo_change, with_demo_revision
    from backend.graph.recall.judge import ReplayJudge
    from backend.graph.recall.runtime import section_reader
    from backend.graph.service_profile import service_profile
    from backend.schemas.recall import ChangedArticle
    from backend.services.demo_replay import ReplayChatModel

    monkeypatch.setenv("GRAPH_ANSWER_BUDGET_S", budget)
    rec = load_demo_change()
    ch = ChangedArticle(**changed_of(rec))
    with service_profile():
        answers = InMemoryAnswerStore()
        graph, _ = _graph(answers)
        for q in SCENARIOS["recall"]["recalled_questions"]:
            tid = "demo-recall-" + uuid.uuid4().hex[:8]
            out = _run(graph, {"question": q, "user_id": "demo-recall", "thread_id": tid, "org": None, "as_of": None}, tid)
            assert out.get("kind") == "answer", out.get("kind")
        assert not replay_env, f"녹화에 없는 요청: {sorted(set(replay_env))}"
        rows = answers.find_by_article(ch.rule_seq, ch.article)
        assert len(rows) == 2, "리콜 대상 질문의 답이 가상 개정 섹션을 인용하지 않았다"
        read = with_demo_revision(section_reader(), rec)
        old, new = read(ch.rule_seq, ch.article, ch.old_version_date), read(ch.rule_seq, ch.article, ch.new_version_date)
        judge = ReplayJudge(ReplayChatModel())
        for r in rows:
            assert judge.recorded(r, ch, old["text"], new["text"]), f"판정 요청이 녹화에 없다: {r['question']}"
            v = judge.judge(r, ch, old["text"], new["text"])
            assert v["judge_failed"] is False and v["conclusion_changed"] is True and "Sr Director" in v["explanation"]
