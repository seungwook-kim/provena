"""검색: 하이브리드(BM25 + 벡터), 리랭킹, 메타데이터 필터.

바꾸기 전에 evals/PREREGISTER.md에 기대를 먼저 적고, 한 번에 하나만 바꿔 다시 재세요.

인터페이스 권고:
  - 대상 필터(예: 기업이나 문서 종류)는 검색 결과를 받은 뒤 거르지 말고 검색 단계의 인자로 받는다.
    후처리로 거르면 결과가 0~2개로 굶어 "우연한 거절"이 생기고 점수가 실제보다 좋게 나온다.
  - 모델을 쓴다면 warmup()을 두고 서버 기동 때 한 번 부른다(첫 질문이 느려지지 않게).
  - 검색 방식(BM25, 벡터, 하이브리드, 리랭킹)마다 score의 뜻과 범위가 다르다. 거절 임계값은 방식마다 따로 정한다.
"""
# 그래프·demo_record가 `from backend.rag.retrieve import search` 로 계약 함수를 받는다(backend/services/demo_record.py).
# 모듈은 sys.modules["backend.rag.retrieve.search"] 또는 `from backend.rag.retrieve.search import ...` 로 연다.
from backend.rag.retrieve.search import search, warmup  # noqa: E402,F401


def retrieve(question: str, *, k: int = 5) -> list[dict]:
    raise NotImplementedError("TODO: 검색 구현")
