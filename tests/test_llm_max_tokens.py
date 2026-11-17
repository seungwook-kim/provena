"""LLM 출력 상한 `LLM_MAX_TOKENS`(기본 2500)가 모든 제공자 경로의 요청에 실리는지 본다. 네트워크·실제 키 없음(요청 본문만 만든다)."""
from __future__ import annotations

import subprocess

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from backend.services import claude_cli_model as C
from backend.services import llm as L

PATH_ENVS = ("LLM_MAX_TOKENS", "LLM_EFFORT", "LLM_EFFORT_BY_TASK", "LLM_DEADLINE_S", "LLM_HEDGE_S", "LLM_PROMPT_CACHE", "LLM_TRACE_DETAIL",
             "LLM_REASONING", "LLM_REASONING_BY_TASK", "LLM_PROVIDER_SORT", "LLM_BASE_URL", "LLM_FALLBACK_MODEL", "LLM_MAX_RETRIES", "LLM_TIMEOUT_S")
MSGS = [SystemMessage("[[task:answer]]\n지시"), HumanMessage("질문")]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in PATH_ENVS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("raw, expected", [(None, 2500), ("", 2500), ("1200", 1200), (" 3000 ", 3000), ("0", 2500), ("-5", 2500), ("abc", 2500)])
def test_llm_max_tokens_env_parsing(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("LLM_MAX_TOKENS", raw)
    assert L.llm_max_tokens() == expected


def test_anthropic_plain_path_sends_max_tokens():
    m = L._provider_model("anthropic", "", "dummy-not-a-real-key")
    assert type(m).__name__ == "ChatAnthropic"
    assert m.max_tokens == 2500
    assert m._get_request_payload(MSGS)["max_tokens"] == 2500


def test_anthropic_tuned_path_sends_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_EFFORT", "low")          # 단계별 effort를 쓰면 ChatAnthropic 하위 클래스(TaskEffortAnthropic)로 간다
    monkeypatch.setenv("LLM_PROMPT_CACHE", "1")
    m = L._provider_model("anthropic", "", "dummy-not-a-real-key")
    assert type(m).__name__ == "TaskEffortAnthropic"
    payload = m._get_request_payload(MSGS)
    assert payload["max_tokens"] == 2500


def test_env_value_overrides_default_on_both_anthropic_paths(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "1800")
    assert L._provider_model("anthropic", "", "k")._get_request_payload(MSGS)["max_tokens"] == 1800
    monkeypatch.setenv("LLM_EFFORT", "none")
    tuned = L._provider_model("anthropic", "", "k")
    assert type(tuned).__name__ == "TaskEffortAnthropic" and tuned._get_request_payload(MSGS)["max_tokens"] == 1800


@pytest.mark.parametrize("provider, model", [("openai", "gpt-x"), ("openrouter", "")])
def test_openai_compatible_paths_send_max_completion_tokens(provider, model):
    m = L._provider_model(provider, model, "dummy-not-a-real-key")
    assert m._get_request_payload(MSGS)["max_completion_tokens"] == 2500


def test_fallback_model_gets_the_same_cap(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-a")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "claude-b")
    m = L._real_chat_model()
    assert isinstance(m, L.FallbackChatModel)
    assert m.primary.max_tokens == 2500 and m.fallback.max_tokens == 2500


def test_claude_cli_passes_cap_through_subprocess_env(monkeypatch):
    seen: list[dict] = []

    def run(cmd, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok", "usage": {}}', stderr="")

    monkeypatch.setattr(C.subprocess, "run", run)
    m = L._provider_model("claude_cli", "", None)
    assert m.max_output_tokens == 2500
    m.cli_path = "claude-fake"
    m.invoke(MSGS)
    assert seen[0]["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "2500"


def test_response_cache_key_changes_with_the_cap(monkeypatch):
    a = L.CachingChatModel(inner=L._provider_model("anthropic", "", "k"))
    monkeypatch.setenv("LLM_MAX_TOKENS", "1000")
    b = L.CachingChatModel(inner=L._provider_model("anthropic", "", "k"))
    assert a._cache_key(MSGS, None, {}) != b._cache_key(MSGS, None, {})


def test_task_cap_raises_only_the_eval_single_reviewer(monkeypatch):
    """평가 전용 단일 검토자(`[[task:single]]`, /admin/eval/review)만 4000. 다른 단계(사용자 경로)는 LLM_MAX_TOKENS 그대로."""
    assert L.TASK_MAX_TOKENS == {"single": 4000}
    assert L.task_max_tokens("single") == 4000
    assert L.task_max_tokens("answer") == 2500 and L.task_max_tokens("supervisor") == 2500 and L.task_max_tokens("team_security") == 2500
    monkeypatch.setenv("LLM_MAX_TOKENS", "6000")
    assert L.task_max_tokens("single") == 6000                  # 전체 상한을 더 크게 주면 그 값(줄이지 않는다)
    monkeypatch.setenv("LLM_MAX_TOKENS", "1500")
    assert L.task_max_tokens("single") == 4000 and L.task_max_tokens("answer") == 1500


def test_call_argument_overrides_cap_for_that_call_only():
    m = L._provider_model("anthropic", "", "dummy-not-a-real-key")
    assert m._get_request_payload(MSGS, max_tokens=4000)["max_tokens"] == 4000
    assert m._get_request_payload(MSGS)["max_tokens"] == 2500
    o = L._provider_model("openai", "gpt-x", "dummy-not-a-real-key")
    assert o._get_request_payload(MSGS, max_tokens=4000)["max_completion_tokens"] == 4000


def test_claude_cli_call_argument_overrides_cap_for_that_call_only(monkeypatch):
    seen: list[dict] = []

    def run(cmd, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok", "usage": {}}', stderr="")

    monkeypatch.setattr(C.subprocess, "run", run)
    m = L._provider_model("claude_cli", "", None)
    m.cli_path = "claude-fake"
    m.invoke(MSGS, max_tokens=4000)
    m.invoke(MSGS)
    assert [s["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] for s in seen] == ["4000", "2500"]
    assert m.max_output_tokens == 2500


def test_single_reviewer_sends_4000_and_team_reviewers_do_not():
    """single_review._single_call은 호출 인자로 max_tokens=4000을 준다. 합동 검토 팀 호출(사용자 경로)은 인자를 주지 않는다."""
    from backend.graph.departments import single_review as S

    calls: list[dict] = []

    class Rec:
        def invoke(self, messages, *a, **k):
            calls.append(k)
            from langchain_core.messages import AIMessage
            return AIMessage('{"missing": [], "issues": []}')

    results: dict = {}
    S._single_call(Rec(), None, S.SINGLE_SYSTEM, "요청", [], {}, results)
    assert calls and calls[0].get("max_tokens") == 4000
