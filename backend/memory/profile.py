"""사용자 프로필(소속·직급·담당 서비스) 장기 기억 헬퍼. LangGraph Store 기반.

State와 Store의 경계 (SDD 5장, 가이드 p.10):
- State = 한 번의 대화(thread) 안에서만 쓰는 값. 질문, 검색 결과, 재검색 횟수, 초안 답 등. thread가 끝나면 체크포인트와 함께 사라져도 된다.
- Store = 다음 대화에도 써야 하는 값. 여기서는 답에 쓰는 사실인 소속(affiliation)·직급(rank)·담당 서비스(service)만 담는다.
  대화 내용, 질문, 검색 결과는 Store에 넣지 않는다.
- namespace는 `(user_id, "profile")`로 사용자마다 나눈다(P-01). 다른 user_id의 값은 읽을 수 없다.
- 틀린 기억은 사용자가 보고 고치거나 지운다(`GET/PATCH/DELETE /me/memory`). 아래 get/put/delete가 그 밑바닥이다.
"""
from __future__ import annotations

from langgraph.store.base import BaseStore

PROFILE_KEY = "me"
# 기억해도 되는 칸. 이 밖의 값은 저장하지 않는다.
ALLOWED_FIELDS = ("affiliation", "rank", "service")


def profile_namespace(user_id: str) -> tuple[str, str]:
    if not user_id:
        raise ValueError("user_id is required")
    return (user_id, "profile")


def get_profile(store: BaseStore, user_id: str) -> dict:
    """저장된 프로필. 없으면 빈 dict."""
    item = store.get(profile_namespace(user_id), PROFILE_KEY)
    if item is None:
        return {}
    return {k: v for k, v in item.value.items() if k in ALLOWED_FIELDS and v}


def put_profile(store: BaseStore, user_id: str, *, affiliation: str | None = None, rank: str | None = None,
                service: str | None = None) -> dict:
    """주어진 칸만 갱신(None은 그대로 둠)하고 갱신된 프로필을 돌려준다."""
    cur = get_profile(store, user_id)
    if affiliation is not None:
        cur["affiliation"] = affiliation
    if rank is not None:
        cur["rank"] = rank
    if service is not None:
        cur["service"] = service
    store.put(profile_namespace(user_id), PROFILE_KEY, cur)
    return cur


def delete_profile(store: BaseStore, user_id: str) -> None:
    store.delete(profile_namespace(user_id), PROFILE_KEY)
