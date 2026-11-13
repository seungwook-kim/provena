"""현재 코드로 0원(키 없는 데모 재생, 오프라인) 평가를 돌려 결과 파일을 남긴다. `evals/ci_compare.py --current <결과 파일>`이 이 파일을 기준값과 비교한다.

    PROVENA_D5_PG_URL=postgresql://app:pw@127.0.0.1:5432/postgres python evals/ci_current_eval.py --out evals/results/ci_current_<날짜>/result.json

왜: 지금까지 CI 비교는 커밋된 옛 측정 결과 파일만 읽어서, 현재 코드가 바뀌어도 점수가 그대로였다. 이 도구는 현재 코드의 질문 그래프(서비스 설정 61.51, 서버와 같은 Postgres 검색)를
키·네트워크 없이 README의 데모 질문 9개(인용 답 6, 거절 3)에 돌리고, 녹화(`data/demo_replay/recorded.jsonl`)에서 찾지 못한 LLM 요청 수와 결과를 센다.
LLM·Voyage·운영 호출은 없다(`LLM_API_KEY`, `VOYAGE_API_KEY` 등을 이 프로세스에서 지우고 돌린다). 임시 DB를 만들어 색인을 적재하고 끝나면 그 DB만 지운다.

지표(질문 그래프 한 번 돌린 값, 추론 답을 보내는 경로와 빠른 답만 보내는 경로 둘 다):
- `answers_ok`: 인용 답이어야 하는 질문 중 실제로 인용 답이 나온 수
- `refusals_ok`: 거절이어야 하는 질문 중 실제로 거절이 나온 수
- `missed_calls`: 녹화에 없는 LLM 요청과 질문 벡터 수(0이 아니면 프롬프트·검색·입력이 바뀌어 녹화가 오래된 것)
- `fake_answers`: 녹화 답이 아니라 발췌형 대체 답이 나온 수
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / "data" / "demo_replay"
README = ROOT / "README.md"
FAKE_ANSWER_MARK = "실제 LLM이 쓴 답이 아닙니다"   # backend/services/demo_replay.py demo_fallback의 발췌형 대체 답 머리 문장
ENV_CLEAR = (
    "LLM_API_KEY", "VOYAGE_API_KEY", "DEMO_MODE", "LLM_RECORD", "LLM_PROVIDER", "LLM_MODEL", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "DEMO_REPLAY_DIR", "SEARCH_RANGE_N", "SERVICE_PROFILE", "MCP_TOKEN", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "SEARCH_DECOMPOSE", "SEARCH_INDEX_DIR",
)
PATHS = (("reasoning_answer_in_time", "1000"), ("reasoning_answer_skipped", "0.001"))   # GRAPH_ANSWER_BUDGET_S: 추론 답을 보내는 경로, 빠른 답만 보내는 경로


def readme_questions() -> tuple[list[str], list[str]]:
    """README의 '키 없이 인용 답이 나오는 질문'과 '키 없이 거절이 나오는 질문'(tests/test_demo_replay.py와 같은 읽기)."""
    import re

    lines = README.read_text(encoding="utf-8").splitlines()
    answers, on = [], False
    for ln in lines:
        if "키 없이 인용 답이 나오는 질문" in ln:
            on = True
        elif on and ln.startswith("  - "):
            answers.append(ln[4:].strip())
        elif on:
            on = False
    refusals = [q for ln in lines if ln.startswith("- 키 없이 거절이 나오는 질문") for q in re.findall(r'"([^"]+)"', ln)]
    return answers, refusals


def make_db(admin_url: str, workdir: Path) -> tuple[str, str]:
    """색인을 적재한 새 DB의 주소와 이름."""
    import psycopg

    from backend.rag.ingest.snapshot import INDEX_ARCHIVE, unpack_index
    from backend.rag.retrieve import load_snapshot

    name = "provena_ci_current_" + uuid.uuid4().hex[:8]
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    u = urlsplit(admin_url)
    url = urlunsplit((u.scheme, u.netloc, f"/{name}", "", ""))
    with psycopg.connect(url, autocommit=True) as c:
        for f in sorted((ROOT / "db").glob("*.sql")):
            c.execute(f.read_text(encoding="utf-8"))
    index = workdir / "index"
    unpack_index(ROOT / INDEX_ARCHIVE, index)
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        if load_snapshot.main(["--index", str(index)]) != 0:
            raise RuntimeError("색인 적재 실패")
    finally:
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev
    return url, name


def run_questions(db_url: str, budget: str) -> list[dict]:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.graph.recall.runtime import make_answer_store
    from backend.graph.service_profile import service_profile
    from backend.main import build_question_graph
    from backend.services import demo_replay as dr
    from backend.services.demo_record import load_questions
    from backend.services.llm import finish_run, run_config

    search = importlib.import_module("backend.rag.retrieve.search")
    for name in ENV_CLEAR:
        os.environ.pop(name, None)
    os.environ["DATABASE_URL"] = db_url
    os.environ["DEMO_REPLAY_DIR"] = str(REPLAY_DIR)
    os.environ["GRAPH_ANSWER_BUDGET_S"] = budget
    missed: list[str] = []

    class SpyStore(dr.ReplayStore):
        def get(self, key):
            row = super().get(key)
            if row is None:
                missed.append("query_embedding")
            return row

    dr._stores[str(REPLAY_DIR)] = SpyStore(REPLAY_DIR)
    dr._warned = True
    real_role, real_fallback = dr.message_role, dr.demo_fallback
    dr.demo_fallback = lambda messages: (missed.append(real_role(messages)), real_fallback(messages))[1]
    search._searcher = None
    rows: list[dict] = []
    try:
        with service_profile():
            st = SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                                 store=InMemoryStore(), answer_store=make_answer_store(None))
            graph = build_question_graph(st)
            for q in (x["question"] for x in load_questions(REPLAY_DIR / "questions.txt")):
                missed.clear()
                tid = "ci-current-" + uuid.uuid4().hex[:8]
                cfg = run_config("ci_current_eval", thread_id=tid, configurable={"thread_id": tid})
                try:
                    out = graph.invoke({"question": q, "user_id": "ci-current", "thread_id": tid, "org": None, "as_of": None}, cfg)
                finally:
                    finish_run(cfg)
                rows.append({"question": q, "kind": out.get("kind"), "citations": len(out.get("citations") or []), "missed_calls": len(missed),
                             "missed_roles": sorted(set(missed)), "fake_answer": FAKE_ANSWER_MARK in (out.get("answer") or "")})
    finally:
        dr.demo_fallback = real_fallback
        s = search._searcher
        if s is not None and hasattr(s.store, "close"):
            s.store.close()
        search._searcher = None
    return rows


def summarize(rows: list[dict], answers: list[str], refusals: list[str]) -> dict:
    by = {r["question"]: r for r in rows}
    return {
        "n_questions": len(rows),
        "answers_ok": sum(1 for q in answers if by.get(q, {}).get("kind") == "answer" and by[q]["citations"] > 0),
        "answers_expected": len(answers),
        "refusals_ok": sum(1 for q in refusals if by.get(q, {}).get("kind") == "refuse"),
        "refusals_expected": len(refusals),
        "missed_calls": sum(r["missed_calls"] for r in rows),
        "stale_questions": sorted(r["question"] for r in rows if r["missed_calls"]),
        "fake_answers": sum(1 for r in rows if r["fake_answer"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="결과 JSON을 쓸 파일")
    ap.add_argument("--pg-url", default=os.environ.get("PROVENA_D5_PG_URL", ""), help="임시 DB를 만들 Postgres 관리 주소(기본: PROVENA_D5_PG_URL)")
    args = ap.parse_args(argv)
    if not args.pg_url:
        print("Postgres 주소가 없습니다(PROVENA_D5_PG_URL 또는 --pg-url).")
        return 2
    import tempfile

    import psycopg

    answers, refusals = readme_questions()
    workdir = Path(tempfile.mkdtemp(prefix="provena-ci-current-"))
    url, name = make_db(args.pg_url, workdir)
    try:
        per_path = {}
        for label, budget in PATHS:
            rows = run_questions(url, budget)
            per_path[label] = {"summary": summarize(rows, answers, refusals), "rows": rows}
    finally:
        with psycopg.connect(args.pg_url, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    commit = ""
    try:
        import subprocess

        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    result = {"meta": {"kind": "ci_current_keyless_replay", "commit": commit, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "note": "현재 코드의 질문 그래프를 키 없는 데모 재생으로 돌린 0원 평가. LLM·Voyage·운영 호출 없음"},
              "paths": per_path}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for label, p in per_path.items():
        print(label, json.dumps(p["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main(sys.argv[1:]))
