"""문서 출처 추상화 `DocumentSource`(F-10, SDD 3장 `backend/rag/ingest/`).

수집 입력을 "경로 → 원문 바이트 + 판 정보" 목록으로 통일해, 출처(git 저장소, 디렉터리 스냅샷)를 바꿔 끼운다.
- `HandbookGitSource`: `handbook.py`의 고른 절·고정 커밋 수집을 그대로 감싼다(로직을 복사하지 않고 `handbook.list_pages`·`read_blobs`·`last_changes`를 부른다).
- `DirectorySnapshotSource`: git 없이 폴더에 둔 두 시점 문서 묶음 중 한 시점(`snapshot_diff.py`가 읽는 형식과 같은 `.md` 파일).

`handbook.collect()`·`schedule.py`는 아직 이 추상화를 거치지 않는다(기존 동작 유지). 새 출처는 `DocumentSource`만 구현하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from backend.rag.ingest import handbook
from backend.rag.ingest.snapshot_diff import MD_SUFFIXES


@dataclass(frozen=True)
class SourcePage:
    path: str
    data: bytes
    version_id: str
    version_date: str
    version_date_before: bool = False


@runtime_checkable
class DocumentSource(Protocol):
    """수집 출처 하나. `pages()`는 경로 순으로 정렬한 목록을 돌려준다."""

    name: str

    def pages(self) -> list[SourcePage]: ...


class HandbookGitSource:
    """핸드북 git 저장소의 고른 절(`handbook.SECTIONS`), 고정 커밋. `checkout=True`이면 `ensure_checkout`으로 받는다."""

    name = "handbook-git"

    def __init__(self, repo: Path, commit: str = handbook.PINNED_COMMIT, *, checkout: bool = False) -> None:
        self.repo, self.commit, self.checkout = Path(repo), commit, checkout

    def pages(self) -> list[SourcePage]:
        if self.checkout:
            handbook.ensure_checkout(self.repo)
        listed = handbook.list_pages(self.repo, self.commit)
        blobs = handbook.read_blobs(self.repo, [b for _, b in listed])
        versions = handbook.last_changes(self.repo, self.commit, [p for p, _ in listed])
        return [SourcePage(path, blobs[blob], versions[path][0][:12], versions[path][1], versions[path][2])
                for path, blob in listed]


class DirectorySnapshotSource:
    """폴더 안 `.md`·`.markdown` 파일. 폴더 걸러내기 규칙은 `snapshot_diff.read_snapshot`과 같음(점으로 시작하는 폴더 제외), 원문은 bytes(BOM·CRLF 정리는 하지 않음). 판 정보는 만든 쪽이 정해 준다(git 이력이 없다)."""

    name = "directory-snapshot"

    def __init__(self, root: Path, *, version_id: str, version_date: str) -> None:
        self.root, self.version_id, self.version_date = Path(root), version_id, version_date

    def pages(self) -> list[SourcePage]:
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and p.suffix.lower() in MD_SUFFIXES and not any(x.startswith(".") for x in rel.parts):
                out.append(SourcePage(rel.as_posix(), p.read_bytes(), self.version_id, self.version_date))
        return out
