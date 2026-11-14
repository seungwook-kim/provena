"""내 정보 암호화 — AES-256-GCM (요청 1번, MYINFO_SPEC.md 5장).

- 키는 환경변수 `PROFILE_ENC_KEYS` 에서만 읽는다: `"1:<base64 32바이트>,2:<base64 32바이트>"`. 저장소·코드에 두지 않는다
  (AUTH_SECRET 과 같은 규칙). 새로 잠글 때는 가장 큰 번호를 쓰고, 풀 때는 줄에 적힌 `key_version` 의 키를 쓴다(키 교체).
- 칸마다, 저장할 때마다 nonce 12바이트를 새로 만든다. AAD = "user_id|칸 이름" 이라 다른 사람·다른 칸에 옮겨 붙이면 풀리지 않는다.
- 키가 없으면: 로컬 데모 모드(PROVENA_ENV=local, PROVENA_DEV_MODE=1)만 무작위 키를 한 번 만들어 키 파일에 두고 다음 실행에
  다시 읽는다(놓친 것 K-23: 전에는 실행마다 새 키라 api를 재시작하면 저장된 내 정보를 풀지 못해 503이었다).
  키 파일은 `PROFILE_KEY_FILE`, 비우면 실행 사용자 홈의 `~/.provena/local_demo_profile.key`(저장소 밖, 컨테이너에서는 /home/app).
  파일을 못 쓰면 이번 실행만 쓰는 키로 돈다. 그 밖의 모드는 키 파일을 읽지도 쓰지도 않고 시작하지 않는다.
- 로컬에서 만든 키로 도는 암호기는 `local_generated=True` 다. 내 정보 API는 이때만 "풀 수 없는 줄 → 다시 입력" 안내를 낸다.
- 오류 메시지·로그에 키·평문·암호문을 쓰지 않는다.
"""
from __future__ import annotations

import base64
import logging
import os
from collections.abc import Mapping
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV = "PROFILE_ENC_KEYS"
KEY_FILE_ENV = "PROFILE_KEY_FILE"
DEFAULT_KEY_FILE = "~/.provena/local_demo_profile.key"   # 저장소 밖이라 커밋·이미지에 들어갈 수 없다
NONCE_BYTES = 12
log = logging.getLogger(__name__)


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


def local_key_file(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path((env.get(KEY_FILE_ENV) or "").strip() or DEFAULT_KEY_FILE).expanduser()


def _read_local_key(path: Path) -> dict[int, bytes] | None:
    """키 파일이 없으면 None. 있는데 못 읽거나 형식이 틀리면 지우고 None(새로 만든다. 옛 내 정보는 다시 입력)."""
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        text = ""
    try:
        return parse_keys(text)
    except ProfileCryptoError:
        log.warning("로컬 데모 키 파일을 읽을 수 없어 새로 만든다(저장된 내 정보는 다시 입력): %s", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None


def load_or_create_local_key(path: Path) -> dict[int, bytes]:
    """로컬 데모 전용. 키 파일이 있으면 그 키, 없으면 만들어 0600으로 적고 돌려준다. 동시에 뜬 다른 프로세스가 먼저 적었으면 그 키를 쓴다."""
    keys = _read_local_key(path)
    if keys is not None:
        return keys
    key = AESGCM.generate_key(bit_length=256)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write("1:" + base64.b64encode(key).decode("ascii") + "\n")
        try:
            os.link(tmp, path)   # 이미 있으면 실패한다(덮어쓰지 않는다)
        except FileExistsError:
            return _read_local_key(path) or {1: key}
        except OSError:          # 하드링크를 못 쓰는 파일 시스템
            os.replace(tmp, path)
            return {1: key}
        log.warning("%s 가 없어 로컬 데모 키를 만들어 파일에 두었다(재시작해도 같은 키): %s", KEY_ENV, path)
    except OSError as exc:
        log.warning("로컬 데모 키 파일을 쓸 수 없어 이번 실행만 쓰는 키로 돈다(재시작하면 내 정보를 다시 입력): %s", type(exc).__name__)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {1: key}


class ProfileCipher:
    def __init__(self, keys: Mapping[int, bytes], *, local_generated: bool = False):
        if not keys or any(len(k) != 32 for k in keys.values()):
            raise ProfileCryptoError("AES-256 키(32바이트)가 필요합니다")
        self._keys = dict(keys)
        self.current_version = max(self._keys)
        self.local_generated = local_generated   # 로컬 데모가 스스로 만든 키일 때만 True (PROFILE_ENC_KEYS 로 받은 키는 항상 False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *, allow_ephemeral: bool = False) -> "ProfileCipher":
        env = os.environ if environ is None else environ
        raw = (env.get(KEY_ENV) or "").strip()
        if raw:
            return cls(parse_keys(raw))
        if allow_ephemeral:   # 로컬 데모 전용(backend/main.py 가 is_local_demo() 로 넘긴다). 이 가지 밖에서는 키 파일을 건드리지 않는다
            return cls(load_or_create_local_key(local_key_file(env)), local_generated=True)
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
        except InvalidTag:
            raise ProfileCryptoError("저장된 내 정보를 풀 수 없습니다") from None
