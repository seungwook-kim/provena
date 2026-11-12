# 재검색 질의와 첫 문맥 청크 (deploy_latency_provena-api-00044-49s)

문항 id x 회차마다 search 관측을 시작 순서대로 적었다. 1번이 첫 검색(앞 5개가 Recall@5 문맥)이다.

## 문항 2 / 1회차 (paired, 결과 answer, 7.748초)
- 검색 1 (retries=0, 파서 json): 질의 `EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?`
  - 하위 질문: ['EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼?', 'IMOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼?']
  - 청크 id(9개): 8ffd2a443138bfd7, 996d3c365eaa9408, 1bcdf8557f4f92c2, 7cd641d28bcdfeb5, 2944820ef4895720, 3069923da5795b3f, df91699339dd7344, c8519d0ba9d6b2e3, ea41ac4fc71c17b0

## 문항 36 / 1회차 (paired, 결과 answer, 6.438초)
- 검색 1 (retries=0, 파서 json): 질의 `외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효하고, 만료되면 어떻게 돼?`
  - 하위 질문: ['외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효해?', '외부 SaaS 벤더 보안 평가(TPRM)가 만료되면 어떻게 돼?']
  - 청크 id(9개): 8d1287e09ae75d03, e92ff33755911829, 99a793a495f96048, 931a9097b6def468, a0f3bf383307d1b1, 9526c8e3efda1e90, a27fa8306cb9ea5d, 4bc8f27014432f8a, ddc919c080c5429b

## 문항 38 / 1회차 (paired, 결과 answer, 15.392초)
- 검색 1 (retries=0, 파서 json): 질의 `새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?`
  - 하위 질문: ['새 SaaS 도구 도입 요청은 어디서 시작해?', '보안 검토(TPRM)는 언제 필요해?']
  - 청크 id(9개): bb96e70d07219884, c9fbc47432ef97c9, c52f4b109076e4a0, bf31f2661c6cdfdf, 5014a314f93379b1, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b
- 검색 2 (retries=1, 파서 json): 질의 `new SaaS vendor adoption request intake form start`
  - 청크 id(13개): bb96e70d07219884, c9fbc47432ef97c9, c52f4b109076e4a0, bf31f2661c6cdfdf, 5014a314f93379b1, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b, 14cd1150f75d2995, 3498f648d6489b5c, 96259aa02a1a1ea6, ac96d726616e421f

## 문항 39 / 1회차 (paired, 결과 answer, 6.749초)
- 검색 1 (retries=0, 파서 json): 질의 `GitLab 계정 2FA 초기화 요청은 어떻게 처리해?`
  - 하위 질문: ['계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)', '계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)']
  - 청크 id(10개): ca1e641aabe65081, b579ee5fefd307d2, cb99f52f7a78e20c, 80a4700384a9740e, be4371acb58882e4, 63183fc4e2a89677, 866184fe686d6a7e, 2782ff2febf78d5b, 42fb803d03f8e8fc, 1349310bf3d9c2f7

## 문항 2 / 2회차 (paired, 결과 answer, 13.445초)
- 검색 1 (retries=0, 파서 json): 질의 `EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?`
  - 하위 질문: ['EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼?', 'IMOC가 응답하지 않으면 어떻게 에스컬레이션돼?']
  - 청크 id(8개): 8ffd2a443138bfd7, 996d3c365eaa9408, 1bcdf8557f4f92c2, df91699339dd7344, 2944820ef4895720, c8519d0ba9d6b2e3, 97c355bcf08f1d3d, 3069923da5795b3f
- 검색 2 (retries=1, 파서 json): 질의 `IMOC unresponsive escalation path incident manager fallback`
  - 청크 id(13개): 8ffd2a443138bfd7, 996d3c365eaa9408, 1bcdf8557f4f92c2, df91699339dd7344, 2944820ef4895720, c8519d0ba9d6b2e3, 97c355bcf08f1d3d, 3069923da5795b3f, 7cd641d28bcdfeb5, e229a5640fe06918, e3dba53a58fc6b2c, 4cf229d754ccff62, aa60b103361ca197

## 문항 36 / 2회차 (paired, 결과 answer, 6.637초)
- 검색 1 (retries=0, 파서 json): 질의 `외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효하고, 만료되면 어떻게 돼?`
  - 하위 질문: ['외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효해?', '외부 SaaS 벤더 보안 평가(TPRM)가 만료되면 어떻게 돼?']
  - 청크 id(9개): 8d1287e09ae75d03, e92ff33755911829, 99a793a495f96048, 931a9097b6def468, a0f3bf383307d1b1, 9526c8e3efda1e90, a27fa8306cb9ea5d, 4bc8f27014432f8a, ddc919c080c5429b

## 문항 38 / 2회차 (paired, 결과 answer, 14.921초)
- 검색 1 (retries=0, 파서 json): 질의 `새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?`
  - 하위 질문: ['새 SaaS 도구 도입 요청은 어디서 시작해?', '보안 검토(TPRM)는 언제 필요해?']
  - 청크 id(9개): bb96e70d07219884, c9fbc47432ef97c9, c52f4b109076e4a0, bf31f2661c6cdfdf, 5014a314f93379b1, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b
