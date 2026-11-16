"""질문 분해: 한국어 질문이 서로 다른 사실을 둘 이상 물으면 2~3개의 하위 질문으로 나눈다 (docs/specs/question-graph.md 4단계).

분해(LLM)는 검색이 아니라 그래프 단계가 한다. 사용자가 쓴 한국어 원 질문을 나누고(측정과 같은 입력), 결과를 `SearchQuery.sub_queries`로 검색에 넘긴다.
프롬프트 본문(`SYSTEM`)과 응답 읽기 규칙은 측정 코드(`evals/retrieval/exp_decompose_v1.py`)와 같고, 시험이 대조한다. 다른 점은 아래와 같다.
- 노드 표지(`[[task:decompose]]`)를 프롬프트 맨 앞에 붙인다(시험용 가짜 모델이 노드를 구분하는 표지).
- 응답 형식이 깨지면 1회 다시 요청한다(`ATTEMPTS`=2). 측정 때는 최대 3번이었다.
- 원 질문이 물음이 아닌 앞 문장(전제)과 질문 문장으로 이루어져 있고 전제의 내용어가 어느 하위 질문에도 없으면, 하위 질문 앞에 그 전제 문장을 붙인다(`keep_premise`, 사전 등록 62.45).
- 하위 질문이 1개이거나, 4개 이상이면 앞 3개만 쓰고, 항목이 비었거나 1000자를 넘거나 원 질문과 같으면 나누지 않은 것으로 본다(검색의 `check_query` 규칙).
실패(형식 오류, 호출 오류)하거나 나누지 않으면 빈 목록이고, 검색은 질문 하나로 그대로 이어 간다. 분해 때문에 답이 멈추지 않는다.
켜는 곳: `decompose_enabled()`. 기본은 켬이다(측정한 확정 조합). 환경 변수 `SEARCH_DECOMPOSE`가 0, false, no, off이면 끈다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable

log = logging.getLogger(__name__)

MIN_SUB = 2
MAX_SUB = 3
MAX_SUB_CHARS = 1000
ATTEMPTS = 2  # 첫 호출 + 재시도 1회
TASK = "decompose"

SYSTEM = (
    "너는 사내 핸드북 검색을 위한 질문 분해기다. 사용자의 한국어 질문이 서로 다른 사실을 둘 이상 묻는 경우에만 독립된 한국어 하위 질문(최대 3개)으로 나눈다.\n"
    "- 하나의 사실을 묻는 질문, 같은 사실을 다른 말로 두 번 묻는 질문, 하나의 사실에 조건·예외를 붙인 질문은 나누지 않는다.\n"
    "- 하위 질문은 질문에 있는 핵심 용어를 그대로 쓰고, 질문에 없는 정보를 더하지 않는다. 각 하위 질문만 읽어도 무엇을 묻는지 알 수 있어야 한다.\n"
    "- 나누지 않으면 split을 false로 하고 sub_questions는 빈 목록으로 둔다.\n"
    "- 설명 없이 JSON 한 개만 출력한다. 예 1: 질문 \"배송은 며칠 걸리고 반품 수수료는 얼마야?\" -> {\"split\": true, \"sub_questions\": [\"배송은 며칠 걸려?\", \"반품 수수료는 얼마야?\"]}. "
    "예 2: 질문 \"휴가 신청은 어떻게 해?\" -> {\"split\": false, \"sub_questions\": []}."
)
SYSTEM_TAGGED = f"[[task:{TASK}]]\n{SYSTEM}"
# `GRAPH_DECOMPOSE_KEEP_SUBJECT=1`(코드 기본 꺼짐, 서비스 설정 켬): 하위 질문이 원 질문의 대상·조건을 빠뜨리면 하위 질문 검색이 원 질문과 다른 대상을 찾는다.
# 켜면 아래 규칙 한 줄을 프롬프트 끝에 더하고(`system_prompt`), 코드가 빠진 앞머리 대상 구를 하위 질문 앞에 붙인다(`keep_subject`). 예시는 핸드북과 무관한 일반 문장이다
KEEP_SUBJECT_RULE = (
    "\n- 원 질문에 대상(누구·어디·무엇)이나 조건(기간·금액·역할·지역 등)이 있으면 모든 하위 질문에 그 대상과 조건을 그대로 넣는다. "
    "하위 질문 하나만 따로 읽어도 원 질문과 같은 대상과 조건을 묻는 질문이어야 한다. "
    "예 3: 질문 \"해외 주문의 배송은 며칠 걸리고 반품 수수료는 얼마야?\" -> {\"split\": true, \"sub_questions\": [\"해외 주문의 배송은 며칠 걸려?\", \"해외 주문의 반품 수수료는 얼마야?\"]}."
)
_COMPANY_PREFIX = re.compile(r"^GitLab(?:의|은|는|이|에서는|에서)?\s+", re.I)


_OFF_VALUES = {"0", "false", "no", "off"}


def decompose_enabled() -> bool:
    """SEARCH_DECOMPOSE가 없거나 비어 있으면 켬(확정 조합). 0, false, no, off면 끔."""
    return (os.environ.get("SEARCH_DECOMPOSE") or "1").strip().lower() not in _OFF_VALUES


def keep_subject_enabled() -> bool:
    """`GRAPH_DECOMPOSE_KEEP_SUBJECT`가 1, true, yes, on이면 켬. 코드 기본은 꺼짐(측정 코드와 같은 프롬프트), 서비스 설정(`service_profile.SERVICE_ENV`)이 켠다."""
    return (os.environ.get("GRAPH_DECOMPOSE_KEEP_SUBJECT") or "").strip().lower() in {"1", "true", "yes", "on"}


def system_prompt(tag: str) -> str:
    """표지(`[[task:...]]`)를 붙인 분해 프롬프트. 스위치를 켜면 대상·조건 유지 규칙을 끝에 더한다. 끄면 `SYSTEM_TAGGED`, `SYSTEM_GATE`와 글자가 같다."""
    return f"[[task:{tag}]]\n{SYSTEM}{KEEP_SUBJECT_RULE if keep_subject_enabled() else ''}"


def parse_split(text: str) -> dict | None:
    """분해 응답 JSON을 읽는다(측정 코드와 같은 규칙). 형식이 틀리면 None."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("split"), bool) or not isinstance(obj.get("sub_questions"), list):
        return None
    if not all(isinstance(x, str) and x.strip() for x in obj["sub_questions"]):
        return None
    return obj


