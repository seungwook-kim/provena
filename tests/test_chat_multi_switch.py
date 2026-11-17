"""`/chat` 질문 그래프 구조 스위치(`QUESTION_GRAPH_MODE`, 2026-11-17 팀장 결정) 시험.

- 코드 기본은 단일 그래프(`single`), 서비스 값(`SERVICE_ENV`)은 Supervisor 멀티 그래프(`multi`)다.
- 멀티 경로가 `/chat`의 단일 경로와 같은 기능을 갖는지 본다: SSE 이벤트 모양, 체크포인트 재개(재시작 뒤 같은 대화), 되묻기, 합동 검토 라우팅과 승인 대기,
  거절과 범위 밖, 질문 속 출력 자리 지시의 출력 검사, 비용 상한, 하루 질문 한도, LLM 기록의 노드 이름과 실행 표지, 출력 상한을 거는 모델 경로.
가짜 모델·메모리 저장소만 쓴다(키·네트워크·DB 없음). 비교 기준은 같은 입력을 준 단일 그래프다(evals/results/chat_multi_switch_20261117/PARITY.md).
"""
from __future__ import annotations

from types import SimpleNamespace

import api_test_support
import pytest
from api_test_support import Env, ask
from fake_search import fake_search
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from qgraph_fakes import answer_with_top_chunk, j, normal_llm
from team_review_fakes import REQUEST, review_llm
from test_live_injection_6277 import LIVE_04, LIVE_12PB, LIVE_12PB_ANSWER
from test_multi_graph import APPROVE, _no_wait  # noqa: F401  (_no_wait는 fixture)

