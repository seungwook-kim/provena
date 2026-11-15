"""2026-11-13 정확도 수정 시험: 사전 등록 62.55~62.59. 가짜 모델, 가짜 검색기, 메모리 저장소만 쓴다(키와 네트워크 없음). 스위치 없이 기본 동작이다.

- 62.55: 나뉜 질문(하위 질문 2개 이상, 달러 금액 질문 제외)의 첫 검색 뒤, 문맥에 든 페이지 안에서 원 질문과 가까운 새 청크 1개를 문맥 끝에 보충한다(앞자리 아님, `[보충]`).
- 62.56: 인용 더하기(A1)는 같은 페이지 같은 절의 청크를 더하지 않고, 표 행끼리는 첫 칸이 같을 때만 같은 값 줄로 본다.
- 62.57: 문장 공유 더하기(A1b)는 표 행을 줄 전체가 상대 청크에 그대로 있을 때만 공유 문장으로 센다.
- 62.58: 겹친 머리 인용 바로잡기(62.52)를 원래 청크가 문맥에 없을 때 같은 페이지 판의 바로 앞 청크를 읽어서까지 한다.
- 62.59: 넓힌 문맥에서 판정 구절이 모두 앞자리일 때, 앞자리 청크만 인용한 둘째 후보가 판정 구절 청크를 더 많이 인용했으면 둘째 후보를 고른다.
"""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, Q_ESC, SUBS, cite, llm, mk, run, searcher
from test_trace_fixes_1113 import GROUNDED, INTRO, INTRO_ID, Q_OPT, QUOTE, X, Y, _ids, _intro_search
from test_widened_first_search import CORE, WIDE, WIDE_IDS, quoting

from backend.graph import answer_fixes as AF
from backend.graph.build import MAX_CHUNKS, SEARCH_K, SPLIT_K, build_graph, chunk_cap, core_chunks, page_filled
from backend.graph.multi import build_multi_graph

FILL = mk("Escalation note: if the EOC is silent for fifteen minutes the duty manager pages the IMOC directly.", title="Incident Management", seq=CORE[0].rule_seq, article="Core 0 > Notes")
OTHER_FILL = mk("Another note from the same page about the pager rotation.", title="Incident Management", seq=CORE[1].rule_seq, article="Core 1 > Pager")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_BEST2_SAMEDOC",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_GROUNDING_QUOTE",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_CITE_EXPAND", "GRAPH_CITE_PHRASE", "GRAPH_DROP_SCOPED_CITES", "GRAPH_CITE_CONSENSUS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")  # 도입부 검색을 넘긴 시험만 실제로 채운다


def pages(found, seen=None):
    """페이지 검색 가짜: 부른 인자를 기록하고 `found`를 돌려준다(검색기는 문맥에 든 청크도 돌려주므로 그대로 섞어 준다)."""
    def fn(query, seqs, org, as_of, k):
        if seen is not None:
            seen.append({"query": query, "seqs": list(seqs), "k": k})
        if isinstance(found, Exception):
            raise found
        return list(found)
    return fn


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, judge_answer="parallel_all", grounding_llm=True, decompose=True, max_research=1, **kw)


def first_run(multi, *, page, quote=CORE[0], answer=None, question=Q_ESC, split=True, intro=False, key="EOC", **kw):
    fn, _ = searcher(((key, [*CORE, *WIDE]),))
    m = llm(decompose=j(split=split, sub_questions=SUBS if split else []), judge=quoting(quote), answer=answer or (lambda u: cite(CORE[0])))
    extra = {"intro_search": _intro_search()} if intro else {}
    return run(graph(multi, fn, m, page_search=page, **extra, **kw), question), m


