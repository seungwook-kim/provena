"""사용자 의견("도움 됨"/"필요 없음")으로 같은 사용자·섹션·변경 유형의 다음 알림을 줄이는 규칙과 집계 (F-08).

집계 키: (user_id, rule_seq, article, change_pattern). 알림 한 건에 의견은 하나(다시 보내면 덮어쓴다).
net = ("필요 없음" 수) - ("도움 됨" 수). 임계값 T = 환경변수 RECALL_FEEDBACK_THRESHOLD(기본 2, 0이면 규칙을 끈다).
- net >= T     : 그 키의 새 알림은 중요도를 한 단계 낮춘다(high -> low). 설명 끝에 이유를 붙인다.
- net >= 2 * T : 이미 low인 새 알림은 사용자 대신 관리자 검토함으로 보낸다(review_reason = feedback_suppressed).
"도움 됨"이 쌓이면 net이 줄어 원래대로 돌아온다. 사라지는 알림은 없다(검토함에서 관리자가 풀어 줄 수 있다).
이미 기록된 같은 답·같은 개정의 알림은 다시 조정하지 않는다(재전송해도 중복 알림이 생기지 않는다).
"""
from __future__ import annotations

import os
from collections import defaultdict

THRESHOLD_ENV = "RECALL_FEEDBACK_THRESHOLD"
DEFAULT_THRESHOLD = 2
LOWERED_NOTE = " (이 섹션의 같은 종류 변경 알림을 '필요 없음'으로 표시하신 이력이 있어 중요도를 낮췄습니다.)"


def threshold_from_env() -> int:
    raw = (os.environ.get(THRESHOLD_ENV) or "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_THRESHOLD
    except ValueError:
        return DEFAULT_THRESHOLD


def adjust(notice: dict, counts: dict | None, threshold: int | None = None) -> dict:
    """의견 집계(`{"useful": n, "not_useful": m}`)로 조정한 새 알림 dict. 의견이 없거나 규칙이 꺼져 있으면 그대로."""
    t = threshold_from_env() if threshold is None else threshold
    if t <= 0 or not counts:
        return notice
    net = int(counts.get("not_useful", 0)) - int(counts.get("useful", 0))
    if net < t:
        return notice
    if notice.get("severity") == "high":
        return {**notice, "severity": "low", "explanation": notice["explanation"] + LOWERED_NOTE}
    if net >= 2 * t and not notice.get("needs_review"):
        return {**notice, "needs_review": True, "review_reason": "feedback_suppressed", "explanation": notice["explanation"] + LOWERED_NOTE}
    return notice


def summarize(rows: list[dict]) -> dict:
    """의견 목록 -> 정밀도 추적용 집계. precision_from_feedback = 도움 됨 / 전체."""
    def block(items: list[dict]) -> dict:
        u = sum(1 for r in items if r["useful"])
        return {"useful": u, "not_useful": len(items) - u, "total": len(items), "precision_from_feedback": (u / len(items)) if items else None}

    by_pattern: dict[str, list[dict]] = defaultdict(list)
    by_user: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_pattern[r.get("pattern") or "(none)"].append(r)
        by_user[r["user_id"]].append(r)
    return {**block(rows), "by_pattern": {k: block(v) for k, v in sorted(by_pattern.items())},
            "by_user": {k: block(v) for k, v in sorted(by_user.items())}}
