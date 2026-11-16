"""효과 분리 측정용 스위치 6개 시험(2026-11-16). 가짜 모델, 가짜 검색기, 메모리 저장소만 쓴다(키와 네트워크 없음).

스위치마다 (1) 비었거나 없을 때와 `1`일 때의 결과·모델 입력이 같고(지금 동작), (2) `0`이면 그 장치의 동작만 바뀌는지 본다.

| 장치 | 스위치 | 끄면 |
|---|---|---|
| 62.51 | `GRAPH_INTRO_IN_CORE` | 넓힌 첫 검색의 앞자리가 앞 `SEARCH_K`자리뿐이다. 도입부 청크는 판정 입력에서 `[보충]`이고 앞자리 답에 들지 않는다 |
| 62.52 | `GRAPH_CITE_HEAD_OWNER` | 겹친 머리 인용 바로잡기(`head_owner_cites`)를 건너뛴다(62.58, 62.70 M 포함) |
| 62.55 | `GRAPH_FIRST_PAGE_FILL` | 나뉜 질문 첫 검색 뒤 페이지 검색을 부르지 않고 보충 청크가 붙지 않는다 |
| 62.56 | `GRAPH_CITE_EXPAND_NARROW` | 인용 더하기에서 같은 절 제외와 표 행 첫 칸 일치가 빠진다 |
| 62.57 | `GRAPH_CITE_PHRASE_WHOLE_ROWS` | 문장 공유 더하기가 본문 전체 단어열(표 행 포함)로 잰다 |
| 끝 1자리 | `SEARCH_FULL_TAIL` | 0이면 나뉜 질문 k=8 첫 검색에 원 질문 끝자리가 없다(원 질문 목록을 만들지 않는다) |
"""
from __future__ import annotations

import pytest
from test_accuracy_fixes_1113 import FILL, TABLE_ROW_TAIL, WORDS, ch, first_run, pages, row
from test_search_v2 import ROWS, Q, S1, S2, ids, make
from test_search_v2 import row as srow
from test_trace_fixes_1113 import GROUNDED, INTRO_ID, X, Y, _ids, _opt_run, _state, intro_run
from test_trace_fixes_1113 import INTRO as INTRO_CHUNK
from test_widened_first_search import CORE, WIDE, WIDE_IDS

from backend.graph import answer_fixes as AF
from backend.graph.build import core_chunks
from backend.schemas.chunk import SearchQuery

SWITCHES = ("GRAPH_INTRO_IN_CORE", "GRAPH_CITE_HEAD_OWNER", "GRAPH_FIRST_PAGE_FILL", "GRAPH_CITE_EXPAND_NARROW", "GRAPH_CITE_PHRASE_WHOLE_ROWS", "SEARCH_FULL_TAIL")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """62.51~62.57 시험(`test_trace_fixes_1113.py`, `test_accuracy_fixes_1113.py`)과 같은 환경. 여섯 스위치는 비운 채 시작한다."""
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_BEST2_SAMEDOC",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_GROUNDING_QUOTE",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S", "GRAPH_CITE_EXPAND", "GRAPH_CITE_PHRASE", "GRAPH_DROP_SCOPED_CITES",
                 "GRAPH_CITE_CONSENSUS", "GRAPH_CITE_ADD_GUARD", "SEARCH_SUB_MERGE", *SWITCHES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    monkeypatch.setenv("GRAPH_INTRO_FILL", "1")


def _calls(m):
    """가짜 모델이 받은 (단계, 사용자 입력) 목록. 같은 입력이면 같은 측정·재생 열쇠다."""
    return sorted(m.calls)


def _view(out):
    return {"kind": out.get("kind"), "answer": out.get("answer"), "citations": _ids(out.get("citations") or []), "chunks": _ids(out.get("chunks") or []),
            "grounding": {k: v for k, v in (out.get("grounding") or {}).items() if k not in ("candidates", "ms")}}


