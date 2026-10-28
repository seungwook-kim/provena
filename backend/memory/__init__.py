"""사용자별 장기 기억 (G4).

namespace에 사용자 id를 넣어 사용자 사이에 기억이 섞이지 않게 합니다.
정할 것: 무엇을 기억하고 무엇을 기억하지 않을지 기준, 틀린 기억을 고치는 절차, DB 기반 Store.
"""


def namespace(user_id: str) -> tuple[str, ...]:
    return ("memories", user_id)
