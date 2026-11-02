"""LLM 출력 파싱(견고하게). 실패하면 호출한 쪽이 안전 기본값을 쓴다."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_json_obj(text: object) -> dict | None:
    """텍스트에서 JSON 객체 하나를 꺼낸다. 코드펜스·앞뒤 설명이 있어도 가장 바깥 {...}를 시도한다. 실패하면 None."""
    if not isinstance(text, str):
        return None
    s = _FENCE.sub("", text.strip())
    for cand in (s, s[s.find("{") : s.rfind("}") + 1] if "{" in s and "}" in s else ""):
        if not cand:
            continue
        try:
            obj = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None
