"""핸드북 git 캐시(~/.cache/provena/handbook)에서 커밋 직전 판과 커밋 판의 섹션 본문을 읽는다(리콜 정답의 연결기). LLM·DB 없음.

- 섹션 비교와 섹션 본문은 운영의 두 시점 비교(`backend.rag.ingest.snapshot_diff.diff_snapshots`, F-07·`/impact-preview`와 같은 함수)로 만든다.
- 판 날짜는 수집과 같은 규칙(커밋 시각 %ct의 UTC 날짜, `handbook.utc_day`). 개정 전 판 날짜 = 커밋 직전 판에서 그 파일을 마지막으로 고친 커밋의 날짜,
  개정 뒤 판 날짜 = 그 커밋의 날짜, 기준일(as_of) = 개정 뒤 판 날짜의 전날(요청 문서 5장 "기준일은 개정 전날").
- 요청 문서의 섹션 이름이 시스템 제목 경로와 글자가 조금 다르면(대소문자·공백·기호) 같은 섹션으로 맞춘다. 맞는 것이 하나가 아니면 오류다.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from evals.newmetrics.common import HANDBOOK_CACHE, section_key


class HistoryError(RuntimeError):
    pass


@dataclass
class SectionChange:
    commit_full: str
    path: str                  # content/handbook/ 다음(커밋 당시 경로)
    rule_seq: int
    article: str               # 시스템 제목 경로(리콜 키)
    change_type: str           # modified | removed | added
    old_version_date: str
    new_version_date: str
    as_of: str
    old_text: str
    new_text: str
    old_raw: str | None
    new_raw: str | None
    source_url: str
    date_adjusted: bool = False


def handbook_url(rel: str) -> str:
    p = rel.removesuffix(".md")
    for tail in ("/_index", "/index"):
        if p.endswith(tail):
            p = p[: -len(tail)]
    return f"https://handbook.gitlab.com/handbook/{p}/"


class HandbookHistory:
    def __init__(self, cache: Path | None = None):
        self.cache = Path(cache or HANDBOOK_CACHE)

    def _git(self, *args: str) -> bytes:
        done = subprocess.run(["git", "-C", str(self.cache), *args], capture_output=True)
        if done.returncode != 0:
            raise HistoryError(f"git {' '.join(args[:2])} 실패: {done.stderr.decode('utf-8', 'replace').strip()[:200]}")
        return done.stdout

    def available(self) -> bool:
        return (self.cache / ".git").exists()

    def full(self, commit: str) -> str:
        return self._git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()

    def file_at(self, commit: str, rel: str) -> str | None:
        done = subprocess.run(["git", "-C", str(self.cache), "show", f"{commit}:content/handbook/{rel}"], capture_output=True)
        if done.returncode != 0:
            return None
        return done.stdout.decode("utf-8").replace("\r\n", "\n")

    def day(self, commit: str) -> str:
        from backend.rag.ingest.handbook import utc_day

        return utc_day(self._git("log", "-1", "--format=%ct", commit).decode().strip())

    def last_change_day(self, commit: str, rel: str) -> str | None:
        from backend.rag.ingest.handbook import utc_day

        out = self._git("log", "-1", "--no-renames", "--format=%ct", commit, "--", f"content/handbook/{rel}").decode().strip()
        return utc_day(out) if out else None

    def section_change(self, commit: str, rel: str, section: str) -> SectionChange:
        from backend.rag.ingest.handbook import rule_seq
        from backend.rag.ingest.snapshot_diff import diff_snapshots

        full = self.full(commit)
        old_raw, new_raw = self.file_at(full + "^", rel), self.file_at(full, rel)
        if old_raw is None:
            raise HistoryError(f"커밋 직전 판에 파일이 없다: {rel}")
        new_date = self.day(full)
        old_date = self.last_change_day(full + "^", rel) or ""
        key = "content/handbook/" + rel
        res = diff_snapshots({key: old_raw}, {key: new_raw} if new_raw is not None else {}, old_date=old_date, new_date=new_date)
        if res.errors:
            raise HistoryError(f"파싱 오류: {res.errors}")
        arts = res.articles
        pick = [a for a in arts if a.article == section]
        if not pick:
            pick = [a for a in arts if section_key(a.article) == section_key(section)]
        if not pick:
            tail = section_key(section.split(" > ")[-1])
            pick = [a for a in arts if section_key(a.article.split(" > ")[-1]) == tail]
        if len(pick) != 1:
            raise HistoryError(f"바뀐 섹션을 하나로 못 찾음: {section!r} (커밋에서 바뀐 섹션: {[a.article for a in arts]})")
        a = pick[0]
        old_text, new_text = res.texts.get((a.rule_seq, a.article), ("", ""))
        new_v = a.new_version_date or new_date
        as_of = (date.fromisoformat(new_v) - timedelta(days=1)).isoformat()
        old_v = a.old_version_date or old_date
        adjusted = False
        if not old_v or old_v >= new_v:
            # 같은 날 앞 커밋이 그 파일을 고친 경우(ddd39597): 판 날짜가 같으면 판 구간 [old, new)가 비어 개정 전 판을 읽을 수 없다.
            # 수집도 하루 단위라 이 둘을 다른 판으로 보지 못한다. 측정에서는 개정 전 판 날짜를 기준일(전날)로 둔다(summary에 표시).
            old_v, adjusted = as_of, True
        return SectionChange(full, rel, rule_seq(key), a.article, a.change_type, old_v, new_v,
                             as_of, old_text, new_text, old_raw, new_raw, handbook_url(rel), adjusted)
