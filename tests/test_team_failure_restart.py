"""합동 검토의 팀 실패 알림(`team_review_failed`)에서 멈춘 뒤 프로세스를 끝내고 새 프로세스에서 재개하는 시험.

`tests/test_decision_approval.py`의 재시작 시험과 같은 방식이다: 실제 Postgres(체크포인터와 승인함 표), 단계마다 새 프로세스(`decision_restart_worker.py`),
같은 `thread_id`로 재개. 모델은 가짜이고 키와 네트워크는 쓰지 않는다. Postgres가 없으면 건너뛴다(고르는 순서는 `test_decision_approval.py` 머리말).

확인하는 것: ① 알림(승인함 `team_review_failed` 건)이 재개 때 중복으로 생기지 않는다 ② 이미 끝난 팀을 다시 돌리지 않는다 ③ 최종 상태(쟁점표, 저장, 승인함)가 맞다.
다룬 응답: `retry`, `mark_unreviewed`, 틀린 값(`bad_action`, `approver_missing`, 다른 승인 건 번호), 그리고 알림 뒤 쟁점표 승인과 반려.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from test_decision_approval import pg_admin_url, pg_url  # noqa: F401 - 같은 임시 Postgres를 쓴다(fixture)

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ("security", "infra", "itops", "finance")
NONE = {t: 0 for t in TEAMS}
SHAPES = pytest.mark.parametrize("shape", ["alone", "sub"])


def w(stage, url, tid, shape, *extra, env=None, rc=0):
    """작업 프로세스 하나를 새로 띄운다. `rc`는 기대하는 종료 코드이고 0이 아니면 결과 줄이 없다."""
    base = {k: v for k, v in os.environ.items() if k != "DATABASE_URL" and not k.startswith("PV_TF_")}
    p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests" / "decision_restart_worker.py"), stage, url, tid, shape, *extra],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env={**base, **(env or {})})
    assert p.returncode == rc, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1]) if rc == 0 else None


def resume(url, tid, shape, body, env=None):
    return w("review_resume", url, tid, shape, json.dumps(body), env=env)


def rows(r):
    return [(x["kind"], x["status"], x["resolution"]) for x in r["approvals"]]


def notices(r):
    return [x for x in r["approvals"] if x["kind"] == "team_review_failed"]


def llm_of(r, **n):
    return {**NONE, **n}


@SHAPES
def test_two_failed_teams_mark_unreviewed_after_restart_then_approve(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    a = w("review_start", pg_url, tid, shape, env={"PV_TF_BAD_START": "infra,finance"})
    assert a["pending"]["kind"] == "team_review_failed" and [f["team"] for f in a["pending"]["failed_teams"]] == ["infra", "finance"]
    assert rows(a) == [("team_review_failed", "pending", None)] and a["saved"] is None
    assert a["llm"] == {"security": 1, "infra": 3, "itops": 1, "finance": 3}                 # 처음 한 번씩, 실패한 팀은 시도 상한까지
    b = w("review_read", pg_url, tid, shape)
    assert b["pending"] == a["pending"] and b["approval_ids"] == a["approval_ids"] and rows(b) == rows(a)     # ① 읽기만 해서는 알림이 늘지 않는다
    c = resume(pg_url, tid, shape, {"action": "mark_unreviewed", "decided_by": "admin-1", "comment": "이번엔 넘어간다"})
    assert c["pending"]["kind"] == "issue_table" and [u["team"] for u in c["pending"]["table"]["unreviewed"]] == ["infra", "finance"]
    assert [r["team"] for r in c["pending"]["table"]["rows"]] == ["security", "itops"]
    assert c["llm"] == NONE and c["supervisor"] == 0                                         # ② 아무 팀도 다시 돌지 않았다
    assert rows(c) == [("team_review_failed", "rejected", "mark_unreviewed"), ("issue_table", "pending", None)] and len(notices(c)) == 1   # ①
    assert c["saved"] is None
    d = resume(pg_url, tid, shape, {"approve": True, "comment": "확인", "decided_by": "admin-1"})
    assert d["pending"] is None and d["review_status"] == "approved" and d["llm"] == NONE      # ③
    assert [r["team"] for r in d["saved"]["rows"]] == ["security", "itops"] and [u["team"] for u in d["saved"]["unreviewed"]] == ["infra", "finance"]
    assert all(u["reason"] for u in d["saved"]["unreviewed"]) and d["saved"]["approved_by"] == "admin-1"
    assert rows(d) == [("team_review_failed", "rejected", "mark_unreviewed"), ("issue_table", "approved", None)] and len(notices(d)) == 1


@SHAPES
def test_two_failed_teams_mark_unreviewed_then_reject_saves_nothing(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    w("review_start", pg_url, tid, shape, env={"PV_TF_BAD_START": "infra,finance"})
    resume(pg_url, tid, shape, {"action": "mark_unreviewed", "decided_by": "admin-1"})
    z = resume(pg_url, tid, shape, {"approve": False, "comment": "근거 부족", "decided_by": "admin-1"})
    assert z["pending"] is None and z["review_status"] == "rejected" and z["saved"] is None and z["llm"] == NONE
    assert rows(z) == [("team_review_failed", "rejected", "mark_unreviewed"), ("issue_table", "rejected", None)]
    assert [x["decided_by"] for x in z["approvals"]] == ["admin-1", "admin-1"]


@SHAPES
def test_retry_that_fails_again_after_restart_raises_one_new_notice_and_old_one_is_not_reused(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    a = w("review_start", pg_url, tid, shape)                                                # infra만 실패
    first = a["pending"]["approval_id"]
    d = resume(pg_url, tid, shape, {"action": "retry", "decided_by": "admin-1"}, env={"PV_TF_BAD_RESUME": "infra"})
    second = d["pending"]["approval_id"]
    assert d["pending"]["kind"] == "team_review_failed" and [f["team"] for f in d["pending"]["failed_teams"]] == ["infra"]
    assert second != first and d["approval_ids"] == [first, second] and d["saved"] is None     # 끝난 번호를 다시 쓰지 않고 새 알림 하나
    assert rows(d) == [("team_review_failed", "approved", "retry"), ("team_review_failed", "pending", None)]
    assert d["llm"] == llm_of(d, infra=3) and d["supervisor"] == 0                          # 실패한 팀만 상한까지, 통과한 팀은 그대로
    e = w("review_read", pg_url, tid, shape)
    assert e["pending"] == d["pending"] and rows(e) == rows(d) and e["approval_ids"] == d["approval_ids"]
    stale = resume(pg_url, tid, shape, {"approval_id": first, "action": "mark_unreviewed", "decided_by": "admin-1"})   # 앞 알림의 늦은 결정
    assert stale["pending"] == d["pending"] and rows(stale) == rows(d) and stale["llm"] == NONE and stale["saved"] is None
    f = resume(pg_url, tid, shape, {"approval_id": second, "action": "mark_unreviewed", "decided_by": "admin-1"})
    assert f["pending"]["kind"] == "issue_table" and [u["team"] for u in f["pending"]["table"]["unreviewed"]] == ["infra"] and f["llm"] == NONE
    assert rows(f) == [("team_review_failed", "approved", "retry"), ("team_review_failed", "rejected", "mark_unreviewed"), ("issue_table", "pending", None)]
    g = resume(pg_url, tid, shape, {"approve": True, "decided_by": "admin-1"})
    assert g["review_status"] == "approved" and [r["team"] for r in g["saved"]["rows"]] == ["security", "itops", "finance"]
    assert [u["team"] for u in g["saved"]["unreviewed"]] == ["infra"] and len(notices(g)) == 2 and g["llm"] == NONE


@SHAPES
def test_retry_of_two_teams_after_restart_asks_again_only_about_the_one_still_failing(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    w("review_start", pg_url, tid, shape, env={"PV_TF_BAD_START": "infra,finance"})
    c = resume(pg_url, tid, shape, {"action": "retry", "decided_by": "admin-1"}, env={"PV_TF_BAD_RESUME": "finance"})
    assert c["pending"]["kind"] == "team_review_failed" and [f["team"] for f in c["pending"]["failed_teams"]] == ["finance"]
    assert c["llm"] == llm_of(c, infra=1, finance=3) and c["supervisor"] == 0                # 통과한 보안·IT 운영 팀은 다시 돌지 않았다
    assert rows(c) == [("team_review_failed", "approved", "retry"), ("team_review_failed", "pending", None)]
    d = resume(pg_url, tid, shape, {"action": "retry", "decided_by": "admin-1"})
    assert d["pending"]["kind"] == "issue_table" and d["pending"]["table"]["unreviewed"] == [] and d["llm"] == llm_of(d, finance=1)   # 이번엔 finance 한 팀만
    e = resume(pg_url, tid, shape, {"approve": True, "decided_by": "admin-1"})
    assert [r["team"] for r in e["saved"]["rows"]] == list(TEAMS) and e["saved"]["unreviewed"] == [] and e["llm"] == NONE
    assert rows(e) == [("team_review_failed", "approved", "retry"), ("team_review_failed", "approved", "retry"), ("issue_table", "approved", None)]


@SHAPES
def test_wrong_resume_values_after_restart_change_nothing(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    a = w("review_start", pg_url, tid, shape)
    cases = [
        ({"action": "retry"}, "approver_missing"),                                            # 결정한 사람이 없음
        ({"action": "mark_unreviewed", "decided_by": "  "}, "approver_missing"),
        ({"approve": True, "decided_by": "admin-1"}, "bad_action"),                           # 쟁점표 승인 값을 보낸 경우
        ({"action": "abort", "decided_by": "admin-1"}, "bad_action"),
    ]
    for body, why in cases:
        r = resume(pg_url, tid, shape, body)
        assert r["pending"] == {**a["pending"], "rejected_resume": why}, body
        assert rows(r) == rows(a) and r["approval_ids"] == a["approval_ids"] and r["saved"] is None and r["llm"] == NONE, body
    z = w("review_read", pg_url, tid, shape)
    assert z["pending"] == {**a["pending"], "rejected_resume": cases[-1][1]} and rows(z) == rows(a)
    ok = resume(pg_url, tid, shape, {"action": "mark_unreviewed", "decided_by": "admin-1"})      # 틀린 값 뒤에도 올바른 값은 받는다
    assert ok["pending"]["kind"] == "issue_table" and ok["llm"] == NONE and len(notices(ok)) == 1


@SHAPES
def test_process_killed_while_retrying_continues_without_new_notice_or_rerunning_passed_teams(pg_url, shape):
    tid = f"tf-{uuid.uuid4().hex[:8]}"
    a = w("review_start", pg_url, tid, shape)
    # 서버(`routes._parse_team_action`)는 재개 값에 승인 건 번호를 항상 붙인다. 하위 그래프에서 앞 건의 값이 다음 멈춤에 흘러 들어가는 것을 이 번호가 막는다
    w("review_resume", pg_url, tid, shape, json.dumps({"approval_id": a["pending"]["approval_id"], "action": "retry", "decided_by": "admin-1"}),
      env={"PV_TF_DIE": "infra"}, rc=7)                                                          # 결정을 적은 뒤 다시 도는 중에 프로세스가 죽는다
    r = w("review_read", pg_url, tid, shape)
    assert r["pending"] is None and rows(r) == [("team_review_failed", "approved", "retry")]       # 결정은 남았고 아직 대기 건이 없다
    b = w("review_continue", pg_url, tid, shape)                                                # 새 프로세스: 서버와 같이 재개 값 없이 이어 간다
    assert b["pending"]["kind"] == "issue_table" and b["pending"]["table"]["unreviewed"] == [] and b["supervisor"] == 0
    assert b["llm"] == llm_of(b, infra=1)                                                       # 죽은 팀만 다시, 통과한 팀은 그대로
    assert rows(b) == [("team_review_failed", "approved", "retry"), ("issue_table", "pending", None)] and b["approval_ids"][0] == a["approval_ids"][0]
    again = w("review_read", pg_url, tid, shape)
    assert again["pending"] == b["pending"] and rows(again) == rows(b)
    assert b["pending"]["approval_id"] != a["pending"]["approval_id"] and b["saved"] is None                  # 앞 결정의 값이 새 쟁점표를 반려로 끝내지 않았다
    c = resume(pg_url, tid, shape, {"approval_id": b["pending"]["approval_id"], "approve": True, "decided_by": "admin-1"})
    assert c["review_status"] == "approved" and [r["team"] for r in c["saved"]["rows"]] == list(TEAMS) and c["llm"] == NONE and len(notices(c)) == 1
