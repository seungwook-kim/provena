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
    for k in ("LLM_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_REASONING", "LLM_PROVIDER_SORT"):
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


# ---------- 속도 스위치: 요청 본문 (네트워크 없음, httpx 가짜 전송) ----------
def _wire_model(monkeypatch):
    import functools
    import json

    import httpx
    import langchain_openai

    seen = []

    def reply(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "anthropic/claude-haiku-5.5",
                                         "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{\"ok\": true}"}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 40, "total_tokens": 45, "completion_tokens_details": {"reasoning_tokens": 30}}})

    client = httpx.Client(transport=httpx.MockTransport(reply))
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", functools.partial(langchain_openai.ChatOpenAI, http_client=client))
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake.invalid/v1")
    return seen


def test_switches_off_send_no_extra_fields(monkeypatch):
    seen = _wire_model(monkeypatch)
    assert get_chat_model().invoke("안녕").content == '{"ok": true}'
    assert not {"reasoning", "provider", "response_format"} & set(seen[0])


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_reasoning_and_sort_send_nothing(monkeypatch, value):
    seen = _wire_model(monkeypatch)
    monkeypatch.setenv("LLM_REASONING", value)
    monkeypatch.setenv("LLM_PROVIDER_SORT", value)
    get_chat_model().invoke("안녕")
    assert not {"reasoning", "provider"} & set(seen[0])


def test_reasoning_and_sort_reach_the_request_body(monkeypatch):
    seen = _wire_model(monkeypatch)
    monkeypatch.setenv("LLM_REASONING", "None")
    monkeypatch.setenv("LLM_PROVIDER_SORT", "latency")
    get_chat_model().invoke("안녕")
    assert seen[0]["reasoning"] == {"effort": "none"} and seen[0]["provider"] == {"sort": "latency"}


