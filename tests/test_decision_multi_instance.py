"""승인 결정 잠금이 인스턴스(프로세스) 둘 이상에서도 지켜지는지 본다 (EVAL_REPORT 6장 21행의 후속).

같은 DB를 보는 서버 프로세스 둘(`tests/decision_multi_server.py`, 포트만 다름)에 같은 승인 건의 결정을 동시에 보낸다.
서버는 재개 직전에 잠깐 기다려(`LOCKTEST_DELAY`) 두 요청이 겹치게 만든다. 잠금이 프로세스 안에만 있으면 두 프로세스가 모두 `pending`을 보고
그래프를 두 번 재개한다. 결정표(`decision_table`)와 쟁점표(`issue_table`) 승인 모두 같은 라우트라서 둘 다 본다.
빈 DB에서 두 서버를 동시에 띄우는 시험도 있다(체크포인트 표 만들기가 서로 부딪히지 않아야 한다).
키 없이 가짜 모델로 돌고, Postgres가 없으면 건너뛴다(고르는 순서는 `test_decision_approval.py` 머리말과 같다).
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from decision_fixtures import EXPENSE_CELLS, FakeLLM, draft_json
from team_review_fakes import REQUEST, Retriever, review_llm
from test_decision_approval import OWNER, _role_url, pg_admin_url, pg_url  # noqa: F401  (같은 임시 Postgres 고르기와 표 소유자 접속 정보를 쓴다)

from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, create_access_token
from backend.graph.checkpoint import open_persistence
from backend.graph.decision import rules as R
from backend.graph.decision.convert import build_convert_graph, pending_interrupt
from backend.graph.decision.repo import PostgresDecisionRepo
from backend.graph.departments import review as Review
from backend.graph.departments.store import PgIssueTableStore
from backend.services.auth_store import _default_connect

ROOT = Path(__file__).resolve().parents[1]
EVENTS_DDL = "CREATE TABLE IF NOT EXISTS lock_events (id bigserial PRIMARY KEY, at timestamptz DEFAULT clock_timestamp(), pid int, kind text, ref text, detail text)"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, proc: subprocess.Popen, secs: float = 90) -> None:
    end = time.time() + secs
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError("서버 프로세스가 먼저 끝났다")
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("서버가 뜨지 않음")


class Servers:
    """같은 DB를 보는 서버 프로세스 둘과 관리자 쿠키를 단 클라이언트 둘. 키는 넘기지 않는다."""

    def __init__(self, url: str, delay: str = "0.4") -> None:
        self.secret, self.admin_id = secrets.token_urlsafe(32), uuid.uuid4()
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL" and not k.upper().endswith("_API_KEY")}
        env.update(DATABASE_URL=url, CHECKPOINTER="postgres", LOCKTEST_SECRET=self.secret, LOCKTEST_ADMIN_ID=str(self.admin_id), LOCKTEST_DELAY=delay, PYTHONUTF8="1")
        self.ports = [_free_port(), _free_port()]
        self.clients: list[httpx.Client] = []
        script = str(ROOT / "tests" / "decision_multi_server.py")
        self.procs = [subprocess.Popen([sys.executable, "-X", "utf8", script, str(p)], env=env, cwd=ROOT,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for p in self.ports]   # 연달아 띄운다

    def wait_ready(self) -> list[httpx.Client]:
        for p, proc in zip(self.ports, self.procs):
            _wait_port(p, proc)
        token = create_access_token(self.admin_id, "admin", secret=self.secret)
        self.clients = [httpx.Client(base_url=f"http://127.0.0.1:{p}", cookies={AUTH_COOKIE_NAME: token, CSRF_COOKIE_NAME: "csrf"},
                                     headers={"X-CSRF-Token": "csrf"}, timeout=60) for p in self.ports]
        assert len({proc.pid for proc in self.procs}) == 2
        return self.clients

    def close(self) -> None:
        for c in self.clients:
            c.close()
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def two_servers(pg_url):  # noqa: F811
    import psycopg

    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute(EVENTS_DDL)
    servers = Servers(pg_url)
    try:
        yield servers.wait_ready()
    finally:
        servers.close()


def _start_pending(pg_url: str, kind: str) -> tuple[str, str]:  # noqa: F811
    """승인 대기까지 돌린 (thread_id, approval_id). 시작은 가짜 모델이 쓴다."""
    tid = f"mi-{uuid.uuid4().hex[:10]}"
    cfg = {"configurable": {"thread_id": tid}}
    with open_persistence("postgres", pg_url) as (saver, store):
        repo = PostgresDecisionRepo(saver.conn)
        if kind == "decision_table":
            graph = build_convert_graph(FakeLLM(draft_json(R.rules_from_cells(EXPENSE_CELLS))), repo, saver, store)
            graph.invoke({"category": "Approving expense", "rule_seq": 1234567890, "version_id": "0a3de83375ab", "source_cells": EXPENSE_CELLS,
                          "requested_by": "admin-1"}, cfg)
        else:
            graph = Review.build_review_graph(Retriever(), saver, llm=review_llm(), store=PgIssueTableStore(_default_connect(pg_url)), approvals=repo)
            graph.invoke({"question": REQUEST, "user_id": "u1", "thread_id": tid, "as_of": "2026-11-05"}, cfg)
        pending = pending_interrupt(graph, tid)
        assert pending["kind"] == kind
        return tid, pending["approval_id"]


@pytest.mark.parametrize("kind", ["decision_table", "issue_table"])
@pytest.mark.parametrize("approve_a,approve_b", [(True, True), (False, False), (True, False), (False, True)])
@pytest.mark.parametrize("round_", [1, 2])
def test_two_instances_resume_the_graph_once_and_keep_one_decision(two_servers, pg_url, kind, approve_a, approve_b, round_):  # noqa: F811
    import psycopg

    tid, aid = _start_pending(pg_url, kind)
    gate, codes, bodies = threading.Barrier(2), [None, None], [None, None]

    def fire(k: int, approve: bool) -> None:
        gate.wait()
        r = two_servers[k].post(f"/approvals/{aid}", json={"approve": approve, "comment": ""})
        codes[k], bodies[k] = r.status_code, r.json()

    threads = [threading.Thread(target=fire, args=(0, approve_a)), threading.Thread(target=fire, args=(1, approve_b))]
    [t.start() for t in threads]
    [t.join() for t in threads]

    with psycopg.connect(pg_url, autocommit=True) as c:
        resumes = c.execute("SELECT count(DISTINCT pid), count(*) FROM lock_events WHERE ref = %s AND kind = 'graph_resume'", (tid,)).fetchone()
        (status,) = c.execute("SELECT status FROM approvals WHERE approval_id = %s", (aid,)).fetchone()
        if kind == "decision_table":
            (table_status,) = c.execute("SELECT t.status FROM approvals a JOIN decision_tables t ON t.table_id = a.target_id WHERE a.approval_id = %s", (aid,)).fetchone()
            assert table_status == status
        else:   # 쟁점표: 승인이면 저장 1건, 반려면 0건(반려 사유는 approvals 줄이 갖는다). 반려인데 저장이 남으면 안 된다
            saved = c.execute("SELECT count(*) FROM issue_tables WHERE thread_id = %s", (tid,)).fetchone()[0]
            assert saved == (1 if status == "approved" else 0), f"저장 {saved}건, 최종 {status}"
    assert resumes[1] == 1, f"그래프가 {resumes[1]}번 재개됐다(프로세스 {resumes[0]}개): {codes}"
    assert status in ("approved", "rejected")
    if approve_a == approve_b:
        assert codes == [200, 200] and {b["status"] for b in bodies} == {status}
    else:
        assert sorted(codes) == [200, 409], codes              # 뒤에 온 반대 결정은 접수된 결정을 말없이 바꾸지 못하고 409다
        winner = codes.index(200)
        assert bodies[winner]["status"] == status and (status == "approved") == (approve_a if winner == 0 else approve_b)


@pytest.mark.parametrize("round_", [1, 2, 3, 4])
def test_two_instances_starting_together_on_an_empty_db_both_come_up(pg_admin_url, pg_url, round_):  # noqa: F811
    """빈 DB(체크포인트·Store 표 없음)에서 서버 둘을 연달아 띄워도 둘 다 저장소를 열어 승인함을 읽는다. 표 만들기가 부딪히면 한쪽이 죽거나 503이다."""
    import psycopg

    db = f"provena_lock_empty_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_admin_url, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {db} OWNER {OWNER}")
    url = _role_url(pg_admin_url, OWNER, db)
    servers = None
    try:
        with psycopg.connect(url, autocommit=True) as c:
            for name in ("102_decision_approvals.sql", "110_issue_tables.sql"):   # 앱 표는 SQL 파일로 만들어 두고, 비어 있는 것은 LangGraph 표뿐이다
                c.execute((ROOT / "db" / name).read_text(encoding="utf-8"))
            assert c.execute("SELECT to_regclass('checkpoints')").fetchone()[0] is None
        servers = Servers(url, delay="0")
        clients = servers.wait_ready()
        for client in clients:
            r = client.get("/approvals")
            assert r.status_code == 200 and r.json() == [], r.text
        with psycopg.connect(url) as c:
            assert c.execute("SELECT count(*) FROM checkpoint_migrations").fetchone()[0] > 0
    finally:
        if servers is not None:
            servers.close()
        with psycopg.connect(pg_admin_url, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
