"""핸드북 git 수집: 고른 절만, 고정 커밋으로.

python -m backend.rag.ingest.handbook                 (기본: data/corpus/ 에 쓴다)

Spec: docs/specs/collect.md. 원문은 바꾸지 않고 그대로 쓴다(파싱은 parse.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HANDBOOK_REPO = "https://gitlab.com/gitlab-com/content-sites/handbook.git"
PINNED_COMMIT = "129243bcffcf6cbc8c2e83f537f1836b99900a61"   # 2026-10-27, PRD 8장
SHALLOW_SINCE = "2023-12-01"   # 개정 이력(history.py)이 2024-01-01부터라 그보다 앞까지 받는다
EXPECTED_PAGES = 1564          # 조장 실측, 경로 조장 확인 2026-10-28
SITE = "https://handbook.gitlab.com/"
USER_AGENT = "proj3-c-provena-collector (aihuman-7th class project)"

# 절(Chunk.org) → content/handbook/ 아래 폴더. engineering/ 바로 밑 낱장(incident-management.md 등)은 넣지 않는다.
SECTIONS: dict[str, tuple[str, ...]] = {
    "infra": ("engineering/infrastructure-platforms",),
    "devops": ("engineering/devops", "engineering/deployments-and-releases", "engineering/releases",
               "engineering/error-budgets", "engineering/monitoring"),
    "workflow": ("engineering/workflow", "engineering/testing", "engineering/ai"),
    "development": ("engineering/development",),
    "data-engineering": ("engineering/data-engineering",),
    "security": ("security",),
    "business-technology": ("business-technology",),
    "support": ("support",),
    "enterprise-data": ("enterprise-data",),
    "tools-and-tips": ("tools-and-tips",),
    "finance": ("finance",),
}


class CollectError(RuntimeError):
    """수집 결과를 믿을 수 없을 때. 조용히 넘어가지 않고 멈춘다."""


def git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True)
    if done.returncode != 0:
        raise CollectError(f"git {' '.join(args[:3])} 실패: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def all_folders() -> list[str]:
    return [f"content/handbook/{f}" for folders in SECTIONS.values() for f in folders]


def org_of(path: str) -> str:
    for org, folders in SECTIONS.items():
        if any(path.startswith(f"content/handbook/{f}/") for f in folders):
            return org
    raise CollectError(f"고른 절에 속하지 않는 경로: {path}")


def ensure_checkout(cache: Path) -> None:
    """파일 내용 없이 이력만 받고(blob:none), 고른 폴더만 내용을 받는다. 이미 있으면 재사용."""
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout",
                               f"--shallow-since={SHALLOW_SINCE}", HANDBOOK_REPO, str(cache)],
                              capture_output=True)
        if done.returncode != 0:
            raise CollectError(f"clone 실패: {done.stderr.decode('utf-8', 'replace').strip()}")
    git(cache, "sparse-checkout", "set", "--no-cone", *[f"{f}/" for f in all_folders()])
    git(cache, "checkout", "-q", "--detach", PINNED_COMMIT)


def list_pages(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(경로, git blob id). git ls-tree 기준이라 작업 폴더 상태와 무관하다."""
    out = git(repo, "ls-tree", "-r", "-z", commit, "--", *all_folders()).decode("utf-8")
    pages = []
    for entry in filter(None, out.split("\0")):
        meta, path = entry.split("\t", 1)
        _mode, kind, blob = meta.split()
        if kind == "blob" and path.endswith(".md"):
            pages.append((path, blob))
    return sorted(pages)


def read_blobs(repo: Path, blobs: list[str]) -> dict[str, bytes]:
    """git 원본 바이트. 작업 폴더 파일은 Windows autocrlf 때문에 CRLF로 바뀌어 있어 쓰지 않는다."""
    out = git(repo, "cat-file", "--batch", stdin="".join(f"{b}\n" for b in blobs).encode())
    result, pos = {}, 0
    for blob in blobs:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode().split()
        if len(header) != 3 or header[1] != "blob":
            raise CollectError(f"blob을 읽지 못함: {header}")
        size = int(header[2])
        result[blob] = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return result


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def page_url(path: str) -> str:
    """content/handbook/a/b/_index.md → https://handbook.gitlab.com/handbook/a/b/ (사이트는 소문자 경로만 열린다)."""
    rel = path.removeprefix("content/").removesuffix(".md")
    rel = rel.removesuffix("/_index").removesuffix("/index")
    return f"{SITE}{rel.lower()}/"