def normalize(question: str, obj: dict) -> list[str]:
    """검색에 넘길 하위 질문. 앞 3개만 쓰고, 2개 미만이거나 원 질문과 같은 항목이 있거나 1000자를 넘는 항목이 있으면 나누지 않은 것이다."""
    subs = [s.strip() for s in obj["sub_questions"]][:MAX_SUB]
    ok = bool(obj["split"]) and len(subs) >= MIN_SUB and all(s != (question or "").strip() and 0 < len(s) <= MAX_SUB_CHARS for s in subs)
    return subs if ok else []


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。？！])\s+")
_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_PARTICLES = ("에서는", "으로는", "에서", "으로", "에게", "한테", "까지", "부터", "마다", "처럼", "이라고", "라고", "을", "를", "은", "는", "이", "가", "의", "에", "와", "과", "도", "로", "만")
_SKIP_WORDS = {"우리", "저희", "제가", "내가", "요즘", "지금", "혹시", "만약", "그리고", "그런데", "그럼", "그러면"}  # 내용이 없는 대명사·접속어
_MIN_STEM = 2  # 조사를 떼고 남는 줄기의 최소 글자 수("평가", "회의", "한도"의 끝 글자는 조사가 아니라 낱말의 일부다)
_ENDINGS_BY_VERB = {  # 서술어 첫 글자(하다·되다·있다 계열의 활용형 첫 음절) -> 그 뒤에 올 수 있는 어미. 낱말 전체가 이 조합일 때만 서술어 조각이다
    "하": ("", "다", "고", "고자", "는", "는데", "는지", "며", "면", "면서", "여", "였다", "지", "지만", "게", "려", "려고", "려는", "도록", "니", "기", "던", "세요", "십시오", "신다"),
    "합": ("", "니다", "니까", "니다만"),
    "한": ("다", "다면", "다는", "다고"),
    "할": ("까", "까요", "지", "게", "려", "려고"),
    "했": ("다", "고", "는데", "던", "습니다", "으며", "으면", "어요", "지만"),
    "해": ("야", "야만", "서", "서요", "요", "라", "주세요", "줘"),  # "해외", "해고", "해지"는 이 목록에 없으므로 내용어다
    "있": ("다", "는", "는데", "는지", "어", "어요", "어서", "으면", "으나", "으며", "습니다", "습니까", "을", "던", "지", "고", "도록", "기", "음", "이"),
    "없": ("다", "는", "는데", "는지", "어", "어요", "어서", "으면", "으나", "으며", "습니다", "습니까", "을", "던", "지", "고", "도록", "기", "음", "이"),
    "되": ("다", "는", "어", "어서", "어요", "면", "고", "지", "려", "려고", "도록", "는데", "었다", "었습니다", "기"),
    "됩": ("니다", "니까"),
    "됐": ("다", "습니다", "는데", "고", "으며"),
    "된": ("다", "다면", "다는", "다고"),
    "될": ("까", "수", "지", "것"),
    "싶": ("다", "은", "어", "어요", "습니다", "으면", "은데", "지", "고", "지만"),
}
_PREDICATE_FORMS = frozenset(head + tail for head, tails in _ENDINGS_BY_VERB.items() for tail in tails)  # "합니다", "하려고", "있는데" 같은 서술어 조각은 내용어로 세지 않는다


