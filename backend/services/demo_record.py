"""데모 질문을 실제 모델로 돌려 응답을 녹화한다(`data/demo_replay/recorded.jsonl`). 키가 있는 사람이 한 번 돌리면 키 없는 데모가 그 응답을 재생한다.

사용: `LLM_API_KEY=... python -m backend.services.demo_record --questions data/demo_replay/questions.txt [--out data/demo_replay] [--search real|fake]`

질문 파일: `.txt`(한 줄에 한 질문, `#` 줄은 주석), `.jsonl`(줄마다 {"question", "org"?, "as_of"?}), `.json`(같은 모양의 목록 또는 문자열 목록).
질문 그래프 전체(분류, 재작성, 판정, 답 작성, 근거 판정, 결정표·합동 검토 경로)를 인메모리 저장소로 돌린다. 모든 LLM 호출은 `llm.py`의 `get_chat_model()`을 거치고,
`LLM_RECORD=1`(이 CLI가 켠다)이면 녹화 래퍼가 요청 키 -> 응답을 쓴다. 재생은 같은 검색 결과(같은 색인)에서만 맞는다: 녹화와 데모 서버가 같은 `data/index`를 써야 한다.
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


def build_default_graph(llm: Any, search: str = "auto"):
    """저장소를 인메모리로 둔 질문 그래프(결정표·합동 검토 포함). 실제 서버와 같은 `build_app`을 쓰되 DB는 건드리지 않는다."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.app import build_app
    from backend.graph import InMemoryAnswerStore

    if search == "auto":
        from backend.main import default_search_fn

        search_fn = default_search_fn()
    elif search == "real":
        from backend.rag.retrieve import search as search_fn
    else:
        from backend.rag.fake_search import fake_search as search_fn
    app = build_app(llm=llm, search_fn=search_fn, checkpointer=InMemorySaver(), store=InMemoryStore(), answer_store=InMemoryAnswerStore())
    return app.question_graph


def record_questions(questions: list[dict], *, graph: Any = None, llm: Any = None, search: str = "auto") -> dict:
    """질문마다 그래프를 한 번 돌린다. `graph`를 주면 그것을(시험용), 아니면 `llm`(없으면 `get_chat_model()`)으로 만든 기본 그래프를 쓴다.
    돌려주는 값: {"questions", "ok", "failed", "new_recordings", "errors"}. `new_recordings`는 `RecordingChatModel`이 새로 쓴 줄 수(알 수 있을 때)."""
    from backend.services.llm import finish_run, get_chat_model, run_config

    if graph is None:
        llm = llm if llm is not None else get_chat_model()
        graph = build_default_graph(llm, search)
    ok, errors = 0, []
    for q in questions:
        tid = f"demo-record-{uuid.uuid4().hex[:8]}"
        cfg = run_config("demo_record", thread_id=tid, configurable={"thread_id": tid}, metadata={"purpose": "demo_record"})
        try:
            graph.invoke({"question": q["question"], "user_id": "demo-record", "thread_id": tid, "org": q.get("org"), "as_of": q.get("as_of")}, cfg)
            ok += 1
        except Exception as e:  # noqa: BLE001 - 한 질문의 실패가 나머지 녹화를 막지 않는다
            errors.append({"question": q["question"], "error": f"{type(e).__name__}: {e}"[:200]})
            log.warning("녹화 실패: %s -> %s", q["question"][:40], e)
        finally:
            finish_run(cfg)
    new = getattr(llm, "recorded", None)
    return {"questions": len(questions), "ok": ok, "failed": len(errors), "new_recordings": new, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="데모 질문을 실제 모델로 돌려 응답을 녹화한다")
    p.add_argument("--questions", type=Path, required=True, help="질문 파일(.txt/.jsonl/.json)")
    p.add_argument("--out", type=Path, default=None, help="녹화 폴더(기본 data/demo_replay 또는 DEMO_REPLAY_DIR)")
    p.add_argument("--search", choices=("auto", "real", "fake"), default="auto", help="검색 경로(기본 auto = 서버와 같은 선택)")
    a = p.parse_args(argv)
    if a.out is not None:
        os.environ["DEMO_REPLAY_DIR"] = str(a.out)
    os.environ["LLM_RECORD"] = "1"
    os.environ.setdefault("DECISION_SEED", "on")  # 재생(데모 모드)은 결정표 시드를 넣어 추출 프롬프트에 업무 종류 후보가 붙는다. 녹화도 같은 입력이어야 키가 맞는다
    from backend.services.llm import get_chat_model, is_demo_mode

    if is_demo_mode():
        print("녹화는 실제 LLM이 필요합니다: LLM_API_KEY를 설정하고 DEMO_MODE를 끄세요.", file=sys.stderr)
        return 2
    questions = load_questions(a.questions)
    if not questions:
        print(f"질문이 없습니다: {a.questions}", file=sys.stderr)
        return 2
    rep = record_questions(questions, llm=get_chat_model(), search=a.search)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if not rep["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
