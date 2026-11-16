# Provena (프로베나)

**IT 조직의 개발·운영 담당자가 정책과 런북을 찾아 판단하는 데 드는 시간을 줄이고, 정책이 바뀐 뒤에도 예전 답을 믿고 일하는 문제를 막는 엔지니어링 지식 AI 플랫폼.** 정책·런북을 섹션과 판 날짜를 붙여 인용해 답하고, 근거가 없으면 거절한다. 인용한 정책이 바뀌면 이미 나간 답을 다시 확인해 받은 사람에게 알리고, 승인 권한표는 사람이 승인한 결정표로만 판단한다.

KDT AI Human 7기 3차 팀 프로젝트 · 3조 · 김승욱(팀장), 박진형, 강경희 · 저장소 https://github.com/aihuman-7th/proj3-c

## 무엇을 하는 서비스인가

개발·SRE·보안·IT 운영 담당자는 일하다가 회사 정책과 런북을 보고 승인권자, 절차, 기한을 판단한다(SaaS 도입, 배포, 장애 대응, 보안 검토). 답을 찾는 데 시간이 들고 담당자 답을 기다리며 흐름이 끊긴다. 정책이 바뀌어도 예전에 받은 답(AI 답 포함)은 그대로 남아 바뀐 절차를 모르고 일하게 된다. 문제의 근거(공개 설문, 현직자 설문 응답 4명, 정책 변경 빈도)는 [docs/PRD.md](./docs/PRD.md) 2장과 [docs/deliverables/survey/](./docs/deliverables/survey/responses_summary.md)에 있다.

Provena는 질문을 받으면 정책 원문에서 근거를 찾아 섹션과 판 날짜를 붙여 답하고, 근거가 없으면 거절한다. 정책이 바뀌면 그 섹션을 인용한 답을 찾아 결론이 바뀌었는지 다시 판정하고, 바뀐 답은 받은 사람과 업무시스템에 알린다. 승인 권한표는 결정표로 바꾸어 사람이 승인한 뒤에만 판단에 쓰고, 금액 판단은 코드가 한다.

## 최종 지표

측정 판은 최종 운영 배포판 `provena-api-00065-q84`(커밋 `5a8c6527`)이고, 값은 배포 주소에 대한 3회 측정의 평균이다. 평가셋 v2는 50건(관련 25, 비관련 25), 검증 세트는 v2와 겹치지 않는 20건(관련 10, 비관련 10)이다. 기준은 D0(10/30)에 합의해 동결했다. 서비스 중인 판은 `provena-api-00079-tmt`(커밋 `c565998d`)이다.

