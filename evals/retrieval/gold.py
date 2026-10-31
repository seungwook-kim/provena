"""평가셋 정답 위치(`gold_chunks`) 풀기와 청크 맞추기.

`evals/README.md`대로 `gold_chunks`에는 청크 id 말고 문서 위치도 쓸 수 있다. 동결한 평가셋은 고치지 않으므로,
청킹을 바꿔도 정답이 그대로 남게 **문서 위치로 적고 채점할 때 청크에 맞춘다**.

한 항목의 표기 (여럿이면 목록에 따로 적는다):
- `경로.md > 제목 > 하위 제목`: 그 페이지의 그 섹션. 경로는 `content/handbook/` 뒤 경로(예: `security/x.md`)나 전체 경로.
- `경로.md`: 페이지 전체(섹션을 모를 때만. 느슨하다).
- `authorization-matrix > 제목`: 2023-05 권한표(`backend/rag/ingest/handbook.py` AUTHZ_PATH).
- 16자리 16진수: 청크 id 그대로.
- `경로.md#L123`: 그 페이지의 원본 123행이 들어 있는 청크(제목으로 좁힐 수 없는 표 밖 각주 등). 청크 줄 범위(`line_start`~`line_end`)로 맞춘다.
- `위치 | 위치`: 그중 하나만 찾으면 되는 정답(같은 문장이 여러 페이지에 있을 때). Recall에서 한 개로 센다.

맞추는 규칙: 페이지(rule_seq)가 같고, 정답 제목 경로가 청크 제목 경로(`Chunk.article`) 안에 **이어서** 들어 있으면 맞다.
청크 제목 경로 앞에 페이지 제목이 붙거나, 청크가 그 섹션의 하위 섹션이어도 맞는다(청킹 방식과 무관하게).
판(version)은 보지 않는다. 기준일(as_of)에 맞는 판을 고르는 것은 검색의 일이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.rag.ingest.handbook import AUTHZ_PATH, rule_seq

HANDBOOK_PREFIX = "content/handbook/"
AUTHZ_ALIAS = "authorization-matrix"
_CHUNK_ID = re.compile(r"^[0-9a-f]{16}$")


def norm(text: str | None) -> list[str]:
    """제목 경로 -> 소문자·공백 정리한 제목 목록."""
    text = re.sub(r"\{#[^}]*\}", "", text or "")  # Hugo 제목 앵커 `{#id}`는 뺀다
    return [re.sub(r"\s+", " ", p).strip().lower() for p in text.split(">") if p.strip()]


@dataclass(frozen=True)
class GoldRef:
    """정답 위치 하나."""

    rule_seq: int | None = None
    article: tuple[str, ...] = ()  # 정규화한 제목 경로. 비면 페이지 전체
    chunk_id: str | None = None
    line: int | None = None  # 원본 줄 번호(`#L123`)
    label: str = field(default="", compare=False)  # 표기 원문(보고용). 같은 위치를 다르게 적어도 같은 정답

    def page_matches(self, c: Any) -> bool:
        return self.rule_seq is not None and c.rule_seq == self.rule_seq

    def matches(self, c: Any) -> bool:
        if self.chunk_id is not None:
            return c.chunk_id == self.chunk_id
        if not self.page_matches(c):
            return False
        if self.line is not None:
            return (getattr(c, "line_start", None) or 0) <= self.line <= (getattr(c, "line_end", None) or -1)
        if not self.article:
            return True
        have, want = norm(c.article), list(self.article)
        return any(have[i : i + len(want)] == want for i in range(len(have) - len(want) + 1))


@dataclass(frozen=True)
class GoldAny:
    """`위치 | 위치`: 하나만 맞으면 된다."""

    refs: tuple[GoldRef, ...]
    label: str = field(default="", compare=False)

    def page_matches(self, c: Any) -> bool:
        return any(r.page_matches(c) for r in self.refs)

    def matches(self, c: Any) -> bool:
        return any(r.matches(c) for r in self.refs)


def page_seq(path: str) -> int:
    """정답 표기의 페이지 경로 -> rule_seq (수집기와 같은 계산)."""
    p = path.strip()
    if p == AUTHZ_ALIAS:
        return rule_seq(AUTHZ_PATH)
    if not p.startswith(HANDBOOK_PREFIX) and p != AUTHZ_PATH:
        p = HANDBOOK_PREFIX + p
    return rule_seq(p)


def parse_ref(text: str) -> GoldRef | GoldAny:
    """`gold_chunks` 한 항목 -> GoldRef(또는 `|`로 묶은 GoldAny). 형식이 틀리면 ValueError."""
    t = text.strip()
    if " | " in t:
        return GoldAny(tuple(parse_ref(x) for x in t.split(" | ")), label=t)
    if _CHUNK_ID.match(t):
        return GoldRef(chunk_id=t, label=t)
    head, _, rest = t.partition(">")
    head = head.strip()
    line = None
    if m := re.fullmatch(r"(.+)#L(\d+)", head):
        head, line = m.group(1), int(m.group(2))
    if not (head.endswith(".md") or head == AUTHZ_ALIAS or head == AUTHZ_PATH):
        raise ValueError(f"정답 위치는 '경로.md > 제목', '{AUTHZ_ALIAS} > 제목' 또는 청크 id다: {text!r}")
    return GoldRef(rule_seq=page_seq(head), article=tuple(norm(rest)), line=line, label=t)


def parse_gold(entries: Iterable[str]) -> list[GoldRef | GoldAny]:
    return list(dict.fromkeys(parse_ref(e) for e in entries if e and e.strip()))


def missing_in_corpus(refs: Iterable[GoldRef | GoldAny], chunks: Iterable[Any]) -> list[str]:
    """어떤 청크와도 맞지 않는 정답 위치(코퍼스에 없거나 표기가 틀림). 판정·청킹 점검용."""
    chunks = list(chunks)
    return [r.label for r in refs if not any(r.matches(c) for c in chunks)]
