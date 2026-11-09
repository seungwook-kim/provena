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


def test_committed_final_results_pass_against_the_committed_baseline(monkeypatch):
    # 저장소에 커밋된 실제 최종 결과(EVAL_REPORT 4장)와 기준 파일이 어긋나지 않는다.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert ci_compare.main([]) == 0