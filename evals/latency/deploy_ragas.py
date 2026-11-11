"""배포본 측정 결과(`deploy_latency.py`의 `run*/rows.jsonl`)를 RAGAS 4지표로 채점한다 (사전 등록 62.25).

채점 방식은 61.51(결정 0022)과 같다: RAGAS 0.4.3, 지표 4개(문맥 정밀도 `context_precision`, 문맥 재현율 `context_recall`,
충실도 `faithfulness`, 답변 관련성 `answer_relevancy`), 판정 모델 Anthropic API `claude-haiku-5-5`, 답변 관련성 임베딩 Voyage `voyage-4`,
참조는 평가셋의 `expected`, 대상은 관련 문항 중 답한 행, 답 끝의 기준일·출처 줄은 빼고 채점한다.

61.51과 다른 점(그래서 정밀도·재현율은 61.51 값과 같은 기준이 아니다)
- 배포 측정은 검색한 청크 본문을 남기지 않고 인용한 청크 id만 남긴다. 문맥은 인용한 청크의 본문이다(`cited_chunk_ids` 순서, 중복은 한 번만).
  id는 로컬 코퍼스 스냅샷(`data/index/chunks.jsonl`, 없으면 `data/index.tar.gz` 안의 같은 파일, 그것도 없으면 `data/chunks/chunks.jsonl`)에서 본문으로 되돌린다.
  스냅샷에 없는 id는 문맥에서 빼고 개수를 적는다. 문맥이 하나도 없는 행은 채점하지 않고 건너뛴 행으로 센다.
- 답 본문은 결과 행의 `answer`에서 읽는다(`deploy_latency.py`가 이 채점을 위해 남기기 시작했다). `answer`가 없는 행(도구를 고치기 전의 측정)이 있으면 멈춘다.

    python -m evals.latency.deploy_ragas --results evals/results/deploy_latency_<리비전> --out evals/results/ragas_deploy_<리비전> [--dry-run]

환경 변수(채점할 때만): ANTHROPIC_API_KEY(`sk-ant-`로 시작해야 함, 아니면 멈춘다), VOYAGE_API_KEY. 값은 출력하지도 저장하지도 않는다.
`--dry-run`은 입력만 만들어 개수와 비용·시간 추정을 보이고 LLM·임베딩을 부르지 않는다(키도 필요 없다).
결과 폴더가 이미 있으면 덮어쓰지 않고 멈춘다(`--resume`이면 이미 채점한 행은 건너뛰고 뒤에 이어 쓴다).

종료 코드: 0 완료, 2 입력·환경 문제 또는 결과 폴더가 이미 있음, 3 비용 상한(`--max-cost`)에 닿아 멈춤, 4 판정 호출이 한도·권한 오류를 내 멈춤.
결과: `ragas_rows.jsonl`(행별 값), `summary.json`, `summary.md`, `cost.json`, `inputs_meta.json`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import time
import warnings
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
DATASET = REPO / "evals" / "dataset_v2.jsonl"
INDEX_DIR = REPO / "data" / "index"
INDEX_ARCHIVE = REPO / "data" / "index.tar.gz"
LOCAL_CHUNKS = REPO / "data" / "chunks" / "chunks.jsonl"
PRICES_FILE = REPO / "backend" / "services" / "llm_prices.json"
RATE_REFERENCE = REPO / "evals" / "results" / "ragas_d6151"   # 61.51 RAGAS 실측(행 수와 비용)

JUDGE = "claude-haiku-5-5"
EMBEDDING = "voyage-4"
NAMES = ("context_precision", "context_recall", "faithfulness", "answer_relevancy")
FAITHFULNESS_LINE = 0.91   # 62.25 통과 기준: 충실도 3회 평균
BATCH = 8
BAD_ERRORS = ("RateLimitError", "PermissionDeniedError", "AuthenticationError")
# 61.51 실측 기본값(RATE_REFERENCE가 없을 때): 300행에 1.412301달러. 25행 채점에 약 143초(로그 `ragas_d6151_225857.log`의 마지막 배치 시간 합)
FALLBACK_USD_PER_ROW = 1.412301 / 300
SECONDS_PER_ROW = 143 / 25
FOOTER = re.compile(r"\n+[ \t]*기준일 \S+ · 근거 판 날짜 [^\n]*· 출처: GitLab Handbook \(CC BY-SA 4\.0, 수정됨\)\s*$")


# ---------------------------------------------------------------- 입력 만들기(순수 계산, LLM·네트워크 없음)

def strip_footer(answer: str) -> str:
    """코드가 붙이는 기준일·판 날짜·출처 줄을 뺀다(61.51 `ragas_d6151.py`와 같은 규칙)."""
    m = FOOTER.search(answer or "")
    return (answer[: m.start()] if m else (answer or "")).rstrip()


def load_dataset(path: Path) -> dict[int, dict]:
    items = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return {int(x["id"]): x for x in items}


def _chunk_map(lines: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ln in lines:
        if ln.strip():
            c = json.loads(ln)
            out[str(c["chunk_id"])] = {"text": c.get("text") or "", "version_date": c.get("version_date")}
    return out


def load_chunks(chunks: Path | None) -> tuple[dict[str, dict], dict[str, Any], str]:
    """(청크 id -> {text, version_date}, 코퍼스 meta, 출처). `deploy_citation_gold.load_corpus`와 같은 순서로 찾는다."""
    if chunks is not None:
        meta_path = chunks.parent / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        return _chunk_map(chunks.read_text(encoding="utf-8").splitlines()), meta, chunks.as_posix()
    if (INDEX_DIR / "chunks.jsonl").is_file():
        return load_chunks(INDEX_DIR / "chunks.jsonl")
    if INDEX_ARCHIVE.is_file():
        with tarfile.open(INDEX_ARCHIVE, "r:gz") as tar:
            data = tar.extractfile("chunks.jsonl").read().decode("utf-8")   # type: ignore[union-attr]
            m = tar.extractfile("meta.json")
            meta = json.loads(m.read().decode("utf-8")) if m else {}
        return _chunk_map(data.splitlines()), meta, f"{INDEX_ARCHIVE.name}:chunks.jsonl"
    if LOCAL_CHUNKS.is_file():
        return _chunk_map(LOCAL_CHUNKS.read_text(encoding="utf-8").splitlines()), {}, LOCAL_CHUNKS.relative_to(REPO).as_posix()
    raise SystemExit("코퍼스 스냅샷이 없다: --chunks로 chunks.jsonl을 주거나 data/index.tar.gz를 둬라")


def read_run_rows(results: Path, runs: list[int] | None) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for rdir in sorted(results.glob("run*"), key=lambda p: p.name):
        m = re.fullmatch(r"run(\d+)", rdir.name)
        rows_path = rdir / "rows.jsonl"
        if not m or not rows_path.is_file() or (runs and int(m.group(1)) not in runs):
            continue
        rows = []
        for ln in rows_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    continue
        out[int(m.group(1))] = rows
    return out


def build_samples(rows_by_run: dict[int, list[dict]], dataset: dict[int, dict], chunks: dict[str, dict]) -> tuple[list[dict], dict[str, Any]]:
    """결과 행 + 평가셋 + 코퍼스 스냅샷 -> RAGAS 입력과 건너뛴 행 집계.

    대상은 평가셋에서 관련(`kind == "relevant"`)이고 성공(`status == "ok"`)하여 답한(`result == "answer"`) 행이다. 이 밖은 건너뛴 행이 아니라 대상 밖이다
    (비관련 문항, 거절·되묻기, 실패 행 수는 `not_target`에 센다)."""
    samples: list[dict] = []
    info: dict[str, Any] = {"rows": 0, "not_target": 0, "no_answer_field": 0, "no_context": 0, "unresolved_ids": 0, "version_date_mismatch": 0, "unknown_dataset_id": 0}
    for run in sorted(rows_by_run):
        for row in rows_by_run[run]:
            info["rows"] += 1
            item = dataset.get(int(row.get("id", -1)))
            if item is None:
                info["unknown_dataset_id"] += 1
                continue
            if item.get("kind") != "relevant" or row.get("status") != "ok" or row.get("result") != "answer":
                info["not_target"] += 1
                continue
            if "answer" not in row:
                info["no_answer_field"] += 1
                continue
            ids = list(dict.fromkeys(str(c) for c in (row.get("cited_chunk_ids") or []) if c))
            dates = {str(c): d for c, d in zip(row.get("cited_chunk_ids") or [], row.get("cited_version_dates") or [])}
            contexts, unresolved = [], 0
            for cid in ids:
                hit = chunks.get(cid)
                if hit is None or not hit["text"].strip():
                    unresolved += 1
                    continue
                if dates.get(cid) and hit.get("version_date") and dates[cid] != hit["version_date"]:
                    info["version_date_mismatch"] += 1
                contexts.append(hit["text"])
            info["unresolved_ids"] += unresolved
            response = strip_footer(str(row.get("answer") or ""))
            if not contexts or not response.strip():
                info["no_context"] += 1
                continue
            samples.append({"run": run, "id": int(item["id"]), "question": item.get("input") or item.get("question") or "", "response": response,
                            "contexts": contexts, "reference": str(item["expected"]), "n_cited": len(ids), "n_unresolved": unresolved})
    info["scored_rows"] = len(samples)
    return samples, info


def estimate(n_rows: int) -> dict[str, Any]:
    """61.51 실측(행당 비용·시간)으로 환산한 추정. 이 실행의 값이 아니다."""
    usd_per_row, source = FALLBACK_USD_PER_ROW, "61.51 실측 1.412301달러/300행(코드 상수)"
    cost_file, rows_file = RATE_REFERENCE / "cost.json", RATE_REFERENCE / "rows.jsonl"
    if cost_file.is_file() and rows_file.is_file():
        n = sum(1 for ln in rows_file.read_text(encoding="utf-8").splitlines() if ln.strip())
        if n:
            usd_per_row = float(json.loads(cost_file.read_text(encoding="utf-8"))["cost_usd"]) / n
            source = f"61.51 실측 {json.loads(cost_file.read_text(encoding='utf-8'))['cost_usd']}달러/{n}행({RATE_REFERENCE.relative_to(REPO).as_posix()})"
    return {"usd_per_row": round(usd_per_row, 5), "usd": round(usd_per_row * n_rows, 3), "minutes": round(SECONDS_PER_ROW * n_rows / 60, 1), "basis": source}


# ---------------------------------------------------------------- 요약(순수 계산)

def _mean(vals: list[float | None]) -> float | None:
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def summarize(rows: list[dict]) -> dict[str, Any]:
    """행별 값 -> 회차별 평균과 전체 평균. 값이 없는 칸(None)은 평균에서 빼고 개수를 적는다."""
    runs = sorted({r["run"] for r in rows})
    per_run = {str(n): {"n": sum(r["run"] == n for r in rows), **{m: _mean([r.get(m) for r in rows if r["run"] == n]) for m in NAMES}} for n in runs}
    overall = {m: _mean([r.get(m) for r in rows]) for m in NAMES}
    missing = {m: sum(r.get(m) is None for r in rows) for m in NAMES}
    # 3회 평균: 회차 평균들의 평균(회차마다 행 수가 다르면 전체 평균과 조금 다르다). 62.25의 충실도 기준은 이 값으로 본다.
    run_means = {m: _mean([per_run[str(n)][m] for n in runs]) for m in NAMES}
    f = run_means["faithfulness"]
    return {"n_rows": len(rows), "per_run": per_run, "mean_of_runs": run_means, "overall_row_mean": overall, "missing_values": missing,
            "faithfulness_line": FAITHFULNESS_LINE, "faithfulness_pass": (f is not None and f >= FAITHFULNESS_LINE)}


def render_markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    lab = {"context_precision": "문맥 정밀도", "context_recall": "문맥 재현율", "faithfulness": "충실도", "answer_relevancy": "답변 관련성"}
    f = lambda v: "-" if v is None else f"{v:.3f}"   # noqa: E731
    lines = [f"# 배포본 RAGAS 채점 (리비전 {meta.get('revision') or '?'}, 사전 등록 62.25)", "",
             f"채점 {summary['n_rows']}행 / 판정 {JUDGE} / 임베딩 {EMBEDDING} / 문맥은 인용한 청크 본문(61.51의 검색한 5개와 다름)", "",
             "| 회차 | 행 | " + " | ".join(lab[m] for m in NAMES) + " |", "|---|---|" + "---|" * len(NAMES)]
    for n, r in summary["per_run"].items():
        lines.append(f"| {n} | {r['n']} | " + " | ".join(f(r[m]) for m in NAMES) + " |")
    lines.append("| 회차 평균 | | " + " | ".join(f(summary["mean_of_runs"][m]) for m in NAMES) + " |")
    lines.append("")
    verdict = "충족" if summary["faithfulness_pass"] else "미달 또는 값 없음"
    lines.append(f"충실도 기준(3회 평균 {FAITHFULNESS_LINE} 이상): {verdict}. 값이 없는 칸 수: " + ", ".join(f"{lab[m]} {n}" for m, n in summary["missing_values"].items()))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 채점 반복(평가 함수를 주입해 시험한다)

def load_done(rows_path: Path) -> tuple[list[dict], set[tuple[int, int]]]:
    rows: list[dict] = []
    if rows_path.is_file():
        for ln in rows_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    done = {(r["run"], r["id"]) for r in rows if all(r.get(m) is not None for m in NAMES)}
    return rows, done


def run_scoring(samples: list[dict], out: Path, evaluate_batch: Callable[[list[dict]], list[dict]], spent: Callable[[], tuple[float, str | None]],
                *, max_cost: float, batch: int = BATCH, log: Callable[[str], None] = print) -> int:
    """남은 행을 `batch`개씩 채점해 `ragas_rows.jsonl`에 이어 쓴다. 0 완료, 3 비용 상한, 4 판정 호출 한도·권한 오류.
    `evaluate_batch(part)`는 part와 같은 길이의 {지표: 값 또는 None} 목록을 돌려주고, 예외를 내면 그 배치는 `error`로 적는다."""
    rows_path = out / "ragas_rows.jsonl"
    _, done = load_done(rows_path)
    todo = [s for s in samples if (s["run"], s["id"]) not in done]
    log(f"채점 대상 {len(samples)}행, 이미 채점 {len(samples) - len(todo)}행, 남은 {len(todo)}행")
    for i in range(0, len(todo), batch):
        cost, bad = spent()
        if cost >= max_cost:
            log(f"채점 비용 {cost:.4f}달러가 상한 {max_cost}달러에 닿아 멈춘다")
            return 3
        if bad:
            log(f"판정 호출 오류 {bad}, 멈춘다")
            return 4
        part = todo[i: i + batch]
        t0 = time.time()
        try:
            scores: list[dict] | None = evaluate_batch(part)
        except Exception as exc:   # noqa: BLE001 - 배치 하나의 실패가 앞 결과를 지우지 않게 한다
            log(f"evaluate 예외 {type(exc).__name__}")
            scores = None
        with rows_path.open("a", encoding="utf-8", newline="\n") as f:
            for k, s in enumerate(part):
                row: dict[str, Any] = {"run": s["run"], "id": s["id"], "n_contexts": len(s["contexts"]), "n_cited": s["n_cited"], "n_unresolved": s["n_unresolved"]}
                if scores is not None:
                    row.update({m: scores[k].get(m) for m in NAMES})
                else:
                    row["error"] = "evaluate 예외"
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        log(f"  {i + len(part)}/{len(todo)} {time.time() - t0:.0f}초 누적 채점 비용 {spent()[0]:.4f}달러")
    cost, bad = spent()
    return 4 if bad else 0


# ---------------------------------------------------------------- 실제 RAGAS 호출(ragas 0.4.3, langchain-anthropic이 있는 환경에서만)

def make_evaluator(cost_path: Path):
    """(evaluate_batch, spent, state) 세 값. 61.51 `ragas_d6151.py`와 같은 설정이다: claude-haiku-5-5는 temperature를 받지 않아 요청에서 뺀다(400),
    생각 토큰 때문에 max_tokens 8192, RAGAS 병렬 8. 채점 호출의 토큰은 단가표(`llm_prices.json`)로 환산해 `cost.json`에 이어 센다(캐시 할인 없이)."""
    import threading
    import urllib.request

    warnings.filterwarnings("ignore")
    for name in ("LLM_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    from datasets import Dataset
    from langchain_anthropic import ChatAnthropic
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.embeddings import Embeddings
    from ragas import RunConfig, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    metrics = [context_precision, context_recall, faithfulness, answer_relevancy]
    assert tuple(m.name for m in metrics) == NAMES
    prices = json.loads(PRICES_FILE.read_text(encoding="utf-8"))["models"][JUDGE]
    api_key, voyage_key = os.environ["ANTHROPIC_API_KEY"], os.environ["VOYAGE_API_KEY"]
    prev = json.loads(cost_path.read_text(encoding="utf-8")) if cost_path.is_file() else {}
    state: dict[str, Any] = {"cost": float(prev.get("cost_usd") or 0), "i": int(prev.get("input_tokens") or 0), "o": int(prev.get("output_tokens") or 0),
                             "calls": int(prev.get("calls") or 0), "bad": None}
    lock = threading.Lock()

    class NoTempAnthropic(ChatAnthropic):
        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            payload.pop("temperature", None)
            return payload

    class Spend(BaseCallbackHandler):
        def on_llm_end(self, response, **kw):
            with lock:
                for gens in response.generations or []:
                    for g in gens:
                        um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                        i, o = int(um.get("input_tokens") or 0), int(um.get("output_tokens") or 0)
                        state["i"] += i
                        state["o"] += o
                        state["calls"] += 1
                        state["cost"] += (i * prices["input"] + o * prices["output"]) / 1e6
                cost_path.write_text(json.dumps({"cost_usd": round(state["cost"], 6), "input_tokens": state["i"], "output_tokens": state["o"], "calls": state["calls"], "judge": JUDGE}), encoding="utf-8")

        def on_llm_error(self, error, **kw):
            if type(error).__name__ in BAD_ERRORS:
                state["bad"] = type(error).__name__

    class Voyage(Embeddings):
        def _call(self, texts, role):
            body = json.dumps({"input": texts, "model": EMBEDDING, "input_type": role}).encode("utf-8")
            for k in range(4):
                try:
                    req = urllib.request.Request("https://api.voyageai.com/v1/embeddings", data=body, headers={"Authorization": f"Bearer {voyage_key}", "Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=120) as r:
                        return [x["embedding"] for x in json.loads(r.read())["data"]]
                except Exception:   # noqa: BLE001
                    if k == 3:
                        raise
                    time.sleep(2 * (k + 1))

        def embed_documents(self, texts):
            return self._call(list(texts), "document")

        def embed_query(self, text):
            return self._call([text], "query")[0]

    llm = LangchainLLMWrapper(NoTempAnthropic(model=JUDGE, api_key=api_key, max_tokens=8192, max_retries=3, timeout=180, callbacks=[Spend()]), bypass_n=True)
    emb = LangchainEmbeddingsWrapper(Voyage())

    def evaluate_batch(part: list[dict]) -> list[dict]:
        data = Dataset.from_dict({"user_input": [s["question"] for s in part], "response": [s["response"] for s in part],
                                  "retrieved_contexts": [s["contexts"] for s in part], "reference": [s["reference"] for s in part]})
        res = evaluate(data, metrics=metrics, llm=llm, embeddings=emb, run_config=RunConfig(max_workers=8, timeout=240, max_retries=3, max_wait=30), show_progress=False, raise_exceptions=False)
        df = res.to_pandas()
        return [{m: (None if df.iloc[k][m] != df.iloc[k][m] else float(df.iloc[k][m])) for m in NAMES} for k in range(len(part))]

    return evaluate_batch, lambda: (state["cost"], state["bad"]), state


# ---------------------------------------------------------------- 실행

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="배포본 측정 결과를 RAGAS 4지표로 채점(사전 등록 62.25)")
    ap.add_argument("--results", required=True, help="deploy_latency 결과 폴더(run1~3/rows.jsonl이 있는 곳)")
    ap.add_argument("--out", required=True, help="RAGAS 결과 폴더(이미 있으면 --resume 없이는 멈춘다)")
    ap.add_argument("--dataset", default=str(DATASET), help="평가셋 JSONL(기본 evals/dataset_v2.jsonl)")
    ap.add_argument("--chunks", default="", help="코퍼스 스냅샷 chunks.jsonl(기본: data/index/chunks.jsonl, data/index.tar.gz 순)")
    ap.add_argument("--runs", default="", help="채점할 회차 번호 쉼표 목록(기본 전부, 61.51과 같음)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N행만(시험용)")
    ap.add_argument("--max-cost", type=float, default=1.0, help="채점 비용 상한(달러). 닿으면 멈춘다")
    ap.add_argument("--revision", default="", help="결과 기록용 배포 리비전 이름")
    ap.add_argument("--dry-run", action="store_true", help="입력만 만들어 개수와 추정을 보인다(LLM·임베딩 호출 없음, 키 필요 없음)")
    ap.add_argument("--resume", action="store_true", help="이미 채점한 행은 건너뛰고 같은 폴더에 이어 쓴다")
    args = ap.parse_args(argv)

    results, out, dataset_path = Path(args.results), Path(args.out), Path(args.dataset)
    if not results.is_dir() or not dataset_path.is_file():
        print(f"결과 폴더 또는 평가셋이 없다: {results} / {dataset_path}", file=sys.stderr)
        return 2
    if not args.dry_run and out.exists() and any(out.iterdir()) and not args.resume:
        print(f"{out}에 이전 결과가 있다. 덮어쓰지 않는다. 이어서 하려면 --resume, 새로 하려면 --out을 바꿔라.", file=sys.stderr)
        return 2
    runs = [int(x) for x in args.runs.split(",") if x.strip()] or None
    rows_by_run = read_run_rows(results, runs)
    if not rows_by_run:
        print(f"{results}에 run*/rows.jsonl이 없다", file=sys.stderr)
        return 2
    dataset = load_dataset(dataset_path)
    chunks, corpus_meta, corpus_source = load_chunks(Path(args.chunks) if args.chunks else None)
    samples, info = build_samples(rows_by_run, dataset, chunks)
    if info["no_answer_field"]:
        print(f"결과 행 {info['no_answer_field']}개에 answer가 없다(답 본문을 남기기 전 도구로 잰 결과). RAGAS는 답 본문이 필요해 채점할 수 없다.", file=sys.stderr)
        return 2
    if args.limit:
        samples = samples[: args.limit]
    est = estimate(len(samples))
    meta = {"revision": args.revision, "results_dir": results.as_posix(), "dataset": dataset_path.name, "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "runs": sorted(rows_by_run), "corpus_source": corpus_source, "corpus_n_chunks": len(chunks), "corpus_meta": {k: corpus_meta.get(k) for k in ("n_chunks", "chunks_sha256", "chunks_fingerprint")},
            "input": info, "estimate": est, "judge": JUDGE, "embedding": EMBEDDING, "contexts": "인용한 청크 본문(61.51은 검색한 5개)", "max_cost_usd": args.max_cost,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    print(f"입력: 결과 행 {info['rows']}, 대상 밖 {info['not_target']}, 문맥 없음 {info['no_context']}, 채점 대상 {len(samples)}행 "
          f"(스냅샷에 없는 인용 id {info['unresolved_ids']}개, 판 날짜 불일치 {info['version_date_mismatch']}개, 코퍼스 {corpus_source})")
    print(f"추정(61.51 실측 환산, 이 실행의 값 아님): 약 {est['usd']}달러, 약 {est['minutes']}분 [{est['basis']}]")
    if args.dry_run:
        print("dry-run: LLM·임베딩을 부르지 않았고 파일도 쓰지 않았다.")
        return 0
    if not samples:
        print("채점할 행이 없다", file=sys.stderr)
        return 2
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key.startswith("sk-ant-") or not os.environ.get("VOYAGE_API_KEY"):
        print("환경 변수 ANTHROPIC_API_KEY(sk-ant- 형식)와 VOYAGE_API_KEY가 필요하다", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "inputs_meta.json"
    if meta_path.is_file():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if old.get("dataset_sha256") != meta["dataset_sha256"]:
            print("이전 결과와 평가셋이 다르다. --out을 바꿔라.", file=sys.stderr)
            return 2
        meta["started_at"] = old.get("started_at", meta["started_at"])
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    evaluate_batch, spent, _ = make_evaluator(out / "cost.json")
    t0 = time.time()
    code = run_scoring(samples, out, evaluate_batch, spent, max_cost=args.max_cost)
    rows, _ = load_done(out / "ragas_rows.jsonl")
    last = {(r["run"], r["id"]): r for r in rows}   # 같은 행을 다시 채점했으면 마지막 줄만 센다(실패 줄은 뺀다)
    summary = summarize([r for r in last.values() if "error" not in r])
    summary["cost_usd"] = round(spent()[0], 6)
    summary["elapsed_s_this_invocation"] = round(time.time() - t0)
    summary["exit_code"] = code
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(render_markdown(summary, meta), encoding="utf-8")
    print(f"완료 코드 {code}, 채점 {summary['n_rows']}행, 충실도 3회 평균 {summary['mean_of_runs']['faithfulness']}, 비용 {summary['cost_usd']}달러, 결과 {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
