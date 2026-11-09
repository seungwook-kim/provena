"""승인 대기의 시스템 몫을 잰다 (EVAL_REPORT 8장 "승인 대기", 가이드 p.19). 사람이 기다린 시간은 사람 몫이라 빼고, 기계가 쓴 시간만 잰다.

- 멈춤: 시작 요청부터 `interrupt()`로 멈춰 체크포인트가 저장되고 호출이 돌아올 때까지. 가짜 LLM이라 LLM 시간은 0에 가깝다(LLM 시간은 stage_report 몫).
- 대기 확인: 멈춘 자리를 체크포인트에서 읽는 시간(`pending_interrupt`). 승인함 목록과 재개 전 검사가 이것을 부른다.
- 재개: `Command(resume=결정)`부터 멈춘 노드가 다시 돌아 결정을 내놓을 때까지(첫 노드), 그다음 노드(저장)가 끝날 때까지(끝).
- HTTP(결정표만): 실제 라우터(`backend/graph/decision/routes.py`)로 `POST /decision-tables/convert`와 `POST /approvals/{id}`의 왕복 시간.
  인증 쿠키·CSRF·승인 건 잠금·재개·저장·응답 만들기가 다 들어간다. TestClient라 네트워크는 없다.

그래프 두 개: 결정표 변환(`convert.build_convert_graph`, 승인 지점 `human_approval`), 합동 검토(`review.build_review_graph`, 승인 지점 `approval`).
체크포인터 두 개: 메모리(`InMemorySaver`, 기준선)와 Postgres(`open_persistence("postgres")`, 배포와 같은 종류). 둘의 차이가 체크포인트 저장·읽기 몫이다.
덧붙여 승인 없는 질문 그래프 한 번을 체크포인터 없음·메모리·Postgres로 잰다: 평가 결과는 체크포인터 없이 잰 값이고 API는 Postgres를 쓴다.
가짜 모델과 가짜 검색기는 팀 시험의 것(`tests/decision_fixtures.py`, `tests/team_review_fakes.py`)을 그대로 쓴다. 키도 네트워크도 쓰지 않는다.

사용 (Postgres 접속 정보는 환경변수로만 받고 출력하지 않는다. 표를 만들므로 빈 DB를 쓴다):
  APPROVAL_PG_URL=postgresql://사용자:***@127.0.0.1:54331/빈DB python -m evals.agent.approval_latency --n 20 --json 결과.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))   # 팀 시험의 가짜 모델·검색기

from decision_fixtures import FakeLLM, draft_json  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402
from langgraph.types import Command  # noqa: E402
from team_review_fakes import REQUEST, Retriever, review_llm  # noqa: E402

from backend.graph.checkpoint import open_persistence  # noqa: E402
from backend.graph.decision import rules as R  # noqa: E402
from backend.graph.decision.convert import build_convert_graph, pending_interrupt  # noqa: E402
from backend.graph.decision.repo import InMemoryDecisionRepo, PostgresDecisionRepo  # noqa: E402
from backend.graph.departments import review as Review  # noqa: E402
from backend.graph.departments.store import InMemoryIssueTableStore, PgIssueTableStore  # noqa: E402
from backend.services.auth_store import _default_connect  # noqa: E402

CATEGORY = "Approving expense"
SQL_FILES = ("102_decision_approvals.sql", "110_issue_tables.sql")


def pct(values: list[float], q: float) -> float | None:
    """최근순위 백분위(`evals/agent/run_eval.py` `_p95`와 같은 방식)."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def authz_cells() -> list[dict]:
    from backend.graph.decision.routes import AUTHZ_CELLS_FILE

    lines = AUTHZ_CELLS_FILE.read_text(encoding="utf-8").splitlines()
    return [c for c in map(json.loads, lines) if R.norm(c["category"]) == R.norm(CATEGORY)]


