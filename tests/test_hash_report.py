"""0원 시험: 청크 해시 기록 도구(backend/rag/ingest/hash_report.py). 임시 data 폴더만 쓴다(저장소 data/를 읽지도 바꾸지도 않는다)."""
from __future__ import annotations

import hashlib
import json

from backend.rag.ingest import hash_report


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _data(tmp_path, eol="\n", extra_chunk=False):
    d = tmp_path / "data"
    (d / "chunks").mkdir(parents=True)
    rows = [{"chunk_id": f"c{i}", "doc_id": 1, "seq": i, "kind": "article", "line_start": 1, "line_end": 2, "chunk_sha256": _sha(f"body{i % 2}".encode()), "body_chars": 5} for i in range(4)]
    (d / "chunks_index.jsonl").write_bytes("".join(json.dumps(r) + eol for r in rows).encode("utf-8"))
    (d / "manifest.jsonl").write_bytes("".join(json.dumps({"doc_id": 1, "version_id": "v", "chunks": 4}) + eol for _ in range(1)).encode("utf-8"))
    full = [{"chunk_id": r["chunk_id"], "body_sha256": r["chunk_sha256"], "text": "x"} for r in rows]
    if extra_chunk:
        full.append({"chunk_id": "cx", "body_sha256": _sha(b"other"), "text": "x"})
    (d / "chunks" / "chunks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in full), encoding="utf-8")
    return d, rows


def test_report_counts_rows_distinct_hashes_and_both_eol_hashes(tmp_path):
    d, rows = _data(tmp_path, "\n")
    r = hash_report.build_report(d)
    ci = r["chunks_index"]
    assert (ci["rows"], ci["distinct_chunk_sha256"], ci["distinct_chunk_id"], ci["eol"]) == (4, 2, 4, "lf")
    raw = (d / "chunks_index.jsonl").read_bytes()
    assert ci["sha256_raw"] == ci["sha256_lf"] == _sha(raw) and ci["sha256_crlf"] == _sha(raw.replace(b"\n", b"\r\n"))
    assert r["manifest"]["docs"] == 1 and r["manifest"]["chunks_sum"] == 4
    assert r["chunks_jsonl_vs_index"]["same_pairs_in_order"] is True


def test_lf_and_crlf_checkouts_have_the_same_lf_and_crlf_hashes_but_different_raw(tmp_path):
    """같은 내용이라도 CRLF로 받은 작업 폴더는 raw 해시가 다르다. 저장소 값(LF)은 두 쪽 모두 같은 열에서 나온다."""
    a = hash_report.build_report(_data(tmp_path / "a", "\n")[0])["chunks_index"]
    b = hash_report.build_report(_data(tmp_path / "b", "\r\n")[0])["chunks_index"]
    assert b["eol"] == "crlf" and a["sha256_raw"] != b["sha256_raw"]
    assert a["sha256_lf"] == b["sha256_lf"] and a["sha256_crlf"] == b["sha256_crlf"] and b["sha256_raw"] == b["sha256_crlf"]


def test_pair_mismatch_between_chunks_jsonl_and_the_list_is_reported(tmp_path):
    d, _ = _data(tmp_path, extra_chunk=True)
    c = hash_report.build_report(d)["chunks_jsonl_vs_index"]
    assert c["same_pairs_in_order"] is False and c["pairs_only_in_chunks_jsonl"] == 1 and c["pairs_only_in_index"] == 0


def test_index_meta_hash_check_and_missing_optional_files(tmp_path):
    d, _ = _data(tmp_path)
    assert "index_meta" not in hash_report.build_report(d)
    (d / "index").mkdir()
    body = b'{"chunk_id": "c0"}\n{"chunk_id": "c1"}\n'
    (d / "index" / "chunks.jsonl").write_bytes(body)
    (d / "index" / "meta.json").write_text(json.dumps({"chunks_file": "chunks.jsonl", "n_chunks": 2, "chunks_sha256": _sha(body), "embedders": {"voyage-4": {}}}), encoding="utf-8")
    m = hash_report.build_report(d)["index_meta"]
    assert m["meta_sha256_matches_raw"] is True and m["index_chunks_rows"] == 2 and m["embedders"] == ["voyage-4"]


def test_main_writes_json_and_markdown_to_the_out_folder(tmp_path, capsys):
    d, _ = _data(tmp_path)
    out = tmp_path / "out"
    assert hash_report.main(["--data", str(d), "--out", str(out)]) == 0
    rep = json.loads((out / "chunk_hash_report.json").read_text(encoding="utf-8"))
    md = (out / "chunk_hash_report.md").read_text(encoding="utf-8")
    assert rep["chunks_index"]["rows"] == 4 and "sha256 LF 기준" in md and rep["chunks_index"]["sha256_lf"] in md
    assert "서로 다른 chunk_sha256 2" in capsys.readouterr().out
    assert not (d / "chunks_index.jsonl.bak").exists()      # data 폴더에는 아무것도 쓰지 않는다
    assert sorted(p.name for p in d.iterdir()) == ["chunks", "chunks_index.jsonl", "manifest.jsonl"]
