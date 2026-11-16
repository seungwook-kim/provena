"""현재 코드로 0원(키 없는 데모 재생, 오프라인) 평가를 돌려 결과 파일을 남긴다. `evals/ci_compare.py --current <결과 파일>`이 이 파일을 기준값과 비교한다.

    PROVENA_D5_PG_URL=postgresql://app:pw@127.0.0.1:5432/postgres python evals/ci_current_eval.py --out evals/results/ci_current_<날짜>/result.json

왜: 지금까지 CI 비교는 커밋된 옛 측정 결과 파일만 읽어서, 현재 코드가 바뀌어도 점수가 그대로였다. 이 도구는 현재 코드의 질문 그래프(서비스 설정 61.51, 서버와 같은 Postgres 검색)를
키·네트워크 없이 README의 데모 질문 9개(인용 답 7, 거절 2)에 돌리고, 녹화(`data/demo_replay/recorded.jsonl`)에서 찾지 못한 LLM 요청 수와 결과를 센다.
LLM·Voyage·운영 호출은 없다(`LLM_API_KEY`, `VOYAGE_API_KEY` 등을 이 프로세스에서 지우고 돌린다). 임시 DB를 만들어 색인을 적재하고 끝나면 그 DB만 지운다.

지표(질문 그래프 한 번 돌린 값, 추론 답을 보내는 경로와 빠른 답만 보내는 경로 둘 다):
- `answers_ok`: 인용 답이어야 하는 질문 중 실제로 인용 답이 나온 수
- `refusals_ok`: 거절이어야 하는 질문 중 실제로 거절이 나온 수
- `missed_calls`: 녹화에 없는 LLM 요청과 질문 벡터 수(0이 아니면 프롬프트·검색·입력이 바뀌어 녹화가 오래된 것)
- `fake_answers`: 녹화 답이 아니라 발췌형 대체 답이 나온 수

전체 평가셋 확장(2026-11-13, 2026-11-16 녹화 위치 변경): 평가셋 v2 50건(`evals/dataset_v2.jsonl`, `as_of`는 평가셋 값)도 녹화해 두었으면(`evals/ci_replay_v2/v2_recorded.json`이 있으면)
데모 질문 9개에 더해 그 질문들도 돌려 `paths.<경로>.v2`에 따로 낸다(관련 질문 중 인용 답이 나온 수, 비관련 질문 중 거절이 나온 수, 녹화에 없는 요청, 발췌형 대체 답).
`v2_recorded.json`이 없으면 이 확장은 하지 않고 9개만 돈다(위 지표 그대로). `--require-v2`를 주면 그때는 실패(종료 코드 1)한다.
50건 녹화는 서비스 이미지에 들어가지 않는 `evals/ci_replay_v2/`에 둔다(Dockerfile은 `data/`를 이미지에 복사하고 `evals/`는 복사하지 않는다). 데모 녹화(`data/demo_replay/`)와 섞지 않고,
50건은 따로 만든 새 DB(번역 장부가 빈 상태)와 이 폴더의 녹화로 돈다. v2 질문 3개(CVSS, CUD, EOC)는 데모 질문과 글이 같아 분류·번역·질문 벡터 요청 키가 데모 녹화와 겹치므로,
같은 폴더나 같은 DB를 쓰면 한쪽 녹화가 다른 쪽 재생을 바꾼다.

    python evals/ci_current_eval.py --export-questions <파일.jsonl> --only-v2          # 녹화할 v2 50건(as_of 포함)을 demo_record 입력 형식으로 쓴다(--only-v2 없으면 데모 9 + v2 50)
    python -m backend.services.demo_record --questions <파일.jsonl> --out evals/ci_replay_v2 --max-total-usd <달러> --report <report.json>   # 키와 색인 적재한 새 DB 필요(유료)
    python evals/ci_current_eval.py --write-v2-manifest <report.json>               # demo_record --report 결과에서 evals/ci_replay_v2/v2_recorded.json을 만든다
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
DATASET_V2 = ROOT / "evals" / "dataset_v2.jsonl"
V2_REPLAY_DIR = ROOT / "evals" / "ci_replay_v2"   # 평가셋 v2 50건 녹화(*.jsonl). 서비스 이미지 밖(Dockerfile은 evals/를 복사하지 않는다)
V2_MANIFEST = V2_REPLAY_DIR / "v2_recorded.json"   # 평가셋 v2 질문을 녹화했다는 표지. 없으면 데모 질문 9개만 돈다
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


def normalize_as_of(value: str | None) -> str | None:
    """평가셋의 `2023-05`처럼 달만 있는 값은 그 달 마지막 날로(evals/latency/deploy_latency.py와 같은 규칙. 녹화와 재생이 같은 값을 보내야 키가 맞는다)."""
    import calendar
    import re

    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}", value):
        y, m = int(value[:4]), int(value[5:])
        return f"{value}-{calendar.monthrange(y, m)[1]:02d}"
    return value


def v2_questions(path: Path = DATASET_V2) -> list[dict]:
    """평가셋 v2의 질문: {"id", "question", "as_of"(정규화), "kind"(relevant/irrelevant)}. 평가셋 순서."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [{"id": r["id"], "question": r["input"].strip(), "as_of": normalize_as_of(r.get("as_of")), "kind": r["kind"]} for r in rows]


