"""한국어 질문 → 영어 검색어(keywords)·영어 문장(sentence) (docs/specs/search.md).

순서: ① 번역 장부(query_translations, 열쇠 = 질문 sha256 + 모델 이름)에 있으면 그 값 ② 없으면 backend/services/llm.py
`get_chat_model()` 로 한 번 부르고(run_config로 비용 상한·Langfuse가 따라감) 검사를 통과하면 장부에 적기 ③ 실패하면 None
→ search()가 dense_ko로 내린다(Spec EC-01·EC-02).
- 프롬프트·검사는 1차 비교(evals/retrieval/experiment_v1.py `PROMPTS`·`valid_english`)와 같은 문장이다. 테스트가 대조한다.
- 데모 모드: get_chat_model()이 재생 모델을 준다. 녹화가 있으면 그 번역, 없으면 한국어 가짜 문장 → 검사에서 걸러져 None.
  가짜 문장은 장부에 적지 않는다.
- 모델 이름은 cost.normalize_model_id로 맞춘다(claude_cli·anthropic·openrouter가 같은 Haiku를 다른 이름으로 부를 수 있음).
- 질문 열쇠는 hashlib.sha256 (파이썬 hash()는 프로세스마다 달라 재생이 어긋난다, rag3-10).
"""
from __future__ import annotations

import concurrent.futures as cf
import contextvars
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Protocol

from backend.services import llm_trace, step_cost

log = logging.getLogger(__name__)

KINDS = ("keywords", "sentence")
PROMPTS = {
    "sentence": ("Translate the user's Korean question into one natural English question for searching an English company handbook. "
                 "Output only the English question on one line, no explanation. Keep product names, codes and numbers as they are."),
    "keywords": ("Rewrite the user's Korean question as English search keywords for an English company handbook. "
                 "Output only the English keywords on one line, no explanation. Keep product names, codes and numbers as they are."),
}
TIMEOUT_S = 15.0     # 11/1 실측(claude_cli Haiku, v1 30문항×2): keywords p95 8.3초·최대 9.6초 → 10초면 정상 호출이 잘린다. 최대값 + 여유
ATTEMPTS = 2         # 첫 호출 + 재시도 1회 (Spec EC-02)
_pool = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")
# 원 하위 질문(`GRAPH_KEEP_SUBJECT_UNION`) 번역 전용 일꾼. 처음 쓸 때 만든다. 위 일꾼(전체 질문 + 하위 질문 최대 4개)에 줄 서지 않게 따로 둔다
_side_pool: cf.ThreadPoolExecutor | None = None
_side_lock = threading.Lock()
_on_side: contextvars.ContextVar[bool] = contextvars.ContextVar("translate_on_side_pool", default=False)


def _pool_now() -> cf.ThreadPoolExecutor:
    global _side_pool
    if not _on_side.get():
        return _pool
    with _side_lock:
        if _side_pool is None:
            _side_pool = cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="translate_alt")
        return _side_pool


def on_side_pool(fn, *args):
    """`fn(*args)`를 부르는 동안 번역 호출이 원 하위 질문 전용 일꾼을 쓰게 한다(`search.Searcher._translate_one`의 side)."""
    token = _on_side.set(True)
    try:
        return fn(*args)
    finally:
        _on_side.reset(token)


def query_sha(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def valid_english(text: str) -> bool:
    """번역으로 쓸 수 있나: 한글이 없고, 메일 주소가 없고, 지시문을 되풀이하지 않는다(experiment_v1과 같은 규칙)."""
    t, low = text.strip(), text.strip().lower()
    echo = low.startswith(("output only", "translate the user", "rewrite the user")) or "company handbook" in low
    return bool(t) and not re.search("[가-힣]", t) and not re.search(r"\S+@\S+\.\S+", t) and not echo


def model_id() -> str:
    """번역 장부의 모델 이름. llm.py가 고를 모델과 같은 규칙으로 정하고 단가표 이름으로 맞춘다."""
    from backend.services.cost import normalize_model_id
    from backend.services.llm import DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENROUTER_MODEL
    provider = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()
    if not model:
        model = DEFAULT_OPENROUTER_MODEL if provider == "openrouter" else DEFAULT_ANTHROPIC_MODEL
    return normalize_model_id(model)


class TranslationStore(Protocol):
    def get_translation(self, query_sha256: str, model: str) -> dict | None: ...
    def put_translation(self, query_sha256: str, model: str, kind: str, text: str) -> None: ...


@dataclass
class Result:
    text: str | None
    source: str      # stored | llm | demo_no_record | invalid | timeout | error | cost_cap


def _first_line(content) -> str:
    text = content if isinstance(content, str) else "".join(
        p.get("text", "") if isinstance(p, dict) else str(p) for p in (content or []))
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _call(query: str, kind: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.services.llm import finish_run, get_chat_model, run_config
    cfg = run_config("search_translate", metadata={"kind": kind})
    try:
        msg = get_chat_model().invoke([SystemMessage(PROMPTS[kind]), HumanMessage(query)], config=cfg)
    finally:
        summary = finish_run(cfg)
        meter = step_cost.current()       # `/chat` 요청 안이면 번역 호출의 비용·토큰도 그 요청의 단계별 합에 보탠다(요청의 `usage`에는 들어가지 않는 별도 집계)
        if meter is not None:
            meter.merge_steps(summary.get("cost_by_step") or {})
    return _first_line(msg.content)


def translate(query: str, kind: str, store: TranslationStore, call=_call) -> Result:
    if kind not in KINDS:
        raise ValueError(f"모르는 번역 종류: {kind}")
    from backend.services.cost import CostCapExceeded
    from backend.services.llm import is_demo_mode
    qsha, model = query_sha(query), model_id()
    row = store.get_translation(qsha, model)
    if row and row.get(kind) and valid_english(row[kind]):
        return Result(row[kind], "stored")
    demo = is_demo_mode()
    reason = "error"
    for _ in range(1 if demo else ATTEMPTS):      # 재생은 같은 입력에 같은 답이라 다시 불러도 소용없다
        try:
            text = _pool_now().submit(step_cost.bind(llm_trace.bind(call)), query, kind).result(timeout=TIMEOUT_S)
        except cf.TimeoutError:
            reason = "timeout"
            continue
        except CostCapExceeded:
            return Result(None, "cost_cap")
        except Exception as e:  # noqa: BLE001 - 번역이 실패해도 검색은 dense_ko로 이어 간다(Spec EC-02)
            log.warning("번역 호출 실패(%s): %s", kind, e)
            reason = "error"
            continue
        if valid_english(text):
            try:
                store.put_translation(qsha, model, kind, text)
            except Exception as e:  # noqa: BLE001  번역은 이미 끝났다. 장부에 못 적어도 검색은 이어 간다(다음 번에 다시 번역한다)
                log.warning("번역 장부 저장 실패: %s", type(e).__name__)
            return Result(text, "llm")
        reason = "demo_no_record" if demo else "invalid"
    return Result(None, reason)
