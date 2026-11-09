"""시작 준비(검색 준비를 기다림, LLM 모듈 미리 올림)와 지연 로그 수준 시험. 키·DB·네트워크 없이 돈다."""
from __future__ import annotations

import logging
import sys
import threading
import time

import pytest

pytest.importorskip("fastapi")

from api_test_support import Env  # noqa: E402

from backend import main  # noqa: E402
import backend.rag.retrieve.search  # noqa: E402,F401

search_mod = sys.modules["backend.rag.retrieve.search"]   # 패키지의 search 는 계약 함수


class FakeSearcher:
    def search(self, q):
        return []


@pytest.fixture
def warm_calls(monkeypatch):
    """`warmup`을 세는 가짜로 바꾼다. 불리면 `_searcher`를 채우므로 뒤의 `search()`는 다시 준비하지 않는다."""
    calls: list[float] = []
    monkeypatch.setattr(search_mod, "_searcher", None)

    def fake_warmup():
        calls.append(time.monotonic())
        search_mod._searcher = FakeSearcher()
        return search_mod._searcher

    monkeypatch.setattr(search_mod, "warmup", fake_warmup)
    return calls


def test_sync_warmup_runs_at_startup_and_first_search_does_not_warm_again(monkeypatch, warm_calls):
    with Env(monkeypatch) as env:
        pass
    assert warm_calls == []                      # 기본값은 끔(시험이 그래프를 꽂은 앱)

    env = Env(monkeypatch)
    monkeypatch.setenv("SEARCH_WARMUP", "1")
    with env:
        assert len(warm_calls) == 1              # 시작이 끝났을 때 이미 준비돼 있다(기다렸다)
        search_mod.search(object())              # 첫 검색
        search_mod.search(object())
        assert len(warm_calls) == 1              # 첫 요청이 준비를 다시 하지 않는다
        assert env.client().get("/health").status_code == 200


def test_startup_waits_for_a_slow_warmup(monkeypatch):
    done = []
    monkeypatch.setattr(search_mod, "_searcher", None)

    def slow():
        time.sleep(0.3)
        done.append(1)
        return FakeSearcher()

    monkeypatch.setattr(search_mod, "warmup", slow)
    env = Env(monkeypatch)
    monkeypatch.setenv("SEARCH_WARMUP", "1")
    with env:
        assert done == [1]                       # 끝나기 전에 시작을 마치지 않는다


def test_warmup_failure_does_not_stop_startup(monkeypatch, caplog):
    def broken():
        raise RuntimeError("색인이 준비되지 않았다")

    monkeypatch.setattr(search_mod, "warmup", broken)
    env = Env(monkeypatch)
    monkeypatch.setenv("SEARCH_WARMUP", "1")
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        with env:
            assert env.client().get("/health").status_code == 200
    assert any(r.levelno == logging.WARNING and "stage=search_warmup" in r.getMessage() for r in caplog.records)


def test_unexpected_warmup_error_logs_only_the_kind(monkeypatch, caplog):
    def broken():
        raise OSError("postgresql://user:secret@host/db 연결 실패")

    monkeypatch.setattr(search_mod, "warmup", broken)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        assert main.run_startup_warmup(preload_llm=False, timeout=5) is False
    assert "OSError" in caplog.text and "secret" not in caplog.text


def test_warmup_timeout_lets_startup_continue(monkeypatch, caplog):
    release = threading.Event()
    monkeypatch.setattr(search_mod, "warmup", lambda: release.wait(5) or FakeSearcher())
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        assert main.run_startup_warmup(preload_llm=False, timeout=0.2) is False
    release.set()
    assert time.monotonic() - started < 2
    assert "stage=startup_warmup" in caplog.text


