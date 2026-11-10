"""배포본 측정 결과의 인용 정답 대조: `deploy_latency.py`가 남긴 행의 `cited_chunk_ids`를 평가셋 정답 위치(`gold_chunks`)와 맞춘다.

LLM 호출도 운영 접속도 없다. 이미 만든 결과 폴더(`run*/rows.jsonl`)와 평가셋, 코퍼스 스냅샷만 읽는다.

    python -m evals.latency.deploy_citation_gold --results evals/results/deploy_latency_v2 --dataset evals/dataset_v2.jsonl [--chunks data/index/chunks.jsonl] [--deployed-corpus-id 값] [--out 폴더]

방식
- 인용 청크 id를 코퍼스 스냅샷의 청크(`rule_seq`, `article`, `line_start`~`line_end`)로 되돌리고 `evals.retrieval.gold`의 `GoldRef.matches`로 정답 위치와 맞춘다.
  스냅샷에 없는 id는 `unresolved`로 세고 정답 밖 인용으로 본다(청크 id로 적은 정답과는 id가 같으면 맞는다).
- 지표 이름과 정의는 질문 그래프 평가 실행기(`evals/agent/run_eval.py` `_row`, `compute_metrics`)와 같다.
  - cited_correct_rate(정답 근거 인용률): 관련 문항 전체 분모, 답한 문항의 (맞힌 정답 위치 수 / 정답 위치 수) 합. 답하지 않으면 0.
  - wrong_citation_rate(오답 근거): 답한 관련 문항 중 정답 위치 밖 청크를 하나라도 인용한 문항 비율. `wrong_citation_rows`는 그 문항(행) 수.
  - citation_accuracy(인용 정확도): 답한 관련 문항 중 인용이 있는 문항의 (정답 위치에 맞는 인용 수 / 전체 인용 수) 합을 답한 관련 문항 수로 나눔.
  - over_refusal_rate(과잉 거절): 관련 문항 중 답하지 않은 비율. correct_refusal_rate(올바른 거절): 비관련 문항 중 답하지 않은 비율.
  - 답함 = 성공한 행(`status == ok`)의 kind가 `answer`. 실패 행(오류, 시간 초과)은 실행기가 오류를 거절로 세는 것과 같이 답하지 않은 것으로 센다.
    실패 행 수는 `n_fail_rows`로 따로 낸다.
  - 문항 수가 적은 평가셋(검증 20건 등)에서는 값이 크게 흔들리므로 회차별 값과 3회 평균, 범위를 함께 낸다.
- 정답 위치가 코퍼스 스냅샷에 하나도 없는 문항은 `gold_unlocatable`에 적는다(채점에서 빼지 않는다. 실행기와 같다).
- `evals/exclusions.json`에 적힌 문항은 채점에서 뺀다(실행기와 같다).

코퍼스 판: 배포본이 쓰는 코퍼스와 이 스냅샷이 같은 판이라는 보장은 없다. 결과에 스냅샷의 meta(`n_chunks`, `chunks_sha256`, `chunks_fingerprint`),
평가셋이 적은 `corpus_version`, 호출자가 준 `--deployed-corpus-id`와의 비교, 스냅샷에서 못 찾은 인용 수, 인용 이벤트의 판 날짜와 스냅샷 청크의 판 날짜가 다른 인용 수를 적는다.
못 찾은 인용이나 판 날짜 불일치가 있으면 이 대조는 배포본 코퍼스와 다른 판의 위치로 한 것이다.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from evals.retrieval.gold import missing_in_corpus
from evals.retrieval.run import load_dataset, load_exclusions

REPO = Path(__file__).resolve().parents[2]
INDEX_DIR = REPO / "data" / "index"
INDEX_ARCHIVE = REPO / "data" / "index.tar.gz"
EXCLUSIONS = REPO / "evals" / "exclusions.json"


# ---------------------------------------------------------------- 코퍼스 스냅샷

def parse_chunks(lines: Iterable[str]) -> list[Any]:
    return [SimpleNamespace(**json.loads(ln)) for ln in lines if ln.strip()]


def load_corpus(chunks: Path | None) -> tuple[list[Any], dict[str, Any], str]:
    """(청크 목록, meta, 출처). `chunks`가 없으면 `data/index/chunks.jsonl`, 그것도 없으면 `data/index.tar.gz` 안의 같은 파일.
    meta는 같은 자리의 `meta.json`(없으면 빈 dict)."""
    if chunks is not None:
        meta_path = chunks.parent / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        return parse_chunks(chunks.read_text(encoding="utf-8").splitlines()), meta, chunks.as_posix()
    if (INDEX_DIR / "chunks.jsonl").is_file():
        return load_corpus(INDEX_DIR / "chunks.jsonl")
    if INDEX_ARCHIVE.is_file():
        with tarfile.open(INDEX_ARCHIVE, "r:gz") as tar:
            data = tar.extractfile("chunks.jsonl").read().decode("utf-8")   # type: ignore[union-attr]
            m = tar.extractfile("meta.json")
            meta = json.loads(m.read().decode("utf-8")) if m else {}
        return parse_chunks(io.StringIO(data)), meta, f"{INDEX_ARCHIVE.name}:chunks.jsonl"
    raise SystemExit("코퍼스 스냅샷이 없다: --chunks로 chunks.jsonl을 주거나 data/index.tar.gz를 둬라")


def corpus_info(corpus: list[Any], meta: dict[str, Any], source: str, dataset_items: list[dict], deployed_id: str | None) -> dict[str, Any]:
    """코퍼스 판 기록. 배포본 코퍼스와 같은 판인지는 이 스냅샷만으로 확인할 수 없어서 비교 재료를 모두 적는다."""
    ids = {str(meta.get(k)) for k in ("chunks_fingerprint", "chunks_sha256") if meta.get(k)}
    same: bool | None = None
    if deployed_id:
        same = any(i.startswith(deployed_id) or deployed_id.startswith(i) for i in ids) if ids else False
    return {
        "source": source, "n_chunks": len(corpus), "meta_n_chunks": meta.get("n_chunks"),
        "chunks_sha256": meta.get("chunks_sha256"), "chunks_fingerprint": meta.get("chunks_fingerprint"),
        "n_version_ids": len({getattr(c, "version_id", None) for c in corpus}),
        "dataset_corpus_versions": sorted({str(it.get("corpus_version")) for it in dataset_items if it.get("corpus_version")}),
        "deployed_corpus_id": deployed_id or None, "same_as_deployed": same,
        "note": "배포본이 이 스냅샷과 같은 코퍼스인지는 이 파일만으로 알 수 없다. same_as_deployed가 None이면 비교할 값을 받지 못한 것이다. "
                "unresolved_citations(스냅샷에 없는 청크 id)와 version_date_mismatch(인용 이벤트와 스냅샷의 판 날짜가 다름)가 0이면 인용이 모두 이 스냅샷의 청크와 맞는다.",
    }


# ---------------------------------------------------------------- 채점(순수 계산)

def stub_chunk(chunk_id: Any) -> SimpleNamespace:
    """스냅샷에 없는 청크. 청크 id로 적은 정답과만 맞을 수 있다."""
    return SimpleNamespace(chunk_id=chunk_id, rule_seq=None, article=None, line_start=None, line_end=None, version_date=None)


def score_row(row: dict, item: dict, by_id: dict[str, Any]) -> dict[str, Any]:
    """행 하나 + 평가셋 문항 -> 문항별 채점. 정의는 `run_eval._row`와 같다."""
    gold = item["gold"]
    cited_ids = list(row.get("cited_chunk_ids") or [])
    objs = [by_id.get(cid) or stub_chunk(cid) for cid in cited_ids]
    unresolved = [cid for cid in cited_ids if cid not in by_id]
    date_mismatch = [cid for cid, d in zip(cited_ids, row.get("cited_version_dates") or []) if cid in by_id and d and d != getattr(by_id[cid], "version_date", None)]
    answered = row.get("status") == "ok" and row.get("result") == "answer"
    on_gold = [any(g.matches(c) for g in gold) for c in objs]
    cited_on_gold = sum(on_gold)
    gold_hit = sum(any(g.matches(c) for c in objs) for g in gold)
    return {
        "run": row.get("run"), "id": row.get("id"), "kind": item["kind"], "expect_refusal": item["kind"] != "relevant",
        "status": row.get("status"), "result": row.get("result"), "answered": answered,
        "has_chunk_ids": "cited_chunk_ids" in row,
        "cited": cited_ids, "cited_on_gold": cited_on_gold, "cited_off_gold": len(cited_ids) - cited_on_gold,
        "cited_gold_flags": on_gold, "gold_total": len(gold), "gold_hit": gold_hit,
        "gold_cited": bool(answered and gold_hit),
        "wrong_citation": bool(answered and cited_on_gold < len(cited_ids)),
        "unresolved": unresolved, "version_date_mismatch": date_mismatch,
        "n_citation_events": row.get("citations"),
    }


def _rate(num: float, den: int) -> float | None:
    return None if den == 0 else num / den


def compute_metrics(scored: list[dict]) -> dict[str, Any]:
    """문항별 채점 -> 지표. 이름과 분자·분모는 `run_eval.compute_metrics`와 같다."""
    relevant = [r for r in scored if not r["expect_refusal"]]
    irrelevant = [r for r in scored if r["expect_refusal"]]
    answered = [r for r in relevant if r["answered"]]
    cited_total = sum(len(r["cited"]) for r in answered)
    return {
        "n": len(scored), "n_relevant": len(relevant), "n_irrelevant": len(irrelevant), "n_answered_relevant": len(answered),
        "n_fail_rows": sum(r["status"] != "ok" for r in scored),
        "cited_correct_rate": _rate(sum(r["gold_hit"] / r["gold_total"] for r in answered if r["gold_total"]), len(relevant)),
        "wrong_citation_rate": _rate(sum(r["cited_on_gold"] < len(r["cited"]) for r in answered), len(answered)),
        "wrong_citation_rows": sum(r["cited_on_gold"] < len(r["cited"]) for r in answered),
        "citation_accuracy": _rate(sum(r["cited_on_gold"] / len(r["cited"]) for r in answered if r["cited"]), len(answered)),
        "citation_accuracy_pooled": _rate(sum(r["cited_on_gold"] for r in answered), cited_total),
        "over_refusal_rate": _rate(len(relevant) - len(answered), len(relevant)),
        "correct_refusal_rate": _rate(sum(not r["answered"] for r in irrelevant), len(irrelevant)),
        "answered_irrelevant": sum(r["answered"] for r in irrelevant),
        "gold_cited_questions": sum(r["gold_cited"] for r in relevant),
        "cited_total": cited_total, "cited_off_gold_total": sum(r["cited_off_gold"] for r in answered),
        "cited_all_rows": sum(len(r["cited"]) for r in scored),
        "unresolved_citations": sum(len(r["unresolved"]) for r in scored),
        "version_date_mismatch": sum(len(r["version_date_mismatch"]) for r in scored),
        "rows_without_chunk_ids": sum(not r["has_chunk_ids"] for r in scored),
    }


def spread(values: list[float | None]) -> dict[str, float | None]:
    v = [x for x in values if x is not None]
    if not v:
        return {"mean": None, "min": None, "max": None}
    return {"mean": round(sum(v) / len(v), 4), "min": round(min(v), 4), "max": round(max(v), 4)}


RATE_KEYS = ("cited_correct_rate", "wrong_citation_rate", "citation_accuracy", "over_refusal_rate", "correct_refusal_rate")


def build_summary(scored_by_run: dict[int, list[dict]]) -> dict[str, Any]:
    per_run = {n: compute_metrics(rows) for n, rows in sorted(scored_by_run.items())}
    all_rows = [r for n in sorted(scored_by_run) for r in scored_by_run[n]]
    mean_over_runs = {k: spread([m[k] for m in per_run.values()]) for k in (*RATE_KEYS, "wrong_citation_rows", "citation_accuracy_pooled")}
    return {"per_run": [{"run": n, **m} for n, m in per_run.items()], "mean_over_runs": mean_over_runs, "pooled_rows": compute_metrics(all_rows)}


def score_runs(runs: dict[int, list[dict]], items: list[dict], corpus: list[Any], exclusions: dict[str, str] | None = None) -> dict[str, Any]:
    """{회차: 행 목록} + 평가셋 + 코퍼스 -> {summary, rows, problems}."""
    exclusions = exclusions or {}
    by_id = {c.chunk_id: c for c in corpus}
    item_by_id = {it["id"]: it for it in items}
    scored_by_run: dict[int, list[dict]] = {}
    problems: list[str] = []
    for n, rows in runs.items():
        out = []
        for row in rows:
            it = item_by_id.get(row.get("id"))
            if it is None:
                problems.append(f"{n}회차 문항 {row.get('id')}이(가) 평가셋에 없다")
                continue
            if str(it["id"]) in exclusions:
                continue
            out.append(score_row(row, it, by_id))
        scored_by_run[n] = out
    unlocatable = {str(it["id"]): missing_in_corpus(it["gold"], corpus) for it in items if it["kind"] == "relevant" and str(it["id"]) not in exclusions}
    unlocatable = {k: v for k, v in unlocatable.items() if v}
    return {"summary": build_summary(scored_by_run), "rows": [r for n in sorted(scored_by_run) for r in scored_by_run[n]],
            "gold_unlocatable": unlocatable, "problems": problems}


# ---------------------------------------------------------------- 입출력

def load_runs(results: Path) -> dict[int, list[dict]]:
    runs: dict[int, list[dict]] = {}
    for p in sorted(results.glob("run*/rows.jsonl")):
        digits = "".join(ch for ch in p.parent.name if ch.isdigit())
        if not digits:
            continue
        rows = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    continue
        runs[int(digits)] = rows
    return runs


def _f(v: float | None, nd: int = 3) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def render_markdown(res: dict[str, Any], meta: dict[str, Any]) -> str:
    s, c = res["summary"], meta["corpus"]
    lines = [f"# 배포본 인용 정답 대조 ({meta['dataset']} x {len(s['per_run'])}회)", "",
             f"- 측정 결과: {meta['results']}, 평가셋 {meta['dataset_path']} (sha256 `{meta['dataset_sha256'][:12]}`)"
             + (f", 측정 때 평가셋 sha256 {'같음' if meta['dataset_sha_match'] else '다름'}" if meta["dataset_sha_match"] is not None else ", 측정 때 평가셋 sha256 확인 못 함"),
             f"- 코퍼스 스냅샷: {c['source']}, 청크 {c['n_chunks']}개, 지문 `{(c.get('chunks_fingerprint') or '-')[:12]}`, 평가셋 corpus_version {', '.join(c['dataset_corpus_versions']) or '없음'}, "
             f"배포본 코퍼스 id {c['deployed_corpus_id'] or '받지 못함'}"
             + ("" if c["same_as_deployed"] is None else f", 스냅샷과 {'같음' if c['same_as_deployed'] else '다름'}"),
             "- 방식: 인용 청크 id를 스냅샷 청크로 되돌려 정답 위치와 맞춤(`GoldRef.matches`). 지표 정의는 `evals/agent/run_eval.py`와 같다. 배포본 코퍼스 판과 다를 수 있다(위 줄과 아래 점검 표).", "",
             "## 지표", "", "| 회차 | 정답 근거 인용률 | 오답 근거 | 오답 근거 행 수 | 인용 정확도 | 과잉 거절 | 올바른 거절 | 답한 관련/관련 | 실패 행 |", "|---|---|---|---|---|---|---|---|---|"]
    for p in s["per_run"]:
        lines.append(f"| {p['run']}회차 | {_f(p['cited_correct_rate'])} | {_f(p['wrong_citation_rate'])} | {p['wrong_citation_rows']} | {_f(p['citation_accuracy'])} | "
                     f"{_f(p['over_refusal_rate'])} | {_f(p['correct_refusal_rate'])} | {p['n_answered_relevant']}/{p['n_relevant']} | {p['n_fail_rows']} |")
    m = s["mean_over_runs"]

    def mm(k: str, nd: int = 3) -> str:
        return f"{_f(m[k]['mean'], nd)} ({_f(m[k]['min'], nd)}~{_f(m[k]['max'], nd)})"

    lines.append(f"| 회차 평균(범위) | {mm('cited_correct_rate')} | {mm('wrong_citation_rate')} | {mm('wrong_citation_rows', 2)} | {mm('citation_accuracy')} | {mm('over_refusal_rate')} | {mm('correct_refusal_rate')} | | |")
    a = s["pooled_rows"]
    lines += ["", f"전 회차 합친 값(참고): 정답 근거 인용률 {_f(a['cited_correct_rate'])}, 인용 정확도 {_f(a['citation_accuracy'])}, 인용 합산 비율(정답 위치 인용 / 전체 인용) {_f(a['citation_accuracy_pooled'])}, "
              f"정답 위치를 하나라도 인용한 관련 문항 {a['gold_cited_questions']}/{a['n_relevant']}.", "",
              "## 코퍼스 판 점검", "", "| 항목 | 값 |", "|---|---|",
              f"| 스냅샷에 없는 인용(unresolved) | {a['unresolved_citations']}/{a['cited_all_rows']}(모든 행의 인용 기준) |",
              f"| 판 날짜가 다른 인용 | {a['version_date_mismatch']} |",
              f"| 청크 id가 없는 행(옛 측정 결과) | {a['rows_without_chunk_ids']} |",
              f"| 정답 위치가 스냅샷에 없는 문항 | {', '.join(f'{k}번' for k in res['gold_unlocatable']) or '없음'} |"]
    if res["problems"]:
        lines += ["", "## 문제", ""] + [f"- {p}" for p in res["problems"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.latency.deploy_citation_gold", description="배포본 측정 결과의 인용 정답 대조(키·네트워크 없음)")
    ap.add_argument("--results", type=Path, required=True, help="deploy_latency 결과 폴더(run1~3/rows.jsonl가 있는 곳)")
    ap.add_argument("--dataset", type=Path, required=True, help="측정에 쓴 평가셋 JSONL(정답 gold_chunks 포함)")
    ap.add_argument("--chunks", type=Path, default=None, help="코퍼스 청크 JSONL(기본 data/index/chunks.jsonl, 없으면 data/index.tar.gz 안의 파일)")
    ap.add_argument("--deployed-corpus-id", default="", help="배포본 코퍼스 지문 또는 sha256(앞부분 가능). 스냅샷 meta와 비교해 기록한다")
    ap.add_argument("--exclusions", type=Path, default=EXCLUSIONS)
    ap.add_argument("--out", type=Path, default=None, help="결과 폴더(기본 --results)")
    a = ap.parse_args(argv)

    runs = load_runs(a.results)
    if not runs:
        print(f"{a.results}에 run*/rows.jsonl이 없다", file=sys.stderr)
        return 2
    items = load_dataset(a.dataset)
    corpus, cmeta, source = load_corpus(a.chunks)
    res = score_runs(runs, items, corpus, load_exclusions(a.exclusions))

    sha = hashlib.sha256(a.dataset.read_bytes()).hexdigest()
    measured_sha = None
    sp = a.results / "summary.json"
    if sp.is_file():
        try:
            measured_sha = json.loads(sp.read_text(encoding="utf-8"))["meta"].get("dataset_sha256")
        except (ValueError, KeyError):
            pass
    meta = {"results": a.results.as_posix(), "dataset": a.dataset.name, "dataset_path": a.dataset.as_posix(), "dataset_sha256": sha,
            "dataset_sha_match": None if not measured_sha else measured_sha == sha,
            "corpus": corpus_info(corpus, cmeta, source, items, a.deployed_corpus_id or None)}
    out = a.out or a.results
    out.mkdir(parents=True, exist_ok=True)
    (out / "citation_gold.json").write_text(json.dumps({"meta": meta, **res}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = render_markdown(res, meta)
    (out / "citation_gold.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
