"""개정 이력 후보 목록: 고른 절의 2024-01-01 이후 커밋 + 2023 권한표 파일의 커밋.

python -m backend.rag.ingest.history          (handbook.py를 먼저 돌려 캐시가 있어야 한다)

"답을 바꾸는 규칙 변경"인지 고르는 것은 사람 몫이다. 여기서는 후보만 만든다(Spec: docs/specs/collect.md).
팀이 고른 리콜 시험 커밋 12건(참고 URL 2장)이 목록에 모두 있는지 확인하고, 하나라도 없으면 멈춘다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from backend.rag.ingest.handbook import (AUTHZ_PATH, AUTHZ_PROJECT, PINNED_COMMIT, SHALLOW_SINCE, USER_AGENT,
                                         VERSION_DATE_FORMAT, CollectError, all_folders, commit_day, git, utc_day)

RS, US = "\x1e", "\x1f"   # 커밋 구분자, 칸 구분자 (커밋 제목에 나오지 않는 문자)
AUTHZ_SINCE, AUTHZ_UNTIL = "2021-01-01", "2023-05-12"   # 2021-10~11 개정(SDD 4-1) ~ 고정 커밋
MAX_API_PAGES = 20   # 페이지당 100건, 요청 상한
# 처음엔 "최근 12개월"(주제서 초안)이었으나 팀 리콜 시험 12건 중 가장 오래된 것이 2024-01-23 → 2024-01-01부터 (10/29)
HISTORY_SINCE = "2024-01-01"
RECALL_COMMITS = (   # 답을 바꾸는 규칙 변경 12건, 팀장 작성 참고 URL 2장
    "0c787db1", "e29aad9a", "1ca85649", "6baed99c", "219f7084", "bf53a691",
    "642fb341", "37eecbf4", "fc6633cf", "4667e540", "ddd39597", "5d615813",
)


def parse_log(text: str) -> list[dict]:
    """git log --format=RS%H US<날짜> US%s --name-status 출력 → 커밋 목록. 날짜 칸은 받은 그대로 둔다."""
    commits = []
    for block in filter(None, text.split(RS)):
        head, *lines = block.strip("\n").split("\n")
        sha, day, title = head.split(US, 2)
        files = []
        for line in filter(None, lines):
            status, path = line.split("\t", 1)
            if status[:1] in ("R", "C"):   # 이름 바뀜(-M): "R100<\t>옛 경로<\t>새 경로" (F-11)
                old, path = path.split("\t", 1)
                files.append({"status": status, "path": path, "old_path": old})
            else:
                files.append({"status": status, "path": path})
        commits.append({"sha": sha, "date": day, "title": title, "files": files})
    return commits


def handbook_history(repo: Path, since: str, follow_renames: bool = False) -> list[dict]:
    """기본은 --no-renames: 이름 바뀜 탐지는 파일 내용을 비교해야 해서 blob:none 캐시에서 내용을 하나씩 내려받는다.
    follow_renames=True(-M)면 옮긴 파일이 `R` 상태와 `old_path` 로 나온다(F-11). 고른 폴더 밖에서 옮겨 온 파일은
    경로 제한 때문에 그대로 추가(A)로 보인다. 기본이 꺼짐이라 handbook_commits.jsonl 은 바뀌지 않는다."""
    out = git(repo, "log", "--no-merges", "-M" if follow_renames else "--no-renames", f"--since={since}",
              f"--format={RS}%H{US}{VERSION_DATE_FORMAT}{US}%s", "--name-status", PINNED_COMMIT, "--", *all_folders())
    commits = parse_log(out.decode("utf-8"))
    for c in commits:
        c["date"] = utc_day(c["date"])   # 판 날짜와 같은 기준(UTC, I-011)
        c["files"] = [f for f in c["files"] if f["path"].endswith(".md")]
    return [c for c in commits if c["files"]]


def missing_recall(commits: list[dict]) -> list[str]:
    """팀 리콜 시험 커밋 중 이력에 없는 것."""
    return [s for s in RECALL_COMMITS if not any(c["sha"].startswith(s) for c in commits)]


def authz_history() -> list[dict]:
    project = urllib.parse.quote(AUTHZ_PROJECT, safe="")
    commits, page = [], 1
    while page:
        if page > MAX_API_PAGES:
            raise CollectError(f"권한표 이력이 {MAX_API_PAGES}쪽을 넘음 (조건 확인)")
        url = (f"https://gitlab.com/api/v4/projects/{project}/repository/commits?"
               + urllib.parse.urlencode({"path": AUTHZ_PATH, "since": AUTHZ_SINCE, "until": AUTHZ_UNTIL,
                                         "per_page": 100, "page": page}))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                raise CollectError(f"권한표 이력 응답 {r.status}")
            data = json.load(r)
            nxt = r.headers.get("X-Next-Page")
        if not isinstance(data, list):
            raise CollectError(f"권한표 이력 응답 형식이 다름: {str(data)[:200]}")
        commits += [{"sha": c["id"], "date": c["committed_date"][:10], "title": c["title"]} for c in data]
        page = int(nxt) if nxt else 0
        time.sleep(1)   # 요청 간격 1초 이상 (AGENTS.md)
    if not commits:
        raise CollectError("권한표 이력 0건 (경로·기간 확인)")
    return commits


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("data/corpus/history"))
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache/provena/handbook")
    ap.add_argument("--skip-authz", action="store_true")
    ap.add_argument("--follow-renames", action="store_true",
                    help="이름 바뀜을 따라간다(R, old_path). 캐시에서 파일 내용을 내려받아 느리다. 기본 꺼짐(F-11)")
    args = ap.parse_args()

    pinned = commit_day(args.cache, PINNED_COMMIT)
    hb = handbook_history(args.cache, HISTORY_SINCE, args.follow_renames)
    missing = missing_recall(hb)
    if missing:   # 캐시가 예전(1년)에 받은 것이면 이력이 모자란다
        raise CollectError(f"리콜 시험 커밋이 이력에 없음: {missing}. "
                           f"캐시 이력 더 받기: git -C {args.cache} fetch --shallow-since={SHALLOW_SINCE} origin")
    write_jsonl(args.out / "handbook_commits.jsonl", hb)
    print(f"핸드북: {HISTORY_SINCE}~{pinned} 커밋 {len(hb)}건 (merge 제외, .md 바뀐 것만), "
          f"리콜 시험 {len(RECALL_COMMITS)}건 모두 있음")
    if not args.skip_authz:
        az = authz_history()
        write_jsonl(args.out / "authz_commits.jsonl", az)
        print(f"권한표: {AUTHZ_SINCE}~{AUTHZ_UNTIL} 커밋 {len(az)}건")


if __name__ == "__main__":
    main()