def test_switch_readers_default_on_and_zero_or_off_turns_them_off(monkeypatch):
    readers = (AF.intro_in_core_enabled, AF.cite_head_owner_enabled, AF.first_page_fill_enabled, AF.cite_expand_narrow_enabled, AF.cite_phrase_whole_rows_enabled)
    for name, read in zip(SWITCHES, readers):
        assert read() is True
        monkeypatch.setenv(name, "1")
        assert read() is True
        for value in ("0", "off"):
            monkeypatch.setenv(name, value)
            assert read() is False
        monkeypatch.delenv(name)


# ---------- 62.51 GRAPH_INTRO_IN_CORE ----------
def test_intro_in_core_off_keeps_only_the_first_slots(monkeypatch):
    both = [*CORE, *WIDE, INTRO_CHUNK]
    state = _state(both, intro_chunk_ids=[INTRO_ID])
    on = [c["chunk_id"] for c in core_chunks(state)]
    monkeypatch.setenv("GRAPH_INTRO_IN_CORE", "1")
    assert [c["chunk_id"] for c in core_chunks(state)] == on == [*(c.chunk_id for c in CORE), INTRO_ID]
    monkeypatch.setenv("GRAPH_INTRO_IN_CORE", "0")
    assert [c["chunk_id"] for c in core_chunks(state)] == [c.chunk_id for c in CORE]          # 62.44 그대로(앞 5자리)
    assert len(core_chunks(_state(both, intro_chunk_ids=[INTRO_ID], retries=1))) == len(both)  # 넓히지 않은 문맥·재검색 뒤는 스위치와 상관없이 전체


@pytest.mark.parametrize("multi", [False, True])
def test_intro_in_core_on_equals_default_and_off_marks_the_intro_chunk_as_extra(monkeypatch, multi):
    base, m0 = intro_run(multi, INTRO_CHUNK)
    monkeypatch.setenv("GRAPH_INTRO_IN_CORE", "1")
    on, m1 = intro_run(multi, INTRO_CHUNK)
    assert _calls(m1) == _calls(m0) and _view(on) == _view(base) and on["best2_log"] == base["best2_log"]
    monkeypatch.setenv("GRAPH_INTRO_IN_CORE", "0")
    off, m2 = intro_run(multi, INTRO_CHUNK)
    assert off["intro_chunk_ids"] == [INTRO_ID] and _ids(off["chunks"]) == _ids(base["chunks"])   # 검색과 문맥은 그대로, 기록도 그대로
    judged = [u for t, u in m2.calls if t == "judge"][0]
    assert f"[보충] chunk_id={INTRO_ID}" in judged and all(f"[보충] chunk_id={i}" in judged for i in WIDE_IDS)
    core_input = [u for t, u in m2.calls if t == "answer" and WIDE_IDS[0] not in u]
    assert len(core_input) == 1 and INTRO_ID not in core_input[0]                                # 앞자리 답이 도입부 청크를 보지 않는다
    assert off["best2_log"]["why"] == "판정 구절이 넓힌 자리에 있음"                              # 도입부 청크가 넓힌 자리로 셈해진다


# ---------- 62.52 GRAPH_CITE_HEAD_OWNER ----------
@pytest.mark.parametrize("multi", [False, True])
def test_head_owner_on_equals_default_and_off_keeps_the_cited_chunk(monkeypatch, multi):
    base, m0 = _opt_run(multi, GROUNDED)
    assert _ids(base["citations"]) == [Y.chunk_id]
    monkeypatch.setenv("GRAPH_CITE_HEAD_OWNER", "1")
    on, m1 = _opt_run(multi, GROUNDED)
    assert _calls(m1) == _calls(m0) and _view(on) == _view(base)
    monkeypatch.setenv("GRAPH_CITE_HEAD_OWNER", "0")
    off, m2 = _opt_run(multi, GROUNDED)
    assert off["kind"] == "answer" and _ids(off["citations"]) == [X.chunk_id] and "head_owner" not in off["grounding"]
    assert "_claim_quotes" not in off["grounding"]
    assert _calls(m2) == _calls(m0)                                                              # 모델 입력은 같다(답 뒤 코드 단계만 다르다)


