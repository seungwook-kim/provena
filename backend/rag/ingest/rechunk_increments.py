"""증분 수집 ③: 증분이 넣은 현재 판의 청크를 고친 청크 생성 코드로 한 번 다시 만든다 (일회성, 결정 0118, 사전 등록 62.62).

    python -m backend.rag.ingest.rechunk_increments --dry-run      (DB 쓰기·Voyage 호출 없음, 무엇이 얼마나 바뀌는지만 본다)
    python -m backend.rag.ingest.rechunk_increments --max-cost 0.10

왜: `schedule.py`가 넣은 증분 판(DB `chunks`의 ord가 스냅샷 행 수 이상인 행)은 옛 청크 생성 코드로 만들어졌고, `schedule.apply`는 이미 있는
(rule_seq, version_id)를 건너뛰므로 코드를 고쳐도 다시 만들어지지 않는다. as_of 없는 실제 질문은 현재 판(valid_to IS NULL)만 보므로 그 쪽 답은
옛 청크에서 나온다. 이 도구는 그 판들만 다시 만든다. 스냅샷 행은 건드리지 않는다.

한 번의 실행(schedule.py와 같은 함수·같은 모양):
① 색인 장부가 ready이고 임베딩 모델이 같은지 대조(`schedule.check_index`) ② 대상 고르기: 현재 판이면서 스냅샷(`data/manifest.jsonl`의
(doc_id, version_id))에 없는 판. 닫힌 증분 판은 개수만 센다 ③ 쪽 원문을 그 판을 만든 실행의 `sync_runs.to_commit`에서 읽는다(`detail`의
added·modified·format_only 경로). 그 쪽의 마지막 수정 커밋이 version_id인지 대조한다 ④ `schedule.page_chunks`로 다시 청킹 ⑤ 판마다 옛 행과 비교
(같음·바뀜·새로·사라짐) ⑥ 같은 글의 벡터는 DB에서 재사용하고(schedule과 같은 질의), 없는 것만 임베딩(비용 상한 `--max-cost`를 쓰기 전에 추정으로 막는다)
⑦ 판마다 한 트랜잭션: 그 판의 행을 지우고 새 행을 넣는다(옛 행과 새 행이 한 판 안에 섞이지 않는다). 끝에서 `index_meta.generation`을 한 번만 +1.
바뀌지 않은 판은 쓰지 않는다 → 두 번째 실행은 바뀐 것 0, generation도 그대로(멱등).

환경 변수(이름만, 값은 출력하지 않는다): DATABASE_URL, VOYAGE_API_KEY(임베딩할 글이 있을 때만).
종료 코드: 0 완료, 1 일부 판 실패, 2 실행을 거부함(색인 준비 안 됨, 환경 변수 없음, 실행 중인 증분 수집 등), 3 비용 상한.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from backend.rag.ingest import schedule
from backend.rag.ingest.handbook import rule_seq as rule_seq_of
from backend.rag.retrieve import links

SNAPSHOT_ROWS = 23095                 # 스냅샷 적재가 ord 0..23094를 쓴다(load_snapshot.py). 증분 행은 그 뒤 번호
MAX_COST_USD = 0.10
TOKENS_PER_CHAR = 0.4                 # 보수적 추정. reembed 계획서 실측 0.21~0.33 토큰/글자의 위쪽 + 여유
ORIGIN_LABELS = ("added", "modified", "format_only")
ROW_COLS = ("chunk_id", "seq", "article", "kind", "text", "source_url", "text_sha256", "line_start", "line_end")
SAMPLE = 12                           # 판별 목록에 출력하는 최대 줄


class SourceError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


class Refused(RuntimeError):
    """실행을 시작하지 않는다(종료 코드 2)."""


class CostCap(RuntimeError):
    """추정 비용이 상한을 넘는다(종료 코드 3)."""


@dataclass
class Target:
    rule_seq: int
    version_id: str
    version_date: str
    version_date_before: bool
    min_ord: int
    rows: list[dict] = field(default_factory=list)


@dataclass
class VersionPlan:
    target: Target
    path: str
    page: dict
    chunks: list[dict]
    unchanged: list[str] = field(default_factory=list)       # chunk_id
    changed: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return bool(self.changed or self.new or self.removed)


# ── 원천: 쪽 원문 (git 또는 시험용 가짜) ──
PageReader = Callable[[int, str], tuple[str, str]]       # (rule_seq, version_id) → (경로, 원문). 못 읽으면 SourceError


def load_origins(conn) -> dict[int, tuple[str, str]]:
    """rule_seq → (경로, 그 판을 만든 실행의 to_commit). 성공한 실행을 오래된 것부터 읽어 같은 쪽은 마지막 실행이 이긴다
    (현재 판을 만든 실행 = 그 쪽을 마지막으로 반영한 실행. schedule.apply가 detail의 added·modified·format_only에 경로를 남긴다)."""
    out: dict[int, tuple[str, str]] = {}
    if not conn.execute("SELECT to_regclass('sync_runs') IS NOT NULL").fetchone()[0]:
        return out
    for to_commit, detail in conn.execute("""SELECT to_commit, detail FROM sync_runs WHERE job = %s AND status = 'succeeded'
                                             AND to_commit IS NOT NULL ORDER BY run_id""", (schedule.JOB,)):
        for label in ORIGIN_LABELS:
            for path in (detail or {}).get(label, []):
                out[rule_seq_of(path)] = (path, to_commit)
    return out


class GitPages:
    """운영 원천: 핸드북 캐시(schedule과 같은 `ensure_checkout`·`fetch_main`)에서 to_commit 시점의 쪽 원문을 읽는다."""

    def __init__(self, cache: Path, origins: dict[int, tuple[str, str]], log=print):
        from backend.rag.ingest.handbook import ensure_checkout
        ensure_checkout(cache)
        schedule.fetch_main(cache)
        self.cache, self.origins = cache, origins
        log(f"핸드북 캐시 준비: {cache}")

    def __call__(self, rule_seq: int, version_id: str) -> tuple[str, str]:
        from backend.rag.ingest.handbook import CollectError, git
        if rule_seq not in self.origins:
            raise SourceError("source_unknown", "sync_runs 기록에 이 쪽의 경로가 없다")
        path, to_commit = self.origins[rule_seq]
        try:
            last = git(self.cache, "log", "-1", "--format=%H", to_commit, "--", path).decode().strip()
            if not (last.startswith(version_id) or to_commit.startswith(version_id)):
                raise SourceError("version_mismatch", f"{path}: 그 커밋에서 마지막 수정은 {last[:12]}, DB 판은 {version_id}")
            raw = git(self.cache, "cat-file", "-p", f"{to_commit}:{path}").decode("utf-8")
        except (CollectError, UnicodeDecodeError) as e:
            raise SourceError("git_failed", f"{path}: {type(e).__name__}") from None
        return path, raw


# ── 대상 고르기 ──
def snapshot_versions(manifest: Path) -> set[tuple[int, str]]:
    """스냅샷 판 = data/manifest.jsonl의 (doc_id, version_id). doc_id가 rule_seq다."""
    out = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.add((int(r["doc_id"]), str(r["version_id"])))
    if not out:
        raise Refused(f"{manifest}에 판이 없다")
    return out


def find_targets(conn, snap: set[tuple[int, str]], snapshot_rows: int) -> tuple[list[Target], dict]:
    """현재 판이면서 스냅샷에 없는 판 = 대상. 닫힌 증분 판과 번호가 맞지 않는 판은 개수만 센다(바꾸지 않는다)."""
    stat = {"current_snapshot": 0, "current_incremental": 0, "closed_incremental": 0, "ord_anomaly": 0}
    targets: list[Target] = []
    rows = conn.execute("""SELECT v.rule_seq, v.version_id, v.version_date, v.version_date_before, v.valid_to IS NULL, min(c.ord)
                           FROM versions v JOIN chunks c ON c.rule_seq = v.rule_seq AND c.version_id = v.version_id
                           GROUP BY v.rule_seq, v.version_id, v.version_date, v.version_date_before, v.valid_to
                           ORDER BY v.rule_seq, v.version_id""").fetchall()
    for rs, vid, vdate, before, current, min_ord in rows:
        if (int(rs), vid) in snap:
            stat["current_snapshot"] += 1 if current else 0
            continue
        if not current:
            stat["closed_incremental"] += 1
            continue
        stat["current_incremental"] += 1
        if min_ord < snapshot_rows:                    # 증분 판인데 스냅샷 번호대의 행이 있다 → 이상한 상태, 건드리지 않는다
            stat["ord_anomaly"] += 1
            continue
        targets.append(Target(int(rs), vid, vdate.isoformat() if hasattr(vdate, "isoformat") else str(vdate), bool(before), int(min_ord)))
    return targets, stat


def load_rows(conn, targets: list[Target]) -> None:
    if not targets:
        return
    by = {(t.rule_seq, t.version_id): t for t in targets}
    q = conn.execute(f"""SELECT c.rule_seq, c.version_id, {', '.join('c.' + x for x in ROW_COLS)}, c.ord
                         FROM chunks c JOIN unnest(%s::bigint[], %s::text[]) AS k(rule_seq, version_id)
                           ON k.rule_seq = c.rule_seq AND k.version_id = c.version_id ORDER BY c.ord, c.seq""",
                     ([t.rule_seq for t in targets], [t.version_id for t in targets]))
    for r in q:
        by[(int(r[0]), r[1])].rows.append({**dict(zip(ROW_COLS, r[2:2 + len(ROW_COLS)])), "ord": r[-1]})


# ── 비교 ──
def row_key(r: dict) -> tuple:
    return tuple(r.get(k) for k in ROW_COLS)


def plan_version(t: Target, path: str, page: dict, chunks: list[dict]) -> VersionPlan:
    """옛 행과 새 청크를 chunk_id로 맞춘다. 같음 = chunk_id와 모든 칸(글·줄 범위·제목 경로 포함)이 같다.
    같은 chunk_id인데 다른 칸이 있으면 바뀜(벡터는 글이 같으면 재사용), 옛에만 있으면 사라짐, 새에만 있으면 새로."""
    p = VersionPlan(t, path, page, chunks)
    old = {r["chunk_id"]: r for r in t.rows}
    new = {c["chunk_id"]: c for c in chunks}
    for cid, c in new.items():
        if cid not in old:
            p.new.append(cid)
        elif row_key(old[cid]) == row_key(c):
            p.unchanged.append(cid)
        else:
            p.changed.append(cid)
    p.removed = [cid for cid in old if cid not in new]
    return p


def known_vectors(conn, rule_seqs: list[int], model: str) -> dict[str, np.ndarray]:
    """schedule.apply와 같은 질의: 같은 쪽에 같은 글(머리말·겹침 포함, 임베딩 입력 그대로)의 벡터가 있으면 재사용한다."""
    known: dict[str, np.ndarray] = {}
    if rule_seqs:
        for text, emb in conn.execute("""SELECT text, embedding FROM chunks WHERE rule_seq = ANY(%s) AND embedder = %s
                                         AND embedding IS NOT NULL""", (rule_seqs, model)):
            known[text] = np.asarray(emb.to_numpy() if hasattr(emb, "to_numpy") else emb, dtype=np.float32)
    return known


def estimate(texts: list[str]) -> dict:
    from backend.services import step_cost
    chars = sum(len(t) for t in texts)
    tokens = math.ceil(chars * TOKENS_PER_CHAR)
    price = step_cost.embed_usd_per_mtok()
    return {"texts": len(texts), "chars": chars, "est_tokens": tokens, "usd_per_mtok": price,
            "est_cost_usd": round(tokens * price / 1_000_000, 6)}


# ── 계획과 반영 ──
def build_plans(conn, targets: list[Target], read: PageReader, today: str, log=print) -> tuple[list[VersionPlan], list[dict]]:
    plans, skipped = [], []
    for t in targets:
        try:
            path, raw = read(t.rule_seq, t.version_id)
            page, chunks = schedule.page_chunks(path, raw, [t.version_id, t.version_date, t.version_date_before], today)
        except SourceError as e:
            skipped.append({"rule_seq": t.rule_seq, "version_id": t.version_id, "kind": e.kind, "detail": e.detail[:200]})
            continue
        except Exception as e:  # noqa: BLE001 — 파싱 오류 등: 그 판만 건너뛴다(schedule.apply와 같은 원칙)
            skipped.append({"rule_seq": t.rule_seq, "version_id": t.version_id, "kind": "parse_error",
                            "detail": f"{type(e).__name__}: {e}"[:200]})
            continue
        if not chunks:                                 # 지금 코드로는 청크가 하나도 안 나오는 쪽: 행을 통째로 지우지 않는다
            skipped.append({"rule_seq": t.rule_seq, "version_id": t.version_id, "kind": "empty_result", "detail": path})
            continue
        plans.append(plan_version(t, path, page, chunks))
    return plans, skipped


def summarize(plans: list[VersionPlan], skipped: list[dict], stat: dict, known: dict, model: str) -> tuple[dict, list[str]]:
    dirty = [p for p in plans if p.dirty]
    need = list(dict.fromkeys(c["text"] for p in dirty for c in p.chunks if c["text"] not in known))
    rows_new = sum(len(p.new) for p in dirty)
    total_chunks = sum(len(p.chunks) for p in dirty)
    report = {
        "embedder": model,
        **stat,
        "targets": len(plans) + len(skipped), "skipped": len(skipped),
        "skipped_by_kind": {k: sum(1 for s in skipped if s["kind"] == k) for k in sorted({s["kind"] for s in skipped})},
        "versions_unchanged": len(plans) - len(dirty), "versions_to_replace": len(dirty),
        "pages_to_replace": len({p.target.rule_seq for p in dirty}),
        "rows": {"unchanged": sum(len(p.unchanged) for p in plans), "changed": sum(len(p.changed) for p in plans),
                 "new": sum(len(p.new) for p in plans), "removed": sum(len(p.removed) for p in plans)},
        "rows_to_write": total_chunks, "rows_new_in_replaced": rows_new,
        "embeddings_needed": len(need), "vectors_reused": total_chunks - len(need) if dirty else 0,
        "estimate": estimate(need),
    }
    return report, need


def apply_plans(conn, plans: list[VersionPlan], known: dict[str, np.ndarray], model: str, out: dict, log=print) -> dict:
    """판마다 한 트랜잭션: 그 판의 행을 모두 지우고 새 청크를 넣는다. 한 판이 실패하면 그 판만 되돌리고 다음으로 간다.
    결과는 `out`(replaced, failed, stale)에 판마다 바로 쌓는다(중간에 끊겨도 몇 판을 바꿨는지 남는다)."""
    docs = conn.execute("SELECT source_url, rule_seq FROM docs").fetchall()
    conn.commit()
    url2seq = links.url_map([*docs, *((p.page["source_url"], p.page["rule_seq"]) for p in plans)])
    done, failed, stale = out.setdefault("done", []), out["failed"], out["stale"]
    for p in plans:
        if not p.dirty:
            continue
        t = p.target
        key = f"{p.path} ({t.version_id})"
        conn.commit()                                   # 열린 읽기 트랜잭션을 끝내야 아래 블록이 진짜 트랜잭션이 된다(저장점이 아니라)
        try:
            with conn.transaction():
                cur = conn.execute("SELECT valid_to FROM versions WHERE rule_seq = %s AND version_id = %s FOR UPDATE",
                                   (t.rule_seq, t.version_id)).fetchone()
                if not cur or cur[0] is not None:       # 그 사이 증분 수집이 이 판을 닫았다 → 건드리지 않는다
                    stale.append(key)
                    continue
                n_old = conn.execute("SELECT count(*) FROM chunks WHERE rule_seq = %s AND version_id = %s",
                                     (t.rule_seq, t.version_id)).fetchone()[0]
                if n_old != len(t.rows):
                    stale.append(key)
                    continue
                ord0 = conn.execute("SELECT COALESCE(max(ord), -1) + 1 FROM chunks").fetchone()[0]
                conn.execute("DELETE FROM chunks WHERE rule_seq = %s AND version_id = %s", (t.rule_seq, t.version_id))
                with conn.cursor() as c:
                    c.executemany("""INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url,
                                                         text_sha256, line_start, line_end, embedding, embedder, link_targets)
                                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                  [(x["chunk_id"], t.version_id, x["rule_seq"], x["seq"], ord0 + i, x["article"], x["kind"],
                                    x["text"], x["source_url"], x["text_sha256"], x["line_start"], x["line_end"],
                                    known[x["text"]], model, links.targets(x, p.page["_element_links"], url2seq))
                                   for i, x in enumerate(p.chunks)])
                got = conn.execute("SELECT count(*) FROM chunks WHERE rule_seq = %s AND version_id = %s",
                                   (t.rule_seq, t.version_id)).fetchone()[0]
                if got != len(p.chunks):                # 행 수 대조(rag4-09): 어긋나면 이 판은 되돌린다
                    raise schedule.SyncError("count_mismatch", f"{key}: 청크 {len(p.chunks)}개 중 DB {got}개")
            if key not in stale:
                done.append(key)
                out["replaced"] = len(done)
        except Exception as e:  # noqa: BLE001 — 이 판만 되돌려졌다. 나머지는 계속한다
            failed.append({"version": key, "error": f"{type(e).__name__}: {e}"[:300]})
            conn.rollback()
    return out


