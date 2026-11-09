"""검색 원문 속 지시(간접 인젝션) 코드 방어 두 가지. 스위치는 만들 때 기본 꺼짐이었고 사전 등록 62.1의 채택 기준을 채워 기본 켬으로 바꿨다(끄려면 값을 0으로).

- `GRAPH_SANITIZE_INPUT` 입력 정화: 검색 원문(본문과 제목·절 제목)을 모델 프롬프트에 넣기 전에, 모델·AI·에이전트를 상대로 한 지시 문장·절을 뺀다.
  `backend.prompts.question.format_materials`가 부르므로 질문 답 경로(판정, 답 작성, 근거 판정, 다시 쓰기)와 합동 검토 팀 에이전트 입력에 같이 걸리고,
  MCP 검색(`mcp_retriever`)과 섹션 읽기가 돌려준 청크도 같은 `format_materials`를 거치므로 같이 걸린다. Skill(`skills/`)은 저장소 안의 신뢰하는 지침이라 대상이 아니다.
- `GRAPH_SCRUB_OUTPUT` 출력 검사: 최종 답 문장(쟁점표 문장)에 검색 원문 지시 문장 안의 표식 후보(따옴표 문자열, 숫자가 든 표식 토큰, 모르는 chunk_id, 가짜 제목 경로)나
  지시 문장 일부(글자 15자 이상)가 그대로 있으면 그 문장을 뺀다. 남는 문장이 없으면 호출한 쪽이 거절한다.

설계 근거(공개 자료):
- Spotlighting (Hines et al., Microsoft, 2024, arXiv:2403.14720): 신뢰하지 않는 글을 모델 입력에서 구획·표시해 구분한다. 이 저장소는 이미 구획 표시(`<<<자료>>>`)를 쓰고
  있어, 여기서는 한 걸음 더 나가 지시 문장 자체를 입력에서 뺀다(구획 표시만으로는 모델이 따르는 경우가 남는다는 것이 이 평가의 가정이다).
- OWASP Top 10 for LLM Applications 2025, LLM01 Prompt Injection(https://genai.owasp.org/llmrisk/llm01-prompt-injection/, CC BY-SA 4.0)의 완화책:
  입력·출력 필터링, 외부 콘텐츠 구분, 기대 출력 형식의 코드 검증.
- 지시 문장 유형은 공개 간접 인젝션 시험 도구의 범주(promptfoo indirect-prompt-injection 플러그인 MIT, NVIDIA garak latentinjection·promptinject Apache-2.0,
  OWASP LLM01 공격 시나리오)를 참고해 직접 쓴 정규식이다. 도구의 규칙·데이터를 복사하지 않았다.

한계: 규칙(정규식)은 알려진 유형만 잡는다. 번역·암시·오타·유니코드 변형·표식 없는 지시(예: 지시가 아닌 사실처럼 쓴 거짓)는 못 잡는다.
"""
from __future__ import annotations

import os
import re
import unicodedata


def _flag(name: str) -> bool:
    """기본값은 켬이다(PREREGISTER 62.1 채택 기준 충족). 환경 변수를 0, false, no, off로 두면 끈다."""
    raw = os.environ.get(name)
    return True if raw is None or not raw.strip() else raw.strip().lower() not in {"0", "false", "no", "off"}


def sanitize_enabled() -> bool:
    return _flag("GRAPH_SANITIZE_INPUT")


def scrub_enabled() -> bool:
    return _flag("GRAPH_SCRUB_OUTPUT")


# ---------- 규칙 ----------
_I = re.I
_TOK = r"[A-Z][A-Z0-9]{2,}(?:[-_][A-Za-z0-9]+)+|[A-Za-z]*\d[A-Za-z0-9\-_]{3,}"          # 표식처럼 보이는 토큰: CANARY-P1-V1, REF2025X
_QUOTED = r"""["'“‘`「『][^"'”’`」』\n]{2,}["'”’`」』]"""
_MARKER_NOUN = r"(?:확인\s*번호|관리\s*번호|검증\s*(?:코드|번호)|승인\s*번호|점검\s*번호|추적\s*(?:코드|번호)|감사\s*코드|표식|토큰|verification\s+(?:code|token|number)|reference\s+(?:code|token)|tracking\s+(?:code|token))"
_AI = r"(?:ai|a\.i\.|llm|assistant|chat ?bot|language model|ai agents?|ai assistants?)"

