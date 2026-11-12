# SPEC: Provena 정본 문서

> 이 문서가 "무엇을 만들고, 어떤 숫자로 잘 됐다고 말하나"의 정본이다(가이드 p.14, p.21). 코드를 바꾸면 이 문서도 같은 PR에서 바꾼다. 기능별 상세는 `docs/specs/`, 설계는 [SDD](./SDD.md), 요구사항은 [PRD](./PRD.md), 팀 규칙은 [TEAM_GUIDE](./TEAM_GUIDE.md), AI 도구 지침은 [AGENTS.md](../AGENTS.md)에 있다. 숫자 기준은 PRD 13-2를 그대로 옮겼고 여기서 새 숫자를 만들지 않는다.

상태: 2026-11-11 갱신(D0 10/30 초안 이후). 숫자 기준은 D0 합의로 동결했고 이후 낮추지 않는다(가이드 p.14, p.19). 3장 결과 칸은 2026-11-11 현재 EVAL_REPORT.md와 evals/results/의 값이다.

## 1. 한 줄 정의

IT 조직의 정책·런북(GitLab 공개 핸드북, CC BY-SA 4.0)을 섹션과 판 날짜를 붙여 인용해 답하고, 근거가 없으면 거절한다. 인용한 정책이 바뀌면 이미 나간 답을 다시 확인해 받은 사람에게 알리고, 승인 권한표는 사람이 승인한 결정표로만 판단한다. 이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다.

## 2. 범위

### 2-1. 만드는 것

| ID | 기능 | 한 줄 | 사람 승인 | 상세 Spec |
|---|---|---|---|---|
| F-01 | 근거 답변 | 정책 섹션을 인용해 한국어로 답하고 판 날짜·출처 URL·CC BY-SA 4.0을 표시한다. 근거가 부족하면 되묻거나 거절한다 | 해당 없음 | [question-graph](./specs/question-graph.md) |
| F-02 | 답변 리콜 | 인용한 섹션이 바뀌면 영향받는 답을 다시 판정해 결론이 바뀐 답만 받은 사람에게 알린다. 연결된 정책은 관리자에게 "함께 볼 정책"으로 알린다. 업무시스템에는 웹훅으로 알린다 | 함께 볼 정책은 관리자 판단 | [recall](./specs/recall.md) |
| F-03 | 팀 합동 검토 | 보안, 인프라·SRE, IT 운영, 재무 에이전트가 한 건을 검토해 쟁점표를 만든다 | 쟁점표 저장 전 | [team-review](./specs/team-review.md) |
| F-04 | 결정표 | 승인 권한표를 결정표로 바꾸고, 관리자가 원문과 대조해 승인한 결정표만 실행한다. 실행에는 LLM을 쓰지 않는다 | 결정표 실행 전 | [decision-approval](./specs/decision-approval.md) |
| P-01 | 로그인과 사용자별 기억 | 로그인, 사용자 id로 대화(thread)와 장기 기억(Store namespace) 분리 | 해당 없음 | [login](./specs/login.md), [memory](./specs/memory.md) |
| P-02 | 문서 적재 | Markdown 파싱, 청킹, 임베딩, `data/manifest.jsonl`, 증분 수집 | 해당 없음 | [collect](./specs/collect.md) |
| P-03 | 업무시스템 연동 | REST(OpenAPI), FastMCP 서버, 웹훅, `mock_erp/`의 Python 예제. 자동 생성 SDK(Java·Python)는 `mock_erp/sdk/`(openapi-generator 7.26.0), Java 목업은 예정(아직 없음) | 해당 없음 | [erp-integration](./specs/erp-integration.md), [mcp](./specs/mcp.md), 업무시스템 쪽 REST는 [api](./api/api.md) |
| P-04 | 데모 모드 | `docker compose up` 한 줄, 키 없이 기동, 데모 계정 2개 시드 | 해당 없음 | 이 문서 4장 |
| 가산 | 자동화, GraphRAG, MCP·Skill | 증분 수집과 정시 실행, 페이지 링크 그래프, FastMCP와 런타임 Skill (가이드 p.20) | 해당 없음 | [incremental](./specs/incremental.md), [mcp](./specs/mcp.md) |

필수 뒤 진행: F-05~F-08. 11/6 중간 점검에서 모두 유지하기로 했고(결정 0066), 핵심 기능과 필수 게이트를 끝낸 뒤 진행한다(PRD 6-3).

