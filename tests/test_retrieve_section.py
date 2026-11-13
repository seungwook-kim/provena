"""섹션 원문 조회 시험 (docs/specs/mcp.md AC-04·AC-05·EC-02·EC-05·EC-08).

DB 없이: 실제 청킹 함수(schedule.page_chunks)로 만든 청크를 되살려 파싱 요소 글과 대조한다.
스냅샷(data/index/chunks.jsonl)·파싱 결과(data/parsed/)가 있으면 전체 청크와 원문 대조 3건도 돈다(CI에는 없음).
TEST_DATABASE_URL이 있으면 증분 수집(schedule.run)으로 판 두 개를 만든 DB에서 as_of 시험을 한다.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.rag.ingest import schedule
from backend.rag.ingest.chunk import is_header_heading
from backend.rag.ingest.parse import parse_page
from backend.rag.retrieve import section
from backend.rag.retrieve.section import MemorySectionStore, SectionIntegrityError

ROOT = Path(__file__).resolve().parents[1]
PATH = "content/handbook/security/test-disclosure.md"
PARA = " ".join(f"Sentence number {i} explains the disclosure rule in detail." for i in range(40))
RAW = ("---\ntitle: Test Disclosure\n---\n\nIntro without heading.\n\n## Disclosure\n\n"
       + "\n\n".join([PARA[:500], PARA[500:1100], PARA[1100:1500]])
       + "\n\nSecurity issues are disclosed 30 days after the patch.\n\n## Contacts\n\nAsk the security team.\n")


def make(raw: str, vid: str, vdate: str, valid_to: str | None = None):
    page, chunks = schedule.page_chunks(PATH, raw, [vid, vdate, False], "2026-10-30")
    rows = [{**c, "version_id": vid} for c in chunks]
    meta = {"rule_seq": page["rule_seq"], "version_id": vid, "title": page["title"], "source_url": page["source_url"],
            "version_date": vdate, "version_date_before": False, "valid_from": vdate, "valid_to": valid_to}
    return page, rows, meta


def elements_text(page: dict, raw: str) -> dict:
    """파싱 요소 글을 섹션별로 "\n" 이은 것 = 청킹 전 원문(색인 대상만, chunk.covered와 같은 기준)."""
    out = collections.defaultdict(list)
    for el in parse_page(page, raw, collections.Counter()):
        if el["review"] or is_header_heading(el):
            continue
        out[" > ".join(el["heading_path"]) or None].append(el["text"])
    return {k: "\n".join(v) for k, v in out.items()}


def test_rebuild_matches_parsed_elements():
    """AC-04: 겹침이 있는 3청크 섹션·제목 없는 머리 섹션·1청크 섹션이 파싱 요소 글과 글자까지 같다."""
    page, rows, meta = make(RAW, "v1", "2026-09-01")
    st = MemorySectionStore(rows, [meta])
    want = elements_text(page, RAW)
    disclosure = [r for r in rows if r["article"] == "Disclosure"]
    assert len(disclosure) >= 3 and any(r["overlap_chars"] for r in disclosure)      # 겹침을 떼야 하는 섹션이다
    for article in (None, "Disclosure", "Contacts"):
        got = section.get_section(page["rule_seq"], article, store=st)
        assert got.text == want[article], article
        assert got.chunk_ids == [r["chunk_id"] for r in rows if r["article"] == article]
    got = section.get_section(page["rule_seq"], "Disclosure", store=st)
    assert got.line_start == min(r["line_start"] for r in disclosure)
    assert got.line_end == max(r["line_end"] for r in disclosure)
    assert got.version_id == "v1" and got.rule_title == "Test Disclosure"


def test_overlap_not_repeated():
    """겹친 글이 두 번 나오지 않는다(겹침 떼기를 지우면 실패)."""
    page, rows, meta = make(RAW, "v1", "2026-09-01")
    got = section.get_section(page["rule_seq"], "Disclosure", store=MemorySectionStore(rows, [meta]))
    assert got.text.count("Sentence number 7 explains") == 1


def test_tampered_chunk_is_error_not_text():
    """EC-05: 지문이 다르면 틀린 원문 대신 SectionIntegrityError(메시지에 chunk_id만)."""
    page, rows, meta = make(RAW, "v1", "2026-09-01")
    bad = [dict(r) for r in rows]
    i = next(i for i, r in enumerate(bad) if r["article"] == "Disclosure" and r["seq"] > 1)
    bad[i]["text"] = bad[i]["text"].replace("Sentence", "Sentense", 1)
    with pytest.raises(SectionIntegrityError) as e:
        section.get_section(page["rule_seq"], "Disclosure", store=MemorySectionStore(bad, [meta]))
    assert bad[i]["chunk_id"] in str(e.value) and "Sentense" not in str(e.value)
    no_sha = [dict(r, text_sha256=None) for r in rows]
    with pytest.raises(SectionIntegrityError):
        section.get_section(page["rule_seq"], "Contacts", store=MemorySectionStore(no_sha, [meta]))


def test_rows_have_no_overlap():
    """권한표 이사회 행처럼 한 섹션에 행 청크가 여럿이어도 겹침을 떼지 않는다(chunk.authz_chunks는 겹침 없이 만든다)."""
    bodies = ["Acquisitions over $5M: Board approval required for every deal", "Debt facilities: Board"]
    rows = [{"chunk_id": f"r{i}", "rule_seq": 7, "version_id": "a", "seq": i, "article": "Board-level approvals",
             "kind": "row", "text": f"Authorization Matrix (2023-05) > Board-level approvals\n{b}",
             "text_sha256": hashlib.sha256(b.encode()).hexdigest(), "line_start": 10 + i, "line_end": 11 + i}
            for i, b in enumerate(bodies)]
    meta = {"rule_seq": 7, "version_id": "a", "title": "Authorization Matrix (2023-05)", "source_url": "u",
            "version_date": "2023-05-01", "version_date_before": False, "valid_from": "2023-05-01", "valid_to": None}
    got = section.get_section(7, "Board-level approvals", store=MemorySectionStore(rows, [meta]))
    assert got.text == "\n".join(bodies)


def test_as_of_picks_old_version():
    """AC-05·EC-08: 개정 전 날짜면 옛 판(30일), 없으면 새 판(90일), 가장 이른 판보다 앞이면 None."""
    new_raw = RAW.replace("30 days", "90 days")
    page, old_rows, old = make(RAW, "v1", "2026-09-01", valid_to="2026-10-30")
    _, new_rows, new = make(new_raw, "v2", "2026-10-30")
    st = MemorySectionStore(old_rows + new_rows, [old, new])
    assert "30 days" in section.get_section(page["rule_seq"], "Disclosure", "2026-10-27", store=st).text
    assert "90 days" in section.get_section(page["rule_seq"], "Disclosure", store=st).text
    assert section.get_section(page["rule_seq"], "Disclosure", "2026-10-30", store=st).version_id == "v2"   # 구간 끝은 새 판
    assert section.get_section(page["rule_seq"], "Disclosure", "2026-08-31", store=st) is None
    assert section.section_names(page["rule_seq"], "2026-08-31", store=st) == []


def test_missing_section_and_names():
    """EC-02: 없는 섹션은 None, 후보는 그 판의 섹션 이름을 첫 청크 순서로."""
    page, rows, meta = make(RAW, "v1", "2026-09-01")
    st = MemorySectionStore(rows, [meta])
    assert section.get_section(page["rule_seq"], "Disclosure > Nope", store=st) is None
    assert section.get_section(123, "Disclosure", store=st) is None
    assert section.section_names(page["rule_seq"], store=st) == [None, "Disclosure", "Contacts"]


@pytest.mark.parametrize("bad", ["2026-1-01", "2026-02-30", "yesterday", "2026-11-03T00:00"])
def test_bad_date_is_value_error(bad):
    page, rows, meta = make(RAW, "v1", "2026-09-01")
    with pytest.raises(ValueError):
        section.get_section(page["rule_seq"], "Disclosure", bad, store=MemorySectionStore(rows, [meta]))


# ---------- 스냅샷 전체 (로컬에만) ----------

SNAP = ROOT / "data/index/chunks.jsonl"
PARSED = ROOT / "data/parsed/document_ir.jsonl"


def snapshot_store():
    rows = [json.loads(line) for line in SNAP.open(encoding="utf-8")]
    pages = {}
    for r in rows:
        pages.setdefault((r["rule_seq"], r["version_id"]), {
            "rule_seq": r["rule_seq"], "version_id": r["version_id"], "title": r["rule_title"],
            "source_url": r["source_url"].split("#")[0], "version_date": r["version_date"],
            "version_date_before": r["version_date_before"], "valid_from": r["version_date"], "valid_to": None})
    return rows, MemorySectionStore(rows, list(pages.values()))


@pytest.mark.skipif(not SNAP.exists(), reason="data/index 스냅샷 없음(로컬에만)")
def test_snapshot_every_section_passes_sha():
    """스냅샷 모든 섹션이 지문 검사를 통과한다(머리말·겹침 떼기 규칙이 실제 청크 전부에 맞다)."""
    rows, _ = snapshot_store()
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["rule_seq"], r["version_id"], r["article"])].append(r)
    for cs in groups.values():
        section.rebuild(sorted(cs, key=lambda r: r["seq"]))
    assert len(groups) > 15000


@pytest.mark.skipif(not (SNAP.exists() and PARSED.exists()), reason="스냅샷·파싱 결과 없음(로컬에만)")
def test_snapshot_three_sections_match_parsed():
    """AC-04 원문 대조 3건: 청크 2개 이상인 실제 섹션 3개가 파싱 결과의 같은 섹션 요소 글과 같다."""
    rows, st = snapshot_store()
    multi = collections.Counter((r["rule_seq"], r["article"]) for r in rows)
    want = collections.defaultdict(list)
    for line in PARSED.open(encoding="utf-8"):
        el = json.loads(line)
        if not (el["review"] or is_header_heading(el)):
            want[(el["rule_seq"], " > ".join(el["heading_path"]) or None)].append(el["text"])
    checked = []
    for key, n in sorted(multi.items(), key=lambda x: -x[1]):
        if n < 2 or key not in want:
            continue
        got = section.get_section(key[0], key[1], store=st)
        if got.text == "\n".join(want[key]):
            checked.append(key)
        if len(checked) == 3:
            break
    assert len(checked) == 3, checked


# ---------- DB (로컬 pgvector) ----------

DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL 없음(로컬 pgvector에서만)")


@pytest.fixture
def pg_two_versions():
    """증분 수집(schedule.run)으로 옛 판(30일)·새 판(90일)을 만든 DB."""
    import psycopg
    from pgvector.psycopg import register_vector
    from tests.test_ingest_schedule import DIM, MODEL, Embed, fake_vec, source
    with psycopg.connect(DB, prepare_threshold=None) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("DROP TABLE IF EXISTS changed_articles, sync_runs, chunks, versions, docs, index_meta, "
                  "query_translations CASCADE")
        c.execute((ROOT / "db/201_search.sql").read_text(encoding="utf-8"))
        c.execute((ROOT / "db/202_sync.sql").read_text(encoding="utf-8"))
        register_vector(c)
        page, chunks = schedule.page_chunks(PATH, RAW, ["oldv00000000", "2026-09-01", False], "2026-10-30")
        c.execute("INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, %s, %s, %s, '2026-10-30')",
                  (page["rule_seq"], page["org"], page["title"], page["source_url"]))
        c.execute("INSERT INTO versions (rule_seq, version_id, version_date, valid_from) VALUES (%s, 'oldv00000000', "
                  "'2026-09-01', '2026-09-01')", (page["rule_seq"],))
        for i, x in enumerate(chunks):
            c.execute("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url,
                                             text_sha256, line_start, line_end, embedding, embedder)
                         VALUES (%s, 'oldv00000000', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                      (x["chunk_id"], x["rule_seq"], x["seq"], i, x["article"], x["kind"], x["text"], x["source_url"],
                       x["text_sha256"], x["line_start"], x["line_end"], fake_vec(x["text"]), MODEL))
        c.execute("""INSERT INTO index_meta (id, embedder, revision, dim, n_chunks, chunks_sha256, vectors_sha256, status)
                     VALUES (1, %s, 'r', %s, 0, 'x', 'y', 'ready')""", (MODEL, DIM))
        c.commit()
        out = schedule.run(c, trigger="schedule", now=datetime(2026, 11, 2, 18, 7, tzinfo=timezone.utc), slot=None,
                           model=MODEL, dim=DIM, source=source(RAW, RAW.replace("30 days", "90 days"),
                                                                ["newv00000000", "2026-10-30", False]),
                           embed_fn=Embed(), log=lambda *_: None)
        assert out["status"] == "succeeded", out
        yield c, page


@needs_db
def test_pg_section_as_of(pg_two_versions):
    """AC-05 (DB): 같은 섹션의 개정 전후 원문을 as_of로 가른다. 겹침이 있는 섹션도 파싱 요소 글과 같다."""
    c, page = pg_two_versions
    st = section.PgSectionStore(DB)
    try:
        old = section.get_section(page["rule_seq"], "Disclosure", "2026-10-27", store=st)
        new = section.get_section(page["rule_seq"], "Disclosure", store=st)
        assert old.version_id == "oldv00000000" and "30 days" in old.text and len(old.chunk_ids) >= 3
        assert new.version_id == "newv00000000" and "90 days" in new.text
        assert old.text == elements_text(page, RAW)["Disclosure"]
        assert section.get_section(page["rule_seq"], None, store=st).text == "Intro without heading."
        assert section.section_names(page["rule_seq"], "2026-10-27", store=st) == [None, "Disclosure", "Contacts"]
        assert section.get_section(page["rule_seq"], "Disclosure", "2026-08-01", store=st) is None
    finally:
        st.pool.close()


# 표 행 안에서 시작한 겹침은 행 처음부터(또는 첫 칸을 붙여) 가져오므로, 섹션 원문 되살리기가 그것도 떼어 내야 한다(2026-11-13)
TABLE_RAW = ("---\ntitle: Test Table\n---\n\n## Labels\n\n| Label | When it is used | Links |\n|---|---|---|\n"
             + "\n".join(f"| label-{i} | " + f"Applied to request number {i} that we handle. " * (2 + 7 * (i % 3)) + f"| Link {i} |"
                         for i in range(12)) + "\n\nClosing note.\n")


def test_rebuild_with_table_row_overlap():
    page, rows, meta = make(TABLE_RAW, "v1", "2026-09-01")
    labels = [r for r in rows if r["article"] == "Labels"]
    tails = [r["text"].split("\n")[1] for r in labels if r["overlap_chars"]]
    assert len(labels) >= 4 and any(t.startswith("Label: label-") for t in tails)       # 행 처음(또는 첫 칸)부터 시작한 겹침이 있다
    got = section.get_section(page["rule_seq"], "Labels", store=MemorySectionStore(rows, [meta]))
    assert got.text == elements_text(page, TABLE_RAW)["Labels"]
    bad = [dict(r) for r in rows]
    i = next(i for i, r in enumerate(bad) if r["article"] == "Labels" and r["overlap_chars"])
    head, tail, rest = bad[i]["text"].split("\n", 2)
    bad[i]["text"] = "\n".join([head, tail[:-1] + "!", rest])                             # 겹침 글만 바꿔도 여전히 멈춘다
    with pytest.raises(SectionIntegrityError):
        section.get_section(page["rule_seq"], "Labels", store=MemorySectionStore(bad, [meta]))
