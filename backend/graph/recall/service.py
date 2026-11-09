"""리콜 처리기: 바뀐 섹션 하나 -> 리콜 그래프 -> 알림 저장(멱등) -> 의견 규칙 -> 검토함·하루 요약·웹훅 -> 함께 볼 정책 후보.

`RecallService.process`가 한 개정을 처리하고, 보낼 알림 id 목록(`to_send`)을 돌려준다. 웹훅은 `dispatch`가 보낸다
(API는 응답 뒤 백그라운드로, 명령줄 처리기는 바로). 알림 JSON 모양은 `notice_json` 한 곳에서 정한다(`GET /recalls`, 웹훅 본문 공통).

- 멱등(EC-06): 같은 개정은 `event_key`(changed_articles.event_id와 같은 규칙)로 한 번만 판정한다. 같은 답·같은 개정의 알림은 한 줄이다.
- 검토함(F-08): 확신도가 `RECALL_MIN_CONFIDENCE`보다 낮거나 의견 규칙으로 눌린 알림은 `review_status=pending`이라 사용자에게 보이지 않고
  웹훅·요약으로도 나가지 않는다. 관리자가 풀어 주면(`release`) 새 알림처럼 나간다.
- 문서 권한(F-06): 사용자에게 보일 때 `acl.groups_for(rule_seq, article)`가 비어 있으면 공개, 아니면 사용자 그룹과 겹칠 때만 보인다.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from backend.graph.recall.digest import digest_mode
from backend.graph.recall.feedback import adjust
from backend.graph.recall.graph import build_recall_graph
from backend.graph.recall.maintenance import find_candidates
from backend.graph.recall.webhook import encode_body
from backend.rag.ingest.schedule import event_id
from backend.schemas.recall import ChangedArticle

log = logging.getLogger(__name__)

NOTICE_KEYS = ("notice_id", "answer_id", "user_id", "thread_id", "question", "answer_excerpt", "changed", "conclusion_changed",
               "explanation", "severity", "confidence", "needs_review", "acked", "created_at", "source_url", "old_text", "new_text")
CHANGED_KEYS = ("rule_seq", "article", "old_version_date", "new_version_date", "change_type")


def notice_id_of(answer_id: str, event_key: str) -> str:
    return "rn-" + hashlib.sha256(f"{answer_id}|{event_key}".encode()).hexdigest()[:16]


def notice_json(rec: dict) -> dict:
    """저장한 알림 한 줄 -> 화면·웹훅이 받는 고정 모양."""
    changed = rec.get("changed") or {}
    conf = rec.get("confidence")
    return {
        "notice_id": rec["notice_id"],
        "answer_id": rec["answer_id"],
        "user_id": rec["user_id"],
        "thread_id": rec.get("thread_id"),
        "question": rec.get("question"),
        "answer_excerpt": rec.get("answer_excerpt"),
        "changed": {k: changed.get(k) for k in CHANGED_KEYS},
        "conclusion_changed": bool(rec.get("conclusion_changed")),
        "explanation": rec.get("explanation") or "",
        "severity": rec.get("severity") or "high",
        "confidence": float(conf) if conf is not None else None,
        "needs_review": rec.get("review_status") == "pending",
        "acked": bool(rec.get("acked")),
        "created_at": str(rec.get("created_at") or ""),
        "source_url": rec.get("source_url"),
        "old_text": rec.get("old_text"),
        "new_text": rec.get("new_text"),
    }


def candidate_json(rec: dict) -> dict:
    return {k: rec.get(k) for k in ("candidate_id", "upper_rule", "upper_version_id", "rule_seq", "article", "reason", "status", "decided_by")}


def user_visible(rec: dict) -> bool:
    """사용자 목록·확인·의견에 보이는 알림: 검토함에 있거나 폐기된 알림은 없는 것처럼 본다."""
    return rec.get("review_status") in (None, "released")


class RecallService:
    def __init__(self, *, store: Any, answers: Any, read_section: Any = None, links: Any = None, judge: Any = None, llm: Any = None,
                 sender: Any = None, acl: Any = None, min_confidence: float | None = None) -> None:
        self.store, self.answers, self.read_section, self.links = store, answers, read_section, links
        self.sender, self.acl, self.min_confidence = sender, acl, min_confidence
        self._judge, self._llm = judge, llm

    @property
    def judge(self) -> Any:
        if self._judge is None:
            from backend.graph.recall.judge import default_judge
            from backend.services.llm import run_config

            # 답마다 비용 집계를 따로 둔다(한 개정에 답이 많아도 질문 1건의 상한이 개정 전체를 막지 않는다)
            self._judge = default_judge(self._llm, config_factory=lambda row: run_config(
                "recall", user_id=row.get("user_id"), metadata={"answer_id": row.get("answer_id")}))
        return self._judge

    # ---------------------------------------------------------------- 처리
    def process(self, changed: ChangedArticle | dict, *, event_key: str | None = None) -> dict:
        ch = changed if isinstance(changed, ChangedArticle) else ChangedArticle.model_validate(changed)
        key = event_key or event_id(ch.model_dump())
        base = {"event_key": key, "notices": [], "to_send": [], "review": 0, "judge_failures": [], "candidates": 0}
        if not self.store.claim_event(key, ch.model_dump()):
            return {**base, "status": "skipped"}
        try:
            graph = build_recall_graph(answers=self.answers, read_section=self.read_section, judge=self.judge,
                                       min_confidence=self.min_confidence)
            result = graph.invoke({"changed": ch.model_dump()})
            daily = digest_mode() == "daily"
            created, to_send, review = [], [], 0
            for n in result.get("notices", []):
                counts = self.store.feedback_counts(n["user_id"], ch.rule_seq, ch.article, n.get("change_pattern") or "")
                n = adjust(n, counts)
                rec = {**n, "notice_id": notice_id_of(n["answer_id"], key), "event_key": key, "acked": False,
                       "review_status": "pending" if n.get("needs_review") else None,
                       "digest_status": "pending" if daily and not n.get("needs_review") else None}
                saved, new = self.store.notice_add(rec)
                if not new:
                    continue
                created.append(saved)
                if saved.get("review_status") == "pending":
                    review += 1
                elif not daily:
                    to_send.append(saved["notice_id"])
            cands = self._candidates(ch, key, result)
            failures = list(result.get("judge_failures", []))
            self.store.finish_event(key, "done", {"notices": len(created), "review": review, "judge_failures": len(failures), "candidates": cands})
            return {**base, "status": "done", "notices": created, "to_send": to_send, "review": review, "judge_failures": failures,
                    "candidates": cands}
        except Exception as e:
            self.store.finish_event(key, "failed", error_kind=type(e).__name__)
            raise

    def _candidates(self, ch: ChangedArticle, key: str, result: dict) -> int:
        if self.links is None:
            return 0
        try:
            sec = result.get("new") or result.get("old")
            if sec is None and self.read_section is not None:
                when = ch.new_version_date if ch.change_type != "removed" else ch.old_version_date
                sec = self.read_section(ch.rule_seq, ch.article, when) if when else None
            cands = find_candidates(ch, event_key=key, links=self.links, upper_version_id=(sec or {}).get("version_id"))
            return self.store.candidates_add(cands)
        except Exception as e:  # noqa: BLE001 - 후보를 못 만들어도 사용자 알림은 그대로 둔다(EC-07)
            log.warning("함께 볼 정책 후보를 만들지 못함: %s", type(e).__name__)
            return 0

    # ---------------------------------------------------------------- 보내기
    def dispatch(self, notice_ids: list[str]) -> list[dict]:
        """알림마다 웹훅을 보낸다(구독이 없으면 아무것도 하지 않는다). 전송 기록 목록."""
        if self.sender is None:
            return []
        out = []
        for nid in notice_ids:
            rec = self.store.notice_get(nid)
            if rec is None or not user_visible(rec):
                continue
            out += self.sender.send(nid, encode_body(notice_json(rec)))
        return out

    def review(self, notice_id: str, action: str) -> tuple[dict | None, list[str]]:
        """관리자 검토함: release면 사용자에게 보이고 새 알림처럼 나간다(하루 요약 모드면 요약 대기), dismiss면 폐기. (알림, 보낼 id)."""
        rec = self.store.notice_get(notice_id)
        if rec is None or rec.get("review_status") != "pending":
            return None, []
        if action == "dismiss":
            return self.store.notice_update(notice_id, review_status="dismissed"), []
        daily = digest_mode() == "daily"
        rec = self.store.notice_update(notice_id, review_status="released", digest_status="pending" if daily else None)
        return rec, ([] if daily else [notice_id])

    # ---------------------------------------------------------------- 권한
    def can_see(self, rec: dict, groups: tuple[str, ...] | list[str]) -> bool:
        """F-06: 인용한 섹션의 권한 그룹이 비어 있으면 공개, 아니면 사용자 그룹과 겹칠 때만 보인다. 권한을 못 읽으면 보이지 않는다."""
        if self.acl is None:
            return True
        changed = rec.get("changed") or {}
        try:
            need = set(self.acl.groups_for(int(changed.get("rule_seq")), changed.get("article")))
        except Exception as e:  # noqa: BLE001 - 권한을 확인할 수 없으면 내용을 내보내지 않는다(안전 쪽)
            log.warning("알림 문서 권한 확인 실패: %s", type(e).__name__)
            return False
        return not need or bool(need & set(groups or ()))
