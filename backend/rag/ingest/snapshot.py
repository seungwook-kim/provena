"""원문 스냅샷 압축: `data/corpus/`(수집 결과 1,500여 파일)를 `data/corpus.tar.gz` 한 파일로 커밋하고, 쓸 때 푼다.

python -m backend.rag.ingest.snapshot pack      (수집한 뒤: data/corpus/ -> data/corpus.tar.gz)
python -m backend.rag.ingest.snapshot unpack    (clone한 뒤: data/corpus.tar.gz -> data/corpus/, 원문 sha256 확인)

- 같은 원문이면 늘 같은 압축 파일이 나온다(파일 순서·시각·소유자를 고정). 그래서 원문이 안 바뀌면 커밋 diff도 없다.
- 풀 때 `pages.jsonl`의 쪽별 `file_sha256`, 권한표 sha256, `corpus_id`를 다시 계산해 수집 때와 같은지 본다.
- `ensure()`: `data/corpus/`가 없으면 푼다. `parse`·`chunk`·`load`가 시작할 때, Dockerfile이 이미지를 만들 때 부른다.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import shutil
import tarfile
from pathlib import Path

from backend.rag.ingest.handbook import corpus_id, sha256

CORPUS = Path("data/corpus")
ARCHIVE = Path("data/corpus.tar.gz")
AUTHZ = "authz/authorization-matrix-2023-05.html.md"  # parse.py와 같은 위치


class SnapshotError(RuntimeError):
    pass


def pack(corpus: Path = CORPUS, archive: Path = ARCHIVE) -> Path:
    files = sorted(p for p in corpus.rglob("*") if p.is_file())
    if not files:
        raise SnapshotError(f"{corpus}에 원문이 없다(수집기를 먼저 돌린다)")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            info = tarfile.TarInfo(p.relative_to(corpus).as_posix())
            info.size, info.mtime, info.mode = p.stat().st_size, 0, 0o644
            with p.open("rb") as f:
                tar.addfile(info, f)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as out, gzip.GzipFile(filename="", fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(buf.getvalue())
    return archive


def verify(corpus: Path = CORPUS) -> dict:
    """수집 때 적은 sha256과 지금 파일이 같은지 본다. 다르면 SnapshotError."""
    manifest = json.loads((corpus / "collect_manifest.json").read_text(encoding="utf-8"))
    pages = [json.loads(line) for line in (corpus / "pages.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [p["path"] for p in pages
           if sha256((corpus / "handbook" / p["path"].removeprefix("content/handbook/")).read_bytes()) != p["file_sha256"]]
    if bad:
        raise SnapshotError(f"원문 sha256이 수집 때와 다르다: {len(bad)}쪽(예: {bad[0]})")
    authz = manifest.get("authz") or {}
    if authz.get("file_sha256"):
        got = sha256((corpus / AUTHZ).read_bytes())
        if got != authz["file_sha256"]:
            raise SnapshotError("2023 권한표 sha256이 수집 때와 다르다")
    if corpus_id([p["file_sha256"] for p in pages]) != manifest["corpus_id"]:
        raise SnapshotError("corpus_id가 수집 때와 다르다")
    return {"pages": len(pages), "corpus_id": manifest["corpus_id"]}


def unpack(archive: Path = ARCHIVE, corpus: Path = CORPUS) -> dict:
    if not archive.is_file():
        raise SnapshotError(f"{archive}가 없다")
    tmp = corpus.with_name(corpus.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(tmp, filter="data")  # 절대 경로·../·링크로 폴더 밖에 쓰는 항목은 막는다
    try:
        info = verify(tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(corpus, ignore_errors=True)
    tmp.rename(corpus)
    return info


def ensure(corpus: Path = CORPUS, archive: Path = ARCHIVE) -> None:
    """기본 위치(`data/corpus/`)에 원문이 없고 압축 파일이 있으면 푼다. 이미 있으면 그대로 둔다(수집 중이거나 고치는 중일 수 있음).
    다른 위치(`--corpus`로 준 시험용 폴더 등)는 건드리지 않는다."""
    if corpus == CORPUS and not (corpus / "pages.jsonl").is_file() and archive.is_file():
        info = unpack(archive, corpus)
        print(f"{archive} 풀어 둠: {info['pages']}쪽, corpus_id {info['corpus_id'][:16]}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingest.snapshot")
    ap.add_argument("command", choices=["pack", "unpack", "verify"])
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--archive", type=Path, default=ARCHIVE)
    a = ap.parse_args()
    if a.command == "pack":
        verify(a.corpus)
        path = pack(a.corpus, a.archive)
        print(f"{path}: {path.stat().st_size / 1e6:.1f}MB, sha256 {sha256(path.read_bytes())[:16]}")
    elif a.command == "unpack":
        info = unpack(a.archive, a.corpus)
        print(f"{a.corpus}: {info['pages']}쪽, corpus_id {info['corpus_id'][:16]} (수집 때와 같음)")
    else:
        print(verify(a.corpus))


if __name__ == "__main__":
    main()
