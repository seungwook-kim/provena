"""질문 그래프 시험 (docs/specs/question-graph.md AC). 키 없이 가짜 모델과 합성 코퍼스로 돈다."""
from __future__ import annotations

from fake_search import fake_search
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from qgraph_fakes import ScriptedLLM, answer_with_top_chunk, first_chunk_id, j, normal_llm

from backend.graph.answer_store import AnswerStore, InMemoryAnswerStore
from backend.graph.build import MSG_REFUSE, build_graph
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
    assert set(found[0]) >= {"answer_id", "user_id", "question", "answer", "as_of", "version_id"}      # 리콜이 쓰는 thread_id, version_date, source_url이 더 붙는다
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


def test_replay_demo_ignores_saved_profile(tmp_path):
    """K-18: 키 없는 데모(재생 모델)는 저장한 기억을 입력에 넣지 않는다. 녹화는 기억 없는 요청이라 기억이 들어가면 녹화 키가 어긋난다."""
    from backend.services.demo_replay import ReplayChatModel, ReplayStore

    store = InMemoryStore()
    put_profile(store, "u1", affiliation="TEST-finance", rank="매니저")
    fn, calls = counting_search()
    out = run(graph(fn, llm=ReplayChatModel(store=ReplayStore(tmp_path)), store=store))
    assert out["profile"] == {}
    assert calls and all(c.org is None for c in calls)
    assert get_profile(store, "u1") == {"affiliation": "TEST-finance", "rank": "매니저"}  # 저장된 기억은 그대로


def test_replay_demo_ignores_saved_profile_when_wrapped_like_server(tmp_path, monkeypatch):
    """K-18: 서버(`backend/main.py`의 `build_question_graph`)는 모델을 `SharedChatModel`로 감싸 넘긴다. 감싼 재생 모델에서도 기억을 넣지 않는다."""
    from backend.graph.service_profile import SharedChatModel
    from backend.services.demo_replay import ReplayChatModel, ReplayStore

    monkeypatch.setattr("backend.services.llm.get_chat_model", lambda: ReplayChatModel(store=ReplayStore(tmp_path)))
    store = InMemoryStore()
    put_profile(store, "u1", affiliation="TEST-finance", rank="매니저")
    fn, calls = counting_search()
    shared = SharedChatModel()
    g = graph(fn, llm=shared, store=store)
    assert shared._model is None  # 그래프를 만들 때는 모델을 만들지 않는다(키 없이도 서버가 뜬다)
    out = run(g)
    assert isinstance(shared._model, ReplayChatModel)
    assert out["profile"] == {}
    assert calls and all(c.org is None for c in calls)
    assert get_profile(store, "u1") == {"affiliation": "TEST-finance", "rank": "매니저"}


def test_wrapped_real_model_still_uses_saved_profile(monkeypatch):
    """K-18: 감싼 모델이 재생 모델이 아니면(키 있는 서버) 기억을 그대로 쓴다."""
    from backend.graph.service_profile import SharedChatModel

    llm = normal_llm(rewrite=j(query="승인자 도입 승인", org=None, as_of=None))
    monkeypatch.setattr("backend.services.llm.get_chat_model", lambda: llm)
    store = InMemoryStore()
    put_profile(store, "u1", affiliation="TEST-finance", rank="매니저")
    fn, calls = counting_search()
    out = run(graph(fn, llm=SharedChatModel(), store=store))
    assert out["profile"] == {"affiliation": "TEST-finance", "rank": "매니저"}
    assert calls[0].org == "TEST-finance"


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


# ---------- 재검색 결과 합치기 (수정 A) ----------
def _by_article(article, version_date="2025-01-01"):
    from fake_search import _CORPUS

    return next(c for c in _CORPUS if c.article == article and c.version_date == version_date)


def test_merge_chunks_keeps_previous_dedups_and_caps():
    from backend.graph.build import MAX_CHUNKS, merge_chunks

    def mk(i, v="v"):
        return {"chunk_id": f"{i:016x}", "version_id": v}

    def ids(chunks):
        return [c["chunk_id"] for c in chunks]

    prev = [mk(0), mk(1), mk(2)]
    got = merge_chunks(prev, [mk(2), mk(3), mk(1, "other"), mk(4)])
    assert ids(got) == [f"{i:016x}" for i in (0, 1, 2, 3, 1, 4)]  # 같은 chunk_id라도 판이 다르면 다른 청크
    assert ids(merge_chunks(prev, [])) == ids(prev)
    assert ids(merge_chunks([], prev)) == ids(prev)
    capped = merge_chunks([mk(i) for i in range(8)], [mk(i) for i in range(8, 20)])
    assert len(capped) == 10 == MAX_CHUNKS
    assert ids(capped) == [f"{i:016x}" for i in range(10)]  # 앞 결과가 먼저 남고 새 청크는 상한까지만
    assert len(merge_chunks([mk(i) for i in range(12)], [], limit=10)) == 10


def test_requery_keeps_first_search_chunks_so_their_citation_survives():
    """6번 문항 경로: 첫 검색에서 찾은 정답이 재검색 뒤에도 근거 목록에 있어야 인용 검사를 통과한다."""
    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    f1 = _by_article("Adoption Policy > Review Request", "2024-05-01")
    f2 = _by_article("Adoption Policy > Contingency", "2024-05-01")
    f3 = _by_article("Adoption Policy > Simplified Adoption", "2024-05-01")
    results = [[paging, f1, f2], [escal, f1, f3]]
    calls = []

    def retriever(q):
        calls.append(q)
        return results[len(calls) - 1]

    llm = normal_llm(
        judge=[j(sufficient=False, reason="부족", clarify=None), j(sufficient=True)],
        rewrite=distinct_rewrites(),
        answer=lambda u: j(answer=f"최초 대응은 15분 이내이다 [{paging.chunk_id}]", citations=[{"chunk_id": paging.chunk_id}]),
    )
    out = run(graph(retriever, llm=llm))
    assert len(calls) == 2
    assert [c["chunk_id"] for c in out["chunks"]] == [c.chunk_id for c in (paging, f1, f2, escal, f3)]  # 앞 결과 유지, 중복 한 번, 새 청크는 뒤
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["citations"]] == [paging.chunk_id] and out["dropped_citations"] == []
    second_judge = [u for t, u in llm.calls if t == "judge"][1]
    assert paging.chunk_id in second_judge and escal.chunk_id in second_judge  # 판단이 합친 목록을 본다
    answer_user = next(u for t, u in llm.calls if t == "answer")
    assert all(c.chunk_id in answer_user for c in (paging, f1, f2, escal, f3))  # 답 작성도 합친 목록을 본다


def test_merged_list_is_capped_and_search_count_stays_three():
    from fake_search import _CORPUS

    pool = list(_CORPUS)
    assert len(pool) >= 15
    batches = [pool[0:5], pool[5:10], pool[10:15]]
    calls = []

    def retriever(q):
        calls.append(q)
        return batches[len(calls) - 1]

    llm = normal_llm(judge=j(sufficient=False, reason="부족", clarify=None), rewrite=distinct_rewrites())
    out = run(graph(retriever, llm=llm))
    assert len(calls) == 3 and out["kind"] == "refuse"
    assert [c["chunk_id"] for c in out["chunks"]] == [c.chunk_id for c in pool[:10]]  # 상한 10, 세 번째 검색의 새 청크는 들어오지 못한다


