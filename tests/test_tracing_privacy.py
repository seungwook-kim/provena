from __future__ import annotations

from backend.services import tracing
from backend.services.llm import run_config


def test_langfuse_callback_is_fail_closed_without_content_capture(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-local-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-local-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.delenv("LANGFUSE_CONTENT_CAPTURE_ENABLED", raising=False)
    tracing.reset()

    config = run_config(
        "privacy-test",
        session_id="session-with-fake-phone-010-1234-5678",
        user_id="user-with-fake-address",
        metadata={"prompt": "fake name Alice, phone 010-1234-5678"},
    )

    assert tracing.tracing_enabled()
    assert tracing.get_handler() is None
    assert len(config["callbacks"]) == 1  # CostTracker only.
    assert "langfuse_session_id" not in config["metadata"]
    assert "langfuse_user_id" not in config["metadata"]
    assert "prompt" not in config["metadata"]


def test_langfuse_is_fully_disabled_without_keys(monkeypatch):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_CONTENT_CAPTURE_ENABLED", raising=False)
    tracing.reset()

    assert tracing.langfuse_settings() is None
    assert tracing.get_handler() is None


def test_safe_event_has_no_content_or_identifiers(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.events = []

        def create_event(self, **kwargs):
            self.events.append(kwargs)

    fake = FakeClient()
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_SAFE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-local-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-local-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setattr(tracing, "_make_client", lambda *_: fake)
    tracing.reset()

    assert tracing.create_safe_event(
        name="ai_run_finished",
        metadata={
            "graph": "privacy-test",
            "calls": 1,
            "prompt": "Alice 010-1234-5678",
            "response": "Seoul office",
            "user_id": "secret-user",
        },
    )
    event = fake.events[0]
    assert event["input"] is None and event["output"] is None
    assert event["metadata"] == {"graph": "privacy-test", "calls": 1}

