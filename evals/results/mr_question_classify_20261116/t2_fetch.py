"""2026-10 병합 MR 중 물음표 댓글이 있던 118건의 사람 댓글 본문을 공개 웹 엔드포인트에서 다시 읽는다(읽기만, 0원).
집계 규칙은 evals/results/market_evidence_20261113/count_mr_questions.ps1과 같다:
  시스템 댓글 제외, 계정 이름이 bot|^project_|^group_|duo|gitlab-qa|danger|^ghost(대소문자 무시)이면 제외,
  본문에서 ``` 코드 블록과 주소(https?://\\S+)를 뺀 뒤 '\\?(\\s|$)'가 있으면 물음표 댓글.
원래 집계(2026-11-13 04:38 UTC 무렵) 뒤에 달린 댓글은 created_at으로 뺀다. 계정 이름은 저장하지 않는다.
"""
import json, os, re, sys, time, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(HERE, "src", "mr_question_rows.json")
OUT = os.path.join(HERE, "out", "mr_questions"); os.makedirs(OUT, exist_ok=True)
W = "https://gitlab.com/gitlab-com/content-sites/handbook/-/merge_requests"
UA = {"User-Agent": "Mozilla/5.0 research-readonly-count"}
CUTOFF = "2026-11-13T05:00:00Z"
EXCL = re.compile(r"bot|^project_|^group_|duo|gitlab-qa|danger|^ghost", re.I)
rows = json.load(open(ROWS, encoding="utf-8-sig"))
targets = [r for r in rows if r["q_notes"] > 0]
print(len(rows), len(targets), sum(r["q_notes"] for r in targets), file=sys.stderr)
def get(u):
    time.sleep(1.2)
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")), r.headers.get("X-Next-Page-Cursor")
notes = []
for t in targets:
    cursor = None
    while True:
        u = f"{W}/{t['iid']}/discussions.json?per_page=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        try:
            data, cursor = get(u)
        except Exception as e:
            print("ERR", t["iid"], e, file=sys.stderr); break
        for d in data:
            for n in d.get("notes", []):
                un = (n.get("author") or {}).get("username") or ""
                if n.get("system") or EXCL.search(un):
                    continue
                created = n.get("created_at") or ""
                body = re.sub(r"(?s)```.*?```", "", n.get("note") or "")
                body = re.sub(r"https?://\S+", "", body)
                isq = bool(re.search(r"\?(\s|$)", body))
                notes.append({"iid": t["iid"], "note_id": n.get("id"), "created_at": created, "policy_path": bool(t["policy_path"]),
                              "question_mark": isq, "after_cutoff": created > CUTOFF[:-1] if created else None,
                              "body": (n.get("note") or "")})
        if not cursor:
            break
json.dump(notes, open(os.path.join(OUT, "notes_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
q = [n for n in notes if n["question_mark"]]
qb = [n for n in q if not n["after_cutoff"]]
print("human notes in 118 MRs", len(notes), "q", len(q), "q_before_cutoff", len(qb), "policy q", sum(n["policy_path"] for n in qb), file=sys.stderr)