def convert_case(saver, store, repo):
    cells = authz_cells()
    graph = build_convert_graph(FakeLLM(draft_json(R.rules_from_cells(cells))), repo, saver, store)
    start = {"category": cells[0]["category"], "rule_seq": 1, "version_id": "s8-bench", "source_cells": cells, "requested_by": "admin-1"}
    return graph, start, lambda p: {"approval_id": p["approval_id"], "approve": True, "comment": "원문과 대조함", "decided_by": "admin-1"}


def review_case(saver, store, repo, issues):
    Review.TEAM_RETRY_WAIT_SECONDS = 0
    graph = Review.build_review_graph(Retriever(), saver, llm=review_llm(), store=issues, approvals=repo)
    return graph, None, lambda p: {"approve": True, "comment": "", "decided_by": "admin-1"}


def one_trial(graph, start: dict, decision, tid: str) -> dict:
    cfg = {"configurable": {"thread_id": tid}}
    t0 = time.perf_counter()
    graph.invoke(start, cfg)
    t_stop = time.perf_counter() - t0
    t0 = time.perf_counter()
    pending = pending_interrupt(graph, tid)
    t_read = time.perf_counter() - t0
    if pending is None:
        raise SystemExit("승인 대기에 이르지 못했다")
    marks: list[tuple[str, float]] = []
    t0 = time.perf_counter()
    for update in graph.stream(Command(resume=decision(pending)), cfg, stream_mode="updates"):
        marks.append((next(iter(update)), time.perf_counter() - t0))
    if pending_interrupt(graph, tid) is not None:
        raise SystemExit("재개 뒤에도 승인 대기다")
    return {"stop_s": t_stop, "read_s": t_read, "resume_first_node_s": marks[0][1], "resume_end_s": marks[-1][1], "nodes": [m[0] for m in marks]}


def run_graph_bench(kind: str, which: str, n: int, url: str | None) -> dict:
    """`kind`: memory|postgres, `which`: convert|review. 앞의 1회는 데우기로 빼고 n회를 잰다."""
    def trials(saver, store, repo, issues):
        graph, start, decision = convert_case(saver, store, repo) if which == "convert" else review_case(saver, store, repo, issues)
        rows = []
        for i in range(n + 1):
            tid = f"s8-{which}-{kind}-{uuid.uuid4().hex[:8]}"
            st = start if start is not None else {"question": REQUEST, "user_id": "u1", "thread_id": tid, "as_of": "2026-11-05"}
            r = one_trial(graph, st, decision, tid)
            if i:
                rows.append(r)
        return rows

    if kind == "memory":
        rows = trials(InMemorySaver(), InMemoryStore(), InMemoryDecisionRepo(), InMemoryIssueTableStore())
    else:
        with open_persistence("postgres", url) as (saver, store):
            rows = trials(saver, store, PostgresDecisionRepo(saver.conn), PgIssueTableStore(_default_connect(url)))
    keys = ("stop_s", "read_s", "resume_first_node_s", "resume_end_s")
    return {"graph": which, "checkpointer": kind, "n": len(rows), "nodes_after_resume": rows[0]["nodes"],
            **{k: {"p50": pct([r[k] for r in rows], 0.5), "p95": pct([r[k] for r in rows], 0.95), "max": max(r[k] for r in rows)} for k in keys},
            "raw": rows}


