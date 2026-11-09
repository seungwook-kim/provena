"""금액 구간 조회(사전 등록 62.7)의 검색만 재현과 회귀. LLM을 부르지 않는다.

    # 같은 질문에서 금액만 바꾼 검색 재현(데모 녹화의 분해·영어 문장을 쓰고 금액만 바꾼다)
    python -m evals.retrieval.range_context demo --out evals/results/range_retrieval_62_7/demo.json
    # v2 50문항 + 검증 20문항의 첫 검색 문맥 전후 비교(저장된 분해·번역으로 같은 검색을 다시 한다)
    python -m evals.retrieval.range_context regress --out evals/results/range_retrieval_62_7/regress.json

- 검색기는 서비스와 같은 `Searcher`다. 저장소만 DB 대신 색인 스냅샷(`data/index/`, 링크 대상 포함)을 numpy로 읽는다(V2 대조에서 같은 청크).
- 질문 임베딩만 Voyage(`VOYAGE_API_KEY`, 환경 변수로만)로 구하고 같은 글은 `--vec-cache`에서 다시 쓴다. 키가 없고 캐시에도 없으면 멈춘다.
- 번역은 LLM 대신 저장된 값을 쓴다: demo는 `data/demo_replay/recorded.jsonl`의 영어 문장(금액만 바꿈), regress는 `--translations`
  (운영 DB `query_translations`를 읽기 전용으로 조회해 만든 파일, `evals/results/range_retrieval_62_7/translations.json`).
- 첫 검색 문맥은 질문 그래프 `search` 노드와 같은 순서로 만든다: 질문 계획(`query_plan.plan_first_search`) -> `search()` -> 제목 경로 검색(용어·절 이름 구)
  -> 도입부 채우기. 답 작성과 판정은 LLM이라 하지 않는다.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from backend.graph import answer_fixes as AF
from backend.graph import query_plan as QP
from backend.graph.build import HEADS_SCAN, merge_chunks
from backend.rag.retrieve import embed, ranges, translate
from backend.rag.retrieve.search import MemoryStore, SearchConfig, Searcher
from backend.schemas.chunk import SearchQuery
from evals.retrieval.gold import parse_gold
from evals.retrieval.metrics import ranking_metrics

S = importlib.import_module("backend.rag.retrieve.search")   # backend.rag.retrieve.search는 함수 이름과 같아 모듈은 이름으로 연다
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evals" / "results" / "range_retrieval_62_7"
RUNS = {  # 최종 API 측정(사전 등록 61.51 bo2sd-a2)의 첫 검색 호출 기록: 질문, 하위 질문, 기준일, 돌려준 청크
    "v2": ("evals/results/agent_v2_q_d6151_r1_bo2sda2_api/single/rows.jsonl", "evals/dataset_v2.jsonl"),
    "holdout": ("evals/results/agent_v2_q_d6151_h1_bo2sda2_api/single/rows.jsonl", "evals/dataset_holdout_v1.jsonl"),
}
AFTER_RANGE_N = 2

# 데모 질문의 금액 칸(한국어, 영어, 그 금액이 속한 'Approving expense' 구간 행의 제목). 구간 제목은 파서가 아니라 원문 표에서 손으로 적었다(채점용 정답)
AMOUNTS = {"10K": ("1만 달러", "$10,000", ">$0K to $25K"), "30K": ("3만 달러", "$30,000", ">$25K up to $50K"),
           "50K": ("5만 달러", "$50,000", ">$25K up to $50K"), "100K": ("10만 달러", "$100,000", ">$50K up to $250K"),
           "300K": ("30만 달러", "$300,000", ">$250K up to $500K")}
EXPENSE = "Approving expense > "


# ---------- 검색기 ----------

def load_store(index: Path) -> MemoryStore:
    meta, rows = S.snapshot_rows(index)
    links = [json.loads(x) for x in (index / "links.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(links) != len(rows) or any(a["chunk_id"] != b["chunk_id"] for a, b in zip(rows, links)):
        raise RuntimeError("links.jsonl과 chunks.jsonl 줄이 다르다")
    for r, lk in zip(rows, links):
        r["link_targets"] = lk["targets"]
    return MemoryStore(rows, np.load(index / "vectors" / "voyage-4.npy"), "voyage-4", meta=meta)


class CachedVoyage:
    """질문 임베딩(Voyage voyage-4). 글마다 한 번만 부르고 캐시 파일에 둔다."""

    def __init__(self, cache: Path):
        self.path, self.calls = cache, 0
        self.cache: dict[str, list[float]] = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
        self.client = embed.VoyageClient(embed.spec("voyage-4"))

    def __call__(self, texts: list[str]) -> np.ndarray:
        miss = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if miss:
            if not os.environ.get("VOYAGE_API_KEY"):
                raise embed.EmbedNoKey(f"VOYAGE_API_KEY가 없고 캐시에도 없는 질문이 있다: {len(miss)}개")
            for t, v in zip(miss, self.client.embed(miss, "query")):
                self.cache[t] = [round(float(x), 6) for x in v]
            self.calls += len(miss)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache), encoding="utf-8")
        return np.stack([np.asarray(self.cache[t], dtype=np.float32) for t in texts])


def make_searcher(store: MemoryStore, embedder, sentences: dict[str, str], range_n: int) -> Searcher:
    def translator(query: str, kind: str):
        if query not in sentences:
            raise KeyError(f"저장된 영어 문장이 없다(LLM을 부르지 않는다): {query[:60]}")
        return translate.Result(sentences[query], "stored")

    cfg = SearchConfig(embed_model="voyage-4", range_n=range_n)
    return Searcher(cfg, store, embedder=embedder, reranker=None, translator=translator, check_meta=False)


def first_context(searcher: Searcher, question: str, query: str, subs: list[str], as_of: str | None) -> tuple[list[SimpleNamespace], list[SimpleNamespace]]:
    """(search() 결과, 첫 검색 문맥). 그래프 build.py의 첫 검색 노드(제목 경로 검색 H·HT, 도입부 R3)와 같은 순서와 상한이다."""
    q = SearchQuery(query=query, as_of=as_of, k=5, sub_queries=subs or None)
    found = [c.model_dump() for c in searcher.search(q)]
    phrases = AF.heading_phrases([query, *subs])
    phrases += [h for h in QP.heading_heads([question, query, *subs]) if h not in phrases]
    have = {c["chunk_id"] for c in found}
    added: list[dict] = []
    for ph in phrases:
        fresh = [c.model_dump() for c in searcher.search_headings(ph, None, as_of, HEADS_SCAN) if c.chunk_id not in have][:1]
        have |= {c["chunk_id"] for c in fresh}
        added += fresh
    ctx = merge_chunks(found, added)
    intro = [c.model_dump() for c in searcher.intro_fill(ctx, query, None, as_of)]
    ctx = merge_chunks(ctx, intro, limit=len(ctx) + len(intro))
    return [SimpleNamespace(**c) for c in found], [SimpleNamespace(**c) for c in ctx]


# ---------- 데모 재현 ----------

def recorded_texts(path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """녹화 -> (질문 -> 분해 하위 질문, 한국어 글 -> 영어 문장). 같은 키는 첫 줄을 쓴다."""
    split: dict[str, list[str]] = {}
    english: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        head = r["user_preview"].split("\n\n")[0]
        if r["role"] == "decompose":
            split.setdefault(head, json.loads(r["response"]).get("sub_questions") or [])
        elif r["role"] == "generic":
            english.setdefault(head, r["response"].strip())
    return split, english


def demo(args) -> dict:
    split, english = recorded_texts(ROOT / "data" / "demo_replay" / "recorded.jsonl")
    pick = lambda amount, mark: next(q for q in split if amount in q and mark in q)  # noqa: E731
    bases = {  # 녹화에서 고른 세 질문. A·B는 같은 말투이고 분해가 '외부 SaaS 도입'을 남겼는지만 다르다. C는 근거 섹션·판 날짜까지 묻는 말투
        "A": (pick("3만 달러", "업무 승인자와 재무 승인자"), "3만 달러", "$30,000"),
        "B": (pick("5만 달러", "업무 승인자와 재무 승인자"), "5만 달러", "$50,000"),
        "C": (pick("10만 달러", "판 날짜"), "10만 달러", "$100,000"),
    }
    store = load_store(Path(args.index))
    voyage = CachedVoyage(Path(args.vec_cache))
    expected = {name: next((r for r in store.rows if (r.get("article") or "") == EXPENSE + band), None) for name, (_, _, band) in AMOUNTS.items()}
    assert all(expected.values()), "Approving expense 구간 행을 색인에서 찾지 못했다"
    rows: list[dict] = []
    for label, (question, ko0, en0) in bases.items():
        subs0 = split[question]
        base = QP.plan_first_search(question, question, subs0, terms=True, branches=True)   # 녹화 때와 같은 용어 붙이기(GRAPH_QUERY_TERMS)
        base_texts = [base.query, *base.subs]
        assert all(en0 in english[t] for t in base_texts), f"녹화 영어 문장에 {en0}가 없다: {label}"
        for name, (ko, en, band) in AMOUNTS.items():
            qn, subs = question.replace(ko0, ko), [s.replace(ko0, ko) for s in subs0]
            plan = QP.plan_first_search(qn, qn, subs, terms=True, branches=True)
            sentences = {t: english[b].replace(en0, en) for t, b in zip([plan.query, *plan.subs], base_texts)}
            eid = expected[name]["chunk_id"]
            row: dict[str, Any] = {"variant": label, "amount": name, "question": qn, "sub_queries": plan.subs, "expected_title": EXPENSE + band, "expected_chunk": eid}
            for tag, n in (("before", 0), ("after", AFTER_RANGE_N)):
                found, ctx = first_context(make_searcher(store, voyage, sentences, n), qn, plan.query, plan.subs, None)
                ids, cids = [c.chunk_id for c in found], [c.chunk_id for c in ctx]
                row[tag] = {"search": [c.article for c in found], "search_rank": ids.index(eid) + 1 if eid in ids else None,
                            "context_rank": cids.index(eid) + 1 if eid in cids else None, "context_size": len(cids)}
            rows.append(row)
    res = {"kind": "demo", "k": 5, "range_n_after": AFTER_RANGE_N, "embed_calls": voyage.calls, "rows": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(demo_table(res))
    return res


def demo_table(res: dict) -> str:
    show = lambda x: "없음" if x is None else f"{x}위"  # noqa: E731
    lines = ["| 질문 틀 | 금액 | 수정 전 검색 결과 | 수정 전 문맥 | 수정 후 검색 결과 | 수정 후 문맥 |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        b, a = r["before"], r["after"]
        lines.append(f"| {r['variant']} | {r['amount']} | {show(b['search_rank'])} | {show(b['context_rank'])} | {show(a['search_rank'])} | {show(a['context_rank'])} |")
    hit = lambda tag, key: sum(1 for r in res["rows"] if r[tag][key] is not None)  # noqa: E731
    lines.append(f"\n정답 구간 행이 든 건수(전체 {len(res['rows'])}): 수정 전 검색 {hit('before', 'search_rank')}, 문맥 {hit('before', 'context_rank')} / "
                 f"수정 후 검색 {hit('after', 'search_rank')}, 문맥 {hit('after', 'context_rank')}")
    return "\n".join(lines)


# ---------- 회귀 ----------

def load_first_searches(rows_path: Path, dataset_path: Path) -> list[dict]:
    data = {r["id"]: r for r in map(json.loads, dataset_path.read_text(encoding="utf-8").splitlines()) if r}
    out = []
    for r in map(json.loads, rows_path.read_text(encoding="utf-8").splitlines()):
        first = [c for c in (r.get("retrieval_calls") or []) if c.get("kind") == "first"]
        if not first:                      # 질문 그래프가 검색까지 가지 않은 문항(범위 밖·되묻기 등)
            continue
        c, it = first[0], data[r["id"]]
        out.append({"id": r["id"], "kind": it["kind"], "question": r["question"], "query": c["graph_query"], "subs": list(c.get("sub_queries") or []),
                    "as_of": c.get("as_of"), "stored": c["returned"], "gold": parse_gold(it.get("gold_chunks") or []) if it["kind"] == "relevant" else []})
    return out


def found_gold(gold, chunks) -> tuple[int, int] | None:
    """(찾은 정답 위치 수, 정답 위치 수). 정답이 없는 문항(비관련)은 None."""
    if not gold:
        return None
    m = ranking_metrics(gold, chunks, max(len(chunks), 1))
    return m["n_found"], m["n_gold"]


STRESS_KO, STRESS_EN = " (금액은 3만 달러)", " (the amount is $30,000)"


def with_amount(it: dict, sentences: dict[str, str]) -> dict:
    """압박 점검: 질문과 하위 질문 끝에 금액 문구를 붙인다(영어 문장에도 같은 뜻). 금액이 든 질문에서 구간 조회가 다른 정답을 밀어내는지 본다."""
    texts = [it["query"], *it["subs"]]
    for t in texts:
        sentences[t + STRESS_KO] = sentences[t] + STRESS_EN
    return {**it, "question": it["question"] + STRESS_KO, "query": it["query"] + STRESS_KO, "subs": [s + STRESS_KO for s in it["subs"]]}


def regress(args) -> dict:
    sentences = {t: next(iter(m.values())) for t, m in json.loads(Path(args.translations).read_text(encoding="utf-8")).items()}
    store = load_store(Path(args.index))
    voyage = CachedVoyage(Path(args.vec_cache))
    result: dict[str, Any] = {"kind": "regress", "range_n_after": AFTER_RANGE_N, "sets": {}}
    jobs = [(name, name, False) for name in RUNS] + [(f"{name}+금액문구", name, True) for name in RUNS]
    for label, name, stress in jobs:
        rows_p, data_p = RUNS[name]
        searchers = {tag: make_searcher(store, voyage, sentences, n) for tag, n in (("before", 0), ("after", AFTER_RANGE_N))}
        rows = []
        for it in load_first_searches(ROOT / rows_p, ROOT / data_p):
            if stress:
                it = with_amount(it, sentences)
            row: dict[str, Any] = {"id": it["id"], "kind": it["kind"], "stored_returned": it["stored"],
                                   "has_amount": bool(ranges.amounts_in([it["question"], it["query"], *it["subs"]]))}
            for tag, s in searchers.items():
                found, ctx = first_context(s, it["question"], it["query"], it["subs"], it["as_of"])
                row[tag] = {"search": [c.chunk_id for c in found], "context": [c.chunk_id for c in ctx],
                            "search_gold": found_gold(it["gold"], found), "context_gold": found_gold(it["gold"], ctx)}
            row["changed"] = row["before"]["context"] != row["after"]["context"]
            row["matches_stored"] = None if stress else set(row["before"]["search"]) == set(it["stored"])   # 압박 점검은 저장된 결과와 비교하지 않는다
            rows.append(row)
        result["sets"][label] = {"rows": rows, "summary": summarize(rows)}
    result["embed_calls"] = voyage.calls
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(regress_table(result))
    return result


def summarize(rows: list[dict]) -> dict:
    rel = [r for r in rows if r["before"]["search_gold"]]

    def recall(tag: str, part: str) -> float:
        return round(sum(r[tag][part][0] / r[tag][part][1] for r in rel) / len(rel), 4) if rel else 0.0

    def hit(tag: str, part: str) -> float:
        return round(sum(1 for r in rel if r[tag][part][0] > 0) / len(rel), 4) if rel else 0.0

    s: dict[str, Any] = {"n_searched": len(rows), "n_relevant_scored": len(rel), "n_with_amount": sum(1 for r in rows if r["has_amount"]),
                         "n_changed": sum(1 for r in rows if r["changed"]), "changed_ids": [r["id"] for r in rows if r["changed"]],
                         "n_matches_stored": sum(1 for r in rows if r["matches_stored"])}
    for tag in ("before", "after"):
        for part in ("search", "context"):
            s[f"{tag}_{part}_recall"], s[f"{tag}_{part}_hit"] = recall(tag, f"{part}_gold"), hit(tag, f"{part}_gold")
    s["context_worse_ids"] = [r["id"] for r in rel if r["after"]["context_gold"][0] < r["before"]["context_gold"][0]]
    s["context_better_ids"] = [r["id"] for r in rel if r["after"]["context_gold"][0] > r["before"]["context_gold"][0]]
    return s


def regress_table(res: dict) -> str:
    lines = ["| 평가셋 | 검색한 문항 | 관련 채점 | 금액이 든 문항 | 문맥이 바뀐 문항 | 저장된 첫 검색과 같은 집합 | 검색 결과 정답 재현율 전→후 | 문맥 정답 재현율 전→후 | 문맥 hit 전→후 | 나빠진 문항 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, d in res["sets"].items():
        s = d["summary"]
        same = "-" if name.endswith("금액문구") else f"{s['n_matches_stored']}/{s['n_searched']}"
        lines.append(f"| {name} | {s['n_searched']} | {s['n_relevant_scored']} | {s['n_with_amount']} | {s['n_changed']} {s['changed_ids']} | {same} | "
                     f"{s['before_search_recall']:.4f} → {s['after_search_recall']:.4f} | {s['before_context_recall']:.4f} → {s['after_context_recall']:.4f} | "
                     f"{s['before_context_hit']:.4f} → {s['after_context_hit']:.4f} | {s['context_worse_ids'] or '없음'} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.retrieval.range_context")
    ap.add_argument("cmd", choices=("demo", "regress"))
    ap.add_argument("--index", default=str(ROOT / "data" / "index"))
    ap.add_argument("--vec-cache", default=str(Path(tempfile.gettempdir()) / "range_qvec_cache.json"))
    ap.add_argument("--translations", default=str(OUT / "translations.json"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    a.out = a.out or str(OUT / f"{a.cmd}.json")
    t = time.perf_counter()
    (demo if a.cmd == "demo" else regress)(a)
    print(f"\n{a.out} ({time.perf_counter() - t:.0f}초)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
