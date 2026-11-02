"""가짜 검색. 합성 시험 데이터, 실제 핸드북 내용 아님.

가상 절 "TEST-security"(과 "TEST-finance")의 승인 권한 정책·장애 대응 런북·SaaS 도입 정책을 흉내 낸 인메모리 코퍼스다.
섹션 내용과 수치는 모두 지어낸 값이며 실제 GitLab 핸드북이나 어느 조직의 정책과도 무관하다.
진짜 검색 없이 그래프를 시험하도록 같은 시그니처 `fake_search(q) -> list[Chunk]`를 제공한다.

동작:
- org(핸드북 절)가 있으면 그 절만.
- as_of가 있으면 정책(절, rule_seq)마다 판 날짜(커밋 날짜)가 as_of 이하인 판 중 가장 늦은 판만. 없으면 모든 판.
- 점수: 질의어(공백 기준)가 본문·정책명·섹션(제목 경로)에 있으면 +1, 없으면 글자 2개씩 겹침 비율의 절반. 0점은 제외.
"""
from __future__ import annotations

import hashlib
import re

from backend.schemas import Chunk, SearchQuery

ORG = "TEST-security"
ORG_B = "TEST-finance"
FETCHED = "2026-11-02"
_BASE_URL = "https://example.invalid/synthetic/test"

# 정책: (org, rule_seq, 정책명)
_DELEG = (ORG, 90001, "승인 권한 정책")
_INCIDENT = (ORG, 90002, "장애 대응 런북")
_ADOPT = (ORG, 90003, "SaaS 도입 정책")
_DELEG_B = (ORG_B, 91001, "승인 권한 정책")


def _chunk(rule, version_date: str, kind: str, article: str | None, text: str) -> Chunk:
    org, rule_seq, title = rule
    version_id = f"TEST-{rule_seq}-{version_date.replace('-', '')}"
    cid = hashlib.sha256(f"{org}|{rule_seq}|{version_id}|{article}|{text}".encode()).hexdigest()[:16]
    return Chunk(
        chunk_id=cid,
        org=org,
        rule_seq=rule_seq,
        rule_title=title,
        article=article,
        version_id=version_id,
        version_date=version_date,
        fetched_at=FETCHED,
        kind=kind,  # type: ignore[arg-type]
        text=text,
        source_url=f"{_BASE_URL}/{rule_seq}",
    )


