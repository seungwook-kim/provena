"""링크 추출·함께 볼 정책 후보 점수(0원, 메모리 청크 표)."""
from __future__ import annotations

from evals.newmetrics import link_eval as LE
from evals.newmetrics import maintenance_eval as ME
from evals.newmetrics.common import page_rule_seq
from evals.newmetrics.corpus_links import ChunkTable

SRC, A, B, C = "src.md", "a.md", "b.md", "c.md"
SEQ = {p: page_rule_seq(p) for p in (SRC, A, B, C)}


def table() -> ChunkTable:
    rows = [
        (SEQ[SRC], "Intro", 1, 10, (SEQ[A],)),
        (SEQ[SRC], "Intro > More", 11, 20, (SEQ[A], SEQ[B])),
        (SEQ[SRC], "Rules", 21, 30, (SEQ[C],)),
        (SEQ[B], "Uses A", 5, 9, (SEQ[A],)),
        (SEQ[C], "Also A", 3, 4, (SEQ[A],)),
    ]
    return ChunkTable(rows, "memory", seq2rel={v: k for k, v in SEQ.items()})


def test_link_section_precision_recall():
    gold = [
        {"id": "L001", "source_page": SRC, "line": 2, "target": A},
        {"id": "L002", "source_page": SRC, "line": 12, "target": A},
        {"id": "L003", "source_page": SRC, "line": 13, "target": "코퍼스 밖"},
        {"id": "L004", "source_page": SRC, "line": 25, "target": A},          # 시스템은 Rules -> C (틀림), Rules -> A (놓침)
        {"id": "L005", "source_page": SRC, "line": 15, "target": B, "ambiguous": True},
    ]
    m = LE.score(gold, table(), [SRC])
    s = m["section"]
    # 시스템 간선: Intro->A, More->A, More->B(애매라 뺌), Rules->C = 3. 정답 간선: Intro->A, More->A, Rules->A = 3
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert m["rows_special"] == 1 and m["ambiguous_edges"] == 1
    assert m["page"]["tp"] == 1 and m["page"]["fp"] == 1


def test_maintenance_precision_uses_labeled_candidates_only():
    t = table()
    cands = ME.candidates_for(A, t)
    keys = {(c["rule_seq"], c["article"]) for c in cands}
    assert (SEQ[B], "Uses A") in keys and (SEQ[C], "Also A") in keys and all(k[0] != SEQ[A] for k in keys)
    gold = [
        {"id": "M01", "linking_page": B, "lines": [6], "needed": True},
        {"id": "M02", "linking_page": C, "lines": [3], "needed": False},
        {"id": "M03", "linking_page": SRC, "lines": [99], "needed": True},       # 후보에 없는 줄(놓침)
    ]
    r = ME.score_revision(cands, gold, t)
    # 후보: src Intro, src More, b Uses A, c Also A. 정답 있는 후보 2개(예 1)
    assert r["labeled"] == 2 and r["yes"] == 1 and r["precision"] == 0.5
    assert len(r["unlabeled"]) == 2
    assert r["gold_yes"] == 2 and r["gold_yes_found"] == 1
