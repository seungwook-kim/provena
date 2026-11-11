"""실패 유형 표(`evals/agent/failure_types.py`) 시험. 합성 행만 쓰고 모델 호출이 없다."""
from __future__ import annotations

import json

from evals.agent import failure_types as ft


def qa(**kw):
    base = {"run": 1, "id": 1, "kind": "relevant", "expect_refusal": False, "status": "ok", "result": "answer", "answered": True,
            "gold_total": 2, "gold_hit": 2, "cited_on_gold": 2, "cited_off_gold": 0, "refuse_stage": None, "refuse_reason": None}
    base.update(kw)
    return base


def refused(**kw):
    return qa(answered=False, result="refuse", gold_hit=0, cited_on_gold=0, **kw)


def review(item, repeat, kind, path):
    return {"id": item, "repeat": repeat, "kind": kind, "path": path, "error_code": None}


def test_right_rows_are_not_failures():
    assert ft.classify_qa(qa()) is None
    assert ft.classify_qa(qa(expect_refusal=True, answered=False, result="refuse", gold_total=0, gold_hit=0)) is None
    assert ft.classify_review(review(1, 1, "full", "review_table")) is None
    assert ft.classify_review(review(8, 1, "clarify", "review_clarify")) is None


def test_each_wrong_row_gets_one_type():
    assert ft.classify_qa(qa(status="fail")) == ft.ERROR
    assert ft.classify_qa(qa(expect_refusal=True)) == ft.ANSWERED_IRRELEVANT
    assert ft.classify_qa(refused(refuse_stage="out_of_domain", refuse_reason="out_of_domain")) == ft.ROUTING
    assert ft.classify_qa(refused(refuse_stage="ground", refuse_reason="unsupported")) == ft.OVER_REFUSAL
    assert ft.classify_qa(qa(gold_hit=1, cited_off_gold=1)) == ft.GOLD_MISS
    assert ft.classify_qa(qa(gold_hit=1, cited_off_gold=1), ctx=[1, 2]) == ft.SEARCH
    assert ft.classify_qa(qa(gold_hit=1), ctx=[2, 2]) == ft.SELECTION
    assert ft.classify_qa(qa(cited_off_gold=1)) == ft.OFF_GOLD
    assert ft.classify_review(review(5, 1, "partial", "other_route")) == ft.ROUTING
    assert ft.classify_review(review(3, 1, "full", "review_clarify")) == ft.FALSE_CLARIFY
    assert ft.classify_review(review(8, 1, "clarify", "review_table")) == ft.MISSED_CLARIFY


def test_rows_from_older_measurements_without_refuse_fields_still_classify():
    row = refused()
    del row["refuse_stage"], row["refuse_reason"], row["status"]
    assert ft.classify_qa(row) == ft.OVER_REFUSAL


def test_primary_type_is_the_most_common_and_ties_go_to_the_earlier_stage():
    assert ft.primary([ft.OFF_GOLD, ft.SEARCH, ft.SEARCH]) == ft.SEARCH
    assert ft.primary([ft.OFF_GOLD, ft.OVER_REFUSAL]) == ft.OVER_REFUSAL
    assert ft.primary([ft.SELECTION, ft.SEARCH]) == ft.SEARCH


def test_an_item_fails_at_two_wrong_runs_and_type_counts_add_up_to_failed_items():
    rows = [(1, 1, None), (1, 2, None), (1, 3, None),
            (2, 1, ft.SEARCH), (2, 2, ft.OVER_REFUSAL), (2, 3, ft.SEARCH),
            (3, 1, ft.OFF_GOLD), (3, 2, None), (3, 3, None),
            (4, 1, ft.OFF_GOLD), (4, 2, ft.OFF_GOLD), (4, 3, None)]
    res = ft.analyze([{"name": "v2", "rows": rows}, {"name": "review", "rows": [(5, r, ft.ROUTING) for r in (1, 2, 3)]}])
    assert res["n_items"] == 5 and res["n_failed"] == 3 and res["type_sum"] == 3
    assert {t: [(i["set"], i["id"]) for i in v] for t, v in res["by_type"].items()} == {
        ft.ROUTING: [("review", 5)], ft.SEARCH: [("v2", 2)], ft.OFF_GOLD: [("v2", 4)]}
    assert [(i["id"], i["wrong"]) for i in res["below_threshold"]] == [(3, 1)]
    assert ft.analyze([{"name": "v2", "rows": rows}], min_wrong=1)["n_failed"] == 3