# ---------- 되묻기 제한 (수정 B) ----------
def test_clarify_with_a_number_becomes_a_refusal():
    """28번 경로: 판단이 인용 없이 수치를 담은 되묻기를 내면 사용자에게 보이지 않고 거절로 바꾼다."""
    for text in ("99.74%가 맞나요?", "SEV 1이 맞는 등급인가요?", "사업소득 3.3% 원천징수 대상인가요?", "2024년 3월에 5일 이내인가요?"):
        llm = normal_llm(judge=j(sufficient=False, reason="부족", clarify=text))
        out = run(graph(llm=llm))
        assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and out["citations"] == [], text
        assert text not in out["answer"]
        assert out["clarify_question"] == text  # 기록에는 남는다


def test_clarify_about_section_or_period_is_kept():
    from backend.graph.build import clarify_has_number

    for text in ("어느 절 기준인가요?", "2023년 기준인가요?", "2024-05-01 이전 판을 말씀하시나요?", "2024년 3월 기준인가요, 아니면 이후 기준인가요?"):
        assert not clarify_has_number(text), text
        out = run(graph(llm=normal_llm(judge=j(sufficient=False, reason="시점 불명", clarify=text))))
        assert out["kind"] == "clarify" and out["answer"] == text
    assert clarify_has_number("99.74%") and not clarify_has_number("SEV2") and clarify_has_number("30분 이내") and not clarify_has_number("")


def test_judge_prompt_limits_clarify_to_missing_section_or_period():
    from backend.prompts.question import JUDGE_SYSTEM

    assert "절(핸드북 섹션)이나 기준 시점이 빠져" in JUDGE_SYSTEM and "그 밖에는 clarify를 null" in JUDGE_SYSTEM
    assert "사용자에게 문서나 자료를 달라고 하지 않는다" in JUDGE_SYSTEM


# ---------- 도메인 밖 경로 (수정 C) ----------
def test_out_of_domain_refuses_without_rewrite_or_search():
    from backend.graph.build import MSG_REFUSE_OUT_OF_DOMAIN

    fn, calls = counting_search()
    st = InMemoryAnswerStore()
    llm = normal_llm(classify=j(route="out_of_domain"))
    out = run(graph(fn, llm=llm, answer_store=st))
    assert out["route"] == "out_of_domain" and out["kind"] == "refuse" and out["answer"] == MSG_REFUSE_OUT_OF_DOMAIN
    assert len(calls) == 0 and out["citations"] == [] and st.all_answers() == [] and llm.count("classify") == 2
    assert llm.count("rewrite") == 0 and llm.count("judge") == 0 and llm.count("answer") == 0
    assert not out.get("drafted") and not out.get("refuse_reason")  # 답 단계 거절이 아니라 답 초안 전 거절이다


def test_out_of_domain_needs_two_same_answers_and_a_split_goes_to_policy_path():
    fn, calls = counting_search()
    llm = normal_llm(classify=[j(route="out_of_domain"), j(route="rule")])
    out = run(graph(fn, llm=llm))
    assert out["route"] == "rule" and out["kind"] == "answer" and len(calls) == 1 and llm.count("classify") == 2


def test_other_routes_are_classified_once():
    fn, _ = counting_search()
    llm = normal_llm(classify=j(route="rule"))
    run(graph(fn, llm=llm))
    assert llm.count("classify") == 1


def test_answer_prompt_limits_scope_and_citations_per_fact():
    from backend.prompts.question import ANSWER_SYSTEM

    assert "질문이 묻는 사실에만 답한다" in ANSWER_SYSTEM and "가장 직접적인 근거 하나만" in ANSWER_SYSTEM


def test_policy_routes_still_search_and_answer():
    for route in ("rule", "decision", "review"):
        fn, calls = counting_search()
        out = run(graph(fn, llm=normal_llm(classify=j(route=route))))
        assert out["kind"] == "answer" and len(calls) == 1, route


def test_ambiguous_or_broken_classification_goes_to_policy_path():
    for raw in ("??", "", j(route=None), j(route="Out_Of_Domain"), j(route="unknown"), "{"):
        fn, calls = counting_search()
        out = run(graph(fn, llm=normal_llm(classify=raw)))
        assert out["route"] == "rule" and out["kind"] == "answer" and len(calls) == 1, raw


def test_out_of_domain_is_not_followed_when_the_model_says_the_question_is_about_the_organization():
    """62.30: 모델이 조직이 정한 것을 묻는 질문이라고 적고도 도메인 밖으로 분류하면 정책 경로로 보낸다(두 번째 확인 호출 없이)."""
    fn, calls = counting_search()
    llm = normal_llm(classify=j(org_specific=True, route="out_of_domain"))
    out = run(graph(fn, llm=llm))
    assert out["route"] == "rule" and out["kind"] == "answer" and len(calls) == 1 and llm.count("classify") == 1


def test_out_of_domain_with_org_specific_false_still_refuses_without_search():
    from backend.graph.build import MSG_REFUSE_OUT_OF_DOMAIN

    fn, calls = counting_search()
    llm = normal_llm(classify=j(org_specific=False, route="out_of_domain"))
    out = run(graph(fn, llm=llm))
    assert out["route"] == "out_of_domain" and out["answer"] == MSG_REFUSE_OUT_OF_DOMAIN and len(calls) == 0 and llm.count("classify") == 2
    assert llm.count("rewrite") == 0 and llm.count("judge") == 0 and llm.count("answer") == 0


def test_second_vote_saying_org_specific_sends_the_question_to_the_policy_path():
    fn, calls = counting_search()
    llm = normal_llm(classify=[j(org_specific=False, route="out_of_domain"), j(org_specific=True, route="out_of_domain")])
    out = run(graph(fn, llm=llm))
    assert out["route"] == "rule" and out["kind"] == "answer" and len(calls) == 1 and llm.count("classify") == 2


def test_route_of_reads_the_reply_and_only_true_overrides_out_of_domain():
    from backend.graph.build import route_of

    assert route_of({"route": "out_of_domain"}) == "out_of_domain"  # 칸이 없으면 분류를 그대로 따른다
    assert route_of({"org_specific": False, "route": "out_of_domain"}) == "out_of_domain"
    assert route_of({"org_specific": True, "route": "out_of_domain"}) == "rule"
    for loose in ("true", 1, "yes", None):  # 참 값 하나만 뒤집는다. 글자나 숫자는 뒤집지 않는다
        assert route_of({"org_specific": loose, "route": "out_of_domain"}) == "out_of_domain", loose
    for route in ("rule", "decision", "review"):  # 다른 경로는 이 칸과 무관하다
        assert route_of({"org_specific": False, "route": route}) == route and route_of({"org_specific": True, "route": route}) == route
    for broken in (None, {}, [], "rule", {"route": None}, {"route": "Out_Of_Domain"}, {"org_specific": False}):
        assert route_of(broken) == "rule", broken