def run_http_bench(n: int, url: str) -> dict:
    """실제 결정표 라우터. 매 회 승인된 표를 지워(시간 밖) 같은 업무 종류로 다시 변환할 수 있게 한다(같은 종류의 승인 표는 하나만 둔다, AC-06)."""
    import psycopg
    from auth_test_support import MemoryRevocationStore
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, create_access_token
    from backend.graph.decision.routes import create_decision_router, open_decision_runtime

    secret = secrets.token_urlsafe(32)
    admin = AuthUser(user_id=uuid.uuid4(), login_id="admin", password_hash="x", role="admin")

    class Users:
        def get_by_login_id(self, login_id):
            return None

        def get_by_user_id(self, user_id):
            return admin if str(user_id) == str(admin.user_id) else None

    os.environ["DATABASE_URL"], os.environ["CHECKPOINTER"] = url, "postgres"
    app = FastAPI()
    app.state.token_revocation_store = MemoryRevocationStore()
    app.include_router(create_decision_router(store=Users(), secret=secret))
    client = TestClient(app)
    client.cookies.set(AUTH_COOKIE_NAME, create_access_token(admin.user_id, admin.role, secret=secret))
    client.cookies.set(CSRF_COOKIE_NAME, "csrf")
    h = {"X-CSRF-Token": "csrf"}
    rows = []
    with open_decision_runtime(app):
        cells = authz_cells()   # 가짜 모델로 바꾼다. 체크포인터·저장소·승인 건 표는 런타임이 연 실제 것 그대로
        app.state.decision_graph = build_convert_graph(FakeLLM(draft_json(R.rules_from_cells(cells))), app.state.decision_repo,
                                                       app.state.checkpointer, app.state.store)
        for i in range(n + 1):
            with psycopg.connect(url, autocommit=True) as c:
                c.execute("DELETE FROM approvals WHERE kind = 'decision_table'")
                c.execute("DELETE FROM decision_tables")
            t0 = time.perf_counter()
            r1 = client.post("/decision-tables/convert", json={"category": CATEGORY}, headers=h)
            t_convert = time.perf_counter() - t0
            if r1.status_code != 201:
                raise SystemExit(f"변환 실패 {r1.status_code}: {r1.text[:200]}")
            aid = r1.json()["approval_id"]
            t0 = time.perf_counter()
            r2 = client.post(f"/approvals/{aid}", json={"approve": True, "comment": "원문과 대조함"}, headers=h)
            t_decide = time.perf_counter() - t0
            if r2.status_code != 200 or r2.json().get("status") != "approved":
                raise SystemExit(f"승인 실패 {r2.status_code}: {r2.text[:200]}")
            if i:
                rows.append({"convert_s": t_convert, "decide_s": t_decide})
    keys = ("convert_s", "decide_s")
    return {"graph": "convert(HTTP)", "checkpointer": "postgres", "n": len(rows),
            **{k: {"p50": pct([r[k] for r in rows], 0.5), "p95": pct([r[k] for r in rows], 0.95), "max": max(r[k] for r in rows)} for k in keys},
            "raw": rows}


def run_question_bench(kind: str, n: int, url: str | None) -> dict:
    """승인 없는 질문 그래프 한 번(가짜 모델·가짜 검색기)의 시간. 평가 결과(stage_report)는 체크포인터 없이 잰 값이고
    API(`backend/main.py` `build_graph(None, state.checkpointer, ...)`)는 Postgres 체크포인터를 쓰므로, 그 차이(노드마다 저장)를 따로 본다."""
    from fake_search import fake_search
    from qgraph_fakes import normal_llm

    from backend.graph.build import build_graph

    def trials(saver, store):
        graph = build_graph(fake_search, saver, llm=normal_llm(), store=store, decompose=False)
        out = []
        for i in range(n + 1):
            tid = f"s8-q-{kind}-{uuid.uuid4().hex[:8]}"
            cfg = {"configurable": {"thread_id": tid}} if saver is not None else None
            t0 = time.perf_counter()
            res = graph.invoke({"question": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "user_id": "u1", "thread_id": tid, "as_of": "2025-06-01"}, cfg)
            dt = time.perf_counter() - t0
            if not res.get("answer"):
                raise SystemExit("질문 그래프가 답을 내지 않았다")
            if i:
                out.append(dt)
        return out

    if kind == "none":
        rows = trials(None, InMemoryStore())
    elif kind == "memory":
        rows = trials(InMemorySaver(), InMemoryStore())
    else:
        with open_persistence("postgres", url) as (saver, store):
            rows = trials(saver, store)
    return {"graph": "question", "checkpointer": kind, "n": len(rows), "total_s": {"p50": pct(rows, 0.5), "p95": pct(rows, 0.95), "max": max(rows)}, "raw": rows}


