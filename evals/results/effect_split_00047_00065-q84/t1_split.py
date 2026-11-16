"""00047-wjn -> 00065-q84 묶음의 장치별 효과 가르기 (0원, 저장된 결과만 읽음).

입력(모두 origin/main 의 커밋된 파일):
  evals/results/deploy_latency{,_holdout,_cite_new}_provena-api-000{47-wjn,65-q84}/run*/rows.jsonl, citation_gold.json
  evals/results/chunk_fix_20261113/changed_chunks.json, gold_impact.json (결정 0115 청크 수정의 영향)
방법:
  1) 00065 행의 실행 기록(path)에서 장치마다 '실제로 발동했는지'를 행 단위로 읽는다(아래 DEVICES).
  2) 문항별로 00047과 00065의 정답 근거(gold_hit/gold_total), 정답 밖 인용 수, 거절을 3회씩 비교한다.
  3) 문항을 '발동한 답 경로 장치의 집합'으로 묶는다. 답 경로 장치가 하나도 발동하지 않은 문항 묶음이 대조군이다.
     어떤 장치가 그 문항 묶음에만 닿으면(다른 장치와 겹치지 않으면) 그 묶음의 변화는 그 장치 또는 회차 변동의 몫이다(62.44/62.45 가르기와 같은 방식).
한계: 00047 행에는 실행 기록(path)이 없어 발동 여부는 00065 쪽에서만 읽는다. 막는 쪽 장치(62.56/62.57 범위, 62.70 K)는 막았을 때 기록이 남지 않는다.
"""
import glob, json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, "src", "evals", "results")
OUT = os.path.join(HERE, "out", "effect_split_00047_00065")
os.makedirs(OUT, exist_ok=True)

SETS = {
    "v2": ("deploy_latency_provena-api-00047-wjn", "deploy_latency_provena-api-00065-q84", "dataset_v2.jsonl", "v2 50"),
    "holdout": ("deploy_latency_holdout_provena-api-00047-wjn", "deploy_latency_holdout_provena-api-00065-q84", "dataset_holdout_v1.jsonl", "검증 20"),
    "cite_new": ("deploy_latency_cite_new_provena-api-00047-wjn", "deploy_latency_cite_new_provena-api-00065-q84", "dataset_cite_new_v1.jsonl", "새 문항 5(인용)"),
}

def rows(d):
    out = []
    for f in sorted(glob.glob(os.path.join(S, d, "run*", "rows.jsonl"))):
        out += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    return out

def gold_rows(d):
    p = os.path.join(S, d, "citation_gold.json")
    if not os.path.exists(p):
        return None
    return {(r["run"], r["id"]): r for r in json.load(open(p, encoding="utf-8"))["rows"]}

DOLLAR = re.compile(r"\$\s?\d|\d\s?(달러|USD)", re.I)

# 장치: (표시 이름, 사전 등록, 답 경로를 바꿀 수 있는가, 행 판정 함수)
def f_split(p): return len(p.get("sub_queries") or []) >= 2
DEVICES = [
    ("intro_core", "62.51 넓힌 첫 검색 앞자리에 도입부 청크 포함", True,
     lambda x, p, g: f_split(p) and bool(p.get("intro_chunk_ids"))),
    ("page_fill", "62.55 나뉜 질문 첫 검색의 같은 페이지 보충", True,
     lambda x, p, g: bool((p.get("search_stats") or {}).get("page_fill"))),
    ("head_owner", "62.52·62.58(+62.70 L·M) 겹친 머리 인용 바로잡기", True,
     lambda x, p, g: bool(g.get("head_owner"))),
    ("cite_add", "62.56·62.57(+62.70 K) 인용 더하기·문장 공유 더하기의 범위", True,
     lambda x, p, g: bool(g.get("cite_expand")) or bool(g.get("cite_phrase"))),
    ("best2_core", "62.59 앞자리 인용끼리 판정 구절 청크 수로 후보 고르기", True,
     lambda x, p, g: "앞자리 인용끼리" in str((p.get("best2") or {}).get("why") or "")),
    ("adopt", "62.68 근거 확인 실패 뒤 받쳐진 다른 후보 쓰기", True,
     lambda x, p, g: bool(g.get("switched_to")) or any(c.get("adopted") for c in g.get("candidates") or []) or bool(g.get("switch_failed"))),
    ("partial", "62.63 일부 판정은 재검색 없이 일부 답 / 62.66 일부 답 문장 빼기", True,
     lambda x, p, g: bool(g.get("partial_route")) or bool(g.get("partial_filter"))),
    ("redraft", "62.67 다시 쓴 답의 일부 답 안내 조건(다시 쓰기 경로)", True,
     lambda x, p, g: bool(g.get("redraft")) or bool(g.get("redrafted")) or bool(g.get("revised"))),
    ("retry_ground", "62.49 재검색 뒤 근거 확인 미리 시작(재검색 행)", False,
     lambda x, p, g: (p.get("retries") or 0) > 0),
    ("early_search", "62.53·62.64 원 질문 첫 검색 일찍 시작·결과 재사용", False,
     lambda x, p, g: (p.get("search_stats") or {}).get("cache_hits", 0) > 0),
    ("none_capped", "62.72 근거 없음 두 표 뒤 셋째 표 1.0초까지만", False,
     lambda x, p, g: any(v.get("how") == "none_capped" for v in p.get("judge_votes") or [])),
]
# 62.67 프롬프트 캐시(모든 LLM 행, 메시지·답 경로 같음), 62.50·62.65 값 뒤집기 탐지(뒤집기 낱말이 든 청크만), 62.72 버린 미리 돌리기 근거 확인 생략(답 후보에 쓰지 않는 쪽)은 행 기록으로 가르지 않는다.

