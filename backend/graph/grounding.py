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


_PUBLIC_GROUNDING = ("llm", "reason", "rejudge", "revised", "redrafted", "partial_route")


def public_grounding(info: dict) -> dict:
    """근거 판정 기록 중 밖으로 낼 수 있는 값만 고른다(MCP `get_grounding`). 초안, 뺀 문장, 판정 이유 문장, 질문에서 뽑은 말은 뺀다."""
    out = {k: info[k] for k in _PUBLIC_GROUNDING if k in info}
    rules = info.get("rules")
    out["rules"] = {k: rules[k] for k in ("cited", "retrieved") if k in rules} if isinstance(rules, dict) else rules
    for key in ("redraft", "revise"):
        if isinstance(info.get(key), dict) and "result" in info[key]:
            out[key] = {"result": info[key]["result"]}
    return out


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


# ---------- 받쳐지지 않는 문장만 빼기 (수정 2) ----------
MAX_REMOVED_SHARE = 0.5  # 빼는 문장이 전체의 이 비율을 넘으면 질문에 답하지 못하는 답으로 보고 전체를 거절한다
_MIN_CLAIM = 6  # 이보다 짧은 목록 항목은 어느 문장인지 믿을 수 없어 일치로 보지 않는다
_MARKS = r"(?:\s*\[[0-9a-f]{16}\])*"
_SENTENCE = re.compile(r".+?[.!?。]" + _MARKS + r"(?=\s|$)|.+$", re.S)
_ANY_MARK = re.compile(r"\[[0-9a-f]{16}\]")


@dataclass
class Pruned:
    ok: bool
    answer: str = ""
    removed: list[str] = field(default_factory=list)
    reason: str = ""  # 실패 사유: no_claims | unmatched | nothing_left | too_many_removed


def same_page_context(cited: list[dict], retrieved: list[dict]) -> list[dict]:
    """인용 청크와 같은 페이지, 같은 판의 검색 청크 중 인용되지 않은 것. 판정 LLM이 규칙의 적용 범위를 확인할 때만 보는 참고이고 값의 근거로 세지 않는다.
    다른 페이지의 청크는 넣지 않는다. 비슷한 주제의 다른 문서가 근거처럼 읽히면 환각을 통과시킬 수 있다."""
    pages = {(c.get("rule_seq"), c.get("version_id")) for c in cited}
    seen = {c["chunk_id"] for c in cited}
    out: list[dict] = []
    for c in retrieved:
        if c["chunk_id"] not in seen and (c.get("rule_seq"), c.get("version_id")) in pages:
            seen.add(c["chunk_id"])
            out.append(c)
    return out


def split_sentences(line: str) -> list[str]:
    """한 줄을 문장으로 나눈다. 문장 끝의 `[chunk_id]` 표시는 그 문장에 붙여 둔다. 소수점(99.74)은 문장 끝으로 보지 않는다."""
    return [m.group(0).strip() for m in _SENTENCE.finditer(line.strip()) if m.group(0).strip()]


def same_text(a: str, b: str) -> bool:
    """공백과 인용 표시를 빼고 같은 글인지. 다시 쓴 답이 그대로면 판정을 다시 하지 않는다."""
    return _flat(a) == _flat(b)


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", _ANY_MARK.sub("", text or ""))


