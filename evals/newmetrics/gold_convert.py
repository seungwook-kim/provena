"""채운 요청 문서(md 표) -> 정답 jsonl 네 개. 칸 글자는 고치지 않는다(앞뒤 공백, 감싼 백틱만 뗀다).

    python -m evals.newmetrics.gold_convert 박진형.md 강경희.md --out-dir evals [--no-history]

- 표는 머리 칸 이름으로 알아본다(리콜: "결론 바뀜"+"질문", 결정표: "구간 줄"+"Manager", 링크: "출발 페이지"+"링크 주소", 후보: "링크하는 페이지"+"함께 봐야").
- 번호가 범위 밖인 행(작성 예시 X, X1, X2)은 버린다. 내용 칸이 모두 빈 행(안 쓴 번호)도 버린다.
- 두 파일에 같은 번호가 내용이 있는 채로 둘 다 있고 내용이 다르면 멈춘다(어느 쪽이 정답인지 정하지 않는다).
- 리콜 행에는 요청 문서 1-1의 배정 표(번호 범위)로 커밋·페이지·섹션을 붙이고, 핸드북 캐시가 있으면 rule_seq·시스템 섹션 이름·판 날짜·기준일·변경 종류를 채운다
  (`exp_recall_v1` 쌍 파일 칸: id, question, answer, as_of, rule_seq, article, old_version_date, new_version_date, change_type, expected).
출력: <out-dir>/recall_pairs.jsonl, decision_cells_gold.jsonl, link_gold.jsonl, maintenance_gold.jsonl, gold_convert_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from evals.newmetrics.common import GOLD_FILES, ID_PATTERNS, is_ambiguous, write_jsonl
from evals.newmetrics.spec_tables import (ROLES, category_for_line, maintenance_revision, parser_category, recall_group)

YES, NO = "예", "아니오"


def split_row(line: str) -> list[str]:
    """`| a | b |` -> ["a", "b"]. `\\|`와 백틱 안의 `|`는 칸 구분이 아니다."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, tick, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "`":
            tick = not tick
        if ch == "|" and not tick:
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur))
    return [c.strip() for c in cells]


def clean(cell: str) -> str:
    c = cell.strip()
    if len(c) >= 2 and c.startswith("`") and c.endswith("`") and c.count("`") == 2:
        c = c[1:-1].strip()
    return c


