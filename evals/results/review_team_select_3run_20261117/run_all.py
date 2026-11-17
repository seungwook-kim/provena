"""켬, 끔, 켬, 끔, 켬, 끔 순서로 `run_one.py`를 회마다 새 프로세스로 돌린다. 누적 비용 상한 0.40달러, 회당 상한 0.08달러.

    .venv\\Scripts\\python.exe evals/results/review_team_select_3run_20261117/run_all.py

회별 출력은 `run{N}_{config}.log.txt`에 개인 경로를 가려 남긴다.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
ORDER = [("on", 1), ("off", 1), ("on", 2), ("off", 2), ("on", 3), ("off", 3)]
TOTAL_CAP = 0.40
RUN_CAP = 0.08


def redact(text: str) -> str:
    text = text.replace(str(ROOT), "<REPO>").replace(str(ROOT).replace("\\", "/"), "<REPO>")
    return re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", "<HOME>", text)


def main() -> int:
    spent = 0.0
    for cfg, n in ORDER:
        left = TOTAL_CAP - spent
        if left < 0.06:
            print(f"누적 {spent:.4f}달러, 남은 한도 {left:.4f}달러라 {cfg} r{n}부터 멈춘다", flush=True)
            return 3
        cap = min(RUN_CAP, left)
        p = subprocess.run([sys.executable, str(OUT / "run_one.py"), "--config", cfg, "--run", str(n), "--max-cost", f"{cap:.4f}"],
                           cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        log = redact((p.stdout or "") + ("\n[stderr]\n" + p.stderr if p.stderr else ""))
        (OUT / f"run{n}_{cfg}.log.txt").write_text(log, encoding="utf-8")
        summ = OUT / f"run{n}_{cfg}" / "summary.json"
        if p.returncode not in (0,) or not summ.is_file():
            print(f"{cfg} r{n} 종료 코드 {p.returncode}, 로그 확인 후 멈춘다", flush=True)
            print(log[-3000:], flush=True)
            if summ.is_file():
                spent += json.loads(summ.read_text(encoding="utf-8"))["metrics"]["cost_usd"]
            print(f"누적 {spent:.4f}달러", flush=True)
            return 2
        m = json.loads(summ.read_text(encoding="utf-8"))["metrics"]
        spent += m["cost_usd"]
        print(f"{cfg} r{n}: 찾음 {m['gold_found']}/{m['gold_total']} 누락률 {m['missed_issue_rate']:.3f} 비용 {m['cost_usd']:.5f} "
              f"평균 {m['latency_mean_s']}초 p95 {m['latency_p95_s']}초 오류 {m['errors']} | 누적 {spent:.4f}달러", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
