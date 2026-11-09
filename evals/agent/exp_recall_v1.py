"""답변 리콜 재현율과 정밀도 (SDD 484줄). 실제 개정 커밋 전후 판 쌍으로 잰다. `notices_for`의 호출자다.

    python -m evals.agent.exp_recall_v1 --pairs evals/recall_pairs.jsonl --out evals/results/recall_v1

쌍 파일 한 줄: {"id", "question", "answer", "as_of", "rule_seq", "article", "old_version_date", "new_version_date", "change_type", "expected": true|false}.
쌍 파일은 아직 없다(docs/specs/recall.md 시험 데이터 절의 커밋 12건에서 사람이 만든다).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class _OneAnswer:
    def __init__(self, row: dict):
        self.row = row

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        return [self.row]


def _read_section(rule_seq, article, as_of):
    from backend.rag.retrieve.privacy import redact_chunk
    from backend.rag.retrieve.section import get_section

    s = get_section(rule_seq, article, as_of)
    return redact_chunk(s.model_dump()) if s else None


def run(rows: list[dict], llm, read_section=_read_section) -> dict:
    from backend.graph.recall.notice import notices_for
    from backend.schemas.recall import ChangedArticle

    tp = fp = fn = 0
    out = []
    for r in rows:
        changed = ChangedArticle(rule_seq=r["rule_seq"], article=r["article"], old_version_date=r["old_version_date"],
                                 new_version_date=r["new_version_date"], change_type=r["change_type"])
        row = {"answer_id": str(r["id"]), "user_id": "eval", "question": r["question"], "answer": r["answer"], "as_of": r.get("as_of")}
        got = bool(notices_for(changed, _OneAnswer(row), read_section, llm, use_skills=True))
        tp += got and r["expected"]
        fp += got and not r["expected"]
        fn += (not got) and r["expected"]
        out.append({"id": r["id"], "expected": r["expected"], "notified": got})
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    return {"n": len(rows), "recall": recall, "precision": precision, "rows": out}


def main(argv=None) -> int:
    from backend.services.llm import get_chat_model

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    rows = [json.loads(x) for x in a.pairs.read_text(encoding="utf-8").splitlines() if x.strip()]
    res = run(rows, get_chat_model())
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
