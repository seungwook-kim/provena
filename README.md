# Provena (프로베나)

**IT 조직의 개발·운영 담당자가 정책과 런북을 찾아 판단하는 데 드는 시간을 줄이고, 정책이 바뀐 뒤에도 예전 답을 믿고 일하는 문제를 막는 엔지니어링 지식 AI 플랫폼.** 정책·런북을 섹션과 판 날짜를 붙여 인용해 답하고, 근거가 없으면 거절한다. 인용한 정책이 바뀌면 이미 나간 답을 다시 확인해 받은 사람에게 알리고, 승인 권한표는 사람이 승인한 결정표로만 판단한다.

KDT AI Human 7기 3차 팀 프로젝트 · 3조 · 김승욱(팀장), 박진형, 강경희 · 저장소 https://github.com/aihuman-7th/proj3-c

## 무엇을 하는 서비스인가

개발·SRE·보안·IT 운영 담당자는 일하다가 회사 정책과 런북을 보고 승인권자, 절차, 기한을 판단한다(SaaS 도입, 배포, 장애 대응, 보안 검토). 답을 찾는 데 시간이 들고 담당자 답을 기다리며 흐름이 끊긴다. 정책이 바뀌어도 예전에 받은 답(AI 답 포함)은 그대로 남아 바뀐 절차를 모르고 일하게 된다. 문제의 근거(공개 설문, 현직자 설문 응답 5명, 정책 변경 빈도)는 [docs/PRD.md](./docs/PRD.md) 2장과 [docs/deliverables/survey/](./docs/deliverables/survey/)(설문지 [questionnaire_2026-11-13.md](./docs/deliverables/survey/questionnaire_2026-11-13.md), 문항별 응답 집계 [responses_tally.md](./docs/deliverables/survey/responses_tally.md), 응답 요약 [responses_summary.md](./docs/deliverables/survey/responses_summary.md), 집계 방법 [aggregation_method.md](./docs/deliverables/survey/aggregation_method.md))에 있다.

Provena는 질문을 받으면 정책 원문에서 근거를 찾아 섹션과 판 날짜를 붙여 답하고, 근거가 없으면 거절한다. 정책이 바뀌면 그 섹션을 인용한 답을 찾아 결론이 바뀌었는지 다시 판정하고, 바뀐 답은 받은 사람과 업무시스템에 알린다. 승인 권한표는 결정표로 바꾸어 사람이 승인한 뒤에만 판단에 쓰고, 금액 판단은 코드가 한다.

## 최종 지표

측정한 운영 배포판은 동결 코드의 `provena-api-00172-rex`(커밋 `194dfd9a`, 2026-11-16 21:38 KST부터 2026-11-17 00:45 KST까지 서비스)이다. 2026-11-17 00:45 KST부터 09:15 KST 무렵까지는 같은 이미지·같은 환경 변수에 LLM 키 비밀값만 바꾼 `provena-api-00178-max`가 서비스했다(00:19~00:36 KST에 키 비밀값이 삭제되어 요청이 실패한 뒤 교체, 경위는 [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md) 2장). 코드와 설정이 같으므로 아래 공식 값은 00178-max에도 같이 해당한다. 2026-11-17 09:15 KST 무렵부터의 서비스 판은 아래 "코드 위치"에 적은 `provena-api-00181-zub`(main 코드 `9bc7d587`)이다. 공식 값은 이 판의 배포 주소에서 잰 3회 측정 평균이다(2026-11-16 22:04~22:46, 실패 행 0, 첫 검색 Recall@5·MRR@5·nDCG@5도 이 판의 운영 Langfuse 기록으로 쟀다). 같은 이미지와 같은 운영 환경 변수로 Langfuse 키만 이전 키인 판 `provena-api-00165-kag`(20:29~21:00)의 값은 같은 이미지·설정의 앞선 측정으로 함께 적었다. 이 판은 질의 분석 LLM 호출을 같은 입력으로 두 번 동시에 보내 먼저 끝난 결과를 쓰는 장치(`GRAPH_CLASSIFY_RACE`, 결정 0127)를 켜고, 분해 때 모든 하위 질문에 원 질문의 대상·조건을 남기는 장치(`GRAPH_DECOMPOSE_KEEP_SUBJECT`)는 운영 환경 변수로 끈 판이다(켠 판 `provena-api-00130-faq`의 v2 정답 근거 인용률이 0.924로 낮았다, 결정 0126, EVAL_REPORT 11장). 평가셋 v2는 50건(관련 25, 비관련 25), 검증 세트는 v2와 겹치지 않는 20건(관련 10, 비관련 10), 새 검증 세트는 측정 전에 등록한 20건(501~520번, 관련 14, 비관련 6)이다. 기준은 D0(10/30)에 합의해 동결했다. 직전 운영 판 `provena-api-00150-jub`(커밋 `11cc305f`)의 값은 비교로 함께 적었고, 이 이미지에서 다시 재지 않은 지표는 직전 최종 판 `provena-api-00065-q84`(커밋 `5a8c6527`)의 값이며 행마다 판을 적었다. 되돌림용 판은 `provena-api-00166-mob`(00150-jub 설정에 새 Langfuse 키)과 `provena-api-00079-tmt`(커밋 `c565998d`)이다. 코드 위치(2026-11-17 확인): 공식 측정값은 그대로 동결 코드 `194dfd9a`의 `provena-api-00172-rex` 3회 측정이다. 2026-11-17 09:15 KST 무렵부터는 main 코드 `9bc7d587`(main HEAD와 실행 코드 같음)의 `provena-api-00181-zub`가 트래픽 100%로 서비스한다. 측정한 코드에 더한 것은 질문 속 한국어 출력 자리 지시 규칙(사전 등록 62.77), 기억 칸 값의 프롬프트 입력 정화, `/admin/sync` 501 안내 문구이고(동결 뒤 코드 커밋 `c7a0e29d`·`9bc7d587`, backend 4개 파일 `backend/api/changes.py`, `backend/api/errors.py`, `backend/graph/untrusted.py`, `backend/prompts/question.py`), 설정은 00178-max와 이미지·라벨·빌드 주석만 다르다. 이 판에서 따로 확인한 것은 배포 점검 7/7, 직접 인젝션 시험 27건 모두 막힘(대조군 3/3 정상), v2 50건 1회 정답 근거 인용률 0.933·인용 정확도 0.940(00172-rex 3회와 다른 문항은 39번 하나), 같은 이미지의 임시 0% 판에서 실패 경로 3종(검색 0건, 비용 상한, 시간 초과)이다(`evals/results/deploy_check_provena-api-00181-zub/`, `injection_live_provena-api-00181-zub/`, `deploy_latency_c1117b_provena-api-00181-zub/`, `failure_paths_provena-api-00181-zub/`). 승격 뒤 확인(09:16~09:18 KST): 트래픽 00181-zub 100%, `/health` 200, 워밍업 1건 성공(10.9초, 0.0152달러, 대화 DB 저장 확인), 00181-zub 5xx 0건(`evals/results/promote_provena-api-00181-zub/`). 동결 SHA `47e3b82a`(실행 코드 `194dfd9a`)는 승격 전까지 00172-rex·00178-max가 서비스했다([제출 체크리스트](./docs/deliverables/submission_checklist.md)).

