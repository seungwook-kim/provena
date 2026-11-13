"""보조 확인(0원): 문맥 같음, 넓힌 문항만의 비용, 새 문항 5건 값, 요약 파일과의 대조. 실행: python aux_checks.py <repo> <out>"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
REPO, OUT = sys.argv[1], sys.argv[2]
R = REPO + "/evals/results/"
res = json.load(open(OUT + "/result.json", encoding="utf-8"))
jl = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
d = [x for x in res["changed_rows_detail"] if x["id"] == 101 and x["rev"].endswith("wjn")]
print("101번 00047 첫 문맥: 1회차==3회차", d[0]["ctx"] == d[2]["ctx"], "/ 1회차==2회차", d[0]["ctx"] == d[1]["ctx"])
d4 = [x for x in res["changed_rows_detail"] if x["id"] == 104]
print("104번 두 리비전 6행의 서로 다른 첫 문맥 수:", len({tuple(x["ctx"]) for x in d4}))
for st, pre in [("v2", "deploy_latency_"), ("holdout", "deploy_latency_holdout_")]:
    ids = set(res["attribution"][st]["widened"]["ids"]); c = n = calls = 0
    for run in (1, 2, 3):
        for r in jl(R + f"{pre}provena-api-00047-wjn/run{run}/rows.jsonl"):
            if r["id"] in ids:
                c += r["cost_usd"]; n += 1; calls += r["llm_calls"]
    print(f"{st} 넓힌 문항 {len(ids)}개 x 3회 = {n}행: 비용 {c:.4f}달러(행당 {c / n:.5f}), LLM 호출 {calls}회, 문항 {sorted(ids)}")
for rev in ["00044-49s", "00047-wjn"]:
    g = json.load(open(R + f"deploy_latency_cite_new_provena-api-{rev}/citation_gold.json", encoding="utf-8"))
    o = {}
    for r in g["rows"]:
        o.setdefault(r["id"], []).append(f"{r['gold_hit']}/{r['gold_total']}+{r['cited_off_gold']}" if r["answered"] else "거절")
    emb = {}
    for run in (1, 2, 3):
        for r in jl(R + f"deploy_latency_cite_new_provena-api-{rev}/run{run}/rows.jsonl"):
            emb.setdefault(r["id"], []).append(r.get("embed_calls"))
    print("새 문항", rev, o, "임베딩 호출", emb)
rows = jl(R + "range_retrieval_62_7/answers_deploy_provena-api-00047-wjn/rows.jsonl")
print("금액 15건 00047: 비용", round(sum(r["cost_usd"] for r in rows), 4), "LLM 호출", sum(r["llm_calls"] for r in rows))
for rev in ["00044-49s", "00047-wjn"]:
    for st, pre in [("v2", "deploy_latency_"), ("holdout", "deploy_latency_holdout_")]:
        s = json.load(open(R + f"{pre}provena-api-{rev}/citation_gold.json", encoding="utf-8"))["summary"]
        pr = s["per_run"]
        print(rev, st, "요약 파일 정답 근거", [round(p["cited_correct_rate"], 4) for p in pr], "평균", round(sum(p["cited_correct_rate"] for p in pr) / 3, 4),
              "오답 근거 행", [p["wrong_citation_rows"] for p in pr], "과잉 거절", [round(p["over_refusal_rate"], 3) for p in pr])
# 넓히지 않은 문항(두 변경 모두 닿지 않음)의 행 단위 차이: 순수 회차 변동의 크기
for st in ("v2", "holdout"):
    t = [x for x in res["attribution"][st]["table"]]
    non = [x for x in t if not x["widened_rows_new"]]; wid = [x for x in t if x["widened_rows_new"]]
    rowdiff = lambda xs: sum(a != b for x in xs for a, b in zip(x["old"], x["new"]))
    print(st, "행 단위로 값이 다른 행: 넓히지 않은 문항", rowdiff(non), "/", len(non) * 3, ", 넓힌 문항", rowdiff(wid), "/", len(wid) * 3)