# ---------- 62.55 같은 페이지 보충 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_appends_one_new_chunk_at_the_end_and_marks_it(multi):
    seen: list = []
    out, m = first_run(multi, page=pages([CORE[0], FILL, OTHER_FILL], seen))
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert ids == [*(c.chunk_id for c in CORE), *WIDE_IDS, FILL.chunk_id]  # 앞 청크의 순서와 내용은 그대로, 문맥에 없던 첫 1개가 끝에 붙는다
    assert out["search_stats"]["page_fill"] == 1
    assert len(seen) == 1 and "EOC" in seen[0]["query"] and seen[0]["k"] == SPLIT_K + 1
    assert seen[0]["seqs"] == [c.rule_seq for c in CORE] + [c.rule_seq for c in WIDE]  # 문맥에 든 페이지(rule_seq, 문맥 순서)
    judged = [u for t, u in m.calls if t == "judge"][0]
    assert f"[보충] chunk_id={FILL.chunk_id}" in judged and "intro_chunk_ids" not in out  # 앞자리가 아니라 보충 표시
    assert FILL.chunk_id not in [c["chunk_id"] for c in core_chunks({"question": Q_ESC, "sub_queries": SUBS, "retries": 0, "chunks": out["chunks"]})]


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_comes_after_the_intro_chunk_and_only_the_intro_chunk_is_a_front_slot(multi):
    out, _ = first_run(multi, page=pages([FILL]), intro=True, key="EOC", )
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert ids[-2:] == [INTRO_ID, FILL.chunk_id] and out["intro_chunk_ids"] == [INTRO_ID]  # 순서는 도입부 -> 보충
    core = [c["chunk_id"] for c in core_chunks({"question": Q_ESC, "sub_queries": SUBS, "retries": 0, "chunks": out["chunks"], "intro_chunk_ids": out["intro_chunk_ids"]})]
    assert INTRO_ID in core and FILL.chunk_id not in core


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_skips_a_chunk_already_in_the_context_and_takes_the_next_new_one(multi):
    out, _ = first_run(multi, page=pages([CORE[2], CORE[0], WIDE[0], OTHER_FILL, FILL]))
    assert [c["chunk_id"] for c in out["chunks"]][-1] == OTHER_FILL.chunk_id and out["search_stats"]["page_fill"] == 1


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_adds_nothing_without_a_new_chunk(multi):
    base, _ = first_run(multi, page=None)
    out, _ = first_run(multi, page=pages([CORE[0], WIDE[1]]))
    assert [c["chunk_id"] for c in out["chunks"]] == [c["chunk_id"] for c in base["chunks"]] and "page_fill" not in out["search_stats"]


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_does_not_duplicate_a_chunk_the_intro_fill_added(multi):
    out, _ = first_run(multi, page=pages([INTRO]), intro=True)
    ids = [c["chunk_id"] for c in out["chunks"]]
    assert ids.count(INTRO_ID) == 1 and ids[-1] == INTRO_ID and "page_fill" not in out["search_stats"]


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_failure_leaves_the_context_and_the_answer_goes_out(multi):
    base, _ = first_run(multi, page=None)
    out, _ = first_run(multi, page=pages(RuntimeError("db down")))
    assert out["kind"] == "answer" and [c["chunk_id"] for c in out["chunks"]] == [c["chunk_id"] for c in base["chunks"]]
    assert "page_fill" not in out["search_stats"]


@pytest.mark.parametrize("multi", [False, True])
def test_page_fill_does_not_touch_an_unsplit_question_or_a_dollar_question(multi):
    seen: list = []
    out, _ = first_run(multi, page=pages([FILL], seen), split=False)
    assert seen == [] and "page_fill" not in out["search_stats"] and FILL.chunk_id not in [c["chunk_id"] for c in out["chunks"]]
    dollar = "계약 금액이 3만 달러라면 EOC가 응답하지 않을 때 어떻게 되고, IMOC도 응답하지 않으면 누구를 불러?"
    out, _ = first_run(multi, page=pages([FILL], seen), question=dollar)
    assert seen == [] and "page_fill" not in out["search_stats"]