def rule_seq(path: str) -> int:
    """페이지 id: 경로 해시라 판이 바뀌어도 같은 페이지는 같은 값(SDD 11-1 3-1 추천안, D0 확정 전 잠정)."""
    return int(sha256(path.encode())[:8], 16)


def front_matter(text: str) -> dict[str, str]:
    """맨 앞 --- 사이에서 title, redirect_to만 읽는다. 키 대소문자는 섞여 있다(Title: 4쪽)."""
    if not text.startswith("---"):
        return {}
    block = text.split("---", 2)[1]
    found = {}
    for key in ("title", "redirect_to"):
        m = re.search(rf"^{key}:\s*(.+)$", block, re.M | re.I)
        if m:
            found[key] = m.group(1).strip().strip("\"'")
    return found


def corpus_id(file_hashes: list[str]) -> str:
    """문서별 원본 지문을 정렬해 해시한다(받는 순서와 무관)."""
    return sha256("\n".join(sorted(file_hashes)).encode())


def check_pages(pages: dict[str, bytes], expected: int) -> dict[str, int]:
    by_org = {org: 0 for org in SECTIONS}
    for path in pages:
        by_org[org_of(path)] += 1
    if len(pages) != expected:
        raise CollectError(f"쪽수 {len(pages)} ≠ 기대 {expected}. 절별: {by_org}")
    empty_orgs = [org for org, n in by_org.items() if n == 0]
    if empty_orgs:
        raise CollectError(f"0쪽인 절: {empty_orgs}")
    empty = [p for p, b in pages.items() if not b.strip()]
    if empty:
        raise CollectError(f"빈 파일 {len(empty)}개: {empty[:5]}")
    return by_org


def write_verified(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if sha256(target.read_bytes()) != sha256(data):
        raise CollectError(f"저장 후 다시 읽은 지문이 다름: {target}")


def collect(out: Path, cache: Path) -> dict:
    ensure_checkout(cache)
    commit_date = git(cache, "show", "-s", "--format=%cs", PINNED_COMMIT).decode().strip()
    listed = list_pages(cache, PINNED_COMMIT)
    blobs = read_blobs(cache, [b for _, b in listed])
    pages = {path: blobs[blob] for path, blob in listed}
    for path, blob in listed:
        if git_blob_id(pages[path]) != blob:
            raise CollectError(f"git 원본과 다른 바이트: {path}")
    by_org = check_pages(pages, EXPECTED_PAGES)

    fetched_at = date.today().isoformat()
    rows = []
    for path, data in pages.items():
        write_verified(out / "handbook" / path.removeprefix("content/handbook/"), data)
        fm = front_matter(data.decode("utf-8"))
        rows.append({
            "rule_seq": rule_seq(path), "org": org_of(path), "path": path,
            "title": fm.get("title"), "source_url": page_url(path),
            "version_id": PINNED_COMMIT[:12], "version_date": commit_date, "fetched_at": fetched_at,
            "file_sha256": sha256(data), "chars": len(data.decode("utf-8")),
            "redirect_to": fm.get("redirect_to"),
        })
    if len({r["rule_seq"] for r in rows}) != len(rows):
        raise CollectError("페이지 id가 겹침")

    with (out / "pages.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {
        "repo": HANDBOOK_REPO, "commit": PINNED_COMMIT, "commit_date": commit_date,
        "folders": all_folders(), "pages": len(rows), "pages_by_org": by_org,
        "bytes": sum(len(d) for d in pages.values()),
        "redirect_pages": sum(1 for r in rows if r["redirect_to"]),
        "corpus_id": corpus_id([r["file_sha256"] for r in rows]),
        "collected_at": fetched_at,
        "git_version": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
        "license": "CC BY-SA 4.0 (data/LICENSES/LICENSES.md)",
    }
    (out / "collect_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8", newline="\n")
    return manifest


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("data/corpus"))
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache/provena/handbook")
    args = ap.parse_args()
    m = collect(args.out, args.cache)
    print(f"{m['pages']}쪽, {m['bytes'] / 1e6:.1f}MB, corpus_id {m['corpus_id'][:16]}")


if __name__ == "__main__":
    main()
