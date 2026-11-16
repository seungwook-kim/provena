"""00047 행의 정답 밖 인용이 62.56 (가) 조건(인용한 다른 청크와 같은 페이지·같은 절 제목)에 맞는지 본다(0원).
00047 행에는 실행 기록이 없어 그 인용이 '코드가 더한 것'인지는 알 수 없다. 조건에 맞는지만 적는다."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena"
sys.path.insert(0, REPO)
from pathlib import Path
from evals.latency import deploy_citation_gold as D
corpus, meta, src = D.load_corpus(Path(REPO) / "data" / "index" / "chunks.jsonl")
by_id = {c.chunk_id: c for c in corpus}
S = os.path.join(HERE, "src", "evals", "results")
res = []
for d, ids in (("deploy_latency_holdout_provena-api-00047-wjn", (105, 107)), ("deploy_latency_cite_new_provena-api-00047-wjn", (301, 304)),
               ("deploy_latency_holdout_provena-api-00065-q84", (109,)), ("deploy_latency_cite_new_provena-api-00065-q84", (305,))):
    g = json.load(open(os.path.join(S, d, "citation_gold.json"), encoding="utf-8"))["rows"]
    for r in g:
        if r["id"] not in ids or not r.get("cited_off_gold"):
            continue
        on = [c for c, f in zip(r["cited"], r["cited_gold_flags"]) if f]
        for c, f in zip(r["cited"], r["cited_gold_flags"]):
            if f: continue
            o = by_id.get(c)
            same = [x for x in on if by_id.get(x) and o and by_id[x].rule_seq == o.rule_seq and by_id[x].article == o.article]
            same_page = [x for x in on if by_id.get(x) and o and by_id[x].rule_seq == o.rule_seq]
            res.append({"dir": d, "id": r["id"], "run": r["run"], "off_chunk": c, "found": bool(o),
                        "same_page_same_section_as_gold_cite": bool(same), "same_page_as_gold_cite": bool(same_page),
                        "title": getattr(o, "title", None), "article": getattr(o, "article", None),
                        "is_table_row": bool(o and " | " in (o.text or ""))})
for x in res: print(json.dumps(x, ensure_ascii=False))
json.dump(res, open(os.path.join(HERE, "out", "effect_split_00047_00065", "offgold_condition.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
