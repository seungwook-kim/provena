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


def test_ci_also_runs_the_demo_replay_tests_that_the_default_run_skips():
    # pytest.ini의 addopts가 `-m "not demo_replay"`라 기본 실행은 키 없는 데모 녹화 대조를 건너뛴다. CI가 따로 돌려야 녹화 키가 깨진 PR을 잡는다.
    wf = load("ci.yml")
    assert "not demo_replay" in (ROOT / "pytest.ini").read_text(encoding="utf-8")
    runs = [s.get("run", "") for s in steps(wf)]
    assert any(re.search(r"python -m pytest\b.*-m demo_replay", r) for r in runs)
    assert next(i for i, r in enumerate(runs) if "-m demo_replay" in r) < next(i for i, r in enumerate(runs) if "ci_compare.py" in r)


def test_ci_demo_replay_step_has_a_database_and_fails_when_skipped():
    # 이 시험은 Postgres가 없으면 건너뛴다. 건너뛴 채 초록이 되지 않도록 DB 서비스와 건너뜀 검사가 있어야 한다.
    wf = load("ci.yml")
    job = next(iter(wf["jobs"].values()))
    assert "pgvector/pgvector" in job["services"]["postgres"]["image"]
    step = next(s for s in steps(wf) if "-m demo_replay" in s.get("run", ""))
    assert step["env"]["PROVENA_D5_PG_URL"].startswith("postgresql://")
    assert step.get("shell") == "bash"     # pipefail로 pytest 실패가 tee에 가려지지 않는다
    assert "skipped" in step["run"] and "exit 1" in step["run"]


EVAL_CMD = re.compile(r"python evals/ci_current_eval\.py\s+--out\s+(\S+)")
COMPARE_CMD = re.compile(r"python evals/ci_compare\.py\s+--current\s+(\S+)")


def current_eval_link_problems(runs: list[str]) -> list[str]:
    """ci.yml의 run 명령 목록에서 `ci_current_eval.py --out <파일>` 다음에 `ci_compare.py --current <같은 파일>`이 이어지는지 본다. 어긋난 곳을 문장으로 돌려준다(비면 연결이 맞다)."""
    evals = [(i, m.group(1)) for i, r in enumerate(runs) for m in [EVAL_CMD.search(r)] if m]
    compares = [(i, m.group(1)) for i, r in enumerate(runs) for m in [COMPARE_CMD.search(r)] if m]
    problems: list[str] = []
    if len(evals) != 1:
        problems.append(f"`python evals/ci_current_eval.py --out <파일>` 단계가 {len(evals)}개다(1개여야 한다)")
    if len(compares) != 1:
        problems.append(f"`python evals/ci_compare.py --current <파일>` 단계가 {len(compares)}개다(1개여야 한다)")
    if len(evals) == 1 and len(compares) == 1:
        if evals[0][0] >= compares[0][0]:
            problems.append("비교 단계가 현재 코드 평가 단계보다 앞에 있다(평가 결과가 나오기 전에 비교한다)")
        if evals[0][1] != compares[0][1]:
            problems.append(f"평가가 쓰는 파일({evals[0][1]})과 비교가 읽는 파일({compares[0][1]})이 다르다")
    return problems


def test_ci_current_eval_step_is_followed_by_the_comparison_reading_the_same_result_file():
    # evals/ci_current_eval.py와 ci.yml의 연결 시험: 한쪽이 지워지거나 이름이 바뀌거나 파일 이름이 어긋나면 현재 코드 평가가 조용히 빠진다.
    runs = [s.get("run", "") for s in steps(load("ci.yml"))]
    assert current_eval_link_problems(runs) == []
    for path in ("evals/ci_current_eval.py", "evals/ci_compare.py", "evals/ci_baseline.json"):
        assert (ROOT / path).is_file(), path
    assert (ROOT / "data" / "demo_replay" / "questions.txt").is_file()   # 이 평가가 재생하는 질문 목록


def test_ci_current_eval_link_check_fails_when_a_step_is_removed_renamed_or_mismatched():
    good = ["python -m pytest -q", "python evals/ci_current_eval.py --out ci_current_result.json", "python evals/ci_compare.py --current ci_current_result.json"]
    assert current_eval_link_problems(good) == []
    assert current_eval_link_problems([good[0], good[2]])                                                    # 평가 단계 삭제
    assert current_eval_link_problems(good[:2])                                                              # 비교 단계 삭제
    assert current_eval_link_problems([good[0], good[1].replace("ci_current_eval.py", "ci_now_eval.py"), good[2]])   # 평가 파일 이름 변경
    assert current_eval_link_problems([good[0], good[1], good[2].replace("ci_compare.py", "ci_cmp.py")])             # 비교 파일 이름 변경
    assert current_eval_link_problems([good[0], good[1], good[2].replace("--current", "--result")])                  # 비교 인자 이름 변경
    assert current_eval_link_problems([good[0], good[1], good[2].replace("ci_current_result.json", "other.json")])   # 결과 파일 이름 불일치
    assert current_eval_link_problems([good[0], good[2], good[1]])                                                   # 순서 뒤바뀜
    assert current_eval_link_problems([good[0], good[1], good[1], good[2]])                                          # 평가 단계 중복


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
