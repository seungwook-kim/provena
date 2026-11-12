"""근거 판정 LLM을 건너뛰어도 되는 조건 `grounding.values_backed` 시험 (L-10 변이 21번이 이 시험으로 잡힌다). 답의 값이 표시한 청크에 없으면 False여야 한다."""
from backend.graph.grounding import values_backed

CID = "0123456789abcdef"
CITED = [{"chunk_id": CID, "rule_title": "장애 대응", "article": "Paging", "text": "Page must be acknowledged within 15 minutes. Cost is 500 USD."}]


def test_value_present_in_the_marked_chunk_is_backed():
    assert values_backed(f"호출은 15분 안에 확인합니다 [{CID}].", CITED) is True


def test_value_missing_from_the_marked_chunk_is_not_backed():
    assert values_backed(f"호출은 30분 안에 확인합니다 [{CID}].", CITED) is False   # 15분이 아니라 30분
    assert values_backed(f"비용은 900달러입니다 [{CID}].", CITED) is False


def test_sentence_without_mark_or_value_is_left_to_the_llm():
    assert values_backed("호출은 15분 안에 확인합니다.", CITED) is False
    assert values_backed(f"호출을 확인합니다 [{CID}].", CITED) is False
