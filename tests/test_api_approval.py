"""`/chat`의 승인 연결과 같은 승인 요청의 중복 실행 시험 (D7, `backend/api/routes.py`, `backend/graph/decision/routes.py`).

합동 검토 질문이 사람 승인(interrupt)에서 멈추면 같은 thread의 새 질문은 409 `approval_pending`이고, 다른 thread는 계속 받는다.
승인 API(`POST /approvals/{id}`)는 같은 결정의 재전송을 그대로 통과시키고(멱등) 다른 결정은 409다. 재전송은 그래프를 다시 돌리지 않는다.
가짜 모델, 가짜 검색기, 메모리 체크포인터·저장소로 돈다. 서버 재시작 뒤 재개는 Postgres가 있을 때만 도는 `tests/test_decision_approval.py`가 본다.
"""
from __future__ import annotations

import threading

import pytest
from api_test_support import Env, ask
from langgraph.types import Command
from qgraph_fakes import first_chunk_id, j
from team_review_fakes import REQUEST, review_llm

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2026-11-05"


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


def mixed_llm():
    """합동 검토 요청(REQUEST)은 review로, 나머지는 정책 질문으로 보낸다."""
    return review_llm(
        classify=lambda u: j(route="review" if REQUEST in u else "rule"),
        rewrite=j(query="SEV2 최초 대응", org="TEST-security", as_of=None),
        judge=j(sufficient=True, reason="", clarify=None),
        answer=lambda u: j(answer=f"근거에 따라 답합니다 [{first_chunk_id(u)}].", citations=[{"chunk_id": first_chunk_id(u)}]),
    )


def review_env(monkeypatch) -> Env:
    llm = mixed_llm()
    return Env(monkeypatch, llm=llm, review_llm=llm)


def start_review(env: Env, thread_id: str = "rv") -> str:
    r, ev = ask(env.client(env.alice), REQUEST, thread_id, as_of=AS_OF)
    assert r.status_code == 200 and [n for n, _ in ev] == ["approval_request"], r.text
    data = ev[0][1]["data"]
    assert data["kind"] == "issue_table" and data["code"] == "approval_pending" and ev[0][1]["thread_id"] == thread_id
    return data["approval_id"]


def count_resumes(env: Env) -> list:
    """승인 라우트가 그래프를 재개한 횟수를 센다(`Command(resume=...)`로 부른 `invoke`)."""
    graph, seen = env.app.state.review_graph, []
    real = graph.invoke

    def spy(inp, *a, **k):
        if isinstance(inp, Command):
            seen.append(inp)
        return real(inp, *a, **k)

    graph.invoke = spy
    return seen


def test_review_question_stops_at_approval_and_blocks_only_that_thread(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        a = env.client(env.alice)
        rec = env.app.state.decision_repo.get_approval(aid)
        assert rec.status == "pending" and rec.thread_id == f"{env.alice.user_id}:rv"    # 승인함에 사용자별 thread 이름으로 올라간다
        assert a.get("/threads").json()["threads"][0]["status"] == "pending_approval"
        r = a.post("/chat", json={"message": Q, "thread_id": "rv"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "approval_pending"
        r, ev = ask(a, Q, "other", as_of="2025-06-01")
        assert r.status_code == 200 and ev[-1][0] == "done"                                 # 다른 thread는 계속 받는다
        r, ev = ask(env.client(env.bob), Q, "rv", as_of="2025-06-01")
        assert r.status_code == 200 and ev[-1][0] == "done"                                 # 다른 사용자의 같은 이름 thread도 받는다


def test_approval_runs_once_and_resend_is_idempotent(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        resumes = count_resumes(env)
        admin = env.client(env.admin)
        first = admin.post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"})
        assert first.status_code == 200 and first.json()["status"] == "approved", first.text
        again = admin.post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"})
        assert again.status_code == 200 and again.json() == first.json()
        assert len(resumes) == 1 and len(env.app.state.issue_store.tables) == 1           # 재개와 저장은 한 번
        flip = admin.post(f"/approvals/{aid}", json={"approve": False, "comment": "반려"})
        assert flip.status_code == 409 and flip.json()["error"]["code"] == "already_decided"
        assert len(resumes) == 1 and env.app.state.decision_repo.get_approval(aid).status == "approved"


def test_concurrent_same_approval_saves_once(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        resumes = count_resumes(env)
        admin_a, admin_b = env.client(env.admin), env.client(env.admin)
        results, gate = [], threading.Barrier(2)

        def send(c):
            gate.wait()
            results.append(c.post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"}))

        workers = [threading.Thread(target=send, args=(c,)) for c in (admin_a, admin_b)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=30)
        assert len(results) == 2 and any(r.status_code == 200 for r in results), [r.text for r in results]
        assert all(r.status_code in (200, 409) for r in results), [r.text for r in results]
        assert len(env.app.state.issue_store.tables) == 1                               # 쟁점표 저장은 한 건
        assert len(resumes) == 1                                                         # 그래프 재개도 한 번
        assert env.app.state.decision_repo.get_approval(aid).status == "approved"


@pytest.mark.parametrize("rounds", [10])
def test_concurrent_same_approval_never_resumes_twice(monkeypatch, rounds):
    """잠금이 없을 때 15번 중 10번 두 번 재개되던 경우를 되풀이해 본다."""
    for _ in range(rounds):
        with review_env(monkeypatch) as env:
            aid = start_review(env)
            resumes, gate, codes = count_resumes(env), threading.Barrier(2), []

            def send(c):
                gate.wait()
                codes.append(c.post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"}).status_code)

            workers = [threading.Thread(target=send, args=(env.client(env.admin),)) for _ in range(2)]
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=30)
            assert sorted(codes) == [200, 200] and len(resumes) == 1 and len(env.app.state.issue_store.tables) == 1


def test_after_approval_the_thread_takes_questions_and_shows_the_answer(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        a = env.client(env.alice)
        assert env.client(env.admin).post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"}).status_code == 200
        assert a.get("/threads").json()["threads"][0]["status"] == "idle"
        detail = a.get("/threads/rv").json()
        assert detail["status"] == "idle" and detail["last"]["kind"] == "answer" and detail["last"]["answer"]   # 재개된 답을 체크포인트에서 읽는다
        r, ev = ask(a, Q, "rv", as_of="2025-06-01")
        assert r.status_code == 200 and ev[-1][0] == "done" and ev[-1][1]["data"]["kind"] == "answer"


def test_rejected_review_frees_the_thread(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        assert env.client(env.admin).post(f"/approvals/{aid}", json={"approve": False, "comment": "근거 부족"}).status_code == 200
        assert env.app.state.issue_store.tables == {}
        r, _ = ask(env.client(env.alice), Q, "rv", as_of="2025-06-01")
        assert r.status_code == 200
