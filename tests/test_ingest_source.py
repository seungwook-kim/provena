"""F-10: DocumentSource 구현체가 기존 handbook 함수 출력과 같은지."""
from backend.rag.ingest import handbook as hb
from backend.rag.ingest.source import DirectorySnapshotSource, DocumentSource, HandbookGitSource
from test_ingest_handbook import PAGES, _repo_with_history


def test_handbook_git_source_equals_handbook_output(tmp_path):
    _, head, _ = _repo_with_history(tmp_path)
    src = HandbookGitSource(tmp_path, head)
    assert isinstance(src, DocumentSource)
    got = src.pages()

    listed = hb.list_pages(tmp_path, head)
    blobs = hb.read_blobs(tmp_path, [b for _, b in listed])
    versions = hb.last_changes(tmp_path, head, [p for p, _ in listed])
    assert [p.path for p in got] == PAGES == [p for p, _ in listed]
    for page, (path, blob) in zip(got, listed):
        assert page.data == blobs[blob]
        assert (page.version_id, page.version_date, page.version_date_before) == (
            versions[path][0][:12], versions[path][1], versions[path][2])


def test_directory_snapshot_source_reads_md_only(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.md").write_bytes(b"x\r\n")
    (tmp_path / "y.txt").write_text("no")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "z.md").write_text("no")
    src = DirectorySnapshotSource(tmp_path, version_id="v1", version_date="2026-11-01")
    assert isinstance(src, DocumentSource)
    pages = src.pages()
    assert [(p.path, p.data, p.version_id, p.version_date) for p in pages] == [("a/x.md", b"x\r\n", "v1", "2026-11-01")]
