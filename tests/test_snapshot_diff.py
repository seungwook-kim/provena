"""git 없는 변경 감지 시험 (F-07): 두 시점 문서 묶음 -> 바뀐 섹션 -> 리콜. 합성 원문만 쓴다."""
from __future__ import annotations

import json

from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.recall.judge import RuleJudge
from backend.graph.recall.service import RecallService
from backend.graph.recall.store import InMemoryRecallStore
from backend.rag.ingest.handbook import rule_seq
from backend.rag.ingest.schedule import event_id
from backend.rag.ingest.snapshot_diff import diff_snapshots, feed, main, read_snapshot
from backend.schemas import Chunk

PATH = "content/handbook/security/x.md"
OTHER = "content/handbook/security/y.md"
OLD = """---
title: Disclosure
---

## Policy

We disclose issues 30 days after the fix.

## Contacts

Ask in #security.
"""
NEW = OLD.replace("30 days", "90 days")


def diff(old, new):
    return diff_snapshots(old, new, old_date="2026-01-01", new_date="2026-02-01")


def test_modified_section_with_texts():
    res = diff({PATH: OLD}, {PATH: NEW})
    [a] = res.articles
    assert (a.rule_seq, a.article, a.change_type, a.old_version_date, a.new_version_date) == (rule_seq(PATH), "Policy", "modified",
                                                                                            "2026-01-01", "2026-02-01")
    old_text, new_text = res.texts[(a.rule_seq, "Policy")]
    assert "30 days" in old_text and "90 days" in new_text


def test_same_and_format_only_are_skipped():
    assert diff({PATH: OLD}, {PATH: OLD}).articles == []
    res = diff({PATH: OLD}, {PATH: OLD.replace("after the fix.", "after the   fix.  ")})
    assert res.articles == [] and res.format_only == 1


def test_new_page_is_added_and_missing_page_is_removed():
    res = diff({OTHER: OLD}, {PATH: OLD})
    kinds = {(a.rule_seq, a.change_type) for a in res.articles}
    assert (rule_seq(PATH), "added") in kinds and (rule_seq(OTHER), "removed") in kinds
    added = next(a for a in res.articles if a.change_type == "added")
    assert added.old_version_date == ""


def test_removed_section_inside_page():
    res = diff({PATH: OLD}, {PATH: OLD.split("## Contacts")[0]})
    assert [(a.article, a.change_type) for a in res.articles] == [("Contacts", "removed")]
    assert res.texts[(rule_seq(PATH), "Contacts")][1] == ""


def test_read_snapshot_dir_and_jsonl(tmp_path):
    d = tmp_path / "snap"
    (d / "security").mkdir(parents=True)
    (d / "security" / "x.md").write_text(OLD, encoding="utf-8")
    (d / ".git").mkdir()
    (d / ".git" / "skip.md").write_text("x", encoding="utf-8")
    (d / "notes.txt").write_text("x", encoding="utf-8")
    assert read_snapshot(d, "content/handbook/") == {PATH: OLD}
    jl = tmp_path / "s.jsonl"
    jl.write_text(json.dumps({"path": "security/x.md", "content": OLD.replace("\n", "\r\n")}) + "\n", encoding="utf-8")
    assert read_snapshot(jl, "content/handbook/") == {PATH: OLD}


def test_cli_json(tmp_path, capsys):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(json.dumps({"path": PATH, "content": OLD}) + "\n", encoding="utf-8")
    b.write_text(json.dumps({"path": PATH, "content": NEW}) + "\n", encoding="utf-8")
    assert main([str(a), str(b), "--old-date", "2026-01-01", "--new-date", "2026-02-01", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["changes"] == 1 and out["changes"][0]["article"] == "Policy"


class FeedConn:
    def __init__(self):
        self.rows, self.runs, self.committed = {}, 0, False

    def execute(self, sql, params=None):
        conn = self

        class Cur:
            rowcount = 0

            def fetchone(self):
                return (conn.runs,)

        cur = Cur()
        if sql.startswith("INSERT INTO sync_runs"):
            self.runs += 1
            assert params[0] == "snapshot-diff"
        elif sql.startswith("INSERT INTO changed_articles"):
            if params[0] not in self.rows:
                self.rows[params[0]] = params
                cur.rowcount = 1
        return cur

    def commit(self):
        self.committed = True


def test_feed_uses_same_event_id_and_is_idempotent():
    res = diff({PATH: OLD}, {PATH: NEW})
    conn = FeedConn()
    assert feed(conn, res.articles) == 1 and conn.committed
    assert list(conn.rows) == [event_id(res.articles[0].model_dump())]
    assert feed(conn, res.articles) == 0


def test_snapshot_change_reaches_recall():
    """git 없이 찾은 바뀐 섹션도 git 경로와 같은 리콜 처리로 이어진다."""
    res = diff({PATH: OLD}, {PATH: NEW})
    [a] = res.articles
    answers = InMemoryAnswerStore()
    cite = Chunk(chunk_id="c1", org="security", rule_seq=a.rule_seq, rule_title="Disclosure", article="Policy", version_id="v1",
                 version_date="2026-01-01", fetched_at="2026-01-02", kind="article", text="30 days", source_url="https://example.invalid/x")
    answers.save("a1", "u1", "u1:t1", "How long until disclosure?", "We disclose 30 days after the fix.", "2026-01-15", [cite])
    texts = res.texts

    def read(seq, article, as_of):
        old, new = texts[(seq, article)]
        return {"text": new if as_of >= "2026-02-01" else old}

    svc = RecallService(store=InMemoryRecallStore(), answers=answers, read_section=read, judge=RuleJudge(), min_confidence=0.5)
    out = svc.process(a)
    [n] = out["notices"]
    assert n["answer_id"] == "a1" and n["severity"] == "high" and n["change_pattern"] == "deadline"
