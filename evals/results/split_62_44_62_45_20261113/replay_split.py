"""62.44(넓힌 첫 검색의 앞 5자리 우선)와 62.45(분해 전제 보존)의 단독 효과를 저장된 결과 파일만으로 가른다. LLM·임베딩·운영 호출 없음(0원).

실행(저장소 복사본 폴더에서, 저장소는 읽기만 한다):
    cd <a1_split>/repo_copy
    <repo>/.venv/Scripts/python.exe ../replay_split.py <repo> ../out

하는 일
A. 작용 범위(코드 재생): 평가셋 질문 전부에 저장소의 `keep_premise`, `has_dollar_amount`, `split_k`를 그대로 불러 적용한다.
   - 62.45는 `keep_premise`가 하위 질문을 바꿀 때만 작용한다. 질문이 한 문장이거나 앞 문장이 물음이면 하위 질문이 무엇이든 그대로 돌려준다(하위 질문 표본으로도 확인).
   - 62.44는 `split_k(question, subs) > SEARCH_K`일 때만 작용한다. 질문에 달러 금액이 있으면 하위 질문이 무엇이든 `SEARCH_K`다.
B. 행 귀속(v2 50건, 검증 20건 x 3회, 00044 대 00047): 저장된 첫 검색 문맥(`context.detail.json`)의 청크 수로 넓힌 행(8청크 이상)을 가리고,
   인용 청크가 문맥의 앞 5자리인지 넓힌 자리인지, 빠진 정답 위치가 문맥의 어느 자리였는지를 센다.
C. 금액 15건(00046 대 00047, 과거 리비전 포함): 거절 단계, 판정·근거 확인 호출 수, 임베딩 토큰 수.
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
RES = REPO / "evals" / "results"
sys.path.insert(0, str(Path.cwd()))  # 저장소 복사본(repo_copy)의 backend, evals를 불러온다

from backend.graph import build as B  # noqa: E402  (복사본의 코드)
from backend.graph import decompose as D  # noqa: E402
from evals.latency import deploy_citation_gold as CG  # noqa: E402
from evals.retrieval.run import load_dataset  # noqa: E402

OLD, NEW = "provena-api-00044-49s", "provena-api-00047-wjn"
SETS = {"v2": ("deploy_latency_", "dataset_v2.jsonl"), "holdout": ("deploy_latency_holdout_", "dataset_holdout_v1.jsonl"), "new": ("deploy_latency_cite_new_", "dataset_cite_new_v1.jsonl")}


def jl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


# ---------------------------------------------------------------- A. 작용 범위
def premise_gate(question: str) -> bool:
    """`keep_premise`가 하위 질문을 바꿀 수 있는 질문인가(코드의 앞 조건과 같은 식). False면 하위 질문이 무엇이든 그대로다."""
    sentences = [s.strip() for s in D._SENTENCE_SPLIT.split((question or "").strip()) if s.strip()]
    return len(sentences) >= 2 and not any(s.endswith(("?", "？")) for s in sentences[:-1])


def sample_subs(question: str) -> list[list[str]]:
    """하위 질문 표본: 질문을 쉼표·접속어·문장으로 자른 조각, 앞뒤 절반, 전제가 빠진 꼴. 실제 분해 결과가 아니라 불변 확인용이다."""
    words = question.split()
    half = max(1, len(words) // 2)
    pieces = [p.strip() for p in D._SENTENCE_SPLIT.split(question) if p.strip()]
    cuts = [[" ".join(words[:half]), " ".join(words[half:])], [words[0] + "?", words[-1] + "?"], ["무엇인가요?", "누구인가요?"], ["a", "b", "c"]]
    if len(pieces) >= 2:
        cuts.append(pieces[:3])
        cuts.append([pieces[-1], pieces[-1] + " 다시"])
    return [c for c in cuts if all(c)]


def scope() -> dict:
    files = {
        "v2": REPO / "evals/dataset_v2.jsonl", "holdout": REPO / "evals/dataset_holdout_v1.jsonl", "new": REPO / "evals/dataset_cite_new_v1.jsonl",
        "amount": RES / "range_retrieval_62_7/amount_questions.jsonl", "review": REPO / "evals/dataset_review_v1.jsonl",
    }
    out: dict = {}
    for name, path in files.items():
        items = jl(path)
        rows = []
        for it in items:
            q = it["input"]
            gate = premise_gate(q)
            dollar = B.has_dollar_amount(q, ())
            samples = sample_subs(q)
            changed = sum(D.keep_premise(q, s) != s for s in samples)  # gate가 False면 0이어야 한다
            k_values = sorted({B.split_k(q, s) for s in samples if len(s) >= 2})  # dollar가 True면 [5]여야 한다
            rows.append({"id": it["id"], "premise_gate": gate, "dollar": dollar, "samples": len(samples), "keep_premise_changed": changed, "split_k_values": k_values})
        out[name] = {
            "n": len(rows), "premise_gate": sum(r["premise_gate"] for r in rows), "dollar": sum(r["dollar"] for r in rows),
            "both_possible": sum(r["premise_gate"] and not r["dollar"] for r in rows),  # 두 규칙이 같은 질문에 함께 닿을 수 있는 질문
            "gate_false_but_changed": sum((not r["premise_gate"]) and r["keep_premise_changed"] > 0 for r in rows),
            "dollar_but_widened": sum(r["dollar"] and r["split_k_values"] != [B.SEARCH_K] for r in rows),
            "ids_premise_gate": [r["id"] for r in rows if r["premise_gate"]], "ids_dollar": [r["id"] for r in rows if r["dollar"]], "rows": rows,
        }
    return out


# ---------------------------------------------------------------- B. 행 귀속
def load_runs(prefix: str, rev: str) -> dict[tuple[int, int], dict]:
    return {(r["id"], run): r for run in (1, 2, 3) for r in jl(RES / f"{prefix}{rev}" / f"run{run}" / "rows.jsonl")}


def step_calls(row: dict, key: str) -> int:
    return int(((row.get("cost_by_step") or {}).get(key) or {}).get("calls") or 0)


def rows_view(corpus_by_id: dict) -> dict:
    """문항·회차별: 채점 값, 첫 검색 문맥 청크 수, 인용과 정답의 문맥 자리."""
    view: dict = {}
    for name in ("v2", "holdout"):
        prefix, ds = SETS[name]
        items = {it["id"]: it for it in load_dataset(REPO / "evals" / ds)}
        for rev in (OLD, NEW):
            scored = {(r["id"], r["run"]): r for r in json.load(open(RES / f"{prefix}{rev}" / "citation_gold.json", encoding="utf-8"))["rows"]}
            raw = load_runs(prefix, rev)
            ctx = {(d["id"], d["run"]): d for d in json.load(open(RES / f"failure_types_{rev}" / "context.detail.json", encoding="utf-8"))["rows"] if d["set"] == name}
            for (qid, run), s in scored.items():
                item, r, c = items[qid], raw[(qid, run)], ctx.get((qid, run))
                rec = {"kind": s["kind"], "result": s["result"], "answered": s["answered"], "gold_total": s["gold_total"], "gold_hit": s["gold_hit"] if s["answered"] else 0,
                       "off_gold": s["cited_off_gold"] if s["answered"] else 0, "refuse_stage": s.get("refuse_stage"), "refuse_reason": s.get("refuse_reason"),
                       "embed_calls": r.get("embed_calls"), "judge_calls": step_calls(r, "judge/judge"), "ground_calls": step_calls(r, "ground/grounding"),
                       "answer_calls": step_calls(r, "write_answer/answer") + step_calls(r, "write_answer/answer_fast"), "total_s": r.get("total_s"), "cited": s["cited"]}
                if c:
                    ids = c["chunk_ids"]
                    pos = {cid: i + 1 for i, cid in enumerate(ids)}
                    objs = [corpus_by_id.get(cid) or CG.stub_chunk(cid) for cid in ids]
                    gold_pos = [[i + 1 for i, o in enumerate(objs) if g.matches(o)] for g in item["gold"]]  # 정답 위치마다 문맥 안 자리(1부터)
                    cited_objs = [corpus_by_id.get(cid) or CG.stub_chunk(cid) for cid in s["cited"]]
                    gold_cited = [any(g.matches(o) for o in cited_objs) for g in item["gold"]]
                    rec.update({"n_chunks": c["n_chunks"], "n_search_obs": c["n_search_obs"], "ctx_differs": c.get("differs"), "ctx": ids,
                                "widened": c["n_chunks"] > B.SEARCH_K and (r.get("embed_calls") or 0) >= 3,
                                "cited_pos": [pos.get(cid) for cid in s["cited"]], "gold_pos": gold_pos, "gold_cited": gold_cited if s["answered"] else [False] * len(gold_pos)})
                view[(name, rev, qid, run)] = rec
    return view


def fmt_run(rec: dict) -> str:
    if not rec["answered"]:
        return "거절"
    return f"{rec['gold_hit']}/{rec['gold_total']}+{rec['off_gold']}"


def where(positions: list[int]) -> str:
    if not positions:
        return "문맥에 없음"
    return "앞 5자리" if min(positions) <= B.SEARCH_K else "넓힌 자리"


def attribute(view: dict) -> dict:
    out: dict = {}
    for name in ("v2", "holdout"):
        ids = sorted({q for (n, _, q, _) in view if n == name})
        rel = [q for q in ids if view[(name, NEW, q, 1)]["kind"] == "relevant"]
        table = []
        for q in rel:
            old = [view[(name, OLD, q, r)] for r in (1, 2, 3)]
            new = [view[(name, NEW, q, r)] for r in (1, 2, 3)]
            share = lambda recs: sum(x["gold_hit"] / x["gold_total"] for x in recs) / 3 / len(rel)  # 정답 근거 인용률(회차 평균)에 이 문항이 보태는 몫
            wid_old, wid_new = sum(bool(x.get("widened")) for x in old), sum(bool(x.get("widened")) for x in new)
            changed = sorted(fmt_run(x) for x in old) != sorted(fmt_run(x) for x in new)
            lost = []  # 00047에서 인용하지 않은 정답 위치가 그 회차 첫 문맥의 어느 자리였나
            for r, x in zip((1, 2, 3), new):
                for gi, (cited, gp) in enumerate(zip(x.get("gold_cited") or [], x.get("gold_pos") or [])):
                    if not cited:
                        lost.append({"run": r, "gold": gi + 1, "where": where(gp), "pos": gp})
            new_ext = sum(any(p and p > B.SEARCH_K for p in x.get("cited_pos") or []) for x in new if x["answered"])
            old_ext = sum(any(p and p > B.SEARCH_K for p in x.get("cited_pos") or []) for x in old if x["answered"])
            table.append({
                "id": q, "old": [fmt_run(x) for x in old], "new": [fmt_run(x) for x in new], "changed": changed,
                "delta_rate": share(new) - share(old), "widened_rows_old": wid_old, "widened_rows_new": wid_new,
                "n_chunks_old": [x.get("n_chunks") for x in old], "n_chunks_new": [x.get("n_chunks") for x in new],
                "same_first_ctx_set": sorted(map(tuple, (x.get("ctx") or [] for x in old))) == sorted(map(tuple, (x.get("ctx") or [] for x in new))),
                "rows_citing_widened_slot_old": old_ext, "rows_citing_widened_slot_new": new_ext, "lost_gold_new": lost,
                "ground_calls_old": [x["ground_calls"] for x in old], "ground_calls_new": [x["ground_calls"] for x in new],
                "refusals_new": [(r, x["refuse_stage"], x["refuse_reason"]) for r, x in zip((1, 2, 3), new) if not x["answered"]],
                "scope": "62.44 작용 범위(넓힌 첫 검색)" if wid_new else "두 변경 모두 닿지 않음(넓히지 않은 질문)",
            })
        rate = lambda rev: [sum(view[(name, rev, q, r)]["gold_hit"] / view[(name, rev, q, r)]["gold_total"] for q in rel) / len(rel) for r in (1, 2, 3)]
        g = lambda rows, key: sum(t[key] for t in rows)
        wid = [t for t in table if t["widened_rows_new"]]
        non = [t for t in table if not t["widened_rows_new"]]
        irrelevant_changed = [q for q in ids if q not in rel and sorted(view[(name, OLD, q, r)]["result"] for r in (1, 2, 3)) != sorted(view[(name, NEW, q, r)]["result"] for r in (1, 2, 3))]
        out[name] = {
            "n_relevant": len(rel), "rate_old_runs": rate(OLD), "rate_new_runs": rate(NEW), "rate_old": sum(rate(OLD)) / 3, "rate_new": sum(rate(NEW)) / 3,
            "widened": {"questions": len(wid), "changed_questions": sum(t["changed"] for t in wid), "delta_rate": g(wid, "delta_rate"), "ids": [t["id"] for t in wid]},
            "not_widened": {"questions": len(non), "changed_questions": sum(t["changed"] for t in non), "delta_rate": g(non, "delta_rate"), "ids": [t["id"] for t in non]},
            "widened_rows": {"old": g(table, "widened_rows_old"), "new": g(table, "widened_rows_new")},
            "irrelevant_result_changed": irrelevant_changed, "table": table,
        }
    return out


def history(name: str) -> dict:
    """같은 문항의 리비전별 회차 값(변동 폭 참고). 저장된 citation_gold.json만 읽는다."""
    prefix, _ = SETS[name]
    out: dict = defaultdict(dict)
    for folder in sorted(RES.glob(f"{prefix}provena-api-*")):
        if name == "v2" and "holdout" in folder.name or "cite_new" in folder.name and name != "new":
            continue
        cg = folder / "citation_gold.json"
        if not cg.exists():
            continue
        rev = folder.name.split("provena-api-")[1]
        for r in json.load(open(cg, encoding="utf-8"))["rows"]:
            if r["kind"] == "relevant":
                out[r["id"]].setdefault(rev, {})[r["run"]] = f"{r['gold_hit']}/{r['gold_total']}+{r['cited_off_gold']}" if r["answered"] else "거절"
    return {q: {rev: [runs.get(i) for i in (1, 2, 3)] for rev, runs in revs.items()} for q, revs in out.items()}


# ---------------------------------------------------------------- C. 금액 15건
def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """2x2 표 [[a, b], [c, d]]의 양쪽 Fisher 정확 검정 p."""
    n, r1, c1 = a + b + c + d, a + b, a + c
    p = lambda x: math.comb(c1, x) * math.comb(n - c1, r1 - x) / math.comb(n, r1)
    p0 = p(a)
    return min(1.0, sum(p(x) for x in range(max(0, r1 - (n - c1)), min(r1, c1) + 1) if p(x) <= p0 + 1e-12))


def amount() -> dict:
    out: dict = {"revisions": {}}
    base = RES / "range_retrieval_62_7"
    for folder in sorted(base.glob("answers_deploy_provena-api-*")):
        rev = folder.name.split("provena-api-")[1]
        rows = jl(folder / "rows.jsonl")
        recs = []
        for r in rows:
            calls = r.get("embed_calls") or 0
            recs.append({"id": r["id"], "repeat": r["repeat"], "kind": r["kind"], "refuse_stage": r.get("refuse_stage"), "refuse_reason": r.get("refuse_reason"),
                         "llm_calls": r.get("llm_calls"), "judge_calls": step_calls(r, "judge/judge"), "ground_calls": step_calls(r, "ground/grounding"),
                         "embed_tokens": r.get("embed_tokens"), "embed_calls": calls,
                         "tokens_per_search": round(r["embed_tokens"] * 3 / calls, 1) if calls and r.get("embed_tokens") is not None else None,  # 검색 1번(질문 + 하위 질문 2개 = 3호출)으로 환산
                         "total_s": r.get("total_s"), "gold_cited_auto": r.get("gold_cited_auto")})
        tok = sorted(x["tokens_per_search"] for x in recs if x["tokens_per_search"] is not None and x["embed_calls"] == 3)
        out["revisions"][rev] = {
            "n": len(recs), "answers": sum(x["kind"] == "answer" for x in recs), "refusals": sum(x["kind"] != "answer" for x in recs),
            "refuse_stages": dict(Counter(f"{x['refuse_stage']}/{x['refuse_reason']}" for x in recs if x["kind"] != "answer")),
            "refused_rows": [(x["id"], x["repeat"]) for x in recs if x["kind"] != "answer"], "requery_rows_judge5plus": sum(x["judge_calls"] >= 5 for x in recs),
            "over_10s": sum((x["total_s"] or 0) > 10 for x in recs),
            "tokens_3call_rows": tok, "tokens_3call_min_median_max": [tok[0], tok[len(tok) // 2], tok[-1]] if tok else None, "rows": recs,
        }
    revs = out["revisions"]
    a, b = revs["00046-qkx"], revs["00047-wjn"]
    out["fisher_refusal_00046_vs_00047"] = fisher_two_sided(a["refusals"], a["answers"], b["refusals"], b["answers"])
    key = lambda x: (x["id"], x["repeat"])
    old = {key(x): x for x in a["rows"]}
    out["changed_rows_00046_to_00047"] = [{"id": x["id"], "repeat": x["repeat"], "old": old[key(x)]["kind"], "new": x["kind"], "new_stage": x["refuse_stage"], "old_stage": old[key(x)]["refuse_stage"],
                                           "tokens_old": old[key(x)]["tokens_per_search"], "tokens_new": x["tokens_per_search"], "embed_calls_old": old[key(x)]["embed_calls"], "embed_calls_new": x["embed_calls"],
                                           "judge_old": old[key(x)]["judge_calls"], "judge_new": x["judge_calls"]} for x in b["rows"] if x["kind"] != old[key(x)]["kind"]]
    # 문항별 거절 이력: 62.45가 없던 리비전에서도 같은 문항이 같은 단계로 거절했는가
    hist: dict = defaultdict(dict)
    for rev, v in revs.items():
        for x in v["rows"]:
            hist[x["id"]].setdefault(rev, []).append("답" if x["kind"] == "answer" else f"거절({x['refuse_stage']}/{x['refuse_reason']})")
    out["history_by_question"] = hist
    pre = [x for rev, v in revs.items() if rev != "00047-wjn" for x in v["rows"]]
    out["pre_62_45_all_revisions"] = {"rows": len(pre), "refusals": sum(x["kind"] != "answer" for x in pre),
                                     "ground_unsupported": sum(x["kind"] != "answer" and x["refuse_stage"] == "ground" for x in pre)}
    return out


def main() -> None:
    sc = scope()
    corpus, _, _ = CG.load_corpus(REPO / "data/index/chunks.jsonl")
    by_id = {c.chunk_id: c for c in corpus}
    view = rows_view(by_id)
    att = attribute(view)
    res = {"constants": {"SEARCH_K": B.SEARCH_K, "SPLIT_K": B.SPLIT_K}, "scope": sc, "attribution": att,
           "history": {"holdout": history("holdout"), "v2": history("v2")}, "amount": amount()}
    (OUT / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    L: list[str] = ["# 재생 출력 (replay_split.py, 0원)", "", "## A. 작용 범위", "",
                    "| 질문 모음 | 문항 | 62.45가 닿을 수 있음(물음이 아닌 앞 문장) | 달러 금액 있음(62.44가 닿지 않음) | 둘 다 닿을 수 있음 | 앞 조건 거짓인데 하위 질문이 바뀜 | 달러인데 넓혀짐 |", "|---|---|---|---|---|---|---|"]
    for name, v in sc.items():
        L.append(f"| {name} | {v['n']} | {v['premise_gate']} | {v['dollar']} | {v['both_possible']} | {v['gate_false_but_changed']} | {v['dollar_but_widened']} |")
    for name in ("v2", "holdout"):
        a = att[name]
        L += ["", f"## B. {name} 관련 {a['n_relevant']}문항 (00044 → 00047)", "",
              f"- 정답 근거 인용률: {a['rate_old']:.4f} → {a['rate_new']:.4f} (회차 {', '.join(f'{x:.3f}' for x in a['rate_old_runs'])} → {', '.join(f'{x:.3f}' for x in a['rate_new_runs'])}), 차 {a['rate_new'] - a['rate_old']:+.4f}",
              f"- 넓힌 문항(62.44 작용 범위) {a['widened']['questions']}문항: 값이 바뀐 문항 {a['widened']['changed_questions']}, 인용률 몫 {a['widened']['delta_rate']:+.4f}",
              f"- 넓히지 않은 문항(두 변경 모두 닿지 않음) {a['not_widened']['questions']}문항: 값이 바뀐 문항 {a['not_widened']['changed_questions']}, 인용률 몫 {a['not_widened']['delta_rate']:+.4f}",
              f"- 넓힌 행 수: 00044 {a['widened_rows']['old']}행, 00047 {a['widened_rows']['new']}행. 비관련 문항 가운데 결과가 바뀐 문항: {a['irrelevant_result_changed'] or '없음'}", "",
              "| 문항 | 00044 (정답/전체+정답 밖) | 00047 | 인용률 몫 | 첫 문맥 청크 수 00044 → 00047 | 첫 문맥 같음 | 넓힌 자리를 인용한 행 00044 → 00047 | 00047에서 빠진 정답 위치의 문맥 자리 | 범위 |", "|---|---|---|---|---|---|---|---|---|"]
        for t in a["table"]:
            lost = "; ".join(f"{x['run']}회차 정답{x['gold']}: {x['where']}{x['pos'] or ''}" for x in t["lost_gold_new"]) or "-"
            mark = "**" if t["changed"] else ""
            L.append(f"| {mark}{t['id']}{mark} | {', '.join(t['old'])} | {', '.join(t['new'])} | {t['delta_rate']:+.4f} | {t['n_chunks_old']} → {t['n_chunks_new']} | {'예' if t['same_first_ctx_set'] else '아니오'} | "
                     f"{t['rows_citing_widened_slot_old']} → {t['rows_citing_widened_slot_new']} | {lost} | {t['scope']} |")
    L += ["", "## B-3. 값이 바뀐 문항의 행별 자리(인용 청크의 첫 문맥 자리, 정답 위치의 첫 문맥 자리. 자리 6 이상이 넓힌 자리, None은 첫 문맥 밖)", "",
          "| 모음 | 문항 | 리비전 | 회차 | 값 | 첫 문맥 청크 수 | 인용 청크의 자리 | 정답 위치별 자리 | 인용 청크 | 근거 확인 호출 | 답 작성 호출 | 거절 단계 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    detail = []
    for name in ("v2", "holdout"):
        for t in att[name]["table"]:
            if not t["changed"] and t["id"] not in (105, 108):
                continue
            for rev in (OLD, NEW):
                for r in (1, 2, 3):
                    x = view[(name, rev, t["id"], r)]
                    detail.append({"set": name, "id": t["id"], "rev": rev, "run": r, **{k: x.get(k) for k in ("n_chunks", "cited_pos", "gold_pos", "cited", "ground_calls", "answer_calls", "refuse_stage", "refuse_reason", "ctx")}, "value": fmt_run(x)})
                    L.append(f"| {name} | {t['id']} | {rev[-9:]} | {r} | {fmt_run(x)} | {x.get('n_chunks')} | {x.get('cited_pos')} | {x.get('gold_pos')} | {', '.join(c[:8] for c in x['cited'])} | {x['ground_calls']} | {x['answer_calls']} | {x.get('refuse_stage') or '-'} |")
    res["changed_rows_detail"] = detail
    (OUT / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    hist_v2 = res["history"]["v2"]
    L += ["", "## B-4. v2 3·6·38·39번의 리비전별 값", ""]
    for q in (3, 6, 38, 39):
        L.append(f"- {q}번: " + " / ".join(f"{rev}: {', '.join(str(v) for v in vals)}" for rev, vals in sorted(hist_v2.get(q, {}).items())))
    L += ["", "## B-2. 검증 문항의 리비전별 값(같은 문항의 회차 변동)", "", "| 문항 | " + " | ".join(sorted({rev for v in res['history']['holdout'].values() for rev in v})) + " |",
          "|---|" + "---|" * len({rev for v in res['history']['holdout'].values() for rev in v})]
    revs_h = sorted({rev for v in res["history"]["holdout"].values() for rev in v})
    for q, v in sorted(res["history"]["holdout"].items()):
        L.append(f"| {q} | " + " | ".join(", ".join(str(x) for x in v.get(rev, [])) for rev in revs_h) + " |")
    am = res["amount"]
    L += ["", "## C. 금액 15건", "", "| 리비전 | 답 | 거절 | 거절 단계 | 거절 행(문항, 회차) | 판정 5회 이상 행 | 10초 초과 행 | 검색 1번의 임베딩 토큰(최소, 중앙, 최대) |", "|---|---|---|---|---|---|---|---|"]
    for rev, v in am["revisions"].items():
        L.append(f"| {rev} | {v['answers']} | {v['refusals']} | {v['refuse_stages'] or '-'} | {v['refused_rows'] or '-'} | {v['requery_rows_judge5plus']} | {v['over_10s']} | {v['tokens_3call_min_median_max']} |")
    L += ["", f"- 00046 대 00047 거절 수 Fisher 정확 검정(양쪽) p = {am['fisher_refusal_00046_vs_00047']:.3f}",
          f"- 62.45가 없던 리비전 전체: {am['pre_62_45_all_revisions']}", "", "바뀐 행(00046 → 00047):", ""]
    for x in am["changed_rows_00046_to_00047"]:
        L.append(f"- {x['id']}번 {x['repeat']}회차: {x['old']}({x['old_stage']}) → {x['new']}({x['new_stage']}), 검색 1번 토큰 {x['tokens_old']} → {x['tokens_new']}, 임베딩 호출 {x['embed_calls_old']} → {x['embed_calls_new']}, 판정 호출 {x['judge_old']} → {x['judge_new']}")
    L += ["", "문항별 이력:", ""]
    for q, v in sorted(am["history_by_question"].items()):
        L.append(f"- {q}번: " + " / ".join(f"{rev}: {', '.join(vals)}" for rev, vals in v.items()))
    (OUT / "tables.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
