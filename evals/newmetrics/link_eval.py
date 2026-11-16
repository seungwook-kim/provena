"""링크 추출 정확도(SPEC 3장 링크 추출 행 "정확도를 재서 공개", 요청 문서 3장). LLM 없음, 0원.

    python -m evals.newmetrics.link_eval --gold evals/link_gold.jsonl --out DIR [--source prod|index] [--revision REV]

시스템 간선 = 맡은 6개 페이지의 현재 판 청크마다 (출발 페이지, 섹션, link_targets의 대상 페이지). 운영 DB 읽기 전용(기본) 또는 로컬 색인.
정답 간선 = 정답 행 중 대상이 코퍼스 경로인 것(코퍼스 밖·자기 페이지·비공개 행은 시스템이 간선을 만들면 안 되는 링크라 정답 간선이 아니다)의
(출발 페이지, 그 줄의 섹션, 대상 페이지). 정답은 페이지의 핸드북 링크를 빠짐없이 적은 것이라(요청 문서 3-2) 정밀도와 재현율을 모두 낸다.
- 섹션 단위(기본): 정밀도 = 맞은 간선 / 시스템 간선, 재현율 = 맞은 간선 / 정답 간선, F1. SPEC의 "정확도"는 이 F1과 두 값을 함께 공개한다.
- 페이지 단위(참고): (출발 페이지, 대상 페이지) 쌍으로 같은 계산.
- 행 단위(참고): 정답 링크 행마다 시스템이 그 간선을 가졌는지(같은 간선의 여러 줄은 각각 센다).
정답의 "애매" 행의 간선은 양쪽에서 빼고 따로 센다(시스템이 그 간선을 내도 틀림으로 세지 않는다).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.newmetrics.common import check_rows, connect_ro, gold_meta, now_kst, prf, read_jsonl, say, write_results
from evals.newmetrics.corpus_links import ChunkTable, from_db, from_index
from evals.newmetrics.spec_tables import LINK_PAGES, LINK_SPECIAL


def gold_edges(gold: list[dict], table: ChunkTable) -> tuple[set, set, list[dict]]:
    sure, unsure, rows = set(), set(), []
    for g in gold:
        art = table.article_at(g["source_page"], g.get("line"))
        t = g.get("target")
        edge = None if t in LINK_SPECIAL or t == g["source_page"] else (g["source_page"], art, t)
        rows.append({**g, "system_article": art, "edge": list(edge) if edge else None})
        if edge:
            (unsure if g.get("ambiguous") else sure).add(edge)
    return sure - unsure, unsure, rows


def score(gold: list[dict], table: ChunkTable, pages: list[str] | None = None) -> dict:
    pages = pages or sorted({g["source_page"] for g in gold})
    gold_set, unsure, rows = gold_edges(gold, table)
    sys_all = table.edges(pages)
    sys_set = {e for e in sys_all if e not in unsure}
    tp = len(sys_set & gold_set)
    section = prf(tp, len(sys_set - gold_set), len(gold_set - sys_set))
    gp = {(s, t) for s, _a, t in gold_set}
    sp = {(s, t) for s, _a, t in sys_set}
    up = {(s, t) for s, _a, t in unsure} - gp
    sp -= up
    page = prf(len(sp & gp), len(sp - gp), len(gp - sp))
    for r in rows:
        r["system_has_edge"] = None if r["edge"] is None else tuple(r["edge"]) in sys_all
    linked = [r for r in rows if r["edge"] is not None and not r.get("ambiguous")]
    special = [r for r in rows if r["edge"] is None]
    per_page = {}
    for p in pages:
        g = {e for e in gold_set if e[0] == p}
        s = {e for e in sys_set if e[0] == p}
        per_page[p] = prf(len(g & s), len(s - g), len(g - s))
    return {"section": section, "page": page,
            "row_recall": round(sum(r["system_has_edge"] for r in linked) / len(linked), 4) if linked else None,
            "rows": len(rows), "rows_corpus_target": len(linked), "rows_special": len(special),
            "rows_special_by_kind": {k: sum(1 for r in special if r.get("target") == k) for k in LINK_SPECIAL},
            "ambiguous_edges": len(unsure), "per_page": per_page,
            "false_positive_edges": sorted([list(e) for e in sys_set - gold_set], key=str),
            "missed_edges": sorted([list(e) for e in gold_set - sys_set], key=str), "row_detail": rows}


def render_md(s: dict) -> str:
    m = s["metrics"]
    lines = [f"# 링크 추출 정확도 ({s['started'][:10]})", "",
             f"시스템 쪽: {s['source']}" + (f" (운영 판 `{s['revision']}`)" if s.get("revision") else "") + f". 정답 `{s['gold']['file']}` {s['gold']['rows']}행, 애매 간선 {m['ambiguous_edges']}개 제외.", "",
             "| 단위 | 정밀도 | 재현율 | F1 | 맞음 / 시스템만 / 정답만 |", "|---|---|---|---|---|"]
    for k, name in (("section", "섹션 간선(기본)"), ("page", "페이지 쌍(참고)")):
        x = m[k]
        lines.append(f"| {name} | {x['precision']} | {x['recall']} | {x['f1']} | {x['tp']} / {x['fp']} / {x['fn']} |")
    lines += ["", f"정답 링크 행 중 시스템이 간선을 가진 비율(행 단위): {m['row_recall']} ({m['rows_corpus_target']}행). "
              f"코퍼스 밖·자기 페이지·비공개 행 {m['rows_special']}개({m['rows_special_by_kind']})는 간선이 없어야 하는 링크라 정답 간선에 넣지 않았다.", "",
              "| 페이지 | 정밀도 | 재현율 | F1 |", "|---|---|---|---|"]
    for p, x in m["per_page"].items():
        lines.append(f"| `{p}` | {x['precision']} | {x['recall']} | {x['f1']} |")
    lines += ["", "틀린 간선(시스템만, 정답만)은 summary.json의 false_positive_edges, missed_edges에 있다."]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="링크 추출 정확도")
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", choices=("prod", "index"), default="prod")
    ap.add_argument("--revision", default="")
    a = ap.parse_args(argv)
    gold = read_jsonl(a.gold)
    check_rows("link", gold)
    if a.source == "prod":
        conn = connect_ro()
        try:
            table = from_db(conn)
        finally:
            conn.close()
    else:
        table = from_index()
    pages = [p for ps in LINK_PAGES.values() for p in ps]
    m = score(gold, table, [p for p in pages if any(g["source_page"] == p for g in gold)] or pages)
    detail = m.pop("row_detail")
    s = {"metric": "link_extraction", "started": now_kst(), "source": table.source, "revision": a.revision, "gold": gold_meta(a.gold),
         "ambiguous": sum(1 for g in gold if g.get("ambiguous")), "metrics": m,
         "definition": "섹션 간선 (출발 페이지, 섹션, 대상 페이지) 기준 정밀도·재현율·F1, 대상이 코퍼스 경로인 정답 행만 간선"}
    write_results(a.out, s, render_md(s), detail)
    say(f"링크 추출: 섹션 정밀도 {m['section']['precision']} 재현율 {m['section']['recall']} F1 {m['section']['f1']} ({table.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