def _stem(word: str) -> str | None:
    """낱말 하나의 내용어 줄기(`_content_stems`의 규칙). 내용어가 아니면 None."""
    for p in _PARTICLES:
        if word.endswith(p) and len(word) - len(p) >= _MIN_STEM:
            word = word[: -len(p)]
            break
    if len(word) < 2 or word in _SKIP_WORDS or word in _PREDICATE_FORMS or word in _PARTICLES:  # 조사만 따로 떨어진 낱말("(연 3천 달러)으로")도 내용어가 아니다
        return None
    if "가" <= word[0] <= "힣":
        word = word[:2]
    return word.casefold()


def _content_stems(sentence: str) -> list[str]:
    """문장의 내용어 줄기. 끝의 조사는 떼고 남는 줄기가 두 글자 이상일 때만 뗀다(두 글자 명사의 끝 글자를 조사로 보지 않는다). 한글 낱말은 앞 두 글자만 쓴다(어미가 붙어도 하위 질문의 같은 낱말과 맞게).
    한 글자 낱말, 대명사·접속어, 서술어 조각(`_PREDICATE_FORMS`: 낱말 전체가 하다·되다·있다 계열의 활용형일 때)은 뺀다. 첫 글자가 같다고 서술어로 보지 않는다("해외", "하드웨어", "합의")."""
    return [s for s in (_stem(w) for w in _WORD.findall(sentence)) if s]


_ASK_WORDS = {"언제", "어디", "어디서", "어디에", "어디에서", "누가", "누구", "무엇", "무엇을", "뭐", "뭘", "어떻게", "얼마", "얼마나", "몇", "왜", "어느", "어떤", "무슨"}  # 묻는 말은 대상 구가 아니다
MAX_SUBJECT_CHARS = 60   # 앞머리 대상 구로 보는 최대 길이. 이보다 길면 붙이지 않는다


