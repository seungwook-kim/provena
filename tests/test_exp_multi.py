"""단일 대 멀티 측정 진입 파일 시험 (`evals/agent/exp_multi_v2.py`). 가짜 모델과 가짜 검색기만 쓰고 실제 측정은 하지 않는다."""
from __future__ import annotations

import pytest
from fake_search import fake_search
from qgraph_fakes import j, normal_llm

import os

from evals.agent import exp_multi_v2 as M
from evals.agent.exp_service_v1 import RecordingSearch
from evals.agent.run_eval import verify_frozen
from evals.retrieval.gold import GoldRef

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
ITEMS = [
    {"id": 1, "kind": "relevant", "input": Q, "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=90002, label="런북")]},
    {"id": 2, "kind": "irrelevant", "irrelevant_type": "out_of_domain", "input": "연봉 협상 방법을 알려 주세요", "gold": []},
    {"id": 3, "kind": "relevant", "input": "SEV2 장애 최초 대응은 몇 분 이내인가요? 에스컬레이션은?", "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=90002, label="런북")]},
]


class FakeSearcher:
    def search(self, q):
        return fake_search(q)


def judge(user):
    return j(sufficient=False, reason="없음", clarify=None) if "연봉" in user else j(sufficient=True)


def make_arms(**llm_over):
    arms = []
    for name in M.ARMS:
        llm = M.CountingLLM(normal_llm(judge=judge, **llm_over))
        rec = RecordingSearch(FakeSearcher())
        arms.append(M.Arm(name, M.build_arm_graph(name, rec, llm, decompose=False, grounding_llm=False), rec, llm))
    return arms


def test_dataset_v2_is_frozen_and_default():
    assert M.DATASET.name == "dataset_v2.jsonl"
    verify_frozen(M.DATASET)  # 동결 해시와 같은 파일이어야 돈다


def test_same_items_run_on_both_arms_with_same_metrics_and_no_changed_items():
    arms = make_arms()
    seen = []
    rows = M.run_arms(ITEMS, arms, "t", on_row=lambda a, r: seen.append((r["id"], a.name)))
    assert [len(rows[n]) for n in M.ARMS] == [3, 3]
    assert seen[:4] == [(1, "single"), (1, "multi"), (2, "multi"), (2, "single")]  # 문항마다 순서가 바뀐다
    res = M.compare(rows)
    assert res["changed_items"] == [] and res["changed_count"] == 0
    assert all(v == 0 for k, v in res["delta_multi_minus_single"].items() if k != "latency_p95_s")  # 응답 시간은 실행마다 다르다
    assert res["metrics"]["single"]["correct_refusal_rate"] == 1.0 and res["metrics"]["single"]["errors"] == 0
    assert [r["llm_calls"] for r in rows["single"]] == [r["llm_calls"] for r in rows["multi"]]  # 멀티가 LLM 호출을 늘리지 않는다
    assert res["totals"]["single"]["llm_calls"] == res["totals"]["multi"]["llm_calls"]


def test_llm_calls_are_counted_per_item_and_multi_rows_carry_agent_trace():
    rows = M.run_arms(ITEMS, make_arms(), "t")
    one, off, _ = rows["multi"]
    assert one["llm_calls"] == 4 and one["agent_trace"] == ["retriever", "writer", "verifier"]  # classify, rewrite, judge, answer
    assert off["agent_trace"] == ["retriever"] * 3 and off["result"] == "refuse"  # 연봉 질문: 재검색 2회 뒤 거절
    assert off["llm_calls"] == 1 + 3 * 2  # classify 1 + (rewrite, judge) 3번
    assert "agent_trace" not in rows["single"][0] and rows["single"][0]["arm"] == "single"
    for r in rows["multi"]:
        assert r["retrieval_calls"] is not None and r["supervisor_log"][-1]["to"] == "end"


def test_compare_lists_items_that_changed():
    rows = M.run_arms(ITEMS, make_arms(), "t")
    rows["multi"][0] = {**rows["multi"][0], "result": "refuse", "answered": False}
    res = M.compare(rows)
    assert res["changed_count"] == 1 and res["changed_items"][0]["id"] == 1
    assert res["changed_items"][0]["changed"]["result"] == {"single": "answer", "multi": "refuse"}
    assert res["delta_multi_minus_single"]["over_refusal_rate"] > 0


def test_compare_with_one_arm_only_reports_metrics():
    arm = make_arms()[0]
    res = M.compare(M.run_arms(ITEMS, [arm], "t"))
    assert set(res["metrics"]) == {"single"} and "changed_items" not in res


def test_search_error_stops_the_run():
    def boom(q):
        raise RuntimeError("검색 실패")

    class Boom:
        search = staticmethod(boom)

    llm = M.CountingLLM(normal_llm())
    rec = RecordingSearch(Boom())
    arm = M.Arm("multi", M.build_arm_graph("multi", rec, llm, decompose=False, grounding_llm=False), rec, llm)
    with pytest.raises(SystemExit):
        M.run_arms(ITEMS, [arm], "t")
    with pytest.raises(ValueError):
        M.build_arm_graph("triple", rec, llm)


def test_use_openrouter_env_sends_only_to_openrouter(monkeypatch):
    """`--llm openrouter`: 주소를 바꾸는 값과 다른 키를 지우고, 기본 OpenRouter 주소로 Haiku를 고른다."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-value")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-other")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-other")
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    M.use_openrouter_env()
    assert os.environ["LLM_PROVIDER"] == "openrouter"
    assert os.environ["LLM_MODEL"] == "anthropic/claude-haiku-5.5"
    assert os.environ["LLM_API_KEY"] == "sk-or-test-value"
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY"):
        assert name not in os.environ
    from backend.services.llm import OPENROUTER_BASE_URL, _real_chat_model
    model = _real_chat_model()
    assert str(model.openai_api_base) == OPENROUTER_BASE_URL
    assert model.openai_api_key.get_secret_value() == "sk-or-test-value"


@pytest.mark.parametrize("value", ["", "sk-ant-other", "other"])
def test_use_openrouter_env_rejects_other_keys(monkeypatch, value, capsys):
    """OpenRouter 형식이 아닌 키는 보내지 않고 멈추며, 값을 출력하지 않는다."""
    monkeypatch.setenv("OPENROUTER_API_KEY", value)
    monkeypatch.setenv("LLM_PROVIDER", "claude_cli")
    with pytest.raises(SystemExit) as e:
        M.use_openrouter_env()
    assert os.environ["LLM_PROVIDER"] == "claude_cli"
    if value:
        assert value not in str(e.value)
        assert value not in capsys.readouterr().out
