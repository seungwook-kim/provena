"""원문 스냅샷 압축(backend/rag/ingest/snapshot.py): 같은 원문이면 같은 압축, 풀면 그대로, 바뀐 원문·위험한 경로는 막음."""
import io
import json
import tarfile

import pytest

from backend.rag.ingest import snapshot
from backend.rag.ingest.handbook import corpus_id, sha256


def _corpus(root, body=b"# Page\n\nhello\r\n"):
    (root / "handbook" / "a").mkdir(parents=True)
    (root / "authz").mkdir()
    (root / "handbook" / "a" / "x.md").write_bytes(body)
    authz = b"| matrix |\n"
    (root / snapshot.AUTHZ).write_bytes(authz)
    page = {"path": "content/handbook/a/x.md", "file_sha256": sha256(body)}
    (root / "pages.jsonl").write_text(json.dumps(page) + "\n", encoding="utf-8")
    manifest = {"corpus_id": corpus_id([page["file_sha256"]]), "authz": {"file_sha256": sha256(authz)}}
    (root / "collect_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_pack_is_deterministic_and_roundtrips(tmp_path):
    src = _corpus(tmp_path / "corpus")
    a, b = snapshot.pack(src, tmp_path / "a.tar.gz"), snapshot.pack(src, tmp_path / "b.tar.gz")
    assert a.read_bytes() == b.read_bytes()
    info = snapshot.unpack(a, tmp_path / "out")
    assert info["pages"] == 1
    assert (tmp_path / "out" / "handbook" / "a" / "x.md").read_bytes() == b"# Page\n\nhello\r\n"  # 줄바꿈 그대로


def test_unpack_rejects_changed_text_and_keeps_old_folder(tmp_path):
    src = _corpus(tmp_path / "corpus")
    (src / "handbook" / "a" / "x.md").write_bytes(b"changed")  # pages.jsonl의 sha256과 달라짐
    archive = snapshot.pack(src, tmp_path / "c.tar.gz")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "keep.txt").write_text("old")
    with pytest.raises(snapshot.SnapshotError, match="sha256"):
        snapshot.unpack(archive, tmp_path / "out")
    assert (tmp_path / "out" / "keep.txt").read_text() == "old"
    assert not (tmp_path / "out.tmp").exists()


def test_unpack_blocks_path_outside_folder(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(tarfile.FilterError):
        snapshot.unpack(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_ensure_only_touches_default_folder(tmp_path, monkeypatch):
    src = _corpus(tmp_path / "src")
    archive = snapshot.pack(src, tmp_path / "data" / "corpus.tar.gz")
    monkeypatch.chdir(tmp_path)
    snapshot.ensure(tmp_path / "other", archive)  # 시험용 다른 폴더는 풀지 않음
    assert not (tmp_path / "other").exists()
    snapshot.ensure(snapshot.CORPUS, archive)  # 기본 위치는 없으면 푼다
    assert (tmp_path / "data" / "corpus" / "pages.jsonl").is_file()
    (tmp_path / "data" / "corpus" / "mark").write_text("x")
    snapshot.ensure(snapshot.CORPUS, archive)  # 이미 있으면 그대로
    assert (tmp_path / "data" / "corpus" / "mark").exists()


def test_committed_archive_matches_collect_manifest():
    """저장소에 커밋한 압축 파일이 수집 때 sha256 그대로인지(clone 직후 상태)."""
    if not snapshot.ARCHIVE.is_file():
        pytest.skip("data/corpus.tar.gz 없음")
    with tarfile.open(snapshot.ARCHIVE, "r:gz") as tar:
        names = set(tar.getnames())
        assert {"pages.jsonl", "collect_manifest.json", snapshot.AUTHZ} <= names
        pages = [json.loads(x) for x in tar.extractfile("pages.jsonl").read().decode("utf-8").splitlines() if x.strip()]
        manifest = json.loads(tar.extractfile("collect_manifest.json").read())
    assert corpus_id([p["file_sha256"] for p in pages]) == manifest["corpus_id"]
    assert all("handbook/" + p["path"].removeprefix("content/handbook/") in names for p in pages)
