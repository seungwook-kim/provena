"""확정 정답 0원 재계산 도구(`evals/agent/review_gold_confirmed_recalc.py`, 사전 등록 62.61) 시험. 저장된 결과 폴더만 읽는다(네트워크·DB 없음)."""
from __future__ import annotations

import pytest

from evals.agent import review_gold_confirmed_recalc as R

pytestmark = pytest.mark.skipif(not all(d.is_dir() for d in R.RUNS.values()), reason="00044·00049 저장 결과 폴더 없음")

EXPECT = {"00044": {"team": 47, "same": 47, "undivided": 9}, "00049": {"team": 47, "same": 46, "undivided": 13}}


def test_confirmed_gold_gives_same_found_counts_as_draft():
    for name, d in R.RUNS.items():
        draft, conf = R.recompute(d, R.DRAFT), R.recompute(d, R.CONFIRMED)
        for arm, want in EXPECT[name].items():
            assert (draft["all"][arm]["found"], draft["all"][arm]["total"]) == (want, 111)
            assert (conf["all"][arm]["found"], conf["all"][arm]["total"]) == (want, 111)
            assert draft["all"][arm]["missed_rate"] == conf["all"][arm]["missed_rate"]


def test_only_issue_wording_differs_between_gold_files():
    diffs = R.issue_text_diff()
    assert len(diffs) == 7 and all(t["same_team_and_section"] for t in diffs)


def test_cli_writes_summary_and_exits_zero(tmp_path):
    assert R.main(["--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "summary.json").is_file() and (tmp_path / "out" / "summary.md").is_file()
