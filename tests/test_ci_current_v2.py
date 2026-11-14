"""0원 시험: 현재 코드 평가(evals/ci_current_eval.py, ci_compare.py --current)가 데모 질문 9개에 더해 평가셋 v2 50건 녹화도 다루는가.

실제 녹화(키 필요)는 사용자가 저장소 밖 실행기 step_record.ps1로 만든다. 여기서는 가짜 모델·가짜 녹화·가짜 결과 파일만 쓴다(LLM·Voyage·Postgres·운영 호출 없음).
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.services import demo_record
from backend.services import demo_replay as dr
from evals import ci_compare
from evals import ci_current_eval as cce


# ---------------------------------------------------------------- 질문 목록
def test_v2_questions_follow_the_frozen_dataset_with_normalized_as_of():
    items = cce.v2_questions()
    assert len(items) == 50 and len({it["id"] for it in items}) == 50
    assert {it["kind"] for it in items} == {"relevant", "irrelevant"}
    assert all(it["question"] and (it["as_of"] is None or len(it["as_of"]) == 10) for it in items)   # 2023-05 같은 달 값은 그 달 마지막 날로
    assert cce.normalize_as_of("2023-05") == "2023-05-31" and cce.normalize_as_of("2026-10-27") == "2026-10-27" and cce.normalize_as_of(None) is None


def test_export_questions_writes_demo_and_v2_questions_in_demo_record_format(tmp_path):
    out = tmp_path / "q.jsonl"
    assert cce.main(["--export-questions", str(out)]) == 0
    rows = demo_record.load_questions(out)
    demo = demo_record.load_questions(cce.REPLAY_DIR / "questions.txt")
    assert len(rows) == len(demo) + 50                                     # 같은 질문이어도 기준일이 다르면 따로 녹화한다(데모는 기준일 없음)
    assert len({(r["question"], r["as_of"]) for r in rows}) == len(rows)
    by_q = {(r["question"], r["as_of"]) for r in rows}
    for it in cce.v2_questions():
        assert (it["question"], it["as_of"]) in by_q
    for q in demo:
        assert (q["question"], None) in by_q


# ---------------------------------------------------------------- 녹화 manifest
def _dataset(tmp_path, n=5):
    p = tmp_path / "dataset_v2.jsonl"
    p.write_text("".join(json.dumps({"id": i, "input": f"질문 {i}", "kind": "relevant" if i % 2 else "irrelevant", "as_of": "2026-10-27" if i != 3 else "2023-05"}, ensure_ascii=False) + "\n"
                         for i in range(1, n + 1)), encoding="utf-8")
    return p


def _report(items, **extra):
    return {"recorded": [{"question": it["question"], "as_of": it["as_of"]} for it in items], "total_cost_usd": 0.12, **extra}


def test_manifest_lists_only_recorded_v2_questions_and_is_read_back(tmp_path):
    ds = _dataset(tmp_path)
    items = cce.v2_questions(ds)
    partial = _report(items[:3] + [{"question": "데모 질문 하나", "as_of": None}])          # 데모 질문과 모르는 질문은 manifest에 들어가지 않는다
    manifest = cce.build_v2_manifest(partial, ds)
    assert manifest["ids"] == [1, 2, 3] and manifest["n"] == 3
    path = tmp_path / "v2_recorded.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    got, problem = cce.load_v2_selection(path, ds)
    assert problem is None and [g["id"] for g in got] == [1, 2, 3]
    assert got[2]["as_of"] == "2023-05-31"


def test_without_a_manifest_only_the_nine_demo_questions_run(tmp_path):
    assert cce.load_v2_selection(tmp_path / "none.json", _dataset(tmp_path)) == ([], None)


def test_manifest_is_rejected_when_the_dataset_changed_after_recording(tmp_path):
    ds = _dataset(tmp_path)
    path = tmp_path / "v2_recorded.json"
    path.write_text(json.dumps(cce.build_v2_manifest(_report(cce.v2_questions(ds)), ds)), encoding="utf-8")
    text = ds.read_text(encoding="utf-8")
    ds.write_text(text.replace("질문 2", "질문 둘"), encoding="utf-8")                  # 질문 글이 바뀜
    items, problem = cce.load_v2_selection(path, ds)
    assert items == [] and problem and "해시" in problem
    ds.write_text("\n".join(text.splitlines()[:3]) + "\n", encoding="utf-8")            # 문항이 줄어듦
    items, problem = cce.load_v2_selection(path, ds)
    assert items == [] and problem and "없다" in problem


def test_write_manifest_cli_from_a_demo_record_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report(cce.v2_questions()[:7])), encoding="utf-8")
    out = tmp_path / "v2_recorded.json"
    assert cce.main(["--write-v2-manifest", str(report), "--manifest-out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["n"] == 7
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"recorded": []}), encoding="utf-8")
    assert cce.main(["--write-v2-manifest", str(empty), "--manifest-out", str(tmp_path / "x.json")]) == 1   # 녹화된 v2 질문이 하나도 없으면 manifest를 성공으로 치지 않는다


# ---------------------------------------------------------------- 요약
def _row(set_, kind, citations=0, missed=0, fake=False, expected=None, id_=None, q="q"):
    return {"set": set_, "id": id_, "expected": expected, "question": q, "kind": kind, "citations": citations, "missed_calls": missed, "missed_roles": [], "fake_answer": fake}


def test_demo_summary_ignores_v2_rows_and_v2_summary_counts_by_expected_kind():
    answers, refusals = ["a"], ["r"]
    rows = [_row("demo", "answer", 2, q="a"), _row("demo", "refuse", q="r"),
            _row("v2", "answer", 1, expected="relevant", id_=1, q="a"),             # 데모 질문과 같은 글이어도 v2 줄은 데모 지표에 들지 않는다
            _row("v2", "refuse", expected="relevant", id_=2, q="x"),
            _row("v2", "refuse", expected="irrelevant", id_=3, q="y"),
            _row("v2", "answer", 1, expected="irrelevant", id_=4, q="z", missed=2, fake=True)]
    s = cce.summarize(rows, answers, refusals)
    assert (s["n_questions"], s["answers_ok"], s["refusals_ok"], s["missed_calls"], s["fake_answers"]) == (2, 1, 1, 0, 0)
    v = cce.summarize_v2(rows)
    assert v["n_questions"] == 4 and v["relevant_total"] == 2 and v["relevant_answered"] == 1
    assert v["irrelevant_total"] == 2 and v["irrelevant_refused"] == 1
    assert v["missed_calls"] == 2 and v["fake_answers"] == 1 and v["stale_questions"] == ["#4"]
    assert v["kinds"] == {"answer": 2, "refuse": 2}


# ---------------------------------------------------------------- ci_compare --current 의 50건 비교
DEMO_BASE = {"n_questions": 9, "answers_ok": 6, "refusals_ok": 3, "missed_calls": 0, "fake_answers": 0}
V2_BASE = {"n_questions": 50, "relevant_answered": 24, "irrelevant_refused": 25, "missed_calls": 0, "fake_answers": 0}


def _result(v2=None, problem=None):
    body = {"summary": {**DEMO_BASE, "stale_questions": []}, "rows": []}
    if v2 is not None:
        body["v2"] = {**V2_BASE, "stale_questions": [], **v2}
    return {"meta": {"commit": "abc1234", "v2_problem": problem}, "paths": {"reasoning_answer_in_time": body, "reasoning_answer_skipped": body}}


def _eval(result, with_v2_base):
    cur = {"metrics": DEMO_BASE, **({"v2_metrics": V2_BASE} if with_v2_base else {})}
    rows, failures = ci_compare.evaluate_current(result, {"current": cur})
    return rows, failures


def test_nine_only_result_and_nine_only_baseline_pass_as_before():
    rows, failures = _eval(_result(), with_v2_base=False)
    assert failures == [] and not any(r["label"].startswith("50건") for r in rows)


def test_v2_result_equal_to_the_v2_baseline_passes_and_adds_rows():
    rows, failures = _eval(_result(v2={}), with_v2_base=True)
    assert failures == [] and sum(1 for r in rows if r["label"].startswith("50건")) == 8


@pytest.mark.parametrize("key,value", [("relevant_answered", 23), ("irrelevant_refused", 24), ("missed_calls", 3), ("fake_answers", 1), ("n_questions", 49)])
def test_v2_result_fails_when_it_is_worse_than_the_v2_baseline(key, value):
    _, failures = _eval(_result(v2={key: value}), with_v2_base=True)
    assert failures, key


def test_v2_result_without_a_v2_baseline_fails_and_so_does_a_missing_v2_result_with_a_baseline():
    _, failures = _eval(_result(v2={}), with_v2_base=False)
    assert any("v2_metrics가 없다" in f for f in failures)
    _, failures = _eval(_result(), with_v2_base=True)
    assert any("50건 평가 결과가 없다" in f for f in failures)
    _, failures = _eval(_result(problem="질문 해시 불일치"), with_v2_base=True)
    assert any("질문 해시 불일치" in f for f in failures)


def test_compare_main_with_a_v2_result_file(tmp_path, monkeypatch):
    """파일을 거치는 전체 경로(ci_compare.main --current)도 50건 기준을 읽는다."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    base = json.loads(ci_compare.BASELINE.read_text(encoding="utf-8"))
    # 이 시험이 실제 기준 파일의 9개 기준과 같은 값을 쓰는지 고정한다(기준 파일을 고치면 이 시험도 보게 된다)
    assert base["current"]["metrics"] == DEMO_BASE
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({**base, "current": {**base["current"], "v2_metrics": V2_BASE}}), encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(json.dumps(_result(v2={})), encoding="utf-8")
    args = ["--baseline", str(baseline), "--current", str(result)]
    # 나머지(운영·옛 측정) 비교는 실제 저장소 파일이라 통과 상태여야 한다
    assert ci_compare.main(args) == 0
    result.write_text(json.dumps(_result(v2={"fake_answers": 2})), encoding="utf-8")
    assert ci_compare.main(args) == 1