def question_set_sha256(items: list[dict]) -> str:
    """질문 집합의 해시: 문항 번호 순으로 `번호<TAB>질문<TAB>기준일` 줄을 이어 해시한다. 평가셋 질문이 바뀌면 녹화한 집합과 달라진다."""
    import hashlib

    lines = [f"{it['id']}\t{it['question']}\t{it.get('as_of') or ''}" for it in sorted(items, key=lambda x: x["id"])]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def build_v2_manifest(report: dict, dataset: Path = DATASET_V2) -> dict:
    """`demo_record --report` 결과에서 평가셋 v2 질문 중 끝까지 녹화된 것만 모아 manifest를 만든다."""
    recorded = {(r["question"], r.get("as_of")) for r in report.get("recorded", [])}
    ids = [it for it in v2_questions(dataset) if (it["question"], it["as_of"]) in recorded]
    return {"dataset": dataset.name, "n": len(ids), "ids": [it["id"] for it in ids], "question_set_sha256": question_set_sha256(ids),
            "total_cost_usd": report.get("total_cost_usd"), "note": "평가셋 v2 질문 중 데모 녹화(recorded.jsonl)에 응답이 있는 문항. ci_current_eval.py가 이 문항들을 현재 코드로 다시 돌린다"}


def load_v2_selection(manifest: Path = V2_MANIFEST, dataset: Path = DATASET_V2) -> tuple[list[dict], str | None]:
    """녹화해 둔 평가셋 v2 질문과 문제 설명. manifest가 없으면 ([], None)(9개만 도는 기존 동작). 있는데 평가셋과 어긋나면 ([], 이유)."""
    if not manifest.is_file():
        return [], None
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in v2_questions(dataset)}
    missing = [i for i in meta.get("ids", []) if i not in by_id]
    if missing:
        return [], f"{manifest.name}의 문항 번호 {missing[:5]}이(가) {dataset.name}에 없다(평가셋이 바뀌었다). 다시 녹화해야 한다"
    items = [by_id[i] for i in meta.get("ids", [])]
    if not items or question_set_sha256(items) != meta.get("question_set_sha256"):
        return [], f"{manifest.name}의 질문 해시가 {dataset.name}의 같은 번호 질문과 다르다(질문 글 또는 기준일이 바뀌었다). 다시 녹화해야 한다"
    return items, None


def export_questions(out: Path, only_v2: bool = False) -> int:
    """녹화할 질문(데모 질문 파일 + 평가셋 v2 전체, 기준일 포함)을 `demo_record --questions`가 읽는 jsonl로 쓴다. 같은 질문·기준일은 한 번만.
    `only_v2`면 평가셋 v2 50건만(평가셋 순서) 쓴다. 50건 녹화는 데모 녹화와 다른 폴더(`V2_REPLAY_DIR`)에 따로 만든다."""
    from backend.services.demo_record import load_questions

    demo = [] if only_v2 else load_questions(REPLAY_DIR / "questions.txt")
    seen, rows = set(), []
    for q in [*demo, *({"question": it["question"], "org": None, "as_of": it["as_of"]} for it in v2_questions())]:
        key = (q["question"], q.get("as_of"))
        if key not in seen:
            seen.add(key)
            rows.append({"question": q["question"], "as_of": q.get("as_of")})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


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


def demo_todo() -> list[dict]:
    """데모 질문(질문 파일)의 할 일 줄."""
    from backend.services.demo_record import load_questions

    return [{"set": "demo", "id": None, "question": x["question"], "as_of": None, "expected": None} for x in load_questions(REPLAY_DIR / "questions.txt")]


