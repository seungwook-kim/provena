"""내 정보 암호화 — AES-256-GCM (요청 1번, MYINFO_SPEC.md 5장).

- 키는 환경변수 `PROFILE_ENC_KEYS` 에서만 읽는다: `"1:<base64 32바이트>,2:<base64 32바이트>"`. 저장소·코드에 두지 않는다
  (AUTH_SECRET 과 같은 규칙). 새로 잠글 때는 가장 큰 번호를 쓰고, 풀 때는 줄에 적힌 `key_version` 의 키를 쓴다(키 교체).
- 칸마다, 저장할 때마다 nonce 12바이트를 새로 만든다. AAD = "user_id|칸 이름" 이라 다른 사람·다른 칸에 옮겨 붙이면 풀리지 않는다.
- 키가 없거나 형식이 틀리면 모든 환경에서 시작을 거부한다. 실행 중 임시 키를 만들지 않는다.
- 오류 메시지에 키·평문·암호문을 쓰지 않는다.
"""
from __future__ import annotations

import base64
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV = "PROFILE_ENC_KEYS"
NONCE_BYTES = 12


class ProfileCryptoError(Exception):
    """키 설정이 틀렸거나 암호문을 풀 수 없을 때. 메시지에 값은 넣지 않는다."""


def _aad(user_id: str, field: str) -> bytes:
    return f"{user_id}|{field}".encode("utf-8")


def parse_keys(raw: str) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        version, sep, encoded = part.partition(":")
        if not sep or not version.strip().isdigit() or int(version) <= 0:
            raise ProfileCryptoError(f"{KEY_ENV} 형식이 틀렸습니다(번호:base64)")
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except ValueError:
            raise ProfileCryptoError(f"{KEY_ENV} 의 키가 base64가 아닙니다") from None
        if len(key) != 32:
            raise ProfileCryptoError(f"{KEY_ENV} 의 키는 32바이트(AES-256)여야 합니다")
        if int(version) in keys:
            raise ProfileCryptoError(f"{KEY_ENV} 에 같은 번호가 두 번 있습니다")
        keys[int(version)] = key
    if not keys:
        raise ProfileCryptoError(f"{KEY_ENV} 가 비어 있습니다")
    return keys


class ProfileCipher:
    def __init__(self, keys: Mapping[int, bytes]):
        if not keys or any(len(k) != 32 for k in keys.values()):
            raise ProfileCryptoError("AES-256 키(32바이트)가 필요합니다")
        self._keys = dict(keys)
        self.current_version = max(self._keys)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProfileCipher":
        env = os.environ if environ is None else environ
        raw = (env.get(KEY_ENV) or "").strip()
        if raw:
            return cls(parse_keys(raw))
        raise ProfileCryptoError(f"{KEY_ENV} 가 없어 내 정보를 저장할 수 없습니다")

    def encrypt(self, user_id: str, field: str, plaintext: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._keys[self.current_version]).encrypt(nonce, plaintext.encode("utf-8"), _aad(user_id, field))
        return nonce + sealed

    def decrypt(self, user_id: str, field: str, blob: bytes, key_version: int) -> str:
        key = self._keys.get(int(key_version))
        if key is None:
            raise ProfileCryptoError("저장된 내 정보의 키 번호를 찾을 수 없습니다")
        blob = bytes(blob)
        if len(blob) < NONCE_BYTES + 16:
            raise ProfileCryptoError("저장된 내 정보가 손상되었습니다")
        try:
            return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], _aad(user_id, field)).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            raise ProfileCryptoError("저장된 내 정보를 풀 수 없습니다") from None
