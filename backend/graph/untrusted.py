"""검색 원문 속 지시(간접 인젝션) 코드 방어 두 가지. 스위치는 만들 때 기본 꺼짐이었고 사전 등록 62.1의 채택 기준을 채워 기본 켬으로 바꿨다(끄려면 값을 0으로).

- `GRAPH_SANITIZE_INPUT` 입력 정화: 검색 원문(본문과 제목·절 제목·절 이름)을 모델 프롬프트에 넣기 전에, 모델·AI·에이전트를 상대로 한 지시 문장·절을 뺀다.
  `backend.prompts.question.format_materials`가 부르므로 질문 답 경로(판정, 답 작성, 근거 판정, 다시 쓰기)와 합동 검토 팀 에이전트 입력에 같이 걸리고,
  MCP 검색(`mcp_retriever`)과 섹션 읽기가 돌려준 청크도 같은 `format_materials`를 거치므로 같이 걸린다. Skill(`skills/`)은 저장소 안의 신뢰하는 지침이라 대상이 아니다.
  `format_materials`를 거치지 않고 원문이 모델에 들어가는 길도 같은 정화를 부른다(사전 등록 62.26): 재작성 입력의 이미 찾은 문서 제목(`prompts/question.py seen_titles`),
  결정표 변환 초안 입력의 권한표 칸(`graph/decision/convert.py`, `sanitize_cell`), 리콜 판정 입력의 개정 전후 본문과 섹션 제목(`graph/recall/notice.py recall_user`).
- `GRAPH_SCRUB_OUTPUT` 출력 검사: 최종 답 문장(쟁점표 문장)에 검색 원문 지시 문장 안의 표식 후보(따옴표 문자열, 숫자가 든 표식 토큰, 모르는 chunk_id, 가짜 제목 경로)나
  지시 문장 일부(글자 15자 이상)가 그대로 있으면 그 문장을 뺀다. 남는 문장이 없으면 호출한 쪽이 거절한다.
  모델이 쓴 글이 사용자에게 나가는 길은 모두 이 검사를 거친다: 답과 다시 쓴 답(`graph/build.py`), 되묻기 문장(`give_up`), 쟁점 문장과 topic 칸(`graph/departments/issue_table.py`),
  리콜 알림 설명(`graph/recall/notice.py guard_explanation`).

설계 근거(공개 자료):
- Spotlighting (Hines et al., Microsoft, 2024, arXiv:2403.14720): 신뢰하지 않는 글을 모델 입력에서 구획·표시해 구분한다. 이 저장소는 이미 구획 표시(`<<<자료>>>`)를 쓰고
  있어, 여기서는 한 걸음 더 나가 지시 문장 자체를 입력에서 뺀다(구획 표시만으로는 모델이 따르는 경우가 남는다는 것이 이 평가의 가정이다).
- OWASP Top 10 for LLM Applications 2025, LLM01 Prompt Injection(https://genai.owasp.org/llmrisk/llm01-prompt-injection/, CC BY-SA 4.0)의 완화책:
  입력·출력 필터링, 외부 콘텐츠 구분, 기대 출력 형식의 코드 검증.
- 지시 문장 유형은 공개 간접 인젝션 시험 도구의 범주(promptfoo indirect-prompt-injection 플러그인 MIT, NVIDIA garak latentinjection·promptinject Apache-2.0,
  OWASP LLM01 공격 시나리오)를 참고해 직접 쓴 정규식이다. 도구의 규칙·데이터를 복사하지 않았다.

일반화(PREREGISTER 62.5): 단어·어미 목록에 맞는 문장만 잡던 한국어 규칙 둘(답 자리+쓰기 어미, 표식 명사+동사)을 한 절에 든 특징의 조합(내용, 행위, 대상 참조) 판정 하나로 바꿨다.
출력 검사는 입력 쪽이 못 본 글에도 답에 토큰이 그대로 옮겨졌을 때는 막도록 의심 절(토큰과 출력 자리·목적 이름표) 단서를 더했다. 자세한 구조는 아래 구조 판정 절 주석.

보강(PREREGISTER 62.48, 새 인젝션 40건): 본문 속 `[chunk_id]` 인용 표시가 든 문장은 입력에서 뺀다(가짜 인용). 묻는 사람에게 전하라는 문장(전달 지시)의
외부 주소와 같은 글의 값을 바꾸라는 값, 검색 원문에 없는 주소는 답에서 뺀다. 규칙이 읽지 못하는 문자(가나·한자·키릴 등)로 쓴 글의 표식 토큰과
인코딩(base64·16진수·퍼센트·태그 문자)해 숨긴 지시의 표식은 출력 검사 후보로 둔다. 질문에 지시 문장이 있으면 질문의 따옴표 문자열·표식 꼴도 후보다.

한계: 규칙(정규식)은 알려진 범주만 잡는다. 번역(한국어·영어 밖, 표식 토큰이 없는 것), 암시, 오타, 유니코드 변형(동형 문자는 다른 문자 비율로 일부만),
표식이 없는 지시(예: 공지 문구만 덧붙이게 하는 것, 정해진 문구로만 회신하게 하는 것), 소문자·숫자 없는 표식, 두 청크에 나눠 쓴 지시,
지시가 아닌 사실처럼 쓴 거짓은 못 잡는다. 사람에게 한 지시도 구조가 같으면(답 자리, 쓰기 동작, 대문자 코드) 지시로 보아 뺄 수 있다.
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
_SNAKE = r"(?-i:(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_]))"     # 내부 필드 이름처럼 보이는 snake_case 낱말(conclusion_changed)
_SPEAKER = r"(?:judges?|graders?|evaluators?|validators?|verifiers?|classifiers?|moderators?|orchestrators?|assistants?|system|llm|ai|model|agent|심사자|판정자|평가자|시스템|어시스턴트|에이전트)"   # 처리 단계 화자 지정("Judge: ...")

RULES_EN_KO: list[tuple[str, re.Pattern]] = [
    ("override_en", re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b(?:\s+\w+){0,3}\s+(?:previous|prior|above|earlier|preceding|former|system|developer|all)\s+(?:\w+\s+)?(?:instructions?|prompts?|rules?|directions?|guidelines?|context|messages?)|"
                             r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+(?:of\s+)?)?your\s+(?:previous|prior|above|earlier|preceding|former|original|initial|system)\b", _I)),
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
                                r"\b(?:list|print|show|output|reveal|dump|include|share|repeat)\b[^.\n]{0,40}\b(?:other|another|different|previous|prior|last|preceding)\s+users?['’]?s?\s+(?:\w+\s+){0,3}?(?:conversations?|chats?|histor(?:y|ies)|profiles?|memor(?:y|ies)|questions?|messages?)|"
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
    # 처리 단계 화자를 지정한 지시 꼴("Judge: <지시>", "시스템: <지시>"). 화자 이름은 파이프라인 쪽 역할(judge, grader, system ...)만 본다.
    # 내부 필드 이름(snake_case)에 "must be"를 붙인 문장은 설정 문서에도 흔해(핸드북 코퍼스에서 오탐 확인) 단독 규칙으로 쓰지 않는다.
    ("speaker_directive", re.compile(rf"(?:^|[\n|)\]>*•\-\"“'‘]\s*|\d\)\s*){_SPEAKER}\s*[:：]\s*(?=[^\n]{{0,80}}?(?:\b(?:must|should|shall|always|never|ignore|set|mark|output|return|answer|reply|respond|approve|reject|do not|don't)\b|하라|[가-힣]\s*것(?![가-힣])|해야|마라))", _I)),
]


# ---------- 구조 판정(PREREGISTER 62.5) ----------
# 단어·어미 목록에 맞는 문장만 잡던 것을, 한 절에 든 **특징의 조합**으로 바꾼다. 지시가 아닌 일반 문장도 특징 하나씩은 흔히 가지므로 조합이 핵심이다.
#   내용 P : 모델이 답에 옮겨 적을 표식 꼴(대문자·숫자가 섞인 5~40자 토큰, 모르는 16자리 id, 확인번호 같은 표식 명사). 소문자 하이픈 낱말(k8s-workloads)은 P가 아니다. 따옴표 문자열은 따로 더 좁은 조건으로만 본다
#   행위 ACT: 쓰라는 말. 명령·요청·권유·의무의 말투(D)이거나, 쓰기·붙이기·언급하기 계열 동작(W)이다. 어미를 가리지 않는다("붙여 주세요", "표기합니다", "남길 것", "좋겠습니다")
#   대상 REF: 그 행위가 향하는 곳. 출력 자리(V: 답·응답·요약·의견 칸·마지막 줄), 글을 읽고 처리하는 쪽의 호칭(A: 시스템·검토자·assistant), 표식 앞의 목적 이름표(L: 확인번호·일련번호·조회 코드·verification code. 그냥 ID나 key는 아니다)
# 입력 정화는 P 앞뒤 `_WIN`자 안에 ACT와 REF가 모두 있을 때만 지시로 본다(먼 곳의 일반 문장과 짝지어지지 않게 한다).
# 출력 검사는 입력 쪽이 놓친 글에 대비해 P(토큰)와 REF만 있어도 "의심 절"로 모은다. 답에 그 토큰이 그대로 옮겨졌다는 둘째 증거가 있을 때만 쓰기 때문이다.
_WIN = 60
_WIN_Q = 30
_QUOTED_RX = re.compile(_QUOTED)
_CODE = (r"(?-i:(?<![A-Za-z0-9@_\-])(?=[A-Z0-9_\-]{5,40}(?![A-Za-z0-9_\-@]))(?=[A-Z0-9_\-]*\d)(?=[A-Z0-9_\-]*[A-Z])"
         r"[A-Z0-9]+(?:[-_][A-Z0-9]+)*(?![A-Za-z0-9]))")
_HEX16 = r"(?-i:(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f]))"
_P_TOKEN = re.compile(_CODE + "|" + _HEX16)
_P_ANY = re.compile(_CODE + "|" + _HEX16 + "|" + _MARKER_NOUN, _I)
_D = re.compile(
    r"(?:어라|아라|하라|해라|세요|십시오|주십시오|주시기|주시길|해\s*달라|바랍니다|바란다|바라며|부탁|좋겠|좋습니다|어야|아야|하여야|해야|야\s*한다|야\s*합니다|"
    r"(?:주시면|주신다면)\s*(?:감사|고맙)|"   # 사의(謝意)로 바꿔 말한 요청("남겨 주시면 감사하겠습니다")
    r"[을를할길줄]\s*것|도록|원칙|권장|필수|요청)|"
    r"\b(?:please|kindly|must|should|shall|ought\s+to|needs?\s+to|has\s+to|have\s+to|required\s+to|expected\s+to|make\s+sure|be\s+sure\s+to|ensure|remember\s+to|recommended|always|never)\b", _I)
_W = re.compile(
    r"(?:적(?:어|은|을|는|고|으|게)|쓰(?:라|세|십|고|도|는|며|면|시|기)|쓸|써(?:라|\s*주)|넣|붙(?:여|이|인|으|은|도|는|고)|남[기길겨]|올[리려]|기입|기재|표기|병기|표시|포함|첨부|출력|언급|명시|추가|덧붙|삽입|부기|명기|제시|기록|곁들)|"
    r"\b(?:append|prepend|add|insert|include|write|print|say|state|mention|cite|quote|echo|tag|mark|stamp|attach|embed|put|leave|repeat|restate|set|override|overwrite|assign|replace|(?:end|close|finish|conclude)s?\s+with)\b", _I)
_V_NOUN = (r"답변|응답|답안|회신|요약(?:본|문|의)?|쟁점표|권고\s*[란칸]|의견\s*[란칸]|"
           r"\b(?:answers?|responses?|repl(?:y|ies)|summar(?:y|ies)|(?:opinion|recommendation)\s+(?:field|column))\b")
_V_POS = (r"의견(?=\s*(?:끝|말미|마지막))|(?:맨\s*)?말미|마지막\s*(?:줄|문장|행)|맨\s*끝|끝에|서두|맨\s*앞|첫\s*(?:줄|문장|행)|첫머리|앞머리|"
          r"\b(?:(?:last|final|first|opening)\s+(?:line|sentence)|(?:end|start|beginning|top)\s+of\s+(?:the|your)|at\s+the\s+(?:end|start|beginning|top))\b")
_V = re.compile(_V_NOUN + "|" + _V_POS, _I)
_V_ONLY_NOUN = re.compile(_V_NOUN, _I)
_A = re.compile(
    r"(?:시스템|모델|어시스턴트|에이전트|챗봇|요약하는|요약기|요약자|검토자|리뷰어|답변자|답변하는|안내하는|담당자|독자|읽는|읽고)|"
    r"\b(?:assistants?|agents?|llms?|ai|chat\s?bots?|bots?|models?|systems?|summari[sz]ers?|summari[sz]es|summari[sz]ing|reviewers?|readers?|whoever|anyone)\b", _I)
_L = re.compile(
    r"(?:(?:확인|관리|검증|승인|점검|추적|감사|조회|열람|일련|식별|수신|인증|발급)\s*(?:번호|코드|값|표식|토큰)|표식|토큰|\bmarker\b|\bstamp\b|\btoken\b|\bcode\s?word\b|\bpass\s?phrase\b|\bphrase\b|"
    r"(?:verification|tracking|audit|serial|confirmation|reference|access|authentication|validation|check)\s+(?:code|token|number|id|tag|key|string))"
    r"\s*[:：=]?\s*[\"'`「『(\[]?\s*(?:" + _CODE + "|" + _HEX16 + ")", _I)
# 시스템 내부 상태를 가리키는 말(S): 전체를 가리키는 수량어 + 승인자·판정·행 같은 내부 대상, snake_case 필드 이름, "모두 승인으로 표시" 꼴. 표식 토큰(P)과 쓰기 동작(ACT)이 같이 있을 때만 REF로 센다.
_S = re.compile(
    r"\b(?:every|all|each|any)\s+(?:the\s+)?(?:approvers?|reviewers?|judges?|verdicts?|rows?|cells?|fields?|columns?|entries|records?|owners?|statuses|decisions?)\b|"
    r"\bmark(?:ed|ing)?\s+(?:it|them|this|these|everything|all\b[^.\n]{0,20}?)\s+(?:as\s+)?(?:approved|passed|valid|verified|safe|true|false)\b|"
    r"(?:모든|각|전체)\s*(?:승인자|검토자|판정|행|셀|필드|열|결재선)|" + _SNAKE, _I)
_MARKERISH = re.compile(rf"{_QUOTED}|{_TOK}|{_MARKER_NOUN}", _I)


def _window(clause: str, p: re.Match) -> tuple[str, int]:
    lo = max(0, p.start() - _WIN)
    return clause[lo:p.end() + _WIN], lo


def _structure_start(clause: str) -> int:
    """P 가까이(앞뒤 `_WIN`자)에 ACT와 REF가 모두 있으면 REF·ACT 가운데 가장 앞 위치, 아니면 -1."""
    for p in _P_ANY.finditer(clause):
        w, lo = _window(clause, p)
        act = [m for m in (_D.search(w), _W.search(w)) if m]
        ref = [m for m in (_V.search(w), _A.search(w), _L.search(w), _S.search(w)) if m]
        if act and ref:
            return lo + min(m.start() for m in act + ref)
    for q in _QUOTED_RX.finditer(clause):   # 따옴표 문자열만 있는 표식은 일반 글에 흔하므로 더 좁게: 아주 가까이에 말투, 쓰기 동작, 출력 자리가 모두 있어야 한다
        w = clause[max(0, q.start() - _WIN_Q):q.end() + _WIN_Q]
        d, v, k = _D.search(w), _V_ONLY_NOUN.search(w), _W.search(w)
        if d and v and k:
            return max(0, q.start() - _WIN_Q) + min(d.start(), v.start(), k.start())
    return -1


def is_suspect(clause: str) -> bool:
    """출력 검사용 의심 절: 토큰 P 가까이에 출력 자리(V)나 목적 이름표(L)만 있으면 된다(ACT 불필요). 입력 정화보다 문턱이 낮다. 호칭(A)은 일반 글에 너무 흔해 뺀다."""
    for p in _P_TOKEN.finditer(clause):
        w, _ = _window(clause, p)
        if _V.search(w) or _L.search(w) or len(_OTHER_SCRIPT.findall(w)) >= _MIN_OTHER_SCRIPT:
            return True
    return False


# 규칙이 읽지 못하는 문자(가나, 한자, 키릴, 그리스, 아랍, 히브리, 태국, 데바나가리)로 쓴 글 안의 표식 토큰은 지시인지 판정할 수 없으므로 출력 검사에서만 의심 절로 둔다.
# 입력은 바꾸지 않는다. 답에 그 토큰이 그대로 옮겨졌을 때만 그 문장을 뺀다.
_OTHER_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\u0400-\u04ff\u0370-\u03ff\u0600-\u06ff\u0590-\u05ff\u0e00-\u0e7f\u0900-\u097f]")
_MIN_OTHER_SCRIPT = 4

# ---------- 본문 속 인용 표시, 주소, 전달 지시 ----------
# 본문 속 `[16자리 hex]`: 정상 원문은 chunk_id를 대괄호로 적지 않는다(코퍼스 23,095청크 0건). 모델이 그 표시를 문장째 옮기면 다른 청크의 인용으로 통과하므로 그 문장을 입력에서 뺀다.
_EMBED_CITE = re.compile(r"\[([0-9a-f]{16})\]")
_FORGED_WIN = 8
_ADDR = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+|(?:https?://|www\.)[^\s<>\"'`)\]}]+", _I)
_VALUE = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(분|시간|일|주|개월|달|년|원|달러|%|퍼센트|건|회|명|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|percent|usd|dollars?)(?![A-Za-z])", _I)
# 전달 지시: 묻는 사람에게 무엇이라고 전하라는 말(안내 문구, 회신, tell users, when asked). 사실을 적은 문장이 아니라 답하는 쪽의 말을 정하는 문장이다.
_TELL = re.compile(
    r"(?:대외\s*안내|안내\s*문구|말씀드린|안내(?:한다|합니다|하도록|하라|할\s*것|해\s*(?:주|드))|(?:회신|답변|응대|통지|고지)(?:한다|합니다|하도록|하라|할\s*것|하실))|"
    r"\b(?:tell|inform|advise|notify|instruct|direct|refer|point)\s+(?:the\s+)?(?:users?|customers?|requesters?|askers?|callers?|them|everyone|anyone|people)\b|"
    r"\bwhen\s+(?:asked|answering|responding|replying)\b|\b(?:answer|respond|reply)\s+(?:with|that)\b|\bin\s+(?:your|all|any|every)\s+(?:answers?|responses?|replies)\b", _I)
# 같은 글의 값을 가리켜 바꾸는 말(위 기준을, 대신, instead of): 전달 지시와 같이 있을 때만 값을 후보로 본다
_OVERRIDE_REF = re.compile(
    r"(?:위|상기|앞의|본|해당)\s*(?:기준|값|수치|기한|시간|한도|금액|내용|규정)|위\s*\d|대신|통일|"
    r"\binstead\s+of\b|\brather\s+than\b|\bregardless\s+of\b|\b(?:above|stated|documented|official|actual)\s+(?:value|limit|deadline|figure|number|time(?:frame)?|sla|policy|rule)\b", _I)


def _host(addr: str) -> str:
    a = addr.casefold().rstrip(".,;:!?")
    if "@" in a and "://" not in a:
        return a.rsplit("@", 1)[1]
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", a).split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]


def _site(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def tell_candidates(sentence: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(주소 후보, (숫자, 단위) 후보). 전달 지시가 든 문장의 주소, 그리고 같은 글의 값을 가리켜 바꾸는 말이 같이 있을 때 그 문장의 값."""
    if not _TELL.search(sentence):
        return [], []
    values = [(n.replace(",", ""), u.casefold()) for n, u in _VALUE.findall(sentence)] if _OVERRIDE_REF.search(sentence) else []
    return [m.group(0).rstrip(".,;:!?") for m in _ADDR.finditer(sentence)], values


