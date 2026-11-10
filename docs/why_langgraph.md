# 왜 LangGraph 그래프로 만들었는가

이 문서는 질문 처리를 함수 호출 순서(단순 체인)가 아니라 상태를 가진 LangGraph 그래프로 만든 이유를 적는다. 가이드의 필수 조건 G4가 "LangGraph 상태 그래프, 체크포인트, 사람 승인(interrupt)"을 요구하므로 선택의 여지가 없던 부분이 있다. 아래는 그 요구를 빼고도 이 서비스에서 그래프가 필요한 이유를 서비스의 동작에서 찾아 적은 것이다. 그래프가 아닌 구현과 나란히 잰 값은 없으며, 그래서 "그래프가 더 낫다"는 측정 결론은 없다. 각 항목의 근거는 코드, 시험, 측정 파일로 적었다.

## 한 줄 요약

사람이 승인할 때까지 멈췄다가 서버가 다시 떠도 같은 대화(`thread_id`)에서 이어져야 하는 경로가 있고, 질문마다 가는 길이 갈리며, 근거가 모자라면 상한을 두고 되돌아가는 단계가 있다. 이 셋을 한 곳에서 상태로 다루려고 그래프를 썼다.

## 그래프가 맡은 일

| 필요 | 그래프에서 하는 방식 | 코드 | 단순 체인이었다면 |
|---|---|---|---|
| 질문마다 다른 길 | 질의 분석(`classify`, LLM 1회)이 질문을 정책 질문, 결정표, 팀 합동 검토, 도메인 밖 거절로 나눠 서로 다른 노드열로 보낸다 | `backend/graph/build.py`의 `classify` 분기, 연결은 결정 0064 | `if` 분기로 쓸 수 있다. 그래프 없이도 되는 부분이다 |
| 근거가 모자라면 되돌아감 | 근거 충분 판정(`judge`)이 부족이라 하면 재작성과 재검색으로 돌아가고, 상한(`MAX_RESEARCH` 2, 서비스 기본값 1)을 넘으면 `give_up`으로 거절이나 되묻기로 닫는다 | `build.py`의 재검색 분기 | `while` 반복으로 쓸 수 있다. 상한 변경을 잡는 시험은 그래프 노드 단위로 쓰기 쉽다(`docs/GATES.md`의 변이 확인 표 1번) |
| 사람 승인에서 멈춤 | 결정표 초안과 합동 검토 쟁점표는 `interrupt()`에서 멈추고, 승인 API가 같은 `thread_id`로 `Command(resume=...)`를 넘기면 멈춘 자리부터 이어진다 | `backend/graph/decision/convert.py`, `backend/graph/departments/review.py` | 대기 상태와 재개 위치를 직접 저장하고 읽는 코드가 필요하다. 이 서비스에서 그래프의 이득이 가장 큰 부분이다 |
| 서버 재시작 뒤 이어받기 | 체크포인터가 노드를 지날 때마다 `thread_id`별 상태를 Postgres에 쓴다 | `backend/graph/checkpoint.py` | 상태 직렬화, 표, 재개 시 중복 실행 방지를 직접 만들어야 한다 |
| 사용자별 기억 | 대화 안의 값은 State, 다음 대화에도 쓸 값(소속, 직급)은 사용자별 Store에 둔다 | `backend/graph/state.py`, `backend/memory/profile.py` | 별도 저장소 코드가 필요하다 |
| 단계별 추적 | 노드가 단위라 Langfuse 트레이스에 그래프 단계별 시간과 비용이 남는다 | `backend/services/tracing.py`, `EVAL_REPORT.md` 7장 | 단계마다 직접 기록해야 한다 |

노드마다 맡은 일은 다음과 같다(`backend/graph/build.py`의 `build_graph`, 간선은 같은 파일 끝의 `add_edge`, `add_conditional_edges`).

