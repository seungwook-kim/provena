"""평가용 합동 검토 단일 모드 `POST /admin/eval/review` 시험 (결정 0104, 사전 등록 62.41). 가짜 모델·가짜 검색기·메모리 저장소만 쓴다(키·네트워크·DB 없음).

확인하는 것: 꺼짐이면 404(권한보다 먼저, 모델·검색기 안 부름), 켜짐이어도 인증·관리자·CSRF가 없으면 거절, `same`이 팀과 같은 검색을 하는지,
`undivided`가 검색 한 번(k 40, 팀 절 없음)인지, 저장·승인함·대화 목록에 아무것도 쓰지 않는지, 하루 상한, 로그에 요청 문장이 없는지, 서비스 경로가 이 코드를 부르지 않는지.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from api_test_support import Env
from langgraph.checkpoint.memory import InMemorySaver
from qgraph_fakes import ScriptedLLM, j
from team_review_fakes import CORPUS, FIN, REQUEST, SEC, TEAM_ORG, Retriever, chunk_ids, review_llm

from backend.api import eval_review as E
from backend.graph.departments import review as R
from backend.graph.departments import single_review as SR
from backend.graph.departments import teams as T
from backend.graph.departments.review import build_review_graph
from backend.graph.departments.store import InMemoryIssueTableStore
from backend.services.cost import CostCapExceeded

ROOT = Path(__file__).resolve().parents[1]
URL = "/admin/eval/review"
AS_OF = "2026-11-05"
ORDER = ("security", "infra", "itops", "finance")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.delenv(E.FLAG_ENV, raising=False)
    monkeypatch.delenv(E.MAX_PER_DAY_ENV, raising=False)
    monkeypatch.setattr("backend.graph.departments.single_review.R.TEAM_RETRY_WAIT_SECONDS", 0)
    E.DAILY.reset()
    yield
    E.DAILY.reset()


def single_handler(user: str) -> str:
    """같은 자료(`same`)면 관점마다 첫 chunk_id를, 나누지 않은 자료면 자료 목록을 돌아가며 근거로 쓴다."""
    out = []
    blocks = re.findall(r"team=(\w+)\)\n(.*?)(?=\n\n## |\Z)", user, re.S)
    if blocks:
        for tid, body in blocks:
            ids = chunk_ids(body)
            if ids:
                out.append({"team": tid, "topic": f"topic-{tid}", "issue": f"{tid} 합성 쟁점", "chunk_id": ids[0], "stance": "condition", "confidence": "medium"})
    else:
        ids = chunk_ids(user)
        out = [{"team": tid, "topic": f"topic-{tid}", "issue": f"{tid} 합성 쟁점", "chunk_id": ids[i % len(ids)], "stance": "condition", "confidence": "medium"}
               for i, tid in enumerate(ORDER) if ids]
    return j(missing=[], issues=out)


class Fakes:
    def __init__(self, handler=single_handler):
        self.llm = ScriptedLLM({"single": handler})
        self.retriever = Retriever()
        self.wide = Retriever()


def open_env(monkeypatch, *, on="1", fakes: Fakes | None = None):
    if on is not None:
        monkeypatch.setenv(E.FLAG_ENV, on)
    fakes = fakes or Fakes()
    env = Env(monkeypatch)
    env.app.state.eval_review_llm, env.app.state.eval_review_retriever, env.app.state.eval_review_wide_retriever = fakes.llm, fakes.retriever, fakes.wide
    return env, fakes


def body(**kw):
    return {"message": REQUEST, "as_of": AS_OF, "search": "same", **kw}


# ============================ 꺼짐, 권한, CSRF ============================

@pytest.mark.parametrize("flag", [None, "", "0", "true", "yes"])
def test_off_is_404_before_any_permission_check_and_nothing_is_called(monkeypatch, flag, caplog):
    env, fakes = open_env(monkeypatch, on=flag)
    with env, caplog.at_level(logging.WARNING, logger="backend.api.eval_review"):
        for who, csrf in ((env.admin, True), (env.alice, True), (None, False)):   # 관리자여도, 일반 사용자여도, 로그인 없이도 존재를 드러내지 않는다
            r = env.client(who, csrf=csrf).post(URL, json=body())
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert fakes.llm.calls == [] and fakes.retriever.calls == [] and fakes.wide.calls == []
    assert [m for m in caplog.messages if "eval_review_single denied reason=flag_off status=404" in m]   # 거절도 한 줄 남긴다


def test_on_requires_login_admin_role_and_csrf(monkeypatch, caplog):
    env, fakes = open_env(monkeypatch)
    with env, caplog.at_level(logging.WARNING, logger="backend.api.eval_review"):
        assert env.client(None, csrf=False).post(URL, json=body()).status_code == 401           # 로그인 없음
        r = env.client(env.alice).post(URL, json=body())                                       # 일반 사용자
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
        r = env.client(env.admin, csrf=False).post(URL, json=body())                           # CSRF 없음
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
        assert fakes.llm.calls == [] and fakes.retriever.calls == []                           # 거절된 요청은 모델·검색기를 부르지 않는다
        assert E.DAILY._n == 0                                                                  # 상한 횟수도 쓰지 않는다
        r = env.client(env.admin).post(URL, json=body())
        assert r.status_code == 200, r.text
    reasons = [m for m in caplog.messages if m.startswith("eval_review_single denied")]
    assert len(reasons) == 3 and any("reason=not_admin" in m for m in reasons) and any("reason=csrf" in m for m in reasons)


def test_a_second_user_session_cannot_use_a_non_admin_token_for_admin_even_with_csrf(monkeypatch):
    env, fakes = open_env(monkeypatch)
    with env:
        c = env.client(env.alice)
        assert c.post(URL, json=body()).status_code == 403 and fakes.llm.calls == []


def test_unknown_fields_and_bad_values_are_422(monkeypatch):
    env, fakes = open_env(monkeypatch)
    with env:
        c = env.client(env.admin)
        for bad in ({"user_id": "x"}, {"search": "team"}, {"as_of": "2026/11/05"}, {"message": ""}, {"message": "x" * 4001}, {"thread_id": "t1"}):
            assert c.post(URL, json=body(**bad)).status_code == 422, bad
        assert fakes.llm.calls == []


# ============================ 검색: same은 팀과 같고 undivided는 한 번 ============================

def team_calls(llm) -> list[tuple]:
    r = Retriever()
    g = build_review_graph(r, InMemorySaver(), llm=llm, store=InMemoryIssueTableStore())
    g.invoke({"question": REQUEST, "user_id": "u1", "thread_id": "t1", "as_of": AS_OF}, {"configurable": {"thread_id": "t1"}})
    return sorted((q.org, q.query, tuple(q.sub_queries or ()), q.k, q.as_of) for q in r.calls)


def test_same_searches_exactly_like_the_team_graph_and_sends_one_model_call(monkeypatch):
    env, fakes = open_env(monkeypatch)
    with env:
        r = env.client(env.admin).post(URL, json=body(search="same"))
    assert r.status_code == 200, r.text
    got = sorted((q.org, q.query, tuple(q.sub_queries or ()), q.k, q.as_of) for q in fakes.retriever.calls)
    assert got == team_calls(review_llm()) and len(got) == 4 and fakes.wide.calls == []   # 같은 org 4개, 같은 query·sub_queries·k·기준일
    assert all(c[3] == R.SEARCH_K == 10 and len(c[2]) == 2 for c in got)
    assert [t for t, _ in fakes.llm.calls] == ["single"]
    data = r.json()
    assert data["status"] == "pending_approval" and data["search"] == "same"
    assert [x["team"] for x in data["issue_rows"]] == list(ORDER) and all(x["issue"] for x in data["issue_rows"])   # 쟁점 문장 포함
    assert set(data["retrieved"]) == set(ORDER) and all(data["retrieved"][t] for t in ORDER)


def test_undivided_searches_once_over_the_whole_corpus_with_the_same_total_and_accepts_other_teams_chunks(monkeypatch):
    env, fakes = open_env(monkeypatch)
    with env:
        r = env.client(env.admin).post(URL, json=body(search="undivided"))
    assert r.status_code == 200, r.text
    (q,) = fakes.wide.calls
    assert fakes.retriever.calls == [] and q.org is None and q.query == REQUEST and q.sub_queries is None and q.as_of == AS_OF
    assert q.k == SR.UNDIVIDED_K == R.SEARCH_K * len(T.TEAMS) == 40
    data = r.json()
    teams = {x["team"] for x in data["issue_rows"]}
    assert teams == set(ORDER)                                                               # 모델이 쟁점마다 팀을 골랐다
    orgs = {x["team"]: next(c.org for c in CORPUS if c.chunk_id == x["chunk_id"]) for x in data["issue_rows"]}
    assert any(orgs[t] != TEAM_ORG[t] for t in orgs)                                         # 다른 팀 절의 청크를 인용한 쟁점도 행이 된다
    assert list(data["retrieved"]) == ["all"] and len(data["retrieved"]["all"]) == len([c for c in CORPUS if c.version_date <= AS_OF])
    user_text = fakes.llm.calls[0][1]
    assert "## 핸드북 자료" in user_text and "team=" not in user_text                       # 관점 구분 없이 자료 한 묶음


def test_undivided_drops_chunk_ids_that_are_not_in_the_materials(monkeypatch):
    def handler(user: str) -> str:
        ids = chunk_ids(user)
        return j(missing=[], issues=[{"team": "security", "topic": "a", "issue": "자료에 있는 근거", "chunk_id": ids[0], "stance": "condition", "confidence": "high"},
                                     {"team": "finance", "topic": "b", "issue": "자료에 없는 근거", "chunk_id": "0" * 16, "stance": "condition", "confidence": "high"}])

    env, fakes = open_env(monkeypatch, fakes=Fakes(handler))
    with env:
        data = env.client(env.admin).post(URL, json=body(search="undivided")).json()
    assert [x["team"] for x in data["issue_rows"]] == ["security"] and data["team_status"]["finance"]["dropped"] == 1


def test_private_documents_are_not_used_as_evidence_in_either_mode(monkeypatch):
    private_cited = lambda user: j(missing=[], issues=[{"team": "security", "topic": "p", "issue": "비공개를 근거로", "chunk_id": next(c.chunk_id for c in CORPUS if "internal" in c.source_url),
                                                         "stance": "allow", "confidence": "low"}])
    for mode in ("same", "undivided"):
        env, _ = open_env(monkeypatch, fakes=Fakes(private_cited))
        with env:
            data = env.client(env.admin).post(URL, json=body(search=mode)).json()
        assert all(not x["source_url"].startswith("[비공개") for x in data["issue_rows"]) and data["issue_rows"] == []


def test_the_form_skill_is_added_once_and_off_with_use_skills(monkeypatch):
    seen = []

    class Rec(ScriptedLLM):
        def invoke(self, messages, *a, **k):
            seen.append(messages[0].content)
            return super().invoke(messages, *a, **k)

    for mode in ("same", "undivided"):
        fakes = Fakes()
        fakes.llm = Rec({"single": single_handler})
        env, _ = open_env(monkeypatch, fakes=fakes)
        with env:
            assert env.client(env.admin).post(URL, json=body(search=mode)).status_code == 200
    assert len(seen) == 2 and all(s.count(SR.FORM_HEADER) == 1 and "[보안 관점 Skill]" in s for s in seen)
    assert seen[0].count("관점의 자료에서 나온 chunk_id만") == 1 and "관점의 자료에서 나온 chunk_id만" not in seen[1] and "자료에 있는 chunk_id만 쓴다." in seen[1]
    seen.clear()
    env, _ = open_env(monkeypatch, fakes=Fakes())
    monkeypatch.setenv("USE_SKILLS", "0")   # Env가 만들 때 지우므로 그 뒤에 켠다
    env.app.state.eval_review_llm = Rec({"single": single_handler})
    with env:
        assert env.client(env.admin).post(URL, json=body()).status_code == 200
    assert seen and SR.FORM_HEADER not in seen[0] and "관점 Skill]" not in seen[0]


# ============================ 저장 없음 ============================

def test_nothing_is_stored_and_no_approval_is_queued(monkeypatch):
    env, fakes = open_env(monkeypatch)
    with env:
        state = env.app.state
        before_pending = [r.approval_id for r in state.decision_repo.list_pending()]
        assert before_pending == [] and state.issue_store.tables == {}
        c = env.client(env.admin)
        for mode in ("same", "undivided"):
            assert c.post(URL, json=body(search=mode)).json()["status"] == "pending_approval"
        assert state.issue_store.tables == {} and [r.approval_id for r in state.decision_repo.list_pending()] == []
        assert state.thread_store.threads_of(str(env.admin.user_id)) == [] and c.get("/approvals").json() == []


def test_the_single_reviewer_never_touches_graph_stores_by_construction():
    sig = SR.run_single.__code__.co_varnames[: SR.run_single.__code__.co_argcount + SR.run_single.__code__.co_kwonlyargcount]
    assert not {"store", "approvals", "checkpointer", "decision_repo", "thread_store", "issue_store"} & set(sig)
    assert "wide_retriever" in sig and "search" in sig


# ============================ 기록과 상한 ============================

def test_response_has_usage_retrieved_request_id_and_revision(monkeypatch):
    monkeypatch.setenv("K_REVISION", "provena-api-test")
    env, _ = open_env(monkeypatch)
    with env:
        r = env.client(env.admin).post(URL, json=body(), headers={"X-Request-ID": "rvchk-abc-1-1"})
    data = r.json()
    assert data["request_id"] == "rvchk-abc-1-1" and data["revision"] == "provena-api-test" and r.headers["X-Request-ID"] == "rvchk-abc-1-1"
    assert set(data["usage"]) == {"input_tokens", "output_tokens", "cost_usd", "calls"} and "retrieved" in data and data["latency_ms"] >= 0
    assert {"cost_by_step", "cost_by_step_total_usd"} <= set(data)


def test_one_warning_line_per_call_with_hash_and_without_the_request_text(monkeypatch, caplog):
    env, _ = open_env(monkeypatch)
    secret_text = "비밀스러운 도입 요청 문장 연 4만 달러"
    with env, caplog.at_level(logging.INFO):
        r = env.client(env.admin).post(URL, json=body(message=secret_text, search="undivided"))
    assert r.status_code == 200
    lines = [rec for rec in caplog.records if rec.getMessage().startswith("eval_review_single request_id=")]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    msg = lines[0].getMessage()
    assert f"message_sha={E.message_sha(secret_text)}" in msg and "search=undivided" in msg and "status=pending_approval" in msg and f"user_id={env.admin.user_id}" in msg
    assert secret_text not in caplog.text and "합성 쟁점" not in "\n".join(m for m in caplog.messages if m.startswith("eval_review_single"))


def test_daily_limit_returns_429_and_stops_calling_the_model(monkeypatch, caplog):
    monkeypatch.setenv(E.MAX_PER_DAY_ENV, "2")
    env, fakes = open_env(monkeypatch)
    with env, caplog.at_level(logging.WARNING):
        c = env.client(env.admin)
        assert [c.post(URL, json=body()).status_code for _ in range(2)] == [200, 200]
        r = c.post(URL, json=body())
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert fakes.llm.count("single") == 2 and any("reason=daily_limit" in m for m in caplog.messages)
    monkeypatch.setenv(E.MAX_PER_DAY_ENV, "abc")
    assert E.max_per_day() == E.DEFAULT_MAX_PER_DAY == 200      # 틀린 값은 기본값


def test_the_per_request_cost_cap_returns_429_limit_exceeded(monkeypatch):
    def boom(user: str) -> str:
        raise CostCapExceeded(0.06, 0.05)

    env, _ = open_env(monkeypatch, fakes=Fakes(boom))
    with env:
        r = env.client(env.admin).post(URL, json=body())
    assert r.status_code == 429 and r.json()["error"]["code"] == "limit_exceeded"


def test_model_errors_are_retried_then_reported_as_not_reviewed_not_as_no_issues(monkeypatch):
    def boom(user: str) -> str:
        raise KeyError("내부 값")

    fakes = Fakes(boom)
    env, _ = open_env(monkeypatch, fakes=fakes)
    with env:
        r = env.client(env.admin).post(URL, json=body())
    # 모델 호출이 깨지면 단일 검토자는 상한까지 다시 시도한 뒤 "쟁점 없음"으로 위장하지 않고 "검토하지 못함"으로 돌려준다(팀 에이전트와 같은 규칙)
    assert r.status_code == 200 and all(v["status"] == "not_reviewed" for v in r.json()["team_status"].values())
    assert len(r.json()["unreviewed"]) == 4 and r.json()["issue_rows"] == []
    assert "내부 값" not in r.text and fakes.llm.count("single") == R.TEAM_ATTEMPTS


def test_unexpected_errors_are_500_internal_error_without_details_and_are_logged_by_kind(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("비밀 내부 값")

    monkeypatch.setattr(SR, "run_single", boom)
    env, _ = open_env(monkeypatch)
    with env, caplog.at_level(logging.WARNING):
        r = env.client(env.admin).post(URL, json=body())
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error" and "비밀 내부 값" not in r.text
    assert any("status=error" in m and "error=RuntimeError" in m for m in caplog.messages) and "비밀 내부 값" not in caplog.text


# ============================ 서비스 경로와 분리 ============================

def test_chat_request_has_no_eval_fields_and_stays_strict():
    from backend.api.routes import ChatRequest

    assert ChatRequest.model_config.get("extra") == "forbid" and not {"search", "eval", "single"} & set(ChatRequest.model_fields)


def test_only_the_eval_endpoint_and_the_measurement_tool_import_the_single_reviewer():
    users = set()
    for path in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "evals").rglob("*.py")) + list((ROOT / "extras").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"single_review\b", text) and path.name != "single_review.py":
            users.add(path.relative_to(ROOT).as_posix())
    assert users == {"backend/api/eval_review.py", "evals/agent/exp_review_v1.py"}, users
    main_text = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "single_review" not in main_text and main_text.count("create_eval_review_router") == 2    # import 한 줄, 등록 한 줄


def test_the_eval_route_exists_once_and_chat_still_works_when_the_flag_is_off(monkeypatch):
    env, _ = open_env(monkeypatch, on=None)
    with env:
        paths = env.client().get("/openapi.json").json()["paths"]
        assert list(paths[URL]) == ["post"] and sum(1 for p in paths if p.startswith("/admin/eval")) == 1
        r = env.client(env.alice).post("/chat", json={"message": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "as_of": "2025-06-01"})
        assert r.status_code == 200 and "event: done" in r.text