def keep_subject(question: str, subs: list[str]) -> list[str]:
    """`GRAPH_DECOMPOSE_KEEP_SUBJECT`의 코드 쪽 보정: 질문 문장(마지막 문장)의 앞머리 대상 구가 하위 질문에서 빠졌으면 그 구를 빠진 하위 질문 앞에 붙인다.
    앞머리 대상 구는 질문 문장에서 어느 하위 질문에든 나오는 첫 내용어 앞까지의 낱말이다(예: "해외 주문의 배송은 ... 반품 수수료는 ..."에서 "해외 주문의").
    그 구의 내용어가 어느 하위 질문에도 없을 때만 대상이 빠진 것으로 본다. 한 하위 질문에라도 남아 있으면 그 구가 한 사실에만 걸린 말일 수 있어(한국어 꾸밈 범위) 손대지 않고 프롬프트 규칙에 맡긴다. 맨 앞 회사 이름은 `drop_company_prefix`가 뺀 것이므로 구에 넣지 않는다.
    나뉘지 않았거나, 구가 없거나 묻는 말뿐이거나, 구가 `MAX_SUBJECT_CHARS`자를 넘거나, 붙이면 길이 한도를 넘으면 하위 질문을 그대로 돌려준다. LLM을 부르지 않는다."""
    if not subs:
        return subs
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split((question or "").strip()) if s.strip()]
    if not sentences:
        return subs
    last = _COMPANY_PREFIX.sub("", sentences[-1], count=1)
    joined = " ".join(subs).casefold()
    words = list(_WORD.finditer(last))
    cut = next((i for i, m in enumerate(words) if (st := _stem(m.group(0))) and st in joined), None)
    if not cut:   # 첫 낱말부터 하위 질문에 있거나(None 아님, 0), 어느 내용어도 하위 질문에 없다(None: 분해가 질문을 크게 바꿈, 판단하지 않는다)
        return subs
    head = [m for m in words[:cut] if m.group(0) not in _ASK_WORDS]
    stems = [st for m in head if (st := _stem(m.group(0)))]
    if not stems or any(st in joined for st in stems):
        return subs
    phrase = last[head[0].start():words[cut].start()].strip()
    if not phrase or len(phrase) > MAX_SUBJECT_CHARS:
        return subs
    out = [s if any(st in s.casefold() for st in stems) else f"{phrase} {s}" for s in subs]
    return out if all(len(s) <= MAX_SUB_CHARS for s in out) else subs


