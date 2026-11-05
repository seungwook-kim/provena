"""증분 수집 ① 바뀐 쪽·바뀐 섹션 찾기 (docs/specs/incremental.md AC-01·AC-02, 설계 V1~V4).

합성 원문·임시 git 저장소 시험은 어디서나 돈다. 실제 핸드북 이력 시험은 캐시(PROVENA_HANDBOOK_CACHE,
기본 ~/.cache/provena/handbook)가 있을 때만 돌고, 없으면 건너뛴 이유를 출력한다.
"""
import os
import subprocess
from pathlib import Path

import pytest

from backend.rag.ingest import diff as D
from backend.rag.ingest.handbook import all_folders, rule_seq
from backend.rag.ingest.history import RECALL_COMMITS

PAGE = {"rule_seq": rule_seq("content/handbook/security/x.md"), "org": "security", "path": "content/handbook/security/x.md"}

OLD = """---
title: Disclosure
---

[TOC]

## Policy

We disclose issues 30 days after the fix. See [the runbook](https://example.com/old).

## Contacts

Ask in #security.
"""


def changes(old, new):
    return [(c.article, c.change_type, c.format_only, c.old_article) for c in D.section_changes(PAGE, old, new)]


# V1 · 본문 낱말이 바뀌면 modified (서식만으로 빠지지 않음)
def test_word_change_is_modified():
    new = OLD.replace("30 days", "90 days")
    assert changes(OLD, new) == [("Policy", "modified", False, None)]


def test_same_text_is_no_change():
    assert changes(OLD, OLD) == []


# V2 · 링크 주소·공백·[TOC] 만 바뀌면 format_only
@pytest.mark.parametrize("edit", [
    lambda s: s.replace("https://example.com/old", "https://example.com/new"),       # 링크 주소
    lambda s: s.replace("after the fix.", "after the   fix.  "),                     # 공백
    lambda s: s.replace("## Policy\n\n", "## Policy\n\n[TOC]\n\n"),                  # [TOC]
    lambda s: s.replace("We disclose issues 30 days", "We disclose issues 30\ndays"),  # 줄바꿈 위치
])
def test_format_only_edits(edit):
    assert changes(OLD, edit(OLD)) == [("Policy", "modified", True, None)]


def test_toc_before_first_heading_is_no_change():
    assert changes(OLD, OLD.replace("[TOC]\n\n", "")) == []      # 첫 제목 앞은 [TOC] 뿐 → 인용될 섹션이 없음


def test_link_text_change_is_content():
    new = OLD.replace("[the runbook]", "[the old runbook]")      # 화면 글자가 바뀌면 본문 변경
    assert changes(OLD, new) == [("Policy", "modified", False, None)]


# V3 · 제목만 바뀐 섹션은 modified 하나 (removed + added 아님)
def test_renamed_heading_is_one_modified():
    new = OLD.replace("## Policy", "## Disclosure policy")
    assert changes(OLD, new) == [("Disclosure policy", "modified", False, "Policy")]


def test_renamed_and_rewritten_heading_is_removed_and_added():
    new = OLD.replace("## Policy\n\nWe disclose issues 30 days after the fix. See [the runbook](https://example.com/old).",
                      "## Bounty\n\nRewards are paid in USD through HackerOne once triaged.")
    assert sorted(changes(OLD, new)) == [("Bounty", "added", False, None), ("Policy", "removed", False, None)]


REVIEW = "Every quarter the team reviews open design documents and assigns an owner to each one before the planning call"


@pytest.mark.parametrize("new_body, paired", [
    # 0.556: 실측에서 같은 섹션이던 "제목+본문 함께 고침" 쪽(0.35~0.6). 문턱을 0.6으로 올리면 놓친다
    ("Every quarter the team reviews open design documents during planning and records decisions in the issue tracker", True),
    # 0.256: 실측에서 다른 섹션이던 쪽. 문턱을 0.25로 내리면 잘못 짝짓는다
    ("The team keeps design notes in the wiki and links them from the epic so reviewers can find them later", False),
])
def test_rename_threshold_boundary(new_body, paired):
    assert round(D.similarity(REVIEW, new_body), 3) == (0.556 if paired else 0.256)
    got = changes(f"## Design Documents\n\n{REVIEW}\n", f"## Design documents\n\n{new_body}\n")
    if paired:
        assert got == [("Design documents", "modified", False, "Design Documents")]
    else:
        assert sorted(got) == [("Design Documents", "removed", False, None), ("Design documents", "added", False, None)]


def test_parent_rename_moves_child_and_skips_empty_parent():
    old = "## A\n\n### Child\n\nbody text here\n"
    new = "## B\n\n### Child\n\nbody text here\n"
    assert changes(old, new) == [("B > Child", "modified", False, "A > Child")]   # 본문 없는 A·B는 청크가 없어 넘기지 않음


# 쪽 추가·사라짐 → 섹션 전부 added·removed
def test_page_added_and_removed():
    assert {t for _, t, _, _ in changes(None, OLD)} == {"added"}
    assert {t for _, t, _, _ in changes(OLD, None)} == {"removed"}
    assert [a for a, _, _, _ in changes(None, OLD)] == ["Policy", "Contacts"]     # 첫 제목 앞은 [TOC] 뿐이라 본문 없음


