"""GitHub Actions 워크플로 시험: YAML이 읽히고, 워크플로가 부르는 명령과 파일이 이 저장소에 실제로 있는지 본다. 네트워크·키 없음.

Actions가 결제 문제로 시작되지 않는 동안에도(EVAL_REPORT.md 8장 CI 문단) 워크플로 파일이 깨지지 않았는지 로컬에서 확인하는 용도다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
NAMES = ["ci.yml", "secret-scan.yml", "handbook-sync.yml"]


def load(name: str) -> dict:
    d = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    if True in d:  # YAML 1.1은 `on`을 True로 읽는다
        d["on"] = d.pop(True)
    return d


def steps(wf: dict) -> list[dict]:
    return [s for job in wf["jobs"].values() for s in job["steps"]]


def run_text(wf: dict) -> str:
    return "\n".join(s.get("run", "") for s in steps(wf))


@pytest.mark.parametrize("name", NAMES)
def test_workflow_parses(name):
    wf = load(name)
    assert wf["name"] and wf["on"] and wf["jobs"]
    for job in wf["jobs"].values():
        assert job["runs-on"] and job["steps"]


def test_ci_runs_pytest_then_the_score_comparison_on_pull_requests():
    wf = load("ci.yml")
    assert "pull_request" in wf["on"]
    text = run_text(wf)
    assert "python -m pytest" in text
    assert text.index("python -m pytest") < text.index("python evals/ci_compare.py")  # 평가 점수 비교가 테스트 뒤 단계다
    assert (ROOT / "evals" / "ci_compare.py").is_file()
    assert (ROOT / "evals" / "ci_baseline.json").is_file()


def test_ci_installs_from_an_existing_requirements_file_and_python_version_is_pinned():
    wf = load("ci.yml")
    req = re.findall(r"pip install -r (\S+)", run_text(wf))
    assert req and all((ROOT / r).is_file() for r in req)
    setup = next(s for s in steps(wf) if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert re.fullmatch(r"3\.\d+", str(setup["with"]["python-version"]))
    assert (ROOT / setup["with"]["cache-dependency-path"]).is_file()


def test_ci_limits_token_and_cancels_superseded_runs():
    wf = load("ci.yml")
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["cancel-in-progress"] is True  # Actions 사용 시간 절약


def test_secret_scan_checks_the_full_history_with_gitleaks():
    wf = load("secret-scan.yml")
    assert wf["permissions"] == {"contents": "read"}
    st = steps(wf)
    checkout = next(s for s in st if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    assert "gitleaks" in run_text(wf)


def test_handbook_sync_does_not_run_on_pull_requests():
    wf = load("handbook-sync.yml")
    assert "pull_request" not in wf["on"]  # 운영 DB와 Voyage 키를 쓰므로 PR에서 돌지 않는다
    assert wf["on"]["schedule"][0]["cron"] and "workflow_dispatch" in wf["on"]
