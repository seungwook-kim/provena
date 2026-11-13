"""분류 단계만 불러 도메인 밖(`out_of_domain`) 분류를 확인한다(사전 등록 62.30). 검색, 판정, 답 작성은 부르지 않는다.

질문 그래프의 `classify` 노드를 서버와 같은 서비스 설정(`apply_service_profile`)과 같은 모델(`get_chat_model`)로 한 질문씩 돌린다.
접수 동시 호출은 끈다(재작성과 분해가 같이 나가지 않게). 그래서 질문 하나에 분류 1회, 도메인 밖이 나오면 확인 호출 1회가 더 나간다.
검색기는 부르면 오류를 내는 것으로 둔다(이 스크립트가 검색 비용을 쓰지 않는다는 보증). DB와 Voyage 키는 필요 없다.

사용(환경 변수는 이름만): `LLM_API_KEY`, `LLM_PROVIDER`(+`LLM_MODEL`)
`python -m evals.agent.classify_overrefuse --repeats 3 --out evals/results/classify_overrefuse_<표지>`
`--plan`은 호출하지 않고 문항 수와 예상 호출 수·비용만 낸다(0원).

문항: `evals/dataset_v2.jsonl` 50, `evals/dataset_holdout_v1.jsonl` 20, `evals/overrefuse_probe_v1.jsonl` 10(사내 규정을 묻는 기술 질문 5, 일반 기술 질문 5),
`evals/review_probe_v1.jsonl` 4(규정상 필요 여부를 예·아니오로 묻는 정책 질문, 사전 등록 62.34. 평가셋과 겹치지 않는다).
합동 검토 경로는 서버처럼 연결된 것으로 두어(자리만 채운 값, 부르지 않는다) 분류 뒤 코드의 되돌림까지 적용한 경로를 적는다.
`--with-review-set`: 합동 검토 평가셋 10건(`evals/dataset_review_v1_gold.jsonl`, 확정 정답 파일. 질문 원문은 초안 파일과 같다)을 더한다(번호 1001~1010). 이 10건은 모두 review여야 하고(문항마다 3회 중 2회 이상, 62.39 초안),
이 묶음 밖 문항이 review로 가면(v2, 검증, 프로브 94건 중) 기준 미달이다. 수정 전 운영 기록에서 이 묶음 밖 review는 0이었다.
종료 코드: 0 통과, 1 기준 미달(뒤 단계를 돌리기 전에 멈춘다), 2 실행 불가(키 없음, 문항 없음).

통과 기준(62.A에 측정 전에 적은 값과 같다. 검증 109번은 이 수정을 만들 때 본 문항이라 따로 적고 기준에서 뺀다):
- 관련 문항(v2 25, 검증 9, 새 사내 규정형 5)의 도메인 밖 행 0
- 일반 지식만 묻는 문항(`GENERAL_IDS`와 새 일반 기술 5)의 도메인 밖 행 비율 0.90 이상
- 필요 여부를 예·아니오로 묻는 문항(`need_yes_no` 4)의 합동 검토(`review`) 행 0 (62.34)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ("evals/dataset_v2.jsonl", "evals/dataset_holdout_v1.jsonl", "evals/overrefuse_probe_v1.jsonl", "evals/review_probe_v1.jsonl")
NEED_PROBE = "need_yes_no"  # 규정상 필요 여부를 예·아니오로 묻는 정책 질문(62.34). 합동 검토로 가면 안 된다
SEEN_ID = 109  # 이 수정을 만들 때 본 검증 문항. 결과는 적되 통과 기준에서 뺀다
# 수정 전 저장 기록(`agent_v2_q_d6151_{r1,r2,r3,h1}_bo2sda2_api`)에서 모든 행이 도메인 밖이었고, 조직이 정한 것이 아니라 일반 지식·외부 법령만 묻는 문항
GENERAL_IDS = (16, 17, 18, 19, 41, 42, 111, 112)
MIN_GENERAL_RATE = 0.90
# 예상 비용 근거: 수정 전 분류 호출 입력 758, 출력 15 토큰(`agent_v2_q_d6151_h1_bo2sda2_api/single/rows.jsonl` 109번 llm_trace). 새 프롬프트는 약 420자 길고 출력에 칸 하나가 더 붙는다
EST_INPUT_TOKENS, EST_OUTPUT_TOKENS = 1050, 25
EST_SECOND_CALL_SHARE = 0.25  # 도메인 밖이 나와 확인 호출이 한 번 더 나가는 문항 비율(80문항 가운데 약 20)


REVIEW_SET = "evals/dataset_review_v1_gold.jsonl"  # 합동 검토 평가셋 10건(`--with-review-set`일 때만 더한다). 문항 종류가 full, partial, clarify, low_issue이고 모두 합동 검토 요청이다
REVIEW_PROBE = "review_request"  # 이 묶음 문항은 분류 경로가 review여야 한다(사전 등록 62.39 초안)
MIN_REVIEW_RUNS = 2  # 문항마다 회차 중 이만큼 이상 review여야 통과(3회 중 2회)


def load_items(paths=DATASETS, with_review_set: bool = False) -> list[dict]:
    out = []
    for rel in paths:
        for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out.append({"id": r["id"], "question": r["input"], "kind": r["kind"], "probe": r.get("probe") or ""})
    if with_review_set:
        for line in (ROOT / REVIEW_SET).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out.append({"id": 1000 + r["id"], "question": r["input"], "kind": r["kind"], "probe": REVIEW_PROBE})  # 번호가 평가셋 v2와 겹치지 않게 1000을 더한다
    return out


def group_of(item: dict) -> str:
    """통과 기준에서 문항이 드는 묶음. `seen`은 기준 밖, `other`는 거절이 정답이지만 분류 경로는 어느 쪽이어도 되는 문항(검색 뒤 판정이 거절한다)."""
    if item["probe"] == REVIEW_PROBE:
        return "review_request"
    if item["id"] == SEEN_ID:
        return "seen"
    if item["kind"] == "relevant":
        return "relevant"
    if item["id"] in GENERAL_IDS or item["probe"] == "general":
        return "general"
    return "other"


def classify_node(llm: Any):
    """질문 그래프의 `classify` 노드. 검색기는 부르면 오류다(분류만 돈다는 보증)."""
    from backend.graph.build import build_graph

    def no_search(_q):
        raise RuntimeError("분류 확인은 검색을 부르지 않는다")

    return build_graph(no_search, llm=llm, parallel_intake=False, review_graph=lambda state: {}).nodes["classify"].bound  # 합동 검토는 자리만 채운다(분류 노드는 부르지 않는다)


class Counting:
    """모델 호출 수와 토큰을 센다."""

    def __init__(self, inner: Any):
        self.inner, self.calls, self.input_tokens, self.output_tokens = inner, 0, 0, 0

    def invoke(self, messages, **kw):
        msg = self.inner.invoke(messages, **kw)
        self.calls += 1
        usage = getattr(msg, "usage_metadata", None) or {}
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        return msg


def run(items: list[dict], llm: Any, repeats: int = 1) -> list[dict]:
    node = classify_node(llm)
    rows = []
    for rep in range(1, repeats + 1):
        for it in items:
            before = llm.calls if hasattr(llm, "calls") else 0
            route = node.invoke({"question": it["question"], "profile": {}}).get("route")
            rows.append({"repeat": rep, "id": it["id"], "kind": it["kind"], "group": group_of(it), "probe": it["probe"], "route": route,
                         "llm_calls": (llm.calls - before) if hasattr(llm, "calls") else None})
    return rows


def summarize(rows: list[dict]) -> dict:
    def part(group: str) -> dict:
        got = [r for r in rows if r["group"] == group]
        out = [r for r in got if r["route"] == "out_of_domain"]
        return {"rows": len(got), "out_of_domain": len(out), "out_of_domain_ids": sorted({r["id"] for r in out}),
                "not_out_of_domain_ids": sorted({r["id"] for r in got if r["route"] != "out_of_domain"})}

    s = {g: part(g) for g in ("relevant", "general", "other", "seen")}
    general_rate = s["general"]["out_of_domain"] / s["general"]["rows"] if s["general"]["rows"] else 0.0
    s["general_out_of_domain_rate"] = round(general_rate, 3)
    s["pass_relevant"] = s["relevant"]["out_of_domain"] == 0
    s["pass_general"] = general_rate >= MIN_GENERAL_RATE
    need = [r for r in rows if r.get("probe") == NEED_PROBE]
    s["need_yes_no"] = {"rows": len(need), "review": sum(1 for r in need if r["route"] == "review"), "review_ids": sorted({r["id"] for r in need if r["route"] == "review"})}
    s["pass_need_yes_no"] = s["need_yes_no"]["review"] == 0
    # 합동 검토 요청 묶음(62.39 초안): 문항마다 회차 중 MIN_REVIEW_RUNS회 이상 review. 이 묶음 밖의 문항이 review로 가면(새는 것) 안 된다
    ask = [r for r in rows if r.get("probe") == REVIEW_PROBE]
    per_id = {i: [r["route"] for r in ask if r["id"] == i] for i in sorted({r["id"] for r in ask})}
    s["review_request"] = {"rows": len(ask), "review_runs": {i: sum(1 for x in v if x == "review") for i, v in per_id.items()}, "routes": per_id}
    s["pass_review_request"] = all(sum(1 for x in v if x == "review") >= min(MIN_REVIEW_RUNS, len(v)) for v in per_id.values())
    leaked = [r for r in rows if r.get("probe") != REVIEW_PROBE and r["route"] == "review"]
    s["review_leak"] = {"rows": len(leaked), "ids": sorted({r["id"] for r in leaked})}
    s["pass_no_review_leak"] = not leaked
    s["passed"] = s["pass_relevant"] and s["pass_general"] and s["pass_need_yes_no"] and s["pass_review_request"] and s["pass_no_review_leak"]
    return s


def plan(items: list[dict], repeats: int) -> dict:
    from backend.services.cost import cost_usd  # 단가표: backend/services/llm_prices.json

    calls = round(len(items) * repeats * (1 + EST_SECOND_CALL_SHARE))
    usd = calls * cost_usd("claude-haiku-5-5", EST_INPUT_TOKENS, EST_OUTPUT_TOKENS)
    return {"items": len(items), "repeats": repeats, "est_llm_calls": calls, "est_cost_usd": round(usd, 4), "embedding_calls": 0,
            "groups": {g: sum(1 for it in items if group_of(it) == g) for g in ("relevant", "general", "other", "seen", "review_request")}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="분류 단계만 불러 도메인 밖 분류를 확인한다(62.30)")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out", type=Path, default=None, help="rows.jsonl과 summary.json을 쓸 폴더")
    p.add_argument("--with-review-set", action="store_true", help=f"합동 검토 평가셋 10건({REVIEW_SET})을 더해 review 분류를 확인한다(62.39 초안)")
    p.add_argument("--plan", action="store_true", help="호출하지 않고 문항 수와 예상 호출 수·비용만 낸다")
    a = p.parse_args(argv)
    items = load_items(with_review_set=a.with_review_set)
    if not items:
        print("문항이 없습니다.", file=sys.stderr)
        return 2
    if a.plan:
        print(json.dumps(plan(items, a.repeats), ensure_ascii=False, indent=2))
        return 0
    from backend.graph.service_profile import apply_service_profile
    from backend.services.llm import get_chat_model, is_demo_mode

    if is_demo_mode():
        print("실제 LLM이 필요합니다: LLM_API_KEY를 설정하고 DEMO_MODE를 끄세요.", file=sys.stderr)
        return 2
    apply_service_profile()
    llm = Counting(get_chat_model())
    rows = run(items, llm, a.repeats)
    summary = {**summarize(rows), "repeats": a.repeats, "llm_calls": llm.calls, "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens}
    if a.out is not None:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