from backend.graph import multi as M
from backend.graph import service_profile as SP
from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.build import build_graph
from backend.graph.decision.repo import InMemoryDecisionRepo
from backend.graph.departments.store import InMemoryIssueTableStore
from backend.graph.multi import build_multi_graph
from backend.graph.stream import stream_events
from backend.main import build_question_graph, question_graph_mode
from backend.services.cost import CostCapExceeded
from backend.services.llm import finish_run, run_config

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2025-06-01"
BUILDERS = {"single": build_graph, "multi": build_multi_graph}
# 출력 자리 지시를 따른 답 끝의 문구(기존 회귀 시험의 값을 그대로 쓴다)
TAIL = LIVE_12PB_ANSWER.rsplit("]. ", 1)[-1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ("QUESTION_GRAPH_MODE", "SUPERVISOR_ROUTER", "USE_SKILLS", "CHAT_FINAL_FROM_STREAM", "DAILY_QUESTION_LIMIT", "GRAPH_JUDGE_VOTE"):
        monkeypatch.delenv(name, raising=False)


def _use(monkeypatch, label: str) -> None:
    """시험 앱(`api_test_support.graph_factory`)이 만들 질문 그래프를 고른다. 멀티는 같은 인자를 받는다."""
    monkeypatch.setattr(api_test_support, "build_graph", BUILDERS[label])


def _stable(events: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """실행마다 달라지는 값(답 id, 요청 단위 시간 기록)만 뺀 이벤트."""
    out = []
    for name, d in events:
        data = dict(d["data"])
        data.pop("answer_id", None)
        if isinstance(data.get("path"), dict):
            data["path"] = {k: v for k, v in data["path"].items() if k not in ("timing", "vote_s")}
        out.append((name, data))
    return out


def _chat_both(monkeypatch, message: str, **env_kw) -> dict[str, list]:
    got = {}
    for label in BUILDERS:
        _use(monkeypatch, label)
        with Env(monkeypatch, **{k: (v() if callable(v) and k in ("llm", "review_llm") else v) for k, v in env_kw.items()}) as env:
            r, ev = ask(env.client(env.alice), message, "t1", as_of=AS_OF)
            assert r.status_code == 200, r.text
            got[label] = ev
            if label == "multi":
                assert "supervisor" in env.app.state.question_graph.nodes
    return got


# ---------- 스위치 ----------

def test_code_default_is_single_and_the_service_value_is_multi(monkeypatch):
    assert question_graph_mode() == "single"
    monkeypatch.setenv("QUESTION_GRAPH_MODE", "")
    assert question_graph_mode() == "single"
    monkeypatch.setenv("QUESTION_GRAPH_MODE", " Multi ")
    assert question_graph_mode() == "multi"
    assert SP.SERVICE_ENV["QUESTION_GRAPH_MODE"] == "multi"
    env: dict = {}
    SP.apply_service_profile(env)
    assert env["QUESTION_GRAPH_MODE"] == "multi"
    env = {"QUESTION_GRAPH_MODE": "off"}                 # 운영에서 되돌릴 때: off는 빈 값(코드 기본 single)
    SP.apply_service_profile(env)
    assert env["QUESTION_GRAPH_MODE"] == ""
    env = {"QUESTION_GRAPH_MODE": "single"}              # 직접 준 값은 그대로
    SP.apply_service_profile(env)
    assert env["QUESTION_GRAPH_MODE"] == "single"


@pytest.mark.parametrize("value", ["supervisor", "both", "1"])
def test_unknown_mode_is_an_error(monkeypatch, value):
    monkeypatch.setenv("QUESTION_GRAPH_MODE", value)
    with pytest.raises(ValueError):
        question_graph_mode()
    with pytest.raises(ValueError):
        build_question_graph(_state())


def _state() -> SimpleNamespace:
    return SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                           store=InMemoryStore(), answer_store=InMemoryAnswerStore())


@pytest.mark.parametrize("mode", ["", "single", "multi"])
def test_service_graph_follows_the_switch_with_the_same_arguments(monkeypatch, mode):
    """서비스 그래프(`build_question_graph`)는 스위치에 따라 단일이나 멀티를 만들고, 안쪽 단일 그래프에 같은 인자(공유 모델, 체크포인터 없음은 멀티만, 결정표, 합동 검토, 서비스 검색)를 넘긴다.
    모델은 두 구조 모두 같은 `SharedChatModel`이라 출력 상한(`LLM_MAX_TOKENS`), 프롬프트 캐시, 시간 상한이 같은 곳에서 걸린다."""
    import backend.graph.build as B

    monkeypatch.setenv("QUESTION_GRAPH_MODE", mode)
    seen: list[dict] = []
    real = B.build_graph

    def spy(*a, **k):
        seen.append({"args": a, **k})
        return real(*a, **k)

    monkeypatch.setattr(B, "build_graph", spy)
    monkeypatch.setattr(M, "build_graph", spy)
    st = _state()
    g = build_question_graph(st)
    (kw,) = seen
    assert isinstance(kw["llm"], SP.SharedChatModel) and kw["decision_repo"] is st.decision_repo and kw["review_graph"] is not None
    assert {"page_search", "intro_search", "prev_chunk"} <= set(kw) and kw["store"] is st.store and kw["answer_store"] is st.answer_store
    if mode == "multi":
        assert set(g.nodes) >= {"supervisor", "retriever", "writer", "verifier", "decision", "review"}
        assert g.checkpointer is st.checkpointer and kw["args"][1] is None   # 체크포인트는 바깥(멀티) 그래프 하나가 가진다
    else:
        assert "supervisor" not in g.nodes and g.checkpointer is st.checkpointer


# ---------- /chat 이벤트가 단일과 같다 ----------

CASES = {
    "answer": dict(message=Q, llm=lambda: normal_llm()),
    "refuse_after_research": dict(message=Q, llm=lambda: normal_llm(judge=j(sufficient=False, reason="부족", clarify=None))),
    "clarify": dict(message=Q, llm=lambda: normal_llm(judge=j(sufficient=False, reason="절 불명", clarify="어느 절 기준인가요?"))),
    "out_of_domain": dict(message="사내 연봉 협상은 어떻게 하나요?", llm=lambda: normal_llm(classify=j(route="out_of_domain"))),
    "verifier_refuses_fake_citation": dict(message=Q, llm=lambda: normal_llm(answer=j(answer="답 [deadbeefdeadbeef]", citations=[{"chunk_id": "deadbeefdeadbeef"}]))),
    "internal_settings_question": dict(message=LIVE_04, llm=lambda: normal_llm()),
    "output_position_instruction": dict(message=LIVE_12PB, llm=lambda: normal_llm(answer=lambda u: _with_tail(answer_with_top_chunk(u)))),
    # 되묻기 글에도 같은 출력 검사(`untrusted.scrub_answer`)가 걸린다(`give_up` 노드). 두 경로가 같은 노드를 부르므로 결과가 같다
    "output_position_instruction_in_clarify": dict(message=LIVE_12PB, llm=lambda: normal_llm(judge=j(sufficient=False, reason="절 불명", clarify=f"어느 절 기준인가요? {TAIL}"))),
}


def _with_tail(reply: str) -> str:
    import json

    obj = json.loads(reply)
    obj["answer"] = f"{obj['answer']} {TAIL}"
    return json.dumps(obj, ensure_ascii=False)


@pytest.mark.parametrize("name", list(CASES))
def test_chat_events_on_the_multi_graph_are_the_same_as_single(monkeypatch, name):
    """이벤트 종류·순서·내용(토큰, 인용, done의 kind·code·refuse_stage·refuse_reason·path·usage)이 같다. 거절·되묻기의 `refuse_stage`도 단일의 노드 이름이다."""
    case = CASES[name]
    got = _chat_both(monkeypatch, case["message"], llm=case["llm"])
    assert _stable(got["multi"]) == _stable(got["single"])
    done = got["multi"][-1][1]["data"]
    assert got["multi"][-1][0] == "done"
    if done["kind"] in ("refuse", "clarify"):
        assert done["refuse_stage"] not in ("supervisor", "retriever", "writer", "verifier")
    if name.startswith("output_position_instruction"):
        text = "".join(d["data"]["text"] for n, d in got["multi"] if n == "token")
        assert TAIL not in text                                   # 출력 검사가 이어 붙인 문구가 든 문장을 뺐다(답, 되묻기 모두)
        assert done["kind"] == ("answer" if name == "output_position_instruction" else done["kind"])


def test_every_single_graph_node_runs_on_the_multi_path():
    """단일 그래프에 노드가 새로 생기면(예: 출력 검사 단계) 멀티에도 배선돼야 한다. 단일의 모든 노드가 Supervisor가 직접 부르는 노드이거나 어느 에이전트 안에 있다.
    새 노드가 생겨 이 시험이 깨지면 `multi.py`의 `AgentSpec`이나 Supervisor에 같은 노드를 넣는다(빠진 채로 /chat이 멀티로 돌지 않게)."""
    from backend.graph.departments.review import build_review_graph
    from team_review_fakes import Retriever

    llm = normal_llm()
    review = build_review_graph(Retriever(), None, llm=llm, store=InMemoryIssueTableStore())
    single = build_graph(fake_search, llm=llm, decision_repo=InMemoryDecisionRepo(), review_graph=review)
    by_supervisor = {"load_memory", "followup", "classify", "out_of_domain", "give_up"}
    in_agents = {n for spec in (*M.AGENTS.values(), *M.CONNECTED_AGENTS.values()) for n in spec.nodes}
    assert set(single.nodes) - {"__start__"} == by_supervisor | in_agents


def test_refuse_stage_names_the_single_graph_node():
    """멀티의 에이전트 노드 이름(supervisor, retriever, verifier)이 아니라, 결과 종류를 쓴 단일 그래프의 노드 이름이 done에 남는다(측정 도구가 읽는다)."""
    stages: dict[str, dict] = {}
    for label, build in BUILDERS.items():
        stages[label] = {}
        for name, llm in (("ood", normal_llm(classify=j(route="out_of_domain"))),
                          ("give_up", normal_llm(judge=j(sufficient=False, reason="부족", clarify=None))),
                          ("clarify", normal_llm(judge=j(sufficient=False, reason="절", clarify="어느 절 기준인가요?"))),
                          ("ground", normal_llm(answer=j(answer="답 [deadbeefdeadbeef]", citations=[{"chunk_id": "deadbeefdeadbeef"}])))):
            g = build(fake_search, InMemorySaver(), llm=llm)
            ev = list(stream_events(g, {"question": Q, "user_id": "u1", "thread_id": "x", "as_of": AS_OF}, thread_id="x"))
            stages[label][name] = (ev[-1].data.get("refuse_stage"), ev[-1].data.get("refuse_reason"))
    assert stages["multi"] == stages["single"]
    assert stages["multi"]["ood"][0] == "out_of_domain" and stages["multi"]["give_up"][0] == "give_up"
    assert stages["multi"]["ground"][0] in ("verify", "ground")
    assert not {s for s, _ in stages["multi"].values()} & {"supervisor", "retriever", "writer", "verifier"}


# ---------- 체크포인트: 재시작 뒤 같은 대화 ----------

@pytest.mark.parametrize("label", list(BUILDERS))
def test_thread_survives_a_new_graph_on_the_same_checkpointer(monkeypatch, label):
    """같은 체크포인터로 그래프를 새로 만들어도(서버 재시작) 같은 대화의 이력과 이어 묻기가 이어진다."""
    _use(monkeypatch, label)
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        ask(c, Q, "t1", as_of=AS_OF)
        st = env.app.state
        st.question_graph = BUILDERS[label](fake_search, st.checkpointer, llm=normal_llm(), store=st.store, answer_store=st.answer_store, decompose=False)
        _, ev = ask(c, "그럼 SEV1은요?", "t1", as_of=AS_OF)
        assert ev[-1][0] == "done" and ev[-1][1]["data"]["kind"] == "answer"
        uid = str(env.alice.user_id)
        values = st.question_graph.get_state({"configurable": {"thread_id": f"{uid}:t1"}}).values
        assert values["asked"][-2:] == [Q, "그럼 SEV1은요?"]
        msgs = c.get("/threads/t1").json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"] and all(m["state"] == "done" for m in msgs if m["role"] == "assistant")


def test_thread_history_is_the_same_on_both_graphs(monkeypatch):
    got = {}
    for label in BUILDERS:
        _use(monkeypatch, label)
        with Env(monkeypatch) as env:
            c = env.client(env.alice)
            ask(c, Q, "t1", as_of=AS_OF)
            ask(c, "사내 연봉 협상은 어떻게 하나요?", "t1", as_of=AS_OF)
            msgs = c.get("/threads/t1").json()["messages"]
            got[label] = [{k: v for k, v in m.items() if k not in ("timestamp", "answer_id")} for m in msgs]
    assert got["multi"] == got["single"]


# ---------- 합동 검토(Supervisor + 팀) 라우팅과 승인 대기 ----------

def test_joint_review_through_chat_on_the_multi_graph_waits_for_approval_and_resumes(monkeypatch, _no_wait):
    _use(monkeypatch, "multi")
    llm = review_llm(classify=j(route="review"))
    with Env(monkeypatch, llm=llm, review_llm=llm) as env:
        c = env.client(env.alice)
        r, ev = ask(c, REQUEST, "t1", as_of="2026-11-05")
        assert r.status_code == 200 and [n for n, _ in ev] == ["approval_request"]
        assert ev[0][1]["data"]["kind"] == "issue_table" and ev[0][1]["data"]["code"] == "approval_pending"
        assert any(t == "supervisor" for t, _ in llm.calls)   # 합동 검토 Supervisor가 돌았다
        msgs = c.get("/threads/t1").json()["messages"]
        assert msgs[-1]["state"] == "approval"                      # 대화 이력이 승인 대기를 읽는다
        uid = str(env.alice.user_id)
        cfg = {"configurable": {"thread_id": f"{uid}:t1"}}
        assert env.app.state.review_graph is env.app.state.question_graph
        done = env.app.state.review_graph.invoke(Command(resume=APPROVE), cfg)
        assert done["kind"] == "answer" and done["review_status"] == "approved" and done["agent_trace"] == ["review"]


def test_joint_review_events_are_the_same_as_single(monkeypatch, _no_wait):
    make = lambda: review_llm(classify=j(route="review"))   # noqa: E731
    got = _chat_both(monkeypatch, REQUEST, llm=make, review_llm=make)
    strip = lambda ev: [(n, {k: v for k, v in d["data"].items() if k != "approval_id"}) for n, d in ev]   # noqa: E731  승인 번호는 사용자·대화에서 정해져 앱마다 다르다
    assert strip(got["multi"]) == strip(got["single"]) and [n for n, _ in got["multi"]] == ["approval_request"]


# ---------- 비용 상한 ----------

@pytest.mark.parametrize("where", ["search", "classify", "answer"])
def test_cost_cap_ends_with_limit_exceeded_on_both_graphs(monkeypatch, where):
    def capped(*_a, **_k):
        raise CostCapExceeded(0.06, 0.05)

    kw: dict = {}
    if where == "search":
        kw["search"] = capped
    else:
        kw["llm"] = lambda: normal_llm(**{where: lambda u: capped()})
    got = _chat_both(monkeypatch, Q, **kw)
    for label in BUILDERS:
        assert [n for n, _ in got[label]] == ["error"] and got[label][0][1]["data"]["code"] == "limit_exceeded", label


# ---------- 하루 질문 한도 ----------

def test_daily_limit_counts_one_per_question_on_the_multi_graph(monkeypatch):
    """멀티는 하위 에이전트의 체크포인트를 하위 이름공간에 따로 남긴다. 한도는 바깥 이름공간의 입력 체크포인트만 세므로 질문 하나가 한 건이다."""
    monkeypatch.setenv("DAILY_QUESTION_LIMIT", "2")
    _use(monkeypatch, "multi")
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        assert ask(c, Q, "t1", as_of=AS_OF)[0].status_code == 200
        assert ask(c, Q, "t2", as_of=AS_OF)[0].status_code == 200
        r, _ = ask(c, Q, "t3", as_of=AS_OF)
        assert r.status_code == 429 and r.json()["error"]["code"] == "daily_limit"


# ---------- LLM 기록: 노드 이름과 실행 표지 ----------

class Seen(BaseCallbackHandler):
    def __init__(self):
        self.rows: list[tuple[str | None, str | None]] = []

    def on_chain_start(self, serialized, inputs, **kw):
        if kw.get("name") == "fake_llm":
            meta = kw.get("metadata") or {}
            self.rows.append((meta.get("langgraph_node"), meta.get("thread_id")))


@pytest.mark.parametrize("llm_kw", [{}, {"judge": j(sufficient=False, reason="부족", clarify=None)}, {"classify": j(route="out_of_domain")}],
                         ids=["answer", "refuse", "out_of_domain"])
def test_llm_calls_carry_the_single_node_names_and_the_run_metadata(llm_kw):
    """`cost_by_step`과 Langfuse가 읽는 노드 이름(`langgraph_node`)이 단일과 같다. Supervisor가 직접 부른 분류도 `classify`로 남는다.
    `run_config`의 실행 표지(thread_id)가 하위 에이전트 안의 호출에도 붙는다."""
    rows = {}
    for label, build in BUILDERS.items():
        scripted = normal_llm(**llm_kw)
        wrapped = RunnableLambda(lambda msgs, _s=scripted: _s.invoke(msgs), name="fake_llm")
        seen = Seen()
        cfg = run_config("question", user_id="u1", thread_id="u1:t", configurable={"thread_id": "u1:t"})
        cfg["callbacks"].append(seen)
        build(fake_search, InMemorySaver(), llm=wrapped).invoke({"question": Q, "user_id": "u1", "thread_id": "u1:t", "as_of": AS_OF}, cfg)
        finish_run(cfg)
        rows[label] = seen.rows
    assert rows["multi"] == rows["single"] and rows["multi"]
    assert all(node not in ("supervisor", None) for node, _ in rows["multi"]) and {t for _, t in rows["multi"]} == {"u1:t"}


# ---------- 판정 기록 ----------

def test_judge_vote_record_is_kept_on_the_multi_graph(monkeypatch):
    """판정 다수결(`GRAPH_JUDGE_VOTE`, 서비스 값)의 표 구성 기록(`judge_votes`, done의 `path.judge_votes`)이 멀티에서도 단일과 같은 수로 남는다."""
    monkeypatch.setenv("GRAPH_JUDGE_VOTE", "1")
    outs = {}
    for label, build in BUILDERS.items():
        out = build(fake_search, llm=normal_llm()).invoke({"question": Q, "user_id": "u1", "thread_id": "t", "as_of": AS_OF})
        outs[label] = out
    assert len(outs["multi"]["judge_votes"]) == len(outs["single"]["judge_votes"]) >= 1
    assert [v.get("retries") for v in outs["multi"]["judge_votes"]] == [v.get("retries") for v in outs["single"]["judge_votes"]]
    assert "judge_votes" in M.RETRIEVER.reads and "judge_votes" in M.RETRIEVER.writes