def prune_answer(answer: str, claims: list[str]) -> Pruned:
    """판정이 받쳐지지 않는다고 한 문장(`claims`, 답에서 복사한 것)과 일치하는 문장을 답에서 뺀다. 줄 구분은 유지한다.

    일치: 공백과 표시를 지운 문장이 항목에 들어 있거나 항목이 문장에 들어 있다. 어느 문장과도 맞지 않는 항목이 하나라도 있으면
    무엇이 틀렸는지 알 수 없으므로 실패한다(호출한 쪽이 전체를 거절한다). 남는 문장이 없거나 뺀 문장이 절반을 넘어도 실패한다."""
    wanted = [c for c in (claims or []) if isinstance(c, str) and c.strip()]
    if not wanted:
        return Pruned(False, reason="no_claims")
    lines = [[s for s in split_sentences(ln)] for ln in (answer or "").splitlines() if ln.strip()]
    sentences = [s for ln in lines for s in ln]
    flat = [_flat(s) for s in sentences]
    drop: set[int] = set()
    for claim in wanted:
        c = _flat(claim)
        hit = [i for i, f in enumerate(flat) if len(c) >= _MIN_CLAIM and f and len(f) >= _MIN_CLAIM and (c in f or f in c)]
        if not hit:
            return Pruned(False, reason="unmatched")
        drop.update(hit)
    if len(drop) >= len(sentences):
        return Pruned(False, reason="nothing_left")
    if len(drop) / len(sentences) > MAX_REMOVED_SHARE:
        return Pruned(False, reason="too_many_removed")
    out, n = [], 0
    for ln in lines:
        keep = []
        for s in ln:
            if n not in drop:
                keep.append(s)
            n += 1
        if keep:
            out.append(" ".join(keep))
    return Pruned(True, "\n".join(out), [sentences[i] for i in sorted(drop)])


# ---------- 값이 인용 청크에 있는지 (`GROUND_SKIP_BACKED`) ----------
_KO_COUNT = re.compile(r"(?:[한두세네]|다섯|여섯|일곱|여덟|아홉|열)\s*(?:번|명|개|시간|주|달|개월|차례|회|분|일)|하루|이틀|사흘|나흘|일주일|보름")  # 숫자 없이 쓴 값은 대조할 수 없다
_KO_UNIT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(달러|시간|분|일|주|개월|달|년|%|퍼센트)")
_UNIT_EN = {"시간": r"(?:hours?|hrs?|h)\b", "분": r"(?:minutes?|mins?|m)\b", "일": r"(?:days?|d)\b", "주": r"weeks?\b", "개월": r"months?\b", "달": r"months?\b",
            "년": r"years?\b", "%": r"(?:%|percent)", "퍼센트": r"(?:%|percent)"}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def _plain_number(text: str) -> str:
    return text.replace(",", "")


def _value_in_source(number: str, unit: str, source: str) -> bool:
    """숫자와 단위가 같이 자료에 있는지. 달러는 $나 USD, dollar와 함께 있어야 한다. 표에 없는 단위는 숫자만 본다."""
    num = re.escape(number)
    if unit == "달러":
        return bool(re.search(rf"(?:\$|USD\s*)\s*{num}(?![\d.])|(?<![\d.]){num}\s*(?:USD|dollars?)\b", source, re.I))
    tail = rf"[\s-]*{_UNIT_EN[unit]}" if unit in _UNIT_EN else r"(?![\d.])"
    return bool(re.search(rf"(?<![\d.]){num}{tail}", source, re.I))


def values_backed(answer: str, cited: list[dict]) -> bool:
    """답의 모든 문장이 값(숫자, 영문 용어)을 하나 이상 갖고, 그 값이 그 문장이 표시한 청크에 있으면 True. 근거 판정 LLM을 건너뛸지 정할 때만 쓴다.

    한국어 문장과 영어 원문은 낱말로 대조할 수 없어 값만 본다. 대조할 값이 없는 문장, 표시가 없는 문장, 숫자 없이 쓴 값(이틀, 세 번)이 있으면 False이고 LLM이 판정한다.
    값이 맞아도 주체나 조건이 틀린 문장은 여기서 잡지 못한다."""
    by_id = {c["chunk_id"]: _plain_number(" ".join(str(c.get(k) or "") for k in ("rule_title", "article", "text"))) for c in cited}
    sentences = [s for ln in (answer or "").splitlines() for s in split_sentences(ln)]
    if not sentences:
        return False
    for sentence in sentences:
        marks = _ANY_MARK.findall(sentence)
        source = "\n".join(by_id.get(m[1:-1], "") for m in marks)
        body = _plain_number(_ANY_MARK.sub("", sentence))
        if not source.strip() or _KO_COUNT.search(body):
            return False
        units = _KO_UNIT.findall(body)
        numbers = _NUMBER.findall(body)
        words = _LATIN.findall(body)
        if not numbers and not words:
            return False
        have_words = {w.lower() for w in _LATIN.findall(source)}
        if any(w.lower() not in have_words for w in words):
            return False
        pairs = [*units, *((n, "") for n in numbers if n not in {x for x, _ in units})]
        if not all(_value_in_source(n, u, source) for n, u in pairs):
            return False
    return True