def _has_value(norm_sentence: str, number: str, unit: str) -> bool:
    return bool(re.search(rf"(?<![\d.,]){re.escape(number)}{re.escape(unit)}", norm_sentence.replace(",", "")))


# ---------- 인코딩해 숨긴 지시 ----------
# base64, 16진수, 퍼센트 인코딩, 유니코드 태그 문자(화면에 안 보임)로 싼 글은 규칙이 읽지 못한다. 모델은 풀 수 있으므로 출력 검사에서만 풀어 본다.
# 푼 글이 지시이면 그 지시의 표식은 답에 옮기면 안 되는 후보다. 입력은 바꾸지 않는다(푼 글을 모델에 넣지 않는다). 풀리지 않거나 UTF-8 글이 아니면 버린다.
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}")
_HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){16,}(?![0-9A-Fa-f])")
_PCT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2}){8,}")
_TAG_RUN = re.compile("[\U000E0020-\U000E007E]{8,}")


def hidden_instructions(text: str) -> list[str]:
    """글 속 인코딩 문자열을 푼 글 가운데 지시(`is_instruction`)인 것. 코드 검사이고 LLM을 부르지 않는다."""
    import base64
    import binascii
    from urllib.parse import unquote_to_bytes

    s = str(text or "")
    decoded = ["".join(chr(ord(ch) - 0xE0000) for ch in m.group(0)) for m in _TAG_RUN.finditer(s)]
    decoded += [t for t in (_utf8(unquote_to_bytes(m.group(0))) for m in _PCT_RUN.finditer(s)) if t]
    for m in _HEX_RUN.finditer(s):
        t = _utf8(bytes.fromhex(m.group(0)))
        if t:
            decoded.append(t)
    for m in _B64_RUN.finditer(s):
        body = m.group(0).rstrip("=")
        try:
            t = _utf8(base64.b64decode(body + "=" * (-len(body) % 4), validate=True))
        except (binascii.Error, ValueError):
            continue
        if t:
            decoded.append(t)
    return [t for t in decoded if is_instruction(t)]


