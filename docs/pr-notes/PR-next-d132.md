# PR-next-d132 — #132 조장 리뷰 결정 반영 (문서만)
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: `origin/main` `601183c7` 위 브랜치 `fix-132-decisions`
- 근거 종류: [조장] 2026-11-12 #132 리뷰 전달문 / [코드] 파일:줄 / [실측] 로컬 grep.

## 무엇을 바꿨나
#132에서 "팀장 판단 필요"·"방식 미정"으로 열어 둔 C-14·L-23·E-04와 G-08·`.env.example` 문장을 확정 상태로 고쳤다. 코드·숫자는 바꾸지 않았다.

| 파일:줄 | 바꾼 내용 |
|---|---|
| `docs/specs/memory.md:83` | E-04 제목을 "충족 판정: 2026-11-12 조장 리뷰(#132)에서 확정"으로, 본문은 충족 판정 이유로 |
| `docs/specs/recall.md:100` | `POST /admin/sync` 설명의 "방식 미정"을 "확정: 정시 수집 workflow 사용"으로 |
| `docs/SDD.md:318`, `:367` | 같은 "방식 미정"을 "수동 실행은 두지 않고 정시 수집 workflow 사용"으로 |
| `docs/api/api.md:30` | openapi 재생성 행에 501 유지 확정 표기 |
| `backend/api/api.md:15` | "실제 수집 실행 방식은 팀장 결정"을 501 유지·정시 수집 workflow로 |
| `backend/graph/decision/decision.md:15` | L-23 201 `status=example` 그대로 확정 |
| `backend/services/services.md:15` | G-08 응답 캐시는 운영·최종 측정에서 켜지 않음, `.env.example` 새 변수 4개는 이미 `.env.example`에 있다(`:134`·`:136`·`:290-291`, 조장이 넣음) |
| `README.md:145` | L-23 201 `status=example` 그대로 확정 |
| `README.md:179` | `LLM_RESPONSE_CACHE`는 운영·최종 측정에서 켜지 않는 이유, `.env.example` 새 변수 4개는 이미 있음 |
| `docs/decisions.md:9-11` | C-14·L-23·E-04 세 행 추가, 결정자 김승욱 (조장), 2026-11-12 |
| `docs/pr-notes/PR-132.md:18, 23, 58, 69, 77, 92` | 열린 질문 문장을 확정 표기로 |
| `docs/pr-notes/PR-132.md:203-` | "13. 조장 리뷰 결정(2026-11-12)" 절 추가, 답 없는 항목 목록 |
| `docs/docs.md:15` | 이 작업 행 추가(PR 미정) |

## 왜 (근거)
- [조장] "승인. G-08 ... 운영과 최종 측정에서는 켜지 않음(운영 /chat 측정은 metadata.eval이 없어 켜면 측정값 오염)". 해당 문장은 위 표의 `README.md:179`, `services.md:15`.
- [실측] `.env.example` 새 변수 4개: 확인 결과 origin/main에 이미 있음(`.env.example:134`·`:136`·`:290-291`, 조장이 넣음). 설명 줄 `:133`이 "운영·측정에서는 끈다"라고 적어 추가 한계 없음.
- [조장] "C-14 ... 501 그대로, 정시 수집 workflow를 쓰는 것으로 문서대로" → `recall.md:100`, `SDD.md:318·367`, `api.md:30`, `backend/api/api.md:15`, `decisions.md` decisions.md 행.
- [조장] "L-23 201 status=example 그대로" → `decision.md:15`, `README.md:145`.
- [조장] "E-04 ... 그래프 thread가 `<user_id>:<thread_id>`이고 남의 thread는 404라 기준의 목적(사용자 분리) 충족" → `memory.md:83`. 코드 근거는 이미 `memory.md`에 있던 `backend/api/routes.py:77, 90-91`, `tests/test_api_isolation.py:12`.

## 확인한 것
- [실측] 변경 파일은 모두 `.md`이고 `.env.example`·코드는 변경 0개(`git diff --stat`).
- [실측] 열린 표현 재검색(`팀장 판단|방식 미정|조장 결정|판단 필요`)에서 C-14·L-23·E-04 관련 남은 곳이 없음을 확인했다. 남은 "조장 결정" 문장은 다른 항목(J·M2 등)이다.

## 한계
- 답이 없는 항목은 그대로 뒀다: I-08 MR 댓글 질문 발췌, O-23 db 번호대, J-09 결정 확정 여부, `.dockerignore` 제안, `FallbackChatModel` 비용 이중 집계, L-23 예시 응답을 Spec에 쓸지.
- PR-132.md의 `파일:줄` 인용은 이 브랜치 기준이다. 코드 변경 없음, 시험 없음.
