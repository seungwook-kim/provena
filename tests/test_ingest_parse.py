"""파싱 (docs/specs/parse.md AC). 원문 없이 작은 예시로 돈다."""
import collections

from backend.rag.ingest import parse as P


# AC-01 · 줄 번호 보존
def test_preprocess_keeps_line_count_and_classifies_shortcodes():
    raw = ('---\ntitle: X\n---\n{{% alert color="info" %}}\nkeep me\n{{% /alert %}}\n'
           'Owner: {{< member-by-name "Kirsty Allen" >}}\n{{< team-by-manager-slug "a" >}}\n'
           '{{% details summary="Open me" %}}\n{{</* performance-indicators "x" */>}}\n')
    counts, unknown = collections.Counter(), set()
    out = P.preprocess(raw, counts, unknown)
    assert out.count("\n") == raw.count("\n")
    assert "keep me" in out and "Kirsty Allen" in out and "Open me" in out
    assert "team-by-manager-slug" not in out and "{{% alert" not in out
    assert '{{< performance-indicators "x" >}}' in out          # 이스케이프는 글자로
    assert counts["data"] == 1 and not unknown