@pytest.mark.parametrize("multi", [False, True])
def test_without_a_page_search_the_first_search_is_the_same_as_before(multi):
    out, _ = first_run(multi, page=None)
    assert "page_fill" not in out["search_stats"] and len(out["chunks"]) == SPLIT_K


@pytest.mark.parametrize("multi", [False, True])
def test_quote_in_the_fill_chunk_uses_the_full_context_draft(multi):
    out, _ = first_run(multi, page=pages([FILL]), quote=FILL, answer=lambda u: cite(FILL if FILL.chunk_id in u and WIDE_IDS[0] in u else CORE[0]))
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 1 and log["why"] == "판정 구절이 넓힌 자리에 있음"
    assert [c["chunk_id"] for c in out["citations"]] == [FILL.chunk_id]


def test_chunk_cap_grows_by_the_fill_and_page_filled_reads_the_stats():
    assert chunk_cap(SUBS, Q_ESC) == MAX_CHUNKS + SPLIT_K - SEARCH_K
    assert chunk_cap(SUBS, Q_ESC, 1) == chunk_cap(SUBS, Q_ESC) + 1
    assert page_filled({"search_stats": {"calls": 1, "page_fill": 1}}) == 1 and page_filled({"search_stats": {"calls": 1}}) == 0 and page_filled({}) == 0


@pytest.mark.parametrize("multi", [False, True])
def test_requery_after_a_fill_still_receives_all_new_chunks(multi):
    """보충 청크가 붙은 실행의 재검색은 상한이 1 올라 새 청크를 자르지 않는다."""
    NEW = [mk(f"Late requery fact {i} about the pager rotation.", title="Incident Management", seq=73000 + i, article=f"Late {i}") for i in range(SEARCH_K)]
    partial = j(checks=[{"fact": "빠진 사실", "value": None}], sufficient=False, partial=True, reason="부족", missing=["빠진 사실"], scope_note=None, clarify=None, query="pager rotation")

    def fn(q):
        return ([*CORE, *WIDE] if q.sub_queries else NEW)[: q.k]

    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=[partial, quoting(CORE[0])], answer=lambda u: cite(CORE[0]))
    out = run(graph(multi, fn, m, page_search=pages([FILL])), Q_ESC)
    ids = {c["chunk_id"] for c in out["chunks"]}
    assert FILL.chunk_id in ids and all(c.chunk_id in ids for c in NEW) and len(out["chunks"]) == SPLIT_K + 1 + SEARCH_K


# ---------- 62.56 인용 더하기 ----------
def ch(text, *, seq, article, title="Policy"):
    return mk(text, title=title, seq=seq, article=article).model_dump()


WORDS = " ".join(f"zq{i:03d}" for i in range(11))


def test_cite_expand_does_not_add_a_chunk_of_the_same_section():
    cited = [ch(f"30 days {WORDS}", seq=80001, article="Fees > Table")]
    same = ch(f"30 days {WORDS}", seq=80001, article="Fees > Table")
    same["chunk_id"] = "same-section-chunk"
    assert AF.pick_extra(cited, [cited[0], same]) == []


def test_cite_expand_still_adds_other_pages_and_other_sections_with_the_same_value():
    cited = [ch(f"30 days {WORDS}", seq=80001, article="Fees > Table")]
    other_page = ch(f"30 days {WORDS}", seq=80002, article="Fees > Table")
    other_section = ch(f"Also, 30 days {WORDS}", seq=80001, article="Fees > Other section")  # 앞에 글이 있어 겹친 머리로 떼이지 않는다
    assert [c["chunk_id"] for c, _ in AF.pick_extra(cited, [cited[0], other_page])] == [other_page["chunk_id"]]
    assert [c["chunk_id"] for c, _ in AF.pick_extra(cited, [cited[0], other_section])] == [other_section["chunk_id"]]


def row(label, weight, desc):
    return f"Label: {label} | Weight: {weight} | Classification: Small | Description: {desc} | Estimate: 30 days"


