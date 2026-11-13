"""섹션 원문 조회 `get_section` · `section_names` (docs/specs/mcp.md How 2).

DB 청크 글 = `머리말 한 줄 + 앞 청크 끝 겹침 + 본문`(chunk.make_chunk)이라 그대로 이으면 겹친 글이 두 번 나온다.
겹침을 어림으로 찾지 않고 청킹과 같은 규칙으로 다시 계산해 뗀다. 일반 글은 chunk.overlap_tail(CHUNK_OVERLAP자),
표 행 안에서 시작한 겹침은 chunk.overlap_for(행 처음부터, 행이 ROW_TAIL_MAX=400자를 넘으면 첫 칸(라벨)만 붙임)라 길이가
CHUNK_OVERLAP과 다를 수 있다. 그래서 body_of는 먼저 overlap_tail로 떼 보고 지문이 안 맞으면 줄바꿈 자리마다 떼 보며,
뗀 본문 sha256이 청크의 text_sha256(본문만의 지문)과 같고 떼어낸 앞부분이 앞 청크 본문의 끝일 때만 그 자리를 쓴다
(퍼지 검색 없음: 지문과 앞 청크 끝이 둘 다 맞는 자리만). 하나라도 안 맞으면 틀린 원문을 돌려주지 않고 SectionIntegrityError.

판 고르기는 검색과 같다(search._FILTER): as_of가 없으면 valid_to가 빈 현재 판, 있으면 valid_from <= as_of < valid_to.
알려진 한계(Spec EC-13): 긴 요소 하나가 청크 둘 이상으로 쪼개진 섹션은 조각 경계에 줄바꿈이 하나 더 들어간다.
글자는 같고 공백만 다르다. DB에 청크별 요소 id가 없어 쪼갠 경계인지 알 수 없기 때문이다(스냅샷 15,901섹션 중 438, 515acc3d 이전 기준).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import threading
from typing import Protocol

from pydantic import BaseModel

from backend.rag.ingest.chunk import CELL_SEP, overlap_tail
from backend.rag.ingest.schedule import CHUNK_OVERLAP

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_NAMES = 10          # EC-02 후보 수


class Section(BaseModel):
    """섹션 하나의 원문. 계약(backend/schemas/) 밖 모델(Spec 열린 항목 3)."""
    rule_seq: int
    rule_title: str                 # 페이지의 지금 제목(docs.title). 옛 판의 제목이 달랐으면 청크 머리말과 다를 수 있다
    article: str | None             # 제목 경로. 제목 없는 페이지는 None
    version_id: str
    version_date: str
    version_date_before: bool
    text: str                       # 청크 본문을 seq 순서로 "\n" 이어 붙인 것(머리말·겹침 뺌)
    source_url: str                 # 페이지 주소
    line_start: int | None
    line_end: int | None
    chunk_ids: list[str]


class SectionIntegrityError(RuntimeError):
    """뗀 본문 지문이 청크 text_sha256과 다르다(EC-05). 메시지에 chunk_id만 넣는다."""


class SectionStore(Protocol):
    def page_version(self, rule_seq: int, as_of: str | None) -> dict | None: ...
    def section_rows(self, rule_seq: int, version_id: str, article: str | None) -> list[dict]: ...
    def articles(self, rule_seq: int, version_id: str) -> list[str | None]: ...
    def orgs(self) -> set[str]: ...


def check_date(value: str | None, name: str = "as_of") -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _DATE.match(value):
        raise ValueError(f"{name}는 YYYY-MM-DD: {value!r}")
    dt.date.fromisoformat(value)           # 2026-02-30 같은 날짜도 멈춘다


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def body_of(text: str, kind: str, prev_body: str, want_sha: str | None = None) -> str:
    """청크 글에서 머리말(첫 줄)과 겹침을 뗀 본문. 겹침은 섹션 안 앞 청크 본문으로 다시 계산한다.
    권한표 행(kind=row)은 겹침 없이 만들었다(chunk.authz_chunks).
    표 행 안에서 시작한 겹침은 행 처음부터(또는 첫 칸을 붙여) 가져오므로(chunk.overlap_for) overlap_tail과 다를 수 있다.
    그때는 want_sha(청크의 text_sha256)와 지문이 같아지는 줄바꿈 자리를 찾아 겹침을 뗀다."""
    _, sep, rest = text.partition("\n")
    if not sep:
        return ""                          # 머리말뿐인 글은 없다 → 지문 검사에서 걸린다
    tail = overlap_tail(prev_body, CHUNK_OVERLAP) if kind == "article" else ""
    body = rest
    if tail:
        if rest.startswith(tail + "\n"):
            body = rest[len(tail) + 1:]
    if want_sha and kind == "article" and prev_body and _sha(body) != want_sha:
        prev = prev_body.rstrip()
        i = rest.find("\n")
        while i != -1:
            cand = rest[:i]            # 겹침 후보: 앞 청크 본문의 끝이거나, 첫 칸(라벨)을 붙인 그 끝
            if _sha(rest[i + 1:]) == want_sha and (prev.endswith(cand) or (CELL_SEP in cand and prev.endswith(cand.split(CELL_SEP, 1)[1]))):
                return rest[i + 1:]
            i = rest.find("\n", i + 1)
    return body


def rebuild(rows: list[dict]) -> list[str]:
    """seq 순서 청크 → 본문 목록. 하나라도 지문이 다르면 SectionIntegrityError."""
    bodies, prev = [], ""
    for r in rows:
        body = body_of(r["text"], r["kind"], prev, r.get("text_sha256"))
        if not r.get("text_sha256") or _sha(body) != r["text_sha256"]:
            raise SectionIntegrityError(f"섹션 본문 지문 불일치: chunk_id={r['chunk_id']}")
        bodies.append(body)
        prev = body
    return bodies


def get_section(rule_seq: int, article: str | None, as_of: str | None = None,
                store: SectionStore | None = None) -> Section | None:
    """그 판의 (rule_seq, article) 섹션 원문. 그날 판이 없거나 그 섹션이 없으면 None."""
    check_date(as_of)
    st = store or default_store()
    page = st.page_version(rule_seq, as_of)
    if page is None:
        return None
    rows = st.section_rows(rule_seq, page["version_id"], article)
    if not rows:
        return None
    bodies = rebuild(rows)
    starts = [r["line_start"] for r in rows]
    ends = [r["line_end"] for r in rows]
    return Section(rule_seq=rule_seq, rule_title=page["title"], article=article, version_id=page["version_id"],
                   version_date=str(page["version_date"]), version_date_before=bool(page["version_date_before"]),
                   text="\n".join(bodies), source_url=page["source_url"],
                   line_start=min(starts) if None not in starts else None,
                   line_end=max(ends) if None not in ends else None,
                   chunk_ids=[r["chunk_id"] for r in rows])


def section_names(rule_seq: int, as_of: str | None = None, store: SectionStore | None = None) -> list[str | None]:
    """그 판의 섹션 이름(첫 청크 seq 순서). 그날 판이 없으면 []."""
    check_date(as_of)
    st = store or default_store()
    page = st.page_version(rule_seq, as_of)
    return st.articles(rule_seq, page["version_id"]) if page else []


# ---------- 저장소 ----------

class MemorySectionStore:
    """시험용. rows = chunks 줄(rule_seq·version_id·seq·article·kind·text·text_sha256·line_*·chunk_id),
    pages = versions·docs 줄(rule_seq·version_id·title·source_url·version_date·version_date_before·valid_from·valid_to)."""

    def __init__(self, rows: list[dict], pages: list[dict]):
        self.rows, self.pages = rows, pages

    def page_version(self, rule_seq, as_of):
        for p in self.pages:
            if p["rule_seq"] != rule_seq:
                continue
            if as_of is None and p.get("valid_to") is None:
                return p
            if as_of is not None and p["valid_from"] <= as_of and (p.get("valid_to") is None or as_of < p["valid_to"]):
                return p
        return None

    def section_rows(self, rule_seq, version_id, article):
        return sorted((r for r in self.rows if r["rule_seq"] == rule_seq and r["version_id"] == version_id
                       and r["article"] == article), key=lambda r: r["seq"])

    def articles(self, rule_seq, version_id):
        first = {}
        for r in sorted((r for r in self.rows if r["rule_seq"] == rule_seq and r["version_id"] == version_id),
                        key=lambda r: r["seq"]):
            first.setdefault(r["article"], r["seq"])
        return list(first)

    def orgs(self):
        return {r["org"] for r in self.rows if r.get("org")}


class PgSectionStore:
    """검색과 같은 DB. 값은 자리(%(이름)s)로 넘긴다. Supabase transaction pooler 대비 prepare_threshold=None(search.PgStore와 같음)."""

    def __init__(self, url: str):
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(url, min_size=1, max_size=2, open=True, kwargs={"prepare_threshold": None})

    def _all(self, sql: str, params: dict) -> list[tuple]:
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def page_version(self, rule_seq, as_of):
        rows = self._all("""SELECT v.version_id, v.version_date, v.version_date_before, d.title, d.source_url
