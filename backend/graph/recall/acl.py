"""리콜 알림의 문서 권한 확인 자리 (F-06: 리콜 알림도 볼 수 있는 섹션만 인용한다).

청크마다 볼 수 있는 그룹은 `chunks.acl`(text[], 201_search.sql)에 있다. 지금 코퍼스는 모두 비어 있어(기본 공개) 모든 알림이 보인다.
- `PublicAcl`: 항상 빈 그룹(공개). DB가 없을 때의 기본이다.
- `PgAcl`: 그 섹션의 청크 acl을 모은다(어느 판이든). 하나라도 그룹이 붙어 있으면 그 그룹 사용자와 관리자만 알림을 본다.
사용자 그룹은 로그인 사용자(`AuthUser.groups`)에서 읽는다. 그룹을 채우는 정책 파일과 검색 단계 거르기는 검색 파트 몫이다.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PublicAcl:
    def groups_for(self, rule_seq: int, article: str | None) -> set[str]:
        return set()


class MemoryAcl:
    """시험용: {(rule_seq, article): {그룹}}."""

    def __init__(self, groups: dict[tuple[int, str], set[str]] | None = None) -> None:
        self.groups = dict(groups or {})

    def groups_for(self, rule_seq: int, article: str | None) -> set[str]:
        return set(self.groups.get((int(rule_seq), article or ""), set()))


class PgAcl:
    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None) -> None:
        if connect is None:
            import psycopg

            def connect() -> Any:
                return psycopg.connect(dsn, autocommit=True, connect_timeout=5, prepare_threshold=None)
        self._connect = connect

    def groups_for(self, rule_seq: int, article: str | None) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT g FROM chunks c, unnest(c.acl) AS g WHERE c.rule_seq = %s "
                                "AND c.article IS NOT DISTINCT FROM %s::text", (int(rule_seq), article)).fetchall()
        return {r[0] for r in rows}
