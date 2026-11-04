"""링크 확장(L1x2) 재료: 청크마다 그 본문의 링크가 가리키는 코퍼스 안 다른 페이지(rule_seq) 목록 (docs/specs/search.md).

규칙은 확정 조합을 잰 측정 코드(evals/retrieval/exp_decompose_v1.py `Links`)와 같다.
  청크의 element_ids → 파싱 결과 요소의 links → 청크 주소 기준으로 urljoin → '#' 뒤를 떼고 끝 '/'를 뗌
  → manifest source_url(페이지 주소)로 rule_seq. 자기 페이지·코퍼스 밖 주소(비공개 internal.gitlab.com 포함)는 빠진다.
LLM을 부르지 않는다. 같은 입력이면 같은 결과(정렬한 목록).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urljoin


def norm(url: str) -> str:
    """'#' 뒤를 떼고 끝 '/'를 뗀다(측정 코드 `_norm`과 같다)."""
    return urldefrag(url)[0].rstrip("/")


def url_map(pages: Iterable[tuple[str, int]]) -> dict[str, int]:
    """(페이지 주소, rule_seq) 목록 → 정규화한 주소 → rule_seq."""
    return {norm(u): int(s) for u, s in pages}


def targets(chunk: dict, element_links: dict[str, list[str]], url2seq: dict[str, int]) -> list[int]:
    """청크 하나가 링크한 다른 페이지들. chunk에는 rule_seq·source_url·element_ids가 있어야 한다."""
    own = int(chunk["rule_seq"])
    out: set[int] = set()
    for e in chunk.get("element_ids") or []:
        for u in element_links.get(e, []):
            seq = url2seq.get(norm(urljoin(chunk["source_url"], u)))
            if seq is not None and seq != own:
                out.add(seq)
    return sorted(out)


def read_element_links(ir: Path) -> dict[str, list[str]]:
    """data/parsed/document_ir.jsonl → 요소 id → 링크 주소 목록."""
    out: dict[str, list[str]] = {}
    with ir.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out[d["element_id"]] = d.get("links") or []
    return out


def read_url_map(manifest: Path) -> dict[str, int]:
    """data/manifest.jsonl(문서 단위) → 정규화한 페이지 주소 → rule_seq(doc_id)."""
    pages = []
    with manifest.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                m = json.loads(line)
                pages.append((m["source_url"], m["doc_id"]))
    return url_map(pages)


def build(rows: list[dict], ir: Path, manifest: Path) -> list[list[int]]:
    """청크 행 순서대로 링크 대상 목록."""
    el, url2seq = read_element_links(ir), read_url_map(manifest)
    return [targets(r, el, url2seq) for r in rows]