FROM versions v JOIN docs d ON d.rule_seq = v.rule_seq
WHERE v.rule_seq = %(r)s
  AND (CASE WHEN %(as_of)s::date IS NULL THEN v.valid_to IS NULL
            ELSE v.valid_from <= %(as_of)s::date AND (v.valid_to IS NULL OR %(as_of)s::date < v.valid_to) END)""",
                         {"r": rule_seq, "as_of": as_of})
        if not rows:
            return None
        vid, vdate, before, title, url = rows[0]
        return {"version_id": vid, "version_date": vdate, "version_date_before": before, "title": title,
                "source_url": url}

    def section_rows(self, rule_seq, version_id, article):
        rows = self._all("""SELECT chunk_id, seq, kind, text, text_sha256, line_start, line_end FROM chunks
WHERE rule_seq = %(r)s AND version_id = %(v)s AND article IS NOT DISTINCT FROM %(a)s::text ORDER BY seq""",
                         {"r": rule_seq, "v": version_id, "a": article})
        cols = ("chunk_id", "seq", "kind", "text", "text_sha256", "line_start", "line_end")
        return [dict(zip(cols, r)) for r in rows]

    def articles(self, rule_seq, version_id):
        rows = self._all("""SELECT article FROM chunks WHERE rule_seq = %(r)s AND version_id = %(v)s
GROUP BY article ORDER BY min(seq)""", {"r": rule_seq, "v": version_id})
        return [r[0] for r in rows]

    def orgs(self):
        return {r[0] for r in self._all("SELECT DISTINCT org FROM docs", {})}


_store: PgSectionStore | None = None
_lock = threading.Lock()


def default_store() -> PgSectionStore:
    global _store
    with _lock:
        if _store is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL이 없다")
            _store = PgSectionStore(url)
    return _store
