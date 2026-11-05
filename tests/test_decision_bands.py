"""금액 구간 해석과 정확한 금액 표기 시험. `data/parsed/authz_cells.jsonl`(2023 권한표 칸 363개)을 그대로 읽는다.

경계 규칙은 권한표 원문에 적혀 있지 않다. 여기서 고정하는 값은 사용자가 확정한 이 프로젝트의 해석이다 (`backend/graph/decision/rules.py` 모듈 설명).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from decision_fixtures import FakeLLM, draft_json
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.graph.decision import rules as R
from backend.graph.decision.convert import ERR_DRAFT, build_convert_graph, pending_interrupt
from backend.graph.decision.execute import DecisionExecutor, decision_citation, format_decision_answer
from backend.graph.decision.repo import InMemoryDecisionRepo
from backend.schemas import DecisionTable

CELLS_FILE = Path(__file__).resolve().parents[1] / "data" / "parsed" / "authz_cells.jsonl"
ABBREVIATED = re.compile(r"\$\s*\d[\d,.]*\s*[kKmM]\b")

EXPENSE, PAYMENT, LEGAL = "Approving expense", "Approving Payment", "Legal Contracts"
BAD_DEBT, NON_BILLABLE, TRANSFER = "Bad debt write off", "Non Billable Expenses", "Transfer of funds among GitLab entities"
HIRING, BENEFIT = "Compensation/Hiring - non-executive", "Benefit changes"
PAO = "PAO or VP Finance"


@pytest.fixture(scope="module")
def cells() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in CELLS_FILE.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        out.setdefault(c["category"], []).append(c)
    return out


@pytest.fixture(scope="module")
def tables(cells) -> dict[str, list[dict]]:
    return {k: R.rules_from_cells(v) for k, v in cells.items()}


def test_cell_file_is_the_expected_2023_table(cells):
    assert sum(map(len, cells.values())) == 363 and len(cells) == 8


# --- 경계 금액의 선택 구간 -------------------------------------------------------------------

@pytest.mark.parametrize("category,amount,band,label,approvers,cooperating", [
    (EXPENSE, 0.01, ">$0K to $25K", "$0 초과 $25,000 이하", ["Manager", PAO], []),
    (EXPENSE, 25_000, ">$0K to $25K", "$0 초과 $25,000 이하", ["Manager", PAO], []),
    (EXPENSE, 25_000.01, ">$25K up to $50K", "$25,000 초과 $50,000 이하", ["Director", PAO], []),
    (EXPENSE, 30_000, ">$25K up to $50K", "$25,000 초과 $50,000 이하", ["Director", PAO], []),
    (EXPENSE, 50_000, ">$25K up to $50K", "$25,000 초과 $50,000 이하", ["Director", PAO], []),
    (EXPENSE, 50_000.01, ">$50K up to $250K", "$50,000 초과 $250,000 이하", ["Sr Director", PAO], []),
    (EXPENSE, 250_000, ">$50K up to $250K", "$50,000 초과 $250,000 이하", ["Sr Director", PAO], []),
    (EXPENSE, 250_000.01, ">$250K up to $500K", "$250,000 초과 $500,000 이하", ["VP", PAO], []),
    (EXPENSE, 499_999.99, ">$250K up to $500K", "$250,000 초과 $500,000 이하", ["VP", PAO], []),
    (EXPENSE, 500_000.01, "$500K to $1M", "$500,000 이상 $1,000,000 이하", ["Exec Group", "CFO"], []),
    (EXPENSE, 999_999.99, "$500K to $1M", "$500,000 이상 $1,000,000 이하", ["Exec Group", "CFO"], []),
    (EXPENSE, 1_000_000.01, "$1M up to $5M", "$1,000,000 이상 $5,000,000 이하", ["CEO"], ["CFO"]),
    (EXPENSE, 5_000_000, "$1M up to $5M", "$1,000,000 이상 $5,000,000 이하", ["CEO"], ["CFO"]),
    (EXPENSE, 5_000_000.01, ">$5M", "$5,000,000 초과", ["CEO", "Board"], ["CFO"]),
    (PAYMENT, 500_000, ">$0k up to $500k", "$0 초과 $500,000 이하", [], [PAO]),
    (PAYMENT, 500_000.01, ">$500K and above", "$500,000 초과", [], ["CFO"]),
    (NON_BILLABLE, 0, "Up to $5K", "$5,000 이하", ["Manager", PAO], []),
    (NON_BILLABLE, 5_000, "Up to $5K", "$5,000 이하", ["Manager", PAO], []),
    (NON_BILLABLE, 5_000.01, ">$5K", "$5,000 초과 $50,000 이하", ["Exec Group", PAO], []),
    (NON_BILLABLE, 50_000, ">$5K", "$5,000 초과 $50,000 이하", ["Exec Group", PAO], []),
    (NON_BILLABLE, 50_000.01, ">$50K", "$50,000 초과", ["Exec Group", "CFO"], []),
    (TRANSFER, 500_000, "Up to $500K", "$500,000 이하", [PAO], []),
    (TRANSFER, 500_000.01, "Over $500K", "$500,000 초과", ["CEO", "CFO"], []),
    (BAD_DEBT, 9_999.99, "Up to $10K", "$10,000 이하", ["Exec Group", PAO], []),
    (BAD_DEBT, 10_000.01, "$10K to $100K", "$10,000 이상 $100,000 이하", ["CEO", PAO], []),
    (BAD_DEBT, 100_000.01, "$100K plus", "$100,000 이상", ["CEO", "CFO"], ["Board"]),
])
def test_boundary_amounts_select_the_band(tables, category, amount, band, label, approvers, cooperating):
    out = R.run_rules(tables[category], amount)
    assert out["source"]["band"] == band                      # 원문 표기는 source에 그대로 남는다
    assert out["source"]["article"] == f"{category} / {band}"
    assert out["band_label"] == label
    assert out["approvers"] == approvers and out["cooperating"] == cooperating


@pytest.mark.parametrize("category,amount", [(EXPENSE, 0), (PAYMENT, 0)])
def test_zero_is_outside_bands_that_start_with_greater_than(tables, category, amount):
    with pytest.raises(R.NotFound):
        R.run_rules(tables[category], amount)


# --- 겹침: 네 금액 전부 ----------------------------------------------------------------------

OVERLAPS = {
    (EXPENSE, 500_000): "$250,000 초과 $500,000 이하 / $500,000 이상 $1,000,000 이하",
    (EXPENSE, 1_000_000): "$500,000 이상 $1,000,000 이하 / $1,000,000 이상 $5,000,000 이하",
    (BAD_DEBT, 10_000): "$10,000 이하 / $10,000 이상 $100,000 이하",
    (BAD_DEBT, 100_000): "$10,000 이상 $100,000 이하 / $100,000 이상",
}


@pytest.mark.parametrize("key,bands", OVERLAPS.items(), ids=[f"{c}-{a}" for c, a in OVERLAPS])
def test_each_overlap_is_refused_with_exact_amounts(tables, key, bands):
    category, amount = key
    with pytest.raises(R.AmbiguousBand) as e:
        R.run_rules(tables[category], amount)
    assert e.value.status == 422
    assert e.value.message == f"금액 {R.usd(amount)}은 두 구간에 함께 들어 구간을 정할 수 없다: {bands}"
    assert not ABBREVIATED.search(e.value.message)


def test_these_four_are_the_only_overlaps_in_the_table(tables):
    found = set()
    for category, rules in tables.items():
        if not all(R.band_bounds(r).has_amount for r in rules):
            continue
        ends = {v for r in rules for v in (r["band_lo"], r["band_hi"]) if v is not None}
        for amount in ends:
            try:
                R.run_rules(rules, amount)
            except R.AmbiguousBand:
                found.add((category, amount))
            except R.NotFound:
                pass
    assert found == set(OVERLAPS)


def test_band_name_cannot_settle_an_overlap_or_reach_a_lower_band(tables):
    with pytest.raises(R.AmbiguousBand):
        R.run_rules(tables[EXPENSE], 500_000, band=">$250K up to $500K")
    with pytest.raises(R.NotFound):                               # 금액으로 고른 구간과 다른 이름은 받지 않는다
        R.run_rules(tables[EXPENSE], 600_000, band=">$25K up to $50K")
    with pytest.raises(R.NotFound):                               # 위 끝이 빈 구간도 다음 구간의 금액을 받지 않는다
        R.run_rules(tables[NON_BILLABLE], 60_000, band=">$5K")
    assert R.run_rules(tables[EXPENSE], 30_000, band=">$25K up to $50K")["approvers"] == ["Director", PAO]


# --- 표기 ------------------------------------------------------------------------------------

def test_no_label_in_the_whole_table_has_an_abbreviated_amount(tables):
    labels = [R.band_label(r, rules) for rules in tables.values() for r in rules]
    assert len(labels) == 33 and not [x for x in labels if ABBREVIATED.search(x)]


@pytest.mark.parametrize("band,label", [
    ("$100K plus", "$100,000 이상"),
    ("Up to $5K", "$5,000 이하"),
    (">$500K and above", "$500,000 초과"),
    ("Over $500K", "$500,000 초과"),
    (">$0k up to $500k", "$0 초과 $500,000 이하"),
    ("Non standard terms > $500k annual revenue", "Non standard terms > $500,000 annual revenue"),
    ("Standard Terms", "Standard Terms"),
    ("Options", "Options"),
    ("Benefit changes", "Benefit changes"),
])
def test_label_of_each_notation(tables, band, label):
    found = [(r, rules) for rules in tables.values() for r in rules if r["band"] == band]
    assert len(found) == 1
    assert R.band_label(*found[0]) == label


def test_parser_ends_match_the_original_notation(tables):
    ends = {r["band"]: (r["band_lo"], r["band_hi"]) for rules in tables.values() for r in rules}
    assert ends["$100K plus"] == (100_000, None)
    assert ends["Up to $5K"] == (0, 5_000)
    assert ends[">$500K and above"] == (500_000, None)
    assert R.band_bounds({"band": ">$500K and above", "band_lo": 500_000, "band_hi": None}).lo_inclusive is False
    assert R.band_bounds({"band": "$100K plus", "band_lo": 100_000, "band_hi": None}).lo_inclusive is True


def test_open_ended_band_notes_the_interpretation(tables):
    out = R.run_rules(tables[NON_BILLABLE], 30_000)
    assert out["range_note"] == "원문 구간의 위 끝이 비어 있어 다음 구간의 시작($50,000)을 끝으로 봤다."
    assert R.run_rules(tables[NON_BILLABLE], 60_000)["range_note"] is None
    assert R.run_rules(tables[EXPENSE], 30_000)["range_note"] is None


# --- 금액 구간이 없는 업무 --------------------------------------------------------------------

@pytest.mark.parametrize("amount", [1_000, 500_000, 600_000])
def test_legal_contracts_with_amount_only_asks_for_band(tables, amount):
    with pytest.raises(R.BadRequest) as e:             # 600,000을 `Non standard terms`로 추측하지 않는다
        R.run_rules(tables[LEGAL], amount)
    assert e.value.status == 400 and "Standard Terms" in e.value.message
    assert "$500,000 annual revenue" in e.value.message and not ABBREVIATED.search(e.value.message)


def test_hiring_needs_band_and_single_band_task_does_not(tables):
    with pytest.raises(R.BadRequest):
        R.run_rules(tables[HIRING], 1_000)
    assert R.run_rules(tables[HIRING], None, band="Options")["approvers"] == ["Board"]
    assert R.run_rules(tables[BENEFIT], None)["band_label"] == "Benefit changes"
    with pytest.raises(R.BadRequest):
        R.run_rules(tables[BENEFIT], -1)


def test_legal_contracts_by_band(tables):
    rules = tables[LEGAL]
    out = R.run_rules(rules, None, band="Standard Terms")
    assert out["band_label"] == "Standard Terms" and out["financial_approvers"] == ["CLO"]
    assert out["cooperating"] == ["Exec Group", PAO]               # Signs는 승인이 아니라 협조다
    with pytest.raises(R.BadRequest):
        R.run_rules(rules, -1, band="Standard Terms")              # 금액을 주면 어느 업무든 형식을 본다
    with pytest.raises(R.NotFound):
        R.run_rules(rules, None, band="없는 구간")
    raw = "Non standard terms > $500k annual revenue"
    with pytest.raises(R.BadRequest):
        R.run_rules(rules, None, band=raw)
    with pytest.raises(R.NotFound):
        R.run_rules(rules, 500_000, band=raw)
    good = R.run_rules(rules, 500_000.01, band=raw)
    assert good["band_label"] == "Non standard terms > $500,000 annual revenue" and good["source"]["band"] == raw
    assert R.run_rules(rules, 600_000, band=good["band_label"])["source"]["band"] == raw   # 보여 준 표기로도 찾는다


@pytest.mark.parametrize("amount", [10 ** 400, float("inf"), "3만", True])
def test_amounts_that_are_not_finite_numbers(tables, amount):
    with pytest.raises(R.BadRequest):
        R.run_rules(tables[EXPENSE], amount)


# --- 실행 결과와 답 문장 ----------------------------------------------------------------------

def _approved(cells_of, version="0a3de8337541") -> InMemoryDecisionRepo:
    repo = InMemoryDecisionRepo()
    rec = repo.queue_draft("t", DecisionTable(table_id="dt", rule_seq=7, version_id=version, cells=R.rules_from_cells(cells_of), status="draft"), "s")
    repo.decide(rec.approval_id, True, "admin-1")
    return repo


def test_executor_result_keeps_original_only_in_source(cells):
    out = DecisionExecutor(_approved(cells[EXPENSE])).run(EXPENSE, 750_000)
    assert out["band_label"] == "$500,000 이상 $1,000,000 이하"
    assert out["source"]["band"] == "$500K to $1M" and out["source"]["rule_seq"] == 7
    assert out["source"]["source_url"].endswith("sites/handbook/source/handbook/finance/authorization-matrix/index.html.md")
    assert not ABBREVIATED.search(json.dumps({k: v for k, v in out.items() if k != "source"}, ensure_ascii=False))
    answer = format_decision_answer(out)
    assert "$500,000 이상 $1,000,000 이하" in answer and not ABBREVIATED.search(answer)


def test_chat_body_has_exact_amounts_and_the_original_is_only_in_the_citation(cells):
    out = DecisionExecutor(_approved(cells[EXPENSE])).run(EXPENSE, 750_000)
    answer, cite = format_decision_answer(out), decision_citation(out)
    assert "$500,000 이상 $1,000,000 이하" in answer and "$500K" not in answer and not ABBREVIATED.search(answer)
    assert cite["article"] == f"{EXPENSE} / $500K to $1M" and cite["version_id"] == out["version_id"]
    assert cite["source_url"] == out["source"]["source_url"] and cite["version_date"] == "2023-05-11"


@pytest.mark.parametrize("category", [EXPENSE, BAD_DEBT, NON_BILLABLE, PAYMENT])
def test_chat_body_never_shows_an_abbreviated_amount_in_any_band(cells, tables, category):
    executor = DecisionExecutor(_approved(cells[category]))
    for rule in tables[category]:
        band = R.band_bounds(rule)
        if band.lo is None:
            continue
        amount = band.lo + 0.5
        try:
            out = executor.run(category, amount)
        except R.DecisionError:
            continue
        assert not ABBREVIATED.search(format_decision_answer(out))


def test_refusal_messages_for_the_chat_do_not_repeat_typed_notation(tables):
    with pytest.raises(R.NotFound) as e:
        R.run_rules(tables[EXPENSE], 30_000, band="$1.5M to $2M")
    assert not ABBREVIATED.search(e.value.message)


def test_citation_of_an_unknown_version_has_no_invented_fields(cells):
    cite = decision_citation(DecisionExecutor(_approved(cells[EXPENSE], "other")).run(EXPENSE, 750_000))
    assert cite["source_url"] is None and cite["rule_title"] is None and cite["version_date"] is None


def test_unknown_version_has_no_invented_source_url(cells):
    assert DecisionExecutor(_approved(cells[EXPENSE], "other")).run(EXPENSE, 750_000)["source"]["source_url"] is None


def test_open_ended_answer_carries_the_note(cells):
    answer = format_decision_answer(DecisionExecutor(_approved(cells[NON_BILLABLE])).run(NON_BILLABLE, 30_000))
    assert "주의: 원문 구간의 위 끝이 비어 있어" in answer and not ABBREVIATED.search(answer)


# --- 셀 불일치 초안의 승인 --------------------------------------------------------------------

def _stopped(cells_of, rules):
    repo = InMemoryDecisionRepo()
    graph = build_convert_graph(FakeLLM(draft_json(rules)), repo, InMemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    graph.invoke({"category": cells_of[0]["category"], "rule_seq": 1, "version_id": "v", "source_cells": cells_of, "requested_by": "a"}, cfg)
    return graph, repo, cfg, pending_interrupt(graph, "t")


def _wrong_draft(cells_of):
    rules = R.rules_from_cells(cells_of)
    rules[0]["approvers"] = ["CEO"]
    return rules


def _resume(graph, cfg, req, approve=True, comment=""):
    graph.invoke(Command(resume={"approval_id": req["approval_id"], "approve": approve, "comment": comment, "decided_by": "admin-1"}), cfg)


@pytest.mark.parametrize("comment", ["", "   ", "\n\t"])
def test_mismatch_approval_without_comment_changes_nothing(cells, comment):
    graph, repo, cfg, req = _stopped(cells[EXPENSE], _wrong_draft(cells[EXPENSE]))
    assert req["comparison"]["mismatch_count"] > 0
    _resume(graph, cfg, req, True, comment)
    again = pending_interrupt(graph, "t")
    assert again["rejected_resume"] == "comment_required" and again["approval_id"] == req["approval_id"]
    assert repo.get_table(req["table_id"]).status == "draft"
    assert repo.get_approval(req["approval_id"]).status == "pending"


def test_mismatch_approval_with_comment_is_kept_and_approved(cells):
    graph, repo, cfg, req = _stopped(cells[EXPENSE], _wrong_draft(cells[EXPENSE]))
    _resume(graph, cfg, req, True, "")
    _resume(graph, cfg, req, True, "첫 구간은 원문이 틀렸음을 재무팀과 확인함")
    assert repo.get_table(req["table_id"]).status == "approved"
    assert repo.get_approval(req["approval_id"]).comment == "첫 구간은 원문이 틀렸음을 재무팀과 확인함"


def test_mismatch_rejection_needs_no_comment(cells):
    graph, repo, cfg, req = _stopped(cells[EXPENSE], _wrong_draft(cells[EXPENSE]))
    _resume(graph, cfg, req, False, "")
    assert repo.get_table(req["table_id"]).status == "rejected"


def test_invented_empty_band_also_needs_a_comment(cells):
    rules = R.rules_from_cells(cells[EXPENSE])
    rules.append({**rules[0], "band": "만든 구간", "approvers": [], "financial_approvers": [], "cooperating_depts": []})
    graph, repo, cfg, req = _stopped(cells[EXPENSE], rules)
    assert req["comparison"]["mismatch_count"] == 0 and req["comparison"]["extra_bands"] == ["만든 구간"]
    _resume(graph, cfg, req, True, "")
    assert pending_interrupt(graph, "t")["rejected_resume"] == "comment_required"


def test_faithful_draft_needs_no_comment(cells):
    graph, repo, cfg, req = _stopped(cells[EXPENSE], R.rules_from_cells(cells[EXPENSE]))
    _resume(graph, cfg, req, True, "")
    assert repo.get_table(req["table_id"]).status == "approved"


def test_comparison_rows_show_exact_labels_next_to_original(cells):
    cmp_ = R.compare_cells(cells[NON_BILLABLE], R.rules_from_cells(cells[NON_BILLABLE]))
    row = next(r for r in cmp_["rows"] if r["band"] == ">$5K")
    assert row["band_label"] == "$5,000 초과 $50,000 이하"


def test_draft_with_duplicate_band_is_unreadable(cells):
    rules = R.rules_from_cells(cells[EXPENSE])
    wrong = {**rules[0], "approvers": ["CEO"]}
    graph = build_convert_graph(FakeLLM(draft_json([wrong, *rules])), InMemoryDecisionRepo(), InMemorySaver())
    res = graph.invoke({"category": EXPENSE, "rule_seq": 1, "version_id": "v", "source_cells": cells[EXPENSE], "requested_by": "a"},
                       {"configurable": {"thread_id": "t"}})
    assert res["outcome"] == "failed" and res["error"] == ERR_DRAFT
