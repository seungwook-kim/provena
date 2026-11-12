"""lf_context.py 시험: 가짜 Langfuse 관측만 쓴다(네트워크·키·유료 호출 없음). 정답 위치 맞춤은 저장소의 `evals.retrieval.gold`를 그대로 쓴다."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from evals.agent import failure_types as ft
from evals.latency import lf_context as C
from evals.retrieval.gold import page_seq, parse_gold

T0 = datetime(2026, 11, 11, 0, 12, 50, tzinfo=timezone.utc)


def A(n: int) -> str:
    return f"{n:016x}"


def ch(page: str, title: str, cid: str) -> dict:
    return {"chunk_id": cid, "org": "x", "rule_seq": page_seq(page), "article": f"{page} title > {title}", "line_start": 1, "line_end": 5, "text": "본문 전문"}


def obs(trace: str, thread: str, start: datetime, chunks: list[dict], *, retries: int = 0, oid: str | None = None) -> dict:
    out = {"chunks": chunks, "sub_queries": [], "search_cache": {}}
    return {"id": oid or f"o-{trace}-{start.timestamp()}", "traceId": trace, "name": "search", "type": "CHAIN", "sessionId": f"u1:{thread}",
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "input": json.dumps({"question": "q", "retries": retries}), "output": json.dumps(out, ensure_ascii=False)}


def item(i: int, gold: list[str], kind: str = "relevant") -> dict:
    return {"id": i, "input": f"q{i}", "kind": kind, "gold_chunks": gold, "gold": parse_gold(gold) if kind == "relevant" else []}


def row(run: int, i: int, thread: str | None) -> dict:
    return {"run": run, "id": i, "status": "ok", "thread_id": thread, "at": T0.astimezone(timezone(timedelta(hours=9))).isoformat(timespec="seconds"), "total_s": 5.0}


def filler(n: int, base: int = 100) -> list[dict]:
    return [ch("z/z.md", f"Z{base + i}", A(base + i)) for i in range(n)]


GOLD2 = ["a/p.md > Alpha", "b/q.md > Beta"]


def test_first_scope_counts_the_whole_first_search_not_just_the_top_five():
    """분해 질문(k=8)에서 정답이 6~8번째거나 맨 뒤 도입부면 서비스는 그 문맥을 봤다. top5로 자르면 검색 실패로 잘못 센다."""
    items = [item(1, GOLD2)]
    chunks = filler(5) + [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2)), ch("z/z.md", "Intro", A(3))]
    ctx, detail = C.build_context("v2", {1: [row(1, 1, "th1")]}, items, [obs("t1", "th1", T0, chunks)])
    assert ctx == {"v2:1:1": [2, 2]} and detail[0]["n_chunks"] == 8 and detail[0]["status"] == "paired"


def test_first_scope_ignores_the_retry_but_final_scope_uses_the_merged_last_search():
    items = [item(1, GOLD2)]
    first = obs("t1", "th1", T0, filler(3) + [ch("a/p.md", "Alpha", A(1))])
    retry = obs("t1", "th1", T0 + timedelta(seconds=6), filler(3) + [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2))], retries=1)
    runs = {1: [row(1, 1, "th1")]}
    f_ctx, f_det = C.build_context("v2", runs, items, [retry, first], scope="first")
    l_ctx, l_det = C.build_context("v2", runs, items, [retry, first], scope="final")
    assert f_ctx["v2:1:1"] == [1, 2] and l_ctx["v2:1:1"] == [2, 2]
    assert f_det[0]["differs"] and f_det[0]["other_scope_hit"] == 2 and l_det[0]["other_scope_hit"] == 1 and f_det[0]["n_search_obs"] == 2


def test_final_scope_skips_a_last_search_without_chunks():
    items = [item(1, GOLD2)]
    ok = obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2))])
    empty = obs("t1", "th1", T0 + timedelta(seconds=5), [], retries=1)
    ctx, _ = C.build_context("v2", {1: [row(1, 1, "th1")]}, items, [ok, empty], scope="final")
    assert ctx["v2:1:1"] == [2, 2]


def test_keys_are_per_run_and_follow_the_thread_id():
    items = [item(1, GOLD2)]
    o1 = obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2))])
    o2 = obs("t2", "th2", T0 + timedelta(seconds=60), [ch("a/p.md", "Alpha", A(1))])
    runs = {1: [row(1, 1, "th1")], 2: [row(2, 1, "th2")]}
    ctx, _ = C.build_context("holdout", runs, items, [o2, o1])
    assert ctx == {"holdout:1:1": [2, 2], "holdout:1:2": [1, 2]}


def test_irrelevant_excluded_and_goldless_items_are_skipped_and_gold_pipe_counts_once():
    items = [item(1, ["a/p.md > Alpha | b/q.md > Alpha"]), item(2, [], kind="irrelevant"), item(3, ["a/p.md > Alpha"]), item(4, [])]
    items[3]["kind"] = "relevant"
    observations = [obs("t1", "th1", T0, [ch("b/q.md", "Alpha", A(1))])]
    runs = {1: [row(1, 1, "th1"), row(1, 2, "th1"), row(1, 3, "th1"), row(1, 4, "th1")]}
    ctx, _ = C.build_context("v2", runs, items, observations, exclusions={"3": "제외"})
    assert ctx == {"v2:1:1": [1, 1]}


def test_unpaired_rows_get_no_key_and_no_search_gets_zero():
    items = [item(1, GOLD2), item(2, GOLD2), item(3, GOLD2), item(4, GOLD2)]
    observations = [obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1))])]
    runs = {1: [row(1, 1, "th1"), row(1, 2, "th-lost"), row(1, 3, "th-nosearch"), row(1, 4, None)]}
    ctx, detail = C.build_context("v2", runs, items, observations, known_sessions={"th1", "th-nosearch"})
    assert ctx == {"v2:1:1": [1, 2], "v2:3:1": [0, 2]}
    assert {d["id"]: d["status"] for d in detail} == {1: "paired", 2: "no_trace", 3: "no_search", 4: "no_thread_id"}


def test_regex_fallback_chunks_are_filled_from_the_corpus():
    items = [item(1, ["a/p.md > Alpha"])]
    o = obs("t1", "th1", T0, [])
    o["output"] = '{"chunks": [{"chunk_id": "%s", "text": "잘림' % A(1)
    ctx, detail = C.build_context("v2", {1: [row(1, 1, "th1")]}, items, [o], corpus_by_id={A(1): ch("a/p.md", "Alpha", A(1))})
    assert ctx == {"v2:1:1": [1, 1]} and detail[0]["parse"] == "regex"


# ---------------------------------------------------------------- 실행 진입점 + 실패 유형 연결

def write_set(tmp: Path, name: str, runs: dict[int, list[dict]], items: list[dict]) -> tuple[Path, Path]:
    for n, rows in runs.items():
        d = tmp / name / f"run{n}"
        d.mkdir(parents=True)
        (d / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ds = tmp / f"{name}.jsonl"
    ds.write_text("\n".join(json.dumps({k: v for k, v in it.items() if k != "gold"}, ensure_ascii=False) for it in items) + "\n", encoding="utf-8")
    return tmp / name, ds


def test_cli_writes_context_for_two_sets_and_failure_types_reads_it(tmp_path, capsys):
    items = [item(1, GOLD2), item(2, GOLD2)]
    v2_dir, v2_ds = write_set(tmp_path, "v2", {r: [row(r, 1, f"a{r}"), row(r, 2, f"b{r}")] for r in (1, 2, 3)}, items)
    ho_dir, ho_ds = write_set(tmp_path, "ho", {1: [row(1, 1, "h1")]}, [item(1, GOLD2)])
    both = [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2))]
    observations = []
    for r in (1, 2, 3):
        observations.append(obs(f"ta{r}", f"a{r}", T0 + timedelta(seconds=r), [both[0]]))      # 문항 1: 문맥에 정답 한 곳만 -> 검색 실패
        observations.append(obs(f"tb{r}", f"b{r}", T0 + timedelta(seconds=r), both))            # 문항 2: 문맥에 정답 전부 -> 근거 선택
    observations.append(obs("th", "h1", T0 + timedelta(seconds=9), both))
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps(observations), encoding="utf-8")
    out = tmp_path / "ft" / "context.json"
    rc = C.main(["--set", "v2", str(v2_dir), str(v2_ds), "--set", "holdout", str(ho_dir), str(ho_ds), "--out", str(out),
                 "--observations-json", str(obs_path), "--chunks", str(tmp_path / "none.jsonl")])
    assert rc == 0
    ctx = json.loads(out.read_text(encoding="utf-8"))
    assert ctx["v2:1:2"] == [1, 2] and ctx["v2:2:3"] == [2, 2] and ctx["holdout:1:1"] == [2, 2] and len(ctx) == 7
    text = out.read_text(encoding="utf-8") + out.with_suffix(".detail.json").read_text(encoding="utf-8")
    assert "본문 전문" not in text and "u1:" not in text                              # 청크 본문과 사용자 id는 저장하지 않는다

    # failure_types 연결: 정답 한 곳을 인용한 3회 -> 검색 실패, 문맥에 다 있는데 한 곳만 인용 -> 근거 선택
    def qrow(i, r):
        return {"run": r, "id": i, "kind": "relevant", "expect_refusal": False, "status": "ok", "result": "answer", "answered": True,
                "gold_total": 2, "gold_hit": 1, "cited_on_gold": 1, "cited_off_gold": 0, "refuse_stage": None, "refuse_reason": None}
    (v2_dir / "citation_gold.json").write_text(json.dumps({"rows": [qrow(i, r) for i in (1, 2) for r in (1, 2, 3)]}), encoding="utf-8")
    assert ft.main(["--qa", f"v2={v2_dir}", "--context", str(out), "--out", str(tmp_path / "res")]) == 0
    md = (tmp_path / "res" / "failure_types.md").read_text(encoding="utf-8")
    assert "| 검색 실패 | 1 | v2 1 |" in md and "| 근거 선택 | 1 | v2 2 |" in md


def test_cli_stops_with_4_when_a_row_cannot_be_paired_unless_allowed(tmp_path, capsys):
    d, ds = write_set(tmp_path, "v2", {1: [row(1, 1, "th1"), row(1, 2, "th-lost")]}, [item(1, GOLD2), item(2, GOLD2)])
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps([obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1))])]), encoding="utf-8")
    known = tmp_path / "known.json"
    known.write_text(json.dumps(["th1"]), encoding="utf-8")
    args = ["--set", "v2", str(d), str(ds), "--out", str(tmp_path / "c.json"), "--observations-json", str(obs_path), "--known-sessions-json", str(known),
            "--chunks", str(tmp_path / "none.jsonl")]
    assert C.main(args) == 4 and "no_trace" in capsys.readouterr().err
    assert C.main(args + ["--allow-missing"]) == 0
    assert json.loads((tmp_path / "c.json").read_text(encoding="utf-8")) == {"v2:1:1": [1, 2]}


def test_cli_stops_with_3_when_rows_have_no_thread_id(tmp_path, capsys):
    d, ds = write_set(tmp_path, "v2", {1: [row(1, 1, None)]}, [item(1, GOLD2)])
    assert C.main(["--set", "v2", str(d), str(ds), "--out", str(tmp_path / "c.json"), "--observations-json", str(tmp_path / "x.json")]) == 3
    assert "thread_id가 없다" in capsys.readouterr().err


def test_only_get_requests_are_ever_built():
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert "urllib" not in src and "POST" not in src and "method=" not in src      # 네트워크는 lf_recall.Langfuse(GET 전용)를 통해서만
