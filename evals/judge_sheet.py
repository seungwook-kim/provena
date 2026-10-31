"""골든셋 초안(md 표) -> 판정 시트(CSV). 두 판정자가 따로 채운 뒤 `--to-jsonl`로 평가셋 파일을 만든다.

    python evals/judge_sheet.py --only v1 --out evals/judge_sheet_v1.csv      # v1 30건만(11/3 동결용)
    python evals/judge_sheet.py <초안.md> --out evals/judge_sheet.csv
    python evals/judge_sheet.py --to-jsonl evals/judge_sheet.csv --version v2 --out evals/dataset_v2.jsonl

- 1~30번은 `dataset_v1.jsonl`을 그대로 옮긴다(질문·기대 답·근거·정답 위치). 31~50번은 초안의 v2 문항(관련 31~40, 비관련 41~50).
  51번은 v1 30번에서 옮긴 관련 문항(코퍼스에 답이 있어 v1에서는 새 비관련 질문으로 바꿈).
- `draft_gold`: 초안의 근거를 `경로.md > 제목` 형식으로 옮긴 제안(evals/retrieval/gold.py 형식). 페이지가 여럿이라 섹션을 나눌 수 없는 문항은
  `확인 필요:`로 시작한다. 판정자는 이 칸을 보고 `judgeN_gold`에 맞는 위치를 적는다(같으면 그대로 복사).
- 판정 칸: `judgeN_ok`(Y = 질문·기대 동작이 맞다 / N = 틀리다), `judgeN_gold`(관련만, `;`로 여러 위치), `judgeN_note`.
- `final_gold`: 두 판정자 위치가 같으면 비워 둬도 된다(`--to-jsonl`이 그 값을 쓴다). 다르면 합의한 위치를 적는다.
  `--to-jsonl`은 두 판정자 중 하나라도 N이거나, 관련 문항의 위치가 갈렸는데 `final_gold`가 비면 멈춘다(합의 전 동결 방지).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

EVALS = Path(__file__).resolve().parent
TYPES = {"a": "out_of_domain", "b": "unknown_entity", "c": "missing_attribute", "d": "wrong_period"}
COLUMNS = ["id", "version", "kind", "irrelevant_type", "input", "draft_expected", "draft_gold", "draft_why", "as_of",
           "judge1_name", "judge1_ok", "judge1_gold", "judge1_note", "judge2_name", "judge2_ok", "judge2_gold", "judge2_note", "final_gold"]
CORPUS_DATE = "2026-10-27"  # 고정 커밋 129243bc 날짜(dataset_v1.jsonl의 as_of)
AUTHZ_HINT = "authorization-matrix"
# 초안 표기가 실제 청크 제목과 달라 `missing_in_corpus`에 걸린 것을 고친 제안(판정자가 확정한다)
GOLD_FIX = {
    34: "engineering/releases/patch-releases/index.md > Patch release types",  # 초안 "(Out-of-band)"는 설명이고 제목이 아님
    40: "authorization-matrix#L559",  # 2023 권한표 표 밖 글은 제목이 'Policy Scope' 하나라 원본 줄로 좁힘(60일 합산 문장)
}
MOVED_FROM_V1 = {
    "id": 51, "version": "v2", "kind": "relevant", "irrelevant_type": "", "input": "FY28 Q1은 몇 월 며칠부터 며칠까지야?", "as_of": CORPUS_DATE,
    "draft_expected": "2027년 2월 1일부터 4월 30일까지 (회계분기는 2/1·5/1·8/1·11/1에 시작하고, 2027년 2월 1일이 Q1 FY28의 시작. "
                      "4월 30일은 다음 분기 시작 5/1의 전날로 계산한 값)",
    "draft_gold": "engineering/data-engineering/quarterly-planning.md > The cycle > Quarter calendar ; security/product-security/mentorship.md > Pilot timeline",
    "draft_why": "quarterly-planning 81행 'GitLab's fiscal quarters start on Feb 1, May 1, Aug 1 and Nov 1', mentorship 193행 "
                 "'Week of 1 February 2027 (Q1 FY28)'. 끝나는 날은 다음 분기 시작의 전날로 계산. v1 30번(비관련)이었으나 코퍼스에 답이 있어 옮김(박진형 점검, PR #23).",
}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split(" | ")]


def _heading(text: str) -> str:
    """초안 제목 표기 -> `A > B`. `(쪽 표시) 제목`의 앞 괄호는 떼고, `A (> B)`는 하위 제목으로 푼다."""
    t = re.sub(r"^\([^)]*\)\s*", "", text.strip())
    if re.search(r"\(\s*(?:>|예시:)\s*", t):  # 이 표기를 연 경우에만 닫는 괄호를 뗀다("Notes (6)"는 그대로)
        t = re.sub(r"\(\s*(?:>|예시:)\s*", "> ", t)
        t = re.sub(r"\)\s*$", "", t)
    return " > ".join(p.strip() for p in t.split(">") if p.strip())


def _tag(text: str) -> str | None:
    m = re.match(r"^\(([^)]*)\)", text.strip())
    return m.group(1).strip().lower() if m else None


def _page_for_tag(tag: str, plist: list[str]) -> str | None:
    """`(on-call)`, `(RCA)` 같은 쪽 표시 -> 그 페이지. 경로 낱말이나 마지막 경로 낱말 머리글자로 찾는다."""
    for p in plist:
        parts = [x for x in re.split(r"[/_.]", p.lower()) if x and x not in ("md", "index")]
        if tag in parts or any("".join(w[0] for w in x.split("-")) == tag for x in parts):
            return p
    return None


def draft_gold(pages: str, headings: str) -> str:
    """초안 근거 -> `경로.md > 제목` 목록. 페이지가 여럿이면 쪽 표시로 나누고(표시 없는 제목은 첫 페이지), 수가 같으면 차례로 짝짓는다."""
    plist = [p.strip() for p in pages.split(" ; ") if p.strip()]
    raw = [h for h in headings.split(" ; ") if h.strip()]
    if len(plist) == 1:
        page = AUTHZ_HINT if "authorization-matrix" in plist[0] else plist[0]
        return " ; ".join(f"{page} > {_heading(h)}" for h in raw) or page
    tags = [_tag(h) for h in raw]
    if any(tags):
        pairs = [(_page_for_tag(t, plist) if t else plist[0], _heading(h)) for t, h in zip(tags, raw)]
        if all(p for p, _ in pairs):
            return " ; ".join(f"{p} > {h}" for p, h in pairs)
    elif len(raw) == len(plist):
        return " ; ".join(f"{p} > {_heading(h)}" for p, h in zip(plist, raw))
    return f"확인 필요: 페이지 [{pages}] 제목 [{headings}]"


def build(md_path: Path | None, only: str = "all") -> list[dict]:
    v1 = [json.loads(x) for x in (EVALS / "dataset_v1.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rel_draft, irr_draft = {}, {}
    for line in ("" if only == "v1" else md_path.read_text(encoding="utf-8")).splitlines():
        if re.match(r"^\| v[12]-R\d+ \|", line):
            c = _cells(line)  # id | 영역 | 질문 | 기대 동작 | 정답 요지 | 근거 페이지 | 제목 경로 | 결정적 문장 | 난이도
            rel_draft[c[0]] = c
        elif re.match(r"^\| v[12]-N\d+ \|", line):
            c = _cells(line)  # id | 유형 | 질문 | 기대 동작 | 거절 이유 | 확인 방법 | 어려운 오답 여부
            irr_draft[c[0]] = c
    rows = []
    for item in v1:
        r = _row(int(item["id"]), "v1", item["kind"], item["input"], None, item.get("irrelevant_type"), item.get("as_of") or CORPUS_DATE)
        r.update({"draft_expected": item.get("expected", ""), "draft_gold": " ; ".join(item.get("gold_chunks") or []), "draft_why": item.get("why", "")})
        rows.append(r)
    if only == "v1":
        return rows
    for n in range(16, 26):
        c = rel_draft[f"v2-R{n}"]
        rows.append(_row(30 + n - 15, "v2", "relevant", c[2], c, None, "2023-05" if "2023-05" in c[5] else CORPUS_DATE))
    for n in range(16, 26):
        c = irr_draft[f"v2-N{n}"]
        rows.append(_row(40 + n - 15, "v2", "irrelevant", c[2], c, TYPES[c[1][0]], CORPUS_DATE))
    rows.append(MOVED_FROM_V1 | {k: "" for k in COLUMNS if k not in MOVED_FROM_V1})
    for r in rows:
        if r["id"] in GOLD_FIX:
            r["draft_gold"] = GOLD_FIX[r["id"]]
    return rows


def _row(n, version, kind, question, c, itype, as_of) -> dict:
    r = dict.fromkeys(COLUMNS, "")
    r.update({"id": n, "version": version, "kind": kind, "irrelevant_type": itype or "", "input": question, "as_of": as_of})
    if c and kind == "relevant":
        r.update({"draft_expected": c[4], "draft_gold": draft_gold(c[5], c[6]), "draft_why": f"결정적 문장: {c[7]}. 난이도: {c[8]}."})
    elif c:
        r.update({"draft_expected": "거절", "draft_why": f"거절 이유: {c[4]}. 확인 방법: {c[5]}."})
    return r


def to_jsonl(sheet: Path, version: str) -> list[dict]:
    out = []
    for r in csv.DictReader(sheet.open(encoding="utf-8-sig")):
        if version == "v1" and r["version"] != "v1":
            continue
        if r["judge1_ok"].strip().upper() != "Y" or r["judge2_ok"].strip().upper() != "Y":
            raise SystemExit(f"{r['id']}번: 두 판정자 모두 Y가 아니다(판정 전이거나 반려)")
        gold: list[str] = []
        if r["kind"] == "relevant":
            g1, g2 = (sorted(x.strip() for x in r[k].split(";") if x.strip()) for k in ("judge1_gold", "judge2_gold"))
            final = [x.strip() for x in r["final_gold"].split(";") if x.strip()]
            if not final and g1 != g2:
                raise SystemExit(f"{r['id']}번: 판정자 위치가 다르고 final_gold가 비었다")
            gold = final or g1
        out.append({"id": int(r["id"]), "input": r["input"], "kind": r["kind"], **({"irrelevant_type": r["irrelevant_type"]} if r["kind"] == "irrelevant" else {}),
                    "expected": r["draft_expected"], "gold_chunks": gold, "why": r["draft_why"], "as_of": r["as_of"], "corpus_version": "129243bc",
                    "judges": [r["judge1_name"], r["judge2_name"]]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python evals/judge_sheet.py")
    ap.add_argument("draft", nargs="?", type=Path)
    ap.add_argument("--to-jsonl", type=Path, default=None)
    ap.add_argument("--version", choices=["v1", "v2"], default="v2")
    ap.add_argument("--only", choices=["v1", "all"], default="all", help="v1: 1~30번만(초안 불필요)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.to_jsonl:
        rows = to_jsonl(a.to_jsonl, a.version)
        a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"{a.out}: {len(rows)}건")
        return 0
    if a.only == "all" and a.draft is None:
        ap.error("초안 md가 필요하다(--only v1이면 없어도 됨)")
    rows = build(a.draft, a.only)
    with a.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    need = [r["id"] for r in rows if r["draft_gold"].startswith("확인 필요")]
    print(f"{a.out}: {len(rows)}건 (관련 {sum(r['kind'] == 'relevant' for r in rows)}, 비관련 {sum(r['kind'] == 'irrelevant' for r in rows)}), 위치 확인 필요 {need}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
