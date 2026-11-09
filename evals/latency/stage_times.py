"""배포 서비스의 Langfuse 트레이스에서 요청 하나(세션)의 단계별 시간을 다시 계산한다. 새로 호출하지 않는다.

입력
- `--obs`: Langfuse 공개 API `/api/public/v2/observations`(fields=core,basic,usage,time,model,metadata)를 시간 범위로 내려받아
  아래 칸만 남긴 JSON 목록. 칸: id, parentObservationId, sessionId, startTime, endTime, type, name, latency.
  질문·답 원문과 사용자 식별자가 들어 있을 수 있으므로 저장소에 올리지 않는다(이 파일은 올리지 않았다).
- `--rows 공급자=리비전=LLM관측이름=경로`(여러 번): `evals/latency/deploy_latency.py`가 쓴 `rows.jsonl`(`run`, `id`, `at`, `total_s`).
  `LLM관측이름`은 그 배포에서 LLM 호출을 기록한 관측의 이름이다(OpenRouter 경로 `ChatOpenAI`, Anthropic 직접 호출 `TaskEffortAnthropic`).
  같은 호출이 SDK 쪽에도 따로 기록되므로 이 이름의 GENERATION만 센다. 요청 시작 시각(`at - total_s`)과 가장 가까운 세션 시작 시각(3초 안)을 순서대로 하나씩 짝지어 질문 번호를 붙인다.

계산(세션마다)
- 검색: 이름이 `search`인 노드(GENERATION이 아닌 것)의 시간 합.
- 생성: 한 세션의 모든 LLM 호출(위 이름의 GENERATION)의 시작~끝 구간을 합집합으로 합친 시간. 겹치는 구간은 한 번만 센다.
- 그래프 전체: 부모가 없는 관측(질문 그래프 전체)의 시작~끝. 하나로 정해지지 않으면 세션의 가장 이른 시작부터 가장 늦은 끝까지.
- LLM 호출 밖: 그래프 전체 - 생성(검색 노드 시간이 여기에 들어 있다).

출력(`--out`): 세션마다 공급자, 리비전, 회차, 질문 번호, 대화 식별자(`<사용자>:<대화>`에서 사용자 부분을 뺀 대화 부분), 단계 시간(초).
질문 원문, 답, 사용자 식별자, 키는 쓰지 않는다. 표준 출력에는 공급자와 리비전별 p50, p95, 평균을 쓴다.

예: python evals/latency/stage_times.py --obs obs.json --rows openrouter=provena-api-00020=ChatOpenAI=evals/results/deploy_latency_v2/run1/rows.jsonl
    (run2, run3도 같은 이름으로 더한다) --out evals/results/deploy_latency_v2/stage_times.json
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import math
import statistics as st
import sys


def ts(s: str) -> float:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def union(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    cs = ce = None
    for a, b in sorted(intervals):
        if ce is None or a > ce:
            if ce is not None:
                total += ce - cs
            cs, ce = a, b
        else:
            ce = max(ce, b)
    if ce is not None:
        total += ce - cs
    return total


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))]


def read_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--obs", required=True)
    ap.add_argument("--rows", action="append", required=True, metavar="공급자=리비전=LLM관측이름=경로")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    obs = json.load(open(args.obs, encoding="utf-8"))
    sessions = collections.defaultdict(list)
    for x in obs:
        sessions[x["sessionId"]].append(x)
    start = {s: min(ts(x["startTime"]) for x in xs) for s, xs in sessions.items()}

    reqs = []
    for spec in args.rows:
        tag, rev, gname, path = spec.split("=", 3)
        for r in read_rows(path):
            at = ts(r["at"])
            reqs.append((tag, rev, gname, r["run"], r["id"], at - r["total_s"], r["total_s"]))

    used: set[str] = set()
    out = []
    for tag, rev, gname, run, qid, begin, total in sorted(reqs, key=lambda r: r[5]):
        cand = [(abs(start[s] - begin), s) for s in start if s not in used]
        if not cand:
            continue
        gap, sid = min(cand)
        if gap >= 3:
            continue
        used.add(sid)
        xs = sessions[sid]
        ids = {x["id"] for x in xs}
        roots = [x for x in xs if x["parentObservationId"] not in ids]
        if len(roots) == 1:
            a, b = ts(roots[0]["startTime"]), ts(roots[0]["endTime"] or roots[0]["startTime"])
        else:
            a = min(ts(x["startTime"]) for x in xs)
            b = max(ts(x["endTime"] or x["startTime"]) for x in xs)
        searches = [x["latency"] for x in xs if x["name"] == "search" and x["type"] != "GENERATION"]
        gens = [(max(ts(x["startTime"]), a), min(ts(x["endTime"]), b)) for x in xs if x["type"] == "GENERATION" and x["name"] == gname and x["endTime"]]
        gen = union(gens)
        out.append({
            "provider": tag, "revision": rev, "run": run, "question_id": qid,
            "thread": sid.split(":", 1)[-1],
            "search_nodes": len(searches), "search_s": sum(searches),
            "generation_s": gen, "graph_s": b - a,
            "outside_llm_s": (b - a) - gen, "client_total_s": total,
            "llm_calls": len(gens),
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    for key in dict.fromkeys((o["provider"], o["revision"]) for o in out):
        rows = [o for o in out if (o["provider"], o["revision"]) == key]
        def f(field, subset=rows):
            v = [o[field] for o in subset]
            return "p50 %.2f p95 %.2f mean %.2f" % (st.median(v), pct(v, 95), st.mean(v))
        print(key[1], "세션", len(rows), "검색 노드 없는 세션", sum(1 for o in rows if o["search_nodes"] == 0))
        for field in ("search_s", "generation_s", "outside_llm_s", "graph_s", "client_total_s"):
            print(" ", field, f(field))
        if len(rows) < 20:
            rest = [o for o in rows if o["question_id"] != 2]  # 질문 2번은 새 인스턴스의 첫 요청(초기화 비용 포함)
            print("  첫 요청 제외 평균(%d개): 검색 %.2f 생성 %.2f LLM 밖 %.2f" % (
                len(rest), st.mean(o["search_s"] for o in rest), st.mean(o["generation_s"] for o in rest),
                st.mean(o["outside_llm_s"] for o in rest)))
            withs = [o["search_s"] for o in rest if o["search_nodes"]]
            print("  첫 요청 제외, 검색 노드가 있는 세션만(%d개): 검색 평균 %.2f" % (len(withs), st.mean(withs)))
    print("짝지은 세션", len(out), "요청", len(reqs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())