def test_demo_modes_skip_the_default_warmup(monkeypatch, warm_calls):
    # 로컬 데모(PROVENA_ENV=local, PROVENA_DEV_MODE=1)
    for key in ("DATABASE_URL", "PROVENA_ENV", "PROVENA_DEV_MODE", "DEMO_MODE", "LLM_API_KEY", "SEARCH_WARMUP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-used")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is True     # 운영 모양
    monkeypatch.setenv("PROVENA_ENV", "local")
    monkeypatch.setenv("PROVENA_DEV_MODE", "1")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False    # 로컬 데모
    monkeypatch.delenv("PROVENA_DEV_MODE")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False    # PROVENA_ENV=local
    monkeypatch.setenv("PROVENA_ENV", "demo")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False
    monkeypatch.delenv("PROVENA_ENV")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False    # 키가 있어도 데모 지정
    monkeypatch.delenv("DEMO_MODE")
    monkeypatch.delenv("LLM_API_KEY")
    assert main.search_warmup_default_on(has_db=True, graph_injected=False) is False    # 키 없는 데모
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-used")
    assert main.search_warmup_default_on(has_db=False, graph_injected=False) is False   # DB 없음
    assert main.search_warmup_default_on(has_db=True, graph_injected=True) is False     # 시험이 그래프를 꽂음

    # 앱을 실제로 띄워도 데모는 준비를 부르지 않는다
    env = Env(monkeypatch)
    monkeypatch.setenv("PROVENA_ENV", "local")
    with env:
        pass
    assert warm_calls == []


def test_search_warmup_env_values(monkeypatch):
    monkeypatch.delenv("SEARCH_WARMUP", raising=False)
    assert main.search_warmup_mode(default_on=True) == "sync"
    assert main.search_warmup_mode(default_on=False) == "off"
    for value, expected in (("1", "sync"), ("true", "sync"), ("0", "off"), ("off", "off"), ("background", "background")):
        monkeypatch.setenv("SEARCH_WARMUP", value)
        assert main.search_warmup_mode(default_on=value == "0") == expected     # 켜고 끄는 값은 기본값을 이긴다
    monkeypatch.setenv("SEARCH_WARMUP", "banana")
    assert main.search_warmup_mode(default_on=True) == "off"                    # 모르는 값은 건너뛴다