def test_cite_expand_needs_the_same_first_cell_for_table_rows():
    desc = "Straight forward change minimal investigation required for this class of work item"
    cited = [ch(row("InfraSecEffort Small", 2, desc), seq=80010, article="Infra > Effort")]
    other_label = ch(row("vuln-mgmt Small", 2, desc), seq=80011, article="Vuln > Effort")
    same_label = ch(row("InfraSecEffort Small", 2, desc), seq=80012, article="Copy > Effort")
    assert AF.pick_extra(cited, [cited[0], other_label]) == []  # 값은 같고 첫 칸이 다르면 더하지 않는다
    assert [c["chunk_id"] for c, _ in AF.pick_extra(cited, [cited[0], same_label])] == [same_label["chunk_id"]]  # 첫 칸이 같으면 더한다


def test_cite_expand_is_unchanged_when_one_side_is_prose():
    desc = "Straight forward change minimal investigation required for this class of work item"
    cited = [ch(row("InfraSecEffort Small", 2, desc), seq=80010, article="Infra > Effort")]
    prose = ch(f"Straight forward change minimal investigation required for this class of work item takes 30 days of Small effort. {desc}", seq=80013, article="Notes")
    both_prose = [ch(f"30 days {WORDS}", seq=80020, article="A")]
    prose2 = ch(f"30 days {WORDS}", seq=80021, article="B")
    assert [c["chunk_id"] for c, _ in AF.pick_extra(cited, [cited[0], prose])] == [prose["chunk_id"]]
    assert [c["chunk_id"] for c, _ in AF.pick_extra(both_prose, [both_prose[0], prose2])] == [prose2["chunk_id"]]


def test_cite_expand_caps_are_unchanged():
    cited = [ch(f"30 days {WORDS}", seq=80030, article="A")]
    cands = [ch(f"30 days {WORDS}", seq=80031 + i, article=f"B{i}") for i in range(3)]
    assert len(AF.pick_extra(cited, [cited[0], *cands])) == AF.MAX_ADD == 2
    assert AF.pick_extra(cited, [cited[0], *cands], cap=1) == []


def test_table_row_helpers():
    assert AF.is_table_row("a: 1 | b: 2") and not AF.is_table_row("plain sentence")
    assert AF.row_first_cell("Label: ~Vuln-Mgmt::Small | Weight: 2") == "vulnmgmtsmall"
    assert AF.row_first_cell("Plain Cell | b: 2") == "plaincell"


# ---------- 62.57 문장 공유 더하기 ----------
TABLE_ROW_TAIL = "Weight: 2 | Classification: Small | Description: Straight forward change, minimal investigation | Estimation Guide: 2 weeks of effort"


def test_phrase_extra_does_not_count_a_table_row_that_shares_only_its_tail():
    cited = [ch(f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}", seq=80040, article="Infra", title="Infrastructure Security")]
    other_row = ch(f"Label: ~vuln-mgmt::Small | {TABLE_ROW_TAIL}", seq=80041, article="App", title="Application Security")
    assert AF.longest_shared_run(AF._words(AF._body(other_row)), AF._words(AF._body(cited[0]))) >= AF.PHRASE_MIN_WORDS  # 62.57 전에는 같은 문장으로 셌다
    assert AF.pick_phrase_extra(cited, [cited[0], other_row]) == []


def test_phrase_extra_counts_a_table_row_that_is_the_same_whole_line():
    line = f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}"
    cited = [ch(line, seq=80040, article="Infra", title="Infrastructure Security")]
    copy = ch(f"{line}\nOther: x", seq=80042, article="Copy", title="Infrastructure Security")
    assert [c["chunk_id"] for c, _ in AF.pick_phrase_extra(cited, [cited[0], copy])] == [copy["chunk_id"]]


