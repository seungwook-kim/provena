"""재시작 뒤 승인 재개 확인 도구(`evals/safety/deploy_restart_resume_check.py`) 시험. 가짜 HTTP 서버만 쓰고 네트워크·LLM은 쓰지 않는다."""
from __future__ import annotations

import json
from contextlib import contextmanager

from evals.safety import deploy_restart_resume_check as rr


class Resp:
    def __init__(self, code: int, body=None, lines: list[str] | None = None):
        self.status_code = code
        self._body = body
        self._lines = lines or []
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def read(self):
        return b""

    def iter_lines(self):
        return iter(self._lines)


def sse(event: str, data: dict) -> list[str]:
    return [f"event: {event}", "data: " + json.dumps({"type": event, "thread_id": "t-x", "data": data}), ""]


class Server:
    """승인함과 대화를 흉내 낸다. `chat_script`는 /chat을 부를 때마다 차례로 쓴다: issue | clarify | team_failed."""

    def __init__(self, chat_script, *, approved_categories=(), flip_ok=False, mutate_on_repeat=False, lose_pending=()):
        self.chat_script = list(chat_script)
        self.pending: dict[str, dict] = {}
        self.decided: dict[str, str] = {}
        self.tables: list[dict] = [{"table_id": f"tb-{i}", "category": c, "status": "approved", "cells": [{}] * 3} for i, c in enumerate(approved_categories)]
        self.answers: dict[str, list[str]] = {}
        self.n = 0
        self.flip_ok, self.mutate_on_repeat, self.lose_pending = flip_ok, mutate_on_repeat, set(lose_pending)
        self.convert_calls: list[str] = []

    def new_id(self, prefix):
        self.n += 1
        return f"{prefix}-{self.n:04d}secret"

    def view(self, rec):
        v = {"approval_id": rec["id"], "kind": rec["kind"], "summary": "s", "save_failed": False}
        if rec["kind"] == rr.KIND_ISSUE:
            v["issue_table"] = {"rows": [{}] * rec["rows"]}
        else:
            v["draft"] = [{}] * rec["rows"]
            v["comparison"] = {}
        return v

    def request(self, role, method, path, body):
        if path == "/approvals" and method == "GET":
            if role != "A":
                return Resp(403, {"error": {"code": "forbidden"}})
            return Resp(200, [self.view(r) for i, r in self.pending.items() if i not in self.lose_pending and i not in self.decided])
        if path == "/decision-tables" and method == "GET":
            return Resp(200, self.tables)
        if path == "/decision-tables/convert":
            if role != "A":
                return Resp(403, {"error": {"code": "forbidden"}})
            cat = body["category"]
            self.convert_calls.append(cat)
            if any(t["category"] == cat for t in self.tables):
                return Resp(409, {"error": {"code": "conflict"}})
            aid = self.new_id("ap")
            self.pending[aid] = {"id": aid, "kind": rr.KIND_DECISION, "rows": 4, "category": cat, "thread": None}
            return Resp(201, self.view(self.pending[aid]))
        if path.startswith("/approvals/") and method == "POST":
            aid = path.rsplit("/", 1)[1]
            if role != "A":
                return Resp(403, {"error": {"code": "forbidden"}})
            rec = self.pending.get(aid)
            if rec is None:
                return Resp(404, {"error": {"code": "not_found"}})
            if "action" in body:   # 팀 실패 알림
                nid = self.new_id("ap")
                self.pending.pop(aid)
                self.pending[nid] = {"id": nid, "kind": rr.KIND_ISSUE, "rows": 5, "thread": rec["thread"]}
                return Resp(200, {"approval_id": aid, "status": "approved", "next_approval": {"approval_id": nid, "kind": rr.KIND_ISSUE}})
            status = "approved" if body["approve"] else "rejected"
            if aid in self.decided:
                if self.decided[aid] != status and not self.flip_ok:
                    return Resp(409, {"error": {"code": "already_decided"}})
                if self.mutate_on_repeat and rec["kind"] == rr.KIND_ISSUE:   # 같은 건을 다시 재개해 답이 덧붙는 결함 흉내
                    self.answers[rec["thread"]].append("again")
                return Resp(200, {"approval_id": aid, "status": self.decided[aid], "table_id": None})
            self.decided[aid] = status
            table_id = None
            if rec["kind"] == rr.KIND_DECISION and status == "approved":
                table_id = self.new_id("tb")
                self.tables.append({"table_id": table_id, "category": rec["category"], "status": "approved", "cells": [{}] * rec["rows"]})
            if rec["kind"] == rr.KIND_ISSUE:
                text = f"승인되어 쟁점표를 저장했습니다. 합동 검토 쟁점표: 쟁점 {rec['rows']}건" if status == "approved" else "반려되어 쟁점표를 저장하지 않았습니다. 사유: x"
                self.answers[rec["thread"]] = [text]   # 승인을 기다리던 한 턴의 답이 채워진다
                table_id = self.new_id("tb") if status == "approved" else None
            return Resp(200, {"approval_id": aid, "status": status, "table_id": table_id})
        if path.startswith("/threads/"):
            tid = path.rsplit("/", 1)[1]
            msgs = [{"role": "user", "text": "q"}] + [{"role": "assistant", "text": t} for t in self.answers.get(tid, [])]
            return Resp(200, {"messages": msgs})
        return Resp(404, {"error": {"code": "not_found"}})

    def chat(self, role, body):
        tid = body["thread_id"]
        if any(r.get("thread") == tid for r in self.pending.values()):
            return Resp(409, {"error": {"code": "approval_pending"}})
        step = self.chat_script.pop(0)
        if step == "clarify":
            return Resp(200, lines=sse("done", {"kind": "clarify", "usage": {"cost_usd": 0.0003}}))
        aid = self.new_id("ap")
        kind = rr.KIND_ISSUE if step == "issue" else rr.KIND_TEAM_FAILED
        self.pending[aid] = {"id": aid, "kind": kind, "rows": 7, "thread": tid}
        self.answers[tid] = [""]   # 대기 중인 턴은 빈 답으로 보인다
        return Resp(200, lines=sse("approval_request", {"approval_id": aid, "kind": kind, "summary": "s"}))


