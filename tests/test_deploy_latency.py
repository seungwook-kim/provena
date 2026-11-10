"""배포본 응답 시간 측정 스크립트(`evals/latency/deploy_latency.py`)의 시간·요약 계산 시험. 가짜 SSE 줄과 가짜 시계만 쓰고 네트워크는 쓰지 않는다."""
from __future__ import annotations

import json

import pytest

from evals.latency import deploy_latency as dl


def sse(event: str, data: dict) -> list[str]:
    return [f"event: {event}\r\n", "data: " + json.dumps({"type": event, "thread_id": "t-x", "data": data}) + "\r\n", "\r\n"]


class Clock:
    """읽을 때마다 정해 둔 값을 차례로 돌려주는 시계. 첫 값은 t0다."""

    def __init__(self, ticks: list[float]):
        self.ticks = list(ticks)

    def __call__(self) -> float:
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def test_stream_times_and_fields_are_computed_from_events():
    lines = [": ping\r\n", "\r\n"] + sse("token", {"text": "안녕"}) + sse("token", {"text": "하세요"}) + sse("citation", {"chunk_id": "a"}) + \
        sse("citation", {"chunk_id": "b"}) + sse("done", {"kind": "answer", "usage": {"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.0123, "calls": 5}})
    # 시계 호출 순서: t0, (ping 줄마다 마감 검사)... 이벤트 도착마다 한 번. 줄 검사는 deadline이 없으면 시계를 쓰지 않는다.
    clock = Clock([10.0, 11.5, 12.0, 12.5, 12.5, 14.25, 14.25])
    got = dl.consume_chat_stream(lines, t0=clock(), clock=clock)
    assert got["status"] == "ok" and got["result"] == "answer"
    assert got["first_token_s"] == 1.5 and got["total_s"] == 4.25    # 첫 token 1.5초, done 4.25초
    assert got["citations"] == 2 and got["answer_chars"] == 5
    assert got["cost_usd"] == 0.0123 and got["input_tokens"] == 100 and got["llm_calls"] == 5


def test_stream_keeps_the_answer_text_by_joining_token_texts_exactly():
    """토큰은 공백을 낀 조각이므로 그대로 이으면 답 본문이 된다. RAGAS 채점이 이 값을 읽는다."""
    text = "SEV2는 30분 안에 확인합니다.\n\n- 근거: 온콜 문서 [1]"
    pieces = ["SEV2는 ", "30분 ", "안에 ", "확인합니다.\n\n", "- ", "근거: ", "온콜 ", "문서 ", "[1]"]
    assert "".join(pieces) == text
    lines = [ln for p in pieces for ln in sse("token", {"text": p})] + sse("citation", {"chunk_id": "a"}) + sse("done", {"kind": "answer", "usage": {}})
    got = dl.consume_chat_stream(lines, t0=0.0, clock=Clock([0.0, 1.0]))
    assert got["answer"] == text and got["answer_chars"] == len(text)
    nothing = dl.consume_chat_stream(sse("done", {"kind": "refuse", "usage": {}}), t0=0.0, clock=Clock([0.0, 1.0]))
    assert nothing["answer"] == "" and nothing["answer_chars"] == 0


def test_refusal_without_token_uses_done_time_as_first_response_and_error_event_fails():
    clock = Clock([0.0, 2.0])
    got = dl.consume_chat_stream(sse("done", {"kind": "refuse", "code": "no_results", "usage": {"cost_usd": None}}), t0=clock(), clock=clock)
    assert got["status"] == "ok" and got["result"] == "refuse" and got["first_token_s"] == 2.0 and got["cost_usd"] is None
    clock = Clock([0.0, 3.0])
    err = dl.consume_chat_stream(sse("error", {"code": "limit_exceeded"}), t0=clock(), clock=clock)
    assert err["status"] == "error" and err["error_code"] == "limit_exceeded" and err["total_s"] == 3.0
    clock = Clock([0.0, 1.0])
    cut = dl.consume_chat_stream(sse("token", {"text": "x"}), t0=clock(), clock=clock)   # done 없이 연결이 끝남
    assert cut["status"] == "no_done" and cut["total_s"] is None


def test_deadline_raises_timeout():
    clock = Clock([0.0, 130.0])
    with pytest.raises(dl.AttemptTimeout):
        dl.consume_chat_stream(sse("token", {"text": "x"}), t0=clock(), clock=clock, deadline_s=120.0)


def test_percentile_is_nearest_rank_like_eval_runner():
    values = [float(i) for i in range(1, 51)]
    assert dl.percentile(values, 50) == 25.0 and dl.percentile(values, 95) == 48.0 and dl.percentile([], 95) is None
    assert dl.percentile([7.0], 95) == 7.0


def test_as_of_with_month_only_becomes_last_day():
    assert dl.normalize_as_of("2023-05") == "2023-05-31" and dl.normalize_as_of("2026-10-27") == "2026-10-27"
    assert dl.normalize_as_of("2024-02") == "2024-02-29" and dl.normalize_as_of(None) is None


def row(run, i, total, result="answer", cost=0.01, status="ok", cites=2, refusal=False):
    return {"run": run, "id": i, "status": status, "first_token_s": total - 0.1, "total_s": total if status == "ok" else None, "result": result,
            "citations": cites, "cost_usd": cost, "expect_refusal": refusal}


def test_summary_counts_only_ok_rows_and_sums_cost_per_run_and_overall():
    runs = {1: [row(1, i, float(i)) for i in range(1, 11)] + [row(1, 11, 0, status="timeout", cost=None)],
            2: [row(2, i, 2.0 * i, result="refuse" if i == 3 else "answer", cites=0 if i == 3 else 2, refusal=i == 3) for i in range(1, 11)]}
    s = dl.build_summary(runs, {"n_questions": 11, "base_url": "https://x", "revision": "r", "commit": "c", "timeout_s": 120,
                                "started_at": "a", "finished_at": "b"})
    r1, r2, allr = s["per_run"][0], s["per_run"][1], s["all_runs"]
    assert (r1["n"], r1["n_ok"], r1["n_fail"]) == (11, 10, 1) and r1["failures"] == [{"run": 1, "id": 11, "status": "timeout"}]
    assert r1["total_s"] == {"mean": 5.5, "p50": 5.0, "p95": 10.0, "max": 10.0}
    assert r2["total_s"]["p50"] == 10.0 and r2["total_s"]["p95"] == 20.0 and r2["kinds"] == {"answer": 9, "refuse": 1}
    assert r1["cost_usd_sum"] == 0.1 and r2["cost_usd_sum"] == 0.1 and allr["cost_usd_sum"] == 0.2
    assert allr["n"] == 21 and allr["n_ok"] == 20 and allr["kinds"] == {"answer": 19, "refuse": 1}
    assert s["irrelevant_only"]["n"] == 1 and s["irrelevant_only"]["kinds"] == {"refuse": 1}
    md = dl.render_markdown(s)
    assert "| 1회차 | 10/11 |" in md and "| 2회 합 | 20/21 |" in md and "| 2 | 3 |" not in md and "timeout" in md
    assert "https://x" in md and "리비전 r" in md


def test_ask_retries_once_on_timeout_and_relogs_in_on_401(monkeypatch):
    calls = []
    script = iter([{"status": "http_401"}, {"status": "timeout", "total_s": 120.0}, {"status": "ok", "total_s": 9.0}])

    def fake_once(client, item, **kw):
        calls.append(item["id"])
        return dict(next(script))

    monkeypatch.setattr(dl, "ask_once", fake_once)
    logins = []
    res = dl.ask(None, {"id": 7, "input": "q"}, lambda: logins.append(1) or True, use_as_of=True, timeout_s=120)
    assert res["status"] == "ok" and res["attempts"] == 2 and len(calls) == 3 and logins == [1]   # 401은 시도 횟수에 넣지 않는다

    monkeypatch.setattr(dl, "ask_once", lambda *a, **k: {"status": "network_error:ConnectError", "total_s": 1.0})
    res = dl.ask(None, {"id": 8, "input": "q"}, lambda: True, use_as_of=True, timeout_s=120)
    assert res["status"] == "network_error:ConnectError" and res["attempts"] == 2    # 재시도 1회 뒤 실패로 기록