def test_phrase_extra_keeps_the_prose_rule_and_the_same_page_and_team_page_exclusions():
    sent = "Patch releases are deployed to production during the scheduled patch window after the release manager approves the package."
    cited = [ch(sent, seq=80050, article="Window", title="Patch Releases")]
    prose = ch(f"For deployments, {sent}", seq=80051, article="Exec", title="Deployments")
    same_page = ch(sent + " More text.", seq=80050, article="Other", title="Patch Releases")
    team = ch(sent, seq=80052, article="Notes", title="Delivery Group")
    assert [c["chunk_id"] for c, _ in AF.pick_phrase_extra(cited, [cited[0], same_page, team, prose])] == [prose["chunk_id"]]


def test_a_304_shaped_answer_ends_with_one_citation_after_both_rules():
    """62.56 + 62.57: 행 이름만 다른 같은 모양 표(다른 페이지)를 인용 더하기도 문장 공유 더하기도 더하지 않는다."""
    cited = [ch(f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}", seq=80060, article="Infra", title="Infrastructure Security")]
    other = ch(f"Label: ~vuln-mgmt::Small | {TABLE_ROW_TAIL}", seq=80061, article="Vuln", title="Application Security")
    body, more = AF.expand_numbered("답 [1]", cited, [cited[0], other])
    body, more = AF.expand_numbered(body, more, [cited[0], other], picker=AF.pick_phrase_extra)
    assert [c["chunk_id"] for c in more] == [cited[0]["chunk_id"]] and body == "답 [1]"


# ---------- 62.58 문맥 밖 앞 청크까지 바로잡기 ----------
def reader(returns):
    seen: list = []

    def fn(chunk):
        seen.append(chunk["chunk_id"])
        if isinstance(returns, Exception):
            raise returns
        return returns
    return fn, seen


def test_head_owner_reads_the_previous_chunk_when_the_original_is_not_in_the_context():
    fn, seen = reader(Y.model_dump())
    got = AF.head_owner_cites("답 [1]", [X.model_dump()], [X.model_dump()], [QUOTE], prev_reader=fn)
    assert got is not None
    body, cited, rec = got
    assert body == "답 [1]" and _ids(cited) == [Y.chunk_id] and rec == [{"from": X.chunk_id, "to": Y.chunk_id, "outside": True}]
    assert seen == [X.chunk_id]


def test_head_owner_leaves_the_citation_when_the_previous_chunk_does_not_end_with_the_head():
    wrong = mk("Another page text that does not contain the copied head at its end.", title="Security Awareness", seq=71600, article="Questions and Answers")
    fn, _ = reader(wrong.model_dump())
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [X.model_dump()], [QUOTE], prev_reader=fn) is None
    fn, _ = reader(None)
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [X.model_dump()], [QUOTE], prev_reader=fn) is None


def test_head_owner_leaves_the_citation_when_reading_fails():
    fn, seen = reader(RuntimeError("db down"))
    assert AF.head_owner_cites("답 [1]", [X.model_dump()], [X.model_dump()], [QUOTE], prev_reader=fn) is None and seen == [X.chunk_id]


def test_head_owner_does_not_read_when_the_original_is_in_the_context_or_the_quote_is_not_in_the_head():
    fn, seen = reader(Y.model_dump())
    got = AF.head_owner_cites("답 [1]", [X.model_dump()], [Y.model_dump(), X.model_dump()], [QUOTE], prev_reader=fn)
    assert got is not None and got[2] == [{"from": X.chunk_id, "to": Y.chunk_id}] and seen == []  # 문맥 안의 길(62.52)
    far = "Privacy and public shaming are discussed in the following paragraphs of this long section"
    long_x = mk(f"{X.text.split(chr(10), 1)[1]} {'Filler sentence about the awareness program. ' * 12}{far}.", title="Security Awareness", seq=71600, article="Questions and Answers").model_dump()
    assert AF.head_owner_cites("답 [1]", [long_x], [long_x], [far], prev_reader=fn) is None and seen == []  # 구절이 본문 앞쪽(머리 후보)이 아니면 앞 청크를 읽지 않는다


