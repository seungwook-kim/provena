"""내 정보 암호화(AES-256-GCM) 시험 — MYINFO_SPEC.md 5·6장. 키는 시험 안에서 무작위로 만든다(저장소에 두지 않는다)."""
import base64
import os

import pytest

from backend.services.profile_crypto import (KEY_ENV, KEY_FILE_ENV, NONCE_BYTES, ProfileCipher, ProfileCryptoError,
                                             load_or_create_local_key, local_key_file, parse_keys)

UID_A = "11111111-1111-4111-8111-111111111111"
UID_B = "22222222-2222-4222-8222-222222222222"


def _key_text(version, key=None):
    return f"{version}:{base64.b64encode(key or os.urandom(32)).decode()}"


@pytest.fixture
def cipher():
    return ProfileCipher({1: os.urandom(32)})


def test_roundtrip_returns_same_value(cipher):
    blob = cipher.encrypt(UID_A, "name", "김민수")
    assert cipher.decrypt(UID_A, "name", blob, cipher.current_version) == "김민수"


def test_ciphertext_has_no_plaintext_and_expected_length(cipher):
    value = "010-1234-5678"
    blob = cipher.encrypt(UID_A, "phone", value)
    assert value.encode() not in blob and b"5678" not in blob
    assert len(blob) == NONCE_BYTES + len(value.encode()) + 16   # nonce + 암호문 + 태그


def test_same_value_gets_new_nonce_and_ciphertext(cipher):
    first = cipher.encrypt(UID_A, "phone", "010-1234-5678")
    second = cipher.encrypt(UID_A, "phone", "010-1234-5678")
    assert first[:NONCE_BYTES] != second[:NONCE_BYTES]
    assert first != second


def test_tampered_byte_fails(cipher):
    blob = bytearray(cipher.encrypt(UID_A, "address", "부산광역시 해운대구"))
    blob[NONCE_BYTES + 1] ^= 0x01
    with pytest.raises(ProfileCryptoError):
        cipher.decrypt(UID_A, "address", bytes(blob), cipher.current_version)


def test_truncated_blob_fails(cipher):
    with pytest.raises(ProfileCryptoError):
        cipher.decrypt(UID_A, "name", b"short", cipher.current_version)


def test_other_user_id_cannot_decrypt(cipher):
    blob = cipher.encrypt(UID_A, "name", "김민수")
    with pytest.raises(ProfileCryptoError):
        cipher.decrypt(UID_B, "name", blob, cipher.current_version)


def test_other_field_cannot_decrypt(cipher):
    blob = cipher.encrypt(UID_A, "name", "김민수")
    with pytest.raises(ProfileCryptoError):
        cipher.decrypt(UID_A, "dept", blob, cipher.current_version)


def test_old_key_version_still_decrypts_after_rotation():
    old_key, new_key = os.urandom(32), os.urandom(32)
    before = ProfileCipher({1: old_key})
    old_blob = before.encrypt(UID_A, "phone", "010-1111-2222")
    after = ProfileCipher.from_env({KEY_ENV: f"{_key_text(1, old_key)},{_key_text(2, new_key)}"})
    assert after.current_version == 2
    assert after.decrypt(UID_A, "phone", old_blob, 1) == "010-1111-2222"
    new_blob = after.encrypt(UID_A, "phone", "010-3333-4444")
    with pytest.raises(ProfileCryptoError):
        before.decrypt(UID_A, "phone", new_blob, 2)    # 옛 설정에는 2번 키가 없다
    with pytest.raises(ProfileCryptoError):
        after.decrypt(UID_A, "phone", new_blob, 1)     # 다른 키로는 못 푼다


@pytest.mark.parametrize("raw", [
    "", " , ", "abc", "0:" + base64.b64encode(b"x" * 32).decode(), "x:" + base64.b64encode(b"x" * 32).decode(),
    "1:not-base64!!", "1:" + base64.b64encode(b"short").decode(),
    "1:" + base64.b64encode(b"a" * 32).decode() + ",1:" + base64.b64encode(b"b" * 32).decode(),
])
def test_bad_key_config_errors(raw):
    with pytest.raises(ProfileCryptoError):
        parse_keys(raw)


def test_error_message_has_no_key_material():
    secret_part = base64.b64encode(b"k" * 31).decode()
    with pytest.raises(ProfileCryptoError) as info:
        parse_keys(f"1:{secret_part}")
    assert secret_part not in str(info.value)


def test_from_env_without_key_raises_unless_ephemeral_allowed(tmp_path):
    with pytest.raises(ProfileCryptoError):
        ProfileCipher.from_env({})
    one = ProfileCipher.from_env({KEY_FILE_ENV: str(tmp_path / "a" / "k.key")}, allow_ephemeral=True)
    two = ProfileCipher.from_env({KEY_FILE_ENV: str(tmp_path / "b" / "k.key")}, allow_ephemeral=True)
    blob = one.encrypt(UID_A, "name", "김민수")
    assert one.decrypt(UID_A, "name", blob, 1) == "김민수"
    with pytest.raises(ProfileCryptoError):
        two.decrypt(UID_A, "name", blob, 1)   # 키 파일이 다르면 다른 무작위 키


def test_configured_key_wins_over_ephemeral():
    key = os.urandom(32)
    configured = ProfileCipher.from_env({KEY_ENV: _key_text(3, key)}, allow_ephemeral=True)
    assert configured.current_version == 3
    assert ProfileCipher({3: key}).decrypt(UID_A, "name", configured.encrypt(UID_A, "name", "김민수"), 3) == "김민수"


