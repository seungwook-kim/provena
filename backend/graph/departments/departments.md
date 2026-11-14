# backend/graph/departments/ : Supervisor와 팀 에이전트

## 이 폴더가 하는 일

합동 검토(F-03). Supervisor가 보안·인프라(SRE)·IT 운영·재무 팀 에이전트에 나눠 쟁점표를 만들고, 쟁점이 있으면 사람 승인(interrupt)에서 멈춘다. 파일: `teams.py`(팀 정의·프롬프트·팀 Skill 불러오기), `issue_table.py`(쟁점표 만들기와 합치기, LLM 없음), `review.py`(합동 검토 그래프), `store.py`(쟁점표 저장).

- 주인: 김승욱
- 입력: 검토 요청, 검색 결과
- 출력: 쟁점표, 승인 항목

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-15 | 박진형 (jinyeong-731) | `review.py` supervisor와 `single_review.py` `run_single`의 기준일 기본값을 한국 날짜(`backend/graph/state.py` `today_kst`)로(놓친 것 D-15, 조장 지시로 처리. 문제 기록은 `backend/graph/graph.md` G-002). 시험 `tests/test_today_kst.py` | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 쟁점표 topic 칸에 쟁점 문장과 같은 출력 검사 추가(`issue_table.build_rows`, 사전 등록 62.26) | - |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #116) 합친 표(DB 재정렬)에 맞춰 `store.py`를 고침 | #116 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #83) 프롬프트 인젝션 방어에 맞춰 `review.py`를 고침 | #83 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
