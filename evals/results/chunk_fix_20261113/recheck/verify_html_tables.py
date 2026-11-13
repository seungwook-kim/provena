"""빈 줄이 든 HTML 표 10개가 요소(IR)에서 한 블록(표 행만)으로 읽히는지 이전/새 파싱 결과로 비교한다. (check_corpus.py 의 broken_html_tables.json 목록 기준)
사용: python -I verify_html_tables.py <broken_html_tables.json> <corpus폴더> <이전 document_ir.jsonl> <새 document_ir.jsonl> <출력.json>"""
import collections
import json
import sys
from pathlib import Path

bh = json.load(open(sys.argv[1], encoding="utf-8"))
corpus = Path(sys.argv[2])
pages = {("handbook/" + p["path"].replace("content/handbook/", "")): p["rule_seq"] for p in map(json.loads, open(corpus / "pages.jsonl", encoding="utf-8"))}


def load(p):
    d = collections.defaultdict(list)
    for l in open(p, encoding="utf-8"):
        e = json.loads(l)
        d[e["rule_seq"]].append(e)
    return d


old, new = load(sys.argv[3]), load(sys.argv[4])


def judge(els, a, b):
    inside = [e for e in els if e["line_start"] >= a and e["line_end"] <= b]       # 표 줄 범위 안에 통째로 들어간 요소
    kinds = collections.Counter(e["kind"] for e in inside)
    rows_whole = [e for e in els if e["kind"] == "table_row" and e["line_start"] <= a and e["line_end"] >= b]
    return {"elements_inside_range": dict(kinds), "table_rows_covering_whole_table": len(rows_whole)}


out = []
for it in bh["items"]:
    rs = pages[it["page"]]
    a, b = it["line_start"], it["line_end"]
    raw = (corpus / it["page"]).read_text(encoding="utf-8").split("\n")
    in_fence = any(l.lstrip().startswith("```") for l in raw[: a - 1]) and sum(1 for l in raw[: a - 1] if l.lstrip().startswith("```")) % 2 == 1
    o, n = judge(old[rs], a, b), judge(new[rs], a, b)
    out.append({"page": it["page"], "line_start": a, "line_end": b, "inside_code_fence": in_fence, "old": o, "new": n,
                "now_one_block": (n["table_rows_covering_whole_table"] > 0 and set(n["elements_inside_range"]) <= {"table_row"}) if not in_fence else None})
res = {"tables": len(out), "in_code_fence(건드리지 않음)": sum(1 for x in out if x["inside_code_fence"]),
       "one_block_now": sum(1 for x in out if x["now_one_block"]), "not_one_block": [x for x in out if x["now_one_block"] is False], "items": out}
Path(sys.argv[5]).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print({k: v for k, v in res.items() if k not in ("items",)})
