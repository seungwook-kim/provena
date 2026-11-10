"""응답 시간 p95 단축 코드 스위치 시험(사전 등록 62.14~62.19). 가짜 모델, 가짜 임베딩, 메모리 저장소, 가짜 DB 연결만 쓴다(키·네트워크·DB 없음).

- C 검색 hedge(`SEARCH_HEDGE`): 임베딩 + 벡터 질의가 늦으면 같은 일을 한 번 더 보내 먼저 온 결과를 쓴다. 결과는 꺼짐과 같다.
- D 원 질문 첫 검색 일찍 시작(`GRAPH_SPECULATE_EARLY_SEARCH`): 예비 분해와 같은 시각에 시작하고, 분해가 나누거나 경로가 정책이 아니면 버린다.
- E 그래프 밖 왕복(`CHAT_FINAL_FROM_STREAM`, `ANSWER_SAVE_ONE_CONN`): 최종 상태 재조회와 답 저장 연결 수를 줄인다. 저장 내용은 같다.
- B 단계별 hedge 후보(`LLM_HEDGE_BY_TASK`)와 A 답 대기 시간은 서비스 기본값을 바꾸지 않는다.
각 스위치는 꺼진 상태가 지금과 같다는 시험을 함께 둔다.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from api_test_support import Env, ask
from langgraph.checkpoint.memory import InMemorySaver
from qgraph_fakes import j, normal_llm
from test_answer_fixes_graph import ESC, IMOC, Q_ESC, SUBS, cite, llm, mk
from test_answer_fixes_graph import run as run_graph
from test_range_search import MEM_ROWS

from backend.graph import answer_fixes as F
from backend.graph import service_profile as SP
from backend.graph.answer_store import InMemoryAnswerStore, PgAnswerStore
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from backend.graph.stream import stream_events
from backend.rag.retrieve import hedge, translate
from backend.rag.retrieve.embed import EmbedNoKey, EmbedUnavailable
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher, last_search_trace
from backend.schemas.chunk import SearchQuery

SWITCHES = ("SEARCH_HEDGE", "SEARCH_HEDGE_S", "GRAPH_SPECULATE_FIRST", "GRAPH_SPECULATE_EARLY_SEARCH", "CHAT_FINAL_FROM_STREAM", "ANSWER_SAVE_ONE_CONN",
            "LLM_HEDGE_BY_TASK", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_JUDGE_ANSWER",
            "GRAPH_SPECULATE_GROUND", "USE_SKILLS")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


# ============================ C: 검색 hedge ============================

def test_hedged_runs_once_when_the_first_attempt_is_in_time():
    calls: list[int] = []
    value, winner, sent = hedge.hedged(lambda a: calls.append(a) or "ok", 0.5)
    assert (value, winner, sent) == ("ok", 0, False) and calls == [0]


def test_hedged_sends_a_second_attempt_and_takes_the_one_that_comes_first():
    gate = threading.Event()

    def fn(attempt):
        if attempt == 0:
            gate.wait(2.0)     # 첫 시도는 막혀 있다
            return "slow"
        return "fast"

    t = time.monotonic()
    assert hedge.hedged(fn, 0.05) == ("fast", 1, True)
    assert time.monotonic() - t < 1.0
    gate.set()


def test_hedged_first_attempt_error_inside_the_wait_is_raised_without_a_second_attempt():
    calls: list[int] = []

    def fn(attempt):
        calls.append(attempt)
        raise RuntimeError("먼저 난 오류")

    with pytest.raises(RuntimeError, match="먼저 난 오류"):
        hedge.hedged(fn, 0.5)
    assert calls == [0]


def test_hedged_waits_for_the_other_attempt_when_one_fails_and_raises_only_if_both_fail():
    def second_fails(attempt):
        if attempt == 0:
            time.sleep(0.15)
            return "first-ok"
        raise ValueError("둘째 실패")

    assert hedge.hedged(second_fails, 0.05) == ("first-ok", 0, True)

    def both_fail(attempt):
        time.sleep(0.12 if attempt == 0 else 0.0)
        raise ValueError(f"실패 {attempt}")

    with pytest.raises(ValueError, match="실패 1"):    # 먼저 실패한 쪽의 오류
        hedge.hedged(both_fail, 0.05)


def test_hedged_timeout_error_from_the_task_is_not_taken_for_a_hedge_timeout():
    calls: list[int] = []

    def fn(attempt):
        calls.append(attempt)
        raise TimeoutError("소켓 시간 초과")

    with pytest.raises(TimeoutError):
        hedge.hedged(fn, 0.5)
    assert calls == [0]


def test_hedge_env_defaults_and_validation(monkeypatch):
    assert hedge.enabled() is False and hedge.hedge_seconds() == 1.5
    monkeypatch.setenv("SEARCH_HEDGE", "1")
    monkeypatch.setenv("SEARCH_HEDGE_S", "0.8")
    assert hedge.enabled() is True and hedge.hedge_seconds() == 0.8
    for bad in ("0", "-1", "abc"):
        monkeypatch.setenv("SEARCH_HEDGE_S", bad)
        with pytest.raises(ValueError):
            hedge.hedge_seconds()
    with pytest.raises(ValueError):
        SearchConfig(embed_model="voyage-4", hedge_s=0).check()
    assert SearchConfig(embed_model="voyage-4").hedge is False


def test_search_config_from_env_reads_the_hedge_switch(monkeypatch):
    assert SearchConfig.from_env().hedge is False
    monkeypatch.setenv("SEARCH_HEDGE", "1")
    monkeypatch.setenv("SEARCH_HEDGE_S", "2.5")
    cfg = SearchConfig.from_env()
    assert cfg.hedge is True and cfg.hedge_s == 2.5


Q_VEC = np.asarray([1, 0, 0, 0, 0, 0], dtype=np.float32)


class Embedder:
    """처음 부른 호출만 delay초 늦는 가짜 임베딩(같은 입력이면 같은 벡터)."""

    def __init__(self, delay: float = 0.0, error: BaseException | None = None):
        self.delay, self.error, self.n, self.lock = delay, error, 0, threading.Lock()

    def __call__(self, texts):
        with self.lock:
            self.n += 1
            k = self.n
        if k == 1:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
        return np.stack([Q_VEC for _ in texts])


def _searcher(embedder, **cfg) -> Searcher:
    vecs = np.stack([np.asarray(r["_v"], dtype=np.float32) / np.linalg.norm(r["_v"]) for r in MEM_ROWS])
    return Searcher(SearchConfig(embed_model="voyage-4", mode="dense_en", rerank_model="none", link_n=0, **cfg), MemoryStore(MEM_ROWS, vecs, "voyage-4"),
                    embedder=embedder, reranker=None, check_meta=False, translator=lambda query, kind: translate.Result(query, "stored"))


def _ids(chunks):
    return [c.chunk_id for c in chunks]


Q_SEARCH = SearchQuery(query="approval for $30,000 contract", k=5)


def test_search_hedge_off_sends_one_request_and_has_no_hedge_mark():
    emb = Embedder(delay=0.2)
    s = _searcher(emb)
    assert _ids(s.search(Q_SEARCH)) and emb.n == 1
    tr = last_search_trace()
    assert tr.hedged is False and tr.hedge_winner == 0


def test_search_hedge_on_gives_the_same_chunks_and_counts_as_off():
    off = _searcher(Embedder())
    want = _ids(off.search(Q_SEARCH))
    want_trace = last_search_trace()
    emb = Embedder(delay=1.0)     # 첫 요청이 hedge 시간을 넘긴다
    on = _searcher(emb, hedge=True, hedge_s=0.05)
    t = time.monotonic()
    got = _ids(on.search(Q_SEARCH))
    took = time.monotonic() - t
    tr = last_search_trace()
    assert got == want and took < 0.8
    assert emb.n == 2 and tr.hedged is True and tr.hedge_winner == 1
    assert (tr.n_dense, tr.n_bm25, tr.n_filtered, tr.n_returned, tr.mode) == (want_trace.n_dense, want_trace.n_bm25, want_trace.n_filtered, want_trace.n_returned, want_trace.mode)
    assert {"embed", "vector"} <= set(tr.ms) and "total" in tr.ms


def test_search_hedge_on_with_a_fast_first_request_sends_nothing_more():
    emb = Embedder()
    s = _searcher(emb, hedge=True, hedge_s=5.0)
    want = _ids(_searcher(Embedder()).search(Q_SEARCH))
    assert _ids(s.search(Q_SEARCH)) == want and emb.n == 1
    tr = last_search_trace()
    assert tr.hedged is False


def test_search_hedge_keeps_errors_and_the_no_key_result():
    for hedge_on in (False, True):
        s = _searcher(Embedder(error=EmbedNoKey("no key")), hedge=hedge_on, hedge_s=5.0)
        assert s.search(Q_SEARCH) == [] and last_search_trace().fallback_reason == "no_key"
        s = _searcher(Embedder(error=EmbedUnavailable("503")), hedge=hedge_on, hedge_s=5.0)
        with pytest.raises(EmbedUnavailable):
            s.search(Q_SEARCH)


def test_search_hedge_second_request_rescues_a_first_request_that_fails_late():
    emb = Embedder(delay=0.2, error=EmbedUnavailable("늦게 실패"))
    s = _searcher(emb, hedge=True, hedge_s=0.05)
    got = _ids(s.search(Q_SEARCH))
    tr = last_search_trace()
    assert got == _ids(_searcher(Embedder()).search(Q_SEARCH))
    assert tr.hedged is True and tr.hedge_winner == 1


# ============================ D: 원 질문 첫 검색 일찍 시작 ============================

def _graph(multi, fn, m, **kw):
    return build_multi_graph(fn, llm=m, **kw) if multi else build_graph(fn, llm=m, **kw)


def _sp(monkeypatch, multi, *, early, gate, split, route="rule", gate_delay=0.0, search_fn=None):
    monkeypatch.setenv("GRAPH_SPECULATE_FIRST", "1")
    if early:
        monkeypatch.setenv("GRAPH_SPECULATE_EARLY_SEARCH", "1")
    searched: list = []
    times: dict = {}

    def fn(q):
        times.setdefault("search_start", time.monotonic())
        searched.append((q.query, tuple(q.sub_queries or ())))
        if search_fn is not None:
            return search_fn(q)
        return [ESC, IMOC]

    def gate_answer(_u):
        time.sleep(gate_delay)
        times["gate_end"] = time.monotonic()
        return j(split=gate, sub_questions=SUBS if gate else [])

    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), decompose_gate=gate_answer, judge=j(sufficient=True, reason="", clarify=None),
            classify=j(route=route), answer=lambda u: cite(ESC))
    out = run_graph(_graph(multi, fn, m, decompose=True, parallel_intake=True, skip_first_rewrite=True), Q_ESC)
    return out, m, searched, times


def _same_answer(a, b):
    assert a["kind"] == b["kind"] and a["answer"] == b["answer"]
    assert [c["chunk_id"] for c in a.get("citations", [])] == [c["chunk_id"] for c in b.get("citations", [])]


def test_early_search_flag_is_off_by_default_and_reads_the_variable(monkeypatch):
    assert F.speculate_early_search_enabled() is False
    monkeypatch.setenv("GRAPH_SPECULATE_EARLY_SEARCH", "1")
    assert F.speculate_early_search_enabled() is True


@pytest.mark.parametrize("multi", [False, True])
def test_early_search_off_starts_the_search_after_the_gate(monkeypatch, multi):
    out, m, s, t = _sp(monkeypatch, multi, early=False, gate=False, split=False, gate_delay=0.3)
    assert t["search_start"] >= t["gate_end"] and len(s) == 1 and out["search_stats"].get("speculated") == "used"


@pytest.mark.parametrize("multi", [False, True])
def test_early_search_on_starts_the_search_with_the_gate_and_gives_the_same_answer(monkeypatch, multi):
    base, m0, s0, _ = _sp(monkeypatch, multi, early=False, gate=False, split=False, gate_delay=0.3)
    out, m, s, t = _sp(monkeypatch, multi, early=True, gate=False, split=False, gate_delay=0.3)
    assert t["search_start"] < t["gate_end"] - 0.15     # 게이트가 끝나기 전에 검색이 시작됐다
    assert s == s0 and len(s) == 1                       # 같은 검색을 한 번(원 질문 하나)
    assert m.count("judge") == m0.count("judge") == 1 and m.count("decompose_gate") == 1
    _same_answer(out, base)
    assert out["search_stats"].get("speculated") == "used"


@pytest.mark.parametrize("multi", [False, True])
def test_early_search_result_is_dropped_when_the_gate_splits(monkeypatch, multi):
    base, m0, s0, _ = _sp(monkeypatch, multi, early=False, gate=True, split=True)
    out, m, s, _ = _sp(monkeypatch, multi, early=True, gate=True, split=True)
    assert len(s0) == 1 and s0[0][1] == tuple(SUBS)
    assert len(s) == 2 and s[0][1] == () and s[1] == s0[0]      # 일찍 돌린 원 질문 검색은 버리고 하위 질문 검색을 쓴다
    assert out["sub_queries"] == SUBS == base["sub_queries"]
    assert m.count("judge") == m0.count("judge") == 1           # 버린 쪽은 판정까지 가지 않는다
    _same_answer(out, base)
    assert out["search_stats"].get("speculated") == "dropped"


@pytest.mark.parametrize("multi", [False, True])
def test_early_search_result_is_dropped_when_the_split_disagrees_with_the_gate(monkeypatch, multi):
    base, m0, s0, _ = _sp(monkeypatch, multi, early=False, gate=False, split=True)
    out, m, s, _ = _sp(monkeypatch, multi, early=True, gate=False, split=True)
    assert out["sub_queries"] == SUBS == base["sub_queries"] and s[-1] == s0[-1]
    _same_answer(out, base)
    assert out["search_stats"].get("speculated") == "dropped"


def test_early_search_is_dropped_when_the_route_is_not_the_policy_path(monkeypatch):
    base, m0, s0, _ = _sp(monkeypatch, False, early=False, gate=False, split=False, route="out_of_domain")
    out, m, s, _ = _sp(monkeypatch, False, early=True, gate=False, split=False, route="out_of_domain")
    assert out["kind"] == base["kind"] == "refuse" and out["answer"] == base["answer"]
    assert m.count("judge") == 0 and len(s) <= 1 and s0 == []     # 일찍 돌린 검색은 최대 하나이고 결과는 쓰지 않는다


def test_early_search_error_that_is_not_used_does_not_break_the_answer(monkeypatch):
    def only_subs(q):
        if not q.sub_queries:
            raise ValueError("원 질문 검색 오류")
        return [ESC, IMOC]

    base, *_ = _sp(monkeypatch, False, early=False, gate=True, split=True, search_fn=only_subs)
    out, m, s, _ = _sp(monkeypatch, False, early=True, gate=True, split=True, search_fn=only_subs)
    _same_answer(out, base)
    assert out["kind"] == "answer"


def test_early_search_embed_unavailable_ends_like_the_sequential_path(monkeypatch):
    def down(_q):
        raise EmbedUnavailable("503")

    base, m0, *_ = _sp(monkeypatch, False, early=False, gate=False, split=False, search_fn=down)
    out, m, *_ = _sp(monkeypatch, False, early=True, gate=False, split=False, search_fn=down)
    assert out["kind"] == base["kind"] == "refuse" and out["search_error"] == base["search_error"] == "unavailable"
    assert out["answer"] == base["answer"] and m.count("judge") == m0.count("judge") == 0


def test_early_search_off_without_speculate_first_changes_nothing(monkeypatch):
    monkeypatch.setenv("GRAPH_SPECULATE_EARLY_SEARCH", "1")      # SP(GRAPH_SPECULATE_FIRST) 없이는 아무 일도 하지 않는다
    searched: list = []

    def fn(q):
        searched.append(q)
        return [ESC, IMOC]

    m = llm(decompose=j(split=False, sub_questions=[]), judge=j(sufficient=True, reason="", clarify=None), answer=lambda u: cite(ESC))
    out = run_graph(build_graph(fn, llm=m, decompose=True, parallel_intake=True, skip_first_rewrite=True), Q_ESC)
    assert out["kind"] == "answer" and len(searched) == 1 and m.count("decompose_gate") == 0 and "speculated" not in out["search_stats"]


# ============================ E: 그래프 밖 왕복 ============================

def _stream(g, question_input, thread_id):
    vals: dict = {}
    events = list(stream_events(g, question_input, thread_id=thread_id, values_out=vals))
    state = dict(g.get_state({"configurable": {"thread_id": thread_id}}).values)
    return events, vals, state


E_KEYS = ("kind", "as_of", "answer_id", "citations")


@pytest.mark.parametrize("variant", ["answer", "refuse", "clarify", "out_of_domain"])
def test_stream_values_equal_the_final_checkpoint_values_the_chat_route_reads(variant):
    from fake_search import fake_search

    handlers = {"answer": {}, "refuse": {"judge": j(sufficient=False, reason="부족", clarify=None)},
                "clarify": {"judge": j(sufficient=False, reason="모호", clarify="어느 심각도인가요?")}, "out_of_domain": {"classify": j(route="out_of_domain")}}[variant]
    g = build_graph(fake_search, InMemorySaver(), llm=normal_llm(**handlers), answer_store=InMemoryAnswerStore())
    events, vals, state = _stream(g, {"question": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "user_id": "u1", "thread_id": "t9", "as_of": "2025-06-01"}, "t9")
    assert [e.type for e in events][-1] == "done"
    for key in E_KEYS:
        assert vals.get(key) == state.get(key), key
    assert vals["answer"] == state["answer"]


def test_stream_values_out_is_optional_and_the_events_do_not_change():
    from fake_search import fake_search

    g = build_graph(fake_search, InMemorySaver(), llm=normal_llm(), answer_store=InMemoryAnswerStore())
    inp = {"question": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"}
    a = [(e.type, {k: v for k, v in e.data.items() if k != "answer_id"}) for e in stream_events(g, inp, thread_id="t1")]
    b = [(e.type, {k: v for k, v in e.data.items() if k != "answer_id"}) for e in stream_events(g, inp, thread_id="t2", values_out={})]
    assert a == b


class CountingGraph:
    """`get_state` 호출 수를 센다. 나머지는 그래프에 그대로 넘긴다."""

    def __init__(self, graph):
        self._graph, self.get_state_calls = graph, 0

    def __getattr__(self, name):
        return getattr(self._graph, name)

    def get_state(self, *a, **k):
        self.get_state_calls += 1
        return self._graph.get_state(*a, **k)


def _chat(monkeypatch, *, on, **env_kw):
    if on:
        monkeypatch.setenv("CHAT_FINAL_FROM_STREAM", "1")
    with Env(monkeypatch, **env_kw) as env:
        counting = CountingGraph(env.app.state.question_graph)
        env.app.state.question_graph = counting
        c = env.client(env.alice)
        r, ev = ask(c, "SEV2 장애 최초 대응은 몇 분 이내인가요?", "t1", as_of="2025-06-01")
        rec = c.get("/threads/t1").json()
        return ev, counting.get_state_calls, rec


def _stable(ev):
    return [(n, {k: v for k, v in d["data"].items() if k != "answer_id"}) for n, d in ev]


def test_chat_off_reads_the_final_state_and_on_does_not_and_the_events_are_the_same(monkeypatch):
    off_ev, off_calls, off_rec = _chat(monkeypatch, on=False)
    on_ev, on_calls, on_rec = _chat(monkeypatch, on=True)
    assert off_calls == 1 and on_calls == 0                 # 최종 상태 재조회 1회가 없어진다
    assert [n for n, _ in off_ev] == [n for n, _ in on_ev] and [n for n, _ in on_ev][-1] == "done"
    assert _stable(off_ev) == _stable(on_ev)
    assert {k: off_rec["last"][k] for k in ("kind", "answer", "as_of")} == {k: on_rec["last"][k] for k in ("kind", "answer", "as_of")}
    assert on_rec["last"]["answer_id"] and on_rec["status"] == off_rec["status"] == "idle"


def test_chat_on_keeps_the_refusal_path(monkeypatch):
    kw = {"llm": normal_llm(judge=j(sufficient=False, reason="부족", clarify=None))}
    off_ev, _, _ = _chat(monkeypatch, on=False, **kw)
    on_ev, calls, _ = _chat(monkeypatch, on=True, **kw)
    assert calls == 0 and on_ev[-1][1]["data"]["kind"] == "refuse" and on_ev[-1][1]["data"]["code"] == "no_results"
    assert _stable(off_ev) == _stable(on_ev)


# ---------- 답 저장을 연결 하나로 ----------

class FakeConn:
    description = None     # execute()가 돌려주는 결과로도 쓴다(행 없음)

    def __init__(self, log, fail_on=None):
        self.log, self.fail_on = log, fail_on

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.log.append(("close",))
        return False

    def transaction(self):
        log = self.log

        class Tx:
            def __enter__(self_inner):
                log.append(("begin",))

            def __exit__(self_inner, exc_type, *rest):
                log.append(("rollback",) if exc_type else ("commit",))
                return False

        return Tx()

    def cursor(self):
        log = self.log

        class Cur:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def executemany(self_inner, sql, rows):
                log.append(("many", " ".join(sql.split()), [tuple(r) for r in rows]))

        return Cur()

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("근거 기록 저장 실패")
        self.log.append(("exec", text, tuple(getattr(p, "obj", p) for p in (params or ()))))
        return self


def _pg_store(fail_on=None):
    log: list = []
    connects = []

    def connect():
        connects.append(1)
        return FakeConn(log, fail_on)

    return PgAnswerStore(connect=connect), log, connects


CITES = [mk("Merge requests get a first response within 2 business days.", title="Review", seq=70101)]
SAVE_ARGS = ("a1", "u1", "u1:t1", "질문?", "답 [1]", "2025-06-01", CITES)
GROUNDING = {"grounded": True}
SKILLS = ["glossary"]


def test_pg_save_with_grounding_runs_the_same_statements_on_one_connection():
    old, old_log, old_connects = _pg_store()
    old.save(*SAVE_ARGS)
    old.save_grounding("a1", GROUNDING, SKILLS)
    new, new_log, new_connects = _pg_store()
    new.save_with_grounding(*SAVE_ARGS, GROUNDING, SKILLS)
    assert len(old_connects) == 2 and len(new_connects) == 1                  # 연결 수가 2에서 1로
    assert [x for x in old_log if x[0] != "close"] == [x for x in new_log if x[0] != "close"]   # 같은 문장, 같은 값, 같은 순서(트랜잭션 경계 포함)


def test_pg_save_with_grounding_keeps_the_answer_when_the_grounding_write_fails():
    new, log, _ = _pg_store(fail_on="answer_grounding")
    with pytest.raises(RuntimeError):
        new.save_with_grounding(*SAVE_ARGS, GROUNDING, SKILLS)
    kinds = [x[0] for x in log]
    assert kinds[:4] == ["begin", "exec", "many", "commit"]     # 답과 인용은 이미 커밋됐다(지금 save와 save_grounding을 따로 부를 때와 같다)
    old, old_log, _ = _pg_store(fail_on="answer_grounding")
    old.save(*SAVE_ARGS)
    with pytest.raises(RuntimeError):
        old.save_grounding("a1", GROUNDING, SKILLS)
    assert [x[0] for x in old_log if x[0] != "close"][:4] == kinds[:4]


class RecordingStore(InMemoryAnswerStore):
    def __init__(self, with_one: bool):
        super().__init__()
        self.calls: list = []
        if with_one:
            self.save_with_grounding = self._one

    def save(self, *a):
        self.calls.append(("save", a[1:]))
        super().save(*a)

    def save_grounding(self, answer_id, grounding, skills_used):
        self.calls.append(("grounding", grounding, skills_used))
        super().save_grounding(answer_id, grounding, skills_used)

    def _one(self, *a):
        *fields, grounding, skills = a
        self.calls.append(("one", tuple(fields[1:]), grounding, skills))
        super().save(*fields)
        super().save_grounding(fields[0], grounding, skills)


def _saved(monkeypatch, *, on, with_one=True):
    from fake_search import fake_search

    if on:
        monkeypatch.setenv("ANSWER_SAVE_ONE_CONN", "1")
    st = RecordingStore(with_one)
    out = build_graph(fake_search, llm=normal_llm(), answer_store=st, grounding_llm=True).invoke(
        {"question": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    return out, st


def test_answer_save_one_conn_off_keeps_the_two_calls(monkeypatch):
    out, st = _saved(monkeypatch, on=False)
    assert [c[0] for c in st.calls] == ["save", "grounding"] and st.get(out["answer_id"])


def test_answer_save_one_conn_on_saves_the_same_content_with_one_call(monkeypatch):
    off_out, off = _saved(monkeypatch, on=False)
    on_out, on = _saved(monkeypatch, on=True)
    assert [c[0] for c in on.calls] == ["one"]
    assert on.calls[0][1] == off.calls[0][1] and on.calls[0][2] == off.calls[1][1] and on.calls[0][3] == off.calls[1][2]
    assert on.get(on_out["answer_id"])["answer"] == off.get(off_out["answer_id"])["answer"] and on.get_grounding(on_out["answer_id"])


def test_answer_save_one_conn_on_falls_back_for_a_store_without_the_method(monkeypatch):
    out, st = _saved(monkeypatch, on=True, with_one=False)
    assert [c[0] for c in st.calls] == ["save", "grounding"] and st.get(out["answer_id"])


# ============================ B, A: 서비스 기본값은 그대로 ============================

def test_candidates_are_not_in_the_service_profile_and_nothing_turns_on():
    assert set(SP.CANDIDATE_ENV) & set(SP.SERVICE_ENV) == set()
    env: dict = {}
    SP.apply_service_profile(env)
    assert not (set(SP.CANDIDATE_ENV) & set(env))                # 서비스 설정을 채워도 후보 스위치는 켜지지 않는다
    assert SP.SERVICE_ENV["GRAPH_ANSWER_WAIT_S"] == "5.5" and SP.SERVICE_ENV["GRAPH_ANSWER_BUDGET_S"] == "8.0" and SP.SERVICE_ENV["LLM_HEDGE_S"] == "3.5"
    assert "--answer-wait" in SP.MEASURED_ARGS and SP.MEASURED_ARGS[SP.MEASURED_ARGS.index("--answer-wait") + 1] == "5.5"
    assert SP.MEASURE_ONLY_ARGS == ("--answer-wait", "4.0", "--answer-budget", "6.5")


def test_user_given_candidate_values_survive_the_service_profile(monkeypatch):
    env = dict(SP.CANDIDATE_ENV)
    before = SP.apply_service_profile(env)
    assert all(env[k] == v for k, v in SP.CANDIDATE_ENV.items()) and not (set(before) & set(SP.CANDIDATE_ENV))


def test_hedge_by_task_candidate_is_read_by_the_llm_layer_and_the_stages_exist(monkeypatch):
    from backend.graph import decompose as D
    from backend.prompts import question as Pq
    from backend.services.llm import hedge_by_task

    monkeypatch.setenv("LLM_HEDGE_BY_TASK", SP.CANDIDATE_ENV["LLM_HEDGE_BY_TASK"])
    assert hedge_by_task() == {"classify": 1.2, "decompose_gate": 1.2, "decompose": 2.0}
    assert Pq.CLASSIFY_SYSTEM.startswith("[[task:classify]]") and D.SYSTEM_GATE.startswith("[[task:decompose_gate]]") and D.SYSTEM_TAGGED.startswith("[[task:decompose]]")


def test_env_example_lists_the_candidates_only_as_comments():
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    for name in SP.CANDIDATE_ENV:
        assert any(line.lstrip().startswith("#") and f"{name}=" in line for line in text.splitlines()), name
        assert not any(line.startswith(f"{name}=") for line in text.splitlines()), name


def test_measurement_runner_takes_the_new_switches_and_the_answer_wait_arguments_only_on_the_command_line():
    import evals.agent.exp_multi_v2 as M
    from test_exp_multi import MODEL_OFF, _parse

    args = _parse(["--speculate-first", "--speculate-early-search", "--search-hedge", "1.5"])
    assert M.chosen_model_switches(args) == {**MODEL_OFF, "GRAPH_SPECULATE_FIRST": "1", "GRAPH_SPECULATE_EARLY_SEARCH": "1", "SEARCH_HEDGE": "1", "SEARCH_HEDGE_S": "1.5"}
    args = _parse([*SP.MEASURE_ONLY_ARGS])
    assert M.chosen_model_switches(args) == {**MODEL_OFF, "GRAPH_ANSWER_WAIT_S": "4.0", "GRAPH_ANSWER_BUDGET_S": "6.5"}
    args = _parse(["--llm-hedge-by-task", "classify=1.2,decompose_gate=1.2,decompose=2.0"])
    assert M.chosen_model_switches(args) == {**MODEL_OFF, "LLM_HEDGE_BY_TASK": "classify=1.2,decompose_gate=1.2,decompose=2.0"}
