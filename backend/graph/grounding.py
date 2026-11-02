"""답 단계 근거 판정의 코드 규칙 (`skills/grounding-check`의 결정적 부분, LLM 없음).

인용 검사를 통과한 답에 대해 "검색된 근거가 질문이 묻는 대상과 시점을 실제로 다루는가"를 본다.
검색 점수 하나로 거르지 않는다(docs/specs/question-graph.md EC-05). 키가 없는 데모 모드에서도 돈다.

규칙(앞에서부터, 처음 걸린 것으로 거절):
1. no_evidence        : 인용으로 남은 청크가 없다.
2. out_of_period      : 질문이 말한 연도가 근거의 가장 이른 판 연도보다 앞서거나, 오늘과 수집일보다 미래다.
3. nonexistent_entity : 질문에 있는 등급·코드(S0, SEV9, P5 등)나 대문자 용어가 검색된 어느 청크에도 없다.

모든 입력은 데이터다. 청크 본문은 문자열 비교에만 쓰고 지시로 읽지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

NO_EVIDENCE = "no_evidence"
OUT_OF_PERIOD = "out_of_period"
NONEXISTENT_ENTITY = "nonexistent_entity"
UNSUPPORTED = "unsupported"  # LLM 판정만 낸다
REASONS = (NO_EVIDENCE, OUT_OF_PERIOD, NONEXISTENT_ENTITY, UNSUPPORTED)

_YEAR_KO = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*년")
_YEAR_ISO = re.compile(r"(?<!\d)((?:19|20)\d{2})[-./]\d{1,2}(?:[-./]\d{1,2})?(?!\d)")
_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4})-?(\d{1,2})(?![A-Za-z0-9])")  # 질문 쪽은 공백 없이 붙은 것만("CTO 5천만원"을 코드로 읽지 않으려는 것)
_CAPS_WORD = re.compile(r"(?<![A-Za-z])[A-Z]{4,}(?![A-Za-z])")
_EV_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,8})[\s-]?(\d{1,3})(?![A-Za-z0-9])")
_EV_WORD = re.compile(r"[A-Za-z]+")
_NOT_CODES = {"Q", "H", "FY", "V", "W"}  # 분기·반기·회계연도·버전처럼 등급이 아닌 표기
_NOT_WORDS = {"TEST"}  # 합성 시험 데이터 표지
_HISTORY_WORDS = ("개정", "변경", "바뀌", "바꾸", "이전", "예전", "전에는", "당시", "기준으로")  # 과거 판을 묻는 질문(리콜·시점 비교)


@dataclass
class Verdict:
    ok: bool
    reason: str = ""  # REASONS 중 하나(통과면 "")
    detail: str = ""
    checks: dict = field(default_factory=dict)


def question_years(question: str) -> list[int]:
    return sorted({int(m) for rx in (_YEAR_KO, _YEAR_ISO) for m in rx.findall(question or "")})


def _norm_code(letters: str, digits: str) -> str:
    return f"{letters.upper()}{int(digits)}"


def _code_aliases(code: str) -> set[str]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", code)
    letters, digits = (m.group(1), m.group(2)) if m else (code, "")
    out = {code}
    if letters == "SEV":
        out.add(f"S{digits}")
    elif letters == "S":
        out.add(f"SEV{digits}")
    return out


def _evidence_blob(chunks: list[dict]) -> str:
    return "\n".join(
        " ".join(str(c.get(k) or "") for k in ("org", "rule_title", "article", "text")) for c in chunks
    )


def check_rules(
    question: str,
    cited: list[dict],
    retrieved: list[dict],
    *,
    today: date | None = None,
) -> Verdict:
    """코드 규칙으로 근거를 판정한다. cited = 인용 검사를 통과한 청크, retrieved = 검색된 청크 전체(없으면 cited)."""
    pool = retrieved or cited
    checks: dict = {"cited": len(cited), "retrieved": len(pool)}
    if not cited:
        return Verdict(False, NO_EVIDENCE, "인용으로 남은 근거가 없습니다", checks)

    # 2. 기간
    years = question_years(question)
    if years:
        ev_years = [int(str(c.get("version_date") or "0000")[:4]) for c in cited if c.get("version_date")]
        fetched = [int(str(c.get("fetched_at") or "0000")[:4]) for c in pool if c.get("fetched_at")]
        first = min(ev_years) if ev_years else None
        last = max([(today or date.today()).year, *fetched])
        checks["question_years"] = years
        checks["evidence_first_year"] = first
        blob_years = _evidence_blob(pool)
        history = any(w in question for w in _HISTORY_WORDS)
        for y in years:
            # 판 날짜는 고정 커밋 날짜라 대부분 같은 해다. 연도가 근거 본문에 나오거나 개정 이력을 묻는 질문은 기간 밖으로 보지 않는다
            if str(y) in blob_years or (history and y <= last):
                continue
            if first is not None and y < first:
                return Verdict(False, OUT_OF_PERIOD, f"질문의 시점 {y}년은 근거의 가장 이른 판({first}년)보다 앞섭니다", checks)
            if y > last:
                return Verdict(False, OUT_OF_PERIOD, f"질문의 시점 {y}년은 수집된 자료의 기간({last}년까지) 밖입니다", checks)

    # 3. 없는 대상
    blob = _evidence_blob(pool)
    have_codes = {_norm_code(a, b) for a, b in _EV_CODE.findall(blob)}
    have_words = {w.upper() for w in _EV_WORD.findall(blob)}
    missing: list[str] = []
    for a, b in _CODE.findall(question or ""):
        if a in _NOT_CODES:
            continue
        code = _norm_code(a, b)
        if not (_code_aliases(code) & have_codes) and code not in missing:
            missing.append(code)
    for w in _CAPS_WORD.findall(question or ""):
        if w not in _NOT_WORDS and w not in have_words and w not in missing:
            missing.append(w)
    checks["missing_terms"] = missing
    if missing:
        return Verdict(False, NONEXISTENT_ENTITY, "질문에 있는 " + ", ".join(missing) + "이(가) 검색된 근거 어디에도 없습니다", checks)

    return Verdict(True, "", "", checks)