def prev_of(chunk_by_id):
    def fn(chunk):
        return chunk_by_id.get(chunk["chunk_id"])
    return fn


@pytest.mark.parametrize("multi", [False, True])
def test_graph_swaps_to_the_previous_chunk_outside_the_context_and_does_not_add_it_to_the_context(multi):
    fn, _ = searcher((("프로그램", [X]),))
    m = llm(answer=cite(X, text="구성원은 빠질 수 없습니다"), grounding=GROUNDED)
    build = build_multi_graph if multi else build_graph
    out = run(build(fn, llm=m, grounding_llm=True, prev_chunk=prev_of({X.chunk_id: Y})), Q_OPT)
    assert _ids(out["citations"]) == [Y.chunk_id] and Y.chunk_id not in [c["chunk_id"] for c in out["chunks"]]  # 인용 목록에만 들어간다
    assert out["grounding"]["head_owner"] == [{"from": X.chunk_id, "to": Y.chunk_id, "outside": True}]
    assert sum(1 for t, _ in m.calls if t == "grounding") == 1  # LLM 호출은 늘지 않는다
    assert out["citations"][0]["source_url"] and out["citations"][0]["text"]  # 인용 카드에 필요한 칸


@pytest.mark.parametrize("multi", [False, True])
def test_graph_keeps_the_citation_when_the_previous_chunk_read_fails_or_is_missing(multi):
    for prev in (lambda c: (_ for _ in ()).throw(RuntimeError("db down")), lambda c: None, None):
        fn, _ = searcher((("프로그램", [X]),))
        m = llm(answer=cite(X, text="구성원은 빠질 수 없습니다"), grounding=GROUNDED)
        build = build_multi_graph if multi else build_graph
        out = run(build(fn, llm=m, grounding_llm=True, prev_chunk=prev), Q_OPT)
        assert out["kind"] == "answer" and _ids(out["citations"]) == [X.chunk_id] and "head_owner" not in out["grounding"]


def test_the_service_searches_offer_the_previous_chunk_reader():
    from backend.graph import service_profile as SP

    assert set(SP.service_searches()) == {"page_search", "heading_search", "intro_search", "prev_chunk"}  # heading_search: 사전 등록 62.69


def test_searcher_prev_chunk_reads_the_chunk_just_before_in_the_same_page_version():
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")  # 패키지가 같은 이름의 함수 `search`를 내보내므로 모듈은 이름으로 연다

    class Store:
        rows = {("a", "v1"): {"chunk_id": "a"}, ("b", "v1"): {"chunk_id": "b"}}

        def page_chunks(self, seq, ver):
            return [(("a", "v1"), "t"), (("b", "v1"), "t"), (("c", "v1"), "t")]

        def fetch(self, keys):
            return {k: Y.model_dump() for k in keys if k == ("b", "v1")}

    s = S.Searcher.__new__(S.Searcher)
    s.store = Store()
    s._refresh = lambda: None
    got = s.prev_chunk({"chunk_id": "c", "version_id": "v1", "rule_seq": 5})
    assert got is not None and got.chunk_id == Y.chunk_id
    assert s.prev_chunk({"chunk_id": "a", "version_id": "v1", "rule_seq": 5}) is None  # 첫 청크
    assert s.prev_chunk({"chunk_id": "zz", "version_id": "v1", "rule_seq": 5}) is None  # 모르는 청크
    assert s.prev_chunk({"chunk_id": "c", "version_id": "", "rule_seq": 5}) is None


