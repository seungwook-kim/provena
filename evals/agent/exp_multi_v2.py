"""단일 대 멀티 에이전트 비교 측정 (D-09, G4, PRD 10장 "단일 대 멀티"). 코드만 있고 이 파일을 만든 시점에는 재지 않았다.

같은 평가셋(기본 동결 v2 50건), 같은 서비스 검색기(`exp_service_v1`의 `Searcher`), 같은 답변 모델, 같은 지표(`run_eval.compute_metrics`)로
단일 그래프(`backend.graph.build.build_graph`)와 멀티 그래프(`backend.graph.multi.build_multi_graph`)를 문항마다 번갈아 돌린다.
달라지는 것은 그래프 구조뿐이다: 노드, 프롬프트, 검색, 인용 검사, 근거 판정 코드는 같다(멀티는 단일의 노드를 꺼내 쓴다).

- 번갈아 돌리는 이유: 서비스 검색기의 질문 번역은 `MemoryStore`에서 프로세스 안에 기억된다. 한 쪽을 먼저 다 돌리면 뒤에 도는 쪽이 번역을 기억에서 받는다.
  문항마다 순서를 바꿔(짝수 번째는 단일 먼저, 홀수 번째는 멀티 먼저) 이 차이가 한 쪽으로 쏠리지 않게 하지만, 없애지는 못한다. `--store pg`는 번역을 DB에 저장하므로 두 쪽이 같은 값을 받는다.
- LLM 호출 수: 그래프의 채팅 모델 호출(`classify`, `rewrite`, `judge`, `answer`, `grounding`, 분해)을 `CountingLLM`이 센다. 검색기 안의 번역 호출은 세지 않는다(두 쪽이 같다).
- 비용: 평가 실행기가 문항마다 `cost_usd`를 낸다. 하위 에이전트 안의 호출도 같은 콜백에 잡힌다(`tests/test_multi_graph.py`가 확인한다).
- 기본 경로는 Anthropic API 키를 쓰지 않는다(`--llm anthropic`일 때만). 기본 모델은 로컬 Claude CLI(Haiku 5.5)이고 `VOYAGE_API_KEY`만 읽는다(`exp_confirmed_v1.fix_env`, `load_voyage_key`).
- `--llm openrouter`: 환경 변수 `OPENROUTER_API_KEY`로 OpenRouter의 Haiku 5.5를 부른다(`use_openrouter_env`). OpenRouter 형식이 아닌 키는 거부한다.
- `--llm anthropic`: 환경 변수 `ANTHROPIC_API_KEY`로 Anthropic API의 Haiku 5.5(`claude-haiku-5-5`, CLI와 같은 모델)를 부른다(`use_anthropic_env`). Anthropic 형식이 아닌 키는 거부한다.
- 멀티 LLM 라우팅 갈래 `multi_llm`: `--arms`로 고른다(기본에는 없다). 라우터는 그래프가 받은 모델을 같이 쓰고 `--llm openrouter`로만 돈다. `multi` 갈래는 환경 변수 `SUPERVISOR_ROUTER`와 상관없이 코드 라우팅이다.

    python -m evals.agent.exp_multi_v2 run --out evals/results/agent_v2_single_vs_multi
    python -m evals.agent.exp_multi_v2 run --store pg --out evals/results/agent_v2_single_vs_multi_pg
    python -m evals.agent.exp_multi_v2 run --arms multi --out <폴더>            # 한 쪽만(점검용이 아니면 비교에 쓰지 않는다)
    python -m evals.agent.exp_multi_v2 run --ids 3,7,16 --out <폴더>            # 점검용(partial)
    python -m evals.agent.exp_multi_v2 run --llm openrouter --arms multi,multi_llm --out <폴더>  # 코드 라우팅과 LLM 라우팅 비교
    python -m evals.agent.exp_multi_v2 run --parallel-intake --brief-output --max-research 1 --out <폴더>  # 속도 스위치. 값은 인자로만 정하고 meta의 switches에 남긴다
    python -m evals.agent.exp_multi_v2 run --llm openrouter --reasoning none --judge-answer parallel --skip-first-rewrite --stop-stalled-search --out <폴더>  # 모델 스위치는 meta의 model_switches에 남긴다

결과 폴더: 고른 갈래마다 `rows.jsonl`, `summary.json`이 든 폴더(`single/`, `multi/`, `multi_llm/`)와 `compare.json`(지표, 차이, 달라진 문항 목록, LLM 호출 수, 라우터 기록).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.agent import exp_confirmed_v1 as X
from evals.agent import exp_service_v1 as S
from evals.agent.run_eval import compute_metrics, run_item, verify_frozen
from evals.retrieval import exp_decompose_v1 as D
from evals.retrieval.run import load_dataset, load_exclusions

ROOT = D.ROOT
DATASET = ROOT / "evals" / "dataset_v2.jsonl"
ARMS = ("single", "multi")  # 기본 비교
ALL_ARMS = (*ARMS, "multi_llm")  # 고를 수 있는 갈래. `multi_llm`은 Supervisor LLM 라우팅이다
ARM_ROUTERS = {"multi": "code", "multi_llm": "llm"}  # 환경 변수가 측정 갈래를 바꾸지 못하게 값을 박는다
COMPARE_FIELDS = ("result", "answered", "cited", "gold_hit", "refuse_reason", "retries")  # 두 쪽 사이에서 달라졌는지 보는 문항 값


class CountingLLM:
    """채팅 모델을 감싸 `invoke` 호출 수를 센다. 호출은 그대로 넘기고 응답을 바꾸지 않는다."""

    def __init__(self, llm: Any):
        self.llm = llm
        self.calls = 0

    def invoke(self, *args, **kwargs):
        self.calls += 1
        return self.llm.invoke(*args, **kwargs)


OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"


def use_openrouter_env() -> None:
    """`--llm openrouter`의 환경을 고정한다. 키는 `OPENROUTER_API_KEY`에서만 가져오고 값은 출력하지 않는다.

    주소를 바꾸는 값과 다른 제공자 키를 지워 기본 OpenRouter 주소로만 나가게 한다.
    """
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key.startswith("sk-or-"):
        raise SystemExit("OPENROUTER_API_KEY가 없거나 OpenRouter 형식이 아니라 멈춘다")
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "ANTHROPIC_API_KEY", "DEMO_MODE", "LLM_RECORD"):
        os.environ.pop(name, None)
    os.environ["LLM_PROVIDER"] = "openrouter"
    os.environ["LLM_MODEL"] = OPENROUTER_MODEL
    os.environ["LLM_API_KEY"] = key


ANTHROPIC_MODEL = "claude-haiku-5-5"  # claude_cli와 같은 모델


def use_anthropic_env() -> None:
    """`--llm anthropic`의 환경을 고정한다(API 경로 지연 측정용). 키는 `ANTHROPIC_API_KEY`에서만 가져오고 값은 출력하지 않는다.

    주소를 바꾸는 값, 폴백 모델, 다른 제공자 키를 지워 기본 Anthropic 주소로 CLI와 같은 모델(Haiku 5.5)만 부른다.
    """
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key.startswith("sk-ant-"):
        raise SystemExit("ANTHROPIC_API_KEY가 없거나 Anthropic 형식이 아니라 멈춘다")
    for name in ("LLM_BASE_URL", "LLM_FALLBACK_MODEL", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "DEMO_MODE", "LLM_RECORD", "LLM_REASONING", "LLM_PROVIDER_SORT"):
        os.environ.pop(name, None)
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["LLM_MODEL"] = ANTHROPIC_MODEL
    os.environ["LLM_API_KEY"] = key
    # 추론 수준을 claude_cli와 같게: CLI 기본 `--effort low`, 단계별 answer=medium, grounding=medium(`claude_cli_model.py`의 기본값과 같은 환경 변수를 읽는다)
    effort = (os.environ.get("CLAUDE_CLI_EFFORT") or "low").strip().lower()
    os.environ["LLM_EFFORT"] = effort if effort in ("low", "medium", "high", "xhigh", "max") else ""
    os.environ["LLM_EFFORT_BY_TASK"] = os.environ.get("CLAUDE_CLI_EFFORT_BY_TASK") or "answer=medium,grounding=medium"


def connected_parts(retriever: Callable, llm: Any) -> dict:
    """결정표와 합동 검토를 질문 그래프에 연결한다(결정 0064). 운영 DB에 승인된 결정표가 없으므로 빈 저장소를 그대로 쓰고, 승인을 지어내지 않는다.
    합동 검토는 사람 승인에서 멈추므로 체크포인터가 필요하고, 그 문항은 답을 내지 않은 행으로 남는다."""
    from langgraph.checkpoint.memory import InMemorySaver

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.review import build_review_graph
    from backend.graph.departments.store import InMemoryIssueTableStore

    return {"checkpointer": InMemorySaver(), "decision_repo": InMemoryDecisionRepo(),
            "review_graph": build_review_graph(retriever, None, llm=llm, store=InMemoryIssueTableStore())}


def build_arm_graph(arm: str, retriever: Callable, llm: Any, **kw):
    """`arm`의 그래프. 같은 인자(`retriever`, `llm`, `kw`)를 단일과 멀티에 그대로 넘긴다. 질문 분해는 서비스 경로처럼 `decompose=True`가 기본이다."""
    from backend.graph.build import build_graph
    from backend.graph.multi import build_multi_graph

    if arm not in ALL_ARMS:
        raise ValueError(f"알 수 없는 경로: {arm}")
    if arm == "single":
        return X.RecordingGraph(build_graph(retriever, **{"decompose": True, **kw}, llm=llm))
    return X.RecordingGraph(build_multi_graph(retriever, **{"decompose": True, **kw}, llm=llm, router=ARM_ROUTERS[arm]))


@dataclass
class Arm:
    name: str
    graph: Any  # RecordingGraph
    rec: Any  # RecordingSearch (set_item, calls, errors)
    llm: CountingLLM
    rows: list[dict] = field(default_factory=list)


class PageSearch:
    """B4 페이지 범위 재검색(`--page-research`)을 검색기(`Searcher.search_pages`)에 직접 부르고, 경로의 검색 기록(`rec.calls`)에 kind="page"로 남긴다.
    MCP 도구 입력에 페이지 범위가 없어 MCP를 거치지 않는다. 결과는 바꾸지 않는다."""

    def __init__(self, searcher, rec):
        self.searcher, self.rec = searcher, rec

    def __call__(self, query: str, rule_seqs: list[int], org: str | None, as_of: str | None, k: int):
        t0 = time.perf_counter()
        out = self.searcher.search_pages(query, rule_seqs, org, as_of, k)
        self.rec.calls.append({"n": len(self.rec.calls) + 1, "kind": "page", "graph_query": query, "pages": list(rule_seqs), "org": org, "as_of": as_of,
                               "k_requested": k, "returned": [c.chunk_id for c in out], "trace": None, "wall_s": round(time.perf_counter() - t0, 3)})
        return out


class IntroSearch:
    """R3 도입부 채우기(`--intro-fill`)를 검색기(`Searcher.intro_fill`)에 직접 부르고, 검색 기록(`rec.calls`)에 kind="intro"로 남긴다. 결과는 바꾸지 않는다."""

    def __init__(self, searcher, rec):
        self.searcher, self.rec = searcher, rec

    def __call__(self, chunks: list, query: str, org: str | None, as_of: str | None):
        t0 = time.perf_counter()
        out = self.searcher.intro_fill(chunks, query, org, as_of)
        if out:  # 더한 것이 있을 때만 남긴다(검색마다 불리므로)
            self.rec.calls.append({"n": len(self.rec.calls) + 1, "kind": "intro", "graph_query": query, "org": org, "as_of": as_of,
                                   "k_requested": 0, "returned": [c.chunk_id for c in out], "trace": None, "wall_s": round(time.perf_counter() - t0, 3)})
        return out


def run_arm_item(arm: Arm, item: dict, run_id: str) -> dict:
    """한 경로로 문항 하나를 돌려 행을 만든다. 단일과 멀티가 같은 행 칸을 낸다(멀티는 에이전트 기록이 더 붙는다)."""
    arm.rec.set_item(item)
    calls0 = arm.llm.calls
    row = run_item(arm.graph, item, run_id=f"{run_id}-{arm.name}")  # 경로마다 Langfuse 세션을 따로 둔다
    out = arm.graph.last or {}
    X.add_recorded(row, out)
    row["arm"] = arm.name
    row["llm_calls"] = arm.llm.calls - calls0
    row["sub_queries"] = out.get("sub_queries")
    row["decompose_source"] = out.get("decompose_source")
    row["retrieval_calls"] = arm.rec.calls
    row["first_searches"] = sum(c["kind"] == "first" for c in arm.rec.calls)
    row["requery_searches"] = sum(c["kind"] == "requery" for c in arm.rec.calls)
    row["stopped_at_approval"] = bool(out.get("__interrupt__"))
    row["review_status"] = out.get("review_status") or ""
    row["judge_missing"] = out.get("judge_missing")  # C2: 판정 기록(점수에는 쓰지 않는다)
    row["judge_partial"] = out.get("judge_partial")
    row["judge_scope"] = out.get("judge_scope")
    row["sub_research"] = out.get("sub_research") or ""
    row["page_searches"] = sum(c["kind"] == "page" for c in arm.rec.calls)
    if out.get("judge_checks_log") is not None or out.get("answer_facts") is not None:  # FL(`--facts-log`): 진단 기록(점수에는 쓰지 않는다)
        row["judge_checks_log"] = out.get("judge_checks_log")
        row["answer_facts"] = out.get("answer_facts")
    if out.get("best2_log") is not None:  # BO2(`--answer-best2`): 두 답 후보의 인용과 고른 이유
        row["best2_log"] = out.get("best2_log")
    row["judge_none"] = bool(out.get("judge_none"))  # R(`--refuse-on-none`)이 걸렸는지
    row["context_chunks"] = [{"chunk_id": c.get("chunk_id"), "rule_seq": c.get("rule_seq"), "title": c.get("title"), "text": c.get("text")} for c in out.get("chunks") or []]  # 저장 답변 채점(RAGAS)의 입력. 답에 쓴 청크는 `cited`의 id로 고른다
    if arm.name in ARM_ROUTERS:
        row["agent_trace"] = out.get("agent_trace")
        row["supervisor_log"] = out.get("supervisor_log")
    return row


def run_arms(items: list[dict], arms: list[Arm], run_id: str, *, on_row: Callable[[Arm, dict], None] | None = None) -> dict[str, list[dict]]:
    """문항마다 모든 경로를 번갈아 돌린다(순서는 문항마다 바뀐다). 검색기 오류가 기록되면 멈춘다."""
    for i, item in enumerate(items):
        for arm in (arms if i % 2 == 0 else list(reversed(arms))):
            row = run_arm_item(arm, item, run_id)
            arm.rows.append(row)
            if on_row:
                on_row(arm, row)
            if arm.rec.errors:
                raise SystemExit(f"검색 오류로 중단({arm.name}, 문항 {item['id']}): {arm.rec.errors[-1]}")
    return {a.name: a.rows for a in arms}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _changed(rows: dict[str, list[dict]], base: str, other: str) -> list[dict]:
    """두 갈래 사이에서 값이 달라진 문항."""
    by_base = {x["id"]: x for x in rows[base]}
    changed = []
    for x in rows[other]:
        y = by_base.get(x["id"])
        if y is None:
            continue
        diff = {f: {base: y.get(f), other: x.get(f)} for f in COMPARE_FIELDS if y.get(f) != x.get(f)}
        if diff:
            changed.append({"id": x["id"], "kind": x["kind"], "changed": diff})
    return changed


def _routing(rows: list[dict]) -> dict:
    """LLM 라우터가 실제로 고른 횟수, 코드로 대체한 횟수, 코드와 다르게 고른 횟수."""
    log = [e for r in rows for e in r.get("supervisor_log") or [] if "code_choice" in e]
    return {
        "llm_routed": sum(e["router"] == "llm" for e in log),
        "fallbacks": sum("fallback" in e for e in log),
        "differs_from_code": sum(e["router"] == "llm" and (e.get("closed_by") or e["to"]) != e["code_choice"] for e in log),
    }


def compare(rows: dict[str, list[dict]]) -> dict:
    """갈래별 지표, 차이(멀티 - 단일, LLM 라우팅 - 코드 라우팅), 달라진 문항, 호출 수. 한 쪽만 있으면 지표만 낸다."""
    metrics = {name: compute_metrics(r) for name, r in rows.items()}
    out: dict = {"metrics": metrics, "totals": {}}
    for name, r in rows.items():
        out["totals"][name] = {
            "items": len(r),
            "llm_calls": sum(x["llm_calls"] for x in r),
            "first_searches": sum(x["first_searches"] for x in r),
            "requery_searches": sum(x["requery_searches"] for x in r),
            "latency_mean_s": round(sum(x["latency_s"] for x in r) / len(r), 3) if r else None,
        }
    if set(ARMS) <= set(rows):
        s, m = metrics["single"], metrics["multi"]
        out["delta_multi_minus_single"] = {k: round(m[k] - s[k], 6) for k in s if _num(s[k]) and _num(m.get(k))}
        changed = _changed(rows, "single", "multi")
        out["changed_items"] = changed
        out["changed_count"] = len(changed)
        out["note"] = ("모델 응답은 같은 입력이어도 실행마다 달라질 수 있어 달라진 문항이 구조 때문이라고 단정하지 않는다. "
                       "차이가 1~4문항이면 이 목록을 EVAL_REPORT.md에 적는다(GATES G5). 개선이 없으면 없다고 적는다.")
    if "multi_llm" in rows:
        out["routing"] = {"multi_llm": _routing(rows["multi_llm"])}
        if "multi" in rows:
            c, m = metrics["multi"], metrics["multi_llm"]
            out["delta_multi_llm_minus_multi"] = {k: round(m[k] - c[k], 6) for k in c if _num(c[k]) and _num(m.get(k))}
            out["changed_multi_llm_vs_multi"] = _changed(rows, "multi", "multi_llm")
    return out


def _write_arm(out: Path, name: str, rows: list[dict], meta: dict) -> None:
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps({"meta": {**meta, "arm": name}, "metrics": compute_metrics(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")


def chosen_switches(args) -> dict:
    """이번 측정의 속도 스위치. 환경 변수가 측정을 바꾸지 못하게 인자로만 정해 그래프에 그대로 넘긴다."""
    return {
        "parallel_intake": args.parallel_intake,
        "brief_output": args.brief_output,
        "max_research": args.max_research,
        "judge_answer": args.judge_answer,
        "skip_first_rewrite": args.skip_first_rewrite,
        "stop_stalled_search": args.stop_stalled_search,
        "ground_skip_backed": args.ground_skip_backed,
        "json_only": args.json_only,
    }


class MergeTaskMap(argparse.Action):
    """`단계=값,단계=값` 목록을 여러 번 주면 덮어쓰지 않고 단계별로 합친다(뒤에 준 같은 단계 값만 바꾼다).
    61.8에서 `--reasoning-by-task answer=low`를 더 주자 앞의 `decompose=low`가 통째로 사라진 일을 막는다."""

    def __call__(self, parser, namespace, values, option_string=None):
        merged: dict[str, str] = {}
        for part in [*str(getattr(namespace, self.dest, "") or "").split(","), *str(values or "").split(",")]:
            if part.strip():
                if "=" not in part:
                    parser.error(f"{option_string}는 단계=값 목록이다: {part!r}")
                task, value = part.split("=", 1)
                merged.pop(task.strip(), None)
                merged[task.strip()] = value.strip()
        setattr(namespace, self.dest, ",".join(f"{k}={v}" for k, v in merged.items()))


def chosen_model_switches(args) -> dict:
    """모델을 만들 때 읽는 스위치(`backend/services/llm.py`). 번역 호출에도 같이 걸리므로 환경 변수로 넣되, 값은 인자로만 정한다. 인자를 안 주면 빈 값으로 덮어 끈다."""
    return {"LLM_REASONING": args.reasoning, "LLM_PROVIDER_SORT": args.provider_sort, "LLM_DEADLINE_S": args.llm_deadline, "LLM_HEDGE_S": args.llm_hedge, "LLM_MAX_RETRIES": args.llm_retries,
            "LLM_TRACE_DETAIL": "1" if args.trace_detail else "", "LLM_JSON_REMINDER": "1" if args.json_reminder else "", "LLM_REASONING_BY_TASK": args.reasoning_by_task, "GRAPH_SECTION_KEEPS_RESEARCH": "1" if args.section_keeps_research else "", "GRAPH_ANSWER_WAIT_S": str(args.answer_wait) if args.answer_wait else "", "GRAPH_ANSWER_BUDGET_S": str(args.answer_budget) if args.answer_budget else "", "LLM_STRUCTURED": args.structured, "GRAPH_JUDGE_QUERY": "1" if args.judge_query else "", "EMBED_KEEPALIVE": "1" if args.embed_keepalive else "", "SEARCH_PARALLEL_SUBS": "1" if args.parallel_subs else "",
            "GRAPH_KEEP_PRODUCT_NAME": "1" if args.keep_product_name else "", "GRAPH_REQUERY_TERMS": "1" if args.requery_terms else "",
            # 첫 검색어 코드 보강(기본 꺼짐, backend/graph/query_plan.py)
            "GRAPH_QUERY_BRANCHES": "1" if args.query_branches else "",
            # 놓친 문항 해결안(기본 꺼짐, backend/graph/answer_fixes.py)
            "GRAPH_CITE_EXPAND": "1" if args.cite_expand else "", "GRAPH_CITE_MULTI": "1" if args.cite_multi else "", "GRAPH_TEAM_LAST": "1" if args.team_last else "",
            "GRAPH_KEEP_CITES": "1" if args.keep_cites else "", "GRAPH_SUB_RESEARCH": "1" if args.sub_research else "", "GRAPH_PAGE_RESEARCH": "1" if args.page_research else "",
            "GRAPH_REQUERY_VOCAB": "1" if args.requery_vocab else "", "GRAPH_UNKNOWN_NAME": "1" if args.unknown_name else "",
            # 분해 상한(기본 꺼짐): 이 초 안에 분해가 오지 않으면 원 질문 하나로 검색한다
            "GRAPH_DECOMPOSE_CAP_S": str(args.decompose_cap) if args.decompose_cap else "",
            # 재검색 수정안(기본 꺼짐): R 첫 판정 전무면 바로 거절, 가 부분 판정 뒤 재검색을 문맥 페이지 안 검색으로 교체
            "GRAPH_REFUSE_ON_NONE": "1" if args.refuse_on_none else "", "GRAPH_RESEARCH_SAME_PAGE": "1" if args.research_same_page else "",
            # 남은 문항 수정안(기본 꺼짐): A1b 문장 공유 인용 보강
            "GRAPH_CITE_PHRASE": "1" if args.cite_phrase else "",
            # Q 근거 확인을 구절 먼저 찾고 판정으로
            "GRAPH_GROUNDING_QUOTE": "1" if args.grounding_quote else "",
            # P 질문에 없는 한정어가 붙은 페이지만 인용한 문장 빼기
            "GRAPH_DROP_SCOPED_CITES": "1" if args.drop_scoped_cites else "",
            # R3 도입부 채우기
            "GRAPH_INTRO_FILL": "1" if args.intro_fill else "",
            # SN 범위 한정 scope_note 거절, CP 답의 근거 고르는 순서
            "GRAPH_SCOPE_NOTE_REFUSE": "1" if args.scope_note_refuse else "",
            "GRAPH_CITE_PICK": "1" if args.cite_pick else "",
            # SS 페이지 재검색이 문맥에 있는 청크 건너뛰기, CS 되풀이 문장 쪽 인용만 남기기, PT 안내 구절뿐인 근거 거절
            "GRAPH_REQUERY_SKIP_SEEN": "1" if args.requery_skip_seen else "", "GRAPH_CITE_CONSENSUS": "1" if args.cite_consensus else "",
            "GRAPH_POINTER_REFUSE": "1" if args.pointer_refuse else "",
            # SP 분해를 기다리는 동안 원 질문으로 첫 검색·판정을 미리 돌리기
            "GRAPH_SPECULATE_FIRST": "1" if args.speculate_first else "",
            # UR 다시 쓰기가 처음 답을 그대로 내면 한 번 더 판정
            "GRAPH_UNCHANGED_REJUDGE": "1" if args.unchanged_rejudge else "",
            # 대조군: HEAD 뒤 기본 프롬프트에 늘 붙게 된 문장을 HEAD 때 문장으로(새 규칙 아님)
            "GRAPH_PROMPTS_HEAD": "1" if args.prompts_head else "",
            # 조사 해법(기본 꺼짐): 판정·근거 확인 다수결, 판정을 인용 먼저
            "GRAPH_JUDGE_VOTE": "1" if args.judge_vote else "", "GRAPH_JUDGE_QUOTE": "1" if args.judge_quote else "",
            "SEARCH_SUB_MERGE": "1" if args.sub_merge else "",
            "GRAPH_FACTS_LOG": "1" if args.facts_log else "",
            "GRAPH_ANSWER_BEST2": "1" if args.answer_best2 else "", "GRAPH_BEST2_SAMEDOC": "1" if args.best2_samedoc else "",
            # SG 답 후보가 나오는 대로 근거 판정을 미리 부르고 같은 입력이면 그 결과를 쓴다
            "GRAPH_SPECULATE_GROUND": "1" if args.speculate_ground else "",
            # 사전 등록 62.14: 검색 hedge(초, 0이면 끔)
            "SEARCH_HEDGE": "1" if args.search_hedge else "", "SEARCH_HEDGE_S": str(args.search_hedge) if args.search_hedge else ""}


def check_dataset(path: Path, sha256: str = "") -> None:
    """평가셋 확인. 기본은 동결 목록(`evals/FROZEN.json`)이다. `--dataset-sha256`을 주면 그 해시와 같은 파일만 돈다(동결 목록 밖 검증 문항, 해시는 사전 등록에 적는다)."""
    if not sha256:
        verify_frozen(path)
        return
    if path == DATASET:
        raise SystemExit("--dataset-sha256은 --dataset으로 다른 평가셋을 줄 때만 쓴다")
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256.strip().lower():
        raise SystemExit(f"평가셋 해시가 다르다: {path.name}")


def run_cmd(args) -> int:
    if "multi_llm" in args.arms.split(",") and args.llm != "openrouter":  # 키를 만지기 전에 멈춘다
        raise SystemExit("multi_llm 갈래는 --llm openrouter로만 돈다(Haiku 5.5)")
    if args.llm == "openrouter":
        use_openrouter_env()
    elif args.llm == "anthropic":
        use_anthropic_env()
        if args.effort:  # --llm anthropic 전용: CLI 기본 추론 수준 대신 이 값(none은 생각 끔)
            os.environ["LLM_EFFORT"] = args.effort
        if args.effort_by_task:
            os.environ["LLM_EFFORT_BY_TASK"] = args.effort_by_task
    else:
        X.fix_env()
    X.load_voyage_key()
    model_switches = chosen_model_switches(args)
    os.environ.update(model_switches)
    dataset = Path(args.dataset) if args.dataset else DATASET
    check_dataset(dataset, args.dataset_sha256)
    from backend.services.llm import get_chat_model, is_demo_mode
    from evals.agent import tracking

    if is_demo_mode():
        raise SystemExit("데모 모드다: 실제 모델 설정이 아니라 멈춘다")
    names = [a for a in ALL_ARMS if a in args.arms.split(",")]
    if not names:
        raise SystemExit(f"--arms는 {','.join(ALL_ARMS)} 중에서 고른다")
    excluded = load_exclusions(ROOT / "evals" / "exclusions.json")
    items = [it for it in load_dataset(dataset) if str(it["id"]) not in excluded]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if str(it["id"]) in want]
    if args.repeat > 1:  # 문항 반복 확인: 고른 문항만 여러 번(점수로 쓰지 않는다). 전체 문항 반복은 하지 않는다
        if not args.ids:
            raise SystemExit("--repeat는 --ids와 같이만 쓴다(고른 문항 반복 확인)")
        items = [it for _ in range(args.repeat) for it in items]
    if not items:
        raise SystemExit("돌릴 문항이 없다")
    switches = chosen_switches(args)
    use_pg = args.store == "pg"
    searcher, setup = S.build_pg_searcher() if use_pg else S.build_searcher()
    arms = []
    for name in names:
        rec = S.RecordingSearch(searcher)
        llm = CountingLLM(get_chat_model())
        server = S.mcp_server_for(rec, use_pg) if args.via_mcp else None  # 경로마다 서버를 따로 둔다. 기록기(rec)가 경로별이기 때문이다
        retriever = rec
        if server is not None:
            from backend.graph.mcp_retriever import make_mcp_retriever
            retriever = make_mcp_retriever(server)
        joined = connected_parts(retriever, llm) if args.connected else {}
        pages = {"page_search": PageSearch(searcher, rec)} if args.page_research or args.research_same_page else {}
        if args.intro_fill:
            pages["intro_search"] = IntroSearch(searcher, rec)
        arms.append(Arm(name, build_arm_graph(name, retriever, llm, section_reader=S.section_reader_for(server, use_pg), **joined, **switches, **pages), rec, llm))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_id = tracking.new_run_id("question")

    seen: dict[tuple[str, Any], int] = {}

    def show(arm: Arm, row: dict) -> None:
        key = (arm.name, row["id"])
        row["repeat"] = seen[key] = seen.get(key, -1) + 1  # 같은 문항의 몇 번째 반복인지(0부터). 반복이 없으면 0
        extra = f" 에이전트 {'>'.join(row['agent_trace'] or []) or '-'}" if arm.name in ARM_ROUTERS else ""
        print(f"[{arm.name}] 문항 {row['id']}: {row['result']} 재시도 {row['retries']} LLM {row['llm_calls']}회 검색 {row['first_searches']}+{row['requery_searches']} "
              f"{row['latency_s']}초{extra}", flush=True)
        with (out / f"{arm.name}.partial.jsonl").open("a", encoding="utf-8") as f:  # 진행 중에 볼 수 있게 행마다 남긴다. 끝나면 갈래 폴더의 rows.jsonl이 정본이다
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    warmed = searcher.store.warm(searcher.cfg.embed_model, as_of="2026-10-27") if args.warm and use_pg else None
    rows = run_arms(items, arms, run_id, on_row=show)
    meta = {
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "service_path": S.SERVICE_PATH_PG if use_pg else S.SERVICE_PATH,
        "store": "PgStore" if use_pg else "MemoryStore",
        "search": {**setup, "first_search": "그래프가 원 질문(한국어)과 하위 질문을 `Searcher.search`에 넘긴다", "requery": "재작성 검색어(영어)를 분해 없이 넘긴다"},
        "llm": {"provider": os.environ["LLM_PROVIDER"], "model": os.environ["LLM_MODEL"], "anthropic_api_key": "unused",
                **({"effort": os.environ.get("LLM_EFFORT") or "api_default", "effort_by_task": os.environ.get("LLM_EFFORT_BY_TASK") or ""} if os.environ["LLM_PROVIDER"] == "anthropic" else {})},
        "arms": names,
        "routers": {n: ARM_ROUTERS[n] for n in names if n in ARM_ROUTERS},
        "switches": switches,
        "model_switches": model_switches,
        "via_mcp": bool(args.via_mcp),
        "warm": warmed,
        "connected": "결정표(승인된 표 없음)와 합동 검토(메모리, 승인함 없음) 연결" if args.connected else "",
        "order": f"문항마다 순서를 뒤집어 번갈아 돌림(짝수 번째 {names[0]} 먼저, 홀수 번째 {names[-1]} 먼저)",
        "translation_cache": "MemoryStore는 프로세스 안에서 번역을 기억한다. 번갈아 돌려도 뒤에 도는 쪽이 번역을 기억에서 받을 수 있다" if not use_pg else "PgStore는 번역을 DB에 저장한다",
        "excluded": sorted(excluded),
        "partial": bool(args.ids),
        "repeat": args.repeat,
        "run_id": run_id,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    for name in names:
        _write_arm(out, name, rows[name], meta)
    result = compare(rows)
    (out / "compare.json").write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in names:
        tracking.record_run_scores(f"{run_id}-{name}", {k: v for k, v in result["metrics"][name].items() if k != "n"})
    print(json.dumps({k: result[k] for k in ("totals", "delta_multi_minus_single", "changed_count", "delta_multi_llm_minus_multi", "routing") if k in result}, ensure_ascii=False, indent=2))
    if use_pg:
        searcher.store.pool.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="단일과 멀티를 같은 문항으로 번갈아 실행(서비스 Searcher, 기본 MemoryStore)")
    p.add_argument("--store", choices=("memory", "pg"), default="memory", help="검색 저장소. pg는 .env의 DATABASE_URL로 운영 DB를 읽는다")
    p.add_argument("--llm", choices=("claude_cli", "openrouter", "anthropic"), default="claude_cli",
                   help="답변 모델 경로. openrouter는 환경 변수 OPENROUTER_API_KEY, anthropic은 ANTHROPIC_API_KEY를 쓴다(같은 Haiku 5.5, API 경로 지연 측정용)")
    p.add_argument("--dataset", help="평가셋 경로. 기본은 동결 v2이고, 동결된 파일만 돈다")
    p.add_argument("--dataset-sha256", default="", help="동결 목록 밖 평가셋(--dataset)을 이 sha256과 같을 때만 돌린다. 기본 꺼짐(동결 목록으로 확인)")
    p.add_argument("--arms", default=",".join(ARMS), help=f"돌릴 경로(쉼표, {','.join(ALL_ARMS)}). 기본 single,multi. multi_llm은 --llm openrouter가 필요하다")
    p.add_argument("--ids", help="쉼표로 고른 문항만 돈다(partial, 점수로 쓰지 않는다)")
    p.add_argument("--repeat", type=int, default=1, help="문항 반복 확인: --ids로 고른 문항을 이 횟수만큼 돈다(행마다 repeat 번호). 기본 1")
    p.add_argument("--via-mcp", action="store_true", help="검색을 같은 프로세스 MCP 서버로 부른다")
    p.add_argument("--llm-hedge", default="", help="이 초 안에 응답이 없으면 같은 요청을 하나 더 보내 먼저 온 답을 쓴다(--llm-deadline과 같이)")
    p.add_argument("--llm-deadline", default="", help="HTTP 시도별 응답 상한(초). 재시도마다 늘어난다. 기본은 없음")
    p.add_argument("--llm-retries", default="", help="시간 초과와 일시 오류의 재요청 횟수. 기본은 SDK 값")
    p.add_argument("--json-reminder", action="store_true", help="입력 끝에 JSON만 내라는 문장을 더한다. 글로 답해 호출을 다시 하는 일을 줄인다")
    p.add_argument("--trace-detail", action="store_true", help="llm_trace에 공급자, 시도 횟수, 요청 id, 답과 판정의 응답 원문을 더한다")
    p.add_argument("--parallel-subs", action="store_true", help="하위 질문을 동시에 찾는다. 순위는 같다")
    p.add_argument("--warm", action="store_true", help="측정 전에 표의 벡터로 색인 페이지를 미리 읽는다(--store pg)")
    p.add_argument("--connected", action="store_true", help="결정표와 합동 검토를 질문 그래프에 연결한다(결정 0064). 기본 꺼짐")
    p.add_argument("--parallel-intake", action="store_true", help="질의 분석, 첫 재작성, 첫 분해를 동시에 부른다. 기본 꺼짐")
    p.add_argument("--brief-output", action="store_true", help="판정의 이유 설명을 짧게 쓰게 한다. 기본 꺼짐")
    p.add_argument("--max-research", type=int, choices=(0, 1, 2), default=2, help="재검색 상한. 기본 2")
    p.add_argument("--reasoning-by-task", default="", action=MergeTaskMap, help="단계별 추론 수준. 예: decompose=low,judge=low. 나머지는 --reasoning. 여러 번 주면 단계별로 합친다")
    p.add_argument("--effort", default="", choices=("", "none", "low", "medium", "high", "xhigh", "max"),
                   help="--llm anthropic 전용 기본 추론 수준(none은 생각 끔). 비우면 claude_cli 기본(low)과 같게")
    p.add_argument("--effort-by-task", default="", action=MergeTaskMap,
                   help="--llm anthropic 전용 단계별 추론 수준. 예: decompose=low,answer=low. 비우면 claude_cli 기본(answer=medium,grounding=medium)과 같게")
    p.add_argument("--section-keeps-research", action="store_true", help="섹션 읽기가 재검색 기회를 쓰지 않는다")
    p.add_argument("--cite-expand", action="store_true", help="A1: 근거 판정 뒤 같은 숫자·단위와 영어 내용어 겹침 0.3 이상인 문맥 청크를 인용에 2개까지 더한다. 기본 꺼짐")
    p.add_argument("--cite-multi", action="store_true", help="A3: 같은 사실을 다른 페이지가 말하면 근거를 3개까지 표시하게 한다. 기본 꺼짐")
    p.add_argument("--team-last", action="store_true", help="A4: 질문이 팀을 말하지 않으면 제목에 Team, Group이 든 청크를 답 입력 뒤로 보낸다. 기본 꺼짐")
    p.add_argument("--keep-cites", action="store_true", help="A5: 근거 판정 뒤 다시 쓴 답에 지적받지 않은 문장의 인용을 넘긴다. 기본 꺼짐")
    p.add_argument("--sub-research", action="store_true", help="B1: 일부 근거로 끝나는 나뉜 질문에서 빠진 하위 질문을 원래 문구로 한 번 더 찾는다. 기본 꺼짐")
    p.add_argument("--page-research", action="store_true", help="B4: B1과 같은 때에 그 하위 질문을 문맥의 페이지 안에서만 다시 찾는다. 기본 꺼짐")
    p.add_argument("--requery-vocab", action="store_true", help="B2: 판정 재검색어가 하위 질문의 영어 용어를 지키고 빠진 사실은 받는 쪽 동사로 쓴다(--judge-query와 같이). 기본 꺼짐")
    p.add_argument("--unknown-name", action="store_true", help="D1: 질문의 영문 구가 코퍼스 전체에 없으면 검색 없이 되묻는다. 기본 꺼짐")
    p.add_argument("--refuse-on-none", action="store_true", help="R: 첫 근거 판정이 전무(충분도 부분도 아니고 되묻기도 없음)면 재검색 없이 거절한다. 기본 꺼짐")
    p.add_argument("--research-same-page", action="store_true", help="가: 부분 판정 뒤 재검색을 전체 검색 대신 문맥에 든 페이지 안 검색으로 바꾼다(횟수 그대로). 기본 꺼짐")
    p.add_argument("--cite-phrase", action="store_true", help="A1b: 근거 판정 뒤 인용 청크와 영어 단어 12개 이상을 그대로 공유하는 다른 페이지 청크를 인용에 2개까지 더한다(다른 팀 페이지 제외). 기본 꺼짐")
    p.add_argument("--grounding-quote", action="store_true", help="Q: 근거 확인이 주장마다 받치는 영어 구절을 먼저 복사(없으면 NOTHING FOUND)하고 판정한다. 번역·말 바꿈과 제목 경로 간접 근거를 인정. 기본 꺼짐")
    p.add_argument("--intro-fill", action="store_true", help="R3: 첫 검색 문맥에 같은 페이지 판 청크가 3개 이상이면 그 페이지 도입부 절 청크 중 질문 벡터와 가장 가까운 1개(절이 2개 이하 청크면 절 전체)를 더한다. 기본 꺼짐")
    p.add_argument("--scope-note-refuse", action="store_true", help="SN: 충분 판정의 scope_note가 자료 범위 한정과 질문 내용 부재를 함께 말하면 재검색 없이 거절한다. 기본 꺼짐")
    p.add_argument("--requery-skip-seen", action="store_true", help="SS: 페이지 재검색(--research-same-page)이 문맥에 이미 있는 청크를 건너뛰고 새 청크 3개만 더하며, 그 뒤에는 섹션 읽기를 하지 않는다. 기본 꺼짐")
    p.add_argument("--best2-samedoc", action="store_true", help="BO2SD: --answer-best2의 둘째 규칙에서 S 청크와 같은 문서(rule_seq)인 S 밖 인용은 세지 않고 다른 문서 인용 수만 비교한다. 기본 꺼짐")
    p.add_argument("--answer-best2", action="store_true", help="BO2: 답을 같은 입력으로 두 번 쓰고 판정 구절(--judge-quote)이 든 문맥 청크를 더 많이, 그 밖 청크를 더 적게 인용한 쪽을 고른다. 구절이 없으면 첫 답. 행에 best2_log. 기본 꺼짐")
    p.add_argument("--facts-log", action="store_true", help="FL(진단): 판정 checks와 첫 답의 asked·picks를 행에 남긴다(judge_checks_log, answer_facts). 답 경로는 그대로다. 기본 꺼짐")
    p.add_argument("--sub-merge", action="store_true", help="분해 검색에서 전체 질문도 후보에 넣고, 하위 질문마다 한 자리를 먼저 준 뒤 남은 자리를 유사도 순으로 채운다(k와 임베딩은 그대로). 기본 꺼짐")
    p.add_argument("--judge-vote", action="store_true", help="판정(judge)과 근거 확인(grounding)을 같은 입력으로 병렬 3번 부르고 결론이 2표 같으면 확정한다. 빠진 사실과 받쳐지지 않는 문장은 2표 이상만 남긴다. 기본 꺼짐")
    p.add_argument("--judge-quote", action="store_true", help="판정이 사실마다 자료 원문 구절을 먼저 복사하고(없으면 NOTHING FOUND) 결론은 코드가 그 목록에서 정한다(--structured의 judge 대조 칸 대신). 기본 꺼짐")
    p.add_argument("--prompts-head", action="store_true", help="대조군: HEAD(11/6 D6 API 커밋) 뒤 스위치 없이 기본 프롬프트와 입력에 늘 붙게 된 문장을 빼고 HEAD 때 문장을 쓴다. 스위치로 붙는 규칙은 그대로다(backend/prompts/question.py at_head). 기본 꺼짐")
    p.add_argument("--speculate-ground", action="store_true", help="SG: 답 후보(추론 답, 빠른 답, 둘째 답)가 나오는 대로 인용 검사와 같은 검사를 거쳐 근거 판정을 미리 부르고, 뽑힌 답의 판정 입력이 같으면 그 결과를 쓴다. 판정 입력·기준은 그대로다. 기본 꺼짐")
    p.add_argument("--search-hedge", type=float, default=0, help="이 초 안에 첫 검색(질문 임베딩 + 벡터 질의)이 안 오면 같은 검색을 한 번 더 보내 먼저 온 결과를 쓴다. 예: 1.5. 기본 꺼짐(0)")
    p.add_argument("--unchanged-rejudge", action="store_true", help="UR: 근거 판정 사유를 받은 다시 쓰기가 처음 답을 그대로 내면 처음 답을 한 번 더 판정하고, 받쳐지면 그대로 낸다. 기본 꺼짐")
    p.add_argument("--speculate-first", action="store_true", help="SP: 예비 분해(단계 decompose_gate, 추론은 --reasoning 값)가 나누지 않는다고 하면 분해를 기다리는 동안 원 질문으로 "
                   "첫 검색과 판정을 미리 돌린다. 분해(decompose)가 나누지 않으면 그 결과를 쓰고, 나누면 버린다(--parallel-intake, --skip-first-rewrite가 필요). 기본 꺼짐")
    p.add_argument("--cite-consensus", action="store_true", help="CS: 한 문장의 인용 셋 이상 중 다른 페이지 둘 이상이 같은 문장을 공유하면 그 문장을 공유하지 않는 다른 페이지 인용을 뺀다. 기본 꺼짐")
    p.add_argument("--pointer-refuse", action="store_true", help="PT: 근거 확인(Q 형식)이 복사한 구절이 모두 다른 자료를 가리키는 안내뿐이면 다시 쓰지 않고 거절한다. 기본 꺼짐")
    p.add_argument("--cite-pick", action="store_true", help="CP: 같은 사실을 여러 자료가 말할 때 근거 고르는 순서(온전한 문장, 되풀이된 문장, 절 제목, 공통 규범)와 주어·조건 확인을 답 프롬프트에 더한다. 기본 꺼짐")
    p.add_argument("--drop-scoped-cites", action="store_true", help="P: 질문에 없는 한정어(제목 경로에서 질문 낱말 바로 앞, 문맥의 다른 페이지 제목에 없는 낱말)가 붙은 페이지만 인용한 문장을 근거 판정 뒤 코드가 뺀다. 기본 꺼짐")
    p.add_argument("--query-branches", action="store_true", help="대상에 따라 절차가 갈리는 주제인데 대상이 없으면 대상마다 하위 질문을 만들고, 답이 대상을 빠뜨리면 한 번 다시 쓴다. 기본 꺼짐")
    p.add_argument("--keep-product-name", action="store_true", help="첫 검색에서 'GitLab 계정'처럼 제품의 대상을 가리키는 회사 이름은 떼지 않는다. 기본 꺼짐")
    p.add_argument("--requery-terms", action="store_true", help="판정 재검색어를 핸드북 용어(search-terms Skill)로 쓰고 질문에 없는 고유 이름을 넣지 않는다(--judge-query와 같이). 기본 꺼짐")
    p.add_argument("--answer-budget", type=float, default=0, help="질문을 받은 뒤 이 초가 지나면 추론 답을 기다리지 않는다(--answer-wait과 같이)")
    p.add_argument("--decompose-cap", type=float, default=0, help="첫 검색의 질문 분해가 이 초 안에 오지 않으면 원 질문 하나로 검색하고 늦은 분해는 버린다. 기본 꺼짐(0)")
    p.add_argument("--answer-wait", type=float, default=0, help="추론 답을 기다리는 초. 넘으면 같이 보낸 빠른 답을 쓴다")
    p.add_argument("--structured", default="", help="결론 앞에 대조 칸을 쓸 단계. 예: judge,answer,grounding")
    p.add_argument("--judge-query", action="store_true", help="판정이 재검색어까지 낸다(재작성 호출 없음)")
    p.add_argument("--embed-keepalive", action="store_true", help="임베딩 연결 재사용, 질문 여럿은 동시에")
    p.add_argument("--judge-answer", choices=("", "parallel", "parallel_all", "joint"), default="", help="판정과 답 작성을 동시에 부르거나(parallel) 한 호출로 합친다(joint). 기본 꺼짐")
    p.add_argument("--skip-first-rewrite", action="store_true", help="검색어가 쓰이지 않는 첫 재작성을 건너뛴다. 기본 꺼짐")
    p.add_argument("--stop-stalled-search", action="store_true", help="근거가 늘지 않으면 더 찾지 않고 같은 입력의 판정을 다시 부르지 않는다. 기본 꺼짐")
    p.add_argument("--ground-skip-backed", action="store_true", help="모든 문장의 값이 인용 청크에 있으면 근거 판정 LLM을 건너뛴다. 기본 꺼짐")
    p.add_argument("--json-only", action="store_true", help="그래프 호출에 response_format=json_object를 붙인다. 기본 꺼짐")
    p.add_argument("--reasoning", choices=("", "none", "minimal", "low", "medium", "high"), default="", help="OpenRouter reasoning.effort. 기본은 보내지 않는다")
    p.add_argument("--provider-sort", choices=("", "latency", "throughput", "price"), default="", help="OpenRouter provider.sort. 기본은 보내지 않는다")
    p.add_argument("--out", required=True, help="갈래별 폴더와 compare.json을 쓸 폴더")
    p.set_defaults(fn=run_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
