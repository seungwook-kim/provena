"""코퍼스 전체(23,095청크)에서 표·수치가 든 청크를 원문 스냅샷과 대조한다 (체크포인트 3조 코멘트 ②, 2026-11-13).

앞서 한 일(`table_number_source_check_20261113`, `_all`)은 평가 정답 청크 123개 중 표·수치 60개만 봤다. 이 스크립트는 같은 방식을 코퍼스 전체로 넓힌다.
LLM·키·운영 호출·네트워크 없음. 저장소 파일은 읽기만 한다(`--out` 폴더에만 쓴다). `--fetch-sample`을 줄 때만 표본 청크의 공개 원문을 GET한다.

대상 고르는 규칙 (청크마다, 청크 글 전체 = 제목 줄 + 겹침 + 본문):
  수치: 아래 값이 하나라도 든다 (check.py `values()`와 같은 규칙).
        금액($100, $25K), 비율(15%), 기간(15 minutes, 90 days), 등급·단계(Tier 1, Level 2, P1, S1), 개수(20 people).
  표:   (a) 청크에 속한 파싱 요소(`element_ids`) 중 table_row가 있거나, (b) 청크 줄 범위(`line_start`~`line_end`)의 원문에 HTML 표(`<table`, `<tr`, `<td`)나
        마크다운 표(구분 줄 `|---|` 또는 `|`로 시작·끝나는 줄)가 있거나, (c) 승인 권한표 행(kind=row)이다.
  대상 = 수치 또는 표.  (참고로 수치·표가 아닌데 숫자만 든 청크는 "숫자 토큰 확인" 한 줄만 따로 센다.)

대조 (모두 스냅샷 `data/corpus.tar.gz` 안 원문):
  1. 숫자 대조: 청크의 수치 값과 단위 없는 숫자(`#5`)를 모두 원문 줄 범위에서 찾는다. 값마다 앞뒤 낱말 3개도 같아야 한다.
     제목 줄과 앞 청크에서 겹쳐 들어온 앞부분은 줄 범위 밖이라 같은 쪽 전체에서 찾는다.
     줄 범위에서는 못 찾고 쪽의 다른 곳에서만 찾으면 "범위 밖"으로 따로 센다.
  2. 표 행·열 대조: 청크에 속한 table_row마다, 원문 표를 파이썬 표준 라이브러리로 따로 읽어(마크다운 표 줄·HTML <tr>/<td>)
     열 이름(표 머리 줄)과 칸 값을 뽑고, 청크가 쓰는 행 모양(`열 이름: 값 | 열 이름: 값`, 빈 칸 생략)으로 다시 써서 청크 본문 낱말과 순서까지 맞춘다.
     칸을 서로 바꾸거나 다른 행의 값이 들어가면 여기서 잡힌다.
  3. 권한표 행·이사회 행: 원문 HTML 줄(`<div class="item-auth-matrix">값</div> <!-- 역할 -->`)에서 역할·값을 따로 읽어 청크의 `- 역할 (…approval): 값` 줄과 맞춘다.
  4. 겹침 조각: 겹침 글이 앞 청크 본문의 꼬리인지, 표 행 중간에서 시작해 앞 칸이 빠졌는지 센다.
  5. 자기 시험: 청크 글에 틀린 값을 일부러 넣어(숫자 변경, 칸 서로 바꾸기, 행 값 바꾸기, 쪽의 다른 숫자로 바꾸기) 검사기가 잡는지 센다.

사용: python -I -B check_corpus.py --root <provena 저장소> --out <결과 폴더> [--fetch-sample --cache <폴더>]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import random
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
DEFAULT_ROOT = Path(r"C:\Users\Wook\Desktop\학원\메인프로젝트\3.main_project\provena")
KST = timezone(timedelta(hours=9))
SEED = 20261113


def find_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    here = Path(__file__).resolve().parents
    if len(here) > 3 and (here[3] / "data" / "index" / "chunks.jsonl").exists():
        return here[3]
    return DEFAULT_ROOT


ROOT = DEFAULT_ROOT
PREV_BODY: dict[str, str] = {}      # 청크 id -> 앞 청크 본문(겹침 확인용)
C = None  # 기존 check.py (읽기만 함)


def load_base(root: Path):
    """기존 check.py를 가져온다(수치 값 뽑는 규칙을 그대로 쓰기 위해). 바이트코드는 쓰지 않는다."""
    global ROOT, C
    ROOT = root
    sys.path.insert(0, str(root / "evals" / "results" / "table_number_source_check_20261113"))
    sys.path.insert(0, str(root))
    import check as _c  # noqa: E402
    C = _c


# ------------------------------------------------------------------ 입력
def load_all(root: Path):
    chunks = [SimpleNamespace(**json.loads(l)) for l in (root / "data" / "index" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    pages = {p["rule_seq"]: p for p in map(json.loads, (root / "data" / "corpus" / "pages.jsonl").read_text(encoding="utf-8").splitlines())}
    ir = {}
    for f in ("document_ir.jsonl", "authz_ir.jsonl"):
        for l in (root / "data" / "parsed" / f).open(encoding="utf-8"):
            d = json.loads(l)
            ir[d["element_id"]] = d
    cells = [json.loads(l) for l in (root / "data" / "parsed" / "authz_cells.jsonl").open(encoding="utf-8")]
    board = [json.loads(l) for l in (root / "data" / "parsed" / "authz_board.jsonl").open(encoding="utf-8")]
    return chunks, pages, ir, cells, board


class Snap:
    """스냅샷 tar의 원문 줄·글자 캐시."""

    def __init__(self, root: Path, pages):
        self.tar = tarfile.open(root / "data" / "corpus.tar.gz")
        self.sha = hashlib.sha256((root / "data" / "corpus.tar.gz").read_bytes()).hexdigest()
        self.pages = pages
        self.titles = {"handbook/" + p["path"].replace("content/handbook/", ""): p["title"] for p in pages.values()}
        self.titles["authz/authorization-matrix-2023-05.html.md"] = "Authorization Matrix (2023-05)"      # chunk.py AUTHZ_TITLE 상수
        self._lines: dict[str, list[str]] = {}
        self._pg: dict[str, dict] = {}

    def member(self, c) -> str:
        p = self.pages.get(c.rule_seq)
        return "handbook/" + p["path"].replace("content/handbook/", "") if p else "authz/authorization-matrix-2023-05.html.md"

    def lines(self, m: str) -> list[str]:
        if m not in self._lines:
            self._lines[m] = self.tar.extractfile(m).read().decode("utf-8").split("\n")
        return self._lines[m]

    def _head_vals(self, m: str) -> set:
        """제목 줄(머리말 줄)에 나올 수 있는 값: 쪽 제목(pages.jsonl)과 원문의 제목 줄(# …, title:, <h1>…)."""
        heads = [self.titles.get(m, "")]
        for ln in self.lines(m):
            if re.match(r"^\s{0,3}#{1,6}\s", ln) or re.match(r"^\s*title:", ln) or re.search(r"<h[1-6]\b", ln, re.I):
                heads.append(ln)
        txt = md_to_text2("\n".join(heads))
        return set(C.values(txt)) | set(C._bare(txt))

    def page(self, m: str) -> dict:
        """쪽 전체의 글자·낱말·값 (한 번만 계산)."""
        if m not in self._pg:
            text = md_to_text2("\n".join(self.lines(m)))
            raw = html.unescape("\n".join(self.lines(m)))
            self._pg[m] = {"text": text, "words": C.words(text), "vals": set(C.values(text)) | set(C._bare(text)),
                           "raw_vals": set(C.values(raw)) | set(C._bare(raw)), "ngrams": {},
                           "name_vals": set(C._bare(re.sub(r"[-_./]", " ", m.rsplit("/", 1)[-1]))),      # 제목 줄 숫자는 파일 이름에서도 온다(권한표 제목 "(2023-05)")
                           "head_vals": self._head_vals(m)}
        return self._pg[m]


def page_has(pg: dict, ctx: str) -> bool:
    """쪽 전체 낱말에서 ctx(낱말 n개)를 찾는다(n-그램 집합을 쪽마다 한 번만 만든다)."""
    if not ctx:
        return True
    cw = tuple(ctx.split())
    n = len(cw)
    if n not in pg["ngrams"]:
        w = pg["words"]
        pg["ngrams"][n] = {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}
    return cw in pg["ngrams"][n]


# ------------------------------------------------------------------ 1. 숫자 대조
def cmp_window(vals, win_text: str, raw_vals: set):
    """줄 범위 글(win_text)에서 값과 문맥을 찾는다. 반환: (없는 값, 문맥이 다른 값)."""
    sw = C.words(win_text)
    src_vals = set(C.values(win_text)) | set(C._bare(win_text))
    missing, ctx_diff = [], []
    for v, ctx in vals:
        if v not in src_vals:
            missing.append(v)
        elif not C.present(ctx, sw):
            ctx_diff.append({"value": v, "chunk_context": ctx})
    return missing, ctx_diff


def number_check(c, text: str, lines: list[str], pg: dict, extra_lines: list[str] = (), row_texts: list[str] = (), code_raw: bool = False) -> dict:
    # 표 행 청크는 열 이름(표 머리 줄)을 행마다 붙이는데 머리 줄은 줄 범위 밖이므로, 그 표의 머리 줄도 같은 범위로 본다
    window = "\n".join(list(lines[c.line_start - 1: c.line_end]) + list(extra_lines))
    header, _, body = text.partition("\n")
    ov = c.overlap_chars or 0
    overlap, main_body = body[:ov], body[ov + 1:] if ov else body
    # 표 행(table_row 요소) 글은 값만 맞추고 앞뒤 낱말은 보지 않는다: `Tier 1: …`처럼 열 이름에 숫자가 든 행은 낱말 규칙이 열 이름을 못 떼고, 열·칸 짝짓기는 표 행 대조가 더 엄격하게 본다
    body_rest = main_body
    row_vals = []
    for rt in sorted(set(row_texts), key=len, reverse=True):
        if rt and rt in body_rest:
            body_rest = body_rest.replace(rt, "\n")
            row_vals += [(v, "") for v in C.values(rt) + C._bare(rt)]
    vals_body = list(dict.fromkeys(C._ctx_with_bare(body_rest, True) + row_vals))
    # 겹침 글은 앞 청크 본문의 꼬리다. 꼬리인지는 따로 글자 그대로 맞추므로(check_chunk) 여기서는 값만 쪽에서 찾는다
    vals_other = [(v, "") for v in C.values(header) + C._bare(header) + C.values(overlap) + C._bare(overlap)]
    header_only = set(C.values(header) + C._bare(header))
    win_text = md_to_text2(window)
    if code_raw:         # 코드 요소는 줄 범위 안이 코드 한가운데라 펜스 줄이 없다: 원문 줄 그대로도 함께 본다
        win_text += " " + re.sub(r"\s+", " ", html.unescape(window))
    win_raw_vals = set(C.values(html.unescape(window))) | set(C._bare(html.unescape(window)))
    miss_b, ctx_b = cmp_window(vals_body, win_text, win_raw_vals)
    in_page_only = [v for v in miss_b if v in pg["vals"]]
    # 줄 범위에는 없고 쪽에도 (화면 글자로는) 없지만 원본 표기(링크 주소·태그 속)에는 있음
    via_raw = [v for v in miss_b if v not in pg["vals"] and v in pg["raw_vals"]]
    missing = [v for v in miss_b if v not in pg["vals"] and v not in pg["raw_vals"]]
    # 겹침·제목 줄은 쪽 전체에서 찾는다
    header_out = []
    for v, ctx in vals_other:
        if v in header_only:         # 제목 줄의 값은 쪽 제목·원문 제목 줄에서 찾는다(쪽 아무 데서나 찾지 않는다)
            if v not in pg["head_vals"] and v not in pg["name_vals"]:
                (header_out if v in pg["vals"] else missing).append(v)
            continue
        if v not in pg["vals"]:
            (via_raw if v in pg["raw_vals"] else missing).append(v)
        elif not page_has(pg, ctx):
            ctx_b.append({"value": v, "chunk_context": ctx})
    allv = list(dict.fromkeys(v for v, _ in vals_other + vals_body))
    ok = not missing and not ctx_b and not in_page_only and not header_out
    return {"values": allv, "missing": missing, "outside_range": in_page_only, "header_not_in_headings": header_out, "ctx_diff": ctx_b, "via_raw_markup": via_raw, "ok": ok}


# ------------------------------------------------------------------ 2. 표 행·열 대조 (원문 표를 따로 읽는다)
PIPE_SPLIT = re.compile(r"(?<!\\)\|")
SEP_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")


def md_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [x.strip() for x in PIPE_SPLIT.split(s)]


def _mdurl_decode(u: str) -> str:
    """markdown-it가 자동 링크 글자를 보여 줄 때 쓰는 퍼센트 풀기: ; / ? : @ & = + $ , # 는 그대로 둔다."""
    return re.sub(r"%([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)) if int(m.group(1), 16) < 128 and chr(int(m.group(1), 16)) not in ";/?:@&=+$,#" else m.group(0), u)


def strip_links(s: str) -> str:
    """`[글자](주소)` -> 글자. 주소 안의 괄호 쌍은 맞춰서 센다(`…(archive)…`)."""
    out, i = [], 0
    rx = re.compile(r"\[([^\]\n]*)\]\(")
    while True:
        m = rx.search(s, i)
        if not m:
            out.append(s[i:])
            break
        depth, j = 1, m.end()
        while j < len(s) and depth and s[j] != "\n":
            depth += (s[j] == "(") - (s[j] == ")")
            j += 1
        if depth:                       # 닫히지 않으면 링크가 아니다
            out.append(s[i:m.end()])
            i = m.end()
            continue
        out.append(s[i:m.start()])
        out.append(m.group(1))
        i = j
    return "".join(out)


TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")        # 글자로 시작하는 것만 태그다(`<75%`, `<20%`는 글자)


def md_to_text2(src: str) -> str:
    """check.py `md_to_text`와 같되: `<75%` 같은 부등호를 태그로 지우지 않고, 주소 속 괄호를 맞추고,
    코드(``` 블록과 `…`) 안은 태그·강조 표시처럼 보여도 글자 그대로 둔다(`6*9`, `<br/>`)."""
    keep: list[str] = []

    def _k(m: re.Match) -> str:
        keep.append(m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(0))
        return f"\x00{len(keep) - 1}\x00"

    def _fence(m: re.Match) -> str:
        keep.append("\n" + m.group(2) + "\n")
        return f"\x00{len(keep) - 1}\x00"

    t = re.sub(r"(?ms)^[ \t]*(```+|~~~+)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$", _fence, src)
    t = re.sub(r"(`+)(.+?)\1", _k, t)
    t = re.sub(r"<!--(.*?)-->", r" \1 ", t, flags=re.S)
    t = strip_links(t)
    t = TAG.sub(" ", t)
    t = re.sub(r"\*\*|__", "", t)                      # 강조 표시는 지우기만 한다(`…__.` 뒤 마침표가 떨어지지 않게)
    t = re.sub(r"(?<![\w])_(?=\S)(.+?)(?<=\S)_(?![\w])", r" \1 ", t)       # _강조_
    t = t.replace("*", "")
    t = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", t)          # 백슬래시 이스케이프(`100\%` -> 100%)
    t = re.sub(r"[>#|]+", " ", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)
    return re.sub(r"\s+", " ", t)

SHORTCODE = re.compile(r"\{\{([<%])\s*(/\*)?\s*(/)?\s*([\w/.-]+)(.*?)\s*[%>]\}\}")
NAME_SC = {"member-by-name", "member-by-gitlab", "member-and-role-by-gitlab", "label"}
WRAP_SC = {"alert", "details", "panel", "note", "tableau"}
EMOJI_NAME = re.compile(r"(?<![\w/:]):[a-z][a-z0-9_+-]*:(?![\w/:])")


def _shortcode(m: re.Match) -> str:
    """Hugo 단축코드가 화면에 내는 글자 (parse.py 머리말의 분류와 같은 규칙: 이름 인자는 글자로, 감싸기는 제목만, 데이터 채움은 지움)."""
    escaped, closing, name, args = m.group(2), m.group(3), m.group(4), m.group(5)
    if escaped:
        return m.group(0).replace("/*", "").replace("*/", "")
    if name in WRAP_SC:
        t = re.search(r'(?:summary|header)="([^"]*)"', args)
        return t.group(1).replace("**", "") if (t and not closing) else ""
    if name in NAME_SC:
        n = re.search(r'name="([^"]*)"', args)
        return n.group(1) if n else ", ".join(re.findall(r'"([^"]*)"', args))
    if name == "ref":
        return (re.findall(r'"([^"]*)"', args) or [""])[0]
    return ""


def cell_text(s: str) -> str:
    """표 칸 한 개의 원문(마크다운·HTML·단축코드)에서 화면에 보이는 글자만 남긴다."""
    s = SHORTCODE.sub(_shortcode, s)
    spans: list[str] = []

    def _keep(m: re.Match) -> str:       # 코드 조각(`…`) 안은 태그처럼 보여도 글자 그대로 남는다
        spans.append(m.group(2).strip())
        return f"\x00{len(spans) - 1}\x00"

    s = re.sub(r"(`+)(.+?)\1", _keep, s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"<(https?://[^>\s]+)>", lambda m: _mdurl_decode(m.group(1)), s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r" \1 ", s)
    s = strip_links(s)
    s = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", s)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~])", r"\1", s)
    s = EMOJI_NAME.sub("", s)
    s = re.sub(r"[*`]", "", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], s) if spans else s