| 노드 | 책임 | 다음 노드 |
|---|---|---|
| `load_memory` | 로그인한 사용자의 Store에서 소속·직급을 읽어 State에 둔다 | `classify` |
| `classify` | 질문 종류 판정(LLM 1회, 도메인 밖이면 확인 1회 더)과 판정 뒤 코드 되돌림(금액 없는 결정표 질문, 사실을 묻는 합동 검토 질문, `org_specific`가 참인 도메인 밖 응답은 정책 질문으로 보냄) | `rewrite`, `decision_params`, `review`, `out_of_domain` |
| `rewrite` | 질의 재작성과 분해. 판정이 고른 섹션 읽기나 빠진 하위 질문 재검색이면 LLM을 부르지 않는다 | `search` |
| `search` | 검색(`search()`). 검색 오류면 끝낸다 | `judge` 또는 끝 |
| `judge` | 근거 충분 판정. 자료가 없으면 LLM 없이 부족으로 본다 | `write_answer`, `rewrite`(상한 안), `give_up` |
| `write_answer` | 인용을 단 답 작성 | `verify` |
| `verify` | 코드로 인용 검사와 출력 검사(내부 문구 유출, 검색 원문의 지시 문장) | `ground` 또는 끝(거절) |
| `ground` | 답 문장이 인용한 청크에 받쳐지는지 판정 | `save` 또는 끝(거절) |
| `save` | 답과 인용을 저장한다 | 끝 |
| `give_up` | 재검색 상한을 넘기면 거절이나 되묻기로 닫는다 | 끝 |
| `out_of_domain` | 검색 없이 도메인 밖 거절 | 끝 |
| `decision_params`, `decision_run`, `decision_answer` | 결정표 경로: 업무 종류와 금액 뽑기, 승인된 결정표 실행(코드), 실행 결과를 코드로 답으로 쓰기 | 끝 |
| `review` | 합동 검토 하위 그래프(`backend/graph/departments/review.py`): Supervisor, 팀 에이전트 4개, 쟁점표 합치기, 사람 승인 `interrupt` | 끝(승인 대기에서 멈춤) |

## 상태 저장과 재개

저장. LangGraph 체크포인터가 노드를 지날 때마다 질문, 청크(직렬화를 피하려 dict), 판정, 초안 답, 승인 대기 값을 `thread_id`별로 Postgres 표(`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`)에 쓴다. 이 표에는 대화 내용이 들어가므로 만든 직후 RLS를 켠다. 메모리 체크포인터는 시험과 로컬 개발용이며 프로세스가 끝나면 사라진다. `is_restart_safe()`가 거짓이고, 재시작에서 살아남지 못함을 시험으로 보인다(`tests/test_decision_approval.py`의 `test_memory_checkpointer_is_not_restart_safe`).

재개. 승인 API가 같은 `thread_id`로 재개를 넘기면 `interrupt()`가 멈춘 노드가 처음부터 다시 돈다. 그래서 `interrupt()`가 있는 노드에는 다른 일을 넣지 않고, 쓰기는 앞뒤 노드(`queue_approval`, `finalize`)로 나눴으며 둘 다 같은 입력으로 다시 돌아도 결과가 같다. 같은 승인 건에 결정이 겹쳐 오면 프로세스 안 잠금과 Postgres 자문 잠금(`PostgresDecisionRepo.decision_lock`)이 하나씩 처리한다.

확인한 것은 다음 세 단계다.

