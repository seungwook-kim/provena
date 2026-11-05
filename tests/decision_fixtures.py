"""결정표 시험 공용 자료. 2023 권한표 `Approving expense`·`Legal Contracts` 일부를 `data/parsed/authz_cells.jsonl`의 값 그대로 옮겼다."""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage

ROLES = [("Manager", "functional"), ("Director", "functional"), ("Sr Director", "functional"), ("VP", "functional"),
         ("Exec Group", "functional"), ("CEO", "functional"), ("Board", "functional"), ("Director of legal", "functional"),
         ("PAO or VP Finance", "financial"), ("CFO", "financial"), ("CLO", "financial")]

# (구간 이름, 아래 끝, 위 끝, {역할: 값})
EXPENSE_BANDS = [
    (">$0K to $25K", 0.0, 25000.0, {"Manager": "Approves", "PAO or VP Finance": "Approves/Signs"}),
    (">$25K up to $50K", 25000.0, 50000.0, {"Director": "Approves", "PAO or VP Finance": "Approves/Signs"}),
    (">$50K up to $250K", 50000.0, 250000.0, {"Sr Director": "Approves", "PAO or VP Finance": "Approves/Signs"}),
    (">$250K up to $500K", 250000.0, 500000.0, {"VP": "Approves", "PAO or VP Finance": "Approves/Signs"}),
    ("$500K to $1M", 500000.0, 1000000.0, {"Exec Group": "Approves", "CFO": "Approves/Signs"}),
    ("$1M up to $5M", 1000000.0, 5000000.0, {"CEO": "Approves", "CFO": "Signs"}),
    (">$5M", 5000000.0, None, {"CEO": "Approves", "Board": "Approves", "CFO": "Signs"}),
]


def make_cells(category: str, bands, start_line: int = 100) -> list[dict]:
    cells, line = [], start_line
    for band, lo, hi, values in bands:
        for role, kind in ROLES:
            cells.append({"category": category, "category_notes": [], "band": band, "band_lo": lo, "band_hi": hi, "role": role,
                          "approval_type": kind, "value": values.get(role, ""), "notes": [], "line": line, "comment_alias": None})
            line += 1
    return cells


EXPENSE_CELLS = make_cells("Approving expense", EXPENSE_BANDS)
LEGAL_CELLS = make_cells("Legal Contracts", [
    ("Standard Terms", None, None, {"Exec Group": "Signs", "PAO or VP Finance": "Signs", "CLO": "Signs/Approves"}),
    ("NDA - Third Party", None, None, {"Director of legal": "Signs/Approves", "PAO or VP Finance": "Signs", "CLO": "Signs/Approves"}),
], start_line=500)


def draft_json(rules: list[dict]) -> str:
    return json.dumps({"rules": [{k: r[k] for k in ("band", "approvers", "financial_approvers", "cooperating_depts")} for r in rules]},
                      ensure_ascii=False)


class FakeLLM:
    """초안 답을 정해 둔 가짜 모델. `reply`는 문자열 또는 (user_text)->문자열. 호출 기록은 `calls`."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def invoke(self, messages, *a, **k):
        self.calls.append(messages[-1].content)
        return AIMessage(content=self.reply(messages[-1].content) if callable(self.reply) else self.reply)
