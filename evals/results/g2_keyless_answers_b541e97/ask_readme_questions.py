"""키 없이 뜬 로컬 서비스(새 clone, `.env` 없음)에 README 데모 질문 9개를 보내 결과를 기록한다 (G2). LLM·Voyage 키와 운영 서비스를 쓰지 않는다(비용 0원).

    python evals/results/g2_keyless_answers_b541e97/ask_readme_questions.py --base-url http://localhost:8000 \
        --clone <새 clone 폴더> --out evals/results/g2_keyless_answers_b541e97

질문과 기대(인용 답 6개, 거절 3개)는 새 clone의 `data/demo_replay/questions.txt`에서 읽는다(`tests/test_demo_replay_fresh.py`가 README와 글자 대조하는 파일).
데모 계정 비밀번호는 새 clone의 `.env.example`에 적힌 공개 데모 값이다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from evals.latency.deploy_latency import ask_once  # noqa: E402
from evals.safety.deploy_check import Creds, _with_csrf, login  # noqa: E402

KST = timezone(timedelta(hours=9))


def read_questions(path: Path) -> list[tuple[str, str]]:
    """(질문, 기대 종류) 목록. 기대는 질문 파일의 주석 구역으로 정한다: 인용 답 6개 구역은 answer, 거절 3개 구역은 refuse."""
    out, expect = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if "인용 답이 나오는 질문" in line:
                expect = "answer"
            elif "거절이 나오는 질문" in line:
                expect = "refuse"
            continue
        if line.strip():
            out.append((line.strip(), expect))
    return out


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{name}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise SystemExit(f"{path}에 {name}이 없다")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--clone", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--commit", default="")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    assert not (args.clone / ".env").exists(), "새 clone에 .env가 있다"
    qs = read_questions(args.clone / "data" / "demo_replay" / "questions.txt")
    creds = Creds("demo-user", env_value(args.clone / ".env.example", "DEMO_USER_PASSWORD"))
    rows = []
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        health = client.get("/health")
        uid, why = login(client, creds)
        _with_csrf(client)
        login_status = "ok" if uid else why
        for i, (q, expect) in enumerate(qs, 1):
            t = time.perf_counter()
            res = ask_once(client, {"input": q}, use_as_of=False, timeout_s=120)
            rows.append({
                "n": i, "question": q, "expected": expect, "http_ok": res["status"] == "ok", "status": res["status"], "kind": res.get("result"),
                "matches_expected": res.get("result") == expect, "citations": res.get("citations"), "cited_chunk_ids": res.get("cited_chunk_ids"),
                "cited_version_dates": res.get("cited_version_dates"), "cost_usd": res.get("cost_usd"), "seconds": round(time.perf_counter() - t, 2),
                "answer": res.get("answer"), "asked_at": datetime.now(KST).isoformat(timespec="seconds"),
            })
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "answers.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_ans = sum(r["kind"] == "answer" for r in rows)
    n_ref = sum(r["kind"] == "refuse" for r in rows)
    same = sum(r["matches_expected"] for r in rows)
    lines = [
        f"# 키 없는 새 clone의 README 질문 9개 (main `{args.commit}`)", "",
        f"- `.env` 없음, LLM·Voyage 키 없음, 운영 서비스 호출 없음. `/health` HTTP {health.status_code}, `demo-user` 로그인 {login_status}.",
        f"- 결과: 인용 답 {n_ans}개, 거절 {n_ref}개, 기대(질문 파일 구역: 인용 답 6, 거절 3)와 같은 질문 {same}/{len(rows)}개. 모든 요청 비용 {sum((r['cost_usd'] or 0) for r in rows)}달러.", "",
        "| # | 질문 | 기대 | 결과 | 인용 | 비용(달러) | 초 | 일치 |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['n']} | {r['question']} | {r['expected']} | {r['kind'] or r['status']} | {r['citations']} | {r['cost_usd']} | {r['seconds']} | {'예' if r['matches_expected'] else '아니오'} |")
    lines += ["", "답 본문과 인용 청크 id, 판 날짜는 `answers.jsonl`에 있다.", ""]
    (args.out / "summary.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"인용 답 {n_ans}, 거절 {n_ref}, 일치 {same}/{len(rows)}")
    return 0 if same == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