RULES_EN_KO: list[tuple[str, re.Pattern]] = [
    ("override_en", re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b(?:\s+\w+){0,3}\s+(?:previous|prior|above|earlier|preceding|former|system|developer|all)\s+(?:\w+\s+)?(?:instructions?|prompts?|rules?|directions?|guidelines?|context|messages?)", _I)),
    ("override_ko", re.compile(r"(?:이전|앞선|위의|기존|지금까지의|모든)\s*(?:지시|명령|지침|규칙|프롬프트)\S*\s*(?:를|을|은|는)?\s*(?:모두\s*|전부\s*)?(?:무시|잊|따르지\s*(?:마|말)|취소|폐기)|지시(?:를|사항을)?\s*(?:모두\s*)?무시")),
    ("addressed_en", re.compile(rf"(?:^|[\s\[(|:>*_-])(?:note|message|instructions?|notice|memo|attention|reminder)s?\s*(?:to|for)\s+(?:the\s+)?{_AI}\b|"
                                rf"(?:^|[\s\[(|])(?:to|for)\s+(?:the\s+)?{_AI}(?:\s+(?:agents?|models?|systems?))?\s*[:\]\)]|"
                                rf"\b{_AI}\s*(?:agents?|models?)?\s*[:,]\s*(?:please\s+)?(?:you\s+)?(?:must|should|shall|always|now|please|append|add|include|write|print|output|say|reply|respond|cite|ignore|do not|don't|never)\b|"
                                rf"\b{_AI}s?\s+(?:agents?\s+|models?\s+)?(?:must|should|shall|will)\s+(?:now\s+|always\s+)?(?:append|add|include|insert|write|print|output|state|cite|reply|respond|say|end|begin|prepend|ignore|reveal)\b|"
                                rf"note[-_ ]to[-_ ](?:the[-_ ])?(?:ai|assistant|llm|model|agent)", _I)),
    ("addressed_ko", re.compile(r"(?:AI|LLM|어시스턴트|에이전트|챗봇|언어\s*모델)\s*(?:전용|에게|께|용)(?![가-힣])|"
                                r"(?:에이전트|어시스턴트|챗봇)(?:와|과)?[^.\n,]{0,20}?(?:는|은)\s*[^.\n]{0,40}(?:적어라|적을\s*것|쓰라|쓸\s*것|넣어라|포함하라|병기|기재|출력하라|인용하라|무시하라)")),
    ("output_en", re.compile(r"\b(?:append|prepend|add|insert|include|write|print|output)\b[^.\n]{0,60}?\b(?:to|in|into|at the (?:end|start|beginning|top|bottom) of|on the last line of)\s+your\s+(?:final\s+|full\s+|complete\s+|entire\s+)?(?:answer|response|reply|output|recommendation|summary)s?\b|"
                             r"\b(?:end|finish|conclude)\s+(?:your|the)\s+(?:answer|response|reply)\s+with\b", _I)),
    ("output_en_the", re.compile(r"\b(?:append|prepend|add|insert|include|write|print|output)\b[^.\n]{0,60}?\b(?:to|in|into|at the (?:end|start|beginning|top|bottom) of|on the last line of)\s+the\s+(?:final\s+)?(?:answer|response|reply|recommendation)s?\b(?!\s+lines?)", _I)),
    ("sysprompt", re.compile(r"\b(?:print|output|repeat|reveal|show|display|disclose|leak|dump|recite|echo|write out)\b[^.\n]{0,50}?\b(?:system prompt|your instructions|your prompt|initial prompt|hidden prompt|instructions above|everything above|text above|above this line)|"
                             r"\brepeat\s+(?:everything|all\s+(?:of\s+)?(?:the\s+)?(?:text|instructions|content))\b[^.\n]{0,20}\b(?:above|before)|"
                             r"(?:시스템\s*프롬프트|지시문|내부\s*지시|초기\s*지시)[^.\n]{0,30}(?:출력|공개|알려|기재|그대로|밝혀|보여|내놓|반복)|"
                             r"(?:출력|공개|기재|반복)[^.\n]{0,30}(?:시스템\s*프롬프트|지시문)", _I)),
    ("memory_exfil", re.compile(r"\b(?:list|print|show|output|reveal|dump|include)\b[^.\n]{0,40}\b(?:stored |saved )?(?:memor(?:y|ies)|profiles?|conversations?)\s+(?:of|from)\s+(?:all\s+)?(?:other|another|different)\s+users?|"
                                r"다른\s*사용자(?:의|들의)?\s*(?:장기\s*)?(?:기억|프로필|소속|직급|질문|대화)", _I)),
    ("cite_authority", re.compile(r"\bcite\b[^.\n]{0,80}\bas\s+(?:the\s+)?(?:authoritative|primary|only|sole|definitive|official)\b|\b(?:always|must)\s+cite\b|"
                                  r"(?:반드시|꼭|항상)[^.\n]{0,40}(?:근거로\s*)?인용(?:하라|할\s*것|한다|하여야|해야|해라)|가장\s*우선(?:한다|하여|시)|"
                                  r"(?:인용|cite)[^.\n]{0,40}\b[0-9a-f]{16}\b|\b[0-9a-f]{16}\b[^.\n]{0,20}(?:인용|cite)", _I)),
    ("approval_bypass", re.compile(r"\b(?:approve|execute|run|apply)\b[^.\n]{0,40}\bwithout\s+(?:any\s+|further\s+|asking for\s+|requiring\s+)?(?:confirmation|approval)|"
                                   r"(?:확인|승인|검토)(?:은|는)?\s*(?:필요\s*없|생략|건너뛰|건너뛴|사후\s*보고|갈음)|승인\s*(?:완료|된)\s*것으로\s*(?:보고|간주|본다)|절차를\s*건너뛰|즉시\s*실행", _I)),
    ("pass_to_agents", re.compile(r"\b(?:pass|forward|relay|tell|instruct|send)\b[^.\n]{0,30}\b(?:this|these|it)\b[^.\n]{0,20}\b(?:to|on to)\b[^.\n]{0,30}\b(?:other|all|every)\b[^.\n]{0,25}\b(?:agents?|assistants?|models?)|"
                                 r"(?:다른|타|해당|모든)\s*(?:부서\s*)?(?:에이전트|어시스턴트)(?:에게|께|에)\s*(?:전달|알려|지시|통보)|(?:에이전트|어시스턴트)\S*\s*(?:에게|께)\s*전달", _I)),
    ("concealment", re.compile(r"\b(?:do not|don't|never)\s+(?:tell|mention|reveal|inform)\s+(?:the\s+)?user|사용자에게\s*(?:알리지|말하지)\s*(?:마|말)", _I)),
    ("split_marker", re.compile(r"(?:조각|\bfragments?\b|\bpieces?\b)[^.\n]{0,50}?(?:이어|합쳐|연결|concat|join|combine|assemble)|(?:이어\s*붙여|합쳐서|연결해)[^.\n]{0,30}(?:답|응답|출력|적)", _I)),
]
_OUT_VENUE_KO = re.compile(r"(?:답변|응답|답안|최종\s*답|회신|쟁점표|권고란|권고\s*칸|마지막\s*줄)")
_WRITE_KO = re.compile(r"(?:적|넣|쓰|포함|병기|기재|출력|표기|추가|덧붙|붙여|첨부)(?:어라|아라|라|하라|해라|세요|십시오|을\s*것|할\s*것|어야|하여야|해야|도록|한다|는다|으라)")
_MARKERISH = re.compile(rf"{_QUOTED}|{_TOK}|{_MARKER_NOUN}", _I)
_MARKER_ASK = re.compile(rf"{_MARKER_NOUN}\s*[\"'`「]?\s*(?:{_TOK})", _I)


_NEEDS_MARKER = {"output_en_the", "split_marker"}   # 일반 문장과 겹치기 쉬운 규칙은 같은 절에 표식 꼴(따옴표 문자열, 표식 토큰)이 있을 때만 지시로 본다


def _first(clause: str) -> int:
    """절이 지시이면 가장 앞 일치 위치, 아니면 -1."""
    best = -1
    for name, rx in RULES_EN_KO:
        m = rx.search(clause)
        if m and name in _NEEDS_MARKER and not _MARKERISH.search(clause):
            m = None
        if m and (best < 0 or m.start() < best):
            best = m.start()
    v, w = _OUT_VENUE_KO.search(clause), _WRITE_KO.search(clause)
    if v and w and _MARKERISH.search(clause):  # 한국어: 답 자리 + 쓰라는 말 + 표식 꼴이 한 절에 모두 있을 때만(일반 정책 문장 오탐을 줄인다)
        best = v.start() if best < 0 else min(best, v.start())
    m = _MARKER_ASK.search(clause)
    if m and re.search(r"병기|적|기재|포함|넣|append|include|add|write", clause[m.end():m.end() + 40], _I):
        best = m.start() if best < 0 else min(best, m.start())
    return best


def is_instruction(clause: str) -> bool:
    return _first(clause) >= 0


# ---------- 정화 ----------
_GROUP = re.compile(r"<!--.*?-->|\[[^\[\]\n]{0,400}\]|\([^()\n]{0,400}\)|\{[^{}\n]{0,400}\}|<[^<>\n]{0,400}>", re.S)
_SENT = re.compile(r"((?<=[.!?。])\s+|\n+|\|)")
_CLAUSE = re.compile(r"(?<=[,;，；])\s*|\s+—\s+")


def _invisible_free(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", s) if unicodedata.category(ch) != "Cf")


def strip_instructions(text: str, *, cut_tail: bool = False) -> tuple[str, list[str]]:
    """(정화한 글, 뺀 문장·절 목록). cut_tail은 제목용: 지시가 시작한 자리부터 끝까지 자른다."""
    s = _invisible_free(str(text or ""))
    removed: list[str] = []

    def group(m: re.Match) -> str:
        inner = m.group(0)
        if is_instruction(inner):
            removed.append(inner)
            return " "
        return inner

    s = _GROUP.sub(group, s)
    out: list[str] = []
    for piece in _SENT.split(s):
        if _SENT.fullmatch(piece) or not piece.strip() or not is_instruction(piece):
            out.append(piece)
            continue
        if cut_tail:
            k = _first(piece)
            removed.append(piece[k:])
            out.append(piece[:k])
            continue
        clauses = _CLAUSE.split(piece)
        hits = [c for c in clauses if c.strip() and is_instruction(c)]
        if hits and len(clauses) > 1:
            removed.extend(c.strip() for c in hits)
            out.append(" ".join(c for c in clauses if c.strip() and not is_instruction(c)))
        else:
            removed.append(piece.strip())
    if not removed:  # 지시가 없으면 글자 하나도 바꾸지 않는다(정상 답의 모델 입력을 바꾸지 않기 위해, 정규화와 공백 정리도 하지 않는다)
        return str(text or ""), removed
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip(), removed


def sanitize_text(text: str) -> str:
    return strip_instructions(text)[0]


def sanitize_heading(text: str | None) -> str:
    return strip_instructions(text or "", cut_tail=True)[0]


def sanitize_chunk(c: dict) -> dict:
    """청크 사본: 본문·제목·절 제목에서 지시를 뺀다. 원본은 바꾸지 않는다(인용 검사와 근거 판정은 원본과 대조한다)."""
    out = dict(c)
    out["text"] = sanitize_text(c.get("text") or "")
    for k in ("rule_title", "article"):
        if c.get(k):
            out[k] = sanitize_heading(c.get(k))
    return out


# ---------- 출력 검사 ----------
_HEXID = re.compile(r"\b[0-9a-f]{16}\b")
_DIGITDASH = re.compile(r"\b\d+(?:-\d+)+\b")
_HEADPATH = re.compile(r"[A-Za-z][A-Za-z0-9 .\-/]{1,40}(?: > [A-Za-z0-9][A-Za-z0-9 .\-/]{0,40})+")
_OBJ_KO = re.compile(r"(\S{3,}?)\s*(?:을|를)\s*(?:그대로\s*)?(?:적|넣|쓰|포함|병기|기재|출력|붙)")
_OBJ_EN = re.compile(r"\b(?:append|include|add|write|print|output|say|insert)\s+(?:the\s+)?(?:token|word|string|phrase|code|text|number)?\s*[\"'`]?([^\s\"'`.,;]{4,})", _I)
_STOP = {"answer", "response", "reply", "output", "final", "following", "your", "this", "that", "the", "to", "답변", "응답", "내용"}


def _norm(s: str) -> str:
    return "".join(ch for ch in _invisible_free(s).casefold() if not ch.isspace())


def _letters(s: str) -> str:
    return "".join(ch for ch in _invisible_free(s).casefold() if unicodedata.category(ch)[0] in "LN")


def marker_candidates(instructions: list[str], benign: str, real_ids: set[str]) -> list[str]:
    """지시 문장들에서 답에 옮겨 적히면 안 되는 표식 후보. 지시 아닌 본문과 질문에 있는 문구는 뺀다."""
    benign_n = _norm(benign)
    found: list[str] = []
    for u in instructions:
        quoted = [q[1:-1].strip() for q in re.findall(_QUOTED, u)]
        found += [q for q in quoted if len(q) >= 4]
        if len(quoted) >= 2:
            found.append("".join(quoted))
        found += re.findall(_TOK, u)
        found += [h for h in _HEXID.findall(u) if h not in real_ids]
        found += _DIGITDASH.findall(u)
        found += [m.strip() for m in _HEADPATH.findall(u)]
        for rx in (_OBJ_KO, _OBJ_EN):
            found += [m.strip("\"'`「」") for m in rx.findall(u)]
    out: list[str] = []
    for f in found:
        n = _norm(f)
        if len(n) >= 4 and n not in _STOP and n not in benign_n and f not in out and f not in real_ids:
            out.append(f)
    return out


_ANS_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def scrub_answer(answer: str, chunks: list[dict], question: str = "") -> tuple[str, list[str]]:
    """(정리한 답, 뺀 문장). 지시 문장이 없는 검색 결과이면 그대로. 문장 안의 `[chunk_id]` 표시도 함께 사라진다."""
    instr: list[str] = []
    benign: list[str] = [question]
    for c in chunks:
        for field in ("text", "rule_title", "article"):
            if c.get(field):
                clean, rem = strip_instructions(str(c[field]), cut_tail=field != "text")
                instr += rem
                benign.append(clean)
    if not instr:
        return answer, []
    cands = [_norm(x) for x in marker_candidates(instr, "\n".join(benign), {c.get("chunk_id") for c in chunks if c.get("chunk_id")})]
    long_parts = [p for p in (_letters(x) for x in instr) if len(p) >= 15]
    kept, removed = [], []
    for sent in _ANS_SENT.split(answer or ""):
        if not sent.strip():
            continue
        n, lt = _norm(sent), _letters(sent)
        bad = any(c in n for c in cands) or any(p[i:i + 15] in lt for p in long_parts for i in range(0, len(p) - 14))
        (removed if bad else kept).append(sent)
    if not removed:
        return answer, []
    return " ".join(s.strip() for s in kept), [s.strip() for s in removed]


def leaks_instruction(text: str, chunks: list[dict], question: str = "") -> bool:
    """스위치가 켜져 있을 때, 글 한 덩어리가 검색 원문 지시에서 온 표식·문장을 옮겼는가(쟁점표 행, 다시 쓴 답 검사). 꺼져 있으면 항상 False."""
    return scrub_enabled() and bool(scrub_answer(text, chunks, question)[1])