XWORD = re.compile(r"[a-z0-9$%.]+(?:[-'][a-z0-9]+)*|[<>=+~]|[^\x00-\x7f\s]")


def xwords(text: str) -> list[str]:
    """표 행 대조용 낱말: check.py `words()` 규칙에 비교·덧셈 기호(< > = + ~)와 ASCII가 아닌 글자(✅, ≥, —)를 한 글자씩 낱말로 더한다.
    기호만 다른 칸 바꿈(✅와 ❌, <=와 >)도 잡기 위해서다."""
    t = html.unescape(text).replace("\xa0", " ").lower()
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = re.sub(r"\$\s+(?=\d)", "$", t)
    return XWORD.findall(t.replace("’", "'"))


def toks(s: str) -> list[str]:
    return xwords(cell_text(s))


class _Tables(HTMLParser):
    """HTML 조각에서 <table>마다 행(<tr>)의 칸 글자와 머리 칸(<th>) 여부를 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[dict]] = []
        self._row = None
        self._cell = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._close_cell()
            if self._row is not None:
                self.tables[-1].append(self._row)          # </tr>가 빠진 원문: 다음 <tr>이 오면 앞 행을 닫는다
            self._row = {"cells": [], "th": False}
        elif tag in ("td", "th") and self._row is not None:
            self._close_cell()
            self._cell = []
            if tag == "th":
                self._row["th"] = True
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif self._cell is not None:
            self._cell.append(" ")

    def _close_cell(self):
        if self._cell is not None and self._row is not None:
            self._row["cells"].append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
        self._cell = None

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._close_cell()
        elif tag == "tr" and self._row is not None and self.tables:
            self._close_cell()
            self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
        elif self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def html_rows(window: str) -> list[tuple[list[str], list[str]]]:
    """HTML 블록의 (머리 칸 목록, 칸 목록) 행 순서대로. 빈 행은 건너뛴다(파서와 같은 규칙)."""
    p = _Tables()
    p.feed(window)
    out = []
    for rows in p.tables:
        rows = [r for r in rows if any(r["cells"])]
        if not rows:
            continue
        head = rows[0]["cells"] if rows[0]["th"] else []
        body = rows[1:] if rows[0]["th"] else rows
        out += [(head, r["cells"]) for r in body]
    return out


def md_header_idx(lines: list[str], row_line: int) -> int | None:
    """마크다운 표 행(1부터) 위로 올라가 구분 줄 바로 앞 줄(열 이름 줄)의 0부터 색인."""
    i = row_line - 2
    while i >= 0 and "|" in lines[i]:
        if SEP_ROW.match(lines[i]):
            return i - 1 if i >= 1 and "|" in lines[i - 1] else None
        i -= 1
    return None


def md_header(lines: list[str], row_line: int) -> list[str]:
    """마크다운 표 행(1부터 줄 번호) 위로 올라가 구분 줄 바로 앞 줄을 열 이름으로 읽는다."""
    i = row_line - 2
    while i >= 0 and "|" in lines[i]:
        if SEP_ROW.match(lines[i]):
            return md_cells(lines[i - 1]) if i >= 1 and "|" in lines[i - 1] else []
        i -= 1
    return []


def expected_row_tokens(header: list[str], cells: list[str]) -> list[str]:
    """청크의 행 모양(`열: 값 | 열: 값`, 빈 칸 생략)으로 다시 쓴 원문 행의 낱말."""
    out = []
    for h, v in zip(header + [""] * len(cells), cells):
        tv = toks(v)
        if not cell_text(v).strip():
            continue
        out += (toks(h + ": ") if h else []) + tv
    return out


def table_row_check(c, body: str, ir: dict, snap: Snap, lines: list[str], cache: dict) -> dict:
    """청크 본문 낱말 = (표 행은 원문 표를 따로 읽어 다시 쓴 낱말, 그 밖의 요소는 파싱 요소 글자의 낱말)을 순서대로 이은 것인가."""
    els = [ir[e] for e in c.element_ids]
    n_rows = sum(1 for e in els if e["kind"] == "table_row")
    if n_rows == 0:
        return {"rows": 0, "ok": True}
    expected: list[str] = []
    detail = []
    parser_vs_src = []
    for e in els:
        if e["kind"] != "table_row":
            expected += xwords(e["text"])
            continue
        if e.get("source") == "html":
            key = (c.rule_seq, e["line_start"], e["line_end"])
            if key not in cache:
                cache[key] = html_rows("\n".join(lines[e["line_start"] - 1: e["line_end"]]))
            rows = cache[key]
            # 같은 블록 안 요소 순서(row)는 표마다 다시 0부터라서, 블록의 table_row 요소 순서로 센다
            idx = cache.setdefault(("idx", key), [x for x in ir.values() if x["rule_seq"] == c.rule_seq and x["kind"] == "table_row" and x.get("source") == "html" and (x["line_start"], x["line_end"]) == (e["line_start"], e["line_end"])])
            n = [x["element_id"] for x in idx].index(e["element_id"])
            if n >= len(rows):
                detail.append({"element": e["element_id"], "problem": "원문 HTML 표에서 행을 못 찾음"})
                expected += xwords(e["text"])
                continue
            head, cells = rows[n]
        else:
            ln = lines[e["line_start"] - 1]
            if "|" not in ln:
                detail.append({"element": e["element_id"], "problem": "원문 줄이 마크다운 표 행이 아님", "line": e["line_start"]})
                expected += xwords(e["text"])
                continue
            cells = md_cells(ln)
            head = md_header(lines, e["line_start"])
        exp = expected_row_tokens(head, cells)
        # 파싱 요소(IR)가 원문 행과 같은지도 따로 본다 (청크 → 요소 → 원문 사슬)
        if exp != xwords(e["text"]):
            parser_vs_src.append(e["element_id"])
        expected += exp
    got = xwords(body)
    if got == expected:
        ok, how = True, "same"
    elif len(els) == 1 and len(els[0]["text"]) > 800 and body.strip() and body.strip() in els[0]["text"]:      # 800자(chunk.py SIZE)를 넘는 요소만 쪼개진다
        ok, how = True, "split_piece"          # 800자를 넘는 요소 하나를 쪼갠 조각: 조각이 요소 글자의 일부이고, 요소 전체는 원문 행과 따로 맞춘다
    else:
        ok, how = False, "diff"
    res = {"rows": n_rows, "ok": ok and not parser_vs_src and not detail, "how": how}
    if not ok:
        res["first_diff"] = _first_diff(got, expected)
    if parser_vs_src:
        res["element_vs_source_diff"] = parser_vs_src[:5]
    if detail:
        res["problems"] = detail[:5]
    return res


def _contains(big: list[str], small: list[str]) -> bool:
    n = len(small)
    return n > 0 and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def _first_diff(a: list[str], b: list[str]) -> dict:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return {"index": i, "chunk": " ".join(a[max(0, i - 4): i + 4]), "source": " ".join(b[max(0, i - 4): i + 4])}
    return {"index": min(len(a), len(b)), "chunk_len": len(a), "source_len": len(b)}


# ------------------------------------------------------------------ 3. 권한표 행·이사회 행
AUTH_DIV = re.compile(r'<div class="item-auth-matrix"[^>]*>(.*?)</div>\s*(?:<!--\s*(.*?)\s*-->)?')
ALIAS = {"exec team": "exec group"}


def authz_header(lines: list[str]) -> list[tuple[str, str]]:
    """맨 위 표 머리: (역할, functional|financial). 원문의 grid-column 칸 나눔을 읽는다."""
    roles, spans, seen_empty = [], [], 0
    for ln in lines[:200]:
        m = re.search(r'grid-column:\s*(\d+)\s*/\s*(\d+)"[^>]*><b>(Functional|Financial) approval', ln)
        if m:
            spans.append((int(m.group(1)), int(m.group(2)), m.group(3).lower()))
        mb = re.match(r'\s*<div class="item-auth-matrix"><b>(.*?)</b></div>', ln)
        if mb and "grid-column" not in ln and not mb.group(1).startswith("Approving"):
            roles.append(mb.group(1))
        if "Approving expense" in ln:
            break
    out = []
    for i, r in enumerate(roles):
        col = i + 2          # 1열은 비어 있는 칸
        kind = next((k for a, b, k in spans if a <= col < b), "?")
        out.append((r, kind))
    return out


def authz_row_check(c, text: str, lines: list[str], pg: dict, hdr: list[tuple[str, str]]) -> dict:
    body = text.partition("\n")[2]
    window = lines[c.line_start - 1: c.line_end]
    problems = []
    if c.config == "authz-board":
        w = md_to_text2("\n".join(window))
        item, _, appr = body.partition(": ")
        wt = C.words(w)
        for part in (item, appr):
            pt = C.words(md_to_text2(part))
            if not _contains(wt, pt):
                problems.append(f"원문 줄 범위에 없는 글: {part[:40]}")
        return {"ok": not problems, "problems": problems}
    # 원문에서 (역할, 값) 읽기
    src = []
    for ln in window:
        m = AUTH_DIV.search(ln)
        if m:
            val = re.sub(r"<sup>.*?</sup>", "", m.group(1))        # 각주 번호 (n)은 칸 값이 아니다
            src.append(((m.group(2) or "").strip(), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(val))).strip()))
    htype = {r.lower(): k for r, k in hdr}
    src_filled = {(ALIAS.get(r.lower(), r.lower()), v.lower()) for r, v in src if v}
    bullets = []
    for ln in body.split("\n"):
        m = re.match(r"^- (.+?) \((functional|financial) approval\): (.*?)((?: \(\d+\))*)$", ln)
        if m:
            bullets.append((m.group(1).lower(), m.group(2), m.group(3).strip().lower()))
    got = {(r, v) for r, _, v in bullets}
    if got != src_filled:
        problems.append({"chunk_only": sorted(got - src_filled)[:5], "source_only": sorted(src_filled - got)[:5]})
    for r, t, v in bullets:
        if htype.get(r) and htype[r] != t:
            problems.append(f"{r}: 청크 {t}, 원문 열 머리 {htype[r]}")
    # 금액 구간 이름: 청크 줄 범위 바로 앞 줄
    band = body.split(":", 1)[0].split(", ", 1)[-1]
    prev = lines[c.line_start - 2]
    m = AUTH_DIV.search(prev)
    sb = re.sub(r"<[^>]+>", "", html.unescape(m.group(1))).strip() if m else ""
    if sb.replace(" ", "") != band.replace(" ", ""):
        problems.append(f"금액 구간: 청크 {band!r}, 원문 {sb!r}")
    # 각주 (n) 글은 쪽에 있어야 한다
    for ln in body.split("\n"):
        mm = re.match(r"^\((\d+)\) (.+)$", ln)
        if mm and not page_has(pg, " ".join(C.words(mm.group(2))[:12])):
            problems.append(f"각주 ({mm.group(1)}) 앞부분이 쪽에 없음")
    return {"ok": not problems, "problems": problems}


# ------------------------------------------------------------------ 선택 규칙
HTML_TABLE = re.compile(r"<table|<t[dhr]\b", re.I)
MD_PIPE = re.compile(r"^\s*\|.*\|\s*$", re.M)
MD_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*\|", re.M)


def classify(c, text: str, lines: list[str], ir: dict) -> dict:
    window = "\n".join(lines[c.line_start - 1: c.line_end])
    has_ir_row = c.kind == "article" and any(ir[e]["kind"] == "table_row" for e in c.element_ids)
    has_markup = bool(HTML_TABLE.search(window) or MD_PIPE.search(window) or MD_SEP.search(window))
    is_table = c.kind == "row" or has_ir_row or has_markup
    vals = C.values(text)
    old_table = c.kind == "row" or bool(re.search(r"<table|<t[dhr]\b|^\s*\|.*\|\s*$|^\s*\|?\s*:?-{3,}", window, re.M | re.I))
    digit = bool(re.search(r"\d", text))
    return {"table": is_table, "table_ir": has_ir_row, "table_markup": has_markup, "table_old_rule": old_table, "has_values": bool(vals), "has_digit": digit}


# ------------------------------------------------------------------ 한 청크 전체 검사
def check_chunk(c, text: str, snap: Snap, ir: dict, hdr, rowcache: dict, selected_only=True) -> dict:
    m = snap.member(c)
    lines = snap.lines(m)
    pg = snap.page(m)
    if c.kind == "row" and c.config == "authz-row":
        # 행 청크에는 각주 본문이 같이 들어간다(chunk.py). 각주는 줄 범위 밖 다른 곳에 있으므로 쪽 전체에서 찾고, 행 부분만 줄 범위와 맞춘다
        h, _, b = text.partition("\n")
        bl = b.split("\n")
        k = next((i for i, l in enumerate(bl) if re.match(r"^\(\d+\) ", l)), len(bl))
        num = number_check(c, h + "\n" + "\n".join(bl[:k]), lines, pg, [lines[c.line_start - 2]], bl[:1])      # 금액 구간 줄은 칸 줄 바로 앞
        for v, ctx in C._ctx_with_bare("\n".join(bl[k:]), True):
            if v not in pg["vals"]:
                num["missing"].append(v)
            elif not page_has(pg, ctx):
                num["ctx_diff"].append({"value": v, "chunk_context": ctx})
        num["ok"] = not num["missing"] and not num["ctx_diff"] and not num["outside_range"]
    else:
        extra, row_texts = [], []
        if c.kind == "article":
            for e in c.element_ids:
                el = ir[e]
                if el["kind"] == "table_row":
                    row_texts.append(el["text"])
                if el["kind"] == "table_row" and el.get("source") != "html":
                    hi = md_header_idx(lines, el["line_start"])
                    if hi is not None and not (c.line_start - 1 <= hi < c.line_end):
                        extra.append(lines[hi])
        has_code = c.kind == "article" and any(ir[e]["kind"] == "code" for e in c.element_ids)
        num = number_check(c, text, lines, pg, extra, row_texts, has_code)
    res = {"numbers": num}
    body = text.partition("\n")[2]
    ov = c.overlap_chars or 0
    main_body = body[ov + 1:] if ov else body
    if c.kind == "row":
        res["authz"] = authz_row_check(c, text, lines, pg, hdr)
    else:
        res["rows"] = table_row_check(c, main_body, ir, snap, lines, rowcache)
    ov = c.overlap_chars or 0
    if ov:
        pb = PREV_BODY.get(c.chunk_id)
        res["overlap_ok"] = pb is not None and pb.rstrip().endswith(body[:ov])
    res["header_ok"] = text.partition("\n")[0] == (c.header or "")
    res["ok"] = res["header_ok"] and num["ok"] and (res.get("authz", {}).get("ok", True)) and res.get("rows", {}).get("ok", True) and res.get("overlap_ok", True)
    return res


# ------------------------------------------------------------------ 4. 겹침 조각
def overlap_scan(chunks, ir: dict) -> list[dict]:
    """겹침 글이 있는 청크마다: 앞 청크 꼬리가 맞는지, 어느 요소의 어디서 시작하는지, 표 행이면 무엇이 빠졌는지."""
    by = {(c.rule_seq, c.seq): c for c in chunks}
    out = []
    for c in chunks:
        ov = c.overlap_chars or 0
        if ov <= 0:
            continue
        prev = by.get((c.rule_seq, c.seq - 1))
        tail = c.text.partition("\n")[2][:ov]
        r = {"chunk_id": c.chunk_id, "prev_chunk_id": prev.chunk_id if prev else None, "overlap_chars": ov, "page": c.rule_title, "article": c.article,
             "recv_has_table_row": c.kind == "article" and any(ir[e]["kind"] == "table_row" for e in c.element_ids)}
        if prev is None or prev.kind != "article":
            r["tail_is_prev_suffix"] = False
            out.append(r)
            continue
        pbody = prev.text.partition("\n")[2]
        pbody = pbody[(prev.overlap_chars or 0) + 1:] if prev.overlap_chars else pbody
        r["tail_is_prev_suffix"] = pbody.rstrip().endswith(tail)
        if not r["tail_is_prev_suffix"]:
            out.append(r)
            continue
        start = len(pbody.rstrip()) - len(tail)
        # 앞 청크의 요소 글자를 이어 붙인 위치에서 start가 어느 요소 안인지
        els = [ir[e] for e in prev.element_ids]
        pos, hit, off = 0, None, 0
        if len(els) == 1:
            hit, off = els[0], start
        else:
            for e in els:
                if pos <= start < pos + len(e["text"]) + 1:
                    hit, off = e, start - pos
                    break
                pos += len(e["text"]) + 1
        if hit is None:
            r["starts_in"] = "unknown"
            out.append(r)
            continue
        r["starts_in"] = hit["kind"]
        r["offset_in_element"] = off
        r["mid_element"] = off > 0
        if hit["kind"] == "table_row" and off > 0:
            parts = []
            hdr_ = hit.get("header") or []
            pos2 = 0
            for h, v in zip(hdr_ + [""] * len(hit["cells"]), hit["cells"]):
                if not v:
                    continue
                s = f"{h}: {v}" if h else v
                parts.append((pos2, pos2 + len(s), h, v, s))
                pos2 += len(s) + 3
            lost_whole = [p for p in parts if p[1] <= off]
            cut = next((p for p in parts if p[0] < off < p[1]), None)
            lost_labels = [p[2] for p in lost_whole if p[2]]
            first = parts[0] if parts else None
            r["row_cells"] = len(parts)
            r["cells_lost_whole"] = len(lost_whole)
            r["lost_cell_values"] = [p[3][:60] for p in lost_whole]
            r["lost_cell_values_have_digit"] = any(re.search(r"\d", p[3]) for p in lost_whole)
            if cut:
                inside_label = bool(cut[2]) and off < cut[0] + len(cut[2]) + 2
                r["cut_inside"] = "label" if inside_label else "value"
                r["cut_cell_label"] = cut[2]
                r["cut_cell_value"] = cut[3][:60]
            else:
                r["cut_inside"] = None
            r["first_cell_value"] = first[3][:60] if first else None
            r["first_cell_value_missing"] = bool(first and first[1] <= off)
            r["first_cell_label_cut"] = bool(first and first[2] and first[0] < off < first[1] and off < first[0] + len(first[2]) + 2)
            r["row_text_in_prev"] = hit["text"][:200]
            r["tail_first_line"] = tail.split("\n")[0][:200]
            r["line_in_page"] = hit["line_start"]
            r["page_path"] = None
        out.append(r)
    return out


# ------------------------------------------------------------------ 4-2. 쪼갠 조각이 토큰(숫자) 한가운데서 잘린 곳
def split_cut_scan(chunks, ir: dict) -> list[dict]:
    """800자를 넘는 요소 하나가 여러 청크로 쪼개질 때(chunk.py split_long), 조각 경계가 공백이 아닌 글자 사이이면 낱말·숫자가 반쪽씩 나뉜다."""
    groups = collections.defaultdict(list)
    for c in chunks:
        if c.kind == "article" and len(c.element_ids) == 1:
            groups[(c.rule_seq, c.element_ids[0])].append(c)
    out = []
    for (rs, eid), cs in groups.items():
        if len(cs) < 2:
            continue
        cs.sort(key=lambda x: x.seq)
        el = ir[eid]["text"]
        bodies = []
        for c in cs:
            b = c.text.partition("\n")[2]
            bodies.append(b[c.overlap_chars + 1:] if c.overlap_chars else b)
        if "".join(bodies) != el:
            out.append({"element": eid, "problem": "조각을 이어 붙인 글이 요소 글자와 다름", "chunks": [c.chunk_id for c in cs]})
            continue
        pos = 0
        for i in range(len(cs) - 1):
            pos += len(bodies[i])
            a, b = el[pos - 1], el[pos]
            if a.isspace() or b.isspace():
                continue
            s, e = pos, pos
            while s > 0 and not el[s - 1].isspace():
                s -= 1
            while e < len(el) and not el[e].isspace():
                e += 1
            tok = el[s:e]
            out.append({"element": eid, "kind": ir[eid]["kind"], "left_chunk": cs[i].chunk_id, "right_chunk": cs[i + 1].chunk_id, "token": tok,
                        "left_part": el[s:pos], "right_part": el[pos:e], "has_digit": bool(re.search(r"\d", tok)),
                        "digit_split": bool(re.search(r"\d", a) and re.search(r"\d", b)), "page_title": cs[i].rule_title, "article": cs[i].article})
    return out


# ------------------------------------------------------------------ 4-3. 빈 줄로 끊긴 HTML 표
def broken_html_tables(snap: Snap, chunks) -> dict:
    """원문 `<table>…</table>` 안에 빈 줄이 있으면 markdown-it가 HTML 블록을 거기서 끊어, 뒤 행의 칸이 열 이름 없이 따로 요소가 된다."""
    found = []
    for m in snap.tar.getmembers():
        if not m.name.endswith(".md"):
            continue
        L = snap.lines(m.name)
        txt = "\n".join(L)
        for t in re.finditer(r"(?is)<table\b.*?</table>", txt):
            body = t.group(0)
            if re.search(r"\n[ \t]*\n", body):
                a = txt.count("\n", 0, t.start()) + 1
                b = txt.count("\n", 0, t.end()) + 1
                found.append({"page": m.name, "line_start": a, "line_end": b})
    by_page = collections.defaultdict(list)
    for f in found:
        by_page[f["page"]].append(f)
    hit = []
    for c in chunks:
        for f in by_page.get(snap.member(c), []):
            if c.line_start is not None and f["line_start"] <= c.line_end and c.line_start <= f["line_end"]:
                hit.append(c.chunk_id)
                break
    return {"tables": len(found), "pages": len(by_page), "chunks_overlapping": len(hit), "chunk_ids": hit, "items": found}


# ------------------------------------------------------------------ 5. 자기 시험
def swap_cells_in_row(text: str):
    """표 행 한 줄에서 서로 다른 두 칸의 값을 맞바꾼다. (원래 줄, 바뀐 줄)"""
    for ln in text.split("\n")[1:]:
        parts = ln.split(" | ")
        if len(parts) < 2:
            continue
        vals = [re.sub(r"^[^:]{1,60}: ", "", p, count=1) for p in parts]
        labs = [p[: len(p) - len(v)] for p, v in zip(parts, vals)]
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                if vals[i] != vals[j] and vals[i].strip() and vals[j].strip():
                    new = list(parts)
                    new[i], new[j] = labs[i] + vals[j], labs[j] + vals[i]
                    return ln, " | ".join(new)
    return None


def swap_value_between_rows(text: str):
    """표 행 두 줄에서 같은 위치 칸의 값을 맞바꾼다(행 섞임)."""
    ls = [l for l in text.split("\n")[1:] if " | " in l]
    for a in range(len(ls)):
        for b in range(a + 1, len(ls)):
            pa, pb = ls[a].split(" | "), ls[b].split(" | ")
            for k in range(min(len(pa), len(pb))):
                va, vb = re.sub(r"^[^:]{1,60}: ", "", pa[k], count=1), re.sub(r"^[^:]{1,60}: ", "", pb[k], count=1)
                if va != vb and va.strip() and vb.strip() and ls[a] != ls[b]:
                    na, nb = list(pa), list(pb)
                    na[k], nb[k] = pa[k][: len(pa[k]) - len(va)] + vb, pb[k][: len(pb[k]) - len(vb)] + va
                    return (ls[a], " | ".join(na)), (ls[b], " | ".join(nb))
    return None


def selftest(selected, snap, ir, hdr, rowcache, limit_per_kind: int) -> dict:
    rnd = random.Random(SEED)
    out = {}

    def run(kind, items, mutate):
        items = list(items)
        rnd.shuffle(items)
        n = det = 0
        miss = []
        for c in items:
            m = mutate(c)
            if m is None:
                continue
            new_text, desc = m
            if new_text == c.text or not check_chunk(c, c.text, snap, ir, hdr, rowcache)["ok"]:
                continue          # 원래 글이 통과하지 못하는 청크는 시험에서 뺀다(통과 여부가 바꾼 값 때문인지 가리기 위해)
            r = check_chunk(c, new_text, snap, ir, hdr, rowcache)
            n += 1
            if not r["ok"]:
                det += 1
            elif len(miss) < 10:
                miss.append({"chunk_id": c.chunk_id, "changed": desc})
            if n >= limit_per_kind:
                break
        out[kind] = {"tried": n, "detected": det, "not_detected_examples": miss}

    def m_number(c):
        for old, new in C._mutations(c.text):
            return c.text.replace(old, new, 1), f"{old} -> {new}"
        return None

    def m_other_page_number(c):
        pg = snap.page(snap.member(c))
        nums = sorted({n for n in re.findall(r"(?<![\w.$#-])\d{2,3}(?![\w%.])", pg["text"])})
        body_nums = re.findall(r"(?<![\w.$#-])\d{2,3}(?![\w%.])", c.text.partition("\n")[2][(c.overlap_chars or 0):])
        win = md_to_text2("\n".join(snap.lines(snap.member(c))[c.line_start - 1: c.line_end]))
        win_nums = set(re.findall(r"(?<![\w.$#-])\d{2,3}(?![\w%.])", win))
        cand = [n for n in nums if n not in win_nums]
        if not body_nums or not cand:
            return None
        old = body_nums[0]
        new = cand[0]
        t = c.text
        i = t.find(old, len(t.partition("\n")[0]) + 1 + (c.overlap_chars or 0))
        if i < 0:
            return None
        return t[:i] + new + t[i + len(old):], f"{old} -> {new} (쪽의 다른 곳에만 있는 숫자)"

    def m_swap_cells(c):
        r = swap_cells_in_row(c.text)
        if not r:
            return None
        return c.text.replace(r[0], r[1], 1), "칸 맞바꿈: " + r[0][:50] + " => " + r[1][:50]

    def m_swap_rows(c):
        r = swap_value_between_rows(c.text)
        if not r:
            return None
        (a0, a1), (b0, b1) = r
        return c.text.replace(a0, a1, 1).replace(b0, b1, 1), "행 섞음: " + a0[:40] + " <-> " + b0[:40]

    def m_drop_row(c):
        ls = c.text.split("\n")
        idx = [i for i, l in enumerate(ls) if i > 0 and " | " in l]
        if len(idx) < 3:
            return None
        k = idx[len(idx) // 2]
        removed = ls.pop(k)
        return "\n".join(ls), "행 삭제: " + removed[:60]

    nums = [c for c in selected if C.values(c.text) or re.search(r"\d", c.text)]
    tabs = [c for c in selected if c.kind == "article" and getattr(c, "_has_ir_row", False)]
    run("숫자 +7 (수치 청크 전체에서)", [c for c in selected if C.values(c.text)], m_number)
    run("쪽의 다른 곳에만 있는 숫자로 바꿈", nums, m_other_page_number)
    run("표 칸 맞바꿈(같은 행 두 칸)", tabs, m_swap_cells)
    run("표 행 섞음(두 행의 같은 열 값)", tabs, m_swap_rows)
    run("표 행 하나 삭제", tabs, m_drop_row)
    return out


# ------------------------------------------------------------------ 표본 읽기용 나란히 보기
def html_row_spans(L: list[str], ls: int, le: int) -> list[tuple[int, int, bool]]:
    """HTML 블록 안 <tr>…</tr>의 (시작 줄, 끝 줄, 머리 행 여부). 줄 번호는 1부터. 빈 행은 뺀다(파서와 같은 규칙)."""
    spans, start = [], None
    for i in range(ls - 1, le):
        if re.search(r"<tr\b", L[i]) and start is None:
            start = i
        if start is not None and re.search(r"</tr>", L[i]):
            seg = "\n".join(L[start: i + 1])
            p = _Tables()
            p.feed("<table>" + seg + "</table>")
            rows = [r for t in p.tables for r in t]
            if rows and any(rows[0]["cells"]):
                spans.append((start + 1, i + 1, rows[0]["th"]))
            start = None
    return spans


def side_by_side(c, snap: Snap, ir: dict | None = None) -> str:
    m = snap.member(c)
    L = snap.lines(m)
    if ir is not None and c.kind == "article":
        hs = [ir[e] for e in c.element_ids if ir[e]["kind"] == "table_row" and ir[e].get("source") == "html"]
        if hs:
            sp = html_row_spans(L, hs[0]["line_start"], hs[0]["line_end"])
            head = [s for s in sp if s[2]]
            body = [s for s in sp if not s[2]]
            idx = [x["element_id"] for x in ir.values() if x["rule_seq"] == c.rule_seq and x["kind"] == "table_row" and x.get("source") == "html"
                   and (x["line_start"], x["line_end"]) == (hs[0]["line_start"], hs[0]["line_end"])]
            out = [f"### {c.chunk_id}  (HTML 표 행)  {m}  블록 {hs[0]['line_start']}~{hs[0]['line_end']}  겹침 {c.overlap_chars}자",
                   "--- 청크 글 ---", c.text, "--- 원문 (줄 번호 | 글), 표 머리 행과 이 청크의 행만 ---"]
            use = head[:1] + [body[idx.index(h["element_id"])] for h in hs if idx.index(h["element_id"]) < len(body)]
            for a, b, _ in use:
                for i in range(a - 1, b):
                    out.append(f">{i + 1:5d} | {L[i][:260]}")
                out.append("        ...")
            return "\n".join(out)
    a = max(1, c.line_start - 2)
    out = [f"### {c.chunk_id}  ({'권한표 행' if c.kind == 'row' else '일반'})  {m}  {c.line_start}~{c.line_end}  겹침 {c.overlap_chars}자",
           "--- 청크 글 ---", c.text, "--- 원문 (줄 번호 | 글) ---"]
    for i in range(a - 1, min(len(L), c.line_end + 1)):
        mark = ">" if c.line_start <= i + 1 <= c.line_end else " "
        out.append(f"{mark}{i + 1:5d} | {L[i][:420]}")
    return "\n".join(out)


UA = "provena-source-check/1.0 (read-only GET)"


def fetch(url: str, cache: Path | None):
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    if cache and (cache / key).exists():
        return 200, (cache / key).read_bytes()
    body, status = b"", -1
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                body, status = r.read(), r.status
            break
        except Exception as e:  # noqa: BLE001
            body = str(e).encode()
            time.sleep(3)
    time.sleep(1.5)
    if cache and status == 200:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / key).write_bytes(body)
    return status, body


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--fetch-sample", action="store_true")
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--selftest-limit", type=int, default=400)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    load_base(find_root(a.root))
    out: Path = a.out
    out.mkdir(parents=True, exist_ok=True)

    chunks, pages, ir, authz_cells, authz_board = load_all(ROOT)
    byseq = {(c.rule_seq, c.seq): c for c in chunks}
    for c in chunks:
        if c.overlap_chars:
            p = byseq.get((c.rule_seq, c.seq - 1))
            if p is not None:
                pb = p.text.partition("\n")[2]
                PREV_BODY[c.chunk_id] = pb[p.overlap_chars + 1:] if p.overlap_chars else pb
    snap = Snap(ROOT, pages)
    lines_hdr = snap.lines("authz/authorization-matrix-2023-05.html.md")
    hdr = authz_header(lines_hdr)
    rowcache: dict = {}

    # --- 1. 대상 고르기
    sel, other_digit, no_digit = [], [], []
    cls = {}
    for c in chunks:
        k = classify(c, c.text, snap.lines(snap.member(c)), ir)
        cls[c.chunk_id] = k
        c._has_ir_row = k["table_ir"]
        if k["table"] or k["has_values"]:
            sel.append(c)
        elif k["has_digit"]:
            other_digit.append(c)
        else:
            no_digit.append(c)
    sel_ids = {c.chunk_id for c in sel}

    # --- 2. 전부 대조
    rows = []
    for c in sel:
        r = check_chunk(c, c.text, snap, ir, hdr, rowcache)
        k = cls[c.chunk_id]
        rows.append({"chunk_id": c.chunk_id, "kind": c.kind, "config": c.config, "page": snap.member(c), "title": c.rule_title, "article": c.article,
                     "line_start": c.line_start, "line_end": c.line_end, "overlap_chars": c.overlap_chars,
                     "reason": ("표+수치" if k["table"] and k["has_values"] else "표" if k["table"] else "수치"),
                     "table_ir": k["table_ir"], "table_markup": k["table_markup"], "table_old_rule": k["table_old_rule"],
                     "ok": r["ok"], "numbers_ok": r["numbers"]["ok"], "rows_ok": r.get("rows", r.get("authz", {})).get("ok", True),
                     "n_values": len(r["numbers"]["values"]), "detail": None if r["ok"] and not r["numbers"]["via_raw_markup"] else r})
    # 숫자만 든 비대상 청크: 숫자 토큰 확인
    od = []
    for c in other_digit:
        r = check_chunk(c, c.text, snap, ir, hdr, rowcache)
        od.append({"chunk_id": c.chunk_id, "ok": r["ok"], "detail": None if r["ok"] else r})

    bad = [r for r in rows if not r["ok"]]
    via_raw = [r for r in rows if r["ok"] and r["detail"]]
    with (out / "results.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "mismatches.json").write_text(json.dumps({"selected": len(rows), "mismatch": len(bad), "items": bad,
                                                      "other_digit_chunks": len(od), "other_digit_mismatch": sum(not x["ok"] for x in od),
                                                      "other_digit_items": [x for x in od if not x["ok"]]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    # --- 3. 겹침 조각
    ov = overlap_scan(chunks, ir)
    for r in ov:
        pass
    (out / "overlap_cut_rows.json").write_text(json.dumps([x for x in ov if x.get("starts_in") == "table_row" and x.get("mid_element")], ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    cuts = split_cut_scan(chunks, ir)
    (out / "split_cuts.json").write_text(json.dumps(cuts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    bh = broken_html_tables(snap, chunks)
    (out / "broken_html_tables.json").write_text(json.dumps(bh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    # --- 4. 자기 시험
    st = selftest([c for c in sel], snap, ir, hdr, rowcache, a.selftest_limit)
    (out / "selftest.json").write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    # --- 5. 표본
    rnd = random.Random(SEED)
    tab_pool = sorted(c.chunk_id for c in sel if cls[c.chunk_id]["table"])
    # 수치 문단: 표가 아닌 수치 청크
    num_pool = sorted(c.chunk_id for c in sel if not cls[c.chunk_id]["table"])
    tab_s = rnd.sample(tab_pool, 20)
    num_s = rnd.sample(num_pool, 10)
    by_id = {c.chunk_id: c for c in chunks}
    (out / "sample.json").write_text(json.dumps({"seed": SEED, "table": tab_s, "numeric_paragraph": num_s, "table_pool": len(tab_pool), "numeric_pool": len(num_pool)}, indent=1) + "\n", encoding="utf-8", newline="\n")
    with (out / "sample_side_by_side.txt").open("w", encoding="utf-8", newline="\n") as f:
        for kind, ids in (("표 청크", tab_s), ("수치 문단 청크", num_s)):
            f.write(f"\n\n######## {kind}\n\n")
            for cid in ids:
                f.write(side_by_side(by_id[cid], snap, ir) + "\n\n")
    cur = []
    if a.fetch_sample:
        now = datetime.now(KST).isoformat(timespec="seconds")
        pcache: dict = {}
        for cid in tab_s + num_s:
            c = by_id[cid]
            url = c.source_url
            if "/-/blob/" in url:
                url = re.sub(r"/-/blob/", "/-/raw/", url.split("#")[0])
            if url not in pcache:
                status, body = fetch(url, a.cache)
                if "/-/raw/" in url:
                    pcache[url] = (status, body.decode("utf-8", "replace").split("\n") if status == 200 else [])
                else:
                    pcache[url] = (status, C.html_to_text(body.decode("utf-8", "replace")) if status == 200 else "")
            status, content = pcache[url]
            if status != 200:
                cur.append({"chunk_id": cid, "url": url, "http_status": status, "match": None})
                continue
            if "/-/raw/" in url:
                cur_w = "\n".join(content[c.line_start - 1: c.line_end]).strip()
                snap_w = "\n".join(snap.lines(snap.member(c))[c.line_start - 1: c.line_end]).strip()
                cur.append({"chunk_id": cid, "url": url, "http_status": status, "mode": "고정 커밋 raw의 같은 줄 범위", "match": cur_w == snap_w, "checked_at": now})
            else:
                header, _, b = c.text.partition("\n")
                # 표 행은 값만 본다(현재 쪽 글자에는 행마다 붙인 열 이름이 없고, `Target % working`처럼 열 이름에 %·숫자가 든 행은 낱말 규칙이 열 이름을 못 뗀다)
                ovn = c.overlap_chars or 0
                ovl, b = b[:ovn], (b[ovn + 1:] if ovn else b)          # 겹침 글은 앞 청크 꼬리라 값만 본다
                b_rest, rv = b, [(v, "") for v in C.values(ovl) + C._bare(ovl)]
                for rt in sorted({ir[e]["text"] for e in c.element_ids if c.kind == "article" and ir[e]["kind"] == "table_row"}, key=len, reverse=True):
                    if rt and rt in b_rest:
                        b_rest = b_rest.replace(rt, "\n")
                        rv += [(v, "") for v in C.values(rt) + C._bare(rt)]
                allv = C._ctx_with_bare(b_rest, True) + rv + [(v, "") for v in C.values(header)]
                r = C.compare_all(allv, content)
                cur.append({"chunk_id": cid, "url": url, "http_status": status, "mode": "쪽 전체 글자", "match": not r["missing"] and not r["ctx_diff"],
                            "missing": r["missing"][:8], "ctx_diff": r["ctx_diff"][:4], "checked_at": now})
        (out / "sample_current_page.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    # --- 요약
    tm = [x for x in ov if x.get("starts_in") == "table_row" and x.get("mid_element")]
    ovs = {
        "overlap_chunks": len(ov), "tail_not_prev_suffix": sum(not x["tail_is_prev_suffix"] for x in ov),
        "mid_element_any": sum(bool(x.get("mid_element")) for x in ov),
        "mid_by_kind": dict(collections.Counter(x.get("starts_in") for x in ov if x.get("mid_element"))),
        "table_row_mid": len(tm), "table_row_complete": sum(1 for x in ov if x.get("starts_in") == "table_row" and not x.get("mid_element")),
        "table_row_mid_recv_table": sum(x["recv_has_table_row"] for x in tm),
        "first_cell_missing": sum(x["first_cell_value_missing"] for x in tm), "first_cell_label_cut_only": sum(x["first_cell_label_cut"] and not x["first_cell_value_missing"] for x in tm),
        "cells_lost_whole_ge1": sum(x["cells_lost_whole"] >= 1 for x in tm), "lost_cells_have_digit": sum(x["lost_cell_values_have_digit"] for x in tm),
        "cut_inside_value_only": sum(1 for x in tm if x["cells_lost_whole"] == 0 and x["cut_inside"] == "value"),
        "cut_inside_label_only": sum(1 for x in tm if x["cells_lost_whole"] == 0 and x["cut_inside"] == "label"),
    }
    (out / "overlap_summary.json").write_text(json.dumps(ovs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    # 전 청크 구조 점검: 본문이 파싱 요소 글자를 이은 것과 같은지(쪼갠 조각은 일부), 제목 줄이 header 칸과 같은지, 겹침이 앞 청크 꼬리인지
    join_bad = []
    for c in chunks:
        hdr_line, _, rest = c.text.partition("\n")
        ovn = c.overlap_chars or 0
        main = rest[ovn + 1:] if ovn else rest
        if hdr_line != (c.header or ""):
            join_bad.append({"chunk_id": c.chunk_id, "problem": "제목 줄이 header 칸과 다름"})
        if c.kind == "article":
            joined = "\n".join(ir[e]["text"] for e in c.element_ids)
            if main != joined and not (len(c.element_ids) == 1 and main in joined):
                join_bad.append({"chunk_id": c.chunk_id, "problem": "본문이 요소 글자와 다름"})
        if ovn and not PREV_BODY.get(c.chunk_id, "").rstrip().endswith(rest[:ovn]):
            join_bad.append({"chunk_id": c.chunk_id, "problem": "겹침 글이 앞 청크 본문 꼬리가 아님"})
    (out / "structure_check.json").write_text(json.dumps({"chunks": len(chunks), "problems": len(join_bad), "items": join_bad[:50]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    # 기타 수: 순서 있는 목록 번호가 사라지는 정도, 등급 규칙 오탐, 표 청크 중 겹침이 있는 수, HTML 표 청크 수
    ordered_el, ordered_chunks, ordered_nonfirst = 0, 0, 0
    for c in chunks:
        hit = False
        if c.kind != "article":
            continue
        L = snap.lines(snap.member(c))
        for e in c.element_ids:
            el = ir[e]
            if el["kind"] == "list_item" and el["line_start"] and re.match(r"^\s*(\d+)[.)]\s", L[el["line_start"] - 1]):
                ordered_el += 1
                hit = True
                if not re.match(r"^\s*1[.)]\s", L[el["line_start"] - 1]):
                    ordered_nonfirst += 1
        ordered_chunks += hit
    grade_only = sum(1 for c in sel if C.values(c.text) and all(re.fullmatch(r"[ps][0-4]", v) for v in C.values(c.text)) and not cls[c.chunk_id]["table"])
    table_with_overlap = sum(1 for c in sel if cls[c.chunk_id]["table"] and c.overlap_chars)
    html_table_chunks = sum(1 for c in chunks if c.kind == "article" and any(ir[e]["kind"] == "table_row" and ir[e].get("source") == "html" for e in c.element_ids))
    extra = {"ordered_list_elements": ordered_el, "ordered_list_elements_not_numbered_1": ordered_nonfirst, "chunks_with_ordered_list": ordered_chunks,
             "values_only_grade_s_p_chunks": grade_only, "table_chunks_with_overlap": table_with_overlap, "html_table_row_chunks": html_table_chunks}
    mk = collections.Counter()
    for c in sel:
        k = cls[c.chunk_id]
        if k["table_markup"] and not k["table_ir"] and c.kind != "row":
            kinds = {ir[e]["kind"] for e in c.element_ids}
            mk["code" if "code" in kinds else "html" if "html" in kinds else "list_item" if "list_item" in kinds else "|".join(sorted(kinds))] += 1
    cnt = collections.Counter(r["reason"] for r in rows)
    summary = {
        "markup_only_kinds": dict(mk), "overlap": ovs, "extra": extra, "structure_problems": len(join_bad),
        "total_chunks": len(chunks), "selected": len(rows), "by_reason": dict(cnt),
        "table_total": sum(cls[c.chunk_id]["table"] for c in sel), "table_ir": sum(cls[c.chunk_id]["table_ir"] for c in sel),
        "table_markup_only": sum(1 for c in sel if cls[c.chunk_id]["table_markup"] and not cls[c.chunk_id]["table_ir"] and c.kind != "row"),
        "table_authz_row": sum(1 for c in sel if c.kind == "row"), "table_old_rule": sum(cls[c.chunk_id]["table_old_rule"] for c in chunks),
        "values_only": cnt.get("수치", 0), "has_values": sum(cls[c.chunk_id]["has_values"] for c in chunks),
        "other_digit": len(od), "no_digit": len(no_digit),
        "mismatch": len(bad), "numbers_mismatch": sum(not r["numbers_ok"] for r in rows), "rows_mismatch": sum(not r["rows_ok"] for r in rows),
        "via_raw_markup": len(via_raw), "other_digit_mismatch": sum(not x["ok"] for x in od),
        "snapshot_sha256": snap.sha, "table_rows_checked": sum(1 for c in sel if c.kind == "article" for e in c.element_ids if ir[e]["kind"] == "table_row"),
        "overlap_chunks": len(ov),
        "split_cuts_total": len([x for x in cuts if "token" in x]), "split_cuts_digit_token": len([x for x in cuts if x.get("has_digit")]),
        "split_cuts_digit_split": len([x for x in cuts if x.get("digit_split")]),
        "broken_html_tables": bh["tables"], "broken_html_chunks": bh["chunks_overlapping"], "sample_current_checked": len(cur), "sample_current_match": sum(1 for x in cur if x.get("match")),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps({k: {x: y for x, y in v.items() if x != "not_detected_examples"} for k, v in st.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