def bump_generation(conn) -> int:
    row = conn.execute("UPDATE index_meta SET generation = generation + 1 WHERE id = 1 RETURNING generation").fetchone()
    conn.commit()
    return int(row[0])


def run(conn, *, model: str, dim: int, read: PageReader, embed_fn: Callable[[list[str]], np.ndarray], dry_run: bool,
        max_cost: float = MAX_COST_USD, snap: set[tuple[int, str]], snapshot_rows: int = SNAPSHOT_ROWS,
        ignore_running: bool = False, today: str | None = None, log=print) -> dict:
    """한 번의 실행. 반환 report(dict). 거부는 Refused, 비용 상한은 CostCap, 일부 실패는 report['failed']에 담는다."""
    conn.commit()
    if dry_run:
        conn.read_only = True                           # 이 연결로는 쓸 수 없다(실수로도)
    try:
        try:
            schedule.check_index(conn, model, dim)      # ready가 아니거나 모델이 다르면 SyncError
        except schedule.SyncError as e:
            raise Refused(str(e)) from None
        if not ignore_running and conn.execute("SELECT to_regclass('sync_runs') IS NOT NULL").fetchone()[0]:
            n = conn.execute("SELECT count(*) FROM sync_runs WHERE job = %s AND status = 'running'", (schedule.JOB,)).fetchone()[0]
            if n:
                raise Refused(f"증분 수집이 실행 중이다(sync_runs running {n}건). 끝난 뒤 하거나 --ignore-running")
        targets, stat = find_targets(conn, snap, snapshot_rows)
        load_rows(conn, targets)
        conn.commit()
        plans, skipped = build_plans(conn, targets, read, today or datetime.now(timezone.utc).date().isoformat(), log)
        known = known_vectors(conn, sorted({p.target.rule_seq for p in plans if p.dirty}), model)
        conn.commit()
        report, need = summarize(plans, skipped, stat, known, model)
        report.update(dry_run=dry_run, skipped_list=skipped[:SAMPLE],
                      dirty_versions=[{"rule_seq": p.target.rule_seq, "version_id": p.target.version_id, "path": p.path,
                                       "unchanged": len(p.unchanged), "changed": len(p.changed), "new": len(p.new),
                                       "removed": len(p.removed)} for p in plans if p.dirty][:SAMPLE])
        if dry_run or not report["versions_to_replace"]:
            report.update(replaced=0, failed=[], stale=[], generation_bumped=False)
            return report
        if report["estimate"]["est_cost_usd"] > max_cost:
            raise CostCap(f"임베딩 추정 비용 {report['estimate']['est_cost_usd']}달러가 상한 {max_cost}달러를 넘는다(글 {len(need)}개, 약 {report['estimate']['est_tokens']}토큰)")
        if need:
            vecs = embed_fn(need)                       # 쓰기 전에, 트랜잭션 밖에서 한 번에(schedule.apply와 같다). 실패하면 아무것도 쓰지 않는다
            if len(vecs) != len(need):
                raise schedule.SyncError("embed_failed", f"벡터 {len(vecs)}개 ≠ 글 {len(need)}개")
            known.update(zip(need, vecs))
        out = {"replaced": 0, "failed": [], "stale": []}
        report["generation_bumped"] = False
        try:
            apply_plans(conn, plans, known, model, out, log)
        finally:
            if out["replaced"]:                         # 중간에 끊겨도 이미 바꾼 판이 있으면 generation은 한 번 올려 서비스가 다시 읽게 한다
                report["generation"] = bump_generation(conn)
                report["generation_bumped"] = True
        report.update(replaced=out["replaced"], failed=out["failed"], stale=out["stale"])
        return report
    finally:
        if dry_run:
            conn.rollback()
            conn.read_only = False