| 지표 | 기준 | 최종 값 | 근거 |
|---|---|---|---|
| 인용 정확도, 평가셋 v2 50건 | 0.85 이상 | **0.953** (정답 근거 인용률 0.942) | [EVAL_REPORT.md](./EVAL_REPORT.md) 5-4절, `evals/results/deploy_latency_provena-api-00065-q84/citation_gold.json` |
| 인용 정확도, 검증 20건 | - | **0.911** (정답 근거 인용률 0.900) | 5-4절, `evals/results/deploy_latency_holdout_provena-api-00065-q84/` |
| 비관련 질문 거절, 평가셋 v2 50건 | 0.90 이상 | **1.000** (과잉 거절 0.000, 검증 20건도 1.000과 0.000) | 5-4절 |
| 첫 검색 Recall@5 (운영 추적의 첫 검색 상위 5) | 0.80 이상 | **0.940** (v2 관련 25건 x 3회). 검증 관련 10건 x 3회는 0.783 | `evals/results/lf_recall_provena-api-00065-q84/`, `evals/results/recall_holdout_00065-q84/`, [docs/GATES.md](./docs/GATES.md) G5 |
| 첫 검색 MRR@5, nDCG@5 (같은 첫 검색 상위 5, 같은 정답) | - | v2 관련 25건 x 3회(75행): MRR@5 **0.778** [0.704, 0.852], nDCG@5 **0.819** [0.758, 0.881]. 검증 관련 10건 x 3회(30행): MRR@5 0.636 [0.491, 0.783], nDCG@5 0.661 [0.524, 0.794]. 괄호는 부트스트랩 2000회(시드 0) 95% 구간 | `evals/results/lf_recall_provena-api-00065-q84/mrr_ndcg.json`, `evals/results/recall_holdout_00065-q84/mrr_ndcg.json`(저장된 첫 검색 상위 5로 공식 채점 코드를 다시 돌린 0원 계산, 재현 스크립트 `recompute_mrr_ndcg.py`) |
| 판 날짜 표시 | 100% | **1.000** (v2 답 75/75, 검증 30/30) | [docs/SPEC.md](./docs/SPEC.md) 3장 |
| 전체 응답 시간 p95 (회차별 p95의 평균, 거절·되묻기 포함) | 10초 이하 | **8.758초**. 답한 질문만은 회차별 8.360초, 10.451초, 9.867초(3회 합 9.867초) | [EVAL_REPORT.md](./EVAL_REPORT.md) 8장 |
| 단계별 응답 시간 | 검색+리랭킹 p95 3초 이하 | 검색 p50 0.00초, p95 1.00초. 리랭킹 사용 안 함. 생성 p50 5.62초, p95 8.14초. 승인 대기의 기계 시간(재개부터 끝, 로컬 Postgres 시험) p95 결정표 33.7밀리초, 합동 검토 80.2밀리초 | 8장 단계별 표(00065 운영 Langfuse 150세션) |
| 요청당 비용 | 0.01달러 이하 | **LLM 비용 0.0049달러** (검증 20건 0.0048달러) | 8장 |
| 신뢰 경계 (배포 주소 대상 주입) | 뚫림 0건 | 질문 주입 0/19, 코퍼스 주입 0/35(시험됨 34, 인용 없는 거절로 판정 불가 1) (같은 이미지의 운영 판 `provena-api-00068-drb`) | [EVAL_REPORT.md](./EVAL_REPORT.md) 6장 |
| 재시작 뒤 승인 재개 | - | **3/3** (재배포 전 `provena-api-00075-5zk`에서 만든 쟁점표 승인·쟁점표 반려·결정표 초안 반려 대기를 재배포 뒤 `provena-api-00079-tmt`에서 처리, 확인 항목 R1~R10 통과, 재개 확인 5.6초) | [docs/GATES.md](./docs/GATES.md) G4, `evals/results/d10_restart_provena-api-00079-tmt/` |
| 개선 전후 (검증 20건 인용 정확도) | - | **0.772 → 0.911** (검증 20건). 실패 유형 분석으로 찾은 다섯 원인(도메인 밖 오분류, 첫 검색 누락, 근거 선택, 정답 밖 인용, 표 청크 라벨 소실)을 고쳐 과잉 거절을 0.100 → 0.000, 오답 근거를 0.370 → 0.200으로 줄였다. 같은 기간 v2 50건은 0.989 → 0.953이다. 최종 판 3회에서 정답 위치를 한 번도 인용하지 못한 v2 문항은 38번 하나이고(3회 모두 정답 위치 0/2, 회당 0.040 감점), 39번은 3회차에 정답 밖 인용이 하나 섞였다. 38번은 문항 표현에 맞춘 검색어 용어표를 일반 규칙이 아니어서 걷어낸 뒤부터 정답 위치를 인용하지 못한다(EVAL_REPORT 8장). | 개선 전은 첫 운영 측정 판 `provena-api-00032-zhs`, 5-4절 리비전별 표, [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md) |

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
| RAGAS 채점 | - | 판정 `claude-haiku-5-5`, 임베딩 `voyage-4` | `evals/results/ragas_deploy_provena-api-00065-q84/summary.md` |

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
- 녹화는 2026-11-16 03:35~03:37에 커밋 `5a8c652`의 코드로 질문 9개 전부를 새 DB에서 다시 떴다. 녹화가 현재 코드와 맞는지는 키·네트워크 없이 `python -m pytest -m demo_replay`로 확인한다(Docker와 pgvector 이미지 필요). 다시 녹화하는 절차와 이전 녹화 이력은 [data/data.md](./data/data.md)에 있다.
- 키 없이 인용 답이 나오는 질문(2026-11-16에 질문 9개 전부를 다시 녹화했고, `data/demo_replay/recorded.jsonl`). 글자가 같아야 한다(공백 차이는 무시). 재녹화 뒤 이 질문들의 결과는 위 설명과 일치한다.
  - 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?
  - CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?
  - 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?
  - EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?
  - 외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  - 외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  - 외부 SaaS 계약 금액이 10만 달러일 때 승인 권한자는 누구이고, 근거 섹션과 판 날짜는 무엇인가요?
    - 참고(질문 글자가 아님): 위 세 금액 질문은 데모 구간 01이다. 5만·3만 달러 질문은 승인 권한표 2023-05판의 `>$25K up to $50K` 행을 인용해 업무 승인자(Director)와 재무 승인자(PAO 또는 VP Finance)를 답한다. 10만 달러 질문은 2026-11-13 녹화까지는 거절로 끝났으나, 2026-11-16 재녹화부터 같은 표의 `>$50K up to $250K` 행을 인용해 근거 섹션(Approving expense > >$50K up to $250K)과 판 날짜(2023-05-11)를 답한다. 다만 이 행이 지출 승인(Approving expense) 행이어서 외부 SaaS 계약에 그대로 적용되는지는 자료만으로 확정하지 않고, 승인 권한자(행에 적힌 Sr Director, PAO 또는 VP Finance)는 단정하지 않는다. 이 설명을 질문 뒤에 붙여 보내면 다른 질문이라 녹화에 없어 거절된다.