def _build_corpus() -> list[Chunk]:
    c: list[Chunk] = []
    # --- 승인 권한 정책: 2024-01-01 판 / 2025-07-01 판 (도입 승인 금액 구간이 다르다) ---
    for date, lo, hi in (("2024-01-01", "1천만원", "1억원"), ("2025-07-01", "5천만원", "2억원")):
        c.append(_chunk(_DELEG, date, "article", "Approval Matrix > Overview", "승인자는 승인 권한표(Approval Matrix > Table 1)에 따라 업무의 종류와 금액에 맞게 정한다. 승인자가 부재하면 대리 승인자가 승인한다."))
        c.append(_chunk(_DELEG, date, "annex", "Approval Matrix > Table 1", f"승인 권한표. 도입 승인: {lo} 미만은 팀 리드, {lo} 이상 {hi} 미만은 디렉터, {hi} 이상은 CTO가 승인한다. 재무와 협조한다."))
        c.append(_chunk(_DELEG, date, "row", "Approval Matrix > Table 1", f"도입 승인 {lo} 미만: 승인자 팀 리드, 협조 부서 없음."))
        c.append(_chunk(_DELEG, date, "row", "Approval Matrix > Table 1", f"도입 승인 {lo} 이상 {hi} 미만: 승인자 디렉터, 협조 부서 재무."))
        c.append(_chunk(_DELEG, date, "row", "Approval Matrix > Table 1", f"도입 승인 {hi} 이상: 승인자 CTO, 협조 부서 재무, IT 운영."))
    # --- 장애 대응 런북: 2023-03-01 판 / 2025-01-01 판 ---
    c.append(_chunk(_INCIDENT, "2023-03-01", "article", "Incident Response > Paging", "SEV2 장애 최초 대응은 30분 이내에 한다."))
    c.append(_chunk(_INCIDENT, "2023-03-01", "article", "Incident Response > Escalation", "SEV2 장애 에스컬레이션은 담당자 호출 후 1시간을 상한으로 당직 관리자에게 한다."))
    c.append(_chunk(_INCIDENT, "2025-01-01", "article", "Incident Response > Paging", "SEV2 장애 최초 대응은 15분 이내에 한다."))
    c.append(_chunk(_INCIDENT, "2025-01-01", "article", "Incident Response > Escalation", "SEV2 장애 에스컬레이션은 담당자 호출 후 2시간을 상한으로 당직 관리자에게 한다."))
    c.append(_chunk(_INCIDENT, "2025-01-01", "article", "Incident Response > Postmortem", "SEV1 장애 대응은 별도의 대응 절차표에 따른다. 사후 분석은 장애 종료 후 5일 이내에 한다."))
    # --- SaaS 도입 정책: 2024-05-01 판 / 2026-03-01 판 ---
    c.append(_chunk(_ADOPT, "2024-05-01", "article", "Adoption Policy > Simplified Adoption", "간이 도입은 추정 비용 2천만원 이하인 경우에 할 수 있다."))
    c.append(_chunk(_ADOPT, "2024-05-01", "article", "Adoption Policy > Review Request", "도입 검토 요청은 검토 회의 7일 전까지 한다."))
    c.append(_chunk(_ADOPT, "2024-05-01", "article", "Adoption Policy > Contingency", "도입 예비비는 도입 금액의 10퍼센트로 한다."))
    c.append(_chunk(_ADOPT, "2026-03-01", "article", "Adoption Policy > Simplified Adoption", "간이 도입은 추정 비용 5천만원 이하인 경우에 할 수 있다."))
    c.append(_chunk(_ADOPT, "2026-03-01", "article", "Adoption Policy > Review Request", "도입 검토 요청은 검토 회의 5일 전까지 한다."))
    c.append(_chunk(_ADOPT, "2026-03-01", "article", "Adoption Policy > Contingency", "도입 예비비는 도입 금액의 10퍼센트로 한다. 소액 도입은 면제할 수 있다."))
    # --- 다른 절: 절 필터 확인용 ---
    c.append(_chunk(_DELEG_B, "2025-01-01", "article", "Approval Matrix > Overview", "승인자는 승인 권한표에 따라 정한다. 도입 승인은 1천만원 미만 매니저, 그 이상은 디렉터가 승인한다."))
    c.append(_chunk(_DELEG_B, "2025-01-01", "annex", "Approval Matrix > Table 1", "승인 권한표. 도입 승인: 1천만원 미만 매니저, 1천만원 이상 디렉터."))
    return c


_CORPUS: list[Chunk] = _build_corpus()


def corpus() -> list[Chunk]:
    """합성 코퍼스 사본(점수 없음)."""
    return [ch.model_copy() for ch in _CORPUS]


def _valid_versions(chunks: list[Chunk], as_of: str) -> set[tuple[str, int, str]]:
    """(org, rule_seq)마다 판 날짜가 as_of 이하인 판 중 가장 늦은 판 -> {(org, rule_seq, version_id)}."""
    best: dict[tuple[str, int], tuple[str, str]] = {}
    for ch in chunks:
        if ch.version_date <= as_of:
            key = (ch.org, ch.rule_seq)
            if key not in best or ch.version_date > best[key][0]:
                best[key] = (ch.version_date, ch.version_id)
    return {(o, s, v) for (o, s), (_, v) in best.items()}


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _score(terms: list[str], ch: Chunk) -> float:
    hay = f"{ch.rule_title} {ch.article or ''} {ch.text}"
    total = 0.0
    for t in terms:
        if t in hay:
            total += 1.0
        else:
            bg = _bigrams(t)
            if bg:
                total += 0.5 * sum(1 for b in bg if b in hay) / len(bg)
    return total


def fake_search(q: SearchQuery) -> list[Chunk]:
    """합성 코퍼스에서 org·as_of로 거르고 키워드 점수 순으로 상위 q.k개를 돌려준다."""
    pool = _CORPUS
    if q.org is not None:
        pool = [ch for ch in pool if ch.org == q.org]
    if q.as_of is not None:
        valid = _valid_versions(pool, q.as_of)
        pool = [ch for ch in pool if (ch.org, ch.rule_seq, ch.version_id) in valid]
    terms = [t for t in re.split(r"\s+", re.sub(r"[?.,!]", " ", q.query)) if t]
    scored = [(s, ch) for ch in pool if (s := _score(terms, ch)) > 0]
    scored.sort(key=lambda x: (-x[0], -int(x[1].version_date.replace("-", "")), x[1].chunk_id))
    return [ch.model_copy() for _, ch in scored[: q.k]]
