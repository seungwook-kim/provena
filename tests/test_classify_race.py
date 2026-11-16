"""분류 호출 동시 요청(`GRAPH_CLASSIFY_RACE`, `backend/graph/build.py` `classify`의 `raced`). 가짜 모델과 가짜 검색기만 쓴다(키와 네트워크 없음, 0원).

- 꺼짐: 분류 호출 수, 순서, 경로가 지금과 같다(도메인 밖이면 차례로 두 번).
- 켬: 같은 분류 호출 두 개를 동시에 보내 먼저 성공한 결과를 쓰고, 남은 호출은 버린다. 도메인 밖은 두 결과가 모두 도메인 밖일 때만 따른다(규칙 그대로).
  한 호출이 실패하면 다른 호출의 결과를 쓰고, 두 호출 모두 비용 집계와 호출 기록에 남는다.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from fake_search import fake_search
from qgraph_fakes import ScriptedLLM, j, normal_llm

from backend.graph.build import build_graph
from backend.services import llm as L
from backend.services import llm_trace as T

SWITCH = "GRAPH_CLASSIFY_RACE"
Q = "SEV2 인시던트의 최초 대응 시간은?"
RULE, OOD, REVIEW = j(route="rule"), j(route="out_of_domain"), j(route="review")


class Ordered:
    """분류 호출을 들어온 차례(0부터)로 나눠 답한다. plan[i] = (기다릴 초, 응답 글 또는 예외). 차례를 넘으면 마지막 항목을 쓴다."""

    def __init__(self, plan: list[tuple[float, Any]]):
        self.plan, self.n, self.lock = plan, 0, threading.Lock()
        self.threads: list[str] = []

    def __call__(self, user: str) -> str:
        with self.lock:
            i, self.n = self.n, self.n + 1
            self.threads.append(threading.current_thread().name)
        wait, out = self.plan[min(i, len(self.plan) - 1)]
        time.sleep(wait)
        if isinstance(out, BaseException):
            raise out
        return out


def classify_node(llm: Any):
    return build_graph(fake_search, llm=llm, parallel_intake=False).nodes["classify"].bound


def classify(llm: Any) -> dict:
    return classify_node(llm).invoke({"question": "일반 질문", "profile": {}})


def wait_calls(llm: ScriptedLLM, n: int, timeout: float = 3.0) -> None:
    """버린 호출이 끝날 때까지(호출 기록이 n개가 될 때까지) 기다린다."""
    end = time.monotonic() + timeout
    while llm.count("classify") < n and time.monotonic() < end:
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    return monkeypatch


# ---------------------------------------------------------------- 꺼짐: 지금과 같다
@pytest.mark.parametrize("value", [None, "", "0", "off"])
def test_off_calls_once_in_the_node_thread_and_twice_in_order_for_out_of_domain(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(SWITCH, value)
    rule = Ordered([(0, RULE)])
    llm = ScriptedLLM({"classify": rule})
    assert classify(llm) == {"route": "rule"} and llm.count("classify") == 1
    assert not any(name.startswith("classify_race") for name in rule.threads)   # 배경 일꾼을 쓰지 않는다(지금처럼 노드 안에서 부른다)
    both = ScriptedLLM({"classify": [OOD, OOD]})
    assert classify(both) == {"route": "out_of_domain"} and both.count("classify") == 2
    split = ScriptedLLM({"classify": [OOD, RULE]})
    assert classify(split) == {"route": "rule"} and split.count("classify") == 2   # 갈리면 정책 경로
    fails = ScriptedLLM({"classify": Ordered([(0, ConnectionError("x"))])})
    with pytest.raises(ConnectionError):
        classify(fails)
    assert fails.count("classify") == 1                                            # 실패는 다시 부르지 않고 그대로 올린다


def run_graph(llm: Any, *, parallel: bool | None = None) -> dict:
    g = build_graph(fake_search, llm=llm, grounding_llm=True, decompose=True, parallel_intake=parallel)
    cfg = L.run_config("test", thread_id="t1")
    out = g.invoke({"question": Q, "user_id": "u", "thread_id": "t1", "as_of": "2025-06-01"}, cfg)
    return {"out": {k: v for k, v in out.items() if k != "answer_id"}, "cost": L.finish_run(cfg)}


class ChatScripted(BaseChatModel):
    """`ScriptedLLM`을 콜백이 도는 채팅 모델로 감싼다(비용 집계와 호출 기록이 돈다)."""

    script: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = self.script.invoke(messages)
        msg.usage_metadata = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def in_order(calls: list, parallel: bool) -> list:
    """접수를 동시에 돌리면(재작성·분해가 분류와 같이 돈다) 그 사이 순서는 실행마다 다르므로 정렬해 비교한다. 순차면 순서 그대로다."""
    return sorted(calls) if parallel else list(calls)


def answer_script() -> ScriptedLLM:
    return normal_llm(decompose=j(split=True, sub_questions=["최초 대응은?", "담당은?"]), grounding=j(reason="", grounded=True))


@pytest.mark.parametrize("parallel", [False, True])
def test_off_keeps_the_whole_graph_calls_and_state(parallel):
    """꺼짐(코드 기본)과 `0`의 그래프 전체 호출 순서·상태·비용이 같고, 분류는 한 번이다."""
    plain = answer_script()
    base = run_graph(ChatScripted(script=plain), parallel=parallel)
    assert plain.count("classify") == 1 and base["out"]["kind"] == "answer"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(SWITCH, "0")
        zero = answer_script()
        again = run_graph(ChatScripted(script=zero), parallel=parallel)
    assert in_order(zero.calls, parallel) == in_order(plain.calls, parallel) and again["out"] == base["out"] and again["cost"]["calls"] == base["cost"]["calls"]


# ---------------------------------------------------------------- 켬: 먼저 온 결과
def test_on_takes_the_first_success_and_ignores_the_slow_one(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    llm = ScriptedLLM({"classify": Ordered([(0.6, REVIEW), (0, RULE)])})   # 먼저 들어간 호출이 늦고 다른 경로를 낸다
    t = time.monotonic()
    assert classify(llm) == {"route": "rule"}                              # 늦은 쪽(review)은 쓰지 않는다
    assert time.monotonic() - t < 0.45                                     # 늦은 호출을 기다리지 않는다
    wait_calls(llm, 2)
    assert llm.count("classify") == 2 and len({u for _, u in llm.calls}) == 1   # 같은 입력 두 개


def test_on_out_of_domain_still_needs_both_and_does_not_wait_in_turn(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    both = ScriptedLLM({"classify": Ordered([(0.5, OOD), (0.5, OOD)])})
    t = time.monotonic()
    assert classify(both) == {"route": "out_of_domain"}
    assert time.monotonic() - t < 0.85                                     # 차례로 부르면 1.0초 이상
    assert both.count("classify") == 2                                     # 세 번째 호출은 없다
    split = ScriptedLLM({"classify": Ordered([(0, OOD), (0.3, RULE)])})    # 먼저 온 쪽이 도메인 밖이면 남은 호출을 기다려 확인한다
    assert classify(split) == {"route": "rule"} and split.count("classify") == 2
    first_rule = ScriptedLLM({"classify": Ordered([(0.4, OOD), (0, RULE)])})   # 먼저 온 쪽이 정책이면 그대로(꺼짐에서도 첫 결과가 정책이면 확인하지 않는다)
    assert classify(first_rule) == {"route": "rule"}


def test_on_one_failure_falls_back_to_the_other_and_both_failures_raise(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")
    one = ScriptedLLM({"classify": Ordered([(0, ConnectionError("x")), (0.1, RULE)])})
    assert classify(one) == {"route": "rule"} and one.count("classify") == 2
    two = ScriptedLLM({"classify": Ordered([(0, ConnectionError("a")), (0.05, TimeoutError("b"))])})
    with pytest.raises((ConnectionError, TimeoutError)):
        classify(two)
    # 도메인 밖을 낸 쪽만 성공하면 확인 호출을 지금처럼 한 번 더 부른다(두 결과가 모두 도메인 밖일 때만 따르는 규칙 그대로)
    confirm_ood = ScriptedLLM({"classify": Ordered([(0, ConnectionError("x")), (0.05, OOD), (0, OOD)])})
    assert classify(confirm_ood) == {"route": "out_of_domain"} and confirm_ood.count("classify") == 3
    confirm_rule = ScriptedLLM({"classify": Ordered([(0, ConnectionError("x")), (0.05, OOD), (0, RULE)])})
    assert classify(confirm_rule) == {"route": "rule"} and confirm_rule.count("classify") == 3


def test_on_cost_cap_is_raised_at_once(monkeypatch):
    from backend.services.cost import CostCapExceeded

    monkeypatch.setenv(SWITCH, "1")
    llm = ScriptedLLM({"classify": Ordered([(0, CostCapExceeded(1.0, 1.0)), (0.3, RULE)])})
    with pytest.raises(CostCapExceeded):
        classify(llm)


@pytest.mark.parametrize("parallel", [False, True])
def test_on_counts_both_calls_in_cost_and_trace_and_keeps_the_answer(monkeypatch, parallel):
    """두 분류 호출 모두 비용 집계(분류 단계 2회)와 호출 기록(`classify/classify` 2줄)에 남고, 답과 다른 단계 호출은 끈 것과 같다."""
    plain = answer_script()
    base = run_graph(ChatScripted(script=plain), parallel=parallel)
    monkeypatch.setenv(SWITCH, "1")
    raced = answer_script()
    with T.capture() as calls:
        got = run_graph(ChatScripted(script=raced), parallel=parallel)
    assert got["out"] == base["out"]
    assert in_order([c for c in raced.calls if c[0] != "classify"], parallel) == in_order([c for c in plain.calls if c[0] != "classify"], parallel)
    assert raced.count("classify") == 2 and plain.count("classify") == 1
    assert got["cost"]["calls"] == base["cost"]["calls"] + 1
    step = {k: v["calls"] for k, v in got["cost"]["cost_by_step"].items() if k.endswith("classify")}
    assert sum(step.values()) == 2
    assert [c["step"] for c in calls].count("classify/classify") == 2 and all(c["ok"] for c in calls)


def test_on_non_policy_route_waits_for_the_loser_before_leaving(monkeypatch):
    """정책 경로가 아니면(합동 검토 연결) 남은 호출이 끝난 뒤 노드가 끝난다(답이 나간 뒤에 호출이 돌지 않게)."""
    monkeypatch.setenv(SWITCH, "1")
    llm = ScriptedLLM({"classify": Ordered([(0, REVIEW), (0.3, REVIEW)])})
    node = build_graph(fake_search, llm=llm, parallel_intake=False, review_graph=lambda state: {}).nodes["classify"].bound
    assert node.invoke({"question": "새 도구 도입안을 합동 검토해줘", "profile": {}})["route"] == "review"
    assert llm.count("classify") == 2                                      # 기다리지 않았다면 아직 1


def test_service_profile_turns_it_on_and_off_turns_it_off():
    from backend.graph import service_profile as SP

    env: dict = {}
    SP.apply_service_profile(env)
    assert env[SWITCH] == "1"
    env = {SWITCH: "off"}
    SP.apply_service_profile(env)
    assert env[SWITCH] == ""                                               # 코드 기본이 꺼짐이라 빈 값이 끔이다
