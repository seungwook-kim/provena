"""운영 Langfuse의 search 관측에서 '첫 검색 상위 5개 청크'를 꺼내 정답 섹션 기준 Recall@5를 낸다 (읽기 전용, 유료 호출 없음).

    python -m evals.latency.lf_recall --run-dir evals/results/deploy_latency_<리비전> [--out <폴더>] [--pairing thread|legacy]

환경 변수(키는 출력·저장하지 않는다): LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
저장소 루트에서 실행한다. 저장소는 읽기만 한다.

정의
- 공식 Recall@5 = `evals/retrieval/run.evaluate` + `metrics.ranking_metrics` + `metrics.aggregate`를 그대로 부른다(정답 섹션 매칭은 `gold.py`).
  문항별 Recall@5 = 상위 5개 안에서 찾은 정답 위치 수 / 정답 위치 수, 집계 = 채점 문항 값의 단순 평균(`evals/exclusions.json`과 코퍼스에 없는 정답 위치는 분모에서 뺀다).
- 첫 검색 = 한 trace(= `/chat` 한 번)에서 시작 시각이 가장 이른 `search` 관측(LangGraph `search` 노드).
- 첫 검색 상위 5개 = 그 관측 output(JSON 문자열)의 `chunks` 목록 앞 5개. `chunks`는 서비스가 판정·답에 문맥으로 쓴 순서이고(backend/graph/build.py `search`),
  나뉜 질문이면 `backend/rag/retrieve/search.py`가 하위 질문 목록(과 링크 확장)으로 7자리를 채우고 끝 1자리만 원 질문 목록으로 채운 SPLIT_K(8)개의 앞 5개(끝 1자리는 앞 5개에 들지 않는다), 뒤에 도입부 채우기(R3)가 붙으면 맨 뒤에 붙으므로 앞 5개에 들지 않는다.
- 짝짓기: 측정기 행의 `thread_id` == Langfuse `sessionId`(`<user_id>:<thread_id>`)의 뒤쪽. 행에 `thread_id`가 없으면 멈춘다(`--pairing legacy`는 리허설 전용 근사).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from evals.retrieval import run as official_run
from evals.retrieval.metrics import aggregate

REPO_ROOT = Path(__file__).resolve().parents[2]
K = 5
_CHUNK_ID_RE = re.compile(r"""['"]chunk_id['"]\s*:\s*['"]([0-9a-f]{16})['"]""")


# ---------------------------------------------------------------- 파서: search 관측 output -> 청크 목록

def parse_search_output(output: Any) -> dict:
    """search 관측의 output을 읽는다. 돌려주는 값: {mode, chunks(순위 순 dict 목록), sub_queries, search_error}.

    mode: `json`(정상: `chunks` 목록의 각 dict), `regex`(JSON이 깨졌을 때 `chunk_id`만 순서대로, 사본 `search_cache` 앞까지), `none`(청크 없음).
    """
    obj = output
    for _ in range(2):   # 이중으로 문자열화된 경우까지
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except ValueError:
                break
    if isinstance(obj, dict):
        ch = obj.get("chunks")
        if isinstance(ch, list):
            chunks = [c for c in ch if isinstance(c, dict) and c.get("chunk_id")]
            return {"mode": "json" if chunks else "none", "chunks": chunks,
                    "sub_queries": obj.get("sub_queries") or [], "search_error": obj.get("search_error") or ""}
        return {"mode": "none", "chunks": [], "sub_queries": obj.get("sub_queries") or [], "search_error": obj.get("search_error") or ""}
    if isinstance(obj, str):
        head = obj.split('"search_cache"', 1)[0].split("'search_cache'", 1)[0]
        ids = list(dict.fromkeys(_CHUNK_ID_RE.findall(head)))
        if ids:
            return {"mode": "regex", "chunks": [{"chunk_id": i} for i in ids], "sub_queries": [], "search_error": ""}
    return {"mode": "none", "chunks": [], "sub_queries": [], "search_error": ""}


def top_k_chunks(parsed: dict, k: int = K) -> list[dict]:
    """서비스가 첫 검색에서 문맥으로 쓴 순서의 상위 k개 (= output.chunks[:k])."""
    return list(parsed["chunks"][:k])


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _input_obj(o: dict) -> dict:
    v = o.get("input")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def thread_of(session_id: str | None) -> str | None:
    """sessionId `<user_id>:<thread_id>` -> thread_id."""
    if not session_id:
        return None
    return session_id.split(":", 1)[1] if ":" in session_id else session_id


def first_search_per_trace(observations: Iterable[dict]) -> dict[str, dict]:
    """trace마다 시작 시각이 가장 이른 search 관측. {trace_id: {obs, n_search, session_id, thread_id, start, question, retries, all_chunk_ids}}."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        if o.get("name") == "search" and o.get("traceId"):
            groups[o["traceId"]].append(o)
    out: dict[str, dict] = {}
    for tid, obs in groups.items():
        obs.sort(key=lambda o: (_ts(o["startTime"]), o.get("id", "")))
        first = obs[0]
        inp = _input_obj(first)
        ids: set[str] = set()
        for o in obs:
            ids.update(c["chunk_id"] for c in parse_search_output(o.get("output"))["chunks"])
        out[tid] = {"obs": first, "n_search": len(obs), "session_id": first.get("sessionId"), "thread_id": thread_of(first.get("sessionId")),
                    "start": _ts(first["startTime"]), "question": inp.get("question"), "retries": inp.get("retries", 0), "all_chunk_ids": ids}
    return out


# ---------------------------------------------------------------- 짝짓기

def pair_by_thread(rows: list[dict], traces: dict[str, dict], known_sessions: set[str] | None = None) -> list[dict]:
    """행 -> trace. 행의 `thread_id`와 sessionId의 thread 부분이 정확히 같은 trace만 짝으로 본다 (시간·문구는 쓰지 않는다).

    상태: paired | no_thread_id | no_trace(그 대화의 trace가 Langfuse에 없음 = 자료 누락) | no_search(trace는 있으나 search 관측이 없음 = 서비스가 검색하지 않음).
    `known_sessions`(trace 목록의 thread id 집합)을 주지 않으면 no_trace와 no_search를 가를 수 없어 둘 다 `no_trace`로 둔다.
    """
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for t in traces.values():
        if t["thread_id"]:
            by_thread[t["thread_id"]].append(t)
    out = []
    for r in rows:
        tid = r.get("thread_id")
        if not tid:
            out.append({"row": r, "status": "no_thread_id", "trace": None, "n_traces": 0})
            continue
        ts = sorted(by_thread.get(tid, []), key=lambda t: t["start"])
        if ts:
            out.append({"row": r, "status": "paired", "trace": ts[0], "n_traces": len(ts)})
        elif known_sessions is not None and tid in known_sessions:
            out.append({"row": r, "status": "no_search", "trace": None, "n_traces": 0})
        else:
            out.append({"row": r, "status": "no_trace", "trace": None, "n_traces": 0})
    return out


def pair_legacy(rows: list[dict], items_by_id: dict[int, dict], traces: dict[str, dict], *, before_s: float = 3.0, after_s: float = 2.0) -> list[dict]:
    """리허설 전용 근사. thread_id가 없는 옛 행을 '요청 구간 안에서 시작한 첫 검색 중 질문 문구가 같은 것 하나'로 짝짓는다.

    구간 = [at - total_s - before_s, at + after_s] (`at`은 행을 쓴 시각). 후보가 정확히 하나일 때만 짝으로 보고 0개·2개 이상이면 짝짓지 않는다(`no_trace`/`ambiguous`).
    thread id로 하는 짝짓기가 아니므로 결과에 `pairing: legacy`를 적는다.
    """
    out = []
    for r in rows:
        q = (items_by_id.get(r["id"]) or {}).get("input")
        if r.get("total_s") is None or not r.get("at") or q is None:
            out.append({"row": r, "status": "no_trace", "trace": None, "n_traces": 0})
            continue
        end = datetime.fromisoformat(r["at"]).astimezone(timezone.utc)
        lo, hi = end - timedelta(seconds=float(r["total_s"]) + before_s), end + timedelta(seconds=after_s)
        cands = [t for t in traces.values() if t["question"] == q and lo <= t["start"] <= hi]
        if len(cands) == 1:
            out.append({"row": r, "status": "paired", "trace": cands[0], "n_traces": 1})
        else:
            out.append({"row": r, "status": "ambiguous" if cands else "no_trace", "trace": None, "n_traces": len(cands)})
    return out


def cited_consistency(row: dict, trace: dict) -> bool | None:
    """행이 인용한 청크가 모두 그 trace의 search 관측에 나온 청크인가(짝이 맞는지 보는 보조 검사). 인용이 없으면 None."""
    cited = [c for c in (row.get("cited_chunk_ids") or []) if c]
    if not cited:
        return None
    return all(c in trace["all_chunk_ids"] for c in cited)


# ---------------------------------------------------------------- 공식 Recall@5 계산 (evals/retrieval 재사용)

def to_chunk_obj(c: dict) -> SimpleNamespace:
    """관측에 실린 청크 dict -> 공식 채점기가 읽는 속성(chunk_id, rule_seq, article, line_start, line_end)."""
    return SimpleNamespace(chunk_id=c.get("chunk_id"), rule_seq=c.get("rule_seq"), article=c.get("article"),
                           line_start=c.get("line_start"), line_end=c.get("line_end"))


def enrich_regex_chunks(chunks: list[dict], corpus_by_id: dict[str, dict]) -> list[dict]:
    """regex로 건진 청크(chunk_id만 있음)에 코퍼스 파일의 rule_seq·article·줄 범위를 채운다. 코퍼스에 없으면 그대로(정답 chunk_id 표기로만 맞는다)."""
    return [{**corpus_by_id.get(c["chunk_id"], {}), **c} for c in chunks]


def score_run(items: list[dict], retrieved: dict[int, list[dict]], *, k: int = K, exclusions: dict | None = None, corpus: list | None = None) -> dict:
    """한 회차: 관련 문항마다 `retrieved[id]`(순위 순 청크 dict 목록)를 검색 결과로 보고 공식 `evaluate`로 채점한다."""
    run = official_run
    rel = [it for it in items if it["kind"] == "relevant" and it["id"] in retrieved]
    by_q = {it["input"]: [to_chunk_obj(c) for c in retrieved[it["id"]][:k]] for it in rel}
    if len(by_q) != len(rel):
        raise ValueError("평가셋에 같은 질문 문구가 둘 이상이다")
    return run.evaluate(rel, lambda q: by_q[q.query], k, exclusions=exclusions or {}, corpus=corpus)


def summarize(per_run: dict[int, dict], k: int = K) -> dict:
    """회차별·전체 요약. 전체 = 모든 회차의 채점 행을 합쳐 공식 `aggregate`로 낸 값(문항·회차 쌍의 단순 평균)."""
    key = f"recall@{k}"
    out = {"per_run": {}, "k": k}
    pooled: list[dict] = []
    for n, res in sorted(per_run.items()):
        s = res["summary"]
        out["per_run"][n] = {"recall": s[key]["value"], "ci95": s[key]["ci95"], "n_scored": s["n_relevant_scored"], "excluded": s["excluded"]}
        pooled += res["rows"]
    if pooled:
        s = aggregate(pooled, k)
        out["all_runs"] = {"recall": s[key]["value"], "ci95": s[key]["ci95"], "n_scored": s["n_relevant_scored"], "excluded": s["excluded"]}
    return out


# ---------------------------------------------------------------- 측정 행 읽기

def load_rows(run_dir: Path) -> dict[int, list[dict]]:
    runs: dict[int, list[dict]] = {}
    for d in sorted(run_dir.glob("run*")):
        m = re.fullmatch(r"run(\d+)", d.name)
        f = d / "rows.jsonl"
        if m and f.is_file():
            runs[int(m.group(1))] = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return runs


def row_window(runs: dict[int, list[dict]], margin_min: float = 10.0) -> tuple[datetime, datetime]:
    ats = [datetime.fromisoformat(r["at"]).astimezone(timezone.utc) for rows in runs.values() for r in rows if r.get("at")]
    starts = [a - timedelta(seconds=float(r.get("total_s") or 0)) for rows in runs.values() for r in rows if r.get("at")
              for a in [datetime.fromisoformat(r["at"]).astimezone(timezone.utc)]]
    return min(starts) - timedelta(minutes=margin_min), max(ats) + timedelta(minutes=margin_min)


# ---------------------------------------------------------------- Langfuse 읽기 (GET만)

class Langfuse:
    def __init__(self, host: str, pk: str, sk: str, timeout: float = 60.0):
        self.host, self.timeout = host.rstrip("/"), timeout
        self._auth = "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()

    @classmethod
    def from_env(cls) -> "Langfuse":
        miss = [n for n in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.environ.get(n)]
        if miss:
            raise SystemExit("환경 변수가 없다: " + ", ".join(miss))
        return cls(os.environ["LANGFUSE_HOST"], os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

    def get(self, path: str, params: dict) -> dict:
        url = f"{self.host}{path}?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"Authorization": self._auth, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise SystemExit(f"Langfuse {path} HTTP {e.code}")
            except (urllib.error.URLError, TimeoutError):
                if attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise SystemExit(f"Langfuse {path} 연결 실패")
        raise SystemExit("unreachable")

    def observations(self, name: str, fields: str, start: datetime, end: datetime, limit: int = 100) -> list[dict]:
        """이름이 `name`인 관측 전부, 커서로 끝까지 (GET /api/public/v2/observations)."""
        out, cursor = [], None
        while True:
            d = self.get("/api/public/v2/observations", {"name": name, "fields": fields, "limit": limit, "cursor": cursor,
                                                       "fromStartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "toStartTime": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
            out += d.get("data", [])
            cursor = (d.get("meta") or {}).get("cursor")
            if not cursor or not d.get("data"):
                return out

    def search_observations(self, start: datetime, end: datetime) -> list[dict]:
        return self.observations("search", "core,basic,io", start, end)

    def thread_ids(self, start: datetime, end: datetime) -> set[str]:
        """구간 안 trace의 thread id 집합. trace 뿌리 관측(이름 `question`, io 없이)의 sessionId에서 읽는다
        (traces API는 410이라 못 쓴다). 검색 관측이 없는 trace(서비스가 검색하지 않음)와 trace 자체가 없는 경우(Langfuse 누락)를 가르는 데 쓴다."""
        return {thread_of(o["sessionId"]) for o in self.observations("question", "core,basic", start, end) if o.get("sessionId")}


# ---------------------------------------------------------------- 전체 흐름

def build_report(runs: dict[int, list[dict]], items: list[dict], observations: list[dict], *, pairing: str = "thread", known_sessions: set[str] | None = None,
                 k: int = K, exclusions: dict | None = None, corpus: list | None = None, corpus_by_id: dict | None = None, allow_missing: bool = False) -> dict:
    """측정 행 + 관측 -> 회차별·전체 Recall@5와 문항별 상세. 짝지을 수 없는 관련 문항이 있으면 `allow_missing` 없이는 ValueError."""
    traces = first_search_per_trace(observations)
    items_by_id = {it["id"]: it for it in items}
    per_run: dict[int, dict] = {}
    detail, problems = [], []
    stats = defaultdict(int)
    for n, rows in sorted(runs.items()):
        paired = pair_by_thread(rows, traces, known_sessions) if pairing == "thread" else pair_legacy(rows, items_by_id, traces)
        retrieved: dict[int, list[dict]] = {}
        for p in paired:
            r, item = p["row"], items_by_id.get(p["row"]["id"])
            if item is None or item["kind"] != "relevant":
                continue
            stats[p["status"]] += 1
            d = {"run": n, "id": r["id"], "status": p["status"], "thread_id": r.get("thread_id")}
            if p["status"] == "paired":
                parsed = parse_search_output(p["trace"]["obs"].get("output"))
                chunks = top_k_chunks(parsed, k)
                if parsed["mode"] == "regex" and corpus_by_id:
                    chunks = enrich_regex_chunks(chunks, corpus_by_id)
                retrieved[r["id"]] = chunks
                cons = cited_consistency(r, p["trace"])
                stats[f"cited_{cons}"] += 1
                stats[f"parse_{parsed['mode']}"] += 1
                if p["trace"]["retries"]:
                    stats["first_search_has_retries"] += 1
                d.update(top5=[c["chunk_id"] for c in chunks], n_chunks_in_first_search=len(parsed["chunks"]), n_sub_queries=len(parsed["sub_queries"]),
                         n_search_obs_in_trace=p["trace"]["n_search"], n_traces_for_thread=p["n_traces"], parse=parsed["mode"], cited_in_trace=cons)
            elif p["status"] == "no_search":
                retrieved[r["id"]] = []   # 서비스가 검색하지 않은 문항: 상위 5개가 비어 있다 (Recall 0)
                d["top5"] = []
            else:
                problems.append(f"run{n} id={r['id']}: {p['status']}")
            detail.append(d)
        per_run[n] = score_run(items, retrieved, k=k, exclusions=exclusions, corpus=corpus) if retrieved else {"summary": {f"recall@{k}": {"value": None, "ci95": None}, "n_relevant_scored": 0, "excluded": []}, "rows": []}
        for row in per_run[n]["rows"]:
            for d in detail:
                if d["run"] == n and d["id"] == row["id"]:
                    d.update(scored=row.get("scored"), recall=row.get(f"recall@{k}"), first_hit_rank=row.get("first_hit_rank"), excluded_reason=row.get("excluded_reason"))
    if problems and not allow_missing:
        raise ValueError(f"짝지을 수 없는 관련 문항 {len(problems)}건 (예: {problems[:5]}). 행에 thread_id를 남기는 측정기로 다시 재거나 --allow-missing")
    n_rel = sum(1 for rows in runs.values() for r in rows if (items_by_id.get(r["id"]) or {}).get("kind") == "relevant")
    n_ok = stats.get("paired", 0) + stats.get("no_search", 0)
    return {"pairing": pairing, "k": k, "summary": summarize(per_run, k), "pair_stats": dict(stats), "unpaired": problems, "detail": detail,
            "coverage": {"relevant_rows": n_rel, "with_langfuse_data": n_ok, "fraction": round(n_ok / n_rel, 3) if n_rel else None}}


def render(report: dict, title: str = "") -> str:
    s, k = report["summary"], report["k"]

    def f(v):
        return "없음" if v is None else f"{v:.3f}"

    lines = [f"# 첫 검색 상위 {k} Recall@{k} (운영 Langfuse) {title}".strip(), "", f"짝짓기: {report['pairing']}" + (" (근사: 리허설 전용)" if report["pairing"] == "legacy" else ""), "",
             "| 구분 | Recall@%d | 채점 문항 |" % k, "|---|---|---|"]
    for n, v in s["per_run"].items():
        lines.append(f"| {n}회차 | {f(v['recall'])} | {v['n_scored']} |")
    if "all_runs" in s:
        v = s["all_runs"]
        ci = f" [{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}]" if v["ci95"] else ""
        lines.append(f"| 전체 | {f(v['recall'])}{ci} | {v['n_scored']} |")
    c = report["coverage"]
    lines += ["", f"Langfuse 자료가 있는 관련 행: {c['with_langfuse_data']}/{c['relevant_rows']} ({c['fraction']}). 모자라면 Recall은 있는 행만의 값이다.",
              f"짝짓기 통계: {report['pair_stats']}"]
    if report["unpaired"]:
        lines.append(f"짝짓지 못한 행: {report['unpaired']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", type=Path, required=True, help="측정기 결과 폴더(run1~3/rows.jsonl)")

    ap.add_argument("--dataset", type=Path, default=None, help="기본 evals/dataset_v2.jsonl")
    ap.add_argument("--pairing", choices=("thread", "legacy"), default="thread")
    ap.add_argument("--observations-json", type=Path, default=None, help="Langfuse 응답 data 배열을 저장한 파일(오프라인). 없으면 Langfuse에서 읽는다")
    ap.add_argument("--chunks", type=Path, default=None, help="코퍼스 청크 파일(기본 data/index/chunks.jsonl). 정답 위치가 코퍼스에 없는 문항을 분모에서 빼는 공식 규칙에 쓴다")
    ap.add_argument("--no-corpus", action="store_true", help="코퍼스 검사를 하지 않는다(시험용)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--allow-missing", action="store_true")
    a = ap.parse_args(argv)
    run = official_run
    items = run.load_dataset(a.dataset or REPO_ROOT / "evals" / "dataset_v2.jsonl")
    exclusions = run.load_exclusions(REPO_ROOT / "evals" / "exclusions.json")
    chunks_path = a.chunks or REPO_ROOT / "data" / "index" / "chunks.jsonl"
    corpus = run.load_chunks(chunks_path) if chunks_path.is_file() and not a.no_corpus else None
    corpus_by_id = {c.chunk_id: vars(c) for c in corpus} if corpus else None
    runs = load_rows(a.run_dir)
    if not runs:
        raise SystemExit(f"{a.run_dir}에 run*/rows.jsonl이 없다")
    missing = sum(1 for rows in runs.values() for r in rows if not r.get("thread_id"))
    if a.pairing == "thread" and missing:
        print(f"행 {missing}건에 thread_id가 없다: 측정기가 대화 id를 남기지 않았다. 정확한 짝짓기 불가 -> 멈춘다. "
              f"(	hread_id를 남기는 evals/latency/deploy_latency.py로 다시 재거나, 리허설만 --pairing legacy)", file=sys.stderr)
        return 3
    lo, hi = row_window(runs)
    known = None
    if a.observations_json:
        obs = json.loads(a.observations_json.read_text(encoding="utf-8"))
    else:
        lf = Langfuse.from_env()
        obs = lf.search_observations(lo, hi)
        known = lf.thread_ids(lo, hi) if a.pairing == "thread" else None
    try:
        rep = build_report(runs, items, obs, pairing=a.pairing, known_sessions=known, k=a.k, exclusions=exclusions, corpus=corpus,
                           corpus_by_id=corpus_by_id, allow_missing=a.allow_missing)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 4
    text = render(rep, a.run_dir.name)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "recall_langfuse.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        (a.out / "recall_langfuse.md").write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
