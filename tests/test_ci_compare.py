"""CI 평가 점수 비교(evals/ci_compare.py)의 단위 시험. 키·네트워크 없이 임시 결과 폴더만 쓴다."""
import json

from evals import ci_compare

SHA = "a" * 64
RUNS = ["r1", "r2", "r3"]
GOOD = {
    "n": 50, "cited_correct_rate": 0.996, "citation_accuracy": 1.0, "correct_refusal_rate": 1.0,
    "wrong_citation_rate": 0.0, "over_refusal_rate": 0.0, "hallucination_risk_rate": 0.0, "latency_p95_s": 9.8,
}
BASELINE = {
    "dataset": "dataset_v2.jsonl",
    "arms": {arm: {k: v for k, v in GOOD.items() if k != "n"} for arm in ("single", "multi")},
}
FROZEN = {"dataset_v2.jsonl": {"sha256": SHA, "count": 50}}


def _write(results, run, arm, metrics=None, sha=SHA, dataset="dataset_v2.jsonl"):
    path = results / run / arm
    path.mkdir(parents=True, exist_ok=True)
    summary = {"meta": {"dataset": dataset, "dataset_sha256": sha}, "metrics": {**GOOD, **(metrics or {})}}
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _setup(tmp_path, overrides=None, stale=()):
    results = tmp_path / "results"
    for run in RUNS:
        for arm in ("single", "multi"):
            extra = (overrides or {}).get((run, arm))
            _write(results, run, arm, extra, sha="b" * 64 if (run, arm) in stale else SHA)
    (tmp_path / "baseline.json").write_text(json.dumps(BASELINE), encoding="utf-8")
    (tmp_path / "frozen.json").write_text(json.dumps(FROZEN), encoding="utf-8")
    return ["--results-dir", str(results), "--runs", *RUNS, "--baseline", str(tmp_path / "baseline.json"), "--frozen", str(tmp_path / "frozen.json")]