# ---------- "자료에 없다"고 밝힌 문장의 인용 ----------
# 없다는 말은 어느 청크로도 받쳐지지 않는다. 표시가 남으면 그 청크가 인용으로 나간다.
# 원문이 없다고 적은 사실("응답 기한이 없다")은 자료를 주어로 쓰지 않아 걸리지 않는다. 쉼표로 이은 문장은 앞쪽 사실의 표시일 수 있어 두고, 원문 규칙일 수 있는 "확인이 필요"는 자료를 말할 때만 본다
_META_ABSENCE = re.compile(r"자료(?:에는|에서는|에서|에|로는)(?!\s*따르)[^.!?\n]{0,30}?(?:없(?!다고|음을)|찾을 수|확인되지|확인할 수|나와 있지|언급되어 있지)|확인 필요")
_ID_MARK = re.compile(r"\s*\[[0-9a-f]{16}\]")


def unmark_absence(answer: str) -> str:
    """자료에 없다고 밝힌 문장에서 근거 표시만 뺀다. 문장은 그대로 둔다."""

    def fix(m: re.Match) -> str:
        sentence = m.group(0)
        if "," in _ID_MARK.sub("", sentence) or not _META_ABSENCE.search(sentence):
            return sentence
        return _ID_MARK.sub("", sentence)

    return "\n".join(_SENTENCE.sub(fix, line) for line in (answer or "").split("\n"))


def says_only_absence(answer: str) -> bool:
    """답의 모든 문장이 자료에 없다는 말인지."""
    sentences = [s for line in (answer or "").splitlines() for s in split_sentences(line)]
    return bool(sentences) and all(_META_ABSENCE.search(s) for s in sentences)


# ---------- 사실 주장이 아닌 문장(자료에 없다는 말, 판 기준 안내)만 받쳐지지 않는다고 한 판정 ----------
# 근거 판정 LLM은 주장마다 받치는 원문 구절을 찾고 없으면 NOTHING FOUND로 적는다. "자료만으로는 확인되지 않습니다", "공개 판 기준입니다"처럼 값을 말하지 않는
# 문장은 어느 청크에도 구절이 없으므로(위 `unmark_absence`도 같은 이유로 표시를 뺀다) 같은 문장이 어떤 호출에서는 받쳐지지 않는 주장으로 꼽혀 답 전체가 거절됐다(운영 트레이스 2026-11-09).
# 판정이 받쳐지지 않는다고 꼽은 문장이 모두 이런 문장이고 답에 값을 말하는 문장이 남아 있으면 그 판정으로 거절하지 않는다. 값을 말하는 문장의 판정은 그대로다.
_ONLY_MATERIAL_ABSENCE = re.compile(r"자료만으로는?[^.!?\n]{0,40}?(?:없(?!다고|음을)|찾을 수|확인되지|확인할 수|알 수 없)")
_VERSION_NOTE = re.compile(r"(?:공개|과거|고정|현재)\s*판|판\s*\(\d{4}-\d{2}\)|\d{4}-\d{2}\s*판")
_DATE = re.compile(r"\d{4}-\d{2}")