def keep_premise(question: str, subs: list[str]) -> list[str]:
    """원 질문이 두 문장 이상이고, 앞 문장(전제)의 내용어가 어느 하위 질문에도 없으면 모든 하위 질문 앞에 그 전제 문장을 붙인다(사전 등록 62.45).
    분해가 전제("외부 SaaS를 도입")를 하위 질문에서 빼거나 줄이면 첫 검색 문맥의 맨 위가 바뀌어 판정이 갈린다. LLM 호출과 프롬프트는 그대로이고 코드가 문장만 붙인다.
    전제는 물음이 아닌 앞 문장이다. 앞 문장이 물음(`?`)이면 그 문장은 하위 질문으로 나뉘어 이미 검색되므로 붙이지 않는다.
    나뉘지 않았거나(빈 목록), 한 문장이거나, 앞 문장에 물음이 있거나, 전제의 내용어가 하위 질문에 모두 있거나, 붙이면 길이 한도를 넘으면 하위 질문을 그대로 돌려준다."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split((question or "").strip()) if s.strip()]
    if not subs or len(sentences) < 2 or any(s.endswith(("?", "？")) for s in sentences[:-1]):
        return subs
    premise = " ".join(sentences[:-1])
    joined = " ".join(subs).casefold()
    if all(stem in joined for stem in _content_stems(premise)):
        return subs
    out = [f"{premise} {s}" for s in subs]
    return out if all(len(s) <= MAX_SUB_CHARS for s in out) else subs


# `GRAPH_KEEP_PRODUCT_NAME=1`(기본 꺼짐): 조사 없이 바로 제품의 대상(계정, 그룹, 프로젝트 등)을 꾸미는 "GitLab"은 회사가 아니라 제품을 가리키므로 떼지 않는다.
# 예: "GitLab 계정"은 GitLab.com 계정이다. "GitLab 정기 릴리스"(v1 3번)처럼 대상 말이 아닌 경우와 조사가 붙은 경우는 그대로 뗀다
_PRODUCT_TARGET = re.compile(
    r"^GitLab\s+(?:계정|account|그룹|group|프로젝트|project|저장소|repository|repo|인스턴스|instance|구독|subscription|"
    r"라이선스|license|사용자|user|네임스페이스|namespace|러너|runner)", re.I)


def keep_product_name_enabled() -> bool:
    """`GRAPH_KEEP_PRODUCT_NAME`이 1, true, yes, on이면 켬. 기본 꺼짐(#44 측정 구성)."""
    return (os.environ.get("GRAPH_KEEP_PRODUCT_NAME") or "").strip().lower() in {"1", "true", "yes", "on"}


def drop_company_prefix(subs: list[str]) -> list[str]:
    """하위 질문 맨 앞의 회사 이름을 뗀다. 모든 문서가 GitLab 핸드북이라 찾는 데 도움이 안 되고, 붙으면 개요 문서로 끌린다(평가셋 v1 3번).
    `GRAPH_KEEP_PRODUCT_NAME=1`이면 제품의 대상을 가리키는 "GitLab 계정" 같은 말은 남긴다."""
    keep = keep_product_name_enabled()
    out = [s.strip() if keep and _PRODUCT_TARGET.match(s.strip()) else _COMPANY_PREFIX.sub("", s, count=1).strip() for s in subs]
    return out if all(out) else subs


GATE_TASK = "decompose_gate"
SYSTEM_GATE = f"[[task:{GATE_TASK}]]\n{SYSTEM}"  # SP 예비 분해: 같은 프롬프트, 다른 표지(단계별 추론 수준을 따로 둘 수 있다. 기본은 전체 수준)


def _for_prompt(question: str) -> str:
    from backend.prompts.question import question_for_prompt   # 질문 속 가짜 자료 구획을 뺀 글(없으면 그대로)

    return question_for_prompt(question)


def gate_split(ask: Callable[[str, str], str], question: str) -> bool | None:
    """SP(`GRAPH_SPECULATE_FIRST`)의 예비 분해. 한 번만 부른다. 나누면 True, 나누지 않으면 False, 형식 오류·호출 오류면 None(미리 돌리지 않는다).
    결과는 검색에 쓰지 않는다. 미리 판정을 시작할지 고르는 데만 쓴다."""
    if not question or not question.strip():
        return None
    try:
        text = ask(system_prompt(GATE_TASK), _for_prompt(question))
    except Exception as e:  # noqa: BLE001  예비 분해가 실패하면 미리 돌리지 않을 뿐이다. 비용 상한은 그대로 올린다
        if type(e).__name__ == "CostCapExceeded":
            raise
        log.warning("예비 분해 호출 실패: %s", type(e).__name__)
        return None
    obj = parse_split(text)
    return None if obj is None else bool(normalize(question, obj))


def decompose_question(ask: Callable[[str, str], str], question: str) -> tuple[list[str], str]:
    """`ask(system, user) -> 응답 문자열`로 질문을 나눈다. (하위 질문 목록, 출처)를 돌려준다. 출처: llm | invalid | error | skipped."""
    if not question or not question.strip():
        return [], "skipped"
    source = "invalid"
    keep = keep_subject_enabled()
    system = system_prompt(TASK)
    for _ in range(ATTEMPTS):
        try:
            text = ask(system, _for_prompt(question))
        except Exception as e:  # noqa: BLE001  분해가 실패해도 검색은 원 질문 그대로 이어 간다. 비용 상한은 그대로 올린다
            if type(e).__name__ == "CostCapExceeded":
                raise
            log.warning("질문 분해 호출 실패: %s", type(e).__name__)
            source = "error"
            continue
        obj = parse_split(text)
        if obj is not None:
            subs = drop_company_prefix(normalize(question, obj))
            if keep:
                subs = keep_subject(question, subs)
            return keep_premise(question, subs), "llm"
        source = "invalid"
    return [], source