| 지표 | 기준 | 최종 값 | 근거 |
|---|---|---|---|
| 인용 정확도, 평가셋 v2 50건 | 0.85 이상 | **0.960** (정답 근거 인용률 0.947, 3회 모두 0.947, 오답 근거 0.040. 같은 이미지·설정의 앞선 측정 00165-kag는 0.960, 0.951. 직전 운영 판 00150-jub은 인용 정확도 0.956, 정답 근거 인용률 0.947) | [EVAL_REPORT.md](./EVAL_REPORT.md) 5-4절, `evals/results/deploy_latency_provena-api-00172-rex/citation_gold.json` |
| 인용 정확도, 검증 20건 | - | **0.911** (정답 근거 인용률 0.900, 3회 모두 0.900, 오답 근거 0.200. 앞선 측정 00165-kag 0.948, 0.883. 직전 운영 판 0.917, 0.900) | 5-4절, `evals/results/deploy_latency_holdout_provena-api-00172-rex/` |
| 인용 정확도, 새 검증 20건(501~520번, 측정 전 등록) | - | **0.661** (정답 근거 인용률 0.857, 3회 모두 0.857, 오답 근거 0.500. 앞선 측정 00165-kag 0.671, 0.881. 직전 운영 판 0.651, 0.833). 첫 검색 관련 14건 x 3회(42행): Recall@5 0.929 [0.833, 1.000], MRR@5 0.738, nDCG@5 0.712. 답 작성 문맥 재현율은 미측정 | `evals/results/deploy_latency_holdout_v2_provena-api-00172-rex/`, `evals/results/recall_holdout_v2_00172-rex/` |
| 비관련 질문 거절, 평가셋 v2 50건 | 0.90 이상 | **1.000** (과잉 거절 0.000. 검증 20건과 새 검증 20건도 1.000과 0.000) | 5-4절 |
| 첫 검색 Recall@5 (운영 추적의 첫 검색 상위 5) | 0.80 이상 | **0.927** [0.871, 0.973] (v2 관련 25건 x 3회, 75행). 검증 관련 10건 x 3회(30행)는 0.817 [0.667, 0.933], 새 검증 관련 14건 x 3회(42행)는 0.929 [0.833, 1.000]. 괄호는 95% 구간. 운영 판 00172-rex의 운영 Langfuse 기록으로 잰 값이다. 직전 운영 판 00150-jub은 v2 0.933, 검증 0.750, 새 검증 0.929, 직전 최종 판 00065-q84는 v2 0.940, 검증 0.783 | `evals/results/lf_recall_provena-api-00172-rex/`, `evals/results/recall_holdout_00172-rex/`, `evals/results/recall_holdout_v2_00172-rex/`, [docs/GATES.md](./docs/GATES.md) G5 |
| 첫 검색 MRR@5, nDCG@5 (같은 첫 검색 상위 5, 같은 정답) | - | 판 00172-rex(위 행과 같음). v2 관련 25건 x 3회(75행): MRR@5 **0.778** [0.704, 0.852], nDCG@5 **0.812** [0.748, 0.876]. 검증 관련 10건 x 3회(30행): MRR@5 0.631 [0.483, 0.778], nDCG@5 0.672 [0.534, 0.805]. 새 검증 관련 14건 x 3회(42행): MRR@5 0.738 [0.635, 0.829], nDCG@5 0.712 [0.622, 0.794]. 괄호는 부트스트랩 2000회(시드 0) 95% 구간. 직전 운영 판 00150-jub은 v2 MRR@5 0.778, nDCG@5 0.816, 검증 0.624, 0.643, 새 검증 0.718, 0.700 | `evals/results/lf_recall_provena-api-00172-rex/mrr_ndcg.json`, `evals/results/recall_holdout_00172-rex/mrr_ndcg.json`, `evals/results/recall_holdout_v2_00172-rex/mrr_ndcg.json`(운영 Langfuse의 첫 검색 상위 5를 공식 채점 코드로 계산) |
| 판 날짜 표시 | 100% | **1.000** (v2 답 75/75, 검증 30/30, 새 검증 42/42) | [docs/SPEC.md](./docs/SPEC.md) 3장 |
| 전체 응답 시간 p95 (회차별 p95의 평균, 거절·되묻기 포함) | 10초 이하 | **8.264초** (회차별 8.125초, 8.514초, 8.152초, 3회 합 8.223초). 답한 질문만(관련 25건)은 회차별 8.125초, 9.492초, 8.253초(3회 합 8.385초)이다. 같은 이미지·설정의 앞선 측정 00165-kag는 8.538초, 답한 질문만 3회 합 8.746초. 직전 운영 판 00150-jub은 9.185초, 답한 질문만 3회 합 10.354초. 검증 20건 회차별 p95 평균 8.543초, 새 검증 20건 9.589초 | [EVAL_REPORT.md](./EVAL_REPORT.md) 8장, `evals/results/deploy_latency_provena-api-00172-rex/summary.md` |
| 단계별 응답 시간 | 검색+리랭킹 p95 3초 이하 | 동결 판 00172-rex(v2 150세션, 운영 Langfuse): 검색 p50 0.00초, p95 0.81초. 리랭킹 사용 안 함. 생성 p50 4.77초, p95 7.70초, 그래프 전체 p50 4.87초, p95 8.01초. 직전 최종 판 00065-q84는 검색 p95 1.00초, 생성 p50 5.62초, p95 8.14초. 승인 대기의 기계 시간(재개부터 끝, 로컬 Postgres 시험) p95 결정표 33.7밀리초, 합동 검토 80.2밀리초 | 8장 단계별 표, `evals/results/stage_table_p1116_00172-rex/` |
| 요청당 비용 | 0.01달러 이하 | **LLM 비용 0.0050달러** (v2 50건 3회 합 0.7501달러. 검증 20건 0.0048달러, 새 검증 20건 0.0072달러. 앞선 측정 00165-kag는 0.0049달러) | 8장 |
| 신뢰 경계 (배포 주소 대상 주입) | 뚫림 0건 | 질문 주입 0/19, 코퍼스 주입 0/35(시험됨 34, 인용 없는 거절로 판정 불가 1). 서비스 판 `provena-api-00178-max`(동결 코드 `194dfd9a`)에서 2026-11-17 02:10~02:18 KST에 다시 잰 값이다(질문 쪽 19건 막힘, 대조군 3/3 정상, 코퍼스 35건 막힘, 대조군 10/10 정상). 처음 잰 판은 커밋 `5a8c6527`의 이전 운영 판 `provena-api-00068-drb`(2026-11-16, 다른 이미지)이며 두 판의 사례별 판정은 모두 같다 | [EVAL_REPORT.md](./EVAL_REPORT.md) 6장, `evals/results/injection_deploy_provena-api-00178-max/`, `evals/results/injection_corpus_deploy_provena-api-00178-max/` |
| 재시작 뒤 승인 재개 | - | **3/3** (동결 판 `provena-api-00172-rex`에서 만든 쟁점표 승인·쟁점표 반려·결정표 초안 반려 대기를 같은 이미지·같은 설정의 새 리비전 `provena-api-d10r1116`(트래픽 0%)을 띄워 재시작으로 삼은 뒤 그 리비전에서 처리, R1~R9 3/3, R10 통과, 재개 확인 6.8초, 2026-11-16 23:17~23:33. 이전 판 기록: `provena-api-00075-5zk`에서 만든 대기를 `provena-api-00079-tmt`에서 처리해 3/3, 재개 확인 5.6초) | [docs/GATES.md](./docs/GATES.md) G4, `evals/results/d10_restart_provena-api-00172-rex/`, 이전 판 기록 `evals/results/d10_restart_provena-api-00079-tmt/` |
| 개선 전후 (검증 20건 인용 정확도) | - | **0.772 → 0.911** (검증 20건, 운영 판 00172-rex). 실패 유형 분석으로 찾은 다섯 원인(도메인 밖 오분류, 첫 검색 누락, 근거 선택, 정답 밖 인용, 표 청크 라벨 소실)을 고쳐 과잉 거절을 0.100 → 0.000, 오답 근거를 0.370 → 0.200으로 줄였다. 같은 기간 v2 50건은 0.989 → 0.960이다. 이 측정 3회에서 정답 위치를 한 번도 인용하지 못한 v2 문항은 38번 하나이고(3회 모두 정답 위치 0/2, 회당 0.040 감점), 39번은 3회 모두 정답 3곳 중 2곳을 인용했다. 38번은 문항 표현에 맞춘 검색어 용어표를 일반 규칙이 아니어서 걷어낸 뒤부터 정답 위치를 인용하지 못한다(EVAL_REPORT 8장). | 개선 전은 첫 운영 측정 판 `provena-api-00032-zhs`, 5-4절 리비전별 표, [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md) |

