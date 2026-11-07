"""스냅샷 압축: 원문(`data/corpus/`, 1,500여 파일)과 검색 색인(`data/index/`, 청크·벡터·링크)을 각각 압축 한 파일로 커밋하고, 쓸 때 푼다.

python -m backend.rag.ingest.snapshot pack            (수집한 뒤: data/corpus/ -> data/corpus.tar.gz)
python -m backend.rag.ingest.snapshot unpack          (clone한 뒤: data/corpus.tar.gz -> data/corpus/, 원문 sha256 확인)
python -m backend.rag.ingest.snapshot pack-index      (색인을 만든 뒤: data/index/ -> data/index.tar.gz)
python -m backend.rag.ingest.snapshot unpack-index    (clone한 뒤: data/index.tar.gz -> data/index/, meta.json sha256 확인)

- 같은 입력이면 늘 같은 압축 파일이 나온다(파일 순서·시각·소유자를 고정). 그래서 내용이 안 바뀌면 커밋 diff도 없다.
- 원문은 풀 때 `pages.jsonl`의 쪽별 `file_sha256`, 권한표 sha256, `corpus_id`를 다시 계산해 수집 때와 같은지 본다.
- 색인은 `meta.json`에 적힌 파일(청크·벡터·링크·번역 장부)만 넣고, 풀 때 각 파일 sha256을 `meta.json`과 대조한다.
- `ensure()`: `data/corpus/`가 없으면 푼다. `parse`·`chunk`·`load`가 시작할 때, Dockerfile이 이미지를 만들 때 부른다.
- `ensure_index()`: `data/index/`가 없으면 푼다. 색인 적재(`backend/rag/retrieve/load_snapshot.py`)가 시작할 때 부른다.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import tarfile
from collections.abc import Callable, Iterable
from pathlib import Path

from backend.rag.ingest.handbook import corpus_id, sha256

CORPUS = Path("data/corpus")
ARCHIVE = Path("data/corpus.tar.gz")
AUTHZ = "authz/authorization-matrix-2023-05.html.md"  # parse.py와 같은 위치
INDEX = Path("data/index")
INDEX_ARCHIVE = Path("data/index.tar.gz")


class SnapshotError(RuntimeError):
    pass


def _pack(root: Path, files: Iterable[Path], archive: Path) -> Path:
    """`files`(root 아래)를 정한 순서로 묶는다. 시각 0·권한 644·소유자 0으로 고정해 같은 입력이면 같은 바이트가 나온다."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            info = tarfile.TarInfo(p.relative_to(root).as_posix())
            info.size, info.mtime, info.mode = p.stat().st_size, 0, 0o644
            with p.open("rb") as f:
                tar.addfile(info, f)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as out, gzip.GzipFile(filename="", fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(buf.getvalue())
    return archive


def _replace_dir(tmp: Path, dst: Path) -> None:
    """대조를 마친 `tmp`를 `dst` 자리에 둔다. `dst`가 이미 있으면 안의 것만 바꾼다
    (compose가 `./data/index`를 연결한 폴더는 폴더 자체를 지우거나 이름을 바꿀 수 없다)."""
    if not dst.exists():
        tmp.rename(dst)
        return
    for child in dst.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in tmp.iterdir():
        shutil.move(str(child), str(dst / child.name))
    tmp.rmdir()


def _unpack(archive: Path, dst: Path, check: Callable[[Path], dict]) -> dict:
    """옆 폴더(`<dst>.tmp`)에 풀어 `check`로 대조한 뒤에만 `dst`를 바꾼다. 대조가 실패하면 `dst`는 그대로 둔다."""
    if not archive.is_file():
        raise SnapshotError(f"{archive}가 없다")
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(tmp, filter="data")  # 절대 경로·../·링크로 폴더 밖에 쓰는 항목은 막는다
    try:
        info = check(tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _replace_dir(tmp, dst)
    return info


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---- 원문 (data/corpus/) ----

def pack(corpus: Path = CORPUS, archive: Path = ARCHIVE) -> Path:
    files = sorted(p for p in corpus.rglob("*") if p.is_file())
    if not files:
        raise SnapshotError(f"{corpus}에 원문이 없다(수집기를 먼저 돌린다)")
    return _pack(corpus, files, archive)


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
    return _unpack(archive, corpus, verify)


def ensure(corpus: Path = CORPUS, archive: Path = ARCHIVE) -> None:
    """기본 위치(`data/corpus/`)에 원문이 없고 압축 파일이 있으면 푼다. 이미 있으면 그대로 둔다(수집 중이거나 고치는 중일 수 있음).
    다른 위치(`--corpus`로 준 시험용 폴더 등)는 건드리지 않는다."""
    if corpus == CORPUS and not (corpus / "pages.jsonl").is_file() and archive.is_file():
        info = unpack(archive, corpus)
        print(f"{archive} 풀어 둠: {info['pages']}쪽, corpus_id {info['corpus_id'][:16]}")


# ---- 검색 색인 (data/index/) ----

def index_files(meta: dict) -> list[tuple[str, str]]:
    """`meta.json`이 가리키는 (파일, sha256). 적재(`load_snapshot.load`)가 대조하는 것과 같은 묶음이다."""
    out = [(meta["chunks_file"], meta["chunks_sha256"])]
    out += [(e["file"], e["sha256"]) for e in (meta.get("embedders") or {}).values()]
    for key in ("links", "query_translations"):
        if meta.get(key):
            out.append((meta[key]["file"], meta[key]["sha256"]))
    return out


def verify_index(index: Path = INDEX) -> dict:
    """`meta.json`에 적힌 파일이 모두 있고 sha256이 같은지 본다. 다르면 SnapshotError."""
    meta_path = index / "meta.json"
    if not meta_path.is_file():
        raise SnapshotError(f"{meta_path}가 없다")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for rel, want in index_files(meta):
        p = index / rel
        if not p.is_file():
            raise SnapshotError(f"색인 파일이 없다: {rel}")
        if _file_sha(p) != want:
            raise SnapshotError(f"색인 파일 sha256이 meta.json과 다르다: {rel}")
    return {"n_chunks": meta["n_chunks"], "chunks_sha256": meta["chunks_sha256"],
            "embedders": sorted(meta.get("embedders") or {})}


def pack_index(index: Path = INDEX, archive: Path = INDEX_ARCHIVE) -> Path:
    """`meta.json`과 그것이 가리키는 파일만 넣는다(폴더에 남은 다른 파일은 넣지 않는다)."""
    meta_path = index / "meta.json"
    if not meta_path.is_file():
        raise SnapshotError(f"{meta_path}가 없다(index.py로 색인을 먼저 만든다)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # 순서는 상대 경로 글자로 정한다(Windows·Linux에서 같은 순서 → 같은 바이트)
    files = sorted({meta_path, *(index / rel for rel, _ in index_files(meta))}, key=lambda p: p.relative_to(index).as_posix())
    return _pack(index, files, archive)


def unpack_index(archive: Path = INDEX_ARCHIVE, index: Path = INDEX) -> dict:
    return _unpack(archive, index, verify_index)


def ensure_index(index: Path = INDEX, archive: Path = INDEX_ARCHIVE, log=print) -> bool:
    """기본 위치(`data/index/`)에 `meta.json`이 없고 압축 파일이 있으면 풀고 True. 이미 있으면 그대로 둔다(True).
    다른 위치(`--index`로 준 시험용 폴더 등)는 건드리지 않는다. 풀지 못하면(압축 파일 없음) False."""
    if (index / "meta.json").is_file():
        return True
    if index != INDEX or not archive.is_file():
        return False
    info = unpack_index(archive, index)
    log(f"{archive} 풀어 둠: 청크 {info['n_chunks']}개, 벡터 {', '.join(info['embedders'])}, "
        f"chunks sha256 {info['chunks_sha256'][:16]}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingest.snapshot")
    ap.add_argument("command", choices=["pack", "unpack", "verify", "pack-index", "unpack-index", "verify-index"])
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--archive", type=Path, default=None, help=f"기본 {ARCHIVE}(원문), {INDEX_ARCHIVE}(색인)")
    ap.add_argument("--index", type=Path, default=INDEX)
    a = ap.parse_args()
    if a.command.endswith("-index"):
        archive = a.archive or INDEX_ARCHIVE
        if a.command == "pack-index":
            verify_index(a.index)
            path = pack_index(a.index, archive)
            print(f"{path}: {path.stat().st_size / 1e6:.1f}MB, sha256 {_file_sha(path)[:16]}")
        elif a.command == "unpack-index":
            info = unpack_index(archive, a.index)
            print(f"{a.index}: 청크 {info['n_chunks']}개, 벡터 {', '.join(info['embedders'])} (meta.json sha256과 같음)")
        else:
            print(verify_index(a.index))
        return
    archive = a.archive or ARCHIVE
    if a.command == "pack":
        verify(a.corpus)
        path = pack(a.corpus, archive)
        print(f"{path}: {path.stat().st_size / 1e6:.1f}MB, sha256 {sha256(path.read_bytes())[:16]}")
    elif a.command == "unpack":
        info = unpack(archive, a.corpus)
        print(f"{a.corpus}: {info['pages']}쪽, corpus_id {info['corpus_id'][:16]} (수집 때와 같음)")
    else:
        print(verify(a.corpus))


if __name__ == "__main__":
    main()
