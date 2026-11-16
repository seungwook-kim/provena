"""시스템 쪽 참조 그래프 재료: 청크(현재 판)의 rule_seq·섹션(article)·줄 범위·링크 대상(link_targets).

- 운영(기본): 운영 DB 읽기 전용 SELECT(`chunks` + 현재 판 `versions.valid_to IS NULL`). 링크 확장 검색과 함께 볼 정책 후보가 쓰는 바로 그 칸이다.
- 로컬(--source index): `data/index/chunks.jsonl` + `data/index/links.jsonl`(운영 DB에 올린 것과 같은 빌드 산출물).
줄 번호는 코퍼스 원문 파일 기준(앞머리 포함)이다. 정답의 줄을 섹션으로 바꿀 때 그 줄을 덮는 청크의 섹션을 쓰고, 덮는 청크가 없으면(제목 줄 등)
시스템 파서 규칙의 제목 경로(`common.line_articles`)를 쓴다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from evals.newmetrics.common import INDEX_CHUNKS, INDEX_LINKS, line_articles, page_rule_seq, read_jsonl, read_pages

SQL_CHUNKS = ("SELECT c.rule_seq, c.article, c.line_start, c.line_end, coalesce(c.link_targets, '{}') FROM chunks c "
              "JOIN versions v ON v.rule_seq = c.rule_seq AND v.version_id = c.version_id AND v.valid_to IS NULL "
              "WHERE c.rule_seq < 9000000000 ORDER BY c.rule_seq, c.seq")


@dataclass
class ChunkTable:
    rows: list[tuple[int, str | None, int, int, tuple[int, ...]]]
    source: str
    seq2rel: dict[int, str] = field(default_factory=dict)
    _by_seq: dict[int, list] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.seq2rel:
            self.seq2rel = {page_rule_seq(rel): rel for rel in read_pages()}
        by = defaultdict(list)
        for r in self.rows:
            by[r[0]].append(r)
        self._by_seq = dict(by)
        self._arts: dict[str, list] = {}

    def chunks_of(self, seq: int) -> list:
        return self._by_seq.get(int(seq), [])

    def article_at(self, rel: str, line: int | None) -> str | None:
        """정답 줄 -> 섹션. 그 줄을 덮는 청크의 섹션, 없으면 파서 규칙의 제목 경로."""
        if not line:
            return None
        hits = [r[1] for r in self.chunks_of(page_rule_seq(rel)) if r[2] and r[3] and r[2] <= line <= r[3]]
        if hits:
            return hits[0]
        if rel not in self._arts:
            try:
                self._arts[rel] = line_articles(rel)
            except FileNotFoundError:
                self._arts[rel] = []
        arts = self._arts[rel]
        return arts[line] if 0 < line < len(arts) else None

    def edges(self, rels: list[str]) -> set[tuple[str, str | None, str]]:
        """(출발 페이지, 섹션, 대상 페이지) 간선. 대상이 코퍼스 경로로 안 풀리면 'seq:<번호>'."""
        out = set()
        for rel in rels:
            for seq, art, _s, _e, tg in self.chunks_of(page_rule_seq(rel)):
                for t in tg:
                    out.add((rel, art, self.seq2rel.get(int(t), f"seq:{t}")))
        return out

    def linked_from(self, target_seq: int) -> list[dict]:
        """`PgLinks.linked_from`과 같은 규칙(자기 페이지 제외, 섹션 있는 것, rule_seq·첫 청크 순, 50개 제한은 호출하는 쪽 find_candidates)."""
        seen, out = set(), []
        for seq in sorted(self._by_seq):
            if seq == target_seq:
                continue
            for _seq, art, _s, _e, tg in self._by_seq[seq]:
                if art and int(target_seq) in tg and (seq, art) not in seen:
                    seen.add((seq, art))
                    out.append({"rule_seq": seq, "article": art, "title": self.seq2rel.get(seq)})
        return out

    def page_title(self, seq: int) -> str | None:
        return self.seq2rel.get(int(seq))


def from_index() -> ChunkTable:
    tg = {r["chunk_id"]: tuple(int(x) for x in r.get("targets") or []) for r in read_jsonl(INDEX_LINKS)}
    rows = [(int(c["rule_seq"]), c.get("article"), int(c.get("line_start") or 0), int(c.get("line_end") or 0), tg.get(c["chunk_id"], ()))
            for c in read_jsonl(INDEX_CHUNKS)]
    return ChunkTable(rows, "index")


def from_db(conn) -> ChunkTable:
    rows = [(int(s), a, int(ls or 0), int(le or 0), tuple(int(x) for x in (t or ()))) for s, a, ls, le, t in conn.execute(SQL_CHUNKS).fetchall()]
    return ChunkTable(rows, "prod-db")
