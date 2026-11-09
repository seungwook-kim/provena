# mock_erp/python_example/ : Python 업무시스템 예제

## 이 폴더가 하는 일

Python 업무시스템이 플랫폼 API를 부르고 리콜 웹훅을 받는 작은 예제.

- 주인: 김승욱

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | `provena_client.py`(로그인, CSRF, `/chat` SSE 읽기, 표준 라이브러리만)와 `webhook_receiver.py`(리콜 웹훅 `X-Signature` 검증, `backend/graph/recall/webhook.py`와 같은 방식) 추가. 시험 `tests/test_mock_erp_example.py` 6개(외부 네트워크 없음) 통과 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
