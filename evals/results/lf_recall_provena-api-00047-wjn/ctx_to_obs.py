"""저장된 첫 검색 문맥(failure_types_<rev>/context.detail.json, 운영 Langfuse의 첫 search 관측에서 읽어 둔 것)을 lf_recall의 --observations-json 형식으로 바꾼다."""
import json, sys
from pathlib import Path
REPO, rev, setname, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
rows = [d for d in json.load(open(REPO / "evals/results" / f"failure_types_provena-api-{rev}" / "context.detail.json", encoding="utf-8"))["rows"] if d["set"] == setname]
need = {c for d in rows for c in d.get("chunk_ids") or []}
meta = {}
with open(REPO / "data/index/chunks.jsonl", encoding="utf-8") as f:
    for line in f:
        c = json.loads(line)
        if c["chunk_id"] in need:
            meta[c["chunk_id"]] = {k: c.get(k) for k in ("chunk_id", "rule_seq", "article", "line_start", "line_end")}
obs = []
for i, d in enumerate(rows):
    if d.get("status") != "paired": continue
    obs.append({"id": f"o{i}", "name": "search", "traceId": f"t{i}", "startTime": "2026-11-12T00:00:00.000Z", "sessionId": f"u:{d['thread_id']}", "input": {"retries": 0},
                "output": {"chunks": [meta.get(c, {"chunk_id": c}) for c in d["chunk_ids"]]}})
out.write_text(json.dumps(obs, ensure_ascii=False), encoding="utf-8")
print(len(obs), "obs", sum(1 for d in rows for c in d.get("chunk_ids") or [] if c not in meta), "코퍼스에 없는 청크")
