"""놓친 문항 해결안(B단계, 2026-11-06). 모두 기본 꺼짐 스위치이고, 꺼져 있으면 그래프의 입력, 프롬프트, 인용이 바뀌지 않는다.

- A3 `GRAPH_CITE_MULTI=1`: 답 프롬프트와 인용 규칙 Skill의 "근거 하나만"을 "같은 사실을 다른 페이지가 말하면 최대 3개"로 바꾼다.
- A5 `GRAPH_KEEP_CITES=1`: 근거 판정 뒤 답을 다시 쓸 때, 처음 답에서 받쳐지지 않는다고 하지 않은 문장의 인용을 코드가 넘겨받는다.
- B1 `GRAPH_SUB_RESEARCH=1`: 일부 근거(partial)로 끝나는 나뉜 질문에서 판정이 빠졌다고 한 사실에 맞는 하위 질문 하나를 원문 그대로 한 번 더 찾는다(그때만 재검색 상한 +1).
- B4 `GRAPH_PAGE_RESEARCH=1`: B1과 같은 때에 그 하위 질문을 지금까지 문맥에 들어온 페이지(rule_seq) 안에서만 다시 찾는다(`Searcher.search_pages`). 기본 검색 경로는 그대로다.
- B2 `GRAPH_REQUERY_VOCAB=1`: 판정이 내는 재검색어에 원 하위 질문의 영어 어휘를 지키고 빠진 사실은 받는 쪽 동사로 쓰라는 규칙을 더한다.
- D1 `GRAPH_UNKNOWN_NAME=1`: 질문의 영문 구(영문 토큰 2개 이상이 이어진 것, 따옴표 안 영문)가 코퍼스 전체(본문과 제목 경로)에 없으면 검색 없이 되묻는다.
  거절 프롬프트를 넓히지 않고 코드 검사로 좁게 둔다(결정 0067의 named 규칙 전례, UAEval4RAG Table 18).
- R `GRAPH_REFUSE_ON_NONE=1`: 첫 근거 판정이 "전무"(sufficient 거짓, partial 거짓, clarify 없음)면 재검색 없이 거절한다.
  #44, #49, #51~#53 기존 행에서 첫 판정이 전무인 관련 문항 행은 0/510행이었다(재검색 분석, 2026-11-06).
- Q `GRAPH_GROUNDING_QUOTE=1`: 근거 확인 프롬프트를 '주장마다 받치는 영어 구절을 먼저 그대로 복사(없으면 NOTHING FOUND)하고 판정'으로 바꾸고(`prompts.question.grounding_quoted`),
  번역·말 바꿈을 받쳐진 것으로 보는 기준을 적는다. 호출 수는 그대로다. 근거: 기존 425행 중 근거 확인이 받쳐지지 않는다고 한 관련 문항 12행은
  모두 첫 답이 정답 근거를 인용했고(3, 4, 7, 14, 15, 39번, 다시 쓰기 +3~4초, 7번 1행은 거절), 비관련 4행은 모두 22번이다.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from backend.graph import grounding as G
from backend.graph.untrusted import drop_suspect_tokens, strip_instructions


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def cite_multi_enabled() -> bool:
    return _flag("GRAPH_CITE_MULTI")


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


def drop_unjudged_cites(draft: str, cited: list[dict], quote_ids: list[str] | None) -> tuple[str, list[dict], list[str], int] | None:
    """사전 등록 62.66: 일부 판정으로 끝난 답(`draft`, 표시 `[chunk_id]`)에서 단 인용이 모두 판정 구절 청크(`quote_ids`) 밖인 문장을 뺀다.
    판정이 근거가 없다고 한 사실을 다른 청크로 써 넣은 문장을 거르는 규칙이다. 표시가 없는 문장과 판정 구절 청크가 하나라도 섞인 문장은 그대로 둔다.
    돌려주는 것: (남은 답, 남은 인용, 빠진 인용의 chunk_id, 뺀 문장 수). 판정 구절 청크를 모르거나(빈 목록), 뺄 문장이 없거나,
    빼고 나면 판정 구절 청크를 인용한 문장이 하나도 남지 않으면 None(답을 그대로 둔다. 빈 답이나 근거 없는 답을 내지 않는다)."""
    judged = {x for x in quote_ids or [] if x}
    if not judged or not (draft or "").strip():
        return None
    lines_out: list[str] = []
    dropped = 0
    has_judged = False
    for line in draft.split("\n"):
        sentences = G.split_sentences(line)
        keep: list[str] = []
        for s in sentences:
            marks = set(_MARK.findall(s))
            if marks and not marks & judged:
                dropped += 1
                continue
            has_judged = has_judged or bool(marks & judged)
            keep.append(s)
        if len(keep) == len(sentences):
            lines_out.append(line)  # 뺄 것이 없는 줄은 글자 그대로 둔다
        elif keep:
            lines_out.append(" ".join(keep))
    if not dropped or not has_judged:
        return None
    new_draft = "\n".join(lines_out).strip()
    left = set(_MARK.findall(new_draft))
    return new_draft, [c for c in cited if c["chunk_id"] in left], [c["chunk_id"] for c in cited if c["chunk_id"] not in left], dropped


def grounding_quote_enabled() -> bool:
    return _flag("GRAPH_GROUNDING_QUOTE")


_NOTHING = "nothing found"


def _squash_quote(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’`]", "", str(s or "").lower())).strip(" .,;:")


def speculate_enabled() -> bool:
    return _flag("GRAPH_SPECULATE_FIRST")


def speculate_early_search_enabled() -> bool:
    """SE `GRAPH_SPECULATE_EARLY_SEARCH=1`(`GRAPH_SPECULATE_FIRST`와 같이 쓴다): 예비 분해(`decompose_gate`)가 끝나길 기다리지 않고 원 질문의 첫 검색을 같은 시각에 시작한다.
    예비 분해가 나누지 않고 분류가 정책 경로이면 그 결과를 쓰고(입력은 같다), 아니면 버린다. 코드 기본은 꺼짐이고 서비스 설정(`service_profile.SERVICE_ENV`)에서 켠다(사전 등록 62.53)."""
    return _flag("GRAPH_SPECULATE_EARLY_SEARCH")


def speculate_ground_enabled() -> bool:
    """SG `GRAPH_SPECULATE_GROUND=1`: 답 후보가 나오는 대로 그 답의 근거 판정을 미리 부르고, 나중에 같은 입력의 판정이 필요하면 그 결과를 쓴다(입력과 판정 기준은 그대로)."""
    return _flag("GRAPH_SPECULATE_GROUND")


def adopt_grounded_enabled() -> bool:
    """`GRAPH_ADOPT_GROUNDED_CANDIDATE=1`(기본 꺼짐, `GRAPH_SPECULATE_GROUND`가 켜져 있어야 동작, 사전 등록 62.68): 고른 답의 근거 확인이 받쳐지지 않는 주장을 찾아
    답을 다시 쓰기 전에, 같은 요청에서 미리 부른 다른 답 후보의 근거 확인이 이미 끝나 같은 일부 답 값·같은 문맥으로 받쳐졌다고 했으면 그 후보를 쓴다.
    그 후보는 고른 답과 같은 검사와 후처리를 다시 거치고, 하나라도 통과하지 못하면 지금처럼 다시 쓴다."""
    return _flag("GRAPH_ADOPT_GROUNDED_CANDIDATE")


def unchanged_rejudge_enabled() -> bool:
    """UR `GRAPH_UNCHANGED_REJUDGE=1`: 근거 판정이 받쳐지지 않는다고 하고, 사유를 받은 다시 쓰기가 처음 답을 그대로 내면 처음 답을 같은 입력으로 한 번 더 판정한다.
    받쳐지면 그 답을 내고, 아니면 지금처럼 문장 빼기와 거절로 간다(그 행에만 판정 호출 +1). 근거: 기존 agent_v2 행에서 이 경로(다시 쓰기 unchanged)는 5행이고
    모두 관련 문항(7번 2행, 14, 4, 31번)이 거절된 행이다. 비관련 문항은 0행. 7번은 같은 검색 결과에서 판정이 131행 중 8행만 받쳐지지 않는다고 했다(61.15 멀티 7번)."""
    return _flag("GRAPH_UNCHANGED_REJUDGE")


def judged_none(obj: dict) -> bool:
    """판정 결과가 "전무"인지: sufficient가 거짓(False)이고 partial이 참이 아니며 되묻기가 없다. 파싱 실패(sufficient 없음)는 전무로 보지 않는다."""
    clarify = obj.get("clarify")
    return obj.get("sufficient") is False and obj.get("partial") is not True and not (isinstance(clarify, str) and clarify.strip())


_MARK = re.compile(r"\[([0-9a-f]{16})\]")


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


# ---------- A5 인용 넘겨받기 ----------
def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\[[0-9a-f]{16}\]|\s+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def carry_citations(draft: str, draft_cited: list[dict], flagged: list[str], new_answer: str, new_cited: list[dict]) -> tuple[str, list[dict]]:
    """처음 답(draft)에서 받쳐지지 않는다고 하지 않은 문장의 인용 중 새 답에 없는 것을 새 답에 넘긴다.
    표시는 새 답에서 그 문장과 가장 비슷한 문장 끝에 붙인다(겹침이 없으면 넘기지 않는다). 인용 수 상한(4)은 사전 등록 62.72로 없앴다."""
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
            if cid in have or cid not in by_id or not sents:
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
# `//` 없이 쓰는 스킴(`javascript:alert(1)`, `data:text/html,…`)도 주소다(놓친 것 11/13 새로 발견 5). 일반 단어 뒤 쌍점(`Note:`)은 막지 않도록 스킴 이름을 적어 둔다
_ECHO_URL = re.compile(r"[a-z][a-z0-9+.\-]*://|\b(?:javascript|vbscript|data|file|blob|mailto)\s*:|www\.|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![a-z0-9-])|(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", re.I)
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


def none_vote_wait_s() -> float | None:
    """`GRAPH_NONE_VOTE_WAIT_S`(초, 기본 빈 값, 서비스 설정 1.0): 판정 다수결에서 먼저 온 두 표가 모두 "근거 없음"(충분도 일부도 아님)이면
    셋째 표를 이 초만큼만 더 기다리고, 그 안에 오지 않으면 두 표로 확정한다(`build.voted`, 기록 `how="none_capped"`). 두 표가 같은 결론이라 바로 거절된다.
    빈 값이면 None이고 지금처럼 셋째 표를 끝까지 기다린다. 숫자가 아니거나 음수면 ValueError다.
    근거(정답을 보지 않은 실행 기록, 운영 00056~00057): 첫 두 표가 모두 근거 없음인 143행 중 셋째 표가 달랐던 것은 비관련 질문 1행(재검색 뒤 거절)이고 관련 질문은 0행이었다."""
    raw = (os.environ.get("GRAPH_NONE_VOTE_WAIT_S") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"GRAPH_NONE_VOTE_WAIT_S는 0 이상의 초다: {raw!r}") from None
    if value < 0:
        raise ValueError(f"GRAPH_NONE_VOTE_WAIT_S는 0 이상의 초다: {raw!r}")
    return value


def spec_stop_ground_enabled() -> bool:
    """`GRAPH_SPEC_STOP_GROUND=1`(기본 꺼짐, 서비스 설정에서 켬): 미리 돌리기(`GRAPH_SPECULATE_FIRST`)를 분해 결과가 달라 버리기로 했으면,
    그 미리 돌리기가 쓴 답 후보의 근거 확인을 미리 부르지 않는다(`build.draft_reply`, 기록 `verdict="skipped_spec_dropped"`). 본 경로의 답은 그대로다.
    근거(정답을 보지 않은 실행 기록): 버린 미리 돌리기에서도 근거 확인을 미리 불러 호출이 늘었다(같은 묶음에서 38회 대 22회)."""
    return _flag("GRAPH_SPEC_STOP_GROUND")


def judge_quote_enabled() -> bool:
    return _flag("GRAPH_JUDGE_QUOTE")


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


def pick_best2(first: dict | None, second: dict | None, quote_ids: list[str]) -> tuple[dict | None, dict]:
    """두 답 초안(draft_fields 결과) 중 하나와 기록 {cands, pick, why}. 한쪽이 없으면 다른 쪽."""
    cands = [d for d in (first, second)]
    s = set(quote_ids or [])
    log = {"quote_ids": list(quote_ids or []), "cands": [], "pick": 0, "why": "", "rule": "s_in,s_out"}
    for d in cands:
        ids = _cited_ids(d) if d else []
        out = [i for i in ids if i not in s]
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
        log["pick"], log["why"] = (0 if a["out_s"] < b["out_s"] else 1), "S 밖 인용 수"
    else:
        log["why"] = "동점, 첫 후보"
    return (second if log["pick"] else first), log
