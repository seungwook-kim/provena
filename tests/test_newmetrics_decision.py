"""결정표 셀 정확도(0원): 정답은 권한표 원문 줄에서 기계로 만든 시험용 행(실제 정답 아님), 초안은 파서 규칙 또는 가짜 LLM."""
from __future__ import annotations

import json

import pytest

from evals.newmetrics import decision_prod as DP
from evals.newmetrics.common import AUTHZ_MD

pytestmark = pytest.mark.skipif(not AUTHZ_MD.exists(), reason="코퍼스 권한표 없음(data/corpus는 저장소에 없음)")
from evals.newmetrics.fakes import FakeDraftLLM, decision_row
from evals.newmetrics.spec_tables import DECISION_CATEGORIES


def gold_for(category: str) -> list[dict]:
    cells = DP.source_cells()[category]
    firsts = sorted({min(int(x["line"]) for x in cells if x["band"] == b) for b in {c["band"] for c in cells}})
    return [decision_row(f"D{i:02d}", f - 1) for i, f in enumerate(firsts, start=1)]


def test_parser_drafts_score_full_marks():
    gold = gold_for("Legal Contracts")
    cells = DP.source_cells()
    from backend.graph.decision.rules import rules_from_cells

    res = DP.score_cells(gold, {"Legal Contracts": rules_from_cells(cells["Legal Contracts"])}, cells)
    assert res["cells"] == len(gold) * 11 and res["cell_accuracy"] == 1.0 and res["extra_bands"] == 0


def test_flipped_cells_lower_accuracy_exactly():
    cat = "Approving expense"
    gold = gold_for(cat)
    cells = DP.source_cells()
    band = cells[cat][0]["band"]
    llm = FakeDraftLLM(flip={(band, "Manager"), (band, "CFO")})
    draft, err = DP.draft_local(cat, cells[cat], llm)
    assert err is None and llm.calls == 1
    res = DP.score_cells(gold, {cat: draft}, cells)
    assert res["cells"] - res["correct"] == 2


def test_failed_draft_counts_all_cells_wrong():
    cat = "Approving Payment"
    cells = DP.source_cells()
    draft, err = DP.draft_local(cat, cells[cat], FakeDraftLLM(broken=True))
    assert draft is None and err
    res = DP.score_cells(gold_for(cat), {cat: None}, cells)
    assert res["correct"] == 0 and res["cell_accuracy"] == 0.0


def test_categories_not_drafted_are_not_counted():
    cells = DP.source_cells()
    gold = gold_for("Legal Contracts") + [dict(r, id=f"D{30 + i}") for i, r in enumerate(gold_for("Benefit changes"))]
    from backend.graph.decision.rules import rules_from_cells

    res = DP.score_cells(gold, {"Legal Contracts": rules_from_cells(cells["Legal Contracts"])}, cells)
    assert set(res["per_category"]) == {"Legal Contracts"}


def test_gold_line_maps_to_parser_category_names():
    for name, lo, hi, _a in DECISION_CATEGORIES:
        assert DP.parser_category(name) in DP.source_cells(), name


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class FakeClient:
    """운영 API 가짜. new=True면 초안만 모드를 아는 새 판(200, draft-only), False면 인자를 무시하는 옛 판(201, 승인 건)."""

    def __init__(self, new: bool = True):
        from backend.graph.decision.rules import rules_from_cells

        self.new, self.calls, self.closed = new, [], False
        self.cells = DP.source_cells()
        self.rules = {c: rules_from_cells(v) for c, v in self.cells.items()}

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json))
        if url.startswith("/approvals/"):
            return FakeResp(200, {"approval_id": url.rsplit("/", 1)[1], "status": "rejected"})
        if "draft_only=maybe" in url:
            return FakeResp(422 if self.new else 400, {})
        if not self.new:
            return FakeResp(201, {"approval_id": "ap-real-1", "table_id": "dt-1", "draft": self.rules[json["category"]]})
        return FakeResp(200, {"approval_id": DP.DRAFT_ONLY_ID, "status": "draft_only", "draft": self.rules[json["category"]],
                              "comparison": {"mismatch_count": 0}})

    def close(self):
        self.closed = True


def _run_main(monkeypatch, tmp_path, client, pending=()):
    import evals.newmetrics.prod as P

    class Conn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [(c,) for c in pending]

        def close(self):
            pass

    gold = tmp_path / "gold.jsonl"
    rows = []
    for cat in ("Legal Contracts", "Benefit changes"):
        rows += [dict(r, id=f"D{len(rows) + i + 1:02d}") for i, r in enumerate(gold_for(cat))]
    gold.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(DP, "connect_ro", lambda *a: Conn())
    monkeypatch.setattr(P, "client", lambda *a, **k: client)
    monkeypatch.setattr(P, "login", lambda *a, **k: "admin-a")
    code = DP.main(["--gold", str(gold), "--out", str(tmp_path / "out"), "--base", "http://x", "--runs", "2", "--call-prod",
                    "--ledger", str(tmp_path / "ledger.json")])
    return code, json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))


def test_prod_draft_only_measures_approved_categories_without_writes(monkeypatch, tmp_path):
    c = FakeClient(new=True)
    code, s = _run_main(monkeypatch, tmp_path, c)
    assert code == 0 and s["blocked"] == {} and set(s["categories"]) == {"Legal Contracts", "Benefit changes"}
    assert [r["cell_accuracy"] for r in s["metrics"]["runs"]] == [1.0, 1.0]
    assert not any(u.startswith("/approvals/") for u, _ in c.calls)                  # 반려(정리) 단계가 없다
    assert sum(1 for u, _ in c.calls if "draft_only=true" in u) == 4                   # 2회 x 2 업무 종류


def test_prod_old_revision_is_detected_before_any_convert(monkeypatch, tmp_path):
    c = FakeClient(new=False)
    code, s = _run_main(monkeypatch, tmp_path, c)
    assert code == DP.EXIT_PREFLIGHT and s["stopped"] == "draft_only_unsupported"
    assert [u for u, _ in c.calls] == ["/decision-tables/convert?draft_only=maybe"]   # 쓰기 없는 검사 한 번뿐


def test_prod_pending_draft_category_is_blocked(monkeypatch, tmp_path):
    code, s = _run_main(monkeypatch, tmp_path, FakeClient(new=True), pending=("Benefit changes",))
    assert code == 0 and list(s["blocked"]) == ["Benefit changes"] and s["categories"] == ["Legal Contracts"]


def test_unexpected_approval_is_rejected_at_once():
    class Half(FakeClient):
        def post(self, url, json=None, headers=None):
            if "draft_only=true" in url:
                self.calls.append((url, json))
                return FakeResp(201, {"approval_id": "ap-real-9"})
            return super().post(url, json, headers)

    c = Half()
    r = DP.convert_draft_only(c, "Legal Contracts")
    assert r["body"]["approval_id"] == "ap-real-9"
    assert DP.reject_prod(c, "ap-real-9") == {"status": 200, "result_status": "rejected"}
    assert c.calls[-1] == ("/approvals/ap-real-9", {"approval_id": "ap-real-9", "approve": False, "comment": DP.REJECT_COMMENT})


def test_cost_estimate_all_eight_categories_under_run_cap():
    cells = DP.source_cells()
    est = DP.estimate_cost(list(cells), cells)
    assert est["calls"] == 8 and est["usd_est"] < 0.01
    json.dumps(est)