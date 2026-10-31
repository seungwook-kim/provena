"""실제 공급자 분기는 생성자만 시험한다(네트워크 호출·실제 키 없음)."""
from langchain_core.language_models.fake_chat_models import FakeListChatModel
import pytest

from backend.services.llm import get_chat_model


def test_real_provider_branches_construct_without_network(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    m = get_chat_model()
    assert type(m).__name__ == "ChatAnthropic" and m.model == "claude-haiku-5-5"  # 기본
    monkeypatch.setenv("LLM_MODEL", "claude-x")
    assert get_chat_model().model == "claude-x"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL")
    with pytest.raises(ValueError):
        get_chat_model()  # openai는 모델 필수
    monkeypatch.setenv("LLM_MODEL", "gpt-x")
    o = get_chat_model()
    assert type(o).__name__ == "ChatOpenAI" and o.model_name == "gpt-x"
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError):
        get_chat_model()


def test_no_key_still_fake(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert isinstance(get_chat_model(), FakeListChatModel)
