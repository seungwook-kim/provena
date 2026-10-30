"""핸드북 수집 (docs/specs/collect.md AC). 네트워크 없이 돈다."""
import subprocess

import pytest

from backend.rag.ingest import handbook as hb
from backend.rag.ingest.history import RECALL_COMMITS, RS, US, missing_recall, parse_log

PAGE = b"---\ntitle: Incident Management\n---\n\nbody\n"


def fake_pages(n_per_org=1, **override):
    pages = {f"content/handbook/{folders[0]}/p{i}.md": PAGE
             for folders in hb.SECTIONS.values() for i in range(n_per_org)}
    pages.update(override)
    return pages


# AC-05 · URL 규칙
@pytest.mark.parametrize("path, url", [
    ("content/handbook/security/_index.md", "https://handbook.gitlab.com/handbook/security/"),
    ("content/handbook/security/readmes/nick-malcolm.md",
     "https://handbook.gitlab.com/handbook/security/readmes/nick-malcolm/"),
    ("content/handbook/finance/accounting/finance-ops/billing-ops-GPO/_index.md",
     "https://handbook.gitlab.com/handbook/finance/accounting/finance-ops/billing-ops-gpo/"),
])
def test_page_url(path, url):
    assert hb.page_url(path) == url


def test_rule_seq_stable_and_distinct():
    a = "content/handbook/security/_index.md"
    assert hb.rule_seq(a) == 1510429323                  # 실행·PC가 달라도 같은 값(리터럴과 비교, GATES.md)
    assert hb.rule_seq(a) != hb.rule_seq("content/handbook/support/_index.md")
    assert 0 < hb.rule_seq(a) < 16**8   # 최대 10자리(앞 8자), Postgres bigint에 들어감


def test_corpus_id_order_independent():
    assert hb.corpus_id(["a", "b", "c"]) == hb.corpus_id(["c", "a", "b"])
    assert hb.corpus_id(["a", "b"]) != hb.corpus_id(["a", "c"])


def test_front_matter_mixed_case_and_redirect():
    assert hb.front_matter("---\nTitle: Self Managed\n---\n") == {"title": "Self Managed"}
    fm = hb.front_matter('---\ntitle: "Operate Workflow"\nredirect_to: /handbook/x/\n---\n')
    assert fm == {"title": "Operate Workflow", "redirect_to": "/handbook/x/"}


def test_org_of_rejects_unselected_path():
    assert hb.org_of("content/handbook/engineering/devops/a.md") == "devops"
    with pytest.raises(hb.CollectError):
        hb.org_of("content/handbook/engineering/incident-management.md")   # 낱장은 고르지 않았다


# AC-02 · 쪽수 불일치면 멈춤
def test_check_pages_count_mismatch_raises():
    pages = fake_pages()
    with pytest.raises(hb.CollectError, match="절별"):
        hb.check_pages(pages, expected=len(pages) + 1)
    assert hb.check_pages(pages, expected=len(pages))["security"] == 1


def test_check_pages_empty_file_raises():
    pages = fake_pages(**{"content/handbook/security/empty.md": b"  \n"})
    with pytest.raises(hb.CollectError, match="빈 파일"):
        hb.check_pages(pages, expected=len(pages))


def test_check_pages_empty_section_raises():
    pages = {p: b for p, b in fake_pages(2).items() if "/finance/" not in p}
    with pytest.raises(hb.CollectError, match="0쪽"):
        hb.check_pages(pages, expected=len(pages))


# AC-04 · 권한표 응답 검증
AUTHZ = b'---\nlayout: markdown_page\ntitle: "Authorization Matrix"\n---\n<div>table</div>\n'


@pytest.mark.parametrize("status, headers, body", [
    (404, {}, b""),
    (200, {"X-Gitlab-Content-Sha256": hb.sha256(b"")}, b""),
    (200, {"X-Gitlab-Content-Sha256": "0" * 64}, AUTHZ),
    (200, {"X-Gitlab-Content-Sha256": hb.sha256(b"---\ntitle: Sign in\n---\n")}, b"---\ntitle: Sign in\n---\n"),
])
def test_check_authz_rejects(status, headers, body):
    with pytest.raises(hb.CollectError):
        hb.check_authz(status, headers, body)


def test_check_authz_accepts():
    hb.check_authz(200, {"x-gitlab-content-sha256": hb.sha256(AUTHZ)}, AUTHZ)


def test_skip_authz_keeps_previous_record_only_if_file_matches(tmp_path):
    manifest, authz_file = tmp_path / "collect_manifest.json", tmp_path / "authz.md"
    authz_file.write_bytes(AUTHZ)
    manifest.write_text('{"authz": {"file_sha256": "%s"}}' % hb.sha256(AUTHZ), encoding="utf-8")
    assert hb.kept_authz(manifest, authz_file) == {"file_sha256": hb.sha256(AUTHZ)}
    authz_file.write_bytes(AUTHZ + b"changed")
    assert hb.kept_authz(manifest, authz_file) is None


# AC-03 · 원본 그대로: 작업 폴더(CRLF 변환)가 아니라 git 원본에서 읽는다
def test_read_blobs_returns_git_original(tmp_path):
    def run(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True).stdout
    run("init", "-q")
    run("config", "core.autocrlf", "true")
    (tmp_path / "a.md").write_bytes(b"line1\nline2\n")
    (tmp_path / "b.md").write_bytes(PAGE)
    run("add", ".")
    blobs = run("ls-files", "-s").decode().split("\n")
    ids = [line.split()[1] for line in blobs if line]
    got = hb.read_blobs(tmp_path, ids)
    assert got[ids[0]] == b"line1\nline2\n"
    assert all(hb.git_blob_id(data) == blob for blob, data in got.items())


def test_parse_log():
    text = (f"{RS}abc{US}2026-06-29{US}Update disclosure: 30 -> 90 days\n\n"
            f"M\tcontent/handbook/security/a.md\nA\tcontent/handbook/security/b.md\n"
            f"{RS}def{US}2026-06-01{US}typo\n\nD\tcontent/handbook/support/c.md\n")
    commits = parse_log(text)
    assert [c["sha"] for c in commits] == ["abc", "def"]
    assert commits[0]["files"][1] == {"status": "A", "path": "content/handbook/security/b.md"}
    assert commits[1]["title"] == "typo"


def test_missing_recall_commits_detected():
    full = [{"sha": s + "0" * 32} for s in RECALL_COMMITS]
    assert missing_recall(full) == []
    assert missing_recall(full[1:]) == ["0c787db1"]              # 1년만 받았을 때 빠졌던 2024-01 커밋
    assert len(RECALL_COMMITS) == 12
    assert {"0c787db1", "e29aad9a", "1ca85649", "6baed99c"} <= set(RECALL_COMMITS)   # 처음에 빠졌던 4건
