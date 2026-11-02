"""질문 그래프 시험 (docs/specs/question-graph.md AC). 키 없이 가짜 모델과 합성 코퍼스로 돈다."""
from __future__ import annotations

from fake_search import fake_search
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from qgraph_fakes import ScriptedLLM, answer_with_top_chunk, first_chunk_id, j, normal_llm

from backend.graph.answer_store import AnswerStore, InMemoryAnswerStore
from backend.graph.build import build_graph
from backend.graph.parsing import parse_json_obj
from backend.graph.stream import stream_events
from backend.memory import delete_profile, get_profile, put_profile
from backend.schemas import Chunk

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
FAKE_ID = "deadbeefdeadbeef"


def graph(search_fn=fake_search, **kw):
    return build_graph(search_fn, **kw)


def run(g, **kw):
    base = {"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"}
    base.update(kw)
    return g.invoke(base)


def counting_search():
    calls = []

    def fn(q):
        calls.append(q)
        return fake_search(q)

    return fn, calls


# ---------- 정상 답 ----------
def test_normal_answer_with_citation_and_saved():
    st = InMemoryAnswerStore()
    llm = normal_llm()
    out = run(graph(llm=llm, answer_store=st))
    assert out["kind"] == "answer"
    assert out["as_of"] == "2025-06-01"
    assert len(out["citations"]) == 1
    c = Chunk(**out["citations"][0])
    assert c.rule_seq == 90002 and c.article == "Incident Response > Paging" and c.version_id.endswith("20250101")
    assert "[1]" in out["answer"] and out["citations"][0]["chunk_id"] not in out["answer"]
    assert "2025-01-01" in out["answer"] and "CC BY-SA 4.0" in out["answer"]
    # 저장되어 리콜이 섹션으로 찾을 수 있다
    assert isinstance(st, AnswerStore)
    found = st.find_by_article(90002, "Incident Response > Paging")
    assert len(found) == 1
    assert set(found[0]) == {"answer_id", "user_id", "question", "answer", "as_of", "version_id"}
    assert found[0]["version_id"] == c.version_id and found[0]["user_id"] == "u1"
    assert st.find_by_article(90002, "Incident Response > Escalation") == []


def test_prompts_wrap_source_text_as_material():
    llm = normal_llm()
    run(graph(llm=llm))
    judge_user = next(u for t, u in llm.calls if t == "judge")
    assert "<<<자료>>>" in judge_user and "<<<끝>>>" in judge_user


# ---------- 재검색 2회 후 거절 ----------
def distinct_rewrites():
    """재작성이 매번 다른 질의를 낸다(같은 질의면 검색 기억이 앞 결과를 쓰므로, 재검색이 실제로 도는 경로를 보려면 다른 질의가 필요하다)."""
    n = iter(range(100))
    return lambda user: j(query=f"SEV2 최초 대응 {next(n)}", org="TEST-security", as_of=None)


def test_refuse_after_two_researches():
    fn, calls = counting_search()
    llm = normal_llm(judge=j(sufficient=False, reason="부족", clarify=None), rewrite=distinct_rewrites())
    out = run(graph(fn, llm=llm, answer_store=InMemoryAnswerStore()))
    assert out["kind"] == "refuse"
    assert len(calls) == 3  # 첫 검색 + 재검색 2회
    assert llm.count("judge") == 3 and llm.count("answer") == 0
    assert out["citations"] == []


def test_clarify_question_when_judge_asks():
    llm = normal_llm(judge=j(sufficient=False, reason="절 불명", clarify="어느 절 기준인가요?"))
    out = run(graph(llm=llm))
    assert out["kind"] == "clarify" and out["answer"] == "어느 절 기준인가요?"


def test_recovers_on_second_search():
    fn, calls = counting_search()
    llm = normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)], rewrite=distinct_rewrites())
    out = run(graph(fn, llm=llm))
    assert out["kind"] == "answer" and len(calls) == 2


def test_recovers_on_second_judge_with_same_query_searches_once():
    fn, calls = counting_search()
    llm = normal_llm(judge=[j(sufficient=False, reason="x", clarify=None), j(sufficient=True)])
    out = run(graph(fn, llm=llm))
    assert out["kind"] == "answer" and len(calls) == 1 and llm.count("judge") == 2  # 같은 질의의 재검색은 기억에서


def test_garbage_llm_output_uses_safe_defaults():
    llm = ScriptedLLM({"classify": "??", "rewrite": "not json", "judge": "}{", "answer": "x"})
    out = run(graph(llm=llm))
    assert out["kind"] == "refuse"  # 판정 파싱 실패 -> 부족 -> 거절. 예외 없음


