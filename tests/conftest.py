"""시험 공통 설정. 질문 분해(SEARCH_DECOMPOSE)는 코드 기본이 켬이라, 분해와 상관없는 그래프 시험은 끈 채로 돌린다.
분해를 시험하는 쪽은 인자(`build_graph(decompose=True)`)나 `monkeypatch.setenv`로 직접 정한다."""
import pytest


@pytest.fixture(autouse=True)
def _decompose_off_unless_asked(monkeypatch):
    monkeypatch.setenv("SEARCH_DECOMPOSE", "0")
