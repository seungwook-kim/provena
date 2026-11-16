"""00065-q84 행 기록으로 장치 하나만 되돌린 인용을 만들어 같은 채점(evals/latency/deploy_citation_gold.score_row)으로 다시 센다.

되돌림을 행 기록만으로 정확히 만들 수 있는 장치만 한다.
  head_owner (62.52·62.58, 이번 묶음에서 새로 들어감): 기록된 to 를 from 으로 되돌린다.
  partial_filter (62.66, 새로 들어감): 뺀 문장이 단 청크(chunks)를 인용에 되돌린다.
  best2_core (62.59, 새로 들어감): 고르지 않은 후보의 인용(best2.cands)으로 바꾼다(근거 확인 뒤 보정 전 값이라 근사).
  cite_add (인용 더하기 자체는 00047에도 있었음. 이번 묶음의 변경은 더하기를 '막는' 범위라 기록이 없다): 더한 청크를 빼 본 값은 참고로만 적는다.
채점 코드와 코퍼스 스냅샷은 citation_gold.json을 만든 것과 같다(data/index/chunks.jsonl, 저장소 코드 읽기 전용).
"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena"
sys.path.insert(0, REPO)
from pathlib import Path
from evals.latency import deploy_citation_gold as D

S = os.path.join(HERE, "src", "evals", "results")
OUT = os.path.join(HERE, "out", "effect_split_00047_00065")
corpus, meta, src = D.load_corpus(Path(REPO) / "data" / "index" / "chunks.jsonl")
by_id = {c.chunk_id: c for c in corpus}
SETS = {"v2": ("deploy_latency_provena-api-00065-q84", "dataset_v2.jsonl"),
        "holdout": ("deploy_latency_holdout_provena-api-00065-q84", "dataset_holdout_v1.jsonl"),
        "cite_new": ("deploy_latency_cite_new_provena-api-00065-q84", "dataset_cite_new_v1.jsonl")}

def sc(row, item, cited):
    r = dict(row); r["cited_chunk_ids"] = list(dict.fromkeys(cited))
    s = D.score_row(r, item, by_id)
    return s["gold_hit"], s["gold_total"], s["cited_off_gold"]

out = []
for sk, (d, dsf) in SETS.items():
    items = {it["id"]: it for it in D.load_dataset(Path(HERE) / "src" / "evals" / dsf)}
    gold = {(r["run"], r["id"]): r for r in json.load(open(os.path.join(S, d, "citation_gold.json"), encoding="utf-8"))["rows"]}
    for f in sorted(glob.glob(os.path.join(S, d, "run*", "rows.jsonl"))):
        for l in open(f, encoding="utf-8"):
            x = json.loads(l)
            if x.get("dataset_kind") != "relevant" or x.get("result") != "answer":
                continue
            item = items[x["id"]]; p = x.get("path") or {}; g = p.get("grounding") or {}
            cited = list(x.get("cited_chunk_ids") or [])
            actual = sc(x, item, cited)
            g0 = gold[(x["run"], x["id"])]
            assert actual == (g0["gold_hit"], g0["gold_total"], g0["cited_off_gold"]), (sk, x["id"], x["run"], actual)
            recs = []
            if g.get("head_owner"):
                cf = list(cited)
                for h in g["head_owner"]:
                    cf = [h["from"] if c == h["to"] else c for c in cf]
                recs.append(("head_owner", "62.52·62.58", cf))
            pf = g.get("partial_filter")
            if isinstance(pf, dict) and pf.get("result") == "dropped":
                recs.append(("partial_filter", "62.66", cited + list(pf.get("chunks") or [])))
            b = p.get("best2") or {}
            if "앞자리 인용끼리" in str(b.get("why") or "") and len(b.get("cands") or []) == 2:
                other = b["cands"][1 - int(b.get("pick", 1))]["cited"]
                recs.append(("best2_core", "62.59", other))
            adds = list(g.get("cite_expand") or []) + list(g.get("cite_phrase") or [])
            if adds:
                recs.append(("cite_add(참고: 00047에도 있던 더하기 자체)", "61.x", [c for c in cited if c not in adds]))
            for name, pre, cf in recs:
                c = sc(x, item, cf)
                out.append({"set": sk, "id": x["id"], "run": x["run"], "device": name, "prereg": pre,
                            "actual": f"{actual[0]}/{actual[1]}+{actual[2]}", "without_device": f"{c[0]}/{c[1]}+{c[2]}",
                            "gold_delta_row": (actual[0] - c[0]) / actual[1], "off_delta_row": actual[2] - c[2]})
json.dump(out, open(os.path.join(OUT, "counterfactual.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lines = ["| 묶음 | 문항 | 회차 | 장치 | 사전 등록 | 00065 실제 | 장치만 되돌린 인용 | 정답 위치 차(행) | 정답 밖 차(행) |", "|---|---|---|---|---|---|---|---|---|"]
for o in out:
    lines.append(f"| {o['set']} | {o['id']} | {o['run']} | {o['device']} | {o['prereg']} | {o['actual']} | {o['without_device']} | {o['gold_delta_row']:+.3f} | {o['off_delta_row']:+d} |")
open(os.path.join(OUT, "counterfactual.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
