"""lf_recall.py 시험: 가짜 Langfuse 관측만 쓴다(네트워크·키·유료 호출 없음). 공식 채점기(evals/retrieval)는 저장소 것을 그대로 쓴다."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.latency import lf_recall as L
from evals.retrieval.gold import page_seq

T0 = datetime(2026, 11, 11, 0, 12, 50, tzinfo=timezone.utc)


# ---------------------------------------------------------------- 가짜 자료 만들기

def ch(page: str, title: str, cid: str, **kw) -> dict:
    """관측 output의 청크 dict. 페이지 `page`(handbook 상대 경로)의 섹션 `title`."""
    return {"chunk_id": cid, "org": "x", "rule_seq": page_seq(page), "article": f"{page} title > {title}", "line_start": kw.get("a", 1), "line_end": kw.get("b", 5), "text": "본문"}


def obs(trace: str, thread: str, start: datetime, chunks: list[dict], question: str, *, oid: str | None = None, retries: int = 0, user: str = "u1", extra: dict | None = None) -> dict:
    out = {"chunks": chunks, "sub_queries": [], "search_cache": {"k": [{"chunk_id": "f" * 16}]}, **(extra or {})}
    return {"id": oid or f"o-{trace}-{start.timestamp()}", "traceId": trace, "name": "search", "type": "CHAIN", "sessionId": f"{user}:{thread}",
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "input": json.dumps({"question": question, "retries": retries}, ensure_ascii=False),
            "output": json.dumps(out, ensure_ascii=False)}


def item(i: int, q: str, gold: list[str], kind: str = "relevant") -> dict:
    return {"id": i, "input": q, "kind": kind, "gold_chunks": gold, "as_of": "2026-10-27"}


def row(run: int, i: int, thread: str | None, at: datetime = T0, total_s: float = 5.0, cited=None) -> dict:
    return {"run": run, "id": i, "status": "ok", "thread_id": thread, "at": at.astimezone(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
            "total_s": total_s, "cited_chunk_ids": cited or []}


def load_items(items: list[dict]) -> list[dict]:
    from evals.retrieval.gold import parse_gold
    for it in items:
        it["gold"] = parse_gold(it["gold_chunks"]) if it["kind"] == "relevant" else []
    return items


def A(n: int) -> str:
    return f"{n:016x}"


# ---------------------------------------------------------------- 파서

def test_parser_reads_json_string_output_in_rank_order():
    chunks = [ch("a/p.md", "S1", A(1)), ch("a/p.md", "S2", A(2)), ch("b/q.md", "S3", A(3))]
    p = L.parse_search_output(json.dumps({"chunks": chunks, "sub_queries": ["x", "y"], "search_cache": {}}))
    assert p["mode"] == "json" and [c["chunk_id"] for c in p["chunks"]] == [A(1), A(2), A(3)] and p["sub_queries"] == ["x", "y"]


def test_parser_accepts_dict_and_double_encoded_output():
    d = {"chunks": [{"chunk_id": A(7)}]}
    assert L.parse_search_output(d)["chunks"][0]["chunk_id"] == A(7)
    assert L.parse_search_output(json.dumps(json.dumps(d)))["chunks"][0]["chunk_id"] == A(7)


def test_parser_falls_back_to_regex_but_never_reads_the_search_cache_copy():
    broken = '{"chunks": [{"chunk_id": "%s", "text": "잘림' % A(1) + '}, {"chunk_id": "%s"}, {"chunk_id": "%s"}], "search_cache": {"q": [{"chunk_id": "%s"}]' % (A(2), A(1), A(9))
    p = L.parse_search_output(broken)
    assert p["mode"] == "regex" and [c["chunk_id"] for c in p["chunks"]] == [A(1), A(2)]   # 중복은 첫 자리만, 캐시 사본(A(9))은 안 읽는다


@pytest.mark.parametrize("bad", [None, "", "not json at all", "{}", '{"chunks": []}', '{"kind": "refuse"}'])
def test_parser_returns_empty_for_outputs_without_chunks(bad):
    p = L.parse_search_output(bad)
    assert p["chunks"] == [] and p["mode"] == "none"


def test_top5_is_the_first_five_of_the_context_order_so_intro_chunks_appended_last_are_out():
    chunks = [ch("a/p.md", f"S{i}", A(i)) for i in range(1, 9)]       # 나뉜 질문: SPLIT_K=8
    top = L.top_k_chunks(L.parse_search_output({"chunks": chunks}), 5)
    assert [c["chunk_id"] for c in top] == [A(i) for i in range(1, 6)]
    assert len(L.top_k_chunks(L.parse_search_output({"chunks": chunks[:3]}), 5)) == 3


# ---------------------------------------------------------------- 첫 검색 고르기

def test_first_search_is_the_earliest_start_in_the_trace_not_the_first_listed():
    later = obs("t1", "th1", T0 + timedelta(seconds=9), [ch("a/p.md", "S", A(2))], "q", retries=1)
    first = obs("t1", "th1", T0 + timedelta(seconds=2), [ch("a/p.md", "S", A(1))], "q")
    other = obs("t2", "th2", T0, [ch("a/p.md", "S", A(3))], "q2")
    tr = L.first_search_per_trace([later, first, other])    # API는 최신이 앞이다
    assert tr["t1"]["n_search"] == 2 and tr["t1"]["obs"]["id"] == first["id"] and tr["t1"]["retries"] == 0
    assert tr["t1"]["all_chunk_ids"] == {A(1), A(2)} and tr["t1"]["thread_id"] == "th1"
    assert set(tr) == {"t1", "t2"}


def test_non_search_observations_are_ignored():
    o = obs("t1", "th1", T0, [ch("a/p.md", "S", A(1))], "q")
    o["name"] = "rewrite"
    assert L.first_search_per_trace([o]) == {}


# ---------------------------------------------------------------- 짝짓기: 대화 id로만

def test_pairing_follows_thread_id_even_when_time_order_would_pair_the_neighbour():
    """예전 사고: 시간이 가까운 trace로 짝지어 틀렸다. 대화 id가 다르면 시각이 같아도 짝이 아니다."""
    qa = obs("tA", "thA", T0, [ch("a/p.md", "S", A(1))], "qa")
    qb = obs("tB", "thB", T0 + timedelta(milliseconds=1), [ch("a/p.md", "S", A(2))], "qb")
    tr = L.first_search_per_trace([qa, qb])
    rows = [row(1, 1, "thB"), row(1, 2, "thA")]             # 행 순서와 trace 시각 순서가 엇갈린다
    got = L.pair_by_thread(rows, tr)
    assert [p["trace"]["obs"]["traceId"] for p in got] == ["tB", "tA"]


def test_pairing_requires_the_exact_thread_id_not_a_prefix_or_substring():
    tr = L.first_search_per_trace([obs("t1", "t-abc123", T0, [ch("a/p.md", "S", A(1))], "q")])
    got = L.pair_by_thread([row(1, 1, "t-abc12"), row(1, 2, "abc123"), row(1, 3, "t-abc123")], tr)
    assert [p["status"] for p in got] == ["no_trace", "no_trace", "paired"]


def test_pairing_statuses_for_missing_thread_id_missing_trace_and_no_search():
    tr = L.first_search_per_trace([obs("t1", "th1", T0, [ch("a/p.md", "S", A(1))], "q")])
    rows = [row(1, 1, None), row(1, 2, "th-lost"), row(1, 3, "th-nosearch"), row(1, 4, "th1")]
    got = L.pair_by_thread(rows, tr, known_sessions={"th1", "th-nosearch"})
    assert [p["status"] for p in got] == ["no_thread_id", "no_trace", "no_search", "paired"]
    got2 = L.pair_by_thread(rows, tr)                         # trace 목록이 없으면 no_search를 가르지 못한다
    assert [p["status"] for p in got2] == ["no_thread_id", "no_trace", "no_trace", "paired"]


def test_two_traces_for_one_thread_use_the_earliest_and_report_the_count():
    tr = L.first_search_per_trace([obs("t2", "th1", T0 + timedelta(seconds=30), [ch("a/p.md", "S", A(2))], "q"),
                                   obs("t1", "th1", T0, [ch("a/p.md", "S", A(1))], "q")])
    p = L.pair_by_thread([row(1, 1, "th1")], tr)[0]
    assert p["trace"]["obs"]["traceId"] == "t1" and p["n_traces"] == 2


def test_cited_chunks_must_all_appear_in_the_paired_trace():
    tr = L.first_search_per_trace([obs("t1", "th1", T0, [ch("a/p.md", "S", A(1)), ch("a/p.md", "S", A(2))], "q")])["t1"]
    assert L.cited_consistency({"cited_chunk_ids": [A(1)]}, tr) is True
    assert L.cited_consistency({"cited_chunk_ids": [A(1), A(5)]}, tr) is False
    assert L.cited_consistency({"cited_chunk_ids": []}, tr) is None


def test_legacy_pairing_needs_same_question_text_and_one_candidate_in_the_request_window():
    q1, q2 = "질문 하나", "질문 둘"
    end = T0 + timedelta(seconds=10)
    o1 = obs("t1", "th1", T0 + timedelta(seconds=6), [ch("a/p.md", "S", A(1))], q1)
    o_other_text = obs("t2", "th2", T0 + timedelta(seconds=6), [ch("a/p.md", "S", A(2))], q2)
    o_outside = obs("t3", "th3", T0 - timedelta(seconds=60), [ch("a/p.md", "S", A(3))], q1)
    tr = L.first_search_per_trace([o1, o_other_text, o_outside])
    items = {1: item(1, q1, []), 2: item(2, "없는 질문", [])}
    got = L.pair_legacy([row(1, 1, None, at=end, total_s=10.0), row(1, 2, None, at=end, total_s=10.0)], items, tr)
    assert [p["status"] for p in got] == ["paired", "no_trace"] and got[0]["trace"]["obs"]["traceId"] == "t1"
    two = L.first_search_per_trace([o1, obs("t9", "th9", T0 + timedelta(seconds=7), [ch("a/p.md", "S", A(9))], q1)])
    assert L.pair_legacy([row(1, 1, None, at=end, total_s=10.0)], items, two)[0]["status"] == "ambiguous"


# ---------------------------------------------------------------- 계산: 공식 정의 그대로

def make_world():
    """문항 3개(관련 2, 비관련 1). 문항 1은 정답 2곳, 문항 2는 정답 1곳."""
    items = load_items([item(1, "q1", ["a/p.md > Alpha", "b/q.md > Beta"]),
                        item(2, "q2", ["c/r.md > Gamma"]),
                        item(3, "q3", [], kind="irrelevant")])
    return items


def test_recall_at_5_uses_the_official_definition_gold_found_over_gold_then_plain_mean():
    items = make_world()
    # 1회차: 문항1은 정답 2곳 중 1곳만 상위 5에 있다(0.5), 문항2는 6번째에만 있다(0). 평균 0.25
    top1 = [ch("a/p.md", "Alpha", A(1))] + [ch("z/z.md", f"Z{i}", A(10 + i)) for i in range(4)]
    top2 = [ch("z/z.md", f"Z{i}", A(20 + i)) for i in range(5)] + [ch("c/r.md", "Gamma", A(30))]
    obs_ = [obs("t1", "th1", T0, top1, "q1"), obs("t2", "th2", T0 + timedelta(seconds=10), top2, "q2")]
    rep = L.build_report({1: [row(1, 1, "th1"), row(1, 2, "th2"), row(1, 3, "th3")]}, items, obs_, known_sessions={"th1", "th2", "th3"}, allow_missing=True)
    s = rep["summary"]["per_run"][1]
    assert s["recall"] == pytest.approx(0.25) and s["n_scored"] == 2
    d = {x["id"]: x for x in rep["detail"]}
    assert d[1]["recall"] == pytest.approx(0.5) and d[2]["recall"] == 0 and d[2]["top5"] == [A(20 + i) for i in range(5)]   # 6번째(A30)는 상위 5가 아니다
    assert 3 not in d                                           # 비관련 문항은 Recall 계산에서 빠진다


def test_overall_is_the_pooled_mean_of_question_run_pairs_and_matches_per_run_means():
    items = make_world()
    good = [ch("a/p.md", "Alpha", A(1)), ch("b/q.md", "Beta", A(2))]
    miss = [ch("z/z.md", "Z", A(3))]
    gamma = [ch("c/r.md", "Gamma", A(4))]
    observations = [obs("t1", "th1", T0, good, "q1"), obs("t2", "th2", T0 + timedelta(seconds=9), gamma, "q2"),
                    obs("t3", "th3", T0 + timedelta(seconds=60), miss, "q1"), obs("t4", "th4", T0 + timedelta(seconds=70), gamma, "q2"),
                    obs("t5", "th5", T0 + timedelta(seconds=120), good, "q1"), obs("t6", "th6", T0 + timedelta(seconds=130), miss, "q2")]
    runs = {1: [row(1, 1, "th1"), row(1, 2, "th2")], 2: [row(2, 1, "th3"), row(2, 2, "th4")], 3: [row(3, 1, "th5"), row(3, 2, "th6")]}
    rep = L.build_report(runs, items, observations)
    pr = rep["summary"]["per_run"]
    assert (pr[1]["recall"], pr[2]["recall"], pr[3]["recall"]) == (pytest.approx(1.0), pytest.approx(0.5), pytest.approx(0.5))
    assert rep["summary"]["all_runs"]["recall"] == pytest.approx((1.0 + 0.5 + 0.5) / 3) and rep["summary"]["all_runs"]["n_scored"] == 6
    assert rep["coverage"]["fraction"] == 1.0


def test_gold_alternatives_with_pipe_count_once_and_match_either_page():
    items = load_items([item(1, "q1", ["a/p.md > Alpha | b/q.md > Alpha"])])
    rep = L.build_report({1: [row(1, 1, "th1")]}, items, [obs("t1", "th1", T0, [ch("b/q.md", "Alpha", A(1))], "q1")])
    assert rep["summary"]["per_run"][1]["recall"] == 1.0


def test_section_match_is_the_official_one_subsection_counts_other_page_does_not():
    items = load_items([item(1, "q1", ["a/p.md > Alpha"])])
    sub = [{**ch("a/p.md", "Alpha > Child", A(1))}]
    wrong_page = [ch("b/q.md", "Alpha", A(2))]
    rep = L.build_report({1: [row(1, 1, "th1")], 2: [row(2, 1, "th2")]}, items,
                         [obs("t1", "th1", T0, sub, "q1"), obs("t2", "th2", T0 + timedelta(seconds=60), wrong_page, "q1")])
    assert rep["summary"]["per_run"][1]["recall"] == 1.0 and rep["summary"]["per_run"][2]["recall"] == 0.0


def test_exclusions_and_gold_missing_from_corpus_are_dropped_from_the_denominator_like_the_official_run():
    items = load_items([item(1, "q1", ["a/p.md > Alpha"]), item(2, "q2", ["c/r.md > Gone"]), item(3, "q3", ["a/p.md > Alpha"])])
    corpus = [SimpleNamespace(**ch("a/p.md", "Alpha", A(1)))]          # 문항 2의 정답 위치는 코퍼스에 없다
    obs_ = [obs(f"t{i}", f"th{i}", T0 + timedelta(seconds=i), [ch("a/p.md", "Alpha", A(1))], f"q{i}") for i in (1, 2, 3)]
    rows = [row(1, i, f"th{i}") for i in (1, 2, 3)]
    rep = L.build_report({1: rows}, items, obs_, exclusions={"3": "시험용 제외"}, corpus=corpus)
    s = rep["summary"]["per_run"][1]
    assert s["n_scored"] == 1 and sorted(s["excluded"]) == [2, 3] and s["recall"] == 1.0


def test_no_search_in_a_known_trace_counts_as_empty_top5_but_a_lost_trace_stops_the_run():
    items = load_items([item(1, "q1", ["a/p.md > Alpha"]), item(2, "q2", ["a/p.md > Alpha"])])
    obs_ = [obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1))], "q1")]
    rows = [row(1, 1, "th1"), row(1, 2, "th-nosearch")]
    rep = L.build_report({1: rows}, items, obs_, known_sessions={"th1", "th-nosearch"})
    assert rep["summary"]["per_run"][1]["recall"] == 0.5 and rep["pair_stats"]["no_search"] == 1
    with pytest.raises(ValueError, match="짝지을 수 없는"):
        L.build_report({1: [row(1, 1, "th1"), row(1, 2, "th-lost")]}, items, obs_, known_sessions={"th1"})
    ok = L.build_report({1: [row(1, 1, "th1"), row(1, 2, "th-lost")]}, items, obs_, known_sessions={"th1"}, allow_missing=True)
    assert ok["summary"]["per_run"][1]["n_scored"] == 1 and ok["coverage"]["fraction"] == 0.5 and ok["unpaired"] == ["run1 id=2: no_trace"]


def test_report_flags_a_wrong_pair_through_the_cited_chunk_check():
    items = load_items([item(1, "q1", ["a/p.md > Alpha"])])
    obs_ = [obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1))], "q1")]
    rep = L.build_report({1: [row(1, 1, "th1", cited=[A(1)])]}, items, obs_)
    assert rep["pair_stats"]["cited_True"] == 1
    rep = L.build_report({1: [row(1, 1, "th1", cited=[A(99)])]}, items, obs_)
    assert rep["pair_stats"]["cited_False"] == 1 and rep["detail"][0]["cited_in_trace"] is False


def test_regex_fallback_chunks_are_filled_from_the_corpus_for_section_matching():
    items = load_items([item(1, "q1", ["a/p.md > Alpha"])])
    bad = '{"chunks": [{"chunk_id": "%s", "text": "잘림' % A(1)       # JSON이 깨진 output
    o = obs("t1", "th1", T0, [], "q1")
    o["output"] = bad
    corpus_by_id = {A(1): ch("a/p.md", "Alpha", A(1))}
    rep = L.build_report({1: [row(1, 1, "th1")]}, items, [o], corpus_by_id=corpus_by_id)
    assert rep["detail"][0]["parse"] == "regex" and rep["summary"]["per_run"][1]["recall"] == 1.0


# ---------------------------------------------------------------- Langfuse 읽기(가짜 GET)

def test_observations_follow_the_cursor_until_the_end_and_thread_ids_come_from_root_sessions(monkeypatch):
    lf = L.Langfuse("https://example.invalid", "pk", "sk")
    calls = []

    def fake_get(path, params):
        calls.append(dict(params))
        if params["name"] == "question":
            return {"data": [{"sessionId": "u1:t-aaa"}, {"sessionId": "u1:t-bbb"}, {"sessionId": None}], "meta": {}}
        if params.get("cursor") is None:
            return {"data": [{"id": "1"}, {"id": "2"}], "meta": {"cursor": "c1"}}
        return {"data": [{"id": "3"}], "meta": {}}

    monkeypatch.setattr(lf, "get", fake_get)
    got = lf.search_observations(T0, T0 + timedelta(minutes=1))
    assert [o["id"] for o in got] == ["1", "2", "3"] and calls[0]["name"] == "search" and calls[0]["fields"] == "core,basic,io" and calls[1]["cursor"] == "c1"
    assert lf.thread_ids(T0, T0 + timedelta(minutes=1)) == {"t-aaa", "t-bbb"}


def test_only_get_requests_are_ever_built():
    src = Path(L.__file__).read_text(encoding="utf-8")
    assert "method=" not in src and "POST" not in src and "data=" not in src.split("class Langfuse", 1)[1].split("def search_observations", 1)[0]


# ---------------------------------------------------------------- 실행 진입점

def test_cli_stops_with_exit_3_when_rows_have_no_thread_id(tmp_path, capsys):
    d = tmp_path / "run1"
    d.mkdir()
    (d.parent / "run1" / "rows.jsonl").write_text(json.dumps(row(1, 1, None)) + "\n", encoding="utf-8")
    assert L.main(["--run-dir", str(tmp_path), "--observations-json", str(tmp_path / "none.json")]) == 3
    assert "thread_id가 없다" in capsys.readouterr().err


def test_cli_offline_run_writes_json_and_md_with_ids_only(tmp_path):
    items_path = tmp_path / "ds.jsonl"
    items_path.write_text(json.dumps(item(1, "q1", ["a/p.md > Alpha"]), ensure_ascii=False) + "\n", encoding="utf-8")
    rd = tmp_path / "res" / "run1"
    rd.mkdir(parents=True)
    (rd / "rows.jsonl").write_text(json.dumps(row(1, 1, "th1")) + "\n", encoding="utf-8")
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps([obs("t1", "th1", T0, [ch("a/p.md", "Alpha", A(1))], "q1")], ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    rc = L.main(["--run-dir", str(tmp_path / "res"), "--dataset", str(items_path), "--observations-json", str(obs_path), "--out", str(out), "--no-corpus"])
    assert rc == 0
    saved = json.loads((out / "recall_langfuse.json").read_text(encoding="utf-8"))
    assert saved["summary"]["per_run"]["1"]["recall"] == 1.0 and saved["detail"][0]["top5"] == [A(1)]
    assert "본문" not in (out / "recall_langfuse.json").read_text(encoding="utf-8")        # 청크 본문은 저장하지 않는다
    assert "Recall@5" in (out / "recall_langfuse.md").read_text(encoding="utf-8")
