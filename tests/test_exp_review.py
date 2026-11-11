"""합동 검토 측정기 시험 (`evals/agent/exp_review_v1.py`). 가짜 모델·가짜 검색기·메모리 저장소만 쓰고 실제 측정은 하지 않는다(키·네트워크·DB 없음)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from qgraph_fakes import j
from team_review_fakes import (
    CORPUS,
    FIN,
    INFRA,
    ITOPS,
    SEC,
    Retriever,
    chunk_ids,
    review_llm,
)

from backend.graph.departments import teams as T
from evals.agent import exp_review_v1 as M
from evals.retrieval.gold import GoldRef, norm, page_seq

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-11-05"
ORDER = ("security", "infra", "itops", "finance")
CHUNK_OF = {"security": SEC, "infra": INFRA, "itops": ITOPS, "finance": FIN}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("USE_SKILLS", raising=False)
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


# ---------- 도우미 ----------

def item(i=1, kind="full", judges=(), gold=(), no_gold=False, text="새 외부 SaaS 모니터링 도구를 연 4만 달러에 도입하려 한다.") -> dict:
    """gold: [(team, chunk, version_date | None)]. 정답 위치는 가짜 청크의 rule_seq와 제목 경로로 만든다."""
    d = {"id": i, "input": text, "kind": kind, "as_of": AS_OF, "corpus_version": "129243bc", "judges": list(judges), "gold_issues": [], "why": "시험"}
    d["_gold"] = [(t, GoldRef(rule_seq=c.rule_seq, article=tuple(norm(c.article)), label=f"{c.rule_title} > {c.article}"), vd) for t, c, vd in gold]
    d["gold_issues"] = [{"team": t, "section": f"x > {c.article}"} for t, c, vd in gold]
    if no_gold:
        d["no_gold_issues"] = True
    return d


def single_issues(user: str, teams=ORDER, text="합성 쟁점") -> str:
    """자료 머리말의 첫 chunk_id를 팀마다 근거로 쓴다(single 갈래의 가짜 모델 응답)."""
    out = []
    for tid in teams:
        m = re.search(rf"team={tid}\)\n.*?chunk_id=([0-9a-f]{{16}})", user, re.S)
        if m:
            out.append({"team": tid, "topic": f"topic-{tid}", "issue": f"{tid} {text}", "chunk_id": m.group(1), "stance": "condition", "confidence": "medium"})
    return j(missing=[], issues=out)


def make_arms(llm=None, retriever=None, single_handler=None):
    llm = llm or review_llm(single=single_handler or single_issues)
    retriever = retriever or Retriever()
    return [M.make_arm(n, retriever, llm) for n in M.ARMS], llm, retriever


def by_id(items):
    return {str(i["id"]): i for i in items}


def run_one(arm, it):
    return M.run_arm_item(arm, it, "t")


# ---------- 평가셋 ----------

def test_dataset_file_has_ten_drafts_with_empty_answers():
    items = M.load_review_dataset(M.DATASET)
    assert len(items) == 10 and len({i["id"] for i in items}) == 10
    kinds = [i["kind"] for i in items]
    assert {k: kinds.count(k) for k in M.KINDS} == {"full": 4, "partial": 3, "clarify": 2, "low_issue": 1}
    for it in items:
        assert it["corpus_version"] == "129243bc" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", it["as_of"]) and it["why"].strip() and it["input"].strip()
        assert not it["gold_issues"] or it["judges"]  # 판정자 없이 정답이 채워지면 안 된다
    for it in items:  # 판정 전이면 정답 지표 대상 문항은 pending
        if not it["judges"]:
            assert M.judged_state(it) == ("n/a" if it["kind"] == "clarify" else "pending")


def test_dataset_does_not_reuse_existing_questions_and_is_not_frozen():
    mine = [i["input"] for i in M.load_review_dataset(M.DATASET)]
    old = [json.loads(x)["input"] for f in ("dataset_v1.jsonl", "dataset_v2.jsonl") for x in (ROOT / "evals" / f).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert not set(mine) & set(old)
    assert M.frozen_state(M.DATASET) == "unfrozen"  # 동결은 판정 뒤다


def write_dataset(tmp_path, rows):
    p = tmp_path / "d.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return p


def raw(**over):
    d = {"id": 1, "input": "x", "kind": "full", "as_of": AS_OF, "corpus_version": "129243bc", "judges": [], "gold_issues": [], "why": "w"}
    d.update(over)
    return d


def test_loader_rejects_bad_rows(tmp_path):
    for bad in (raw(kind="other"), raw(gold_issues=[{"team": "hr", "section": "a.md > b"}]), raw(gold_issues=[{"team": "security", "section": "섹션 이름만"}]),
                raw(gold_issues=[{"team": "security", "section": "a.md > b", "version_date": "2026/10/01"}])):
        with pytest.raises(ValueError):
            M.load_review_dataset(write_dataset(tmp_path, [bad]))
    with pytest.raises(ValueError):
        M.load_review_dataset(write_dataset(tmp_path, [raw(), raw()]))  # id 중복
    r = raw(judges=["a"], gold_issues=[{"team": "security", "section": "security/foo.md > Bar > Baz", "version_date": "2026-04-24"}])
    (it,) = M.load_review_dataset(write_dataset(tmp_path, [r]))
    team, ref, vd = it["_gold"][0]
    assert team == "security" and vd == "2026-04-24" and ref.rule_seq == page_seq("security/foo.md")


# ---------- team 갈래: 실제 그래프를 interrupt까지 ----------

def test_team_arm_runs_real_graph_to_the_approval_interrupt_and_saves_nothing():
    (team, single), llm, retriever = make_arms()
    row = run_one(team, item())
    assert row["status"] == "pending_approval" and row["interrupt_kind"] == "issue_table" and row["error"] is None
    assert [r["team"] for r in row["issue_rows"]] == list(ORDER)
    assert row["saved_before_approval"] == 0 and team.store.tables == {} and team.store.rejections == {}
    assert row["llm_calls"] == 5 and [c["org"] for c in row["retrieval_calls"]].count("finance") == 1  # Supervisor 1 + 팀 4, 팀마다 검색 1번
    assert {"id", "kind", "arm", "latency_s", "cost_usd", "input_tokens", "output_tokens", "team_status"} <= row.keys()


def test_pre_approval_save_is_detected(monkeypatch):
    (team, _), _, _ = make_arms()
    orig = team.graph.invoke

    def buggy(inp, config=None, **k):  # 승인 전에 저장하는 잘못된 그래프를 흉내 낸다
        out = orig(inp, config, **k)
        team.store.save(approval_id="a1", thread_id="t", user_id="u", request="r", as_of=None, rows=[], unreviewed=[], approved_by=None)
        return out

    monkeypatch.setattr(team.graph, "invoke", buggy)
    row = run_one(team, item())
    assert row["saved_before_approval"] == 1
    assert M.compute_review_metrics([row], by_id([item()]))["pre_approval_saved"] == 1


def test_team_arm_is_not_resumed_even_with_a_saved_earlier_table():
    (team, _), _, _ = make_arms()
    rows = [run_one(team, item(1)), run_one(team, item(2))]
    assert [r["saved_before_approval"] for r in rows] == [0, 0]  # 문항마다 새로 센다
    assert M.compute_review_metrics(rows, by_id([item(1), item(2)]))["pre_approval_saved"] == 0


def test_team_arm_clarify_missing_value_skips_teams():
    llm = review_llm(supervisor=j(missing=["도입 금액"], tasks={}))
    (team, _), _, retriever = make_arms(llm=llm)
    row = run_one(team, item(kind="clarify", text="새 SaaS를 도입하려 한다."))
    assert row["status"] == "clarify" and row["issue_rows"] == [] and "도입 금액" in row["clarify_question"]
    assert retriever.calls == [] and row["llm_calls"] == 1 and row["saved_before_approval"] == 0


def test_team_arm_failed_team_stops_at_failure_gate_not_as_error():
    (team, _), _, _ = make_arms(retriever=Retriever(fail_orgs=("finance",)))
    row = run_one(team, item())
    assert row["status"] == M.TEAM_FAILED and row["interrupt_kind"] == M.TEAM_FAILED and row["error"] is None
    assert [r["team"] for r in row["issue_rows"]] == ["security", "infra", "itops"]
    assert [u["team"] for u in row["unreviewed"]] == ["finance"] and row["saved_before_approval"] == 0


def test_team_arm_error_is_recorded_and_the_run_goes_on():
    def boom(_user):
        raise RuntimeError("모델 오류(시험)")

    (team, _), _, _ = make_arms(llm=review_llm(supervisor=boom))
    row = run_one(team, item())
    assert row["status"] == "error" and "RuntimeError" in row["error"]
    assert M.compute_review_metrics([row], by_id([item()]))["errors"] == 1


# ---------- single 갈래: 에이전트 하나, 같은 검색과 인용 검사 ----------

def test_single_arm_reviews_four_views_in_one_call_with_same_searches():
    (team, single), llm, retriever = make_arms()
    row = run_one(single, item())
    assert row["status"] == "pending_approval" and [r["team"] for r in row["issue_rows"]] == list(ORDER)
    assert row["llm_calls"] == 1 and row["saved_before_approval"] is None
    assert [c["org"] for c in row["retrieval_calls"]] == [t.org for t in T.TEAMS]  # 팀과 같은 절, 같은 검색어, 팀마다 한 번
    assert [c["query"] for c in row["retrieval_calls"]] == [T.search_text(t, item()["input"]) for t in T.TEAMS]
    for r in row["issue_rows"]:  # 같은 인용 검사: 근거 섹션, 판 날짜는 청크에서 복사
        c = CHUNK_OF[r["team"]]
        assert r["chunk_id"] == c.chunk_id and r["version_date"] == c.version_date and r["section_path"]


def test_single_arm_searches_with_the_same_sub_queries_k_and_form_skill_as_the_team(monkeypatch):
    """사전 등록 62.41: 단일 갈래(same)는 팀과 같은 자료를 받는다. 하위 질문 둘, 10개, 쟁점표 양식 Skill 한 번."""
    (team, single), llm, retriever = make_arms()
    run_one(team, item())
    team_q = sorted((q.org, q.query, tuple(q.sub_queries or ()), q.k) for q in retriever.calls)
    retriever.calls.clear()
    row = run_one(single, item())
    single_q = sorted((q.org, q.query, tuple(q.sub_queries or ()), q.k) for q in retriever.calls)
    assert single_q == team_q and all(c["sub_queries"] == [c["query"], next(t.focus for t in T.TEAMS if t.org == c["org"])] and c["k"] == 10 for c in row["retrieval_calls"])
    (system,) = llm.systems["single"]
    assert system.count("[쟁점표 양식 Skill]") == 1 and "[보안 관점 Skill]" in system
    monkeypatch.setenv("USE_SKILLS", "0")
    (_, single2), llm2, _ = make_arms()
    run_one(single2, item())
    (system2,) = llm2.systems["single"]
    assert "[쟁점표 양식 Skill]" not in system2 and "관점 Skill]" not in system2


def test_single_arm_undivided_searches_once_and_the_single_code_lives_in_the_backend_module():
    from backend.graph.departments import single_review as SR

    assert M.run_single is SR.run_single and M.SINGLE_SYSTEM is SR.SINGLE_SYSTEM and M.single_leaks is SR.single_leaks   # 측정기는 같은 코드를 다시 내보낸다
    llm, r = review_llm(single=single_issues), Retriever()
    out = SR.run_single(item()["input"], AS_OF, retriever=r, llm=llm, search="undivided", wide_retriever=r)
    assert len(r.calls) == 1 and r.calls[0].org is None and r.calls[0].k == 40 and r.calls[0].sub_queries is None and out["retrieved"].keys() == {"all"}


def test_single_arm_uses_the_same_citation_check():
    def bad(user):  # 자료에 없는 chunk_id와 다른 팀 자료의 chunk_id를 쓴다
        ids = chunk_ids(user)
        return j(missing=[], issues=[{"team": "security", "issue": "없는 근거", "chunk_id": "0" * 16, "stance": "block", "confidence": "high"},
                                      {"team": "security", "issue": "다른 팀 근거", "chunk_id": [i for i in ids if i == FIN.chunk_id][0], "stance": "block", "confidence": "high"}])

    (_, single), _, _ = make_arms(single_handler=bad)
    row = run_one(single, item())
    assert row["issue_rows"] == [] and row["llm_calls"] == 3  # 모두 걸리면 상한까지 다시 묻는다(team과 같은 상한)
    assert len(row["unreviewed"]) == 4  # 조용히 쟁점 없음으로 위장하지 않는다
    assert row["team_status"]["security"]["status"] == "not_reviewed"


def test_single_arm_unreadable_json_is_retried_then_left_unreviewed():
    (_, single), llm, _ = make_arms(single_handler="이건 JSON이 아니다")
    row = run_one(single, item())
    assert row["llm_calls"] == 3 and row["issue_rows"] == [] and len(row["unreviewed"]) == 4 and row["status"] == "pending_approval"


def test_single_arm_clarifies_and_empty_request():
    (_, single), _, _ = make_arms(single_handler=j(missing=["도입 금액"], issues=[]))
    row = run_one(single, item(kind="clarify", text="새 SaaS를 도입하려 한다."))
    assert row["status"] == "clarify" and "도입 금액" in row["clarify_question"] and row["issue_rows"] == []
    row = run_one(single, item(2, text="   "))
    assert row["status"] == "clarify" and row["llm_calls"] == 0


def test_single_arm_search_failure_leaves_that_view_unreviewed_not_missing():
    (_, single), _, _ = make_arms(retriever=Retriever(fail_orgs=("infra",)))
    row = run_one(single, item())
    assert [r["team"] for r in row["issue_rows"]] == ["security", "itops", "finance"]
    assert [u["team"] for u in row["unreviewed"]] == ["infra"] and row["retrieval_errors"] == 3


# ---------- 번갈아 돌리기, 같은 모델 ----------

def test_run_arms_alternates_order_and_both_arms_share_one_model():
    arms, llm, _ = make_arms()
    assert arms[0].llm.llm is arms[1].llm.llm  # 같은 모델 객체
    seen = []
    rows = M.run_arms([item(1), item(2), item(3)], arms, "t", on_row=lambda a, r: seen.append((r["id"], a.name)))
    assert seen == [(1, "team"), (1, "single"), (2, "single"), (2, "team"), (3, "team"), (3, "single")]
    assert [len(rows[n]) for n in M.ARMS] == [3, 3]
    res = M.compare(rows, by_id([item(1), item(2), item(3)]))
    assert res["metrics"]["team"]["issue_rows"] == res["metrics"]["single"]["issue_rows"] == 12
    assert res["delta_team_minus_single"]["llm_calls_mean"] == 4  # 5회 - 1회


def test_run_arms_stops_on_search_error_by_default_and_can_continue():
    arms, _, _ = make_arms(retriever=Retriever(fail_orgs=("security",)))
    with pytest.raises(SystemExit, match="검색 오류로 중단"):
        M.run_arms([item(1), item(2)], arms, "t")
    arms, _, _ = make_arms(retriever=Retriever(fail_orgs=("security",)))
    rows = M.run_arms([item(1), item(2)], arms, "t", stop_on_search_error=False)
    assert len(rows["team"]) == len(rows["single"]) == 2


# ---------- 지표 계산: 맞는 경우와 틀린 경우 ----------

def fake_row(i, team_rows, status="pending_approval", saved=0, kind="full", **extra):
    return {"id": i, "kind": kind, "arm": "team", "status": status, "issue_rows": team_rows, "unreviewed": [], "saved_before_approval": saved,
            "latency_s": 1.0, "cost_usd": 0.001, "llm_calls": 5, "retrieval_errors": 0, **extra}


def irow(team, chunk, **over):
    d = {"team": team, "rule_seq": chunk.rule_seq, "article": chunk.article, "chunk_id": chunk.chunk_id, "section_path": f"{chunk.rule_title} > {chunk.article}",
         "version_date": chunk.version_date}
    d.update(over)
    return d


def test_missed_issue_rate_counts_gold_issues_with_no_matching_row():
    it = item(1, judges=["a"], gold=[("security", SEC, "2026-04-24"), ("infra", INFRA, None), ("itops", ITOPS, None), ("finance", FIN, None)])
    rows = [fake_row(1, [irow("security", SEC), irow("infra", INFRA)])]  # itops, finance를 놓침
    m = M.compute_review_metrics(rows, by_id([it]))
    assert m["gold_status"] == "계산함" and m["gold_total"] == 4 and m["gold_found"] == 2 and m["missed_issue_rate"] == 0.5


def test_gold_match_needs_same_team_and_section_and_wrong_ones_do_not_count():
    it = item(1, judges=["a"], gold=[("security", SEC, None)])
    other_team = fake_row(1, [irow("finance", SEC)])  # 섹션은 같지만 다른 팀의 행
    other_section = fake_row(1, [irow("security", SEC, rule_seq=SEC.rule_seq + 1)])  # 다른 페이지
    other_article = fake_row(1, [irow("security", SEC, article="Other > Part")])
    for r in (other_team, other_section, other_article):
        m = M.compute_review_metrics([r], by_id([it]))
        assert m["missed_issue_rate"] == 1.0 and m["unmatched_row_rate"] == 1.0
    ok = M.compute_review_metrics([fake_row(1, [irow("security", SEC, article="Intro > " + SEC.article + " > Sub")])], by_id([it]))
    assert ok["missed_issue_rate"] == 0.0 and ok["unmatched_row_rate"] == 0.0  # 제목 경로가 이어서 들어 있으면 맞다(하위 섹션도)


def test_same_section_with_another_issue_text_is_not_distinguished_known_limit():
    it = item(1, judges=["a"], gold=[("security", SEC, None)])
    r = fake_row(1, [irow("security", SEC, issue="전혀 다른 말")])
    assert M.compute_review_metrics([r], by_id([it]))["missed_issue_rate"] == 0.0  # 한계 1: 쟁점 문장은 비교하지 않는다


def test_date_agree_rate_only_over_gold_issues_with_a_date():
    it = item(1, judges=["a"], gold=[("security", SEC, "2026-04-24"), ("infra", INFRA, "2020-01-01"), ("finance", FIN, None)])
    rows = [fake_row(1, [irow("security", SEC), irow("infra", INFRA), irow("finance", FIN)])]
    m = M.compute_review_metrics(rows, by_id([it]))
    assert m["missed_issue_rate"] == 0.0 and m["date_agree_rate"] == 0.5


def test_gold_metrics_show_pending_and_do_not_invent_numbers():
    pending = [item(1), item(2, judges=["a"], gold=[("security", SEC, None)])]  # 1번은 판정자도 정답도 없음
    rows = [fake_row(1, [irow("security", SEC)]), fake_row(2, [irow("security", SEC)])]
    m = M.compute_review_metrics(rows, by_id(pending))
    assert m["gold_status"] == M.PENDING and m["gold_pending_ids"] == [1]
    assert m["missed_issue_rate"] == m["date_agree_rate"] == m["unmatched_row_rate"] == M.PENDING
    assert m["gold_total"] is None and m["gold_found"] is None
    assert m["section_rate"] == 1.0  # 정답과 무관한 지표는 그대로 낸다
    assert M.compute_review_metrics(rows[:1], by_id(pending))["gold_status"] == M.PENDING


def test_pending_rules_judges_without_gold_and_confirmed_no_issue():
    assert M.judged_state(item(1)) == "pending"
    assert M.judged_state(item(1, judges=["a"])) == "pending"  # 판정자가 있는데 정답이 비었고 '쟁점 없음' 확인도 없다
    assert M.judged_state(item(1, judges=["a"], no_gold=True)) == "ready"
    assert M.judged_state(item(1, judges=["a"], gold=[("security", SEC, None)])) == "ready"
    assert M.judged_state(item(1, kind="clarify")) == "n/a"
    quiet = item(1, kind="low_issue", judges=["a"], no_gold=True)
    m = M.compute_review_metrics([fake_row(1, [irow("finance", FIN)], kind="low_issue")], by_id([quiet]))
    assert m["gold_status"] == "계산함" and m["gold_total"] == 0 and m["missed_issue_rate"] is None and m["unmatched_row_rate"] == 1.0


def test_clarify_items_are_excluded_from_gold_metrics_and_only_clarify_items_give_clarify_rate():
    items = [item(1, judges=["a"], gold=[("security", SEC, None)]), item(2, kind="clarify")]
    rows = [fake_row(1, [irow("security", SEC)]), fake_row(2, [], status="clarify", kind="clarify")]
    m = M.compute_review_metrics(rows, by_id(items))
    assert m["gold_status"] == "계산함" and m["missed_issue_rate"] == 0.0
    assert m["clarify_expected"] == 1 and m["clarify_asked"] == 1 and m["clarify_rate"] == 1.0 and m["false_clarify_rate"] == 0.0
    assert m["clarify_confirmed"] is False  # 판정자 확인 전
    only_clarify = M.compute_review_metrics(rows[1:], by_id(items))
    assert only_clarify["gold_status"] == "해당 문항 없음" and only_clarify["missed_issue_rate"] is None


def test_clarify_rate_is_zero_when_the_request_is_not_questioned_and_false_clarify_is_counted():
    items = [item(1, kind="clarify"), item(2)]
    rows = [fake_row(1, [irow("security", SEC)], kind="clarify"), fake_row(2, [], status="clarify")]
    m = M.compute_review_metrics(rows, by_id(items))
    assert m["clarify_rate"] == 0.0 and m["false_clarify_rate"] == 1.0


def test_evidence_rates_catch_missing_section_or_date():
    good = irow("security", SEC)
    no_sec = irow("infra", INFRA, section_path="")
    no_date = irow("itops", ITOPS, version_date=None)
    bad_date = irow("finance", FIN, version_date="2023/05/11")
    m = M.compute_review_metrics([fake_row(1, [good, no_sec, no_date, bad_date])], by_id([item()]))
    assert (m["section_rate"], m["date_rate"], m["evidence_complete_rate"]) == (0.75, 0.5, 0.25)
    empty = M.compute_review_metrics([fake_row(1, [], status="no_issues")], by_id([item()]))
    assert empty["section_rate"] is None and empty["evidence_complete_rate"] is None  # 분모 0은 None


def test_real_team_rows_all_carry_section_and_date():
    (team, single), _, _ = make_arms()
    rows = {"team": [run_one(team, item())], "single": [run_one(single, item())]}
    res = M.compare(rows, by_id([item()]))
    for a in M.ARMS:
        assert res["metrics"][a]["evidence_complete_rate"] == 1.0 and res["metrics"][a]["errors"] == 0
    assert res["metrics"]["team"]["pre_approval_saved"] == 0 and res["metrics"]["single"]["pre_approval_saved"] is None


def test_latency_cost_and_error_aggregation():
    rows = [fake_row(i, [], status="no_issues", latency_s=float(i), cost_usd=0.01 * i, llm_calls=i) for i in range(1, 5)]
    rows[3]["status"] = "error"
    m = M.compute_review_metrics(rows, by_id([item(i) for i in range(1, 5)]))
    assert m["latency_mean_s"] == 2.5 and m["latency_p95_s"] == 4.0 and m["errors"] == 1
    assert m["cost_usd"] == 0.1 and m["cost_usd_mean"] == pytest.approx(0.025) and m["llm_calls_mean"] == 2.5


# ---------- 결과 파일, 환경 ----------

def test_write_arm_writes_raw_rows_and_summary(tmp_path):
    (team, _), _, _ = make_arms()
    rows = [run_one(team, item())]
    m = M.compute_review_metrics(rows, by_id([item()]))
    M._write_arm(tmp_path, "team", rows, m, {"x": 1})
    back = [json.loads(x) for x in (tmp_path / "team" / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert back[0]["issue_rows"][0]["section_path"] and back[0]["saved_before_approval"] == 0
    s = json.loads((tmp_path / "team" / "summary.json").read_text(encoding="utf-8"))
    assert s["meta"]["arm"] == "team" and s["metrics"]["gold_status"] == M.PENDING


def test_openrouter_env_is_fixed_and_refuses_bad_keys(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY", "DEMO_MODE", "LLM_RECORD"):
        monkeypatch.setenv(name, "x")  # 시험이 끝나면 되돌린다
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        M.use_openrouter_env()
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-an-openrouter-key")
    with pytest.raises(SystemExit):
        M.use_openrouter_env()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-only")
    M.use_openrouter_env()
    assert os.environ["LLM_PROVIDER"] == "openrouter" and os.environ["LLM_MODEL"] == "anthropic/claude-haiku-5.5"
    assert "ANTHROPIC_API_KEY" not in os.environ and "LLM_BASE_URL" not in os.environ and "LLM_FALLBACK_MODEL" not in os.environ


def test_default_llm_is_openrouter(monkeypatch):
    captured = {}
    monkeypatch.setattr(M, "run_cmd", lambda a: captured.setdefault("args", a) and 0)  # main()이 이름으로 읽는다. 실제 실행은 하지 않는다
    M.main(["run", "--out", "x"])
    a = captured["args"]
    assert a.llm == "openrouter" and a.store == "memory" and a.limit is None and a.dataset is None
    with pytest.raises(SystemExit):
        M.main(["run"])  # --out은 필수


# ---------- missing 기준 (사전 등록 62.36) ----------

def test_missing_rule_is_one_text_shared_by_both_arms_and_is_narrow():
    """missing 기준은 한 곳(`T.MISSING_RULE`)에 있고 team과 single이 같은 문구를 쓴다. 세부 식별 정보는 넣지 않고 결론을 가르는 값만 넣는다."""
    assert T.MISSING_RULE in T.SUPERVISOR_SYSTEM and T.MISSING_RULE in M.SINGLE_SYSTEM
    assert "검토에 꼭 필요한데 요청에 없는 값" not in T.SUPERVISOR_SYSTEM + M.SINGLE_SYSTEM  # 옛 넓은 정의
    for phrase in ("결론", "나눠 적을 수 있으면 넣지 않는다", "세부 식별 정보", "통째로 빠졌으면"):
        assert phrase in T.MISSING_RULE
    (team, single), llm, _ = make_arms()
    run_one(team, item())
    run_one(single, item())
    assert T.MISSING_RULE in llm.systems["supervisor"][0] and T.MISSING_RULE in llm.systems["single"][0]


def test_empty_missing_goes_on_to_search_and_filled_missing_asks_back_in_both_arms():
    (team, single), _, retriever = make_arms(llm=review_llm(supervisor=j(missing=[], tasks={}), single=single_issues))
    for arm in (team, single):
        row = run_one(arm, item())
        assert row["status"] == "pending_approval" and row["issue_rows"]
    assert len(retriever.calls) == 8  # 갈래마다 팀 4곳을 검색한다
    filled = review_llm(supervisor=j(missing=["도입 금액"], tasks={}), single=j(missing=["도입 금액"], issues=[]))
    (team, single), _, retriever = make_arms(llm=filled)
    row = run_one(team, item(kind="clarify", text="새 SaaS를 도입하려 한다."))
    assert row["status"] == "clarify" and row["issue_rows"] == [] and retriever.calls == []  # team은 검색 없이 되묻는다
    row = run_one(single, item(kind="clarify", text="새 SaaS를 도입하려 한다."))  # single은 기존대로 검색을 먼저 한 뒤 모델이 되묻는다
    assert row["status"] == "clarify" and row["issue_rows"] == []