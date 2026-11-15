"""K-24: 키 없는 데모에서 같은 녹화 질문을 여러 번 물어도 답이 같아야 한다 (`demo_replay` 표지, Postgres 필요, 키·네트워크 없이 0원).

서버처럼 한 프로세스·한 재생 저장소에서 데모 질문 9개를 차례로 여러 바퀴 돌려 질문마다 결과(종류, 답 글, 인용)가 바퀴마다 같은지 본다.
예전에는 재생 저장소가 같은 요청 키의 응답 변형 차례를 프로세스 전체로 세서, 둘째 바퀴부터 다른 변형으로 시작해 근거 확인 다수결과 답 글이 바뀌었다
(`backend/services/demo_replay.py` `pick_ranked`, `backend/services/llm.py` `run_config`의 `replay_run`). DB 준비는 `test_demo_replay_fresh.py`와 같다.
"""
from __future__ import annotations

import importlib
import uuid

import pytest
from test_decision_approval import pg_admin_url  # noqa: F401  (같은 임시 Postgres 고르기)
from test_demo_replay_fresh import _ENV_CLEAR, REPLAY_DIR, _file_questions, keyless_db  # noqa: F401

ROUNDS = 3


def _run_rounds(keyless_db, monkeypatch, rounds: int) -> dict[str, list[tuple]]:
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.graph.recall.runtime import make_answer_store
    from backend.graph.service_profile import service_profile
    from backend.main import build_question_graph
    from backend.services import demo_replay as dr
    from backend.services.llm import finish_run, run_config

    search = importlib.import_module("backend.rag.retrieve.search")
    for name in _ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", keyless_db)
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(REPLAY_DIR))
    monkeypatch.setitem(dr._stores, str(REPLAY_DIR), dr.ReplayStore(REPLAY_DIR))   # 서버처럼 바퀴 사이에 같은 저장소를 쓴다
    monkeypatch.setattr(dr, "_warned", True)
    monkeypatch.setattr(search, "_searcher", None)
    monkeypatch.setenv("GRAPH_ANSWER_BUDGET_S", "1000")   # 검색 속도에 따라 추론 답 경로가 갈리지 않게 고정한다

    seen: dict[str, list[tuple]] = {}
    try:
        with service_profile():
            st = SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                                 store=InMemoryStore(), answer_store=make_answer_store(None))
            graph = build_question_graph(st)
            for _ in range(rounds):
                for q in _file_questions():
                    tid = "demo-replay-repeat-" + uuid.uuid4().hex[:8]
                    cfg = run_config("demo_replay_repeat", thread_id=tid, configurable={"thread_id": tid})
                    try:
                        out = graph.invoke({"question": q, "user_id": "demo-replay-repeat", "thread_id": tid, "org": None, "as_of": None}, cfg)
                    finally:
                        finish_run(cfg)
                    cited = tuple(c.get("chunk_id") for c in out.get("citations") or [])
                    seen.setdefault(q, []).append((out.get("kind"), out.get("answer") or "", cited))
    finally:
        s = search._searcher
        if s is not None and hasattr(s.store, "close"):
            s.store.close()
    return seen


@pytest.mark.demo_replay
def test_same_demo_question_gives_the_same_answer_every_time(keyless_db, monkeypatch):
    seen = _run_rounds(keyless_db, monkeypatch, ROUNDS)
    differ = {q: [f"{k} {len(a)}자 인용{len(c)}" for k, a, c in runs] for q, runs in seen.items() if len(set(runs)) > 1}
    assert not differ, f"같은 질문인데 바퀴마다 결과가 달랐다(K-24): {differ}"
