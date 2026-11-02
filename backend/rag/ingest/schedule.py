"""증분 수집 ②: 정해진 시각에 한 번 — 새 커밋만 받아 바뀐 쪽만 다시 처리하고, 바뀐 섹션을 리콜 표에 쌓는다.

    python -m backend.rag.ingest.schedule --once                  (정시 실행: 오늘 UTC 날짜 슬롯)
    python -m backend.rag.ingest.schedule --once --slot manual-1  (같은 날 손으로 한 번 더)

Spec: docs/specs/incremental.md. 한 번의 실행:
① 슬롯 차지(같은 슬롯이면 아무것도 안 함) ② 색인 장부의 임베딩 모델 대조 ③ fetch → 두 끝 비교(diff.py)
④ 바뀐 쪽 파싱·청킹(처음 수집과 같은 함수) ⑤ 같은 글이면 벡터 재사용, 없는 것만 임베딩
⑥ 한 트랜잭션: 옛 판 닫기·새 판 넣기·바뀐 섹션·실행 기록·generation+1 → 실패하면 전부 되돌리고 failed로 남긴 뒤 종료 코드 1
(실패 알림은 workflow의 if: failure() 단계가 보낸다 — 파이썬이 중간에 죽어도 알림이 간다).
목록이 불완전한 날(빈 폴더)은 삭제만 보류하고 성공으로 끝내되 보류 알림을 보내고, 다음 완전한 실행이 보류한 쪽을 다시 확인한다.
두 커밋을 비교하지 못한 날(커밋 없음·ls-tree 실패)은 실패다.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from backend.rag.ingest import chunk as chunking
from backend.rag.ingest.handbook import PINNED_COMMIT, commit_day, front_matter, org_of, page_url, rule_seq
from backend.rag.ingest.parse import ParseError, parse_page

JOB = "handbook-sync"
SQL = Path(__file__).resolve().parents[3] / "db" / "202_sync.sql"
# 동결 기준일 = 고정 커밋(129243bc) 날짜. 평가셋 정답이 이 날의 판을 본다(SDD 11장).
# 새 판의 유효 시작·옛 판의 유효 끝을 이 날 다음 날보다 앞으로 두지 않는다 → as_of=동결일 검색 결과는 증분 뒤에도 같다.
# (같은 날 고정 커밋 뒤에 고친 쪽은 판 날짜가 이 날이라 그대로 두면 동결일 검색에 새 판이 섞인다.)
FROZEN_AS_OF = date(2026, 10, 27)
FLOOR = FROZEN_AS_OF + timedelta(days=1)
CHUNK_SIZE, CHUNK_OVERLAP = 800, 120            # chunk.py 기본값(Spec chunk.md)과 같아야 한다 — 테스트가 대조
CHUNK_CONFIG = f"structure-s{CHUNK_SIZE}-o{CHUNK_OVERLAP}-h"
FETCH_TRIES = 3                                 # 재시도 정책(Spec 표): git fetch만, 간격을 늘려 3번
# 비교 자체를 못 한 이유(diff.list_changes). 이때는 사라진 쪽뿐 아니라 새로 생긴·바뀐 쪽도 못 봤다
# → 보류(성공)가 아니라 실패로 끝내고, 다음 실행이 같은 커밋부터 다시 본다(EC-03). empty_folder 는 보류.
LIST_FAILED = ("commit_missing", "ls_tree_failed")


class SyncError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def slot_of(now: datetime) -> str:
    """정시 실행 슬롯 = UTC 날짜. 한국 03:07에 돌아도, 몇 분 늦게 돌아도 같은 이름."""
    if now.tzinfo is None:
        raise ValueError("now는 시간대가 있어야 한다(UTC로 바꿔 슬롯을 정한다)")
    return now.astimezone(timezone.utc).date().isoformat()


def event_id(a: dict) -> str:
    key = f"{a['rule_seq']}:{a['article']}:{a['new_version_date']}:{a['change_type']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ── 원천: git(운영) 또는 시험용 가짜 ──
@dataclass
class Source:
    """두 끝 비교 결과. report는 diff.diff_commits 의 반환값, raw는 새 판 원문(경로 → 글)."""
    head: str
    head_date: str
    report: dict
    raw: dict[str, str] = field(default_factory=dict)
    head_paths: set[str] | None = None      # 새 커밋의 쪽 경로 전부(목록이 완전할 때만). 보류한 삭제를 다시 확인할 때 쓴다


def git_source(cache: Path, from_commit: str, log=print) -> Source:
    """핸드북 캐시를 준비하고(blob:none + 고른 폴더) 새 커밋을 받은 뒤 from_commit 과 비교한다."""
    from backend.rag.ingest import diff
    from backend.rag.ingest.handbook import ensure_checkout, git, list_pages
    ensure_checkout(cache)
    for i in range(FETCH_TRIES):
        done = subprocess.run(["git", "-C", str(cache), "fetch", "-q", "--filter=blob:none", "origin", "main"],
                              capture_output=True)
        if done.returncode == 0:
            break
        if i == FETCH_TRIES - 1:
            raise SyncError("fetch_failed", done.stderr.decode("utf-8", "replace").strip()[-500:])
        time.sleep(5 * 2 ** i)
    head = git(cache, "rev-parse", "FETCH_HEAD").decode().strip()
    head_date = commit_day(cache, head)
    if head == from_commit:
        return Source(head, head_date, {})
    raw: dict[str, str] = {}
    report = diff.diff_commits(cache, from_commit, head, fetch_ok=True, raw_out=raw)
    log(f"비교 {from_commit[:10]} → {head[:10]}: {report['summary']}")
    head_paths = {p for p, _ in list_pages(cache, head)} if report["changes"]["list_complete"] else None
    return Source(head, head_date, report, raw, head_paths)


# ── 쪽 하나 → 새 판 청크 ──
def page_chunks(path: str, raw: str, version: list, fetched_at: str) -> tuple[dict, list[dict]]:
    """처음 수집(handbook.collect → parse.run → chunk.run)과 같은 함수로 쪽 정보와 청크를 만든다."""
    fm = front_matter(raw)
    page = {"rule_seq": rule_seq(path), "org": org_of(path), "path": path,
            "title": fm.get("title") or Path(path).parent.name, "source_url": page_url(path),
            "version_id": version[0], "version_date": version[1], "version_date_before": bool(version[2]),
            "fetched_at": fetched_at, "redirect_to": fm.get("redirect_to")}
    if page["redirect_to"]:
        return page, []                 # 처음 수집도 다른 쪽으로 넘기는 쪽은 청크를 만들지 않았다(parse.run)
    elements = parse_page(page, raw, collections.Counter())
    chunks = chunking.chunk_structure(page, elements, CHUNK_SIZE, CHUNK_OVERLAP, True, CHUNK_CONFIG)
    for c in chunks:
        c.pop("_body", None)
    return page, chunks


# ── DB ──
def claim(conn, slot: str, trigger: str, now: datetime) -> int | None:
    """슬롯 차지. 영향 행이 1이면 run_id, 0이면(이미 그 슬롯이 있음) None."""
    row = conn.execute("""INSERT INTO sync_runs (job, slot, trigger, status, started_at)
                          VALUES (%s, %s, %s, 'running', %s) ON CONFLICT (job, slot) DO NOTHING RETURNING run_id""",
                       (JOB, slot, trigger, now)).fetchone()
    conn.commit()
    return row[0] if row else None


def last_commit(conn) -> str:
    """마지막으로 성공 반영한 커밋. 처음이면 스냅샷의 고정 커밋."""
    row = conn.execute("""SELECT to_commit FROM sync_runs WHERE job = %s AND status IN ('succeeded', 'noop')
                          AND to_commit IS NOT NULL ORDER BY finished_at DESC, run_id DESC LIMIT 1""", (JOB,)).fetchone()
    return row[0] if row else PINNED_COMMIT


def pending_holds(conn) -> list[dict]:
    """아직 다시 확인하지 못한 삭제 보류 = 마지막으로 목록을 끝까지 받아 성공한 실행 뒤의, 목록이 불완전했던 성공 실행들.
    보류한 날 last_commit 은 앞으로 가므로, 다음 날 두 끝 비교에는 그 쪽이 다시 '사라짐'으로 나오지 않는다
    → 여기서 따로 꺼내 다음 완전한 실행이 다시 확인한다(rag4-13 "다음 동기화에서 다시 확인")."""
    rows = conn.execute("""SELECT detail FROM sync_runs WHERE job = %s AND status = 'succeeded' AND list_complete = false
                           AND run_id > COALESCE((SELECT max(run_id) FROM sync_runs WHERE job = %s
                                                  AND status = 'succeeded' AND list_complete), 0)
                           ORDER BY run_id""", (JOB, JOB)).fetchall()
    return [r[0] for r in rows if r[0].get("removed_held")]


def check_index(conn, model: str, dim: int) -> None:
    """색인 장부와 지금 쓸 임베딩 모델이 같은가. 차원이 같고 모델만 달라도 오류 없이 틀리므로 이름까지 대조(rag1-11)."""
    row = conn.execute("SELECT embedder, dim, status FROM index_meta WHERE id = 1").fetchone()
    if not row or row[2] != "ready":
        raise SyncError("index_not_ready", f"index_meta {row}")
    if (row[0], row[1]) != (model, dim):
        raise SyncError("index_mismatch", f"색인 {row[0]}({row[1]}) ≠ 지금 {model}({dim}) — 전체 다시 적재(load_snapshot) 필요")


def apply(conn, run_id: int, src: Source, model: str, embed_fn: Callable[[list[str]], np.ndarray],
          now: datetime, log=print) -> dict:
    """반영. 임베딩은 트랜잭션 밖에서 먼저 하고, 쓰기는 한 트랜잭션으로 한다(rag4-14)."""
    rep, fetched_at = src.report, now.astimezone(timezone.utc).date().isoformat()
    ch = rep["changes"]
    failed = [r for r in ch["reasons"] if r.startswith(LIST_FAILED)]
    if failed:                                      # 비교를 못 했다 ≠ 바뀐 게 없다 → 성공으로 끝내지 않는다(시끄러운 실패)
        raise SyncError("list_failed", ", ".join(failed))
    plan, detail = [], collections.defaultdict(list)
    for p in rep["pages"]:
        if p["kind"] == "error":
            detail["errors"].append({"path": p["path"], "error": p["error"]})      # 그 쪽만 건너뜀(rag1-07)
            continue
        if p["page_change"] == "removed":
            continue
        try:
            page, chunks = page_chunks(p["path"], src.raw[p["path"]], p["new_version"], fetched_at)
        except (ParseError, KeyError, ValueError) as e:
            detail["errors"].append({"path": p["path"], "error": f"{type(e).__name__}: {e}"})
            continue
        if p.get("review"):
            detail["review"].append(p["path"])                                 # 처음 보는 단축코드: 그 요소만 색인에서 빠짐(처음 수집과 같음)
        page["_label"] = "format_only" if p["kind"] == "format_only" else p["page_change"]
        plan.append((page, chunks))

    # 같은 쪽에 같은 글(머리말·겹침 포함, 임베딩 입력 그대로)의 벡터가 있으면 재사용. 서식만 바뀐 쪽은 거의 다 재사용.
    seqs = [pg["rule_seq"] for pg, _ in plan]
    known = {}
    if seqs:
        for text, emb in conn.execute("""SELECT text, embedding FROM chunks WHERE rule_seq = ANY(%s) AND embedder = %s
                                         AND embedding IS NOT NULL""", (seqs, model)):
            # 차원 없는 vector 칸은 pgvector가 Vector 객체로 돌려준다 → numpy로
            known[text] = np.asarray(emb.to_numpy() if hasattr(emb, "to_numpy") else emb, dtype=np.float32)
    need = list(dict.fromkeys(c["text"] for _, cs in plan for c in cs if c["text"] not in known))
    if need:
        vecs = embed_fn(need)
        if len(vecs) != len(need):
            raise SyncError("embed_failed", f"벡터 {len(vecs)}개 ≠ 글 {len(need)}개")
        known.update(zip(need, vecs))
    reused = sum(1 for _, cs in plan for c in cs) - len(need)

    complete = ch["list_complete"]
    removed_seen = [r[0] for r in ch["removed"]]
    removed_applied = removed_seen if complete else []                  # 못 본 것과 사라진 것은 다르다(rag4-13)
    removed_held = [] if complete else removed_seen
    held_seqs = {rule_seq(p) for p in removed_held}
    # 보류한 쪽의 '사라진 섹션'은 리콜에 아직 보내지 않는다(닫지도 않은 쪽을 사라졌다고 알리지 않음) → 다시 확인해 닫는 날 보낸다
    articles = [a for a in rep["articles"] if a["rule_seq"] not in held_seqs]
    held_articles = [a for a in rep["articles"] if a["rule_seq"] in held_seqs]
    # 앞서 보류한 삭제 다시 확인: 오늘 목록이 완전하고 그 쪽이 새 커밋에도 없으면 닫는다. 다시 생긴 쪽은 그대로 둔다.
    retry, kept = [], []                                                # retry: (경로, 보류한 날의 판 날짜)
    if complete and src.head_paths is not None:
        seen = set(removed_seen)
        for d in pending_holds(conn):
            for path in d["removed_held"]:
                if path in seen:
                    continue
                seen.add(path)
                if path in src.head_paths:
                    kept.append(path)
                else:
                    retry.append((path, d.get("held_date") or src.head_date))
                    retry_seq = rule_seq(path)
                    articles += [a for a in d.get("held_articles", []) if a["rule_seq"] == retry_seq]
    with conn.transaction():
        ord0 = conn.execute("SELECT COALESCE(max(ord), -1) + 1 FROM chunks").fetchone()[0]
        n_new = 0
        for page, chunks in plan:
            vid, vdate = page["version_id"], page["version_date"]
            if conn.execute("SELECT 1 FROM versions WHERE rule_seq = %s AND version_id = %s",
                            (page["rule_seq"], vid)).fetchone():
                continue                                                       # 이미 반영한 판(멱등)
            detail[page["_label"]].append(page["path"])
            conn.execute("""INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (rule_seq) DO UPDATE SET title = EXCLUDED.title, fetched_at = EXCLUDED.fetched_at""",
                         (page["rule_seq"], page["org"], page["title"], page["source_url"], fetched_at))
            start = max(date.fromisoformat(vdate), FLOOR)
            conn.execute("""UPDATE versions SET valid_to = GREATEST(%s::date, valid_from)
                            WHERE rule_seq = %s AND valid_to IS NULL""", (start, page["rule_seq"]))
            if not chunks:
                continue                                                       # 넘기는 쪽: 옛 판만 닫는다
            conn.execute("""INSERT INTO versions (rule_seq, version_id, version_date, version_date_before, valid_from)
                            VALUES (%s, %s, %s, %s, %s)""", (page["rule_seq"], vid, vdate, page["version_date_before"], start))
            with conn.cursor() as c:
                c.executemany("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url,
                                                     text_sha256, line_start, line_end, embedding, embedder)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                              [(x["chunk_id"], vid, x["rule_seq"], x["seq"], ord0 + n_new + i, x["article"], x["kind"],
                                x["text"], x["source_url"], x["text_sha256"], x["line_start"], x["line_end"],
                                known[x["text"]], model) for i, x in enumerate(chunks)])
            n_new += len(chunks)
            got = conn.execute("SELECT count(*) FROM chunks WHERE rule_seq = %s AND version_id = %s",
                               (page["rule_seq"], vid)).fetchone()[0]
            if got != len(chunks):                                             # 행 수 대조(rag4-09)
                raise SyncError("count_mismatch", f"{page['path']}: 청크 {len(chunks)}개 중 DB {got}개")
        end = max(date.fromisoformat(src.head_date), FLOOR)
        closed = 0
        for path in removed_applied:
            closed += conn.execute("""UPDATE versions SET valid_to = GREATEST(%s::date, valid_from)
                                      WHERE rule_seq = %s AND valid_to IS NULL""", (end, rule_seq(path))).rowcount
        retried = 0
        for path, held_date in retry:                                  # 유효 끝 = 처음 사라진 것으로 본 날(오늘이 아님)
            retried += conn.execute("""UPDATE versions SET valid_to = GREATEST(%s::date, valid_from)
                                       WHERE rule_seq = %s AND valid_to IS NULL""",
                                    (max(date.fromisoformat(held_date), FLOOR), rule_seq(path))).rowcount
        with conn.cursor() as c:
            c.executemany("""INSERT INTO changed_articles (event_id, run_id, rule_seq, article, old_version_date,
                                                           new_version_date, change_type)
                             VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING""",
                          [(event_id(a), run_id, a["rule_seq"], a["article"], a["old_version_date"], a["new_version_date"],
                            a["change_type"]) for a in articles])
            new_articles = c.rowcount if articles else 0
        # 현재 판이 둘인 쪽은 DB 고유 색인(versions_one_current)이 막는다 — 여기서 다시 세지 않는다
        conn.execute("UPDATE index_meta SET generation = generation + 1 WHERE id = 1")    # api가 BM25를 다시 만든다
        counts = {"added": len(detail["added"]), "modified": len(detail["modified"]),
                  "format_only": len(detail["format_only"]), "removed_seen": len(removed_seen),
                  "removed_applied": closed + retried, "removed_held": len(removed_held), "removed_retried": retried,
                  "articles": new_articles, "embedded": len(need), "reused": reused}
        detail.update(removed=removed_applied, removed_held=removed_held, list_reasons=ch["reasons"],
                      removed_retried=[p for p, _ in retry], removed_kept=kept)
        if removed_held:
            detail.update(held_date=src.head_date, held_articles=held_articles)
        finish(conn, run_id, "succeeded", now, src.head, complete, counts, dict(detail))
    log(f"반영 완료: {counts}" + ("" if complete else f" — 삭제 보류(목록 불완전: {ch['reasons']})"))
    return {**counts, "list_reasons": ch["reasons"]}


def finish(conn, run_id: int, status: str, now: datetime, to_commit: str | None, list_complete: bool | None = None,
           counts: dict | None = None, detail: dict | None = None, error: SyncError | None = None,
           from_commit: str | None = None) -> None:
    c = counts or {}
    conn.execute("""UPDATE sync_runs SET status = %s, finished_at = %s, to_commit = %s, list_complete = %s,
                        from_commit = COALESCE(%s, from_commit),
                        added = %s, modified = %s, format_only = %s, removed_seen = %s, removed_applied = %s,
                        articles = %s, embedded = %s, reused = %s, detail = %s, error_kind = %s, error_detail = %s
                    WHERE run_id = %s""",
                 (status, now, to_commit, list_complete, from_commit, c.get("added"), c.get("modified"),
                  c.get("format_only"), c.get("removed_seen"), c.get("removed_applied"), c.get("articles"),
                  c.get("embedded"), c.get("reused"), json.dumps(detail or {}, ensure_ascii=False),
                  error.kind if error else None, error.detail[:2000] if error else None, run_id))


def run(conn, *, trigger: str, now: datetime, slot: str | None, model: str, dim: int,
        source: Callable[[str], Source], embed_fn: Callable[[list[str]], np.ndarray], log=print) -> dict:
    """실행 한 번. 반환 {status, run_id, ...}. 실패면 기록을 남기고 SyncError를 다시 던진다(종료 코드 1 → 알림)."""
    conn.execute(SQL.read_text(encoding="utf-8"))
    conn.commit()
    slot = slot or slot_of(now)
    run_id = claim(conn, slot, trigger, now)
    if run_id is None:
        log(f"슬롯 {slot} 은 이미 시작됨 — 아무것도 하지 않는다")
        return {"status": "skipped_duplicate", "slot": slot}
    from_commit = None
    try:
        check_index(conn, model, dim)
        from_commit = last_commit(conn)
        conn.execute("UPDATE sync_runs SET from_commit = %s WHERE run_id = %s", (from_commit, run_id))
        conn.commit()
        src = source(from_commit)
        if src.head == from_commit or not src.report:
            finish(conn, run_id, "noop", now, src.head, True)
            conn.commit()
            log(f"새 커밋 없음({from_commit[:10]})")
            return {"status": "noop", "run_id": run_id, "slot": slot}
        counts = apply(conn, run_id, src, model, embed_fn, now, log)
        conn.commit()
        return {"status": "succeeded", "run_id": run_id, "slot": slot, **counts}
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 기록을 남기고 다시 던진다
        conn.rollback()
        err = e if isinstance(e, SyncError) else SyncError(type(e).__name__, str(e))
        finish(conn, run_id, "failed", now, None, error=err, from_commit=from_commit)
        conn.commit()
        log(f"실패: {err}")
        raise err from e


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingest.schedule")
    ap.add_argument("--once", action="store_true", required=True, help="한 번 돌고 끝낸다(정시 실행은 workflow가 부른다)")
    ap.add_argument("--slot", default=None, help="기본은 오늘 UTC 날짜. 같은 날 한 번 더 돌릴 때만 manual-<시각>")
    ap.add_argument("--cache", type=Path, default=Path(os.environ.get("HANDBOOK_CACHE")
                                                       or Path.home() / ".cache/provena/handbook"))
    a = ap.parse_args(argv)
    import psycopg
    from pgvector.psycopg import register_vector
    from backend.rag.retrieve import embed
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL이 없다")
    s = embed.spec()
    model_holder = {}

    def embed_fn(texts: list[str]) -> np.ndarray:        # 새 글이 있을 때만 모델을 올린다(서식만 바뀐 날은 안 올림)
        if "m" not in model_holder:
            model_holder["m"] = embed.load_model(s.name)
        return embed.encode_docs(model_holder["m"], texts)

    now = datetime.now(timezone.utc)
    with psycopg.connect(url, prepare_threshold=None) as conn:
        register_vector(conn)
        try:
            manual = bool(a.slot) or os.environ.get("GITHUB_EVENT_NAME", "schedule") != "schedule"
            out = run(conn, trigger="manual" if manual else "schedule", now=now, slot=a.slot, model=s.name, dim=s.dim,
                      source=lambda frm: git_source(a.cache, frm), embed_fn=embed_fn)
        except SyncError:
            return 1
    print(json.dumps(out, ensure_ascii=False))
    write_outputs(out, os.environ.get("GITHUB_OUTPUT"))
    return 0


def write_outputs(out: dict, path: str | None) -> None:
    """성공이지만 사람이 알아야 하는 날(목록 불완전 → 삭제 보류)을 workflow 다음 단계(보류 알림)에 넘긴다.
    알림 글에 그대로 들어가므로 따옴표·역슬래시 같은 글자는 뺀다."""
    if not path or not out.get("removed_held"):
        return
    reasons = re.sub(r"[^\w:,. /-]", "", ", ".join(out.get("list_reasons", [])))[:300]
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"held={int(out['removed_held'])}\nreasons={reasons}\n")


if __name__ == "__main__":
    raise SystemExit(main())
