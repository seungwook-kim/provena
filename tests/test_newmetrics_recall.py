"""리콜 운영 측정기의 계획·안전장치·점수(0원, 운영 접속 없음). 넣기·정리의 실제 SQL은 버리는 로컬 Postgres 예행(newmetrics_local_dryrun.ps1)에서 본다."""
from __future__ import annotations

import pytest

from evals.newmetrics import recall_prod as RP
from evals.newmetrics.handbook_history import SectionChange


class FakeHistory:
    def __init__(self, removed: set[str] = frozenset()):
        self.removed = removed

    def section_change(self, commit, page, section):
        ct = "removed" if section in self.removed else "modified"
        return SectionChange(commit + "f" * 32, page, 123, section, ct, "2026-01-01", "2026-02-01", "2026-01-31",
                             "old body 30 days", "" if ct == "removed" else "new body 90 days", "raw", "raw", f"https://handbook.gitlab.com/{page}", False)


def pairs() -> list[dict]:
    out = []
    for i in range(1, 7):
        sec = "S1" if i <= 3 else "S2"
        out.append({"id": f"R{i:02d}", "commit": "0c787db1", "page": "p.md", "section": sec, "question": f"질문 {i}", "answer": f"답 {i}",
                    "expected": i % 2 == 1, "ambiguous": i == 6})
    return out


def test_plan_marks_every_row_and_uses_92e8_range():
    plan = RP.build_plan(pairs(), FakeHistory({"S2"}), run=2, date="20261116", user_id="u-b")
    assert [g.rule_seq for g in plan.groups] == [9_200_000_200, 9_200_000_201]
    assert all(a["answer_id"].startswith("TEST-RCL-EVAL-20261116-r2-") for g in plan.groups for a in g.answers)
    assert plan.groups[1].new_chunk is None                     # 삭제된 섹션은 새 판 청크가 없다
    assert len(set(plan.event_keys)) == 2
    RP.assert_ours(plan)
    plan.groups[0].answers[0]["answer_id"] = "real-answer"
    with pytest.raises(ValueError):
        RP.assert_ours(plan)


def test_event_keys_differ_between_runs():
    p1 = RP.build_plan(pairs(), FakeHistory(), run=1, date="20261116", user_id="u")
    p2 = RP.build_plan(pairs(), FakeHistory(), run=2, date="20261116", user_id="u")
    assert not set(p1.event_keys) & set(p2.event_keys)


class FakeConn:
    """execute 결과를 순서대로 돌려주는 가짜 연결(실제 SQL은 실행하지 않음)."""

    def __init__(self, one=None, rows=None, rowcount=1):
        self.sql, self.one, self.rows, self.rowcount = [], one, rows or [], rowcount
        self.committed = self.rolled = False

    def execute(self, sql, prm=None):
        self.sql.append((sql, prm))
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled = True


def test_preflight_stops_when_any_webhook_subscription_is_active():
    plan = RP.build_plan(pairs(), FakeHistory(), run=1, date="20261116", user_id="u")
    with pytest.raises(RP.PreflightError):
        RP.preflight(FakeConn(one=(1,)), plan)


def test_insert_rolls_back_when_counts_differ():
    plan = RP.build_plan(pairs(), FakeHistory(), run=1, date="20261116", user_id="u")
    conn = FakeConn(one=(0,), rowcount=0)
    with pytest.raises(RuntimeError):
        RP.insert_plan(conn, plan)
    assert conn.rolled and not conn.committed
    assert all("%(" in s or "%s" not in s for s, _ in conn.sql)   # 값은 이름 자리로만


def test_delete_sql_is_scoped_by_keys_and_prefix():
    for name, sql in RP.SQL_DEL:
        assert "ANY(" in sql or "starts_with" in sql or "?| %(nids)s" in sql, name
        if name in ("citations", "answers", "chunks", "versions", "docs"):
            assert "starts_with" in sql and "ANY(" in sql, name


def rows(view_hits: dict[str, bool], status="done"):
    out = []
    for r in pairs():
        hit = view_hits.get(r["id"], False)
        out.append({"id": r["id"], "expected": r["expected"], "ambiguous": r["ambiguous"], "event_status": status,
                    "notice": hit, "user": hit, "judge": hit})
    return out


def test_score_recall_precision_excludes_ambiguous():
    # 양성(예) R01, R03, R05. 알림 R01, R02, R06(애매) -> TP 1, FP 1, FN 2, 애매 R06은 세지 않음
    s = RP.score(rows({"R01": True, "R02": True, "R06": True}), "notice")
    assert (s["tp"], s["fp"], s["fn"], s["n"]) == (1, 1, 2, 5)
    assert s["recall"] == round(1 / 3, 4) and s["precision"] == 0.5


def test_not_processed_rows_leave_denominator():
    s = RP.score(rows({"R01": True}, status="failed"), "notice")
    assert s["n"] == 0 and s["not_processed"] == 5


def test_aggregate_three_runs_majority():
    r1 = rows({"R01": True, "R03": True})
    r2 = rows({"R01": True})
    r3 = rows({"R03": True, "R05": True})
    agg = RP.aggregate([r1, r2, r3])["notice"]
    assert agg["majority"]["tp"] == 2            # R01 2/3, R03 2/3, R05 1/3
    assert agg["mean"]["precision"] == 1.0


def test_row_results_views():
    plan = RP.build_plan(pairs(), FakeHistory(), run=1, date="20261116", user_id="u")
    a = plan.groups[0].answers
    notices = {a[0]["answer_id"]: {"review_status": None, "review_reason": None},
               a[1]["answer_id"]: {"review_status": "pending", "review_reason": "judge_disagrees_with_rule"}}
    out = RP.row_results(plan, notices, {g.event_key: {"status": "done"} for g in plan.groups})
    first, second = out[0], out[1]
    assert (first["notice"], first["user"], first["judge"]) == (True, True, True)
    assert (second["notice"], second["user"], second["judge"]) == (True, False, False)


def test_cost_estimate_is_small_and_needs_no_llm():
    plan = RP.build_plan(pairs(), FakeHistory(), run=1, date="20261116", user_id="u")
    est = RP.estimate_cost(plan)
    assert est["calls"] == 6 and 0 < est["usd_est"] < 0.03