v2 값은 같은 50건의 실패 문항에서 출발해 고친 뒤의 값이라 낙관적일 수 있다. 일반화는 검증 20건으로 읽는다(아래 "알려진 한계"). 지표별 전체 이력과 미측정 지표는 [docs/SPEC.md](./docs/SPEC.md) 3장에 있다.

### 사용 모델

운영 값은 Cloud Run 서비스 `provena-api`의 환경변수 이름과 모델 이름 값(2026-11-16 조회, 키 값은 읽지 않음)과 코드 기본값으로 확인했다. 운영에는 `LLM_PROVIDER=anthropic`만 있고 `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `EMBED_MODEL`, `RERANK_MODEL`은 없으므로 아래 코드 기본값이 쓰인다.

| 역할 | 운영 서비스 | 측정 | 근거 |
|---|---|---|---|
| 답 작성, 질의 분석(`classify`), 질문 분해·재작성, 근거 충분 판정(`judge`), 근거 확인(`ground`), 질문 번역 | `claude-haiku-5-5`, Anthropic API 직접 호출 | 같음(배포 측정은 운영 서비스를 그대로 부른다. 4장 로컬 최종 측정도 Anthropic API 직접 호출) | `LLM_PROVIDER`, `backend/services/llm.py:70`(`DEFAULT_ANTHROPIC_MODEL`), `backend/graph/build.py:445`, `backend/rag/retrieve/translate.py:83` |
| 팀 합동 검토(Supervisor, 팀 에이전트 4개) | 같은 모델 | 같음 | `backend/graph/departments/review.py:139` |
| 결정표 변환 초안 | 같은 모델 | - | `backend/graph/decision/routes.py:550-552` |
| 답변 리콜의 결론 재판정 | 같은 모델(키 없는 데모는 녹화한 판정, 녹화에 없으면 규칙 판정) | - | `backend/graph/recall/judge.py` `default_judge` |
| 추론 수준 | 분해·답 작성·근거 충분 판정만 `low`, 나머지 끔 | 같음 | `backend/graph/service_profile.py:50, 94-95` |
| 임베딩(문서·질문) | `voyage-4`, Voyage AI API | 같음 | `EMBED_MODEL`, `backend/rag/retrieve/embed.py:53` |
| 리랭커 | 없음 | 비교 측정에서만 4종(EVAL_REPORT 3-2절) | `RERANK_MODEL`, `backend/rag/retrieve/rerank.py:43` |
| 인용 정확도·거절 채점 | - | LLM 없음. 두 판정자가 정한 정답 위치와 인용 청크를 코드로 대조 | `evals/latency/deploy_citation_gold.py` |
| RAGAS 채점 | - | 판정 `claude-haiku-5-5`, 임베딩 `voyage-4` | `evals/results/ragas_deploy_provena-api-00172-rex/summary.md` |

답 작성 모델은 같은 공급자의 Sonnet 5.5와 v2 관련 25건에서 비교했다. 인용 정확도는 0.931 대 0.938로 비슷하고 비용은 18.4배, p95는 9.776초 대 14.527초여서 Haiku를 쓴다(EVAL_REPORT 8장). 초기 배포판 `provena-api-00020`은 OpenRouter를 거쳐 같은 Haiku를 불렀다(8장 이력).

## 핵심 기능과 데모 구간

| 구간 | 보여주는 것 |
|---|---|
| 01 | 승인권자 질문: 외부 SaaS 금액 구간에 맞는 업무 승인·재무 승인 권한자와 근거 섹션·판 날짜 |
| 02 | 보안 검토·장애 대응 질문: 한국어 질문에 영어 핸드북 섹션을 인용한 답 |
| 03 | 답변 리콜: 정책 변경을 넣으면 그 섹션으로 답을 받은 사람과 업무시스템에 알림이 간다 |
| 04 | 결정표 승인: 승인 권한표를 결정표 초안으로 바꾸고, 사람이 승인한 뒤에만 판단에 쓴다 |
| 05 | 팀 합동 검토: 보안·인프라·IT 운영·재무 관점 쟁점표 (Supervisor + 팀 에이전트) |
| 06 | 거절: 근거가 없거나 비공개(internal) 문서, 고른 판 범위 밖 질문은 답하지 않는다 |

### 기존 제품과 다른 점

| 차별점 | Provena | 기존 제품 |
|---|---|---|
| 답변 리콜 | 바뀐 섹션을 근거로 **이미 나간 답을 받은 사람에게** 예전 답을 다시 검증해 알린다 | Guru·Glean·Notion은 검증 기한이 지난 문서를 문서 담당자·소유자에게 알린다. 답을 받은 사람에게 다시 알린다는 내용은 문서에서 찾지 못했다 |
| 결정표 승인 | 승인 권한표를 결정표로 바꾸고 **사람이 승인한 뒤에만** 판단에 쓴다. 금액 판단은 코드가 한다 | Moveworks·ServiceNow는 금액별 결재 흐름 엔진이 있다. 정책에서 뽑은 표를 사람이 승인한 뒤 답에 쓰는 단계는 문서 기준으로 찾지 못했다 |

"찾지 못했다"는 확인한 문서 기준(2026-10-28)이고, 없다고 증명한 것은 아니다. 범용 챗봇과 같은 질문으로 비교한 결과는 [EVAL_REPORT.md](./EVAL_REPORT.md) 10장에 있다.

**데이터.** GitLab이 회사 운영 문서로 공개한 핸드북(영어 Markdown, CC BY-SA 4.0)에서 IT·플랫폼 절을 고른다. 고정 커밋 `129243bc`(2026-10-27)에서 고른 1,564쪽과 2023 권한표, 문서 1,565건을 제목 단위로 잘라 청크 23,095개, 본문 sha256 기준 서로 다른 청크 22,378개다(`data/data.md`). 질문은 한국어로 하고 근거 문서는 영어여도 된다.

**만들지 않는 것:** 실제 회사 시스템(배포·구매) 연동, 회사 내부망 배포, GitLab 비공개(internal) 문서, 결재 상신.

## 배포 주소와 평가용 계정

배포 주소는 https://provena-api-cttaanqntq-du.a.run.app 이다. 상태 확인은 주소 뒤에 `/health`를 붙인 주소이다(`{"status":"ok"}`). 평가용 계정(일반 사용자 1개, 관리자 1개)의 아이디와 비밀번호는 **저장소에 적지 않고 DM으로 제출한다.**

1. 로그인 화면에서 DM으로 받은 **일반 사용자 계정**으로 로그인한다.
2. 질문을 입력한다. 예: "외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?"(데모 구간 01). 답에 붙은 인용 [1]을 열어 근거 섹션, 판 날짜, 출처와 라이선스 안내를 확인한다.
3. 핸드북 밖 질문(예: "오늘 점심 메뉴 추천해줘")을 보내 거절을 확인한다(데모 구간 06).
4. 사람 승인이 필요한 경로(결정표 변환, 팀 합동 검토)는 승인 대기에서 멈춘다. **관리자 계정**으로 로그인해 승인함에서 처리한다. 일반 계정이 승인 결정을 보내면 403이다.

이 서비스는 실제 LLM과 질문 임베딩 키로 동작하고 키는 서비스의 환경변수와 Secret Manager에만 있다.

## 실행 방법 (docker compose up)

평가자는 API 키가 없으므로 키 없이 뜨는 **데모 모드**가 기본이다. 필요한 것은 Docker(Compose v2)뿐이다.

```bash
git clone https://github.com/aihuman-7th/proj3-c.git
cd proj3-c
docker compose up          # .env 없이도 뜬다. 처음에는 이미지를 빌드해서 시간이 걸린다
```

Windows에서는 clone 전에 `git config --global core.longpaths true`를 한 번 실행한다(저장소에 경로가 긴 파일이 있어 깊은 폴더에 clone하면 `Filename too long`으로 체크아웃이 실패할 수 있다).

1. 브라우저에서 http://localhost:8000 을 연다(로그인 화면으로 이동한다). 상태 확인은 http://localhost:8000/health 이다.
2. **로컬 데모 계정**으로 로그인한다. 아이디는 `demo-user`(일반 사용자), `demo-admin`(관리자)이다. 비밀번호는 [.env.example](./.env.example)의 `DEMO_USER_PASSWORD`, `DEMO_ADMIN_PASSWORD` 값이다.
3. 가입 승인·사용자 관리 화면은 최고 관리자만 연다. 로컬에서 열려면 `docker compose up` 전에 `.env`에 `PROVENA_OWNER_LOGIN_ID=demo-admin`을 적는다(비우면 이 두 화면만 403).
4. 끝내려면 `docker compose down`, 데이터까지 지우려면 `docker compose down -v`. 8000번 포트를 이미 쓰고 있으면 `.env`에 `API_PORT=8001`처럼 적는다.

검색 색인은 `data/index.tar.gz` 한 파일로 저장소에 들어 있고, `docker compose up`을 하면 `loader` 서비스가 압축을 풀어 DB에 한 번 적재한 뒤 `api`가 뜬다. 색인이 없으면 서버는 뜨고 질문은 "검색 색인이 아직 준비되지 않아 답할 수 없습니다."라는 거절로 끝난다. 색인 다시 만들기와 압축 절차는 [data/data.md](./data/data.md)의 "검색 색인 스냅샷 쓰는 법"에 있다.

새 clone 실측: 2026-11-16 커밋 `c565998d`(`.env` 없음, 빌드 레이어 캐시 있음)에서 `docker compose up -d`부터 `/health` 200까지 70.4초, 데모 질문 9개는 기대와 9/9 일치, `python -m pytest -m demo_replay` 3 passed였다(`evals/results/fresh_clone_20261116b/`). 같은 날 커밋 `a374decb`에서 73.8초, 2026-11-13 빌드 캐시 없이 136.0초(`4c8d8bc`)와 272.8초(`d01eaff`)였다. 측정 조건과 증거는 [docs/GATES.md](./docs/GATES.md) G2에 있다.

### 키 없이 뜨는 데모 모드

- `DEMO_MODE=1`(기본)이면 LLM 키 없이 `data/demo_replay/`의 녹화 응답(LLM 응답과 질문 임베딩)을 재생한다. 키가 없으면 새 질문의 벡터를 만들 수 없으므로 **녹화한 질문만 키 없이 답이 나온다.** 녹화에 없는 질문은 "검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다."라는 거절로 끝난다. 다른 질문을 시험하려면 `.env`에 `LLM_API_KEY`와 `VOYAGE_API_KEY`를 넣고 `DEMO_MODE=0`으로 바꾼다(키는 `.env`에만 둔다).
- 녹화는 2026-11-16 14:15에 커밋 `e4e4f49b`의 코드로 질문 9개 전부를 새 DB에서 다시 떴고(`807bdf65`), 같은 날 10만 달러 질문만 문구를 바꿔 다시 녹화했다. 녹화가 현재 코드와 맞는지는 키·네트워크 없이 `python -m pytest -m demo_replay`로 확인한다(Docker와 pgvector 이미지 필요). 다시 녹화하는 절차와 이전 녹화 이력은 [data/data.md](./data/data.md)에 있다.
- 키 없이 인용 답이 나오는 질문(2026-11-16에 질문 9개 전부를 다시 녹화했고, `data/demo_replay/recorded.jsonl`). 글자가 같아야 한다(공백 차이는 무시). 재녹화 뒤 이 질문들의 결과는 위 설명과 일치한다.
  - 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?
  - CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?
  - 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?
  - EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?
  - 외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  - 외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  - 외부 SaaS 구매 비용이 10만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
    - 참고(질문 글자가 아님): 위 세 금액 질문은 데모 구간 01이다. 5만·3만 달러 질문은 승인 권한표 2023-05판의 `>$25K up to $50K` 행을 인용해 업무 승인자(Director)와 재무 승인자(PAO 또는 VP Finance)를 답한다. 10만 달러 질문은 같은 표의 `>$50K up to $250K` 행(Approving expense, 판 날짜 2023-05-11)을 인용해 업무 승인자(Sr Director)와 재무 승인자(PAO 또는 VP Finance, 승인·서명)를 답하고, 2023-05 고정 판 기준이라는 점과 계약 체결 전 법무 검토가 필요하다는 점을 덧붙인다. 이 질문은 2026-11-16에 권한표가 다루는 지출 승인 표현("구매 비용")으로 바꾸고 이 질문만 다시 녹화했다. 예전 질문("계약 금액 … 승인 권한자, 근거 섹션과 판 날짜")은 지출 승인 행을 계약에 적용할 근거가 없다는 판정으로 거절되었다. 이 설명을 질문 뒤에 붙여 보내면 다른 질문이라 녹화에 없어 거절된다.
- 키 없이 거절이 나오는 질문(녹화에도 거절): "구매 승인에는 어떤 승인자가 필요한가요?"(핸드북에 승인자 근거가 없다), "오늘 점심 메뉴 추천해줘"(범위 밖).
- 키 없이 재생하는 팀 합동 검토와 리콜(데모 구간 03, L-23 해소. 2026-11-16 녹화 `data/demo_replay/recorded_scenarios.jsonl`, 시나리오 `data/demo_replay/scenarios.json`):
  - 팀 합동 검토: `demo-user`로 다음 요청을 글자 그대로 보내면 Supervisor와 팀 에이전트 4개(보안·인프라·IT 운영·재무)의 검토가 녹화로 재생되고 쟁점표 승인 요청에서 멈춘다. `demo-admin`으로 승인함에서 승인하면 쟁점표가 저장된다. 요청: 외부 SaaS 로그 모니터링 도구를 연 4만 달러에 도입하려고 합니다. 업체와 제품 선정은 끝났고, 데이터는 미국 리전에 저장됩니다. 프로덕션 서비스 로그가 이 도구로 전송되고, 온콜 담당자가 알림을 받는 경로에도 들어갑니다. 합동 검토를 부탁합니다.
  - 리콜: `demo-user`로 위 5만·3만 달러 질문을 보낸 뒤, `demo-admin`으로 리콜 화면의 "처리 대기 변경 지금 처리"를 누르면 두 답의 리콜 알림 2건이 생긴다. 판정 확신도가 낮아(0.45) 두 알림은 관리자 검토함으로 가고, `demo-admin`이 내보내면 `demo-user`의 알림 목록에 보인다(2026-11-16 새 clone 확인, [evals/results/fresh_clone_20261116_demo_review_recall/](./evals/results/fresh_clone_20261116_demo_review_recall/)). 바뀐 섹션은 데모용 가상 개정 한 건이다(승인 권한표 2023-05판 `>$25K up to $50K` 행에서 업무 승인자 Director를 Sr Director로 바꾼 글, 새 판 날짜 2027-07-01, 실제 핸드북 문구 아님). 결론 재판정 설명은 녹화한 LLM 판정을 재생하고, 녹화에 없는 판정 요청은 규칙 판정으로 낸다. 가상 개정은 키 없는 로컬 데모(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`, LLM 키 없음)에서만 서버 시작 때 처리 대기로 들어가고(`backend/graph/recall/demo_change.py`), 리콜 저장소가 메모리(기본)이면 서버를 다시 띄울 때 다시 처리 대기가 된다. 처리 전에 물은 답만 대상이다.
  - 녹화가 현재 코드와 맞는지는 `python -m pytest -m demo_replay`의 `tests/test_demo_replay_scenarios.py`가 본다(검토는 승인 멈춤과 재개 뒤 저장까지, 리콜은 두 답 경로의 판정 요청이 모두 녹화에 있는지).