impact = json.load(open(os.path.join(HERE, "src", "gold_impact.json"), encoding="utf-8-sig"))
changed = json.load(open(os.path.join(HERE, "src", "changed_chunks.json"), encoding="utf-8-sig"))
changed_ids = {c["chunk_id"] for c in changed["changed"]}
gold_touch = collections.defaultdict(bool)
for d in impact["detail"]:
    if d.get("touched_changed_chunk"):
        gold_touch[(d["set"], d["id"])] = True

def q_stats(gr, ids, runs=(1, 2, 3)):
    out = {}
    for q in ids:
        cells = []
        for r in runs:
            x = gr.get((r, q))
            if x is None:
                cells.append(None); continue
            if not x.get("answered"):
                cells.append(("R", x.get("gold_total"), 0))
            else:
                cells.append((x.get("gold_hit"), x.get("gold_total"), x.get("cited_off_gold")))
        out[q] = cells
    return out

def cell_str(c):
    if c is None: return "-"
    if c[0] == "R": return f"거절(0/{c[1]})"
    return f"{c[0]}/{c[1]}+{c[2]}"

def rate(cells):
    v = [(0 if c[0] == "R" else c[0]) / c[1] for c in cells if c and c[1]]
    return sum(v) / len(v) if v else None

result = {"sets": {}, "devices": [(k, n, a) for k, n, a, _ in DEVICES]}
md = []
for sk, (d47, d65, dsf, impact_set) in SETS.items():
    ds = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(HERE, "src", "evals", dsf), encoding="utf-8") if l.strip()}
    rel = [i for i, q in ds.items() if q.get("kind") == "relevant"]
    g47, g65 = gold_rows(d47), gold_rows(d65)
    r65 = {(x["run"], x["id"]): x for x in rows(d65)}
    s47, s65 = q_stats(g47, rel), q_stats(g65, rel)
    nrel = len(rel)
    per_q = []
    for q in rel:
        fired = collections.Counter(); ctx_changed = False
        for r in (1, 2, 3):
            x = r65.get((r, q))
            if not x: continue
            p = x.get("path") or {}; g = p.get("grounding") or {}
            for k, n, a, fn in DEVICES:
                try:
                    if fn(x, p, g): fired[k] += 1
                except Exception:
                    pass
            if set(p.get("context_ids") or []) & changed_ids or set(x.get("cited_chunk_ids") or []) & changed_ids:
                ctx_changed = True
        split_runs = sum(1 for r in (1, 2, 3) if f_split(((r65.get((r, q)) or {}).get("path") or {})))
        a47, a65 = rate(s47[q]), rate(s65[q])
        off47 = sum(c[2] for c in s47[q] if c and c[0] != "R"); off65 = sum(c[2] for c in s65[q] if c and c[0] != "R")
        ref47 = sum(1 for c in s47[q] if c and c[0] == "R"); ref65 = sum(1 for c in s65[q] if c and c[0] == "R")
        answer_dev = sorted(k for k, n, a, _ in DEVICES if a and fired[k])
        per_q.append({
            "id": q, "dollar": bool(DOLLAR.search(ds[q]["input"])), "split_runs_00065": split_runs,
            "fired": dict(fired), "answer_path_devices": answer_dev,
            "corpus_fix_touches_gold": gold_touch[(impact_set, q)], "corpus_fix_in_context": ctx_changed,
            "c47": [cell_str(c) for c in s47[q]], "c65": [cell_str(c) for c in s65[q]],
            "rate47": a47, "rate65": a65, "contrib": (a65 - a47) / nrel,
            "off47": off47, "off65": off65, "ref47": ref47, "ref65": ref65,
        })
    tot47 = sum(p["rate47"] for p in per_q) / nrel; tot65 = sum(p["rate65"] for p in per_q) / nrel
    # 묶음별 합
    groups = collections.defaultdict(list)
    for p in per_q:
        groups[tuple(p["answer_path_devices"]) or ("(답 경로 장치 발동 없음)",)].append(p)
    result["sets"][sk] = {"n_relevant": nrel, "gold_rate_00047": tot47, "gold_rate_00065": tot65, "per_question": per_q,
                          "groups": {"+".join(k): {"ids": [p["id"] for p in v], "contrib": sum(p["contrib"] for p in v),
                                                    "changed_ids": [p["id"] for p in v if abs(p["rate65"] - p["rate47"]) > 1e-9 or p["off47"] != p["off65"] or p["ref47"] != p["ref65"]]}
                                     for k, v in groups.items()}}
    md.append(f"\n## {sk} (관련 {nrel}문항): 정답 근거 인용률 00047 {tot47:.3f} → 00065 {tot65:.3f} ({tot65 - tot47:+.3f})\n")
    md.append("| 문항 | 00065에서 발동한 답 경로 장치(3회 중 발동 회차) | 속도·기록 장치 | 나뉜 회차 | 청크 수정(결정 0115)이 정답에 닿음 | 00047 (정답 위치/전체+정답 밖) | 00065 | 몫 | 정답 밖 인용 47→65 | 거절 47→65 |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for p in per_q:
        ad = ", ".join(f"{k}({p['fired'][k]})" for k in p["answer_path_devices"]) or "없음"
        sd = ", ".join(f"{k}({v})" for k, v in p["fired"].items() if k not in p["answer_path_devices"]) or "없음"
        md.append(f"| {p['id']} | {ad} | {sd} | {p['split_runs_00065']}/3 | {'예' if p['corpus_fix_touches_gold'] else '아니오'} | {', '.join(p['c47'])} | {', '.join(p['c65'])} | {p['contrib']:+.4f} | {p['off47']}→{p['off65']} | {p['ref47']}→{p['ref65']} |")
    md.append("\n묶음(발동한 답 경로 장치 집합)별 합:\n")
    md.append("| 장치 집합 | 문항 | 바뀐 문항 | 정답 근거 몫 합 |")
    md.append("|---|---|---|---|")
    for k, v in sorted(result["sets"][sk]["groups"].items(), key=lambda kv: kv[0]):
        md.append(f"| {k} | {', '.join(map(str, v['ids']))} | {', '.join(map(str, v['changed_ids'])) or '없음'} | {v['contrib']:+.4f} |")

# 장치별 닿은 문항 표
md2 = ["| 장치 | 사전 등록 | 답 경로를 바꿀 수 있나 | 닿는 조건(코드) | 00065에서 발동한 문항(v2) | (검증) | (새 문항) |", "|---|---|---|---|---|---|---|"]
COND = {
    "intro_core": "하위 질문 2개 이상(달러 금액 없음)이고 도입부 채우기 청크가 있을 때 첫 검색만",
    "page_fill": "하위 질문 2개 이상(달러 금액 없음)의 첫 검색",
    "head_owner": "근거 구절이 인용 청크의 겹친 머리에만 있을 때",
    "cite_add": "근거 확인 뒤 코드가 인용을 더할 때(막은 경우는 기록 없음)",
    "best2_core": "넓힌 문맥에서 판정 구절이 모두 앞자리일 때 둘째 후보 선택",
    "adopt": "고른 답의 근거 확인이 실패했을 때",
    "partial": "판정이 일부일 때",
    "redraft": "근거 확인 실패 뒤 다시 쓰기",
    "retry_ground": "재검색이 있었을 때(시간만)",
    "early_search": "예비 분해가 안 나눔이고 정책 경로일 때(입력 같음, 시간만)",
    "none_capped": "판정 첫 두 표가 모두 근거 없음일 때(시간만)",
}
for k, n, a, _ in DEVICES:
    cols = []
    for sk in SETS:
        ids = [str(p["id"]) for p in result["sets"][sk]["per_question"] if p["fired"].get(k)]
        cols.append(", ".join(ids) or "없음")
    m = re.match(r"^([\d.·]+(?:\(\+62\.70 [A-Z·]+\))?)\s+(.*)$", n)
    pre, name = m.group(1), m.group(2)
    md2.append(f"| {name} | {pre} | {'예' if a else '아니오(시간)'} | {COND[k]} | {cols[0]} | {cols[1]} | {cols[2]} |")

json.dump(result, open(os.path.join(OUT, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(os.path.join(OUT, "tables.md"), "w", encoding="utf-8").write("# 장치별 닿는 문항\n\n" + "\n".join(md2) + "\n\n# 문항별 변화\n" + "\n".join(md) + "\n")
for sk in SETS:
    s = result["sets"][sk]
    print(sk, round(s["gold_rate_00047"], 4), round(s["gold_rate_00065"], 4))
    for k, v in s["groups"].items():
        print("  ", k, v["ids"], "changed", v["changed_ids"], round(v["contrib"], 4))
