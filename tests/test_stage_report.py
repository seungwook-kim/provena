"""`evals/agent/stage_report.py` 시험: 단계 나누기, 비용, 회차 p95 대조. 작은 가짜 결과 폴더로 돈다(네트워크·DB 없음)."""
from __future__ import annotations

import json

import pytest

from evals.agent import stage_report as S

PRICES = {"default": {"input": 0.10, "output": 0.50}, "models": {}}


def call(step, seconds, i=1000, o=100):
    return {"step": step, "seconds": seconds, "model": "anthropic/claude-haiku-5.5", "input_tokens": i, "output_tokens": o}


def row(rid, latency, llm, searches=()):
    return {"id": rid, "latency_s": latency, "cost_usd": 0.0, "llm_trace": llm,
            "retrieval_calls": [{"wall_s": w, "trace": {"ms": {"translate": 0.0, "embed": 100.0, "vector": 50.0, "total": w * 1000}}} for w in searches]}


ROWS = [
    # 번역 LLM(0.4초)은 검색 호출(1.0초) 안에서 돈다: 시간은 검색 1.0초에 이미 있고 비용만 검색에 붙는다
    row(1, 6.0, [call("classify/classify", 1.0), call("translate_sentence", 0.4), call("judge/judge", 1.0),
                 call("write_answer/answer", 2.0), call("ground/grounding", 1.0)], searches=[1.0]),
    row(2, 2.0, [call("classify/classify", 2.0)]),     # 검색 없이 끝난 질문(되묻기 등)
]


def write_run(tmp_path, name, rows, p95=None):
    for arm in S.ARMS:
        d = tmp_path / name / arm
        d.mkdir(parents=True)
        (d / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        val = p95 if p95 is not None else S._p95([r["latency_s"] for r in rows])
        (d / "summary.json").write_text(json.dumps({"metrics": {"latency_p95_s": val}}), encoding="utf-8")
    return tmp_path / name


def test_stages_split_time_and_cost():
    out = S.summarize(ROWS, PRICES)
    st = out["stages"]
    assert st["search"]["n"] == 1 and st["search"]["p50"] == 1.0           # 번역 0.4초를 두 번 세지 않는다
    assert st["plan"]["n"] == 2 and sorted([st["plan"]["p50"], st["plan"]["p95"]]) == [2.0, 2.0]
    assert st["generate"]["n"] == 1 and st["generate"]["p95"] == 2.0
    assert st["verify"]["n"] == 1 and st["verify"]["p95"] == 1.0
    one = (1000 * 0.10 + 100 * 0.50) / 1_000_000                            # 호출 하나의 단가표 비용
    assert st["search"]["cost_per_request"] == pytest.approx(one / 2)      # 번역 비용은 검색 몫, 없는 행은 0으로 평균
    assert st["generate"]["cost_per_request"] == pytest.approx(one / 2)
    assert out["total"]["cost_per_request"] == pytest.approx(6 * one / 2)
    assert out["residual_s"]["max"] == pytest.approx(0.0)                   # 전체 = 검색 + 번역 뺀 LLM


def test_reported_cost_wins_over_price_table():
    rep = {**call("write_answer/answer", 2.0), "reported_cost_usd": 0.00002}     # 캐시가 맞아 정가보다 싸게 청구된 호출
    out = S.summarize([row(4, 3.0, [call("classify/classify", 1.0), rep])], PRICES)
    one = (1000 * 0.10 + 100 * 0.50) / 1_000_000
    assert out["stages"]["generate"]["cost_per_request"] == pytest.approx(0.00002)
    assert out["total"]["cost_per_request"] == pytest.approx(one + 0.00002)
    assert out["cost_source_calls"] == {"reported": 1, "price_table": 1}


def test_unknown_step_stops():
    with pytest.raises(SystemExit, match="단계 표에 없는"):
        S.summarize([row(3, 1.0, [call("새/단계", 1.0)])], PRICES)


def test_p95_matches_summary_and_stops_when_not(tmp_path):
    good = write_run(tmp_path, "good", ROWS)
    assert all(c["same"] for c in S.check_runs([good]))
    bad = write_run(tmp_path, "bad", ROWS, p95=9.999)
    with pytest.raises(SystemExit, match="summary.json과 다르다"):
        S.check_runs([bad])


def test_percentile_is_nearest_rank_like_run_eval():
    vals = [float(x) for x in range(1, 21)]
    assert S.pct(vals, 0.95) == S._p95(vals) == 19.0
    assert S.pct(vals, 0.5) == 10.0