# ---------- 62.59 앞자리 인용끼리 판정 구절 청크 수 비교 ----------
def two_candidates(quote_chunks, first_cites, second_cites, *, second_answer=None):
    """앞자리 답(첫 후보)은 `first_cites`, 전체 문맥 답(둘째 후보)은 `second_cites`를 인용하는 가짜 모델로 돌린 결과. 판정 구절은 `quote_chunks`의 본문이다."""
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    quote = j(checks=[{"fact": f"사실{i}", "quote": c.text.split("\n", 1)[1]} for i, c in enumerate(quote_chunks)], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
    answer = lambda u: cite(*(second_cites if WIDE_IDS[0] in u else first_cites))  # noqa: E731
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quote, answer=second_answer or answer)
    return m, fn


@pytest.mark.parametrize("multi", [False, True])
def test_second_candidate_wins_when_it_cites_more_judge_quote_chunks_all_in_the_front_slots(multi):
    m, fn = two_candidates([CORE[0], CORE[1], CORE[2]], [CORE[3], CORE[0]], [CORE[1], CORE[2]])
    out = run(graph(multi, fn, m), Q_ESC)
    log = out["best2_log"]
    assert log["rule"] == "core_first" and log["pick"] == 1 and log["why"] == "앞자리 인용끼리 판정 구절 청크 수"
    assert _ids(out["citations"]) == [CORE[1].chunk_id, CORE[2].chunk_id]


@pytest.mark.parametrize("multi", [False, True])
def test_first_candidate_stays_when_the_second_cites_a_widened_slot(multi):
    m, fn = two_candidates([CORE[0], CORE[1], CORE[2]], [CORE[3], CORE[0]], [CORE[1], CORE[2], WIDE[0]])
    log = run(graph(multi, fn, m), Q_ESC)["best2_log"]
    assert log["pick"] == 0 and log["why"] == "판정 구절이 모두 앞자리"


@pytest.mark.parametrize("multi", [False, True])
def test_first_candidate_stays_when_the_second_cites_the_fill_chunk(multi):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    quote = j(checks=[{"fact": f"사실{i}", "quote": c.text.split("\n", 1)[1]} for i, c in enumerate([CORE[0], CORE[1]])], sufficient=True, partial=False, reason="", missing=[], scope_note=None, clarify=None, query="")
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quote, answer=lambda u: cite(*([CORE[0], CORE[1], FILL] if WIDE_IDS[0] in u else [CORE[0]])))
    out = run(graph(multi, fn, m, page_search=pages([FILL])), Q_ESC)
    log = out["best2_log"]
    assert log["pick"] == 0 and log["why"] == "판정 구절이 모두 앞자리"


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("first, second", [
    ([CORE[0], CORE[1]], [CORE[1], CORE[2]]),   # 판정 구절 청크 수가 같음(둘 다 CORE[0..1]이 판정 구절일 때 1 대 1)
    ([CORE[0], CORE[1]], [CORE[0]]),            # 둘째가 더 적음
])
def test_first_candidate_stays_when_the_judge_quote_chunk_count_is_equal_or_less(multi, first, second):
    m, fn = two_candidates([CORE[0], CORE[1]], first, second)
    log = run(graph(multi, fn, m), Q_ESC)["best2_log"]
    assert log["pick"] == 0 and log["why"] == "판정 구절이 모두 앞자리"


@pytest.mark.parametrize("multi", [False, True])
def test_first_candidate_stays_when_the_second_candidate_has_no_citation(multi):
    m, fn = two_candidates([CORE[0], CORE[1]], [CORE[0]], [], second_answer=lambda u: j(asked=["사실"], picks=[], answer="답", citations=[], period_covered=True) if WIDE_IDS[0] in u else cite(CORE[0]))
    log = run(graph(multi, fn, m), Q_ESC)["best2_log"]
    assert log["pick"] == 0


@pytest.mark.parametrize("multi", [False, True])
def test_unwidened_context_keeps_the_old_rule(multi):
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=False, sub_questions=[]), judge=quoting(CORE[0]), answer=lambda u: cite(CORE[0]))
    out = run(graph(multi, fn, m), Q_ESC)
    assert out["best2_log"].get("rule") != "core_first"
