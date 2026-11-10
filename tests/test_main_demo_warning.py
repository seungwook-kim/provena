"""키 없이 조용히 데모 모드로 도는 배포를 시작 로그로 알리는지(backend/main.py warn_if_silent_demo). 동작은 바꾸지 않는다."""
from __future__ import annotations

import logging

import pytest

from backend.main import warn_if_silent_demo

ENV_KEYS = ["PROVENA_ENV", "DEMO_MODE", "LLM_PROVIDER", "LLM_API_KEY"]


@pytest.fixture
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_warns_when_key_missing_outside_demo(clean_env, caplog):
    clean_env.setenv("PROVENA_ENV", "production")
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        assert warn_if_silent_demo() is True
    assert "LLM_API_KEY" in caplog.text


@pytest.mark.parametrize("key,value", [("PROVENA_ENV", "local"), ("PROVENA_ENV", "demo"), ("DEMO_MODE", "1"),
                                       ("LLM_PROVIDER", "claude_cli"), ("LLM_API_KEY", "x")])
def test_silent_when_demo_is_intended_or_key_present(clean_env, caplog, key, value):
    clean_env.setenv(key, value)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        assert warn_if_silent_demo() is False
    assert "LLM_API_KEY" not in caplog.text
