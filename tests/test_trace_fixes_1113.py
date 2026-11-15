"""2026-11-13 수정 시험: 측정 기록의 답 경로(`path`).
가짜 모델, 가짜 검색기, 메모리 저장소만 쓴다(키와 네트워크 없음). 62.51(넓힌 첫 검색의 앞자리)과 62.52(겹친 머리 인용 바로잡기) 시험은 사전 등록 62.72로 그 장치를 코드째 제거하면서 지웠다.

- 62.72 뒤: 근거 구절이 인용 청크의 겹친 머리에만 있어도 인용을 바꾸지 않는다(제거 확인).
- path: `done.data.path`는 하위 질문, 문맥 청크 id, 판정 구절이 든 청크 id(구절 글은 없음), 답 후보와 고른 쪽을 싣는다. 답 경로는 읽지 않는다.
"""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import ESC, IMOC, Q_ESC, SUBS, cite, llm, mk, run, searcher
from test_widened_first_search import CORE, WIDE, quoting

from backend.graph import answer_fixes as AF
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph
from backend.graph.stream import stream_events
from backend.services.step_cost import path_meta

INTRO = mk("Overview of the incident management route for the EOC and the IMOC.", title="Incident Management", seq=71500, article="Overview")
INTRO_ID = INTRO.chunk_id


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER",
                 "GRAPH_SPECULATE_FIRST", "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "GRAPH_GROUNDING_QUOTE",
                 "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")


def graph(multi, fn, m, **kw):
    return (build_multi_graph if multi else build_graph)(fn, llm=m, judge_answer="parallel_all", grounding_llm=True, **kw)


# ---------- 62.52 겹친 머리(제거 확인) ----------
HEAD = "Team members can not opt out of this program because it keeps team members, customers and the company secure."
Y = mk(f"Questions and Answers. I do not want to be included, how do I remove myself? {HEAD}", title="Security Awareness", seq=71600, article="Questions and Answers")
X = mk(f"{HEAD} Privacy and public shaming are discussed in the following paragraphs of this section.", title="Security Awareness", seq=71600, article="Questions and Answers")
QUOTE = "Team members can not opt out of this program"


def _ids(cs):
    return [c["chunk_id"] for c in cs]


GROUNDED = j(claims=[{"claim": "구성원은 빠질 수 없다", "quote": QUOTE, "scope": None}], reason="", grounded=True, reason_code="", unsupported_sentences=[])
Q_OPT = "참여자는 프로그램에서 빠지고 싶으면 어떻게 해?"


@pytest.mark.parametrize("multi", [False, True])
def test_graph_keeps_the_citation_when_the_quote_is_only_in_the_copied_head(multi):
    """사전 등록 62.72: 겹친 머리 인용 바로잡기를 제거했다. 구절이 겹친 머리에만 있어도 답이 인용한 청크 그대로이고 기록 칸도 없다."""
    fn, _ = searcher((("프로그램", [Y, X]),))
    m = llm(answer=cite(X, text="구성원은 빠질 수 없습니다"), grounding=GROUNDED)
    out = run((build_multi_graph if multi else build_graph)(fn, llm=m, grounding_llm=True), Q_OPT)
    assert out["kind"] == "answer" and _ids(out["citations"]) == [X.chunk_id]
    assert "head_owner" not in out["grounding"] and "_claim_quotes" not in out["grounding"]
    assert sum(1 for t, _ in m.calls if t == "grounding") == 1


GROUNDED = j(claims=[{"claim": "구성원은 빠질 수 없다", "quote": QUOTE, "scope": None}], reason="", grounded=True, reason_code="", unsupported_sentences=[])
Q_OPT = "참여자는 프로그램에서 빠지고 싶으면 어떻게 해?"


def _opt_run(multi, grounding, *, answer=None, **kw):
    fn, _ = searcher((("프로그램", [Y, X]),))
    m = llm(answer=answer or cite(X, text="구성원은 빠질 수 없습니다"), grounding=grounding)
    build = build_multi_graph if multi else build_graph
    out = run(build(fn, llm=m, grounding_llm=True, **kw), Q_OPT)
    return out, m


