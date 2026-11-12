# K-19 확인 — 키 없는 데모에서 README 질문 1이 녹화 답으로 나오는가
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: `origin/main` `601183c7`, 브랜치 `gap3-k19b`
- 결과: 코드 변경 없음, 확인만 했다. 근거 종류: [코드] 파일:줄 / [실측] 로컬 실행.

## 무엇을 확인했나
1. 재생 키에 프롬프트 본문이 들어가는지. 들어가면 `ed5ef330`(11/12 01:40)의 `CLASSIFY_SYSTEM` 변경이 녹화(11/11 20:44)와 어긋났을 수 있다.
2. 키 없이(`DEMO_MODE=1`, LLM·Voyage 키 없음) 데모 질문 9개(README 인용 답 5, 거절 2, 금액만 바꾼 거절 2)를 현재 그래프로 돌려 녹화에 없는 요청이 있는지.
3. 첫 화면 추천 질문 3개가 인용 답 질문과 같은 글자인지.

## 근거 (파일:줄, 시험 수, 재생 결과)
- [코드] 키는 sha256(역할 + 정규화한 메시지 전체)이라 프롬프트 본문이 키에 들어간다(`backend/services/demo_replay.py:11`, `:94`). 정규화는 공백 접기와 `기준일:` 날짜 삭제뿐이다.
- [실측] 현재 `CLASSIFY_SYSTEM`으로 만든 분류 요청 키가 `data/demo_replay/recorded.jsonl`에 9/9 있다(`LLM_JSON_REMINDER=1`, `.env.example:72`). 녹화는 새 분류 프롬프트로 떴다. 녹화 줄 시각은 2026-11-11 20:44~20:46 KST다.
- [실측] 기본 시험 `test_demo_replay_fresh.py`, `test_demo_replay.py`, `test_demo_record_roundtrip.py`, `test_main_demo_warning.py`: 22 passed.
- [실측] `python -m pytest -m demo_replay tests/test_demo_replay_fresh.py`(새 Postgres에 `db/*.sql`과 색인 적재, 키·네트워크 없음): 2 passed. 두 경로(추론 답을 보냄 / 건너뜀)에서 질문 9개 모두 녹화에 없는 요청 0건이다.
- 이 시험이 질문마다 확인하는 것: 인용 답 5개는 `kind=answer`, 인용 1개 이상, 발췌 대체 문구 없음, 인용 청크가 녹화 답에 있음. 거절 4개는 `kind=refuse`.

| 질문 | 결과 | 녹화에 없는 요청 |
|---|---|---|
| Q1 제3자 프로덕션 데이터 | 인용 답(녹화 LLM 답) | 0 |
| Q2 CVSS 9.0 | 인용 답 | 0 |
| Q3 CUD 계약 승인자 | 인용 답 | 0 |
| Q4 EOC 에스컬레이션 | 인용 답 | 0 |
| Q5 외부 SaaS 5만 달러 | 인용 답 | 0 |
| 구매 승인(근거 없음) | 거절 | 0 |
| 점심 메뉴(범위 밖) | 거절 | 0 |
| 3만 달러 | 거절 | 0 |
| 10만 달러 | 거절 | 0 |

- 첫 화면 추천 3개는 Q1·Q3·Q5와 같은 글자이고 시험(`test_first_screen_suggestions_are_readme_keyless_answer_questions`)이 통과해 같은 결과다.
- 결론: K-19 해결. 질문 1은 녹화한 LLM 답으로 나온다.

## 한계
- 가짜 응답이나 실제 LLM이 아니라 녹화 재생만 확인했다. LLM·네트워크 호출은 하지 않았다.
- 재생은 색인 `data/index.tar.gz`와 `SEARCH_RANGE_N` 비움 조건에서 확인했다. 검색 코드나 프롬프트를 바꾸면 다시 확인해야 한다.
- 시험은 API가 아니라 질문 그래프를 직접 돌린다. 화면(SSE)과 브라우저 경로는 보지 않았다.
