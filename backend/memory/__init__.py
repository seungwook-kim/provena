"""사용자별 장기 기억 (G4).

namespace에 사용자 id를 넣어 사용자 사이에 기억이 섞이지 않게 합니다.
기억 기준·정정 절차·State/Store 경계는 `docs/specs/memory.md`에 있다.

프로필(소속·직급)은 `profile.py`가 `(user_id, "profile")` namespace에 따로 둡니다.
"""
from backend.memory.profile import delete_profile, get_profile, profile_namespace, put_profile

__all__ = ["delete_profile", "get_profile", "namespace", "profile_namespace", "put_profile"]


def namespace(user_id: str) -> tuple[str, ...]:
    return (user_id, "memories")
