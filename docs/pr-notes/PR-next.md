# 조장 11/13 재점검 후속 — 박진형 몫 낮음 5건, 실패 분석 검색 파트, 데이터·Spec 문서, #148 리뷰 반영
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `8122c86e`(#154까지)를 합친 묶음 브랜치. 갈래 `pr138-followup`, `fa-search-1113`, `data-docs-1113`, `fix-front-1113`, `fix-backend-1113`, `l1-dates-1113`, `l2-front-tests-1113`을 git merge로 묶음
- 근거 종류 표기: [코드] `파일:줄` / [문서] 팀 문서 / [실측] 직접 돌린 결과 / [추정].
- 운영 호출 없음. LLM·Voyage 호출 없음. 조장 "놓친 것 목록 (2026-11-13)" 6절 새로 발견 중 박진형 몫(#3·#4·#6·#7·#8)과 H-33, 2차 재검토로 찾은 리콜 날짜 칸·빈 섹션 표시·H-08 화면 시험을 다룸.

## 1. 한 것 — 코드
| 항목 | 문제 | 고친 것 | 근거 |
|---|---|---|---|
| 새로 발견 #3 `/chat` 없는 날짜 | `as_of`에 `2026-02-30`처럼 형식만 맞는 날짜를 주면 요청은 통과하고, 스트림 안에서 검색기가 `date.fromisoformat`으로 멈춰 SSE error 이벤트가 나갔다 | `backend/api/routes.py` `ChatRequest.as_of`에 실제 날짜 검사(`field_validator`)를 더해 공통 422 봉투(`validation_error`)로 막음. 오류 문구는 고정해 입력값을 응답에 담지 않음 | [코드] 패턴은 형식만 봄(`routes.py` `DATE_PATTERN`), 멈추던 곳 `backend/rag/retrieve/search.py`의 `check_query`. [실측] `2026-02-30`·`2026-13-45`·`2025-02-29`·`0000-00-00`·전각·아랍 숫자 날짜 422, 윤일 `2024-02-29` 200 |
| 새로 발견 #4 가입 아이디 글자 | 가입 아이디는 빈칸·64자 초과·공백만 막아 `<script>`·따옴표·제어문자·한글이 그대로 저장됐다 | `backend/auth.py` 가입에만 소문자 변환 뒤 `^[a-z0-9._@+-]+$`(fullmatch) 검사. 로그인·Google 경로는 그대로. `docs/specs/106-signup-approval.md` Edge Cases 한 줄 | [실측] 거절 10개, 허용 5개(`demo-user`, `demo-admin`, 일반 이메일), 규칙 밖 글자가 든 옛 계정 로그인 유지. 부작용: `o'brien@x.com`처럼 따옴표·`%`가 든 이메일은 가입 불가 |
| 새로 발견 #7 다시 시도 말풍선 | 채팅 '다시 시도'를 누를 때마다 질문+오류 말풍선 한 쌍이 계속 쌓였다 | `lib/chat-service.js`·`lib/chat-preview.js`: 다시 시도일 때 마지막이 같은 질문의 오류 말풍선이면 그 쌍을 새 턴으로 바꿈. 일반 전송은 그대로 뒤에 붙음. `DemoChatPage.jsx`가 다시 시도를 구분해 넘김 | [실측] 3번 다시 시도해도 메시지 2개 유지, 같은 질문 일반 전송은 4개 |
| 새로 발견 #6 영향 미리보기 섹션 칸 | '섹션' 칸이 늘 비었다. 서버는 본문의 제목 줄(#)에서 섹션 이름을 만드는데(`backend/rag/ingest/diff.py` `article_of`), 화면 예시 본문에 제목 줄이 없었다 | `RecallPage.jsx` 예시에 제목 줄을 넣고, 섹션 이름이 빈 항목이 오면 입력 형식별 안내문을 보임 | [실측] 제목 줄 없는 본문 → `article=''`, 있으면 "제목 > 1조" |
| 새로 발견 #8 가입 화면 `type=email` | 바꾸지 않음 | — | [문서] 가입은 이메일 인증 흐름(`specs/107-email-signup-verification.md`). 이메일이 아닌 데모 아이디는 시드 계정이라 가입 화면을 쓰지 않음 |
| 리콜 날짜 칸(2차 재검토) | `/recalls/digest/flush`의 `day`, `/impact-preview` 날짜, 규정 변경 웹훅 날짜에 없는 날짜·전각 숫자를 넣으면 200으로 받고 결과가 조용히 틀렸다: 영향 미리보기는 날짜를 글자로 비교해 전각 숫자면 과거 답 전부 "영향 있음", `0000-00-00`이면 0건, 웹훅은 본문을 못 찾아 사용자에게 "확인 필요" 알림이 잘못 나가고, 묶음 알림은 없는 날짜로 저장되며 대기 알림이 "보냄"으로 바뀌어 되돌릴 수 없다 | `backend/api/recalls.py`에 `/chat`과 같은 규칙의 `real_date()`를 두고 세 곳에 적용 → 422 `validation_error`(고정 문구). 웹훅은 날짜 오류만 있을 때 422, 다른 형식 오류가 섞이면 원래대로 400, 오류 위치에 항목 번호. `docs/specs/recall.md` 응답 코드에 422 한 줄 | [코드] `backend/graph/recall/notice.py:82` 글자 비교, `digest.py:74-76`, `judge.py:62-64`. [실측] 3개 날짜 × 7개 경로 422, 윤일 200, 잘못된 day로는 묶음이 저장되지 않고 대기 알림 수 그대로 |
| 빈 섹션 표시(2차 재검토) | 영향 미리보기 표(화면 응답·MR 댓글)의 '섹션' 칸이 빈칸으로 나왔다 | `backend/graph/recall/impact.py` `render_markdown`의 두 표에서 빈 이름을 "(제목 없는 구간)"으로 보임. 리포트 JSON의 `article`은 그대로 `''` | [코드] 빈 이름은 인용을 찾는 기준값(`impact.py` `find_by_article`)이라 데이터는 바꾸지 않고 표시만 바꿈 |
| H-08 화면 시험(2차 재검토) | 채팅 422·403 오류는 처리 코드만 있고 화면 시험이 없었다 | 새 `web/react-app/src/chat-error-status.test.jsx` 4개: 422·403(보안 토큰)·403(본문 없음) 오류 말풍선, 생성 중 말풍선 없음, 다시 시도, `/chat` 호출 수(보안 토큰 오류만 2번). 제품 코드 변경 없음 | [실측] 오류 처리 줄을 망가뜨리면 실패(변이 4종) |
| H-33 로그아웃 때 `/me` 401 | 바꾸지 않음(조장 결정 필요) | — | [코드] 콘솔의 빨간 줄은 브라우저가 401 응답에 찍는 것이라 JS로 못 지움. 보내지 않으려면 "세션 없음" 단서가 필요한데 로그인 쿠키는 httpOnly(`backend/auth.py` 쿠키 설정), Google 콜백은 CSRF 쿠키를 심지 않음 |

## 2. 한 것 — 문서
| 항목 | 무엇 | 근거 |
|---|---|---|
| M-05 실패 분석 검색 파트 | `docs/deliverables/failure_analysis.md`: 38번 낡은 문장, 5-5 요약과 달라진 문항 목록, "수집·파싱·색인과 검색 기반의 실패(박진형 파트)" 표, 6장 지금 상태(39번 몫, PDF 색인 0건) | [실측] `EVAL_REPORT.md` 해당 줄 대조, `chunks_index` PDF 0건 |
| S-08 PDF 색인 제외 | `data/data.md` PDF 절 "아직 검색 색인에 없음"과 알려진 한계 행 | [실측] 색인 청크에 PDF 출처 0건 |
| parse Spec 목표 줄 | `docs/specs/parse.md:15` Markdown 목표 줄이 11/03 PDF 파싱 추가 때 PDF 목표로 덮였던 것을 되돌림, `:88` PDF 7건 미색인 | [코드] `git log -p`로 덮인 커밋 확인 |
| F-08 증분 실행 기록 | `docs/specs/incremental.md` 실행 기록의 현재 상태(정시 실행 꺼짐) | [실측] GitHub API 워크플로 상태 `disabled_manually` |
| K-03 후속 PRD | `docs/PRD.md` 9장 bcrypt·pyjwt·langfuse를 판 요구(`requirements.txt`)와 조사 시점 판으로 나눠 적음 | [코드] `backend/requirements.txt` |
| AGENTS 검색 모드 위치 | 줄 번호 대신 `SearchConfig.from_env()` 함수 이름으로 가리킴(코드가 바뀌어도 낡지 않게) | [코드] `backend/rag/retrieve/search.py` |
| #148 조장 리뷰 | `.gitattributes`의 검증 20건 줄 중복은 main이 이미 한 줄로 정리함(`.gitattributes:12`). #148 작업 내역 이름을 `PR-148.md`로, 기록 칸 5곳 `#148`(`docs.md` 2, `ingest.md`, `mock_erp.md`, `sdk.md`). #148 후속 커밋이 main에 이력만 합쳐져 내용이 빠졌던 것을 다시 적용 | [문서] 조장 #148 리뷰 "한 줄이 중복되니 하나만 남겨 주세요" |
| 포트폴리오 근거 줄 | `deliverables/portfolio-박진형.md`: main을 합칠 때마다 `EVAL_REPORT.md` 줄이 밀려 근거 줄 칸 10행을 새 줄로 옮기고 기준 커밋 표기를 바꿈 | [실측] 표의 숫자 36개가 모두 근거 줄에 있음(0 불일치) |

## 3. 진형이 결정한 것
| 결정 | 고른 것 | 왜 | 버린 대안 |
|---|---|---|---|
| 조장 목록 나누기 | 박진형 몫(#3·#4·#6·#7·#8·H-33)만 고치고 #1(#149)·#2(#150)는 조장이 이미 고쳤고, #5·C-24·L-23·H-25는 조장에게 | 그래프·`main.py`·결정 기록은 조장 파일이고, 같은 파일을 다른 세션(비밀번호 변경·기억 설정)이 고치는 중이라 충돌을 피함 | 한 PR에서 전부 |
| 가입 아이디 규칙 | 가입에만, 데모 아이디·이메일이 통과하는 허용 글자 목록 | 옛 계정·Google 계정을 막으면 로그인이 깨진다 | 로그인까지 검사, 이메일만 허용 |
| H-33 | 코드 변경 없이 보류 | 프론트만으로는 못 고치고, `/me`를 200 익명 응답으로 바꾸는 것은 API 계약 변경 | `/me` 계약 변경, CSRF 쿠키 유무로 추측 |

## 4. 확인한 것
| 대상 | 결과 |
|---|---|
| 전체 pytest | 3894 passed, 0 failed, 180 skipped, 2 deselected, 809초 [실측, 11/13, main `29e887f5`(#153까지)를 합친 최종 묶음, Docker `python:3.12`, 묶음 브랜치 `git archive` → `pip install -r backend/requirements-dev.txt` → `python -m pytest -q`] |
| 전체 vitest | 35 파일 406 passed [실측, 11/13, 최종 묶음] |
| 변이 시험 | 고친 줄을 되돌리면 새 시험이 실패: 다시 시도 3개(화면 1개 포함), 미리보기 모드 1개, 영향 안내 2개, `as_of` 1개(전각 숫자 입력값 노출로 실패), 가입 거절 7개 [실측] |
| 갈래별 독립 검증 | 작업과 다른 검증자가 diff만 보고 확인. 프론트 지적 2건(미리보기 모드 다시 시도, 섹션 목록 입력 안내 문구), 백엔드 지적 1건(전각·아랍 숫자 날짜의 오류 문구에 입력값이 담김)을 고침. 2차: 리콜 날짜 칸을 "문제 없음"으로 둔 판단이 틀렸다는 지적(조용히 틀린 결과 3경로)으로 고침, 버그를 못 잡던 시험 2개(대기 알림 0건인 묶음 시험, 보안 토큰 재전송 횟수) 보강, 섞인 오류 400 유지 |
| 흔들린 시험 | 중간 실행 한 번에서 `tests/test_d7_fixes.py::test_speculation_is_dropped_when_the_split_splits[False]`(그래프 쪽, 이 PR이 건드리지 않은 시험) 1건 실패. 같은 판을 단독으로 3회, main도 3회 돌려 모두 통과, 최종 전체 실행에서도 통과 → 부하에 따라 흔들리는 시험으로 봄 [실측] |
| AI 표기 검사 | 커밋 메시지 0, 추가 줄은 `ai_tools_log.md` 한 행 말고 0 |

## 5. 남의 폴더 (확인 필요)
- `backend/auth.py`(강경희): 가입 아이디 검사 2줄.
- `backend/api/routes.py`(김승욱): `ChatRequest.as_of` 검사.
- `backend/api/recalls.py`(김승욱): 날짜 칸 세 곳 검사, 웹훅 날짜 오류 422. `backend/graph/recall/impact.py`: 표의 빈 섹션 표시.
- `web/`(강경희, 프론트 작업은 박진형 배정 11/11): `chat-service.js`, `chat-preview.js`, `DemoChatPage.jsx`, `RecallPage.jsx`와 시험.
- `docs/`(조장): `PRD.md` 9장, `deliverables/failure_analysis.md`, `specs/parse.md`·`incremental.md`·`106-signup-approval.md`·`recall.md`, `docs.md` 기록, `pr-notes/`.
- `data/data.md`, `AGENTS.md`, `mock_erp/mock_erp.md`·`mock_erp/sdk/sdk.md`·`backend/rag/ingest/ingest.md` 기록 칸(#148).

## 6. 한계·남은 일
- 영향 미리보기: 제목 줄이 없는 본문의 섹션 이름은 데이터에서 계속 빈 값이다(인용 대조 기준값이라 바꾸지 않음). 표에는 "(제목 없는 구간)"으로 보인다.
- 형식만 보는 날짜 칸이 `/eval/review`(`eval_review.py`)에 남아 있다. 평가 전용 경로라 이번에 넣지 않았다.
- `docs/api/openapi.json`의 `/webhooks/regulation-updated`는 202만 적혀 있고 400·422가 없다(main부터 그랬고 생성물이라 손대지 않음).
- 링크 확장 청크의 조직·기준일 필터: 지금 코드는 거른다(`search.py`의 링크 후보도 `org`·`as_of`를 넘김). `EVAL_REPORT.md` 3장 "검색 개선 전후" 표 8번 행(110행)의 "필터를 거치지 않는다"는 링크 확장이 검색 코드에 들어오기 전 실험 기준일 가능성이 있다 [추정, 조장 확인 필요].
- 다시 시도는 서버에 질문을 한 번 더 보낸다. 서버가 실패한 질문을 저장하는 오류라면 새로고침 뒤 서버 기록에는 중복이 남을 수 있다 [추정].
- 접근성 항목 중 이번에 하지 않은 것: 관리자 화면(AdminPage) 표 행의 키보드 선택, 답변 영역의 `aria-live`, 다른 대화상자의 포커스 처리. 회수 화면(RecallPage) 관리자 요약의 "최근 N일"은 일수가 아니라 행 수를 센다.
- PR 번호가 나오면 이 문서를 `PR-<번호>.md`로 바꾸고 기록 칸 `미정`을 채운다.