### 2-2. 만들지 않는 것

실제 조직 시스템(배포·구매) 연동, 조직 내부망 배포, GitLab 비공개(internal) 문서, 결재 상신. 비공개 주소로만 연결된 내용은 답의 근거로 쓰지 않는다.

## 3. 숫자 기준 (PRD 13-2, 동결)

기준 칸은 D0(10/30) 합의로 동결했고 낮추지 않는다. 결과 칸은 2026-11-12 현재 `EVAL_REPORT.md`와 `evals/results/`의 결과 파일에 있는 값만 옮겼고, 값마다 잰 조건과 리비전을 적었다. 재지 않은 지표는 `미측정`으로 두고 이유를 적었다. 응답 시간, 비용, 질문 쪽 주입 결과는 리비전이 바뀌면 값이 바뀌므로 리비전을 함께 읽는다. 아래 응답 시간과 비용 행의 "공식 값"은 최신 배포 `provena-api-00044-49s`(11/12 03시 최종 운영 배포판, 커밋 `a50487f`)의 v2 50건 3회 측정이고(`EVAL_REPORT.md` 8장 표와 같다), 다른 행의 값은 행에 적은 리비전의 측정이다.

| 지표 | 기준 | 재는 법 (PRD 13-2) | 측정 명령 / 결과 파일 | 결과 (2026-11-11) |
|---|---|---|---|---|
| 검색 Recall@5 | 0.80 이상 | 평가셋 관련 문항, 사람이 정한 정답 섹션 기준 | `python -m evals.retrieval.compare ...`(`EVAL_REPORT.md` 9장), 결과 `evals/results/retrieval_v2_round2/`, `retrieval_fix_v1/` | v2 관련 25건 기본형(`voyage-4` 영어 문장 벡터, 리랭커 없음, 청크 800/120, k=5) 0.843(95% 구간 0.707~0.960). v1 관련 15건에서 질문 분해와 링크 확장(L1x2)을 더한 서비스 구성은 0.833에서 0.967(사후 등록 #9, `EVAL_REPORT.md` 3장). 서비스 최종 구성의 v2 관련 25건 x 3회 첫 검색 문맥 Recall@5는 최종 운영 배포판 `provena-api-00044-49s`에서 0.933(75행, 회차별 0.947, 0.927, 0.927, 95% 구간 0.880~0.980, 운영 Langfuse 추적의 첫 검색 문맥 청크 기준, 결과 `evals/results/lf_recall_provena-api-00044-49s/`)이다 |
| 인용 정확도 | 0.85 이상 | 답이 인용한 섹션이 정답 섹션과 맞는 비율 | `python -m evals.agent.exp_multi_v2 run --store pg --llm anthropic --out <폴더>`(전체 인자는 결과 폴더 `compare.json`의 `meta`), 결과 `evals/results/agent_v2_q_d6151_r1~r3_bo2sda2_api/`, 배포 측정은 `python -m evals.latency.deploy_latency`와 `deploy_citation_gold`, 결과 `deploy_latency_provena-api-00044-49s/`(이전 `deploy_latency_provena-api-00037-2jt/`, `deploy_latency_provena-api-00035-h69/`, `deploy_latency_provena-api-00032-zhs/`) | 최신 배포 `provena-api-00044-49s`(11/12 03시 최종 운영 배포판, 커밋 `a50487f`) v2 50건 3회: 인용 정확도 0.927(기준 충족), 정답 근거 인용률 0.913으로 비교 기준 `provena-api-00032-zhs`의 0.989와 0.976보다 낮고 사전 등록 62.38 (2)의 실패 기준 0.930 아래이다(직전 11/11 09시 운영 배포판 `provena-api-00037-2jt`는 0.918과 0.936, 그 앞 11/10 밤 운영 배포판 `provena-api-00035-h69`는 0.924와 0.929)(`EVAL_REPORT.md` 5장, README와 같은 값). 00044에서 v2 8·9번의 정답 밖 인용은 사라졌고(0/6행) v2 38번은 정답 문서를 인용하지 못한 채 남았으며(1/2, 0/2, 0/2) v2 3번·6번이 3회 모두 정답 위치 1/2로 새로 내려갔다. 3번·6번의 원인은 사전 등록 62.38 (2)로 나뉜 질문의 첫 검색 k를 8로 넓혀 문맥에 같은 사실을 말하는 다른 절이 더 들어온 것이다. 3번은 두 리비전의 문맥을 모두 확인해 확정했고 6번은 00044 문맥만 확인해 00037에서 그 절이 문맥에 없었다는 것은 가설이다. 금액 질문은 결정 0105(사전 등록 62.43)로 달러 금액이 든 나뉜 질문만 첫 검색 k=5로 되돌리는 것으로 처리했고, 이를 배포한 11/12 22시 배포판 `provena-api-00046-qkx`의 금액 15건은 답 14, 거절 1, 202~204번 답 8/9로 사전 등록 62.43의 기대를 채웠다(`EVAL_REPORT.md` 5-4절). v2 3번·6번은 달러 금액이 없는 질문이라 k=8 그대로이고 v2와 검증은 00046에서 다시 재지 않았다. 참고로 v2 50건 최종 3회 평균(사전 등록 61.51, 로컬)은 단일 1.000, 멀티 0.992이다. v2와 겹치지 않는 검증 20건(관련 10건)은 `00044-49s`에서 인용 정확도 0.772, 정답 근거 인용률 0.867이고 `00037-2jt`에서는 0.751과 0.750, `00035-h69`에서는 0.822와 0.800, `00032-zhs`에서는 0.772와 0.750으로 네 리비전 모두 인용 정확도가 기준 0.85에 못 미치고 정답 근거 인용률은 `00044-49s`만 0.85를 넘는다(`deploy_latency_holdout_provena-api-00044-49s/`, `deploy_latency_holdout_provena-api-00037-2jt/`, `deploy_latency_holdout_provena-api-00035-h69/`, `deploy_latency_holdout_provena-api-00032-zhs/`). v2 값은 같은 50건을 보고 고친 뒤의 값이라 낙관적일 수 있다(`EVAL_REPORT.md` 4장) |
| 비관련 질문 거절 | 0.90 이상 | 비관련 4종(도메인 밖, 코퍼스에 없는 대상, 없는 항목, 기간이 다른 질문). 비공개 문서 질문 포함 | 위와 같다 | 배포 `provena-api-00044-49s` v2 50건 3회 1.000(25/25), 과잉 거절 0.000. 같은 답의 RAGAS 충실도 0.9573(기준 0.91 충족, 문맥 정밀도 0.9733, 문맥 재현율 0.8618, 답변 관련성 0.6211, 채점 75행, 결과 `evals/results/ragas_deploy_provena-api-00044-49s/`). 이전 `00037-2jt` v2 50건 3회 1.000(25/25), RAGAS 충실도 0.919(기준 0.91 충족, 문맥 정밀도 0.939, 문맥 재현율 0.892, 답변 관련성 0.631, 채점 75행, 결과 `evals/results/ragas_deploy_provena-api-00037-2jt/`). 이전 `00035-h69` v2 50건 3회 1.000(25/25), RAGAS 충실도 0.967(문맥 정밀도 0.946, 문맥 재현율 0.882, 답변 관련성 0.643, 채점 74행, 결과 `evals/results/ragas_deploy_provena-api-00035-h69/`). 이전 `00032-zhs` v2 50건 3회 1.000, 검증 20건 3회 1.000. v2 50건 최종 3회 평균(로컬)은 단일·멀티 모두 1.000 |
| 판 날짜 표시 | 100% | 모든 답에 근거 섹션의 판 날짜 표시 | `evals/agent/run_eval.py`가 보조 값으로 내는 판 날짜 표시, 시험은 `tests/` | 최종 운영 배포판 `provena-api-00044-49s`의 배포 측정 원자료로 다시 센 값 1.000(130/130: v2 75/75, 검증 30/30, 새 문항 15/15, 금액 답 10/10, 거절 5건은 분모 밖, `EVAL_REPORT.md` 5장 5-4절. PR #131 결정 ②). 답 본문 글에 인용의 판 날짜가 모두 있는지를 센 값이며 화면 표시를 센 값은 아니다(00037-2jt 원자료 재계산은 합 134/134). `EVAL_REPORT.md` 4장 "판 날짜 표시율" 단락의 1.000은 로컬 실행기 값이다. 배포 측정에서 판 날짜가 다른 인용은 0건(00032-zhs, v2 50건 3회와 검증 20건 3회)이지만 이것은 인용한 판의 일치이지 표시율이 아니다 |
| 답변 리콜 | 재현율 0.80 이상, 정밀도 0.80 이상 | 실제 개정 커밋 전후 판으로 만든 시험 답변에서 결론이 바뀐 답을 찾는 비율 | 측정기 `python -m evals.agent.exp_recall_v1 --pairs evals/recall_pairs.jsonl --out evals/results/recall_v1` | 미측정. 측정기는 있으나 입력 파일 `evals/recall_pairs.jsonl`이 저장소에 없어 돌리지 않았다. 리콜 동작 자체는 시험(`tests/test_recall_graph.py`, `tests/test_recall_notice.py`)으로만 확인한다 |
| 함께 볼 정책 후보 | 정밀도를 재서 공개 | 사람이 정한 연결 정책과 대조 | 측정기 없음 | 미측정. 후보 평가 실행기를 만들지 않았다 |
| 링크 추출 | 정확도를 재서 공개 | 참조 그래프 간선을 원문과 대조 | 측정기 없음 | 미측정. 링크 있는 청크는 2,661개로 세었으나(`docs/GATES.md` G4) 간선을 원문과 대조한 정확도는 재지 않았다. 링크 확장의 검색 효과는 위 Recall@5 행에 있다 |
| 결정표 | 승인 전 실행 0건. 셀 정확도는 재서 공개 | 사람이 원문에서 뽑은 정답과 셀 대조 | 승인 전 실행은 `tests/test_decision_approval.py`(decision-approval AC-01) | 승인 전 실행 0건을 시험으로 확인했다. 재시작 뒤 승인·반려·결정표 승인 재개는 11/11 09시 운영 배포판 `provena-api-00037-2jt`의 묶음에서 건너뛰어 재지 않았으므로 최신 값은 배포 `provena-api-00035-h69`의 3건 모두 확인이다(R1~R9 전부 참, `evals/results/d7_restart_provena-api-00035-h69/`, 이전 `provena-api-00032-zhs`에서도 3건 확인). 셀 정확도는 원문 권한표 파싱 363칸 중 역할 주석 대조 불일치 0(`EVAL_REPORT.md` 1장)까지이고, 모델이 만든 결정표 초안의 셀 정확도는 정답 평가셋이 없어 미측정 |
| 신뢰 경계 | 결정표 기준 변경·승인 우회·유출 경로는 뚫림 0건, 나머지는 공격 성공률 공개 | 간접 인젝션 최소 30건 | `python -m evals.safety.run_safety`(30건 고정 세트), 배포 주소 대상은 `python -m evals.safety.deploy_injection_check`와 `deploy_corpus_injection_check`, 결과 `evals/results/injection_*`, `EVAL_REPORT.md` 6장 | 고정 30건 시험 기본 모드 뚫림 0, 실제 모델(Haiku 5.5) 뚫림 0. 최신 배포 `provena-api-00037-2jt`(11/11 09시 운영 배포판) 질문 쪽 주입 19건 뚫림 0, 대조군 3건 정상, 코퍼스 주입 9건 뚫림 0(9건 모두 시험 청크가 인용되어 시험됨, 판정 불가 0). 코퍼스 주입 시험만 11/11 12시 46분 운영 배포판(리비전 `provena-api-00038-th7`, 커밋 `4a14241`)에서 35건과 대조군 10건으로 늘려 쟀고 뚫림 0/35, 시험됨 32건, 판정 불가 3건(인용 없는 거절), 대조군 10/10 정상이다(사전 등록 62.37, 6장 26행). 이전 배포 `provena-api-00034-tkx` 질문 쪽 주입 19건 뚫림 0, 대조군 3건 정상. 배포 `provena-api-00033-kwn` 코퍼스 주입 9건 뚫림 0(시험 청크가 인용된 8건 막힘, 1건은 판정 불가). 모델이 심은 지시를 따라 답 본문이나 쟁점표 문장을 바꾸는 경로는 코드로 막을 수 없어 공격 성공률을 공개한다(6장) |
| 응답 시간 | 검색+리랭킹 p95 3초 이하(첫 요청 제외), 전체 p95 10초 이하 | Cloud Run에서 단계별 실측 | `python -m evals.latency.deploy_latency --revision <리비전> --commit <커밋>`, 결과 `evals/results/deploy_latency_<리비전>/`, 단계별은 `evals/latency/stage_times.py`와 `evals/agent/stage_report.py` | 전체 p95 공식 값: 11/12 03시 최종 운영 배포판 `provena-api-00044-49s`(커밋 `a50487f`) v2 50건 3회, 회차별 p95 평균 11.524초(8.583, 11.665, 14.323)로 거절·되묻기를 포함한 150건 기준으로도 충족하지 못하고 1회차만 10초 안이다. 답을 낸 질문만 보면 3회 합 p95가 14.921초이다(`EVAL_REPORT.md` 8장 "응답 종류별 분리"). 원인은 2번·38번의 재검색 경로, 측정 중 Cloud Run이 인스턴스를 새로 띄우는 동안 32번 3회차가 약 20초 기다린 것(그 행을 빼도 답한 것만 3회 합 p95는 14.32초), 13번·43번의 검색 노드 지연이 겹친 것이며 앞의 둘은 확정이고 검색 지연의 이유는 가설이다(`EVAL_REPORT.md` 8장). 응답 시간 초과의 처리는 결정 0105(금액 질문만 k=5)의 범위 밖이라 00044 값이 현재 값이다. 금액 15건만 11/12 22시 배포판 `00046-qkx`에서 다시 쟀고 p50 11.344초, p95 17.540초로 10초를 넘은 행이 8행이다. 직전 11/11 09시 운영 배포판 `00037-2jt`는 회차별 p95 평균 8.416초(8.348, 8.611, 8.289)로 충족했고 답을 낸 질문만은 13.174초였다. 11/10 밤 운영 배포판 `00035-h69`는 회차별 p95 평균 8.942초(8.518, 8.169, 10.139)로 3회차가 10초를 넘었고 답을 낸 질문만은 13.608초였다. 같은 방식의 이력은 `00032-zhs` 8.473초, `00029-qbd` 11.153초, `00020` 15.641초. `00033-kwn` 1회 측정 10.634초는 3회 평균이 아니어서 이력으로만 둔다. 검색 단계 p95는 0.92초(11/12 03시 최종 운영 배포판 `00044-49s`의 Langfuse 세션 149개, 검색 노드 시간의 세션 합. 11/11 09시 `00037-2jt`의 세션 49개에서는 1.02초, 11/10 밤 `00035-h69`의 세션 64개에서는 1.22초), 로컬 최종 측정 150건에서 1.11초로 3초 이하이며 리랭커는 쓰지 않는다. 같은 리비전 `00044-49s`의 검증 20건 3회 p95 평균은 9.656초(12.700, 7.259, 9.008)로 10초 안이나 1회차는 10초를 넘었다(`00037-2jt`는 9.788초, `00035-h69`는 10.322초) |
| 비용 | 질문 1건 평균 $0.01 이하 | Langfuse 비용 기록 | Langfuse 대시보드(스크린샷은 `docs/images/langfuse/`), 배포 측정 요약 `evals/results/deploy_latency_<리비전>/summary.json` | 배포 `provena-api-00044-49s`(11/12 03시 최종 운영 배포판) 요청당 0.0076달러(3회 합 1.1347달러를 150건으로 나눈 값, 질문 번역 LLM 비용 제외), `00037-2jt` 0.0079달러(3회 합 1.1814달러), `00035-h69` 0.0074달러(3회 합 1.1025달러), `00032-zhs` 0.0067달러, `00029-qbd` 0.0052달러. 로컬 최종 측정은 50건 회당 단일 0.261달러(요청당 약 0.0052달러). 단계별 비용은 배포본 `00044-49s`의 서버 집계(`done.cost_by_step`, 150행)가 `EVAL_REPORT.md` 8장 "배포본 단계별 비용" 표에 있고 Voyage 질문 임베딩은 150행 합 0.000301달러다(`00037-2jt`는 0.000295달러, `00035-h69`는 0.000287달러). 로컬 최종 측정 150건 재계산은 `evals/results/d8_stage_report/`에 있다 |
| 기동 | 깨끗한 환경에서 `docker compose up` 10분 이내 | G2 | 새 clone에서 `docker compose up -d --build`와 `/health` 확인, 소요 시간은 `docs/GATES.md` G2 칸에 기록 (손으로 잼) | 2026-11-09 새 clone(main `0b503f7`, `.env` 없음) `/health` 응답까지 5분 35초. 이미지 풀기가 늦은 회차 1번은 10분 22초, 다른 회차 3분 51초. 2026-11-10에 발견된 `db/106` 역할 오류는 [PR #110](https://github.com/aihuman-7th/proj3-c/pull/110)이 고쳤고 이후 `db/109` 재정렬이 들어갔으므로, 이 병합본 기준의 새 clone 재확인은 아직 하지 않았다 |

공통 규칙:

- 평가셋은 v1(`evals/dataset_v1.jsonl`), v2(`evals/dataset_v2.jsonl`)이고 동결 해시는 `evals/FROZEN.json`에 있다. v1은 2026-11-01, v2는 2026-11-02에 동결했고 v2는 2026-11-07에 38번 정답을 판정자 확인에 맞춰 고치고 다시 동결했다(결정 0075, 현재 해시 `810d01f1…24d9f`). 검증 20건(`evals/dataset_holdout_v1.jsonl`)은 v2와 겹치지 않는 문항으로 결정 0074에 따라 따로 둔다. 이 20건은 팀장이 검토했고 두 판정자의 판정 기록은 찾지 못해 판정을 다시 받았다. 2026-11-11 두 판정자(박진형, 강경희) 재판정 완료, 20건 모두 Y, 정답 변화 없음(`evals/judge_sheet_holdout_v1.csv`, 결정 0096). 동결 확인은 `python evals/freeze.py --check`이며 `tests/test_frozen_evals.py`가 PR마다 검사한다.
- 실험은 바꾸기 전에 `evals/PREREGISTER.md`에 기대를 먼저 적고 한 번에 하나만 바꾼다.
- 숫자는 실행 결과에서 나온 값만 쓰고, 실행 명령을 함께 적는다. 점수가 오르지 않았으면 오르지 않았다고 쓴다.
- 평가 결과는 `EVAL_REPORT.md`에 개선 전후, 달라진 문항, 지표 5개 분리 보고로 옮긴다.
- 한 번에 재는 명령(`evals/run_all.py`)은 만들지 않았다. 지표마다 위 표의 명령을 쓰고, CI는 커밋된 최종 측정 결과를 통과선과 견주는 `python evals/ci_compare.py`와 `pytest -q`를 돌린다(`.github/workflows/ci.yml`).

## 4. 데모 모드 (P-04, G2)

평가자에게는 API 키가 없으므로 `docker compose up` 한 줄이 키 없이 떠야 한다.

| 항목 | 내용 |
|---|---|
| 기동 | `docker compose up`. `.env`가 없어도 뜬다. compose가 `.env.example`을 먼저 읽고 `.env`가 있으면 그 값으로 덮는다 |
| LLM | `DEMO_MODE=1`이면 키 없이 기록해 둔 응답을 재생하고, 기록이 없는 호출은 결정적 가짜 응답으로 대신한다(`backend/services/llm.py`, `backend/services/demo_replay.py`) |
| DB | 로컬 pgvector 컨테이너(`db`). 검색 색인은 compose의 `loader` 서비스가 커밋된 `data/index.tar.gz`(없으면 `INDEX_URL`)를 풀어 적재한다(`backend/rag/retrieve/load_snapshot.py`). 색인이 없으면 적재를 건너뛰고 서버는 뜨며, 질문은 거절로 끝난다 |
| 로그인 | 로컬 데모 계정 2개(user, admin)를 시드한다. `PROVENA_ENV=local`이고 `PROVENA_DEV_MODE=1`일 때만 만들고 그 밖의 모드에서는 만들지 않는다. 아이디·비밀번호는 환경변수(`DEMO_USER_*`, `DEMO_ADMIN_*`)에서 읽고(로컬 데모 값은 `.env.example`) 비밀번호는 8자 이상이다. 코드와 SQL에는 값이 없다 |
| 평가용 계정 | 제출하는 평가용 계정(G1)은 데모 계정과 다른 값이고 저장소에 적지 않는다 |
| 서명 키 | `AUTH_SECRET`은 저장소에 두지 않는다. 비어 있으면 로컬 데모 모드에서만 실행마다 무작위로 만들고(재시작하면 다시 로그인), 그 밖의 모드에서는 시작하지 않는다 |
| 구현 위치 | `backend/main.py`(라우터 연결, 시드 호출), `backend/services/auth_store.py`(Postgres 저장소), `backend/services/demo_seed.py`(시드), `db/101_auth_users.sql`(users 테이블) |
| 시험 | `tests/test_auth_store.py`(저장소, 시드, 앱 연결), 실제 Postgres까지는 `PROVENA_TEST_DATABASE_URL`을 줄 때만 |

## 5. 파트 사이 계약과 API

- 데이터 형식은 `backend/schemas/`(chunk, events, approval, recall, decision)이고 SDD 6장과 같다. 필드 추가는 PR 하나로 3명 승인, 이름 변경·삭제는 회의에서만 정한다. 시험은 `tests/test_schemas.py`. `AgentEvent.data`의 `type`별 키는 SDD 6장 표를 따른다.
- 엔드포인트 목록은 SDD 4-4장과 정적 명세 docs/api/openapi.json(경로 48개, 동작 54개. 라우터가 바뀌면 python docs/api/export_openapi.py로 다시 만든다. 사용법은 [api.md](./api/api.md))이다. 구현된 것은 /health, 로그인·가입 라우터(/auth/csrf, /auth/login, /auth/logout, /auth/signup, /auth/google/start, /auth/google/callback, /me, /me/profile), 사용자 관리(/admin/users, /admin/signup-requests 아래), 결정표·승인(/decision-tables 아래, /approvals 아래), /chat(SSE), /threads, /threads/{thread_id}, /me/memory, 리콜(/recalls 아래, /impact-preview, /maintenance-candidates, /webhook-subscriptions, /webhook-deliveries, /webhooks/regulation-updated), 변경 감시(/changes 아래), 평가 전용 `POST /admin/eval/review`(관리자 전용, 환경 변수 `EVAL_REVIEW_SINGLE=1`일 때만 열림, 기본 꺼짐, 결정 0104)이며 /health 밖의 라우터는 DATABASE_URL이 있을 때만 붙는다. 화면 파일을 내주는 경로와 /mcp(FastMCP 앱)는 명세에 나오지 않는다. 모든 오류는 `{"error": {"code", "message", "request_id"}}` 한 모양이고(화면 호환을 위해 같은 문구의 `detail` 문자열을 함께 낸다) 화면은 `code`로 분기한다(`backend/api/errors.py`). 요청마다 `X-Request-ID` 헤더와 로그 한 줄을 남긴다(`backend/api/middleware.py`). 오류 본문, HTTP 상태별 `code`, 요청 ID, 재시도 안내는 SDD 4-4절을, `/chat` SSE의 전달 형식·이벤트 순서·`done`의 `code`는 SDD 6장을 따른다. 경로를 더하거나 바꾸면 이 문서, SDD, 정적 명세를 같은 PR에서 고친다.

## 6. 게이트와 증거

필수 게이트 G1~G7이 이 저장소 어디에서 채워지는지와 지금 상태는 [GATES.md](./GATES.md)에 있다. 핵심 코드를 한 줄 깨뜨려 테스트가 실제로 실패하는지 확인하는 기록도 그 문서에 둔다.

## 7. 데이터와 이용 조건

핸드북 본문은 CC BY-SA 4.0이다. 답에 원문을 보일 때는 페이지 URL, 라이선스 링크, 수정 여부를 함께 표시한다. 원문 텍스트는 코드와 폴더를 나누고 `data/LICENSES/`에 고지와 출처를 적는다. 로고를 쓰지 않으며 README와 발표에 "GitLab Inc.와 제휴·보증 관계 없음"을 적는다(SDD 8장).

## 이메일 가입·인증 API 정합성

이메일 가입은 `/auth/signup`에서 시작하고 `/auth/signup/verify`와 `/auth/signup/resend`로 인증을 처리한다. 인증번호는 5분간 유효하며 재발송은 이메일별 60초 및 최대 5회 제한과 IP별 60초 30회 제한을 함께 적용한다. 관리자 가입 승인 목록은 `/admin/signup-requests`이고, 승인은 `request_id` 기반 `/admin/signup-requests/by-id/{request_id}/{action}`를 우선 사용한다. 최고 관리자(owner)만 이메일 미인증·승인 대기 신청의 발송 횟수를 `/admin/signup-requests/by-id/{request_id}/reset-verification`으로 초기화할 수 있으며, 해당 요청은 CSRF 보호를 적용한다.

`107_email_signup_verification.sql` 및 `108_auth_privacy_hardening.sql`의 운영 적용 여부와 순서는 최신 DB 재정렬 정책(`109_realign.sql`)과 함께 DB 담당자가 결정한다. 애플리케이션은 운영 DB에 마이그레이션을 자동 적용하지 않는다.