def is_caveat(sentence: str, known: str) -> bool:
    """값을 말하지 않는 단서 문장인지. (a) 자료에 없거나 확인되지 않는다는 말, 또는 (b) 근거 판 기준이라는 안내이고, (c) 문장의 숫자와 영문 용어가
    모두 질문이나 근거(`known`)에 있어야 한다. 값을 새로 들이는 문장은 단서로 보지 않는다."""
    body = _ID_MARK.sub("", sentence or "").strip()
    if not body or not (_META_ABSENCE.search(body) or _ONLY_MATERIAL_ABSENCE.search(body) or _VERSION_NOTE.search(body)):
        return False
    low = known.lower()
    return all(re.search(rf"(?<![0-9A-Za-z_.]){re.escape(t.lower())}(?![0-9A-Za-z_.])", low) for t in [*_NUMBER.findall(_DATE.sub("", body)), *_LATIN.findall(body)])


def only_caveats(answer: str, known: str) -> bool:
    """답의 모든 문장이 단서 문장인지(값을 말하는 문장이 없다)."""
    sentences = [s for line in (answer or "").splitlines() for s in split_sentences(line)]
    return all(is_caveat(s, known) for s in sentences)


def caveat_only_flags(answer: str, claims: list[str], question: str, evidence: list[dict]) -> bool:
    """판정이 받쳐지지 않는다고 꼽은 문장(`claims`)이 있고 모두 단서 문장이며, 답에 값을 말하는 문장이 남아 있으면 True."""
    if not claims:
        return False
    known = f"{question}\n{_evidence_blob(evidence)}"
    sentences = [s for line in (answer or "").splitlines() for s in split_sentences(line)]
    for claim in claims:
        c = _flat(claim)
        hit = [s for s in sentences if len(c) >= _MIN_CLAIM and len(_flat(s)) >= _MIN_CLAIM and (c in _flat(s) or _flat(s) in c)]
        if not hit or not all(is_caveat(s, known) for s in hit):  # 꼽은 문장이 답의 문장과 맞아야 하고, 맞는 답 문장이 모두 단서여야 한다
            return False
    return not only_caveats(answer, known)


# ---------- 요청한 기간의 자료가 없는 답 (수정 3) ----------
# 질문에 연도, 연월, 월이 있어야 적용한다. 공백은 지우고 비교한다("2026년 9월" -> "2026년9월")
_PERIOD_EXPR = re.compile(r"(?:(?:19|20)\d{2}\s*년\s*)?\d{1,2}\s*월|(?:19|20)\d{2}\s*년|(?:19|20)\d{2}-\d{2}(?!\d)|[1-4]\s*분기|\bQ[1-4]\b|\bFY\s?\d{2,4}\b")
_SAME_PERIOD = ("해당기간", "그기간", "해당월", "그달", "해당분기", "그분기")  # 답이 기간을 다시 적지 않고 가리키는 말
_ABSENCE = ("없", "확인 필요", "찾을 수 없", "제공되지")  # 답이 그 기간의 자료가 없다고 밝히는 말


def question_periods(question: str) -> list[str]:
    """질문에 적힌 시점 표현(연월, 연도, 월). 공백을 지운 형태로 돌려준다."""
    return list(dict.fromkeys(re.sub(r"\s+", "", m.group(0)) for m in _PERIOD_EXPR.finditer(question or "")))


def period_missing(question: str, answer: str, period_covered: object) -> str:
    """답이 질문의 기간 자료가 없다고 밝히면 그 근거를, 아니면 ""를 돌려준다. 질문에 시점 표현이 없으면 적용하지 않는다.
    (a) 답 작성이 `period_covered`를 false로 냈다. (b) 답의 한 문장에 질문의 시점 표현과 "없다"류 표현이 함께 있다."""
    periods = question_periods(question)
    if not periods:
        return ""
    if period_covered is False:
        return "period_covered=false"
    for line in (answer or "").splitlines():
        for sentence in split_sentences(line):
            flat = re.sub(r"\s+", "", sentence)
            names = {*periods, *(re.sub(r"^(?:19|20)\d{2}년", "", p) for p in periods), *_SAME_PERIOD}  # "2026년 9월"을 물으면 답의 "9월"도 같은 기간이다
            if any(p and p in flat for p in names) and any(w in sentence for w in _ABSENCE):
                return "answer says the period is missing: " + sentence[:120]
    return ""
