"""질문 분해와 링크 확장 비교 (`evals/PREREGISTER.md` #6, #7). 평가 전용 실험이며 서비스 `search()`와 별개다.

조건은 `voyage-4` 영어 문장 벡터, 청크 800자·겹침 120자, 리랭커 없음, k=5, 동결본 `evals/dataset_v1.jsonl` 30건이다.
변형 네 가지를 한 번에 하나씩만 바꿔 비교한다.

- `base`: 영어 문장 벡터 상위 5
- `L1x2`: 상위 5 가운데 뒤의 2자리를, 상위 5가 링크한 페이지의 청크 중 질문과 가장 가까운 2개로 바꾼다(링크 확장)
- `dec`: 질문을 하위 질문으로 나눠 하위 질문마다 검색하고 번갈아 5개를 채운다(나뉘지 않은 질문은 `base`와 같다)
- `dec+L1x2`: 위 둘을 모두 쓴다

세 단계로 나뉜다. 앞의 둘은 모델을 부르고, `search`는 저장한 값만 읽는다(비용 없음).

    # 1) 분해와 하위 질문 영어 번역. 로컬 Claude CLI(Haiku 5.5)를 쓰며 API 키가 필요 없다. 받은 결과는 다시 부르지 않는다
    python -m evals.retrieval.exp_decompose_v1 prep
    # 2) 하위 질문 벡터. 환경 변수 VOYAGE_API_KEY가 필요하다(유료 API)
    python -m evals.retrieval.exp_decompose_v1 embed
    # 3) 검색과 채점. 저장한 분해, 번역, 벡터만 읽는다. --out을 주면 결과 JSON을 쓴다
    python -m evals.retrieval.exp_decompose_v1 search --variant dec+L1x2 --check-stored

필요한 로컬 파일(저장소에 넣지 않는 것, `data/data.md`): `data/chunks/chunks.jsonl`, `data/parsed/document_ir.jsonl`,
`data/index_exp/voyage-4.npy`, `data/index_exp/voyage-4.queries.json`, `data/index_exp/chunk_ids.json`.
`--check-stored`는 `evals/results/retrieval_fix_v1/decompose/voyage/<변형>.json`에 저장된 검색 결과와 지표를 다시 계산한 값과 비교한다.
답 생성과 인용 집계는 `exp_answer_v1.py`가 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urldefrag, urljoin

import numpy as np

from evals.retrieval import experiment_v1 as ev
from evals.retrieval.run import evaluate, load_dataset, load_exclusions

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "chunks" / "chunks.jsonl"
IR = ROOT / "data" / "parsed" / "document_ir.jsonl"
MANIFEST = ROOT / "data" / "manifest.jsonl"
CACHE = ROOT / "data" / "index_exp"
FIX = ROOT / "evals" / "results" / "retrieval_fix_v1"
DEC = FIX / "decompose"
DATASET = ROOT / "evals" / "dataset_v1.jsonl"
KEEP = ("chunk_id", "rule_seq", "rule_title", "article", "line_start", "line_end", "text", "source_url", "kind")
VARIANTS = ("base", "L1x2", "dec", "dec+L1x2")
POOL = 100

SYSTEM = (
    "너는 사내 핸드북 검색을 위한 질문 분해기다. 사용자의 한국어 질문이 서로 다른 사실을 둘 이상 묻는 경우에만 독립된 한국어 하위 질문(최대 3개)으로 나눈다.\n"
    "- 하나의 사실을 묻는 질문, 같은 사실을 다른 말로 두 번 묻는 질문, 하나의 사실에 조건·예외를 붙인 질문은 나누지 않는다.\n"
    "- 하위 질문은 질문에 있는 핵심 용어를 그대로 쓰고, 질문에 없는 정보를 더하지 않는다. 각 하위 질문만 읽어도 무엇을 묻는지 알 수 있어야 한다.\n"
    "- 나누지 않으면 split을 false로 하고 sub_questions는 빈 목록으로 둔다.\n"
    "- 설명 없이 JSON 한 개만 출력한다. 예 1: 질문 \"배송은 며칠 걸리고 반품 수수료는 얼마야?\" -> {\"split\": true, \"sub_questions\": [\"배송은 며칠 걸려?\", \"반품 수수료는 얼마야?\"]}. "
    "예 2: 질문 \"휴가 신청은 어떻게 해?\" -> {\"split\": false, \"sub_questions\": []}."
)


# ---------- 1) 분해와 번역 (Claude CLI, 키 없음) ----------

def _cli(system: str, text: str) -> tuple[str, float, dict]:
    exe = shutil.which("claude") or shutil.which("claude.exe")
    if not exe:
        raise RuntimeError("claude CLI를 찾지 못했다")
    cmd = [exe, "-p", "--model", ev.CLI_MODEL, "--output-format", "json", "--safe-mode", "--tools", "", "--no-session-persistence", "--system-prompt", system]
    with tempfile.TemporaryDirectory(prefix="claude_cli_") as cwd:
        out = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, cwd=cwd)
    d = json.loads(out.stdout)
    return str(d.get("result", "")), float(d.get("total_cost_usd") or 0), d.get("usage") or {}


def parse_split(text: str) -> dict | None:
    """분해 응답 JSON을 읽는다. 형식이 틀리면 None."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        o = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(o.get("split"), bool) or not isinstance(o.get("sub_questions"), list):
        return None
    if not all(isinstance(x, str) and x.strip() for x in o["sub_questions"]):
        return None
    return o