# EC-10 · 처음 보는 단축코드는 review 표시
def test_unknown_shortcode_marks_review():
    new = OLD.replace("Ask in #security.", "Ask in #security. {{< brand-new-shortcode >}}")
    got = D.section_changes(PAGE, OLD, new)
    assert [(c.article, c.review) for c in got] == [("Contacts", True)]


# 리콜에 넘길 목록: 서식만은 빼고, 제목만 바뀐 섹션은 옛 경로로
def test_changed_articles_skip_format_only_and_use_old_article():
    secs = [D.SectionChange("Policy", "modified", format_only=True),
            D.SectionChange("Disclosure policy", "modified", old_article="Policy"),
            D.SectionChange("Bounty", "added")]
    got = D.changed_articles(7, secs, "2026-10-27", "2026-10-30")
    assert [(a.article, a.change_type) for a in got] == [("Policy", "modified"), ("Bounty", "added")]
    assert got[0].rule_seq == 7 and got[0].old_version_date == "2026-10-27" and got[0].new_version_date == "2026-10-30"


# ── 임시 git 저장소: 쪽 목록 비교 (V4) ──
def git(repo, *args, stdin=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=True).stdout


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "hb"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")
    for f in all_folders():
        p = repo / f / "a.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"## A\n\nkeep {f}\n", encoding="utf-8")
    return repo


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").decode().strip()


def test_list_changes_added_modified_removed_moved(tmp_path):
    repo = make_repo(tmp_path)
    sec = repo / "content/handbook/security"
    (sec / "gone.md").write_text("## G\n\nold page\n", encoding="utf-8")
    (sec / "move-me.md").write_text("## M\n\nsame bytes\n", encoding="utf-8")
    old = commit(repo, "old")
    (sec / "gone.md").unlink()
    (sec / "move-me.md").rename(sec / "moved.md")
    (sec / "a.md").write_text("## A\n\nchanged\n", encoding="utf-8")
    (sec / "new.md").write_text("## N\n\nnew page\n", encoding="utf-8")
    new = commit(repo, "new")

    ch = D.list_changes(repo, old, new)
    assert ch.list_complete and ch.reasons == []
    assert [p for p, _ in ch.added] == ["content/handbook/security/moved.md", "content/handbook/security/new.md"]
    assert [p for p, _, _ in ch.modified] == ["content/handbook/security/a.md"]
    assert [p for p, _ in ch.removed] == ["content/handbook/security/gone.md", "content/handbook/security/move-me.md"]
    assert [(o, n) for o, n, _ in ch.moved] == [("content/handbook/security/move-me.md", "content/handbook/security/moved.md")]
    assert ch.unchanged == 16
    assert sum(ch.pages_by_folder.values()) == 19 and len(ch.pages_by_folder) == 17


# V4 · 17개 폴더 중 하나가 비면 삭제 보류(list_complete=False), 본 사라짐은 그대로 기록
def test_empty_folder_makes_list_incomplete(tmp_path):
    repo = make_repo(tmp_path)
    old = commit(repo, "old")
    git(repo, "rm", "-q", "-r", "content/handbook/finance")
    new = commit(repo, "finance moved away")
    ch = D.list_changes(repo, old, new)
    assert ch.list_complete is False
    assert ch.reasons == ["empty_folder:content/handbook/finance"]
    assert [p for p, _ in ch.removed] == ["content/handbook/finance/a.md"]


def test_fetch_failure_and_missing_commit_make_list_incomplete(tmp_path):
    repo = make_repo(tmp_path)
    c = commit(repo, "one")
    assert D.list_changes(repo, c, c, fetch_ok=False).reasons == ["fetch_failed"]
    ch = D.list_changes(repo, c, "0" * 40)
    assert ch.list_complete is False and ch.reasons == ["commit_missing:new"] and ch.added == []


def test_diff_commits_one_bad_page_does_not_stop_others(tmp_path):
    repo = make_repo(tmp_path)
    old = commit(repo, "old")
    (repo / "content/handbook/security/a.md").write_text("## A\n\nkeep but changed words\n", encoding="utf-8")
    (repo / "content/handbook/support/a.md").write_bytes(b"## A\n\n\xff\xfe not utf-8\n")
    new = commit(repo, "new")
    rep = D.diff_commits(repo, old, new)
    kinds = {p["path"].split("/")[2]: p["kind"] for p in rep["pages"]}
    assert kinds == {"security": "content", "support": "error"}
    assert [(a["article"], a["change_type"]) for a in rep["articles"]] == [("A", "modified")]


