"""답변 리콜 재현율·정밀도를 운영 배포판의 실제 리콜 경로로 잰다(SPEC 3장 답변 리콜 행, 요청 문서 1장).

    python -m evals.newmetrics.recall_prod --pairs evals/recall_pairs.jsonl --base URL --out DIR --runs 3 --ledger L.json [--write-prod]
    python -m evals.newmetrics.recall_prod --pairs ... --plan-only --out DIR          # DB·API 접속 없이 계획·SQL·비용 추정만
    python -m evals.newmetrics.recall_prod --pairs ... --local-dsn postgresql://...    # 버리는 로컬 Postgres로 넣기·처리·정리 예행
    python -m evals.newmetrics.recall_prod --cleanup-only --plan-file DIR/run1/plan.json   # 죽은 실행 뒤 정리

운영 경로: 시험 페이지(rule_seq 92억대, org `TEST-RCL-EVAL-<날짜>`)에 개정 전·후 판과 바뀐 섹션 청크를 넣고, 정답의 지난 질문·답을 일반 평가용 계정(B)의
답과 인용으로 넣은 뒤, 서비스 키로 `POST /webhooks/regulation-updated`(운영 수집이 쓰는 입구)에 바뀐 섹션을 보낸다. 운영 서버가 리콜 그래프
(답 찾기 -> LLM 판정 -> 알림·검토함)를 돌려 `recall_notices`에 남긴 것을 읽기 전용으로 읽고, 끝나면(예외·중단 포함) 넣은 행과 리콜이 만든 행을 지워 0행을 확인한다.

측정 정의(SPEC 3장: "결론이 바뀐 답을 찾는 비율", 재현율 0.80 이상, 정밀도 0.80 이상):
- 양성 = 정답 "결론 바뀜: 예". 시스템 양성 = 그 답에 운영 리콜이 알림을 만들었음.
- 재현율 = TP / (TP + FN), 정밀도 = TP / (TP + FP), F1은 참고. 정답의 "애매" 행은 빼고 세고 따로 적는다.
- 보기 셋(같은 판정 1번에서 함께 센다). SPEC에 올리는 값은 `judge`다(팀장 결정 2026-11-16).
  `judge`(기본): LLM 판정이 바뀜·판정 실패인 알림. 판정은 그대로인데 코드 규칙이 중요한 변경이라 검토함에 보낸 `judge_disagrees_with_rule`은 뺀다.
  `exp_recall_v1`의 notices_for와 같은 기준이다.
  `notice`(함께 기록): 알림 후보 전부(사용자 알림 + 관리자 검토함). `user`(함께 기록): 사용자에게 바로 보인 알림만.
- 3회 실행(--runs 3): 회차별 값, 평균, 3회 합산, 행별 2/3 다수결 값을 모두 낸다.

부작용과 범위(--write-prod일 때만 쓴다):
- 영향받는 답은 넣은 답뿐이다(넣기 전 시험 rule_seq를 인용한 답이 0인지 확인). 알림은 계정 B에게만 간다. 판정이 낮은 확신도이면 관리자 검토함(관리자 모두 볼 수 있음)에 잠깐 보인다.
- 웹훅 구독(업무시스템 전송)은 사용자와 상관없이 모든 활성 구독으로 나간다. 활성 구독이 1개라도 있으면 넣기 전에 멈춘다(실제 시스템으로 나가는 부작용).
- 검색 격리: 시험 청크는 임베딩·embedder가 비어 벡터 질의(`embedder = ...`)에 잡히지 않고, 새 판도 하루짜리로 닫아(valid_to = 새 판 날짜 + 1일)
  기준일 없는 일반 질문의 현재 판 필터(valid_to IS NULL)에도 걸리지 않는다. BM25 색인은 서버 기동 때 한 번 읽으므로, 측정하는 몇 분 사이에 새 인스턴스가
  뜨고 그 인스턴스에 시험 판 기간(개정 전날~새 판 다음 날)을 기준일로 준 질문이 올 때만 시험 청크가 후보가 될 수 있다(남는 위험). 넣은 뒤 이를 SQL로 확인한다.
- 링크 대상이 없어 함께 볼 정책 후보도 0이다.
- 판정 LLM 비용은 운영 서버 키로 나간다. 직접 셀 수 없어 프롬프트 길이로 추정해 장부에 '추정'으로 적는다(단가 backend/services/llm_prices.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.newmetrics.common import (CostLedger, check_rows, connect_ro, connect_rw, gold_meta, mean, now_kst, prf, read_jsonl, say,
                                     write_jsonl, write_results)

RULE_SEQ_BASE = 9_200_000_000      # 실제 rule_seq < 2^32, 코퍼스 주입 시험은 90억대 앞쪽(그 인용이 남아 있다) -> 92억대
PREFIX_ROOT = "TEST-RCL-EVAL-"
VIEWS = ("judge", "notice", "user")   # 첫째가 SPEC에 올리는 값
OUT_TOKENS_GUESS = 300             # 판정 응답 한 번의 출력 토큰 추정
CHARS_PER_TOKEN = 3.0              # 영어·한국어가 섞인 프롬프트의 보수적 환산
RETRY_FACTOR_WORST = 3             # 최악: 재시도 2번(LLM_MAX_RETRIES=2)
EXIT_OK, EXIT_FAIL, EXIT_ENV, EXIT_COST, EXIT_CLEANUP, EXIT_PREFLIGHT = 0, 1, 2, 3, 4, 5


# ---------- 계획 ----------

@dataclass
class Group:
    gi: int
    rule_seq: int
    commit_full: str
    page: str
    article: str
    change_type: str
    old_version_date: str
    new_version_date: str
    title: str
    source_url: str
    old_text: str
    new_text: str
    old_chunk: str
    new_chunk: str | None
    old_version: str
    new_version: str
    event_key: str
    date_adjusted: bool = False
    answers: list[dict] = field(default_factory=list)

    def changed(self) -> dict:
        return {"rule_seq": self.rule_seq, "article": self.article, "old_version_date": self.old_version_date,
                "new_version_date": self.new_version_date, "change_type": self.change_type}


@dataclass
class Plan:
    date: str
    run: int
    prefix: str
    user_id: str
    groups: list[Group]

    @property
    def seqs(self) -> list[int]:
        return [g.rule_seq for g in self.groups]

    @property
    def answer_ids(self) -> list[str]:
        return [a["answer_id"] for g in self.groups for a in g.answers]

    @property
    def event_keys(self) -> list[str]:
        return [g.event_key for g in self.groups]

    def to_json(self) -> dict:
        return {"date": self.date, "run": self.run, "prefix": self.prefix, "user_id": self.user_id, "groups": [asdict(g) for g in self.groups]}

    @staticmethod
    def from_json(d: dict) -> "Plan":
        return Plan(d["date"], d["run"], d["prefix"], d["user_id"], [Group(**g) for g in d["groups"]])


def tag_prefix(date: str, run: int) -> str:
    return f"{PREFIX_ROOT}{date}-r{run}"


def build_plan(rows: list[dict], history, *, run: int, date: str, user_id: str) -> Plan:
    """정답 쌍 -> 넣을 행 계획. 섹션 본문은 핸드북 캐시에서 운영의 두 시점 비교 함수로 만든다(handbook_history)."""
    from backend.rag.ingest.schedule import event_id

    prefix = tag_prefix(date, run)
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by[(r["commit"], r["page"], r["section"])].append(r)
    groups = []
    for gi, (key, rs) in enumerate(sorted(by.items(), key=lambda kv: min(int(x["id"][1:]) for x in kv[1]))):
        c = history.section_change(*key)
        seq = RULE_SEQ_BASE + run * 100 + gi
        g = Group(gi=gi, rule_seq=seq, commit_full=c.commit_full, page=key[1], article=c.article,
                  change_type=c.change_type, old_version_date=c.old_version_date, new_version_date=c.new_version_date,
                  title=f"[평가용 시험 페이지] {key[1]}", source_url=c.source_url, old_text=c.old_text, new_text=c.new_text,
                  old_chunk=f"{prefix}-{gi:02d}-o", new_chunk=None if c.change_type == "removed" else f"{prefix}-{gi:02d}-n",
                  old_version=f"TESTRCL{date}R{run}G{gi:02d}O", new_version=f"TESTRCL{date}R{run}G{gi:02d}N",
                  event_key="", date_adjusted=c.date_adjusted)
        g.event_key = event_id(g.changed())
        for r in sorted(rs, key=lambda x: int(x["id"][1:])):
            g.answers.append({"answer_id": f"{prefix}-{r['id']}", "id": r["id"], "question": r["question"], "answer": r["answer"],
                              "as_of": c.as_of, "expected": r["expected"], "ambiguous": bool(r.get("ambiguous"))})
        groups.append(g)
    return Plan(date, run, prefix, user_id, groups)


def assert_ours(plan: Plan) -> None:
    """넣기·지우기 전 검사: 모든 행이 시험 표식(접두·rule_seq 범위)을 달고 있어야 한다."""
    if not plan.groups:
        raise ValueError("계획이 비었다")
    for g in plan.groups:
        if not (g.rule_seq >= RULE_SEQ_BASE and g.old_chunk.startswith(plan.prefix + "-") and g.old_version.startswith(f"TESTRCL{plan.date}")):
            raise ValueError(f"시험 표식이 아닌 항목: {g.rule_seq}")
        for a in g.answers:
            if not a["answer_id"].startswith(plan.prefix + "-"):
                raise ValueError(f"시험 표식이 아닌 답: {a['answer_id']}")


# ---------- SQL (값은 자리 %(이름)s로만) ----------

SQL_INS_DOC = "INSERT INTO docs (rule_seq, org, title, fmt, source_url, fetched_at) VALUES (%(seq)s, %(org)s, %(title)s, 'md', %(url)s, %(d)s)"
SQL_INS_VER = ("INSERT INTO versions (rule_seq, version_id, version_date, version_date_before, valid_from, valid_to) "
               "VALUES (%(seq)s, %(vid)s, %(d)s, false, %(d)s, %(to)s)")
SQL_INS_CHUNK = ("INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url, text_sha256, line_start, line_end) "
                 "VALUES (%(cid)s, %(vid)s, %(seq)s, 0, 0, %(art)s, 'article', %(text)s, %(url)s, %(sha)s, 1, %(le)s)")
SQL_INS_ANSWER = "INSERT INTO answers (answer_id, user_id, thread_id, question, answer, as_of) VALUES (%(aid)s, %(uid)s, '', %(q)s, %(a)s, %(as_of)s)"
SQL_INS_CITE = ("INSERT INTO citations (answer_id, chunk_id, version_id, rule_seq, article, version_date, source_url) "
                "VALUES (%(aid)s, %(cid)s, %(vid)s, %(seq)s, %(art)s, %(vd)s, %(url)s)")

SQL_MINE = """SELECT
 (SELECT count(*) FROM docs WHERE rule_seq = ANY(%(seqs)s::bigint[]) OR starts_with(org, %(prefix)s)),
 (SELECT count(*) FROM versions WHERE rule_seq = ANY(%(seqs)s::bigint[])),
 (SELECT count(*) FROM chunks WHERE rule_seq = ANY(%(seqs)s::bigint[]) OR starts_with(chunk_id, %(prefix)s)),
 (SELECT count(*) FROM answers WHERE answer_id = ANY(%(aids)s::text[]) OR starts_with(answer_id, %(prefix)s)),
 (SELECT count(*) FROM citations WHERE rule_seq = ANY(%(seqs)s::bigint[]) OR answer_id = ANY(%(aids)s::text[])),
 (SELECT count(*) FROM recall_events WHERE event_key = ANY(%(keys)s::text[])),
 (SELECT count(*) FROM recall_notices WHERE event_key = ANY(%(keys)s::text[]) OR answer_id = ANY(%(aids)s::text[])),
 (SELECT count(*) FROM maintenance_candidates WHERE event_key = ANY(%(keys)s::text[])),
 (SELECT count(*) FROM webhook_deliveries WHERE notice_id IN (SELECT notice_id FROM recall_notices WHERE event_key = ANY(%(keys)s::text[]))),
 (SELECT count(*) FROM recall_digests WHERE notice_ids ?| %(nids)s::text[])"""
MINE_KEYS = ("docs", "versions", "chunks", "answers", "citations", "recall_events", "recall_notices", "maintenance_candidates",
             "webhook_deliveries", "recall_digests")
SQL_COUNTS = "SELECT (SELECT count(*) FROM docs), (SELECT count(*) FROM versions), (SELECT count(*) FROM chunks)"
SQL_SUBS_ACTIVE = "SELECT count(*) FROM webhook_subscriptions WHERE active"
SQL_EVENTS = "SELECT event_key, status, notices, review, judge_failures, candidates, error_kind FROM recall_events WHERE event_key = ANY(%(keys)s::text[])"
SQL_NOTICES = ("SELECT notice_id, event_key, answer_id, user_id, conclusion_changed, explanation, severity, confidence, change_pattern, "
               "review_status, review_reason, judge_failed FROM recall_notices WHERE event_key = ANY(%(keys)s::text[])")
SQL_NOTICE_IDS = "SELECT notice_id FROM recall_notices WHERE event_key = ANY(%(keys)s::text[]) OR answer_id = ANY(%(aids)s::text[])"
SQL_FOREIGN_CITES = "SELECT count(*) FROM citations WHERE rule_seq = ANY(%(seqs)s::bigint[]) AND NOT (answer_id = ANY(%(aids)s::text[]))"
SQL_SEARCH_VISIBLE = ("SELECT count(*) FROM chunks c JOIN versions v ON v.rule_seq = c.rule_seq AND v.version_id = c.version_id "
                      "WHERE c.rule_seq = ANY(%(seqs)s::bigint[]) AND (v.valid_to IS NULL OR c.embedder IS NOT NULL OR c.embedding IS NOT NULL)")
SQL_OWNERS ="SELECT DISTINCT a.user_id FROM citations c JOIN answers a ON a.answer_id = c.answer_id WHERE c.rule_seq = ANY(%(seqs)s::bigint[])"
# 정리(한 트랜잭션, 넣은 키와 접두로만)
SQL_DEL = (
    ("webhook_deliveries", "DELETE FROM webhook_deliveries WHERE notice_id = ANY(%(nids)s::text[])"),
    ("recall_digests", "DELETE FROM recall_digests WHERE user_id = %(uid)s AND notice_ids ?| %(nids)s::text[]"),
    ("recall_notices", "DELETE FROM recall_notices WHERE event_key = ANY(%(keys)s::text[]) AND (answer_id = ANY(%(aids)s::text[]) OR starts_with(answer_id, %(prefix)s))"),
    ("recall_notices_orphan", "DELETE FROM recall_notices WHERE starts_with(answer_id, %(prefix)s) AND user_id = %(uid)s"),
    ("maintenance_candidates", "DELETE FROM maintenance_candidates WHERE event_key = ANY(%(keys)s::text[])"),
    ("recall_events", "DELETE FROM recall_events WHERE event_key = ANY(%(keys)s::text[])"),
    ("citations", "DELETE FROM citations WHERE answer_id = ANY(%(aids)s::text[]) AND starts_with(answer_id, %(prefix)s)"),
    ("answers", "DELETE FROM answers WHERE answer_id = ANY(%(aids)s::text[]) AND starts_with(answer_id, %(prefix)s) AND user_id = %(uid)s"),
    ("chunks", "DELETE FROM chunks WHERE rule_seq = ANY(%(seqs)s::bigint[]) AND starts_with(chunk_id, %(prefix)s)"),
    ("versions", "DELETE FROM versions WHERE rule_seq = ANY(%(seqs)s::bigint[]) AND starts_with(version_id, %(vprefix)s)"),
    ("docs", "DELETE FROM docs WHERE rule_seq = ANY(%(seqs)s::bigint[]) AND starts_with(org, %(prefix)s)"),
)


def org_of(plan: Plan) -> str:
    return plan.prefix


def params(plan: Plan, nids: list[str] | None = None) -> dict:
    return {"seqs": plan.seqs, "prefix": plan.prefix, "vprefix": f"TESTRCL{plan.date}R{plan.run}", "aids": plan.answer_ids,
            "keys": plan.event_keys, "uid": plan.user_id, "nids": list(nids or [])}


def _one(conn, sql: str, prm: dict) -> tuple:
    return tuple(conn.execute(sql, prm).fetchone())


def mine(conn, plan: Plan) -> dict[str, int]:
    nids = [r[0] for r in conn.execute(SQL_NOTICE_IDS, params(plan)).fetchall()]
    return dict(zip(MINE_KEYS, map(int, _one(conn, SQL_MINE, params(plan, nids or ["-"])))))


def counts(conn) -> dict[str, int]:
    d, v, c = _one(conn, SQL_COUNTS, {})
    return {"docs": int(d), "versions": int(v), "chunks": int(c)}


class PreflightError(RuntimeError):
    pass


def preflight(conn, plan: Plan, *, require_no_subs: bool = True) -> dict:
    """읽기 전용. 활성 웹훅 구독 0, 시험 표식 행 0, 시험 rule_seq를 인용한 다른 답 0. 아니면 PreflightError(DB 변경 없음)."""
    subs = int(_one(conn, SQL_SUBS_ACTIVE, {})[0])
    if require_no_subs and subs:
        raise PreflightError(f"활성 웹훅 구독 {subs}개: 시험 알림이 업무시스템으로 나간다. 멈춘다")
    left = mine(conn, plan)
    if any(left.values()):
        raise PreflightError(f"시험 표식 행이 이미 있다 {left}: --cleanup-only로 먼저 정리한다")
    return {"webhook_subscriptions_active": subs, "counts_before": counts(conn)}


def next_day(d: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def insert_plan(conn, plan: Plan) -> dict[str, int]:
    """한 트랜잭션으로 넣는다. 한 줄이라도 실패하면 전부 되돌린다."""
    assert_ours(plan)
    n = defaultdict(int)
    try:
        for g in plan.groups:
            n["docs"] += conn.execute(SQL_INS_DOC, {"seq": g.rule_seq, "org": org_of(plan), "title": g.title, "url": g.source_url,
                                                     "d": g.new_version_date}).rowcount
            n["versions"] += conn.execute(SQL_INS_VER, {"seq": g.rule_seq, "vid": g.old_version, "d": g.old_version_date, "to": g.new_version_date}).rowcount
            # 새 판도 하루짜리로 닫는다: 현재 판(valid_to IS NULL)을 보는 일반 검색(as_of 없음)의 필터에 시험 청크가 걸리지 않게(검색 격리)
            n["versions"] += conn.execute(SQL_INS_VER, {"seq": g.rule_seq, "vid": g.new_version, "d": g.new_version_date,
                                                         "to": next_day(g.new_version_date)}).rowcount
            for cid, vid, body in ((g.old_chunk, g.old_version, g.old_text), (g.new_chunk, g.new_version, g.new_text)):
                if cid is None:
                    continue
                text = f"{g.title} > {g.article}\n{body}"   # 청크 글 = 머리말 한 줄 + 본문(겹침 없음, section.body_of 규칙)
                n["chunks"] += conn.execute(SQL_INS_CHUNK, {"cid": cid, "vid": vid, "seq": g.rule_seq, "art": g.article, "text": text,
                                                             "url": g.source_url, "sha": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                                                             "le": body.count("\n") + 1}).rowcount
            for a in g.answers:
                n["answers"] += conn.execute(SQL_INS_ANSWER, {"aid": a["answer_id"], "uid": plan.user_id, "q": a["question"], "a": a["answer"],
                                                               "as_of": a["as_of"]}).rowcount
                n["citations"] += conn.execute(SQL_INS_CITE, {"aid": a["answer_id"], "cid": g.old_chunk, "vid": g.old_version, "seq": g.rule_seq,
                                                               "art": g.article, "vd": g.old_version_date, "url": g.source_url}).rowcount
        want = {"docs": len(plan.groups), "versions": 2 * len(plan.groups), "chunks": sum(1 + (g.new_chunk is not None) for g in plan.groups),
                "answers": len(plan.answer_ids), "citations": len(plan.answer_ids)}
        if dict(n) != want:
            raise RuntimeError(f"넣은 행 수가 계획과 다르다 {dict(n)} != {want}")
        visible = int(_one(conn, SQL_SEARCH_VISIBLE, params(plan))[0])
        if visible:
            raise RuntimeError(f"시험 청크 {visible}개가 일반 검색(현재 판·벡터)에 보인다")
        foreign = int(_one(conn, SQL_FOREIGN_CITES, params(plan))[0])
        owners = {r[0] for r in conn.execute(SQL_OWNERS, params(plan)).fetchall()}
        if foreign or owners != {plan.user_id}:
            raise RuntimeError(f"시험 rule_seq를 다른 답·사용자가 인용한다(다른 인용 {foreign}, 주인 {len(owners)}명)")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(n)


def cleanup_plan(conn, plan: Plan, before: dict | None = None) -> dict:
    """넣은 행과 리콜이 만든 행만 지운다(한 트랜잭션). 이어서 남은 행이 0인지, docs·versions·chunks 전체 수가 시작 때와 같은지 본다."""
    assert_ours(plan)
    nids = [r[0] for r in conn.execute(SQL_NOTICE_IDS, params(plan)).fetchall()]
    prm = params(plan, nids or ["-"])
    deleted = {}
    try:
        for name, sql in SQL_DEL:
            deleted[name] = conn.execute(sql, prm).rowcount
        limits = {"answers": len(plan.answer_ids), "citations": len(plan.answer_ids), "docs": len(plan.groups), "versions": 2 * len(plan.groups),
                  "chunks": 2 * len(plan.groups), "recall_events": len(plan.groups), "recall_notices": len(plan.answer_ids)}
        over = {k: v for k, v in deleted.items() if k in limits and v > limits[k]}
        if over:
            raise RuntimeError(f"계획보다 많은 행이 지워지려 한다 {over}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    left = mine(conn, plan)
    after = counts(conn)
    match = before is None or after == before
    return {"deleted": deleted, "leftover": left, "counts_before": before, "counts_after": after, "counts_match": match,
            "ok": not any(left.values()) and match}


# ---------- 결과 읽기 ----------

def wait_events(conn, plan: Plan, timeout_s: float, poll_s: float = 10.0) -> dict[str, dict]:
    cols = ("event_key", "status", "notices", "review", "judge_failures", "candidates", "error_kind")
    end, got = time.time() + timeout_s, {}
    while True:
        got = {r[0]: dict(zip(cols, r)) for r in conn.execute(SQL_EVENTS, {"keys": plan.event_keys}).fetchall()}
        if len(got) == len(plan.groups) and all(v["status"] in ("done", "failed") for v in got.values()):
            return got
        if time.time() >= end:
            return got
        time.sleep(poll_s)


def read_notices(conn, plan: Plan) -> dict[str, dict]:
    cols = ("notice_id", "event_key", "answer_id", "user_id", "conclusion_changed", "explanation", "severity", "confidence", "change_pattern",
            "review_status", "review_reason", "judge_failed")
    return {r[2]: dict(zip(cols, r)) for r in conn.execute(SQL_NOTICES, {"keys": plan.event_keys}).fetchall()}


def row_results(plan: Plan, notices: dict[str, dict], events: dict[str, dict]) -> list[dict]:
    out = []
    for g in plan.groups:
        ev = events.get(g.event_key) or {}
        for a in g.answers:
            n = notices.get(a["answer_id"])
            out.append({
                "id": a["id"], "run": plan.run, "expected": a["expected"], "ambiguous": a["ambiguous"], "event_status": ev.get("status"),
                "notice": n is not None, "user": bool(n) and n.get("review_status") is None,
                "judge": bool(n) and n.get("review_reason") != "judge_disagrees_with_rule",
                "review_status": (n or {}).get("review_status"), "review_reason": (n or {}).get("review_reason"),
                "judge_failed": (n or {}).get("judge_failed"), "confidence": (n or {}).get("confidence"), "severity": (n or {}).get("severity"),
                "explanation": str((n or {}).get("explanation") or "")[:400], "article": g.article, "change_type": g.change_type,
            })
    return out


# ---------- 점수 ----------

def score(rows: list[dict], view: str, include_ambiguous: bool = False) -> dict:
    """한 회차의 행 -> 재현율·정밀도. 처리되지 않은 개정(event_status가 done이 아님)의 행은 분모에서 빼고 수를 적는다."""
    use = [r for r in rows if (include_ambiguous or not r["ambiguous"]) and r["expected"] is not None]
    done = [r for r in use if r.get("event_status") == "done"]
    tp = sum(1 for r in done if r["expected"] and r[view])
    fp = sum(1 for r in done if not r["expected"] and r[view])
    fn = sum(1 for r in done if r["expected"] and not r[view])
    tn = sum(1 for r in done if not r["expected"] and not r[view])
    return {**prf(tp, fp, fn), "tn": tn, "n": len(done), "not_processed": len(use) - len(done)}


def aggregate(per_run: list[list[dict]]) -> dict:
    out: dict[str, Any] = {}
    for view in VIEWS:
        runs = [score(rs, view) for rs in per_run]
        pooled = score([r for rs in per_run for r in rs], view)
        by_id: dict[str, list[dict]] = defaultdict(list)
        for rs in per_run:
            for r in rs:
                by_id[r["id"]].append(r)
        votes = []
        for rid, rs in by_id.items():
            ok = [r for r in rs if r.get("event_status") == "done"]
            if not ok:
                continue
            votes.append({**ok[0], view: sum(1 for r in ok if r[view]) * 2 > len(ok), "event_status": "done"})
        out[view] = {"runs": runs, "mean": {"recall": mean(r["recall"] for r in runs), "precision": mean(r["precision"] for r in runs),
                                            "f1": mean(r["f1"] for r in runs)},
                     "pooled": pooled, "majority": score(votes, view), "with_ambiguous_pooled": score([r for rs in per_run for r in rs], view, True)}
    return out


# ---------- 비용 추정 ----------

def estimate_cost(plan: Plan) -> dict:
    """운영 판정 호출 = 영향받는 답 1건당 1번. 입력 = 판정 시스템 프롬프트(+mail-templates Skill) + 질문·답·개정 전후 본문."""
    from backend.graph.recall.notice import recall_user, system_prompt
    from backend.schemas.recall import ChangedArticle
    from backend.services.cost import load_prices, price_for

    p_in, p_out = price_for(os.environ.get("LLM_MODEL") or "claude-haiku-5-5", load_prices())
    sys_chars = len(system_prompt(True))
    calls, chars = 0, 0
    for g in plan.groups:
        ch = ChangedArticle(**g.changed())
        for a in g.answers:
            calls += 1
            chars += sys_chars + len(recall_user({"question": a["question"], "answer": a["answer"]}, ch, g.old_text, g.new_text))
    tin = chars / CHARS_PER_TOKEN
    tout = calls * OUT_TOKENS_GUESS
    usd = (tin * p_in + tout * p_out) / 1e6
    return {"calls": calls, "input_tokens_est": int(tin), "output_tokens_est": tout, "usd_est": round(usd, 5),
            "usd_worst": round(usd * RETRY_FACTOR_WORST * 2, 5), "price_per_mtok": [p_in, p_out]}


# ---------- 실행 ----------

def local_process(dsn: str, plan: Plan, llm) -> None:
    """예행(--local-dsn): 운영 웹훅 대신 같은 코드(RecallService + Postgres 저장소 + section_reader)를 로컬 DB에 붙여 처리한다."""
    from backend.graph.answer_store import PgAnswerStore
    from backend.graph.recall.judge import LLMJudge
    from backend.graph.recall.runtime import section_reader
    from backend.graph.recall.service import RecallService
    from backend.graph.recall.store import PgRecallStore
    from backend.schemas.recall import ChangedArticle

    from backend.graph.recall.maintenance import PgLinks

    svc = RecallService(store=PgRecallStore(dsn), answers=PgAnswerStore(dsn), read_section=section_reader(dsn), links=PgLinks(dsn),
                        judge=LLMJudge(llm))
    for g in plan.groups:
        svc.process(ChangedArticle(**g.changed()))


def run_one(plan: Plan, out: Path, *, base: str | None, dsn: str | None, local_llm=None, timeout_s: float, write: bool) -> dict:
    """한 회차: 사전 점검 -> 원장 쓰기 -> 넣기 -> 보내기 -> 기다리기 -> 읽기 -> (언제나) 정리·확인."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")   # 원장: 죽어도 이것으로 지운다
    res: dict[str, Any] = {"run": plan.run, "started": now_kst(), "event_keys": plan.event_keys}
    ro = connect_ro(dsn)
    try:
        res["preflight"] = preflight(ro, plan)
    finally:
        ro.close()
    if not write:
        res["skipped"] = "--write-prod 없이 넣지 않음"
        return res
    rw = connect_rw(dsn)
    try:
        res["inserted"] = insert_plan(rw, plan)
        if local_llm is not None:
            local_process(dsn, plan, local_llm)
            res["webhook"] = {"status": "local", "accepted": len(plan.groups)}
        else:
            code, body = post_changes(base, plan)
            res["webhook"] = {"status": code, "accepted": body.get("accepted"),
                              "event_ids_match": (body.get("event_ids") or []) == plan.event_keys}
            if code != 202:
                raise RuntimeError(f"웹훅 {code}")
        ro = connect_ro(dsn)
        try:
            events = wait_events(ro, plan, timeout_s, poll_s=0.5 if local_llm is not None else 10.0)
            notices = read_notices(ro, plan)
        finally:
            ro.close()
        res["events"] = events
        res["rows"] = row_results(plan, notices, events)
    finally:
        try:
            res["cleanup"] = cleanup_plan(rw, plan, (res.get("preflight") or {}).get("counts_before"))
            if local_llm is None:
                time.sleep(90)                 # 늦게 끝난 백그라운드 처리가 알림을 더 쓰지 않았는지 한 번 더 본다
                again = mine(rw, plan)
                if any(again.values()):
                    res["cleanup_second"] = cleanup_plan(rw, plan, None)
        finally:
            rw.close()
    res["finished"] = now_kst()
    (out / "run.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def post_changes(base: str | None, plan: Plan) -> tuple[int, dict]:
    from evals.newmetrics.prod import post_regulation_updated

    if not base:
        raise RuntimeError("--base 없음")
    return post_regulation_updated(base, [g.changed() for g in plan.groups])


def render_md(summary: dict) -> str:
    a = summary.get("metrics") or {}
    lines = [f"# 답변 리콜 재현율·정밀도 ({summary['started'][:10]})", "",
             f"운영 판 `{summary.get('revision')}`, 커밋 `{summary.get('commit')}`. 경로: 시험 페이지·평가용 계정 B의 답을 넣고 `POST /webhooks/regulation-updated`로 운영 리콜을 돌렸다(실행 {summary['runs_done']}회).",
             f"정답 `{summary['gold']['file']}` {summary['gold']['rows']}행(sha256 `{summary['gold']['sha256'][:12]}`), 애매 {summary['ambiguous']}행은 기본 값에서 뺐다.", "",
             "| 보기 | 재현율(평균) | 정밀도(평균) | F1(평균) | 3회 합산 재현율 / 정밀도 | 2/3 다수결 재현율 / 정밀도 | 기준 |", "|---|---|---|---|---|---|---|"]
    names = {"judge": "LLM 판정 기준(SPEC 값)", "notice": "알림 후보 전부(함께 기록)", "user": "사용자에게 바로 보인 알림(함께 기록)"}
    for v in VIEWS:
        m = a.get(v)
        if not m:
            continue
        lines.append(f"| {names[v]} | {m['mean']['recall']} | {m['mean']['precision']} | {m['mean']['f1']} | {m['pooled']['recall']} / {m['pooled']['precision']} | "
                     f"{m['majority']['recall']} / {m['majority']['precision']} | 재현율 0.80 이상, 정밀도 0.80 이상 |")
    lines += ["", f"비용(추정, 운영 서버 키): {summary.get('cost_est_usd')}달러. 정리: {summary.get('cleanup_ok')}.", "",
              "회차별 값과 행별 판정은 summary.json, rows.jsonl에 있다."]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="답변 리콜 운영 측정")
    ap.add_argument("--pairs", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--revision", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--total-cap", type=float, default=0.5)
    ap.add_argument("--run-cap", type=float, default=0.05)
    ap.add_argument("--timeout-s", type=float, default=900.0)
    ap.add_argument("--write-prod", action="store_true", help="운영 DB에 시험 행을 넣고 웹훅을 보낸다(없으면 사전 점검까지만)")
    ap.add_argument("--plan-only", action="store_true", help="DB·API 없이 계획·비용 추정만")
    ap.add_argument("--local-dsn", default="", help="버리는 로컬 Postgres(예행). 가짜 판정 모델로 같은 처리 코드를 돈다")
    ap.add_argument("--cleanup-only", action="store_true")
    ap.add_argument("--plan-file", type=Path)
    a = ap.parse_args(argv)

    if a.cleanup_only:
        plan = Plan.from_json(json.loads(a.plan_file.read_text(encoding="utf-8")))
        rw = connect_rw(a.local_dsn or None)
        try:
            res = cleanup_plan(rw, plan, None)
        finally:
            rw.close()
        write_results(a.out, {"cleanup": res}, f"# 리콜 시험 행 정리\n\n결과 {res['ok']}, 남은 행 {res['leftover']}\n")
        say(f"정리 ok={res['ok']} 남은 행 {res['leftover']}")
        return EXIT_OK if res["ok"] else EXIT_CLEANUP

    from evals.newmetrics.handbook_history import HandbookHistory

    rows = read_jsonl(a.pairs)
    check_rows("recall", rows)
    history = HandbookHistory()
    user_id = "plan-only-user"
    if not a.plan_only and not a.local_dsn:
        from evals.newmetrics.prod import client, login

        if not os.environ.get("DATABASE_URL"):
            say("DATABASE_URL 없음")
            return EXIT_ENV
        with client(a.base) as cb:
            user_id = login(cb, "B")
    elif a.local_dsn:
        user_id = "dryrun-user-b"
    plans = [build_plan(rows, history, run=i, date=a.date, user_id=user_id) for i in range(1, a.runs + 1)]
    est = estimate_cost(plans[0])
    summary: dict[str, Any] = {"metric": "recall", "started": now_kst(), "revision": a.revision, "commit": a.commit, "gold": gold_meta(a.pairs),
                               "ambiguous": sum(1 for r in rows if r.get("ambiguous")), "cost_estimate_per_run": est, "runs_done": 0,
                               "date_adjusted_groups": [g.article for g in plans[0].groups if g.date_adjusted],
                               "definition": "재현율 = TP/(TP+FN), 정밀도 = TP/(TP+FP), 양성 = 정답 '결론 바뀜: 예', 시스템 양성 = 운영 리콜 알림 중 LLM 판정이 바뀜·실패인 것(보기 judge, SPEC 값). notice·user 보기는 함께 기록", "primary_view": "judge"}
    if a.plan_only:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "plan_run1.json").write_text(json.dumps(plans[0].to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        write_results(a.out, summary, f"# 답변 리콜 계획(접속 없음)\n\n시험 페이지 {len(plans[0].groups)}개, 답 {len(plans[0].answer_ids)}건, 회차당 비용 추정 {est['usd_est']}달러(최악 {est['usd_worst']}).\n")
        say(f"계획만: 페이지 {len(plans[0].groups)} 답 {len(plans[0].answer_ids)} 회차당 추정 {est['usd_est']}달러")
        return EXIT_OK
    ledger = CostLedger(a.ledger or (a.out / "cost_ledger.json"), a.total_cap)
    llm = None
    if a.local_dsn:
        from evals.newmetrics.fakes import FakeRecallLLM

        if os.environ.get("DATABASE_URL") and os.environ["DATABASE_URL"] != a.local_dsn:
            say("예행인데 DATABASE_URL이 다른 DB를 가리킨다: 멈춘다(운영 DB에 쓰지 않게)")
            return EXIT_ENV
        os.environ["DATABASE_URL"] = a.local_dsn      # section_reader(get_section)는 이 값의 DB를 읽는다
        llm = FakeRecallLLM({r["question"]: bool(r["expected"]) for r in rows})
    per_run, cleanup_ok, spent = [], True, 0.0
    code = EXIT_OK
    for plan in plans:
        if not a.local_dsn and a.write_prod:
            ok, why = ledger.allow(est["usd_est"], a.run_cap)
            if not ok:
                say(f"비용 상한으로 멈춤: {why}")
                code = EXIT_COST
                break
        try:
            res = run_one(plan, a.out / f"run{plan.run}", base=a.base, dsn=a.local_dsn or None, local_llm=llm, timeout_s=a.timeout_s,
                          write=a.write_prod or bool(a.local_dsn))
        except PreflightError as e:
            say(f"사전 점검에서 멈춤(DB 변경 없음): {e}")
            code = EXIT_PREFLIGHT
            break
        if not a.local_dsn and a.write_prod:
            ledger.add("recall", plan.run, est["usd_est"], "추정")
            spent += est["usd_est"]
        cl = res.get("cleanup") or {}
        cleanup_ok = cleanup_ok and (cl.get("ok", True) if "cleanup_second" not in res else res["cleanup_second"].get("ok", False))
        if "rows" in res:
            per_run.append(res["rows"])
            summary["runs_done"] += 1
            say(f"회차 {plan.run}: 처리 {sum(1 for e in res['events'].values() if e['status'] == 'done')}/{len(plan.groups)}, 알림 {sum(r['notice'] for r in res['rows'])}건, 정리 {cl.get('ok')}")
        if not cleanup_ok:
            say("정리 확인 실패: 다음 회차를 하지 않는다")
            code = EXIT_CLEANUP
            break
    summary.update({"metrics": aggregate(per_run) if per_run else None, "cost_est_usd": round(spent, 5), "cleanup_ok": cleanup_ok,
                    "finished": now_kst(), "mode": "local-dryrun" if a.local_dsn else ("prod" if a.write_prod else "preflight-only")})
    write_results(a.out, summary, render_md(summary), [r for rs in per_run for r in rs])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
