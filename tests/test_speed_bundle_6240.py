"""응답 시간 속도 묶음 시험(사전 등록 62.40). 가짜 모델, 가짜 검색기, 가짜 DB 연결만 쓴다(키·네트워크·DB·유료 호출 없음).

- ① 시작 준비 넓히기(`backend/main.py` `first_request_warmup`)
- ② 답 저장소 연결 다시 쓰기(`ANSWER_STORE_REUSE_CONN`)
- ③ 근거 확인 실패 연쇄 병렬화(`GRAPH_REVISE_AHEAD`)
- ④ 판정 단계 호출 상한(`LLM_DEADLINE_BY_TASK`)
- ⑤ 답이 나간 뒤 버려지는 근거 확인 호출 막기
각 스위치는 꺼진 상태가 지금과 같다는 시험을 함께 둔다.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fake_search import fake_search
from qgraph_fakes import ScriptedLLM, first_chunk_id, j, normal_llm
from test_answer_fixes_graph import run as run_q
from test_question_graph import Q, _by_article, _sentences_answer, run

from backend import main
from backend.graph import answer_store as AS
from backend.graph import service_profile as SP
from backend.graph.answer_store import InMemoryAnswerStore, PgAnswerStore
from backend.graph.build import build_graph
from backend.services import llm as L

import backend.rag.retrieve.search  # noqa: E402,F401

search_mod = sys.modules["backend.rag.retrieve.search"]

SWITCHES = ("GRAPH_REVISE_AHEAD", "GRAPH_SPECULATE_GROUND", "GRAPH_SPECULATE_FIRST", "GRAPH_JUDGE_ANSWER", "GRAPH_ANSWER_WAIT_S",
            "GRAPH_ANSWER_BUDGET_S", "ANSWER_STORE_REUSE_CONN", "LLM_DEADLINE_BY_TASK", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_SUB_RESEARCH", "GRAPH_PAGE_RESEARCH",
            "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_QUERY_TERMS", "GRAPH_QUERY_BRANCHES", "GRAPH_REQUERY_TERMS")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


# ============================ ① 시작 준비 넓히기 ============================

class FakeSearcher:
    """`first_request_warmup`이 쓰는 것만 가진 검색기. 부른 일을 차례로 적는다."""

    def __init__(self, fail_embed=False):
        self.calls: list = []
        self.cfg = SimpleNamespace(embed_model="voyage-4")
        self.store = self
        self.fail_embed = fail_embed

    def embed(self, texts):
        self.calls.append(("embed", tuple(texts)))
        if self.fail_embed:
            raise OSError("postgresql://user:secret@host/db 연결 실패")
        return [[0.1, 0.2]]

    def vector_top(self, vec, model, org, as_of, n):
        self.calls.append(("top", model, org, as_of, n))
        return []

    def search(self, q):    # 번역·LLM을 거치는 길. 시작 준비는 부르지 않는다
        self.calls.append(("search",))
        return []


@pytest.fixture
def warm(monkeypatch):
    """검색 준비는 가짜로 끝난 것으로 하고, tracing 부르기를 센다."""
    s = FakeSearcher()
    monkeypatch.setattr(search_mod, "_searcher", s)
    monkeypatch.setattr(search_mod, "warmup", lambda: s)
    handler_calls: list = []
    from backend.services import tracing

    monkeypatch.setattr(tracing, "get_handler", lambda **kw: handler_calls.append(kw))
    return SimpleNamespace(searcher=s, handler_calls=handler_calls)


def test_first_request_warmup_creates_the_langfuse_client_and_embeds_and_queries_once(warm, caplog):
    with caplog.at_level(logging.INFO, logger="backend.main"):
        main.first_request_warmup(searcher_ready=True)
    assert warm.handler_calls == [{"allow_evaluation": True}]           # 클라이언트·핸들러만 만든다(트레이스는 보내지 않는다)
    assert warm.searcher.calls == [("embed", (main.WARMUP_QUERY,)), ("top", "voyage-4", None, None, 1)]   # 번역·LLM 길(search)은 부르지 않는다
    assert any("stage=first_request_warmup" in r.getMessage() and "steps=tracing,search" in r.getMessage() for r in caplog.records)


def test_first_request_warmup_skips_the_search_when_the_search_warmup_failed(warm):
    main.first_request_warmup(searcher_ready=False)
    assert warm.searcher.calls == [] and len(warm.handler_calls) == 1


def test_first_request_warmup_step_failures_only_warn_and_do_not_raise(monkeypatch, caplog):
    from backend.services import tracing

    def broken(**kw):
        raise ImportError("langfuse 없음")

    s = FakeSearcher(fail_embed=True)
    monkeypatch.setattr(search_mod, "_searcher", s)
    monkeypatch.setattr(tracing, "get_handler", broken)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main.first_request_warmup(searcher_ready=True)           # 두 단계가 모두 실패해도 예외가 없다
    assert "stage=first_request_warmup" in caplog.text and "ImportError" in caplog.text and "OSError" in caplog.text
    assert "secret" not in caplog.text                         # 오류 종류만 남긴다
    assert s.calls == [("embed", (main.WARMUP_QUERY,))]        # 임베딩이 실패하면 색인 질의는 하지 않는다


def test_startup_warmup_runs_the_first_request_warmup_after_the_search_warmup_and_survives_its_failure(monkeypatch, warm):
    order = []
    monkeypatch.setattr(search_mod, "warmup", lambda: order.append("search") or warm.searcher)
    monkeypatch.setattr(main, "first_request_warmup", lambda **kw: order.append(("first", kw["searcher_ready"])))
    assert main.run_startup_warmup(preload_llm=False, timeout=5) is True
    assert order == ["search", ("first", True)]

    def boom(**kw):
        raise RuntimeError("예상 밖 오류")

    order.clear()
    monkeypatch.setattr(main, "first_request_warmup", boom)
    main.run_startup_warmup(preload_llm=False, timeout=5)      # 스레드 안의 오류가 서버 시작을 막지 않는다(반환만 한다)


def test_demo_and_local_modes_do_not_run_the_warmup_at_all(monkeypatch):
    """운영에서만 켜는 기존 조건(`search_warmup_default_on`)을 그대로 쓴다: 로컬·데모는 시작 준비 자체를 하지 않는다."""
    calls = []
    monkeypatch.setattr(main, "first_request_warmup", lambda **kw: calls.append(kw))
    monkeypatch.delenv("SEARCH_WARMUP", raising=False)
    monkeypatch.setenv("PROVENA_ENV", "local")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False
    assert calls == []


# ============================ ② 답 저장소 연결 다시 쓰기 ============================

class Conn:
    """재사용 풀이 읽는 만큼만 가진 가짜 연결."""

    def __init__(self, log, ident, fail_first=False):
        from psycopg.pq import TransactionStatus

        self.log, self.ident, self.closed, self.fail_first = log, ident, False, fail_first
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

    def close(self):
        self.closed = True
        self.log.append(("close", self.ident))

    def transaction(self):
        conn = self

        class Tx:
            def __enter__(self_inner):
                conn.log.append(("begin", conn.ident))

            def __exit__(self_inner, exc_type, *rest):
                conn.log.append(("rollback" if exc_type else "commit", conn.ident))
                return False

        return Tx()

    def cursor(self):
        conn = self

        class Cur:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def executemany(self_inner, sql, rows):
                conn.log.append(("many", conn.ident, len(list(rows))))

        return Cur()

    def execute(self, sql, params=None):
        import psycopg

        if self.fail_first:
            self.fail_first = False
            self.closed = True
            raise psycopg.OperationalError("서버가 연결을 닫았다")
        self.log.append(("exec", self.ident, " ".join(sql.split())[:30]))
        return self


def _pool(clock=time.monotonic, fail_first_ids=()):
    log: list = []
    opened: list = []

    def open_conn():
        c = Conn(log, len(opened) + 1, fail_first=(len(opened) + 1) in fail_first_ids)
        opened.append(c)
        return c

    return AS._ConnectionReuse(open_conn, clock), log, opened


def test_reused_connection_serves_sequential_uses_from_one_connection():
    pool, log, opened = _pool()
    for _ in range(3):
        with pool() as conn:
            assert conn is opened[0]
    assert len(opened) == 1 and not opened[0].closed


def test_reused_connection_gives_concurrent_users_different_connections_and_keeps_at_most_two_idle():
    pool, log, opened = _pool()
    inside = threading.Barrier(3)
    seen: list = []

    def use():
        with pool() as conn:
            seen.append(conn)
            inside.wait(5)          # 세 사용자가 동시에 연결을 쥐고 있다

    ts = [threading.Thread(target=use) for _ in range(3)]
    [t.start() for t in ts]
    [t.join(5) for t in ts]
    assert len({id(c) for c in seen}) == 3 and len(opened) == 3          # 서로 다른 연결(저장이 섞이지 않는다)
    assert len(pool._idle) == AS.REUSE_IDLE_MAX == 2 and sum(1 for c in opened if c.closed) == 1   # 남는 하나는 닫는다


def test_reused_connection_is_closed_not_reused_after_an_error_or_when_a_transaction_is_open():
    from psycopg.pq import TransactionStatus

    pool, log, opened = _pool()
    with pytest.raises(RuntimeError):
        with pool():
            raise RuntimeError("저장 실패")
    assert opened[0].closed and pool._idle == []
    with pool() as c2:
        c2.info.transaction_status = TransactionStatus.INTRANS      # 트랜잭션이 열린 채 돌려주면 다시 쓰지 않는다
    assert c2.closed and len(opened) == 2 and pool._idle == []


def test_reused_connection_that_was_idle_too_long_is_replaced():
    now = [0.0]
    pool, log, opened = _pool(clock=lambda: now[0])
    with pool():
        pass
    now[0] += AS.REUSE_IDLE_SECONDS - 1
    with pool() as c:
        assert c is opened[0]
    now[0] += AS.REUSE_IDLE_SECONDS + 1
    with pool() as c:
        assert c is opened[1] and opened[0].closed        # 서버 쪽에서 끊겼을 수 있는 오래 논 연결은 쓰지 않는다


def _args(i=1):
    from test_speed_p95_code import CITES

    return (f"a{i}", "u1", "u1:t1", "질문?", "답 [1]", "2025-06-01", CITES)


def test_pg_store_with_reuse_saves_the_same_statements_on_one_connection():
    pool, log, opened = _pool()
    PgAnswerStore(connect=pool).save(*_args(1))
    PgAnswerStore(connect=pool).save_with_grounding(*_args(2), {"grounded": True}, ["glossary"])
    assert len(opened) == 1
    kinds = [x[0] for x in log if x[0] != "close"]
    assert kinds == ["begin", "exec", "many", "commit", "begin", "exec", "many", "commit"]    # 저장마다 한 트랜잭션, 답 INSERT 한 문장 + 인용


def test_pg_store_with_reuse_retries_once_with_a_new_connection_when_the_kept_one_was_closed_by_the_server():
    pool, log, opened = _pool(fail_first_ids=(1,))
    store = PgAnswerStore(connect=pool)
    store.save(*_args(1))              # 첫 연결이 끊겨 있어 한 번 실패하고, 새 연결로 다시 저장된다
    assert len(opened) == 2 and opened[0].closed
    assert [x[0] for x in log if x[0] in ("commit", "rollback")] == ["rollback", "commit"]
    assert [x for x in log if x[0] == "exec" and x[1] == 2]           # 저장은 새 연결에서 끝났다


def test_pg_store_without_reuse_does_not_retry(monkeypatch):
    """꺼져 있으면(연결을 다시 쓰지 않으면) 지금처럼 한 번만 부르고 오류는 그대로 올린다."""
    import psycopg

    calls = []

    def connect():
        calls.append(1)
        c = Conn([], len(calls), fail_first=True)
        return SimpleNamespace(__enter__=lambda s: c, __exit__=lambda *a: False)

    class Ctx:
        def __enter__(self):
            calls.append(1)
            raise psycopg.OperationalError("연결 실패")

        def __exit__(self, *a):
            return False

    with pytest.raises(psycopg.OperationalError):
        PgAnswerStore(connect=lambda: Ctx()).save(*_args(1))
    assert len(calls) == 1


def test_default_connect_reuses_only_when_the_switch_is_on(monkeypatch):
    import psycopg

    opened = []
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: opened.append(1) or Conn([], len(opened)))
    monkeypatch.delenv("ANSWER_STORE_REUSE_CONN", raising=False)
    off = AS._default_connect("postgresql://x")
    assert not isinstance(off, AS._ConnectionReuse)
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    on = AS._default_connect("postgresql://x")
    assert isinstance(on, AS._ConnectionReuse)
    with on():
        pass
    with on():
        pass
    assert len(opened) == 1


# ============================ ③ 근거 확인 실패 연쇄 병렬화 ============================

def _chain(redraft_ok: bool, revise_ok: bool, events: list | None = None):
    """근거 확인이 셋째 문장을 지적한다. redraft_ok면 다시 쓴 답이 통과하고, 아니면 같은 답이 나와 문장 빼기로 간다(revise_ok면 통과)."""
    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    s1, s2, s3 = "SEV2 장애 최초 대응은 15분 이내이다", "담당자가 직접 호출한다", "에스컬레이션은 2시간 상한이다"
    first = _sentences_answer((s1, paging.chunk_id), (s2, paging.chunk_id), (s3, escal.chunk_id))
    redo = _sentences_answer((s1 + " 입니다", paging.chunk_id), (s2, paging.chunk_id))

    def grounding(user):
        if s3 in user:
            return j(grounded=False, reason_code="unsupported", reason="2시간이 자료와 다름", unsupported_sentences=[f"{s3} [{escal.chunk_id}]."])
        if events is not None:
            events.append(("second_grounding_start", time.monotonic()))
        return j(grounded=True) if (redraft_ok or revise_ok) else j(grounded=False, reason_code="unsupported", reason="아직 틀림", unsupported_sentences=[])

    calls = []

    def answer(user):
        calls.append(1)
        if len(calls) > 1 and events is not None:      # 다시 쓰는 호출은 느리다(0.3초)
            time.sleep(0.3)
            events.append(("redraft_end", time.monotonic()))
        return redo if (redraft_ok and len(calls) > 1) else first

    return normal_llm(answer=answer, grounding=grounding), [paging, escal], (s1, s2, s3)


def _run_chain(monkeypatch, *, ahead: bool, redraft_ok: bool, revise_ok: bool, events: list | None = None):
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    if ahead:
        monkeypatch.setenv("GRAPH_REVISE_AHEAD", "1")
    llm, chunks, sents = _chain(redraft_ok, revise_ok, events)
    out = run(build_graph(lambda q: chunks, llm=llm, grounding_llm=True, answer_store=InMemoryAnswerStore()))
    time.sleep(0.2)                 # 버려진 미리 부르기가 있으면 끝나도록
    return out, llm, sents


def _core(out):
    g = dict(out.get("grounding") or {})
    return {"kind": out["kind"], "answer": out["answer"], "citations": [c["chunk_id"] for c in out.get("citations", [])],
            "refuse_reason": out.get("refuse_reason"), "revise": g.get("revise"), "redraft": g.get("redraft"), "rejudge": g.get("rejudge"),
            "revised": g.get("revised"), "redrafted": g.get("redrafted"), "llm": g.get("llm")}


@pytest.mark.parametrize("redraft_ok,revise_ok", [(True, True), (False, True), (False, False)])
def test_revise_ahead_gives_the_same_result_as_off(monkeypatch, redraft_ok, revise_ok):
    off, off_llm, _ = _run_chain(monkeypatch, ahead=False, redraft_ok=redraft_ok, revise_ok=revise_ok)
    on, on_llm, _ = _run_chain(monkeypatch, ahead=True, redraft_ok=redraft_ok, revise_ok=revise_ok)
    assert _core(on) == _core(off)
    assert on["kind"] == ("answer" if (redraft_ok or revise_ok) else "refuse")


def test_revise_ahead_when_the_redraft_fails_reuses_the_early_call_instead_of_calling_again(monkeypatch):
    off, off_llm, _ = _run_chain(monkeypatch, ahead=False, redraft_ok=False, revise_ok=True)
    on, on_llm, _ = _run_chain(monkeypatch, ahead=True, redraft_ok=False, revise_ok=True)
    assert off_llm.count("grounding") == on_llm.count("grounding") == 2        # 첫 확인 + 문장 뺀 답 재확인 (같은 호출 수, 순서만 앞당김)
    assert on["grounding"]["revised"] is True and on["grounding"]["rejudge"] == "grounded"


def test_revise_ahead_starts_the_recheck_before_the_redraft_finishes_and_off_starts_it_after(monkeypatch):
    for ahead in (True, False):
        monkeypatch.delenv("GRAPH_REVISE_AHEAD", raising=False)
        events: list = []
        _run_chain(monkeypatch, ahead=ahead, redraft_ok=False, revise_ok=True, events=events)
        at = dict(events)
        assert at["second_grounding_start"] < at["redraft_end"] if ahead else at["second_grounding_start"] > at["redraft_end"]


def test_revise_ahead_when_the_redraft_passes_wastes_at_most_the_one_early_call(monkeypatch):
    off, off_llm, _ = _run_chain(monkeypatch, ahead=False, redraft_ok=True, revise_ok=True)
    on, on_llm, _ = _run_chain(monkeypatch, ahead=True, redraft_ok=True, revise_ok=True)
    assert off_llm.count("grounding") == 2
    assert 2 <= on_llm.count("grounding") <= 3          # 다시 쓴 답이 쓰이면 미리 부른 재확인은 버려진다(최대 한 번)
    assert on["grounding"]["redrafted"] is True and "revise" not in on["grounding"]


def test_revise_ahead_does_not_call_early_when_the_code_checks_before_the_llm_fail(monkeypatch):
    """지적한 문장이 답에 없으면(문장 빼기가 LLM 전에 떨어짐) 미리 부르지 않는다. 호출 수는 꺼짐과 같다."""
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    monkeypatch.setenv("GRAPH_REVISE_AHEAD", "1")
    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    answer = _sentences_answer(("SEV2 장애 최초 대응은 15분 이내이다", paging.chunk_id), ("에스컬레이션은 2시간 상한이다", escal.chunk_id))
    llm = normal_llm(answer=answer, grounding=j(grounded=False, reason_code="unsupported", reason="x", unsupported_sentences=["답에 없는 문장을 지어 낸 항목입니다"]))
    out = run(build_graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    time.sleep(0.1)
    assert out["kind"] == "refuse" and out["grounding"]["revise"]["result"] == "unmatched" and llm.count("grounding") == 1


def test_revise_ahead_needs_the_speculative_ground_pool(monkeypatch):
    """`GRAPH_SPECULATE_GROUND`가 꺼져 있으면 일꾼이 없으므로 이 스위치도 동작하지 않고 결과와 호출 수가 꺼짐과 같다."""
    monkeypatch.setenv("GRAPH_REVISE_AHEAD", "1")
    llm, chunks, _ = _chain(False, True)
    out = run(build_graph(lambda q: chunks, llm=llm, grounding_llm=True))
    monkeypatch.delenv("GRAPH_REVISE_AHEAD")
    llm2, chunks2, _ = _chain(False, True)
    base = run(build_graph(lambda q: chunks2, llm=llm2, grounding_llm=True))
    assert _core(out) == _core(base) and llm.count("grounding") == llm2.count("grounding") == 2


# ============================ ④ 판정 단계 호출 상한 ============================

def _post(task=None):
    import httpx

    content = b'{"system": "[[task:%s]] SECRET", "messages": []}' % task.encode() if task else b"{}"
    return httpx.Request("POST", "http://fake.invalid/", content=content)


class SlowTransport:
    def __init__(self, seconds):
        self.seconds = seconds

    def handle_request(self, request):
        import httpx

        time.sleep(self.seconds)
        return httpx.Response(200, json={})


def test_deadline_by_task_gives_only_that_task_the_longer_limit():
    import httpx

    t = L.DeadlineTransport(SlowTransport(0.3), 0.1, by_task={"judge": 0.6})
    assert t.handle_request(_post("judge")).status_code == 200          # 판정은 0.6초까지 기다린다
    for other in ("answer", "grounding", None):
        with pytest.raises(httpx.ReadTimeout):
            t.handle_request(_post(other))                            # 다른 단계와 표지 없는 요청은 기본 상한(0.1초)


def test_deadline_by_task_empty_keeps_every_task_on_the_default_limit():
    import httpx

    t = L.DeadlineTransport(SlowTransport(0.3), 0.1)
    with pytest.raises(httpx.ReadTimeout):
        t.handle_request(_post("judge"))


def test_deadline_by_task_limit_still_grows_with_the_retry_number():
    import httpx

    class Quick:
        def handle_request(self, request):
            time.sleep(0.25)
            return httpx.Response(200, json={})

    retry = _post("judge")
    retry.headers["x-stainless-retry-count"] = "1"
    t = L.DeadlineTransport(Quick(), 0.1, by_task={"judge": 0.15})
    assert t.handle_request(retry).status_code == 200                    # 0.15 x 2 = 0.3초


def test_deadline_by_task_on_the_anthropic_transport():
    import httpx2

    class Slow2(httpx2.BaseTransport):
        def handle_request(self, request):
            time.sleep(0.3)
            return httpx2.Response(200, json={})

    t = L._deadline_transport_httpx2(0.1, 0.0, (), {"judge": 0.6})
    t.inner = Slow2()
    req = httpx2.Request("POST", "http://fake.invalid/", content=b'{"system": [{"type": "text", "text": "[[task:judge]] x"}], "messages": []}')
    assert t.handle_request(req).status_code == 200
    req2 = httpx2.Request("POST", "http://fake.invalid/", content=b'{"system": "[[task:answer]] x", "messages": []}')
    with pytest.raises(httpx2.ReadTimeout):
        t.handle_request(req2)


def test_deadline_by_task_parses_the_environment(monkeypatch):
    monkeypatch.delenv("LLM_DEADLINE_BY_TASK", raising=False)
    assert L.deadline_by_task() == {}
    monkeypatch.setenv("LLM_DEADLINE_BY_TASK", " judge=12 , Answer=6.5,")
    assert L.deadline_by_task() == {"judge": 12.0, "answer": 6.5}
    for bad in ("judge", "judge=", "judge=abc", "judge=0", "judge=-3", "=12", "ju dge=12"):
        monkeypatch.setenv("LLM_DEADLINE_BY_TASK", bad)
        with pytest.raises(ValueError):
            L.deadline_by_task()


def test_deadline_by_task_reaches_the_clients(monkeypatch):
    monkeypatch.setenv("LLM_DEADLINE_S", "8")
    monkeypatch.setenv("LLM_DEADLINE_BY_TASK", "judge=12")
    client = L._anthropic_http_client()
    assert client._transport.by_task == {"judge": 12.0} and client._transport.seconds == 8.0
    monkeypatch.delenv("LLM_DEADLINE_BY_TASK")
    assert L._anthropic_http_client()._transport.by_task == {}


# ============================ ⑤ 버려지는 근거 확인 호출 막기 ============================

def _reply(word, delay=0.0):
    def call(user):
        time.sleep(delay)
        return j(answer=f"{word} [{first_chunk_id(user)}]", citations=[{"chunk_id": first_chunk_id(user)}], period_covered=True)
    return call


def _wait_graph(monkeypatch, wait_s, slow_delay):
    monkeypatch.setenv("GRAPH_ANSWER_WAIT_S", wait_s)
    monkeypatch.setenv("GRAPH_JUDGE_ANSWER", "parallel_all")
    monkeypatch.setenv("GRAPH_SPECULATE_GROUND", "1")
    llm = ScriptedLLM({**normal_llm().handlers, "decompose": j(split=False, sub_questions=[]), "grounding": j(reason="", grounded=True),
                       "answer": _reply("느린답", slow_delay), "answer_fast": _reply("빠른답")})
    out = run_q(build_graph(fake_search, llm=llm, grounding_llm=True), Q)
    return out, llm


def test_late_careful_answer_does_not_start_a_grounding_call_nobody_uses(monkeypatch):
    out, llm = _wait_graph(monkeypatch, "0.05", 0.5)
    assert out["kind"] == "answer" and "빠른답" in out["answer"]
    time.sleep(0.8)                          # 늦은 추론 답이 끝난 뒤
    assert llm.count("grounding") == 1       # 쓰인 빠른 답의 확인 하나뿐. 버려진 추론 답의 확인 3표를 시작하지 않는다
    assert out["grounding"].get("ground_ahead") is True


def test_careful_answer_that_arrives_in_time_keeps_its_early_grounding_call(monkeypatch):
    out, llm = _wait_graph(monkeypatch, "3", 0.05)
    assert out["kind"] == "answer" and "느린답" in out["answer"]
    assert out["grounding"].get("ground_ahead") is True           # 쓰인 답의 확인은 지금처럼 미리 불렀고 그 결과를 썼다


# ============================ 서비스 설정과 문서 ============================

def test_three_switches_are_service_defaults_and_no_candidate_switch_is_left():
    from pathlib import Path

    on = {"ANSWER_STORE_REUSE_CONN": "1", "GRAPH_REVISE_AHEAD": "1", "LLM_DEADLINE_BY_TASK": "judge=12"}   # 사용자 결정 11/11 14 A: 서비스 값으로 올림
    assert {k: SP.SERVICE_ENV.get(k) for k in on} == on and not set(on) & set(SP.CANDIDATE_ENV)
    assert SP.CANDIDATE_ENV == {} and "GRAPH_JUDGE_RETRY_FAST" not in SP.SERVICE_ENV   # 추론 끔은 코드째 제거했다
    env: dict = {}
    SP.apply_service_profile(env)
    assert {k: env.get(k) for k in on} == on and "GRAPH_JUDGE_RETRY_FAST" not in env   # 서비스 설정을 채우면 셋은 켜진다
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "GRAPH_JUDGE_RETRY_FAST" not in text
    for name, value in on.items():
        assert f"{name}={value}" in text.splitlines()
