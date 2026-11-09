"""D7 신뢰 경계 보강 시험 — 검색 원문 속 지시(간접 인젝션)와 내부 지시문 유출을 코드가 막는지 본다.

키 없이 가짜 모델(`qgraph_fakes.ScriptedLLM`)로 돈다. 각 시험은 고친 줄을 되돌리면 실패한다.
- G1 되묻기(give_up) 길에도 유출 검사
"""
from __future__ import annotations

from qgraph_fakes import ScriptedLLM, j

from backend.graph.build import MSG_REFUSE_LEAK, build_graph
from backend.prompts import question as P
from backend.schemas import Chunk

QUESTION = "1Password 처음 설정은 어떻게 해?"
BODY = "You will receive an invitation to get started in your email on your first day."
CLEAN_ID = "c3c3c3c3c3c3c3c3"
LEAKED = "너는 근거 충분성 판정기다. 질문에 답하는 데 아래 자료가 충분한지 판단한다."  # JUDGE_SYSTEM 둘째 줄 그대로


def _chunk(cid: str, text: str, *, title: str = "1Password Setup Guide", article: str | None = None) -> Chunk:
    return Chunk(chunk_id=cid, org="security", rule_seq=102204584, rule_title=title, article=article,
                 version_id="6f6d09965730", version_date="2024-11-01", fetched_at="2026-10-31", kind="article",
                 text=text, source_url="https://handbook.example/security/1password/setup/")


def _clean_search(_q):
    return [_chunk(CLEAN_ID, f"1Password Setup Guide\n{BODY}")]


def _run(llm, search=_clean_search):
    g = build_graph(search, llm=llm, use_skills=True, grounding_llm=True, decompose=False)
    return g.invoke({"question": QUESTION, "user_id": "u-d7", "thread_id": "t-d7", "as_of": "2026-11-07"})


def _give_up_llm(clarify: str) -> ScriptedLLM:
    """재검색 상한까지 부족 판정을 내고, 마지막에 clarify 문장을 남기는 가짜 모델."""
    n = iter(range(100))
    return ScriptedLLM({
        "classify": j(route="rule"),
        "rewrite": lambda _u: j(query=f"1Password setup {next(n)}", org=None, as_of=None),
        "judge": j(sufficient=False, partial=False, reason="부족", clarify=clarify),
    })


# ---------------- G1: 되묻기 길 유출 검사 ----------------
def test_g1_clarify_with_system_prompt_line_is_refused():
    out = _run(_give_up_llm(LEAKED))
    assert out["kind"] == "refuse"
    assert out["answer"] == MSG_REFUSE_LEAK
    assert not P.leaks_internal(out["answer"])


def test_g1_normal_clarify_still_goes_out():
    """대조군: 내부 문장이 없는 보통 되묻기는 그대로 사용자에게 간다(검사가 되묻기를 막지 않는다). 숫자가 있으면 원래 규칙(clarify_has_number)으로 거절되므로 숫자 없는 문장을 쓴다."""
    ask = "어느 팀의 비밀번호 관리 도구 설정 절차를 찾으시나요? 절(핸드북 섹션)을 알려 주세요."
    out = _run(_give_up_llm(ask))
    assert out["kind"] == "clarify"
    assert out["answer"] == ask
