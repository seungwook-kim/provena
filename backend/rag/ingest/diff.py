"""증분 수집 ①: 두 커밋 사이에서 바뀐 쪽과 바뀐 섹션을 찾는다. DB·임베딩 모델 없이 돈다.

python -m backend.rag.ingest.diff 129243bc 52419353ea              (보고서: data/diff/<옛>-<새>.json)
python -m backend.rag.ingest.diff 129243bc 52419353ea --out x.json

Spec: docs/specs/incremental.md. 판정은 코드로만 한다(LLM 없음). DB 반영·정시 실행은 schedule.py(따로).
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.rag.ingest.handbook import (CollectError, all_folders, last_changes, list_pages, org_of, read_blobs,
                                         rule_seq)
from backend.rag.ingest.parse import ParseError, parse_page
from backend.schemas.recall import ChangedArticle

HEADER_LEVELS = 4            # 제목 경로(article)를 만드는 제목 단계. parse.py open_heads·chunk.py 와 같은 값
# 제목만 바뀐 섹션의 짝 찾기 문턱(본문 낱말 유사도). 관례값이 아니라 실측값(2026-11-02): 2024~ 이력 커밋 400개 표본 +
# 10/27→10/30 의 짝 후보 345쌍 중 0.25~0.9 의 65쌍에 같은 섹션·다른 섹션 표시를 붙여 오류가 가장 적은 곳(0.28·0.34~0.35, 각 6건)
# 중에서 다른 섹션을 덜 짝짓는 쪽. 0.6 이면 같은 섹션 17쌍을 놓친다. 잘못 짝지은 것도 리콜에서 빠지지는 않는다(modified 로 넘어감).
RENAME_MIN_SIMILARITY = 0.35
TOC = re.compile(r"^\[toc\]$", re.I)    # Hugo 목차 자리표시. 화면 글자가 아니다
SPACE = re.compile(r"\s+")
WORD = re.compile(r"\w+")


# ── 쪽 목록 비교 ──
@dataclass
class Changes:
    old_commit: str
    new_commit: str
    added: list[tuple[str, str]] = field(default_factory=list)            # (경로, 새 blob)
    modified: list[tuple[str, str, str]] = field(default_factory=list)    # (경로, 옛 blob, 새 blob)
    removed: list[tuple[str, str]] = field(default_factory=list)          # (경로, 옛 blob) — 본 것. 반영은 list_complete 일 때만
    unchanged: int = 0
    moved: list[tuple[str, str, str]] = field(default_factory=list)       # (옛 경로, 새 경로, blob). added·removed 에도 그대로 남음
    pages_by_folder: dict[str, int] = field(default_factory=dict)         # 새 커밋 기준
    list_complete: bool = False
    reasons: list[str] = field(default_factory=list)                      # list_complete 가 거짓인 이유


def run_git(repo: Path, *args: str, stdin: bytes | None = None, lazy: bool = True) -> subprocess.CompletedProcess:
    """lazy=False: blob:none 캐시에서 없는 객체를 하나씩 내려받지 않는다(없으면 없다고만 답함)."""
    env = None if lazy else {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, env=env)


def commit_exists(repo: Path, commit: str) -> bool:
    done = run_git(repo, "cat-file", "-t", commit, lazy=False)
    return done.returncode == 0 and done.stdout.strip() == b"commit"


def folder_of(path: str) -> str:
    return next(f for f in all_folders() if path.startswith(f + "/"))


def list_changes(repo: Path, old_commit: str, new_commit: str, fetch_ok: bool = True) -> Changes:
    """두 커밋의 고른 17개 폴더 목록(경로·blob id)을 비교한다. 커밋을 하나씩 보지 않고 두 끝만 본다(설계 D2).

    목록 완전성(설계 D3) 증거 4개: fetch 성공(fetch_ok, 부른 쪽이 넘김)·두 커밋이 실제로 있음·ls-tree 성공·
    17개 폴더가 모두 1쪽 이상. 하나라도 아니면 list_complete=False 이고 이유를 reasons 에 남긴다.
    비율 규칙("많이 지워지면 멈춤")은 쓰지 않는다: 2024~ 실제로 하루 156쪽이 지워진 날이 있다.
    """
    ch = Changes(old_commit, new_commit)
    if not fetch_ok:
        ch.reasons.append("fetch_failed")
    for role, c in (("old", old_commit), ("new", new_commit)):
        if not commit_exists(repo, c):
            ch.reasons.append(f"commit_missing:{role}")
    if any(r.startswith("commit_missing") for r in ch.reasons):
        return ch
    try:
        old, new = dict(list_pages(repo, old_commit)), dict(list_pages(repo, new_commit))
    except CollectError as e:
        ch.reasons.append(f"ls_tree_failed:{e}")
        return ch
    ch.pages_by_folder = {f: 0 for f in all_folders()}
    for path in new:
        ch.pages_by_folder[folder_of(path)] += 1
    ch.reasons += [f"empty_folder:{f}" for f, n in ch.pages_by_folder.items() if n == 0]

    for path, blob in sorted(new.items()):
        if path not in old:
            ch.added.append((path, blob))
        elif old[path] != blob:
            ch.modified.append((path, old[path], blob))
        else:
            ch.unchanged += 1
    ch.removed = [(p, b) for p, b in sorted(old.items()) if p not in new]
    gone = collections.defaultdict(list)
    for p, b in ch.removed:
        gone[b].append(p)
    ch.moved = [(gone[b][0], p, b) for p, b in ch.added if gone.get(b)]    # 같은 바이트가 다른 경로로 = 옮김(Q5 전엔 기록만)
    ch.list_complete = not ch.reasons
    return ch


def fetch_blobs(repo: Path, blobs: list[str]) -> dict[str, bytes]:
    """blob:none 캐시에 없는 파일을 git fetch 한 번으로 묶어 받은 뒤 읽는다.
    하나씩 읽으면(cat-file 이 없는 객체마다 따로 내려받음) 278개에 5분이 넘었다(설계 M7)."""
    blobs = list(dict.fromkeys(blobs))
    if not blobs:
        return {}
    check = run_git(repo, "cat-file", "--batch-check", stdin="".join(f"{b}\n" for b in blobs).encode(), lazy=False)
    missing = [line.split()[0] for line in check.stdout.decode().splitlines() if line.endswith(" missing")]
    if missing:
        done = run_git(repo, "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "origin", "--no-tags",
                       "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none", "--stdin",
                       stdin="".join(f"{b}\n" for b in missing).encode())
        if done.returncode != 0:
            raise CollectError(f"파일 {len(missing)}개 묶어 받기 실패: {done.stderr.decode('utf-8', 'replace').strip()}")
    return read_blobs(repo, blobs)


# ── 섹션 비교 ──
@dataclass
class Section:
    path: tuple[str, ...]
    body: list[str] = field(default_factory=list)     # 화면 글자(공백 정규화). 같으면 같은 말
    form: list[str] = field(default_factory=list)     # 원본 줄 + 링크 주소. 본문은 같고 이것만 다르면 서식만
    review: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.body)


@dataclass
class SectionChange:
    article: str                    # 제목 경로 " > " (chunk.py article 과 같은 규칙, 첫 제목 앞 글은 "")
    change_type: str                # added · removed · modified (계약 ChangedArticle)
    format_only: bool = False       # 링크 주소·공백·[TOC] 만 다름 → 리콜에 보내지 않음(SDD 4-1)
    old_article: str | None = None  # 제목만 바뀐 섹션의 옛 제목 경로
    similarity: float | None = None  # 짝 찾기에 쓴 본문 유사도
    review: bool = False            # 처음 보는 단축코드가 있는 쪽(EC-10)


def norm(text: str) -> str:
    return SPACE.sub(" ", text).strip()


def sections(page: dict, raw: str) -> dict[tuple[str, ...], Section]:
    """parse_page 요소를 제목 경로별로 모은다. 1~4단계 제목은 경로가 되고, 나머지 요소는 그 경로의 본문이 된다."""
    lines = raw.split("\n")
    found: dict[tuple[str, ...], Section] = {}
    for el in parse_page(page, raw, collections.Counter()):
        sec = found.setdefault(tuple(el["heading_path"]), Section(tuple(el["heading_path"])))
        sec.review = sec.review or bool(el["review"])
        sec.form += lines[el["line_start"] - 1:el["line_end"]] + [str(el["links"])]
        if el["kind"] == "heading" and el["level"] <= HEADER_LEVELS:
            continue                           # 제목 글자는 경로(키)로 비교한다
        text = norm(el["text"])
        if text and not TOC.match(text):
            sec.body.append(text)
    return found


def similarity(a: str, b: str) -> float:
    """낱말 순서까지 본 유사도(0~1). 둘 다 빈 본문이면 0: 내용 없는 제목끼리는 짝을 지을 근거가 없다."""
    wa, wb = WORD.findall(a.lower()), WORD.findall(b.lower())
    if not wa and not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def article_of(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def section_changes(page: dict, old_raw: str | None, new_raw: str | None) -> list[SectionChange]:
    """같은 쪽의 두 원문을 비교한다. git 없이 원문 두 개만 받는다(git 없는 두 시점 묶음 F-07에도 쓸 수 있게).
    old_raw=None 이면 새로 생긴 쪽(섹션 전부 added), new_raw=None 이면 사라진 쪽(전부 removed).

    page: parse_page 가 쓰는 rule_seq·org·path. 파싱 오류(ParseError)는 부른 쪽이 그 쪽만 건너뛰게 그대로 올린다.
    """
    old = sections(page, old_raw) if old_raw is not None else {}
    new = sections(page, new_raw) if new_raw is not None else {}
    out: list[SectionChange] = []
    for path in old.keys() & new.keys():
        o, n = old[path], new[path]
        if o.body != n.body:
            out.append(SectionChange(article_of(path), "modified", review=n.review))
        elif o.form != n.form:
            out.append(SectionChange(article_of(path), "modified", format_only=True, review=n.review))

    # 본문 없는 섹션(제목만, 바로 아래 하위 제목)은 청크가 없어 인용될 수 없다(chunk.py). 그 제목 글자는 하위 경로에 남는다
    gone = [p for p in old if p not in new and old[p].body]
    born = [p for p in new if p not in old and new[p].body]
    pairs = sorted(((similarity(old[g].text, new[b].text), gi, bi) for gi, g in enumerate(gone)
                    for bi, b in enumerate(born)), reverse=True)
    used_g, used_b = set(), set()
    for sim, gi, bi in pairs:                  # 유사도가 높은 짝부터 하나씩(한 섹션은 한 짝만)
        if sim < RENAME_MIN_SIMILARITY:
            break
        if gi in used_g or bi in used_b:
            continue
        used_g.add(gi)
        used_b.add(bi)
        out.append(SectionChange(article_of(born[bi]), "modified", old_article=article_of(gone[gi]),
                                 similarity=round(sim, 4), review=new[born[bi]].review))
    out += [SectionChange(article_of(g), "removed", review=old[g].review) for i, g in enumerate(gone) if i not in used_g]
    out += [SectionChange(article_of(b), "added", review=new[b].review) for i, b in enumerate(born) if i not in used_b]
    order = {p: i for i, p in enumerate([*new, *old])}
    key = {article_of(p): i for p, i in order.items()}
    return sorted(out, key=lambda c: (key.get(c.article, len(key)), c.change_type))


def changed_articles(rule_seq_: int, changes: list[SectionChange], old_date: str, new_date: str) -> list[ChangedArticle]:
    """리콜에 넘길 목록(계약 ChangedArticle). 서식만 바뀐 섹션은 넣지 않는다.
    제목만 바뀐 섹션은 옛 제목 경로를 article 로 둔다: 지난 답이 인용한 것은 옛 경로다(조장 확인 필요)."""
    return [ChangedArticle(rule_seq=rule_seq_, article=c.old_article or c.article, old_version_date=old_date,
                           new_version_date=new_date, change_type=c.change_type)
            for c in changes if not c.format_only]


def page_of(path: str) -> dict:
    return {"rule_seq": rule_seq(path), "org": org_of(path), "path": path}


def page_kind(changes: list[SectionChange]) -> str:
    if not changes:
        return "no_section_change"     # 머리말(front matter) 등 섹션 밖만 바뀜
    return "format_only" if all(c.format_only for c in changes) else "content"


def diff_commits(repo: Path, old_commit: str, new_commit: str, fetch_ok: bool = True,
                 raw_out: dict[str, str] | None = None) -> dict:
    """목록 비교 → 바뀐 쪽 파일 묶어 받기 → 쪽마다 섹션 비교 → ChangedArticle. 한 쪽이 실패해도 나머지는 계속(EC-11).
    raw_out을 주면 새 판 원문(경로 → 글)을 채운다(schedule.py가 같은 원문을 다시 받지 않고 파싱·청킹한다)."""
    ch = list_changes(repo, old_commit, new_commit, fetch_ok)
    work = ([(p, None, b) for p, b in ch.added] + [(p, o, n) for p, o, n in ch.modified]
            + [(p, b, None) for p, b in ch.removed])
    data = fetch_blobs(repo, [b for _, o, n in work for b in (o, n) if b])
    paths = [p for p, _, _ in work]
    new_dates = last_changes(repo, new_commit, [p for p, _, n in work if n])
    old_dates = last_changes(repo, old_commit, [p for p, o, _ in work if o])
    pages, articles = [], []
    for path, o, n in work:
        page = page_of(path)
        row = {"path": path, "rule_seq": page["rule_seq"], "page_change": "added" if o is None else
               "removed" if n is None else "modified",
               # 새 판 (판 커밋 앞 12자리, 판 날짜, '이전' 여부) — handbook.collect 의 version_id 규칙과 같다
               "new_version": [new_dates[path][0][:12], new_dates[path][1], new_dates[path][2]] if n else None}
        try:
            if n and raw_out is not None:
                raw_out[path] = data[n].decode("utf-8")
            secs = section_changes(page, data[o].decode("utf-8") if o else None, data[n].decode("utf-8") if n else None)
        except (ParseError, UnicodeDecodeError) as e:
            pages.append({**row, "kind": "error", "error": f"{type(e).__name__}: {e}"})
            continue
        old_date = old_dates[path][1] if o else ""
        new_date = new_dates[path][1] if n else ""
        found = changed_articles(page["rule_seq"], secs, old_date, new_date)
        articles += [a.model_dump() for a in found]
        pages.append({**row, "kind": page_kind(secs), "review": any(s.review for s in secs),
                      "sections": [asdict(s) for s in secs]})
    kinds = collections.Counter(p["kind"] for p in pages)
    return {"changes": {**asdict(ch), "unchanged": ch.unchanged}, "pages": pages, "articles": articles,
            "summary": {"pages": len(paths), "added": len(ch.added), "modified": len(ch.modified),
                        "removed": len(ch.removed), "moved": len(ch.moved), "unchanged": ch.unchanged,
                        "list_complete": ch.list_complete, "reasons": ch.reasons, "by_kind": dict(kinds),
                        "sections": dict(collections.Counter(
                            ("format_only" if s["format_only"] else s["change_type"])
                            for p in pages for s in p.get("sections", []))),
                        "articles": len(articles)}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache/provena/handbook")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = diff_commits(args.cache, args.old, args.new)
    out = args.out or Path("data/diff") / f"{args.old[:10]}-{args.new[:10]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    s = report["summary"]
    print(f"쪽 {s['pages']} (추가 {s['added']}·수정 {s['modified']}·사라짐 {s['removed']}·옮김 {s['moved']}), "
          f"그대로 {s['unchanged']}, 목록 완전 {s['list_complete']} {s['reasons']}")
    print(f"쪽 판정 {s['by_kind']}, 섹션 {s['sections']}, 리콜에 넘길 섹션 {s['articles']} → {out}")


if __name__ == "__main__":
    main()
