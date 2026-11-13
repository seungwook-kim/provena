"""표본 크기 확인(0원): 바뀐 값이 회차 변동과 구별되는지 Fisher 정확 검정(양쪽)으로 본다. 입력은 out/result.json. 실행: python stats.py <out>"""
import json, math, sys
sys.stdout.reconfigure(encoding="utf-8")
res = json.load(open(sys.argv[1] + "/result.json", encoding="utf-8"))
def fisher(a, b, c, d):
    n, r1, c1 = a + b + c + d, a + b, a + c
    p = lambda x: math.comb(c1, x) * math.comb(n - c1, r1 - x) / math.comb(n, r1)
    return min(1.0, sum(p(x) for x in range(max(0, r1 - (n - c1)), min(r1, c1) + 1) if p(x) <= p(a) + 1e-12))
H, V = res["history"]["holdout"], res["history"]["v2"]
full = lambda v: v and v != "거절" and v.split("+")[0].split("/")[0] == v.split("+")[0].split("/")[1] and v.endswith("+0")
def count(hist, q, revs, pred):
    vals = [v for rev in revs for v in hist[str(q)].get(rev, []) if v is not None]
    return sum(bool(pred(v)) for v in vals), len(vals)
PRE = ["00032-zhs", "00035-h69", "00037-2jt", "00044-49s"]
k, n = count(V, 3, ["00044-49s"], full); k2, n2 = count(V, 3, ["00047-wjn"], full)
k6, n6 = count(V, 6, ["00044-49s"], full); k62, n62 = count(V, 6, ["00047-wjn"], full)
print(f"v2 3번 정답 2/2+0 행: 00044 {k}/{n} -> 00047 {k2}/{n2}, p={fisher(k, n - k, k2, n2 - k2):.3f}")
print(f"v2 6번 정답 2/2+0 행: 00044 {k6}/{n6} -> 00047 {k62}/{n62}, p={fisher(k6, n6 - k6, k62, n62 - k62):.3f}")
print(f"v2 3번+6번 합: 00044 {k + k6}/{n + n6} -> 00047 {k2 + k62}/{n2 + n62}, p={fisher(k + k6, n + n6 - k - k6, k2 + k62, n2 + n62 - k2 - k62):.4f}")
r, n = count(H, 101, PRE, lambda v: v == "거절"); r2, n2 = count(H, 101, ["00047-wjn"], lambda v: v == "거절")
print(f"검증 101번 거절 행: 62.44 앞 리비전 4개 {r}/{n} -> 00047 {r2}/{n2}, p={fisher(r, n - r, r2, n2 - r2):.3f}")
r, n = count(H, 101, ["00044-49s"], lambda v: v == "거절")
print(f"검증 101번 거절 행: 00044만 {r}/{n} -> 00047 {r2}/{n2}, p={fisher(r, n - r, r2, n2 - r2):.3f}")
b, n = count(H, 104, PRE, lambda v: not full(v)); b2, n2 = count(H, 104, ["00047-wjn"], lambda v: not full(v))
print(f"검증 104번 정답 2/2+0이 아닌 행: 62.44 앞 리비전 4개 {b}/{n} -> 00047 {b2}/{n2}, p={fisher(b, n - b, b2, n2 - b2):.3f}")
b, n = count(H, 104, ["00044-49s"], lambda v: not full(v))
print(f"검증 104번 정답 2/2+0이 아닌 행: 00044만 {b}/{n} -> 00047 {b2}/{n2}, p={fisher(b, n - b, b2, n2 - b2):.3f}")
a, b = res["amount"]["revisions"]["00046-qkx"], res["amount"]["revisions"]["00047-wjn"]
for label, key in [("거절", "refusals"), ("판정 5회 이상(재검색)", "requery_rows_judge5plus"), ("10초 초과", "over_10s")]:
    print(f"금액 15건 {label} 행: 00046 {a[key]}/15 -> 00047 {b[key]}/15, p={fisher(a[key], 15 - a[key], b[key], 15 - b[key]):.3f}")
pre = res["amount"]["pre_62_45_all_revisions"]
print("금액 62.45 앞 리비전 전체 거절:", pre)
