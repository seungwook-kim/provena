"""G-08: 응답 캐시. 가짜 모델로 같은 입력 2번 → 모델 호출 1번. 캐시를 끄면 기존 동작 그대로."""
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from backend.services import llm
from backend.services.llm import CachingChatModel


class CountingModel(FakeListChatModel):
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _inner():
    return CountingModel(responses=["a", "b", "c", "d"])


def test_same_input_twice_calls_once():
    inner = _inner()
    m = CachingChatModel(inner=inner)
    first = m.invoke([HumanMessage("질문")])
    second = m.invoke([HumanMessage("질문")])
    assert inner.calls == 1
    assert first.content == second.content == "a"
    assert (m.hits, m.misses) == (1, 1)


def test_different_input_or_stop_misses():
    inner = _inner()
    m = CachingChatModel(inner=inner)
    m.invoke([HumanMessage("질문 1")])
    m.invoke([HumanMessage("질문 2")])
    m.invoke([HumanMessage("질문 1")], stop=["x"])
    assert inner.calls == 3


def test_eval_metadata_bypasses_cache():
    inner = _inner()
    m = CachingChatModel(inner=inner)
    cfg = {"metadata": {"eval": True}}
    m.invoke([HumanMessage("질문")], config=cfg)
    m.invoke([HumanMessage("질문")], config=cfg)
    assert inner.calls == 2
    assert m.hits == 0


def test_hit_zeroes_usage_so_cost_not_double_counted():
    class UsageModel(CountingModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            msg = AIMessage("x", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
            from langchain_core.outputs import ChatGeneration, ChatResult
            return ChatResult(generations=[ChatGeneration(message=msg)])

    m = CachingChatModel(inner=UsageModel(responses=["x"]))
    first = m.invoke([HumanMessage("q")])
    second = m.invoke([HumanMessage("q")])
    assert first.usage_metadata["input_tokens"] == 10
    assert second.usage_metadata["input_tokens"] == 0


def test_lru_evicts_oldest():
    inner = _inner()
    m = CachingChatModel(inner=inner, max_entries=1)
    m.invoke([HumanMessage("1")])
    m.invoke([HumanMessage("2")])
    m.invoke([HumanMessage("1")])
    assert inner.calls == 3


def test_flag_off_by_default_and_demo_untouched(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_RESPONSE_CACHE", "1")
    assert not isinstance(llm.get_chat_model(["안녕"]), CachingChatModel)  # 데모 모드는 그대로


def test_flag_wraps_real_model_only_when_on(monkeypatch):
    fake = _inner()
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("LLM_RECORD", raising=False)
    monkeypatch.setattr(llm, "_real_chat_model", lambda: fake)
    monkeypatch.delenv("LLM_RESPONSE_CACHE", raising=False)
    assert llm.get_chat_model() is fake
    monkeypatch.setenv("LLM_RESPONSE_CACHE", "1")
    assert isinstance(llm.get_chat_model(), CachingChatModel)


class _UsageInner(CountingModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult
        self.calls += 1
        msg = AIMessage("x", usage_metadata={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _tracked(model, n):
    """그래프처럼 RunnableLambda 안에서 CostTracker 콜백을 달고 n번 부른다. (calls, input_tokens)를 돌려준다."""
    from langchain_core.runnables import RunnableLambda
    from backend.services.cost import CostTracker
    tracker = CostTracker(100.0)
    chain = RunnableLambda(lambda q: model.invoke([HumanMessage(q)]))
    for _ in range(n):
        chain.invoke("q", {"callbacks": [tracker]})
    s = tracker.summary()
    return s["calls"], s["input_tokens"]


def test_cost_counted_once_per_miss_and_zero_on_hit():
    assert _tracked(_UsageInner(responses=["x"]), 1) == (1, 1000)             # 감싸지 않은 값
    assert _tracked(CachingChatModel(inner=_UsageInner(responses=["x"])), 1) == (1, 1000)   # 미스 1번 = 같은 값
    calls, tokens = _tracked(CachingChatModel(inner=_UsageInner(responses=["x"])), 2)       # 적중은 사용량 0
    assert tokens == 1000 and calls == 2


def test_eval_bypass_counts_cost_once():
    from langchain_core.runnables import RunnableLambda
    from backend.services.cost import CostTracker
    tracker = CostTracker(100.0)
    m = CachingChatModel(inner=_UsageInner(responses=["x"]))
    RunnableLambda(lambda q: m.invoke([HumanMessage(q)])).invoke("q", {"callbacks": [tracker], "metadata": {"eval": True}})
    assert tracker.summary()["calls"] == 1 and tracker.summary()["input_tokens"] == 1000


def test_key_distinguishes_tool_calls_and_tool_call_id():
    from langchain_core.messages import ToolMessage
    m = CachingChatModel(inner=_inner())
    a = [AIMessage("", tool_calls=[{"name": "f", "args": {"x": 1}, "id": "1"}])]
    b = [AIMessage("", tool_calls=[{"name": "f", "args": {"x": 2}, "id": "1"}])]
    assert m._cache_key(a, None, {}) != m._cache_key(b, None, {})
    t1, t2 = [ToolMessage("r", tool_call_id="1")], [ToolMessage("r", tool_call_id="2")]
    assert m._cache_key(t1, None, {}) != m._cache_key(t2, None, {})
    assert m._cache_key([AIMessage("a", id="i1")], None, {}) == m._cache_key([AIMessage("a", id="i2")], None, {})  # id는 키에서 뺌
