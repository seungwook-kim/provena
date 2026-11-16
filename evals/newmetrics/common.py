"""새 지표 측정기 공통 부분: 경로, 번호 범위·예시 제외, 애매 표시, 정밀도·재현율, 결과 폴더, 비용 장부, DB 연결, 줄 -> 제목 경로."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import backend

from evals.newmetrics.spec_tables import EXCLUDED_COMMITS

REPO = Path(backend.__file__).resolve().parents[1]
CORPUS = REPO / "data" / "corpus"
HANDBOOK = CORPUS / "handbook"
PAGES = CORPUS / "pages.jsonl"
AUTHZ_MD = CORPUS / "authz" / "authorization-matrix-2023-05.html.md"
AUTHZ_CELLS = REPO / "data" / "parsed" / "authz_cells.jsonl"
INDEX_CHUNKS = REPO / "data" / "index" / "chunks.jsonl"
INDEX_LINKS = REPO / "data" / "index" / "links.jsonl"
HANDBOOK_CACHE = Path(os.environ.get("HANDBOOK_CACHE") or (Path.home() / ".cache" / "provena" / "handbook"))
KST = timezone(timedelta(hours=9))

GOLD_FILES = {"recall": "recall_pairs.jsonl", "decision": "decision_cells_gold.jsonl", "link": "link_gold.jsonl", "maintenance": "maintenance_gold.jsonl"}
ID_PATTERNS = {
    "recall": re.compile(r"^R(0[1-9]|[12]\d|3[0-6])$"),
    "decision": re.compile(r"^D(0[1-9]|[1-3]\d|40)$"),
    "link": re.compile(r"^L(00[1-9]|0[1-9]\d|100)$"),
    "maintenance": re.compile(r"^M(0[1-9]|[1-5]\d|60)$"),
}
AMBIGUOUS = "애매"


class GoldError(ValueError):
    """정답 파일이 측정에 쓸 수 없는 모양이다(예시 행, 범위 밖 번호, 뺀 커밋, 중복)."""


def check_rows(metric: str, rows: list[dict]) -> None:
    """측정 전에 반드시 부른다. 작성 예시(X, X1, X2)·범위 밖 번호·뺀 커밋(4667e540)·중복 번호가 있으면 멈춘다."""
    pat, seen = ID_PATTERNS[metric], set()
    for r in rows:
        rid = str(r.get("id") or "")
        if not pat.match(rid):
            raise GoldError(f"{metric}: 측정할 수 없는 번호 {rid!r}(작성 예시이거나 범위 밖)")
        if rid in seen:
            raise GoldError(f"{metric}: 같은 번호가 두 번 있다 {rid}")
        seen.add(rid)
        commit = str(r.get("commit") or "")
        if any(commit.startswith(c) for c in EXCLUDED_COMMITS):
            raise GoldError(f"{metric}: 측정에서 뺀 커밋 {commit}의 행 {rid}")


def is_ambiguous(note: str | None) -> bool:
    return AMBIGUOUS in str(note or "")


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p is not None and r is not None and p + r else (0.0 if p == 0 or r == 0 else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f)}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def mean(xs: Iterable[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def write_results(out: Path, summary: dict, md: str, rows: list[dict] | None = None) -> None:
    """다른 evals/results 폴더와 같은 모양: summary.json(메타·지표), summary.md(사람이 읽는 표), rows.jsonl(행별 결과)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "summary.md").write_text(mask(md), encoding="utf-8", newline="\n")
    if rows is not None:
        write_jsonl(out / "rows.jsonl", rows)


def gold_meta(path: Path) -> dict:
    return {"file": str(path), "sha256": sha256_file(path), "rows": len(read_jsonl(path))}


# ---------- 비용 장부 (여러 실행이 같은 파일을 본다) ----------