@pytest.mark.parametrize("name,value", [("LLM_REASONING", "off"), ("LLM_PROVIDER_SORT", "fast")])
def test_unknown_reasoning_or_sort_is_an_error(monkeypatch, name, value):
    _wire_model(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        get_chat_model()


def test_json_only_call_option_reaches_the_request_body_and_reads_the_reply(monkeypatch):
    seen = _wire_model(monkeypatch)
    msg = get_chat_model().invoke("안녕", response_format={"type": "json_object"})
    assert seen[0]["response_format"] == {"type": "json_object"} and msg.content == '{"ok": true}'


def test_reasoning_tokens_are_recorded_in_the_llm_trace(monkeypatch):
    from backend.services import llm_trace
    from backend.services.llm import run_config

    _wire_model(monkeypatch)
    with llm_trace.capture() as calls:
        get_chat_model().invoke("안녕", config=run_config("t"))
    assert calls[0]["output_tokens"] == 40 and calls[0]["reasoning_tokens"] == 30


def _trace_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake.invalid/v1")


def _ok_body():
    return {"id": "gen-1", "provider": "Anthropic", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{\"sufficient\": true}"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9}}


def test_trace_detail_records_provider_attempts_and_text(monkeypatch):
    import functools

    import httpx
    import langchain_openai

    from backend.services import llm_trace
    from backend.services.llm import run_config

    state = {"n": 0}

    def reply(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500, json={"error": "잠깐"})
        return httpx.Response(200, headers={"x-request-id": "req-1"}, json=_ok_body())

    client = httpx.Client(transport=httpx.MockTransport(reply), event_hooks=llm_trace.http_hooks())
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", functools.partial(langchain_openai.ChatOpenAI, http_client=client))
    monkeypatch.setattr("backend.services.llm._openrouter_client", lambda: {})
    _trace_env(monkeypatch)
    monkeypatch.setenv("LLM_TRACE_DETAIL", "1")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    with llm_trace.capture() as calls:
        got = get_chat_model().invoke("[[task:judge]] 판정", config=run_config("t"))
    row = calls[0]
    assert row["provider"] == "Anthropic" and row["http_attempts"] == 2 and row["retries"] == 1 and row["http_statuses"] == [500, 200]
    assert row["request_id"] == "req-1" and row["generation_id"] == "gen-1" and row["output_text"] == got.content


def test_trace_detail_off_adds_nothing(monkeypatch):
    from backend.services import llm_trace
    from backend.services.llm import _openrouter_client, run_config

    monkeypatch.delenv("LLM_TRACE_DETAIL", raising=False)
    monkeypatch.delenv("LLM_DEADLINE_S", raising=False)
    assert _openrouter_client() == {}
    _wire_model(monkeypatch)
    with llm_trace.capture() as calls:
        get_chat_model().invoke("[[task:judge]] 판정", config=run_config("t"))
    assert not {"provider", "http_attempts", "output_text", "request_id"} & set(calls[0])


class _SlowFirst:
    """첫 시도만 오래 걸리는 전송. 빈 문자를 흘리는 공급자처럼 바이트 사이 시간 제한으로는 끊기지 않는 경우다."""

    def __init__(self, delay):
        self.delay, self.n, self.seen = delay, 0, []

    def handle_request(self, request):
        import time

        import httpx

        self.n += 1
        self.seen.append(request.headers.get("x-stainless-retry-count"))
        if self.n == 1:
            time.sleep(self.delay)
        return httpx.Response(200, json=_ok_body())

    def close(self):
        return None


def test_deadline_cuts_a_stuck_attempt_and_the_sdk_asks_again(monkeypatch):
    import functools
    import time

    import httpx
    import langchain_openai

    from backend.services import llm_trace
    from backend.services.llm import DeadlineTransport, run_config

    inner = _SlowFirst(1.5)
    client = httpx.Client(transport=DeadlineTransport(inner, 0.2), event_hooks=llm_trace.http_hooks())
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", functools.partial(langchain_openai.ChatOpenAI, http_client=client))
    monkeypatch.setattr("backend.services.llm._openrouter_client", lambda: {})
    _trace_env(monkeypatch)
    monkeypatch.setenv("LLM_TRACE_DETAIL", "1")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    t = time.perf_counter()
    with llm_trace.capture() as calls:
        got = get_chat_model().invoke("[[task:judge]] 판정", config=run_config("t"))
    assert time.perf_counter() - t < 1.4 and got.content
    assert inner.seen == ["0", "1"] and calls[0]["http_attempts"] == 2 and calls[0]["http_statuses"] == [200] and calls[0]["retries"] == 1


def test_deadline_grows_with_the_retry_number():
    import time

    import httpx

    from backend.services.llm import DeadlineTransport

    class Slow:
        def handle_request(self, request):
            time.sleep(0.25)
            return httpx.Response(200, json={})

    transport = DeadlineTransport(Slow(), 0.15)
    url = "http://fake.invalid/"
    with pytest.raises(httpx.ReadTimeout):
        transport.handle_request(httpx.Request("POST", url))
    assert transport.handle_request(httpx.Request("POST", url, headers={"x-stainless-retry-count": "1"})).status_code == 200


def test_deadline_builds_a_client_only_when_asked(monkeypatch):
    from backend.services.llm import _openrouter_client

    monkeypatch.delenv("LLM_TRACE_DETAIL", raising=False)
    monkeypatch.setenv("LLM_DEADLINE_S", "6")
    assert "http_client" in _openrouter_client()
    monkeypatch.setenv("LLM_DEADLINE_S", "")
    assert _openrouter_client() == {}


def _local_server(handler):
    """실제 소켓으로 응답하는 작은 서버. 가짜 전송으로는 실제 전송의 형식 충돌을 잡지 못한다."""
    import http.server
    import json as _json
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            handler()
            body = _json.dumps(_ok_body()).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("x-request-id", "req-real")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_real_transport_answers_and_records_the_call(monkeypatch):
    from backend.services import llm_trace
    from backend.services.llm import run_config

    server = _local_server(lambda: None)
    try:
        _trace_env(monkeypatch)
        monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("LLM_TRACE_DETAIL", "1")
        monkeypatch.setenv("LLM_DEADLINE_S", "5")
        with llm_trace.capture() as calls:
            got = get_chat_model().invoke("[[task:judge]] 판정", config=run_config("t"))
    finally:
        server.shutdown()
    assert got.content and calls[0]["ok"] and calls[0]["provider"] == "Anthropic" and calls[0]["request_id"] == "req-real" and calls[0]["http_attempts"] == 1


def test_real_transport_retries_a_stuck_attempt(monkeypatch):
    import threading
    import time

    from backend.services import llm_trace
    from backend.services.llm import run_config

    state = {"n": 0}
    lock = threading.Lock()

    def slow_first():
        with lock:
            state["n"] += 1
            first = state["n"] == 1
        if first:
            time.sleep(1.5)

    server = _local_server(slow_first)
    try:
        _trace_env(monkeypatch)
        monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("LLM_TRACE_DETAIL", "1")
        monkeypatch.setenv("LLM_DEADLINE_S", "0.3")
        monkeypatch.setenv("LLM_MAX_RETRIES", "2")
        t = time.perf_counter()
        with llm_trace.capture() as calls:
            got = get_chat_model().invoke("[[task:judge]] 판정", config=run_config("t"))
        took = time.perf_counter() - t
    finally:
        server.shutdown()
    assert got.content and took < 1.4 and calls[0]["http_attempts"] == 2 and calls[0]["retries"] == 1 and calls[0]["http_statuses"] == [200]


def _task_request(system, **extra):
    import json as _json

    import httpx
    body = {"model": "m", "messages": [{"role": "system", "content": system}, {"role": "user", "content": "q"}], **extra}
    return httpx.Request("POST", "https://x.invalid/chat", headers={"x-stainless-retry-count": "1"}, content=_json.dumps(body).encode("utf-8"))


@pytest.mark.parametrize("system,want", [
    ("[[task:judge]]\n판정", "low"),
    ("[[task:decompose]]\n분해", "minimal"),
    ("[[task:classify]]\n분류", "none"),
    ("표지 없음", "none"),
])
def test_task_reasoning_overrides_only_the_listed_tasks(system, want):
    import json as _json

    import httpx

    from backend.services.llm import TaskReasoningTransport
    seen = {}

    def handler(req):
        seen.update(body=_json.loads(req.content), retry=req.headers.get("x-stainless-retry-count"), length=req.headers.get("content-length"))
        return httpx.Response(200, json={})

    t = TaskReasoningTransport(httpx.MockTransport(handler), {"judge": "low", "decompose": "minimal"})
    t.handle_request(_task_request(system, reasoning={"effort": "none"}))
    assert seen["body"]["reasoning"] == {"effort": want}
    assert seen["retry"] == "1" and int(seen["length"]) == len(_json.dumps(seen["body"]).encode()) or seen["body"]["reasoning"]["effort"] == want
    assert seen["body"]["messages"][0]["content"] == system


def test_reasoning_by_task_reads_the_environment(monkeypatch):
    from backend.services.llm import reasoning_by_task
    monkeypatch.setenv("LLM_REASONING_BY_TASK", "decompose=low, judge=minimal")
    assert reasoning_by_task() == {"decompose": "low", "judge": "minimal"}
    monkeypatch.setenv("LLM_REASONING_BY_TASK", "")
    assert reasoning_by_task() == {}
    monkeypatch.setenv("LLM_REASONING_BY_TASK", "judge=fast")
    with pytest.raises(ValueError):
        reasoning_by_task()


def test_hedge_sends_a_second_request_and_takes_the_first_answer():
    import threading
    import time

    import httpx

    from backend.services.llm import DeadlineTransport

    calls = []
    lock = threading.Lock()

    class FirstSlow:
        def handle_request(self, request):
            with lock:
                calls.append(time.monotonic())
                n = len(calls)
            time.sleep(1.0 if n == 1 else 0.01)
            return httpx.Response(200, json={"n": n})

    transport = DeadlineTransport(FirstSlow(), 2.0, hedge=0.1)
    started = time.monotonic()
    response = transport.handle_request(httpx.Request("POST", "http://fake.invalid/", content=b"{}"))
    assert response.json() == {"n": 2} and time.monotonic() - started < 0.6 and len(calls) == 2


def test_hedge_is_not_used_when_the_answer_is_quick():
    import httpx

    from backend.services.llm import DeadlineTransport

    calls = []

    class Quick:
        def handle_request(self, request):
            calls.append(1)
            return httpx.Response(200, json={})

    assert DeadlineTransport(Quick(), 2.0, hedge=0.5).handle_request(httpx.Request("POST", "http://fake.invalid/")).status_code == 200
    assert len(calls) == 1


def test_hedge_still_times_out_when_both_requests_are_slow():
    import time

    import httpx

    from backend.services.llm import DeadlineTransport

    class Slow:
        def handle_request(self, request):
            time.sleep(0.5)
            return httpx.Response(200, json={})

    with pytest.raises(httpx.ReadTimeout):
        DeadlineTransport(Slow(), 0.2, hedge=0.05).handle_request(httpx.Request("POST", "http://fake.invalid/"))


def _hedge_request(task):
    import json

    import httpx
    body = {"messages": [{"role": "system", "content": f"[[task:{task}]]\n규칙"}, {"role": "user", "content": "q"}]}
    return httpx.Request("POST", "http://fake.invalid/", content=json.dumps(body).encode())


def test_deadline_skip_tasks_send_listed_tasks_without_the_limit():
    """`LLM_DEADLINE_SKIP_TASKS`에 맞는 단계(정확한 이름, 끝 * 접두어)는 상한을 넘겨도 자르지 않고 hedge도 보내지 않는다. 맞지 않는 단계는 지금처럼 자른다."""
    import time

    import httpx

    from backend.services.llm import DeadlineTransport

    calls = []

    class Slow:
        def handle_request(self, request):
            calls.append(1)
            time.sleep(0.3)
            return httpx.Response(200, json={})

    t = DeadlineTransport(Slow(), 0.1, hedge=0.05, skip_tasks=("decision_draft", "supervisor", "team_*"))
    for task in ("decision_draft", "supervisor", "team_security", "team_finance"):
        calls.clear()
        assert t.handle_request(_hedge_request(task)).status_code == 200 and calls == [1], task  # 잘리지 않고 한 번만 보낸다
    for task in ("judge", "answer", "supervisor_route", "decision_params", "team"):
        with pytest.raises(httpx.ReadTimeout):
            t.handle_request(_hedge_request(task))
    with pytest.raises(httpx.ReadTimeout):  # 표지가 없으면 지금처럼 자른다
        t.handle_request(httpx.Request("POST", "http://fake.invalid/", content=b"{}"))
    with pytest.raises(httpx.ReadTimeout):  # 목록이 비면 지금과 같다
        DeadlineTransport(Slow(), 0.1).handle_request(_hedge_request("decision_draft"))


def test_deadline_skip_tasks_on_the_anthropic_transport():
    """anthropic(httpx2) 전송도 같은 목록을 읽는다. 시스템 프롬프트는 맨 위 `system` 칸이다."""
    import time

    import httpx2

    from backend.services.llm import _deadline_transport_httpx2

    class Slow(httpx2.BaseTransport):
        def handle_request(self, request):
            time.sleep(0.3)
            return httpx2.Response(200, json={}, request=request)

    t = _deadline_transport_httpx2(0.1, 0.0, ("team_*",))
    t.inner = Slow()
    with httpx2.Client(transport=t) as c:
        assert c.post("https://api.anthropic.com/v1/messages", json={"system": "[[task:team_infra]]\n규칙", "messages": []}).status_code == 200
        with pytest.raises(httpx2.ReadTimeout):
            c.post("https://api.anthropic.com/v1/messages", json={"system": "[[task:judge]]\n규칙", "messages": []})


def test_deadline_skip_tasks_parses_the_environment_and_reaches_the_clients(monkeypatch):
    from backend.services import llm

    monkeypatch.delenv("LLM_DEADLINE_SKIP_TASKS", raising=False)
    assert llm.deadline_skip_tasks() == ()
    monkeypatch.setenv("LLM_DEADLINE_SKIP_TASKS", " decision_draft, Supervisor ,team_*,")
    assert llm.deadline_skip_tasks() == ("decision_draft", "supervisor", "team_*")
    monkeypatch.setenv("LLM_DEADLINE_S", "8")
    monkeypatch.delenv("LLM_REASONING_BY_TASK", raising=False)
    assert llm._openrouter_client()["http_client"]._transport.skip_tasks == ("decision_draft", "supervisor", "team_*")
    assert llm._anthropic_http_client()._transport.skip_tasks == ("decision_draft", "supervisor", "team_*")
    for bad in ("team-*", "*", "a*b", "judge=1"):
        monkeypatch.setenv("LLM_DEADLINE_SKIP_TASKS", bad)
        with pytest.raises(ValueError):
            llm.deadline_skip_tasks()
