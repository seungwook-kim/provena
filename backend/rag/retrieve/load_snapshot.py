"""적재(모델 불필요): data/index/ → DB (docs/specs/search.md). `docker compose up` 의 loader가 db가 뜬 뒤 한 번 돌린다.

    python -m backend.rag.retrieve.load_snapshot [--index data/index] [--embedder <EMBED_MODEL>]

색인이 없으면 커밋한 압축(data/index.tar.gz)을 풀고, 그것도 없으면 INDEX_URL·INDEX_SHA256으로 받고, 다 없으면 건너뛴다(ensure_index).

순서(설계 D13): ① meta.json sha256으로 파일 대조 ② 같은 스냅샷이 이미 ready면 건너뜀 ③ index_meta=loading
④ docs·versions·chunks를 배치마다 커밋((chunk_id, version_id)로 upsert, 멱등) ⑤ 스냅샷 밖 행은 지우지 않음(증분이 넣은 판)
⑥ 대조: 스냅샷 청크가 다 있고, 벡터가 비었거나 다른 모델인 행이 0 ⑦ 링크 대상(links.jsonl, L1x2) ⑧ 번역 장부
⑨ 마지막에만 ready·generation+1.
중간에 끊기면 loading으로 남아 api가 뜨지 않는다(배치 커밋이지만 '준비 완료'는 맨 끝에만, rag4-09 행 수 대조).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from backend.rag.retrieve import embed
from backend.rag.retrieve.index import file_sha, load_rows

SQL = Path(__file__).resolve().parents[3] / "db" / "201_search.sql"
BATCH = 2000   # 근거 없음 — V1 적재 시간을 재고 조정한다
COLS = ("chunk_id", "version_id", "rule_seq", "seq", "ord", "article", "kind", "text", "source_url", "text_sha256",
        "line_start", "line_end", "embedding", "embedder")
TYPES = ("text", "text", "int8", "int4", "int4", "text", "text", "text", "text", "text", "int4", "int4", "vector", "text")


def page_url(url: str) -> str:
    return url.split("#", 1)[0]


def versions_of(rows: list[dict]) -> list[dict]:
    """페이지마다 판을 날짜순으로 세워 valid_from = 판 날짜, valid_to = 다음 판 날짜(마지막 판은 None)."""
    by_page: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_page[r["rule_seq"]].setdefault(r["version_id"], {
            "rule_seq": r["rule_seq"], "version_id": r["version_id"], "version_date": r["version_date"],
            "version_date_before": bool(r.get("version_date_before", False))})
    out = []
    for vs in by_page.values():
        ordered = sorted(vs.values(), key=lambda v: (v["version_date"], v["version_id"]))
        for i, v in enumerate(ordered):
            out.append({**v, "valid_from": v["version_date"],
                        "valid_to": ordered[i + 1]["version_date"] if i + 1 < len(ordered) else None})
    return out


def pick_embedder(meta: dict, name: str | None) -> tuple[str, dict]:
    ents = meta.get("embedders") or {}
    name = name or os.environ.get("EMBED_MODEL") or embed.DEFAULT_MODEL
    if name not in ents:
        raise SystemExit(f"스냅샷에 {name} 벡터가 없다(있는 것: {', '.join(ents) or '없음'})")
    return name, ents[name]


def verify_files(index: Path, meta: dict, ent: dict) -> None:
    for rel, want in ((meta["chunks_file"], meta["chunks_sha256"]), (ent["file"], ent["sha256"])):
        got = file_sha(index / rel)
        if got != want:
            raise SystemExit(f"파일이 meta.json과 다르다: {rel} (meta {want[:12]}…, 받은 것 {got[:12]}…)")


def load(conn, index: Path, embedder: str | None = None, batch: int = BATCH, log=print) -> dict:
    meta = json.loads((index / "meta.json").read_text(encoding="utf-8"))
    name, ent = pick_embedder(meta, embedder)
    verify_files(index, meta, ent)
    conn.execute(SQL.read_text(encoding="utf-8"))
    conn.commit()

    lk = meta.get("links")
    if lk and file_sha(index / lk["file"]) != lk["sha256"]:
        raise SystemExit(f"링크 파일이 meta.json과 다르다: {lk['file']}")
    cur = conn.execute("SELECT embedder, chunks_sha256, vectors_sha256, status, generation, links_sha256 "
                       "FROM index_meta WHERE id = 1").fetchone()
    # 줄 범위 칸이 생기기 전에 적재한 DB는 같은 스냅샷이어도 다시 넣는다(칸이 비어 있으면 #L 정답을 못 맞춘다)
    no_lines = conn.execute("SELECT EXISTS (SELECT 1 FROM chunks WHERE line_start IS NULL)").fetchone()[0]
    # 링크 파일이 있는 스냅샷인데 아직 안 실었으면(링크 칸이 생기기 전 적재) 다시 넣는다
    same_links = not lk or cur and cur[5] == lk["sha256"]
    if cur and cur[:4] == (name, meta["chunks_sha256"], ent["sha256"], "ready") and not no_lines and same_links:
        log(f"같은 스냅샷이 이미 적재됨({name}, generation {cur[4]}) — 건너뜀")
        return {"skipped": True, "generation": cur[4]}
    conn.execute("""INSERT INTO index_meta (id, embedder, revision, dim, prefixes, max_seq_length, n_chunks, chunks_sha256,
                                            vectors_sha256, status, generation, loaded_at)
                    VALUES (1, %(e)s, %(r)s, %(d)s, %(p)s, %(m)s, %(n)s, %(c)s, %(v)s, 'loading', 0, now())
                    ON CONFLICT (id) DO UPDATE SET embedder = EXCLUDED.embedder, revision = EXCLUDED.revision,
                        dim = EXCLUDED.dim, prefixes = EXCLUDED.prefixes, max_seq_length = EXCLUDED.max_seq_length,
                        n_chunks = EXCLUDED.n_chunks, chunks_sha256 = EXCLUDED.chunks_sha256,
                        vectors_sha256 = EXCLUDED.vectors_sha256, links_sha256 = NULL, status = 'loading',
                        loaded_at = now()""",
                 {"e": name, "r": ent["revision"], "d": ent["dim"], "p": json.dumps(ent.get("prefixes") or {}),
                  "m": ent.get("max_seq_length"), "n": meta["n_chunks"], "c": meta["chunks_sha256"], "v": ent["sha256"]})
    conn.commit()

    t0 = time.perf_counter()
    rows = load_rows(index / meta["chunks_file"])
    vecs = np.load(index / ent["file"], mmap_mode="r")
    if len(rows) != len(vecs) or len(rows) != meta["n_chunks"]:
        raise SystemExit(f"청크 {len(rows)} · 벡터 {len(vecs)} · meta {meta['n_chunks']} 가 다르다")

    pages = {r["rule_seq"]: r for r in rows}
    with conn.cursor() as c:
        c.executemany("""INSERT INTO docs (rule_seq, org, title, source_url, fetched_at)
                         VALUES (%(rule_seq)s, %(org)s, %(rule_title)s, %(url)s, %(fetched_at)s)
                         ON CONFLICT (rule_seq) DO UPDATE SET org = EXCLUDED.org, title = EXCLUDED.title,
                             source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at""",
                      [{**r, "url": page_url(r["source_url"])} for r in pages.values()])
        # 증분이 닫아 둔 판(valid_to가 있는 판)은 그대로 둔다
        c.executemany("""INSERT INTO versions (rule_seq, version_id, version_date, version_date_before, valid_from, valid_to)
                         VALUES (%(rule_seq)s, %(version_id)s, %(version_date)s, %(version_date_before)s, %(valid_from)s, %(valid_to)s)
                         ON CONFLICT (rule_seq, version_id) DO UPDATE SET version_date = EXCLUDED.version_date,
                             version_date_before = EXCLUDED.version_date_before, valid_from = EXCLUDED.valid_from,
                             valid_to = COALESCE(versions.valid_to, EXCLUDED.valid_to)""", versions_of(rows))
    conn.commit()

    conn.execute("CREATE TEMP TABLE IF NOT EXISTS chunks_in (LIKE chunks INCLUDING DEFAULTS) ON COMMIT PRESERVE ROWS")
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLS[2:])
    for start in range(0, len(rows), batch):
        part = rows[start:start + batch]
        with conn.cursor() as c:
            c.execute("TRUNCATE chunks_in")
            with c.copy(f"COPY chunks_in ({', '.join(COLS)}) FROM STDIN WITH (FORMAT BINARY)") as cp:
                cp.set_types(list(TYPES))
                for i, r in enumerate(part, start):
                    cp.write_row([r["chunk_id"], r["version_id"], r["rule_seq"], r["seq"], i, r.get("article"), r["kind"],
                                  r["text"], r["source_url"], r.get("text_sha256"), r.get("line_start"), r.get("line_end"),
                                  np.asarray(vecs[i], dtype=np.float32), name])
            c.execute(f"INSERT INTO chunks ({', '.join(COLS)}) SELECT {', '.join(COLS)} FROM chunks_in "
                      f"ON CONFLICT (chunk_id, version_id) DO UPDATE SET {sets}")
        conn.commit()
        log(f"  {min(start + batch, len(rows))}/{len(rows)}")

    keys_ids = [r["chunk_id"] for r in rows]
    keys_vers = [r["version_id"] for r in rows]
    present = conn.execute("""SELECT count(*) FROM chunks c JOIN unnest(%(i)s::text[], %(v)s::text[]) AS k(chunk_id, version_id)
                              ON k.chunk_id = c.chunk_id AND k.version_id = c.version_id""",
                           {"i": keys_ids, "v": keys_vers}).fetchone()[0]
    stale = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL OR embedder IS DISTINCT FROM %(e)s "
                         "OR vector_dims(embedding) <> %(d)s", {"e": name, "d": ent["dim"]}).fetchone()[0]
    want = len(set(zip(keys_ids, keys_vers)))
    if present != want or stale:
        raise SystemExit(f"대조 실패: 스냅샷 청크 {want}개 중 DB에 {present}개, 다른 모델·빈 벡터 {stale}행 — loading으로 남김")

    n_link = load_links(conn, index, lk, rows) if lk else 0

    n_tr = 0
    tr = meta.get("query_translations")
    if tr:
        if file_sha(index / tr["file"]) != tr["sha256"]:
            raise SystemExit("번역 장부 파일이 meta.json과 다르다")
        items = [json.loads(x) for x in (index / tr["file"]).read_text(encoding="utf-8").splitlines() if x.strip()]
        with conn.cursor() as c:
            c.executemany("""INSERT INTO query_translations (query_sha256, model, keywords, sentence)
                             VALUES (%(query_sha256)s, %(model)s, %(keywords)s, %(sentence)s)
                             ON CONFLICT (query_sha256, model) DO NOTHING""", items)
        n_tr = len(items)

    gen = conn.execute("UPDATE index_meta SET status = 'ready', generation = generation + 1, loaded_at = now() "
                       "WHERE id = 1 RETURNING generation").fetchone()[0]
    conn.commit()
    secs = round(time.perf_counter() - t0, 1)
    log(f"적재 완료: {name}, 청크 {present}개, 링크 있는 청크 {n_link}개, 번역 {n_tr}개, {secs}초, generation {gen}")
    return {"skipped": False, "chunks": present, "links": n_link, "translations": n_tr, "seconds": secs, "generation": gen}


def load_links(conn, index: Path, lk: dict, rows: list[dict]) -> int:
    """links.jsonl(줄 순서 = chunks.jsonl) → chunks.link_targets. 줄 순서·개수가 청크와 다르면 멈춘다(loading으로 남음)."""
    items = [json.loads(x) for x in (index / lk["file"]).read_text(encoding="utf-8").splitlines() if x.strip()]
    if [(x["chunk_id"], x["version_id"]) for x in items] != [(r["chunk_id"], r["version_id"]) for r in rows]:
        raise SystemExit("링크 파일 줄이 청크 파일과 다르다 — index links를 다시 돌린다")
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS links_in (chunk_id text, version_id text, targets bigint[]) "
                 "ON COMMIT PRESERVE ROWS")
    with conn.cursor() as c:
        c.execute("TRUNCATE links_in")
        # 배열은 PostgreSQL 배열 글('{1,2}', 빈 목록은 '{}')로 직접 써서 넘긴다. 빈 파이썬 list는 원소 형을 몰라
        # 드라이버 추론에 기대게 되므로, 텍스트 COPY에서 서버가 칸 형(bigint[])으로 읽게 한다(PostgreSQL 문서 8.15.2).
        with c.copy("COPY links_in (chunk_id, version_id, targets) FROM STDIN") as cp:
            for x in items:
                cp.write_row([x["chunk_id"], x["version_id"], "{" + ",".join(str(int(t)) for t in x["targets"]) + "}"])
        n = c.execute("""UPDATE chunks SET link_targets = l.targets FROM links_in l
                         WHERE chunks.chunk_id = l.chunk_id AND chunks.version_id = l.version_id""").rowcount
        want = len({(x["chunk_id"], x["version_id"]) for x in items})
        if n != want:
            raise SystemExit(f"링크 대조 실패: {want}행 중 {n}행만 반영 — loading으로 남김")
        c.execute("UPDATE index_meta SET links_sha256 = %(s)s WHERE id = 1", {"s": lk["sha256"]})
    conn.commit()
    return sum(1 for x in items if x["targets"])


def ensure_index(index: Path, log=print) -> bool:
    """색인이 있으면 True. 없으면 ① 커밋한 압축 `data/index.tar.gz`를 풀어 meta.json sha256과 대조한다(기본 위치일 때만,
    backend/rag/ingest/snapshot.py). ② 그것도 없으면 INDEX_URL(tar.gz)을 받아 INDEX_SHA256과 대조한 뒤 푼다(조장 답 ②).
    주소도 없으면 False — compose가 색인 없이도 뜨게(팀원 PC·CI) 하고, 검색은 search()가 '색인이 준비되지 않았다'로 멈춘다.
    INDEX_REQUIRED=1이면 색인이 없을 때 실패로 끝내 api가 뜨지 않게 한다(배포용)."""
    from backend.rag.ingest import snapshot
    if snapshot.ensure_index(index, log=log):
        return True
    url = (os.environ.get("INDEX_URL") or "").strip()
    if not url:
        if os.environ.get("INDEX_REQUIRED") == "1":
            raise SystemExit(f"{index}/meta.json도 INDEX_URL도 없다(INDEX_REQUIRED=1)")
        log(f"색인 없음({index}/meta.json, INDEX_URL 비어 있음) — 적재를 건너뛴다. 검색은 준비되지 않은 상태로 뜬다")
        return False
    want = (os.environ.get("INDEX_SHA256") or "").strip().lower()
    if len(want) != 64:
        raise SystemExit("INDEX_URL을 받으려면 INDEX_SHA256(64자)이 필요하다 — 대조 없이 받은 색인은 쓰지 않는다")
    import hashlib
    import tarfile
    import tempfile
    import urllib.request
    index.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=index.parent) as tmp:
        dst = Path(tmp) / "index.tar.gz"
        h = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as r, dst.open("wb") as f:   # 주소는 로그에 남기지 않는다(토큰이 붙을 수 있음)
            for block in iter(lambda: r.read(1 << 20), b""):
                h.update(block)
                f.write(block)
        if h.hexdigest() != want:
            raise SystemExit(f"받은 색인이 INDEX_SHA256과 다르다(받은 것 {h.hexdigest()[:12]}…)")
        with tarfile.open(dst) as t:
            t.extractall(index, filter="data")       # 저장소 밖 경로·링크는 풀지 않는다
    if not (index / "meta.json").is_file():
        raise SystemExit("받은 색인에 meta.json이 없다")
    log(f"색인을 받아 풀었다({index}, sha256 {want[:12]}…)")
    return True


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.retrieve.load_snapshot")
    ap.add_argument("--index", type=Path, default=Path("data/index"))
    ap.add_argument("--embedder", default=None)
    ap.add_argument("--batch", type=int, default=BATCH)
    a = ap.parse_args(argv)
    if not ensure_index(a.index):
        return 0
    import psycopg
    from pgvector.psycopg import register_vector
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL이 없다")
    with psycopg.connect(url, prepare_threshold=None) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)
        load(conn, a.index, a.embedder, a.batch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