- 키 없이 거절이 나오는 질문(녹화에도 거절): "구매 승인에는 어떤 승인자가 필요한가요?"(핸드북에 승인자 근거가 없다), "오늘 점심 메뉴 추천해줘"(범위 밖).
- 키 없이 재생하는 팀 합동 검토와 리콜(데모 구간 03, L-23 해소. 2026-11-16 녹화 `data/demo_replay/recorded_scenarios.jsonl`, 시나리오 `data/demo_replay/scenarios.json`):
  - 팀 합동 검토: `demo-user`로 다음 요청을 글자 그대로 보내면 Supervisor와 팀 에이전트 4개(보안·인프라·IT 운영·재무)의 검토가 녹화로 재생되고 쟁점표 승인 요청에서 멈춘다. `demo-admin`으로 승인함에서 승인하면 쟁점표가 저장된다. 요청: 외부 SaaS 로그 모니터링 도구를 연 4만 달러에 도입하려고 합니다. 업체와 제품 선정은 끝났고, 데이터는 미국 리전에 저장됩니다. 프로덕션 서비스 로그가 이 도구로 전송되고, 온콜 담당자가 알림을 받는 경로에도 들어갑니다. 합동 검토를 부탁합니다.
  - 리콜: `demo-user`로 위 5만·3만 달러 질문을 보낸 뒤, `demo-admin`으로 리콜 화면의 "처리 대기 변경 지금 처리"를 누르면 두 답이 리콜 대상이 된다. 바뀐 섹션은 데모용 가상 개정 한 건이다(승인 권한표 2023-05판 `>$25K up to $50K` 행에서 업무 승인자 Director를 Sr Director로 바꾼 글, 새 판 날짜 2027-07-01, 실제 핸드북 문구 아님). 결론 재판정 설명은 녹화한 LLM 판정을 재생하고, 녹화에 없는 판정 요청은 규칙 판정으로 낸다. 가상 개정은 키 없는 로컬 데모(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`, LLM 키 없음)에서만 서버 시작 때 처리 대기로 들어가고(`backend/graph/recall/demo_change.py`), 리콜 저장소가 메모리(기본)이면 서버를 다시 띄울 때 다시 처리 대기가 된다. 처리 전에 물은 답만 대상이다.
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

### 폴더

| 폴더 | 내용 |
|---|---|
| `backend/` | FastAPI 서버, 로그인, 질문 그래프와 팀 에이전트·결정표·리콜(`graph/`), 수집·파싱·청킹(`rag/ingest/`), 검색(`rag/retrieve/`), 사용자별 기억(`memory/`), LLM 호출(`services/llm.py`) |
| `web/` | 화면 |
| `data/` | 핸드북 원문 스냅샷, manifest, 검색 색인, 키 없는 데모 녹화, `LICENSES/` |
| `evals/` | 평가셋(v1·v2·검증), 동결 해시, 사전 등록, 평가 실행기, 원시 결과(`results/`) |
| `tests/` | 회귀 테스트 (CI가 PR마다 실행) |
| `skills/`, `extras/mcp_skill/` | 런타임 Skill, FastMCP 서버와 MCP 클라이언트 (가산) |
| `mock_erp/`, `db/`, `docs/` | 업무시스템 목업, DB 스키마, 문서 |

## 알려진 한계

- **v2 값은 낙관적일 수 있다.** 코드 수정이 v2 실패 문항에서 출발했고, 38번 정답은 판정자 확인을 거쳐 동결 뒤에 고쳤다(결정 0075, 0087). 일반화는 검증 20건 0.911과 새 인용 5건 0.933으로 읽는다. [EVAL_REPORT.md](./EVAL_REPORT.md) 2장, 5-4절
- **검증 20건 값도 처음 보는 문항의 값이 아니다.** 101·104·105·109번의 실패를 분석해 고친 뒤 0.772 → 0.911이 되었으므로, 처음 보는 문항으로 다시 재야 일반화 값이 된다(결정 0113). EVAL_REPORT 2장
- **사전 등록 순서는 62.63부터만 커밋으로 입증된다.** 62.63부터는 예측을 결과보다 먼저 별도 커밋으로 올렸고, 그 이전 행은 순서를 커밋으로 입증하지 못한다. EVAL_REPORT 3장 "사전 등록의 커밋 순서(한계)", [evals/PREREGISTER.md](./evals/PREREGISTER.md)
- **감점 문항이 남아 있다.** 최종 판에서 v2 38·39번, 검증 101·108번과 109번(3회차만)이다. 38·101번은 첫 검색에서 정답 절이 문맥에 들지 않는 검색 실패로 확인했고, 한 문항만 맞추는 규칙은 넣지 않았다. EVAL_REPORT 5-5절, [docs/deliverables/failure_analysis.md](./docs/deliverables/failure_analysis.md)
- **응답 시간 여유가 크지 않다.** 답한 질문만의 p95는 14.890초(`provena-api-00047-wjn`)에서 9.867초로 줄었고 전체 p95는 8.758초이지만, 목표 10초까지 여유가 크지 않다. EVAL_REPORT 8장
- **값을 뒤집는 문장(I03 유형)의 방어는 낱말 목록 기반이다.** 실제 모델 재시험에서 뚫린 사례를 찾아 막았고 최종 판 재시험 3건은 모두 막혔으나, 목록 밖 표현까지 막는다는 근거는 아니다. EVAL_REPORT 6장
- **CI 회귀 검사는 녹화된 데모 질문 9개만 본다.** 평가셋 50건 전체는 CI가 아니라 운영 배포 측정으로 확인했다. EVAL_REPORT 8장, [docs/GATES.md](./docs/GATES.md) G5
- **재지 않은 지표가 있다.** 답변 리콜의 재현율·정밀도와 결정표 셀 정확도는 미측정이다. [docs/SPEC.md](./docs/SPEC.md) 3장
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