@pytest.mark.parametrize("multi", [False, True])
def test_head_owner_off_also_skips_the_outside_context_read(monkeypatch, multi):
    from test_accuracy_fixes_1113 import prev_of
    from test_answer_fixes_graph import cite, llm, run, searcher

    from backend.graph.build import build_graph
    from backend.graph.multi import build_multi_graph

    read: list = []

    def prev(chunk):
        read.append(chunk["chunk_id"])
        return prev_of({X.chunk_id: Y})(chunk)

    monkeypatch.setenv("GRAPH_CITE_HEAD_OWNER", "0")
    fn, _ = searcher((("프로그램", [X]),))
    m = llm(answer=cite(X, text="구성원은 빠질 수 없습니다"), grounding=GROUNDED)
    out = run((build_multi_graph if multi else build_graph)(fn, llm=m, grounding_llm=True, prev_chunk=prev), "참여자는 프로그램에서 빠지고 싶으면 어떻게 해?")
    assert _ids(out["citations"]) == [X.chunk_id] and read == [] and "head_owner" not in out["grounding"]


# ---------- 62.55 GRAPH_FIRST_PAGE_FILL ----------
@pytest.mark.parametrize("multi", [False, True])
def test_first_page_fill_on_equals_default_and_off_does_not_call_the_page_search(monkeypatch, multi):
    seen0: list = []
    base, m0 = first_run(multi, page=pages([FILL], seen0))
    assert _ids(base["chunks"])[-1] == FILL.chunk_id and base["search_stats"]["page_fill"] == 1
    monkeypatch.setenv("GRAPH_FIRST_PAGE_FILL", "1")
    seen1: list = []
    on, m1 = first_run(multi, page=pages([FILL], seen1))
    assert _calls(m1) == _calls(m0) and _view(on) == _view(base) and seen1 == seen0
    monkeypatch.setenv("GRAPH_FIRST_PAGE_FILL", "0")
    seen2: list = []
    off, m2 = first_run(multi, page=pages([FILL], seen2))
    no_page, m3 = first_run(multi, page=None)
    assert seen2 == [] and "page_fill" not in off["search_stats"] and FILL.chunk_id not in _ids(off["chunks"])
    assert _ids(off["chunks"]) == _ids(no_page["chunks"]) and _calls(m2) == _calls(m3)         # 페이지 검색을 넘기지 않은 그래프와 같다


@pytest.mark.parametrize("multi", [False, True])
def test_first_page_fill_off_keeps_the_same_page_requery(monkeypatch, multi):
    """끄는 것은 첫 검색 보충뿐이다. 같은 `page_search`를 쓰는 일부 판정 뒤 페이지 재검색(`GRAPH_RESEARCH_SAME_PAGE`)은 그대로다(나뉘지 않은 질문)."""
    from qgraph_fakes import j
    from test_answer_fixes_graph import Q_ESC, cite, llm, run, searcher

    from backend.graph.build import build_graph
    from backend.graph.multi import build_multi_graph

    monkeypatch.setenv("GRAPH_RESEARCH_SAME_PAGE", "1")
    monkeypatch.setenv("GRAPH_FIRST_PAGE_FILL", "0")
    for name in ("GRAPH_JUDGE_QUOTE", "GRAPH_ANSWER_BEST2"):
        monkeypatch.delenv(name)
    partial = j(checks=[{"fact": "빠진 사실", "value": None}], sufficient=False, partial=True, reason="부족", missing=["빠진 사실"], scope_note=None, clarify=None, query="pager rotation")
    seen: list = []
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=False, sub_questions=[]), judge=[partial, j(sufficient=True, reason="", clarify=None)], answer=lambda u: cite(CORE[0]))
    out = run((build_multi_graph if multi else build_graph)(fn, llm=m, decompose=True, max_research=1, page_search=pages([FILL], seen)), Q_ESC)
    assert len(seen) == 1 and seen[0]["query"] == "pager rotation" and FILL.chunk_id in _ids(out["chunks"])


# ---------- 62.56 GRAPH_CITE_EXPAND_NARROW ----------
DESC = "Straight forward change minimal investigation required for this class of work item"