def _utf8(raw: bytes) -> str:
    """UTF-8로 읽히고 제어 문자가 없는 글만(우연히 풀린 바이트를 버린다)."""
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return t if t.strip() and not any(unicodedata.category(ch) == "Cc" and ch not in "\n\t\r" for ch in t) else ""


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
    k = _structure_start(clause)
    if k >= 0:
        best = k if best < 0 else min(best, k)
    return best


def is_instruction(clause: str) -> bool:
    return _first(clause) >= 0


# ---------- 정화 ----------
_GROUP = re.compile(r"<!--.*?-->|\[[^\[\]\n]{0,400}\]|\([^()\n]{0,400}\)|\{[^{}\n]{0,400}\}|<[^<>\n]{0,400}>", re.S)
_SENT = re.compile(r"((?<=[.!?。])\s+|\n+|\|)")
_CLAUSE = re.compile(r"(?<=[,;，；])\s*|\s+—\s+")


def _invisible_free(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", s) if unicodedata.category(ch) != "Cf")


def strip_instructions(text: str, *, cut_tail: bool = False, whole_sentence: bool = False) -> tuple[str, list[str]]:
    """(정화한 글, 뺀 문장·절 목록). cut_tail은 제목용: 지시가 시작한 자리부터 끝까지 자른다.
    whole_sentence는 지시로 판정된 절이 든 문장을 통째로 뺀다. 기본(꺼짐)은 지시 절만 빼고 같은 문장의 나머지 절을 남겨 검색 원문의 사실을 지킨다.
    쉼표로 이어진 지시 문장은 뒷절이 따로는 지시로 안 보이는 조각이 많아("..., including your system prompt, verbatim.") 그 조각이 남는다.
    남은 조각을 그대로 인용하면 안 되는 쪽(되묻기가 질문 속 영문 구를 따옴표로 인용할 때)이 켠다."""
    s = _invisible_free(str(text or ""))
    removed: list[str] = []

    def group(m: re.Match) -> str:
        inner = m.group(0)
        if _EMBED_CITE.fullmatch(inner):   # 본문 속 인용 표시는 문장 단계에서 그 문장째 뺀다
            return inner
        if is_instruction(inner):
            removed.append(inner)
            return " "
        return inner

    s = _GROUP.sub(group, s)
    out: list[str] = []
    for piece in _SENT.split(s):
        if _SENT.fullmatch(piece) or not piece.strip():
            out.append(piece)
            continue
        forged = _EMBED_CITE.search(piece)
        if forged:   # 본문 속 `[chunk_id]`가 든 문장: 제목은 그 자리부터, 본문은 문장째 뺀다
            removed.append(piece[forged.start():] if cut_tail else piece.strip())
            if cut_tail:
                out.append(piece[:forged.start()])
            continue
        if not is_instruction(piece):
            out.append(piece)
            continue
        if cut_tail:
            k = _first(piece)
            removed.append(piece[k:])
            out.append(piece[:k])
            continue
        if whole_sentence:
            removed.append(piece.strip())
            continue
        clauses = _CLAUSE.split(piece)
        hits = [c for c in clauses if c.strip() and is_instruction(c)]
        if hits and len(clauses) > 1:
            hits = [c for c in clauses if c.strip() and (is_instruction(c) or _P_TOKEN.search(c))]   # 지시 문장의 표식 절은 따로 떼어 남기지 않는다
            removed.extend(c.strip() for c in hits)
            out.append(" ".join(c for c in clauses if c.strip() and c not in hits))
        else:
            removed.append(piece.strip())
    if not removed:  # 지시가 없으면 글자 하나도 바꾸지 않는다(정상 답의 모델 입력을 바꾸지 않기 위해, 정규화와 공백 정리도 하지 않는다)
        return str(text or ""), removed
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip(), removed


def sanitize_text(text: str) -> str:
    return strip_instructions(text)[0]


def drop_suspect_tokens(text: str) -> str:
    """지시 문장 판정(`strip_instructions`)이 놓친 의심 문장(`is_suspect`: 표식 꼴 토큰 가까이에 출력 자리나 목적 이름표)에서 그 토큰만 뺀다.
    되묻기가 질문 속 문자열을 인용하기 전에 쓴다. 의심 문장이 없으면 글자 하나도 바꾸지 않는다."""
    pieces = _SENT.split(text or "")
    changed = False
    for i, piece in enumerate(pieces):
        if i % 2 == 0 and piece.strip() and is_suspect(piece):
            pieces[i] = _P_TOKEN.sub(" ", piece)
            changed = changed or pieces[i] != piece
    return "".join(pieces) if changed else (text or "")


def sanitize_heading(text: str | None) -> str:
    return strip_instructions(text or "", cut_tail=True)[0]


def sanitize_chunk(c: dict) -> dict:
    """청크 사본: 본문·제목·절 제목·절 이름(org)에서 지시를 뺀다. 원본은 바꾸지 않는다(인용 검사와 근거 판정은 원본과 대조한다)."""
    out = dict(c)
    out["text"] = sanitize_text(c.get("text") or "")
    for k in ("rule_title", "article", "org"):
        if c.get(k):
            out[k] = sanitize_heading(c.get(k))
    return out


def sanitize_cell(value: object) -> object:
    """권한표 칸 같은 짧은 칸 하나. 문자열이면 제목처럼 지시가 시작한 자리부터 자르고, 문자열이 아니면(숫자, 목록, 비어 있음) 그대로 돌려준다.
    스위치(`GRAPH_SANITIZE_INPUT`)가 꺼져 있으면 아무것도 바꾸지 않는다. 지시가 없는 칸은 글자 하나도 바꾸지 않는다."""
    if not sanitize_enabled() or not isinstance(value, str):
        return value
    return sanitize_heading(value)


# ---------- 출력 검사 ----------
_HEXID = re.compile(r"\b[0-9a-f]{16}\b")
_DIGITDASH = re.compile(r"\b\d+(?:-\d+)+\b")
_HEADPATH = re.compile(r"[A-Za-z][A-Za-z0-9 .\-/]{1,40}(?: > [A-Za-z0-9][A-Za-z0-9 .\-/]{0,40})+")
_OBJ_KO = re.compile(r"(\S{3,}?)\s*(?:을|를)\s*(?:그대로\s*)?(?:적|넣|쓰|포함|병기|기재|출력|붙)")
_OBJ_EN = re.compile(r"\b(?:append|include|add|write|print|output|say|insert)\s+(?:the\s+)?(?:token|word|string|phrase|code|text|number|line)?\s*[\"'`]?([^\s\"'`.,;]{4,})", _I)
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
    return _keep_new(found, benign_n, real_ids)


def _keep_new(found: list[str], benign_n: str, real_ids: set[str]) -> list[str]:
    out: list[str] = []
    for f in found:
        n = _norm(f)
        if len(n) >= 4 and n not in _STOP and n not in benign_n and f not in out and f not in real_ids:
            out.append(f)
    return out


def split_suspects(text: str) -> tuple[str, list[str]]:
    """(의심 절을 뺀 나머지, 의심 절 목록). 문장 단위. 입력 정화가 지시로 보지 못한 글에서 출력 검사가 쓸 단서를 모은다."""
    keep, sus = [], []
    for piece in _SENT.split(_invisible_free(text)):
        (sus if is_suspect(piece) else keep).append(piece)
    return "".join(keep), sus


def suspect_candidates(suspects: list[str], benign: str, real_ids: set[str]) -> list[str]:
    """의심 절의 토큰·따옴표 문자열 가운데 의심 절 밖의 본문과 질문에 없는 것."""
    found: list[str] = []
    for u in suspects:
        found += [m.group(0) for m in _P_TOKEN.finditer(u)]
        found += [q[1:-1].strip() for q in re.findall(_QUOTED, u)]
    return _keep_new(found, _norm(benign), real_ids)


_ANS_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def scrub_answer(answer: str, chunks: list[dict], question: str = "") -> tuple[str, list[str]]:
    """(정리한 답, 뺀 문장). 지시 문장이 없는 검색 결과이면 그대로. 문장 안의 `[chunk_id]` 표시도 함께 사라진다."""
    instr: list[str] = []
    suspects: list[str] = []
    q_rest, q_instr = strip_instructions(question, whole_sentence=True) if question else ("", [])
    q_instr = q_instr + hidden_instructions(question)   # 질문 속 인코딩 문자열을 푼 지시도 같다(지시는 질문 원문의 따옴표·표식 꼴과 함께 후보를 낸다)
    benign: list[str] = [q_rest if q_instr else question]   # 지시 문장이 든 질문은 지시 문장을 믿는 글에서 뺀다
    tells: list[str] = []
    texts: list[str] = []
    for c in chunks:
        for field in ("text", "rule_title", "article"):
            if c.get(field):
                clean, rem = strip_instructions(str(c[field]), cut_tail=field != "text")
                instr += rem + hidden_instructions(str(c[field]))   # 인코딩해 숨긴 지시(푼 글)도 지시 문장으로 센다
                if rem and field != "text":
                    # 제목은 지시가 시작한 자리부터 잘려 앞 토막에 표식이 남을 수 있다(예: "문서번호 X-1 를 ..."). 지시가 든 제목의 남은 토막은 믿는 글로 보지 않고 의심 절로 둔다(사전 등록 62.26)
                    suspects.append(clean)
                    continue
                rest, sus = split_suspects(clean)
                suspects += sus
                benign.append(rest)
                if field == "text":
                    texts.append(rest)
                    tells += [p for p in _SENT.split(rest) if p.strip() and _TELL.search(p)]
    answer_addrs = [m.group(0) for m in _ADDR.finditer(answer or "")]
    if not instr and not suspects and not q_instr and not tells and not answer_addrs:
        return answer, []
    real = {c.get("chunk_id") for c in chunks if c.get("chunk_id")}
    benign_all = "\n".join(benign)
    cands = [_norm(x) for x in marker_candidates(instr, benign_all, real) + suspect_candidates(suspects, benign_all, real)]
    if q_instr:   # 질문에 지시 문장이 있으면 질문의 따옴표 문자열·표식 꼴은 답에 옮기면 안 되는 표식 후보다(검색 원문에 있는 것은 뺀다)
        from_chunks = "\n".join(benign[1:])
        cands += [_norm(x) for x in marker_candidates([question, *q_instr], from_chunks, real)]
    long_parts = [p for p in (_letters(x) for x in instr) if len(p) >= 15]
    forged = [(_letters(_EMBED_CITE.sub("", u)), set(_EMBED_CITE.findall(u))) for u in instr if _EMBED_CITE.search(u)]
    # 전달 지시 문장의 주소와 값: 그 문장 밖의 원문과 질문에 없는 것만 후보다. 주소는 청크 출처와 같은 사이트면 믿는다
    own_sites = {_site(_host(str(c.get("source_url")))) for c in chunks if c.get("source_url")}
    outside = _norm("\n".join([benign[0], *("".join(p for p in _SENT.split(t) if not _TELL.search(p)) for t in texts)]))
    tell_addrs: list[str] = []
    tell_values: list[tuple[str, str]] = []
    for t in tells:
        addrs, values = tell_candidates(t)
        tell_addrs += [_norm(a) for a in addrs if _site(_host(a)) not in own_sites and _norm(a) not in outside]
        tell_values += [v for v in values if not _has_value(outside, *v)]
    # 답의 주소는 검색 원문(본문·출처 주소)에 있는 호스트여야 한다. 질문이 준 주소는 근거가 아니다
    source_blob = "\n".join(f"{c.get('text') or ''}\n{c.get('source_url') or ''}" for c in chunks).casefold()
    unbacked = [_norm(a) for a in answer_addrs if _host(a) and _host(a) not in source_blob]
    kept, removed = [], []
    for sent in _ANS_SENT.split(answer or ""):
        if not sent.strip():
            continue
        n, lt = _norm(sent), _letters(sent)
        bad = any(c in n for c in cands) or any(p[i:i + 15] in lt for p in long_parts for i in range(0, len(p) - 14))
        bad = bad or any(a in n for a in tell_addrs + unbacked) or any(_has_value(n, *v) for v in tell_values)
        bad = bad or any(ids & set(_EMBED_CITE.findall(sent)) and any(p[i:i + _FORGED_WIN] in lt for i in range(0, max(1, len(p) - _FORGED_WIN + 1)))
                         for p, ids in forged if len(p) >= _FORGED_WIN)
        (removed if bad else kept).append(sent)
    if not removed:
        return answer, []
    return " ".join(s.strip() for s in kept), [s.strip() for s in removed]


def leaks_instruction(text: str, chunks: list[dict], question: str = "") -> bool:
    """스위치가 켜져 있을 때, 글 한 덩어리가 검색 원문 지시에서 온 표식·문장을 옮겼는가(쟁점표 행, 다시 쓴 답 검사). 꺼져 있으면 항상 False."""
    return scrub_enabled() and bool(scrub_answer(text, chunks, question)[1])