class Client:
    def __init__(self, server: Server, role: str):
        self.server, self.role = server, role

    def get(self, path, headers=None, params=None):
        return self.server.request(self.role, "GET", path, None)

    def post(self, path, json=None, headers=None):
        return self.server.request(self.role, "POST", path, json)

    @contextmanager
    def stream(self, method, path, json=None, headers=None):
        yield self.server.chat(self.role, json)

    def close(self):
        pass


def clients(server):
    return Client(server, "A"), Client(server, "B")


def prepared(server, **kw):
    a, b = clients(server)
    state, code = rr.prepare(a, b, revision="rev-old", base_url="https://x.example", **kw)
    return state, code


def test_prepare_makes_three_items_and_retries_after_clarify():
    server = Server(["clarify", "issue", "clarify", "issue"])
    state, code = prepared(server)
    assert code == 0 and state["complete"]
    assert [(i["label"], i["kind"], i["decision"]) for i in state["items"]] == [("a", "issue_table", "approve"), ("b", "issue_table", "reject"), ("c", "decision_table", "approve")]
    assert [x["amount"] for x in state["attempts"] if x["kind"] == "chat"] == list(rr.AMOUNTS[:4])
    assert all(i["pending_rows"] > 0 for i in state["items"])
    assert server.convert_calls == ["Benefit changes"]   # 금액 질문에 쓰이는 업무 종류를 피한다
    assert state["items"][0]["thread_id"] != state["items"][1]["thread_id"]


def test_prepare_skips_already_approved_category():
    server = Server(["issue", "issue"], approved_categories=("Benefit changes",))
    state, code = prepared(server)
    assert code == 0
    assert server.convert_calls == ["Transfer of funds among GitLab entities"]


def test_prepare_incomplete_when_always_clarify():
    server = Server(["clarify"] * 5)
    state, code = prepared(server)
    assert code == 1 and not state["complete"]
    assert [i["label"] for i in state["items"]] == ["c"]
    assert len([x for x in state["attempts"] if x["kind"] == "chat"]) == rr.MAX_JOINT_ATTEMPTS


def test_prepare_resolves_team_failure_into_issue_item():
    server = Server(["team_failed", "issue"])
    state, code = prepared(server)
    assert code == 0
    assert state["attempts"][0]["resolved_team_failure"] is True
    assert not any(r["kind"] == rr.KIND_TEAM_FAILED for r in server.pending.values())


def run_resume(server, state, tmp_path):
    a, b = clients(server)
    out = tmp_path / "restart_resume.json"
    evidence, code = rr.resume(a, b, state, revision_after="rev-new", commit="abc1234", out_path=str(out))
    return evidence, code, out


