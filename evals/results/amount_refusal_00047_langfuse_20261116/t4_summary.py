"""금액 15건(00047-wjn) Langfuse 관측 요약: 회차별 판정 구절 청크, 답 초안의 단서 문장 여부, 근거 확인 판정과 사유, 결과.
질문 원문·답 전문은 저장하지 않고, 판정 사유와 단서 문장 여부만 남긴다(사유 문장은 근거 확인 LLM 출력의 reason 칸)."""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "out", "amount_lf", "obs_private.json"), encoding="utf-8"))
tm, per = D["trace_map"], D["obs"]
CAVEAT = re.compile(r"(SaaS[^.]{0,40}(적용|해당|확인)|확인되지 않|확인하지 않|확인 필요|확정할 수 없)")
rows = []
for tid, t in sorted(tm.items(), key=lambda kv: (kv[1]["id"], kv[1]["repeat"])):
    obs = sorted(per[tid], key=lambda o: o["start"])
    def first(name):
        for o in obs:
            if o["name"] == name:
                v = o["output"]
                try: return json.loads(v) if isinstance(v, str) else v
                except Exception: return v
        return None
    judge = first("judge") or {}; ground = first("ground") or {}; wa = first("write_answer") or {}
    draft = (wa.get("answer") if isinstance(wa, dict) else "") or ""
    g = ground.get("grounding") or {} if isinstance(ground, dict) else {}
    verdicts = []
    for o in obs:
        if o["name"] == "TaskEffortAnthropic":
            inp = json.dumps(o["input"], ensure_ascii=False)
            m = re.search(r"\[\[task:([a-z_]+)\]\]", inp)
            if m and m.group(1).startswith("grounding"):
                try:
                    c = json.loads(json.loads(o["output"])["content"] if isinstance(o["output"], str) else o["output"]["content"])
                    verdicts.append({"grounded": c.get("grounded"), "reason_code": c.get("reason_code"), "reason": c.get("reason")})
                except Exception as e:
                    verdicts.append({"parse_error": str(e)[:60]})
    rows.append({"id": t["id"], "repeat": t["repeat"], "trace": tid[:12],
                 "result": (ground.get("kind") or "answer") if isinstance(ground, dict) else None,
                 "refuse_reason": ground.get("refuse_reason") if isinstance(ground, dict) else None,
                 "judge_quote_ids": judge.get("judge_quote_ids") if isinstance(judge, dict) else None,
                 "draft_has_caveat": bool(CAVEAT.search(draft)), "draft_caveat_spans": [m.group(0) for m in CAVEAT.finditer(draft)][:3],
                 "ground_llm_final": g.get("llm"), "redraft": (g.get("redraft") or {}).get("result"), "revise": (g.get("revise") or {}).get("result"),
                 "ground_detail": g.get("detail"), "n_grounding_calls": len(verdicts),
                 "grounding_verdicts": [(v.get("grounded"), v.get("reason_code")) for v in verdicts]})
json.dump(rows, open(os.path.join(HERE, "out", "amount_lf", "amount_00047_grounding.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lines = ["| 문항 | 회차 | 결과 | 판정 구절 청크 | 답 초안의 단서 문장 | 근거 확인 최종 | 다시 쓰기 / 문장 빼기 | 근거 확인 호출 판정(받쳐짐, 사유 코드) |", "|---|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r['id']} | {r['repeat']} | {r['result']}{'/' + r['refuse_reason'] if r['refuse_reason'] else ''} | {', '.join(r['judge_quote_ids'] or [])} | {'있음: ' + ' / '.join(r['draft_caveat_spans']) if r['draft_has_caveat'] else '없음'} | {r['ground_llm_final']} | {r['redraft']} / {r['revise']} | {'; '.join(f'{a},{b}' for a, b in r['grounding_verdicts'])} |")
open(os.path.join(HERE, "out", "amount_lf", "amount_00047_grounding.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))

