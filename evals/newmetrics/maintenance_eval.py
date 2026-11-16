"""함께 볼 정책 후보 정밀도(SPEC 3장 "정밀도를 재서 공개", 요청 문서 4장). LLM 없음, 0원.

    python -m evals.newmetrics.maintenance_eval --gold evals/maintenance_gold.jsonl --out DIR [--source prod|index] [--revision REV]

시스템 후보 = 운영 코드 `find_candidates`(개정된 페이지를 링크하는 다른 페이지의 섹션, 최대 50개)를 운영 DB 읽기 전용 `PgLinks`(기본) 또는
로컬 색인으로 돌린 결과. 개정 두 건(219f7084 monthly-releases, ddd39597 expenses)마다 따로 돌린다. DB에 쓰지 않는다(후보 저장은 하지 않음).
정답 행(링크하는 페이지, 줄 번호들) -> 그 줄을 덮는 청크의 섹션 -> (rule_seq, 섹션). 후보와 같은 (rule_seq, 섹션)이면 그 행의 예/아니오가 후보의 정답.
- 정밀도 = 정답 "예"인 후보 / 정답이 있는 후보(애매 행은 빼고 따로 센다). 개정별 값과 합산을 낸다.
- 정답이 없는 후보(작성자가 적지 않은 섹션)는 목록으로 따로 적는다(정밀도 분모에 넣지 않음).
- 정답 "예" 행 중 후보에 없는 것(참고 재현율) = 시스템이 놓친 함께 볼 섹션.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from evals.newmetrics.common import check_rows, connect_ro, gold_meta, now_kst, page_rule_seq, read_jsonl, say, write_results
from evals.newmetrics.corpus_links import ChunkTable, from_db, from_index
from evals.newmetrics.spec_tables import MAINTENANCE_REVISIONS


def candidates_for(page: str, links) -> list[dict]:
    from backend.graph.recall.maintenance import find_candidates
    from backend.schemas.recall import ChangedArticle

    ch = ChangedArticle(rule_seq=page_rule_seq(page), article="(측정용)", old_version_date="", new_version_date="", change_type="modified")
    return find_candidates(ch, event_key="newmetrics-eval", links=links)


def gold_keys(rows: list[dict], table: ChunkTable) -> dict[tuple[int, str], list[dict]]:
    out: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in rows:
        seq = page_rule_seq(r["linking_page"])
        arts = {table.article_at(r["linking_page"], n) for n in r.get("lines") or []}
        r["system_articles"] = sorted(a for a in arts if a)
        for a in r["system_articles"]:
            out[(seq, a)].append(r)
    return out


def score_revision(cands: list[dict], rows: list[dict], table: ChunkTable) -> dict:
    keys = gold_keys(rows, table)
    labeled, unlabeled, ambiguous, conflict = [], [], [], []
    for c in cands:
        rs = keys.get((int(c["rule_seq"]), c["article"]), [])
        vals = {r["needed"] for r in rs if not r.get("ambiguous")}
        item = {"rule_seq": c["rule_seq"], "page": table.page_title(c["rule_seq"]), "article": c["article"], "gold_ids": [r["id"] for r in rs]}
        if not rs:
            unlabeled.append(item)
        elif not vals:
            ambiguous.append(item)
        elif len(vals) > 1:
            conflict.append(item)
        else:
            labeled.append({**item, "needed": vals.pop()})
    yes = sum(1 for x in labeled if x["needed"])
    cand_keys = {(int(c["rule_seq"]), c["article"]) for c in cands}
    gold_yes = [r for r in rows if r.get("needed") and not r.get("ambiguous")]
    found_yes = [r for r in gold_yes if any((page_rule_seq(r["linking_page"]), a) in cand_keys for a in r["system_articles"])]
    return {"candidates": len(cands), "limit_hit": len(cands) >= 50, "labeled": len(labeled), "yes": yes,
            "precision": round(yes / len(labeled), 4) if labeled else None,
            "unlabeled": unlabeled, "ambiguous": ambiguous, "conflict": conflict, "labeled_detail": labeled,
            "gold_yes": len(gold_yes), "gold_yes_found": len(found_yes),
            "coverage_of_yes": round(len(found_yes) / len(gold_yes), 4) if gold_yes else None,
            "gold_yes_missed": [{"id": r["id"], "page": r["linking_page"], "lines": r["lines"], "system_articles": r["system_articles"]}
                                for r in gold_yes if r not in found_yes]}


def render_md(s: dict) -> str:
    lines = [f"# 함께 볼 정책 후보 정밀도 ({s['started'][:10]})", "",
             f"시스템 쪽: {s['source']}" + (f" (운영 판 `{s['revision']}`)" if s.get("revision") else "") + f". 정답 `{s['gold']['file']}` {s['gold']['rows']}행, 애매 {s['ambiguous']}행 제외.", "",
             "| 개정 | 후보 | 정답 있는 후보 | 그중 예 | 정밀도 | 정답 없는 후보 | 정답 예 중 후보에 든 비율(참고) |", "|---|---|---|---|---|---|---|"]
    for k, x in s["per_revision"].items():
        lines.append(f"| {k} | {x['candidates']} | {x['labeled']} | {x['yes']} | {x['precision']} | {len(x['unlabeled'])} | {x['coverage_of_yes']} |")
    t = s["metrics"]
    lines.append(f"| 합산 | {t['candidates']} | {t['labeled']} | {t['yes']} | {t['precision']} | {t['unlabeled']} | {t['coverage_of_yes']} |")
    lines += ["", "정답 없는 후보와 놓친 섹션은 summary.json에 있다."]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="함께 볼 정책 후보 정밀도")
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", choices=("prod", "index"), default="prod")
    ap.add_argument("--revision", default="")
    a = ap.parse_args(argv)
    gold = read_jsonl(a.gold)
    check_rows("maintenance", gold)
    if a.source == "prod":
        from backend.graph.recall.maintenance import PgLinks

        conn = connect_ro()
        try:
            table = from_db(conn)
        finally:
            conn.close()
        links = PgLinks(connect=connect_ro)       # 운영 코드 그대로, 읽기 전용 세션
    else:
        table = from_index()
        links = table
    per = {}
    for author, rev in MAINTENANCE_REVISIONS.items():
        rows = [g for g in gold if g["revised_page"] == rev["page"]]
        per[f"{rev['commit']} {rev['page']}"] = score_revision(candidates_for(rev["page"], links), rows, table)
    tot_l = sum(x["labeled"] for x in per.values())
    tot_y = sum(x["yes"] for x in per.values())
    gy = sum(x["gold_yes"] for x in per.values())
    gf = sum(x["gold_yes_found"] for x in per.values())
    metrics = {"candidates": sum(x["candidates"] for x in per.values()), "labeled": tot_l, "yes": tot_y,
               "precision": round(tot_y / tot_l, 4) if tot_l else None, "unlabeled": sum(len(x["unlabeled"]) for x in per.values()),
               "coverage_of_yes": round(gf / gy, 4) if gy else None}
    s = {"metric": "maintenance_candidates", "started": now_kst(), "source": table.source if a.source == "index" else "prod-db (PgLinks)",
         "revision": a.revision, "gold": gold_meta(a.gold), "ambiguous": sum(1 for g in gold if g.get("ambiguous")), "metrics": metrics,
         "per_revision": per, "definition": "정밀도 = 정답 '예'인 후보 / 정답이 있는 후보"}
    write_results(a.out, s, render_md(s), [{**x, "revision": k} for k, v in per.items() for x in v["labeled_detail"]])
    say(f"함께 볼 정책 후보: 정밀도 {metrics['precision']} (예 {tot_y}/{tot_l}), 후보 {metrics['candidates']}, 정답 없는 후보 {metrics['unlabeled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
