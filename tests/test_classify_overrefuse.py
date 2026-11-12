"""분류 단계만 부르는 확인(evals/agent/classify_overrefuse.py, 사전 등록 62.30). 가짜 모델로 0원."""
from __future__ import annotations

from evals.agent import classify_overrefuse as C
from qgraph_fakes import ScriptedLLM, j


def _llm(route_for):
    return C.Counting(ScriptedLLM({"classify": lambda user: route_for(user)}))


def test_items_cover_both_sets_and_the_probe_file_without_overlap():
    items = C.load_items()
    ids = [it["id"] for it in items]
    assert len(items) == 84 and len(set(ids)) == 84
    groups = {g: sum(1 for it in items if C.group_of(it) == g) for g in ("relevant", "general", "other", "seen")}
    assert groups == {"relevant": 43, "general": 13, "other": 27, "seen": 1}
    probe = [it for it in items if it["probe"]]
    assert sum(1 for it in probe if it["probe"] == "org_rule") == 5 and sum(1 for it in probe if it["probe"] == "general") == 5
    assert sum(1 for it in probe if it["probe"] == C.NEED_PROBE) == 4
    asked = {it["question"] for it in items if not it["probe"]}
    assert not asked & {it["question"] for it in probe}


def test_only_the_classify_step_is_called_and_out_of_domain_is_asked_twice():
    items = [{"id": 1, "question": "사내 질문", "kind": "relevant", "probe": ""}, {"id": 18, "question": "일반 질문", "kind": "irrelevant", "probe": ""}]
    llm = _llm(lambda user: j(org_specific=False, route="out_of_domain") if "일반 질문" in user else j(org_specific=True, route="rule"))
    rows = C.run(items, llm, repeats=2)
    assert [r["route"] for r in rows] == ["rule", "out_of_domain"] * 2 and [r["llm_calls"] for r in rows] == [1, 2] * 2
    assert {task for task, _ in llm.inner.calls} == {"classify"} and llm.calls == 6
    assert C.summarize(rows)["passed"]


def test_gate_fails_when_a_relevant_question_is_out_of_domain_and_ignores_the_seen_item():
    row = lambda i, group, route: {"repeat": 1, "id": i, "kind": "", "group": group, "route": route, "llm_calls": 1}  # noqa: E731
    seen_only = C.summarize([row(109, "seen", "out_of_domain"), row(1, "relevant", "rule"), row(18, "general", "out_of_domain")])
    assert seen_only["passed"] and seen_only["seen"]["out_of_domain"] == 1
    bad = C.summarize([row(1, "relevant", "out_of_domain"), row(18, "general", "out_of_domain")])
    assert not bad["passed"] and not bad["pass_relevant"] and bad["relevant"]["out_of_domain_ids"] == [1]
    leaky = C.summarize([row(1, "relevant", "rule")] + [row(18, "general", "out_of_domain")] * 8 + [row(19, "general", "rule")] * 2)
    assert not leaky["passed"] and leaky["general_out_of_domain_rate"] == 0.8


def test_plan_makes_no_call_and_counts_no_embedding():
    plan = C.plan(C.load_items(), 3)
    assert plan["items"] == 84 and plan["embedding_calls"] == 0 and 240 <= plan["est_llm_calls"] <= 480 and plan["est_cost_usd"] < 0.1


def test_need_yes_no_questions_must_not_end_at_review():
    """필요 여부를 예·아니오로 묻는 문항은 모델이 합동 검토라고 해도 정책 경로다(62.34). 검토를 맡기는 요청은 그대로다."""
    need = [it for it in C.load_items() if it["probe"] == C.NEED_PROBE]
    asked = [*need, {"id": 900, "question": "새 모니터링 도구 도입안을 합동 검토해줘", "kind": "relevant", "probe": ""}]
    rows = C.run(asked, _llm(lambda user: j(org_specific=True, route="review")))
    assert [r["route"] for r in rows] == ["rule"] * len(need) + ["review"]
    assert C.summarize(rows)["pass_need_yes_no"]
    row = lambda route: {"repeat": 1, "id": 321, "kind": "relevant", "group": "relevant", "probe": C.NEED_PROBE, "route": route, "llm_calls": 1}  # noqa: E731
    general = {"repeat": 1, "id": 18, "kind": "", "group": "general", "probe": "", "route": "out_of_domain", "llm_calls": 1}
    bad = C.summarize([row("review"), general])
    assert not bad["passed"] and bad["need_yes_no"]["review_ids"] == [321]


def test_review_set_is_added_only_on_request_and_its_ids_do_not_collide():
    base = C.load_items()
    with_set = C.load_items(with_review_set=True)
    assert len(base) == 84 and len(with_set) == 94 and len({it["id"] for it in with_set}) == 94
    ask = [it for it in with_set if C.group_of(it) == "review_request"]
    assert sorted(it["id"] for it in ask) == list(range(1001, 1011)) and {it["probe"] for it in ask} == {C.REVIEW_PROBE}
    assert C.plan(with_set, 3)["groups"]["review_request"] == 10


def test_review_set_gate_wants_review_two_runs_of_three_and_no_review_outside_the_set():
    """합동 검토 요청 10건은 문항마다 3회 중 2회 이상 review, 그 밖 문항은 review 0(62.39 초안)."""
    ask = lambda i, route: {"repeat": 1, "id": i, "kind": "partial", "group": "review_request", "probe": C.REVIEW_PROBE, "route": route, "llm_calls": 1}  # noqa: E731
    other = lambda i, route: {"repeat": 1, "id": i, "kind": "relevant", "group": "relevant", "probe": "", "route": route, "llm_calls": 1}  # noqa: E731
    gen = {"repeat": 1, "id": 18, "kind": "", "group": "general", "probe": "", "route": "out_of_domain", "llm_calls": 1}  # 일반 지식 기준은 따로 통과해 둔다
    ok = C.summarize([ask(1005, "rule"), ask(1005, "review"), ask(1005, "review"), other(1, "rule"), gen])
    assert ok["pass_review_request"] and ok["pass_no_review_leak"] and ok["passed"]
    miss = C.summarize([ask(1005, "decision"), ask(1005, "rule"), ask(1005, "review"), other(1, "rule"), gen])
    assert not miss["pass_review_request"] and not miss["passed"] and miss["review_request"]["review_runs"] == {1005: 1}
    leak = C.summarize([ask(1005, "review"), ask(1005, "review"), ask(1005, "review"), other(7, "review"), gen])
    assert leak["pass_review_request"] and not leak["pass_no_review_leak"] and leak["review_leak"]["ids"] == [7] and not leak["passed"]


def test_review_set_questions_are_never_sent_back_to_the_policy_path_by_code():
    """모델이 review라고 하면 코드의 되돌림(asks_fact_not_review)은 이 10건을 정책 경로로 돌리지 않는다. 분류 문구가 원인임을 0원으로 가른다."""
    ask = [it for it in C.load_items(with_review_set=True) if it["probe"] == C.REVIEW_PROBE]
    rows = C.run(ask, _llm(lambda user: j(org_specific=True, route="review")))
    assert [r["route"] for r in rows] == ["review"] * 10