class CostLedger:
    """작업 전체 상한(total_cap)과 실행별 상한(run_cap). 운영 서버가 쓰는 LLM 비용은 직접 셀 수 없어 실행 전 추정치를 적고 '추정'으로 표시한다."""

    def __init__(self, path: Path, total_cap: float):
        self.path, self.total_cap = Path(path), float(total_cap)

    def _rows(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def spent(self) -> float:
        return round(sum(float(r["usd"]) for r in self._rows()), 6)

    def remaining(self) -> float:
        return round(self.total_cap - self.spent(), 6)

    def allow(self, usd: float, run_cap: float) -> tuple[bool, str]:
        if usd > run_cap:
            return False, f"실행 추정 {usd:.4f}달러가 실행 상한 {run_cap:.4f}달러를 넘는다"
        if usd > self.remaining():
            return False, f"실행 추정 {usd:.4f}달러가 남은 전체 상한 {self.remaining():.4f}달러를 넘는다"
        return True, "ok"

    def add(self, metric: str, run: int, usd: float, kind: str) -> None:
        rows = self._rows()
        rows.append({"metric": metric, "run": run, "usd": round(float(usd), 6), "kind": kind, "at": now_kst()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 환경 변수·DB (값은 출력·저장하지 않는다) ----------

SECRET_ENVS = ("DATABASE_URL", "SERVICE_API_KEY", "PROBE_A_LOGIN", "PROBE_A_PASSWORD", "PROBE_B_LOGIN", "PROBE_B_PASSWORD",
               "NIGHT_A_LOGIN", "NIGHT_A_PASSWORD", "NIGHT_LAT_LOGIN", "NIGHT_LAT_PASSWORD")


def mask(text: Any) -> str:
    s = str(text)
    for name in SECRET_ENVS:
        v = os.environ.get(name) or ""
        if len(v) >= 4:
            s = s.replace(v, "<가림>")
    return re.sub(r"postgres(ql)?://\S+", "<db>", s)


def say(*parts: Any) -> None:
    print(mask(" ".join(str(p) for p in parts)), flush=True)


def load_dotenv_keys(path: Path, keys: tuple[str, ...]) -> list[str]:
    """`.env`에서 고른 키만 이 프로세스 환경 변수에 넣는다(이미 있으면 두고). 넣은 키 이름 목록을 돌려준다. 값은 출력하지 않는다."""
    done = []
    if not Path(path).exists():
        return done
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k in keys and not os.environ.get(k):
            os.environ[k] = v.strip().strip('"').strip("'")
            done.append(k)
    return done


def connect_ro(dsn: str | None = None):
    """읽기 전용 세션(SET default_transaction_read_only = on). 쓰기 문장은 DB가 거부한다."""
    import psycopg

    conn = psycopg.connect(dsn or os.environ["DATABASE_URL"], connect_timeout=10, autocommit=True, prepare_threshold=None)
    conn.execute("SET default_transaction_read_only = on")
    return conn


def connect_rw(dsn: str | None = None):
    """쓰기 세션(autocommit 꺼짐: 넣기·지우기를 한 트랜잭션으로 묶는다). 리콜 운영 측정의 시험 행에만 쓴다."""
    import psycopg

    return psycopg.connect(dsn or os.environ["DATABASE_URL"], connect_timeout=10, autocommit=False, prepare_threshold=None)


# ---------- 페이지·줄 -> 제목 경로 ----------

def read_pages() -> dict[str, dict]:
    """코퍼스 경로(content/handbook/ 다음) -> pages.jsonl 줄."""
    out = {}
    for r in read_jsonl(PAGES):
        out[r["path"].removeprefix("content/handbook/")] = r
    return out


def page_rule_seq(rel: str) -> int:
    from backend.rag.ingest.handbook import rule_seq

    return rule_seq("content/handbook/" + rel)


def line_articles(rel: str, raw: str | None = None) -> list[str | None]:
    """쪽의 줄마다(1부터, 0번 칸은 비움) 그 줄이 속한 제목 경로(chunk.article 규칙: 1~4단계 제목을 " > "로 이음, 첫 제목 앞은 None).
    제목 경로는 시스템 파서(parse_page)의 규칙으로 만든다: 시스템 섹션 이름과 정확히 맞추기 위해서다. 링크의 존재·대상은 정답 그대로 쓴다."""
    from backend.rag.ingest.diff import HEADER_LEVELS
    from backend.rag.ingest.parse import parse_page
    from backend.rag.ingest.snapshot_diff import page_of

    raw = raw if raw is not None else (HANDBOOK / rel).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    n = raw.count("\n") + 1
    out: list[str | None] = [None] * (n + 1)
    marks: list[tuple[int, int, str | None]] = []
    for el in parse_page(page_of("content/handbook/" + rel), raw, collections.Counter()):
        path = [h for h in el["heading_path"]][:HEADER_LEVELS]
        marks.append((el["line_start"], el["line_end"], " > ".join(path) if path else None))
    marks.sort()
    cur = None
    j = 0
    for ln in range(1, n + 1):
        while j < len(marks) and marks[j][0] <= ln:
            cur = marks[j][2]
            j += 1
        out[ln] = cur
    for s, e, art in marks:          # 요소 안의 줄은 그 요소의 경로
        for ln in range(s, min(e, n) + 1):
            out[ln] = art
    return out


def section_key(s: str | None) -> str:
    """섹션 이름 비교용: 대소문자·공백·기호 차이를 지운다."""
    return re.sub(r"[^0-9a-z가-힣>]+", "", str(s or "").casefold())
