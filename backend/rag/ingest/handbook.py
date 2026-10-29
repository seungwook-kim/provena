"""핸드북 git 수집: 고른 절만, 고정 커밋으로.

Spec: docs/specs/collect.md. 원문은 바꾸지 않고 그대로 쓴다(파싱은 parse.py).
"""
from __future__ import annotations

import hashlib
import re

HANDBOOK_REPO = "https://gitlab.com/gitlab-com/content-sites/handbook.git"
PINNED_COMMIT = "129243bcffcf6cbc8c2e83f537f1836b99900a61"   # 2026-10-27, PRD 8장
SHALLOW_SINCE = "2023-12-01"   # 개정 이력(history.py)이 2024-01-01부터라 그보다 앞까지 받는다
EXPECTED_PAGES = 1564          # 조장 실측, 경로 조장 확인 2026-10-28
SITE = "https://handbook.gitlab.com/"
USER_AGENT = "proj3-c-provena-collector (aihuman-7th class project)"

# 절(Chunk.org) → content/handbook/ 아래 폴더. engineering/ 바로 밑 낱장(incident-management.md 등)은 넣지 않는다.
SECTIONS: dict[str, tuple[str, ...]] = {
    "infra": ("engineering/infrastructure-platforms",),
    "devops": ("engineering/devops", "engineering/deployments-and-releases", "engineering/releases",
               "engineering/error-budgets", "engineering/monitoring"),
    "workflow": ("engineering/workflow", "engineering/testing", "engineering/ai"),
    "development": ("engineering/development",),
    "data-engineering": ("engineering/data-engineering",),
    "security": ("security",),
    "business-technology": ("business-technology",),
    "support": ("support",),
    "enterprise-data": ("enterprise-data",),
    "tools-and-tips": ("tools-and-tips",),
    "finance": ("finance",),
}


class CollectError(RuntimeError):
    """수집 결과를 믿을 수 없을 때. 조용히 넘어가지 않고 멈춘다."""


def all_folders() -> list[str]:
    return [f"content/handbook/{f}" for folders in SECTIONS.values() for f in folders]


def org_of(path: str) -> str:
    for org, folders in SECTIONS.items():
        if any(path.startswith(f"content/handbook/{f}/") for f in folders):
            return org
    raise CollectError(f"고른 절에 속하지 않는 경로: {path}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def page_url(path: str) -> str:
    """content/handbook/a/b/_index.md → https://handbook.gitlab.com/handbook/a/b/ (사이트는 소문자 경로만 열린다)."""
    rel = path.removeprefix("content/").removesuffix(".md")
    rel = rel.removesuffix("/_index").removesuffix("/index")
    return f"{SITE}{rel.lower()}/"


def rule_seq(path: str) -> int:
    """페이지 id: 경로 해시라 판이 바뀌어도 같은 페이지는 같은 값(SDD 11-1 3-1 추천안, D0 확정 전 잠정)."""
    return int(sha256(path.encode())[:15], 16)


def front_matter(text: str) -> dict[str, str]:
    """맨 앞 --- 사이에서 title, redirect_to만 읽는다. 키 대소문자는 섞여 있다(Title: 4쪽)."""
    if not text.startswith("---"):
        return {}
    block = text.split("---", 2)[1]
    found = {}
    for key in ("title", "redirect_to"):
        m = re.search(rf"^{key}:\s*(.+)$", block, re.M | re.I)
        if m:
            found[key] = m.group(1).strip().strip("\"'")
    return found


def corpus_id(file_hashes: list[str]) -> str:
    """문서별 원본 지문을 정렬해 해시한다(받는 순서와 무관)."""
    return sha256("\n".join(sorted(file_hashes)).encode())


def check_pages(pages: dict[str, bytes], expected: int) -> dict[str, int]:
    by_org = {org: 0 for org in SECTIONS}
    for path in pages:
        by_org[org_of(path)] += 1
    if len(pages) != expected:
        raise CollectError(f"쪽수 {len(pages)} ≠ 기대 {expected}. 절별: {by_org}")
    empty_orgs = [org for org, n in by_org.items() if n == 0]
    if empty_orgs:
        raise CollectError(f"0쪽인 절: {empty_orgs}")
    empty = [p for p, b in pages.items() if not b.strip()]
    if empty:
        raise CollectError(f"빈 파일 {len(empty)}개: {empty[:5]}")
    return by_org
