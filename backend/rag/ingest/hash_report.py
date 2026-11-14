"""청크 해시 기록을 한 명령으로 다시 만든다(0원, 읽기만: data/ 파일을 바꾸지 않는다).

    python -m backend.rag.ingest.hash_report [--data data] [--out evals/results/chunk_hashes_<오늘>]

무엇을 기록하나 (체크포인트 D10 "청크별 sha256 목록이나 DB 행 수 조회와 열람 방법, 해시는 CRLF·LF까지"):
- 청크별 sha256 목록은 `data/chunks_index.jsonl`(커밋, 줄마다 `chunk_id`, `chunk_sha256`)이다. 이 도구는 그 목록의 줄 수, 서로 다른 해시 수, 문서 수를 세고
  (있으면) 풀린 `data/chunks/chunks.jsonl`의 (chunk_id, body_sha256) 쌍과 줄 단위로 같은지, 풀린 색인 `data/index/meta.json`의 `n_chunks`·`chunks_sha256`이 `data/index/chunks.jsonl`과 맞는지 본다.
- `chunk_sha256`은 청크 본문 글자(UTF-8)의 sha256이다(`backend/rag/ingest/chunk.py`의 `sha(body)`, 머리말·겹침 뺀 본문만). 파일의 줄바꿈과 무관하다.
- 목록 파일(`chunks_index.jsonl`, `manifest.jsonl`)의 해시는 파일 바이트의 sha256이라 줄바꿈에 따라 달라진다. 그래서 raw(지금 작업 폴더 바이트), LF로 맞춘 값, CRLF로 맞춘 값을 모두 적는다.
  저장소 안(git blob)은 LF이고(`load.py`가 `newline="\\n"`으로 쓴다), `.gitattributes`가 두 파일을 `eol=lf`로 고정하므로 어느 운영체제에서 받아도 raw 값이 LF 값과 같아야 한다.
- DB 행 수는 운영 DB를 읽어야 해서 이 도구 범위 밖이다(읽기 전용 조회 스크립트와 기록 표는 `docs/specs/chunk.md`의 "청크 해시와 DB 행 수 기록").

결과: `<out>/chunk_hash_report.json`, `<out>/chunk_hash_report.md`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_hashes(path: Path) -> dict:
    """파일 바이트의 sha256을 raw, LF로 맞춘 값, CRLF로 맞춘 값으로 낸다. `eol`은 지금 파일의 줄바꿈(lf, crlf, mixed, none)."""
    raw = path.read_bytes()
    crlf, lf_only = raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")
    eol = "none" if not (crlf or lf_only) else "crlf" if crlf and not lf_only else "lf" if lf_only and not crlf else "mixed"
    lf = raw.replace(b"\r\n", b"\n")
    return {"file": path.name, "bytes": len(raw), "lines": lf.count(b"\n"), "eol": eol, "sha256_raw": _sha(raw), "sha256_lf": _sha(lf), "sha256_crlf": _sha(lf.replace(b"\n", b"\r\n"))}


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def build_report(data: Path) -> dict:
    index_rows = _rows(data / "chunks_index.jsonl")
    shas = [r["chunk_sha256"] for r in index_rows]
    report: dict = {
        "chunks_index": {**file_hashes(data / "chunks_index.jsonl"), "rows": len(index_rows), "distinct_chunk_sha256": len(set(shas)), "distinct_chunk_id": len({r["chunk_id"] for r in index_rows}),
                         "per_chunk_list": "data/chunks_index.jsonl (줄마다 chunk_id, chunk_sha256)"},
    }
    manifest_rows = _rows(data / "manifest.jsonl")
    report["manifest"] = {**file_hashes(data / "manifest.jsonl"), "rows": len(manifest_rows), "docs": len({r["doc_id"] for r in manifest_rows}), "chunks_sum": sum(int(r.get("chunks") or 0) for r in manifest_rows)}
    chunks_file = data / "chunks" / "chunks.jsonl"
    if chunks_file.is_file():
        pairs = [(r["chunk_id"], r["body_sha256"]) for r in _rows(chunks_file)]
        idx_pairs = [(r["chunk_id"], r["chunk_sha256"]) for r in index_rows]
        report["chunks_jsonl_vs_index"] = {"chunks_jsonl_rows": len(pairs), "index_rows": len(idx_pairs), "same_pairs_in_order": pairs == idx_pairs,
                                           "pairs_only_in_chunks_jsonl": len(set(pairs) - set(idx_pairs)), "pairs_only_in_index": len(set(idx_pairs) - set(pairs))}
    meta_file = data / "index" / "meta.json"
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        idx_chunks = data / "index" / meta.get("chunks_file", "chunks.jsonl")
        info = {"n_chunks": meta.get("n_chunks"), "chunks_sha256": meta.get("chunks_sha256"), "embedders": sorted((meta.get("embedders") or {}))}
        if idx_chunks.is_file():
            raw = idx_chunks.read_bytes()
            info["index_chunks_file_sha256_raw"] = _sha(raw)
            info["index_chunks_file_sha256_lf"] = _sha(raw.replace(b"\r\n", b"\n"))
            info["meta_sha256_matches_raw"] = info["index_chunks_file_sha256_raw"] == meta.get("chunks_sha256")
            info["meta_sha256_matches_lf"] = info["index_chunks_file_sha256_lf"] == meta.get("chunks_sha256")
            info["index_chunks_rows"] = sum(1 for x in raw.splitlines() if x.strip())
        report["index_meta"] = info
    return report


def render_md(r: dict) -> str:
    ci, mf = r["chunks_index"], r["manifest"]
    out = ["# 청크 해시 기록", "",
           "생성: `python -m backend.rag.ingest.hash_report` (0원, 읽기만). 청크별 sha256 목록은 `data/chunks_index.jsonl`이고, `chunk_sha256`은 청크 본문 글자(UTF-8)의 sha256이라 줄바꿈과 무관하다.", "",
           "| 파일 | 줄 수 | 서로 다른 값 | 지금 줄바꿈 | sha256 raw | sha256 LF 기준 | sha256 CRLF 기준 |", "|---|---|---|---|---|---|---|",
           f"| `data/chunks_index.jsonl` | {ci['rows']} | 청크 해시 {ci['distinct_chunk_sha256']}, 청크 id {ci['distinct_chunk_id']} | {ci['eol']} | `{ci['sha256_raw']}` | `{ci['sha256_lf']}` | `{ci['sha256_crlf']}` |",
           f"| `data/manifest.jsonl` | {mf['rows']} | 문서 {mf['docs']} (청크 수 합 {mf['chunks_sum']}) | {mf['eol']} | `{mf['sha256_raw']}` | `{mf['sha256_lf']}` | `{mf['sha256_crlf']}` |", "",
           "저장소 안(git blob)은 LF 기준 값이다. Windows 작업 폴더가 CRLF이면 raw 값이 CRLF 기준 값과 같고 저장소 값과 다르다(`.gitattributes`가 두 파일을 `eol=lf`로 고정해 새로 받은 폴더는 LF가 된다).", ""]
    if "chunks_jsonl_vs_index" in r:
        c = r["chunks_jsonl_vs_index"]
        out += ["풀린 `data/chunks/chunks.jsonl`과 목록 대조: " + f"줄 {c['chunks_jsonl_rows']} 대 {c['index_rows']}, 같은 (chunk_id, body_sha256) 쌍을 같은 순서로 가짐 = {c['same_pairs_in_order']}, 한쪽에만 있는 쌍 {c['pairs_only_in_chunks_jsonl']} / {c['pairs_only_in_index']}", ""]
    if "index_meta" in r:
        m = r["index_meta"]
        out += ["풀린 색인 `data/index/meta.json`: " + f"`n_chunks` {m['n_chunks']}, `chunks_sha256` `{m['chunks_sha256']}`, 색인 `chunks.jsonl` 줄 {m.get('index_chunks_rows')}, "
                f"meta 해시와 파일 바이트 일치(raw {m.get('meta_sha256_matches_raw')}, LF {m.get('meta_sha256_matches_lf')})", ""]
    out += ["열람: `python -c \"import json;r=[json.loads(l) for l in open('data/chunks_index.jsonl',encoding='utf-8') if l.strip()];print(len(r),len({x['chunk_sha256'] for x in r}))\"` 또는 에디터에서 `data/chunks_index.jsonl`을 연다.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "data", help="data 폴더(기본: 저장소의 data)")
    ap.add_argument("--out", type=Path, default=None, help="결과 폴더(기본: evals/results/chunk_hashes_<오늘>)")
    a = ap.parse_args(argv)
    out = a.out or ROOT / "evals" / "results" / f"chunk_hashes_{date.today():%Y%m%d}"
    report = build_report(a.data)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chunk_hash_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    (out / "chunk_hash_report.md").write_text(render_md(report) + "\n", encoding="utf-8", newline="\n")
    ci = report["chunks_index"]
    print(f"chunks_index 줄 {ci['rows']}, 서로 다른 chunk_sha256 {ci['distinct_chunk_sha256']}, 줄바꿈 {ci['eol']}, 결과 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
