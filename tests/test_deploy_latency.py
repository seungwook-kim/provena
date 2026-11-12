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


# ---------- 서버가 done에 실은 단계별 비용·Voyage·거절 칸(backend/api/routes.py)을 행에 저장 ----------

STEP_DONE = {"kind": "answer", "usage": {"cost_usd": 0.0007, "input_tokens": 4500, "output_tokens": 430, "calls": 4},
             "cost_by_step": {"judge/judge": {"calls": 2, "input_tokens": 2000, "output_tokens": 200, "cost_usd": 0.0003, "llm_s": 1.5},
                              "write_answer/answer": {"calls": 1, "input_tokens": 3000, "output_tokens": 300, "cost_usd": 0.0004, "llm_s": 2.0}},
             "cost_by_step_total_usd": 0.0007, "embed_tokens": 13, "embed_calls": 1, "embed_cost_usd": 7.8e-07}


def test_stream_saves_server_step_fields_and_keeps_existing_columns():
    clock = Clock([0.0, 1.0])
    got = dl.consume_chat_stream(sse("done", STEP_DONE), t0=clock(), clock=clock)
    assert got["cost_usd"] == 0.0007 and got["input_tokens"] == 4500 and got["llm_calls"] == 4 and got["result"] == "answer"
    assert got["cost_by_step"]["judge/judge"]["calls"] == 2 and got["embed_tokens"] == 13 and got["embed_cost_usd"] == 7.8e-07
    assert got["refuse_stage"] is None and got["refuse_reason"] is None
    refused = dl.consume_chat_stream(sse("done", {"kind": "refuse", "code": "no_results", "usage": {}, "refuse_stage": "give_up", "refuse_reason": "no_evidence"}),
                                     t0=0.0, clock=Clock([0.0, 1.0]))
    assert (refused["refuse_stage"], refused["refuse_reason"]) == ("give_up", "no_evidence")
    old = dl.consume_chat_stream(sse("done", {"kind": "answer", "usage": {"cost_usd": 0.001}}), t0=0.0, clock=Clock([0.0, 1.0]))
    assert all(old[k] is None for k in dl.STEP_FIELDS)     # 옛 서버: 칸이 없으면 None


def test_summary_adds_per_step_totals_only_from_rows_that_have_them():
    ok = dl.consume_chat_stream(sse("done", STEP_DONE), t0=0.0, clock=Clock([0.0, 1.0]))
    refused = dl.consume_chat_stream(sse("done", {"kind": "refuse", "usage": {"cost_usd": 0.0002}, "refuse_stage": "give_up", "refuse_reason": "no_evidence",
                                                  "cost_by_step": {"judge/judge": {"calls": 1, "input_tokens": 1000, "output_tokens": 100, "cost_usd": 0.0001, "llm_s": 0.5}},
                                                  "embed_tokens": 0, "embed_calls": 0, "embed_cost_usd": 0.0}), t0=0.0, clock=Clock([0.0, 1.0]))
    old = dl.consume_chat_stream(sse("done", {"kind": "answer", "usage": {"cost_usd": 0.001}}), t0=0.0, clock=Clock([0.0, 1.0]))
    s = dl.summarize_rows([ok, refused, old])
    assert s["step_rows"] == 2 and s["cost_by_step"]["judge/judge"]["calls"] == 3 and s["cost_by_step"]["judge/judge"]["calls_per_question"] == 1.5
    assert s["cost_by_step"]["judge/judge"]["cost_usd"] == pytest.approx(0.0004) and s["cost_by_step"]["write_answer/answer"]["rows"] == 1
    assert s["embed_rows"] == 2 and s["embed_tokens_sum"] == 13 and s["refuse_stage_reason"] == {"give_up/no_evidence": 1}
    assert dl.summarize_rows([old])["step_rows"] == 0 and dl.summarize_rows([old])["cost_by_step"] == {}
    summary = {"meta": {"n_questions": 3, "base_url": "x"}, "per_run": [{"run": 1, **s}], "all_runs": s, "relevant_only": s, "irrelevant_only": s}
    md = dl.render_markdown(summary)
    assert "## 단계별 비용" in md and "judge/judge" in md and "Voyage 임베딩: 토큰 합 13" in md and "give_up/no_evidence 1건" in md


def kind_row(run, i, total, kind, result="answer", status="ok"):
    """`dataset_kind`가 있는 행(deploy_latency가 저장하는 모양). 거절 기대 칸은 일부러 종류와 맞추지 않는 값으로 두어 `dataset_kind`를 읽는지 본다."""
    return {"run": run, "id": i, "status": status, "first_token_s": 0.1, "total_s": total if status == "ok" else None, "result": result,
            "citations": 1, "cost_usd": 0.01, "dataset_kind": kind, "expect_refusal": False}


