"""요청 문서(`새 지표 정답 세트 작성 요청 (2026-11-16).md`)의 배정 표를 그대로 옮긴 값. 정답 행에는 커밋·섹션 칸이 없으므로 번호 범위로 찾는다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecallGroup:
    first: int          # R 번호 시작
    last: int           # R 번호 끝(포함)
    commit: str         # 앞 8자
    commit_full: str
    date: str           # 요청 문서에 적힌 커밋 날짜
    page: str           # data/corpus/handbook/ 다음 경로(커밋 당시 경로)
    section: str        # 요청 문서의 "바뀐 섹션"(제목 경로)
    author: str


def _g(first, last, full, date, page, section, author):
    return RecallGroup(first, last, full[:8], full, date, page, section, author)


RECALL_GROUPS: tuple[RecallGroup, ...] = (
    _g(1, 3, "0c787db174bfb47af8de56ee58f25d969e80936e", "2024-01-23", "security/security-assurance/security-risk/third-party-risk-management.md",
       "Third Party Minimum Security Standards > TPRM Risk Acceptance Process", "박진형"),
    _g(4, 6, "e29aad9a9f1ffb1670ee9f0c468b4ac8672d223f", "2024-01-23", "security/security-assurance/security-risk/storm-program/_index.md",
       "StORM Procedures > Risk Response > Accept the Risk", "박진형"),
    _g(7, 9, "1ca85649a175c2cb74129fab135f4f3a2cc860fe", "2024-10-18", "finance/accounts-payable/corp-credit-cards.md",
       "7. Exceptions to the Policy", "박진형"),
    _g(10, 12, "6baed99c59a8020e1367015c2431255cf5c323be", "2025-09-19", "engineering/infrastructure-platforms/incident-review.md",
       "Timeline that we expect for reviews to be completed", "박진형"),
    _g(13, 15, "219f7084d5312cf065b905a5416cdb9c3167b9bd", "2026-01-15", "engineering/releases/monthly-releases/index.md",
       "Frequently Asked Questions > When do I need to have my MR merged in order for it to be included in the monthly release?", "박진형"),
    _g(16, 18, "bf53a6914ae32969037ecd2fbd1b0c4b2980e335", "2026-01-26", "engineering/infrastructure-platforms/incident-management/on-call/_index.md",
       "How to set up an on-call rotation > Defining escalation paths", "박진형"),
    _g(19, 21, "642fb34161e5775418e2a91fca4e242ca1b87c89", "2026-01-29", "security/security-assurance/security-risk/third-party-risk-management.md",
       "Third Party Minimum Security Standards > TPRM Approval Windows", "강경희"),
    _g(22, 24, "37eecbf430b4aabe8007bcb8ce5dc37fceb5dece", "2026-05-22", "engineering/releases/_index.md",
       "Release Policy > Exception Process", "강경희"),
    _g(25, 27, "fc6633cf93268172dad58545d692cf54e1690993", "2026-06-23", "engineering/infrastructure-platforms/incident-management/on-call/tier-2.md",
       "Active Tier 2 rotations > EOC Technical Escalation", "강경희"),
    _g(28, 30, "ddd395971ee181bee9e00d23d34e1001489d76ef", "2026-07-14", "finance/expenses.md",
       "3. General Guidelines", "강경희"),
    _g(31, 33, "ddd395971ee181bee9e00d23d34e1001489d76ef", "2026-07-14", "finance/expenses.md",
       "Approved Office Supplies List > VPN Subscription", "강경희"),
    _g(34, 36, "5d615813da0a66e430e237029bfd5836a8d2b81a", "2026-07-31", "engineering/infrastructure-platforms/incident-management/_index.md",
       "Severities > Incident Severity", "강경희"),
)

EXCLUDED_COMMITS = ("4667e540",)   # AC-01·데모 사례, 작성 예시로만 쓴다


def recall_group(rid: str) -> RecallGroup:
    n = int(rid[1:])
    for g in RECALL_GROUPS:
        if g.first <= n <= g.last:
            return g
    raise KeyError(rid)


# 결정표: 원문 `data/corpus/authz/authorization-matrix-2023-05.html.md` 업무 종류별 줄 범위(요청 문서 2-1)
AUTHZ_RANGE = (61, 481)
DECISION_CATEGORIES: tuple[tuple[str, int, int, str], ...] = (
    ("Approving expense", 76, 160, "강경희"),
    ("Approving Payment", 161, 185, "박진형"),
    ("Legal Contracts", 186, 258, "강경희"),
    ("Bad debt write off", 259, 295, "박진형"),
    ("Compensation/Hiring - non-executive", 296, 404, "박진형"),
    ("Benefit changes", 405, 417, "박진형"),
    ("Employee Travel & Entertainment > Non Billable Expenses", 418, 455, "강경희"),
    ("Transfer of funds among GitLab entities", 456, 480, "박진형"),
)
# 권한표 칸 순서(표 머리 65~75줄). 앞 8개 업무 승인, 뒤 3개 재무 승인
ROLES = ("Manager", "Director", "Sr Director", "VP", "Exec Group", "CEO", "Board", "Director of legal", "PAO or VP Finance", "CFO", "CLO")
FINANCIAL_ROLES = ("PAO or VP Finance", "CFO", "CLO")


def category_for_line(line: int) -> str | None:
    for name, lo, hi, _ in DECISION_CATEGORIES:
        if lo <= line <= hi:
            return name
    return None


def parser_category(name: str) -> str:
    """요청 문서의 업무 종류 이름 -> 파서(`authz_cells.jsonl`) 이름. 하위 제목이 붙은 것은 마지막 부분이다."""
    return name.split(" > ")[-1].strip()


# 링크 추출: 맡은 페이지(요청 문서 3-1)
LINK_PAGES: dict[str, tuple[str, ...]] = {
    "박진형": ("finance/accounts-payable/_index.md", "security/policies_and_standards/password-standard.md", "engineering/releases/backports.md"),
    "강경희": ("engineering/infrastructure-platforms/incident-management/roles/incident-lead.md",
            "security/security-and-technology-policies/change-management-policy.md", "finance/growth-and-development/_index.md"),
}
LINK_SPECIAL = ("코퍼스 밖", "자기 페이지", "비공개")

# 함께 볼 정책 후보: 맡은 개정(요청 문서 4-1)
MAINTENANCE_REVISIONS: dict[str, dict] = {
    "박진형": {"ids": (1, 30), "commit": "219f7084", "page": "engineering/releases/monthly-releases/index.md", "slug": "monthly-releases"},
    "강경희": {"ids": (31, 60), "commit": "ddd39597", "page": "finance/expenses.md", "slug": "expenses"},
}


def maintenance_revision(mid: str) -> dict:
    n = int(mid[1:])
    for author, r in MAINTENANCE_REVISIONS.items():
        if r["ids"][0] <= n <= r["ids"][1]:
            return {**r, "author": author}
    raise KeyError(mid)
