# 재현 명령과 출력 (main 4c8d8bc, 2026-11-13)

새로 clone한 `4c8d8bc` 사본에서 실행했다. 두 명령 모두 키, 네트워크, 비용이 필요 없고 저장소 파일만 읽는다. Python은 3.13.15였다.

## 1. 서로 다른 청크 수와 전체 청크 수 (G3, `EVAL_REPORT.md` 1장)

`chunk_sha256`은 청크 본문의 sha256이고 `data/chunks_index.jsonl`의 각 줄 안에 들어 있는 값이다. 파일 줄바꿈과 무관하다.

```bash
python -c "import json;r=[json.loads(l)['chunk_sha256'] for l in open('data/chunks_index.jsonl',encoding='utf-8') if l.strip()];print('total_rows',len(r),'distinct_chunk_sha256',len(set(r)))"
```

출력:

```text
total_rows 23095 distinct_chunk_sha256 22378
```

전체 청크 23,095개 가운데 본문이 서로 다른 것은 22,378개이다(G3 기준 1만 개 이상).

## 2. 검증 20건 `evals/dataset_holdout_v1.jsonl`의 sha256

```bash
python -c "import hashlib;d=open('evals/dataset_holdout_v1.jsonl','rb').read();lf=d.replace(b'\r\n',b'\n');crlf=lf.replace(b'\n',b'\r\n');print('on_disk_has_CRLF',b'\r\n' in d,'lines',lf.count(b'\n'));print('LF  ',hashlib.sha256(lf).hexdigest());print('CRLF',hashlib.sha256(crlf).hexdigest());print('on_disk',hashlib.sha256(d).hexdigest())"
```

출력(Windows에서 `core.autocrlf=true`로 clone한 사본):

```text
on_disk_has_CRLF True lines 20
LF   51c020fb10b8b0d18990932b24205810eff1cef96c7a9541e1193bd7c5104771
CRLF c877c0657ff086a174135cc22e4d71858b776a4c02555325ce63721f1af51d07
on_disk c877c0657ff086a174135cc22e4d71858b776a4c02555325ce63721f1af51d07
```

| 기준 | sha256 | 설명 |
|---|---|---|
| LF | `51c020fb10b8b0d18990932b24205810eff1cef96c7a9541e1193bd7c5104771` | git 저장소 안(blob)의 바이트이다. Linux·Mac에서 `core.autocrlf` 없이 받으면 작업 폴더 파일도 이 값이다 |
| CRLF | `c877c0657ff086a174135cc22e4d71858b776a4c02555325ce63721f1af51d07` | **`EVAL_REPORT.md`가 정의하는 값이다**(2장, 9장의 `--dataset-sha256`). Windows에서 `core.autocrlf=true`로 받은 작업 폴더 파일이 이 값이다 |

같은 20건의 내용은 같고 줄바꿈만 다르다. `evals/dataset_holdout_v1.jsonl`에는 `.gitattributes`에 줄바꿈 지정이 없어(`git ls-files --eol`: 저장소 안 `i/lf`, 이 사본의 작업 폴더 `w/crlf`) 받는 환경에 따라 어느 한쪽 값이 나온다. 위 명령은 두 값을 한 번에 계산하므로 어느 환경에서 받았든 두 값 중 하나가 `on_disk`와 같아야 하고, 보고서의 정의는 CRLF 쪽이다. 저장소의 `.gitattributes`는 바꾸지 않았다.
