"""Claude Code CLI(`claude -p`)를 채팅 모델로 쓰는 어댑터. API 키 없이 로컬에 로그인된 Claude Code 구독으로 LLM 지표를 잴 때 쓴다.

선택: `LLM_PROVIDER=claude_cli` (`backend/services/llm.py`가 이 클래스를 만든다). 키(`LLM_API_KEY`)는 필요 없다.
환경변수:
- `LLM_MODEL`: 모델 id 또는 별칭. 기본 `claude-haiku-5-5`.
- `CLAUDE_CLI_PATH`: claude 실행 파일 경로. 없으면 PATH, 그다음 `~/.local/bin/claude(.exe)`.
- `CLAUDE_CLI_TIMEOUT`: 호출 한 번의 제한 시간(초, 기본 180). `CLAUDE_CLI_RETRIES`: 일시 실패 재시도 횟수(기본 2).
- `CLAUDE_CLI_STATS_FILE`: 있으면 프로세스 종료 때 모델별 호출 수·비용·토큰 합계를 이 파일에 한 줄 덧붙인다.
- `CLAUDE_CLI_MAX_CONCURRENCY`: 프로세스 안에서 동시에 띄울 CLI 수(기본 3).

실제로 쓰는 명령(격리 검증은 `evals/results/metrics_20261030/real_llm_haiku/README.md`):

    claude -p --model <모델> --output-format json --safe-mode --tools "" --no-session-persistence --system-prompt <system>   (프롬프트는 stdin, cwd는 빈 임시 폴더)

- `--safe-mode`: 사용자 전역 CLAUDE.md, 훅(terse 스타일·SessionStart 등), 플러그인, 스킬, MCP를 모두 끈다. 인증(구독 로그인)은 그대로 쓴다. (`--bare`는 OAuth를 안 읽어 쓸 수 없다.)
- `--tools ""`: 내장 도구 전부 끔. `--system-prompt`: 기본 시스템 프롬프트를 대체한다(시스템 메시지가 없어도 중립 문구를 넣는다).
- 시스템 메시지 이외의 메시지는 "역할: 내용" 형식으로 이어 붙여 stdin으로 보낸다. 시스템 프롬프트가 너무 길면(Windows 명령줄 한도) stdin 앞머리로 옮긴다.
- 반환 `AIMessage.usage_metadata`는 입력(캐시 생성·읽기 포함)·출력 토큰, `response_metadata`는 `total_cost_usd`(CLI가 보고한 API 환산 비용)·`model`·`duration_ms`·`duration_api_ms`·`wall_s`(하위 프로세스 전체)·`cli_queue_s`(동시 실행 대기)·`cli_retries`(다시 시도한 횟수).
  `CostTracker`는 `total_cost_usd`가 있으면 단가표 계산 대신 그 값을 쓴다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ChatMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

log = logging.getLogger(__name__)

DEFAULT_CLI_MODEL = "claude-haiku-5-5"
DEFAULT_SYSTEM = "You are a helpful assistant. Follow the instructions in the user message exactly."
MAX_ARG_CHARS = 12000  # 시스템 프롬프트를 명령줄로 넘길 상한. 넘으면 stdin 앞머리로 보낸다(Windows 명령줄 32k 한도 여유)

_sem_lock = threading.Lock()
_sem: threading.Semaphore | None = None
_sem_size = 0


_stats_lock = threading.Lock()
_stats: dict[str, dict] = {}
_stats_registered = False


def _record_stats(model: str, cost: float, in_tok: int, out_tok: int) -> None:
    """`CLAUDE_CLI_STATS_FILE`이 있으면 프로세스가 끝날 때 모델별 호출 수·비용·토큰 합계를 그 파일에 한 줄(JSON) 덧붙인다(평가 1회 비용 집계용)."""
    global _stats_registered
    path = os.environ.get("CLAUDE_CLI_STATS_FILE")
    if not path:
        return
    with _stats_lock:
        row = _stats.setdefault(model, {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0})
        row["calls"] += 1
        row["cost_usd"] += cost
        row["input_tokens"] += in_tok
        row["output_tokens"] += out_tok
        if not _stats_registered:
            import atexit

            def _dump() -> None:
                try:
                    with open(path, "a", encoding="utf-8", newline="\n") as f:
                        f.write(json.dumps({"pid": os.getpid(), "argv": " ".join(__import__("sys").argv[:4]), "models": _stats}, ensure_ascii=False) + "\n")
                except OSError:
                    pass

            atexit.register(_dump)
            _stats_registered = True


class ClaudeCliError(RuntimeError):
    """claude CLI 호출이 재시도 뒤에도 실패했다."""


def _semaphore() -> threading.Semaphore:
    global _sem, _sem_size
    size = max(1, int(os.environ.get("CLAUDE_CLI_MAX_CONCURRENCY") or 3))
    with _sem_lock:
        if _sem is None or size != _sem_size:
            _sem, _sem_size = threading.Semaphore(size), size
        return _sem


def find_claude() -> str:
    explicit = (os.environ.get("CLAUDE_CLI_PATH") or "").strip()
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude"):
        p = Path.home() / ".local" / "bin" / name
        if p.exists():
            return str(p)
    raise ClaudeCliError("claude 실행 파일을 찾지 못했다 (CLAUDE_CLI_PATH로 지정)")


def _role(m: BaseMessage) -> str:
    if isinstance(m, HumanMessage):
        return "User"
    if isinstance(m, AIMessage):
        return "Assistant"
    if isinstance(m, ChatMessage):
        return m.role.capitalize()
    return m.type.capitalize()


def _content_text(m: BaseMessage) -> str:
    c = m.content
    if isinstance(c, str):
        return c
    parts = []
    for p in c:
        parts.append(p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else str(p)))
    return "".join(parts)


def split_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    """(시스템 프롬프트, 나머지 메시지를 이은 프롬프트). 사람 메시지 하나뿐이면 역할 표시 없이 그대로 보낸다."""
    system = "\n\n".join(_content_text(m) for m in messages if isinstance(m, SystemMessage)).strip()
    rest = [m for m in messages if not isinstance(m, SystemMessage)]
    if len(rest) == 1 and isinstance(rest[0], HumanMessage):
        return system, _content_text(rest[0])
    return system, "\n\n".join(f"{_role(m)}: {_content_text(m)}" for m in rest)


EFFORTS = ("low", "medium", "high", "xhigh", "max")
_TASK = re.compile(r"\[\[task:([a-z_]+)\]\]")


def parse_effort_map(text: str) -> dict[str, str]:
    pairs = (part.split("=", 1) for part in text.split(",") if "=" in part)
    return {k.strip(): v.strip().lower() for k, v in pairs if k.strip() and v.strip()}


def effort_for(system: str, default: str, by_task: dict[str, str]) -> str:
    m = _TASK.search(system or "")
    return by_task.get(m.group(1), default) if m else default


def build_command(exe: str, model: str, system: str, effort: str = "low") -> list[str]:
    extra = ["--effort", effort] if effort in EFFORTS else []  # "default" 등은 CLI 기본
    return [exe, "-p", "--model", model, "--output-format", "json", "--safe-mode", "--tools", "", "--no-session-persistence", *extra, "--system-prompt", system]


class ClaudeCliChatModel(BaseChatModel):
    """`claude -p` 하위 프로세스로 답을 받는 채팅 모델. 호출은 동기, 도구 없음, 스트리밍 없음."""

    model: str = DEFAULT_CLI_MODEL
    timeout_s: float = Field(default_factory=lambda: float(os.environ.get("CLAUDE_CLI_TIMEOUT") or 180))
    retries: int = Field(default_factory=lambda: int(os.environ.get("CLAUDE_CLI_RETRIES") or 2))
    cli_path: Optional[str] = None
    # 기본 `--effort low`. CLI 기본 노력 수준으로는 작은 JSON 판정에도 출력 800~1,300토큰을 쓰고 4~7초가 걸렸다(10/30 측정, low는 171토큰·1.6초).
    # MAX_THINKING_TOKENS=0은 Haiku 5.5에서 줄지 않았다. CLAUDE_CLI_EFFORT=default면 플래그 없이 CLI 기본 그대로
    effort: str = Field(default_factory=lambda: (os.environ.get("CLAUDE_CLI_EFFORT") or "low").strip().lower())
    # 역할(시스템 프롬프트의 `[[task:...]]`)별로 덮는 노력 수준. 근거 판정은 low에서 "내용은 받쳐짐"이라 쓰고도 실패로 내는 등
    # 판정이 흔들리고, 답 작성을 low로 두면 관련 질문 거짓 거절이 1/14에서 5~7/14로 늘었다(10/31 측정 4회). 답·판정만 medium. 형식: "grounding=medium,answer=low". 빈 값이면 기본
    effort_by_task: dict[str, str] = Field(default_factory=lambda: parse_effort_map(os.environ.get("CLAUDE_CLI_EFFORT_BY_TASK") or "answer=medium,grounding=medium"))

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort}

    def _run_once(self, system: str, prompt: str) -> dict:
        exe = self.cli_path or find_claude()
        effort = effort_for(system, self.effort, self.effort_by_task)  # 시스템 지시를 앞머리로 옮기기 전에 정한다
        if len(system) > MAX_ARG_CHARS:  # 명령줄이 너무 길어지면 시스템 지시를 사용자 메시지 앞머리로
            prompt = f"[Instructions]\n{system}\n\n[Message]\n{prompt}"
            system = DEFAULT_SYSTEM
        cmd = build_command(exe, self.model, system or DEFAULT_SYSTEM, effort)
        with tempfile.TemporaryDirectory(prefix="claude_cli_") as cwd:  # 빈 임시 폴더: 프로젝트 CLAUDE.md·설정이 닿지 않게
            try:
                proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout_s, cwd=cwd)
            except subprocess.TimeoutExpired as e:
                raise ClaudeCliError(f"claude CLI 시간 초과 ({self.timeout_s}초)") from e
        out = (proc.stdout or "").strip()
        try:
            data = json.loads(out)
        except ValueError as e:
            raise ClaudeCliError(f"claude CLI 출력을 JSON으로 읽지 못함 (exit {proc.returncode}): {out[:200]!r} {(proc.stderr or '')[:200]!r}") from e
        if proc.returncode != 0 or data.get("is_error"):
            raise ClaudeCliError(f"claude CLI 오류 (exit {proc.returncode}): {str(data.get('result') or data.get('subtype') or '')[:300]}")
        if not isinstance(data.get("result"), str):
            raise ClaudeCliError("claude CLI 출력에 result가 없다")
        return data

    def _call(self, system: str, prompt: str) -> dict:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                t_wait = time.perf_counter()
                with _semaphore():
                    t0 = time.perf_counter()
                    data = self._run_once(system, prompt)
                    data["_wall_s"] = round(time.perf_counter() - t0, 4)
                    data["_queue_s"] = round(t0 - t_wait, 4)
                    data["_retries"] = attempt
                    return data
            except ClaudeCliError as e:
                last = e
                log.warning("claude CLI 호출 실패 (%d/%d): %s", attempt + 1, self.retries + 1, e)
                if attempt < self.retries:
                    time.sleep(min(2.0 * (attempt + 1), 6.0))
        err = ClaudeCliError(str(last))
        err.retries = self.retries  # 호출별 기록(`llm_trace.py`)이 읽는다
        raise err

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        system, prompt = split_messages(messages)
        data = self._call(system, prompt)
        text = data["result"]
        for s in stop or []:  # CLI에 stop 옵션이 없어 사후 절단
            i = text.find(s)
            if i >= 0:
                text = text[:i]
        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        used = list((data.get("modelUsage") or {}).keys())
        model_name = used[0] if used else self.model
        meta = {
            "model": model_name,
            "model_name": model_name,
            "total_cost_usd": float(data.get("total_cost_usd") or 0.0),
            "duration_ms": data.get("duration_ms"),
            "duration_api_ms": data.get("duration_api_ms"),
            "wall_s": data.get("_wall_s"),
            "cli_queue_s": data.get("_queue_s"),
            "cli_retries": data.get("_retries"),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "stop_reason": data.get("stop_reason"),
        }
        _record_stats(model_name, meta["total_cost_usd"], in_tok, out_tok)
        msg = AIMessage(content=text, usage_metadata={"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok}, response_metadata=meta)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools: Any, **kwargs: Any):  # 도구 호출은 지원하지 않는다(그래프는 JSON 문자열 파싱만 쓴다)
        raise NotImplementedError("ClaudeCliChatModel은 도구 호출을 지원하지 않는다. with_structured_output(method='json_mode')를 쓰거나 JSON 문자열을 직접 파싱한다.")

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any):
        """프롬프트에 JSON 형식을 덧붙이고 결과를 파싱한다(도구 호출 없는 json_mode 대체). schema는 pydantic 클래스 또는 dict(JSON Schema)."""
        from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
        from langchain_core.runnables import RunnableLambda

        is_pyd = isinstance(schema, type) and hasattr(schema, "model_json_schema")
        spec = json.dumps(schema.model_json_schema() if is_pyd else schema, ensure_ascii=False)
        parser = PydanticOutputParser(pydantic_object=schema) if is_pyd else JsonOutputParser()
        hint = f"\n\nReturn ONLY one JSON object (no code fences, no prose) that matches this JSON Schema:\n{spec}"

        def add_hint(value: Any) -> list[BaseMessage]:
            msgs = list(self._convert_input(value).to_messages())
            sys_i = next((i for i, m in enumerate(msgs) if isinstance(m, SystemMessage)), None)
            if sys_i is None:
                msgs.insert(0, SystemMessage(content=hint.strip()))
            else:
                msgs[sys_i] = SystemMessage(content=_content_text(msgs[sys_i]) + hint)
            return msgs

        def strip_fence(m: AIMessage) -> str:
            t = _content_text(m).strip()
            if t.startswith("```"):
                t = t.strip("`")
                t = t[4:] if t[:4].lower() == "json" else t
            return t.strip()

        chain = RunnableLambda(add_hint) | self
        if include_raw:
            return chain | RunnableLambda(lambda m: {"raw": m, "parsed": parser.parse(strip_fence(m)), "parsing_error": None})
        return chain | RunnableLambda(strip_fence) | parser