def test_background_mode_does_not_block_startup(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(search_mod, "warmup", lambda: release.wait(5) or FakeSearcher())
    started = time.monotonic()
    t = main.start_search_warmup()
    assert time.monotonic() - started < 1 and t.is_alive()
    release.set()
    t.join(5)
    assert not t.is_alive()


def test_startup_warmup_preloads_llm_modules_first_and_survives_failure(monkeypatch):
    order = []
    monkeypatch.setattr(search_mod, "warmup", lambda: order.append("search") or FakeSearcher())
    from backend.services import llm

    monkeypatch.setattr(llm, "preload_provider_modules", lambda: order.append("llm") or ["anthropic"])
    assert main.run_startup_warmup(preload_llm=True, timeout=5) is True
    assert order == ["llm", "search"]

    order.clear()

    def broken():
        raise ImportError("없음")

    monkeypatch.setattr(llm, "preload_provider_modules", broken)
    assert main.run_startup_warmup(preload_llm=True, timeout=5) is True          # 못 올려도 검색 준비는 한다
    assert order == ["search"]


@pytest.mark.parametrize("provider,key,demo,expected", [
    ("anthropic", "k", "", ["anthropic", "langchain_anthropic"]),
    ("", "k", "", ["anthropic", "langchain_anthropic"]),                         # 기본 제공자는 anthropic
    ("openrouter", "k", "", ["langchain_openai"]),
    ("openai", "k", "", ["langchain_openai"]),
    ("claude_cli", "", "", []),
    ("anthropic", "k", "1", []),                                                  # 데모는 올릴 것이 없다
    ("anthropic", "", "", []),                                                    # 키 없음 = 데모
])
def test_preload_loads_only_what_the_provider_needs(monkeypatch, provider, key, demo, expected):
    from backend.services import llm

    for name in ("LLM_PROVIDER", "LLM_API_KEY", "DEMO_MODE"):
        monkeypatch.delenv(name, raising=False)
    if provider:
        monkeypatch.setenv("LLM_PROVIDER", provider)
    if key:
        monkeypatch.setenv("LLM_API_KEY", key)
    if demo:
        monkeypatch.setenv("DEMO_MODE", demo)
    loaded = []
    monkeypatch.setattr(llm.importlib, "import_module", lambda name: loaded.append(name))
    monkeypatch.setattr(llm, "_tuned_anthropic", lambda: loaded.append("tuned"))
    assert llm.preload_provider_modules() == expected
    assert [n for n in loaded if n != "tuned"] == expected
    assert ("tuned" in loaded) == (provider in ("anthropic", "") and bool(expected))


def test_app_logging_is_info_and_added_once():
    lg = logging.getLogger("backend")
    before = list(lg.handlers), lg.level
    try:
        lg.setLevel(logging.WARNING)
        for h in list(lg.handlers):
            if getattr(h, "_provena", False):
                lg.removeHandler(h)
        main.configure_app_logging()
        main.configure_app_logging()
        assert lg.level == logging.INFO
        assert lg.isEnabledFor(logging.INFO)
        assert sum(1 for h in lg.handlers if getattr(h, "_provena", False)) <= 1
    finally:
        lg.handlers[:] = before[0]
        lg.setLevel(before[1])


def _post(task=None):
    import httpx

    content = b'{"system": "[[task:%s]] SECRET-PROMPT-TEXT", "messages": []}' % task.encode() if task else b"{}"
    return httpx.Request("POST", "http://fake.invalid/", content=content)


def test_hedge_log_is_warning_without_prompt_content(caplog):
    import httpx

    from backend.services.llm import DeadlineTransport

    calls = []
    lock = threading.Lock()

    class FirstSlow:
        def handle_request(self, request):
            with lock:
                calls.append(1)
                n = len(calls)
            time.sleep(0.6 if n == 1 else 0.01)
            return httpx.Response(200, json={"n": n})

    with caplog.at_level(logging.INFO, logger="backend.services.llm"):
        DeadlineTransport(FirstSlow(), 2.0, hedge=0.1).handle_request(_post("answer"))
    rows = [r for r in caplog.records if r.name == "backend.services.llm"]
    assert len(rows) == 1 and rows[0].levelno == logging.WARNING
    text = rows[0].getMessage()
    assert "request_id=" in text and "stage=answer" in text and "elapsed_s=0.1" in text and "attempt=0" in text
    assert "SECRET-PROMPT-TEXT" not in text and "fake.invalid" not in text


def test_deadline_exceeded_logs_are_warning_with_attempt(caplog):
    import httpx

    from backend.services.llm import DeadlineTransport

    class Slow:
        def handle_request(self, request):
            time.sleep(0.4)
            return httpx.Response(200, json={})

    # 한 요청만 보내는 경로
    with caplog.at_level(logging.INFO, logger="backend.services.llm"):
        with pytest.raises(httpx.ReadTimeout):
            DeadlineTransport(Slow(), 0.1).handle_request(_post("judge"))
    one = [r for r in caplog.records if r.name == "backend.services.llm"]
    assert [r.levelno for r in one] == [logging.WARNING]
    assert "stage=judge" in one[0].getMessage() and "attempt=0" in one[0].getMessage() and "SECRET-PROMPT-TEXT" not in one[0].getMessage()

    # hedge까지 보내고 둘 다 느린 경로: hedge 로그와 상한 초과 로그가 모두 WARNING
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="backend.services.llm"):
        with pytest.raises(httpx.ReadTimeout):
            DeadlineTransport(Slow(), 0.2, hedge=0.05).handle_request(_post("judge"))
    both = [r for r in caplog.records if r.name == "backend.services.llm"]
    assert len(both) == 2 and all(r.levelno == logging.WARNING for r in both)

    # 재시도(SDK가 붙이는 헤더)는 시도 번호가 로그에 남는다
    caplog.clear()
    retry = _post()
    retry.headers["x-stainless-retry-count"] = "2"
    with caplog.at_level(logging.INFO, logger="backend.services.llm"):
        with pytest.raises(httpx.ReadTimeout):
            DeadlineTransport(Slow(), 0.05).handle_request(retry)
    assert "attempt=2" in caplog.text and "stage=-" in caplog.text