def test_resume_happy_path_and_evidence_has_no_identifiers(tmp_path):
    server = Server(["issue", "issue"])
    state, _ = prepared(server)
    evidence, code, out = run_resume(server, state, tmp_path)
    assert code == 0 and evidence["summary"] == {"items_expected": 3, "items_passed": 3, "all_passed": True}
    by = {i["label"]: i for i in evidence["items"]}
    assert by["a"]["decision_status"] == "approved" and by["a"]["saved_rows"] == 7 and by["a"]["new_question_while_pending_http"] == 409
    assert by["b"]["decision_status"] == "rejected" and by["b"]["saved_rows"] == 0
    assert by["c"]["saved_rows"] == 4 and by["c"]["approved_tables_of_category_before_after"] == [0, 1]
    assert all(i["repeat_same_http"] == 200 and i["repeat_flip_http"] == 409 and i["non_admin_decide_http"] == 403 for i in by.values())
    text = out.read_text(encoding="utf-8")
    for it in state["items"]:
        assert it["approval_id"] not in text
        if it["thread_id"]:
            assert it["thread_id"] not in text
    assert "secret" not in text and "user_id" not in text and "login" not in text.casefold()
    assert evidence["revision_before_restart"] == "rev-old" and evidence["revision_after_restart"] == "rev-new"
    assert evidence["resume_started_at_utc"].endswith("+00:00")


def test_resume_twice_keeps_first_result(tmp_path):
    server = Server(["issue", "issue"])
    state, _ = prepared(server)
    evidence1, _, out = run_resume(server, state, tmp_path)
    first_text = out.read_text(encoding="utf-8")
    # 같은 --out 으로 한 번 더 실행해도 첫 결과는 그대로 남고 새 파일(_2)에 쓴다
    a, b = clients(server)
    evidence2, _ = rr.resume(a, b, state, revision_after="rev-new", commit="abc1234", out_path=str(out))
    assert out.read_text(encoding="utf-8") == first_text
    second = tmp_path / "restart_resume_2.json"
    assert second.exists() and evidence2["_written_to"] == str(second)
    a, b = clients(server)
    evidence3, _ = rr.resume(a, b, state, revision_after="rev-new", commit="abc1234", out_path=str(out))
    assert evidence3["_written_to"] == str(tmp_path / "restart_resume_3.json")
    assert out.read_text(encoding="utf-8") == first_text
    assert "_written_to" not in first_text and evidence1["_written_to"] == str(out)


def test_write_unique_never_overwrites(tmp_path):
    target = tmp_path / "sub" / "x.json"
    paths = [rr.write_unique(str(target), f"v{i}") for i in range(3)]
    assert [p.name for p in paths] == ["x.json", "x_2.json", "x_3.json"]
    assert [p.read_text(encoding="utf-8") for p in paths] == ["v0", "v1", "v2"]


def test_resume_fails_when_decision_can_be_flipped(tmp_path):
    server = Server(["issue", "issue"], flip_ok=True)
    state, _ = prepared(server)
    evidence, code, _ = run_resume(server, state, tmp_path)
    assert code == 1
    assert all(i["checks"]["R7"] is False for i in evidence["items"])


def test_resume_fails_when_repeat_changes_the_result(tmp_path):
    server = Server(["issue", "issue"], mutate_on_repeat=True)
    state, _ = prepared(server)
    evidence, code, _ = run_resume(server, state, tmp_path)
    by = {i["label"]: i for i in evidence["items"]}
    assert code == 1 and by["a"]["checks"]["R6"] is True and by["a"]["checks"]["R8"] is False
    assert by["a"]["answers_before_after_repeat"] == [1, 2]


def test_resume_reports_lost_pending_and_continues(tmp_path):
    server = Server(["issue", "issue"])
    state, _ = prepared(server)
    lost = state["items"][0]["approval_id"]
    server.lose_pending.add(lost)
    evidence, code, _ = run_resume(server, state, tmp_path)
    by = {i["label"]: i for i in evidence["items"]}
    assert code == 1 and by["a"]["checks"]["R1"] is False and by["a"]["passed"] is False
    assert by["b"]["passed"] and by["c"]["passed"]


def test_main_refuses_same_revision(tmp_path, monkeypatch):
    state_file = tmp_path / "s.json"
    state_file.write_text(json.dumps({"revision_before": "rev-old", "items": []}), encoding="utf-8")
    for n in rr.ENV_REQUIRED:
        monkeypatch.setenv(n, "x")
    code = rr.main(["resume", "--revision", "rev-old", "--commit", "abc", "--state", str(state_file), "--out", str(tmp_path / "o.json")])
    assert code == 2


def test_main_prepare_refuses_existing_state(tmp_path, monkeypatch):
    state_file = tmp_path / "s.json"
    state_file.write_text("{}", encoding="utf-8")
    for n in rr.ENV_REQUIRED:
        monkeypatch.setenv(n, "x")
    assert rr.main(["prepare", "--revision", "r", "--state", str(state_file)]) == 2
