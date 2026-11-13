"""정답 근거 청크 전체의 본문 낱말을 원문 스냅샷 줄 범위와 맞춘다 (체크포인트 3조 코멘트 ②, 2026-11-13).

`table_number_source_check_20261113/check.py`는 수치 값과 값 앞뒤 낱말 3개만 본다(그 한계는 EVAL_REPORT 1장 원문 대조 5번 행). 이 스크립트는 수치가 없는 청크까지 포함해
정답 위치에 맞는 청크 전부(v1, v2, 검증, 새 인용 문항)의 본문 낱말이 원문에서 왔는지 본다. 값 이외의 문장이 바뀌었는지 보는 약한 대조다.

방법 (LLM·키·네트워크 없음, 스냅샷 `data/corpus.tar.gz`만):
  1. 청크의 `line_start`~`line_end` 줄을 원문에서 꺼낸다(링크는 글자만 남긴 것과 원본 줄을 함께 센다).
  2. 청크 본문(제목 줄과 앞 청크에서 겹쳐 들어온 `overlap_chars`는 뺀다)의 낱말을 소문자로 세어, 원문 줄 범위의 같은 낱말 개수와 맞춘다.
  3. 원문 줄 범위에서 개수가 모자란 낱말을 분류한다.
     - 개수만 모자람: 낱말이 줄 범위에 있으나 청크에 더 많이 나온다(표 청크가 행마다 열 이름을 되풀이해 적는 경우).
     - 줄 범위에 없고 쪽에는 있음: 쪽의 다른 줄에 있는 낱말(표 머리 줄이 범위 밖인 경우 등).
     - 쪽에도 없음: 원문에 없는 낱말. 이것이 있으면 청크가 원문과 다르다는 신호다.
사용: python evals/results/table_number_source_check_20261113_all/word_check.py
"""
from __future__ import annotations

import json
import re
import sys
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals" / "results" / "table_number_source_check_20261113"))
sys.path.insert(0, str(ROOT))
import check as C  # noqa: E402

OUT = Path(__file__).resolve().parent
SETS = ("v1", "v2", "holdout", "cite_new")


def toks(text: str) -> list[str]:
    return [w.strip(".") for w in C.words(text)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    C.DATASETS[:] = [C.SET_FILES[k][:2] for k in SETS]
    chunks = C.load_chunks()
    by_id = {c.chunk_id: c for c in chunks}
    pages = {p["rule_seq"]: p for p in map(json.loads, (ROOT / "data" / "corpus" / "pages.jsonl").read_text(encoding="utf-8").splitlines())}
    tar = tarfile.open(ROOT / "data" / "corpus.tar.gz")
    qs = C.gold_chunks(chunks)
    which: dict[str, list[str]] = {}
    for q in qs:
        for cid in q["chunk_ids"]:
            which.setdefault(cid, []).append(f"{q['dataset']} {q['id']}")
    rows = []
    for cid, qlist in which.items():
        c = by_id[cid]
        page = pages.get(c.rule_seq)
        member = "handbook/" + page["path"].replace("content/handbook/", "") if page else "authz/authorization-matrix-2023-05.html.md"
        lines = tar.extractfile(member).read().decode("utf-8").split("\n")
        raw = "\n".join(lines[c.line_start - 1 : c.line_end])
        win = Counter(toks(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw) + " " + raw))
        page_words = set(toks("\n".join(lines)))
        _, _, body = c.text.partition("\n")
        need = Counter(toks(body[(c.overlap_chars or 0):]))
        count_only, other_line, absent = Counter(), Counter(), Counter()
        for w, n in need.items():
            short = n - win[w]
            if short <= 0:
                continue
            if win[w] > 0:
                count_only[w] += short
            elif w in page_words:
                other_line[w] += short
            else:
                absent[w] += short
        is_table = c.kind == "row" or bool(re.search(r"<table|<t[dhr]\b|^\s*\|.*\|\s*$|^\s*\|?\s*:?-{3,}", raw, re.M | re.I))
        rows.append({"chunk_id": cid, "questions": qlist, "kind": c.kind, "table": is_table, "page": member, "line_start": c.line_start, "line_end": c.line_end,
                     "body_words": sum(need.values()),
                     "words_over_line_range_count": sum(count_only.values()), "words_only_elsewhere_in_page": sum(other_line.values()), "words_not_in_page": sum(absent.values()),
                     "count_only_examples": dict(count_only.most_common(6)), "elsewhere_examples": dict(other_line.most_common(6)), "absent_examples": dict(absent.most_common(6))})
    rows.sort(key=lambda r: r["chunk_id"])
    n = len(rows)
    full = [r for r in rows if not (r["words_over_line_range_count"] or r["words_only_elsewhere_in_page"] or r["words_not_in_page"])]
    cnt = [r for r in rows if (r["words_over_line_range_count"] or r["words_only_elsewhere_in_page"]) and not r["words_not_in_page"]]
    bad = [r for r in rows if r["words_not_in_page"]]
    summary = {"chunks": n, "all_words_in_line_range": len(full), "extra_words_only_repeats_or_other_lines": len(cnt),
               "extra_words_all_table_chunks": all(r["table"] for r in cnt), "chunks_with_words_not_in_page": len(bad)}
    (OUT / "word_check.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    L = ["# 정답 근거 청크 전체의 본문 낱말 대조 (2026-11-13)", "",
         f"- 대상: v1, v2, 검증, 새 인용 문항의 정답 위치에 맞는 청크 {n}개 전부(수치가 없는 청크 포함). 방법은 `word_check.py` 머리말.",
         f"- 본문 낱말이 모두 원문 줄 범위에 있음: {len(full)}개.",
         f"- 본문 낱말 가운데 줄 범위에 없거나 개수가 모자란 것이 있으나 모두 같은 쪽 안에 있음: {len(cnt)}개 (표 청크 {sum(r['table'] for r in cnt)}개). 열 이름을 행마다 되풀이해 적는 표 청크 구조 때문이다.",
         f"- 원문 쪽에 없는 낱말이 있는 청크: {len(bad)}개.", "",
         "| 청크 id | 문항 | 종류 | 표 | 줄 범위 | 본문 낱말 | 줄 범위의 개수 초과 | 쪽의 다른 줄에만 있음 | 쪽에 없음 | 개수 초과 낱말 예 | 다른 줄 낱말 예 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in cnt + bad:
        L.append(f"| `{r['chunk_id']}` | {', '.join(r['questions'])} | {r['kind']} | {'예' if r['table'] else '아니오'} | `{r['page'].split('/', 1)[1]}` {r['line_start']}~{r['line_end']} | {r['body_words']} | {r['words_over_line_range_count']} | {r['words_only_elsewhere_in_page']} | {r['words_not_in_page']} | {', '.join(r['count_only_examples']) or '-'} | {', '.join(r['elsewhere_examples']) or '-'} |")
    L += ["", "한계: 낱말 개수를 맞춘 약한 대조이며 낱말의 순서와 문장 뜻은 보지 않는다. 표 청크의 열 이름 되풀이는 파싱 방식이므로 불일치로 세지 않았다(EVAL_REPORT 1장 원문 대조 2번 행). 순서와 문장은 사람이 읽은 표본(EVAL_REPORT 1장 원문 대조 7번 행)으로만 봤다."]
    (OUT / "word_check.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