def setup_db(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as c:
        for name in SQL_FILES:
            c.execute((ROOT / "db" / name).read_text(encoding="utf-8"))


def ms(x: float | None) -> str:
    return "-" if x is None else f"{x * 1000:.1f}"


def render(results: list[dict]) -> str:
    lines = ["| 그래프 | 체크포인터 | n | 멈춤 p50/p95 | 대기 확인 p50/p95 | 재개→첫 노드 p50/p95 | 재개→끝 p50/p95 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        if "stop_s" not in r:
            continue
        cell = lambda k: f"{ms(r[k]['p50'])} / {ms(r[k]['p95'])}"  # noqa: E731
        lines.append(f"| {r['graph']} | {r['checkpointer']} | {r['n']} | {cell('stop_s')} | {cell('read_s')} | {cell('resume_first_node_s')} | {cell('resume_end_s')} |")
    lines.append("\n(ms. 재개 뒤 노드 순서: " + "; ".join(f"{r['graph']} {r['nodes_after_resume']}" for r in results if "nodes_after_resume" in r) + ")")
    q = [r for r in results if r["graph"] == "question"]
    if q:
        lines.append("\n질문 그래프 한 번(승인 없음, 가짜 모델): " + ", ".join(f"체크포인터 {r['checkpointer']} p50 {ms(r['total_s']['p50'])} p95 {ms(r['total_s']['p95'])} ms (n {r['n']})" for r in q))
    for r in results:
        if "convert_s" in r:
            lines.append(f"\nHTTP 결정표 (Postgres, n {r['n']}): POST /decision-tables/convert p50 {ms(r['convert_s']['p50'])} p95 {ms(r['convert_s']['p95'])} ms, "
                         f"POST /approvals/{{id}} p50 {ms(r['decide_s']['p50'])} p95 {ms(r['decide_s']['p95'])} ms")
    return "\n".join(lines)


def measured_with(url: str | None) -> dict:
    """무엇으로 잰 숫자인가(원칙집 0장 12번). 접속 정보는 남기지 않고 서버 판만 남긴다."""
    import importlib.metadata as md
    import platform
    import subprocess

    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = {"code_commit": head, "llm": "가짜 모델(tests/decision_fixtures.FakeLLM, team_review_fakes, qgraph_fakes)", "network": "없음(TestClient, 로컬 DB)",
            "python": platform.python_version(), **{p: md.version(p) for p in ("langgraph", "langgraph-checkpoint-postgres", "psycopg")}}
    if url:
        import psycopg

        with psycopg.connect(url) as c:
            meta["postgres"] = c.execute("SHOW server_version").fetchone()[0] + " (같은 PC의 Docker 컨테이너)"
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    url = os.environ.get("APPROVAL_PG_URL")
    for name in ("DEMO_MODE", "LLM_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        os.environ.pop(name, None)   # 가짜 모델만 쓴다. 키가 남아 있어도 부르지 않게 지운다
    results = []
    for which in ("convert", "review"):
        results.append(run_graph_bench("memory", which, args.n, None))
        if url:
            if which == "convert":
                setup_db(url)
            results.append(run_graph_bench("postgres", which, args.n, url))
    for kind in ("none", "memory", "postgres"):
        if kind != "postgres" or url:
            results.append(run_question_bench(kind, args.n, url))
    if url:
        results.append(run_http_bench(args.n, url))
    meta = measured_with(url)
    print(render(results))
    print(f"\n무엇으로 잰 숫자인가: {meta}")
    if args.json:
        Path(args.json).write_text(json.dumps({"measured_with": meta, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
