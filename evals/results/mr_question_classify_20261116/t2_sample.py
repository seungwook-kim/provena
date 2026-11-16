"""분류 대상 고르기: 정책 경로 MR의 물음표 댓글 전부(24) + 정책 경로가 아닌 물음표 댓글 286개 중 무작위 30개(시드 고정)."""
import json, os, random, re
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "mr_questions")
SEED = 20261116
notes = json.load(open(os.path.join(OUT, "notes_raw.json"), encoding="utf-8"))
q = [n for n in notes if n["question_mark"] and not n["after_cutoff"]]
q.sort(key=lambda n: (n["iid"], n["note_id"]))
pol = [n for n in q if n["policy_path"]]
rest = [n for n in q if not n["policy_path"]]
samp = random.Random(SEED).sample(rest, 30)
samp.sort(key=lambda n: (n["iid"], n["note_id"]))
def clean(b):
    b = re.sub(r"(?s)```.*?```", "[코드]", b)
    b = re.sub(r"https?://\S+", "[주소]", b)
    b = re.sub(r"(?<![\w.])@[A-Za-z0-9_.\-]+", "@[멘션]", b)
    return re.sub(r"\s+", " ", b).strip()
sel = [dict(n, group="policy_all") for n in pol] + [dict(n, group="nonpolicy_sample") for n in samp]
for i, n in enumerate(sel, 1):
    n["no"] = i; n["text"] = clean(n["body"])
json.dump({"seed": SEED, "n_question_notes": len(q), "n_policy": len(pol), "n_rest": len(rest),
           "items": [{k: n[k] for k in ("no", "group", "iid", "note_id", "created_at", "text")} for n in sel]},
          open(os.path.join(OUT, "selected.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for n in sel:
    print(f"#{n['no']} [{n['group']}] !{n['iid']} :: {n['text'][:700]}")
