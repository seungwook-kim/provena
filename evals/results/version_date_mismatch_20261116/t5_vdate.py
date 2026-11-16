"""data/chunks/chunks.jsonl 과 data/index/chunks.jsonl 의 version_date 불일치 원인 확인(0원, 네트워크 없음).
판 날짜는 version_id(커밋 sha 앞 12자리)의 커밋 시각에서 나온다. 로컬 핸드북 캐시(~/.cache/provena/handbook, 수집기 기본 경로)에서
각 판 커밋의 %ct(초)와 %cs(커밋한 사람 시간대 날짜)를 읽어, 두 파일의 날짜가 각각 어느 방식과 맞는지 센다.
  - 고친 뒤 방식(커밋 d259169): utc_day(%ct)
  - 고치기 전 방식: %cs
"""
import json, os, subprocess, collections, sys
from datetime import datetime, timezone
REPO = r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "provena", "handbook")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "vdate"); os.makedirs(OUT, exist_ok=True)
def load(p):
    d = {}
    for l in open(p, encoding="utf-8"):
        if l.strip():
            x = json.loads(l); d[x["chunk_id"]] = x
    return d
A = load(os.path.join(REPO, "data", "chunks", "chunks.jsonl"))
B = load(os.path.join(REPO, "data", "index", "chunks.jsonl"))
common = set(A) & set(B)
mism = [c for c in common if A[c].get("version_date") != B[c].get("version_date")]
other_diff = [c for c in mism if {k: v for k, v in A[c].items() if k != "version_date"} != {k: v for k, v in B[c].items() if k != "version_date"}]
vers = collections.defaultdict(list)
for c in mism:
    vers[A[c]["version_id"]].append(c)
def git(*a):
    r = subprocess.run(["git", "-C", CACHE, *a], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()
res = []
for vid, cids in sorted(vers.items()):
    rc, out, err = git("show", "-s", "--format=%H %ct %cs %ci %as", vid)
    a_d = sorted({A[c]["version_date"] for c in cids}); b_d = sorted({B[c]["version_date"] for c in cids})
    row = {"version_id": vid, "lines": len(cids), "chunks_date": a_d, "index_date": b_d, "rule_seq": sorted({A[c].get("rule_seq") for c in cids})}
    if rc == 0 and out:
        sha, ct, cs, ci_d, ci_t, ci_tz, as_ = out.split()[:7]
        utc = datetime.fromtimestamp(int(ct), timezone.utc).date().isoformat()
        row.update({"commit": sha[:12], "utc_day": utc, "cs": cs, "ci": f"{ci_d} {ci_t} {ci_tz}",
                    "chunks_is_utc": a_d == [utc], "index_is_cs": b_d == [cs], "chunks_is_cs": a_d == [cs], "index_is_utc": b_d == [utc]})
    else:
        row["git_error"] = (err or "not found")[:120]
    res.append(row)
summ = {"chunks_lines": len(A), "index_lines": len(B), "common": len(common), "mismatch_lines": len(mism), "mismatch_versions": len(vers),
        "mismatch_lines_other_fields_differ": len(other_diff),
        "chunks_later_lines": sum(1 for c in mism if A[c]["version_date"] > B[c]["version_date"]),
        "chunks_earlier_lines": sum(1 for c in mism if A[c]["version_date"] < B[c]["version_date"]),
        "versions_found_in_cache": sum(1 for r in res if "utc_day" in r),
        "versions_chunks_utc_and_index_cs": sum(1 for r in res if r.get("chunks_is_utc") and r.get("index_is_cs")),
        "versions_chunks_cs_and_index_utc": sum(1 for r in res if r.get("chunks_is_cs") and r.get("index_is_utc")),
        "lines_chunks_utc_and_index_cs": sum(r["lines"] for r in res if r.get("chunks_is_utc") and r.get("index_is_cs")),
        "lines_chunks_cs_and_index_utc": sum(r["lines"] for r in res if r.get("chunks_is_cs") and r.get("index_is_utc")),
        "versions_neither": [r["version_id"] for r in res if "utc_day" in r and not ((r.get("chunks_is_utc") and r.get("index_is_cs")) or (r.get("chunks_is_cs") and r.get("index_is_utc")))],
        "cache_head": git("rev-parse", "HEAD")[1][:12], "cache_shallow": os.path.exists(os.path.join(CACHE, ".git", "shallow"))}
# 대조: 날짜가 같은 판에서도 두 방식이 다른 판이 있는지(있으면 그 판은 어느 파일에서든 같은 방식이라는 뜻)
same_vers = collections.defaultdict(set)
for c in common:
    if A[c].get("version_date") == B[c].get("version_date"):
        same_vers[A[c]["version_id"]].add(A[c]["version_date"])
diffmethod_same = 0; checked = 0
for vid in list(same_vers)[:4000]:
    if vid in vers: continue
    rc, out, err = git("show", "-s", "--format=%ct %cs", vid)
    if rc or not out: continue
    ct, cs = out.split()
    utc = datetime.fromtimestamp(int(ct), timezone.utc).date().isoformat()
    checked += 1
    if utc != cs:
        diffmethod_same += 1
summ["control_versions_checked"] = checked
summ["control_versions_where_cs_ne_utc_but_files_agree"] = diffmethod_same
json.dump({"summary": summ, "versions": res}, open(os.path.join(OUT, "vdate_check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(summ, ensure_ascii=False, indent=1))
