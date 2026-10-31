"""적재: 지금은 manifest(G3 증거)만. 임베딩·DB 적재는 B-4에서 이 파일에 더한다.

python -m backend.rag.ingest.load --manifest      (chunk.py 를 먼저 돌려야 한다)
출력(커밋 대상): data/manifest.jsonl(문서 단위), data/chunks_index.jsonl(청크 번호·위치·지문, 본문 없음)
형식: data/README.md. chars_kept 는 청크 본문 글자 합(겹침·머리말 제외)이라 Hugo 표시·front matter를 지운 만큼
chars_original 보다 대체로 작다(예외 2쪽: 표 행 글자에 열 이름이 붙어 더 큼). 길이로 자른 적은 없어서 truncated 는 모두 false.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from importlib.metadata import version
from pathlib import Path

from backend.rag.ingest.handbook import AUTHZ_PATH, rule_seq


def build_manifest(corpus: Path, chunks_dir: Path, data: Path) -> dict:
    chunks = [json.loads(line) for line in (chunks_dir / "chunks.jsonl").open(encoding="utf-8")]
    by_doc = collections.defaultdict(list)
    for c in chunks:
        by_doc[c["rule_seq"]].append(c)
    collect = json.loads((corpus / "collect_manifest.json").read_text(encoding="utf-8"))
    parser = f"markdown-it-py {version('markdown-it-py')} + beautifulsoup4 {version('beautifulsoup4')}"

    docs = [json.loads(line) for line in (corpus / "pages.jsonl").open(encoding="utf-8")]
    authz = collect["authz"]
    docs.append({"rule_seq": rule_seq(AUTHZ_PATH), "path": AUTHZ_PATH, "org": "finance", "title": "Authorization Matrix (2023-05)",
                 "source_url": authz["source_url"], "version_id": authz["commit"][:12], "fetched_at": collect["collected_at"],
                 "chars": len((corpus / "authz/authorization-matrix-2023-05.html.md").read_text(encoding="utf-8")),
                 "redirect_to": None})
    rows = []
    for d in docs:
        cs = by_doc.get(d["rule_seq"], [])
        rows.append({"doc_id": d["rule_seq"], "path": d["path"], "org": d["org"], "title": d["title"],
                     "source_url": d["source_url"], "version_id": d["version_id"], "collected_at": d["fetched_at"],
                     "parser": parser, "chunks": len(cs), "chars_original": d["chars"],
                     "chars_kept": sum(c["body_chars"] for c in cs), "truncated": False,
                     "skipped": "redirect" if d["redirect_to"] else ("no_body" if not cs else None)})
    if sum(r["chunks"] for r in rows) != len(chunks):
        raise RuntimeError("manifest 청크 수 합이 청크 파일과 다름")

    with (data / "manifest.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (data / "chunks_index.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            f.write(json.dumps({"chunk_id": c["chunk_id"], "doc_id": c["rule_seq"], "seq": c["seq"], "kind": c["kind"],
                                "line_start": c["line_start"], "line_end": c["line_end"],
                                "chunk_sha256": c["body_sha256"], "body_chars": c["body_chars"]}) + "\n")
    back = [json.loads(line) for line in (data / "manifest.jsonl").open(encoding="utf-8")]   # 저장 성공 ≠ 재사용 가능
    if len(back) != len(rows) or sum(r["chunks"] for r in back) != len(chunks):
        raise RuntimeError("다시 읽은 manifest 가 다름")
    return {"docs": len(rows), "docs_with_chunks": sum(1 for r in rows if r["chunks"]),
            "chunks": len(chunks), "unique_chunk_sha256": len({c["body_sha256"] for c in chunks}),
            "skipped": collections.Counter(r["skipped"] for r in rows if r["skipped"])}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", action="store_true", required=True)
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ap.add_argument("--chunks", type=Path, default=Path("data/chunks"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    a = ap.parse_args()
    r = build_manifest(a.corpus, a.chunks, a.data)
    print(f"문서 {r['docs']}(청크 있는 문서 {r['docs_with_chunks']}), 청크 {r['chunks']}, "
          f"서로 다른 chunk_sha256 {r['unique_chunk_sha256']}, 건너뜀 {dict(r['skipped'])}")


if __name__ == "__main__":
    main()