def _expand_cases():
    cited = [ch(f"30 days {WORDS}", seq=80001, article="Fees > Table")]
    same = ch(f"Also, 30 days {WORDS}", seq=80001, article="Fees > Table")   # 앞에 글이 있어 겹친 머리로 떼이지 않는다
    same["chunk_id"] = "same-section-chunk"
    other_page = ch(f"30 days {WORDS}", seq=80002, article="Fees > Table")
    rcited = [ch(row("InfraSecEffort Small", 2, DESC), seq=80010, article="Infra > Effort")]
    other_label = ch(row("vuln-mgmt Small", 2, DESC), seq=80011, article="Vuln > Effort")
    same_label = ch(row("InfraSecEffort Small", 2, DESC), seq=80012, article="Copy > Effort")
    return {"same": (cited, [cited[0], same]), "other_page": (cited, [cited[0], other_page]),
            "other_label": (rcited, [rcited[0], other_label]), "same_label": (rcited, [rcited[0], same_label])}


def _picked(picker, cases):
    return {k: [c["chunk_id"] for c, _ in picker(cited, ctx)] for k, (cited, ctx) in cases.items()}


def test_cite_expand_narrow_on_equals_default_and_off_restores_the_older_rule(monkeypatch):
    cases = _expand_cases()
    base = _picked(AF.pick_extra, cases)
    assert base["same"] == [] and base["other_label"] == [] and base["other_page"] and base["same_label"]
    monkeypatch.setenv("GRAPH_CITE_EXPAND_NARROW", "1")
    assert _picked(AF.pick_extra, cases) == base
    monkeypatch.setenv("GRAPH_CITE_EXPAND_NARROW", "0")
    off = _picked(AF.pick_extra, cases)
    assert off["same"] == ["same-section-chunk"]                                   # (가) 같은 절 제외가 빠진다
    assert off["other_label"] == [cases["other_label"][1][1]["chunk_id"]]           # (나) 표 행 첫 칸 일치가 빠진다
    assert off["other_page"] == base["other_page"] and off["same_label"] == base["same_label"]   # 그 밖의 더하기는 같다