- 키 없는 데모에서 만들어지지 않는 것: 결정표 변환은 "예시 응답"이라고 표시된 고정 응답(`status=example`)을 내며 저장·승인되지 않는다. 녹화한 요청 밖의 합동 검토 요청은 다른 질문과 같이 녹화에 없어 처리되지 않는다.
- 규정 변경 웹훅(`POST /webhooks/regulation-updated`)은 `.env`의 `SERVICE_API_KEY`가 비면 항상 401이다. 키 없는 데모의 리콜은 위 가상 개정과 관리자 화면 버튼으로 본다. 웹훅으로 보려면 `.env`에 값을 넣고 요청 헤더 `X-Service-Key`에 같은 값을 보낸다.
- DB는 compose가 띄우는 로컬 pgvector 컨테이너이고 Supabase 계정이 필요 없다. 데모 전용 계정 2개는 `PROVENA_ENV=local`과 `PROVENA_DEV_MODE=1`이 모두 켜진 로컬 실행에서만 만들어지며, 배포 계정과 다르고 배포 계정 값은 저장소에 없다.

### 테스트

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
pytest -q
```

`tests/test_decision_approval.py`와 `tests/test_decision_multi_instance.py`는 임시 Postgres가 필요하다. 이미 떠 있는 DB를 쓰려면 `PROVENA_D5_PG_URL`(역할과 DB를 만들 수 있는 접속 문자열)을 지정한다. 지정하지 않으면 컨테이너 이름 `provena-d5-ckpt`로 새로 띄우므로 같은 이름의 컨테이너가 남아 있으면 오류가 난다.

### Cloud Run 재배포

배포 서비스는 Google Cloud Run의 `provena-api`(프로젝트 `provena-team`, 리전 `asia-northeast3`, 포트 8000)이고 소스 배포로 올린다.

```bash
gcloud run deploy provena-api --source . --project provena-team --region asia-northeast3 --port 8000 --allow-unauthenticated --max-instances 1
```

`--max-instances 1`을 올리기 전에 인스턴스 사이에서 공유되지 않는 기록(로그인 실패 제한 등)을 따로 확인한다. 플래그 설명, 배포 환경변수 표, Google 로그인 설정, 운영 DB 마이그레이션 순서는 [docs/specs/deploy.md](./docs/specs/deploy.md)에 있다. 값은 저장소에 적지 않는다.

## 구조

```
사용자 → FastAPI /chat → 질문 그래프 (LangGraph, Postgres 체크포인터)
  load_memory (사용자별 기억) → classify (질의 분석)
    ├ 정책 질문: rewrite → search (voyage-4 벡터, 링크 확장, 금액 구간 조회) → judge ─ 부족하면 rewrite로
    │           → write_answer → verify (인용 검사) → ground (근거 판정) → save
    ├ 결정표: 사람이 승인한 결정표만 실행 (decision_params → decision_run → decision_answer)
    ├ 팀 합동 검토: Supervisor + 팀 에이전트 4개 → 쟁점표 → 사람 승인 (interrupt)
    └ 도메인 밖: 거절
