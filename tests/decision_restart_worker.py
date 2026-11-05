"""재시작 시험용 작업 프로세스. 단계마다 새 프로세스로 떠서 Postgres 체크포인터와 결정표 표만으로 이어 간다.
사용: python tests/decision_restart_worker.py <start|resume|run> <DB URL> <thread_id> [approval_id] [approve:0|1]
합동 검토: python tests/decision_restart_worker.py <review_start|review_read> <DB URL> <thread_id> <alone|sub>
          python tests/decision_restart_worker.py review_resume <DB URL> <thread_id> <alone|sub> <재개 값 JSON>
결과는 마지막 줄에 JSON 한 줄로 낸다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_fixtures import EXPENSE_CELLS, FakeLLM, draft_json  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command  # noqa: E402
from team_review_fakes import REQUEST, Retriever, review_llm  # noqa: E402

from backend.graph.checkpoint import is_restart_safe, open_persistence  # noqa: E402
from backend.graph.decision import rules as R  # noqa: E402
from backend.graph.decision.convert import build_convert_graph, pending_interrupt  # noqa: E402
from backend.graph.decision.execute import DecisionExecutor  # noqa: E402
from backend.graph.decision.repo import PostgresDecisionRepo, team_resolution  # noqa: E402
from backend.graph.departments import review as Review  # noqa: E402
from backend.graph.departments.store import PgIssueTableStore  # noqa: E402
from backend.services.auth_store import _default_connect  # noqa: E402

TEAMS = ("security", "infra", "itops", "finance")
BAD_REPLY = "이건 JSON이 아님"


def run_review(stage: str, url: str, thread_id: str, shape: str, saver) -> dict:
    """첫 프로세스에서는 infra 팀의 응답을 읽을 수 없고, 그 뒤 프로세스에서는 읽을 수 있다."""
    Review.TEAM_RETRY_WAIT_SECONDS = 0
    cfg = {"configurable": {"thread_id": thread_id}}
    llm = review_llm(team_infra=BAD_REPLY) if stage == "review_start" else review_llm()
    repo, issues = PostgresDecisionRepo(saver.conn), PgIssueTableStore(_default_connect(url))
    if shape == "sub":
        p = StateGraph(Review.ReviewState)
        p.add_node("review", Review.build_review_graph(Retriever(), None, llm=llm, store=issues, approvals=repo))
        p.add_edge(START, "review")
        p.add_edge("review", END)
        graph = p.compile(checkpointer=saver)
    else:
        graph = Review.build_review_graph(Retriever(), saver, llm=llm, store=issues, approvals=repo)
    res: dict = {}
    if stage == "review_start":
        res = graph.invoke({"question": REQUEST, "user_id": "u1", "thread_id": thread_id, "as_of": "2026-11-05"}, cfg)
    elif stage == "review_resume":
        res = graph.invoke(Command(resume=json.loads(sys.argv[5])), cfg)
    rows = [r for r in repo._rows("SELECT approval_id FROM approvals WHERE thread_id = %s ORDER BY created_at", (thread_id,))]
    records = [repo.get_approval(r["approval_id"]) for r in rows]
    return {"restart_safe": is_restart_safe(saver), "pending": pending_interrupt(graph, thread_id), "review_status": res.get("review_status"),
            "llm": {t: llm.count(f"team_{t}") for t in TEAMS}, "supervisor": llm.count("supervisor"),
            "saved": issues.get_by_thread(thread_id, "u1"),
            "approvals": [{"kind": r.kind, "status": r.status, "resolution": team_resolution(r), "decided_by": r.decided_by} for r in records]}


def main() -> None:
    stage, url, thread_id = sys.argv[1:4]
    cfg = {"configurable": {"thread_id": thread_id}}
    with open_persistence("postgres", url) as (saver, store):
        if stage.startswith("review_"):
            print(json.dumps(run_review(stage, url, thread_id, sys.argv[4], saver), ensure_ascii=False, default=str))
            return
        repo = PostgresDecisionRepo(saver.conn)   # 체크포인터와 같은 연결 풀
        llm = FakeLLM(draft_json(R.rules_from_cells(EXPENSE_CELLS)))
        graph = build_convert_graph(llm, repo, saver, store)
        out: dict = {"restart_safe": is_restart_safe(saver)}
        if stage == "start":
            graph.invoke({"category": "Approving expense", "rule_seq": 1234567890, "version_id": "0a3de83375ab",
                          "source_cells": EXPENSE_CELLS, "requested_by": "admin-1"}, cfg)
            out.update(pending=pending_interrupt(graph, thread_id), llm_calls=len(llm.calls))
        elif stage == "resume":
            approval_id, approve = sys.argv[4], sys.argv[5] == "1"
            before = pending_interrupt(graph, thread_id)
            res = graph.invoke(Command(resume={"approval_id": approval_id, "approve": approve, "comment": "원문과 대조함",
                                               "decided_by": "admin-1"}), cfg)
            out.update(pending_before=bool(before), outcome=res.get("outcome"), pending_after=pending_interrupt(graph, thread_id),
                       llm_calls=len(llm.calls))
        elif stage == "run":
            ex = DecisionExecutor(repo)
            try:
                out["result"] = ex.run("Approving expense", 30000)
            except R.DecisionError as e:
                out["error"] = {"status": e.status, "reason": e.reason}
            out["executions"] = len(ex.executions)
        print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
