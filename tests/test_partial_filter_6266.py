"""일부 답에서 판정 구절 청크 밖만 인용한 문장 빼기(사전 등록 62.66) 시험. 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음).

일부 판정(`judge_partial`)으로 끝난 답에서, 문장이 단 인용이 모두 판정 구절 청크(`judge_quote_ids`) 밖이면 그 문장을 뺀다.
판정 구절 청크가 섞인 문장, 표시 없는 문장은 그대로 둔다. 판정 구절 청크를 모르거나, 일부 답이 아니거나, 빼면 판정 구절 청크를 인용한 문장이 남지 않으면 답은 그대로다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j
from test_answer_fixes_graph import Q_ESC, SUBS, llm, mk, run, searcher

from backend.graph import answer_fixes as AF
from backend.graph.build import MSG_PARTIAL_NOTE, build_graph
from backend.graph.multi import build_multi_graph

JUDGED = mk("If the EOC does not respond, the incident is escalated to the IMOC within fifteen minutes.", title="Incident Management", seq=73001, article="Escalation")
OTHER = mk("Individual requests for unrelated software must be submitted through the dedicated intake form.", title="Software Intake", seq=73002, article="Intake")
THIRD = mk("The IMOC pages the infrastructure leadership when the escalation has not been acknowledged.", title="Incident Management", seq=73003, article="Leadership")
ALL = [JUDGED, OTHER, THIRD]
SENT_A, SENT_B = "EOC가 응답하지 않으면 IMOC로 올립니다.", "무관한 요청은 접수 양식으로 냅니다."


def _quote(chunk) -> str:
    return chunk.text.split("\n", 1)[1]


def _judge(*, partial: bool = True, quote_from=JUDGED) -> str:
    """사실 둘 중 첫째만 구절이 있으면 일부 판정, 둘 다 있으면 충분 판정이다(인용 먼저 판정)."""
    second = {"fact": "사실2", "quote": _quote(THIRD)} if not partial else {"fact": "사실2", "quote": "NOTHING FOUND"}
    return j(checks=[{"fact": "사실1", "quote": _quote(quote_from)}, second], sufficient=not partial, partial=partial, reason="일부" if partial else "",
             missing=["사실2"] if partial else [], scope_note=None, clarify=None, query="EOC escalation")


def _answer(text: str, *chunks):
    return j(asked=["사실"], picks=[], answer=text, citations=[{"chunk_id": c.chunk_id} for c in chunks], period_covered=True)


def _run(multi, monkeypatch, *, judge, answer, best2=True):
    monkeypatch.setenv("GRAPH_JUDGE_QUOTE", "1")
    if best2:
        monkeypatch.setenv("GRAPH_ANSWER_BEST2", "1")
    else:
        monkeypatch.delenv("GRAPH_ANSWER_BEST2", raising=False)
    fn, _ = searcher((("EOC", ALL),))
    m = llm(decompose=j(split=True, sub_questions=SUBS), judge=judge, answer=answer)
    build = build_multi_graph if multi else build_graph
    return run(build(fn, llm=m, decompose=True, max_research=1), Q_ESC)


def _ids(out) -> list[str]:
    return [c["chunk_id"] for c in out["citations"]]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("GRAPH_ANSWER_WAIT_S", "GRAPH_ANSWER_BUDGET_S", "GRAPH_STOP_STALLED_SEARCH", "GRAPH_JUDGE_ANSWER", "GRAPH_SPECULATE_FIRST",
                 "GRAPH_PARALLEL_INTAKE", "GRAPH_SKIP_FIRST_REWRITE", "GRAPH_JUDGE_VOTE", "SEARCH_DECOMPOSE", "USE_SKILLS", "GRAPH_DECOMPOSE_CAP_S"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_STRUCTURED", "judge,answer,grounding")
    monkeypatch.setenv("GRAPH_JUDGE_QUERY", "1")


def _two_sentences():
    return _answer(f"{SENT_A} [{JUDGED.chunk_id}] {SENT_B} [{OTHER.chunk_id}]", JUDGED, OTHER)


# ---------- 그래프 ----------
@pytest.mark.parametrize("multi", [False, True])
def test_partial_answer_drops_the_sentence_cited_only_outside_the_judge_quote(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(), answer=_two_sentences())
    assert out["kind"] == "answer" and out["judge_partial"] is True
    assert _ids(out) == [JUDGED.chunk_id]
    assert SENT_A in out["answer"] and SENT_B not in out["answer"] and MSG_PARTIAL_NOTE in out["answer"]
    assert out["grounding"]["partial_filter"] == {"result": "dropped", "sentences": 1, "chunks": [OTHER.chunk_id]}


@pytest.mark.parametrize("multi", [False, True])
def test_a_sentence_cited_inside_the_judge_quote_stays(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(), answer=_answer(f"{SENT_A} [{JUDGED.chunk_id}]", JUDGED))
    assert out["kind"] == "answer" and _ids(out) == [JUDGED.chunk_id] and "partial_filter" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_a_sentence_citing_both_inside_and_outside_stays_whole(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(), answer=_answer(f"{SENT_A} [{JUDGED.chunk_id}][{OTHER.chunk_id}]", JUDGED, OTHER))
    assert out["kind"] == "answer" and sorted(_ids(out)) == sorted([JUDGED.chunk_id, OTHER.chunk_id]) and "partial_filter" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_an_answer_that_is_not_partial_is_untouched(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(partial=False), answer=_two_sentences())
    assert out["kind"] == "answer" and not out["judge_partial"]
    assert sorted(_ids(out)) == sorted([JUDGED.chunk_id, OTHER.chunk_id]) and SENT_B in out["answer"] and "partial_filter" not in out["grounding"]


@pytest.mark.parametrize("multi", [False, True])
def test_without_the_judge_quote_chunks_nothing_is_dropped(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(), answer=_two_sentences(), best2=False)  # `judge_quote_ids`는 답 두 개 고르기(BEST2)가 켜져 있을 때만 채워진다
    assert out["kind"] == "answer" and out["judge_partial"] is True and not out.get("judge_quote_ids")
    assert sorted(_ids(out)) == sorted([JUDGED.chunk_id, OTHER.chunk_id]) and SENT_B in out["answer"]


@pytest.mark.parametrize("multi", [False, True])
def test_when_no_sentence_cites_the_judge_quote_the_answer_stays_as_it_was(monkeypatch, multi):
    out = _run(multi, monkeypatch, judge=_judge(quote_from=THIRD),
               answer=_answer(f"{SENT_A} [{JUDGED.chunk_id}] {SENT_B} [{OTHER.chunk_id}]", JUDGED, OTHER))
    assert out["kind"] == "answer" and out["answer"].strip() and MSG_PARTIAL_NOTE in out["answer"]
    assert sorted(_ids(out)) == sorted([JUDGED.chunk_id, OTHER.chunk_id]) and "partial_filter" not in out["grounding"]


# ---------- 함수 ----------
def _cited(*chunks):
    return [c.model_dump() for c in chunks]


def test_drop_removes_outside_sentences_and_keeps_line_breaks():
    draft = f"{SENT_A} [{JUDGED.chunk_id}] {SENT_B} [{OTHER.chunk_id}]\n둘째 줄입니다. [{OTHER.chunk_id}]\n셋째 줄입니다. [{THIRD.chunk_id}]"
    got = AF.drop_unjudged_cites(draft, _cited(JUDGED, OTHER, THIRD), [JUDGED.chunk_id, THIRD.chunk_id])
    assert got is not None
    text, kept, gone, n = got
    assert text == f"{SENT_A} [{JUDGED.chunk_id}]\n셋째 줄입니다. [{THIRD.chunk_id}]" and n == 2
    assert [c["chunk_id"] for c in kept] == [JUDGED.chunk_id, THIRD.chunk_id] and gone == [OTHER.chunk_id]


def test_drop_keeps_a_sentence_without_a_mark_and_an_other_citation_of_a_kept_chunk():
    draft = f"표시 없는 문장입니다. {SENT_A} [{JUDGED.chunk_id}] {SENT_B} [{OTHER.chunk_id}]"
    text, kept, gone, n = AF.drop_unjudged_cites(draft, _cited(JUDGED, OTHER), [JUDGED.chunk_id])
    assert text.startswith("표시 없는 문장입니다.") and SENT_B not in text and n == 1


@pytest.mark.parametrize("quote_ids", [None, [], [""]])
def test_drop_is_none_when_the_judge_quote_chunks_are_unknown(quote_ids):
    assert AF.drop_unjudged_cites(f"{SENT_B} [{OTHER.chunk_id}]", _cited(OTHER), quote_ids) is None


def test_drop_is_none_when_nothing_is_outside():
    assert AF.drop_unjudged_cites(f"{SENT_A} [{JUDGED.chunk_id}]", _cited(JUDGED), [JUDGED.chunk_id]) is None


def test_drop_is_none_when_no_sentence_would_cite_the_judge_quote():
    draft = f"{SENT_B} [{OTHER.chunk_id}] {SENT_A} [{THIRD.chunk_id}]"
    assert AF.drop_unjudged_cites(draft, _cited(OTHER, THIRD), [JUDGED.chunk_id]) is None  # 모두 빠지면 빈 답이 되므로 그대로 둔다
