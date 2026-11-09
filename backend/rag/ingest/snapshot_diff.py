"""git 없는 변경 감지(F-07): 두 시점의 문서 묶음을 섹션 단위로 비교해 git 경로와 같은 바뀐 섹션 목록(`ChangedArticle`)을 만든다.

    python -m backend.rag.ingest.snapshot_diff <옛 폴더|옛.jsonl> <새 폴더|새.jsonl> --old-date YYYY-MM-DD --new-date YYYY-MM-DD
        [--prefix content/handbook/] [--json] [--feed]

- 입력: 폴더 하나가 한 시점(`.md` 파일을 재귀로 읽음, 숨김 폴더 제외) 또는 JSONL 한 파일이 한 시점(줄마다 `{"path", "content"}`).
  위키 페이지 이력 내보내기처럼 git이 없는 원천을 이 모양으로 내보내면 된다. `--prefix`는 경로 앞에 붙여 rule_seq를 코퍼스와 맞춘다.
- 비교: 같은 경로끼리 짝짓고 섹션 비교는 git 경로와 같은 함수(`diff.section_changes`)를 쓴다. 제목이 바뀐 섹션은 본문 유사도로 같은 섹션으로 보고
  (`diff.RENAME_MIN_SIMILARITY`) 옛 제목 경로로 적는다. 서식만 바뀐 섹션은 리콜에 넘기지 않는다. 새 쪽은 전부 added, 없어진 쪽은 전부 removed.
- 출력: 사람이 읽는 목록 또는 `--json`(`changes`는 `python -m backend.graph.recall.impact --changes`가 그대로 읽는다).
- `--feed`: `DATABASE_URL`의 `changed_articles`에 넣는다(실행 기록 `sync_runs.job = snapshot-diff`). 증분 수집과 같은 event_id라 같은 개정은 한 줄이고,
  리콜 처리기(`python -m backend.graph.recall.process_pending`)가 git 경로와 같은 길로 처리한다.
LLM·네트워크는 쓰지 않는다. 한계: 경로가 바뀐 쪽은 removed + added로 보인다. 쪽 하나가 파싱에 실패하면 그 쪽만 건너뛰고 `errors`에 남긴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.rag.ingest import diff
from backend.rag.ingest.handbook import CollectError, org_of, rule_seq
from backend.rag.ingest.parse import ParseError
from backend.schemas.recall import ChangedArticle

JOB = "snapshot-diff"
MD_SUFFIXES = (".md", ".markdown")


def read_snapshot(src: Path, prefix: str = "") -> dict[str, str]:
    """경로 -> 원문. 폴더면 .md 파일, .jsonl/.json이면 줄마다 {"path", "content"}."""
    src = Path(src)
    out: dict[str, str] = {}
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src)
            if p.is_file() and p.suffix.lower() in MD_SUFFIXES and not any(x.startswith(".") for x in rel.parts):
                out[prefix + rel.as_posix()] = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        return out
    text = src.read_text(encoding="utf-8-sig")
    rows = json.loads(text) if src.suffix.lower() == ".json" else [json.loads(x) for x in text.splitlines() if x.strip()]
    for r in rows:
        out[prefix + str(r["path"]).replace("\\", "/")] = str(r.get("content") or "").replace("\r\n", "\n")
    return out


def page_of(path: str) -> dict:
    """parse_page가 쓰는 쪽 정보. 고른 절 밖의 경로도 받는다(org = external)."""
    try:
        org = org_of(path)
    except CollectError:
        org = "external"
    return {"rule_seq": rule_seq(path), "org": org, "path": path}


@dataclass
class SnapshotDiff:
    articles: list[ChangedArticle] = field(default_factory=list)
    texts: dict[tuple[int, str], tuple[str, str]] = field(default_factory=dict)   # (rule_seq, article) -> (개정 전, 개정 뒤) 본문
    format_only: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        kinds = {k: sum(1 for a in self.articles if a.change_type == k) for k in ("added", "removed", "modified")}
        return {"changes": [a.model_dump() for a in self.articles], "errors": self.errors,
                "summary": {"changes": len(self.articles), **kinds, "format_only": self.format_only}}


def _texts(page: dict, raw: str | None) -> dict[str, str]:
    return {diff.article_of(p): s.text for p, s in diff.sections(page, raw).items()} if raw is not None else {}


def diff_snapshots(old: dict[str, str], new: dict[str, str], *, old_date: str, new_date: str) -> SnapshotDiff:
    res = SnapshotDiff()
    for path in sorted(set(old) | set(new)):
        o, n = old.get(path), new.get(path)
        if o == n:
            continue
        page = page_of(path)
        try:
            secs = diff.section_changes(page, o, n)
            ot, nt = _texts(page, o), _texts(page, n)
        except ParseError as e:
            res.errors.append({"path": path, "error": f"ParseError: {e}"})
            continue
        res.format_only += sum(1 for c in secs if c.format_only)
        for a, c in zip(diff.changed_articles(page["rule_seq"], [c for c in secs if not c.format_only], old_date if o is not None else "", new_date),
                        [c for c in secs if not c.format_only]):
            res.articles.append(a)
            res.texts[(a.rule_seq, a.article)] = (ot.get(c.old_article or c.article, ""), nt.get(c.article, "") if c.change_type != "removed" else "")
    return res


def feed(conn, articles: list[ChangedArticle], now: datetime | None = None) -> int:
    """`changed_articles`에 넣는다(202_sync.sql을 먼저 실행). 새로 넣은 줄 수. 같은 개정(event_id)은 다시 넣지 않는다."""
    from backend.rag.ingest.schedule import SQL, event_id

    now = now or datetime.now(timezone.utc)
    conn.execute(SQL.read_text(encoding="utf-8"))
    run_id = conn.execute("INSERT INTO sync_runs (job, slot, trigger, status, started_at, finished_at, list_complete, articles) "
                          "VALUES (%s, %s, 'manual', 'succeeded', %s, %s, true, %s) RETURNING run_id",
                          (JOB, f"manual-{now.strftime('%Y%m%dT%H%M%S%f')}", now, now, len(articles))).fetchone()[0]
    new = 0
    for a in articles:
        cur = conn.execute("INSERT INTO changed_articles (event_id, run_id, rule_seq, article, old_version_date, new_version_date, change_type) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
                           (event_id(a.model_dump()), run_id, a.rule_seq, a.article, a.old_version_date, a.new_version_date, a.change_type))
        new += cur.rowcount
    conn.commit()
    return new


def format_text(res: SnapshotDiff) -> str:
    ko = {"added": "추가", "removed": "삭제", "modified": "수정"}
    lines = [f"바뀐 섹션 {len(res.articles)}개 (서식만 바뀐 섹션 {res.format_only}개는 제외)"]
    lines += [f"- {ko[a.change_type]} | {a.article} | rule_seq={a.rule_seq}" for a in res.articles]
    lines += [f"! {e['path']}: {e['error']}" for e in res.errors]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingest.snapshot_diff", description="git 없이 문서 두 시점을 섹션 단위로 비교한다")
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--old-date", required=True)
    ap.add_argument("--new-date", required=True)
    ap.add_argument("--prefix", default="", help="경로 앞에 붙일 글자(예: content/handbook/)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--feed", action="store_true", help="DATABASE_URL의 changed_articles에 넣는다")
    a = ap.parse_args(argv)
    from backend.rag.retrieve.section import check_date

    try:
        check_date(a.old_date, "old_date")
        check_date(a.new_date, "new_date")
    except ValueError as e:
        ap.error(str(e))
    for p in (a.old, a.new):
        if not p.exists():
            print(f"없는 경로: {p}", file=sys.stderr)
            return 2
    res = diff_snapshots(read_snapshot(a.old, a.prefix), read_snapshot(a.new, a.prefix), old_date=a.old_date, new_date=a.new_date)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1) if a.json else format_text(res))
    if a.feed:
        import os

        import psycopg

        url = os.environ.get("DATABASE_URL")
        if not url:
            print("DATABASE_URL이 없다", file=sys.stderr)
            return 2
        with psycopg.connect(url, prepare_threshold=None) as conn:
            print(f"changed_articles에 {feed(conn, res.articles)}줄을 넣었습니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
