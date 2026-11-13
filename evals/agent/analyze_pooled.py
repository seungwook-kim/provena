"""0원 후처리(LLM·운영 호출 없음): 합동 검토 재측정 결과 폴더들을 읽어 팀 대 same 짝 비교를 낸다.

    python -m evals.agent.analyze_pooled --dataset <평가셋.jsonl> --runs 00044=<폴더> new=<폴더> [--out <txt>]

- 짝: 같은 (문항, 회차)의 팀 런과 same 런. 정답 쟁점 단위로 (팀 찾음, same 찾음) 4칸 표를 센다.
- 구간: 문항을 단위로 부트스트랩(2000회)해 누락률 차이(same - 팀, 양수면 팀이 적음)의 95% 구간을 낸다.
- 천장: same 런이 돌려받은 검색 결과(retrieved)에 정답 섹션이 든 정답 쟁점 수. 팀과 same은 같은 검색이므로 이 값이 두 방식의 공통 상한이다.
  "팀이 낫다" 규칙(차이 0.10 이상)이 이 평가셋에서 도달 가능한지 (천장 - same 찾음) / 정답 수 로 본다.
- 보조: 충돌 행(팀 입장이 갈린 행) 수, 쟁점 행 수, 런당 비용(관찰값 또는 서버 로그값).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
from evals.agent import exp_review_v1 as X  # noqa: E402

ARM_DIR = {"team": "team", "same": "single_same", "undivided": "single_undivided"}


def load_rows(folder: Path) -> dict:
    out = {}
    for arm, d in ARM_DIR.items():
        p = folder / d / "rows.jsonl"
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[(arm, str(r["id"]), int(r["repeat"]))] = r
    return out


def chunk_meta(repo: Path, wanted: set) -> dict:
    meta = {}
    with open(repo / "data" / "chunks" / "chunks.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            d = json.loads(ln)
            if d["chunk_id"] in wanted:
                meta[d["chunk_id"]] = (d["rule_seq"], d["article"])
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--runs", nargs="+", required=True, help="라벨=폴더")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    repo = Path(a.repo)
    items = {str(i["id"]): i for i in X.load_review_dataset(Path(a.dataset))}
    sets = {}
    for spec in a.runs:
        lab, _, p = spec.partition("=")
        sets[lab] = load_rows(Path(p))
    lines: list[str] = []
    P = lines.append

    wanted = {cid for rows in sets.values() for (arm, _, _), r in rows.items() if arm == "same" for ids in (r.get("retrieved") or {}).values() for cid in ids}
    meta = chunk_meta(repo, wanted)

    # 정답 쟁점 단위 결과: label -> [(item, rep, team_found, same_found, retrieved_has_gold)]
    units = {}
    for lab, rows in sets.items():
        u = []
        for (arm, i, rep), r in sorted(rows.items()):
            if arm != "team":
                continue
            it = items.get(i)
            if not it or it["kind"] == "clarify" or not it["_gold"]:
                continue
            rs = rows.get(("same", i, rep))
            if not rs:
                continue
            mt = X.match_gold(it, r.get("issue_rows") or [])["detail"]
            ms = X.match_gold(it, rs.get("issue_rows") or [])["detail"]
            ret = rs.get("retrieved") or {}
            for k, g in enumerate(it["_gold"]):
                team, ref, _vd = g
                has = any(ref.matches(SimpleNamespace(rule_seq=meta[c][0], article=meta[c][1], chunk_id=c, line_start=None, line_end=None))
                          for c in ret.get(team, []) if c in meta)
                u.append((i, rep, bool(mt[k]["found"]), bool(ms[k]["found"]), has))
        units[lab] = u

    def table(u):
        c = collections.Counter((t, s) for _, _, t, s, _ in u)
        return c

    P("== 정답 쟁점 단위 짝 비교 (팀 런과 same 런, 청크 메타로 맞춘 검색 천장 포함) ==")
    allu = []
    for lab, u in units.items():
        allu += [(f"{lab}:{i}", rep, t, s, h) for i, rep, t, s, h in u]
        n = len(u); ft = sum(t for _, _, t, _, _ in u); fs = sum(s for _, _, _, s, _ in u); ceil = sum(h for *_, h in u)
        c = table(u)
        P(f"[{lab}] 정답 쟁점 {n}: 팀 찾음 {ft} ({1 - ft / n:.3f}), same 찾음 {fs} ({1 - fs / n:.3f}), 누락률 차이(same-팀) {(ft - fs) / n:+.3f}"
          f" | 짝표 둘 다 {c[(True, True)]}, 팀만 {c[(True, False)]}, same만 {c[(False, True)]}, 둘 다 못 찾음 {c[(False, False)]}"
          f" | 검색 천장 {ceil}/{n} -> 도달 가능한 최대 차이 {(ceil - fs) / n:.3f}")
    if len(units) > 1:
        n = len(allu); ft = sum(x[2] for x in allu); fs = sum(x[3] for x in allu); ceil = sum(x[4] for x in allu)
        c = table([(0, 0, x[2], x[3], x[4]) for x in allu])
        P(f"[합침] 정답 쟁점 {n}: 팀 {ft} ({1 - ft / n:.3f}), same {fs} ({1 - fs / n:.3f}), 짝표 둘 다 {c[(True, True)]}, 팀만 {c[(True, False)]}, same만 {c[(False, True)]}, 천장 {ceil}/{n}")

    P("")
    P("== 문항 단위 부트스트랩 (차이 = 팀 찾음률 - same 찾음률, 양수면 팀이 더 찾음) ==")
    rnd = random.Random(a.seed)
    for lab, group in list(units.items()) + ([("합침", None)] if len(units) > 1 else []):
        if group is None:
            group = [(f"{l}:{i}", rep, t, s, h) for l, u in units.items() for i, rep, t, s, h in u]
        else:
            group = [(f"{lab}:{i}", rep, t, s, h) for i, rep, t, s, h in group]
        by_item = collections.defaultdict(list)
        for i, rep, t, s, h in group:
            by_item[i].append((t, s))
        ids = list(by_item)
        diffs = []
        for _ in range(2000):
            pick = [rnd.choice(ids) for _ in ids]
            tt = sum(t for i in pick for t, s in by_item[i]); ss = sum(s for i in pick for t, s in by_item[i]); nn = sum(len(by_item[i]) for i in pick)
            diffs.append((tt - ss) / nn if nn else 0.0)
        diffs.sort()
        tt = sum(t for v in by_item.values() for t, s in v); ss = sum(s for v in by_item.values() for t, s in v); nn = sum(len(v) for v in by_item.values())
        P(f"[{lab}] 점추정 {(tt - ss) / nn:+.3f}, 95% 구간 [{diffs[50]:+.3f}, {diffs[1949]:+.3f}] (문항 {len(ids)}개 재표집)")

    P("")
    P("== 보조: 행 수, 충돌 행, 비용 (방식별) ==")
    for lab, rows in sets.items():
        for arm in ARM_DIR:
            rs = [r for (a_, _, _), r in rows.items() if a_ == arm]
            if not rs:
                continue
            ir = [x for r in rs for x in (r.get("issue_rows") or [])]
            conf = sum(1 for x in ir if x.get("conflict"))
            costs = [c for c in ((r.get("cost_usd_observed") if r.get("cost_usd_observed") is not None else r.get("cost_usd_log")) for r in rs) if c is not None]
            P(f"[{lab}] {arm}: 런 {len(rs)}, 행 {len(ir)}, 충돌 행 {conf}, 충돌 있는 런 {sum(1 for r in rs if any(x.get('conflict') for x in (r.get('issue_rows') or [])))}, "
              f"비용 본 런 {len(costs)}, 런당 {sum(costs) / len(costs):.5f}달러" if costs else f"[{lab}] {arm}: 런 {len(rs)}, 행 {len(ir)}, 충돌 행 {conf}, 비용 미확인")
    text = "\n".join(lines)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