def test_classify_prompt_separates_general_knowledge_from_what_the_organization_set():
    from backend.prompts.question import CLASSIFY_SYSTEM

    assert "주제가 아니라 무엇을 묻는지로 가린다" in CLASSIFY_SYSTEM and "검색한 뒤에 판정하므로 여기서 따지지 않는다" in CLASSIFY_SYSTEM
    assert "org_specific" in CLASSIFY_SYSTEM and '{"org_specific": true, "route": "rule"}' in CLASSIFY_SYSTEM


def test_classify_prompt_names_out_of_domain_and_defaults_to_rule():
    from backend.prompts.question import CLASSIFY_SYSTEM

    assert "out_of_domain" in CLASSIFY_SYSTEM and "모호하면 rule로 분류한다" in CLASSIFY_SYSTEM


# ---------- 인용 범위 (수정 1) ----------
def _six_chunks():
    from fake_search import _CORPUS

    return list(_CORPUS[:6])


def _answer_marking(ids_in_body, ids_in_list):
    body = " ".join(f"문장 {i} [{c}]." for i, c in enumerate(ids_in_body))
    return lambda user: j(answer=body, citations=[{"chunk_id": c} for c in ids_in_list])


def test_citation_cap_keeps_first_four_in_body_order_and_records_trimmed():
    """인용 상한: 본문에 먼저 나온 4개만 남기고 나머지는 `trimmed_citations`에 둔다. 가짜 인용이 아니므로 `dropped_citations`는 비어 있다."""
    from backend.graph.build import MAX_CITATIONS

    chunks = _six_chunks()
    ids = [c.chunk_id for c in chunks]
    body_order = [ids[5], ids[0], ids[3], ids[1], ids[4], ids[2]]
    llm = normal_llm(answer=_answer_marking(body_order, ids))
    out = run(graph(lambda q: chunks, llm=llm), question="일반 질문입니다")
    assert MAX_CITATIONS == 4
    assert out["kind"] == "answer"
    assert [c["chunk_id"] for c in out["citations"]] == body_order[:4]
    assert out["trimmed_citations"] == [c for c in ids if c not in body_order[:4]]
    assert out["dropped_citations"] == []
    assert all(t not in out["answer"] for t in body_order[4:]) and "[5]" not in out["answer"]


def test_citation_not_marked_in_body_is_not_kept():
    chunks = _six_chunks()
    ids = [c.chunk_id for c in chunks]
    llm = normal_llm(answer=_answer_marking([ids[0]], [ids[0], ids[1], ids[2]]))
    out = run(graph(lambda q: chunks, llm=llm), question="일반 질문입니다")
    assert [c["chunk_id"] for c in out["citations"]] == [ids[0]] and out["trimmed_citations"] == [ids[1], ids[2]]


def test_citations_without_any_body_mark_follow_list_order_up_to_cap():
    from backend.graph.build import select_citations

    valid = [{"chunk_id": f"{i:016x}"} for i in range(6)]
    kept, trimmed, text = select_citations(valid, "표시 없는 답입니다.")
    assert [c["chunk_id"] for c in kept] == [f"{i:016x}" for i in range(4)] and len(trimmed) == 2 and text == "표시 없는 답입니다."
    kept, trimmed, _ = select_citations(valid[:3], "답 [" + valid[2]["chunk_id"] + "]")
    assert [c["chunk_id"] for c in kept] == [valid[2]["chunk_id"]] and len(trimmed) == 2


def test_two_citations_are_untouched():
    chunks = _six_chunks()
    ids = [c.chunk_id for c in chunks]
    llm = normal_llm(answer=_answer_marking([ids[1], ids[0]], [ids[0], ids[1]]))
    out = run(graph(lambda q: chunks, llm=llm), question="일반 질문입니다")
    assert [c["chunk_id"] for c in out["citations"]] == [ids[1], ids[0]] and out["trimmed_citations"] == []


def test_answer_prompt_asks_for_directly_supporting_chunks_with_the_same_cap():
    from backend.prompts.question import ANSWER_SYSTEM, MAX_CITATIONS

    assert MAX_CITATIONS == 4 and "4개 이하" in ANSWER_SYSTEM
    assert "직접 받치는 근거" in ANSWER_SYSTEM and "답에 표시한 chunk_id만" in ANSWER_SYSTEM
    assert "답에 쓰지 않은 자료는 citations에 넣지 않는다" in ANSWER_SYSTEM


# ---------- 근거 판정의 부분 제거 (수정 2) ----------
def _sentences_answer(*pairs):
    """(문장, 청크) 쌍으로 답과 인용을 만든다."""
    body = " ".join(f"{text} [{cid}]." for text, cid in pairs)
    cites = list(dict.fromkeys(cid for _, cid in pairs))
    return j(answer=body, citations=[{"chunk_id": c} for c in cites])


def _partial_setup(claims, second=None, three=True):
    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    s1, s2, s3 = "SEV2 장애 최초 대응은 15분 이내이다", "담당자가 직접 호출한다", "에스컬레이션은 2시간 상한이다"
    pairs = [(s1, paging.chunk_id), (s2, paging.chunk_id)] + ([(s3, escal.chunk_id)] if three else [])

    def grounding(user):
        if second is not None and "<<<답>>>" in user and s3 not in user:
            return second
        return j(grounded=False, reason_code="unsupported", reason="2시간이 자료와 다름", unsupported_sentences=claims(s1, s2, s3))

    llm = normal_llm(answer=_sentences_answer(*pairs), grounding=grounding)
    return llm, paging, escal, (s1, s2, s3)


def test_unsupported_sentence_is_removed_and_the_answer_is_kept():
    llm, paging, escal, (s1, s2, s3) = _partial_setup(lambda a, b, c: [f"{c} [{_by_article('Incident Response > Escalation').chunk_id}]."], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True, answer_store=InMemoryAnswerStore()))
    assert out["kind"] == "answer" and not out.get("refuse_reason")
    assert s1 in out["answer"] and s2 in out["answer"] and s3 not in out["answer"]
    assert [c["chunk_id"] for c in out["citations"]] == [paging.chunk_id]  # 뺀 문장만 받치던 청크는 인용에서도 빠진다
    g = out["grounding"]
    assert g["revised"] is True and g["rejudge"] == "grounded" and g["llm"] == "ungrounded"
    assert [r["sentence"].startswith(s3) for r in g["removed"]] == [True] and g["removed"][0]["reason"] == "2시간이 자료와 다름"
    assert s3 in g["draft_answer"]  # 원래 답은 기록에 남는다
    assert llm.count("grounding") == 2  # 판정 한 번, 남은 답의 재판정 한 번
    assert "2025-01-01" in out["answer"] and "CC BY-SA 4.0" in out["answer"]


def test_revised_answer_must_pass_the_rejudge_or_it_is_refused():
    for second in (j(grounded=False, reason_code="unsupported", reason="아직 틀림", unsupported_sentences=[]), "판정 불가 응답"):
        llm, paging, escal, _ = _partial_setup(lambda a, b, c: [c], second=second)
        out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
        assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["citations"] == []
        assert out["grounding"]["revise"]["result"].startswith("rejudge_") and "revised" not in out["grounding"]
        assert llm.count("grounding") >= 2


