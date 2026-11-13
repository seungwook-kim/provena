# 끝 1자리 규칙의 평가셋 근거 (0원 계산, 2026-11-13)

규칙과 계산 방법은 `analyze_tail_slot.py` 머리말에 있다. 규칙을 끈 상태로 따로 잰 적은 없으므로 아래는 켠 상태의 측정 행에서 끝 자리가 한 일을 센 값이다.

| 리비전 | 문맥을 받은 행 | 규칙이 작동한 행(문맥 8청크 이상) | 작동한 문항(v2 / 검증) | 끝 자리 청크가 정답 위치인 행 | 끝 자리 때문에만 문맥의 정답 위치 수가 는 행 | 끝 자리 청크를 답이 인용한 행 |
|---|---|---|---|---|---|---|
| `provena-api-00044-49s` | 105 | 67 (v2 46, 검증 21) | 16 / 7 | 9 | 6 | 7 |
| `provena-api-00047-wjn` | 105 | 67 (v2 46, 검증 21) | 16 / 7 | 9 | 3 | 5 |

문맥 안 정답 위치 수(작동한 행의 정답 위치 합 118개 중):

| 리비전 | 8청크 전체 | 끝 자리를 뺀 7청크 |
|---|---|---|
| `provena-api-00044-49s` | 110 | 104 |
| `provena-api-00047-wjn` | 108 | 105 |

정답 근거 인용률(관련 문항 행, 문항별 정답 위치 중 인용한 비율의 평균). 하한은 끝 자리 청크가 문맥에 있던 행에서 그 청크의 인용을 지운 값이다.

| 리비전 | 평가셋 | 관련 행 | 실제 | 끝 자리 인용을 뺀 하한 | 값이 바뀌는 행(문항 번호, 회차) |
|---|---|---|---|---|---|
| `provena-api-00044-49s` | v2 | 75 | 0.9133 | 0.9067 | 2번 2회 |
| `provena-api-00044-49s` | 검증 | 30 | 0.8667 | 0.7500 | 106번 1회, 106번 2회, 106번 3회, 109번 1회, 109번 3회 |
| `provena-api-00047-wjn` | v2 | 75 | 0.9422 | 0.9289 | 2번 2회, 2번 3회 |
| `provena-api-00047-wjn` | 검증 | 30 | 0.8333 | 0.8000 | 106번 2회, 106번 3회 |

끝 자리 청크가 정답 위치이거나, 답이 인용했거나, 끝 자리 때문에만 정답 위치 수가 는 행:

| 리비전 | 평가셋 | 문항 | 회차 | 문맥 청크 | 정답 위치 수 | 문맥의 정답 위치(8청크 / 끝 자리 뺌) | 끝 자리 청크가 정답 위치 | 끝 자리 청크 인용 | 끝 자리 청크의 절 |
|---|---|---|---|---|---|---|---|---|---|
| `provena-api-00044-49s` | v2 | 2 | 2 | 8 | 2 | 1 / 1 | 예 | 예 | References > Incident Manager Escalation |
| `provena-api-00044-49s` | v2 | 2 | 3 | 8 | 2 | 1 / 1 | 예 | 예 | References > Incident Manager Escalation |
| `provena-api-00044-49s` | 검증 | 106 | 1 | 9 | 2 | 2 / 1 | 예 | 예 | Responsibilities |
| `provena-api-00044-49s` | 검증 | 109 | 1 | 9 | 1 | 1 / 0 | 예 | 예 | SQL Style Guide > Common Table Expressions (CTEs) |
| `provena-api-00044-49s` | 검증 | 106 | 2 | 9 | 2 | 2 / 1 | 예 | 예 | Responsibilities |
| `provena-api-00044-49s` | 검증 | 109 | 2 | 8 | 1 | 1 / 1 | 예 | 아니오 | SQL Style Guide > Common Table Expressions (CTEs) |
| `provena-api-00044-49s` | 검증 | 106 | 3 | 9 | 2 | 2 / 1 | 예 | 예 | Responsibilities |
| `provena-api-00044-49s` | 검증 | 108 | 3 | 9 | 2 | 2 / 1 | 예 | 아니오 | Questions & Answers > Other Notes |
| `provena-api-00044-49s` | 검증 | 109 | 3 | 9 | 1 | 1 / 0 | 예 | 예 | SQL Style Guide > Common Table Expressions (CTEs) |
| `provena-api-00047-wjn` | v2 | 2 | 1 | 8 | 2 | 1 / 1 | 예 | 예 | References > Incident Manager Escalation |
| `provena-api-00047-wjn` | v2 | 5 | 1 | 9 | 1 | 1 / 1 | 예 | 아니오 | CI Health incidents {#broken-master} > If you're assigned to an incident {#triage-broken-master} > 3. Fix it {#resolution-of-broken-master} |
| `provena-api-00047-wjn` | v2 | 2 | 2 | 8 | 2 | 1 / 1 | 예 | 예 | References > Incident Manager Escalation |
| `provena-api-00047-wjn` | v2 | 2 | 3 | 9 | 2 | 2 / 1 | 예 | 예 | Detailed Team Responsibilities > Infrastructure Leadership Responsibilities |
| `provena-api-00047-wjn` | 검증 | 109 | 1 | 8 | 1 | 1 / 1 | 예 | 아니오 | SQL Style Guide > Common Table Expressions (CTEs) |
| `provena-api-00047-wjn` | 검증 | 106 | 2 | 9 | 2 | 2 / 1 | 예 | 예 | Responsibilities |
| `provena-api-00047-wjn` | 검증 | 109 | 2 | 8 | 1 | 1 / 1 | 예 | 아니오 | SQL Style Guide > Common Table Expressions (CTEs) |
| `provena-api-00047-wjn` | 검증 | 106 | 3 | 9 | 2 | 2 / 1 | 예 | 예 | Responsibilities |
| `provena-api-00047-wjn` | 검증 | 109 | 3 | 8 | 1 | 1 / 1 | 예 | 아니오 | SQL Style Guide > Common Table Expressions (CTEs) |

읽는 법과 한계:
- 이 규칙의 설계 근거는 평가셋이 아니라 데모 질문 하나다(`backend/rag/retrieve/search.py` 주석). 평가셋에서는 끝 1자리를 원 질문 목록에 두는 방식과 첫 목록으로 두는 방식을 가르지 못했다(사전 등록 62.38). 이 표는 규칙을 정한 뒤에 켠 상태의 운영 행에서 끝 자리가 한 일을 센 값이고, 규칙이 옳다는 증명이 아니다.
- 끝 자리 청크가 원 질문 목록에서 왔는지, 새 청크가 없어 하위 질문 목록의 다음 청크로 채워졌는지는 문맥 기록에 없다(검색기를 다시 돌리면 질문 임베딩 호출이 든다). 그래서 "끝 자리"는 문맥의 8번째 청크를 뜻한다.
- 하한은 끝 자리 인용을 지운 값이다. 끝 자리가 없었다면 답이 다른 청크를 인용했을 수 있으므로 실제로 잃을 값의 예측이 아니다.
- 3회 반복 행이고 정답 위치 수가 문항마다 1~3이라 1~3행 차이는 개선이나 효과로 읽지 않는다.
- 검증 20건은 동결 목록 밖이며 결과를 본 뒤 고친 문항이 있어 값이 낙관적일 수 있다(EVAL_REPORT 2장).