# ---------- path (측정 기록) ----------
def test_quote_rows_lists_only_chunk_ids_per_fact():
    chunks = [CORE[0].model_dump(), INTRO.model_dump()]
    obj = {"checks": [{"fact": "사실 하나", "quote": CORE[0].text.split("\n", 1)[1]}, {"fact": "사실 둘", "quote": "NOTHING FOUND"},
                      {"fact": "사실 셋", "quote": INTRO.text.split("\n", 1)[1]}, {"fact": "사실 넷", "quote": "x"}]}
    assert AF.quote_rows(obj, chunks) == [[CORE[0].chunk_id], [], [INTRO_ID], []]
    assert AF.quote_rows(None, chunks) == [] and AF.quote_rows({"checks": "x"}, chunks) == []
    assert len(AF.quote_rows({"checks": [{"fact": "f", "quote": "NOTHING FOUND"}] * 12}, chunks)) == 8


def _full_run(multi=False):
    """나뉜 질문, 문맥은 `INTRO`와 앞 청크들(검색 k=5). 판정 구절과 답 인용이 모두 `INTRO`다."""
    fn, _ = searcher((("EOC", [INTRO, *CORE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(INTRO), answer=lambda u: cite(INTRO))
    return run(graph(multi, fn, m, decompose=True, max_research=1), Q_ESC)


@pytest.mark.parametrize("multi", [False, True])
def test_path_meta_has_the_sub_queries_context_ids_quotes_and_the_pick(multi):
    out = _full_run(multi)
    path = path_meta(out)["path"]
    assert path["sub_queries"] == SUBS and path["context_ids"] == _ids(out["chunks"]) and "intro_chunk_ids" not in path
    assert path["judge_quote_ids"] == [INTRO_ID] and path["judge_quotes"] == [[INTRO_ID]]
    assert path["best2"]["pick"] == 0 and path["best2"]["rule"] == "s_in,s_out" and path["retries"] == 0
    assert "timing" not in path and "vote_s" not in path   # 요청 집계(`step_cost.begin`) 밖에서는 단계 시간을 싣지 않는다(62.72)
    assert path["grounding"]["llm"] == "grounded"
    flat = repr(path)
    assert "quote" not in path["best2"] and INTRO.text.split("\n", 1)[1] not in flat  # 구절 글은 싣지 않는다


def test_path_meta_is_empty_without_a_search():
    assert path_meta({"kind": "refuse", "answer": "도메인 밖"}) == {}
    assert path_meta({"chunks": [], "kind": "refuse"}) == {}
    assert path_meta({}) == {}


def test_path_meta_does_not_change_the_answer_and_the_done_event_carries_it():
    fn, _ = searcher((("EOC", [INTRO, *CORE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(INTRO), answer=lambda u: cite(INTRO))
    g = build_graph(fn, llm=m, judge_answer="parallel_all", decompose=True, max_research=1)
    events = list(stream_events(g, {"question": Q_ESC, "user_id": "u1", "thread_id": "tp", "as_of": "2025-06-01"}, thread_id="tp"))
    done = events[-1]
    assert done.type == "done" and done.data["path"]["sub_queries"] == SUBS and done.data["path"]["judge_quotes"] == [[INTRO_ID]]
    assert done.data["answer_id"] and "refuse_stage" not in done.data  # 기존 칸은 그대로
    assert [e.type for e in events].count("citation") == 1


def test_done_has_no_path_without_a_search():
    m = llm(classify=j(route="out_of_domain"))
    g = build_graph(lambda q: [ESC, IMOC], llm=m)
    events = list(stream_events(g, {"question": "오늘 점심 뭐 먹지?", "user_id": "u1", "thread_id": "tn", "as_of": "2025-06-01"}, thread_id="tn"))
    assert events[-1].type == "done" and "path" not in events[-1].data


def test_judge_quotes_do_not_exist_without_the_best_of_two_switch(monkeypatch):
    monkeypatch.delenv("GRAPH_ANSWER_BEST2")
    fn, _ = searcher((("EOC", [*CORE, *WIDE]),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=quoting(CORE[0]), answer=lambda u: cite(CORE[0]))
    out = run(build_graph(fn, llm=m, judge_answer="parallel_all", decompose=True, max_research=1), Q_ESC)
    assert "judge_quotes" not in out and "judge_quote_ids" not in out


