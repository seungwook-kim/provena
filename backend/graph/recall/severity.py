"""개정 전후 본문의 변경 종류·중요도·확신도를 정하는 키워드 규칙(코드, LLM 없음). 알림 피로 줄이기(F-08).

- 중요도(severity): 금액·비율, 기한(기간), 건수·숫자 기준, 승인자(직책), 권한(허용/금지/필수)이 바뀌면 `high`, 그런 신호가 없고 문구만 바뀌면 `low`.
  섹션이 새로 생기거나 사라진 경우는 `high`, 개정 전후 본문을 못 찾았을 때도 `high`(보수적).
- 변경 패턴(pattern): 바뀐 종류를 이름순으로 `+`로 이은 문자열(`amount`, `approver+permission`, `wording` ...). 피드백 집계의 키다.
- 확신도(confidence, 결정적 경로): 이 답이 인용한 값이 바뀐 값과 닿아 있으면 0.9, 질문·답에 바뀐 종류의 값이 아예 없으면 0.45,
  숫자 기준이 질문·답의 값과 범위가 안 닿으면 0.3, 문구만 바뀌었으면 0.3.
  LLM 판정에는 이 규칙이 확신도를 만들지 않고, "문구만 바뀜"일 때만 상한(0.45)을 건다(`cap_for_wording`).
규칙은 휴리스틱이다: 숫자 표기를 못 읽거나(영문 서수, 'SEV2'처럼 문자에 붙은 숫자) 직책 목록에 없는 말은 신호로 못 잡아 `low`로 나올 수 있다.
그래도 알림이 사라지는 것이 아니라 관리자 검토함으로 간다(`RECALL_MIN_CONFIDENCE`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HIGH_KINDS = frozenset({"amount", "deadline", "threshold", "approver", "permission", "section_added", "section_removed", "unknown"})
WORDING_CAP = 0.45  # LLM이 바뀜이라 했어도 규칙이 문구만 바뀐 것으로 보면 확신도를 이 값 이하로 누른다(기본 하한 0.5 아래)
CONF_RELEVANT, CONF_NO_MENTION, CONF_OUTSIDE, CONF_WORDING = 0.9, 0.45, 0.3, 0.3

_MUL = {"천만": 10_000_000, "백만": 1_000_000, "십만": 100_000, "억": 100_000_000, "만": 10_000, "천": 1_000, "백": 100}
_DUR = {"초": 1 / 60, "분": 1, "시간": 60, "영업일": 1440, "일": 1440, "주": 10080, "개월": 43200, "달": 43200, "년": 525600,
        "min": 1, "mins": 1, "minute": 1, "minutes": 1, "hour": 60, "hours": 60, "hr": 60, "hrs": 60, "day": 1440, "days": 1440,
        "week": 10080, "weeks": 10080, "month": 43200, "months": 43200, "year": 525600, "years": 525600}
_MONEY = {"원", "달러", "usd", "krw", "won", "dollar", "dollars"}
_PCT = {"%", "퍼센트", "percent"}
_COUNT = {"명", "건", "회", "배"}
_UNIT = "|".join(sorted([*_DUR, *_MONEY, *_PCT, *_COUNT], key=len, reverse=True))
_NUM = re.compile(
    rf"(?<![A-Za-z0-9_.])(\$)?(\d[\d,]*(?:\.\d+)?)\s*(천만|백만|십만|억|만|천|백)?\s*(business\s+days?|{_UNIT})?(?![A-Za-z])",
    re.IGNORECASE,
)

_ROLES = (
    "승인자", "결재자", "승인권자", "팀장", "부서장", "본부장", "센터장", "실장", "임원", "이사", "대표", "담당자", "책임자", "관리자", "검토자",
    "심의위원회", "위원회", "보안팀", "인프라팀", "법무팀", "재무팀", "ciso", "cto", "cfo", "ceo", "cio", "approver", "manager", "director",
    "reviewer", "owner", "administrator", "admin", "committee", "officer", "vp",
)
_ROLE_RE = re.compile("|".join(sorted((re.escape(r) for r in _ROLES), key=len, reverse=True)), re.IGNORECASE)

_PERMISSION = (
    "할 수 있", "할 수 없", "수 있", "수 없", "불가", "금지", "허용", "허가", "가능", "필수", "의무", "면제", "예외", "제외", "반드시", "해야",
    "하여야", "해서는 안", "안 된다", "않아도", "must", "may not", "shall", "required", "allowed", "prohibited", "forbidden", "exempt",
    "optional", "not permitted", "permitted",
)
_PERM_QUESTION = re.compile(r"할 수|수 있|수 없|되나요|됩니까|가능|해도|허용|금지|필수|\bcan\b|\bmay\b|allowed", re.IGNORECASE)
_APPROVE_Q = re.compile(r"승인|결재|누가|누구|approv|\bwho\b", re.IGNORECASE)


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass(frozen=True)
class Signals:
    numbers: frozenset  # {(분류, 값)}: money(원) / percent / duration(분) / count / plain
    roles: frozenset
    permission: frozenset


def signals(text: str) -> Signals:
    nums: set[tuple[str, float]] = set()
    for m in _NUM.finditer(text or ""):
        dollar, raw, mul, unit = m.group(1), m.group(2), m.group(3), (m.group(4) or "").lower()
        unit = re.sub(r"\s+", " ", unit)
        end = m.end()
        if not unit and not mul and not dollar and text[end:end + 1] == "." and (text[end + 1:end + 2] in ("", " ", "\n")):
            continue  # "1. 개요" 같은 목록 번호
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if mul:
            val *= _MUL[mul]
        if dollar or unit in _MONEY or (mul and not unit):
            nums.add(("money", val))
        elif unit in _PCT:
            nums.add(("percent", val))
        elif unit.startswith("business"):
            nums.add(("duration", val * 1440))
        elif unit in _DUR:
            nums.add(("duration", val * _DUR[unit]))
        elif unit in _COUNT:
            nums.add(("count", val))
        else:
            nums.add(("plain", val))
    low = (text or "").lower()
    roles = frozenset(m.group(0).lower() for m in _ROLE_RE.finditer(text or ""))
    perms = frozenset(p for p in _PERMISSION if p in low)
    return Signals(frozenset(nums), roles, perms)


_NUM_KIND = {"money": "amount", "percent": "amount", "duration": "deadline", "count": "threshold", "plain": "threshold"}


@dataclass(frozen=True)
class ChangeAnalysis:
    kinds: tuple[str, ...]
    numeric: dict = field(default_factory=dict)  # 분류 -> (개정 전 값 집합, 개정 후 값 집합)  (바뀐 값만)
    roles: tuple[str, ...] = ()  # 바뀐 직책
    identical: bool = False

    @property
    def severity(self) -> str:
        return "high" if HIGH_KINDS & set(self.kinds) else "low"

    @property
    def pattern(self) -> str:
        return "none" if self.identical else ("+".join(sorted(self.kinds)) or "wording")

    @property
    def wording_only(self) -> bool:
        return not self.identical and not self.kinds


def analyze_change(old: str, new: str) -> ChangeAnalysis:
    """개정 전·후 본문을 키워드 규칙으로 비교한다."""
    o, n = _ws(old), _ws(new)
    if not o and not n:
        return ChangeAnalysis(kinds=("unknown",))
    if o == n:
        return ChangeAnalysis(kinds=(), identical=True)
    if not n:
        return ChangeAnalysis(kinds=("section_removed",))
    if not o:
        return ChangeAnalysis(kinds=("section_added",))
    so, sn = signals(o), signals(n)
    kinds: set[str] = set()
    numeric: dict = {}
    for cls in {c for c, _ in (so.numbers ^ sn.numbers)}:
        ov = {v for c, v in so.numbers if c == cls}
        nv = {v for c, v in sn.numbers if c == cls}
        if ov != nv:
            numeric[cls] = (ov - nv, nv - ov)
            kinds.add(_NUM_KIND[cls])
    changed_roles = tuple(sorted(so.roles ^ sn.roles))
    if changed_roles:
        kinds.add("approver")
    if so.permission != sn.permission:
        kinds.add("permission")
    return ChangeAnalysis(kinds=tuple(sorted(kinds)), numeric=numeric, roles=changed_roles)


def relevance(question: str, answer: str, a: ChangeAnalysis) -> tuple[float, str]:
    """이 답(질문+답 문장)이 바뀐 값과 닿아 있는가. (확신도, 이유 코드). 결정적 경로의 확신도로 쓴다."""
    if a.identical:
        return 0.95, "identical"
    if a.wording_only:
        return CONF_WORDING, "wording_only"
    if set(a.kinds) & {"section_added", "section_removed", "unknown"}:
        return CONF_RELEVANT, "structure"
    qa = f"{question}\n{answer}"
    sig = signals(qa)
    best, why = 0.0, "no_mention"
    for cls, (ov, nv) in a.numeric.items():
        mentioned = {v for c, v in sig.numbers if c == cls}
        vals = ov | nv
        if not mentioned:
            score, code = CONF_NO_MENTION, "no_mention"
        elif not ov or not nv or mentioned & vals or any(min(vals) <= v <= max(vals) for v in mentioned):
            score, code = CONF_RELEVANT, "value_in_range"
        else:
            score, code = CONF_OUTSIDE, "outside_range"
        if score > best:
            best, why = score, code
    if "approver" in a.kinds:
        hit = any(r in sig.roles or r in qa.lower() for r in a.roles) or bool(_APPROVE_Q.search(qa))
        score, code = (CONF_RELEVANT, "role_mentioned") if hit else (CONF_NO_MENTION, "no_mention")
        if score > best:
            best, why = score, code
    if "permission" in a.kinds:
        hit = bool(sig.permission) or bool(_PERM_QUESTION.search(question))
        score, code = (CONF_RELEVANT, "permission_mentioned") if hit else (CONF_NO_MENTION, "no_mention")
        if score > best:
            best, why = score, code
    return (best, why) if best else (CONF_NO_MENTION, "no_mention")


def cap_for_wording(confidence: float | None, a: ChangeAnalysis) -> float | None:
    """판정 모델이 준 확신도에 규칙의 교차 확인을 건다: 규칙이 '문구만 바뀜'으로 보면 상한을 둔다. 확신도가 없으면 그대로 None."""
    if confidence is None or not a.wording_only:
        return confidence
    return min(confidence, WORDING_CAP)


def parse_confidence(value: object) -> float | None:
    """판정 응답의 confidence를 0~1 숫자로. 없거나 숫자가 아니면 None(걸러내지 않음). 범위 밖은 0~1로 자른다."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return max(0.0, min(1.0, v))
