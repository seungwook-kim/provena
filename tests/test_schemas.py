"""backend/schemas/ 계약 시험 (SDD 6장). 필드 이름과 집합이 바뀌면 실패한다.

필드를 더하거나 이름을 바꾸는 PR은 3명 승인이 필요하므로, 아래 기대 목록도 같은 PR에서 고친다.
"""
import pytest
from pydantic import ValidationError

from backend.schemas import (
    AgentEvent,
    ApprovalItem,
    ChangedArticle,
    Chunk,
    Decision,
    DecisionRule,
    DecisionTable,
    MaintenanceCandidate,
    RecallNotice,
    SearchQuery,
)

EXPECTED_FIELDS = {
    Chunk: ["chunk_id", "org", "rule_seq", "rule_title", "article", "version_id", "version_date",
            "fetched_at", "kind", "text", "source_url", "text_sha256", "version_date_before", "line_start", "line_end"],
    SearchQuery: ["query", "org", "as_of", "k"],
    AgentEvent: ["type", "thread_id", "data"],
    ApprovalItem: ["approval_id", "kind", "summary", "created_at"],
    Decision: ["approval_id", "approve", "comment", "decided_by"],
    ChangedArticle: ["rule_seq", "article", "old_version_date", "new_version_date", "change_type"],
    RecallNotice: ["answer_id", "user_id", "changed", "conclusion_changed", "explanation"],
    MaintenanceCandidate: ["candidate_id", "upper_rule", "upper_version_id", "rule_seq", "article", "reason"],
    DecisionTable: ["table_id", "rule_seq", "version_id", "cells", "status", "approved_by"],
    DecisionRule: ["category", "band", "band_lo", "band_hi", "approvers", "financial_approvers",
                   "cooperating_depts", "range_note"],
}


@pytest.mark.parametrize("model", list(EXPECTED_FIELDS))
def test_field_names_match_sdd(model):
    assert list(model.model_fields) == EXPECTED_FIELDS[model]


def _chunk(**over):
    base = dict(chunk_id="0123456789abcdef", org="security", rule_seq=4_294_967_295, rule_title="Incident Management",
                article="Incident Management > Severities", version_id="129243bc", version_date="2026-10-27",
                fetched_at="2026-10-30", kind="article", text="본문", source_url="https://handbook.gitlab.com/x")
    base.update(over)
    return base


def test_chunk_accepts_rule_seq_above_int32():
    # 페이지 id는 8자리 16진수(최대 4294967295)라 부호 있는 32비트를 넘는다. DB 칸은 BIGINT여야 한다.
    c = Chunk(**_chunk())
    assert c.rule_seq == 4_294_967_295 > 2**31 - 1


def test_chunk_article_may_be_none_and_kind_is_restricted():
    assert Chunk(**_chunk(article=None)).article is None
    for kind in ("article", "annex", "row", "buchik", "pre"):
        assert Chunk(**_chunk(kind=kind)).kind == kind
    with pytest.raises(ValidationError):
        Chunk(**_chunk(kind="table"))


def test_chunk_requires_every_field():
    data = _chunk()
    del data["source_url"]
    with pytest.raises(ValidationError):
        Chunk(**data)


def test_search_query_defaults():
    q = SearchQuery(query="외부 SaaS 승인")
    assert (q.org, q.as_of, q.k) == (None, None, 8)


def test_agent_event_type_is_restricted():
    for t in ("token", "citation", "approval_request", "error", "done"):
        assert AgentEvent(type=t, thread_id="t1", data={}).type == t
    with pytest.raises(ValidationError):
        AgentEvent(type="start", thread_id="t1", data={})


def test_approval_kind_and_decision_default_comment():
    assert ApprovalItem(approval_id="a", kind="issue_table", summary="s", created_at="2026-10-30").kind == "issue_table"
    with pytest.raises(ValidationError):
        ApprovalItem(approval_id="a", kind="other", summary="s", created_at="2026-10-30")
    assert Decision(approval_id="a", approve=True).comment == ""


def test_recall_notice_nests_changed_article():
    n = RecallNotice(answer_id="a1", user_id="u1", conclusion_changed=True, explanation="바뀜",
                     changed=dict(rule_seq=4_294_967_295, article="A > B",
                                  old_version_date="2026-01-01", new_version_date="2026-10-27",
                                  change_type="modified"))
    assert isinstance(n.changed, ChangedArticle)


def test_decision_table_status_is_restricted():
    t = DecisionTable(table_id="t", rule_seq=1, version_id="v", cells={"r": 1}, status="draft")
    assert t.approved_by is None
    for s in ("approved", "rejected"):
        assert DecisionTable(table_id="t", rule_seq=1, version_id="v", cells=[], status=s).status == s
    with pytest.raises(ValidationError):
        DecisionTable(table_id="t", rule_seq=1, version_id="v", cells={}, status="pending")


def test_changed_article_type_is_restricted():
    with pytest.raises(ValidationError):
        ChangedArticle(rule_seq=1, article="A", old_version_date="2026-01-01", new_version_date="2026-10-27",
                       change_type="renamed")


def test_decision_rule_keeps_financial_approvers_apart():
    r = DecisionRule(category="Hardware", band="$0 - $25K", band_lo=0, band_hi=25_000, approvers=["Manager"],
                     financial_approvers=["Director, Finance"])
    assert r.cooperating_depts == []
    assert "Director, Finance" not in r.approvers
    assert DecisionRule(category="Hardware", band="$1M+", band_lo=1_000_000, approvers=["CFO"]).band_hi is None


def test_decision_rule_range_note_defaults_to_none():
    # I-004: 해석으로 끝을 채운 칸만 설명을 가진다
    assert DecisionRule(category="Hardware", band="$0 - $25K", approvers=["Manager"]).range_note is None


def test_chunk_version_date_before_defaults_to_exact_date():
    assert Chunk(**_chunk()).version_date_before is False
    assert Chunk(**_chunk(version_date="2023-12-01", version_date_before=True)).version_date_before is True


def test_approval_created_at_is_datetime_and_serializes_iso():
    from datetime import datetime

    item = ApprovalItem(approval_id="a", kind="decision_table", summary="s", created_at="2026-10-30T22:43:00")
    assert isinstance(item.created_at, datetime)
    assert item.model_dump(mode="json")["created_at"] == "2026-10-30T22:43:00"
    with pytest.raises(ValidationError):
        ApprovalItem(approval_id="a", kind="decision_table", summary="s", created_at="어제")