| 확인 | 내용 | 근거 |
|---|---|---|
| 시험용 Postgres, 프로세스 분리 | 시작해 승인 대기에서 멈춤, 프로세스 종료, 새 프로세스에서 같은 `thread_id`로 재개. 승인과 반려 모두 시험하고 재개 때 초안을 다시 쓰지 않는지도 본다 | `tests/test_decision_approval.py`, `tests/decision_restart_worker.py` |
| 운영 DB와 Cloud Run, 2026-11-09 | 이전 리비전이 만든 합동 검토 쟁점표 승인 대기 1건을 새 리비전 `provena-api-00029-qbd`에서 승인하자 체크포인트에서 이어져 쟁점표 18행이 저장됐다 | `EVAL_REPORT.md` 4장 체크포인트 행 |
| 운영 서비스 재배포, 2026-11-10 | 리비전 `provena-api-00031-dhq`에서 승인 대기 3건(쟁점표 승인용, 쟁점표 반려용, 결정표 승인용)을 만들고, 재배포한 `provena-api-00032-zhs`(커밋 `5d6a2fe`)에서 3건을 처리했다. 3건 모두 통과했다 | `evals/results/d7_restart_provena-api-00032-zhs/restart_resume.json`, 실행기 `evals/safety/deploy_restart_resume_check.py` |
| 운영 서비스 재배포, 2026-11-11 | 재시작 전 리비전 `provena-api-00034-tkx`에서 만든 승인 대기 3건을 재배포한 `provena-api-00035-h69`(커밋 `b2bc434`)에서 처리했다. 3건 모두 통과했고 R1~R9가 모두 참이었다(문제 0개, 상태 완전, 승인함 대기 복원, 승인·반려·번복 409·반복 같은 결과) | `evals/results/d7_restart_provena-api-00035-h69/restart_resume.json`, 실행기 `evals/safety/deploy_restart_resume_check.py` |

2026-11-10 확인의 세부는 다음과 같다. 대기 건은 05:55 UTC(+09:00 14:55)에 만들었고 재개는 06:20 UTC에 시작해 4.5초 안에 끝났다. 재시작 뒤에도 3건이 승인함 목록에 있었고, 쟁점표 승인 건은 18행, 반려 건은 20행, 결정표 건은 2행이 준비 때와 같게 복원됐다. 대기 중인 대화에 새 질문을 보내면 409, 일반 계정이 결정을 보내면 403이었다. 관리자의 승인은 200이고 상태가 `approved`(승인), `rejected`(반려)로 바뀌어 승인한 쟁점표는 18행, 승인한 결정표는 2행이 저장됐고 반려한 건은 저장이 0이었다. 같은 결정을 다시 보내면 200(같은 상태), 반대 결정은 409였고, 재요청 뒤 대화 답의 개수와 승인된 결정표 수는 늘지 않았다. 증거 파일에는 승인 번호, 대화 번호, 사용자 식별자, 아이디가 없다.

한계. 이 확인은 응답 코드, 승인함 목록, 대화 답, 승인된 표 목록으로 판정한 것이다. 그래프가 몇 번 재개됐는지는 API로 볼 수 없고 배포 로그 권한이 없어 세지 못했다. 배포는 인스턴스 1개(`--max-instances 1`)라 인스턴스가 2개 이상일 때의 동시 재개는 배포 서비스에서 확인하지 못했다(로컬에서 서버 프로세스 2개로 재현하고 고친 기록은 `EVAL_REPORT.md` 6장 21행). 팀 실패 알림(`team_review_failed`)에서 멈춘 건의 재시작 뒤 재개는 확인하지 못했다.

## 그래프를 쓴 대가

- 노드 함수가 `build_graph` 안의 클로저라 다른 파일에서 import할 수 없다. 멀티 그래프(`backend/graph/multi.py`)는 컴파일된 그래프의 `builder`를 읽어 노드를 꺼내 쓰므로 LangGraph 버전(1.2.x)에 묶여 있고, 읽을 수 없으면 조용히 다르게 돌지 않고 멈춘다.
- 체크포인트에 넣는 값은 직렬화할 수 있어야 해서 청크를 dict로 둔다. 재개하면 멈춘 노드가 처음부터 다시 돌기 때문에 쓰기 위치에 규칙이 생긴다(위 "재개").
- 체크포인트 표에 대화 내용이 남는다. RLS를 켜고 정책을 두지 않아 공개 키 역할은 막고 앱만 쓴다.
- 그래프가 아닌 구현과 같은 질문으로 정확도나 응답 시간을 나란히 잰 값은 없다. 이 문서의 이유는 구조와 동작에 관한 것이고 성능 비교가 아니다.

## Supervisor가 잘못 나눌 수 있는 입력

