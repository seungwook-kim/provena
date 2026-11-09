"""런타임 Skill 불러오기. 환경변수 USE_SKILLS(기본 켬)로 전부 켜고 끈다(docs/SDD.md 2-3).

끄면 load_skill은 빈 문자열을 돌려준다. 켰을 때와 껐을 때 다른 조건은 같아야 하므로 호출하는 쪽은 빈 문자열이면 Skill 블록을 붙이지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
SKILL_NAMES = (
    "citation-rules", "grounding-check", "glossary",
    "delegation", "report-writing", "chat-tool-guide", "mail-templates", "retrieval-slots",
    "search-terms",  # 재검색어 용어표. `GRAPH_REQUERY_TERMS=1`일 때만 판정에 붙는다(기본 꺼짐)
)
_OFF_VALUES = {"0", "false", "no", "off", "끔"}


def skills_enabled() -> bool:
    """USE_SKILLS가 없거나 비어 있으면 켬. 0, false, no, off면 끔."""
    return os.environ.get("USE_SKILLS", "1").strip().lower() not in _OFF_VALUES


def load_skill(name: str, *, enabled: bool | None = None) -> str:
    """SKILL.md 본문(머리말 제외). 꺼져 있으면 "".

    enabled: None이면 USE_SKILLS를 따르고, True/False면 환경변수를 무시한다(평가 비교용).
    알 수 없는 이름은 ValueError, 파일이 없으면 FileNotFoundError.
    """
    if name not in SKILL_NAMES:
        raise ValueError(f"알 수 없는 Skill: {name!r}")
    if not (skills_enabled() if enabled is None else enabled):
        return ""
    raw = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return raw.strip()
