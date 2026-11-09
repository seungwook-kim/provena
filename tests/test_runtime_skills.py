"""런타임 Skill 5개의 형식과 금지 사항 시험 (미실행 초안). 파일 내용만 읽는다. LLM과 네트워크를 쓰지 않는다."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services.skills import SKILL_NAMES, load_skill

ROOT = Path(__file__).resolve().parents[1]
NEW = ("delegation", "report-writing", "chat-tool-guide", "mail-templates", "retrieval-slots")


def raw(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NEW)
def test_registered_and_loads(name):
    assert name in SKILL_NAMES
    assert load_skill(name, enabled=True)
    assert load_skill(name, enabled=False) == ""  # 끔과 비교할 수 있어야 한다


@pytest.mark.parametrize("name", NEW)
def test_same_form_as_existing_skills(name):
    body = raw(name)
    assert re.search(rf"^name: {name}$", body, re.M)
    assert re.search(r"^description: .+", body, re.M)
    assert "## 출력 형식" in body and "## 출처" in body
    assert "3차에서 새로 작성했다" in body


@pytest.mark.parametrize("name", NEW)
def test_no_material_marks(name):
    """`with_skills`의 약속: Skill 안에 원문 구분자를 넣지 않는다."""
    assert "<<<" not in raw(name)


def test_delegation_has_no_band_amounts():
    """구간 금액은 자료 본문에서만 가져온다. Skill에 금액을 박으면 판이 바뀔 때 틀린다."""
    assert not re.search(r"\$\s*\d", raw("delegation"))


def test_delegation_says_boundary_is_project_interpretation():
    assert "프로젝트 해석" in raw("delegation")


@pytest.mark.parametrize("name", ["delegation", "report-writing", "mail-templates", "retrieval-slots"])
def test_rules_name_their_source_section(name):
    assert "근거 절" in raw(name)


def test_chat_tool_guide_offers_only_read_tools():
    body = raw("chat-tool-guide")
    assert "`search_handbook`" in body and "`get_section`" in body
    for word in ("explain_decision", "get_grounding", "get_agent_trace", "approve"):
        assert word not in body


def test_retrieval_slots_does_not_show_gold():
    assert "정답 청크를 보지 않고" in raw("retrieval-slots")
