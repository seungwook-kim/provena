"""나뉜 질문의 첫 검색 끝 1자리 규칙(`FULL_TAIL`, 사전 등록 62.38)이 평가셋에서 얼마나 쓰였는지 0원으로 센다 (체크포인트 3조 코멘트 ③, 2026-11-13).

규칙: 나뉜 질문(하위 질문 2개 이상, 달러 금액 없음)의 첫 검색은 k=8이고, 하위 질문과 링크 확장으로 7자리를 채운 뒤
끝 1자리(문맥의 8번째, 색인 7)만 원 질문 후보 목록의 아직 없는 앞 청크로 채운다(`docs/specs/search.md` 27행, `docs/specs/question-graph.md` 178행).

입력(모두 저장소에 있는 측정 결과, LLM·키·네트워크 없음):
  - `evals/results/failure_types_<리비전>/context.detail.json`: 운영 Langfuse에서 받은 행별 첫 검색 문맥(청크 id 순서 그대로)
  - `evals/results/deploy_latency_<리비전>/`, `deploy_latency_holdout_<리비전>/`의 `run1~3/rows.jsonl`과 `citation_gold.json`
  - `evals/dataset_v2.jsonl`, `evals/dataset_holdout_v1.jsonl`(정답 위치), `data/index/chunks.jsonl`(청크, 압축을 푼 색인)

센 것:
  1. 규칙이 작동한 행: 첫 검색 문맥이 8청크 이상인 행. k=5 검색은 도입부 절을 최대 2개 붙여도 7청크 이하라 이 기준이 k=8 검색과 같다.
     8번째 청크가 끝 1자리인 것은 도입부 절(R3)이 문맥 뒤에 붙고 검색기가 정확히 k=8을 돌려주기 때문이다(`backend/rag/retrieve/search.py`, `backend/graph/build.py` `with_intro`).
  2. 끝 자리 청크가 정답 위치에 맞는 행, 그리고 끝 자리 청크 때문에만 정답 위치 수가 늘어난 행(끝 자리를 빼면 문맥의 정답 위치 수가 줄어듦).
  3. 끝 자리 청크를 답이 인용한 행.
  4. 끝 자리 청크의 인용을 뺐을 때의 정답 근거 인용률 하한(관련 문항 행). 답이 달라질 수 있으므로 예측이 아니라 이 측정 행에서 끝 자리 인용을 지운 값이다.
  이 규칙을 끈 상태로 따로 잰 적은 없다. 그래서 위 숫자는 "규칙이 이 행들에서 한 일"의 상한과 하한이지 켠 것과 끈 것의 비교 실험이 아니다.

사용: python evals/results/tail_slot_rule_20261113/analyze_tail_slot.py   (결과는 같은 폴더의 result.json, report.md)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from evals.retrieval import run as R  # noqa: E402

RES = ROOT / "evals" / "results"
OUT = Path(__file__).resolve().parent
REVS = ["provena-api-" + s for s in ("00044-49s", "00047-wjn")]  # Cloud Run 리비전 이름(비밀값 아님)
SETS = {"v2": ROOT / "evals" / "dataset_v2.jsonl", "holdout": ROOT / "evals" / "dataset_holdout_v1.jsonl"}
DIRS = {"v2": "deploy_latency_{}", "holdout": "deploy_latency_holdout_{}"}
LABEL = {"v2": "v2", "holdout": "검증"}
TAIL = 7  # 8번째 자리(색인 7)가 끝 1자리
K_SPLIT = 8


def main() -> int:
    corpus = {c.chunk_id: c for c in R.load_chunks(ROOT / "data" / "index" / "chunks.jsonl")}
    ds = {s: {x["id"]: x for x in R.load_dataset(p)} for s, p in SETS.items()}
    result: dict = {}
    for rev in REVS:
        det = json.loads((RES / f"failure_types_{rev}" / "context.detail.json").read_text(encoding="utf-8"))["rows"]
        rows, cg = {}, {}
        for s in SETS:
            d = RES / DIRS[s].format(rev)
            for n in (1, 2, 3):
                for line in (d / f"run{n}" / "rows.jsonl").read_text(encoding="utf-8").splitlines():
                    r = json.loads(line)
                    rows[(s, r["id"], n)] = r
            for r in json.loads((d / "citation_gold.json").read_text(encoding="utf-8"))["rows"]:
                cg[(s, r["id"], r["run"])] = r

        fired = [d for d in det if (d.get("n_chunks") or 0) >= K_SPLIT]
        stat: Counter = Counter()
        per: list[dict] = []
        for d in fired:
            key = (d["set"], d["id"], d["run"])
            gold = ds[d["set"]][d["id"]]["gold"]
            ids = d["chunk_ids"]
            objs = [corpus.get(c) for c in ids]
            stat["missing_chunks"] += sum(o is None for o in objs)

            def hits(skip=None):
                return sum(any(o is not None and g.matches(o) for j, o in enumerate(objs) if j != skip) for g in gold)

            h_all, h_wo = hits(), hits(TAIL)
            tail_gold = objs[TAIL] is not None and any(g.matches(objs[TAIL]) for g in gold)
            tail_cited = ids[TAIL] in (rows[key].get("cited_chunk_ids") or [])
            stat["rows"] += 1
            stat[f"rows_{d['set']}"] += 1
            stat["gold_total"] += len(gold)
            stat["gold_in_context_all8plus"] += h_all
            stat["gold_in_context_without_tail"] += h_wo
            stat["tail_is_gold"] += tail_gold
            stat["tail_sole_gold_rows"] += h_all > h_wo
            stat["tail_cited_rows"] += tail_cited
            stat["recorded_hit_mismatch"] += h_all != d["hit"]
            if tail_gold or h_all > h_wo or tail_cited:
                per.append({"set": LABEL[d["set"]], "id": d["id"], "run": d["run"], "context_chunks": d["n_chunks"], "gold": len(gold),
                            "gold_in_context": h_all, "gold_in_context_without_tail": h_wo, "tail_chunk": ids[TAIL],
                            "tail_section": " > ".join(objs[TAIL].article) if objs[TAIL] is not None and not isinstance(objs[TAIL].article, str) else getattr(objs[TAIL], "article", None),
                            "tail_is_gold": tail_gold, "tail_cited": tail_cited})
        nonfired = [d for d in det if (d.get("n_chunks") or 0) < K_SPLIT]
        questions = {s: sorted({d["id"] for d in fired if d["set"] == s}) for s in SETS}

        # 정답 근거 인용률(관련 문항 행): 실제 값과, 끝 자리 청크가 문맥에 있던 행에서 그 청크의 인용을 지운 하한
        tail_of = {(d["set"], d["id"], d["run"]): d["chunk_ids"][TAIL] for d in fired}
        rate: dict = {}
        for s in SETS:
            rel = [r for (ss, _, _), r in cg.items() if ss == s and r["kind"] == "relevant"]
            act, low, changed = [], [], []
            for r in sorted(rel, key=lambda x: (x["id"], x["run"])):
                g = ds[s][r["id"]]["gold"]
                cited = r.get("cited") or []
                objs = [corpus.get(c) for c in cited]

                def gh(skip=None):
                    return sum(any(o is not None and gg.matches(o) for c, o in zip(cited, objs) if c != skip) for gg in g)

                a = gh()
                t = tail_of.get((s, r["id"], r["run"]))
                b = gh(t) if t else a
                if a != r.get("gold_hit"):
                    stat["citation_gold_mismatch"] += 1
                act.append(a / len(g))
                low.append(b / len(g))
                if a != b:
                    changed.append({"id": r["id"], "run": r["run"], "gold_cited": a, "gold_cited_without_tail": b, "gold": len(g)})
            n = len(rel)
            rate[s] = {"relevant_rows": n, "gold_cited_rate": round(sum(act) / n, 4), "gold_cited_rate_without_tail_citation": round(sum(low) / n, 4), "changed_rows": changed}
        result[rev] = {"context_rows": len(det), "fired_rows": len(fired), "fired_questions": questions, "nonfired_rows": len(nonfired),
                       "stat": dict(stat), "rows_with_tail_effect": per, "citation_rate": rate}

    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    write_report(result)
    for rev, v in result.items():
        s = v["stat"]
        print(f"{rev}: 규칙 작동 행 {v['fired_rows']}/{v['context_rows']}, 끝 자리 청크가 정답 위치인 행 {s['tail_is_gold']}, 끝 자리 때문에만 정답 위치가 는 행 {s['tail_sole_gold_rows']}, "
              f"끝 자리 청크를 인용한 행 {s['tail_cited_rows']}, 기록과 어긋난 행 {s['recorded_hit_mismatch']}, 청크 못 찾음 {s['missing_chunks']}")
        for st, r in v["citation_rate"].items():
            print(f"   {LABEL[st]} 관련 {r['relevant_rows']}행: 정답 근거 인용률 {r['gold_cited_rate']} -> 끝 자리 인용을 뺀 하한 {r['gold_cited_rate_without_tail_citation']}")
    return 0


def write_report(result: dict) -> None:
    L = ["# 끝 1자리 규칙의 평가셋 근거 (0원 계산, 2026-11-13)", "",
         "규칙과 계산 방법은 `analyze_tail_slot.py` 머리말에 있다. 규칙을 끈 상태로 따로 잰 적은 없으므로 아래는 켠 상태의 측정 행에서 끝 자리가 한 일을 센 값이다.", "",
         "| 리비전 | 문맥을 받은 행 | 규칙이 작동한 행(문맥 8청크 이상) | 작동한 문항(v2 / 검증) | 끝 자리 청크가 정답 위치인 행 | 끝 자리 때문에만 문맥의 정답 위치 수가 는 행 | 끝 자리 청크를 답이 인용한 행 |", "|---|---|---|---|---|---|---|"]
    for rev, v in result.items():
        s = v["stat"]
        q = v["fired_questions"]
        L.append(f"| `{rev}` | {v['context_rows']} | {v['fired_rows']} (v2 {s.get('rows_v2', 0)}, 검증 {s.get('rows_holdout', 0)}) | {len(q['v2'])} / {len(q['holdout'])} | {s['tail_is_gold']} | {s['tail_sole_gold_rows']} | {s['tail_cited_rows']} |")
    L += ["", "문맥 안 정답 위치 수(작동한 행의 정답 위치 합 %d개 중):" % list(result.values())[0]["stat"]["gold_total"], "",
          "| 리비전 | 8청크 전체 | 끝 자리를 뺀 7청크 |", "|---|---|---|"]
    for rev, v in result.items():
        s = v["stat"]
        L.append(f"| `{rev}` | {s['gold_in_context_all8plus']} | {s['gold_in_context_without_tail']} |")
    L += ["", "정답 근거 인용률(관련 문항 행, 문항별 정답 위치 중 인용한 비율의 평균). 하한은 끝 자리 청크가 문맥에 있던 행에서 그 청크의 인용을 지운 값이다.", "",
          "| 리비전 | 평가셋 | 관련 행 | 실제 | 끝 자리 인용을 뺀 하한 | 값이 바뀌는 행(문항 번호, 회차) |", "|---|---|---|---|---|---|"]
    for rev, v in result.items():
        for st, r in v["citation_rate"].items():
            ch = ", ".join(f"{c['id']}번 {c['run']}회" for c in r["changed_rows"]) or "없음"
            L.append(f"| `{rev}` | {LABEL[st]} | {r['relevant_rows']} | {r['gold_cited_rate']:.4f} | {r['gold_cited_rate_without_tail_citation']:.4f} | {ch} |")
    L += ["", "끝 자리 청크가 정답 위치이거나, 답이 인용했거나, 끝 자리 때문에만 정답 위치 수가 는 행:", "",
          "| 리비전 | 평가셋 | 문항 | 회차 | 문맥 청크 | 정답 위치 수 | 문맥의 정답 위치(8청크 / 끝 자리 뺌) | 끝 자리 청크가 정답 위치 | 끝 자리 청크 인용 | 끝 자리 청크의 절 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for rev, v in result.items():
        for p in v["rows_with_tail_effect"]:
            L.append(f"| `{rev}` | {p['set']} | {p['id']} | {p['run']} | {p['context_chunks']} | {p['gold']} | {p['gold_in_context']} / {p['gold_in_context_without_tail']} | {'예' if p['tail_is_gold'] else '아니오'} | {'예' if p['tail_cited'] else '아니오'} | {p['tail_section']} |")
    L += ["", "읽는 법과 한계:",
          "- 이 규칙의 설계 근거는 평가셋이 아니라 데모 질문 하나다(`backend/rag/retrieve/search.py` 주석). 평가셋에서는 끝 1자리를 원 질문 목록에 두는 방식과 첫 목록으로 두는 방식을 가르지 못했다(사전 등록 62.38). 이 표는 규칙을 정한 뒤에 켠 상태의 운영 행에서 끝 자리가 한 일을 센 값이고, 규칙이 옳다는 증명이 아니다.",
          "- 끝 자리 청크가 원 질문 목록에서 왔는지, 새 청크가 없어 하위 질문 목록의 다음 청크로 채워졌는지는 문맥 기록에 없다(검색기를 다시 돌리면 질문 임베딩 호출이 든다). 그래서 \"끝 자리\"는 문맥의 8번째 청크를 뜻한다.",
          "- 하한은 끝 자리 인용을 지운 값이다. 끝 자리가 없었다면 답이 다른 청크를 인용했을 수 있으므로 실제로 잃을 값의 예측이 아니다.",
          "- 3회 반복 행이고 정답 위치 수가 문항마다 1~3이라 1~3행 차이는 개선이나 효과로 읽지 않는다.",
          "- 검증 20건은 동결 목록 밖이며 결과를 본 뒤 고친 문항이 있어 값이 낙관적일 수 있다(EVAL_REPORT 2장)."]
    (OUT / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