def test_context_file_may_key_each_run_and_the_run_key_wins_over_the_item_key(tmp_path):
    v2 = tmp_path / "deploy_latency_x"
    v2.mkdir()
    rows = [qa(id=2, run=1, gold_hit=1), qa(id=2, run=2, gold_hit=1), qa(id=2, run=3, gold_hit=1)]
    (v2 / "citation_gold.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    ctx = {"v2:2:1": [1, 2], "v2:2:2": [2, 2], "v2:2:3": [1, 2], "v2:2": [2, 2]}   # 회차 키가 문항 키보다 먼저
    sets = ft.load_sets([("v2", v2)], [], ctx)
    assert [k for _, _, k in sets[0]["rows"]] == [ft.SEARCH, ft.SELECTION, ft.SEARCH]
    only_item = ft.load_sets([("v2", v2)], [], {"v2:2": [2, 2]})
    assert {k for _, _, k in only_item[0]["rows"]} == {ft.SELECTION}                # 옛 형식은 그대로 읽힌다
    assert {k for _, _, k in ft.load_sets([("v2", v2)], [], {"v2:2:2": [2, 2]})[0]["rows"]} == {ft.GOLD_MISS, ft.SELECTION}   # 키가 없는 회차는 미구분


def test_the_largest_type_keeps_stage_order_on_a_tie():
    rows = [(1, r, ft.OFF_GOLD) for r in (1, 2)] + [(2, r, ft.SEARCH) for r in (1, 2)]
    assert ft.analyze([{"name": "v2", "rows": rows}])["largest"] == ft.SEARCH
    assert ft.analyze([{"name": "v2", "rows": [(1, 1, None)]}])["largest"] is None


def test_cli_reads_result_folders_and_writes_the_table(tmp_path, capsys):
    v2 = tmp_path / "deploy_latency_x"
    v2.mkdir()
    rows = [qa(id=1, run=r) for r in (1, 2, 3)] + [qa(id=2, run=r, gold_hit=1) for r in (1, 2, 3)] + [qa(id=3, run=r, cited_off_gold=1) for r in (1, 2)] + [qa(id=3, run=3)]
    (v2 / "citation_gold.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    rv = tmp_path / "review_deploy_x"
    rv.mkdir()
    (rv / "rows.jsonl").write_text("\n".join(json.dumps(review(5, r, "partial", "other_route")) for r in (1, 2, 3)), encoding="utf-8")
    ctx = tmp_path / "context.json"
    ctx.write_text(json.dumps({"v2:2": [1, 2]}), encoding="utf-8")
    out = tmp_path / "o"
    assert ft.main(["--qa", f"v2={v2}", "--review", f"review={rv}", "--context", str(ctx), "--out", str(out)]) == 0
    assert "실패 문항 3 / 문항 4" in capsys.readouterr().out
    md = (out / "failure_types.md").read_text(encoding="utf-8")
    assert "| 검색 실패 | 1 | v2 2 |" in md and "| 라우팅 오분류 | 1 | review 5 |" in md and "| 합계 | 3 | 실패 문항 수 3와 같음 |" in md
    res = json.loads((out / "failure_types.json").read_text(encoding="utf-8"))
    assert res["type_sum"] == res["n_failed"] == 3
    assert ft.main(["--qa", f"v2={v2}"]) == 0 and "정답 위치 누락" in capsys.readouterr().out
