"""OpenRouter 공급자와 OpenRouter식 모델 id의 단가 찾기. 네트워크 호출 없음(생성자만)."""
from langchain_core.language_models.fake_chat_models import FakeListChatModel
import pytest

from backend.services import cost
from backend.services.llm import OPENROUTER_BASE_URL, get_chat_model

PRICES = {
    "default": {"input": 9.0, "output": 9.0},
    "models": {"claude-haiku-5-5": {"input": 0.10, "output": 0.50}, "gpt-6-luna": {"input": 0.20, "output": 0.60}},
}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("LLM_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def test_openrouter_defaults(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_PROVIDER", "OpenRouter")
    m = get_chat_model()
    assert type(m).__name__ == "ChatOpenAI"
    assert m.model_name == "anthropic/claude-haiku-5.5"
    assert str(m.openai_api_base) == OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


def test_openrouter_model_and_base_url_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6-luna")
    monkeypatch.setenv("LLM_BASE_URL", "http://proxy.test/v1")
    m = get_chat_model()
    assert m.model_name == "openai/gpt-6-luna" and str(m.openai_api_base) == "http://proxy.test/v1"
    monkeypatch.setenv("LLM_BASE_URL", "  ")  # 공백이면 기본 주소
    assert str(get_chat_model().openai_api_base) == OPENROUTER_BASE_URL


def test_openrouter_without_key_is_fake(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert isinstance(get_chat_model(), FakeListChatModel)


def test_unknown_provider_message_lists_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="openrouter"):
        get_chat_model()


@pytest.mark.parametrize("model,expected", [
    ("anthropic/claude-haiku-5.5", "claude-haiku-5-5"),
    ("Anthropic/Claude-Haiku-5.5", "claude-haiku-5-5"),
    ("openai/gpt-6-luna:free", "gpt-6-luna"),
    ("claude-haiku-5-5", "claude-haiku-5-5"),
    (None, ""),
])
def test_normalize_model_id(model, expected):
    assert cost.normalize_model_id(model) == expected


@pytest.mark.parametrize("model,price", [
    ("claude-haiku-5-5", (0.10, 0.50)),  # 기존 동작: 정확히 같은 이름
    ("claude-haiku-5-5-20260101", (0.10, 0.50)),  # 기존 동작: 접두어
    ("anthropic/claude-haiku-5.5", (0.10, 0.50)),  # OpenRouter id
    ("anthropic/claude-haiku-5.5-20260101", (0.10, 0.50)),
    ("openai/gpt-6-luna:online", (0.20, 0.60)),
    ("someone/unknown-model", (9.0, 9.0)),  # 모르면 default
    (None, (9.0, 9.0)),
])
def test_price_for_maps_openrouter_ids(model, price):
    assert cost.price_for(model, PRICES) == price


def test_cost_usd_for_openrouter_id_uses_table_row():
    assert cost.cost_usd("anthropic/claude-haiku-5.5", 1_000_000, 1_000_000, PRICES) == pytest.approx(0.60)


def test_real_price_table_knows_openrouter_haiku():
    p = cost.load_prices()
    assert cost.price_for("anthropic/claude-haiku-5.5", p) == cost.price_for("claude-haiku-5-5", p)
