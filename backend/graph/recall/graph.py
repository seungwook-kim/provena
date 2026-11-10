"""F-02 리콜 그래프: ChangedArticle -> 영향받는 과거 답 찾기(코드) -> 결론 변화 판정(LLM 또는 규칙) -> 바뀐 답만 알림 후보.

노드 세 개(LangGraph, 질문 그래프와 별도).
1. `find_answers`: 답 저장소의 `find_by_article`로 그 섹션을 인용한 답을 찾는다. 같은 답은 한 번만, 기준일·인용 판이 새 판 이후인 답은 뺀다(EC-03).
   개정 전후 섹션 원문은 `read_section(rule_seq, article, as_of)`로 읽는다(추가된 섹션은 개정 전, 삭제된 섹션은 개정 뒤를 읽지 않는다).
2. `judge`: 답마다 따로 판정한다(사용자 사이 내용이 섞이지 않는다). 판정이 깨지면 알리고 `judge_failures`에 남긴다(EC-01, AC-05).
3. `notify`: 결론이 바뀐 답만 알림 후보로 만든다(EC-04). 다만 판정이 "그대로"라 해도 코드 규칙이 중요한 변경(금액·승인자·기한·권한, 섹션 신설·삭제)이라 하면
   알림을 버리지 않고 `needs_review`, `review_reason="judge_disagrees_with_rule"`, 설명 맨 앞 "[판정 실패, 확인 필요]"로 관리자 검토함에 둔다(판정이 개정 본문 속 문장에 따랐을 수 있다). 중요도는 개정 전후 본문의 키워드 규칙(`severity.py`), 확신도가
   `RECALL_MIN_CONFIDENCE`(기본 0.5)보다 낮으면 `needs_review=True`(관리자 검토함, F-08).
저장·멱등·웹훅·의견 규칙은 `service.py`가 한다. 출력 알림은 계약(`RecallNotice`)의 칸에 화면용 칸을 더한 dict다.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from backend.graph.recall.judge import default_judge
from backend.graph.recall.notice import MSG_FAILED, guard_explanation, is_affected
from backend.graph.recall.severity import HIGH_KINDS, analyze_change
from backend.schemas.recall import ChangedArticle

MIN_CONFIDENCE_ENV = "RECALL_MIN_CONFIDENCE"
DISAGREE_EXPLANATION = f"{MSG_FAILED} 판정은 결론이 그대로라고 했지만 개정이 금액·승인자·기한·권한 또는 섹션 신설·삭제에 닿아 있어 관리자 확인이 필요합니다."
DEFAULT_MIN_CONFIDENCE = 0.5
EXCERPT = 200

SectionReader = Callable[[int, str, str | None], dict | None]


def min_confidence_from_env() -> float:
    """환경변수 RECALL_MIN_CONFIDENCE(0~1, 기본 0.5). 읽을 수 없는 값이면 기본값."""
    raw = (os.environ.get(MIN_CONFIDENCE_ENV) or "").strip()
    try:
        return max(0.0, min(1.0, float(raw))) if raw else DEFAULT_MIN_CONFIDENCE
    except ValueError:
        return DEFAULT_MIN_CONFIDENCE


def outer_thread(user_id: str, thread_id: str | None) -> str | None:
    """그래프 thread 이름(`<user_id>:<thread_id>`)에서 화면이 쓰는 바깥 이름을 꺼낸다."""
    if not thread_id:
        return None
    prefix = f"{user_id}:"
    return thread_id[len(prefix):] if thread_id.startswith(prefix) else thread_id


def excerpt(text: str | None, n: int = EXCERPT) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


class RecallState(TypedDict, total=False):
    changed: dict                 # ChangedArticle.model_dump()
    affected: list[dict]          # 영향받는 과거 답 (코드)
    old: dict | None              # 개정 전 섹션(read_section 결과)
    new: dict | None              # 개정 뒤 섹션
    judgements: list[dict]
    judge_failures: list[str]     # 판정이 깨진 answer_id (알림은 내되 설명에 표시)
    notices: list[dict]           # 결론이 바뀐 답만


def _read(read_section: SectionReader | None, rule_seq: int, article: str, as_of: str | None) -> dict | None:
    if read_section is None or not as_of:
        return None
    try:
        return read_section(rule_seq, article, as_of)
    except Exception:  # noqa: BLE001 - 원문을 못 읽어도 판정은 이어 간다(규칙 판정은 확인 필요, LLM은 (없음)으로 본다)
        return None


def build_recall_graph(*, answers: Any, read_section: SectionReader | None = None, judge: Any = None, llm: Any = None,
                       min_confidence: float | None = None, checkpointer: BaseCheckpointSaver | None = None):
    """입력 상태: {"changed": ChangedArticle(dict 또는 모델)}. 출력: notices, judgements, judge_failures.

    `judge`를 비우면 `default_judge(llm)`(모델을 주면 LLM 판정, 키가 없으면 규칙 판정)."""
    judge_ = judge if judge is not None else default_judge(llm)

    def find_answers(state: RecallState) -> dict:
        ch = ChangedArticle.model_validate(state["changed"])
        affected, seen = [], set()
        for r in answers.find_by_article(ch.rule_seq, ch.article):
            if r["answer_id"] in seen or not is_affected(r, ch):
                continue
            seen.add(r["answer_id"])
            affected.append(dict(r))
        if not affected:
            return {"changed": ch.model_dump(), "affected": [], "old": None, "new": None}
        old = _read(read_section, ch.rule_seq, ch.article, ch.old_version_date) if ch.change_type != "added" else None
        new = _read(read_section, ch.rule_seq, ch.article, ch.new_version_date) if ch.change_type != "removed" else None
        return {"changed": ch.model_dump(), "affected": affected, "old": old, "new": new}

    def judge_node(state: RecallState) -> dict:
        ch = ChangedArticle.model_validate(state["changed"])
        old_text, new_text = (state.get("old") or {}).get("text"), (state.get("new") or {}).get("text")
        judgements, failures = [], []
        for a in state["affected"]:
            v = judge_.judge(a, ch, old_text, new_text)
            if not v["judge_failed"]:              # 어떤 판정기든 설명에 지시문·표지·다른 사용자 값이 섞이면 고정 문장으로 바꾸고 실패로 센다
                text, why = guard_explanation(v["explanation"], row=a, others=state["affected"], sources=(old_text, new_text))
                if why:
                    v = {**v, "explanation": text, "confidence": None, "judge_failed": True, "guarded": why}
            if v["judge_failed"]:
                failures.append(a["answer_id"])
            judgements.append({**v, "answer_id": a["answer_id"]})
        return {"judgements": judgements, "judge_failures": failures}

    def notify(state: RecallState) -> dict:
        ch = ChangedArticle.model_validate(state["changed"])
        floor = min_confidence if min_confidence is not None else min_confidence_from_env()
        old, new = state.get("old") or {}, state.get("new") or {}
        old_text = old.get("text") if ch.change_type != "added" else ""
        new_text = new.get("text") if ch.change_type != "removed" else ""
        analysis = analyze_change(old_text or "", new_text or "")
        by_id = {a["answer_id"]: a for a in state["affected"]}
        notices, failures = [], list(state.get("judge_failures") or [])
        rule_high = bool(set(analysis.kinds) & (HIGH_KINDS - {"unknown"}))    # 금액·승인자·기한·권한이 바뀌었거나 섹션이 신설·삭제됨
        for j in state["judgements"]:
            disagree = False
            if not j["conclusion_changed"]:
                if not rule_high:                    # 결론이 그대로이고 문구만 바뀐 답은 알리지 않는다(EC-04)
                    continue
                # 판정은 "그대로"인데 코드 규칙은 중요한 변경이라 한다(개정 본문에 심어 둔 문장에 판정이 따랐을 수 있다): 버리지 않고 검토함으로 보낸다
                disagree = True
                failures.append(j["answer_id"])
            a = by_id[j["answer_id"]]
            conf = None if disagree else j.get("confidence")
            low = disagree or (conf is not None and conf < floor)
            notices.append({
                "answer_id": a["answer_id"],
                "user_id": a["user_id"],
                "thread_id": outer_thread(a["user_id"], a.get("thread_id")),
                "question": a.get("question"),
                "answer_excerpt": excerpt(a.get("answer")),
                "changed": ch.model_dump(),
                "conclusion_changed": True,
                "explanation": DISAGREE_EXPLANATION if disagree else j["explanation"],
                "severity": analysis.severity,
                "change_pattern": analysis.pattern,
                "confidence": conf,
                "needs_review": low,
                "review_reason": "judge_disagrees_with_rule" if disagree else ("low_confidence" if low else None),
                "judge_failed": disagree or bool(j.get("judge_failed")),
                "source_url": new.get("source_url") or old.get("source_url") or a.get("source_url"),
                "old_text": old.get("text") if ch.change_type != "added" else None,
                "new_text": new.get("text") if ch.change_type != "removed" else None,
            })
        return {"notices": notices, "judge_failures": failures}

    g = StateGraph(RecallState)
    g.add_node("find_answers", find_answers)
    g.add_node("judge", judge_node)
    g.add_node("notify", notify)
    g.add_edge(START, "find_answers")
    g.add_edge("find_answers", "judge")
    g.add_edge("judge", "notify")
    g.add_edge("notify", END)
    return g.compile(checkpointer=checkpointer)
