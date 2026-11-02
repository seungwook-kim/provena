"""답변·인용 저장소 (SDD 5장 `answers`, `citations`).

`AnswerStore` Protocol을 지키면 Postgres 구현으로 바꿔 끼울 수 있다(B-05).
`find_by_article`은 리콜(backend/graph/recall)이 "이 섹션을 인용한 과거 답"을 찾는 데 쓴다. 이름·반환 키는 리콜 담당과 맞춘 것이다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from backend.schemas import Chunk

@runtime_checkable
class AnswerStore(Protocol):
    def save(
        self,
        answer_id: str,
        user_id: str,
        thread_id: str,
        question: str,
        answer: str,
        as_of: str | None,
        citations: list[Chunk],
    ) -> None: ...

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        """그 정책(rule_seq)의 그 섹션(article)을 인용한 답. 키: answer_id, user_id, question, answer, as_of, version_id."""
        ...


class InMemoryAnswerStore:
    """인메모리 구현(테스트·데모용)."""

    def __init__(self) -> None:
        self._answers: dict[str, dict] = {}
        self._citations: dict[str, list[Chunk]] = {}

    def save(self, answer_id, user_id, thread_id, question, answer, as_of, citations) -> None:
        self._answers[answer_id] = {
            "answer_id": answer_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "question": question,
            "answer": answer,
            "as_of": as_of,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._citations[answer_id] = list(citations)

    def get(self, answer_id: str) -> dict | None:
        a = self._answers.get(answer_id)
        return None if a is None else {**a, "citations": list(self._citations[answer_id])}

    def all_answers(self) -> list[dict]:
        return [self.get(i) for i in self._answers]  # type: ignore[misc]

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for aid, cites in self._citations.items():
            a = self._answers[aid]
            for c in cites:
                if c.rule_seq == rule_seq and c.article == article and (aid, c.version_id) not in seen:
                    seen.add((aid, c.version_id))
                    out.append(
                        {
                            "answer_id": aid,
                            "user_id": a["user_id"],
                            "question": a["question"],
                            "answer": a["answer"],
                            "as_of": a["as_of"],
                            "version_id": c.version_id,
                        }
                    )
        return out
