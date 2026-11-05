"""결정표 규칙 (D-06, docs/specs/decision-approval.md). 이 파일에는 LLM이 없다.

- 권한표 칸(`parse_authz()` 출력, `data/parsed/authz_cells.jsonl`) -> 규칙(`DecisionRule` 모양 dict)
- 초안 규칙과 원문 칸을 칸 단위로 맞대는 셀 대조표 (AC-03, EC-06)
- 금액으로 규칙을 실행해 승인 순서를 얻는 코드 (AC-02, AC-04, EC-03, EC-10)

금액 구간 해석(EC-03). 권한표 원문에는 경계 규칙이 적혀 있지 않다. 아래는 사용자가 확정한 이 프로젝트의 해석이며 원문의 규칙이 아니다.
- 구간 이름이 `>`나 `Over`로 시작하거나 `>`를 담으면 아래 끝은 초과다. 그 밖에는 이상이다.
- 위 끝은 `to`, `up to` 모두 이하다.
- 이 해석으로 두 구간에 함께 드는 금액은 추측하지 않고 `AmbiguousBand`(422)로 거절한다. 2023 권한표에서는 `Approving expense`의
  $500,000과 $1,000,000, `Bad debt write off`의 $10,000과 $100,000 네 금액이다.
- 위 끝이 비어 있는 구간에 시작이 더 큰 구간이 뒤따르면(`>$5K`와 `>$50K`) 뒤 구간의 시작을 위 끝으로 본다(I-004 결정). 응답의 `range_note`로 이 해석을 알린다.
- 금액 칸이 없는 구간이 하나라도 있는 업무(`Legal Contracts` 등)는 금액으로 구간을 고르지 않고 구간 이름(`band`)을 받는다.

표기: 사용자에게 보이는 금액은 `band_label()`의 정확한 금액으로 쓴다(`$500K` 같은 약어를 쓰지 않는다). 원문 표기는 실행 결과의 `source` 안에 그대로 둔다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from backend.schemas import DecisionRule

# 권한표 열 순서 = 아래 단계에서 위 단계로, 업무 승인 다음 재무 승인. 승인 순서는 이 순서를 따른다.
ROLE_ORDER = (
    "Manager", "Director", "Sr Director", "VP", "Exec Group", "CEO", "Board", "Director of legal",
    "PAO or VP Finance", "CFO", "CLO",
)
_APPROVE = re.compile(r"approve", re.I)

APPROVER, FINANCIAL, COOPERATING, NONE = "approver", "financial", "cooperating", "none"


class DecisionError(Exception):
    """결정표 실행·승인 오류. `status`는 API가 그대로 쓸 수 있는 HTTP 코드 후보(P-01, 사용자가 확정)."""

    status = 400
    reason = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BadRequest(DecisionError):
    status, reason = 400, "bad_request"


class NotFound(DecisionError):
    status, reason = 404, "not_found"


class Conflict(DecisionError):
    """지금 상태에서는 받을 수 없는 요청이다."""

    status, reason = 409, "conflict"


class AlreadyDecided(Conflict):
    """이미 끝난 승인 건에 다른 결정을 보냈다."""

    status, reason = 409, "already_decided"


class NotApproved(DecisionError):
    """초안·반려·승인 대기 결정표를 실행하려 했다 (EC-01, AC-01). 규칙은 실행되지 않았다."""

    status, reason = 409, "not_approved"


class AmbiguousTable(DecisionError):
    """업무 종류로 승인된 표가 0개거나 2개 이상 (EC-04, AC-06)."""

    status, reason = 409, "ambiguous_table"


class AmbiguousBand(DecisionError):
    """금액이 두 구간에 함께 들어 구간이 하나로 정해지지 않는다 (EC-03)."""

    status, reason = 422, "ambiguous_band"


def norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def order_roles(roles: list[str]) -> list[str]:
    """승인 순서: 권한표 열 순서. 목록에 없는 역할은 뒤에 원래 순서로. 중복은 뺀다."""
    seen = list(dict.fromkeys(roles))
    rank = {r.casefold(): i for i, r in enumerate(ROLE_ORDER)}
    return sorted(seen, key=lambda r: rank.get(r.casefold(), len(ROLE_ORDER)))


def cell_kind(approval_type: str, value: str | None) -> str:
    """원문 칸 한 개가 결정표에서 맡는 자리. 'Approve'가 들어 있으면 승인자(업무·재무), 다른 표시(Signs, Recommends, Advised, X)는 협조, 빈 칸은 없음."""
    v = (value or "").strip()
    if not v:
        return NONE
    if _APPROVE.search(v):
        return FINANCIAL if approval_type == "financial" else APPROVER
    return COOPERATING


@dataclass(frozen=True)
class Bounds:
    lo: float | None
    hi: float | None
    lo_inclusive: bool
    hi_inclusive: bool = True

    @property
    def has_amount(self) -> bool:
        return self.lo is not None or self.hi is not None

    def contains(self, amount: float) -> bool:
        if self.lo is not None and not (amount >= self.lo if self.lo_inclusive else amount > self.lo):
            return False
        if self.hi is not None and not (amount <= self.hi if self.hi_inclusive else amount < self.hi):
            return False
        return True


def band_bounds(rule: dict) -> Bounds:
    """구간 이름과 파서가 채운 끝값으로 만든 구간. 시작이 더 큰 구간과의 관계는 `effective_bounds()`가 본다."""
    label = str(rule.get("band") or "").strip().lower()
    exclusive = ">" in label or re.match(r"over\b", label) is not None
    return Bounds(rule.get("band_lo"), rule.get("band_hi"), lo_inclusive=not exclusive)


def effective_bounds(rule: dict, rules: list[dict]) -> Bounds:
    """실제로 적용하는 구간. 위 끝이 빈 구간은 시작이 더 큰 다음 구간의 시작을 위 끝으로 본다(I-004 결정)."""
    own = band_bounds(rule)
    if own.lo is None or own.hi is not None:
        return own
    later = [b for b in map(band_bounds, rules) if b.lo is not None and b.lo > own.lo]
    if not later:
        return own
    nxt = min(later, key=lambda b: b.lo)
    return Bounds(own.lo, nxt.lo, own.lo_inclusive, hi_inclusive=not nxt.lo_inclusive)


# --- 정확한 금액 표기 ---------------------------------------------------------------------------

_MONEY = r"\$\s*\d[\d,]*(?:\.\d+)?\s*[km]?\b"
_MONEY_TOKEN = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([km]?)\b", re.I)
_AMOUNT_ONLY = re.compile(rf"(?:\s|>|over\b|up to\b|to\b|and above\b|plus\b|{_MONEY})+", re.I)
_UNIT = {"": 1, "k": 1_000, "m": 1_000_000}


def usd(amount: float) -> str:
    """약어 없는 달러 표기. `usd(500000)` -> `$500,000`."""
    return f"${int(amount):,}" if float(amount).is_integer() else f"${amount:,}"


def _expand_money(text: str) -> str:
    """글 안의 약어 금액만 정확한 금액으로 바꾼다. `> $500k annual revenue` -> `> $500,000 annual revenue`."""
    return _MONEY_TOKEN.sub(lambda m: usd(float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()]), text)


def band_label(rule: dict, rules: list[dict] | None = None) -> str:
    """사용자에게 보이는 구간 표기. 금액 구간은 끝값으로 쓰고, 금액 없는 구간은 원문 이름 그대로, 금액을 담은 이름은 금액만 풀어 쓴다.
    `rules`를 주면 `effective_bounds()`로 적용 구간을 쓴다."""
    name = str(rule.get("band") or "")
    if not band_bounds(rule).has_amount:
        return name
    if not _AMOUNT_ONLY.fullmatch(name.strip()):
        return _expand_money(name)
    b = effective_bounds(rule, rules) if rules is not None else band_bounds(rule)
    parts = []
    if b.lo is not None and (b.lo != 0 or not b.lo_inclusive or b.hi is None):      # `Up to $5K`의 "$0 이상"은 쓰지 않는다
        parts.append(f"{usd(b.lo)} {'이상' if b.lo_inclusive else '초과'}")
    if b.hi is not None:
        parts.append(f"{usd(b.hi)} {'이하' if b.hi_inclusive else '미만'}")
    return " ".join(parts)


def _band_key(rule_or_label: dict | str) -> str:
    return norm(rule_or_label["band"] if isinstance(rule_or_label, dict) else rule_or_label)


# --- 원문 칸 -> 규칙 -------------------------------------------------------------------------

def rules_from_cells(cells: list[dict]) -> list[dict]:
    """원문 칸에서 코드로 만든 기준 규칙(LLM 없음). 초안과 맞댈 때의 정답 쪽이고, 시험과 평가에도 쓴다."""
    by_band: dict[str, dict] = {}
    for c in cells:
        key = _band_key(c["band"])
        r = by_band.setdefault(key, {
            "category": c["category"], "band": c["band"], "band_lo": _int(c.get("band_lo")), "band_hi": _int(c.get("band_hi")),
            "approvers": [], "financial_approvers": [], "cooperating_depts": [], "range_note": None,
        })
        kind = cell_kind(c["approval_type"], c.get("value"))
        slot = {APPROVER: "approvers", FINANCIAL: "financial_approvers", COOPERATING: "cooperating_depts"}.get(kind)
        if slot:
            r[slot].append(c["role"])
    out = []
    for r in by_band.values():
        for slot in ("approvers", "financial_approvers", "cooperating_depts"):
            r[slot] = order_roles(r[slot])
        out.append(DecisionRule(**r).model_dump())
    return out


def _int(v: Any) -> int | None:
    return None if v is None else int(v)


def normalize_draft(obj: dict | None, source_cells: list[dict]) -> list[dict]:
    """LLM 초안(JSON 객체)을 `DecisionRule` 모양 목록으로 바꾼다. 금액 끝과 업무 종류는 LLM이 아니라 원문 칸에서 채운다.
    형식이 어긋나면 `BadRequest`. 승인 순서도 코드가 정한다(`order_roles`)."""
    rows = (obj or {}).get("rules")
    if not isinstance(rows, list) or not rows:
        raise BadRequest("초안에 rules 목록이 없다")
    category = source_cells[0]["category"] if source_cells else ""
    src = {_band_key(c["band"]): c for c in source_cells}
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("band"), str) or not row["band"].strip():
            raise BadRequest("초안 규칙에 band가 없다")
        if _band_key(row["band"]) in seen:   # 대조표는 구간마다 한 줄만 맞대므로 중복을 받으면 틀린 줄이 대조에서 빠진다
            raise BadRequest("초안에 같은 구간이 두 번 나온다")
        seen.add(_band_key(row["band"]))
        lists = {}
        for slot in ("approvers", "financial_approvers", "cooperating_depts"):
            v = row.get(slot, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise BadRequest(f"초안의 {slot}가 문자열 목록이 아니다")
            lists[slot] = order_roles([x.strip() for x in v if x.strip()])
        known = src.get(_band_key(row["band"]))
        out.append(DecisionRule(
            category=category, band=known["band"] if known else row["band"].strip(),
            band_lo=_int(known.get("band_lo")) if known else None, band_hi=_int(known.get("band_hi")) if known else None,
            range_note=None if known else "원문에 없는 구간(초안이 만듦)", **lists,
        ).model_dump())
    return out


# --- 셀 대조표 -------------------------------------------------------------------------------

def _draft_kind(rule: dict | None, role: str) -> str:
    if rule is None:
        return NONE
    hits = [k for k, slot in ((APPROVER, "approvers"), (FINANCIAL, "financial_approvers"), (COOPERATING, "cooperating_depts"))
            if role.casefold() in {x.casefold() for x in rule.get(slot, [])}]
    return NONE if not hits else hits[0] if len(hits) == 1 else "multiple"


def compare_cells(source_cells: list[dict], draft_rules: list[dict]) -> dict:
    """초안과 원문을 칸 단위로 맞댄다 (AC-03). 행마다 원문 값·원문 줄 번호·초안이 둔 자리·원문 기준 자리·일치 여부.
    원문에서 비어 있고 초안도 비운 칸은 싣지 않는다(칸 수는 `source_cells`로 따로 센다). 불일치는 `mismatch_count`와 행의 `match`로 드러난다."""
    drafts = {_band_key(r): r for r in draft_rules}
    source_rules = rules_from_cells(source_cells) if source_cells else []
    labels = {_band_key(r): band_label(r, source_rules) for r in source_rules}
    rows, seen = [], set()
    for c in source_cells:
        key = _band_key(c["band"])
        seen.add(key)
        expected = cell_kind(c["approval_type"], c.get("value"))
        got = _draft_kind(drafts.get(key), c["role"])
        if expected == NONE and got == NONE:
            continue
        rows.append({"category": c["category"], "band": c["band"], "band_label": labels[key], "role": c["role"], "approval_type": c["approval_type"],
                     "source_value": c.get("value") or "", "source_line": c.get("line"),
                     "expected": expected, "draft": got, "match": expected == got})
    source_roles = {(_band_key(c["band"]), c["role"].casefold()) for c in source_cells}
    for key, r in drafts.items():
        for slot, kind in (("approvers", APPROVER), ("financial_approvers", FINANCIAL), ("cooperating_depts", COOPERATING)):
            for role in r.get(slot, []):
                if (key, role.casefold()) not in source_roles:   # 원문에 없는 구간이나 역할을 초안이 만들었다
                    rows.append({"category": r["category"], "band": r["band"], "band_label": labels.get(key, band_label(r)), "role": role, "approval_type": None,
                                 "source_value": "", "source_line": None, "expected": NONE, "draft": kind, "match": False})
    return {"rows": rows, "source_cells": len(source_cells), "mismatch_count": sum(1 for r in rows if not r["match"]),
            "extra_bands": sorted(r["band"] for k, r in drafts.items() if k not in seen)}


def has_mismatch(comparison: dict) -> bool:
    """초안이 원문과 다른 칸이 있거나 원문에 없는 구간을 만들었는가. 있으면 승인에 comment가 필수다."""
    return bool(comparison.get("mismatch_count") or comparison.get("extra_bands"))


# --- 실행 ------------------------------------------------------------------------------------

def check_amount(amount: Any) -> float:
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise BadRequest("amount_usd는 유한한 숫자여야 한다")
    try:
        value = float(amount)
    except OverflowError:
        raise BadRequest("amount_usd는 유한한 숫자여야 한다") from None
    if not math.isfinite(value):
        raise BadRequest("amount_usd는 유한한 숫자여야 한다")
    if value < 0:
        raise BadRequest("amount_usd는 음수일 수 없다")
    return value


def _find_band(rules: list[dict], band: str) -> dict:
    """구간 이름으로 찾는다. 원문 이름과 `band_label()` 표기를 모두 받는다."""
    want = norm(band)
    for r in rules:
        if want in (_band_key(r), norm(band_label(r, rules))):
            return r
    raise NotFound("지정한 구간이 표에 없다")  # 입력 표기를 되풀이하지 않는다: 이 문장은 채팅 답 본문에도 들어간다


def select_rule(rules: list[dict], amount_usd: Any = None, band: str | None = None) -> dict:
    """금액 또는 구간 이름으로 규칙 한 개를 고른다. 해석은 모듈 설명을 따른다.
    금액 구간표에서는 `band`를 주어도 금액으로 고른다. 겹치는 금액을 `band`로 골라 낮은 승인 단계를 받을 수 없게 하려는 것이다."""
    if not rules:
        raise NotFound("결정표에 규칙이 없다")
    amount = None if amount_usd is None else check_amount(amount_usd)
    named = _find_band(rules, band) if band else None
    if not all(band_bounds(r).has_amount for r in rules):        # 금액 칸이 없는 구간이 있는 업무: 구간 이름으로 고른다
        if named is None:
            if len(rules) == 1:
                return rules[0]
            raise BadRequest("금액으로 구간을 고를 수 없는 업무라 band(구간 이름)가 필요하다: "
                             + " / ".join(band_label(r, rules) for r in rules))
        if band_bounds(named).has_amount:
            if amount is None:
                raise BadRequest(f"구간 '{band_label(named, rules)}'에는 amount_usd가 필요하다")
            if not band_bounds(named).contains(amount):
                raise NotFound(f"금액 {usd(amount)}이 구간 '{band_label(named, rules)}'에 들지 않는다")
        return named
    if amount is None:
        raise BadRequest("amount_usd는 유한한 숫자여야 한다")
    hits = [r for r in rules if effective_bounds(r, rules).contains(amount)]
    if not hits:
        raise NotFound(f"금액 {usd(amount)}이 속하는 구간이 표에 없다")
    if len(hits) > 1:
        raise AmbiguousBand(f"금액 {usd(amount)}은 두 구간에 함께 들어 구간을 정할 수 없다: "
                            + " / ".join(band_label(r, rules) for r in hits))
    if named is not None and named is not hits[0]:
        raise NotFound(f"금액 {usd(amount)}이 구간 '{band_label(named, rules)}'에 들지 않는다")
    return hits[0]


def _range_note(rule: dict, rules: list[dict]) -> str | None:
    if rule.get("range_note"):
        return rule["range_note"]
    own, applied = band_bounds(rule), effective_bounds(rule, rules)
    if own.hi is None and applied.hi is not None:
        return f"원문 구간의 위 끝이 비어 있어 다음 구간의 시작({usd(applied.hi)})을 끝으로 봤다."
    return None


def run_rules(rules: list[dict], amount_usd: Any = None, band: str | None = None) -> dict:
    """규칙 목록을 금액으로 실행해 승인 순서를 돌려준다. LLM도 외부 호출도 없다."""
    r = select_rule(rules, amount_usd, band)
    functional, financial = order_roles(r.get("approvers", [])), order_roles(r.get("financial_approvers", []))
    return {
        "approvers": functional + financial,          # 업무 승인 다음 재무 승인 (AC-02). 각각 아래 단계 먼저
        "functional_approvers": functional,
        "financial_approvers": financial,
        "cooperating": order_roles(r.get("cooperating_depts", [])),
        "band_label": band_label(r, rules),
        "range_note": _range_note(r, rules),
        "source": {"category": r["category"], "band": r["band"], "article": f"{r['category']} / {r['band']}"},   # 원문 표기 그대로
    }
