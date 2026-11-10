"""합동 검토 대 단일 측정 도구(`evals/agent/exp_joint_review.py`)의 계산 함수 시험. 키와 네트워크, 색인 스냅샷이 없어도 돈다."""
from __future__ import annotations

from types import SimpleNamespace

from evals.agent import exp_joint_review as J
from evals.retrieval.gold import GoldRef


def test_percentile_is_nearest_rank_like_run_eval():
    values = [float(i) for i in range(1, 25)]  # 24회
    assert J.percentile(values, 0.5) == 12.0
    assert J.percentile(values, 0.95) == 23.0
    assert J.percentile([], 0.5) is None


def test_trace_summary_counts_translation_and_cost():
    calls = [{"step": "classify/classify", "cost_usd": 0.001, "ok": True}, {"step": "translate_sentence", "cost_usd": 0.0005, "ok": True},
             {"step": "judge/judge", "cost_usd": None, "ok": False, "input_tokens": 10, "output_tokens": 2}]
    s = J.summarize_trace(calls)
    assert s["llm_calls"] == 3 and s["translation_calls"] == 1
    assert s["cost_usd"] == 0.0015 and s["cost_unknown_calls"] == 1 and s["failed_calls"] == 1


def test_grade_uses_the_existing_gold_matcher():
    item = {"gold": [GoldRef(chunk_id="a" * 16), GoldRef(chunk_id="b" * 16)]}
    cited = [SimpleNamespace(chunk_id="a" * 16), SimpleNamespace(chunk_id="c" * 16)]
    assert J.grade(item, cited) == {"cited_on_gold": 1, "gold_total": 2, "gold_hit": 1}


def test_stability_is_mean_pairwise_jaccard_per_item():
    rows = [{"id": "x", "cited": ["a", "b"]}, {"id": "x", "cited": ["a", "b"]}, {"id": "x", "cited": ["a", "c"]},
            {"id": "y", "cited": []}, {"id": "y", "cited": []}]
    # x: (1 + 1/3 + 1/3) / 3 = 0.5556, y: 1.0 -> 평균 0.7778
    assert J.jaccard_stability(rows) == 0.7778
