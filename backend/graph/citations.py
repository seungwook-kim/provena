"""인용 검사(코드, LLM 없음). SDD 4-3 "섹션·판이 코퍼스에 있는지", SDD 9장 "인용은 코드로 원문과 대조한다".

규칙: 답이 인용한 chunk_id가 이번에 검색된 결과(=코퍼스)에 실제로 있어야 한다. 인용에 섹션·판·정책 번호가 함께 적혀 있으면
그 청크의 값과도 같아야 한다. 하나라도 어긋나면 그 인용은 가짜로 보고 뺀다. 답 본문에 남은 가짜 `[chunk_id]` 표시도 지운다.
"""
from __future__ import annotations

import re

_MARK = re.compile(r"\[([0-9a-f]{16})\]")
_CHECKED_FIELDS = ("rule_seq", "article", "version_id")


def _normalize(raw: object) -> dict | None:
    if isinstance(raw, str):
        return {"chunk_id": raw}
    if isinstance(raw, dict) and isinstance(raw.get("chunk_id"), str):
        return raw
    return None


def check_citations(raw_citations: list, chunks: list[dict], answer: str) -> tuple[list[dict], list, str]:
    """(실제 있는 인용 청크들, 걸러낸 인용들, 정리한 답)을 돌려준다. 청크는 중복 없이 인용 순서대로."""
    by_id = {c["chunk_id"]: c for c in chunks}
    valid: list[dict] = []
    dropped: list = []
    seen: set[str] = set()
    for raw in raw_citations or []:
        item = _normalize(raw)
        if item is None:
            dropped.append(raw)
            continue
        ch = by_id.get(item["chunk_id"])
        if ch is None or any(f in item and item[f] != ch.get(f) for f in _CHECKED_FIELDS):
            dropped.append(raw)
            continue
        if ch["chunk_id"] not in seen:
            seen.add(ch["chunk_id"])
            valid.append(ch)
    # 본문에 남은 가짜 표시 제거: 코퍼스에 없는 [16자리 id]와 걸러낸 id
    cleaned = _MARK.sub(lambda m: m.group(0) if m.group(1) in by_id and m.group(1) in seen else "", answer or "")
    for d in dropped:
        item = _normalize(d)
        if item and item["chunk_id"] not in seen:  # 같은 id가 한 번은 맞았으면(필드만 틀린 인용이 따로 있었으면) 맞은 표시는 남긴다
            cleaned = cleaned.replace(item["chunk_id"], "")
    return valid, dropped, cleaned.strip()