def v2_todo(v2_items: list[dict]) -> list[dict]:
    """녹화해 둔 평가셋 v2 질문의 할 일 줄(평가셋 순서, 녹화 때와 같은 순서라 번역 장부가 같은 차례로 쌓인다)."""
    return [{"set": "v2", "id": it["id"], "question": it["question"], "as_of": it["as_of"], "expected": it["kind"]} for it in v2_items]


def run_questions(db_url: str, budget: str, v2_items: list[dict] | None = None, *, todo: list[dict] | None = None, replay_dir: Path = REPLAY_DIR) -> list[dict]:
    """할 일 줄(`todo`, 없으면 데모 질문과 주어진 `v2_items`)을 현재 코드의 질문 그래프에 돌린 줄. 줄의 `set`은 demo 또는 v2.
    `replay_dir`은 이번 실행이 재생할 녹화 폴더다(데모는 `data/demo_replay`, 50건은 `evals/ci_replay_v2`)."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.graph.recall.runtime import make_answer_store
    from backend.graph.service_profile import service_profile
    from backend.main import build_question_graph
    from backend.services import demo_replay as dr
    from backend.services.llm import finish_run, run_config

    search = importlib.import_module("backend.rag.retrieve.search")
    for name in ENV_CLEAR:
        os.environ.pop(name, None)
    os.environ["DATABASE_URL"] = db_url
    os.environ["DEMO_REPLAY_DIR"] = str(replay_dir)
    os.environ["GRAPH_ANSWER_BUDGET_S"] = budget
    missed: list[str] = []

    class SpyStore(dr.ReplayStore):
        def get(self, key):
            row = super().get(key)
            if row is None:
                missed.append("query_embedding")
            return row

    dr._stores[str(replay_dir)] = SpyStore(replay_dir)
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
            if todo is None:
                todo = demo_todo() + v2_todo(v2_items or [])
            for t in todo:
                q = t["question"]
                missed.clear()
                tid = "ci-current-" + uuid.uuid4().hex[:8]
                cfg = run_config("ci_current_eval", thread_id=tid, configurable={"thread_id": tid})
                try:
                    out = graph.invoke({"question": q, "user_id": "ci-current", "thread_id": tid, "org": None, "as_of": t["as_of"]}, cfg)
                finally:
                    finish_run(cfg)
                rows.append({"set": t["set"], "id": t["id"], "expected": t["expected"], "question": q, "kind": out.get("kind"), "citations": len(out.get("citations") or []),
                             "missed_calls": len(missed), "missed_roles": sorted(set(missed)), "fake_answer": FAKE_ANSWER_MARK in (out.get("answer") or "")})
    finally:
        dr.demo_fallback = real_fallback
        s = search._searcher
        if s is not None and hasattr(s.store, "close"):
            s.store.close()
        search._searcher = None
    return rows


def summarize_v2(rows: list[dict]) -> dict:
    """평가셋 v2 질문 줄의 요약: 관련 질문 중 인용 답이 나온 수, 비관련 질문 중 거절이 나온 수, 녹화에 없는 요청, 발췌형 대체 답."""
    rows = [r for r in rows if r.get("set") == "v2"]
    rel = [r for r in rows if r["expected"] == "relevant"]
    irr = [r for r in rows if r["expected"] == "irrelevant"]
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[str(r["kind"])] = kinds.get(str(r["kind"]), 0) + 1
    return {
        "n_questions": len(rows),
        "relevant_total": len(rel),
        "relevant_answered": sum(1 for r in rel if r["kind"] == "answer" and r["citations"] > 0),
        "irrelevant_total": len(irr),
        "irrelevant_refused": sum(1 for r in irr if r["kind"] == "refuse"),
        "kinds": dict(sorted(kinds.items())),
        "missed_calls": sum(r["missed_calls"] for r in rows),
        "stale_questions": sorted(f"#{r['id']}" for r in rows if r["missed_calls"]),
        "fake_answers": sum(1 for r in rows if r["fake_answer"]),
    }


def summarize(rows: list[dict], answers: list[str], refusals: list[str]) -> dict:
    rows = [r for r in rows if r.get("set", "demo") == "demo"]   # 데모 질문 9개의 지표(평가셋 v2 줄은 summarize_v2)
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
    ap.add_argument("--out", type=Path, default=None, help="결과 JSON을 쓸 파일(평가를 돌릴 때 필요)")
    ap.add_argument("--pg-url", default=os.environ.get("PROVENA_D5_PG_URL", ""), help="임시 DB를 만들 Postgres 관리 주소(기본: PROVENA_D5_PG_URL)")
    ap.add_argument("--export-questions", type=Path, default=None, help="녹화할 질문(데모 9 + 평가셋 v2 50, 기준일 포함)을 demo_record 입력 jsonl로 쓰고 끝낸다(평가 안 함)")
    ap.add_argument("--only-v2", action="store_true", help="--export-questions가 평가셋 v2 50건만 쓴다(50건 녹화는 evals/ci_replay_v2에 따로 만든다)")
    ap.add_argument("--write-v2-manifest", type=Path, default=None, metavar="REPORT", help="demo_record --report 결과에서 evals/ci_replay_v2/v2_recorded.json을 만들고 끝낸다(평가 안 함)")
    ap.add_argument("--manifest-out", type=Path, default=V2_MANIFEST, help="--write-v2-manifest가 쓸 파일(기본 evals/ci_replay_v2/v2_recorded.json)")
    ap.add_argument("--require-v2", action="store_true", help="평가셋 v2 50건 녹화가 없거나 평가셋과 어긋나면 평가하지 않고 실패한다(종료 코드 1)")
    args = ap.parse_args(argv)
    if args.export_questions is not None:
        print(f"녹화할 질문 {export_questions(args.export_questions, only_v2=args.only_v2)}개를 {args.export_questions}에 썼습니다.")
        return 0
    if args.write_v2_manifest is not None:
        manifest = build_v2_manifest(json.loads(args.write_v2_manifest.read_text(encoding="utf-8")))
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"평가셋 v2 녹화 manifest {manifest['n']}문항을 {args.manifest_out}에 썼습니다.")
        return 0 if manifest["n"] else 1
    if args.out is None:
        print("--out이 필요합니다.")
        return 2
    if not args.pg_url:
        print("Postgres 주소가 없습니다(PROVENA_D5_PG_URL 또는 --pg-url).")
        return 2
    import tempfile

    import psycopg

    answers, refusals = readme_questions()
    v2_items, v2_problem = load_v2_selection()
    if args.require_v2 and (not v2_items or v2_problem):
        print("평가셋 v2 50건 녹화가 필요합니다(--require-v2):", v2_problem or f"{V2_MANIFEST}가 없습니다")
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="provena-ci-current-"))
    made: list[str] = []
    try:
        # 데모 9개: 데모 녹화(data/demo_replay)와 그 질문만 적재한 DB. 두 경로(추론 답 보냄, 빠른 답만)를 같은 DB에서 차례로 돈다(번역 장부가 녹화 때처럼 쌓인다)
        url, name = make_db(args.pg_url, workdir / "demo")
        made.append(name)
        per_path = {label: {"rows": run_questions(url, budget, todo=demo_todo(), replay_dir=REPLAY_DIR)} for label, budget in PATHS}
        if v2_items:
            # 평가셋 v2 50건: 따로 만든 새 DB와 50건 녹화(evals/ci_replay_v2). 데모와 글이 같은 질문의 번역·질문 벡터가 데모 실행에서 섞이지 않게 한다
            url2, name2 = make_db(args.pg_url, workdir / "v2")
            made.append(name2)
            for label, budget in PATHS:
                per_path[label]["rows"] += run_questions(url2, budget, todo=v2_todo(v2_items), replay_dir=V2_REPLAY_DIR)
        for label, body in per_path.items():
            body["summary"] = summarize(body["rows"], answers, refusals)
            if v2_items:
                body["v2"] = summarize_v2(body["rows"])
    finally:
        with psycopg.connect(args.pg_url, autocommit=True) as c:
            for n in made:
                c.execute(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)")
    commit = ""
    try:
        import subprocess

        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    result = {"meta": {"kind": "ci_current_keyless_replay", "commit": commit, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "note": "현재 코드의 질문 그래프를 키 없는 데모 재생으로 돌린 0원 평가. LLM·Voyage·운영 호출 없음",
                       "v2_questions": len(v2_items), "v2_problem": v2_problem},
              "paths": per_path}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for label, p in per_path.items():
        print(label, json.dumps(p["summary"], ensure_ascii=False))
        if "v2" in p:
            print(label, "v2", json.dumps(p["v2"], ensure_ascii=False))
    if v2_problem:
        print("평가셋 v2 확장을 건너뜀:", v2_problem)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main(sys.argv[1:]))