def test_passes_when_results_equal_the_baseline(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_compare.main(_setup(tmp_path)) == 0
    assert "결과: **통과**" in capsys.readouterr().out


def test_fails_below_the_spec_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    low = {(run, "single"): {"correct_refusal_rate": 0.8} for run in RUNS}
    assert ci_compare.main(_setup(tmp_path, low)) == 1
    out = capsys.readouterr().out
    assert "통과선 미달" in out and "single 비관련 질문 거절" in out


def test_fails_when_a_metric_drops_below_the_baseline_even_above_the_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    worse = {(run, "multi"): {"citation_accuracy": 0.9} for run in RUNS}
    assert ci_compare.main(_setup(tmp_path, worse)) == 1
    assert "기준보다 낮음" in capsys.readouterr().out


def test_fails_when_a_lower_is_better_metric_rises(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    worse = {(run, "single"): {"hallucination_risk_rate": 0.02} for run in RUNS}
    assert ci_compare.main(_setup(tmp_path, worse)) == 1
    assert "기준보다 높음" in capsys.readouterr().out


def test_fails_when_p95_exceeds_the_spec_ceiling(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    slow = {(run, "multi"): {"latency_p95_s": 10.5} for run in RUNS}
    assert ci_compare.main(_setup(tmp_path, slow)) == 1


def test_result_with_an_old_dataset_hash_is_left_out_of_the_average(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    # r3의 single은 옛 해시이고 점수가 나쁘다. 빠져야 하므로 평균이 기준과 같아 통과한다.
    args = _setup(tmp_path, {("r3", "single"): {"citation_accuracy": 0.1}}, stale=[("r3", "single")])
    assert ci_compare.main(args) == 0
    out = capsys.readouterr().out
    assert "제외: r3 (동결 해시와 다름(옛 결과))" in out and "2회 평균" in out


def test_fails_when_every_result_of_an_arm_has_an_old_hash(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup(tmp_path, stale=[(run, "multi") for run in RUNS])
    assert ci_compare.main(args) == 1
    assert "multi: 동결 해시와 일치하는 결과가 없어" in capsys.readouterr().out


def test_fails_when_a_summary_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup(tmp_path)
    for run in RUNS:
        (tmp_path / "results" / run / "single" / "summary.json").unlink()
    assert ci_compare.main(args) == 1


def test_wrong_item_count_is_excluded(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup(tmp_path, {(run, "single"): {"n": 30} for run in RUNS})
    assert ci_compare.main(args) == 1


def test_writes_the_table_to_the_github_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert ci_compare.main(_setup(tmp_path)) == 0
    text = summary.read_text(encoding="utf-8")
    assert "| single | 인용 정확도 | 1.0 | 1.0 | >= 0.85 | 통과 |" in text


# ------------------------------------------------ 가장 최근 운영 측정 (deploy_latency_provena-api-*)
OP_GOOD = {"cited_correct_rate": 0.942, "citation_accuracy": 0.95, "correct_refusal_rate": 1.0, "wrong_citation_rate": 0.067, "over_refusal_rate": 0.0}
OP_BASELINE = {**BASELINE, "operating": {"revision": "provena-api-00047-wjn", "metrics": {**OP_GOOD, "latency_p95_s": 8.51}}}


def _write_operating(tmp_path, revision, finished_at, metrics=None, p95=8.51, sha=SHA, n=50):
    folder = tmp_path / "results" / f"deploy_latency_provena-api-{revision}"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"dataset": "dataset_v2.jsonl", "dataset_sha256": sha, "revision": f"provena-api-{revision}", "finished_at": finished_at}
    per_run = [{"run": i, "total_s": {"p95": p95}} for i in (1, 2, 3)]
    (folder / "summary.json").write_text(json.dumps({"meta": meta, "per_run": per_run}), encoding="utf-8")
    gold = {"summary": {"per_run": [{"run": i, "n": n, **OP_GOOD, **(metrics or {})} for i in (1, 2, 3)]}}
    (folder / "citation_gold.json").write_text(json.dumps(gold), encoding="utf-8")


def _setup_operating(tmp_path):
    args = _setup(tmp_path)
    (tmp_path / "baseline.json").write_text(json.dumps(OP_BASELINE), encoding="utf-8")
    return args


def test_operating_measurement_equal_to_the_baseline_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00")
    assert ci_compare.main(args) == 0
    assert "운영 provena-api-00047-wjn" in capsys.readouterr().out


def test_newest_operating_measurement_is_the_one_compared(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00")
    _write_operating(tmp_path, "00050-new", "2026-11-14T10:00:00+09:00", {"cited_correct_rate": 0.8})   # 더 늦은 측정이 나빠졌다
    assert ci_compare.main(args) == 1
    out = capsys.readouterr().out
    assert "운영 provena-api-00050-new 정답 근거 인용률 0.8 < 통과선 0.85" in out and "기준 파일은 provena-api-00047-wjn 측정" in out


def test_an_older_bad_operating_measurement_is_not_compared(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00040-old", "2026-11-10T01:54:02+09:00", {"correct_refusal_rate": 0.5})
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00")
    assert ci_compare.main(args) == 0


def test_operating_drop_below_the_baseline_fails_even_above_the_floor(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00", {"citation_accuracy": 0.9})
    assert ci_compare.main(args) == 1
    assert "인용 정확도 0.9 < 기준 0.95" in capsys.readouterr().out


def test_operating_p95_over_the_ceiling_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00", p95=10.4)
    assert ci_compare.main(args) == 1


def test_operating_measurement_with_an_old_dataset_hash_or_wrong_count_is_not_used(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    args = _setup_operating(tmp_path)
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00", sha="b" * 64)
    assert ci_compare.main(args) == 1
    assert "운영 측정 결과(deploy_latency_provena-api-*)가 없어" in capsys.readouterr().out
    _write_operating(tmp_path, "00047-wjn", "2026-11-13T01:54:02+09:00", n=30)
    assert ci_compare.main(args) == 1


def test_committed_final_results_pass_against_the_committed_baseline(monkeypatch):
    # 저장소에 커밋된 실제 최종 결과(EVAL_REPORT 4장)와 기준 파일이 어긋나지 않는다.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_compare.main([]) == 0