"""하위 질문에 원 질문의 대상·조건 유지(`GRAPH_DECOMPOSE_KEEP_SUBJECT`). 가짜 LLM만 쓴다(0원). 예시 질문은 핸드북·평가셋과 무관한 일반 문장이다."""
from __future__ import annotations

import json

import pytest

from backend.graph import decompose as D
from backend.graph import service_profile as SP

SWITCH = "GRAPH_DECOMPOSE_KEEP_SUBJECT"
Q = "해외 주문의 배송은 며칠 걸리고 반품 수수료는 얼마야?"
SUBS_DROPPED = ["배송은 며칠 걸려?", "반품 수수료는 얼마야?"]


def fake_ask(subs, seen):
    def ask(system, user):
        seen.append((system, user))
        return json.dumps({"split": True, "sub_questions": subs}, ensure_ascii=False)
    return ask


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(SWITCH, "1")


def test_off_keeps_the_measured_prompt_and_subs(off):
    assert D.keep_subject_enabled() is False
    assert D.system_prompt(D.TASK) == D.SYSTEM_TAGGED and D.system_prompt(D.GATE_TASK) == D.SYSTEM_GATE
    seen: list = []
    assert D.decompose_question(fake_ask(SUBS_DROPPED, seen), Q) == (SUBS_DROPPED, "llm")
    assert seen[0][0] == D.SYSTEM_TAGGED


def test_on_adds_the_rule_to_both_prompts_and_keeps_the_tag(on):
    for tag in (D.TASK, D.GATE_TASK):
        p = D.system_prompt(tag)
        assert p.startswith(f"[[task:{tag}]]\n{D.SYSTEM}") and p.endswith(D.KEEP_SUBJECT_RULE)
    seen: list = []
    assert D.gate_split(fake_ask(SUBS_DROPPED, seen), Q) is True
    assert seen[0][0].endswith(D.KEEP_SUBJECT_RULE)


def test_on_prefixes_the_dropped_subject_to_every_sub(on):
    seen: list = []
    subs, source = D.decompose_question(fake_ask(SUBS_DROPPED, seen), Q)
    assert source == "llm" and subs == ["해외 주문의 배송은 며칠 걸려?", "해외 주문의 반품 수수료는 얼마야?"]
    assert seen[0][0].endswith(D.KEEP_SUBJECT_RULE)


@pytest.mark.parametrize("question,subs", [
    (Q, ["해외 주문의 배송은 며칠 걸려?", "해외 주문의 반품 수수료는 얼마야?"]),   # 이미 들어 있다
    (Q, ["해외 주문의 배송은 며칠 걸려?", "반품 수수료는 얼마야?"]),                  # 한 하위 질문에 남았다: 꾸밈 범위를 모르므로 손대지 않는다
    ("배송은 며칠 걸리고 반품 수수료는 얼마야?", ["배송은 며칠 걸려?", "반품 수수료는 얼마야?"]),   # 첫 낱말부터 하위 질문에 있다
    ("언제 배송되고 반품 수수료는 얼마야?", ["배송은 언제 돼?", "반품 수수료는 얼마야?"]),         # 앞머리가 묻는 말뿐이다
    ("해외 주문의 배송은 며칠 걸리고 반품 수수료는 얼마야?", ["택배 기간은?", "환불 비용은?"]),     # 어느 내용어도 하위 질문에 없다: 판단하지 않는다
])
def test_keep_subject_leaves_subs_alone(question, subs):
    assert D.keep_subject(question, subs) == subs


def test_keep_subject_uses_the_question_sentence_and_not_the_company_name():
    q = "주문을 넣으려고 합니다. GitLab의 해외 주문 배송은 며칠 걸리고 반품 수수료는 얼마야?"
    out = D.keep_subject(q, SUBS_DROPPED)
    assert out == [f"해외 주문 {s}" for s in SUBS_DROPPED]
    assert not any("GitLab" in s for s in out)


def test_keep_subject_skips_a_too_long_head_and_empty_subs():
    long_head = "가" * (D.MAX_SUBJECT_CHARS + 1)
    assert D.keep_subject(f"{long_head}의 배송은 며칠 걸리고 반품 수수료는 얼마야?", SUBS_DROPPED) == SUBS_DROPPED
    assert D.keep_subject(Q, []) == []


def test_service_profile_turns_the_switch_on():
    assert SP.SERVICE_ENV[SWITCH] == "1"
    env: dict = {}
    SP.apply_service_profile(env)
    assert env[SWITCH] == "1"
    env2: dict = {SWITCH: "off"}
    SP.apply_service_profile(env2)
    assert env2[SWITCH] == ""   # 운영에서 off를 주면 재배포 없이 끈다(빈 값 = 코드 기본 꺼짐)
