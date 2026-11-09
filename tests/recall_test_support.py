"""리콜 시험 공통 자료. 합성 시험 데이터이며 실제 핸드북 내용이 아니다.

가상 정책 90001("승인 권한 정책")의 섹션 "Approval Matrix > Table 1"이 2024-01-01 판에서 2025-07-01 판으로 바뀐다고 둔다.
- 금액 개정(AMOUNT_OLD -> AMOUNT_NEW): 중요도 high.
- 문구 개정(WORDING_OLD -> WORDING_NEW): 낱말 하나만 더해져 중요도 low, 규칙 판정 확신도 0.3(관리자 검토함).
"""
from __future__ import annotations

import hashlib

from backend.graph.answer_store import InMemoryAnswerStore
from backend.schemas import Chunk
from backend.schemas.recall import ChangedArticle

SEQ = 90001
ARTICLE = "Approval Matrix > Table 1"
OLD_DATE, NEW_DATE = "2024-01-01", "2025-07-01"
URL = "https://example.invalid/synthetic/test/90001"

AMOUNT_OLD = "도입 승인: 5천만원 이상 2억원 미만은 디렉터가 승인한다."
AMOUNT_NEW = "도입 승인: 1억원 이상 2억원 미만은 디렉터가 승인한다."
WORDING_OLD = "승인자는 승인 권한표에 따라 정한다."
WORDING_NEW = "승인자는 아래 승인 권한표에 따라 정한다."


def chunk(rule_seq: int = SEQ, article: str | None = ARTICLE, version_date: str = OLD_DATE, text: str = AMOUNT_OLD) -> Chunk:
    version_id = f"TEST-{rule_seq}-{version_date.replace('-', '')}"
    cid = hashlib.sha256(f"{rule_seq}|{version_id}|{article}|{text}".encode()).hexdigest()[:16]
    return Chunk(chunk_id=cid, org="TEST-security", rule_seq=rule_seq, rule_title="승인 권한 정책", article=article, version_id=version_id,
                 version_date=version_date, fetched_at="2026-11-02", kind="article", text=text,  # type: ignore[arg-type]
                 source_url=URL)


def changed(change_type: str = "modified", *, rule_seq: int = SEQ, article: str = ARTICLE, old: str = OLD_DATE,
            new: str = NEW_DATE) -> ChangedArticle:
    return ChangedArticle(rule_seq=rule_seq, article=article, old_version_date=old if change_type != "added" else "",
                          new_version_date=new, change_type=change_type)  # type: ignore[arg-type]


def reader(old_text: str = AMOUNT_OLD, new_text: str = AMOUNT_NEW, seen: list | None = None):
    """(rule_seq, article, as_of) -> 섹션 dict. as_of가 새 판 날짜 이상이면 새 판 본문."""
    def read(rule_seq, article, as_of):
        if seen is not None:
            seen.append(as_of)
        new = bool(as_of) and as_of >= NEW_DATE
        return {"text": new_text if new else old_text, "source_url": URL,
                "version_id": f"TEST-{rule_seq}-{(NEW_DATE if new else OLD_DATE).replace('-', '')}",
                "version_date": NEW_DATE if new else OLD_DATE}

    return read


def save_answer(store, answer_id: str, user_id: str, *, question: str = "5천만원짜리 도입은 누가 승인하나요?",
                answer: str = "5천만원 이상 2억원 미만이면 디렉터가 승인합니다.", as_of: str | None = "2025-01-15",
                thread: str = "t1", citations: list[Chunk] | None = None) -> None:
    store.save(answer_id, user_id, f"{user_id}:{thread}", question, answer, as_of, citations if citations is not None else [chunk()])


def answers_with(*rows: tuple[str, str]) -> InMemoryAnswerStore:
    """(answer_id, user_id) 목록으로 같은 섹션을 인용한 답 저장소."""
    store = InMemoryAnswerStore()
    for aid, uid in rows:
        save_answer(store, aid, uid)
    return store
