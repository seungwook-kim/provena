"""검색 -> 에이전트 계약 (SDD 6장). 필드 이름과 타입은 SDD 그대로이고 혼자 고치지 않는다."""
from typing import Literal

from pydantic import BaseModel


class Chunk(BaseModel):
    chunk_id: str  # sha256 앞 16자
    org: str  # 핸드북 절 (예: "security", "finance")
    # 페이지 id. 페이지 경로 sha256 앞 8자리 16진수를 정수로 바꾼 값(0..4294967295)이라
    # 부호 있는 32비트(INT)를 넘는다. DB 칸은 BIGINT로 둔다 (SDD 11-1 3-1, docs/specs/collect.md).
    rule_seq: int
    rule_title: str  # 페이지 제목
    article: str | None  # 제목 경로 (예: "Incident Management > Severities")
    version_id: str  # 커밋 기반 판 id (SDD 5장 versions, citations와 같은 값)
    version_date: str  # 이 판(커밋)의 날짜 YYYY-MM-DD
    fetched_at: str  # 수집일 YYYY-MM-DD
    # article(섹션), row(권한표 행) 위주로 쓴다. 나머지 값은 남겨 둔다.
    kind: Literal["article", "annex", "row", "buchik", "pre"]
    text: str
    source_url: str  # 핸드북 페이지 URL
    text_sha256: str | None = None  # 본문 sha256. G3 "서로 다른 청크 수"와 중복 제거에 쓴다 (SDD 11-1 3-6)
    # True면 판 날짜를 정확히 모르고 version_date 이전이라는 뜻(얕은 이력, I-001). 화면은 "YYYY-MM-DD 이전"으로 보인다
    version_date_before: bool = False
    # 원본 페이지 줄 범위(1부터, 끝 포함). 평가셋의 `경로#L523` 정답을 맞추고 출처 링크에 쓴다.
    # Spec에 없던 추가라 조장 승인 대기(docs/specs/search.md 열린 항목 8). 모르면 None
    line_start: int | None = None
    line_end: int | None = None


class SearchQuery(BaseModel):
    query: str
    org: str | None = None  # 절
    as_of: str | None = None  # 이 날짜 기준 핸드북 판(커밋)만
    k: int = 8
