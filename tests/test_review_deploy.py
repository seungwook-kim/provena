"""`evals/agent/review_deploy.py` 0원 시험(사전 등록 62.41): 로컬 가짜 HTTP 서버(스텁)로 로그인·CSRF·팀 SSE 읽기·단일 JSON 읽기·행 읽기/반려·판정·상한 종료·fill-cost를 확인한다.
운영 서버와 LLM은 부르지 않는다(키·네트워크·DB 없음).
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from evals.agent import exp_review_v1 as X
from evals.agent import review_deploy as D

DATASET = X.EVALS / "dataset_review_v1_gold_draft.jsonl"
ITEMS = X.load_review_dataset(DATASET)
BY_INPUT = {it["input"]: it for it in ITEMS}
BY_ID = {str(it["id"]): it for it in ITEMS}
PW_B, PW_A = "pw-b-secret-zz", "pw-a-secret-zz"
STATE: dict = {}
SECRET_ISSUE = "ISSUE-TEXT-KEPT-FOR-JUDGING"


def reset(**kw):
    STATE.clear()
    STATE.update({"pending": {}, "rejected": [], "calls": [], "single_flag": 200, "logins": [], **kw})


def gold_rows(it, n=None):
    out = []
    for team, ref, vd in it["_gold"][:n]:
        r = ref.refs[0] if hasattr(ref, "refs") else ref
        out.append({"team": team, "team_label": team, "topic": "t", "issue": SECRET_ISSUE, "chunk_id": uuid.uuid4().hex[:16], "rule_seq": r.rule_seq, "rule_title": "t",
                    "article": " > ".join(r.article), "section_path": "s", "version_date": vd or "2026-01-01", "stance": "condition", "confidence": "medium", "conflict": False})
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _csrf_ok(self):
        c = self._cookie("provena_csrf")
        return bool(c) and self.headers.get("X-CSRF-Token") == c

    def _role(self):
        return {"b-user": "user", "a-user": "admin"}.get(self._cookie("provena_auth") or "")

    def _json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, b'{"ok":true}')
        if self.path == "/auth/csrf":
            return self._send(200, b"{}", extra=[("Set-Cookie", "provena_csrf=tok123; Path=/; Secure")])
        if self.path == "/approvals":
            if self._role() != "admin":
                return self._send(403 if self._role() else 401, b"{}")
            views = [{"approval_id": k, "kind": "issue_table", "issue_table": {"rows": v["rows"], "unreviewed": []}} for k, v in STATE["pending"].items()]
            views.append({"approval_id": "someone-else", "kind": "issue_table", "issue_table": {"rows": [], "unreviewed": []}})
            return self._send(200, json.dumps(views).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.path == "/auth/login":
            if not self._csrf_ok():
                return self._send(403, b"{}")
            b = self._json()
            STATE["logins"].append(b.get("login_id"))
            if (b.get("login_id"), b.get("password")) not in {("b-user", PW_B), ("a-user", PW_A)}:
                return self._send(401, b"{}")
            return self._send(200, json.dumps({"user_id": b["login_id"]}).encode(), extra=[("Set-Cookie", f"provena_auth={b['login_id']}; Path=/; HttpOnly")])
        if self.path == "/chat":
            if not self._csrf_ok():
                return self._send(403, b"{}")
            if self._role() is None:
                return self._send(401, b"{}")
            body = self._json()
            it = BY_INPUT[body["message"]]
            STATE["calls"].append(("team", it["id"], self.headers.get("X-Request-ID")))
            ev = []

            def e(t, data):
                ev.append(f"event: {t}\ndata: {json.dumps({'type': t, 'thread_id': 't-x', 'data': data}, ensure_ascii=False)}\n\n")

            if it["kind"] == "clarify":
                e("token", {"text": "검토에 필요한 값이 요청에 없습니다: 금액."})
                e("done", {"answer_id": None, "kind": "clarify", "usage": {"cost_usd": 0.0002, "calls": 1}, "refuse_stage": "review"})
            elif it["id"] == 3:
                e("token", {"text": "정책 답입니다."})
                e("done", {"answer_id": "a", "kind": "answer", "usage": {"cost_usd": 0.001, "calls": 3}})
            elif it["id"] == 7:
                e("error", {"code": "internal_error", "message": "x", "request_id": "r"})
            else:
                aid = str(uuid.uuid4())
                STATE["pending"][aid] = {"rows": gold_rows(it)}
                e("approval_request", {"approval_id": aid, "kind": "issue_table", "summary": "합동 검토 쟁점표"})
            payload = "".join(ev).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/admin/eval/review":
            if self._role() != "admin" or not self._csrf_ok():
                return self._send(403, b"{}")
            if STATE["single_flag"] != 200:
                return self._send(STATE["single_flag"], b"{}")
            body = self._json()
            it = BY_INPUT[body["message"]]
            search = body["search"]
            STATE["calls"].append((search, it["id"], self.headers.get("X-Request-ID")))
            if it["kind"] == "clarify":
                data = {"status": "clarify", "issue_rows": [], "unreviewed": [], "clarify_question": "금액이 없습니다.", "retrieved": {}, "llm_calls": 1}
            else:
                data = {"status": "pending_approval", "issue_rows": gold_rows(it, None if search == "same" else 1), "unreviewed": [], "clarify_question": None,
                        "retrieved": {"all": ["c1"]} if search == "undivided" else {t: ["c1"] for t in ("security", "infra", "itops", "finance")}, "llm_calls": 1}
            data.update(search=search, usage={"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.004, "calls": 1}, latency_ms=10.0, revision="rev-test", request_id="x")
            return self._send(200, json.dumps(data, ensure_ascii=False).encode())
        if self.path.startswith("/approvals/"):
            if self._role() != "admin" or not self._csrf_ok():
                return self._send(403, b"{}")
            aid = self.path.rsplit("/", 1)[1]
            if aid not in STATE["pending"] or self._json().get("approve") is not False:
                return self._send(404, b"{}")
            STATE["pending"].pop(aid)
            STATE["rejected"].append(aid)
            return self._send(200, b'{"status":"rejected"}')
        self._send(404, b"{}")


@pytest.fixture(scope="module")
def base_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _state():
    reset()


def run(base_url, argv, *, admin=True, monkeypatch=None):
    env = {"DEPLOY_LATENCY_LOGIN": "b-user", "DEPLOY_LATENCY_PASSWORD": PW_B, "DEPLOY_LATENCY_BASE_URL": base_url}
    if admin:
        env.update(DEPLOY_CHECK_A_LOGIN="a-user", DEPLOY_CHECK_A_PASSWORD=PW_A)
    for k in ("DEPLOY_CHECK_A_LOGIN", "DEPLOY_CHECK_A_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = D.main(argv)
    return code, buf.getvalue(), err.getvalue()


def rows_of(out: Path, arm: str) -> list[dict]:
    return D.load_rows(out / D.ARM_DIR[arm] / "rows.jsonl")


# ============================ 전체 실행 ============================

def test_full_run_writes_three_arms_alternates_the_order_and_never_leaks(base_url, tmp_path, monkeypatch):
    out = tmp_path / "full"
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--repeats", "3", "--revision", "rev-test", "--commit", "abc1234", "--out", str(out), "--max-cost", "1.0"], monkeypatch=monkeypatch)
    assert code == 0, se
    team, same, und = (rows_of(out, a) for a in D.ARMS)
    assert len(team) == len(same) == len(und) == 30
    assert sorted({r["path"] for r in team}) == ["error", "other_route", "review_clarify", "review_table"]
    assert {r["path"] for r in same} == {"review_table", "review_clarify"} == {r["path"] for r in und}
    # 호출 순서: 첫 문항은 팀 -> same -> undivided, 다음 문항은 반대
    first = [c[0] for c in STATE["calls"][:6]]
    assert first == ["team", "same", "undivided", "undivided", "same", "team"]
    assert len({c[2] for c in STATE["calls"]}) == 90 and all(c[2].startswith("rvfair-") for c in STATE["calls"])   # 요청마다 고유 X-Request-ID
    # 팀 쟁점표 행은 GET /approvals로 읽고 시험 건은 반려, 남의 건은 그대로
    tbl = [r for r in team if r["path"] == "review_table"]
    assert tbl and all(r["rows_source"] == "GET /approvals" and r["rejected"] is True for r in tbl) and not STATE["pending"] and len(STATE["rejected"]) == len(tbl)
    # 단일 행은 응답에서 읽고 retrieved·쟁점 문장을 남긴다
    assert all(r["rows_source"] == "response" and r["retrieved"] is not None for r in same + und if r["path"] == "review_table")
    assert any(x["issue"] == SECRET_ISSUE for r in tbl + same for x in (r["issue_rows"] or []))
    blob = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
    assert not any(it["input"][:20] in blob for it in ITEMS)                                  # 질문 원문 없음
    assert PW_A not in blob + so + se and PW_B not in blob + so + se and "b-user" not in blob and "a-user" not in blob
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["meta"]["revision"] == "rev-test" and not s["meta"]["partial"] and (out / "summary.md").is_file()
    assert s["comparison"]["pairs_excluded"] == {"team_not_routed": 6, "total_team_runs": 30}   # 3번(정책 답)과 7번(오류) x 3회


def test_summary_separates_routing_from_the_comparison(base_url, tmp_path, monkeypatch):
    out = tmp_path / "cmp"
    assert run(base_url, ["--dataset", str(DATASET), "--repeats", "3", "--out", str(out)], monkeypatch=monkeypatch)[0] == 0
    c = json.loads((out / "summary.json").read_text(encoding="utf-8"))["comparison"]
    # 전체 30런: 팀이 3번·7번을 못 찾아(분류 누락과 오류) same이 낫게 보인다
    assert c["all"]["team_vs_same"]["diff"] < -D.MARGIN and c["all"]["team_vs_same"]["text"].startswith("단일이 낫다")
    # 짝을 맞춘 런(팀이 합동 검토 경로에 닿은 쌍): same과 같고, 나누지 않은 검색(단일 문항당 쟁점 1개)보다 낫다
    p = c["paired"]
    assert p["team_vs_same"]["diff"] == 0 and p["team_vs_same"]["text"].startswith("차이 없음") and p["team_vs_same"]["role"] == "main"
    assert p["team_vs_undivided"]["diff"] > D.MARGIN and p["team_vs_undivided"]["text"].startswith("팀이 낫다") and p["team_vs_undivided"]["role"] == "aux"
    assert all(v is not None and v > 0 for v in p["team_vs_undivided"]["per_repeat"].values())
    assert p["n_pairs"] == 3 * 8                                                              # 10문항 중 3번·7번 제외, x 3회
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "주 기준선은 same" in md and "주 판정: 방식별 전체 런" in md and "보조: 짝을 맞춘 런" in md and "비용 배수" in md


def test_cost_ratio_needs_team_cost_from_the_server_log_then_is_filled(base_url, tmp_path, monkeypatch):
    out = tmp_path / "cost"
    assert run(base_url, ["--dataset", str(DATASET), "--repeats", "1", "--out", str(out)], monkeypatch=monkeypatch)[0] == 0
    c0 = json.loads((out / "summary.json").read_text(encoding="utf-8"))["comparison"]["paired"]
    assert c0["cost_ratio_team_over_same"] is None or c0["arms"]["team"]["cost"]["mean_usd"]   # 쟁점표 런은 응답에 비용이 없다
    team = rows_of(out, "team")
    tab = [r for r in team if r["path"] == "review_table"]
    log = "\n".join(f"2026-11-11 llm id={r['request_id']} route=/chat model=m input_tokens=9 output_tokens=2 calls=9 cost_usd=0.008000 ms=1.0" for r in tab)
    lf = tmp_path / "gcloud.txt"
    lf.write_text(log, encoding="utf-8")
    code, so, se = run(base_url, ["fill-cost", "--out", str(out), "--log-file", str(lf), "--dataset", str(DATASET)], monkeypatch=monkeypatch)
    assert code == 0 and f"{len(tab)}/{len(team)}" in so
    c1 = json.loads((out / "summary.json").read_text(encoding="utf-8"))["comparison"]["paired"]
    assert c1["arms"]["team"]["cost"]["runs_with_cost"] >= len(tab)
    assert c1["cost_ratio_team_over_same"] is not None and 1.5 < c1["cost_ratio_team_over_same"] < 2.5   # 팀 약 0.008, 단일 0.004
    assert abs(c1["cost_ratio_team_over_same"] - c1["cost_ratio_team_over_undivided"]) < 1e-9


# ============================ 멈추는 경우 ============================

def test_flag_off_404_stops_after_the_first_single_call_with_exit_2(base_url, tmp_path, monkeypatch):
    reset(single_flag=404)
    out = tmp_path / "off"
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--repeats", "3", "--out", str(out)], monkeypatch=monkeypatch)
    assert code == 2 and "EVAL_REVIEW_SINGLE" in se
    assert [c[0] for c in STATE["calls"]] == ["team"]                                         # 팀 한 건 뒤 첫 단일 호출이 404라 더 보내지 않는다
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["meta"]["partial"] is True


def test_daily_limit_429_stops_with_exit_2(base_url, tmp_path, monkeypatch):
    reset(single_flag=429)
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--out", str(tmp_path / "limit")], monkeypatch=monkeypatch)
    assert code == 2 and "429" in se and len(STATE["calls"]) == 1


def test_budget_stops_before_sending_the_next_item_with_exit_3(base_url, tmp_path, monkeypatch):
    out = tmp_path / "budget"
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--repeats", "3", "--out", str(out), "--max-cost", "0.05"], monkeypatch=monkeypatch)
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    n = sum(len(rows_of(out, a)) for a in D.ARMS)
    assert code == 3 and s["meta"]["partial"] and 0 < n < 90 and n == len(STATE["calls"]) and n % 3 == 0   # 문항 단위로 멈춘다


def test_admin_account_is_required_before_any_question_is_sent(base_url, tmp_path, monkeypatch):
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--out", str(tmp_path / "noadmin")], admin=False, monkeypatch=monkeypatch)
    assert code == 2 and "DEPLOY_CHECK_A_LOGIN" in se and STATE["calls"] == [] and STATE["logins"] == []


def test_old_results_folder_is_refused(base_url, tmp_path, monkeypatch):
    out = tmp_path / "again"
    assert run(base_url, ["--dataset", str(DATASET), "--repeats", "1", "--limit", "1", "--out", str(out)], monkeypatch=monkeypatch)[0] == 0
    calls = len(STATE["calls"])
    code, so, se = run(base_url, ["--dataset", str(DATASET), "--out", str(out)], monkeypatch=monkeypatch)
    assert code == 2 and len(STATE["calls"]) == calls


# ============================ 판정 규칙(네트워크 없음) ============================

def test_verdict_needs_the_margin_and_the_same_direction_in_every_repeat():
    team = {1: 0.40, 2: 0.45, 3: 0.50}
    better = {1: 0.60, 2: 0.65, 3: 0.70}
    v = D.verdict(team, better, 0.45, 0.65)
    assert v["diff"] == 0.2 and v["text"].startswith("팀이 낫다")
    mixed = {1: 0.60, 2: 0.40, 3: 0.70}      # 2회차는 팀이 못함
    assert D.verdict(team, mixed, 0.45, 0.5666667)["text"].startswith("차이 없음")
    assert D.verdict(team, {1: 0.45, 2: 0.50, 3: 0.55}, 0.45, 0.50)["text"].startswith("차이 없음")           # 0.05 차이
    assert D.verdict(team, {1: 0.45, 2: 0.50, 3: 0.55}, 0.45, 0.55)["text"].startswith("차이 없음") is False    # 정확히 0.10은 이긴 것
    worse = {1: 0.20, 2: 0.25, 3: 0.30}
    assert D.verdict(team, worse, 0.45, 0.25)["text"].startswith("단일이 낫다")
    assert D.verdict(team, worse, None, 0.25)["text"].startswith("미확인") and D.verdict(team, worse, 0.45, None)["diff"] is None


def test_unreadable_team_rows_make_the_metric_unknown_not_zero():
    it = BY_ID["1"]
    row = {"arm": "team", "id": 1, "repeat": 1, "kind": "full", "path": "review_table", "issue_rows": None, "unreviewed": None, "latency_s": 1.0}
    assert D.rows_unknown([row]) == 1 and D._missed([row], BY_ID) is None
    full = {**row, "issue_rows": gold_rows(it)}
    assert D._missed([full], BY_ID) == 0.0


def test_arm_order_alternates():
    assert D.arm_order(0) == ["team", "same", "undivided"] and D.arm_order(1) == ["undivided", "same", "team"] and D.arm_order(2) == D.arm_order(0)


def test_the_tool_never_calls_the_team_path_through_the_eval_endpoint_and_sends_only_known_fields():
    import inspect

    src = inspect.getsource(D.post_single)
    assert '"search": search' in src and "/admin/eval/review" in src and "thread_id" not in src
    assert "/chat" in inspect.getsource(D.post_chat) and "/admin/eval" not in inspect.getsource(D.post_chat)
