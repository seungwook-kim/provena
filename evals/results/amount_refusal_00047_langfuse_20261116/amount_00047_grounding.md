| 문항 | 회차 | 결과 | 판정 구절 청크 | 답 초안의 단서 문장 | 근거 확인 최종 | 다시 쓰기 / 문장 빼기 | 근거 확인 호출 판정(받쳐짐, 사유 코드) |
|---|---|---|---|---|---|---|---|
| 201 | 1 | answer | 72b09f608ddee143 | 없음 | grounded | None / None | True,; True,None; True,; False,unsupported; False,unsupported; True, |
| 201 | 2 | answer | 72b09f608ddee143 | 있음: 확인되지 않 | grounded | None / None | True,; True,None; True,None; False,unsupported; True,unsupported; False,out_of_period |
| 201 | 3 | answer | 72b09f608ddee143 | 없음 | grounded | None / None | True,; True,None; True,; True,; True,; True, |
| 202 | 1 | answer | 9b386ea93519a5a3 | 있음: SaaS 구매가 이 행으로 판정되는지는 자료로 확인되지 않아 확인 | grounded | None / None | True,; True,None; True,None; False,unsupported; False,unsupported; True,None |
| 202 | 2 | refuse/unsupported | 9b386ea93519a5a3 | 있음: SaaS 계약 자체의 승인 행으로 확인 | ungrounded | empty / citation_check_failed | False,unsupported; True,None; False,unsupported; True,; True,; True, |
| 202 | 3 | answer | 9b386ea93519a5a3 | 없음 | grounded | None / None | True,None; False,out_of_period; True,; False,out_of_period; False,out_of_period; False,out_of_period |
| 203 | 1 | answer | 9b386ea93519a5a3 | 있음: 확인 필요 | grounded | None / None | True,unsupported; False,out_of_period; False,unsupported; True,None; False,out_of_period; True,None |
| 203 | 2 | answer | 9b386ea93519a5a3 | 없음 | grounded | None / None | False,unsupported; True,; False,unsupported; False,unsupported; False,unsupported; False,unsupported |
| 203 | 3 | answer | 9b386ea93519a5a3 | 없음 | ungrounded | rejudge_grounded / None | False,unsupported; True,; False,unsupported; True,; True,; False,unsupported; True,None; True,; True,None |
| 204 | 1 | refuse/unsupported | 96eff1a8c833ff33 | 있음: 확정할 수 없 / SaaS 계약에 그대로 적용되는지는 자료로 확인 / 확인 필요 | ungrounded | empty / citation_check_failed | True,None; False,unsupported; False,unsupported; False,unsupported; False,no_evidence; False,out_of_period |
| 204 | 2 | answer | 96eff1a8c833ff33 | 있음: 확인되지 않 | grounded | None / None | False,unsupported; True,None; False,out_of_period; True,; False,unsupported; True, |
| 204 | 3 | answer | 96eff1a8c833ff33 | 있음: 확인되지 않 | grounded | None / None | True,; False,out_of_period; False,out_of_period; True,unsupported; False,out_of_period; False,unsupported |
| 205 | 1 | answer | fdde953c7bca6352 | 없음 | grounded | None / None | True,; False,unsupported; False,unsupported; True,; True,; False,unsupported |
| 205 | 2 | answer | fdde953c7bca6352 | 없음 | grounded | None / None | False,unsupported; False,unsupported; False,unsupported; False,unsupported; True,None; False,out_of_period |
| 205 | 3 | answer | fdde953c7bca6352 | 있음: 확인되지 않 / 확인 필요 | grounded | None / None | True,; False,out_of_period; False,out_of_period; False,unsupported; True,; True,unsupported |
