"""평가 실행기와 지표 시험. 값은 손으로 계산했다."""
from __future__ import annotations

import pytest
from fake_search import fake_search
from qgraph_fakes import j, normal_llm

from backend.graph.build import build_graph
from evals.agent.judge import parse_judgement
from backend.schemas import SearchQuery
from evals.agent.run_eval import _row, compute_metrics, run_eval
from evals.retrieval.gold import GoldRef


def R(**kw):
    base = dict(id="x", expect_refusal=False, answered=True, cited=[], cited_on_gold=0, gold_total=1, gold_hit=0, dropped=[], drafted=True,
                refuse_stage="", shows_date=True, latency_s=1.0)
    base.update(kw)
    return base


def test_metrics_hand_computed():
    rows = [
        R(id="a", gold_total=2, gold_hit=1, cited=["c1"], cited_on_gold=1),  # 인용률 0.5
        R(id="b", gold_hit=1, cited=["c3", "zz"], cited_on_gold=1),  # 인용률 1, 오답 근거
        R(id="c", answered=False, refuse_stage="answer_check"),  # 과잉 거절, 답 단계
        R(id="d", expect_refusal=True, answered=False, gold_total=0, drafted=False, refuse_stage="before_answer"),  # 올바른 거절
        R(id="e", expect_refusal=True, gold_total=0, cited=["c9"]),  # 답하면 안 되는데 답함
        R(id="f", gold_hit=1, cited=["c5"], cited_on_gold=1, dropped=[{"chunk_id": "fake"}]),  # 가짜 인용을 걸러냄
    ]
    m = compute_metrics(rows)
    assert m["n"] == 6
    assert m["cited_correct_rate"] == pytest.approx((0.5 + 1 + 0 + 1) / 4)
    assert m["wrong_citation_rate"] == pytest.approx(1 / 3)
    assert m["over_refusal_rate"] == pytest.approx(1 / 4)
    assert m["correct_refusal_rate"] == pytest.approx(1 / 2)
    assert m["hallucination_risk_rate"] == pytest.approx(2 / 5)
    assert m["answer_check_refusals"] == 1
    assert m["over_refusal_rate_without_answer_check"] == 0
    assert m["citation_accuracy"] == pytest.approx((1 + 0.5 + 1) / 3)


def test_zero_denominators_are_none():
    m = compute_metrics([R(expect_refusal=True, answered=False, gold_total=0, drafted=False, refuse_stage="before_answer")])
    assert m["cited_correct_rate"] is None and m["wrong_citation_rate"] is None and m["over_refusal_rate"] is None
    assert m["correct_refusal_rate"] == 1.0 and m["hallucination_risk_rate"] is None


def test_runner_end_to_end_with_fake_model():
    seq = 90002  # 합성 코퍼스의 장애 대응 런북
    items = [
        {"id": 1, "kind": "relevant", "input": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=seq, label="런북")]},
        {"id": 2, "kind": "irrelevant", "irrelevant_type": "out_of_domain", "input": "연봉 협상 방법을 알려 주세요", "gold": []},
    ]

    def judge(user):
        return j(sufficient=False, reason="없음", clarify=None) if "연봉" in user else j(sufficient=True)

    llm = normal_llm(judge=judge)
    report = run_eval(build_graph(fake_search, llm=llm, grounding_llm=False), items)
    a, b = report["rows"]
    assert a["answered"] and a["gold_hit"] == 1 and a["shows_date"]
    assert not b["answered"] and b["refuse_stage"] == "before_answer"
    assert report["metrics"]["correct_refusal_rate"] == 1.0 and report["metrics"]["over_refusal_rate"] == 0.0


def test_failed_item_is_counted_as_error_and_run_continues():
    def boom(q):
        raise RuntimeError("검색 실패")

    item = {"id": 1, "kind": "relevant", "input": "질문", "gold": [GoldRef(rule_seq=1)]}
    m = run_eval(build_graph(boom, llm=normal_llm()), [item, {**item, "id": 2}])["metrics"]
    assert m["n"] == 2 and m["errors"] == 2 and m["over_refusal_rate"] == 1.0


def test_judge_parsing_does_not_invent_a_score():
    assert parse_judgement('```json {"grounded": true, "accurate": false, "reason": "x"} ```').score == 0.5
    broken = parse_judgement("모르겠음")
    assert broken.parse_ok is False and broken.score is None


def test_gold_hit_counts_only_matching_citations():
    chunk = fake_search(SearchQuery(query="SEV2 최초 대응", k=1))[0].model_dump()
    out = {"kind": "answer", "answer": chunk["version_date"], "citations": [chunk], "chunks": [chunk]}
    item = {"id": 1, "kind": "relevant", "input": "질문"}
    hit = _row({**item, "gold": [GoldRef(rule_seq=chunk["rule_seq"])]}, out, 0.1)
    miss = _row({**item, "gold": [GoldRef(rule_seq=1)]}, out, 0.1)
    assert (hit["gold_hit"], hit["cited_on_gold"]) == (1, 1)
    assert (miss["gold_hit"], miss["cited_on_gold"]) == (0, 0)