정책 변경 (규정 변경 웹훅) → 그 섹션을 인용한 답 재판정 → 받은 사람 알림 또는 관리자 검토함
```

- **왜 LangGraph인가.** 질문마다 다른 노드열로 가는 분기, 근거가 모자라면 상한을 두고 돌아가는 재검색, 사람이 승인할 때까지 멈췄다가 서버가 다시 떠도 같은 `thread_id`에서 이어지는 승인이 있어 상태를 가진 그래프로 만들었다. 그래프가 아닌 구현과 나란히 잰 값은 없다([docs/why_langgraph.md](./docs/why_langgraph.md)).
- **검색 방식 선택:** 하이브리드 검색(BM25+벡터)과 리랭커 4종을 같은 25문항으로 비교 측정했다. 기본 벡터 검색(`voyage-4`, 0.843)이 하이브리드(0.790)와 리랭커(0.817~0.837)보다 정확했고, 리랭커는 응답 시간 p95를 0.7초에서 최대 14.9초로 늘렸다. 그래서 벡터 검색에 질문 분해와 링크 확장을 더한 구성을 쓴다(EVAL_REPORT 3-2).

### 에이전트 구조와 한계

**왜 멀티에이전트인가.** 사내 요청 하나에는 보안·인프라·IT 운영·재무 검토가 함께 걸린다. 그래서 팀 에이전트 4개가 각자 자기 팀 절에서 규정을 찾아 검토하고, Supervisor가 결과를 쟁점표 하나로 합쳐 사람이 승인해야 저장되게 했다. **효과.** 같은 문항 90런 재측정(00049-nph)에서 정답 쟁점 누락률은 팀 합동 검토 0.577, 요청 그대로 한 번 찾는 1인 검토자 0.883으로 팀이 0.306 낮았다(3회 모두 같은 방향). 팀별로 찾은 자료를 한 번의 호출로 받는 1인 검토자는 0.586으로 팀과 차이가 없어(0.009), 효과는 호출을 팀으로 나눈 데서가 아니라 팀별로 나눠 찾는 검색에서 나온다. 비용은 런당 0.00403달러로 같은 자료를 받는 1인 검토자(0.00266달러)의 1.52배다. 두 1인 검토자는 같은 모델, 같은 쟁점 행 만들기와 인용 검사를 쓰는 평가 전용 기준선이고 승인함과 쟁점표 저장소에 연결돼 있지 않다(`backend/graph/departments/single_review.py`). **정책 질문 경로.** 일반 질문에 쓰는 멀티 그래프는 단일 그래프와 정확도 차이가 흔들림 안이었다(v2 50건 3회). 역할을 나눠도 정확도가 떨어지지 않았다.

| 항목 | 한 번에 찾는 1인 검토자 | 같은 자료를 받는 1인 검토자 | 팀 합동 검토(멀티) |
|---|---|---|---|
| 검색 | 요청 그대로 전체 코퍼스에서 한 번(40개) | 팀마다 팀 절에서 찾은 결과를 모아 한 번의 호출에 넣음 | 팀 에이전트 4개가 각자 팀 절에서 찾음 |
| 정답 쟁점 누락률(00049-nph) | 0.883 (13/111 찾음) | 0.586 (46/111) | 0.577 (47/111) |
| 런당 비용(00049-nph) | 0.00254달러 | 0.00266달러 | 0.00403달러 |
| 응답 시간 p95(00049-nph) | 10.305초 | 13.487초 | 11.554초 |
| 쟁점별 팀·근거 청크·판 날짜 | 있음 | 있음 | 있음 |
| 검토하지 못한 팀 표시 | 있음 | 있음 | 있음 |
| 사람 승인 뒤 저장 | 없음(평가 전용, 저장하지 않음) | 없음(평가 전용, 저장하지 않음) | 있음 |
| 장점 | 비용이 가장 낮고 p95가 가장 짧다 | 팀과 비슷한 누락률을 팀 비용의 1/1.52로 낸다 | 누락률이 가장 낮고, 서비스 경로로 승인과 저장까지 이어진다 |
| 단점 | 팀별 쟁점을 가장 많이 놓친다 | 팀별 검색은 그대로 필요하고 p95가 가장 길다 | 비용이 가장 높고, 같은 자료를 받는 1인 검토자보다 정확도 이득은 없다(0.009) |

값은 [EVAL_REPORT.md](./EVAL_REPORT.md) 4장 "합동 검토 같은 문항 재측정"(사전 등록 62.47, `evals/results/review_deploy_provena-api-00049-nph/`)과 4장 단일 대 멀티 표(v2 50건 3회, 로컬 실행기)에서 옮겼다. 세 방식 모두 같은 측정 리비전 `provena-api-00049-nph`에서 같은 10문항 x 3회를 쟀다. 정답 쟁점이 있는 표본은 문항 8개 x 3회이고 정답 쟁점은 2026-11-13에 조원 2명이 확인해 확정했다.

- 서비스(`/chat`)가 쓰는 그래프는 질문 그래프 하나이고, 팀 합동 검토가 그 안에 하위 그래프로 붙어 있다. 정책 질문 경로의 멀티 그래프(Supervisor와 검색·작성·검증 서브에이전트 3개, `backend/graph/multi.py`)는 단일 그래프와 같은 노드와 프롬프트를 Supervisor 아래에 다시 배선한 형태다.
- 공유하는 것과 다른 것, 상태 칸 제한과 시험은 [docs/why_langgraph.md](./docs/why_langgraph.md)의 "멀티 그래프의 범위와 한계", 노드별 설계 질문과 답은 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)에 있다.

**Supervisor를 코드로 둔 이유.** 경로를 가르는 판정은 질의 분석(`classify`, LLM 1회)이 하고, Supervisor의 라우팅은 그 결과를 읽는 코드다(결정 0055). 경로를 LLM이 정하게 한 비교(사전 등록 #48)에서 LLM이 경로를 정한 59번이 모두 코드와 달랐고(코드는 모두 검색, LLM은 거절로 닫기 53번과 작성 6번) 정답 근거 인용률이 낮아져 코드 라우팅을 유지했다(결정 0063). LLM 라우팅은 스위치로만 남아 있고 기본은 꺼져 있다.

**잘못 나뉘는 입력(측정으로 확인된 것만).** 잘못 나뉘는 입력은 `classify`가 질문 종류를 틀리게 낸 입력이다.

| 입력 | 잘못 간 경로 | 조치 |
|---|---|---|
| v2 7·15·38번(정책 문서에 답이 있는 사실 질문) | 7·38번은 합동 검토(`review`), 15번은 결정표(`decision`) | 금액이 없으면 결정표로, 사실을 묻는 질문은 합동 검토로 보내지 않는 코드 규칙. 수정 뒤 단일·멀티 340행에서 `review`·`decision` 0행 |
| v1 3번(릴리스 주기) | 일부 회차 도메인 밖(`out_of_domain`)으로 검색 없이 거절 | 같은 분류가 두 번 나올 때만 도메인 밖을 따르고 갈리면 정책 경로로 보냄 |
| 검증 109번(데이터팀 dbt SQL 스타일) | 두 번 모두 도메인 밖 | 도메인 밖 기준을 "답이 이 조직과 무관하게 정해지는가"로 바꿈(결정 0097). 이 문항을 보고 만든 수정이라 효과 판단에서 뺐다 |
| 키 없는 데모의 "보안 검토가 필요한가요?" | 합동 검토(승인 대기) | 필요·의무 여부를 묻고 검토 요청이 없으면 정책 경로로 보냄(결정 0102) |
| 외부 SaaS 금액 승인자 질문 15건 | 결정표에서 업무 종류를 못 찾아 거절 | 업무 종류를 못 찾으면 정책 경로로 보냄(PR #97) |

반대 방향(합동 검토나 결정표로 가야 할 질문이 정책 경로로 가는 경우)은 재는 평가셋이 없어 비율을 모른다. 근거 파일과 수정 전후 값은 [docs/why_langgraph.md](./docs/why_langgraph.md) "Supervisor가 잘못 나눌 수 있는 입력", [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) "Supervisor가 잘못 나누는 입력"에 있다.

**멀티에이전트 최소형 요건을 채우는 곳: 팀 합동 검토.** 서비스 경로에서 Supervisor와 서브에이전트가 실제로 나뉘어 도는 곳은 합동 검토 하위 그래프(`backend/graph/departments/review.py`의 `build_review_graph`)다.

| 요건 | 합동 검토에서의 구현 |
|---|---|
| 입력별 라우팅 | 질의 분석이 `review`로 나눈 요청만 이 하위 그래프로 간다. Supervisor(LLM 1회)는 요청을 팀마다 볼 것(`tasks`)으로 나누고, 판단에 필요한 값이 빠졌으면 팀을 돌리지 않고 되묻는다(`review_status=clarify`) |
| 서브에이전트별 프롬프트 | Supervisor 프롬프트 `SUPERVISOR_SYSTEM`과 팀마다 다른 팀 프롬프트 `team_system`(팀 이름과 팀 Skill `skills/security`·`infra`·`itops`·`finance`의 본문을 붙임, `backend/graph/departments/teams.py`) |
| 서브에이전트별 검색 범위 | 팀 4개가 각자 자기 코퍼스 절(`Chunk.org`: `security`, `infra`, `business-technology`, `finance`)에서만 찾는다(`teams.py`의 `TEAMS`) |
| 상태 | 하위 그래프 상태 `ReviewState`(요청, 팀별 결과 `team_results`, 실패한 팀, 합친 쟁점표, 승인 건). 팀 결과는 팀 id별로 합쳐지고, 실패한 팀만 다시 돌릴 수 있다. 쟁점표는 `interrupt()`로 사람 승인 뒤에만 저장된다 |

효과는 위 표의 누락률(팀 0.577 대 요청 그대로 한 번 찾는 1인 검토자 0.883)이다. 정책 질문 경로의 멀티 그래프는 단일 그래프와 차이가 없다: 사전 등록 61.51의 v2 50건 3회 평균에서 정답 근거 인용률 단일 0.996·멀티 0.991, 인용 정확도 단일 1.000·멀티 0.992로 같은 조건 3회의 흔들림 안이고, 비용은 멀티가 단일의 0.96배다([EVAL_REPORT.md](./EVAL_REPORT.md) 4장 "단일 대 멀티 해석"). `/chat`의 정책 질문은 단일 그래프로 돌고, 멀티 그래프는 측정과 시험에서만 쓴다.

### 폴더

| 폴더 | 내용 |
|---|---|
| `backend/` | FastAPI 서버, 로그인, 질문 그래프와 팀 에이전트·결정표·리콜(`graph/`), 수집·파싱·청킹(`rag/ingest/`), 검색(`rag/retrieve/`), 사용자별 기억(`memory/`), LLM 호출(`services/llm.py`) |
| `web/` | 화면 |
| `data/` | 핸드북 원문 스냅샷, manifest, 검색 색인, 키 없는 데모 녹화, `LICENSES/` |
| `evals/` | 평가셋(v1·v2·검증), 동결 해시, 사전 등록, 평가 실행기, 원시 결과(`results/`) |
| `tests/` | 회귀 테스트 (CI가 PR마다 실행) |
| `skills/`, `extras/mcp_skill/` | 런타임 Skill, FastMCP 서버와 MCP 클라이언트 (가산). `/mcp/` 토큰은 서비스 내부용 `MCP_TOKEN`(제한 없음)과 외부 클라이언트용 `MCP_EXTERNAL_TOKEN`(분당 30회·하루 500회, 넘으면 429)으로 나뉜다([docs/specs/mcp.md](./docs/specs/mcp.md)) |
| `mock_erp/`, `db/`, `docs/` | 업무시스템 목업, DB 스키마, 문서 |

## 알려진 한계

- **v2 값은 낙관적일 수 있다.** 코드 수정이 v2 실패 문항에서 출발했고, 38번 정답은 판정자 확인을 거쳐 동결 뒤에 고쳤다(결정 0075, 0087). 일반화는 검증 20건 0.911(정답 근거 인용률 0.900)과 측정 전에 등록한 새 검증 20건(501~520번) 0.661(정답 근거 인용률 0.857, 둘 다 운영 판 00172-rex 측정), 새 인용 5건 0.933(00065-q84, 이후 판 미측정)으로 읽는다. [EVAL_REPORT.md](./EVAL_REPORT.md) 2장, 5-4절
- **검증 20건 값도 처음 보는 문항의 값이 아니다.** 101·104·105·109번의 실패를 분석해 고친 뒤 0.772 → 0.917이 되었으므로, 처음 보는 문항으로 다시 재야 일반화 값이 된다(결정 0113). 처음 보는 문항으로 잰 값은 위 표의 새 검증 20건(501~520번) 행이다. EVAL_REPORT 2장
- **사전 등록 순서는 62.63부터만 커밋으로 입증된다.** 62.63부터는 예측을 결과보다 먼저 별도 커밋으로 올렸고, 그 이전 행은 순서를 커밋으로 입증하지 못한다. EVAL_REPORT 3장 "사전 등록의 커밋 순서(한계)", [evals/PREREGISTER.md](./evals/PREREGISTER.md)
- **감점 문항이 남아 있다.** 동결 판 00172-rex에서 v2 38·39번, 검증 101·108·109번(정답 밖 인용 행), 새 검증 504·505·507·511·513·515·517번이다. 38·101번은 첫 검색에서 정답 절이 문맥에 들지 않는 검색 실패로 확인했고, 한 문항만 맞추는 규칙은 넣지 않았다. EVAL_REPORT 5-5절, [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md)
- **응답 시간.** 동결 판 00172-rex의 v2 50건 전체 p95는 회차별 평균 8.264초(3회 합 8.223초), 답한 질문만의 p95는 3회 합 8.385초(회차별 평균 8.623초)이다(직전 운영 판 00150-jub은 9.185초, 10.354초). 검증 20건의 전체 p95는 회차별 평균 8.543초(3회 합 8.483초, 답한 질문만 3회 합 8.734초), 새 검증 20건은 9.589초(3회 합 9.941초, 답한 질문만 3회 합 11.323초, 회차별 평균 12.206초)이다. 같은 이미지·설정의 앞선 측정 00165-kag(20:29~21:00)에서는 검증 20건 10.698초, 새 검증 20건 11.505초였다. EVAL_REPORT 8장
- **인젝션 방어 규칙은 알려진 범주를 잡는다.** 규칙으로 막지 못하는 변형은 모델 판단과 근거 확인에 기대며, 세부 사례는 공개하지 않는다. 운영 코퍼스에 시험 문서를 심은 값 바꾸기 시험 3건은 동결 코드 `194dfd9a`의 서비스 판 `provena-api-00178-max`에서 2026-11-17 01:34 KST에 3건 모두 막혔고 3건 모두 시험 청크가 인용되어 실제로 시험됐다(비용 0.013768달러, 끝난 뒤 시험 행 0, `evals/results/injection_corpus_valueflip_provena-api-00178-max/`). EVAL_REPORT 6장
- **운영 추적 기록에 빈 구간이 있다.** 2026-11-16 19:28~20:52 KST 운영 Langfuse 적재가 멈췄다(조직 사용량 한도 초과로 수집 중단). 새 조직·프로젝트 키로 바꿔 20:52 KST에 같은 이미지·설정의 운영 판 `provena-api-00166-mob`에 반영했고, 21:38 KST부터 서비스하는 `provena-api-00172-rex`도 새 키를 쓴다(21:51 확인: 요청 1건 정상, Langfuse 트레이스 3건·관측 66건, 권한 오류·내보내기 오류·5xx 0건). [docs/GATES.md](./docs/GATES.md) G1
- **CI 회귀 검사는 녹화 재생이라 답·거절 수만 본다.** CI는 데모 질문 9개와 평가셋 v2 50건 녹화(`evals/ci_replay_v2/`, `--require-v2`)를 현재 코드로 키 없이 재생해 인용 답·거절 수와 녹화에 없는 요청 수를 기준과 견준다(50건 기준: 관련 25건 중 인용 답 24, 비관련 25건 중 거절 24, 녹화에 없는 요청 0). 정답 근거 인용률·인용 정확도 같은 50건 채점 값은 CI가 아니라 운영 배포 측정으로 확인했다. EVAL_REPORT 8장, [docs/GATES.md](./docs/GATES.md) G5
- **한 배포에 묶어 넣은 수정은 일부만 효과를 갈랐다.** 한 변수만 바꾼 운영 비교는 Skill 켬·끔(62.75)과 GraphRAG 켬·끔(62.76)이고, 62.44와 62.45는 닿는 문항이 겹치지 않아 문항 범위로 나눴다. 그 밖의 장치는 2026-11-16에 장치 하나만 끈 운영 판 11개로 v2 50건을 1회씩 쟀다: 끈 판이 기준보다 낮게 나와 몫이 갈린 장치는 인용 추가 가드(62.70), 인용 더하기 좁히기(62.56), 표 행 줄 전체 일치(62.57)이고, 나머지 8개는 차이가 한 문항 안팎이라 1회로는 몫을 확정하지 못했다. 결정 0126(대상·조건 유지 끔)과 0127(분류 동시 요청)은 판 전체로만 쟀다. EVAL_REPORT 5-4절, 11장
- **재지 않은 지표가 있다.** 답변 리콜의 재현율·정밀도와 결정표 셀 정확도는 미측정이다. 측정하지 않은 항목 전체는 [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md) 5장. [docs/SPEC.md](./docs/SPEC.md) 3장
- **제출 전 점검(2026-11-17).** 최종 main `47e3b82a` 새 clone에서 키 없이 `/health` 200까지 63.2초, README 질문 9개 9/9, `pytest -m demo_replay` 6 passed(`evals/results/fresh_clone_20261117/`). 최종 main `3dbc36ca` 전체 이력 gitleaks 검출 0건(`evals/results/gitleaks_20261117/`). [docs/GATES.md](./docs/GATES.md) G2, G7
- **키 없는 데모는 녹화한 질문만 답한다.** 합동 검토와 리콜도 녹화한 요청 한 건과 데모용 가상 개정 한 건만 키 없이 재생한다(2026-11-16, L-23 해소). 위 "키 없이 뜨는 데모 모드"
- 가장 큰 약점에 대한 팀의 판단은 EVAL_REPORT 11장에 있다.

## 문서 안내

| 문서 | 내용 |
|---|---|
| [EVAL_REPORT.md](./EVAL_REPORT.md) | 평가 리포트: 코퍼스, 평가셋, 검색 개선 전후, 단일 대 멀티, 실패 유형, 신뢰 경계, 비용과 단계별 응답 시간, 재현 명령, 대체재 비교, 가장 큰 약점 |
| [docs/GATES.md](./docs/GATES.md) | 필수 게이트 G1~G7 자기 점검과 증거 |
| [docs/SPEC.md](./docs/SPEC.md) | 정본 문서: 범위, 숫자 기준과 지표별 결과 이력, 데모 모드 |
| [docs/PRD.md](./docs/PRD.md), [docs/deliverables/survey/](./docs/deliverables/survey/responses_summary.md) | 문제, 페르소나, 대체재, 요구 사항, 현직자 설문 |
| [docs/SDD.md](./docs/SDD.md) | 설계 문서 |
| [docs/GRAPH.md](./docs/GRAPH.md) | 그래프별 노드 책임, 읽고 쓰는 상태 키, 분기 조건, 중단·재개, 경로를 바꾸는 설정 스위치 |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md), [docs/why_langgraph.md](./docs/why_langgraph.md) | 요청 흐름, 설계 질문과 답, 그래프로 만든 이유, 멀티 그래프의 범위와 한계 |
| [docs/decisions.md](./docs/decisions.md) | 결정 기록 |
| [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md) | 실패 사례 분석 |
| [evals/README.md](./evals/README.md), [evals/PREREGISTER.md](./evals/PREREGISTER.md) | 평가셋 동결 규칙과 재현, 사전 등록 |
| [docs/specs/deploy.md](./docs/specs/deploy.md) | 배포·실행 모드, 환경변수, 운영 재배포, Google 로그인 설정 |
| [docs/embedding_measurement.md](./docs/embedding_measurement.md) | 임베딩 측정 기록 |
| [docs/TEAM_GUIDE.md](./docs/TEAM_GUIDE.md) | 팀 작업 지침서: 일정, 역할, 협업 규칙, 폴더 주인 |
| [AGENTS.md](./AGENTS.md) | AI 코딩 도구 규칙 |

## 데이터 출처와 라이선스

시연 데이터는 GitLab이 공개한 핸드북(https://handbook.gitlab.com, 소스 https://gitlab.com/gitlab-com/content-sites/handbook)이다. 핸드북 본문은 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)으로 공개되어 있고, 이 저장소의 원문 스냅샷은 `data/` 아래에 코드와 폴더를 나눠 두며 고지와 출처는 `data/LICENSES/`에 있다. 답에 원문을 보일 때는 페이지 URL, 라이선스, 수정 여부를 함께 표시한다.

**이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다.** GitLab 로고를 쓰지 않으며 "GitLab 핸드북 기반 데모"라는 사실만 밝힌다.

## 조원 소개

| 이름 | GitHub | 역할 | 맡는 축 | 한마디 |
|---|---|---|---|---|
| 김승욱(팀장) | [@seungwook-kim](https://github.com/seungwook-kim) | 테크 리드 · 풀스택 | ③ 에이전트 | |
| 강경희 | [@kkh-hue](https://github.com/kkh-hue) | 서비스 (로그인·웹 화면·첫 배포) 담당 | 서비스 개발 | 잘 부탁드립니다. |
| 박진형 | [@jinyeong-731](https://github.com/jinyeong-731) | 검색·데이터 (수집·파싱·청킹·검색·FastMCP) 담당 | ② RAG 품질 | 잘 부탁드립니다. |

행을 고칠 때는 자기 행만 브랜치 → PR → 리뷰 → merge로 고친다. 협업 규칙(브랜치, PR 승인, 제출 기준)은 [docs/TEAM_GUIDE.md](./docs/TEAM_GUIDE.md) 4장과 5장에 있다.

## 비밀값 규칙

- 키는 `.env`와 Secret Manager에만 둔다. `.env`는 `.gitignore`에 등록되어 커밋되지 않고, 필요한 키 목록은 `.env.example`에 값 없이 적는다.
- 평가용 계정 값은 저장소에 없다.
- push마다 Secret Scan(GitHub Actions)이 검사한다.
