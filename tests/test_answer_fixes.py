"""놓친 문항 해결안(`backend/graph/answer_fixes.py`)의 순수 함수 시험. 키와 네트워크 없음."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.graph import answer_fixes as F
from backend.prompts import question as P
from backend.services.skills import load_skill


def ch(cid: str, body: str, title: str = "Page", head: str = "Page > Sec") -> dict:
    return {"chunk_id": cid, "text": f"{head}\n{body}", "rule_title": title}


A = "a" * 16
B = "b" * 16
C = "c" * 16
D = "d" * 16


# ---------- A1 ----------
def test_value_keys_normalize_words_and_units():
    assert ("7", "day") in F.value_keys("must be fixed within seven days")
    assert ("2", "day") in F.value_keys("review within 2 business days")
    assert ("30", "%") in F.value_keys("about 30 percent")


def test_expand_adds_same_value_chunk_from_another_page():
    cited = [ch(A, "Merge requests should receive a review response within 2 business days for team members.")]
    ctx = [cited[0], ch(B, "The review response SLO for merge requests is 2 business days for team members.", title="Code Review"),
           ch(C, "Incidents are paged within 15 minutes.")]
    ans, out = F.expand_citations(f"리뷰는 2영업일 안에 한다 [{A}].", cited, ctx)
    assert [c["chunk_id"] for c in out] == [A, B]
    assert f"[{A}][{B}]" in ans


def test_expand_needs_a_shared_value_and_overlap():
    cited = [ch(A, "Merge requests should receive a review response within 2 business days.")]
    no_value = ch(B, "Merge requests should receive a review response quickly from reviewers.")
    other_value = ch(C, "Merge requests should receive a review response within 5 business days.")
    low_overlap = ch(D, "Laptops are shipped in 2 days from the vendor warehouse after the order.")
    ans, out = F.expand_citations(f"x [{A}]", cited, [cited[0], no_value, other_value, low_overlap])
    assert out == cited and ans == f"x [{A}]"


def test_expand_respects_the_cap_and_max_add():
    body = "Merge requests should receive a review response within 2 business days for team members."
    cited = [ch(A, body)]
    ctx = [ch(x * 16, body) for x in "bcdef"]
    _, out = F.expand_citations(f"x [{A}]", cited, ctx)
    assert len(out) == 1 + F.MAX_ADD
    _, out = F.expand_citations("x", [ch(x * 16, body) for x in "1234"], ctx, cap=4)
    assert len(out) == 4  # 이미 상한이면 더하지 않는다


def test_expand_numbered_continues_the_numbers():
    body = "Merge requests should receive a review response within 2 business days for team members."
    cited = [ch(A, "Incidents are paged within 15 minutes by the on-call engineer."), ch(B, body)]
    ctx = [*cited, ch(C, body, title="Code Review")]
    got, out = F.expand_numbered("페이지는 15분 [1]. 리뷰는 2영업일 [2].", cited, ctx)
    assert got == "페이지는 15분 [1]. 리뷰는 2영업일 [2][3]." and [c["chunk_id"] for c in out] == [A, B, C]


# ---------- A3 ----------
def test_relax_one_source_changes_the_answer_prompt_and_skill():
    system = P.answer_picked(P.ANSWER_SYSTEM)
    assert F.ONE_SOURCE_RULE in system and F.ONE_PICK in system
    relaxed = F.relax_one_source(system)
    assert F.ONE_SOURCE_RULE not in relaxed and F.MULTI_SOURCE_RULE in relaxed and F.MULTI_PICK in relaxed
    body = load_skill("citation-rules", enabled=True)
    assert F.SKILL_ONE in body and F.SKILL_MULTI in F.relax_skill(body)


# ---------- A4 ----------
def test_team_docs_go_last_only_when_no_team_is_asked():
    chunks = [ch(A, "x", title="Support Team Workflow"), ch(B, "y", title="Code Review Guidelines"), ch(C, "z", title="Data Group")]
    got = F.team_docs_last("코드 리뷰는 며칠 안에 해?", chunks)
    assert [c["chunk_id"] for c in got] == [B, A, C]
    assert F.team_docs_last("데이터팀 인시던트 심각도가 애매하면?", chunks) == chunks  # 14번처럼 팀을 말하면 그대로
    assert F.team_docs_last("support team 절차는?", chunks) == chunks


# ---------- A5 ----------
def test_carry_citations_keeps_unflagged_sentences():
    draft = f"정기 릴리스는 셋째 목요일이다 [{A}]. 패치는 한 달에 두 번이다 [{B}]."
    cited = [ch(A, "x"), ch(B, "y")]
    new = f"정기 릴리스는 매월 셋째 목요일에 나간다. 패치 릴리스는 매달 두 번 예정된다 [{C}]."
    ans, out = F.carry_citations(draft, cited, [f"패치는 한 달에 두 번이다 [{B}]."], new, [ch(C, "z")])
    assert [c["chunk_id"] for c in out] == [C, A]
    assert f"셋째 목요일에 나간다. [{A}]" in ans or f"나간다.[{A}]" in ans or f"[{A}]" in ans.split("패치")[0]
    same, out2 = F.carry_citations(draft, cited, [], f"전혀 다른 말 [{A}][{B}]", cited)
    assert out2 == cited


# ---------- B1 ----------
def test_pick_missing_sub():
    subs = ["EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼?", "IMOC도 응답이 없으면 어떻게 돼?"]
    assert F.pick_missing_sub(subs, ["IMOC 무응답 시 다음 단계"]) == subs[1]
    assert F.pick_missing_sub(subs, []) is None
    assert F.pick_missing_sub(subs[:1], ["IMOC"]) is None
    assert F.pick_missing_sub(subs, ["전혀 관계없는 말"]) is None


# ---------- D1 ----------
def test_english_phrases():
    assert F.english_phrases("Hard PCL보다 더 강한 Critical PCL은 언제 선언해?") == ["Hard PCL", "Critical PCL"]
    assert F.english_phrases("'Done'으로 인정되려면?") == ["Done"]
    assert F.english_phrases("온콜 호출이 오면?") == []


def test_unknown_phrases_with_a_small_corpus():
    corpus = F._squash("Hard PCL is declared by ... post-deploy migration (PDM)")
    assert F.unknown_phrases("Hard PCL보다 강한 Critical PCL은?", corpus) == ["Critical PCL"]
    assert F.unknown_phrases("post-deploy migration은 왜 안 돌려?", corpus) == []
    assert F.unknown_phrases("Critical PCL?", "") == []  # 코퍼스가 없으면 검사하지 않는다
    assert "Critical PCL" in F.unknown_name_message(["Critical PCL"])


@pytest.mark.skipif(not Path("data/chunks/chunks.jsonl").exists(), reason="코퍼스 파일 없음")
def test_unknown_phrases_on_the_corpus_spare_relevant_v2_questions():
    corpus = F.corpus_text()
    items = {it["id"]: it for it in (json.loads(x) for x in Path("evals/dataset_v2.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}
    for iid in (5, 12, 33, 34):  # 영문 구가 있는 관련 문항
        assert F.english_phrases(items[iid]["input"]), iid
        assert F.unknown_phrases(items[iid]["input"], corpus) == [], iid
    flagged_relevant = [i for i, it in items.items() if it["kind"] == "relevant" and F.unknown_phrases(it["input"], corpus)]
    assert flagged_relevant == []
    assert F.unknown_phrases(items[25]["input"], corpus)  # Critical PCL