경로를 가르는 판정은 질의 분석(`classify`, LLM 1회)이고 Supervisor의 라우팅은 그 결과를 읽는 코드이다(결정 0055). 그래서 잘못 나뉘는 입력은 `classify`가 질문 종류를 틀리게 낸 입력이다. 아래는 저장소의 결과 파일과 녹화 파일로 확인된 사례만 적은 것이다(2026-11-11 기준). 수치는 근거 파일의 행을 직접 센 값이다. 이전 판의 근거와 시험 이름은 [EVAL_REPORT.md](../EVAL_REPORT.md) 4장 "Supervisor가 잘못 나눌 수 있는 입력"과 [ARCHITECTURE.md](./ARCHITECTURE.md)의 "Supervisor가 잘못 나누는 입력"에도 있다.

| 입력 유형 | 예시(평가셋 문항) | 잘못 간 경로 | 올바른 경로 | 발견 근거 파일 | 조치와 수정 전후 | 남은 오분류 |
|---|---|---|---|---|---|---|
| 정책 문서에 답이 있는 사실 질문이 합동 검토나 결정표로 감 | v2 7번(별도 DB·마이크로서비스 도입 승인), 15번(클라우드 약정 할인 계약은 누가 승인하나), 38번(새 SaaS 도구 요청과 TPRM 시점) | `review`(7, 38번), `decision`(15번) | 정책 질문(`rule`) | `evals/results/agent_v2_multi_pg/`, `_r2/`, `_r3/`의 `single/rows.jsonl`, `multi/rows.jsonl` `route` 칸 | 금액이 없으면 결정표로 보내지 않고, 의문사로 묻고 "검토"라는 말이 없으면 합동 검토로 보내지 않는 코드 되돌림을 `classify`에 넣었다(결정 2026-11-02 "질의 라우팅은 분류 결과를 남기고…"). 수정 뒤 `agent_v2_q_d6151_r1/r2/r3/h1_bo2sda2_api`의 단일·멀티 340행에서 `review`, `decision` 0행 | 모델의 분류 응답은 지금도 15번을 3회 중 3회 `decision`으로 낸다(`evals/results/classify_overrefuse_62_30/rows.jsonl`). 금액이 없어 코드가 정책 경로로 보내고, 배포본 `provena-api-00035-h69` v2 3회에서 15번은 3회 모두 답이 나왔다(`evals/results/deploy_latency_provena-api-00035-h69/`) |
| 정책에 답이 있는 질문이 도메인 밖으로 감(흔들림) | v1 3번(정기·패치 릴리스 주기) | `out_of_domain`(일부 회차, 검색 없이 거절) | 정책 질문 | `evals/results/agent_v1_final_asof_r2/`, `agent_v1_final_ground_r2/`, `agent_v1_service_pg_r3/`의 `rows.jsonl` | 같은 분류가 두 번 나올 때만 도메인 밖을 따르고, 갈리면 정책 경로로 보낸다. 시험 `tests/test_question_graph.py`의 `test_out_of_domain_needs_two_same_answers_and_a_split_goes_to_policy_path` | 아래 행처럼 두 번 다 틀리는 경우는 이 규칙으로 막지 못한다 |
| 조직이 정한 지침을 묻는 기술 질문이 도메인 밖으로 감(기준 오류) | 검증 109번(데이터팀 dbt 모델 SQL 서브쿼리와 팀 스타일 가이드) | `out_of_domain`(두 번 확인을 통과해 검색 없이 거절) | 정책 질문 | `agent_v2_q_d6151_h1_bo2sda2_api` 단일·멀티 2행 모두 `out_of_domain`. 배포 `provena-api-00032-zhs` 3회 모두 거절(사전 등록 62.30 원인 칸) | 도메인 밖 기준을 주제에서 "답이 이 조직과 무관하게 정해지는가"로 바꾸고 `org_specific`가 참이면 정책 경로로 보낸다(결정 0097, 사전 등록 62.30). 분류만 부르는 확인 3회(84문항 252행, `classify_overrefuse_62_30`): 관련 43문항 129행의 도메인 밖 0행, 평가셋에 없는 사내 규정형 기술 질문 5문항(`evals/overrefuse_probe_v1.jsonl`) 15행도 0행, 109번 3행 0행. 배포 `provena-api-00035-h69` 검증 20건 3회에서 관련 문항 거절은 101번 2행(근거 판정 단계)뿐이고 109번은 3회 모두 답이 나왔다(`evals/results/deploy_latency_holdout_provena-api-00035-h69/`) | 109번은 이 수정을 만들 때 본 문항이라 효과 판단에서 뺐다. 일반 지식만 묻는 13문항 39행은 수정 뒤에도 39행 모두 도메인 밖으로 거절됐다(기준 0.90 이상 통과) |
| 규정상 필요 여부를 예·아니오로 묻는 질문이 합동 검토로 감 | 키 없는 데모 질문 "제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?" | `review`(인용 답 대신 승인 대기) | 정책 질문 | 데모 녹화 `data/demo_replay/recorded.jsonl`의 분류 응답(2026-11-09 녹화는 `rule`, 2026-11-10 녹화는 `review`). 사전 등록 62.34 원인 칸 | 필요·의무 여부를 묻는 말로 끝나고 검토를 해 달라는 말이 없으면 정책 경로로 보낸다(`asks_fact_not_review`, 결정 0102, 사전 등록 62.34). 평가셋과 겹치지 않는 필요 여부 질문 4문항(`evals/review_probe_v1.jsonl`) 12행의 `review` 0행(`classify_overrefuse_62_30`) | 데모 질문의 모델 분류 응답은 지금 녹화에서도 `review`이고 코드 되돌림이 정책 경로로 보낸다. 안건을 적고 필요 여부만 묻는 글("~하려 한다. 검토가 필요한가?")은 검토 요청이어도 정책 답으로 간다(62.34에 적은 대가) |
| 외부 SaaS 도입 금액 승인자 질문이 결정표로 가서 거절됨 | 금액 구간 질문 5종 x 3회 15건(예: 연 5만 달러 SaaS 도입 승인자) | `decision`(결정표 값 뽑기가 업무 종류를 찾지 못해 거절) | 정책 질문(금액 구간 검색) | 리비전 `provena-api-00029-qbd`에서 15건 모두 "결정표를 실행하지 않았습니다"(EVAL_REPORT.md 5-4절) | 업무 종류를 못 찾으면 거절하지 않고 `rule`로 보낸다(PR #97). 이후 15건 중 답 00030-6t4 11건, 00032-zhs 10건, 00034-tkx 12건, 00035-h69 13건(`evals/results/range_retrieval_62_7/answers_deploy_provena-api-00035-h69/rows.jsonl`, "결정표를 실행하지 않았습니다" 0건) | 00035-h69의 거절 2건은 분류가 아니라 `give_up` 1건, `ground` 1건 단계에서 났다 |

위 표와 반대 방향, 곧 합동 검토나 결정표로 가야 할 질문이 정책 질문 경로로 가는 경우는 재는 평가셋이 저장소에 없어 비율을 모른다. 경로를 LLM이 정하게 한 비교(코드 라우팅 대 LLM 라우팅, 사전 등록 #48)에서는 LLM이 경로를 정한 59번이 모두 코드와 달랐고(코드는 모두 검색, LLM은 거절로 닫기 53번과 작성 6번) 정답 근거가 낮아져 코드 라우팅을 유지했다(결정 0063). 표의 사례를 막는 시험은 `tests/test_multi_graph.py`, `tests/test_question_graph.py`에 있다.

## 관련 결정과 문서

- Supervisor는 코드 라우팅이다(결정 0055, 대체한 결정 0010 "Supervisor는 LLM"). 라우터를 LLM으로 바꾸는 스위치와 비교는 결정 0063, 질문 그래프와 결정표·합동 검토 연결은 결정 0064. 모두 [decisions.md](./decisions.md)에 있다.
- 단일 그래프와 멀티 그래프가 무엇을 공유하는지는 [README.md](../README.md)의 "멀티 그래프의 범위와 한계"에 있다.
- 사람 승인 위치와 이유, 체크포인트와 State·Store 구분의 상세는 [ARCHITECTURE.md](./ARCHITECTURE.md) "조가 채울 것" 표에 있다.
- 노드 단위 시험이 실제로 실패하는지 확인한 변이 확인은 [GATES.md](./GATES.md)에 있다.
