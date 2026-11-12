"""사전 등록 62.20 측정 오케스트레이터(세 갈래 x 3회, 회차마다 순서 회전). 키는 프로세스 환경 변수로만 둔다(출력, 저장 없음)."""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"<임시 폴더>\pv_speed")
PY = r"<임시 폴더>\venv\Scripts\python.exe"
OUT = ROOT / "evals" / "results" / "speed_p95_code_2026-11-10"
LOG = OUT / "orchestrator.log"
COST_STOP = 4.5   # 행 cost_usd 합 기준 누적 상한(사용자 상한 5달러보다 낮게)
STALL_S = 600
ORDER = {1: ["a", "b", "c"], 2: ["b", "c", "a"], 3: ["c", "a", "b"]}

sys.path.insert(0, str(ROOT))
from backend.graph.service_profile import MEASURED_ARGS  # noqa: E402

BASE = list(MEASURED_ARGS)
B_EXTRA = ["--search-hedge", "1.5", "--speculate-early-search", "--llm-hedge-by-task", "classify=1.2,decompose_gate=1.2,decompose=2.0"]


def arm_args(arm: str) -> list[str]:
    args = list(BASE)
    if arm in ("b", "c"):
        args += B_EXTRA
    if arm == "c":
        i = args.index("--answer-wait"); args[i + 1] = "4.0"
        i = args.index("--answer-budget"); args[i + 1] = "6.5"
    return args


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def secret(name: str) -> str:
    r = subprocess.run(["gcloud", "secrets", "versions", "access", "latest", f"--secret={name}", "--project=provena-team"],
                       capture_output=True, text=True, shell=(os.name == "nt"))
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"비밀 {name} 읽기 실패(코드 {r.returncode})")
    return r.stdout.strip()


def run_cost(folder: Path) -> float:
    p = folder / "single" / "rows.jsonl"
    if not p.is_file():
        return 0.0
    return sum(float(json.loads(x).get("cost_usd") or 0) for x in p.read_text(encoding="utf-8").splitlines() if x.strip())


def run_one(name: str, arm: str, env: dict) -> int:
    folder = OUT / name
    if (folder / "single" / "rows.jsonl").is_file():
        log(f"{name}: 이미 끝남, 건너뜀")
        return 0
    if folder.exists():  # 중간에 끊긴 폴더는 지우고 처음부터 다시(회차 일부만 쓰지 않는다)
        import shutil
        shutil.rmtree(folder)
    cmd = [PY, "-m", "evals.latency.run_local_pg", "run", "--store", "pg", "--llm", "anthropic", "--arms", "single", "--warm", *arm_args(arm), "--out", str(folder)]
    log(f"{name}: 시작 (갈래 {arm})")
    t0 = time.time()
    (OUT / "stdout").mkdir(parents=True, exist_ok=True)
    with (OUT / "stdout" / f"{name}.txt").open("w", encoding="utf-8") as so:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=so, stderr=subprocess.STDOUT)
        last_size, last_change = -1, time.time()
        while p.poll() is None:
            time.sleep(15)
            part = folder / "single.partial.jsonl"
            size = part.stat().st_size if part.is_file() else 0
            if size != last_size:
                last_size, last_change = size, time.time()
            elif time.time() - last_change > STALL_S:
                log(f"{name}: {STALL_S}초 넘게 진행 없음, 중단(자식 종료)")
                p.kill()
                return 99
    rc = p.returncode
    log(f"{name}: 끝 코드 {rc}, {time.time() - t0:.0f}초, 행 비용합 {run_cost(folder):.4f}달러")
    return rc


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = secret("llm_key2_test")
    env["VOYAGE_API_KEY"] = secret("provena-voyage-key")
    env["LOCAL_PG_URL"] = "postgresql://app:app@127.0.0.1:55441/app"
    env["SEARCH_HNSW"] = "1"
    for k in ("OPENROUTER_API_KEY", "LLM_API_KEY", "DATABASE_URL"):
        env.pop(k, None)
    plan = [("warmup_a", "a")] + [(f"{arm}_r{r}", arm) for r in (1, 2, 3) for arm in ORDER[r]]
    only = sys.argv[1:]  # 이름을 주면 그것만
    total = 0.0
    for name, arm in plan:
        if only and name not in only:
            continue
        total = sum(run_cost(OUT / n) for n, _ in plan)
        if total > COST_STOP:
            log(f"누적 비용 {total:.3f}달러가 {COST_STOP}를 넘어 멈춤")
            return 4
        rc = run_one(name, arm, env)
        if rc != 0:
            log(f"{name}: 실패, 오케스트레이터 멈춤(코드 {rc})")
            return 3
        s = json.loads((OUT / name / "single" / "summary.json").read_text(encoding="utf-8"))
        errs = (s.get("metrics") or {}).get("errors")
        log(f"{name}: 오류 행 {errs}")
        if errs:
            log("오류 행이 있어 멈춤")
            return 5
    log(f"전체 끝, 행 비용합 {sum(run_cost(OUT / n) for n, _ in plan):.4f}달러")
    return 0


if __name__ == "__main__":
    sys.exit(main())
