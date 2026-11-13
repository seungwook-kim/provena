"""합동 검토 측정기의 초안·확정 정답, 반복, 비용 상한, 예상 기능 시험 (사전 등록 62.35). 가짜 모델과 가짜 검색기만 쓴다(키·네트워크·비용 없음)."""
from __future__ import annotations

import hashlib

import pytest
from test_exp_review import by_id, item, make_arms

from evals.agent import exp_review_v1 as M

DRAFT = M.EVALS / "dataset_review_v1_gold_draft.jsonl"  # 00044·00049가 쓴 초안(그대로 둔다)
GOLD = M.EVALS / "dataset_review_v1_gold.jsonl"  # 조원 2명이 확인한 확정 정답(2026-11-13, 결정기록 0117)
GOLD_SHA256_LF = "9b235976eff5a29b4b89bba9f6eb7ab857e2e6e795be8bf553df885be8ab6b7e"  # LF 바이트 기준(.gitattributes eol=lf)
DRAFT_SHA256 = "d0d1537f27671e6c216713fbf64d65a871d8d0f326fe8b8099a2b1b6e7875620"  # 00044·00049가 읽은 초안 바이트(작업 폴더 CRLF 기준)
# 확인 결과에서 쟁점 문장을 고친 7개(문항 id, 쟁점 번호 1부터)
REVISED = {(1, 6), (2, 2), (2, 7), (3, 6), (4, 7), (5, 2), (10, 1)}


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


def test_confirmed_gold_file_is_the_draft_with_exactly_seven_revised_issues():
    draft = {d["id"]: d for d in M.load_review_dataset(DRAFT)}
    gold = M.load_review_dataset(GOLD)
    assert [g["id"] for g in gold] == list(draft) and len(gold) == 10
    diffs = set()
    for g in gold:
        d = draft[g["id"]]
        assert g["gold_status"] == M.CONFIRMED_STATUS != M.DRAFT_STATUS
        assert {k: v for k, v in g.items() if k not in ("gold_status", "gold_issues")} == {k: v for k, v in d.items() if k not in ("gold_status", "gold_issues")}
        assert len(g["gold_issues"]) == len(d["gold_issues"])
        for n, (a, b) in enumerate(zip(g["gold_issues"], d["gold_issues"]), 1):
            assert {k: v for k, v in a.items() if k != "issue"} == {k: v for k, v in b.items() if k != "issue"}  # 팀, 근거 섹션, 판 날짜는 그대로
            if a["issue"] != b["issue"]:
                diffs.add((g["id"], n))
    assert diffs == REVISED
    assert sum(len(g["gold_issues"]) for g in gold) == 37 and [g["id"] for g in gold if not g["gold_issues"]] == [8, 9]


def test_confirmed_gold_is_used_without_the_flag_and_is_labelled():
    for g in M.load_review_dataset(GOLD):
        assert M.judged_state(g) == M.judged_state(g, True) == ("n/a" if g["kind"] == "clarify" else "ready")  # 스위치 없이 계산 대상
    it = item(gold=())
    it.update(gold_status=M.CONFIRMED_STATUS)
    it["_gold"] = []
    it["gold_issues"] = [{"team": "security", "section": "x > y"}]
    (team, _), _, _ = make_arms()
    row = M.run_arm_item(team, it, "t")
    got = M.compute_review_metrics([row], by_id([it]))
    assert got["gold_status"] == f"계산함(확정 정답 기준: {M.CONFIRMED_STATUS})" and got["gold_items"] == 1


def test_confirmed_gold_sha256_is_pinned_and_the_draft_is_untouched():
    lf = GOLD.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(lf).hexdigest() == GOLD_SHA256_LF
    assert hashlib.sha256(DRAFT.read_bytes()).hexdigest() == DRAFT_SHA256  # 00044·00049 재현용 원본이 바뀌지 않았다
    assert M.frozen_state(GOLD) == "unfrozen"


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
    for path in (GOLD, DRAFT):
        assert M.main(["plan", "--dataset", str(path), "--repeats", "3", "--max-cost", "1"]) == 0
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
