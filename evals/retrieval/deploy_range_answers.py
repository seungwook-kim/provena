"""배포본 금액 구간 질문 확인: 데모 구간 01의 금액 질문(5개 금액 x 3회)을 배포본 `/chat`에 보내 답과 인용을 저장한다.

- 질문은 `evals/results/range_retrieval_62_7/amount_questions.jsonl`의 201~205번(1만·3만·5만·10만·30만 달러)을 그대로 쓴다.
- 문항마다 새 대화로 보낸다(thread_id 없음). `as_of`는 문항의 값을 그대로 보낸다.
- 정답 구간 행 인용 여부는 인용 본문에 `gold_chunks`의 구간 표기(예 `>$0K to $25K`)가 들어 있는지로 자동 표시한다. 업무·재무 승인자 정오와 거절 여부는 저장된 답 전문으로 사람이 확인한다(자동 표시는 참고용).
- 로그인 정보는 환경 변수로만 받고 출력·저장하지 않는다.

    환경 변수: DEPLOY_RANGE_BASE_URL, DEPLOY_RANGE_LOGIN, DEPLOY_RANGE_PASSWORD
    python -m evals.retrieval.deploy_range_answers --out evals/results/range_retrieval_62_7/answers_deploy [--repeats 3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from evals.latency.deploy_latency import consume_chat_stream, iter_sse, normalize_as_of  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = REPO / "evals" / "results" / "range_retrieval_62_7" / "amount_questions.jsonl"
AUTH_COOKIE, CSRF_COOKIE, CSRF_HEADER = "provena_auth", "provena_csrf", "X-CSRF-Token"
FUNCTIONAL = {201: "Manager", 202: "Director", 203: "Director", 204: "Sr Director", 205: "VP"}


def _set_cookies(client: httpx.Client, headers) -> None:
    for raw in headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name in (AUTH_COOKIE, CSRF_COOKIE):
            client.cookies.delete(name)
            client.cookies.set(name, rest.split(";", 1)[0])


def login(client: httpx.Client, login_id: str, password: str) -> bool:
    r = client.get("/auth/csrf")
    _set_cookies(client, r.headers)
    tok = client.cookies.get(CSRF_COOKIE)
    if tok:
        client.headers[CSRF_HEADER] = tok
    r = client.post("/auth/login", json={"login_id": login_id, "password": password})
    if r.status_code != 200:
        print(f"로그인 응답 {r.status_code}")
        return False
    _set_cookies(client, r.headers)
    tok = client.cookies.get(CSRF_COOKIE)
    if tok:
        client.headers[CSRF_HEADER] = tok
    return True


def ask(client: httpx.Client, item: dict) -> dict:
    body = {"message": item["input"]}
    as_of = normalize_as_of(item.get("as_of"))
    if as_of:
        body["as_of"] = as_of
    t0 = time.perf_counter()
    answer, cites, done, err = [], [], {}, None
    step_fields = ("cost_by_step", "cost_by_step_total_usd", "embed_tokens", "embed_calls", "embed_cost_usd", "refuse_stage", "refuse_reason", "path")   # done의 측정용 칸(deploy_latency.STEP_FIELDS와 같다)
    with client.stream("POST", "/chat", json=body, headers={"Accept": "text/event-stream"}, timeout=120) as resp:
        if resp.status_code != 200:
            return {"status": f"http_{resp.status_code}", "total_s": round(time.perf_counter() - t0, 3)}
        for name, raw in iter_sse(resp.iter_lines()):
            try:
                p = json.loads(raw)
            except ValueError:
                continue
            et = name if name != "message" else p.get("type")
            d = p.get("data") or {}
            if et == "token":
                answer.append(str(d.get("text") or ""))
            elif et == "citation":
                cites.append({"rule_title": d.get("rule_title"), "article": d.get("article"), "version_date": d.get("version_date"), "text": d.get("text")})
            elif et == "done":
                done = d
            elif et == "error":
                err = d.get("code") or "error"
    usage = done.get("usage") or {}
    return {"status": "ok" if done else (err or "no_done"), "kind": done.get("kind"), "cost_usd": usage.get("cost_usd"),
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"), "llm_calls": usage.get("calls"),
            "total_s": round(time.perf_counter() - t0, 3), "answer": "".join(answer), "citations": cites,
            **{k: done.get(k) for k in step_fields}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args(argv)
    base, lid, pw = (os.environ.get(k) for k in ("DEPLOY_RANGE_BASE_URL", "DEPLOY_RANGE_LOGIN", "DEPLOY_RANGE_PASSWORD"))
    if not (base and lid and pw):
        print("환경 변수 DEPLOY_RANGE_BASE_URL, DEPLOY_RANGE_LOGIN, DEPLOY_RANGE_PASSWORD가 필요하다.")
        return 2
    items = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(base_url=base, timeout=30) as c:
        if not login(c, lid, pw):
            return 1
        for rep in range(1, a.repeats + 1):
            for it in items:
                r = ask(c, it)
                gold = it["gold_chunks"][0].split(" > ")[-1]
                row = {"id": it["id"], "repeat": rep, "question": it["input"], "gold_range": gold, "expected": it["expected"], **r}
                row["gold_cited_auto"] = any(gold in (ct.get("text") or "") for ct in r.get("citations", []))
                row["refused_auto"] = r.get("kind") == "refuse"
                row["functional_named_auto"] = FUNCTIONAL[it["id"]] in (r.get("answer") or "")
                rows.append(row)
                print(it["id"], rep, r.get("status"), r.get("kind"), "gold_cited" if row["gold_cited_auto"] else "no_gold", f"{r.get('total_s')}s")
    (out / "rows.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    print("저장:", out / "rows.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