def test_cite_expand_narrow_does_not_touch_the_phrase_rule(monkeypatch):
    cited = [ch(f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}", seq=80040, article="Infra", title="Infrastructure Security")]
    other_row = ch(f"Label: ~vuln-mgmt::Small | {TABLE_ROW_TAIL}", seq=80041, article="App", title="Application Security")
    monkeypatch.setenv("GRAPH_CITE_EXPAND_NARROW", "0")
    assert AF.pick_phrase_extra(cited, [cited[0], other_row]) == []


# ---------- 62.57 GRAPH_CITE_PHRASE_WHOLE_ROWS ----------
def _phrase_cases():
    cited = [ch(f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}", seq=80040, article="Infra", title="Infrastructure Security")]
    other_row = ch(f"Label: ~vuln-mgmt::Small | {TABLE_ROW_TAIL}", seq=80041, article="App", title="Application Security")
    copy = ch(f"Label: InfraSecEffort::Small | {TABLE_ROW_TAIL}\nOther: x", seq=80042, article="Copy", title="Infrastructure Security")
    sent = "Patch releases are deployed to production during the scheduled patch window after the release manager approves the package."
    pcited = [ch(sent, seq=80050, article="Window", title="Patch Releases")]
    prose = ch(f"For deployments, {sent}", seq=80051, article="Exec", title="Deployments")
    same_page = ch(sent + " More text.", seq=80050, article="Other", title="Patch Releases")
    team = ch(sent, seq=80052, article="Notes", title="Delivery Group")
    return {"tail_row": (cited, [cited[0], other_row]), "whole_row": (cited, [cited[0], copy]),
            "prose": (pcited, [pcited[0], same_page, team, prose])}


def test_cite_phrase_whole_rows_on_equals_default_and_off_restores_the_older_rule(monkeypatch):
    cases = _phrase_cases()
    base = _picked(AF.pick_phrase_extra, cases)
    assert base["tail_row"] == [] and base["whole_row"] and base["prose"]
    monkeypatch.setenv("GRAPH_CITE_PHRASE_WHOLE_ROWS", "1")
    assert _picked(AF.pick_phrase_extra, cases) == base
    monkeypatch.setenv("GRAPH_CITE_PHRASE_WHOLE_ROWS", "0")
    off = _picked(AF.pick_phrase_extra, cases)
    assert off["tail_row"] == [cases["tail_row"][1][1]["chunk_id"]]                  # 뒤 칸만 같은 다른 표의 행을 다시 같은 문장으로 센다(62.57 이전)
    assert off["whole_row"] == base["whole_row"] and off["prose"] == base["prose"]   # 산문 규칙, 같은 페이지·다른 팀 제외는 그대로


def test_cite_phrase_whole_rows_does_not_touch_the_value_rule(monkeypatch):
    cases = _expand_cases()
    base = _picked(AF.pick_extra, cases)
    monkeypatch.setenv("GRAPH_CITE_PHRASE_WHOLE_ROWS", "0")
    assert _picked(AF.pick_extra, cases) == base


# ---------- 끝 1자리 규칙 SEARCH_FULL_TAIL ----------
Z_ROWS = ROWS + [srow("z1", [2.0, 0, 0], page=30)]   # 전체 질문에만 아주 가까운 청크: 끝자리가 있어야 들어온다


def _split_search(**cfg):
    s = make(Z_ROWS, **cfg)
    seen: list = []
    real = s.store.vector_top
    s.store.vector_top = lambda *a, **k: (seen.append(1), real(*a, **k))[1]
    return ids(s.search(SearchQuery(query=Q, sub_queries=[S1, S2], k=8))), len(seen)


def test_full_tail_on_equals_default_and_zero_drops_the_original_question_slot(monkeypatch):
    base, n0 = _split_search()
    assert base == ["a1", "c1", "a2", "c2", "a3", "b2", "b3", "z1"] and n0 == 3       # 하위 질문 2개 + 원 질문 1개 벡터 질의
    monkeypatch.setenv("SEARCH_FULL_TAIL", "1")
    assert _split_search() == (base, n0)
    for off in ("0", "off"):
        monkeypatch.setenv("SEARCH_FULL_TAIL", off)
        got, n = _split_search()
        assert "z1" not in got and len(got) == 8 and n == 2                           # 원 질문 목록을 만들지 않는다
        assert got == ["a1", "c1", "a2", "c2", "a3", "c3", "b2", "b3"]               # 하위 질문만 번갈아 8자리 → 링크 확장 L1x2(뒤 2자리)
        assert _split_search(link_n=0)[0] == ["a1", "c1", "a2", "c2", "a3", "c3", "a4", "c4"]


def test_full_tail_does_not_touch_default_k_or_team_searches(monkeypatch):
    def run_all():
        s = make(Z_ROWS)
        return (ids(s.search(SearchQuery(query=Q, sub_queries=[S1, S2]))), ids(s.search(SearchQuery(query=Q))),
                ids(s.search(SearchQuery(query=Q, sub_queries=[Q, S2], k=8))))
    base = run_all()
    monkeypatch.setenv("SEARCH_FULL_TAIL", "0")
    assert run_all() == base                                                           # k=5, 나뉘지 않은 질문, 합동 검토 팀 검색은 끝자리 규칙을 타지 않는다


def test_full_tail_is_capped_below_k(monkeypatch):
    monkeypatch.setenv("SEARCH_FULL_TAIL", "2")
    got, _ = _split_search(link_n=0)
    assert got[-2:] == ["z1", "a4"] and got[:6] == ["a1", "c1", "a2", "c2", "a3", "c3"]   # 끝 2자리가 원 질문 목록
    monkeypatch.setenv("SEARCH_FULL_TAIL", "99")
    got, _ = _split_search(link_n=0)
    assert len(got) == 8 and got[0] == "a1"                                           # k-1까지만(하위 질문 1자리는 남는다)
