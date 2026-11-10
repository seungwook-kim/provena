"""첫 검색어를 코드로 보강한다. LLM이 규칙을 따르기를 기대하지 않고 정해진 표로 검색어를 바꾼다. 두 스위치 모두 기본 꺼짐이다.

- `GRAPH_QUERY_TERMS=1`: 질문 말이 표의 조건을 모두 채우면 그 하위 질문 끝에 핸드북 영어 용어를 괄호로 붙인다.
  한국어 질문을 번역하면 핸드북이 쓰지 않는 말(예: "도입" -> adopt)이 되어 다른 팀의 문서로 끌리는 일을 막는다.
- `GRAPH_QUERY_BRANCHES=1`: 대상에 따라 핸드북 절차가 갈리는 주제(계정, 2FA, 비밀번호 등)인데 질문에 대상이 없으면,
  그 하위 질문을 대상마다 하나씩 나눠 둘 다 검색한다. 답 작성에는 대상 목록을 넘기고, 답이 대상 하나를 빠뜨리면 한 번 다시 쓰게 한다.

표는 문항이나 청크가 아니라 핸드북의 개념에 묶는다. 검색 방식(분해 합치기, 순위 합치기, k)은 그대로다. 하위 질문 수는 검색의 상한(3개)을 넘지 않는다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

MAX_SUBS = 3  # backend.rag.retrieve.search.MAX_SUB_QUERIES와 같다(검색이 받는 하위 질문 상한)


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def terms_enabled() -> bool:
    return _flag("GRAPH_QUERY_TERMS")


def branches_enabled() -> bool:
    return _flag("GRAPH_QUERY_BRANCHES")


@dataclass(frozen=True)
class TermRow:
    """`all_of`의 정규식이 모두 맞으면 `terms`를 붙인다. `none_of`가 하나라도 맞으면 붙이지 않는다."""
    name: str
    all_of: tuple[str, ...]
    terms: str
    none_of: tuple[str, ...] = ()
    heads: tuple[str, ...] = ()  # 제목 경로 검색(H, `GRAPH_HEADING_HEADS`)에만 쓰는 핸드북 절 이름 구. 검색어에는 붙이지 않는다

    def hits(self, text: str) -> bool:
        return all(re.search(p, text, re.I) for p in self.all_of) and not any(re.search(p, text, re.I) for p in self.none_of)


# 핸드북 용어표. 한국어 말이 번역되면 핸드북 용어와 멀어지는 개념만 둔다.
# 지금은 비어 있다: 구매·새 도구 도입 행과 업체 보안 검토 행은 v2 문항의 말에 맞춘 것이라 뺐다(사전 등록 62.34).
# 금액으로 승인자를 묻는 질문에 구매 절차 용어가 붙어 승인 권한표의 금액 구간 행이 검색에서 밀렸다. 표가 비면 덧붙임과 제목 경로 추가(H, HT)는 아무것도 하지 않는다
TERM_ROWS: tuple[TermRow, ...] = ()
# heads: 핸드북이 그 개념의 절 제목에 쓰는 구. 검색어 벡터는 바꾸지 않는다


def heading_heads(texts: list[str]) -> list[str]:
    """H 확장: 첫 검색어·하위 질문 중 하나라도 맞는 표 줄의 `heads`(소문자, 표 순서, 중복 없음)."""
    out: list[str] = []
    for r in TERM_ROWS:
        if any(r.hits(t or "") for t in texts):
            out += [h.strip().lower() for h in r.heads if h.strip().lower() not in out]
    return out
# 넣지 않은 행: "2FA 초기화 -> 2FA removal, account recovery"는 영어 검색 점검에서 셀프 복구 안내로 끌려 대상별 절차 청크를 밀어냈다(2026-11-06)


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


def add_terms(text: str) -> str:
    """맞는 행의 용어를 괄호로 붙인다. 그 행의 용어가 이미 모두 들어 있으면 붙이지 않는다."""
    low = text.lower()
    extra = [r.terms for r in TERM_ROWS if r.hits(text) and not all(t.strip().lower() in low for t in r.terms.split(","))]
    return f"{text} ({'; '.join(extra)})" if extra else text


def branch_rule(text: str) -> BranchRule | None:
    return next((r for r in BRANCH_RULES if r.hits(text)), None)


@dataclass(frozen=True)
class Plan:
    query: str
    subs: list[str]
    targets: list[str]  # 답이 다뤄야 할 대상 이름(나누지 않았으면 빈 목록)


def plan_first_search(question: str, query: str, subs: list[str], *, terms: bool, branches: bool) -> Plan:
    """첫 검색의 (검색어, 하위 질문, 대상). 스위치가 둘 다 꺼져 있으면 받은 값 그대로다.
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
    if terms:
        subs = [add_terms(s) for s in subs]
        if not subs:
            query = add_terms(query)
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
