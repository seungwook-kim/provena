"""00065-q84 단계별 시간·비용 표를 커밋된 결과 파일에서 다시 센다(0원, 호출 없음).
입력: evals/results/deploy_latency_provena-api-00065-q84/stage_times.json (세션별 단계 시간), summary.json (all_runs.cost_by_step)
백분위는 evals/latency/stage_times.py 의 pct 와 같은 함수를 저장소에서 불러 쓴다."""
import json, os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena"
sys.path.insert(0, REPO)
from evals.latency.stage_times import pct
D = os.path.join(HERE, "src", "evals", "results", "deploy_latency_provena-api-00065-q84")
st = json.load(open(os.path.join(D, "stage_times.json"), encoding="utf-8"))
out = {"n_sessions": len(st), "no_search_node": sum(1 for r in st if not r.get("search_nodes"))}
lines = ["| 단계 | p50 | p95 | 평균 |", "|---|---|---|---|"]
for k, name in (("search_s", "검색(검색 노드 시간, 세션 합)"), ("generation_s", "생성(그래프가 도는 동안의 LLM 호출 시간, 겹침 제외 합집합)"),
                ("outside_llm_s", "LLM 호출 밖"), ("graph_s", "그래프 전체"), ("client_total_s", "클라이언트 측 전체(짝지은 세션)"), ("llm_calls", "세션당 LLM 호출 수")):
    v = [float(r[k]) for r in st if r.get(k) is not None]
    out[k] = {"n": len(v), "p50": statistics.median(v), "p95": pct(v, 95), "mean": statistics.mean(v)}  # stage_times.py와 같게 p50은 중앙값, p95는 가장 가까운 순위
    fmt = (lambda x: f"{x:.0f}") if k == "llm_calls" else (lambda x: f"{x:.3f}초")
    lines.append(f"| {name} | {fmt(out[k]['p50'])} | {fmt(out[k]['p95'])} | {out[k]['mean']:.3f}{'' if k == 'llm_calls' else '초'} |")
summ = json.load(open(os.path.join(D, "summary.json"), encoding="utf-8"))
cbs = summ["all_runs"]["cost_by_step"]
print(json.dumps(cbs if isinstance(cbs, dict) and len(json.dumps(cbs)) < 4000 else str(cbs)[:3000], ensure_ascii=False)[:3000], file=sys.stderr)
json.dump(out, open(os.path.join(HERE, "out", "stage_00065.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(lines)); print(out["n_sessions"], out["no_search_node"])
