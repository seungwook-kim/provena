"""검색 색인 스냅샷 압축(backend/rag/ingest/snapshot.py *_index): 같은 색인이면 같은 압축, 풀면 그대로,
meta.json sha256과 다른 파일·빠진 파일은 막음, compose가 연결한 빈 폴더에도 푼다."""
import hashlib
import io
import json
import tarfile

import pytest

from backend.rag.ingest import snapshot


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _index(root, chunks=b'{"chunk_id": "c1"}\r\n', vec=b"\x93NUMPY fake vectors", links=b'{"targets": []}\n'):
    (root / "vectors").mkdir(parents=True)
    (root / "chunks.jsonl").write_bytes(chunks)
    (root / "vectors" / "m.npy").write_bytes(vec)
    (root / "links.jsonl").write_bytes(links)
    meta = {"chunks_file": "chunks.jsonl", "chunks_sha256": _sha(chunks), "n_chunks": 1,
            "embedders": {"m": {"file": "vectors/m.npy", "sha256": _sha(vec)}},
            "links": {"file": "links.jsonl", "sha256": _sha(links)}}
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return root


def test_pack_index_is_deterministic_and_roundtrips(tmp_path):
    src = _index(tmp_path / "index")
    (src / "stray.tmp").write_text("not in meta")  # meta.json이 가리키지 않는 파일은 넣지 않는다
    a = snapshot.pack_index(src, tmp_path / "a.tar.gz")
    b = snapshot.pack_index(src, tmp_path / "b.tar.gz")
    assert a.read_bytes() == b.read_bytes()
    with tarfile.open(a, "r:gz") as tar:
        assert tar.getnames() == ["chunks.jsonl", "links.jsonl", "meta.json", "vectors/m.npy"]
        assert {(m.mtime, m.mode, m.uid, m.gid) for m in tar.getmembers()} == {(0, 0o644, 0, 0)}
    info = snapshot.unpack_index(a, tmp_path / "out")
    assert info == {"n_chunks": 1, "chunks_sha256": _sha(b'{"chunk_id": "c1"}\r\n'), "embedders": ["m"]}
    assert (tmp_path / "out" / "chunks.jsonl").read_bytes() == b'{"chunk_id": "c1"}\r\n'  # 줄바꿈 그대로
    assert (tmp_path / "out" / "vectors" / "m.npy").read_bytes() == b"\x93NUMPY fake vectors"
    assert not (tmp_path / "out" / "stray.tmp").exists()


def test_unpack_index_rejects_sha_mismatch_and_keeps_old_folder(tmp_path):
    src = _index(tmp_path / "index")
    archive = snapshot.pack_index(src, tmp_path / "c.tar.gz")
    # 압축 안의 벡터를 바꿔치기한다(meta.json sha256은 그대로)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "r:gz") as tin, tarfile.open(bad, "w:gz") as tout:
        for m in tin.getmembers():
            data = tin.extractfile(m).read()
            if m.name == "vectors/m.npy":
                data = b"changed"
                m.size = len(data)
            tout.addfile(m, io.BytesIO(data))
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "keep.txt").write_text("old")
    with pytest.raises(snapshot.SnapshotError, match="sha256"):
        snapshot.unpack_index(bad, tmp_path / "out")
    assert (tmp_path / "out" / "keep.txt").read_text() == "old"
    assert not (tmp_path / "out.tmp").exists()


def test_verify_and_pack_index_reject_bad_folder(tmp_path):
    src = _index(tmp_path / "index")
    (src / "links.jsonl").unlink()
    with pytest.raises(snapshot.SnapshotError, match="없다"):
        snapshot.verify_index(src)
    (src / "links.jsonl").write_bytes(b"other")
    with pytest.raises(snapshot.SnapshotError, match="sha256"):
        snapshot.verify_index(src)
    with pytest.raises(snapshot.SnapshotError, match="meta.json"):
        snapshot.pack_index(tmp_path / "empty", tmp_path / "x.tar.gz")


def test_unpack_index_into_existing_empty_folder(tmp_path):
    """compose가 ./data/index를 연결하면 폴더 자체는 바꿀 수 없다. 비어 있는(또는 옛) 폴더 안에 풀어야 한다."""
    archive = snapshot.pack_index(_index(tmp_path / "index"), tmp_path / "i.tar.gz")
    dst = tmp_path / "mounted"
    dst.mkdir()
    (dst / "old.txt").write_text("old")
    snapshot.unpack_index(archive, dst)
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()) == [
        "chunks.jsonl", "links.jsonl", "meta.json", "vectors/m.npy"]
    assert not (tmp_path / "mounted.tmp").exists()


def test_ensure_index_only_touches_default_folder(tmp_path, monkeypatch):
    archive = snapshot.pack_index(_index(tmp_path / "src"), tmp_path / "data" / "index.tar.gz")
    monkeypatch.chdir(tmp_path)
    log = lambda *_: None  # noqa: E731
    assert snapshot.ensure_index(tmp_path / "other", archive, log=log) is False  # 시험용 다른 폴더는 풀지 않음
    assert not (tmp_path / "other").exists()
    assert snapshot.ensure_index(snapshot.INDEX, tmp_path / "data" / "none.tar.gz", log=log) is False  # 압축 파일 없음
    assert snapshot.ensure_index(snapshot.INDEX, archive, log=log) is True  # 기본 위치는 없으면 푼다
    assert (tmp_path / "data" / "index" / "meta.json").is_file()
    (tmp_path / "data" / "index" / "mark").write_text("x")
    assert snapshot.ensure_index(snapshot.INDEX, archive, log=log) is True  # 이미 있으면 그대로
    assert (tmp_path / "data" / "index" / "mark").exists()


def test_loader_unpacks_committed_archive_before_index_url(tmp_path, monkeypatch):
    """loader(load_snapshot.ensure_index)는 data/index/가 없으면 INDEX_URL보다 먼저 커밋한 압축을 푼다."""
    from backend.rag.retrieve import load_snapshot
    snapshot.pack_index(_index(tmp_path / "src"), tmp_path / "data" / "index.tar.gz")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INDEX_URL", "http://127.0.0.1:9/never-called.tar.gz")  # 부르면 실패한다
    monkeypatch.setenv("INDEX_SHA256", "0" * 64)
    monkeypatch.setenv("INDEX_REQUIRED", "1")
    assert load_snapshot.ensure_index(snapshot.INDEX, log=lambda *_: None) is True
    assert (tmp_path / "data" / "index" / "vectors" / "m.npy").is_file()


def test_committed_index_archive_matches_meta():
    """저장소에 커밋한 색인 압축 파일 안의 파일이 meta.json sha256 그대로인지(clone 직후 상태)."""
    if not snapshot.INDEX_ARCHIVE.is_file():
        pytest.skip("data/index.tar.gz 없음")
    with tarfile.open(snapshot.INDEX_ARCHIVE, "r:gz") as tar:
        meta = json.loads(tar.extractfile("meta.json").read())
        want = dict(snapshot.index_files(meta))
        assert set(tar.getnames()) == {"meta.json", *want}
        for name, sha in want.items():
            h, f = hashlib.sha256(), tar.extractfile(name)
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
            assert h.hexdigest() == sha, name
