"""배포 결과 RAGAS 채점(`evals/latency/deploy_ragas.py`)의 입력 만들기, 요약, 반복, 안전 장치 시험. LLM·임베딩·네트워크는 쓰지 않는다(RAGAS 패키지도 필요 없다)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evals.latency import deploy_ragas as dr

FOOTER = "\n\n기준일 2026-11-10 · 근거 판 날짜 2026-09-13 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)"


def jl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    dataset = [
        {"id": 1, "input": "온콜 확인 기한은?", "kind": "relevant", "expected": "15분", "gold_chunks": []},
        {"id": 2, "input": "점심 메뉴는?", "kind": "irrelevant", "expected": "거절", "gold_chunks": []},
        {"id": 3, "input": "예산 비율은?", "kind": "relevant", "expected": "25%", "gold_chunks": []},
        {"id": 4, "input": "승인 절차는?", "kind": "relevant", "expected": "2단계", "gold_chunks": []},
    ]
    ds = tmp_path / "dataset.jsonl"
    jl(ds, dataset)
    chunks = tmp_path / "idx" / "chunks.jsonl"
    jl(chunks, [{"chunk_id": "c1", "text": "온콜 > 기한\n15분 안에 확인", "version_date": "2026-09-13"}, {"chunk_id": "c2", "text": "예산 > 비율\n25% 예비비", "version_date": "2026-09-13"}])
    res = tmp_path / "res"
    ok = {"status": "ok", "result": "answer"}
    jl(res / "run1" / "rows.jsonl", [
        {"run": 1, "id": 1, **ok, "answer": "15분 안에 확인합니다. [1]" + FOOTER, "cited_chunk_ids": ["c1", "c1", "zz"], "cited_version_dates": ["2026-09-13", "2026-09-13", "2026-09-13"]},
        {"run": 1, "id": 2, "status": "ok", "result": "refuse", "answer": "답할 수 없습니다.", "cited_chunk_ids": []},
        {"run": 1, "id": 3, **ok, "answer": "25%입니다.", "cited_chunk_ids": ["c2"], "cited_version_dates": ["2026-01-01"]},
        {"run": 1, "id": 4, **ok, "answer": "2단계입니다.", "cited_chunk_ids": ["nope"]},
    ])
    jl(res / "run2" / "rows.jsonl", [
        {"run": 2, "id": 1, **ok, "answer": "15분입니다.", "cited_chunk_ids": ["c1"], "cited_version_dates": ["2026-09-13"]},
        {"run": 2, "id": 3, "status": "timeout", "result": None},
    ])
    return {"ds": ds, "chunks": chunks, "res": res, "tmp": tmp_path}


def build(w):
    rows = dr.read_run_rows(w["res"], None)
    chunks, _, _ = dr.load_chunks(w["chunks"])
    return dr.build_samples(rows, dr.load_dataset(w["ds"]), chunks)


def test_footer_line_is_removed_from_the_answer_only_at_the_end():
    assert dr.strip_footer("본문 [1]" + FOOTER) == "본문 [1]"
    assert dr.strip_footer("본문\n\n기준일 미지정 · 근거 판 날짜 2026-09-13 이전 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)") == "본문"
    assert dr.strip_footer("기준일 2026-11-10 이라는 말이 본문에 있다") == "기준일 2026-11-10 이라는 말이 본문에 있다"


def test_samples_use_cited_chunk_text_dedupe_ids_and_skip_what_cannot_be_scored(world):
    samples, info = build(world)
    got = {(s["run"], s["id"]): s for s in samples}
    assert set(got) == {(1, 1), (1, 3), (2, 1)}   # 4번은 스냅샷에 없는 id뿐이라 문맥이 없어 건너뜀, 2번 비관련·거절, run2의 3번 실패 행은 대상 밖
    s = got[(1, 1)]
    assert s["response"] == "15분 안에 확인합니다. [1]" and s["question"] == "온콜 확인 기한은?" and s["reference"] == "15분"
    assert s["contexts"] == ["온콜 > 기한\n15분 안에 확인"] and s["n_cited"] == 2 and s["n_unresolved"] == 1   # c1 중복은 한 번, zz는 못 찾음
    assert info["not_target"] == 2 and info["no_context"] == 1 and info["unresolved_ids"] == 2 and info["version_date_mismatch"] == 1
    assert info["scored_rows"] == 3 and info["no_answer_field"] == 0


def test_runs_can_be_limited_and_rows_without_answer_text_are_counted(world):
    rows = dr.read_run_rows(world["res"], [2])
    assert list(rows) == [2]
    old = {1: [{"run": 1, "id": 1, "status": "ok", "result": "answer", "cited_chunk_ids": ["c1"]}]}
    chunks, _, _ = dr.load_chunks(world["chunks"])
    samples, info = dr.build_samples(old, dr.load_dataset(world["ds"]), chunks)
    assert samples == [] and info["no_answer_field"] == 1


def test_summary_averages_runs_ignores_missing_values_and_checks_the_faithfulness_line():
    rows = [
        {"run": 1, "id": 1, "context_precision": 1.0, "context_recall": 1.0, "faithfulness": 1.0, "answer_relevancy": 0.6},
        {"run": 1, "id": 3, "context_precision": 0.5, "context_recall": None, "faithfulness": 0.8, "answer_relevancy": 0.7},
        {"run": 2, "id": 1, "context_precision": 0.9, "context_recall": 0.9, "faithfulness": 0.9, "answer_relevancy": 0.5},
    ]
    s = dr.summarize(rows)
    assert s["per_run"]["1"]["faithfulness"] == 0.9 and s["per_run"]["1"]["context_recall"] == 1.0 and s["per_run"]["1"]["n"] == 2
    assert s["mean_of_runs"]["faithfulness"] == 0.9 and s["missing_values"]["context_recall"] == 1
    assert s["faithfulness_pass"] is False   # 0.9 < 0.91
    assert dr.summarize([{"run": 1, "id": 1, "faithfulness": 0.95, **{m: 1.0 for m in dr.NAMES if m != "faithfulness"}}])["faithfulness_pass"] is True
    assert "충실도" in dr.render_markdown(s, {"revision": "r"})


def fake_evaluator(calls):
    def evaluate(part):
        calls.append([(p["run"], p["id"]) for p in part])
        return [{m: 0.5 for m in dr.NAMES} for _ in part]
    return evaluate


def test_scoring_loop_appends_rows_skips_done_rows_and_stops_at_the_cost_cap(world, tmp_path):
    samples, _ = build(world)
    out = tmp_path / "out"
    out.mkdir()
    calls: list = []
    spend = {"cost": 0.0}
    assert dr.run_scoring(samples, out, fake_evaluator(calls), lambda: (spend["cost"], None), max_cost=1.0, batch=2, log=lambda m: None) == 0
    assert calls == [[(1, 1), (1, 3)], [(2, 1)]]
    rows, done = dr.load_done(out / "ragas_rows.jsonl")
    assert len(rows) == 3 and done == {(1, 1), (1, 3), (2, 1)}
    calls.clear()
    assert dr.run_scoring(samples, out, fake_evaluator(calls), lambda: (0.0, None), max_cost=1.0, log=lambda m: None) == 0 and calls == []   # 이어 하면 새로 채점하지 않는다
    capped = tmp_path / "capped"
    capped.mkdir()
    assert dr.run_scoring(samples, capped, fake_evaluator(calls), lambda: (1.0, None), max_cost=1.0, log=lambda m: None) == 3
    assert not (capped / "ragas_rows.jsonl").exists()
    assert dr.run_scoring(samples, capped, fake_evaluator(calls), lambda: (0.0, "RateLimitError"), max_cost=1.0, log=lambda m: None) == 4


def test_failed_batch_is_recorded_as_error_and_retried_on_resume(world, tmp_path):
    samples, _ = build(world)
    out = tmp_path / "out2"
    out.mkdir()

    def boom(part):
        raise RuntimeError("x")

    assert dr.run_scoring(samples, out, boom, lambda: (0.0, None), max_cost=1.0, log=lambda m: None) == 4   # 유효한 값이 한 칸도 없으면 정상 종료(0)가 아니다
    rows, done = dr.load_done(out / "ragas_rows.jsonl")
    assert len(rows) == 3 and all(r["error"] for r in rows) and done == set()
    calls: list = []
    dr.run_scoring(samples, out, fake_evaluator(calls), lambda: (0.0, None), max_cost=1.0, log=lambda m: None)
    assert sum(len(c) for c in calls) == 3


def test_all_nan_scores_exit_nonzero_with_message_but_partial_values_pass(world, tmp_path):
    samples, _ = build(world)
    msgs: list[str] = []
    none_all = lambda part: [{m: None for m in dr.NAMES} for _ in part]   # noqa: E731 - RAGAS가 NaN만 돌려준 경우
    out = tmp_path / "nan"
    out.mkdir()
    assert dr.run_scoring(samples, out, none_all, lambda: (0.0, None), max_cost=1.0, log=msgs.append) == 4
    assert any("유효한 지표 값이 없다" in m for m in msgs)
    some = lambda part: [{**{m: None for m in dr.NAMES}, "faithfulness": 0.9} for _ in part]   # noqa: E731
    out2 = tmp_path / "some"
    out2.mkdir()
    assert dr.run_scoring(samples, out2, some, lambda: (0.0, None), max_cost=1.0, log=lambda m: None) == 0


def run_main(w, *extra, out="out"):
    return dr.main(["--results", str(w["res"]), "--dataset", str(w["ds"]), "--chunks", str(w["chunks"]), "--out", str(w["tmp"] / out), *extra])


def test_dry_run_reports_input_counts_without_keys_files_or_ragas(world, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    assert run_main(world, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "채점 대상 3행" in out and "추정" in out and "dry-run" in out
    assert not (world["tmp"] / "out").exists()
    assert "ragas" not in sys.modules


def test_real_run_stops_before_any_call_without_an_anthropic_format_key(world, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-or-not-anthropic")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-x")
    assert run_main(world) == 2
    err = capsys.readouterr().err
    assert "sk-ant-" in err and "sk-or-not-anthropic" not in err
    assert not (world["tmp"] / "out").exists()


def test_existing_result_folder_is_never_overwritten_without_resume(world, capsys):
    out = world["tmp"] / "out"
    out.mkdir()
    (out / "keep.txt").write_text("이전 결과", encoding="utf-8")
    assert run_main(world) == 2
    assert "덮어쓰지 않는다" in capsys.readouterr().err
    assert (out / "keep.txt").read_text(encoding="utf-8") == "이전 결과"


def test_rows_without_answer_text_stop_the_run(world, capsys, monkeypatch):
    jl(world["res"] / "run3" / "rows.jsonl", [{"run": 3, "id": 1, "status": "ok", "result": "answer", "cited_chunk_ids": ["c1"]}])
    assert run_main(world, "--dry-run") == 2
    assert "answer가 없다" in capsys.readouterr().err


def test_estimate_scales_with_rows_and_names_its_basis():
    a, b = dr.estimate(25), dr.estimate(75)
    assert a["usd_per_row"] == b["usd_per_row"] and b["usd"] == pytest.approx(a["usd"] * 3, abs=0.01) and "61.51" in a["basis"]
