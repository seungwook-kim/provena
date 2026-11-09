"""내 정보 암호화(AES-256-GCM) 시험 — MYINFO_SPEC.md 5·6장. 키는 시험 안에서 무작위로 만든다(저장소에 두지 않는다)."""
import base64
import os

import pytest

from backend.services.profile_crypto import KEY_ENV, NONCE_BYTES, ProfileCipher, ProfileCryptoError, parse_keys

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


def test_from_env_without_key_always_raises():
    with pytest.raises(ProfileCryptoError):
        ProfileCipher.from_env({})


def test_configured_key_is_used():
    key = os.urandom(32)
    configured = ProfileCipher.from_env({KEY_ENV: _key_text(3, key)})
    assert configured.current_version == 3
    assert ProfileCipher({3: key}).decrypt(UID_A, "name", configured.encrypt(UID_A, "name", "김민수"), 3) == "김민수"
