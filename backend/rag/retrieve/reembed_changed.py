"""바뀐 청크만 다시 임베딩해 색인(data/index/)을 갈아 끼운다.

기존 `index.py build`는 1,000개 블록 단위 캐시라 바뀐 글이 블록마다 하나씩만 있어도 거의 전부 다시 계산한다(parts 키 = 블록 해시).
`index.py refresh`는 본문·id가 같을 때만 쓸 수 있다(여기서는 id 37개가 바뀌어 멈춘다).
그래서 "예전 색인의 글 -> 벡터"를 재사용하고, 예전에 없던 글(762행, 서로 다른 글 760개)만 임베딩한다.
schedule.apply(증분 수집)가 DB의 같은 글 벡터를 재사용하는 것과 같은 원리다.

사용(운영자 승인 뒤, Voyage 키는 환경 변수 VOYAGE_API_KEY로만):
    python -m backend.rag.retrieve.reembed_changed --new-chunks data/chunks/chunks.jsonl --index data/index [--dry-run] [--fake]
  --dry-run: 임베딩 호출 없이 몇 개를 다시 계산할지만 출력
  --fake:    Voyage를 부르지 않고 글 해시로 만든 가짜 단위벡터로 조립만 시험(오프라인 검증용, 결과는 쓰지 않고 --out에 둔다)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from backend.rag.retrieve import embed
from backend.rag.retrieve import index as ix


def fake_vecs(texts: list[str], dim: int) -> np.ndarray:
    out = []
    for t in texts:
        seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "little")
        v = np.random.default_rng(seed).standard_normal(dim).astype(np.float32)
        out.append(v / np.linalg.norm(v))
    return np.stack(out)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-chunks", type=Path, default=Path("data/chunks/chunks.jsonl"))
    ap.add_argument("--index", type=Path, default=Path("data/index"))
    ap.add_argument("--out", type=Path, default=None, help="기본: --index 자리에 쓴다")
    ap.add_argument("--embedder", default="voyage-4")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args(argv)
    out = a.out or a.index
    s = embed.spec(a.embedder)
    meta = ix.read_meta(a.index)
    ent = meta["embedders"][s.name]
    old_rows = ix.load_rows(a.index / meta["chunks_file"])
    old_vecs = np.load(a.index / ent["file"])
    new_rows = ix.load_rows(a.new_chunks)
    assert len(old_rows) == len(old_vecs) == meta["n_chunks"]

    # 색인 쪽 판 날짜 칸(UTC 반영, refresh로 들어간 값)은 그대로 둔다. 새 청크 파일에서는 본문·겹침·줄·id 쪽만 가져온다.
    by_key = {(r["rule_seq"], r["seq"]): r for r in old_rows}
    rows = []
    for n in new_rows:
        o = by_key.get((n["rule_seq"], n["seq"]))
        rows.append({**n, **{k: o[k] for k in ("version_date", "version_date_before", "fetched_at", "version_id")}} if o else n)
    assert [(r["rule_seq"], r["seq"]) for r in rows] == [(r["rule_seq"], r["seq"]) for r in old_rows], "쪽·순번 배열이 다르다"

    # 같은 자리의 글이 그대로면 그 자리의 옛 벡터를 그대로 쓴다. (같은 글이 여러 행에 있어도 옛 색인의 벡터가 행마다 8e-4쯤 달라, 글로 찾으면 192행이 미세하게 바뀐다)
    keep = [i for i, (o, n) in enumerate(zip(old_rows, rows)) if o["text"] == n["text"]]
    kept = set(keep)
    have = {}
    for i, r in enumerate(old_rows):
        have.setdefault(r["text"], old_vecs[i])
    need = list(dict.fromkeys(r["text"] for i, r in enumerate(rows) if i not in kept and r["text"] not in have))
    print(f"청크 {len(rows)}행, 같은 자리 벡터 그대로 {len(keep)}행, 바뀐 글 {len(rows) - len(keep)}행 중 새로 계산할 글 {len(need)}개(서로 다른 글, 같은 글이 두 번 나오면 한 번만)")
    if a.dry_run:
        return 0
    if need:
        if a.fake:
            new_v = fake_vecs(need, s.dim)
        else:
            model = embed.load_model(s.name, None)
            new_v = embed.encode_docs(model, need)
        have.update(zip(need, new_v))
    vecs = np.stack([old_vecs[i] if i in kept else have[r["text"]] for i, r in enumerate(rows)]).astype(np.float32)
    embed.check_norms(vecs)
    tmp_chunks = out / "chunks.new.jsonl"
    out.mkdir(parents=True, exist_ok=True)
    with tmp_chunks.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # write_snapshot은 청크 집합 지문이 다르면 멈춘다 -> 새 meta로 다시 쓴다(옛 meta의 embedders·번역 장부 표기는 이어받고 지문·sha256을 새로 적는다)
    new_meta = {k: v for k, v in meta.items() if k not in ("chunks_fingerprint", "chunks_sha256", "n_chunks", "links")}
    (out / "vectors").mkdir(exist_ok=True)
    np.save(out / ent["file"], vecs)
    tmp_chunks.replace(out / "chunks.jsonl")
    new_meta.update({"chunks_sha256": ix.file_sha(out / "chunks.jsonl"), "n_chunks": len(rows), "chunks_fingerprint": ix.fingerprint(rows)})
    new_meta["embedders"][s.name].update({"sha256": ix.file_sha(out / ent["file"]), "made_by": "reembed_changed(2026-11-13: 청크 쪼개기·표 겹침 수정, 바뀐 글만)"})
    new_meta["embedders"][s.name].pop("check", None)
    (out / "meta.json").write_text(json.dumps(new_meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"n_chunks": len(rows), "embedded": len(need), "chunks_sha256": new_meta["chunks_sha256"][:12]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
