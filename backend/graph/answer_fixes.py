"""놓친 문항 해결안(B단계, 2026-11-06). 모두 기본 꺼짐 스위치이고, 꺼져 있으면 그래프의 입력, 프롬프트, 인용이 바뀌지 않는다.

- A1 `GRAPH_CITE_EXPAND=1`: 답을 쓴 뒤 코드가 인용을 보강한다(LLM 호출 없음). 인용한 청크와 같은 숫자·단위를 담고 영어 내용어가 0.3 이상 겹치는,
  문맥에 있지만 인용하지 않은 청크를 최대 2개 더한다. 같은 사실을 다른 페이지가 말할 때 답이 하나만 고르는 규칙(ANSWER_SYSTEM)의 보완이다.
  CiteFix(arXiv 2504.15629)는 문장마다 인용을 바꾸는 교정 방식이고, 여기서는 바꾸지 않고 더하는 보강 방식이다. 문턱 0.3은 v2 결과를 보고 정했다(과적합 위험).
- A3 `GRAPH_CITE_MULTI=1`: 답 프롬프트와 인용 규칙 Skill의 "근거 하나만"을 "같은 사실을 다른 페이지가 말하면 최대 3개"로 바꾼다(A1과 비교용).
- A4 `GRAPH_TEAM_LAST=1`: 질문이 팀, 그룹, 부서를 말하지 않으면 페이지 제목에 Team이나 Group이 든 청크를 답 입력 목록 뒤로 보낸다(빼지 않고 순서만).
- A5 `GRAPH_KEEP_CITES=1`: 근거 판정 뒤 답을 다시 쓸 때, 처음 답에서 받쳐지지 않는다고 하지 않은 문장의 인용을 코드가 넘겨받는다.
- B1 `GRAPH_SUB_RESEARCH=1`: 일부 근거(partial)로 끝나는 나뉜 질문에서 판정이 빠졌다고 한 사실에 맞는 하위 질문 하나를 원문 그대로 한 번 더 찾는다(그때만 재검색 상한 +1).
- B4 `GRAPH_PAGE_RESEARCH=1`: B1과 같은 때에 그 하위 질문을 지금까지 문맥에 들어온 페이지(rule_seq) 안에서만 다시 찾는다(`Searcher.search_pages`). 기본 검색 경로는 그대로다.
- B2 `GRAPH_REQUERY_VOCAB=1`: 판정이 내는 재검색어에 원 하위 질문의 영어 어휘를 지키고 빠진 사실은 받는 쪽 동사로 쓰라는 규칙을 더한다.
- D1 `GRAPH_UNKNOWN_NAME=1`: 질문의 영문 구(영문 토큰 2개 이상이 이어진 것, 따옴표 안 영문)가 코퍼스 전체(본문과 제목 경로)에 없으면 검색 없이 되묻는다.
  거절 프롬프트를 넓히지 않고 코드 검사로 좁게 둔다(결정 0067의 named 규칙 전례, UAEval4RAG Table 18).
- R `GRAPH_REFUSE_ON_NONE=1`: 첫 근거 판정이 "전무"(sufficient 거짓, partial 거짓, clarify 없음)면 재검색 없이 거절한다.
  #44, #49, #51~#53 기존 행에서 첫 판정이 전무인 관련 문항 행은 0/510행이었다(재검색 분석, 2026-11-06).
- 가 `GRAPH_RESEARCH_SAME_PAGE=1`: 부분(partial) 판정 뒤의 재검색을 전체 검색 대신 지금 문맥에 든 페이지(rule_seq) 안 검색(`Searcher.search_pages`)으로 바꾼다.
  재검색 횟수는 그대로다(추가가 아니라 교체). 검색어는 재검색 때와 같은 `search_query`(판정이 낸 재검색어)다.
- A1b `GRAPH_CITE_PHRASE=1`: 근거 판정 뒤 코드가 인용을 보강한다(LLM 호출 없음). 인용한 청크와 영어 단어 `PHRASE_MIN_WORDS`개 이상을 그대로 이어서
  공유하는, 다른 페이지(rule_seq)의 문맥 청크를 최대 2개 더한다. 숫자가 없는 같은 사실(A1이 보지 못함)을 다른 페이지가 말할 때의 보완이다.
  다른 팀의 페이지(제목에 Team이나 Group이 있고 인용 청크의 페이지 제목과 다름)는 더하지 않는다(다른 팀 페이지에 옮겨 적은 글).
  문턱 12는 v2 기존 행(#44, #49, #52~#54 답한 421행)에서 10~15가 같은 결과(33번 5행 정답 근거 +1, 비정답 추가 0)를 낸 구간의 가운데다(과적합 위험).
- Q `GRAPH_GROUNDING_QUOTE=1`: 근거 확인 프롬프트를 '주장마다 받치는 영어 구절을 먼저 그대로 복사(없으면 NOTHING FOUND)하고 판정'으로 바꾸고(`prompts.question.grounding_quoted`),
  번역·말 바꿈과 제목 경로의 간접 근거(적용 범위)를 받쳐진 것으로 보는 기준을 적는다. 호출 수는 그대로다. 근거: 기존 425행 중 근거 확인이 받쳐지지 않는다고 한 관련 문항 12행은
  모두 첫 답이 정답 근거를 인용했고(3, 4, 7, 14, 15, 39번, 다시 쓰기 +3~4초, 7번 1행은 거절), 비관련 4행은 모두 22번이다.
- P `GRAPH_DROP_SCOPED_CITES=1`: 근거 판정(과 A1, A1b) 뒤, 질문에 없는 한정어가 붙은 페이지만 인용한 문장을 코드가 빼고 번호를 다시 매긴다(LLM 호출 없음, `qualifiers`).
  한정어는 페이지 제목에서 질문에 나온 영어 낱말 바로 앞에 붙은 낱말 중 질문, 조직 이름, 같은 문맥의 다른 페이지 제목 경로에 없는 것이다. 남는 인용 문장이 없으면 그대로 둔다. 특정 이름은 코드에 두지 않는다.
- R3 `GRAPH_INTRO_FILL=1`: 검색 결과를 합친 문맥에 같은 페이지 판(rule_seq, version_id)의 청크가 3개 이상이면, 그 페이지 첫 청크의 첫 절(h2) 청크 중
  방금 검색한 질문 벡터와 가장 가까운 1개를 문맥 뒤에 더한다(`Searcher.intro_fill`, 임베딩·LLM 호출 없음). 그 절의 청크가 이미 문맥에 있으면 더하지 않는다. 그래프에 intro_search가 있어야 한다.
  근거(다른 에이전트 오프라인 분석, #54·#55·#61 기존 행): 도입부 절이 정답인 문항(Overview)은 4/4행에서 문맥에 들고, 다른 관련 문항에는 비정답 77개가 섞이며 문맥 글자가 7.4% 는다.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from backend.graph.untrusted import drop_suspect_tokens, strip_instructions


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def cite_expand_enabled() -> bool:
    return _flag("GRAPH_CITE_EXPAND")


def cite_multi_enabled() -> bool:
    return _flag("GRAPH_CITE_MULTI")


def team_last_enabled() -> bool:
    return _flag("GRAPH_TEAM_LAST")


def keep_cites_enabled() -> bool:
    return _flag("GRAPH_KEEP_CITES")


def sub_research_enabled() -> bool:
    return _flag("GRAPH_SUB_RESEARCH")


def requery_vocab_enabled() -> bool:
    return _flag("GRAPH_REQUERY_VOCAB")


def page_research_enabled() -> bool:
    return _flag("GRAPH_PAGE_RESEARCH")


def unknown_name_enabled() -> bool:
    return _flag("GRAPH_UNKNOWN_NAME")


def refuse_on_none_enabled() -> bool:
    return _flag("GRAPH_REFUSE_ON_NONE")


def research_same_page_enabled() -> bool:
    return _flag("GRAPH_RESEARCH_SAME_PAGE")


def cite_phrase_enabled() -> bool:
    return _flag("GRAPH_CITE_PHRASE")


def drop_scoped_enabled() -> bool:
    return _flag("GRAPH_DROP_SCOPED_CITES")


# P: 한정어. 인용 청크의 제목 경로에 있고, 질문에 없고, 같은 문맥의 다른 페이지 청크 제목 경로에도 없는 영어 낱말이다.
# 좁은 형태(기본): 페이지 제목에서 질문에 나온 영어 낱말 바로 앞에 붙은 낱말만 한정어로 본다(예: 질문의 낱말 X 앞의 'Y X'). 특정 이름은 코드에 두지 않는다
_EN = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
_QUAL_STOP = frozenset("the a an and or of for to in on with by at from as is are be how what when why who which new our your".split())
_NUM_SENTENCE = re.compile(r".+?[.!?。](?:\s*\[\d+\])*(?=\s|$)|.+$", re.S)
_NUM = re.compile(r"\[(\d+)\]")


def _heading_words(c: dict, *, page_only: bool = False) -> list[str]:
    title = str(c.get("rule_title") or c.get("title") or "")
    return [w.lower() for w in _EN.findall(title if page_only else f"{title} > {c.get('article') or ''}")]


def qualifiers(question: str, chunk: dict, context: list[dict] | None = None, *, adjacent: bool = True) -> list[str]:
    """P의 한정어 목록. 질문의 영어 낱말, 청크의 조직 이름(org), 같은 문맥의 다른 페이지(rule_seq) 청크 제목 경로의 낱말, 짧은 기능어는 한정어가 아니다.
    adjacent=True면 페이지 제목에서 질문에 나온 낱말 바로 앞의 낱말만 본다. False는 제목 경로의 모든 낱말(넓은 형태, 오프라인 비교용)."""
    asked = {w.lower() for w in _EN.findall(question or "")}
    if not asked:
        return []
    seq = chunk.get("rule_seq")
    other = {w for c in context or [] if c.get("rule_seq") != seq for w in _heading_words(c)}
    org = str(chunk.get("org") or "").lower()

    def qual(w: str) -> bool:
        return len(w) >= 3 and w not in asked and w not in other and w != org and w not in _QUAL_STOP
    words = _heading_words(chunk, page_only=adjacent)  # 좁은 형태는 페이지 제목에서만 본다(절 제목의 낱말은 질문 낱말 앞에 흔히 붙는다)
    if adjacent:
        return list(dict.fromkeys(words[i - 1] for i, w in enumerate(words) if i and w in asked and qual(words[i - 1])))
    return list(dict.fromkeys(w for w in words if qual(w)))


def scoped_out(question: str, chunk: dict, context: list[dict] | None = None) -> bool:
    """질문에 없는 한정어가 붙은 페이지의 청크인지(`qualifiers`가 비어 있지 않음)."""
    return bool(qualifiers(question, chunk, context))

def drop_scoped_cites(body: str, cited: list[dict], question: str, note: str, context: list[dict] | None = None) -> tuple[str, list[dict], list[str]] | None:
    """P: `finish_answer`를 거친 본문(표시 `[n]`)에서 한정 페이지만 인용한 문장을 빼고, 다른 인용과 같이 붙은 표시는 지운다. 번호는 남은 인용 순서로 다시 매긴다.
    뺀 문장이 있으면 `note`(일부 답 안내)를 붙인다. 뺄 것이 없거나 인용 문장이 하나도 남지 않으면 None(답을 그대로 둔다)."""
    ctx = context if context is not None else cited
    bad = {i for i, c in enumerate(cited, 1) if scoped_out(question, c, ctx)}
    if not bad:
        return None
    lines_out, dropped = [], False
    for line in body.split("\n"):
        kept = []
        for m in _NUM_SENTENCE.finditer(line.strip()):
            s = m.group(0).strip()
            nums = {int(n) for n in _NUM.findall(s)}
            if nums and nums <= bad:
                dropped = True
                continue
            kept.append(_NUM.sub(lambda x: "" if int(x.group(1)) in bad else x.group(0), s) if nums & bad else s)
        lines_out.append(" ".join(kept))
    new_body = re.sub(r"[ \t]+([.!?])", r"\1", "\n".join(lines_out)).strip()
    keep = [i for i in range(1, len(cited) + 1) if i not in bad]
    if not keep or not any(int(n) in keep for n in _NUM.findall(new_body)):
        return None
    order = {old: new for new, old in enumerate(keep, 1)}
    new_body = _NUM.sub(lambda x: f"[{order[int(x.group(1))]}]" if int(x.group(1)) in order else "", new_body)
    if dropped and note not in new_body:
        new_body = f"{new_body} {note}"
    return new_body, [cited[i - 1] for i in keep], [cited[i - 1]["chunk_id"] for i in sorted(bad)]


def grounding_quote_enabled() -> bool:
    return _flag("GRAPH_GROUNDING_QUOTE")



_NOTHING = "nothing found"


def _squash_quote(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’`]", "", str(s or "").lower())).strip(" .,;:")


def intro_fill_enabled() -> bool:
    return _flag("GRAPH_INTRO_FILL")


def scope_note_refuse_enabled() -> bool:
    return _flag("GRAPH_SCOPE_NOTE_REFUSE")


def requery_skip_seen_enabled() -> bool:
    return _flag("GRAPH_REQUERY_SKIP_SEEN")


def pointer_refuse_enabled() -> bool:
    return _flag("GRAPH_POINTER_REFUSE")


def speculate_enabled() -> bool:
    return _flag("GRAPH_SPECULATE_FIRST")


def speculate_early_search_enabled() -> bool:
    """SE `GRAPH_SPECULATE_EARLY_SEARCH=1`(`GRAPH_SPECULATE_FIRST`와 같이 쓴다): 예비 분해(`decompose_gate`)가 끝나길 기다리지 않고 원 질문의 첫 검색을 같은 시각에 시작한다.
    예비 분해가 나누지 않고 분류가 정책 경로이면 그 결과를 쓰고(입력은 같다), 아니면 버린다. 코드 기본은 꺼짐이고 서비스 설정(`service_profile.SERVICE_ENV`)에서 켠다(사전 등록 62.53)."""
    return _flag("GRAPH_SPECULATE_EARLY_SEARCH")


def speculate_ground_enabled() -> bool:
    """SG `GRAPH_SPECULATE_GROUND=1`: 답 후보가 나오는 대로 그 답의 근거 판정을 미리 부르고, 나중에 같은 입력의 판정이 필요하면 그 결과를 쓴다(입력과 판정 기준은 그대로)."""
    return _flag("GRAPH_SPECULATE_GROUND")


def unchanged_rejudge_enabled() -> bool:
    """UR `GRAPH_UNCHANGED_REJUDGE=1`: 근거 판정이 받쳐지지 않는다고 하고, 사유를 받은 다시 쓰기가 처음 답을 그대로 내면 처음 답을 같은 입력으로 한 번 더 판정한다.
    받쳐지면 그 답을 내고, 아니면 지금처럼 문장 빼기와 거절로 간다(그 행에만 판정 호출 +1). 근거: 기존 agent_v2 행에서 이 경로(다시 쓰기 unchanged)는 5행이고
    모두 관련 문항(7번 2행, 14, 4, 31번)이 거절된 행이다. 비관련 문항은 0행. 7번은 같은 검색 결과에서 판정이 131행 중 8행만 받쳐지지 않는다고 했다(61.15 멀티 7번)."""
    return _flag("GRAPH_UNCHANGED_REJUDGE")


# PT: 근거 구절이 내용 없이 다른 자료(링크, 다른 페이지)를 가리키는 안내 문장인지
_POINTER = re.compile(r"\brefer to\b|\bfollowing links?\b|\bsee (the )?(links?|pages?|guides?)\b|\bcan be found (at|in|on)\b|\bprovides instructions\b|\bfor more information\b", re.I)


def pointer_only(quotes: list[str] | None) -> bool:
    """PT: 근거 확인(Q 형식)이 주장마다 복사한 구절이 모두 안내 문장이거나 제목 경로뿐이고, 안내 문장이 하나 이상인지. 구절이 없으면 거짓이다.
    NOTHING FOUND 구절은 보지 않는다. 받쳐진(grounded) 판정에서 구절이 없는 주장은 답이 스스로 '자료에 없다'고 한 문장이다(61.15 멀티 22번)."""
    qs = [q.strip() for q in quotes or [] if isinstance(q, str) and q.strip() and _squash_quote(q) != _NOTHING]
    if not qs:
        return False
    heading = lambda q: " > " in q and not re.search(r"[.!?]\s*$", q) and len(q) <= 160  # noqa: E731
    # 링크 이름 목록: 두 줄 이상이고 줄마다 숫자 없는 4낱말 이하(링크로 걸린 항목 이름만 줄마다 적힌 구절)
    names = lambda q: len(lines := [x.strip(" -*•") for x in q.splitlines() if x.strip(" -*•")]) >= 2 and all(len(x.split()) <= 4 and not re.search(r"\d", x) for x in lines)  # noqa: E731
    return any(_POINTER.search(q) for q in qs) and all(_POINTER.search(q) or heading(q) or names(q) for q in qs)


# SN: 판정이 충분하다고 하면서 scope_note에 '자료가 다른 대상·용도에 한정된다'와 '질문한 것은 자료에 없다'를 함께 쓴 경우
_SCOPE_LIMITED = re.compile(r"한정|에만\s*적용|용도|맥락의|대상이고|전용")
_SCOPE_ABSENT = re.compile(r"자료에(는)?\s*(직접\s*)?(없|나와\s*있지\s*않)")


def scope_note_refuses(obj: dict) -> bool:
    """SN: sufficient=true 판정의 scope_note가 자료의 적용 범위 한정과 질문 내용의 부재를 함께 말하는지. 둘 중 하나만이면 거짓이다."""
    note = obj.get("scope_note")
    if obj.get("sufficient") is not True or not isinstance(note, str):
        return False
    return bool(_SCOPE_LIMITED.search(note)) and bool(_SCOPE_ABSENT.search(note))


def cite_pick_enabled() -> bool:
    return _flag("GRAPH_CITE_PICK")


CITE_PICK_RULE = ("- 같은 사실을 여러 자료가 말하면 근거는 이 순서로 고른다. (1) 그 사실의 문장이 자료 안에 처음부터 온전히 있는 자료. 본문이 문장 중간에서 시작해 앞 자료와 겹친 부분에만 그 말이 있는 자료는 고르지 않는다. "
                  "(2) 여러 자료가 같은 문장을 그대로 되풀이하면 그 문장이 있는 자료. 한 자료만 다르게 풀어 쓴 문장보다 앞선다. "
                  "(3) 절 제목(제목 경로의 마지막 부분)이 질문이 묻는 항목 자체를 이름으로 가진 자료. 단 절 제목이나 본문이 질문에 없는 조건(특정 사용자 유형, 특정 팀, '~인 경우')에만 적용된다고 하면 그 조건을 물을 때만 쓴다. "
                  "(4) 질문이 팀, 직무, 경우를 정하지 않았으면 한 팀·한 직무·특정 경우의 절차보다 일반 조건과 여러 팀에 공통인 규범. "
                  "근거를 달기 전에 자료 문장의 주어와 조건이 질문과 같은지 확인한다. 질문이 'A가 응답하지 않으면'을 물을 때 'B가 응답하지 않으면 A를 부른다'는 자료는 다른 사실이다.")


def judged_none(obj: dict) -> bool:
    """판정 결과가 "전무"인지: sufficient가 거짓(False)이고 partial이 참이 아니며 되묻기가 없다. 파싱 실패(sufficient 없음)는 전무로 보지 않는다."""
    clarify = obj.get("clarify")
    return obj.get("sufficient") is False and obj.get("partial") is not True and not (isinstance(clarify, str) and clarify.strip())


_MARK = re.compile(r"\[([0-9a-f]{16})\]")

# ---------- A1 인용 보강 ----------
_STOP = set("the a an of to in on and or for is are be as by with at it its that this from if not no can may will must should do does have has been was were their "
            "they them you your we our us which when where who what than then there these those also any all each other such only into out up over under per via etc one two".split())
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15,
              "twenty": 20, "thirty": 30, "twenty-four": 24, "forty-eight": 48}
_UNIT = r"(minutes?|hours?|days?|weeks?|months?|years?|%|percent|times|business days|working days|k|million)"
MIN_OVERLAP = 0.3  # 0.2는 쓰지 않는다(비정답 추가가 늘었다)
MAX_ADD = 2


def _body(c: dict) -> str:
    parts = str(c.get("text") or "").split("\n", 1)  # 첫 줄은 제목 경로다
    return parts[1] if len(parts) > 1 else parts[0]


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9\-]+|\d+", s.lower()) if w not in _STOP and len(w) > 1}


def value_keys(text: str) -> set[tuple[str, str]]:
    """본문의 (숫자, 단위) 쌍. seven -> 7, business days -> day처럼 맞춘다."""
    t = text.lower()
    for w, n in _NUM_WORDS.items():
        t = re.sub(rf"\b{w}\b", str(n), t)
    out = set()
    for m in re.finditer(rf"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(?:business\s+|working\s+|calendar\s+)?{_UNIT}\b", t):
        unit = m.group(2).rstrip("s")
        out.add((m.group(1), "%" if unit == "percent" else unit))
    return out


def _own_body(c: dict, cited: list[dict]) -> str:
    """본문에서 앞 청크와 겹친 머리를 뗀 것. 같은 페이지 인용 청크 본문의 끝과 그대로 같은 머리는 청킹이 앞 청크에서 복사한 글이라 이 청크의 근거로 세지 않는다."""
    body = _body(c)
    cut = 0
    for x in cited:
        if c.get("rule_seq") is None or x.get("rule_seq") != c.get("rule_seq") or x["chunk_id"] == c["chunk_id"]:
            continue
        prev = _body(x)
        for n in range(min(len(body), len(prev)), cut, -1):
            if prev.endswith(body[:n]):
                cut = n
                break
    return body[cut:]


def _value_lines(body: str, keys: set[tuple[str, str]]) -> list[tuple[set[tuple[str, str]], set[str], str]]:
    """본문에서 `keys`의 값을 담은 줄마다 (그 줄의 값, 그 줄의 단어, 그 줄 글). 세 줄 이상인 본문에서 줄의 절반 이상에 되풀이되는 단어(표의 열 이름 등)는 뺀다."""
    lines = [ln for ln in body.split("\n") if ln.strip()]
    toks = [_tokens(ln) for ln in lines]
    common: set[str] = set()
    if len(lines) >= 3:
        common = {t for t in set().union(*toks) if sum(t in x for x in toks) * 2 >= len(lines)}
    return [(value_keys(ln) & keys, t - common, ln) for ln, t in zip(lines, toks) if value_keys(ln) & keys]


TABLE_SEP = " | "  # 표 행의 칸 구분(`이름: 값 | 이름: 값 ...`)


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def is_table_row(line: str) -> bool:
    return TABLE_SEP in line


def row_first_cell(line: str) -> str:
    """표 행의 첫 칸 값. `이름: 값`이면 값, 이름 칸이 없으면 칸 전체(영숫자 소문자만)."""
    cell = line.split(TABLE_SEP, 1)[0]
    return _alnum(cell.split(":", 1)[1] if ":" in cell else cell)


def _same_section(c: dict, cited: list[dict]) -> bool:
    """사전 등록 62.56: 같은 페이지(rule_seq) 같은 절 제목(article)의 청크는 한 표나 한 절이 청크로 나뉜 것이라 같은 값을 말해도 다른 사실의 근거가 아니다."""
    return c.get("rule_seq") is not None and bool(c.get("article")) and any(x.get("rule_seq") == c.get("rule_seq") and x.get("article") == c.get("article") for x in cited)


def pick_extra(cited: list[dict], context: list[dict], *, cap: int = 4) -> list[tuple[dict, int]]:
    """더할 청크와 그 청크와 가장 많이 겹친 인용 청크의 자리(0부터). 문맥 순서대로 보고 `MAX_ADD`개, 인용 합계 `cap`개까지.
    겹침은 청크 전체가 아니라 같은 값을 담은 줄끼리 잰다: 값(숫자, 단위)만 같고 그 값이 가리키는 대상이 다른 줄은 같은 사실이 아니다.
    줄 겹침만 보면 값과 단위 단어만 같은 다른 문서의 짧은 줄이 붙는다(운영 00035·00037의 v2 8·9번). 청크 전체 겹침도 같이 넘어야 한다."""
    if not cited or len(cited) >= cap:
        return []
    keys = set().union(*(value_keys(_body(c)) for c in cited))
    if not keys:
        return []
    have = {c["chunk_id"] for c in cited}
    cited_lines = [_value_lines(_body(c), keys) for c in cited]
    cited_tokens = [_tokens(_body(c)) for c in cited]
    added: list[tuple[dict, int]] = []
    for c in context:
        if len(added) >= min(MAX_ADD, cap - len(cited)):
            break
        if c["chunk_id"] in have or _same_section(c, cited):  # 62.56(가): 같은 절의 다른 청크는 더하지 않는다
            continue
        anchor, score = -1, 0.0
        for k, t, ln in _value_lines(_own_body(c, cited), keys):
            for i, rows in enumerate(cited_lines):
                for k2, t2, ln2 in rows:
                    if is_table_row(ln) and is_table_row(ln2) and (row_first_cell(ln) != row_first_cell(ln2) or not row_first_cell(ln)):
                        continue  # 62.56(나): 표 행끼리는 첫 칸이 같을 때만 같은 값 줄로 본다
                    if t and k & k2 and len(t & t2) / len(t) > score:
                        anchor, score = i, len(t & t2) / len(t)
        if score >= MIN_OVERLAP:
            ct = _tokens(_body(c))
            whole = max((len(ct & x) / len(ct) for x in cited_tokens), default=0.0) if ct else 0.0
            if whole >= MIN_OVERLAP:
                added.append((c, anchor))
                have.add(c["chunk_id"])
    return added


def _insert_after(text: str, mark: str, extra: str) -> str:
    i = text.find(mark)
    return text[: i + len(mark)] + extra + text[i + len(mark):] if i >= 0 else f"{text} {extra}"


def expand_citations(answer: str, cited: list[dict], context: list[dict], *, cap: int = 4) -> tuple[str, list[dict]]:
    """(답, 인용). 답의 표시가 `[chunk_id]`일 때. 더한 청크의 표시는 가장 많이 겹친 인용 청크의 첫 표시 바로 뒤에 붙인다."""
    added = pick_extra(cited, context, cap=cap)
    for c, i in added:
        answer = _insert_after(answer, f"[{cited[i]['chunk_id']}]", f"[{c['chunk_id']}]")
    return answer, [*cited, *(c for c, _ in added)]


def expand_numbered(body: str, cited: list[dict], context: list[dict], *, cap: int = 4, picker=None) -> tuple[str, list[dict]]:
    """`finish_answer`를 거친 본문(표시가 `[n]`)에 같은 규칙으로 더한다. 새 청크는 인용 목록 끝에 붙어 번호가 이어진다.
    `picker`를 주면 그 규칙(`pick_phrase_extra` 등)으로 고른다. 기본은 A1(`pick_extra`)."""
    added = (picker or pick_extra)(cited, context, cap=cap)
    for j, (c, i) in enumerate(added, len(cited) + 1):
        body = _insert_after(body, f"[{i + 1}]", f"[{j}]")
    return body, [*cited, *(c for c, _ in added)]


# ---------- A1b 같은 문장을 다른 페이지가 말할 때 ----------
PHRASE_MIN_WORDS = 12
_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*")


def _words(s: str) -> list[str]:
    return _WORD.findall((s or "").lower())


def longest_shared_run(a: list[str], b: list[str]) -> int:
    """두 단어열이 그대로 이어서 공유하는 가장 긴 길이."""
    if not a or not b:
        return 0
    pos: dict[str, list[int]] = {}
    for j, w in enumerate(b):
        pos.setdefault(w, []).append(j)
    best, prev = 0, {}
    for w in a:
        cur = {}
        for j in pos.get(w, ()):
            cur[j] = prev.get(j - 1, 0) + 1
            best = max(best, cur[j])
        prev = cur
    return best


def _words_whole_rows(body: str, other: str, gap: str) -> list[str]:
    """사전 등록 62.57: `body`의 단어열. 표 행(` | `이 있는 줄)은 그 줄 전체가 `other`에도 그대로(영숫자 비교) 있을 때만 넣고, 아니면 건너뛰며 그 자리에 서로 맞지 않는 표지(`gap`)를 둔다.
    산문 줄은 지금처럼 이어 붙인다. 표 행의 뒤 칸 일부만 같은 다른 문서의 행은 같은 문장으로 세지 않는다."""
    other_norm = _alnum(other)
    out: list[str] = []
    for ln in body.split("\n"):
        if is_table_row(ln):
            norm = _alnum(ln)
            if not norm or norm not in other_norm:
                out.append(gap)
                continue
        out.extend(_words(ln))
    return out


def _other_team_page(c: dict, anchor: dict) -> bool:
    title = str(c.get("rule_title") or "")
    return bool(_TEAM_TITLE.search(title)) and title != str(anchor.get("rule_title") or "")


def pick_phrase_extra(cited: list[dict], context: list[dict], *, cap: int = 4, n: int = PHRASE_MIN_WORDS) -> list[tuple[dict, int]]:
    """더할 청크와 그 청크와 문장을 공유한 인용 청크의 자리(0부터). 문맥 순서대로 보고 `MAX_ADD`개, 인용 합계 `cap`개까지.
    인용 청크와 같은 페이지(rule_seq)의 청크와 다른 팀의 페이지는 더하지 않는다."""
    if not cited or len(cited) >= cap:
        return []
    have = {c["chunk_id"] for c in cited}
    added: list[tuple[dict, int]] = []
    for c in context:
        if len(added) >= min(MAX_ADD, cap - len(cited)):
            break
        if c["chunk_id"] in have:
            continue
        for i, x in enumerate(cited):
            if c.get("rule_seq") == x.get("rule_seq") or _other_team_page(c, x):
                continue
            if longest_shared_run(_words_whole_rows(_body(c), _body(x), "\x00c"), _words_whole_rows(_body(x), _body(c), "\x00x")) >= n:
                added.append((c, i))
                have.add(c["chunk_id"])
                break
    return added


# ---------- CS 여러 페이지가 되풀이하는 문장 쪽 인용만 남기기 ----------
CONSENSUS_MIN_WORDS = 6


def consensus_enabled() -> bool:
    return _flag("GRAPH_CITE_CONSENSUS")


def drop_odd_cites(body: str, cited: list[dict], *, n: int = CONSENSUS_MIN_WORDS) -> tuple[str, list[dict], list[str]] | None:
    """CS: `finish_answer`를 거친 본문(표시 `[n]`)의 한 문장이 인용 셋 이상을 달았고, 그중 서로 다른 페이지 둘 이상이 같은 문장(단어 n개 이상 그대로)을 공유하면,
    그 페이지들 밖의 인용 중 그 문장을 공유하지 않는 것의 표시를 그 문장에서 지운다. 어디에도 표시가 남지 않은 인용은 목록에서 빼고 번호를 다시 매긴다.
    지울 것이 없으면 None(답을 그대로 둔다)."""
    words = [_words(_body(c)) for c in cited]
    seq = [c.get("rule_seq") for c in cited]
    changed = False
    lines_out = []
    for line in body.split("\n"):
        kept = []
        for m in _NUM_SENTENCE.finditer(line.strip()):
            s = m.group(0).strip()
            nums = [int(x) for x in _NUM.findall(s) if 0 < int(x) <= len(cited)]
            idx = list(dict.fromkeys(i - 1 for i in nums))
            if len(idx) >= 3:
                core = {i for a in idx for b in idx if a < b and seq[a] != seq[b] and longest_shared_run(words[a], words[b]) >= n for i in (a, b)}
                pages = {seq[i] for i in core}
                odd = {i for i in idx if i not in core and seq[i] not in pages and all(longest_shared_run(words[i], words[j]) < n for j in core)}
                if core and odd:
                    s = _NUM.sub(lambda x: "" if int(x.group(1)) - 1 in odd else x.group(0), s)
                    changed = True
            kept.append(s)
        lines_out.append(" ".join(kept))
    if not changed:
        return None
    new_body = re.sub(r"[ \t]+([.!?])", r"\1", "\n".join(lines_out)).strip()
    used = sorted({int(x) for x in _NUM.findall(new_body) if 0 < int(x) <= len(cited)})
    order = {old: new for new, old in enumerate(used, 1)}
    new_body = _NUM.sub(lambda x: f"[{order[int(x.group(1))]}]" if int(x.group(1)) in order else "", new_body)
    removed = [cited[i - 1]["chunk_id"] for i in range(1, len(cited) + 1) if i not in order]
    return new_body, [cited[i - 1] for i in used], removed


# ---------- A3 여러 근거 표시 ----------
ONE_SOURCE_RULE = "- 한 사실에는 가장 직접적인 근거 하나만 표시한다. 같은 사실을 여러 자료가 말해도 하나만 고르고, 서로 어긋날 때만 둘 다 표시한다."
MULTI_SOURCE_RULE = "- 한 사실에는 가장 직접적인 근거를 표시한다. 같은 사실을 서로 다른 페이지가 말하면 그 자료를 최대 3개까지 함께 표시하고, 서로 어긋나면 둘 다 표시한다."
ONE_PICK = '"chunk_id": 그 값이 적힌 가장 직접적인 자료 하나}'
MULTI_PICK = '"chunk_id": 그 값이 적힌 가장 직접적인 자료}를 쓰고, 같은 값을 다른 페이지가 말하면 그 chunk_id도 answer에 함께 표시한다(사실마다 3개 이하)'
SKILL_ONE = "4. 한 쟁점에 근거가 여럿이면 가장 직접적인 하나만 단다."
SKILL_MULTI = "4. 한 쟁점에 근거가 여럿이면 가장 직접적인 것을 달고, 같은 사실을 서로 다른 페이지가 말하면 3개까지 함께 단다."


def relax_one_source(system: str) -> str:
    """답 프롬프트의 근거 하나 규칙을 바꾼다. 바꿀 문장이 없으면 그대로다(프롬프트 조립에 따라 picks 문장이 없을 수 있다)."""
    return system.replace(ONE_SOURCE_RULE, MULTI_SOURCE_RULE).replace(ONE_PICK, MULTI_PICK)


def relax_skill(body: str) -> str:
    return body.replace(SKILL_ONE, SKILL_MULTI) if body else body


# ---------- A4 팀 문서를 뒤로 ----------
_TEAM_TITLE = re.compile(r"\b(team|group)s?\b", re.I)
_TEAM_ASKED = re.compile(r"팀|그룹|부서|\bteam\b|\bgroup\b", re.I)


def team_docs_last(question: str, chunks: list[dict]) -> list[dict]:
    """질문이 팀을 말하지 않으면 제목(`rule_title`)에 Team, Group이 든 청크를 뒤로 보낸다. 순서만 바꾸고 빼지 않는다."""
    if _TEAM_ASKED.search(question or ""):
        return chunks
    front = [c for c in chunks if not _TEAM_TITLE.search(str(c.get("rule_title") or ""))]
    return front + [c for c in chunks if _TEAM_TITLE.search(str(c.get("rule_title") or ""))]


# ---------- A5 인용 넘겨받기 ----------
def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\[[0-9a-f]{16}\]|\s+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def carry_citations(draft: str, draft_cited: list[dict], flagged: list[str], new_answer: str, new_cited: list[dict], *, cap: int = 4) -> tuple[str, list[dict]]:
    """처음 답(draft)에서 받쳐지지 않는다고 하지 않은 문장의 인용 중 새 답에 없는 것을 새 답에 넘긴다.
    표시는 새 답에서 그 문장과 가장 비슷한 문장 끝에 붙인다(겹침이 없으면 넘기지 않는다)."""
    flagged_set = {re.sub(r"[\s.!?。]+", "", _MARK.sub("", f)) for f in flagged or []}
    have = {c["chunk_id"] for c in new_cited}
    by_id = {c["chunk_id"]: c for c in draft_cited}
    out_cited = list(new_cited)
    sents = _sentences(new_answer)
    for s in _sentences(draft):
        bare = re.sub(r"[\s.!?。]+", "", _MARK.sub("", s))
        if any(bare and (bare in f or f in bare) for f in flagged_set if f):
            continue
        for cid in _MARK.findall(s):
            if cid in have or cid not in by_id or len(out_cited) >= cap or not sents:
                continue
            target = max(sents, key=lambda t: len(_bigrams(t) & _bigrams(s)))
            if not _bigrams(target) & _bigrams(s):
                continue
            idx = sents.index(target)
            sents[idx] = f"{target.rstrip()} [{cid}]" if not _MARK.search(target[-20:]) else target.rstrip() + f"[{cid}]"
            out_cited.append(by_id[cid])
            have.add(cid)
    if len(out_cited) == len(new_cited):
        return new_answer, new_cited
    return " ".join(sents), out_cited


# ---------- B1 빠진 하위 질문 ----------
def pick_missing_sub(subs: list[str], missing: list[str], *, min_overlap: float = 0.2) -> str | None:
    """판정이 빠졌다고 한 사실과 글자 두 개 묶음이 가장 많이 겹치는 하위 질문. 겹침이 문턱보다 작으면 None."""
    if len(subs or []) < 2 or not missing:
        return None
    want = set().union(*(_bigrams(m) for m in missing))
    if not want:
        return None
    best, score = None, 0.0
    for s in subs:
        b = _bigrams(re.sub(r"\(.*?\)", "", s))  # 붙인 영어 용어는 빼고 잰다
        sc = len(b & want) / max(1, len(want))
        if sc > score:
            best, score = s, sc
    return best if score >= min_overlap else None


# ---------- B2 재검색어 어휘 ----------
REQUERY_VOCAB_RULE = ("- query를 쓸 때 하위 질문이나 첫 검색어에 있던 영어 용어는 그대로 쓰고 다른 말로 바꾸지 않는다. "
                      "빠진 사실은 그 일을 받는 쪽의 동사로 쓴다(예: is paged, does not respond, unable to respond, is escalated to).")


# ---------- D1 코퍼스에 없는 영문 구 ----------
_TOK = r"[A-Za-z][A-Za-z0-9\.\-/#:+_]*"
# 앞에서부터 처음 있는 파일 하나만 읽는다. 둘은 같은 23095청크다. 서비스 이미지에는 `data/chunks/`(커밋하지 않음)가 없고,
# Dockerfile이 커밋한 data/index.tar.gz를 풀어 둔 `data/index/chunks.jsonl`이 있다
_CORPUS_FILES = ("data/chunks/chunks.jsonl", "data/index/chunks.jsonl")
_ROOT = Path(__file__).resolve().parents[2]


def _squash(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", (s or "").lower())


@lru_cache(maxsize=1)
def corpus_text(root: str = "") -> str:
    """코퍼스 전체(제목, 제목 경로, 본문)를 소문자로 이은 문자열. 검색 색인과 같은 `data/chunks/chunks.jsonl`(23095청크)이고, 없으면 `data/index/chunks.jsonl`이다.
    둘 다 없으면 빈 문자열(검사하지 않는다)."""
    parts: list[str] = []
    for rel in _CORPUS_FILES:
        p = Path(root or _ROOT) / rel
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    parts.append(f"{c.get('rule_title') or ''} {c.get('article') or ''} {c.get('text') or ''}")
        break
    return _squash("\n".join(parts))


def english_phrases(question: str) -> list[str]:
    """영문 토큰 2개 이상이 이어진 구와 따옴표 안의 영문 구."""
    runs = [m.group(0) for m in re.finditer(rf"{_TOK}(?:\s+{_TOK})+", question or "")]
    quoted = []
    for q in re.findall(r"[\"'“”‘’`]([^\"'“”‘’`]{2,60})[\"'“”‘’`]", question or ""):
        quoted += [x.strip() for x in re.findall(r"[A-Za-z][A-Za-z0-9\- ]*", q) if len(x.strip()) >= 2]
    return list(dict.fromkeys(runs + quoted))


def unknown_phrases(question: str, corpus: str) -> list[str]:
    """코퍼스에 전혀 없는 영문 구. 코퍼스가 비면 검사하지 않는다."""
    if not corpus:
        return []
    return [p for p in english_phrases(question) if _squash(p.strip(" .,?!()")) not in corpus]


def quotable_phrases(question: str, corpus: str) -> list[str]:
    """되묻기 문장에 따옴표로 인용해도 되는 모르는 영문 구. 질문을 입력 정화와 같은 지시 문장 판정(`untrusted.strip_instructions`)으로 나눠
    지시로 판정된 절이 든 문장(쉼표·접속 조각으로 이어진 뒷절 포함)과 묶음 괄호를 통째로 뺀 글에서만 뽑고, 의심 문장(표식 꼴 토큰 가까이에
    출력 자리나 목적 이름표)의 토큰도 뺀다. 지시도 의심 문장도 없으면 글자 하나도 바뀌지 않으므로 `unknown_phrases`와 같은 목록이다."""
    return unknown_phrases(drop_suspect_tokens(strip_instructions(question or "", whole_sentence=True)[0]), corpus)


_ECHO_MAX = 40  # 되묻기에 되풀이할 영문 구의 최대 길이. 이보다 길면 이름이 아니라 붙여 넣은 문장이다
# 주소 꼴: 스킴(`이름://`), `www.`, 점으로 이은 이름 + 2자 이상 영문 끝자리(TLD 목록 없음), IPv4. 끝자리가 숫자·1자면(`v1.2`, `e.g`) 주소가 아니다.
# `config.yml`·`Node.js` 같은 파일·제품 이름은 도메인과 꼴이 같아 함께 막힌다. 막혀도 인용 없는 일반 문구로 되물을 뿐이라 안전한 쪽을 택했다
_ECHO_URL = re.compile(r"[a-z][a-z0-9+.\-]*://|www\.|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![a-z0-9-])|(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", re.I)
_ECHO_SQL = re.compile(r"\b(?:select|insert|update|delete|drop|union|alter|truncate|exec)\b.*\b(?:from|into|table|set|select|where|database)\b|;\s*--|--\s|/\*", re.I | re.S)


def echo_safe(phrase: str) -> bool:
    """되묻기 글에 되풀이해도 되는 구인지. 길거나, 줄바꿈·주소·SQL 꼴이 든 구는 이름이 아니라 붙여 넣은 글이다(J-11)."""
    return len(phrase) <= _ECHO_MAX and "\n" not in phrase and not _ECHO_URL.search(phrase) and not _ECHO_SQL.search(phrase)


def unknown_name_message(phrases: list[str]) -> str:
    """phrases가 비면(모르는 구가 지시 절에만 있었다) 문자열을 인용하지 않는 일반 문구로 되묻는다."""
    if not phrases:
        return "질문에 핸드북 자료에서 찾지 못한 표현이 있습니다. 정확한 이름이나 다른 표현으로 다시 물어봐 주세요."
    shown = [p for p in phrases if echo_safe(p)][:3]
    if not shown:
        return "질문에 핸드북 자료에서 찾지 못한 표현이 있습니다. 정확한 이름이나 다른 표현으로 다시 물어봐 주세요."
    names = ", ".join(f"'{p}'" for p in shown)
    return f"질문의 {names}은(는) 핸드북 자료에서 찾지 못했습니다. 정확한 이름이나 다른 표현으로 다시 물어봐 주세요."


# ---------- 판정 다수결(`GRAPH_JUDGE_VOTE`)과 인용 먼저 판정(`GRAPH_JUDGE_QUOTE`) ----------
# 조사 해법(11/6 조정자 지시 2, 5번). 문항 단어 없음. 기본 꺼짐이고, 끄면 판정·근거 확인 호출과 프롬프트가 그대로다.
# 다수결: 같은 입력을 병렬로 3번 부르고 결론(불리언)이 2표 같으면 셋째를 기다리지 않는다. 목록 칸(빠진 사실, 받쳐지지 않는 문장)은 2표 이상 받은 것만 남긴다.
VOTES = 3
_VOTE_LISTS = {"judge": ("missing",), "grounding": ("unsupported_sentences", "off_topic_sentences")}


def judge_vote_enabled() -> bool:
    return _flag("GRAPH_JUDGE_VOTE")


def judge_quote_enabled() -> bool:
    return _flag("GRAPH_JUDGE_QUOTE")


def judge_retry_fast_enabled() -> bool:
    """JRF `GRAPH_JUDGE_RETRY_FAST=1`(기본 꺼짐): 나뉜 질문(하위 질문 2개 이상)이고 앞 판정이 일부(partial)였을 때, 재검색 뒤 판정만 단계 표지를 `judge_retry`로 바꿔 추론을 끈다.
    프롬프트 본문과 입력은 그대로이고 첫 판정과 미리 돌리는 판정(재검색 0회)은 바뀌지 않는다."""
    return _flag("GRAPH_JUDGE_RETRY_FAST")


def revise_ahead_enabled() -> bool:
    """RA `GRAPH_REVISE_AHEAD=1`(기본 꺼짐, `GRAPH_SPECULATE_GROUND`가 켜져 있어야 동작): 근거 확인이 받쳐지지 않는 주장을 지적하면, 답 다시 쓰기와 동시에
    문장 빼기 뒤 재확인을 같은 입력으로 미리 부른다. 어느 답을 쓸지의 순서는 그대로이고, 다시 쓴 답이 쓰이면 미리 부른 결과는 버린다."""
    return _flag("GRAPH_REVISE_AHEAD")


def _vote_key(task: str, obj: dict) -> tuple:
    if task == "judge":
        s = obj.get("sufficient") is True
        return (s, False if s else obj.get("partial") is True)
    return (obj.get("grounded") is True, obj.get("grounded") is False)


def votes_settled(task: str, objs: list[dict]) -> bool:
    """결론이 같은 표가 둘 이상이면 확정이다(나머지 호출을 기다리지 않는다).
    판정(judge)의 부족 2표(충분도 일부도 아님)는 셋째 표를 기다린다. 표가 갈렸는지 알아야 바로 거절할지 정할 수 있다(`votes_unanimous`, 사전 등록 62.33)."""
    keys = [_vote_key(task, o) for o in objs if o]
    return any(keys.count(k) >= 2 and not (task == "judge" and k == (False, False)) for k in keys) or len(objs) >= VOTES


def votes_unanimous(obj: dict) -> bool:
    """합친 표(`merge_votes`)의 표가 모두 같은 결론이었는지. 다수결을 쓰지 않은 표(`_votes` 없음)는 한 표이므로 True다."""
    v = obj.get("_votes")
    return not isinstance(v, dict) or v.get("agree") == v.get("n")


def _same_item(a: str, b: str) -> bool:
    """두 목록 항목이 같은 것인지. 공백을 빼고 같거나, 글자 두 개 묶음이 절반 이상 겹치면 같다(빠진 사실은 표마다 말이 조금씩 다르다)."""
    x, y = re.sub(r"\s+", "", a or ""), re.sub(r"\s+", "", b or "")
    if not x or not y:
        return False
    if x == y:
        return True
    bx, by = _bigrams(a), _bigrams(b)
    return bool(bx and by) and len(bx & by) / len(bx | by) >= 0.5


def merge_votes(task: str, objs: list[dict]) -> dict:
    """다수 결론을 낸 표 중 먼저 온 것을 대표로 쓰고, 목록 칸은 다른 표 하나 이상에도 있는 항목만 남긴다. 표가 없으면 빈 dict."""
    good = [o for o in objs if o]
    if not good:
        return {}
    keys = [_vote_key(task, o) for o in good]
    best = max(keys, key=lambda k: (keys.count(k), -keys.index(k)))
    same = [o for o, k in zip(good, keys) if k == best]
    out = dict(same[0])
    for name in _VOTE_LISTS.get(task, ()):
        items = out.get(name)
        if isinstance(items, list) and len(same) >= 2:
            others = [o.get(name) if isinstance(o.get(name), list) else [] for o in same[1:]]
            out[name] = [m for m in items if isinstance(m, str) and any(any(_same_item(m, n) for n in other if isinstance(n, str)) for other in others)]
    out["_votes"] = {"n": len(good), "agree": len(same)}
    return out


def judge_from_quotes(obj: dict) -> dict:
    """인용 먼저 판정: checks의 사실마다 quote가 있으면(NOTHING FOUND가 아님) 근거가 있는 사실이다. 결론은 이 목록에서 정한다.
    모든 사실에 구절이 있으면 충분, 일부만 있으면 부분(사실이 둘 이상일 때), 하나도 없으면 부족이다. 구절이 없는 사실은 missing에 옮긴다.
    checks가 없거나 형식이 틀리면 모델의 결론을 그대로 둔다. 되묻기(clarify)는 건드리지 않는다."""
    checks = obj.get("checks")
    rows = [c for c in checks if isinstance(c, dict) and isinstance(c.get("fact"), str)] if isinstance(checks, list) else []
    if not rows:
        return obj
    found = [_squash_quote(c.get("quote")) not in ("", _NOTHING) for c in rows]
    n, f = len(rows), sum(found)
    missing = [c["fact"] for c, ok in zip(rows, found) if not ok]
    return {**obj, "sufficient": f == n, "partial": 0 < f < n and n >= 2, "missing": missing if f < n else [], "_from_quotes": True}


# ---------- FL 사실 기록(`GRAPH_FACTS_LOG`, 기본 꺼짐, 진단 전용) ----------
# 판정 대표 표의 checks(사실, 값)와 첫 답 초안의 asked·picks를 상태에 남긴다. 프롬프트, 입력, 인용, 결론은 바꾸지 않는다(61.39).
def facts_log_enabled() -> bool:
    return _flag("GRAPH_FACTS_LOG")


def judge_facts(obj: dict, retries: int) -> dict:
    """판정 한 번의 기록. checks는 dict 항목만 남긴다."""
    checks = obj.get("checks")
    votes = obj.get("_votes") if isinstance(obj.get("_votes"), dict) else None
    return {"retries": retries, "sufficient": obj.get("sufficient"), "partial": obj.get("partial"),
            "checks": [c for c in checks if isinstance(c, dict)] if isinstance(checks, list) else None, "votes": votes}


def answer_facts(obj: dict) -> dict:
    """첫 답 초안의 asked(질문이 묻는 사실)와 picks(사실마다 값과 근거 chunk_id)."""
    asked, picks = obj.get("asked"), obj.get("picks")
    return {"asked": [a for a in asked if isinstance(a, str)] if isinstance(asked, list) else None,
            "picks": [x for x in picks if isinstance(x, dict)] if isinstance(picks, list) else None}


# ---------- BO2 답 두 개 중 판정 구절과 맞는 쪽(`GRAPH_ANSWER_BEST2`, 기본 꺼짐) ----------
# 같은 입력으로 답을 두 번 쓰고, 판정이 복사한 원문 구절(`GRAPH_JUDGE_QUOTE`의 checks.quote)이 든 문맥 청크 집합 S와 대조해 하나를 고른다(61.45).
# 정답은 쓰지 않는다. 고르는 순서: S에 든 서로 다른 인용 청크 수가 많은 쪽, 같으면 S 밖 인용 수가 적은 쪽, 그래도 같으면 첫 후보.
# 구절이 없으면(판정 구절 끔 포함) 첫 후보다. 고른 뒤 근거 확인과 인용 후처리는 그대로 거친다. 끄면 답 호출과 경로가 그대로다
BEST2_MIN_QUOTE = 15  # 영문·숫자만 남긴 구절이 이보다 짧으면 청크를 찾는 데 쓰지 않는다(흔한 낱말 하나로 맞는 것을 막는다)


def answer_best2_enabled() -> bool:
    return _flag("GRAPH_ANSWER_BEST2")


def best2_samedoc_enabled() -> bool:
    """BO2SD(`GRAPH_BEST2_SAMEDOC`, 기본 꺼짐): 둘째 규칙에서 S 밖 인용 중 S 청크와 같은 문서(rule_seq)인 청크는 세지 않고,
    다른 문서인 청크 수만 비교한다. 같은 문서의 이웃 절은 정당한 추가 근거이고, 다른 문서 청크는 정답 밖 인용 위험이다(61.48)"""
    return _flag("GRAPH_BEST2_SAMEDOC")


def _alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def quote_chunk_ids(obj: dict | None, chunks: list[dict]) -> list[str]:
    """판정 checks의 quote(NOTHING FOUND 제외)를 그대로 담은 문맥 청크의 chunk_id(문맥 순서, 중복 없음). 구절이 없으면 빈 목록."""
    checks = (obj or {}).get("checks")
    quotes = [_alnum(c.get("quote")) for c in checks if isinstance(c, dict) and _squash_quote(c.get("quote")) not in ("", _NOTHING)] if isinstance(checks, list) else []
    quotes = [q for q in quotes if len(q) >= BEST2_MIN_QUOTE]
    if not quotes:
        return []
    out: list[str] = []
    for c in chunks or []:
        body, cid = _alnum(c.get("text")), c.get("chunk_id")
        if cid and cid not in out and any(q in body for q in quotes):
            out.append(cid)
    return out


def quote_rows(obj: dict | None, chunks: list[dict], *, limit: int = 8) -> list[list[str]]:
    """판정 checks를 측정 기록용으로 줄인 것: 사실마다 그 구절을 그대로 담은 문맥 청크 id 목록(구절이 없거나 NOTHING FOUND이면 빈 목록).
    `quote_chunk_ids`와 같은 대조를 사실별로 한다. 사실 문장과 구절 글은 싣지 않고 청크 id만 남긴다. 답 경로는 이 값을 읽지 않는다."""
    checks = (obj or {}).get("checks")
    rows: list[list[str]] = []
    for c in checks if isinstance(checks, list) else []:
        if not isinstance(c, dict):
            continue
        found = _squash_quote(c.get("quote")) not in ("", _NOTHING)
        q = _alnum(c.get("quote")) if found else ""
        ids = [x.get("chunk_id") for x in chunks or [] if x.get("chunk_id") and len(q) >= BEST2_MIN_QUOTE and q in _alnum(x.get("text"))]
        rows.append(list(dict.fromkeys(ids)))
    return rows[:limit]


def _cited_ids(draft: dict) -> list[str]:
    ids: list[str] = []
    for c in draft.get("raw_citations") or []:
        cid = c.get("chunk_id") if isinstance(c, dict) else c
        if isinstance(cid, str) and cid not in ids:
            ids.append(cid)
    return ids


def pick_best2(first: dict | None, second: dict | None, quote_ids: list[str], doc_of: dict | None = None) -> tuple[dict | None, dict]:
    """두 답 초안(draft_fields 결과) 중 하나와 기록 {cands, pick, why}. 한쪽이 없으면 다른 쪽.
    doc_of(chunk_id -> rule_seq)를 주면(BO2SD) 둘째 규칙은 S 청크와 다른 문서인 S 밖 인용 수만 센다. 문서를 모르는 청크는 다른 문서로 센다."""
    cands = [d for d in (first, second)]
    s = set(quote_ids or [])
    samedoc = doc_of is not None
    s_docs = {doc_of.get(i) for i in s if doc_of.get(i) is not None} if samedoc else set()
    log = {"quote_ids": list(quote_ids or []), "cands": [], "pick": 0, "why": "", "rule": "s_in,s_out_otherdoc" if samedoc else "s_in,s_out"}
    for d in cands:
        ids = _cited_ids(d) if d else []
        out = [i for i in ids if i not in s]
        if samedoc:
            out = [i for i in out if doc_of.get(i) is None or doc_of.get(i) not in s_docs]
        log["cands"].append(None if d is None else {"cited": ids, "in_s": sum(i in s for i in ids), "out_s": len(out)})
    if first is None or second is None:
        log["pick"], log["why"] = (1, "첫 후보 없음") if first is None and second is not None else (0, "둘째 후보 없음")
        return (second if log["pick"] else first), log
    from backend.graph.grounding import says_only_absence  # 답 확인(verify)이 답이 아니라고 보는 것과 같은 판별

    absent = [says_only_absence(str(d.get("answer") or "")) for d in cands]
    if absent[0] != absent[1] and log["cands"][absent.index(False)]["cited"]:  # 한쪽만 자료에 없다는 말뿐이고 다른 쪽은 인용이 있는 답이다
        log["pick"], log["why"] = absent.index(False), "한쪽만 자료에 없다는 말"
        return cands[log["pick"]], log
    if not s:
        log["why"] = "구절 없음, 첫 후보"
        return first, log
    a, b = log["cands"]
    if a["in_s"] != b["in_s"]:
        log["pick"], log["why"] = (0 if a["in_s"] > b["in_s"] else 1), "S 안 인용 청크 수"
    elif a["out_s"] != b["out_s"]:
        log["pick"], log["why"] = (0 if a["out_s"] < b["out_s"] else 1), ("S 밖 다른 문서 인용 수" if samedoc else "S 밖 인용 수")
    else:
        log["why"] = "동점, 첫 후보"
    return (second if log["pick"] else first), log


# ---------- HO 겹친 머리 인용 바로잡기(스위치 없이 기본 동작, 사전 등록 62.52) ----------
# 청킹은 앞 청크의 끝 글을 다음 청크의 머리에 겹쳐 둔다. 답이 다음 청크 X를 인용했는데 그 주장을 받친 구절(근거 확인이 복사한 원문 구절)이 모두 X의 겹친 머리에만 있으면,
# 그 글의 원래 자리는 앞 청크 Y다(X의 머리는 문장 중간에서 시작하고, 그 사실을 묻는 제목이나 문단 첫머리는 Y에 있다). Y가 문맥에 있으면 인용을 Y로 바꾼다.
# 근거 확인이 끝난 뒤의 코드 단계이고 LLM 호출이 없다. Y의 본문은 X의 머리 글을 그대로 담고 있어 근거 확인 결과가 달라지지 않는다.
# 구절이 X의 자기 본문에도 있거나, 구절을 찾지 못했거나, Y가 문맥에 없으면 그대로 둔다.
HEAD_MIN_CHARS = 40  # 이보다 짧은 겹침은 우연히 같은 글일 수 있어 겹친 머리로 보지 않는다
HEAD_READ_MAX_CHARS = 400  # 62.58: 문맥 밖 앞 청크를 읽어 보는 것은 구절이 본문 앞 이만큼 안에 있을 때만(겹친 머리는 본문 앞쪽이다. 101번의 머리는 119자)


def head_overlap(chunk: dict, prev: dict) -> int:
    """`chunk` 본문의 머리 중 `prev` 본문의 끝과 그대로 같은 글자 수(`HEAD_MIN_CHARS` 미만이면 0). 같은 페이지 판의 다른 청크일 때만 잰다."""
    if chunk.get("chunk_id") == prev.get("chunk_id") or chunk.get("rule_seq") is None or chunk.get("rule_seq") != prev.get("rule_seq") or chunk.get("version_id") != prev.get("version_id"):
        return 0
    body, tail = _body(chunk), _body(prev)
    for n in range(min(len(body), len(tail)), HEAD_MIN_CHARS - 1, -1):
        if tail.endswith(body[:n]):
            return n
    return 0


def head_owner_cites(body: str, cited: list[dict], context: list[dict], quotes: list[str] | None, prev_reader=None) -> tuple[str, list[dict], list[dict]] | None:
    """HO: `finish_answer`를 거친 본문(표시 `[n]`)과 인용 목록에서, 근거 구절이 겹친 머리에만 있는 인용 청크를 그 글의 원래 청크로 바꾼다.
    (본문, 인용, 바꾼 기록 [{from, to}(문맥 밖 청크로 바꿨으면 outside: True)]). 바꿀 것이 없으면 None. 원래 청크가 이미 인용돼 있으면 표시를 그 번호로 합치고 번호를 다시 매긴다.
    사전 등록 62.58: 원래 청크가 문맥에 없으면 `prev_reader(청크)`가 같은 페이지 판의 바로 앞 청크를 읽어 돌려주고(문맥에는 넣지 않는다), 그 끝이 머리와 그대로 같을 때만 바꾼다.
    읽기가 실패하거나 None이면 그대로 둔다."""
    qs = [q for q in (_alnum(x) for x in quotes or []) if len(q) >= BEST2_MIN_QUOTE and q != "nothingfound"]
    if not qs or not cited:
        return None
    swaps: dict[int, dict] = {}
    outside: set[int] = set()
    for i, x in enumerate(cited):
        text = _body(x)
        mine = [q for q in qs if q in _alnum(text)]
        if not mine:
            continue

        def owns(y: dict) -> bool:
            n = head_overlap(x, y)
            return bool(n) and all(q in _alnum(text[:n]) and q not in _alnum(text[n:]) for q in mine)

        for y in context or []:
            if owns(y):
                swaps[i] = y
                break
        else:
            if prev_reader is None or not all(q in _alnum(text[:HEAD_READ_MAX_CHARS]) for q in mine):  # 머리는 본문 앞쪽이다. 구절이 그보다 뒤에 있으면 읽지 않는다(DB 읽기를 아낀다)
                continue
            try:
                y = prev_reader(x)
            except Exception:  # noqa: BLE001 - 앞 청크 읽기 실패가 답을 막지 않는다
                continue
            if isinstance(y, dict) and y.get("chunk_id") and owns(y):
                swaps[i] = y
                outside.add(i)
    if not swaps:
        return None
    out: list[dict] = []
    number: dict[int, int] = {}
    for i, x in enumerate(cited):
        c = swaps.get(i, x)
        ids = [k["chunk_id"] for k in out]
        if c["chunk_id"] in ids:
            number[i + 1] = ids.index(c["chunk_id"]) + 1
        else:
            out.append(c)
            number[i + 1] = len(out)
    new_body = _NUM.sub(lambda m: f"[{number[int(m.group(1))]}]" if int(m.group(1)) in number else m.group(0), body)
    new_body = re.sub(r"(\[\d+\])(?:\s*\1)+", r"\1", new_body)  # 합쳐져 되풀이된 같은 번호는 한 번만
    return new_body, out, [{"from": cited[i]["chunk_id"], "to": y["chunk_id"], **({"outside": True} if i in outside else {})} for i, y in sorted(swaps.items())]
