"""키 없는 데모의 리콜 시나리오 시험 (2026-11-16, L-23 해소). 0원: LLM·Voyage·DB 없음.

- 가상 개정 한 건(`data/demo_replay/scenarios.json`의 recall, `backend/graph/recall/demo_change.py`): 섹션 읽기 감싸기와 처리 대기 줄 넣기.
- ReplayJudge: 녹화에 있는 판정 요청은 녹화한 LLM 판정, 없으면 규칙 판정.
- 재생 키: 답 끝 표시의 오늘 날짜(`기준일 YYYY-MM-DD · 근거 판 날짜`)는 키에서 지운다(저장한 답을 입력으로 받는 판정 요청이 날마다 바뀌지 않게).
"""
from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from recall_test_support import AMOUNT_NEW, AMOUNT_OLD, changed

from backend.graph.recall import demo_change as DC
from backend.graph.recall.judge import ReplayJudge, RuleJudge
from backend.graph.recall.notice import judge_messages, system_prompt
from backend.rag.ingest.schedule import event_id
from backend.services import demo_replay as dr


def test_scenarios_file_holds_a_labelled_demo_revision_of_one_row():
    rec = DC.load_demo_change()
    assert rec is not None and rec["change_type"] == "modified" and rec["new_version_date"] > rec["old_version_date"]
    assert rec["new_text"].startswith("(데모용 가상 개정본")          # 실제 핸드북 문구가 아니라고 글에 적혀 있다
    scen = json.loads(DC.SCENARIOS_FILE.read_text(encoding="utf-8"))
    assert scen["review"]["question"].strip() and len(scen["recall"]["recalled_questions"]) == 2


def test_missing_or_incomplete_scenario_is_none(tmp_path):
    assert DC.load_demo_change(tmp_path / "none.json") is None
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"recall": {"rule_seq": 1, "article": "A"}}), encoding="utf-8")
    assert DC.load_demo_change(p) is None


def _rec():
    return {"rule_seq": 7, "article": "A > B", "old_version_date": "2023-05-11", "new_version_date": "2027-07-01", "change_type": "modified",
            "new_text": "(데모용 가상 개정본) 새 글"}


def test_reader_returns_the_revision_only_for_the_new_version_read():
    seen = []

    def base(rule_seq, article, as_of):
        seen.append(as_of)
        return {"text": f"원문 {as_of}", "source_url": "u", "version_id": "v1", "version_date": "2023-05-11"}

    read = DC.with_demo_revision(base, _rec())
    new = read(7, "A > B", "2027-07-01")
    assert new["text"] == "(데모용 가상 개정본) 새 글" and new["version_date"] == "2027-07-01" and new["version_id"] == DC.DEMO_VERSION_ID
    assert new["source_url"] == "u" and seen == ["2023-05-11"]           # 칸은 개정 전 섹션에서 가져온다
    assert read(7, "A > B", "2023-05-11")["text"] == "원문 2023-05-11"   # 개정 전 읽기와 다른 섹션은 그대로
    assert read(7, "A > C", "2027-07-01")["text"] == "원문 2027-07-01"
    assert DC.with_demo_revision(None, _rec()) is None and DC.with_demo_revision(base, None) is base


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.log.append((sql, params))

        class R:
            def fetchone(self_inner):
                return (True,) if "to_regclass" in sql else (42,)

        return R()


def test_seed_inserts_one_pending_row_and_resets_only_when_asked():
    log: list = []
    eid = DC.seed_pending_change("unused", _rec(), reset=False, connect=lambda: _Conn(log))
    assert eid == event_id(DC.changed_of(_rec()))
    insert = [x for x in log if "INSERT INTO changed_articles" in x[0]]
    assert len(insert) == 1 and "DO NOTHING" in insert[0][0] and insert[0][1][:2] == (eid, 42)
    assert any("sync_runs" in x[0] and DC.DEMO_JOB in x[1] for x in log)
    log.clear()
    DC.seed_pending_change("unused", _rec(), reset=True, connect=lambda: _Conn(log))
    assert "DO UPDATE SET status = 'pending'" in [x for x in log if "INSERT INTO changed_articles" in x[0]][0][0]


def _row(date: str) -> dict:
    return {"answer_id": "a1", "user_id": "u1", "question": "5천만원짜리 도입은 누가 승인하나요?",
            "answer": f"디렉터가 승인합니다 [1].\n\n기준일 {date} · 근거 판 날짜 2024-01-01 · 출처: 테스트"}


def test_replay_judge_uses_the_recorded_verdict_and_falls_back_to_rules(tmp_path):
    system = system_prompt(False)
    msgs = judge_messages(_row("2026-11-16"), changed(), AMOUNT_OLD, AMOUNT_NEW, system=system)
    verdict = {"conclusion_changed": True, "confidence": 0.9, "explanation": "승인 금액 구간이 1억원 이상으로 바뀌었습니다."}
    (tmp_path / "recorded.jsonl").write_text(json.dumps({"key": dr.request_key(msgs), "role": "recall_explain", "model": "m", "user_preview": "",
                                                         "response": json.dumps(verdict, ensure_ascii=False), "recorded_at": "x"}, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    store = dr.ReplayStore(tmp_path)
    judge = ReplayJudge(dr.ReplayChatModel(store=store), use_skills=False, store=store)
    # 다른 날 물은 답(끝 표시의 기준일만 다름)도 같은 녹화를 찾는다
    got = judge.judge(_row("2026-12-01"), changed(), AMOUNT_OLD, AMOUNT_NEW)
    assert got["explanation"] == verdict["explanation"] and got["judge_failed"] is False and got["conclusion_changed"] is True
    other = {**_row("2026-11-16"), "question": "다른 질문"}
    assert judge.judge(other, changed(), AMOUNT_OLD, AMOUNT_NEW) == RuleJudge().judge(other, changed(), AMOUNT_OLD, AMOUNT_NEW)


def test_request_key_ignores_the_answer_footer_date_only():
    k = lambda t: dr.request_key([HumanMessage(content=t)])  # noqa: E731
    assert k("답\n\n기준일 2026-11-16 · 근거 판 날짜 2023-05-11 · 출처") == k("답\n\n기준일 2027-01-02 · 근거 판 날짜 2023-05-11 · 출처")
    assert k("답\n\n기준일 2026-11-16 · 근거 판 날짜 2023-05-11") != k("답\n\n기준일 2026-11-16 · 근거 판 날짜 2023-05-12")
    assert k("기준일 2026-11-16에 바뀐 규정") != k("기준일 2026-11-17에 바뀐 규정")     # 끝 표시가 아닌 날짜는 그대로 키에 든다