# 묶어 받기: blob:none 복제에서 없는 파일 여러 개를 fetch 한 번으로
def test_fetch_blobs_fetches_missing_in_one_request(tmp_path, monkeypatch):
    src = make_repo(tmp_path)
    git(src, "config", "uploadpack.allowFilter", "true")
    git(src, "config", "uploadpack.allowAnySHA1InWant", "true")
    commit(src, "one")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{src.as_posix()}", str(clone)],
                   check=True, capture_output=True)
    blobs = [b for _, b in D.list_pages(clone, "HEAD")]
    calls = []
    real = D.run_git
    monkeypatch.setattr(D, "run_git", lambda repo, *a, **k: calls.append(a[0] if a[0] != "-c" else a[2]) or real(repo, *a, **k))
    monkeypatch.setattr("backend.rag.ingest.handbook.git", _git_no_lazy)
    got = D.fetch_blobs(clone, blobs)
    assert calls.count("fetch") == 1
    assert len(got) == 17 and all(v.startswith(b"## A") for v in got.values())


def _git_no_lazy(repo, *args, stdin=None):
    """read_blobs 가 없는 파일을 하나씩 내려받으면 실패하게(묶어 받기를 건너뛴 변이를 잡는다)."""
    done = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True,
                          env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    if done.returncode != 0:
        raise D.CollectError(done.stderr.decode("utf-8", "replace"))
    return done.stdout


# ── 실제 핸드북 이력 (캐시가 있을 때만) ──
CACHE = Path(os.environ.get("PROVENA_HANDBOOK_CACHE", Path.home() / ".cache/provena/handbook"))
PINNED, LATEST, LINK_CLEANUP = "129243bc", "52419353ea", "2666725a9b"


def need_cache(*commits):
    if not (CACHE / ".git").exists():
        pytest.skip(f"핸드북 캐시 없음({CACHE}): 실제 이력 시험 건너뜀")
    missing = [c for c in commits if not D.commit_exists(CACHE, c)]
    if missing:
        pytest.skip(f"캐시에 커밋 없음 {missing}: git -C {CACHE} fetch origin")


# V1 · AC-01: 리콜 시험 커밋 12건 모두 그 쪽에서 본문 변경이 나오고 서식만으로 빠지지 않는다
RECALL_EXPECTED = {   # 커밋 → {쪽 파일 이름: 리콜에 넘길 섹션 종류}. fc6633cf 는 섹션 하나를 통째로 지운 커밋(원문 23줄 삭제)
    "0c787db1": {"third-party-risk-management.md": {"modified"}},
    "e29aad9a": {"_index.md": {"modified"}},
    "1ca85649": {"corp-credit-cards.md": {"modified"}},
    "6baed99c": {"incident-review.md": {"modified"}},
    "219f7084": {"index.md": {"modified"}},
    "bf53a691": {"incident-manager-onboarding.md": {"added"}, "_index.md": {"modified"}},
    "642fb341": {"third-party-risk-management.md": {"modified"}},
    "37eecbf4": {"_index.md": {"modified"}},
    "fc6633cf": {"tier-2.md": {"removed"}},
    "4667e540": {"engaging-with-security.md": {"modified"}, "hackerone-process.md": {"modified"}},
    "ddd39597": {"expenses.md": {"modified"}},
    "5d615813": {"_index.md": {"modified"}},
}


@pytest.mark.parametrize("commit", RECALL_COMMITS)
def test_recall_commits_are_found(commit):
    need_cache(commit)
    rep = D.diff_commits(CACHE, commit + "^", commit)
    got = {}
    for p in rep["pages"]:
        assert p["kind"] == "content", p["path"]
        got[p["path"].rsplit("/", 1)[1]] = {s["change_type"] for s in p["sections"] if not s["format_only"]}
    assert got == RECALL_EXPECTED[commit[:8]]
    assert rep["articles"]


def test_recall_disclosure_commit_sections():
    need_cache("4667e540")
    rep = D.diff_commits(CACHE, "4667e540^", "4667e540")
    arts = sorted(a["article"] for a in rep["articles"])
    assert "Vulnerability Reports and HackerOne > Process for disclosing security issues" in arts
    assert len(arts) == 7 and all(a["change_type"] == "modified" for a in rep["articles"])


# V2 · AC-02: 링크 정리 커밋은 대부분 서식만, 리콜에 넘길 섹션은 글자가 지워진 3쪽 6섹션뿐
def test_link_cleanup_commit_is_mostly_format_only():
    need_cache(LINK_CLEANUP)
    s = D.diff_commits(CACHE, LINK_CLEANUP + "^", LINK_CLEANUP)["summary"]
    assert (s["modified"], s["added"], s["removed"]) == (110, 0, 0)
    assert s["by_kind"] == {"format_only": 107, "content": 3}
    assert s["sections"] == {"format_only": 154, "modified": 6} and s["articles"] == 6


# V9 미리보기 · 고정 커밋(10/27) → 52419353ea(10/30): 설계 M2·M3 숫자와 대조
def test_pinned_to_latest_matches_design_counts():
    need_cache(PINNED, LATEST)
    s = D.diff_commits(CACHE, PINNED, LATEST)["summary"]
    assert (s["added"], s["modified"], s["removed"], s["moved"], s["unchanged"]) == (1, 138, 0, 0, 1426)
    assert s["list_complete"] is True and s["reasons"] == []
    assert s["by_kind"] == {"content": 23, "format_only": 116}
