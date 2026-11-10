"""첫 검색어를 코드로 보강한다. LLM이 규칙을 따르기를 기대하지 않고 정해진 표로 하위 질문을 나눈다. 스위치는 기본 꺼짐이다.

- `GRAPH_QUERY_BRANCHES=1`: 대상에 따라 핸드북 절차가 갈리는 주제(계정, 2FA, 비밀번호 등)인데 질문에 대상이 없으면,
  그 하위 질문을 대상마다 하나씩 나눠 둘 다 검색한다. 답 작성에는 대상 목록을 넘기고, 답이 대상 하나를 빠뜨리면 한 번 다시 쓰게 한다.

표는 문항이나 청크가 아니라 핸드북의 개념에 묶는다. 검색 방식(분해 합치기, 순위 합치기, k)은 그대로다. 하위 질문 수는 검색의 상한(3개)을 넘지 않는다.
검색어 용어 덧붙임(`GRAPH_QUERY_TERMS`)과 제목 경로 추가(`GRAPH_HEADING_*`)는 용어표가 v2 문항 단어에 맞춘 것이라 걷어냈다(결정 0101, 2026-11-10).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

MAX_SUBS = 3  # backend.rag.retrieve.search.MAX_SUB_QUERIES와 같다(검색이 받는 하위 질문 상한)


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def branches_enabled() -> bool:
    return _flag("GRAPH_QUERY_BRANCHES")


@dataclass(frozen=True)
class BranchRule:
    """주제(`topic`)가 맞고 대상 말(`audience`)이 없으면 `targets`마다 하위 질문을 만든다. targets: (답에 쓸 이름, 검색어에 붙일 말, 답에서 찾을 말)."""
    name: str
    topic: str
    audience: str
    targets: tuple[tuple[str, str, str], ...]

    def hits(self, text: str) -> bool:
        return bool(re.search(self.topic, text, re.I)) and not re.search(self.audience, text, re.I)


# GitLab 핸드북은 계정 문제를 사내 팀원(IT 지원)과 GitLab.com 사용자(고객 지원)로 나눠 다룬다
BRANCH_RULES: tuple[BranchRule, ...] = (
    BranchRule("계정 대상", r"계정|2FA|이중\s*인증|2단계\s*인증|OTP|비밀번호|패스워드|로그인|잠[겼김금]",
               r"팀원|직원|사내|임직원|구성원|고객|사용자|유저|회원|team\s*member|customer|user",
               (("GitLab 팀원", "대상: GitLab 팀원", r"팀원|team\s*member|임직원|사내"),
                ("GitLab.com 사용자(고객)", "대상: GitLab.com 사용자, 고객", r"고객|customer|GitLab\.com"))),
)


def branch_rule(text: str) -> BranchRule | None:
    return next((r for r in BRANCH_RULES if r.hits(text)), None)


@dataclass(frozen=True)
class Plan:
    query: str
    subs: list[str]
    targets: list[str]  # 답이 다뤄야 할 대상 이름(나누지 않았으면 빈 목록)


def plan_first_search(question: str, query: str, subs: list[str], *, branches: bool) -> Plan:
    """첫 검색의 (검색어, 하위 질문, 대상). 스위치가 꺼져 있으면 받은 값 그대로다.
    question: 사용자 원 질문(대상 말을 찾는다). query: 검색에 넘길 전체 질문. subs: 분해가 낸 하위 질문(나누지 않았으면 빈 목록)."""
    subs = list(subs)
    targets: list[str] = []
    if branches:
        rule = branch_rule(question)
        if rule is not None:
            base = subs or [query]
            i = next((k for k, s in enumerate(base) if re.search(rule.topic, s, re.I)), None)
            if i is not None and len(base) - 1 + len(rule.targets) <= MAX_SUBS:
                split = [f"{base[i]} ({add})" for _, add, _ in rule.targets]
                subs = [*base[:i], *split, *base[i + 1:]]
                targets = [label for label, _, _ in rule.targets]
    return Plan(query, subs, targets)


def missing_targets(answer: str, targets: list[str]) -> list[str]:
    """답이 다루지 않은 대상 이름. 대상마다 정한 말이 답에 없으면 빠졌다고 본다."""
    if not targets:
        return []
    found = {label: pat for rule in BRANCH_RULES for label, _, pat in rule.targets}
    return [t for t in targets if t in found and not re.search(found[t], answer or "", re.I)]


def targets_note(targets: list[str], missing: list[str] | None = None) -> str:
    """답 작성 입력 끝에 붙이는 안내. 코드가 고른 대상 이름만 담는다."""
    if not targets:
        return ""
    note = (f"\n이 질문은 대상에 따라 절차가 갈린다: {', '.join(targets)}. 질문이 대상을 정하지 않았으므로 자료에 있는 대상마다 따로 한 문장 이상 쓰고, "
            "각 문장에 그 대상의 근거를 인용한다. 대상을 하나만 골라 답하지 않는다.")
    if missing:
        note += f"\n앞 답은 다음 대상을 빠뜨렸다: {', '.join(missing)}. 자료에 그 대상의 내용이 있으면 반드시 넣는다."
    return note
