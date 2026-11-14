"""데모 질문을 실제 모델로 돌려 응답을 녹화한다(`data/demo_replay/recorded.jsonl`). 키가 있는 사람이 한 번 돌리면 키 없는 데모가 그 응답을 재생한다.

사용(환경 변수는 이름만): `LLM_API_KEY`, `LLM_PROVIDER`(+`LLM_MODEL`), `VOYAGE_API_KEY`, `DATABASE_URL`(색인을 적재한 새 Postgres)을 프로세스 환경에 둔다.
`python -m backend.services.demo_record --questions data/demo_replay/questions.txt [--out data/demo_replay]`
녹화 전에 `data/demo_replay/recorded.jsonl`을 치운다(남아 있으면 새 응답이 변형으로 섞인다). 저장소 밖 실행기(`run_demo_rerecord.ps1`)가 새 Postgres 준비부터
녹화, 시험까지 한다. 다 돌린 뒤 `python -m pytest -m demo_replay`로 녹화가 현재 코드와 맞는지 본다(tests/test_demo_replay_fresh.py).

비용(2026-11-10 추정): 질문 하나가 LLM을 평균 약 10회(배포 측정 50문항 평균 9.98회) 부르고 약 0.005달러(claude-haiku-5-5, 입력 0.10·출력 0.50달러/100만 토큰)다.
`data/demo_replay/questions.txt`의 9개 질문은 약 90~117회, 약 0.05달러(최대 관측 질문당 0.013달러로 잡으면 0.12달러 이하)이고 Voyage 질문 임베딩은 0.0001달러 미만이다.

2026-11-13 확장: 평가셋 v2 50건(기준일 포함)도 같이 녹화해 CI의 현재 코드 평가(`evals/ci_current_eval.py`)가 재생하게 한다. 질문 목록은 `python evals/ci_current_eval.py --export-questions <파일.jsonl>`이 만들고(데모 9 + v2 50 = 59개),
`--max-total-usd <달러>`는 전체 비용 상한(닿으면 남은 질문은 돌리지 않고 종료 코드 3), `--report <파일>`은 녹화된 질문과 비용을 JSON으로 남긴다(`python evals/ci_current_eval.py --write-v2-manifest <report>`가 `data/demo_replay/v2_recorded.json`을 만든다).
비용 추정은 평가셋 v2 운영 측정 150요청 합 1.1419달러(질문당 0.007613달러, `evals/results/deploy_latency_provena-api-00047-wjn/summary.md`)로 59개에 약 0.45달러다. 저장소 밖 실행기 `step_record.ps1`이 이 전 과정을 한다.

질문 파일: `.txt`(한 줄에 한 질문, `#` 줄은 주석), `.jsonl`(줄마다 {"question", "org"?, "as_of"?}), `.json`(같은 모양의 목록 또는 문자열 목록).
서버(`/chat`)와 같은 질문 그래프(`backend.main.build_question_graph`, 서비스 설정 61.51 포함)를 체크포인터·Store만 메모리로 두고 돌린다. 검색도 서버와 같은 Postgres 경로다
(numpy 저장소는 DB와 검색 결과가 달라 이 녹화는 데모 재생과 키가 맞지 않는다). 모든 LLM 호출은 `llm.py`의 `get_chat_model()`을 거치고,
`LLM_RECORD=1`(이 CLI가 켠다)이면 녹화 래퍼가 요청 키 -> 응답을 쓴다. 재생은 같은 검색 결과(같은 색인, 번역 장부가 빈 새 DB)에서만 맞는다.
금액 구간 조회(`SEARCH_RANGE_N`)는 서비스·키 없는 데모와 같은 기본값(3)으로 녹화한다(직접 준 값이 있으면 그 값. 재생할 때도 같은 값이어야 키가 맞는다).
데모 모드(키 없음 또는 DEMO_MODE=1)에서는 실행을 거부한다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_questions(path: Path | str) -> list[dict]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    rows: list[Any]
    if p.suffix == ".json":
        rows = json.loads(text)
    elif p.suffix == ".jsonl":
        rows = [json.loads(x) for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")]
    else:
        rows = [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")]
    out = []
    for r in rows:
        d = {"question": r} if isinstance(r, str) else dict(r)
        if isinstance(d.get("question"), str) and d["question"].strip():
            out.append({"question": d["question"].strip(), "org": d.get("org"), "as_of": d.get("as_of")})
    return out


def build_default_graph(search: str = "real"):
    """서버(`/chat`)와 같은 질문 그래프(`backend.main.build_question_graph`: 서비스 설정 61.51, 결정표, 합동 검토). 체크포인터·Store·답 저장소만 메모리로 둔다.

    검색은 서버와 같은 `backend.rag.retrieve.search`라서 `DATABASE_URL`의 Postgres(색인이 적재된 DB)가 필요하다. 서비스 설정은 환경 변수로 채운 채로 두고
    되돌리지 않는다(이 프로세스는 녹화만 한다). 모델은 `SharedChatModel`이 처음 부를 때 `get_chat_model()`로 만든다."""
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.graph.recall.runtime import make_answer_store
    from backend.graph.service_profile import apply_service_profile
    from backend.main import build_question_graph

    if search not in ("real", "auto"):
        raise ValueError("서버와 같은 검색(real)만 녹화할 수 있다. 가짜 검색으로 만든 녹화는 데모 재생과 키가 맞지 않는다")
    apply_service_profile()
    state = SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                            store=InMemoryStore(), answer_store=make_answer_store(None))
    return build_question_graph(state)


def record_questions(questions: list[dict], *, graph: Any = None, search: str = "real", max_total_usd: float | None = None) -> dict:
    """질문마다 그래프를 한 번 돌린다. `graph`를 주면 그것을(시험용), 아니면 서버와 같은 기본 그래프를 쓴다.
    `max_total_usd`를 주면 지금까지 쓴 LLM 비용(질문마다 `finish_run`이 센 값의 합)이 이 값 이상일 때 다음 질문부터는 돌리지 않고 `skipped`에 남긴다
    (질문당 상한 `LLM_COST_CAP_USD`와 별개인 전체 상한. 이미 돌고 있는 질문은 끊지 않으므로 전체 비용은 상한을 질문 하나 분량까지 넘길 수 있다).
    돌려주는 값: {"questions", "ok", "failed", "new_recordings", "errors", "recorded", "skipped", "total_cost_usd", "stopped_by_cap"}.
    `new_recordings`는 녹화 폴더의 요청 키 수 증가분, `recorded`는 끝까지 녹화된 질문({"question", "as_of"})이다."""
    from backend.services.demo_replay import get_store
    from backend.services.llm import finish_run, run_config

    if graph is None:
        graph = build_default_graph(search)
    before = len(get_store())
    ok, errors, recorded, skipped, spent = 0, [], [], [], 0.0
    for q in questions:
        if max_total_usd is not None and spent >= max_total_usd:
            skipped.append(q["question"])
            continue
        tid = f"demo-record-{uuid.uuid4().hex[:8]}"
        cfg = run_config("demo_record", thread_id=tid, configurable={"thread_id": tid}, metadata={"purpose": "demo_record"})
        try:
            graph.invoke({"question": q["question"], "user_id": "demo-record", "thread_id": tid, "org": q.get("org"), "as_of": q.get("as_of")}, cfg)
            ok += 1
            recorded.append({"question": q["question"], "as_of": q.get("as_of")})
        except Exception as e:  # noqa: BLE001 - 한 질문의 실패가 나머지 녹화를 막지 않는다
            errors.append({"question": q["question"], "error": f"{type(e).__name__}: {e}"[:200]})
            log.warning("녹화 실패: %s -> %s", q["question"][:40], e)
        finally:
            spent += float((finish_run(cfg) or {}).get("cost_usd") or 0.0)
    return {"questions": len(questions), "ok": ok, "failed": len(errors), "new_recordings": len(get_store()) - before, "errors": errors,
            "recorded": recorded, "skipped": skipped, "total_cost_usd": round(spent, 6), "stopped_by_cap": bool(skipped)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="데모 질문을 실제 모델로 돌려 응답을 녹화한다")
    p.add_argument("--questions", type=Path, required=True, help="질문 파일(.txt/.jsonl/.json)")
    p.add_argument("--out", type=Path, default=None, help="녹화 폴더(기본 data/demo_replay 또는 DEMO_REPLAY_DIR)")
    p.add_argument("--search", choices=("real", "auto"), default="real", help="검색 경로. 서버와 같은 Postgres 검색만 지원한다(두 값은 같다)")
    p.add_argument("--max-total-usd", type=float, default=None, help="전체 LLM 비용 상한(달러). 이 값 이상 쓰면 남은 질문은 돌리지 않는다(종료 코드 3). 질문당 상한은 LLM_COST_CAP_USD")
    p.add_argument("--report", type=Path, default=None, help="결과(녹화된 질문, 실패, 비용)를 JSON으로 쓸 파일")
    a = p.parse_args(argv)
    if a.out is not None:
        os.environ["DEMO_REPLAY_DIR"] = str(a.out)
    os.environ["LLM_RECORD"] = "1"
    from backend.services.llm import is_demo_mode

    if is_demo_mode():
        print("녹화는 실제 LLM이 필요합니다: LLM_API_KEY를 설정하고 DEMO_MODE를 끄세요.", file=sys.stderr)
        return 2
    if not (os.environ.get("DATABASE_URL") or "").strip():
        print("DATABASE_URL이 없습니다: 색인을 적재한 새 Postgres가 필요합니다(서버와 같은 검색 경로).", file=sys.stderr)
        return 2
    questions = load_questions(a.questions)
    if not questions:
        print(f"질문이 없습니다: {a.questions}", file=sys.stderr)
        return 2
    rep = record_questions(questions, search=a.search, max_total_usd=a.max_total_usd)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.report is not None:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if rep["failed"]:
        return 1
    return 3 if rep["stopped_by_cap"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