def test_summary_has_p50_and_p95_per_dataset_kind_overall_and_per_run():
    runs = {
        1: [kind_row(1, i, float(i), "relevant") for i in range(1, 11)] + [kind_row(1, 100 + i, 2.0 * i, "irrelevant", result="refuse") for i in range(1, 5)],
        2: [kind_row(2, i, 10.0 + i, "relevant") for i in range(1, 11)] + [kind_row(2, 100 + i, 1.0, "irrelevant", result="refuse") for i in range(1, 5)]
        + [kind_row(2, 999, 0, "relevant", status="timeout")],
    }
    s = dl.build_summary(runs, {"n_questions": 14, "base_url": "https://x", "revision": "r", "commit": "c", "timeout_s": 120, "started_at": "a", "finished_at": "b"})
    k = s["by_dataset_kind"]
    rel, irr = k["relevant"], k["irrelevant"]
    # 관련 전체: 1~10와 11~20 (20개, 실패 1행은 뺀다). p50 = 10번째 값 10.0, p95 = 19번째 값 19.0 (가장 가까운 순위)
    assert (rel["all_runs"]["n"], rel["all_runs"]["n_ok"]) == (21, 20)
    assert rel["all_runs"]["total_s"]["p50"] == 10.0 and rel["all_runs"]["total_s"]["p95"] == 19.0 and rel["all_runs"]["total_s"]["max"] == 20.0
    assert [(p["run"], p["total_s"]["p50"], p["total_s"]["p95"]) for p in rel["per_run"]] == [(1, 5.0, 10.0), (2, 15.0, 20.0)]
    # 비관련: 회차 1은 2,4,6,8초 / 회차 2는 모두 1초
    assert [(p["run"], p["total_s"]["p50"], p["total_s"]["p95"]) for p in irr["per_run"]] == [(1, 4.0, 8.0), (2, 1.0, 1.0)]
    assert irr["all_runs"]["total_s"]["p50"] == 1.0 and irr["all_runs"]["total_s"]["p95"] == 8.0
    # 답을 낸 문항만: 비관련은 모두 거절이라 비어 있다. 관련은 전체와 같다
    assert irr["all_runs"]["answered_total_s"]["p95"] is None and rel["all_runs"]["answered_total_s"]["p95"] == 19.0
    # 같은 계산 함수(percentile)와 같은 값
    assert rel["all_runs"]["total_s"]["p95"] == dl.percentile([float(i) for i in range(1, 11)] + [10.0 + i for i in range(1, 11)], 95)


def test_dataset_kind_falls_back_to_expect_refusal_for_old_rows_and_existing_summary_keys_stay():
    old = row(1, 1, 3.0, result="refuse", refusal=True)         # `dataset_kind` 칸이 없는 옛 행
    assert "dataset_kind" not in old and dl.row_kind(old) == "irrelevant" and dl.row_kind(row(1, 2, 1.0)) == "relevant"
    s = dl.build_summary({1: [old, row(1, 2, 1.0)]}, {"n_questions": 2, "base_url": "u", "revision": "r", "commit": "c", "timeout_s": 1, "started_at": "a", "finished_at": "b"})
    assert s["by_dataset_kind"]["irrelevant"]["all_runs"]["n"] == 1 and s["by_dataset_kind"]["relevant"]["all_runs"]["n"] == 1
    assert s["relevant_only"]["n"] == 1 and s["irrelevant_only"]["n"] == 1 and set(s) >= {"meta", "per_run", "all_runs", "relevant_only", "irrelevant_only"}


def test_markdown_lists_the_p50_and_p95_of_each_kind_for_every_run_and_overall(tmp_path):
    runs = {1: [kind_row(1, i, float(i), "relevant") for i in range(1, 5)] + [kind_row(1, 9, 7.0, "irrelevant", result="refuse")],
            2: [kind_row(2, i, float(i) + 1, "relevant") for i in range(1, 5)] + [kind_row(2, 9, 3.0, "irrelevant", result="refuse")]}
    meta = {"n_questions": 5, "base_url": "https://x", "revision": "r", "commit": "c", "timeout_s": 120, "started_at": "a", "finished_at": "b"}
    dl.write_outputs(tmp_path, runs, meta)
    md = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "## 관련·비관련 문항별 시간" in md
    lines = [ln for ln in md.splitlines() if ln.startswith("| 관련 |") or ln.startswith("| 비관련 |")]
    assert [ln.split("|")[1:3] for ln in lines] == [[" 관련 ", " 1회차 "], [" 관련 ", " 2회차 "], [" 관련 ", " 전체 "],
                                                     [" 비관련 ", " 1회차 "], [" 비관련 ", " 2회차 "], [" 비관련 ", " 전체 "]]
    irr_all = lines[-1].split("|")
    assert irr_all[3].strip() == "2/2" and irr_all[4].strip() == "3.000" and irr_all[5].strip() == "7.000"       # 성공/전체, p50, p95
    import json

    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved["by_dataset_kind"]["relevant"]["all_runs"]["total_s"]["p95"] == 5.0


def test_stream_keeps_the_thread_id_sent_in_every_event():
    """행에 대화 id를 남긴다: 운영 Langfuse sessionId(`<user_id>:<thread_id>`)와 정확히 짝짓는 열쇠. 이벤트 바깥 칸 thread_id에서 읽는다."""
    lines = sse("token", {"text": "a"}) + sse("done", {"kind": "answer", "usage": {}})
    got = dl.consume_chat_stream(lines, t0=0.0, clock=lambda: 1.0)
    assert got["thread_id"] == "t-x" and got["status"] == "ok"
    assert dl.consume_chat_stream([], t0=0.0, clock=lambda: 1.0)["thread_id"] is None