- 검색 2 (retries=1, 파서 json): 질의 `SaaS tool adoption request intake procurement vendor onboarding`
  - 청크 id(13개): bb96e70d07219884, c9fbc47432ef97c9, c52f4b109076e4a0, bf31f2661c6cdfdf, 5014a314f93379b1, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b, 887070ae2bcc84c4, 14cd1150f75d2995, 3386a22b1ae97ab2, b95dd76c46d89094

## 문항 39 / 2회차 (paired, 결과 answer, 6.612초)
- 검색 1 (retries=0, 파서 json): 질의 `GitLab 계정 2FA 초기화 요청은 어떻게 처리해?`
  - 하위 질문: ['계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)', '계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)']
  - 청크 id(10개): ca1e641aabe65081, b579ee5fefd307d2, cb99f52f7a78e20c, 80a4700384a9740e, be4371acb58882e4, 63183fc4e2a89677, 866184fe686d6a7e, 2782ff2febf78d5b, 42fb803d03f8e8fc, 1349310bf3d9c2f7

## 문항 2 / 3회차 (paired, 결과 answer, 14.323초)
- 검색 1 (retries=0, 파서 json): 질의 `EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?`
  - 하위 질문: ['EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼?', 'IMOC도 응답이 없으면 어떻게 에스컬레이션돼?']
  - 청크 id(8개): 8ffd2a443138bfd7, 996d3c365eaa9408, 1bcdf8557f4f92c2, df91699339dd7344, 2944820ef4895720, c8519d0ba9d6b2e3, 97c355bcf08f1d3d, 3069923da5795b3f
- 검색 2 (retries=1, 파서 json): 질의 `escalation when incident management on-call does not acknowledge page`
  - 청크 id(13개): 8ffd2a443138bfd7, 996d3c365eaa9408, 1bcdf8557f4f92c2, df91699339dd7344, 2944820ef4895720, c8519d0ba9d6b2e3, 97c355bcf08f1d3d, 3069923da5795b3f, 7cd641d28bcdfeb5, 4cf229d754ccff62, e3dba53a58fc6b2c, c7f01fabbaeb4c56, 9a134d1b976b0c73

## 문항 36 / 3회차 (paired, 결과 answer, 6.632초)
- 검색 1 (retries=0, 파서 json): 질의 `외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효하고, 만료되면 어떻게 돼?`
  - 하위 질문: ['외부 SaaS 벤더 보안 평가(TPRM)는 얼마 동안 유효해?', '외부 SaaS 벤더 보안 평가(TPRM)가 만료되면 어떻게 돼?']
  - 청크 id(9개): 8d1287e09ae75d03, e92ff33755911829, 99a793a495f96048, 931a9097b6def468, a0f3bf383307d1b1, 9526c8e3efda1e90, a27fa8306cb9ea5d, 4bc8f27014432f8a, ddc919c080c5429b

## 문항 38 / 3회차 (paired, 결과 answer, 16.428초)
- 검색 1 (retries=0, 파서 json): 질의 `새 SaaS 도구를 도입하고 싶은데 요청은 어디서 시작하고, 보안 검토(TPRM)는 언제 필요해?`
  - 하위 질문: ['새 SaaS 도구 도입 요청은 어디서 시작해?', '보안 검토(TPRM)는 언제 필요해?']
  - 청크 id(9개): bb96e70d07219884, c9fbc47432ef97c9, 5014a314f93379b1, bf31f2661c6cdfdf, c52f4b109076e4a0, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b
- 검색 2 (retries=1, 파서 json): 질의 `new SaaS vendor adoption request intake process`
  - 청크 id(13개): bb96e70d07219884, c9fbc47432ef97c9, 5014a314f93379b1, bf31f2661c6cdfdf, c52f4b109076e4a0, d96029d78f460b1a, 5dc72fc0dff21d9d, 03c384a559ed29b2, ddc919c080c5429b, 3498f648d6489b5c, ac96d726616e421f, 91bbb8ee02edab73, b238cba8b182d7a2

## 문항 39 / 3회차 (paired, 결과 answer, 5.635초)
- 검색 1 (retries=0, 파서 json): 질의 `GitLab 계정 2FA 초기화 요청은 어떻게 처리해?`
  - 하위 질문: ['계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab 팀원)', '계정 2FA 초기화 요청은 어떻게 처리해? (대상: GitLab.com 사용자, 고객)']
  - 청크 id(10개): ca1e641aabe65081, b579ee5fefd307d2, cb99f52f7a78e20c, 80a4700384a9740e, be4371acb58882e4, 63183fc4e2a89677, 866184fe686d6a7e, 2782ff2febf78d5b, 42fb803d03f8e8fc, 1349310bf3d9c2f7
