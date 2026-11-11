"""기억 namespace의 첫 요소는 항상 사용자 id (E-03, SDD 4-3)."""
from backend.memory import namespace, profile_namespace


def test_every_memory_namespace_starts_with_the_user_id():
    assert namespace("u-1") == ("u-1", "memories")
    assert profile_namespace("u-1") == ("u-1", "profile")
    assert namespace("u-1")[0] != namespace("u-2")[0]