# ---------------------------------------------------------------- 가짜 녹화: 녹화 CLI 로직(전체 비용 상한)과 재생
class FakeModel:
    model = "fake-haiku"

    def invoke(self, messages, stop=None, **kw):
        return AIMessage(content=json.dumps({"q": messages[-1].content[:30]}, ensure_ascii=False))


class FakeRecordingGraph:
    """질문마다 가짜 모델을 녹화 래퍼로 한 번 부르고(녹화 한 줄), 질문당 일정 비용을 쓴 것으로 센다."""

    def __init__(self, store, per_question_usd, fail_on=()):
        self.model = dr.RecordingChatModel(inner=FakeModel(), model_name="fake", store=store)
        self.per_q, self.fail_on, self.spent = per_question_usd, set(fail_on), []

    def invoke(self, state, cfg):
        if state["question"] in self.fail_on:
            raise RuntimeError("fake failure")
        self.model.invoke([SystemMessage(content="[[task:answer]]\n규칙"), HumanMessage(content=state["question"])])
        self.spent.append(self.per_q)
        return {}


@pytest.fixture()
def fake_record(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(tmp_path / "rec"))
    dr._stores.pop(str(tmp_path / "rec"), None)
    store = dr.ReplayStore(tmp_path / "rec")
    monkeypatch.setitem(dr._stores, str(tmp_path / "rec"), store)
    state = {"graph": None, "n": 0}

    import backend.services.llm as llm

    def fake_finish_run(cfg):
        g = state["graph"]
        cost = g.spent[state["n"]] if g and state["n"] < len(g.spent) else 0.0
        state["n"] = len(g.spent) if g else 0
        return {"cost_usd": cost}

    monkeypatch.setattr(llm, "finish_run", fake_finish_run)
    return tmp_path / "rec", store, state


