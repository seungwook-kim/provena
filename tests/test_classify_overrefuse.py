"""분류 단계만 부르는 확인(evals/agent/classify_overrefuse.py, 사전 등록 62.A). 가짜 모델로 0원."""
from __future__ import annotations

from evals.agent import classify_overrefuse as C
from qgraph_fakes import ScriptedLLM, j


def _llm(route_for):
    return C.Counting(ScriptedLLM({"classify": lambda user: route_for(user)}))


def test_items_cover_both_sets_and_the_probe_file_without_overlap():
    items = C.load_items()
    ids = [it["id"] for it in items]
    assert len(items) == 80 and len(set(ids)) == 80
    groups = {g: sum(1 for it in items if C.group_of(it) == g) for g in ("relevant", "general", "other", "seen")}
    assert groups == {"relevant": 39, "general": 13, "other": 27, "seen": 1}
    probe = [it for it in items if it["probe"]]
    assert sum(1 for it in probe if it["probe"] == "org_rule") == 5 and sum(1 for it in probe if it["probe"] == "general") == 5
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
    assert plan["items"] == 80 and plan["embedding_calls"] == 0 and 240 <= plan["est_llm_calls"] <= 480 and plan["est_cost_usd"] < 0.1
