from backend.services.llm import get_chat_model


def test_fake_model_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    m = get_chat_model(["안녕"])
    assert m.invoke("hi").content == "안녕"
