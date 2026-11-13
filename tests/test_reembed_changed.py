"""바뀐 청크만 다시 임베딩하는 도구(`backend/rag/retrieve/reembed_changed.py`)의 오프라인 시험. `--fake`와 `--dry-run`만 쓴다(Voyage 호출·키·네트워크 없음)."""
from __future__ import annotations

import json

import numpy as np

from backend.rag.retrieve import embed
from backend.rag.retrieve import index as ix
from backend.rag.retrieve import reembed_changed as R

SPEC = embed.spec("voyage-4")


def _row(seq, text):
    return {"chunk_id": f"c{seq}", "rule_seq": 7, "seq": seq, "text": text, "version_id": "v1", "version_date": "2025-01-01", "version_date_before": False, "fetched_at": "2026-11-01"}


def _make_index(root, rows):
    (root / "vectors").mkdir(parents=True)
    rng = np.random.default_rng(1)
    vecs = rng.standard_normal((len(rows), SPEC.dim)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    np.save(root / "vectors" / "voyage-4.npy", vecs)
    chunks = root / "chunks.jsonl"
    chunks.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    meta = {"chunks_file": "chunks.jsonl", "n_chunks": len(rows), "chunks_sha256": ix.file_sha(chunks), "chunks_fingerprint": ix.fingerprint(rows),
            "embedders": {"voyage-4": {"file": "vectors/voyage-4.npy", "sha256": ix.file_sha(root / "vectors" / "voyage-4.npy"), "check": {"x": 1}}}}
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return vecs


def _new_chunks(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_fake_run_keeps_unchanged_vectors_and_embeds_only_the_changed_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VOYAGE_API_KEY", "secret-key-value-for-test")
    monkeypatch.setattr(embed, "load_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Voyage 모델을 부르면 안 된다")))
    old = [_row(1, "first chunk text"), _row(2, "second chunk text"), _row(3, "third chunk text")]
    old_vecs = _make_index(tmp_path / "index", old)
    new = [old[0], {**old[1], "text": "label: second chunk text with the copied overlap"}, old[2]]
    _new_chunks(tmp_path / "new.jsonl", new)
    out = tmp_path / "out"
    assert R.main(["--new-chunks", str(tmp_path / "new.jsonl"), "--index", str(tmp_path / "index"), "--out", str(out), "--fake"]) == 0
    printed = capsys.readouterr().out
    assert "secret-key-value-for-test" not in printed  # 키는 환경 변수로만 받고 출력하지 않는다
    assert "새로 계산할 글 1개" in printed and '"embedded": 1' in printed
    vecs = np.load(out / "vectors" / "voyage-4.npy")
    assert vecs.shape == old_vecs.shape and np.array_equal(vecs[0], old_vecs[0]) and np.array_equal(vecs[2], old_vecs[2])  # 같은 자리 글은 비트까지 같다
    assert not np.array_equal(vecs[1], old_vecs[1]) and abs(float(np.linalg.norm(vecs[1])) - 1.0) < 1e-4  # 바뀐 글만 새 벡터(길이 1)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["n_chunks"] == 3 and meta["chunks_fingerprint"] == ix.fingerprint(ix.load_rows(out / "chunks.jsonl"))
    assert "secret-key-value-for-test" not in json.dumps(meta) and "check" not in meta["embedders"]["voyage-4"]
    assert [r["text"] for r in ix.load_rows(out / "chunks.jsonl")][1].startswith("label:")
    assert ix.read_meta(tmp_path / "index")["n_chunks"] == 3 and np.array_equal(np.load(tmp_path / "index" / "vectors" / "voyage-4.npy"), old_vecs)  # 옛 색인은 그대로


def test_dry_run_writes_nothing_and_does_not_need_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    old = [_row(1, "a text"), _row(2, "b text")]
    _make_index(tmp_path / "index", old)
    _new_chunks(tmp_path / "new.jsonl", [old[0], {**old[1], "text": "b text changed"}])
    out = tmp_path / "out"
    assert R.main(["--new-chunks", str(tmp_path / "new.jsonl"), "--index", str(tmp_path / "index"), "--out", str(out), "--dry-run"]) == 0
    assert "새로 계산할 글 1개" in capsys.readouterr().out and not out.exists()