# ---- 로컬 데모 키 파일 (놓친 것 K-23) --------------------------------------------
def test_local_demo_key_is_persisted_and_reused_after_restart(tmp_path):
    """api를 재시작(프로세스가 새로 뜸)해도 같은 키 파일을 읽어 전에 저장한 내 정보를 푼다."""
    env = {KEY_FILE_ENV: str(tmp_path / "keys" / "local_demo_profile.key")}
    first = ProfileCipher.from_env(env, allow_ephemeral=True)
    blob = first.encrypt(UID_A, "name", "김민수")
    restarted = ProfileCipher.from_env(env, allow_ephemeral=True)   # 메모리의 키는 없고 파일만 남은 상태
    assert restarted is not first and restarted.local_generated is True
    assert restarted.decrypt(UID_A, "name", blob, 1) == "김민수"
    text = (tmp_path / "keys" / "local_demo_profile.key").read_text(encoding="ascii")
    assert set(parse_keys(text)) == {1}   # PROFILE_ENC_KEYS 와 같은 형식
    assert [p.name for p in (tmp_path / "keys").iterdir()] == ["local_demo_profile.key"]   # 임시 파일을 남기지 않는다


def test_production_mode_never_reads_or_writes_a_key_file(tmp_path):
    """로컬 데모가 아니면(allow_ephemeral=False) 키 파일이 있어도 쓰지 않고, 없어도 만들지 않고, 시작을 막는다."""
    path = tmp_path / "keys" / "local_demo_profile.key"
    with pytest.raises(ProfileCryptoError):
        ProfileCipher.from_env({KEY_FILE_ENV: str(path)})
    assert not path.exists() and not path.parent.exists()
    load_or_create_local_key(path)   # 로컬 데모 때 남은 파일이 있어도
    with pytest.raises(ProfileCryptoError):
        ProfileCipher.from_env({KEY_FILE_ENV: str(path)})


def test_configured_key_ignores_key_file_and_is_not_local_generated(tmp_path):
    path = tmp_path / "k.key"
    configured = ProfileCipher.from_env({KEY_ENV: _key_text(1), KEY_FILE_ENV: str(path)}, allow_ephemeral=True)
    assert configured.local_generated is False and not path.exists()


def test_broken_key_file_is_replaced_with_a_new_key(tmp_path):
    path = tmp_path / "k.key"
    path.write_text("1:not-a-key", encoding="ascii")
    env = {KEY_FILE_ENV: str(path)}
    one = ProfileCipher.from_env(env, allow_ephemeral=True)
    two = ProfileCipher.from_env(env, allow_ephemeral=True)
    assert two.decrypt(UID_A, "name", one.encrypt(UID_A, "name", "김민수"), 1) == "김민수"


def test_badly_formatted_key_file_is_removed_and_regenerated(tmp_path):
    """읽기는 됐는데 형식이 틀린 파일만 지우고 새 키를 적는다."""
    path = tmp_path / "k.key"
    path.write_text("garbage", encoding="ascii")
    keys = load_or_create_local_key(path)
    assert set(keys) == {1}
    assert parse_keys(path.read_text(encoding="ascii")) == keys   # 새 키가 같은 경로에 적혔다


@pytest.mark.parametrize("error", [PermissionError("denied"), UnicodeDecodeError("ascii", b"\xff", 0, 1, "bad")])
def test_key_file_read_error_keeps_the_file_and_raises(tmp_path, monkeypatch, error):
    """읽는 중 오류(권한·잠금·해독 실패)는 파일을 지우지도 덮어쓰지도 않고 시작을 멈춘다(기존 내 정보 보호)."""
    from pathlib import Path
    path = tmp_path / "k.key"
    original = _key_text(1) + "\n"
    path.write_text(original, encoding="ascii")
    real_read_text = Path.read_text

    def failing_read_text(self, *args, **kwargs):
        if self == path:
            raise error
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)
    with pytest.raises(ProfileCryptoError):
        ProfileCipher.from_env({KEY_FILE_ENV: str(path)}, allow_ephemeral=True)
    monkeypatch.undo()
    assert path.read_text(encoding="ascii") == original
    assert [p.name for p in tmp_path.iterdir()] == ["k.key"]   # 임시 파일도 남기지 않는다


def test_unwritable_key_file_falls_back_to_this_run_only(tmp_path, caplog):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="ascii")
    env = {KEY_FILE_ENV: str(blocker / "k.key")}   # 부모가 파일이라 만들 수 없다
    one = ProfileCipher.from_env(env, allow_ephemeral=True)
    assert one.decrypt(UID_A, "name", one.encrypt(UID_A, "name", "김민수"), 1) == "김민수"
    assert "이번 실행만" in caplog.text


def test_key_file_log_has_no_key_material(tmp_path, caplog):
    path = tmp_path / "k.key"
    ProfileCipher.from_env({KEY_FILE_ENV: str(path)}, allow_ephemeral=True)
    encoded = path.read_text(encoding="ascii").strip().split(":", 1)[1]
    assert encoded not in caplog.text


def test_default_key_file_is_outside_the_repo():
    from pathlib import Path
    default = local_key_file({})
    repo = Path(__file__).resolve().parents[1]
    assert default.is_absolute() and repo not in default.parents
    assert local_key_file({KEY_FILE_ENV: "  "}) == default