def test_record_questions_stops_at_the_total_cost_cap_and_reports_what_was_recorded(fake_record):
    rec, store, state = fake_record
    questions = [{"question": f"질문 {i}", "as_of": "2026-10-27"} for i in range(1, 8)]
    graph = state["graph"] = FakeRecordingGraph(store, 0.1)
    rep = demo_record.record_questions(questions, graph=graph, max_total_usd=0.35)
    assert rep["ok"] == 4 and rep["failed"] == 0                    # 0.1 x 4 = 0.4 >= 0.35 에서 멈춘다(다음 질문부터 안 돌림)
    assert rep["stopped_by_cap"] is True and rep["skipped"] == ["질문 5", "질문 6", "질문 7"]
    assert rep["total_cost_usd"] == pytest.approx(0.4) and [r["question"] for r in rep["recorded"]] == ["질문 1", "질문 2", "질문 3", "질문 4"]
    assert rep["new_recordings"] == 4


def test_record_questions_without_a_cap_records_everything_and_keeps_failures_out_of_recorded(fake_record):
    rec, store, state = fake_record
    questions = [{"question": f"질문 {i}", "as_of": None} for i in range(1, 5)]
    graph = state["graph"] = FakeRecordingGraph(store, 0.1, fail_on={"질문 2"})
    rep = demo_record.record_questions(questions, graph=graph)
    assert rep["ok"] == 3 and rep["failed"] == 1 and rep["stopped_by_cap"] is False and rep["skipped"] == []
    assert [r["question"] for r in rep["recorded"]] == ["질문 1", "질문 3", "질문 4"]


def test_fake_recording_round_trip_manifest_and_replay(fake_record, tmp_path):
    """가짜 녹화 -> 보고서 -> manifest -> 재생: manifest가 가리킨 질문마다 녹화 응답이 재생에서 나오고, 녹화 못 한 질문은 manifest에 없다."""
    rec, store, state = fake_record
    ds = _dataset(tmp_path, n=6)
    items = cce.v2_questions(ds)
    graph = state["graph"] = FakeRecordingGraph(store, 0.1)
    rep = demo_record.record_questions([{"question": it["question"], "as_of": it["as_of"]} for it in items], graph=graph, max_total_usd=0.45)
    assert rep["stopped_by_cap"] and rep["ok"] == 5                  # 0.1 x 5 >= 0.45 에서 멈춘다
    manifest_path = tmp_path / "v2_recorded.json"
    manifest_path.write_text(json.dumps(cce.build_v2_manifest(rep, ds)), encoding="utf-8")
    selected, problem = cce.load_v2_selection(manifest_path, ds)
    assert problem is None and [s["id"] for s in selected] == [1, 2, 3, 4, 5]
    replay = dr.ReplayChatModel(store=dr.ReplayStore(rec))
    for s in selected:
        assert json.loads(replay.invoke([SystemMessage(content="[[task:answer]]\n규칙"), HumanMessage(content=s["question"])]).content)["q"].startswith("질문")
    assert replay.misses == 0 and replay.hits == 5
    replay.invoke([SystemMessage(content="[[task:answer]]\n규칙"), HumanMessage(content="질문 6")])   # 녹화 못 한 6번은 재생에서도 없다(가짜 응답으로 내려감)
    assert replay.misses == 1
