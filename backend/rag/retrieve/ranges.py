"""금액 구간 조회: 질문에 든 금액이 속한 구간 행(예: ">$25K up to $50K")을 코드로 찾는다.

왜 필요한가: 벡터 검색은 "$30,000"이 ">$25K up to $50K" 구간에 든다는 것을 알지 못한다. 구간 행은 본문이 제목과 역할 줄뿐이라
구간 일곱 개의 벡터가 서로 거의 같고, 질문의 금액과 글자가 겹치는 구간(예: "$50,000"과 "$50K")만 우연히 상위에 든다(EVAL_REPORT 5장).
이 파일은 모델이나 LLM을 쓰지 않는 순수 함수만 둔다. 검색 쪽(`search.py`의 `Searcher._range_expand`)이 부른다.

- `amounts_in(texts)`: 질문들(한국어 원문, 영어 번역)에서 달러 금액을 뽑는다. `$30,000`, `$30K`, `$1.5M`, `30,000 dollars`, `USD 30K`,
  `3만 달러`, `3만 5천 달러`, `10만 달러`. 통화 표시(`$`, 달러, USD, dollars)가 없는 숫자(15분, SEV2)는 금액이 아니다.
- `parse_band(heading_last)`: 제목 경로의 마지막 단계가 금액 구간 하나뿐일 때 `Band`로 바꾼다. 구간 표기 6가지는 아래 `_PATTERNS`.
  구간 말이 없는 금액(예: "$500k annual revenue")과 문장 속 금액은 구간이 아니다.
- `covering(headings, amounts)`: 제목 경로 목록에서 금액이 든 구간 행을, 표(제목 경로에서 구간 단계를 뺀 앞부분)와 금액마다 가장 좁은 구간 하나씩 고른다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

INF = float("inf")
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_SUFFIX = r"(?:thousand|million|billion|[KMBkmb])(?![A-Za-z])"

# 영어: $30,000 · $30K · $1.5M · USD 30,000 · 30,000 dollars · 30K USD
_EN = [
    re.compile(rf"\$\s?(?P<n>{_NUM})\s?(?P<s>{_SUFFIX})?", re.I),
    re.compile(rf"\bUSD\s?(?P<n>{_NUM})\s?(?P<s>{_SUFFIX})?", re.I),
    re.compile(rf"(?<![\w$.,])(?P<n>{_NUM})\s?(?P<s>{_SUFFIX})?\s?(?:USD|dollars?)\b", re.I),
]
# 한국어: 3만 달러 · 3만 5천 달러 · 10만 달러 · 5천 달러 · 50,000달러 · 1.5억 달러
_KO_UNIT = r"(?:억|만|천|백)"
_KO_N = rf"(?:{_NUM})(?!\d)"          # 숫자 덩어리를 쪼개 되돌아가지 않게 한다(긴 숫자 열에서 느려지지 않는다)
_KO = re.compile(rf"(?P<n>(?:{_KO_N}\s*{_KO_UNIT}?\s*|{_KO_UNIT}\s*)+)\s*(?:달러|USD|\$)")
_KO_TOKEN = re.compile(rf"(?:(?P<num>{_KO_N})\s*(?P<unit>{_KO_UNIT})?|(?P<only>{_KO_UNIT}))")
_KO_MULT = {"억": 1e8, "만": 1e4, "천": 1e3, "백": 1e2}


def _ko_value(span: str) -> float:
    """'3만 5천' -> 35000, '2천만' -> 20000000, '50,000' -> 50000."""
    total = seg = 0.0
    for m in _KO_TOKEN.finditer(span):
        if m.group("only"):                              # 앞 묶음에 만·억을 곱한다(2천만)
            total += (seg or 1.0) * _KO_MULT[m.group("only")]
            seg = 0.0
            continue
        n, unit = float(m.group("num").replace(",", "")), m.group("unit")
        if unit in ("천", "백"):
            seg += n * _KO_MULT[unit]
        elif unit in ("만", "억"):
            total += (seg + n) * _KO_MULT[unit]
            seg = 0.0
        else:
            seg += n
    return total + seg


def amounts_in(texts: list[str | None]) -> list[float]:
    """질문 글들에서 달러 금액(중복 없음, 처음 나온 순서). 0과 음수는 뺀다."""
    out: list[float] = []

    def add(v: float) -> None:
        if v > 0 and v not in out:
            out.append(v)

    for text in texts:
        if not text:
            continue
        for rx in _EN:
            for m in rx.finditer(text):
                scale = _SCALE.get((m.group("s") or "").lower(), 1.0)
                add(float(m.group("n").replace(",", "")) * scale)
        for m in _KO.finditer(text):
            add(_ko_value(m.group("n")))
    return out


@dataclass(frozen=True)
class Band:
    lo: float
    hi: float
    lo_open: bool = False        # ">$25K"처럼 아래 끝을 넣지 않으면 True

    def covers(self, x: float) -> bool:
        return (x > self.lo if self.lo_open else x >= self.lo) and x <= self.hi

    @property
    def width(self) -> float:
        return self.hi - self.lo


def _money(num: str, scale: str | None) -> float:
    return float(num.replace(",", "")) * _SCALE.get((scale or "").lower(), 1.0)


def _amount(n: str, s: str) -> str:
    return rf"\$\s?(?P<{n}>{_NUM})\s?(?P<{s}>{_SUFFIX})?"


_A1, _A2 = _amount("n1", "s1"), _amount("n2", "s2")
_PATTERNS = (
    # (정규식, 만드는 법). 모두 전체 일치. 아래 끝은 '>'가 있을 때만 열린다.
    (re.compile(rf"(?P<gt>>)?\s*{_A1}\s*(?:up\s+to|to|-|–|~)\s*{_A2}", re.I), "between"),       # >$25K up to $50K · $500K to $1M
    (re.compile(rf"(?:up\s+to|under|below|less\s+than|<=?)\s*{_A1}", re.I), "upto"),            # Up to $10K
    (re.compile(rf"(?:>|>=|over|above|more\s+than|greater\s+than)\s*{_A1}(?:\s+(?:and\s+above|and\s+over|plus|\+))?", re.I), "over"),  # >$5M · Over $500K · >$500K and above
    (re.compile(rf"{_A1}\s*(?:\+|plus|and\s+above|and\s+over)", re.I), "atleast"),              # $100K plus
)


def parse_band(heading_last: str | None) -> Band | None:
    """제목 경로 마지막 단계 하나가 금액 구간이면 Band. 아니면 None."""
    text = re.sub(r"\s+", " ", (heading_last or "").replace("&gt;", ">").replace("&lt;", "<")).strip()
    if not text or "$" not in text:
        return None
    for rx, kind in _PATTERNS:
        m = rx.fullmatch(text)
        if not m:
            continue
        lo = _money(m.group("n1"), m.group("s1"))
        if kind == "between":
            hi = _money(m.group("n2"), m.group("s2"))
            return Band(lo, hi, bool(m.group("gt"))) if hi > lo else None
        if kind == "upto":
            return Band(0.0, lo)
        if kind == "over":
            return Band(lo, INF, True)
        return Band(lo, INF)
    return None


def covering(headings: list[tuple[object, str]], amounts: list[float]) -> list[tuple[object, tuple[str, ...]]]:
    """headings: (키, 제목 경로 'A > B > C') 목록. 금액이 든 구간 행을 (표, 금액)마다 가장 좁은 구간 하나씩 돌려준다.
    표 = 제목 경로에서 마지막(구간) 단계를 뺀 앞부분. 같은 너비면 먼저 나온 행. 돌려주는 값: [(키, 표)] (입력 순서)."""
    best: dict[tuple, tuple[tuple[float, float, int], object]] = {}
    for i, (key, article) in enumerate(headings):
        parts = tuple(p.strip() for p in (article or "").split(" > ") if p.strip())
        band = parse_band(parts[-1]) if parts else None
        if band is None:
            continue
        table = parts[:-1]
        for x in amounts:
            if band.covers(x):
                rank = (band.width, -band.lo, i)       # 좁은 구간 먼저, 끝이 열린 구간끼리는 아래 끝이 큰 쪽(더 구체적), 그래도 같으면 먼저 나온 행
                cur = best.get((table, x))
                if cur is None or rank < cur[0]:
                    best[(table, x)] = (rank, key)
    seen: dict[object, tuple[str, ...]] = {}
    for (table, _x), (rank, key) in sorted(best.items(), key=lambda kv: kv[1][0][2]):
        seen.setdefault(key, table)
    return list(seen.items())
