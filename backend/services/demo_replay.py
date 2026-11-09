"""데모 재생(replay) 모델 (SDD 7장 G2: 키가 없으면 녹화한 응답을 재생한다).

흐름
- 데모 모드(`LLM_API_KEY` 없음, 또는 `DEMO_MODE=1`)의 `get_chat_model()`은 `ReplayChatModel`을 돌려준다.
  호출마다 요청 키로 `data/demo_replay/*.jsonl`에서 녹화한 응답을 찾는다. 없으면 결정적 가짜 응답(`demo_fallback`)으로 대신하고, 처음 한 번만 로그를 남긴다.
- 녹화 모드(`LLM_RECORD=1` + 실제 키 + 데모 아님)의 `get_chat_model()`은 `RecordingChatModel`로 실제 모델을 감싸 요청 키 -> 응답을 같은 폴더에 덧붙인다.
  녹화는 `python -m backend.services.demo_record --questions <파일>`이 한다. 이 CLI는 서비스 설정(61.51)을 적용하지 않아 서버와 프롬프트가 다를 수 있으니,
  데모 서버가 재생할 녹화는 서버를 `LLM_RECORD=1`·`DEMO_MODE=0`으로 띄워 `/chat`에 질문을 보내 만든다(2026-11-09 data/demo_replay/ 녹화가 이 방법이다).

요청 키(`request_key`): sha256(역할 + 정규화한 메시지). 역할은 시스템 프롬프트 첫 줄의 `[[task:...]]` 표지(없으면 `generic`).
공급자·모델 이름은 키에 넣지 않는다(녹화한 모델과 재생하는 쪽의 모델 설정이 달라도 같은 요청이면 같은 응답을 찾으려는 것이고, 모델 이름은 녹화 줄에 정보로만 남긴다).
정규화: 공백을 하나로 접고, 맨 앞 `기준일: YYYY-MM-DD` 줄의 날짜는 지운다(오늘 날짜가 들어가서 날마다 키가 바뀌는 것을 막는다).

환경변수
- `DEMO_MODE`: 1/true/yes/on이면 키가 있어도 데모(재생). 키가 없으면 이 값과 무관하게 데모.
- `DEMO_REPLAY_DIR`: 녹화 폴더(기본 `<repo>/data/demo_replay`). 읽기: 폴더의 `*.jsonl` 전부(이름 순, 뒤 파일의 같은 키가 앞 파일을 덮는다). 쓰기: 같은 폴더의 `recorded.jsonl`.
  같은 파일에 같은 키가 여러 줄이면 응답 변형이다: 그래프가 같은 요청을 여러 번 부르고 매번 다른 응답을 받은 것(답 두 번 써서 고르기, 판정 투표, 근거 판정)이라 재생도 부를 때마다 차례로 돌려가며 낸다.
  다시 녹화해 바꾸려면 `recorded.jsonl`을 지우고 녹화한다(남아 있으면 새 응답이 변형으로 섞인다).
- `LLM_RECORD`: 1/true/yes/on이면 녹화 모드(실제 키가 있고 데모가 아닐 때만).
녹화 줄: {"key", "role", "model", "user_preview", "response", "recorded_at"}. 비밀키는 쓰지 않는다.
질문 임베딩(voyage-4 API)도 같은 폴더에 녹화·재생한다(`backend/rag/retrieve/embed.py`): 역할 `query_embedding`, 응답은 벡터(JSON 목록)다.
키 없는 데모는 녹화에 있는 질문만 검색할 수 있다(질문 벡터를 만들 수 없으면 검색은 빈 결과 `no_key`로 끝나고 질문은 거절된다).
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY_DIR = ROOT / "data" / "demo_replay"
RECORD_FILE = "recorded.jsonl"
GENERIC_ROLE = "generic"
DEFAULT_FAKE_TEXT = "(가짜 모델 응답) 합성 시험용 답변입니다. 실제 핸드북 근거가 아닙니다."
_TRUE = ("1", "true", "yes", "on")
_TASK = re.compile(r"\[\[task:(\w+)\]\]")
_ASOF_LINE = re.compile(r"(?m)^기준일: \d{4}-\d{2}-\d{2}")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE


def replay_dir() -> Path:
    return Path(os.environ.get("DEMO_REPLAY_DIR") or DEFAULT_REPLAY_DIR)


# ---------------------------------------------------------------- 요청 키
def _content_text(m: BaseMessage) -> str:
    c = m.content
    return c if isinstance(c, str) else json.dumps(c, ensure_ascii=False, sort_keys=True, default=str)


def _normalize(text: str) -> str:
    return " ".join(_ASOF_LINE.sub("기준일: <date>", text).split())


def message_role(messages: list[BaseMessage]) -> str:
    for m in messages:
        mt = _TASK.search(_content_text(m))
        if mt:
            return mt.group(1)
    return GENERIC_ROLE


def request_key_for(role: str, parts: list[str]) -> str:
    """LLM 메시지가 아닌 요청(질문 임베딩 등)의 키: sha256(역할 + 정규화한 글 조각들). 녹화 줄의 `role`은 이 역할이다."""
    payload = {"v": 1, "role": role, "parts": [_normalize(p) for p in parts]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def request_key(messages: list[BaseMessage]) -> str:
    payload = {"v": 1, "role": message_role(messages), "messages": [[m.type, _normalize(_content_text(m))] for m in messages]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 저장소
class ReplayStore:
    """`*.jsonl` 녹화 폴더. 파일이 바뀌면(이름·수정 시각·크기) 다음 조회에서 다시 읽는다. 스레드 안전."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory is not None else replay_dir()
        self._lock = threading.Lock()
        self._sig: tuple | None = None
        self._rows: dict[str, dict] = {}
        self._variants: dict[str, list[dict]] = {}
        self._turn: dict[str, int] = {}

    def _files(self) -> list[Path]:
        return sorted(self.directory.glob("*.jsonl")) if self.directory.is_dir() else []

    def _refresh(self) -> None:
        """같은 키의 줄이 한 파일에 여러 개면 그 요청을 여러 번 불렀을 때 응답이 달랐던 것(답을 두 번 써서 고르기, 판정 투표, 근거 판정 여러 번)이라
        모두 남긴다(`pick`이 돌려가며 낸다). 뒤 파일(이름 순)에 같은 키가 있으면 앞 파일의 줄 전체를 덮는다."""
        files = self._files()
        sig = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
        if sig == self._sig:
            return
        variants: dict[str, list[dict]] = {}
        for f in files:
            per_file: dict[str, list[dict]] = {}
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    per_file.setdefault(row["key"], []).append(row)
                except (ValueError, KeyError, TypeError):
                    log.warning("녹화 줄을 읽지 못해 건너뜁니다: %s:%d", f.name, n)
            variants.update(per_file)
        rows = {k: v[-1] for k, v in variants.items()}
        self._rows, self._variants, self._sig = rows, variants, sig

    def get(self, key: str) -> dict | None:
        """그 키의 가장 나중 녹화 줄(변형이 여럿이어도 하나)."""
        with self._lock:
            self._refresh()
            return self._rows.get(key)

    def pick(self, key: str) -> dict | None:
        """그 키의 녹화 줄. 응답 변형이 여럿이면 부를 때마다 차례로 돌려가며 낸다(재생이 녹화 때처럼 여러 답을 섞어 쓰게)."""
        with self._lock:
            self._refresh()
            rows = self._variants.get(key)
            if not rows:
                return None
            n = self._turn.get(key, 0)
            self._turn[key] = n + 1
            return rows[n % len(rows)]

    def __len__(self) -> int:
        with self._lock:
            self._refresh()
            return len(self._rows)

    def add(self, key: str, role: str, model: str, user_preview: str, response: str) -> bool:
        """녹화 한 줄을 `recorded.jsonl`에 덧붙인다. 같은 키에 같은 응답이 이미 있으면 쓰지 않고 False."""
        with self._lock:
            self._refresh()
            if any(r.get("response") == response for r in self._variants.get(key, ())):
                return False
            self.directory.mkdir(parents=True, exist_ok=True)
            row = {
                "key": key, "role": role, "model": model, "user_preview": user_preview[:200], "response": response,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            with (self.directory / RECORD_FILE).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._sig = None  # 다음 조회에서 다시 읽는다
            return True


_stores: dict[str, ReplayStore] = {}
_stores_lock = threading.Lock()


def get_store(directory: Path | str | None = None) -> ReplayStore:
    d = str(Path(directory) if directory is not None else replay_dir())
    with _stores_lock:
        if d not in _stores:
            _stores[d] = ReplayStore(d)
        return _stores[d]


# ---------------------------------------------------------------- 결정적 가짜 응답(녹화가 없을 때)
_BLOCK = re.compile(r"<<<자료>>>\n(.*?)\n<<<끝>>>", re.S)
_CHUNK_ID = re.compile(r"chunk_id=(\S+)")
_SENT_END = re.compile(r"(?<=[.!?。])\s+")
MAX_SENTENCE = 220


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#>*- ").strip()
        if len(line) < 8:
            continue
        s = _SENT_END.split(line, maxsplit=1)[0].strip()
        return s if len(s) <= MAX_SENTENCE else s[: MAX_SENTENCE - 1].rstrip() + "…"
    return ""


def _materials(user: str) -> list[tuple[str, str]]:
    """프롬프트의 `<<<자료>>>` 블록에서 (chunk_id, 본문)을 차례대로 뽑는다."""
    out = []
    for m in _BLOCK.finditer(user):
        head, _, body = m.group(1).partition("\n")
        cid = _CHUNK_ID.search(head)
        if cid:
            out.append((cid.group(1), body))
    return out


def _field(user: str, label: str) -> str:
    m = re.search(rf"(?m)^{label}: (.*)$", user)
    return m.group(1).strip() if m else ""


def demo_fallback(messages: list[BaseMessage]) -> str:
    """녹화가 없을 때의 결정적 응답. 역할(`[[task:...]]`)마다 그래프가 읽는 JSON을 돌려준다. 같은 입력이면 항상 같은 출력.

    - classify: 일반 정책 질문(rule). rewrite: 질문 그대로. judge: 자료가 있으면 충분.
    - answer: 검색된 상위 근거 청크의 첫 문장을 `[1]`, `[2]` 표시와 함께 보여 주고 그 청크를 인용한다(인용 검사·근거 판정 코드 규칙이 통과할 수 있는 답).
    - 알 수 없는 역할(다른 그래프의 프롬프트)은 예전과 같은 고정 문장.
    """
    role = message_role(messages)
    user = _content_text(messages[-1]) if messages else ""
    dump = lambda **kw: json.dumps(kw, ensure_ascii=False)  # noqa: E731
    if role == "classify":
        return dump(route="rule")
    if role == "rewrite":
        q = user.split("질문: ", 1)[-1].split("\n이전 검색이", 1)[0].strip()
        return dump(query=q, org=None, as_of=None)
    if role == "judge":
        if _materials(user):
            return dump(sufficient=True, reason="", clarify=None)
        return dump(sufficient=False, reason="검색 결과 없음", clarify=None)
    if role == "decision_extract":
        return dump(task_type=None, amount=None)
    if role == "grounding":
        return dump(grounded=True)
    if role == "answer":
        picks = [(cid, s) for cid, body in _materials(user) if (s := _first_sentence(body))][:2]
        if not picks:
            return dump(answer="검색된 근거에서 인용할 문장을 찾지 못했습니다.", citations=[])
        lines = [f"- {s} [{i}]" for i, (_, s) in enumerate(picks, 1)]
        head = "검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다)."
        dec = _field(user, "결정표 실행 결과(코드가 계산한 값, 그대로 쓸 것)")
        if dec:
            try:
                d = ast.literal_eval(dec)
                if d.get("approver"):
                    lines.insert(0, f"- 결정표 결과: 승인자 {d['approver']}")
            except (ValueError, SyntaxError, AttributeError):
                pass
        asof = _field(user, "기준일")
        if asof and asof != "미지정":
            lines.append(f"기준일: {asof}")
        return dump(answer="\n".join([head, *lines]), citations=[{"chunk_id": cid} for cid, _ in picks])
    return DEFAULT_FAKE_TEXT


# ---------------------------------------------------------------- 모델
class ReplayChatModel(FakeListChatModel):
    """데모 모델. 녹화한 응답을 요청 키로 찾고, 없으면 `demo_fallback`. `FakeListChatModel`의 하위 클래스라
    "가짜 모델이면 건너뛴다"는 기존 검사(`isinstance(llm, FakeListChatModel)`)가 그대로 통한다."""

    responses: list[str] = [DEFAULT_FAKE_TEXT]
    store: Any = None
    hits: int = 0
    misses: int = 0
    warned: bool = False

    @property
    def _llm_type(self) -> str:
        return "demo-replay"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        store = self.store if self.store is not None else get_store()
        row = store.pick(request_key(messages))
        if row is not None:
            self.hits += 1
            text = str(row["response"])
        else:
            self.misses += 1
            text = demo_fallback(messages)
            if not _warned_once():
                log.warning("데모 재생: 녹화 응답이 없어 결정적 가짜 응답을 씁니다(역할 %s, 녹화 %d건, 폴더 %s). 이 메시지는 한 번만 냅니다.", message_role(messages), len(store), store.directory)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


_warn_lock = threading.Lock()
_warned = False


def _warned_once() -> bool:
    """처음 부르면 False(그리고 기억), 이후엔 True."""
    global _warned
    with _warn_lock:
        was, _warned = _warned, True
        return was


def reset_warned() -> None:
    global _warned
    with _warn_lock:
        _warned = False


class RecordingChatModel(FakeListChatModel):
    """녹화 모드: 실제 모델(`inner`)을 부르고 요청 키 -> 응답을 저장소에 덧붙인다. 사용량(usage_metadata)은 그대로 넘겨 비용 집계가 유지된다."""

    responses: list[str] = [DEFAULT_FAKE_TEXT]
    inner: Any = None
    store: Any = None
    model_name: str = ""
    recorded: int = 0

    @property
    def _llm_type(self) -> str:
        return "demo-record"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        ai = self.inner.invoke(messages, stop=stop, **kwargs)
        text = ai.content if isinstance(ai.content, str) else json.dumps(ai.content, ensure_ascii=False, default=str)
        store = self.store if self.store is not None else get_store()
        if store.add(request_key(messages), message_role(messages), self.model_name, _content_text(messages[-1]) if messages else "", text):
            self.recorded += 1
        return ChatResult(generations=[ChatGeneration(message=ai)])