def test_claim_that_matches_no_sentence_refuses_the_whole_answer_without_rejudge():
    llm, paging, escal, _ = _partial_setup(lambda a, b, c: ["답에 없는 문장을 지어 낸 항목입니다"], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported"
    assert out["grounding"]["revise"]["result"] == "unmatched" and llm.count("grounding") == 1


def test_answer_that_loses_more_than_half_or_everything_is_refused():
    """빼고 남은 말이 질문에 답하지 못하는 경우: 문장 3개 중 2개를 빼면 거절한다."""
    llm, paging, escal, _ = _partial_setup(lambda a, b, c: [b, c], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["grounding"]["revise"]["result"] == "too_many_removed" and llm.count("grounding") == 1
    llm, paging, escal, _ = _partial_setup(lambda a, b, c: [a, b, c], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["grounding"]["revise"]["result"] == "nothing_left"


def test_ungrounded_without_sentence_list_or_with_other_reason_is_refused_as_before():
    llm = normal_llm(grounding=j(grounded=False, reason_code="unsupported", reason="기한이 다름"))
    out = run(graph(llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and llm.count("grounding") == 1
    llm = normal_llm(grounding=j(grounded=False, reason_code="nonexistent_entity", reason="대상 없음", unsupported_sentences=["근거에 따라 답합니다"]))
    out = run(graph(llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "nonexistent_entity" and llm.count("grounding") == 1
    # 질문에 시점 표현이 있으면 모델의 out_of_period 표는 그대로 거절 사유다(사전 등록 62.29)
    llm = normal_llm(grounding=j(grounded=False, reason_code="out_of_period", reason="판 없음", unsupported_sentences=["근거에 따라 답합니다"]))
    out = run(graph(llm=llm, grounding_llm=True), question="FY21 기준 " + Q)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "out_of_period" and llm.count("grounding") == 1


def test_code_rules_still_refuse_before_any_llm_judgement():
    llm, paging, escal, _ = _partial_setup(lambda a, b, c: [c], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True), question="SEV9 장애 최초 대응은 몇 분 이내인가요?")
    assert out["kind"] == "refuse" and out["refuse_reason"] == "nonexistent_entity" and llm.count("grounding") == 0


def test_prune_answer_rules():
    from backend.graph.grounding import MAX_REMOVED_SHARE, prune_answer, split_sentences

    a, b, c = "0123456789abcdef", "fedcba9876543210", "aaaaaaaaaaaaaaaa"
    assert MAX_REMOVED_SHARE == 0.5
    text = f"SEV2는 99.74퍼센트를 지킨다 [{a}]. 담당자는 15분 안에 답한다 [{b}]. 나머지는 팀이 정한다 [{c}]."
    assert split_sentences(text) == [f"SEV2는 99.74퍼센트를 지킨다 [{a}].", f"담당자는 15분 안에 답한다 [{b}].", f"나머지는 팀이 정한다 [{c}]."]
    r = prune_answer(text, ["나머지는  팀이 정한다"])  # 공백과 표시 차이는 무시한다
    assert r.ok and r.answer == f"SEV2는 99.74퍼센트를 지킨다 [{a}]. 담당자는 15분 안에 답한다 [{b}]." and r.removed == [f"나머지는 팀이 정한다 [{c}]."]
    assert prune_answer(text, ["짧음"]).reason == "unmatched" and prune_answer(text, []).reason == "no_claims"
    two = prune_answer(text, ["담당자는 15분 안에 답한다 [" + b + "]. 나머지는 팀이 정한다 [" + c + "]."])
    assert not two.ok and two.reason == "too_many_removed"
    multi = f"첫 줄 문장이 있다 [{a}].\n둘째 줄 문장이 있다 [{b}].\n셋째 줄 문장이 있다 [{c}]."
    r = prune_answer(multi, ["둘째 줄 문장이 있다"])
    assert r.ok and r.answer == f"첫 줄 문장이 있다 [{a}].\n셋째 줄 문장이 있다 [{c}]."


def test_grounding_prompt_keeps_the_criteria_and_adds_only_the_sentence_list():
    from backend.prompts.question import GROUNDING_SYSTEM

    for kept in ("자료 밖 지식으로 받쳐졌다고 보지 않는다", "문장이 그럴듯하다는 이유로 통과시키지 않는다", "unsupported: 자료는 관련 있지만 답의 주장"):
        assert kept in GROUNDING_SYSTEM
    assert "unsupported_sentences" in GROUNDING_SYSTEM and "한 글자도 바꾸지 않고 그대로 복사" in GROUNDING_SYSTEM
    assert "판정 기준을 낮추지 않는다" in GROUNDING_SYSTEM


# ---------- 요청한 기간의 자료가 없는 답 (수정 3) ----------
Q_PERIOD = "2026년 9월 GitLab.com 서비스 가용률은 몇 퍼센트였어?"


def _adjacent_value_answer(text, covered=True):
    def fn(user):
        cid = first_chunk_id(user)
        return j(answer=f"{text} [{cid}]", citations=[{"chunk_id": cid}], period_covered=covered)

    return fn


def test_answer_that_says_the_requested_month_is_missing_but_cites_a_nearby_value_is_refused():
    """28번 경로: 기간 자료가 없다고 말하면서 가까운 달 값을 인용한 답은 거절한다. 사유 out_of_period, 답 단계 거절이다."""
    from backend.graph.build import MSG_REFUSE_BY_REASON

    for text in ("제공된 자료에는 2026년 9월 가용률이 없습니다. 가장 최근 값은 2026년 8월 99.74%입니다.", "2026년 9월 값은 확인 필요하지만 8월은 99.74%입니다."):
        out = run(graph(llm=normal_llm(answer=_adjacent_value_answer(text))), question=Q_PERIOD)
        assert out["kind"] == "refuse" and out["refuse_reason"] == "out_of_period" and out["citations"] == []
        assert out["answer"] == MSG_REFUSE_BY_REASON["out_of_period"] and "99.74" not in out["answer"]
        assert out["drafted"] is True and out["dropped_citations"] == [] and "9월" in out["grounding"]["detail"]


def test_period_covered_false_refuses_even_with_an_empty_answer():
    llm = normal_llm(answer=j(answer="", citations=[], period_covered=False))
    out = run(graph(llm=llm), question=Q_PERIOD)
    assert out["kind"] == "refuse" and out["refuse_reason"] == "out_of_period" and out["grounding"]["detail"] == "period_covered=false"


def test_period_rule_does_not_apply_to_questions_without_a_period():
    """시점 표현이 없는 질문은 답에 "없다"가 있어도, 모델이 period_covered=false를 내도 이 규칙으로 거절하지 않는다."""
    ans = j(answer="최초 대응은 15분 이내이다. 다만 담당 연락처는 자료에 없다 [{cid}]", citations=[{"chunk_id": "{cid}"}], period_covered=False)

    def fn(user):
        return ans.replace("{cid}", first_chunk_id(user))

    out = run(graph(llm=normal_llm(answer=fn)))  # Q에는 연도나 월이 없다
    assert out["kind"] == "answer" and not out.get("refuse_reason")


def test_period_question_with_a_normal_answer_is_kept():
    """기간을 묻는 질문이라도 답이 그 기간의 값을 주면(없다는 말이 없으면) 그대로 답한다."""
    out = run(graph(llm=normal_llm(answer=_adjacent_value_answer("2025년 판 기준 최초 대응은 15분 이내이다."))), question="2025년 기준 SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert out["kind"] == "answer"


def test_period_missing_rule_units():
    from backend.graph.grounding import period_missing, question_periods

    assert question_periods("2026년 9월 가용률과 2020년 기준, 3월 값, 2024-05 판") == ["2026년9월", "2020년", "3월", "2024-05"]
    assert question_periods("SEV2 최초 대응은?") == []
    assert period_missing("SEV2 최초 대응은?", "자료에 없다", False) == ""
    assert period_missing(Q_PERIOD, "99.74%입니다.", None) == "" and period_missing(Q_PERIOD, "99.74%입니다.", True) == ""
    assert period_missing(Q_PERIOD, "99.74%입니다.", False) == "period_covered=false"
    assert period_missing(Q_PERIOD, "8월은 99.74%입니다. 2026년 9월은 자료에 없다.", True).startswith("answer says")
    assert period_missing(Q_PERIOD, "2026년 8월은 없다.", True) == ""  # 질문의 시점(9월)에 대한 말이 아니다


def test_answer_prompt_carries_the_period_rule_and_output_flag():
    from backend.prompts.question import ANSWER_SYSTEM

    assert "period_covered를 false로 하고 answer를 빈 문자열, citations를 빈 목록으로 한다" in ANSWER_SYSTEM
    assert "가까운 다른 기간의 값이 있어도 그 값을 답으로 쓰지 않는다" in ANSWER_SYSTEM and '"period_covered": true' in ANSWER_SYSTEM


# ---------- 기준일 (수정 4) ----------
def _search_with_as_of():
    seen = []

    def fn(q):
        seen.append(q.as_of)
        return fake_search(q)

    return fn, seen


def test_rewrite_as_of_is_ignored_when_the_question_has_no_period():
    """15번 경로: 질문에 시점이 없는데 재작성이 낸 기준일(측정일 등)은 쓰지 않고 오늘로 둔다."""
    from datetime import date

    fn, seen = _search_with_as_of()
    llm = normal_llm(rewrite=j(query="SEV2 최초 대응", org=None, as_of="2025-03-04"))
    out = run(graph(fn, llm=llm), as_of=None)
    assert seen == [date.today().isoformat()] and out["as_of"] == date.today().isoformat()


def test_rewrite_as_of_is_used_when_the_question_has_a_period():
    fn, seen = _search_with_as_of()
    llm = normal_llm(rewrite=j(query="SEV2 최초 대응", org=None, as_of="2025-03-04"))
    out = run(graph(fn, llm=llm), as_of=None, question="2025년 3월 기준 SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert seen == ["2025-03-04"] and out["as_of"] == "2025-03-04"


def test_given_as_of_always_wins_over_rewrite():
    fn, seen = _search_with_as_of()
    llm = normal_llm(rewrite=j(query="SEV2 최초 대응", org=None, as_of="2025-03-04"))
    run(graph(fn, llm=llm), as_of="2025-06-01", question="2025년 3월 기준 SEV2 장애 최초 대응은 몇 분 이내인가요?")
    assert seen == ["2025-06-01"]


def test_mentions_period_examples():
    from backend.graph.build import mentions_period

    for q in ("2023년 5월 승인 한도는?", "3월에 바뀐 규정은?", "작년 휴가 정책", "2분기 목표 승인자", "FY25 예산 승인", "Q3 정책", "6개월 전 규칙", "지난달 변경", "오늘 기준 한도"):
        assert mentions_period(q), q
    for q in ("SEV2 최초 대응은 누가 해?", "신규 DB 도입 승인은?", "", "승인 한도"):
        assert not mentions_period(q), q


def test_month_level_as_of_of_the_dataset_becomes_the_last_day_of_the_month():
    from evals.agent.run_eval import _as_of

    cases = [("2026-10-27", "2026-10-27"), ("2023-05", "2023-05-31"), ("2024-02", "2024-02-29"), ("2023-02", "2023-02-28"), ("2025-12", "2025-12-31"),
             ("2025-13", None), ("2025-00", None), ("2025", None), ("", None), (None, None), (202305, None), ("05-2023", None)]
    for raw, want in cases:
        assert _as_of({"as_of": raw}) == want, raw
    assert _as_of({}) is None


def test_removal_that_leaves_no_citation_mark_is_refused_by_the_citation_recheck():
    """빼고 남은 문장에 인용 표시가 하나도 없으면(받치는 자료를 보일 수 없는 답) 남은 답을 내지 않고 원래 판정대로 거절한다."""
    paging = _by_article("Incident Response > Paging")
    keep1, keep2, bad = "SEV2 장애 최초 대응은 15분 이내이다", "담당자가 직접 호출한다", "에스컬레이션은 2시간 상한이다"
    body = f"{keep1}. {keep2}. {bad} [{paging.chunk_id}]."

    def grounding(user):
        if "<<<답>>>" in user and bad not in user:
            return j(grounded=True)
        return j(grounded=False, reason_code="unsupported", reason="2시간이 자료와 다름", unsupported_sentences=[bad])

    llm = normal_llm(answer=j(answer=body, citations=[{"chunk_id": paging.chunk_id}]), grounding=grounding)
    out = run(graph(lambda q: [paging], llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["citations"] == []
    assert out["grounding"]["revise"]["result"] == "citation_check_failed" and llm.count("grounding") == 1


# ---------- 답의 일부를 뺐다는 안내 ----------
def test_removed_sentence_is_announced_once_before_the_date_line():
    from backend.graph.build import MSG_PARTIAL_NOTE

    llm, paging, escal, (_, _, s3) = _partial_setup(lambda a, b, c: [c], second=j(grounded=True))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "answer" and s3 not in out["answer"]
    assert out["answer"].count(MSG_PARTIAL_NOTE) == 1
    assert out["answer"].index(MSG_PARTIAL_NOTE) < out["answer"].index("기준일")


def test_answer_with_nothing_removed_has_no_partial_note():
    from backend.graph.build import MSG_PARTIAL_NOTE

    out = run(graph(llm=normal_llm(grounding=j(grounded=True)), grounding_llm=True))
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE not in out["answer"]


# ---------- 판정 입력: 인용 자료와 같은 페이지 참고 ----------
def _chunk_copy(base: Chunk, **kw) -> Chunk:
    return base.model_copy(update=kw)


def test_same_page_context_keeps_only_uncited_chunks_of_the_same_page_and_version():
    from backend.graph.grounding import same_page_context

    paging = _by_article("Incident Response > Paging").model_dump()
    sibling = _by_article("Incident Response > Escalation").model_dump()
    other_page = {**sibling, "chunk_id": "1" * 16, "rule_seq": 12345}
    other_version = {**sibling, "chunk_id": "2" * 16, "version_id": "TEST-old"}
    got = same_page_context([paging], [paging, sibling, sibling, other_page, other_version])
    assert [c["chunk_id"] for c in got] == [sibling["chunk_id"]]
    assert same_page_context([], [paging, sibling]) == []


def test_grounding_input_separates_cited_material_from_same_page_context_and_leaves_other_pages_out():
    paging, sibling = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    other = _chunk_copy(sibling, chunk_id="3" * 16, rule_seq=12345, text="다른 페이지의 문장이다")
    llm = normal_llm(answer=_sentences_answer(("SEV2 장애 최초 대응은 15분 이내이다", paging.chunk_id)), grounding=j(grounded=True))
    run(graph(lambda q: [paging, sibling, other], llm=llm, grounding_llm=True))
    user = next(u for t, u in llm.calls if t == "grounding")
    material, _, context = user.partition("<<<참고>>>")
    assert f"chunk_id={paging.chunk_id}" in material and sibling.chunk_id not in material
    assert f"chunk_id={sibling.chunk_id}" in context and paging.chunk_id not in context
    assert other.chunk_id not in user and "다른 페이지의 문장이다" not in user


def test_grounding_input_has_no_context_block_without_a_same_page_chunk():
    paging = _by_article("Incident Response > Paging")
    other = _chunk_copy(_by_article("Incident Response > Escalation"), chunk_id="3" * 16, rule_seq=12345)
    llm = normal_llm(answer=_sentences_answer(("SEV2 장애 최초 대응은 15분 이내이다", paging.chunk_id)), grounding=j(grounded=True))
    run(graph(lambda q: [paging, other], llm=llm, grounding_llm=True))
    assert "<<<참고>>>" not in next(u for t, u in llm.calls if t == "grounding")


def test_context_is_for_applicability_only_and_a_value_must_be_in_the_cited_material():
    from backend.prompts.question import GROUNDING_SYSTEM

    assert "적용되는지" in GROUNDING_SYSTEM and "<<<참고>>>에만 있으면 받쳐지지 않은 것으로 본다" in GROUNDING_SYSTEM
    assert "자료 밖 지식으로 받쳐졌다고 보지 않는다" in GROUNDING_SYSTEM


def _material_only_judge(value: str):
    """프롬프트 규칙대로 판정하는 가짜 모델: 값이 <<<자료>>> 칸에 있어야 통과한다. <<<참고>>> 칸은 보지 않는다."""

    def grounding(user):
        material = user.split("<<<답>>>", 1)[1].split("<<<끝>>>", 1)[1].partition("<<<참고>>>")[0]
        return j(grounded=True) if value in material else j(grounded=False, reason_code="unsupported", reason=f"{value}이 인용 자료에 없음", unsupported_sentences=[])

    return grounding


def test_value_found_only_in_same_page_context_does_not_pass():
    """검색된 같은 페이지 청크에 값이 있어도 그 청크를 인용하지 않으면 답이 나가지 않는다. 다시 써서 인용을 고치면 나간다."""
    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    wrong = _sentences_answer(("에스컬레이션은 2시간 상한이다", paging.chunk_id))
    llm = normal_llm(answer=wrong, grounding=_material_only_judge("2시간"))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["citations"] == [] and "2시간" not in out["answer"]
    fixed = _sentences_answer(("에스컬레이션 상한은 2시간이다", escal.chunk_id))
    llm = normal_llm(answer=[wrong, fixed], grounding=_material_only_judge("2시간"))
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["citations"]] == [escal.chunk_id] and out["grounding"]["redrafted"] is True


# ---------- 답 다시 쓰기: 근거 판정이 거절한 답을 한 번 ----------
def _redraft_setup(second_answer, verdicts=None, claims=None, chunks=None):
    paging = _by_article("Incident Response > Paging")
    first = _sentences_answer(("SEV2 장애 최초 대응은 2시간 이내이다", paging.chunk_id))
    bad = j(grounded=False, reason_code="unsupported", reason="2시간이 자료와 다름", unsupported_sentences=claims if claims is not None else ["SEV2 장애 최초 대응은 2시간 이내이다"])
    llm = normal_llm(answer=[first, second_answer], grounding=verdicts or [bad, j(grounded=True)])
    return llm, paging, chunks or [paging]


def test_refused_answer_is_rewritten_once_and_must_pass_the_judge_again():
    good = _by_article("Incident Response > Paging")
    llm, paging, chunks = _redraft_setup(_sentences_answer(("SEV2 장애 최초 대응은 15분 이내이다", good.chunk_id)))
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True, answer_store=InMemoryAnswerStore()))
    assert out["kind"] == "answer" and "15분" in out["answer"] and "2시간" not in out["answer"] and not out.get("refuse_reason")
    g = out["grounding"]
    assert g["redrafted"] is True and g["redraft"]["result"] == "rejudge_grounded" and "2시간" in g["draft_answer"]
    assert "revise" not in g and "revised" not in g  # 다시 쓰기가 먼저이고, 통과하면 문장을 빼지 않는다
    assert llm.count("answer") == 2 and llm.count("grounding") == 2
    assert out["answer_id"] and "2025-01-01" in out["answer"] and "CC BY-SA 4.0" in out["answer"] and "[1]" in out["answer"]
    second = [u for t, u in llm.calls if t == "answer"][1]
    assert "<<<이전 답>>>" in second and "2시간이 자료와 다름" in second


def test_rewrite_keeps_the_answering_sentence_that_removal_would_lose():
    """핵심 문장에 틀린 말이 섞이면 빼는 것으로는 답이 사라진다. 빼기 전에 다시 써서 핵심 사실을 남긴다."""
    paging = _by_article("Incident Response > Paging")
    core, side = "SEV2 장애 최초 대응은 배정 시점부터 15분 이내이다", "이 기한은 외부 담당자에게 적용되지 않는다"
    first = _sentences_answer((core, paging.chunk_id), (side, paging.chunk_id))
    fixed = _sentences_answer(("SEV2 장애 최초 대응은 15분 이내이다", paging.chunk_id))

    def grounding(user):
        return j(grounded=False, reason_code="unsupported", reason="배정 시점이 자료에 없음", unsupported_sentences=[core]) if core in user else j(grounded=True)

    llm = normal_llm(answer=[first, fixed], grounding=grounding)
    out = run(graph(lambda q: [paging], llm=llm, grounding_llm=True))
    assert out["kind"] == "answer" and "SEV2 장애 최초 대응은 15분 이내이다" in out["answer"] and side not in out["answer"]
    assert out["grounding"]["redrafted"] is True and "revise" not in out["grounding"]


def test_removal_is_the_fallback_when_the_rewrite_does_not_pass():
    from backend.graph.build import MSG_PARTIAL_NOTE

    paging, escal = _by_article("Incident Response > Paging"), _by_article("Incident Response > Escalation")
    s1, s2, s3 = "SEV2 장애 최초 대응은 15분 이내이다", "담당자가 직접 호출한다", "에스컬레이션은 3시간 상한이다"
    first = _sentences_answer((s1, paging.chunk_id), (s2, paging.chunk_id), (s3, escal.chunk_id))
    rewrite = _sentences_answer(("에스컬레이션은 지어낸 값 9시간 상한이다", escal.chunk_id))

    def grounding(user):
        if s3 in user or "9시간" in user:
            return j(grounded=False, reason_code="unsupported", reason="상한이 자료와 다름", unsupported_sentences=[s3])
        return j(grounded=True)

    llm = normal_llm(answer=[first, rewrite], grounding=grounding)
    out = run(graph(lambda q: [paging, escal], llm=llm, grounding_llm=True))
    assert out["kind"] == "answer" and s1 in out["answer"] and s3 not in out["answer"] and "9시간" not in out["answer"] and MSG_PARTIAL_NOTE in out["answer"]
    g = out["grounding"]
    assert g["redraft"]["result"] == "rejudge_ungrounded" and g["revise"]["result"] == "pruned" and g["revised"] is True and "redrafted" not in g
    assert llm.count("answer") == 2 and llm.count("grounding") == 3


def test_rewritten_answer_without_support_is_still_refused():
    """다시 쓴 답도 판정이 거절하거나 결론이 없으면 나가지 않는다. 다시 쓰기는 한 번뿐이다."""
    good = _by_article("Incident Response > Paging")
    bad = j(grounded=False, reason_code="unsupported", reason="근거 없음", unsupported_sentences=["자료에 없는 문장"])
    for second_verdict in (bad, "판정 불가 응답", j(grounded=False, reason_code="no_evidence", reason="없음")):
        llm, _, chunks = _redraft_setup(_sentences_answer(("SEV2 장애 최초 대응은 지어낸 값 3분이다", good.chunk_id)), verdicts=[bad, second_verdict])
        out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
        assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["citations"] == []
        assert "3분" not in out["answer"] and not out.get("answer_id")
        assert out["grounding"]["redraft"]["result"].startswith("rejudge_") and "redrafted" not in out["grounding"]
        assert llm.count("answer") == 2 and llm.count("grounding") <= 3


def test_rewritten_answer_with_a_made_up_chunk_id_is_refused_and_counted():
    from evals.agent import run_eval as E

    llm, _, chunks = _redraft_setup(j(answer=f"최초 대응은 15분 이내이다 [{FAKE_ID}].", citations=[{"chunk_id": FAKE_ID}]))
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and out["grounding"]["redraft"]["result"] == "citation_check_failed" and llm.count("grounding") == 1
    assert out["dropped_citations"] == [{"chunk_id": FAKE_ID}]  # 환각 위험 지표가 세는 칸이다
    assert FAKE_ID not in out["answer"]
    row = E._row({"id": 1, "kind": "relevant", "input": Q, "gold": []}, out, 0.1)
    assert E.compute_metrics([row])["hallucination_risk_rate"] == 1.0


def test_empty_or_broken_or_unchanged_rewrite_is_refused_without_another_judgement():
    paging = _by_article("Incident Response > Paging")
    same = _sentences_answer(("SEV2 장애 최초 대응은 2시간 이내이다", paging.chunk_id))
    for second, result in ((j(answer="", citations=[]), "empty"), ("JSON이 아닌 응답", "empty"), (same, "unchanged")):
        llm, _, chunks = _redraft_setup(second)
        out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
        assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and out["grounding"]["redraft"]["result"] == result
        assert llm.count("grounding") == 1


def test_unchanged_rewrite_gets_one_more_judgement_when_ur_is_on(monkeypatch):
    """UR: 다시 쓰기가 처음 답을 그대로 내면 처음 답을 한 번 더 판정한다. 받쳐지면 그 답을 내고, 아니면(PT 안내뿐 포함) 지금처럼 거절한다."""
    monkeypatch.setenv("GRAPH_UNCHANGED_REJUDGE", "1")
    monkeypatch.setenv("GRAPH_POINTER_REFUSE", "1")
    paging = _by_article("Incident Response > Paging")
    same = _sentences_answer(("SEV2 장애 최초 대응은 2시간 이내이다", paging.chunk_id))
    bad = j(grounded=False, reason_code="unsupported", reason="적용 대상이 자료에 없음", unsupported_sentences=["SEV2 장애 최초 대응은 2시간 이내이다"])
    pointer = j(grounded=True, claims=[{"claim": "안내", "quote": "For more information, please refer to the following links.", "scope": None}])
    for name, second, state in (("grounded", j(grounded=True), "grounded"), ("ungrounded", bad, "ungrounded"), ("pointer", pointer, "grounded")):
        llm, _, chunks = _redraft_setup(same, verdicts=[bad, second])
        out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
        assert llm.count("grounding") == 2, name  # 판정 +1. 다시 판정이 거절하면 문장 빼기 뒤 남는 답이 없어 더 부르지 않는다
        g = out["grounding"]
        assert g["redraft"]["result"] == "unchanged" and g["redraft"]["rejudge"] == state, name
        if name == "grounded":
            assert out["kind"] == "answer" and "2시간" in out["answer"] and g["rejudged_unchanged"] is True
            assert [c["chunk_id"] for c in out["citations"]] == [paging.chunk_id]
        else:
            assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and "rejudged_unchanged" not in g, name


def test_unchanged_rewrite_is_not_rejudged_when_ur_is_off(monkeypatch):
    monkeypatch.delenv("GRAPH_UNCHANGED_REJUDGE", raising=False)
    paging = _by_article("Incident Response > Paging")
    same = _sentences_answer(("SEV2 장애 최초 대응은 2시간 이내이다", paging.chunk_id))
    llm, _, chunks = _redraft_setup(same)
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and llm.count("grounding") == 1 and "rejudge" not in out["grounding"]["redraft"]


def test_rewrite_that_says_the_period_is_missing_is_refused():
    good = _by_article("Incident Response > Paging")
    second = j(answer=f"최초 대응은 15분이다 [{good.chunk_id}].", citations=[{"chunk_id": good.chunk_id}], period_covered=False)
    llm, _, chunks = _redraft_setup(second)
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True), question="2025년 1월 SEV2 장애 최초 대응은 몇 분이었나요?")
    assert out["kind"] == "refuse" and out["grounding"]["redraft"]["result"] == "answer_check_failed" and llm.count("grounding") == 1


def test_only_unsupported_gets_a_rewrite():
    """no_evidence, nonexistent_entity와, 질문에 시점 표현이 있을 때의 out_of_period는 다시 쓰지 않고 거절한다.
    시점 표현이 없는 질문의 out_of_period는 unsupported로 읽어 다시 쓴다(사전 등록 62.29, `grounding.recode_vote`)."""
    for code, question in (("no_evidence", Q), ("nonexistent_entity", Q), ("out_of_period", "FY21 기준 " + Q)):
        llm = normal_llm(grounding=j(grounded=False, reason_code=code, reason="없음", unsupported_sentences=["근거에 따라 답합니다"]))
        out = run(graph(llm=llm, grounding_llm=True), question=question)
        assert out["kind"] == "refuse" and out["refuse_reason"] == code and llm.count("answer") == 1 and "redraft" not in out["grounding"]
    for code in ("out_of_period",):
        llm = normal_llm(grounding=j(grounded=False, reason_code=code, reason="없음", unsupported_sentences=["근거에 따라 답합니다"]))
        out = run(graph(llm=llm, grounding_llm=True))
        assert out["kind"] == "refuse" and out["refuse_reason"] == "unsupported" and llm.count("answer") == 2
        assert out["grounding"]["recoded"] == [code] and out["grounding"]["redraft"]["result"] == "unchanged"


def test_rewrite_that_dropped_an_asked_fact_says_so():
    from backend.graph.build import MSG_PARTIAL_NOTE

    good = _by_article("Incident Response > Paging")
    second = j(answer=f"최초 대응은 15분 이내이다 [{good.chunk_id}].", citations=[{"chunk_id": good.chunk_id}], partial=True)
    llm, _, chunks = _redraft_setup(second)
    out = run(graph(lambda q: chunks, llm=llm, grounding_llm=True))
    assert out["kind"] == "answer" and out["answer"].count(MSG_PARTIAL_NOTE) == 1


def test_refused_draft_stays_in_the_record_not_in_the_answer():
    llm = normal_llm(grounding=j(grounded=False, reason_code="out_of_period", reason="판 없음"))
    out = run(graph(llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and "근거에 따라 답합니다" in out["grounding"]["draft_answer"] and "근거에 따라 답합니다" not in out["answer"]


# ---------- 일부 근거만 있는 나뉜 질문 ----------
TWO_FACTS = j(split=True, sub_questions=["SEV2 최초 대응 기한은 얼마인가요?", "SEV2 장애 사후 분석 담당은 누구인가요?"])
PARTIAL = j(sufficient=False, partial=True, reason="사후 분석 담당이 자료에 없다", clarify=None)
NOT_PARTIAL = j(sufficient=False, partial=False, reason="대상이 자료에 없다", clarify=None)


def _rewrites():
    n = iter(range(100))
    return lambda user: j(query=f"SEV2 최초 대응 {next(n)}", org="TEST-security", as_of=None)


def test_compound_question_with_partial_evidence_answers_that_part_and_says_the_rest_is_out():
    from backend.graph.build import MSG_PARTIAL_NOTE

    fn, calls = counting_search()
    llm = normal_llm(decompose=TWO_FACTS, judge=PARTIAL, rewrite=_rewrites(), grounding=j(grounded=True))
    out = run(graph(fn, llm=llm, decompose=True, grounding_llm=True, answer_store=InMemoryAnswerStore()))
    assert len(calls) == 1 and llm.count("judge") == 1  # 나뉜 질문의 일부 판정은 재검색하지 않고 일부 답으로 간다(사전 등록 62.63)
    assert out["kind"] == "answer" and out["citations"] and out["answer_id"] and out["answer"].count(MSG_PARTIAL_NOTE) == 1
    assert out["grounding"]["partial_route"] is True
    assert "자료가 직접 답하는 사실만 답하고" in next(u for t, u in llm.calls if t == "answer")


def test_partial_answer_must_still_pass_the_grounding_judge():
    llm = normal_llm(decompose=TWO_FACTS, judge=PARTIAL, rewrite=_rewrites(),
                     grounding=j(grounded=False, reason_code="no_evidence", reason="질문의 대상이 자료에 없다"))
    out = run(graph(llm=llm, decompose=True, grounding_llm=True))
    assert out["kind"] == "refuse" and out["refuse_reason"] == "no_evidence" and out["citations"] == []


def test_research_that_finds_the_rest_gives_a_full_answer_without_the_note():
    from backend.graph.build import MSG_PARTIAL_NOTE

    llm = normal_llm(decompose=TWO_FACTS, judge=[NOT_PARTIAL, j(sufficient=True)], rewrite=_rewrites(), grounding=j(grounded=True))   # 일부가 아닌 부족 판정은 지금도 재검색한다
    out = run(graph(llm=llm, decompose=True, grounding_llm=True))
    assert out["kind"] == "answer" and MSG_PARTIAL_NOTE not in out["answer"] and out["judge_partial"] is False
    assert "자료가 직접 답하는 사실만 답하고" not in next(u for t, u in llm.calls if t == "answer")


def test_partial_flag_on_a_single_fact_question_is_refused_as_before():
    """나뉘지 않은 질문은 일부 근거 경로로 가지 않는다. 없는 대상을 비슷한 자료로 답하지 않기 위한 코드 조건이다."""
    fn, calls = counting_search()
    llm = normal_llm(decompose=j(split=False, sub_questions=[]), judge=PARTIAL, rewrite=_rewrites())
    out = run(graph(fn, llm=llm, decompose=True, grounding_llm=True))
    assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and len(calls) == 3 and llm.count("answer") == 0
    llm = normal_llm(judge=PARTIAL, rewrite=_rewrites())  # 분해를 끈 경로
    out = run(graph(llm=llm, grounding_llm=True))
    assert out["kind"] == "refuse" and llm.count("answer") == 0


def test_compound_question_without_the_partial_flag_is_refused():
    for verdict in (NOT_PARTIAL, j(sufficient=False, partial="true", reason="x", clarify=None), j(sufficient=False, reason="x", clarify=None)):
        llm = normal_llm(decompose=TWO_FACTS, judge=verdict, rewrite=_rewrites())
        out = run(graph(llm=llm, decompose=True, grounding_llm=True))
        assert out["kind"] == "refuse" and out["answer"] == MSG_REFUSE and llm.count("answer") == 0


def test_judge_prompt_limits_the_partial_flag():
    from backend.prompts.question import JUDGE_SYSTEM

    assert "partial=true" in JUDGE_SYSTEM and "사실이 하나뿐이거나" in JUDGE_SYSTEM and "질문의 대상 자체가 자료에 없거나" in JUDGE_SYSTEM


def test_answer_prompt_lists_the_asked_facts_first():
    from backend.prompts.question import ANSWER_SYSTEM

    assert '"asked"' in ANSWER_SYSTEM and "asked에 없는 내용은 자료에 있어도 쓰지 않는다" in ANSWER_SYSTEM and "먼저 나온 자료를 고른다" in ANSWER_SYSTEM
    assert "조직 전체에 적용되는 지침을 고른다" in ANSWER_SYSTEM


def test_grounding_prompt_asks_for_the_reason_before_the_verdict():
    """판정을 먼저 쓰면 뒤의 이유가 판정과 어긋나도 판정이 남는다. 형식 예시 모두 reason이 grounded보다 앞이어야 한다."""
    import re

    from backend.prompts.question import GROUNDING_SYSTEM

    examples = re.findall(r"\{.*?\}", GROUNDING_SYSTEM.split("JSON 한 개만 출력한다", 1)[1])
    assert len(examples) == 3 and all(e.index('"reason"') < e.index('"grounded"') for e in examples)
    assert "reason을 먼저 써서" in GROUNDING_SYSTEM


def test_prompt_profile_has_only_measured_fields_not_service():
    """service 칸은 저장만 한다. 분류·재작성 프롬프트에는 측정(main) 때와 같은 affiliation·rank만 들어간다(H-13)."""
    from backend.prompts.question import classify_user, rewrite_user

    profile = {"affiliation": "TEST-finance", "rank": "TEST-lead", "service": "TEST-SVC-NAME"}
    for text in (classify_user("질문", profile), rewrite_user("질문", profile, None)):
        assert "TEST-SVC-NAME" not in text and "service" not in text
        assert "TEST-finance" in text and "TEST-lead" in text
    assert classify_user("질문", {"service": "TEST-SVC-NAME"}) == classify_user("질문", {})