def fake_embed(dim: int) -> Callable[[list[str]], np.ndarray]:
    """시험용: 글의 해시로 만든 벡터. 운영 DB에는 쓰지 못하게 main이 막는다."""
    def fn(texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "little")
            v = np.random.default_rng(seed).standard_normal(dim).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)
    return fn


def _local_db(url: str) -> bool:
    from psycopg.conninfo import conninfo_to_dict
    host = str(conninfo_to_dict(url).get("host") or "")
    return host in ("localhost", "127.0.0.1", "::1", "")


def print_report(rep: dict, log=print) -> None:
    r, e = rep["rows"], rep["estimate"]
    log("== 증분 판 다시 청킹" + (" (dry-run, 쓰기 없음)" if rep["dry_run"] else ""))
    log(f"  현재 판: 스냅샷 {rep['current_snapshot']}(건드리지 않음), 증분 {rep['current_incremental']}, 닫힌 증분 판 {rep['closed_incremental']}(개수만, 바꾸지 않음)"
        + (f", 번호 이상 {rep['ord_anomaly']}(건너뜀)" if rep["ord_anomaly"] else ""))
    log(f"  대상 판 {rep['targets']}개 중 건너뜀 {rep['skipped']}개 {rep['skipped_by_kind'] or ''}")
    log(f"  판: 그대로 {rep['versions_unchanged']}, 바꿀 판 {rep['versions_to_replace']}개(쪽 {rep['pages_to_replace']}개)")
    log(f"  행: 같음 {r['unchanged']}, 바뀜 {r['changed']}, 새로 {r['new']}, 사라짐 {r['removed']} (바꿀 판에 쓸 행 {rep['rows_to_write']}개)")
    log(f"  임베딩 필요 {rep['embeddings_needed']}개(재사용 {rep['vectors_reused']}개), 약 {e['est_tokens']}토큰, 추정 {e['est_cost_usd']}달러(보수적 추정, 100만 토큰당 {e['usd_per_mtok']}달러)")
    for s in rep["skipped_list"]:
        log(f"  건너뜀: {s['kind']} {s['rule_seq']} {s['version_id']} {s['detail']}")
    for d in rep["dirty_versions"]:
        log(f"  바뀜: {d['path']} ({d['version_id']}) 같음 {d['unchanged']} 바뀜 {d['changed']} 새로 {d['new']} 사라짐 {d['removed']}")
    if not rep["dry_run"]:
        log(f"  반영: 판 {rep['replaced']}개 교체, 실패 {len(rep['failed'])}, 그 사이 바뀌어 건너뜀 {len(rep['stale'])}, "
            f"generation {'+1 -> ' + str(rep['generation']) if rep.get('generation_bumped') else '그대로'}")
        for f in rep["failed"]:
            log(f"  실패: {f['version']} {f['error']}")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingest.rechunk_increments", description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기·Voyage 호출 없이 바뀔 것만 보고한다")
    ap.add_argument("--fake", action="store_true", help="시험용 가짜 임베딩(로컬 DB에서만 허용)")
    ap.add_argument("--max-cost", type=float, default=MAX_COST_USD, help="임베딩 추정 비용 상한(달러). 추정이 넘으면 쓰기 전에 멈춘다")
    ap.add_argument("--manifest", type=Path, default=Path("data/manifest.jsonl"))
    ap.add_argument("--snapshot-rows", type=int, default=SNAPSHOT_ROWS)
    ap.add_argument("--ignore-running", action="store_true")
    ap.add_argument("--json-out", type=Path, default=None, help="보고(JSON)를 이 파일에 쓴다")
    ap.add_argument("--cache", type=Path, default=Path(os.environ.get("HANDBOOK_CACHE") or Path.home() / ".cache/provena/handbook"))
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL이 없다", file=sys.stderr)
        return 2
    if a.fake and not _local_db(url):
        print("--fake는 로컬 DB에서만 쓸 수 있다(가짜 벡터가 운영에 들어가지 않게)", file=sys.stderr)
        return 2
    if not a.manifest.is_file():
        print(f"{a.manifest}가 없다(스냅샷 판 목록)", file=sys.stderr)
        return 2
    import psycopg
    from pgvector.psycopg import register_vector
    from backend.rag.retrieve import embed
    s = embed.spec()

    def embed_fn(texts: list[str]) -> np.ndarray:
        if a.fake:
            return fake_embed(s.dim)(texts)
        return embed.encode_docs(embed.load_model(s.name), texts)

    try:
        snap = snapshot_versions(a.manifest)
        with psycopg.connect(url, prepare_threshold=None) as conn:
            register_vector(conn)
            origins = load_origins(conn)
            conn.commit()
            read = GitPages(a.cache, origins)
            try:
                if not a.dry_run and not a.fake and not os.environ.get("VOYAGE_API_KEY"):
                    # 임베딩할 글이 없을 수도 있으므로 먼저 dry-run으로 필요량을 본 뒤에만 키를 요구한다
                    pre = run(conn, model=s.name, dim=s.dim, read=read, embed_fn=embed_fn, dry_run=True, max_cost=a.max_cost,
                              snap=snap, snapshot_rows=a.snapshot_rows, ignore_running=a.ignore_running, log=lambda *_: None)
                    if pre["embeddings_needed"] and pre["versions_to_replace"]:
                        print("VOYAGE_API_KEY가 없다(임베딩할 글이 있다)", file=sys.stderr)
                        return 2
                rep = run(conn, model=s.name, dim=s.dim, read=read, embed_fn=embed_fn, dry_run=a.dry_run, max_cost=a.max_cost,
                          snap=snap, snapshot_rows=a.snapshot_rows, ignore_running=a.ignore_running)
            except Refused as e:
                print(f"거부: {e}", file=sys.stderr)
                return 2
            except CostCap as e:
                print(f"멈춤(비용 상한): {e}", file=sys.stderr)
                return 3
    except Refused as e:
        print(f"거부: {e}", file=sys.stderr)
        return 2
    print_report(rep)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 1 if rep["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
