"""색인 만들기(오프라인, 모델 필요): data/chunks/chunks.jsonl → data/index/ (docs/specs/search.md, 가이드 p.12 4-3).

    python -m backend.rag.retrieve.index build --embedder Snowflake/snowflake-arctic-embed-l-v2.0     # 직접 임베딩(GPU 권장)
    python -m backend.rag.retrieve.index import --from data/index_exp --embedder Snowflake/snowflake-arctic-embed-l-v2.0
    python -m backend.rag.retrieve.index check --embedder Snowflake/snowflake-arctic-embed-l-v2.0      # 이 장비에서 표본 재계산

결과(data/index/): chunks.jsonl(청크 파일 그대로) · vectors/<모델 줄임>.npy(float32, 행 순서 = chunks.jsonl) · meta.json.
- meta.json: 청크 수·청크 파일 sha256·청크 지문(chunk_id·version_id·본문 해시 정렬), 모델마다 판·차원·앞말·벡터 sha256.
  load_snapshot이 이 sha256으로 받은 파일을 대조한다. 이 파일은 저장소에 커밋하고 큰 파일은 Release로 나눠 준다(Spec 열린 항목 6).
- build: 같은 본문은 한 번만 계산하고, 1,000개마다 중간 저장(parts/)해 끊겨도 이어 간다. 저장 키에 모델·판·앞말을 넣는다(I-010).
- import: 1차 비교 캐시(data/index_exp/<이름>.npy + chunk_ids.json)를 받아 쓴다. 순서·개수·길이·차원을 대조한다.
- check: 청크 n개(시드 고정)를 이 장비에서 다시 임베딩해, 평가셋 질문마다 그 n개의 순위가 받은 벡터와 같은지 본다.
- translations: 1차 비교 번역(translations.json)을 번역 장부 파일(query_translations.jsonl)로 옮기고 meta.json에 sha256을 적는다.
    python -m backend.rag.retrieve.index translations --from evals/results/retrieval_v1_round1/translations.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from backend.rag.retrieve import embed

CHUNKS = Path("data/chunks/chunks.jsonl")
OUT = Path("data/index")
DATASET = Path("evals/dataset_v1.jsonl")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"청크가 없다: {path}")
    return rows


def fingerprint(rows: list[dict]) -> str:
    """같은 청크 집합인가(순서 무관). 계약 text_sha256은 본문만이라 여기서는 text 전체를 다시 해시한다."""
    lines = sorted(f"{r['chunk_id']}\t{r['version_id']}\t{sha(r['text'])}" for r in rows)
    return sha("\n".join(lines))


def vector_file(s: embed.EmbedderSpec) -> str:
    return f"vectors/{s.short}.npy"


def read_meta(out: Path) -> dict:
    p = out / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def write_snapshot(out: Path, chunks: Path, rows: list[dict], s: embed.EmbedderSpec, vecs: np.ndarray, entry: dict) -> dict:
    """청크 파일을 복사하고 벡터를 저장한 뒤 meta.json을 갱신한다. 다른 청크 집합의 meta가 있으면 멈춘다."""
    if len(vecs) != len(rows):
        raise ValueError(f"벡터 {len(vecs)} ≠ 청크 {len(rows)}")
    if vecs.shape[1] != s.dim:
        raise ValueError(f"차원이 다르다: {s.name} 명부 {s.dim}, 벡터 {vecs.shape[1]}")
    embed.check_norms(vecs)
    out.mkdir(parents=True, exist_ok=True)
    meta = read_meta(out)
    fp = fingerprint(rows)
    if meta and meta.get("chunks_fingerprint") != fp:
        raise SystemExit(f"{out}/meta.json 은 다른 청크 집합이다 — 지우고 다시 만든다")
    dst = out / "chunks.jsonl"
    if not dst.is_file() or file_sha(dst) != file_sha(chunks):
        shutil.copyfile(chunks, dst)
    vpath = out / vector_file(s)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    np.save(vpath, vecs.astype(np.float32))
    meta.update({"chunks_file": "chunks.jsonl", "chunks_sha256": file_sha(dst), "n_chunks": len(rows),
                 "chunks_fingerprint": fp})
    meta.setdefault("embedders", {})[s.name] = {
        "short": s.short, "revision": entry.pop("revision"), "dim": s.dim, "max_seq_length": embed.MAX_SEQ_LENGTH,
        "file": vector_file(s), "sha256": file_sha(vpath), **entry,
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return meta


def embed_unique(model, texts: list[str], parts: Path, salt: str, save_every: int = 1000) -> np.ndarray:
    uniq = list(dict.fromkeys(texts))
    parts.mkdir(parents=True, exist_ok=True)
    done, secs = [], 0.0
    for start in range(0, len(uniq), save_every):
        block = uniq[start:start + save_every]
        part, key = parts / f"part_{start:06d}.npy", parts / f"part_{start:06d}.sha256"
        block_key = sha(salt + "\n" + "\n".join(sha(t) for t in block))
        if part.exists() and key.exists() and key.read_text() == block_key:
            done.append(np.load(part))
            continue
        t0 = time.perf_counter()
        vecs = embed.encode_docs(model, block)
        secs += time.perf_counter() - t0
        np.save(part, vecs)
        key.write_text(block_key)
        done.append(vecs)
        print(f"  {start + len(block)}/{len(uniq)}  누적 {secs:.0f}초", flush=True)
    uvecs = np.concatenate(done)
    pos = {t: i for i, t in enumerate(uniq)}
    return uvecs[[pos[t] for t in texts]]


def cmd_build(a) -> int:
    s = embed.spec(a.embedder)
    rows = load_rows(a.chunks)
    model = embed.load_model(s.name, a.device)
    salt = json.dumps([s.name, model.pinned_revision, embed.used_prefixes(model, s), embed.MAX_SEQ_LENGTH])
    t0 = time.perf_counter()
    vecs = embed_unique(model, [r["text"] for r in rows], a.out / "parts" / s.short, salt)
    meta = write_snapshot(a.out, a.chunks, rows, s, vecs, {
        "revision": model.pinned_revision, "prefixes": embed.used_prefixes(model, s), "made_by": "build",
        "device": str(model.device), "encode_seconds": round(time.perf_counter() - t0, 1)})
    print(json.dumps(meta["embedders"][s.name], ensure_ascii=False))
    return 0


def cmd_import(a) -> int:
    """1차 비교 캐시: <from>/<short>.npy 의 행 순서 = <from>/chunk_ids.json (experiment_v1.prepare)."""
    s = embed.spec(a.embedder)
    rows = load_rows(a.chunks)
    ids = json.loads((a.src / "chunk_ids.json").read_text(encoding="utf-8"))
    mine = [r["chunk_id"] for r in rows]
    if ids != mine:
        bad = next((i for i, (x, y) in enumerate(zip(ids, mine)) if x != y), min(len(ids), len(mine)))
        raise SystemExit(f"청크 순서가 다르다: 받은 것 {len(ids)}개, 여기 {len(mine)}개, 처음 다른 줄 {bad}")
    vecs = np.load(a.src / f"{s.short}.npy").astype(np.float32)
    rev = a.revision or s.revision
    meta = write_snapshot(a.out, a.chunks, rows, s, vecs, {
        "revision": rev, "prefixes": {"note": "1차 비교 캐시 — check로 이 장비 재계산과 대조할 것"},
        "made_by": f"import:{a.src}", "revision_confirmed": bool(a.revision)})
    print(json.dumps(meta["embedders"][s.name], ensure_ascii=False))
    return 0


def same_ranking(got: np.ndarray, local: np.ndarray, qvecs: np.ndarray) -> dict:
    """질문마다 표본 청크를 두 벡터로 각각 순위 매겨 비교(동점은 번호 순). 코사인 문턱 대신 순서로 판정한다."""
    def rank(v):
        return np.array([np.lexsort((np.arange(len(v)), -sc)) for sc in qvecs @ v.T])
    a, b = rank(got), rank(local)
    differ = [i for i in range(len(qvecs)) if not np.array_equal(a[i], b[i])]
    top5 = [i for i in range(len(qvecs)) if set(a[i][:5]) != set(b[i][:5])]
    cos = np.sum(got * local, axis=1)
    return {"questions": len(qvecs), "order_differs": differ, "top5_differs": top5,
            "cosine_min": round(float(cos.min()), 6), "cosine_mean": round(float(cos.mean()), 6)}


def cmd_check(a) -> int:
    s = embed.spec(a.embedder)
    meta = read_meta(a.out)
    ent = (meta.get("embedders") or {}).get(s.name)
    if not ent:
        raise SystemExit(f"{a.out}/meta.json 에 {s.name} 가 없다")
    rows = load_rows(a.out / "chunks.jsonl")
    vecs = np.load(a.out / ent["file"])
    model = embed.load_model(s.name, a.device)
    picks = sorted(random.Random(a.seed).sample(range(len(rows)), min(a.sample, len(rows))))
    local = embed.encode_docs(model, [rows[i]["text"] for i in picks])
    qs = [json.loads(x)["input"] for x in a.dataset.read_text(encoding="utf-8").splitlines() if x.strip()]
    rank = same_ranking(vecs[picks], local, embed.encode_queries(model, qs))
    ent["check"] = {**rank, "sample": len(picks), "seed": a.seed, "device": str(model.device),
                    "local_revision": model.pinned_revision, "passed": not rank["order_differs"],
                    "checked_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    (a.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(ent["check"], ensure_ascii=False))
    return 0 if ent["check"]["passed"] else 1


TRANSLATIONS_FILE = "query_translations.jsonl"


def cmd_translations(a) -> int:
    """1차 비교 번역(experiment_v1 TRANSLATIONS 형식: {"model", "items": {질문: {"keywords", "sentence"}}})을
    스냅샷 번역 장부 파일로 옮긴다. load_snapshot이 DB 장부에, make_search가 메모리 장부에 넣는다.
    같은 번역으로 돌아야 1차 비교를 재현한다(번역은 부를 때마다 달라진다, 11/2 V3: 29/30 다름)."""
    src = json.loads(a.src.read_text(encoding="utf-8"))
    model, items = src["model"], src["items"]
    rows = []
    for q, v in items.items():
        if not v.get("keywords") and not v.get("sentence"):
            raise SystemExit(f"번역이 비었다: {q[:40]}")
        rows.append({"query_sha256": sha(q), "model": model, "keywords": v.get("keywords"), "sentence": v.get("sentence")})
    rows.sort(key=lambda r: r["query_sha256"])
    path = a.out / TRANSLATIONS_FILE
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
    meta = read_meta(a.out)
    if not meta:
        raise SystemExit(f"{a.out}/meta.json이 없다 — build 또는 import를 먼저 돌린다")
    meta["query_translations"] = {"file": TRANSLATIONS_FILE, "sha256": file_sha(path), "n": len(rows), "model": model,
                                  "source": a.src.as_posix(), "source_sha256": file_sha(a.src)}
    (a.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta["query_translations"], ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.retrieve.index")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("translations", help="1차 비교 번역 → 스냅샷 번역 장부")
    p.add_argument("--from", dest="src", type=Path, required=True)
    p.add_argument("--out", type=Path, default=OUT)
    for name in ("build", "import", "check"):
        p = sub.add_parser(name)
        p.add_argument("--embedder", default=None, help="EMBED_MODEL 값 (기본: 환경 변수, 없으면 arctic)")
        p.add_argument("--chunks", type=Path, default=CHUNKS)
        p.add_argument("--out", type=Path, default=OUT)
        p.add_argument("--device", default=None)
        if name == "import":
            p.add_argument("--from", dest="src", type=Path, required=True)
            p.add_argument("--revision", default=None, help="1차 비교 때 쓴 HF 커밋(조장 확인값)")
        if name == "check":
            p.add_argument("--sample", type=int, default=50)
            p.add_argument("--seed", type=int, default=0)
            p.add_argument("--dataset", type=Path, default=DATASET)
    a = ap.parse_args(argv)
    return {"build": cmd_build, "import": cmd_import, "check": cmd_check, "translations": cmd_translations}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