def tables(md: str) -> list[tuple[list[str], list[list[str]], int]]:
    """md 안의 표마다 (머리, 행들, 첫 줄 번호)."""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            head = split_row(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            out.append((head, rows, i + 1))
            i = j
        else:
            i += 1
    return out


def kind_of(head: list[str]) -> str | None:
    h = " ".join(head)
    if "결론 바뀜" in h and "질문" in h:
        return "recall"
    if "구간 줄" in h and "Manager" in h:
        return "decision"
    if "출발 페이지" in h and "링크 주소" in h:
        return "link"
    if "링크하는 페이지" in h and "함께 봐야" in h:
        return "maintenance"
    return None


def col(head: list[str], *names: str) -> int:
    for i, h in enumerate(head):
        if all(n in h for n in names):
            return i
    raise KeyError(names)


def _get(row: list[str], i: int) -> str:
    return clean(row[i]) if i < len(row) else ""


def _int(s: str) -> int | None:
    s = s.strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def _lines(s: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", s)]


def _yn(s: str) -> bool | None:
    t = s.strip()
    return True if t == YES else False if t == NO else None


def _path(s: str) -> str:
    p = clean(s)
    for pre in ("data/corpus/handbook/", "content/handbook/"):
        p = p.removeprefix(pre)
    return p


def parse_recall(head, row) -> dict | None:
    rid = _get(row, col(head, "id"))
    q, a = _get(row, col(head, "질문")), _get(row, col(head, "지난 답"))
    old_e, new_e = _get(row, col(head, "개정 전 근거")), _get(row, col(head, "개정 뒤 근거"))
    note = _get(row, col(head, "비고"))
    if not (q or a or old_e or new_e):
        return None
    g = recall_group(rid)
    ch = _get(row, col(head, "결론 바뀜"))
    return {"id": rid, "author": g.author, "commit": g.commit, "commit_full": g.commit_full, "page": g.page, "section": g.section,
            "commit_cell": _get(row, col(head, "커밋")), "expected": _yn(ch), "expected_raw": ch, "question": q, "answer": a,
            "old_evidence": old_e, "new_evidence": new_e, "note": note, "ambiguous": is_ambiguous(note)}


def parse_decision(head, row) -> dict | None:
    rid = _get(row, col(head, "id"))
    cat, band, line = _get(row, col(head, "업무 종류")), _get(row, col(head, "구간")), _get(row, col(head, "구간 줄"))
    if not (cat or band or line):
        return None
    cells = {}
    for role in ROLES:
        idx = next(i for i, h in enumerate(head) if h.strip() == role)
        cells[role] = _get(row, idx)
    note = _get(row, col(head, "비고"))
    ln = _int(line)
    return {"id": rid, "author": "박진형" if int(rid[1:]) <= 20 else "강경희", "category": cat, "category_by_line": category_for_line(ln) if ln else None,
            "parser_category": parser_category(cat) if cat else None, "band": band, "band_line": ln, "band_line_raw": line, "cells": cells,
            "note": note, "ambiguous": is_ambiguous(note)}


def parse_link(head, row) -> dict | None:
    rid = _get(row, col(head, "id"))
    src, url = _get(row, col(head, "출발 페이지")), _get(row, col(head, "링크 주소"))
    if not (src or url):
        return None
    line = _get(row, col(head, "줄 번호"))
    target = _get(row, col(head, "대상 페이지"))
    note = _get(row, col(head, "비고"))
    return {"id": rid, "author": "박진형" if int(rid[1:]) <= 50 else "강경희", "source_page": _path(src), "line": _int(line), "line_raw": line,
            "section": _get(row, col(head, "섹션")), "url": url, "target": target if target in ("코퍼스 밖", "자기 페이지", "비공개") else _path(target),
            "target_raw": target, "note": note, "ambiguous": is_ambiguous(note)}


def parse_maintenance(head, row) -> dict | None:
    rid = _get(row, col(head, "id"))
    page = _get(row, col(head, "링크하는 페이지"))
    if not page:
        return None
    rev = maintenance_revision(rid)
    yn = _get(row, col(head, "함께 봐야"))
    reason = _get(row, col(head, "이유"))
    return {"id": rid, "author": rev["author"], "commit": rev["commit"], "revised_page": rev["page"], "linking_page": _path(page),
            "lines": _lines(_get(row, col(head, "줄 번호"))), "lines_raw": _get(row, col(head, "줄 번호")), "section": _get(row, col(head, "섹션")),
            "needed": _yn(yn), "needed_raw": yn, "reason": reason, "ambiguous": is_ambiguous(reason)}


PARSERS = {"recall": parse_recall, "decision": parse_decision, "link": parse_link, "maintenance": parse_maintenance}


def convert(texts: list[tuple[str, str]]) -> tuple[dict[str, list[dict]], dict]:
    """[(파일 이름, md 글)] -> ({지표: 행 목록}, 보고). 예시·빈 행은 버리고 센다."""
    got: dict[str, dict[str, dict]] = {k: {} for k in PARSERS}
    report = {"files": [n for n, _ in texts], "skipped_examples": 0, "skipped_empty": 0, "duplicates_same": 0, "conflicts": []}
    for name, md in texts:
        for head, rows, at in tables(md):
            kind = kind_of(head)
            if kind is None:
                continue
            for row in rows:
                rid = clean(row[0]) if row else ""
                if not ID_PATTERNS[kind].match(rid):
                    report["skipped_examples"] += 1
                    continue
                rec = PARSERS[kind](head, row)
                if rec is None:
                    report["skipped_empty"] += 1
                    continue
                rec["source_file"] = name
                old = got[kind].get(rid)
                if old is not None:
                    same = {k: v for k, v in old.items() if k != "source_file"} == {k: v for k, v in rec.items() if k != "source_file"}
                    if same:
                        report["duplicates_same"] += 1
                        continue
                    report["conflicts"].append({"metric": kind, "id": rid, "files": [old["source_file"], name]})
                    continue
                got[kind][rid] = rec
    out = {k: [v[i] for i in sorted(v, key=lambda x: int(x[1:]))] for k, v in got.items()}
    report["rows"] = {k: len(v) for k, v in out.items()}
    return out, report


def fill_recall(rows: list[dict], history) -> list[str]:
    """핸드북 캐시로 리콜 쌍의 시스템 칸을 채운다. 못 채운 이유 목록."""
    problems, cache = [], {}
    for r in rows:
        key = (r["commit"], r["page"], r["section"])
        if key not in cache:
            try:
                cache[key] = history.section_change(r["commit"], r["page"], r["section"])
            except Exception as e:  # noqa: BLE001 - 검증기가 다시 잡는다
                cache[key] = e
        c = cache[key]
        if isinstance(c, Exception):
            problems.append(f"{r['id']}: {c}")
            continue
        r.update({"commit_full": c.commit_full, "rule_seq": c.rule_seq, "article": c.article, "change_type": c.change_type,
                  "old_version_date": c.old_version_date, "new_version_date": c.new_version_date, "as_of": c.as_of,
                  "source_url": c.source_url, "date_adjusted": c.date_adjusted})
    return problems


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="채운 요청 문서 md -> 정답 jsonl")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--no-history", action="store_true", help="핸드북 캐시로 리콜 칸을 채우지 않는다")
    a = ap.parse_args(argv)
    out, report = convert([(f.name, f.read_text(encoding="utf-8-sig")) for f in a.files])
    if report["conflicts"]:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        print("같은 번호에 서로 다른 내용이 있어 멈춘다. 작성자에게 확인한다.")
        return 2
    if not a.no_history:
        from evals.newmetrics.handbook_history import HandbookHistory

        h = HandbookHistory()
        report["recall_fill_problems"] = fill_recall(out["recall"], h) if h.available() else ["핸드북 캐시 없음"]
    for k, rows in out.items():
        write_jsonl(a.out_dir / GOLD_FILES[k], rows)
    (a.out_dir / "gold_convert_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
