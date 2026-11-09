"""리콜 판정기 두 가지. 리콜 그래프(`graph.py`)와 영향 미리보기(`impact.py`)가 같은 판정기를 쓴다.

- `LLMJudge`: 판정 모델(`notice.judge_answer`, `mail-templates` Skill). 운영 기본이다. 확신도는 모델이 준 값을 쓰고,
  개정 전후가 문구만 다르면 상한 0.45를 건다(`severity.cap_for_wording`).
- `RuleJudge`: LLM 없는 섹션 단위 규칙(키가 없거나 데모 모드). 개정 전후 본문의 낱말이 하나라도 달라지면 "결론이 바뀜",
  조사·관사·순서·공백만 다르면 "그대로", 두 본문을 모두 못 찾으면 판정 실패(확인 필요)다. 확신도는 이 답의 질문·답이
  바뀐 값에 닿는지로 정한다(`severity.relevance`). 재현율을 앞세운 규칙이라 정밀도는 LLM 판정보다 낮을 수 있다.
- `default_judge`: 모델을 주면 LLMJudge, 데모 모드(키 없음)면 RuleJudge, 그 밖에는 `get_chat_model()`로 LLMJudge.

판정 결과(dict): conclusion_changed, explanation, confidence(0~1 또는 None), judge_failed.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from backend.graph.recall.notice import FAILED_EXPLANATION, MSG_FAILED, judge_answer, system_prompt
from backend.graph.recall.severity import analyze_change, cap_for_wording, parse_confidence, relevance
from backend.schemas.recall import ChangedArticle

_TOKEN = re.compile(r"[0-9A-Za-z가-힣$%]+")
_STOP = frozenset("the a an of to and or is are be in on for by that this it 그 이 저 가 은 는 을 를 의 에 와 과 및 등 도 로 으로".split())


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def judge_texts(old: str, new: str) -> tuple[bool | None, str]:
    """(결론이 바뀌었나, 설명). 판정할 수 없으면 (None, 설명). LLM 없이 개정 전후 본문의 낱말 차이만 본다."""
    o, n = _tokens(old), _tokens(new)
    if not o and not n:
        return None, "개정 전후 본문을 찾지 못했습니다."
    if not n:
        return True, "섹션이 삭제되어 이 답의 근거가 사라집니다."
    if not o:
        return True, "섹션이 신설되었습니다."
    co, cn = Counter(o), Counter(n)
    removed, added = sorted((co - cn).keys()), sorted((cn - co).keys())
    if not removed and not added:
        return False, "낱말 순서·공백만 달라졌습니다."
    if all(t in _STOP for t in [*removed, *added]):
        return False, "조사·관사 수준의 문구만 달라졌습니다."

    def show(ts: list[str]) -> str:
        return (", ".join(ts[:4]) + (" 외" if len(ts) > 4 else "")) or "-"

    return True, f"본문이 달라졌습니다(삭제: {show(removed)} / 추가: {show(added)}). 규칙 판정이라 실제 결론 변화는 사람이 확인해야 합니다."


class RuleJudge:
    """LLM 없는 섹션 단위 규칙 판정. 같은 입력이면 항상 같은 출력이다."""

    mode = "rule"

    def judge(self, row: dict, changed: ChangedArticle, old_text: str | None, new_text: str | None) -> dict:
        old, new = old_text or "", new_text or ""
        if changed.change_type == "removed":
            new = ""
        changed_, why = judge_texts(old, new)
        if changed_ is None:
            return {"conclusion_changed": True, "explanation": f"{MSG_FAILED} {why} 새 판 기준으로 다시 확인해 주세요.",
                    "confidence": None, "judge_failed": True}
        analysis = analyze_change(old, new)
        conf = relevance(row.get("question") or "", row.get("answer") or "", analysis)[0] if changed_ else 0.9
        if changed_:
            conf = cap_for_wording(conf, analysis)
        return {"conclusion_changed": changed_, "explanation": why, "confidence": conf, "judge_failed": False}


class LLMJudge:
    """판정 모델로 답마다 한 번씩 판정한다. `config`를 주면 호출마다 넘긴다(비용 집계·트레이스)."""

    mode = "llm"

    def __init__(self, llm: Any, *, use_skills: bool | None = None, config_factory: Any = None) -> None:
        self.llm = llm
        self.system = system_prompt(use_skills)
        self.config_factory = config_factory

    def judge(self, row: dict, changed: ChangedArticle, old_text: str | None, new_text: str | None) -> dict:
        config = self.config_factory(row) if self.config_factory else None
        v = judge_answer(row, changed, old_text, new_text, self.llm, system=self.system, config=config)
        if v["judge_failed"]:
            return v if v.get("guarded") else {**v, "explanation": FAILED_EXPLANATION}
        conf = parse_confidence(v.get("confidence"))
        if v["conclusion_changed"]:
            conf = cap_for_wording(conf, analyze_change(old_text or "", "" if changed.change_type == "removed" else (new_text or "")))
        return {**v, "confidence": conf}


def default_judge(llm: Any = None, *, use_skills: bool | None = None, config_factory: Any = None):
    """모델을 주면 LLMJudge. 데모 모드(키 없음)면 RuleJudge. 그 밖에는 서비스 모델로 LLMJudge."""
    if llm is not None:
        return LLMJudge(llm, use_skills=use_skills, config_factory=config_factory)
    from backend.services.llm import get_chat_model, is_demo_mode

    if is_demo_mode():
        return RuleJudge()
    return LLMJudge(get_chat_model(), use_skills=use_skills, config_factory=config_factory)