def prep(args) -> int:
    DEC.mkdir(parents=True, exist_ok=True)
    items = load_dataset(DATASET)
    f = DEC / "decomposition.json"
    dec = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"model": ev.CLI_MODEL, "system_prompt": SYSTEM, "items": {}}
    for it in items:
        k = str(it["id"])
        if k in dec["items"]:
            continue
        for att in range(1, 4):
            text, cost, usage = _cli(SYSTEM, it["input"])
            o = parse_split(text)
            if o:
                subs = [s.strip() for s in o["sub_questions"]][:3]
                split = bool(o["split"]) and len(subs) >= 2 and all(s != it["input"] for s in subs)
                dec["items"][k] = {"question": it["input"], "kind": it["kind"], "split": split, "sub_questions": subs if split else [], "raw": text,
                                   "attempts": att, "cost_usd": cost, "usage": usage}
                break
        else:
            raise SystemExit(f"분해 3번 실패: {k}")
        f.write_text(json.dumps(dec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(k, dec["items"][k]["split"], dec["items"][k]["sub_questions"], flush=True)
    tf = DEC / "subq_translations.json"
    tr = json.loads(tf.read_text(encoding="utf-8")) if tf.is_file() else {"model": ev.CLI_MODEL, "calls": 0, "cost_usd": 0.0, "items": {}}
    for v in dec["items"].values():
        for s in v["sub_questions"]:
            cur = tr["items"].setdefault(s, {})
            for kind in ev.PROMPTS:
                if ev.valid_english(cur.get(kind, "")):
                    continue
                for _ in range(3):
                    text, cost = ev._cli_translate(s, kind)
                    tr["calls"] += 1
                    tr["cost_usd"] = round(tr["cost_usd"] + cost, 6)
                    if ev.valid_english(text):
                        cur[kind] = text
                        break
                else:
                    raise SystemExit(f"번역({kind}) 3번 실패: {s}")
            tf.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
    print("끝", "split", sum(v["split"] for v in dec["items"].values()), "/", len(dec["items"]), "번역 호출", tr["calls"])
    return 0


# ---------- 2) 하위 질문 벡터 (Voyage API, 환경 변수 VOYAGE_API_KEY) ----------

def embed(args) -> int:
    if not os.environ.get("VOYAGE_API_KEY"):
        raise SystemExit("환경 변수 VOYAGE_API_KEY가 없다")
    dec = json.loads((DEC / "decomposition.json").read_text(encoding="utf-8"))["items"]
    tr = json.loads((DEC / "subq_translations.json").read_text(encoding="utf-8"))["items"]
    qv = json.loads((CACHE / "voyage-4.queries.json").read_text(encoding="utf-8"))
    subs = []
    for v in dec.values():
        for s in v["sub_questions"]:
            if s not in subs:
                subs.append(s)
    probe = next(iter(json.loads(ev.TRANSLATIONS.read_text(encoding="utf-8"))["items"]))  # 기존 질문 하나로 경로를 점검한다
    sentence = json.loads(ev.TRANSLATIONS.read_text(encoding="utf-8"))["items"][probe]["sentence"]
    used = [0]
    ev.VOYAGE_MAX_TOKENS = 200_000
    m = ev._voyage([sentence] + [tr[s]["sentence"] for s in subs], "query", used)
    old = np.asarray(qv[ev.qkey(probe)]["en"], dtype=np.float32)
    cos = float(m[0] @ old / np.linalg.norm(old))
    print("하위 질문", len(subs), "점검 코사인", round(cos, 5), "토큰", used[0])
    if cos <= 0.999:
        raise SystemExit("기존 질문 벡터와 다르다: 중단")
    out = {"tokens": used[0], "probe_cos": cos, "vec": {ev.qkey(s): m[i + 1].tolist() for i, s in enumerate(subs)}}
    (DEC / "subq_vec_voyage.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


# ---------- 3) 검색 (저장한 값만 읽는다) ----------

def _norm(u: str) -> str:
    return urldefrag(u)[0].rstrip("/")


class Links:
    """청크가 링크한 다른 페이지(rule_seq) 목록과 페이지별 청크 위치."""

    def __init__(self, raw: list[dict], chunks: list[SimpleNamespace]):
        ir = {}
        for line in IR.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            ir[d["element_id"]] = d.get("links") or []
        url2seq = {}
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = json.loads(line)
                url2seq[_norm(m["source_url"])] = str(m["doc_id"])
        self.target = []
        for c in raw:
            s = set()
            for e in c["element_ids"]:
                for u in ir.get(e, []):
                    q = url2seq.get(_norm(urljoin(c["source_url"], u)))
                    if q and q != str(c["rule_seq"]):
                        s.add(q)
            self.target.append(s)
        self.page: dict[str, list[int]] = {}
        for i, c in enumerate(chunks):
            self.page.setdefault(str(c.rule_seq), []).append(i)

    def pick(self, top: list[int], sims: np.ndarray, n: int) -> list[int]:
        """상위 5 밖에서, 상위 5가 링크한 페이지의 청크 가운데 질문 유사도가 높은 n개."""
        seen = set(top)
        seqs: set[str] = set()
        for i in top:
            seqs |= self.target[i]
        pool = sorted((j for s in seqs for j in self.page.get(s, []) if j not in seen), key=lambda j: -sims[j])
        return pool[:n]


def roundrobin(lists: list[list[int]], k: int = 5) -> list[int]:
    out, r = [], 0
    while len(out) < k and r < max(len(x) for x in lists):
        for x in lists:
            if r < len(x) and x[r] not in out:
                out.append(x[r])
                if len(out) == k:
                    break
        r += 1
    return out


def make_search(variant: str, chunks, docs, links, qv, split_of, sub_vec, link_n: int = 2):
    """변형 하나의 검색 함수. 질문마다 한 번만 계산한다."""
    use_dec, use_link = variant.startswith("dec"), "L1x2" in variant
    cache: dict[str, list[int]] = {}

    def compute(q: str) -> list[int]:
        en = docs @ np.asarray(qv[ev.qkey(q)]["en"], dtype=np.float32)
        subs = split_of.get(q) if use_dec else None
        if subs:
            top = roundrobin([list(ev._top(docs @ np.asarray(sub_vec[ev.qkey(s)], dtype=np.float32), POOL)) for s in subs], 5)
        else:
            top = list(ev._top(en, 5))[:5]
        if use_link:
            ext = links.pick(top, en, link_n)
            top = top[:5 - len(ext)] + ext
        return top

    def search(q):
        if q.query not in cache:
            cache[q.query] = compute(q.query)
        return [chunks[i] for i in cache[q.query]][:q.k]
    return search


def load_cell():
    """800/120 청크(장 전체 칸 포함), 벡터, 질문 벡터를 읽고 색인이 청크와 맞는지 확인한다."""
    raw = [json.loads(x) for x in CHUNKS.read_text(encoding="utf-8").splitlines() if x.strip()]
    chunks = [SimpleNamespace(**{k: v for k, v in c.items() if k in KEEP}) for c in raw]
    if json.loads((CACHE / "chunk_ids.json").read_text(encoding="utf-8")) != [c.chunk_id for c in chunks]:
        raise SystemExit("색인과 청크가 다르다")
    docs = np.load(CACHE / "voyage-4.npy")
    qv = json.loads((CACHE / "voyage-4.queries.json").read_text(encoding="utf-8"))
    return raw, chunks, docs, qv


def summary_brief(s: dict) -> dict:
    return {k: (round(s[k]["value"], 4) if s[k]["value"] is not None else None) for k in ("recall@5", "hit@5", "rr", "ndcg@5")}


def run_variant(variant: str, cell, items) -> dict:
    raw, chunks, docs, qv = cell
    dec = json.loads((DEC / "decomposition.json").read_text(encoding="utf-8"))["items"]
    sub_vec = json.loads((DEC / "subq_vec_voyage.json").read_text(encoding="utf-8"))["vec"]
    split_of = {it["input"]: dec[str(it["id"])]["sub_questions"] for it in items}
    search = make_search(variant, chunks, docs, Links(raw, chunks), qv, split_of, sub_vec)
    t0 = time.perf_counter()
    res = evaluate(items, search, 5, exclusions=load_exclusions(ROOT / "evals" / "exclusions.json"), corpus=chunks)
    rel = [r for r in res["rows"] if r["kind"] == "relevant" and r.get("scored")]
    return {"variant": variant, "seconds": round(time.perf_counter() - t0, 1), "summary": summary_brief(res["summary"]), "rows": res["rows"],
            "not_found": [r["id"] for r in rel if r["recall@5"] == 0], "partial": [r["id"] for r in rel if 0 < r["recall@5"] < 1],
            "recall_by_id": {r["id"]: round(r["recall@5"], 4) for r in rel}, "split_ids": sorted(it["id"] for it in items if split_of[it["input"]])}


def check_stored(out: dict) -> bool:
    """저장된 결과와 지표, 질문마다 돌려준 청크가 같은지 본다. 점수가 거의 같은 청크는 순서만 바뀔 수 있어 청크 집합으로 비교한다."""
    v = out["variant"]
    path = DEC / "voyage" / f"{v}.json" if v.startswith("dec") else FIX / "voyage" / f"{v}.json"
    if not path.is_file():
        print("저장된 결과 없음:", path.name)
        return False
    old = json.loads(path.read_text(encoding="utf-8"))
    old_s = old.get("summary_frozen") or old["summary"]
    old_rows = old.get("rows_frozen") or old["rows"]
    old_vals = {k: round(old_s[k]["value"], 4) if isinstance(old_s[k], dict) else round(old_s[k], 4) for k in ("recall@5", "hit@5", "rr", "ndcg@5")}
    same_vals = old_vals == out["summary"]
    pairs = list(zip(old_rows, out["rows"]))
    same_set = all(set(a["returned"]) == set(b["returned"]) for a, b in pairs)
    order_diff = [a["id"] for a, b in pairs if a["returned"] != b["returned"]]
    print(f"저장값 {old_vals}\n다시 계산 {out['summary']}\n지표 일치 {same_vals} / 질문마다 돌려준 청크 집합 일치 {same_set} / 순서만 다른 문항 {order_diff}")
    return same_vals and same_set


def search_cmd(args) -> int:
    items = load_dataset(DATASET)
    cell = load_cell()
    variants = VARIANTS if args.variant == "all" else (args.variant,)
    ok = True
    for v in variants:
        out = run_variant(v, cell, items)
        s = out["summary"]
        print(f"{v}: Recall@5 {s['recall@5']:.3f} hit@5 {s['hit@5']:.3f} MRR {s['rr']:.3f} nDCG@5 {s['ndcg@5']:.3f} 못 찾음 {out['not_found']} 일부 {out['partial']} 나뉜 문항 {out['split_ids'] if v.startswith('dec') else '쓰지 않음'}")
        if args.check_stored:
            ok = check_stored(out) and ok
        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            (Path(args.out) / f"{v}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep", help="분해와 하위 질문 영어 번역(Claude CLI)").set_defaults(fn=prep)
    sub.add_parser("embed", help="하위 질문 벡터(Voyage API, VOYAGE_API_KEY)").set_defaults(fn=embed)
    p = sub.add_parser("search", help="검색과 채점(저장한 값만 읽음, 비용 없음)")
    p.add_argument("--variant", default="dec+L1x2", choices=(*VARIANTS, "all"))
    p.add_argument("--check-stored", action="store_true", help="저장된 결과와 지표, 돌려준 청크를 비교한다")
    p.add_argument("--out", help="결과 JSON을 쓸 폴더(없으면 쓰지 않는다)")
    p.set_defaults(fn=search_cmd)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
