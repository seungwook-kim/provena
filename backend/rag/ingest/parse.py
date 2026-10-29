"""파싱: 수집한 원문(data/corpus/)을 요소 단위 중간 표현과 권한표 칸 목록으로 바꾼다.

Spec: docs/specs/parse.md. 원문은 읽기만 하고 결과는 data/parsed/ 에 쓴다(저장소에 커밋하지 않음).
"""
from __future__ import annotations

import collections
import re

# ── Hugo 단축코드 분류 (원문 45종 전수 조사, 2026-10-29) ──
WRAP = {"alert", "details", "panel", "note", "tableau"}            # 표시만 지우고 안 글자 유지
NAME = {"member-by-name", "member-by-gitlab", "member-and-role-by-gitlab", "label"}   # 인자 글자로
LINK = {"ref"}                                                      # 링크 주소 자리 → 경로
DATA = {                                                            # 사이트가 다른 데이터로 채움 → 지우고 개수 기록
    "team-by-manager-slug", "team-by-manager-role", "team-by-departments", "group-by-slugs",
    "manager-by-report-name", "include", "include-readme", "include-remote", "youtube",
    "performance-indicators", "product/jtbd", "product/section-group-table", "devops-diagram",
    "release-schedule", "release-managers", "a", "all-data-warehouse-sources", "group-pages-by-category",
    "security/public-policy-standards-toc", "support/runbooks",
    "engineering/stable-counterparts", "engineering/test-execution-allure-link",
    "engineering/design-document-header", "engineering/workflow-labels", "engineering/create-retrospectives",
    "engineering/create/career-development", "engineering/verify-team-communication",
    "engineering/design-documents-list", "engineering/service-maturity-scores",
    "engineering/service-maturity-details", "engineering/support-glossary",
    "engineering/section-counterparts", "engineering/stages-counterparts", "engineering/support-skill-areas",
}
SHORTCODE = re.compile(r"\{\{([<%])\s*(/\*)?\s*(/)?\s*([\w/.-]+)(.*?)\s*[%>]\}\}")
QUOTED = re.compile(r'"([^"]*)"')
EMOJI = re.compile(r"(?<![\w/:]):[a-z][a-z0-9_+-]*:(?![\w/:])")   # 앞뒤가 글자면 이모지가 아님(cpe:/o:redhat:…)
FRONT_MATTER = re.compile(r"\A---\n.*?\n---[ \t]*\n", re.S)


# ── 전처리: 줄 수를 바꾸지 않는다(요소의 줄 번호 = 원본 줄 번호) ──
def preprocess(raw: str, counts: collections.Counter, unknown: set) -> str:
    text = FRONT_MATTER.sub(lambda m: "\n" * m.group(0).count("\n"), raw)

    def replace(m: re.Match) -> str:
        escaped, closing, name, args = m.group(2), m.group(3), m.group(4), m.group(5)
        if escaped:                       # {{</* x */>}} 는 Hugo도 글자 그대로 보여 준다
            counts["escaped"] += 1
            return m.group(0).replace("/*", "").replace("*/", "")
        if name in WRAP:
            counts["wrap"] += 1
            if closing:
                return ""
            title = re.search(r'(?:summary|header)="([^"]*)"', args)   # details 요약·panel 제목은 화면에 보이는 글자
            return title.group(1).replace("**", "") if title else ""
        if name in NAME:
            counts["name"] += 1
            named = re.search(r'name="([^"]*)"', args)
            return named.group(1) if named else ", ".join(QUOTED.findall(args))
        if name in LINK:
            counts["link"] += 1
            return (QUOTED.findall(args) or [""])[0]
        if name in DATA:
            counts["data"] += 1
            counts[f"data:{name}"] += 1
            return ""
        unknown.add(name)
        return m.group(0)                  # 모르는 것은 지우지 않는다 → 검토 대기

    return SHORTCODE.sub(replace, text)
