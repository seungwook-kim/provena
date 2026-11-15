"""요청 한 건의 단계별 비용·시간과 임베딩(Voyage) 사용량 집계. 숫자만 모으고 프롬프트·응답·질문 내용은 저장하지 않는다.

- 켜고 끄는 스위치 없이 항상 켠다. 요청당 메모리 dict 몇 개와 호출마다 덧셈 몇 번이라 추가 비용이 무시할 만하다.
- 단계(step) 이름은 `llm_trace.step_of`가 정한다(노드/표지. 예: `judge/judge`, `write_answer/answer`, `ground/grounding`, `search/decompose`, `classify/classify`).
  그래프 LLM 호출은 `cost.CostTracker`가 단계별로 쌓고(`CostTracker.by_step()`), 질문 번역 LLM 호출은 `translate._call`이 자기 `CostTracker` 합계를 이 요청 집계에 보탠다(`merge_steps`).
  번역은 요청의 `usage.cost_usd`(그래프 `CostTracker`)에 들어가지 않는 별도 호출이라 `cost_by_step`에만 나타난다. 두 값의 차이가 번역 몫이다.
- 임베딩: `rag/retrieve/embed.py`가 Voyage 응답의 `usage.total_tokens`를 `record_embed`로 넘긴다. 호출이 없으면(캐시 적중 등) 0이다.
  단가는 `llm_prices.json`의 `embeddings`(없으면 `DEFAULT_EMBED_USD_PER_MTOK`)이고 무료 한도는 반영하지 않은 환산값이다.
- 요청 경계는 contextvar다. `/chat`이 `begin()`으로 열고 `end()`로 닫는다. 다른 스레드로 넘길 때는 `bind(fn)`으로 집계 자리만 옮긴다
  (그래프 노드와 hedge, 하위 질문 병렬 검색은 `contextvars.copy_context()`를 써서 이미 따라온다).
- 거절 단계·사유 코드(`refuse_meta`)는 마지막으로 `kind`를 거절·되묻기로 쓴 그래프 노드 이름과 그 상태 값에서 읽는다.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# voyage-4 100만 토큰당 0.06달러, 계정당 처음 2억 토큰 무료. 출처: EVAL_REPORT.md 225행 부근의 단가 서술(2026-09-29 갱신본, Voyage 요금 공지 기준)과
# evals/safety/deploy_corpus_injection_check.py의 VOYAGE_USD_PER_MTOK = 0.06. 요금이 바뀌면 `llm_prices.json`의 `embeddings`만 고친다.
# 실제 청구는 무료 한도가 먼저 차감되므로 `embed_cost_usd`는 한도 없이 환산한 값이다.
DEFAULT_EMBED_USD_PER_MTOK = 0.06
DEFAULT_PRICES_FILE = Path(__file__).with_name("llm_prices.json")
CACHE_KEYS = ("cache_read_tokens", "cache_creation_tokens")   # 단계 행의 프롬프트 캐시 칸(`cost.CostTracker.by_step`). 입력 토큰을 나눈 값이다


@functools.lru_cache(maxsize=8)
def _embed_price(path: str, model: str) -> float:
    try:
        row = ((json.loads(Path(path).read_text(encoding="utf-8")).get("embeddings") or {}).get(model) or {})
        return float(row["input"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return DEFAULT_EMBED_USD_PER_MTOK


def embed_usd_per_mtok(model: str | None = None) -> float:
    """임베딩 모델의 100만 토큰당 달러. `llm_prices.json`(또는 LLM_PRICES_FILE)의 `embeddings.<모델>.input`, 없으면 `DEFAULT_EMBED_USD_PER_MTOK`. 파일은 경로마다 한 번만 읽는다."""
    return _embed_price(str(os.environ.get("LLM_PRICES_FILE") or DEFAULT_PRICES_FILE), model or "voyage-4")


class StepMeter:
    """요청 한 건의 집계. 여러 스레드가 함께 쓴다."""

    def __init__(self) -> None:
        self.steps: dict[str, dict] = {}   # 그래프 밖에서 보탠 단계(질문 번역). 그래프 단계는 `CostTracker`가 갖고 있다
        self.embed_tokens = 0
        self.embed_calls = 0
        self._lock = threading.Lock()

    def merge_steps(self, by_step: dict[str, dict]) -> None:
        with self._lock:
            for name, row in by_step.items():
                cur = self.steps.setdefault(name, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_s": 0.0})
                for k in cur:
                    if k not in CACHE_KEYS:   # 캐시 칸은 아래에서 한 번만 더한다(같은 단계를 두 번 합칠 때 두 번 더하지 않게)
                        cur[k] += row.get(k) or 0
                for k in CACHE_KEYS:   # 프롬프트 캐시 칸(`CostTracker.by_step`)은 들어온 행에 있을 때만 더한다
                    if k in row:
                        cur[k] = cur.get(k, 0) + (row.get(k) or 0)

    def add_embed(self, tokens: int) -> None:
        with self._lock:
            self.embed_calls += 1
            self.embed_tokens += max(int(tokens or 0), 0)

    def snapshot(self, graph_steps: dict[str, dict] | None = None) -> dict:
        """응답에 실을 칸. `graph_steps`는 그래프 `CostTracker.by_step()`."""
        with self._lock:
            merged: dict[str, dict] = {k: dict(v) for k, v in (graph_steps or {}).items()}
            for name, row in self.steps.items():
                cur = merged.setdefault(name, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_s": 0.0})
                for k in cur:
                    if k not in CACHE_KEYS:
                        cur[k] += row.get(k) or 0
                for k in CACHE_KEYS:
                    if k in row:
                        cur[k] = cur.get(k, 0) + (row.get(k) or 0)
            tokens, calls = self.embed_tokens, self.embed_calls
        for row in merged.values():
            row["cost_usd"], row["llm_s"] = round(row["cost_usd"], 8), round(row["llm_s"], 3)
        return {
            "cost_by_step": merged,
            "cost_by_step_total_usd": round(sum(r["cost_usd"] for r in merged.values()), 8),
            "embed_tokens": tokens,
            "embed_calls": calls,
            "embed_cost_usd": round(tokens * embed_usd_per_mtok() / 1_000_000, 8) if tokens else 0.0,
        }


_current: contextvars.ContextVar[StepMeter | None] = contextvars.ContextVar("step_meter", default=None)


def begin() -> tuple[StepMeter, contextvars.Token]:
    """요청을 시작할 때 부른다. 돌려준 토큰으로 `end`를 부른다."""
    meter = StepMeter()
    return meter, _current.set(meter)


def end(token: contextvars.Token) -> None:
    try:
        _current.reset(token)
    except ValueError:   # 다른 컨텍스트에서 닫혔다(연결이 끊긴 뒤 정리). 집계 자리는 스레드와 함께 사라진다
        pass


def current() -> StepMeter | None:
    return _current.get()


def record_embed(tokens: int) -> None:
    """Voyage 호출 한 번의 `usage.total_tokens`. 요청 밖(기동 때 워밍업, 색인 만들기)이면 아무 일도 하지 않는다."""
    m = _current.get()
    if m is not None:
        m.add_embed(tokens)


def usage_tokens(body: Any) -> int:
    """Voyage 응답 본문의 `usage.total_tokens`. 없거나 이상하면 0."""
    try:
        return max(int((body.get("usage") or {}).get("total_tokens") or 0), 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def bind(fn: Callable) -> Callable:
    """`fn`을 다른 스레드에서 돌려도 지금 요청의 집계에 남게 한다. 요청 밖이면 `fn`을 그대로 돌려준다."""
    meter = _current.get()
    if meter is None:
        return fn

    def run(*args: Any, **kwargs: Any) -> Any:
        token = _current.set(meter)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)

    return run


# 거절·되묻기 사유 코드: 상태의 `refuse_reason`(그래프가 정한 값)이 있으면 그대로, 없으면 단계와 상태에서 읽는다.
def refuse_meta(stage: str, kind: str | None, state: dict, messages: dict[str, str]) -> dict:
    """{"refuse_stage": 노드 이름, "refuse_reason": 코드}. `messages`는 {거절 문장: 코드}(build.py의 MSG_*)."""
    reason = state.get("refuse_reason")
    if not reason:
        if state.get("search_error"):
            reason = state["search_error"]            # unavailable | no_key | unknown_name
        elif state.get("decision_error"):
            reason = "decision_error"
        else:
            reason = messages.get(state.get("answer") or "")
        if not reason:
            reason = "clarify" if kind == "clarify" else "no_evidence"
    return {"refuse_stage": stage, "refuse_reason": str(reason)}


# 답 경로 기록(측정용). 검색·판정·답 고르기에서 코드가 정한 값만 싣는다: 하위 질문, 문맥 청크 id, 판정 구절이 든 청크 id(구절 글은 싣지 않는다), 답 후보의 인용과 고른 쪽, 인용 후처리 기록.
# 답 본문·초안·판정 이유 문장·판정 구절 글은 싣지 않는다. 상태를 읽기만 하므로 답 경로는 그대로다.
PATH_TEXT_WIDTH = 200
_PATH_STATS_LISTS = ("heading_terms", "heading_added")   # `search_stats` 중 숫자가 아니어도 싣는 칸(사전 등록 62.69 제목 경로 추가의 구와 더한 청크 id)
# candidates: 이 실행의 근거 확인 호출마다 후보 종류(reasoning | fast | answer | chosen | extra), 문맥(core | full), 넘긴 일부 답 값, 결론, 쓰였는지(사전 등록 62.67). partial_filter: 62.66 문장 빼기 결과
# switched_from, switched_to: 근거 확인 실패 뒤 이미 받쳐진 다른 후보를 쓴 경우의 후보 종류, switch_failed: 그 후보가 다시 거친 검사에서 걸린 곳(사전 등록 62.68)
_PATH_GROUNDING_KEYS = ("llm", "reason", "revised", "redrafted", "rejudge", "partial_route", "cite_expand", "cite_phrase", "head_owner", "ground_ahead",
                        "partial_filter", "candidates", "switched_from", "switched_to", "switch_failed",
                        "cite_phrase_head")   # cite_phrase_head: 62.70 L이 앞 청크로 바꿔 더한 기록({from, to})
# redraft: 답 다시 쓰기 기록 중 결과, 재판정, 일부 답 안내 결과(`partial_note`, 62.67), 넘겨받은 인용, 버린 인용만 싣는다. 다시 쓴 답 본문(`answer`)은 싣지 않는다(사전 등록 62.68)
_PATH_REDRAFT_KEYS = ("result", "rejudge", "partial_note", "carried", "dropped")


def redraft_row(redraft: dict) -> dict:
    """답 다시 쓰기 기록의 행. 버린 인용(`dropped`)은 모델이 낸 인용 값 그대로일 수 있어 청크 id(문자열 `chunk_id`)만 남긴다."""
    row = {k: redraft[k] for k in _PATH_REDRAFT_KEYS if k in redraft}
    if "dropped" in row:
        row["dropped"] = [d["chunk_id"] for d in row["dropped"] or [] if isinstance(d, dict) and isinstance(d.get("chunk_id"), str)]
    return row


def path_meta(state: dict) -> dict:
    """{"path": {...}}. 검색을 하지 않은 실행(도메인 밖, 결정표, 합동 검토)은 빈 dict다. 측정 도구(`evals/latency/deploy_latency.py`)가 행에 그대로 남긴다."""
    chunks = state.get("chunks")
    if not isinstance(chunks, list) or (not chunks and not state.get("sub_queries")):
        return {}
    best2 = state.get("best2_log") if isinstance(state.get("best2_log"), dict) else None
    grounding = state.get("grounding") if isinstance(state.get("grounding"), dict) else {}
    redraft = grounding.get("redraft") if isinstance(grounding.get("redraft"), dict) else None
    quotes = [[str(i) for i in q] for q in state.get("judge_quotes") or [] if isinstance(q, (list, tuple))]   # 사실마다 판정 구절이 든 청크 id(구절 글은 싣지 않는다)
    path = {
        "sub_queries": [str(s)[:PATH_TEXT_WIDTH] for s in state.get("sub_queries") or []],
        "decompose_source": state.get("decompose_source") or "",
        "context_ids": [c.get("chunk_id") for c in chunks if isinstance(c, dict)],
        "intro_chunk_ids": list(state.get("intro_chunk_ids") or []),
        "retries": int(state.get("retries") or 0),
        "search_stats": {k: (v if isinstance(v, (int, float)) else [str(x)[:PATH_TEXT_WIDTH] for x in v])
                         for k, v in (state.get("search_stats") or {}).items()
                         if isinstance(v, (int, float)) or (k in _PATH_STATS_LISTS and isinstance(v, (list, tuple)))},   # 62.69: 제목 경로 구와 더한 청크 id
        "judge_partial": bool(state.get("judge_partial")),
        "judge_quote_ids": list(state.get("judge_quote_ids") or []),
        "judge_quotes": quotes,
        "best2": {k: best2.get(k) for k in ("quote_ids", "cands", "pick", "why", "rule")} if best2 else None,
        "trimmed_citations": list(state.get("trimmed_citations") or []),
        "grounding": {**{k: grounding[k] for k in _PATH_GROUNDING_KEYS if k in grounding},
                      **({"redraft": redraft_row(redraft)} if redraft else {})},
        "judge_votes": [v for v in state.get("judge_votes") or [] if isinstance(v, dict)],   # 판정마다 표 구성(표별 충분·일부, 확정 방식, 일찍 확정했는지). 사전 등록 62.67
    }
    return {"path": path}
