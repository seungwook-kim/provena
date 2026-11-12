"""근거를 비워도 답하는지 회귀 시험 (S-03, 강의 3주 02). 검색이 아무것도 못 찾았는데 모델이 판정에서 "충분"이라 하고
그럴듯한 답을 지어내도(가짜 인용을 붙이거나 인용 없이) 그래프는 거절해야 한다. 단일 그래프와 멀티 그래프 모두. 키 없이 가짜 모델만 쓴다."""
from __future__ import annotations

import pytest
from qgraph_fakes import j, normal_llm

from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.build import build_graph
from backend.graph.multi import build_multi_graph

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
FAKE_ID = "deadbeefdeadbeef"
BUILDERS = {"single": build_graph, "multi": build_multi_graph}

# 모델이 지어낸 답: (이름, 답 작성 출력)
INVENTED = {
    "fake_citation": j(answer=f"SEV2는 15분 이내에 대응합니다 [{FAKE_ID}].", citations=[{"chunk_id": FAKE_ID}]),
    "no_citation": j(answer="SEV2는 15분 이내에 대응합니다.", citations=[]),
    "plain_text": "SEV2는 15분 이내에 대응합니다.",
}


@pytest.mark.parametrize("graph_kind", sorted(BUILDERS))
@pytest.mark.parametrize("invented", sorted(INVENTED))
def test_empty_search_never_becomes_an_answer_even_if_the_judge_says_sufficient(graph_kind, invented):
    llm = normal_llm(judge=j(sufficient=True, reason="", clarify=None), answer=INVENTED[invented])
    store = InMemoryAnswerStore()
    out = BUILDERS[graph_kind](lambda q: [], llm=llm, answer_store=store).invoke(
        {"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert out["kind"] != "answer", out
    assert out.get("citations") in (None, [])
    assert "15분" not in out.get("answer", "")  # 지어낸 값이 사용자에게 나가지 않는다
    assert llm.count("judge") == 0 and llm.count("answer") == 0  # 근거가 없으면 모델에게 판정도 답 작성도 시키지 않는다(판정 단계 안전장치)
    assert store.all_answers() == []  # 리콜이 찾을 답으로 저장되지 않는다
