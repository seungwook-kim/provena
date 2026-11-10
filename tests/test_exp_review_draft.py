"""합동 검토 측정기의 초안 정답·반복·비용 상한·예상 기능 시험 (사전 등록 62.35). 가짜 모델과 가짜 검색기만 쓴다(키·네트워크·비용 없음)."""
from __future__ import annotations

import pytest
from test_exp_review import by_id, item, make_arms

from evals.agent import exp_review_v1 as M

DRAFT = M.EVALS / "dataset_review_v1_gold_draft.jsonl"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


def test_gold_draft_keeps_the_dataset_and_marks_every_item_as_draft():
    base = M.load_review_dataset(M.DATASET)
    draft = M.load_review_dataset(DRAFT)  # 정답 위치 형식이 틀리면 여기서 ValueError
    assert [(d["id"], d["input"], d["kind"], d["as_of"]) for d in draft] == [(b["id"], b["input"], b["kind"], b["as_of"]) for b in base]
    for d in draft:
        assert d["gold_status"] == M.DRAFT_STATUS and d["judges"] == []  # 판정자 칸은 판정자가 채운다
        if d["kind"] == "clarify":
            assert d["gold_issues"] == [] and M.judged_state(d, True) == "n/a"
        else:
            assert d["gold_issues"] and all(g["issue"].strip() for g in d["gold_issues"])
            assert M.judged_state(d) == "pending" and M.judged_state(d, True) == "ready"
    assert M.frozen_state(DRAFT) == "unfrozen"


def test_draft_gold_is_used_only_with_the_flag_and_is_labelled():
    it = item(gold=())
    it.update(gold_status=M.DRAFT_STATUS)
    it["_gold"] = []
    it["gold_issues"] = [{"team": "security", "section": "x > y"}]
    (team, _), _, _ = make_arms()
    row = M.run_arm_item(team, it, "t")
    assert M.compute_review_metrics([row], by_id([it]))["gold_status"] == M.PENDING
    got = M.compute_review_metrics([row], by_id([it]), allow_draft=True)
    assert got["gold_status"].startswith("계산함(초안 정답 기준") and got["gold_items"] == 1


def test_repeats_alternate_arm_order_and_record_the_repeat():
    arms, _, _ = make_arms()
    items = [item(1), item(2)]
    seen = []
    rows = M.run_arms(items, arms, "t", repeats=2, on_row=lambda a, r: seen.append((r["repeat"], r["id"], a.name)))
    assert {k: len(v) for k, v in rows.items()} == {"team": 4, "single": 4}
    assert seen == [(1, 1, "team"), (1, 1, "single"), (1, 2, "single"), (1, 2, "team"),
                    (2, 1, "single"), (2, 1, "team"), (2, 2, "team"), (2, 2, "single")]


def test_max_cost_stops_before_the_run_that_would_cross_it(monkeypatch):
    monkeypatch.setattr(M, "EST_RUN_USD", 0.4)
    monkeypatch.setattr(M.tracking, "finish_item", lambda config: {"cost_usd": 0.3})  # 런마다 0.3달러가 든 것으로 둔다
    arms, _, _ = make_arms()
    with pytest.raises(M.BudgetExceeded):
        M.run_arms([item(1), item(2)], arms, "t", max_cost=1.0)
    assert sum(len(a.rows) for a in arms) == 3  # 누적 0.9 + 예상 0.4 > 1.0 이라 네 번째 런 전에 멈춘다


def test_plan_counts_runs_and_cost_without_calling_anything():
    items = M.load_review_dataset(DRAFT)
    p = M.plan(items, 3, 1.0)
    assert p["items"] == 10 and p["clarify_items"] == 2 and p["runs"] == 60
    assert p["llm_calls_without_translation"] == 3 * ((8 * 5 + 2) + 10)
    assert p["search_calls"] == 3 * (8 * 4 + 10 * 4)
    assert p["est_cost_usd_upper"] == round(60 * M.EST_RUN_USD, 4) and p["fits_max_cost"] is True


def test_plan_cli_is_zero_cost(capsys):
    assert M.main(["plan", "--dataset", str(DRAFT), "--repeats", "3", "--max-cost", "1"]) == 0
    out = capsys.readouterr().out
    assert '"runs": 60' in out and '"ready": 8' in out


def test_anthropic_env_needs_a_key_and_never_prints_it(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        M.use_anthropic_env()
    fake = "sk-ant-" + "x" * 20
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-y")
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_FALLBACK_MODEL", "DEMO_MODE", "LLM_RECORD", "LLM_REASONING", "LLM_PROVIDER_SORT"):
        monkeypatch.setenv(name, "x")  # 원래 값(없음 포함)을 기록해 시험 뒤 되돌린다. 함수가 바꾼 값이 다른 시험으로 새지 않게
        monkeypatch.delenv(name)
    M.use_anthropic_env()
    import os
    assert os.environ["LLM_PROVIDER"] == "anthropic" and os.environ["LLM_MODEL"] == M.ANTHROPIC_MODEL
    assert "OPENROUTER_API_KEY" not in os.environ and "ANTHROPIC_API_KEY" not in os.environ
    assert fake not in capsys.readouterr().out
