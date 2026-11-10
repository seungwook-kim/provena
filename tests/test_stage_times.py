"""evals/latency/stage_times.py: 그래프가 끝난 뒤 시작한 LLM 호출이 생성 시간을 음수로 만들지 않는지 가짜 관측 목록으로 확인한다. 네트워크·키 없음."""
import importlib.util
import json
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "evals" / "latency" / "stage_times.py"
_spec = importlib.util.spec_from_file_location("stage_times", _PATH)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


def _session(sid, minute):
    t = lambda s: f"2026-11-10T00:{minute:02d}:{s:02d}Z"
    return [
        {"id": f"{sid}g", "parentObservationId": None, "sessionId": f"u:{sid}", "type": "SPAN", "name": "graph",
         "startTime": t(0), "endTime": t(10), "latency": 10},
        {"id": f"{sid}c1", "parentObservationId": f"{sid}g", "sessionId": f"u:{sid}", "type": "GENERATION",
         "name": "TaskEffortAnthropic", "startTime": t(1), "endTime": t(4), "latency": 3},
        {"id": f"{sid}s", "parentObservationId": f"{sid}g", "sessionId": f"u:{sid}", "type": "SPAN",
         "name": "search", "startTime": t(4), "endTime": t(5), "latency": 1},
        # 그래프가 끝난(10초) 뒤 시작한 호출 → 세지 않는다(고치기 전에는 생성 합이 -27초가 됐다)
        {"id": f"{sid}c2", "parentObservationId": f"{sid}g", "sessionId": f"u:{sid}", "type": "GENERATION",
         "name": "TaskEffortAnthropic", "startTime": t(20), "endTime": t(50), "latency": 30},
    ]


def test_generation_after_graph_end_is_not_negative(tmp_path, monkeypatch):
    obs = _session("t1", 0) + _session("t2", 5)  # 요약이 첫 요청을 뺀 평균도 내므로 세션 둘
    (tmp_path / "obs.json").write_text(json.dumps(obs), encoding="utf-8")
    rows = [{"run": 1, "id": 7, "at": "2026-11-10T00:00:10Z", "total_s": 10},
            {"run": 1, "id": 8, "at": "2026-11-10T00:05:10Z", "total_s": 10}]
    (tmp_path / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["stage_times.py", "--obs", str(tmp_path / "obs.json"),
                                      "--rows", f"anthropic=rev=TaskEffortAnthropic={tmp_path / 'rows.jsonl'}",
                                      "--out", str(out)])
    assert st.main() == 0
    for row in json.loads(out.read_text(encoding="utf-8")):
        assert abs(row["generation_s"] - 3.0) < 1e-6
        assert abs(row["outside_llm_s"] - 7.0) < 1e-6
