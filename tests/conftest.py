"""시험 공통 설정. 질문 분해(SEARCH_DECOMPOSE)는 코드 기본이 켬이라, 분해와 상관없는 그래프 시험은 끈 채로 돌린다.
분해를 시험하는 쪽은 인자(`build_graph(decompose=True)`)나 `monkeypatch.setenv`로 직접 정한다."""
import pytest


@pytest.fixture(autouse=True)
def _decompose_off_unless_asked(monkeypatch):
    monkeypatch.setenv("SEARCH_DECOMPOSE", "0")


@pytest.fixture(autouse=True)
def _webhook_dns_offline(monkeypatch):
    """웹훅 주소 검사(`webhook._resolve`)가 시험 중 실제 DNS를 부르지 않게 한다. `example.com` 이름은 공인 IP로 푼다."""
    import ipaddress

    from backend.graph.recall import webhook

    real = webhook._resolve
    monkeypatch.setattr(webhook, "_resolve", lambda host: [ipaddress.ip_address("93.184.216.34")] if host.endswith("example.com") else real(host))


@pytest.fixture(autouse=True)
def _local_demo_profile_key_in_tmp(monkeypatch, tmp_path):
    """로컬 데모 모드로 앱을 만드는 시험이 개발자 홈(~/.provena)에 키 파일을 남기지 않게, 키 파일 자리를 시험용 임시 폴더로 돌린다(K-23)."""
    monkeypatch.setenv("PROFILE_KEY_FILE", str(tmp_path / "profile-key" / "local_demo_profile.key"))
