"""비공개 주소 가리기. MCP 서버와 그래프가 같은 함수를 쓴다(SDD 76줄, docs/specs/mcp.md EC-11).

비공개 주소(internal.gitlab.com)는 공개 핸드북 본문에도 링크로 남아 있다(스냅샷 23,095청크 중 `text` 7청크, 다른 칸 0).
검색 순위와 섹션 지문 검사는 바꾸기 전 글로 하고, 검색 밖으로 나갈 때만 바꾼다. 같은 글에 두 번 걸어도 결과가 같다.
"""
from __future__ import annotations

import re

PRIVATE_HOST = "internal.gitlab.com"
PRIVATE_MARK = "[비공개 문서]"
_PRIVATE_LINK = re.compile(r"\[([^\]]*)\]\(\s*(?:https?://)?internal\.gitlab\.com[^)]*\)")
_PRIVATE_URL = re.compile(r"(?:https?://)?internal\.gitlab\.com[^\s)\]>|\"'`]*")
_FIELDS = ("text", "source_url")


def redact(text: str) -> str:
    text = _PRIVATE_LINK.sub(lambda m: f"{m.group(1)} {PRIVATE_MARK}".strip(), text)
    return _PRIVATE_URL.sub(PRIVATE_MARK, text)


def redact_chunk(chunk: dict) -> dict:
    """청크(또는 섹션) dict의 본문과 주소를 가린 새 dict. `text_sha256`은 원문 지문 그대로 둔다."""
    out = dict(chunk)
    for key in _FIELDS:
        if isinstance(out.get(key), str):
            out[key] = redact(out[key])
    return out
