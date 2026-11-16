"""금액 15건(00047-wjn, 2026-11-13 01:56 KST 무렵)의 Langfuse 관측을 읽어(GET만) 거절 2행의 근거 확인 판정 사유를 꺼낸다.
키는 저장소 .env에서 이 프로세스 환경에만 넣고 출력·저장하지 않는다. 질문 원문이 든 관측 전체는 저장하지 않고 필요한 칸만 요약한다."""
import json, os, sys, re
from datetime import datetime, timedelta, timezone
REPO = r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "amount_lf"); os.makedirs(OUT, exist_ok=True)
for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
    m = re.match(r"\s*(LANGFUSE_[A-Z_]+)\s*=\s*(.*)\s*$", line)
    if m:
        os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")
if not os.environ.get("LANGFUSE_HOST") and os.environ.get("LANGFUSE_BASE_URL"):
    os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]
sys.path.insert(0, REPO)
from evals.latency.lf_recall import Langfuse
lf = Langfuse.from_env()
start = datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc); end = datetime(2026, 11, 12, 17, 30, tzinfo=timezone.utc)
mode = sys.argv[1] if len(sys.argv) > 1 else "roots"
if mode == "roots":
    roots = lf.observations("question", "core,basic,io", start, end)
    out = []
    for o in roots:
        inp = json.dumps(o.get("input"), ensure_ascii=False)
        if "SaaS" in inp or "달러" in inp or "$" in inp:
            out.append({"traceId": o.get("traceId"), "start": o.get("startTime"), "session_tail": (o.get("sessionId") or "")[-14:],
                        "q": re.sub(r"\s+", " ", inp)[:160], "out": re.sub(r"\s+", " ", json.dumps(o.get("output"), ensure_ascii=False))[:300]})
    out.sort(key=lambda x: x["start"])
    json.dump(out, open(os.path.join(OUT, "roots.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(roots), len(out))
if mode == "obs":
    qs = [json.loads(l) for l in open(os.path.join(HERE, "src", "evals", "results", "range_retrieval_62_7", "amount_questions.jsonl"), encoding="utf-8") if l.strip()]
    s2 = datetime(2026, 11, 12, 16, 53, tzinfo=timezone.utc); e2 = datetime(2026, 11, 12, 16, 57, 30, tzinfo=timezone.utc)
    roots = [o for o in lf.observations("question", "core,basic,io", s2, e2)]
    trace_map = {}
    seen = {}
    for o in sorted(roots, key=lambda o: o["startTime"]):
        q = (o.get("input") or {}).get("question") if isinstance(o.get("input"), dict) else None
        if q is None:
            try: q = json.loads(o["input"]).get("question")
            except Exception: q = str(o.get("input"))
        qid = next((x["id"] for x in qs if x.get("question", x.get("input")) == q), None)
        if qid is None: continue
        seen[qid] = seen.get(qid, 0) + 1
        trace_map[o["traceId"]] = {"id": qid, "repeat": seen[qid], "start": o["startTime"], "root_output": o.get("output")}
    allobs = []
    cursor = None
    while True:
        d = lf.get("/api/public/v2/observations", {"fields": "core,basic,io", "limit": 100, "cursor": cursor,
                                                    "fromStartTime": s2.strftime("%Y-%m-%dT%H:%M:%SZ"), "toStartTime": e2.strftime("%Y-%m-%dT%H:%M:%SZ")})
        allobs += d.get("data", []); cursor = (d.get("meta") or {}).get("cursor")
        if not cursor or not d.get("data"): break
    per = {}
    for o in allobs:
        t = trace_map.get(o.get("traceId"))
        if not t: continue
        per.setdefault(o["traceId"], []).append({"name": o.get("name"), "type": o.get("type"), "start": o.get("startTime"), "end": o.get("endTime"),
                                                 "metadata": o.get("metadata"), "input": o.get("input"), "output": o.get("output")})
    names = {}
    for tid, obs in per.items():
        for o in obs: names[o["name"]] = names.get(o["name"], 0) + 1
    print("traces", len(trace_map), "obs", len(allobs), "matched", sum(len(v) for v in per.values()))
    print(json.dumps(names, ensure_ascii=False))
    print(json.dumps(sorted((v["id"], v["repeat"], k[:10]) for k, v in trace_map.items())))
    json.dump({"trace_map": trace_map, "obs": per}, open(os.path.join(OUT, "obs_private.json"), "w", encoding="utf-8"), ensure_ascii=False)