def test_default_fake_model_does_not_crash(monkeypatch):
    """키 없는 기본 모델(데모 재생 모델, 녹화 없음)이면 결정적 가짜 응답으로 검색된 근거를 인용해 답한다."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_REPLAY_DIR", "nonexistent-dir-for-test")
    out = run(graph())
    assert out["kind"] == "answer" and out["citations"] and "[1]" in out["answer"]


# ---------- 인용 검사 ----------
def test_citation_check_filters_fake_citation():
    """GATES 후보: backend/graph/citations.py의 코퍼스 대조 한 줄을 깨면 실패한다."""
    st = InMemoryAnswerStore()

    def ans(user):
        cid = first_chunk_id(user)
        return j(
            answer=f"대응 시간은 정해져 있다 [{cid}] 그리고 [{FAKE_ID}] 도 근거다.",
            citations=[{"chunk_id": cid}, {"chunk_id": FAKE_ID}],
        )

    out = run(graph(llm=normal_llm(answer=ans), answer_store=st))
    assert out["kind"] == "answer"
    ids = [c["chunk_id"] for c in out["citations"]]
    assert FAKE_ID not in ids and len(ids) == 1
    assert FAKE_ID not in out["answer"]
    assert out["dropped_citations"] == [{"chunk_id": FAKE_ID}]
    assert all(c.chunk_id != FAKE_ID for rec in st.all_answers() for c in rec["citations"])


def test_citation_with_wrong_article_is_dropped():
    def ans(user):
        cid = first_chunk_id(user)
        return j(answer=f"답 [{cid}]", citations=[{"chunk_id": cid, "article": "Nonexistent > Missing"}])

    out = run(graph(llm=normal_llm(answer=ans)))
    assert out["kind"] == "refuse" and out["citations"] == [] and len(out["dropped_citations"]) == 1


def test_only_fake_citations_refuses_and_not_saved():
    st = InMemoryAnswerStore()
    llm = normal_llm(answer=j(answer=f"답 [{FAKE_ID}]", citations=[{"chunk_id": FAKE_ID}]))
    out = run(graph(llm=llm, answer_store=st))
    assert out["kind"] == "refuse" and st.all_answers() == []


def test_non_json_answer_has_no_citations_so_refused():
    out = run(graph(llm=normal_llm(answer="그냥 문장입니다.")))
    assert out["kind"] == "refuse"


# ---------- 기억 / namespace ----------
def test_memory_profile_used_for_org():
    store = InMemoryStore()
    put_profile(store, "u1", affiliation="TEST-finance", rank="매니저")
    fn, calls = counting_search()
    llm = normal_llm(rewrite=j(query="승인자 도입 승인", org=None, as_of=None))
    out = run(graph(fn, llm=llm, store=store))
    assert out["profile"] == {"affiliation": "TEST-finance", "rank": "매니저"}
    assert calls[0].org == "TEST-finance"
    rewrite_user = next(u for t, u in llm.calls if t == "rewrite")
    assert "TEST-finance" in rewrite_user


def test_store_namespace_is_per_user():
    store = InMemoryStore()
    put_profile(store, "alice", affiliation="TEST-security", rank="디렉터")
    put_profile(store, "bob", affiliation="TEST-finance")
    assert get_profile(store, "alice") == {"affiliation": "TEST-security", "rank": "디렉터"}
    assert get_profile(store, "bob") == {"affiliation": "TEST-finance"}
    assert get_profile(store, "carol") == {}
    assert store.get(("alice", "profile"), "me") is not None and store.get(("bob", "profile"), "me").value["affiliation"] == "TEST-finance"
    delete_profile(store, "alice")
    assert get_profile(store, "alice") == {} and get_profile(store, "bob") != {}


def test_graph_does_not_leak_profile_across_users():
    store = InMemoryStore()
    put_profile(store, "alice", affiliation="TEST-finance")
    llm = normal_llm(rewrite=j(query="승인", org=None, as_of=None))
    out = run(graph(llm=llm, store=store), user_id="bob")
    assert out["profile"] == {}


def test_put_profile_ignores_unknown_fields_and_partial_update():
    store = InMemoryStore()
    put_profile(store, "u", affiliation="A")
    put_profile(store, "u", rank="B")
    assert get_profile(store, "u") == {"affiliation": "A", "rank": "B"}
    store.put(("u", "profile"), "me", {"affiliation": "A", "secret": "x"})
    assert get_profile(store, "u") == {"affiliation": "A"}


# ---------- 스트림 어댑터 ----------
def test_stream_events_token_citation_done():
    g = graph(llm=normal_llm(), answer_store=InMemoryAnswerStore())
    ev = list(stream_events(g, {"question": Q, "user_id": "u1", "thread_id": "t9", "as_of": "2025-06-01"}, thread_id="t9"))
    types = [e.type for e in ev]
    assert types[0] == "token" and types[-1] == "done" and types.count("citation") == 1
    assert all(e.thread_id == "t9" for e in ev)
    assert "".join(e.data["text"] for e in ev if e.type == "token").startswith("근거에 따라")
    assert ev[-1].data["answer_id"]
    cite = next(e for e in ev if e.type == "citation")
    assert set(cite.data) == {"chunk_id", "rule_title", "article", "version_date", "version_date_before", "source_url"}


def test_stream_events_error():
    def boom(q):
        raise RuntimeError("검색 실패")

    g = graph(boom, llm=normal_llm())
    ev = list(stream_events(g, {"question": Q, "user_id": "u", "thread_id": "t"}, thread_id="t"))
    assert [e.type for e in ev] == ["error"] and "검색 실패" in ev[0].data["message"]


# ---------- 파서 ----------
def test_parse_helpers():
    assert parse_json_obj('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_obj('설명입니다 {"a": 2} 끝') == {"a": 2}
    assert parse_json_obj("nope") is None and parse_json_obj(None) is None and parse_json_obj("[1]") is None


# ---------- 형식이 깨진 응답 (EC-06) ----------
def test_broken_json_is_asked_once_more():
    llm = normal_llm(judge=["}{", j(sufficient=True)])
    out = run(graph(llm=llm))
    assert out["kind"] == "answer" and llm.count("judge") == 2


# ---------- 재검색 상한 (AC-03): 상수가 아니라 리터럴과 비교한다 ----------
def test_ac03_search_is_called_exactly_three_times():
    fn, calls = counting_search()
    n = iter(range(100))
    llm = normal_llm(judge=j(sufficient=False, reason="부족", clarify=None), rewrite=lambda u: j(query=f"질의 {next(n)}", org=None, as_of=None))
    out = run(graph(fn, llm=llm))
    assert len(calls) == 3 and out["kind"] == "refuse" and out["citations"] == []


# ---------- 기준일 (AC-05, EC-04) ----------
def test_ac05_citations_are_not_later_than_as_of():
    out = run(graph(llm=normal_llm()), as_of="2024-01-01")
    assert out["kind"] == "answer" and all(c["version_date"] <= "2024-01-01" for c in out["citations"])


def test_impossible_as_of_from_llm_is_ignored():
    llm = normal_llm(rewrite=j(query="SEV2 최초 대응", org=None, as_of="2026-02-30"))
    out = run(graph(llm=llm), as_of=None)
    assert out["kind"] == "answer" and out["as_of"] != "2026-02-30"


# ---------- 라우팅 ----------
def test_unconnected_routes_are_answered_as_policy_questions():
    for route in ("decision", "review"):
        fn, calls = counting_search()
        out = run(graph(fn, llm=normal_llm(classify=j(route=route))))
        assert out["route"] == route and len(calls) == 1 and out["kind"] == "answer"


def test_unknown_route_becomes_rule():
    out = run(graph(llm=normal_llm(classify=j(route="없는 경로"))))
    assert out["route"] == "rule" and out["kind"] == "answer"


# ---------- 근거 판정 ----------
def test_grounding_rule_refuses_missing_entity_after_draft():
    out = run(graph(llm=normal_llm()), question="SEV9 장애 최초 대응은 몇 분 이내인가요?")
    assert out["kind"] == "refuse" and out["refuse_reason"] == "nonexistent_entity" and out["drafted"] is True


def test_grounding_llm_can_refuse():
    llm = normal_llm(grounding=j(grounded=False, reason_code="unsupported", reason="기한이 다름"))
    out = run(graph(llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["citations"] == []
    assert "기한이 다름" not in out["answer"] and out["grounding"]["detail"] == "기한이 다름"


# ---------- 체크포인터 ----------
def test_memory_checkpointer_keeps_thread_state():
    g = graph(llm=normal_llm(), checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "tk"}}
    g.invoke({"question": Q, "user_id": "u1", "thread_id": "tk", "as_of": "2025-06-01"}, cfg)
    assert g.get_state(cfg).values["kind"] == "answer"
