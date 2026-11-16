"""결정표 셀 정확도를 운영 배포판의 결정표 변환 API(초안만 모드)로 잰다(SPEC 3장 결정표 행 "사람이 원문에서 뽑은 정답과 셀 대조", 요청 문서 2장).

    python -m evals.newmetrics.decision_prod --gold evals/decision_cells_gold.jsonl --base URL --out DIR --runs 3 --ledger L.json [--call-prod]
    python -m evals.newmetrics.decision_prod --gold ... --plan-only --out DIR      # 접속 없이: 파서 기준값(0원)과 비용 추정
    python -m evals.newmetrics.decision_prod --gold ... --local --out DIR          # 같은 초안 단계를 로컬 LLM 설정으로(사용자 결정 뒤에만)

운영 경로: 관리자 평가용 계정(A)으로 `POST /decision-tables/convert?draft_only=true {"category"}`. 운영 서버가 변환 그래프와 같은 초안 단계
(`convert.make_draft`)와 셀 대조만 돌려 200으로 돌려준다. 승인 건·결정표·체크포인트를 쓰지 않으므로 반려·정리 단계가 없고, 승인된 표가 있는
업무 종류도 잴 수 있다(8개 전부). 대기 중인 초안이 있는 업무 종류만 서버가 409로 막아 읽기 전용 사전 점검에서 `blocked`로 뺀다.
- 사전 점검(0원, 쓰기 없음): 운영 판이 초안만 모드를 아는지 본다. `?draft_only=maybe`에 빈 본문을 보내 422(질의 인자 검사)면 안다,
  400(본문 검사)이면 모르는 옛 판이다. 옛 판은 인자를 무시하고 승인함에 올리는 일반 변환을 하므로 측정하지 않고 멈춘다(종료 코드 5).
- 응답이 200이 아니거나 `approval_id`가 `draft-only`가 아니면(옛 판이 일반 변환을 한 경우) 바로 반려로 닫고 멈춘다.
- 회차마다 업무 종류 하나에 초안 1번(LLM 1회).

셀 정확도 정의: 정답 한 줄(금액 구간) x 역할 11칸. 칸마다 원문 글자를 규칙(`rules.cell_kind`: Approve가 들어 있으면 그 열의 승인자, 업무 승인 열이면 approver,
재무 승인 열이면 financial, 다른 글자는 협조 cooperating, 빈 칸은 none)으로 자리로 바꾸고, 초안이 그 역할을 둔 자리(`rules._draft_kind`)와 같으면 맞음.
셀 정확도 = 맞은 칸 / 전체 칸(빈 칸 포함). 참고로 비지 않은 칸만의 정확도, 구간 일치율, 초안이 만든 원문에 없는 구간 수를 함께 낸다.
초안을 못 만든 업무 종류(502 등)는 그 칸을 모두 틀림으로 센다. 정답의 "애매" 행은 빼고 세고 따로 적는다.
LLM 없는 기준값(`parser_baseline`): 운영 입력과 같은 파서 칸(`data/parsed/authz_cells.jsonl`)을 규칙으로 옮긴 표(`rules.rules_from_cells`)의 셀 정확도. 0원.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.newmetrics.common import (AUTHZ_CELLS, CostLedger, check_rows, connect_ro, gold_meta, mean, now_kst, read_jsonl, say, write_results)
from evals.newmetrics.spec_tables import FINANCIAL_ROLES, ROLES, category_for_line, parser_category

OUT_TOKENS_PER_BAND = 80
CHARS_PER_TOKEN = 3.0
EXIT_OK, EXIT_FAIL, EXIT_ENV, EXIT_COST, EXIT_PREFLIGHT = 0, 1, 2, 3, 5
REJECT_COMMENT = "새 지표 측정 중 옛 판이 일반 변환으로 올린 초안. 바로 반려(2026-11-16)."
DRAFT_ONLY_ID = "draft-only"


def source_cells() -> dict[str, list[dict]]:
    """업무 종류(파서 이름) -> 칸. 운영 `routes._authz_cells`가 읽는 파일과 같다."""
    by: dict[str, list[dict]] = defaultdict(list)
    for c in read_jsonl(AUTHZ_CELLS):
        by[c["category"]].append(c)
    return dict(by)


def gold_category(row: dict) -> str:
    """구간 줄 -> 업무 종류(요청 문서 2-1 줄 범위) -> 파서 이름. 줄이 범위 밖이면 적은 업무 종류."""
    cat = category_for_line(row["band_line"]) if row.get("band_line") else None
    return parser_category(cat or row.get("category") or "")


def _source_band(row: dict, cells: list[dict]) -> str | None:
    from backend.graph.decision.rules import norm

    bands: dict[str, int] = {}
    for c in cells:
        bands[c["band"]] = min(bands.get(c["band"], 10**9), int(c.get("line") or 10**9))
    for b in bands:
        if norm(b) == norm(row.get("band")):
            return b
    for b, first in bands.items():          # 글자가 다르면 줄 번호로(구간 이름 칸 바로 다음 줄이 첫 역할 칸)
        if row.get("band_line") and first - 1 == row["band_line"]:
            return b
    return None


def score_cells(gold: list[dict], drafts: dict[str, list[dict] | None], cells_by_cat: dict[str, list[dict]],
                include_ambiguous: bool = False) -> dict:
    """정답 행 x 11칸을 초안과 맞댄다. drafts[업무 종류] = 초안 규칙 목록(못 만들었으면 None). 초안이 없는(대상 밖) 업무 종류의 행은 세지 않는다."""
    from backend.graph.decision.rules import NONE, _band_key, _draft_kind, cell_kind

    rows, matched_bands = [], defaultdict(set)
    for g in gold:
        if g.get("ambiguous") and not include_ambiguous:
            continue
        cat = gold_category(g)
        if cat not in drafts:
            continue
        draft = drafts[cat]
        src_band = _source_band(g, cells_by_cat.get(cat, []))
        key = _band_key(src_band or g.get("band") or "")
        rule = None if draft is None else next((r for r in draft if _band_key(r) == key), None)
        if rule is not None:
            matched_bands[cat].add(key)
        for role in ROLES:
            exp = cell_kind("financial" if role in FINANCIAL_ROLES else "functional", g["cells"].get(role))
            got = "failed" if draft is None else _draft_kind(rule, role)
            rows.append({"id": g["id"], "category": cat, "band": g.get("band"), "role": role, "gold_value": g["cells"].get(role) or "",
                         "expected": exp, "draft": got, "match": exp == got, "band_found": rule is not None})
    total = len(rows)
    ok = sum(r["match"] for r in rows)
    nonempty = [r for r in rows if r["expected"] != NONE]
    extra = 0
    for cat, draft in drafts.items():
        if draft:
            extra += sum(1 for r in draft if _band_key(r) not in matched_bands[cat])
    gold_bands = {(r["category"], r["id"]) for r in rows}
    found = {(r["category"], r["id"]) for r in rows if r["band_found"]}
    per_cat = {}
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        per_cat[cat] = {"cells": len(rs), "correct": sum(r["match"] for r in rs), "accuracy": round(sum(r["match"] for r in rs) / len(rs), 4)}
    return {"cells": total, "correct": ok, "cell_accuracy": round(ok / total, 4) if total else None,
            "nonempty_cells": len(nonempty), "nonempty_accuracy": round(sum(r["match"] for r in nonempty) / len(nonempty), 4) if nonempty else None,
            "bands": len(gold_bands), "bands_found": len(found), "extra_bands": extra,
            "confusion": dict(Counter(f"{r['expected']}->{r['draft']}" for r in rows if not r["match"])),
            "per_category": per_cat, "rows": rows}


def parser_baseline(gold: list[dict], cells_by_cat: dict[str, list[dict]]) -> dict:
    from backend.graph.decision.rules import rules_from_cells

    drafts = {cat: rules_from_cells(cs) for cat, cs in cells_by_cat.items()}
    res = score_cells(gold, drafts, cells_by_cat)
    res.pop("rows")
    return res


def estimate_cost(categories: list[str], cells_by_cat: dict[str, list[dict]]) -> dict:
    from backend.graph.decision.convert import DRAFT_SYSTEM, prompt_cells
    from backend.services.cost import load_prices, price_for

    p_in, p_out = price_for(os.environ.get("LLM_MODEL") or "claude-haiku-5-5", load_prices())
    tin = tout = 0.0
    for cat in categories:
        cs = cells_by_cat[cat]
        tin += (len(DRAFT_SYSTEM) + len(json.dumps(prompt_cells(cs), ensure_ascii=False)) + 30) / CHARS_PER_TOKEN
        tout += OUT_TOKENS_PER_BAND * len({c["band"] for c in cs})
    usd = (tin * p_in + tout * p_out) / 1e6
    return {"calls": len(categories), "input_tokens_est": int(tin), "output_tokens_est": int(tout), "usd_est": round(usd, 5),
            "usd_worst": round(usd * 3 * 2, 5)}


# ---------- 운영 ----------

SQL_PENDING = ("SELECT t.cells->0->>'category' FROM approvals a JOIN decision_tables t ON t.table_id = a.target_id "
               "WHERE a.kind = 'decision_table' AND a.status = 'pending'")


def prod_blocked(conn) -> dict[str, str]:
    """읽기 전용. 업무 종류 -> 막힌 이유. 초안만 모드는 승인된 표를 막지 않고, 대기 중인 초안만 409다."""
    out = {}
    for (cat,) in conn.execute(SQL_PENDING).fetchall():
        if cat:
            out.setdefault(cat, "대기 중인 초안이 있어 서버가 409로 막음")
    return out


def _json(r) -> dict:
    try:
        b = r.json()
        return b if isinstance(b, dict) else {}
    except ValueError:
        return {}


def supports_draft_only(ca) -> tuple[bool, int]:
    """운영 판이 초안만 모드를 아는가. 어느 판이든 쓰기 없이 끝나는 요청이다(빈 본문은 400, 틀린 질의 인자는 422)."""
    r = ca.post("/decision-tables/convert?draft_only=maybe", json={}, headers={"Accept": "application/json"})
    return r.status_code == 422, r.status_code


def convert_draft_only(ca, category: str) -> dict:
    r = ca.post("/decision-tables/convert?draft_only=true", json={"category": category}, headers={"Accept": "application/json"})
    return {"status": r.status_code, "body": _json(r)}


def reject_prod(ca, approval_id: str) -> dict:
    """안전장치: 옛 판이 일반 변환으로 승인함에 올린 건을 바로 반려한다(정상 흐름에서는 부르지 않는다)."""
    r = ca.post(f"/approvals/{approval_id}", json={"approval_id": approval_id, "approve": False, "comment": REJECT_COMMENT},
                headers={"Accept": "application/json"})
    body = _json(r)
    return {"status": r.status_code, "result_status": body.get("status")}


def draft_local(category: str, cells: list[dict], llm) -> tuple[list[dict] | None, str | None]:
    """운영과 같은 그래프(`build_convert_graph`)를 메모리 저장소·메모리 체크포인터로 돌려 승인 대기까지 간 초안을 읽는다(저장·승인 없음)."""
    from langgraph.checkpoint.memory import MemorySaver

    from backend.graph.decision.convert import build_convert_graph, pending_interrupt
    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.decision.routes import AUTHZ_VERSION_ID
    from backend.rag.ingest.handbook import AUTHZ_PATH, rule_seq

    g = build_convert_graph(llm, InMemoryDecisionRepo(), MemorySaver())
    tid = f"nm-eval-{uuid.uuid4().hex[:8]}"
    out = g.invoke({"category": category, "rule_seq": rule_seq(AUTHZ_PATH), "version_id": AUTHZ_VERSION_ID, "source_cells": cells,
                    "requested_by": "eval"}, {"configurable": {"thread_id": tid}})
    if out.get("error"):
        return None, out["error"]
    p = pending_interrupt(g, tid)
    return (p or {}).get("draft"), None


def render_md(s: dict) -> str:
    m = s.get("metrics") or {}
    lines = [f"# 결정표 셀 정확도 ({s['started'][:10]})", "",
             f"경로: {s['mode']}. 운영 판 `{s.get('revision')}`. 정답 `{s['gold']['file']}` {s['gold']['rows']}행, 애매 {s['ambiguous']}행 제외.", "",
             f"측정한 업무 종류: {', '.join(s.get('categories') or []) or '없음'}", ""]
    if s.get("blocked"):
        lines += ["운영에서 잴 수 없던 업무 종류(기본 값에 넣지 않음):", ""] + [f"- {k}: {v}" for k, v in s["blocked"].items()] + [""]
    if m:
        lines += ["| 값 | 셀 정확도 | 비지 않은 칸 정확도 | 구간 일치 | 원문에 없는 구간 |", "|---|---|---|---|---|"]
        for i, r in enumerate(m["runs"], start=1):
            lines.append(f"| {i}회차 | {r['cell_accuracy']} ({r['correct']}/{r['cells']}) | {r['nonempty_accuracy']} | {r['bands_found']}/{r['bands']} | {r['extra_bands']} |")
        lines.append(f"| 평균 | {m['mean_cell_accuracy']} | {m['mean_nonempty_accuracy']} | | |")
    b = s.get("parser_baseline") or {}
    lines += ["", f"LLM 없는 기준값(파서 칸을 규칙으로 옮긴 표, 같은 업무 종류 전체 8개): 셀 정확도 {b.get('cell_accuracy')} ({b.get('correct')}/{b.get('cells')}).",
              f"비용(추정, 운영 서버 키): {s.get('cost_est_usd')}달러. 운영에 남긴 행: 없음(초안만 모드)."]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="결정표 셀 정확도")
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--revision", default="")
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--total-cap", type=float, default=0.5)
    ap.add_argument("--run-cap", type=float, default=0.03)
    ap.add_argument("--call-prod", action="store_true", help="운영 초안만 변환 API를 부른다(LLM 비용, 없으면 사전 점검까지만)")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--local", action="store_true", help="운영 대신 같은 그래프를 로컬 LLM 설정으로(사용자 결정 뒤에만)")
    ap.add_argument("--categories", default="", help="쉼표로 고른 업무 종류(파서 이름). 비우면 정답에 있는 것 중 잴 수 있는 것 전부")
    a = ap.parse_args(argv)

    gold = read_jsonl(a.gold)
    check_rows("decision", gold)
    cells_by_cat = source_cells()
    want = [c for c in dict.fromkeys(gold_category(g) for g in gold) if c in cells_by_cat]
    if a.categories:
        want = [c for c in want if c in {x.strip() for x in a.categories.split(",")}]
    s: dict[str, Any] = {"metric": "decision_cells", "started": now_kst(), "revision": a.revision, "gold": gold_meta(a.gold),
                         "ambiguous": sum(1 for g in gold if g.get("ambiguous")), "parser_baseline": parser_baseline(gold, cells_by_cat),
                         "definition": "셀 정확도 = 맞은 칸 / (정답 구간 수 x 11칸), 칸 자리는 rules.cell_kind 규칙"}
    blocked: dict[str, str] = {}
    mode = "local" if a.local else ("prod" if a.call_prod else ("plan-only" if a.plan_only else "preflight-only"))
    if not a.plan_only and not a.local:
        if not os.environ.get("DATABASE_URL"):
            say("DATABASE_URL 없음")
            return EXIT_ENV
        ro = connect_ro()
        try:
            blocked = {c: why for c, why in prod_blocked(ro).items() if c in want}
        finally:
            ro.close()
    cats = [c for c in want if c not in blocked]
    est = estimate_cost(cats, cells_by_cat)
    s.update({"mode": mode, "categories": cats, "blocked": blocked, "cost_estimate_per_run": est})
    if a.plan_only or not (a.call_prod or a.local):
        write_results(a.out, s, render_md(s))
        say(f"{mode}: 잴 업무 종류 {cats}, 막힘 {list(blocked)}, 회차당 추정 {est['usd_est']}달러, 파서 기준값 {s['parser_baseline']['cell_accuracy']}")
        return EXIT_OK
    ledger = CostLedger(a.ledger or (a.out / "cost_ledger.json"), a.total_cap)
    runs, all_rows, raw, spent, code = [], [], [], 0.0, EXIT_OK
    ca = llm = None
    if a.local:
        from backend.graph.service_profile import apply_service_profile
        from backend.services.llm import get_chat_model

        apply_service_profile()
        llm = get_chat_model()
    else:
        from evals.newmetrics.prod import client, login

        ca = client(a.base, read_s=180.0)
        login(ca, "A")
        ok, st = supports_draft_only(ca)
        s["draft_only_probe_status"] = st
        if not ok:
            ca.close()
            say(f"운영 판이 초안만 모드를 모른다(검사 응답 {st}): 일반 변환이 승인함에 올리므로 측정하지 않는다")
            s.update({"metrics": None, "stopped": "draft_only_unsupported", "finished": now_kst()})
            write_results(a.out, s, render_md(s))
            return EXIT_PREFLIGHT
    try:
        for run in range(1, a.runs + 1):
            ok, why = ledger.allow(est["usd_est"], a.run_cap)
            if not ok:
                say(f"비용 상한으로 멈춤: {why}")
                code = EXIT_COST
                break
            drafts: dict[str, list[dict] | None] = {}
            for cat in cats:
                if a.local:
                    d, err = draft_local(cat, cells_by_cat[cat], llm)
                    drafts[cat] = d
                    raw.append({"run": run, "category": cat, "error": err, "draft": d})
                    continue
                r = convert_draft_only(ca, cat)
                body = r["body"]
                aid = body.get("approval_id")
                if aid not in (None, DRAFT_ONLY_ID, "example-convert"):        # 옛 판이 일반 변환을 했다: 바로 반려하고 멈춘다
                    raw.append({"run": run, "category": cat, "status": r["status"], "approval_id": aid, "reject": reject_prod(ca, aid)})
                    say(f"초안만 모드가 아닌 응답(승인 건 {aid}): 반려하고 멈춘다")
                    code = EXIT_FAIL
                    break
                ok_resp = r["status"] == 200 and aid == DRAFT_ONLY_ID          # 키 없는 데모의 예시 응답(example-convert)은 측정 아님
                d = body.get("draft") if ok_resp else None
                drafts[cat] = [{k: v for k, v in x.items() if k != "band_label"} for x in d] if d else None
                raw.append({"run": run, "category": cat, "status": r["status"], "approval_id": aid, "summary": body.get("summary"),
                            "draft": drafts[cat], "server_mismatch": (body.get("comparison") or {}).get("mismatch_count"),
                            "note": body.get("detail") if not ok_resp else None})
            if code != EXIT_OK:
                break
            ledger.add("decision", run, est["usd_est"], "추정")
            spent += est["usd_est"]
            res = score_cells(gold, drafts, cells_by_cat)
            for r in res.pop("rows"):
                all_rows.append({**r, "run": run})
            runs.append(res)
            say(f"회차 {run}: 셀 정확도 {res['cell_accuracy']} ({res['correct']}/{res['cells']})")
    finally:
        if ca is not None:
            ca.close()
    s.update({"metrics": {"runs": runs, "mean_cell_accuracy": mean(r["cell_accuracy"] for r in runs),
                          "mean_nonempty_accuracy": mean(r["nonempty_accuracy"] for r in runs)} if runs else None,
              "cost_est_usd": round(spent, 5), "finished": now_kst()})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "drafts.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    write_results(a.out, s, render_md(s), all_rows)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
