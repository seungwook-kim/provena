"""개정된 정책 -> 함께 볼 정책 후보(`MaintenanceCandidate`). 후보 찾기는 코드만 쓴다(LLM 없음).

참조 그래프: 핸드북 페이지 사이 링크(`chunks.link_targets`, `backend/rag/retrieve/links.py`). 개정된 페이지(P)를 링크하는 다른 페이지(Q)의
섹션이 후보다. Q가 P의 기준을 따르거나 인용하므로 P가 바뀌면 Q도 함께 봐야 한다. 링크를 만들 때 자기 페이지·코퍼스 밖·비공개 주소
(internal.gitlab.com)는 이미 빠져 있다(EC-08). 후보의 근거(reason)에는 어느 섹션이 어느 페이지를 링크하는지 적는다.
정비가 필요한지는 관리자가 판단한다(`POST /maintenance-candidates/{id}`). 후보는 관리자에게만 보인다(AC-04).
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, Protocol

from backend.schemas.recall import ChangedArticle, MaintenanceCandidate

LIMIT = 50  # 개정 하나에 만드는 후보의 최대 수


class LinkLookup(Protocol):
    def linked_from(self, rule_seq: int) -> list[dict]:
        """rule_seq 페이지를 링크하는 다른 페이지의 섹션들(현재 판). 키: rule_seq, article, title."""
        ...

    def page_title(self, rule_seq: int) -> str | None: ...


class MemoryLinks:
    """시험·로컬용. links: [{"rule_seq": 링크하는 쪽, "article", "title", "target": 링크 대상 rule_seq}]."""

    def __init__(self, links: list[dict] | None = None, titles: dict[int, str] | None = None) -> None:
        self.links = list(links or [])
        self.titles = dict(titles or {})

    def linked_from(self, rule_seq: int) -> list[dict]:
        return [{"rule_seq": int(r["rule_seq"]), "article": r["article"], "title": r.get("title")} for r in self.links
                if int(r["target"]) == int(rule_seq) and int(r["rule_seq"]) != int(rule_seq)]

    def page_title(self, rule_seq: int) -> str | None:
        return self.titles.get(int(rule_seq))


def _default_connect(dsn: str) -> Callable[[], Any]:
    import psycopg

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)

    return connect


class PgLinks:
    """검색과 같은 DB의 `chunks.link_targets`(현재 판만, valid_to IS NULL)."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        self._connect = connect or _default_connect(dsn or "")

    def _rows(self, sql: str, params: tuple) -> list[tuple]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def linked_from(self, rule_seq: int) -> list[dict]:
        rows = self._rows(
            "SELECT c.rule_seq, c.article, d.title, min(c.seq) AS first_seq FROM chunks c "
            "JOIN versions v ON v.rule_seq = c.rule_seq AND v.version_id = c.version_id AND v.valid_to IS NULL "
            "JOIN docs d ON d.rule_seq = c.rule_seq "
            "WHERE %s = ANY(c.link_targets) AND c.rule_seq <> %s AND c.article IS NOT NULL "
            "GROUP BY c.rule_seq, c.article, d.title ORDER BY c.rule_seq, first_seq LIMIT %s",
            (int(rule_seq), int(rule_seq), LIMIT))
        return [{"rule_seq": int(s), "article": a, "title": t} for s, a, t, _ in rows]

    def page_title(self, rule_seq: int) -> str | None:
        rows = self._rows("SELECT title FROM docs WHERE rule_seq = %s", (int(rule_seq),))
        return rows[0][0] if rows else None


def candidate_id(event_key: str, rule_seq: int, article: str) -> str:
    return "mc-" + hashlib.sha256(f"{event_key}|{rule_seq}|{article}".encode()).hexdigest()[:16]


def find_candidates(changed: ChangedArticle, *, event_key: str, links: LinkLookup | None, upper_version_id: str | None = None) -> list[dict]:
    """개정된 페이지를 링크하는 다른 정책 섹션 -> 후보 dict 목록(계약 `MaintenanceCandidate` 칸 + status, event_key)."""
    if links is None:
        return []
    upper_title = links.page_title(changed.rule_seq) or f"정책 {changed.rule_seq}"
    version = upper_version_id or changed.new_version_date or changed.old_version_date or ""
    out, seen = [], set()
    for r in links.linked_from(changed.rule_seq):
        key = (r["rule_seq"], r["article"])
        if key in seen or not r["article"]:
            continue
        seen.add(key)
        title = r.get("title") or f"정책 {r['rule_seq']}"
        cand = MaintenanceCandidate(
            candidate_id=candidate_id(event_key, r["rule_seq"], r["article"]), upper_rule=upper_title, upper_version_id=version,
            rule_seq=r["rule_seq"], article=r["article"],
            reason=f"참조 그래프: {title}의 '{r['article']}' 섹션이 개정된 '{upper_title}' 페이지를 링크합니다"
                   f"(개정 섹션: {changed.article}, {changed.change_type}).",
        )
        out.append({**cand.model_dump(), "event_key": event_key, "status": "pending"})
        if len(out) >= LIMIT:
            break
    return out
